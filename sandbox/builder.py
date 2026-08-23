"""Docker sandbox builder — manages containers for Kiro CLI project builds.

This module provides a clean interface to:
  1. Build the sandbox Docker image (if not already built)
  2. Start a container with Kiro CLI authenticated
  3. Run commands inside the container (kiro --print "...", npm run build, etc.)
  4. Copy built files out of the container
  5. Stop and clean up the container

Usage:
    python -m sandbox.builder --test

How it works:
    - Docker SDK (pip package "docker") talks to Docker Desktop on your machine
    - We create a container from our custom image (sandbox/Dockerfile)
    - The container stays running (tail -f /dev/null) while we exec commands into it
    - When done, we copy files out and destroy the container

Think of it like renting a fresh Linux VM for each build, except it starts in seconds.
"""

import os
import sys
import time
import tarfile
import io
from typing import Optional

import docker
from docker.errors import ImageNotFound, NotFound, APIError
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

load_dotenv(os.path.join(PROJECT_ROOT, "config", ".env"))

from sandbox.config import (
    IMAGE_FULL,
    DOCKERFILE_DIR,
    MEMORY_LIMIT,
    CPU_LIMIT,
    COMMAND_TIMEOUT,
    CONTAINER_WORKSPACE,
    HOST_OUTPUT_DIR,
    KIRO_API_KEY_ENV,
)

# ---------------------------------------------------------------------------
# Docker client — connects to Docker Desktop on your machine
# ---------------------------------------------------------------------------

def _get_docker_client() -> docker.DockerClient:
    """Create a Docker client connected to the local Docker daemon.

    On Windows with Docker Desktop, this uses the named pipe.
    On Linux/Mac, it uses the Unix socket /var/run/docker.sock.
    """
    try:
        client = docker.from_env()
        client.ping()  # Verify connection
        return client
    except Exception as e:
        raise RuntimeError(
            f"Cannot connect to Docker. Is Docker Desktop running?\n"
            f"Error: {e}"
        )

# ---------------------------------------------------------------------------
# Image management
# ---------------------------------------------------------------------------

def build_image(force_rebuild: bool = False) -> str:
    """Build the sandbox Docker image from the Dockerfile.

    Args:
        force_rebuild: If True, rebuilds even if the image already exists.

    Returns:
        The full image name:tag string.

    This is like compiling your code — you only need to do it once, or when
    you change the Dockerfile. Subsequent calls are no-ops if the image exists.
    """
    client = _get_docker_client()

    # Check if image already exists
    if not force_rebuild:
        try:
            client.images.get(IMAGE_FULL)
            print(f"  Image {IMAGE_FULL} already exists (use force_rebuild=True to rebuild)")
            return IMAGE_FULL
        except ImageNotFound:
            pass  # Need to build

    print(f"  Building Docker image: {IMAGE_FULL}")
    print(f"  Dockerfile location: {DOCKERFILE_DIR}")
    print(f"  This may take a few minutes on first run (downloading Ubuntu, Node.js, etc.)...")

    try:
        image, build_logs = client.images.build(
            path=DOCKERFILE_DIR,
            tag=IMAGE_FULL,
            rm=True,  # Remove intermediate containers after build
            forcerm=True,  # Remove intermediate containers even on failure
        )

        # Print build output so you can see progress
        for chunk in build_logs:
            if "stream" in chunk:
                line = chunk["stream"].strip()
                if line:
                    print(f"    {line}")

        print(f"  ✅ Image built successfully: {IMAGE_FULL}")
        return IMAGE_FULL

    except Exception as e:
        raise RuntimeError(f"Docker image build failed: {e}")

# ---------------------------------------------------------------------------
# Container lifecycle
# ---------------------------------------------------------------------------

def start_container(
    kiro_api_key: Optional[str] = None,
    extra_env: Optional[dict] = None,
) -> str:
    """Start a new sandbox container.

    Args:
        kiro_api_key: Kiro CLI API key. If None, reads from KIRO_API_KEY env var.
        extra_env: Additional environment variables to pass (e.g., user secrets).

    Returns:
        The container ID (a hex string like "a1b2c3d4e5...").

    What happens:
        1. Creates a container from the sandbox image
        2. Sets KIRO_API_KEY so Kiro CLI can authenticate
        3. Sets resource limits (memory, CPU) so a runaway build can't crash your machine
        4. Starts the container (it sits idle with tail -f /dev/null)
        5. Returns the container ID for future commands
    """
    # Resolve API key
    api_key = kiro_api_key or os.getenv(KIRO_API_KEY_ENV)
    if not api_key:
        raise ValueError(
            f"No Kiro API key provided. Set {KIRO_API_KEY_ENV} in config/.env "
            f"or pass kiro_api_key parameter."
        )

    # Make sure the image is built
    build_image()

    client = _get_docker_client()

    # Build environment variables dict
    env = {KIRO_API_KEY_ENV: api_key}
    if extra_env:
        env.update(extra_env)

    # Create and start the container
    print(f"  Starting sandbox container...")
    container = client.containers.run(
        IMAGE_FULL,
        detach=True,  # Run in background (don't block Python)
        environment=env,
        # Resource limits — safety net against infinite loops or memory leaks
        mem_limit=MEMORY_LIMIT,
        nano_cpus=int(CPU_LIMIT * 1e9),  # Docker uses nanoseconds for CPU
        # Working directory inside the container
        working_dir=CONTAINER_WORKSPACE,
        # Labels so we can find our containers later
        labels={"app": "autoapply-sandbox"},
    )

    print(f"  ✅ Container started: {container.short_id}")
    return container.id

def run_command(
    container_id: str,
    command: str,
    timeout: int = COMMAND_TIMEOUT,
    workdir: Optional[str] = None,
) -> tuple[int, str, str]:
    """Execute a command inside a running container.

    Args:
        container_id: The container to run in (from start_container).
        command: Shell command to execute (e.g., "npm install", "kiro --print '...'").
        timeout: Max seconds to wait. Default from config (600s = 10 min).
        workdir: Working directory inside the container. Defaults to /workspace.

    Returns:
        Tuple of (exit_code, stdout, stderr).

    This is like SSH-ing into the container and running a command.
    The Docker SDK equivalent of: docker exec <container_id> bash -c "<command>"
    """
    client = _get_docker_client()

    try:
        container = client.containers.get(container_id)
    except NotFound:
        raise RuntimeError(f"Container {container_id[:12]} not found. Was it stopped?")

    if container.status != "running":
        raise RuntimeError(
            f"Container {container_id[:12]} is not running (status: {container.status})"
        )

    # Execute the command
    # We wrap in bash -c so shell features (pipes, &&, etc.) work
    exec_result = container.exec_run(
        cmd=["bash", "-c", command],
        workdir=workdir or CONTAINER_WORKSPACE,
        demux=True,  # Separate stdout and stderr
    )

    # demux=True means output is a tuple (stdout_bytes, stderr_bytes)
    stdout = (exec_result.output[0] or b"").decode("utf-8", errors="replace")
    stderr = (exec_result.output[1] or b"").decode("utf-8", errors="replace")
    exit_code = exec_result.exit_code

    return exit_code, stdout, stderr

def get_container_status(container_id: str) -> str:
    """Get the current status of a container.

    Returns one of: "running", "exited", "paused", "restarting", "not_found"
    """
    client = _get_docker_client()
    try:
        container = client.containers.get(container_id)
        return container.status
    except NotFound:
        return "not_found"

def stop_container(container_id: str, remove: bool = True) -> None:
    """Stop and optionally remove a container.

    Args:
        container_id: The container to stop.
        remove: If True (default), also delete the container after stopping.
                This frees disk space. Set False if you want to inspect it later.

    Always call this when a build finishes (success or failure) to clean up.
    """
    client = _get_docker_client()

    try:
        container = client.containers.get(container_id)
    except NotFound:
        print(f"  Container {container_id[:12]} already gone.")
        return

    if container.status == "running":
        print(f"  Stopping container {container.short_id}...")
        container.stop(timeout=10)

    if remove:
        container.remove(force=True)
        print(f"  ✅ Container {container.short_id} removed.")
    else:
        print(f"  Container {container.short_id} stopped (not removed).")

def copy_files_from_container(
    container_id: str,
    src_path: str = CONTAINER_WORKSPACE,
    dest_path: Optional[str] = None,
) -> str:
    """Copy files from the container to your host machine.

    Args:
        container_id: The container to copy from.
        src_path: Path inside the container (default: /workspace).
        dest_path: Path on your machine to save to. Default: sandbox_output/<container_short_id>/

    Returns:
        The destination path where files were saved.

    This is how you get the built project out of the container.
    Docker's copy mechanism works via tar archives (it sends a .tar stream).
    """
    client = _get_docker_client()

    try:
        container = client.containers.get(container_id)
    except NotFound:
        raise RuntimeError(f"Container {container_id[:12]} not found.")

    # Determine output path
    if dest_path is None:
        dest_path = os.path.join(HOST_OUTPUT_DIR, container.short_id)

    os.makedirs(dest_path, exist_ok=True)

    # Get tar archive from container
    print(f"  Copying {src_path} from container to {dest_path}...")
    bits, stat = container.get_archive(src_path)

    # Extract the tar archive
    stream = io.BytesIO()
    for chunk in bits:
        stream.write(chunk)
    stream.seek(0)

    with tarfile.open(fileobj=stream) as tar:
        tar.extractall(path=dest_path)

    print(f"  ✅ Files copied to: {dest_path}")
    return dest_path

def cleanup_all_sandbox_containers() -> int:
    """Remove ALL sandbox containers (running or stopped).

    Returns the number of containers removed.
    Useful for cleanup if something goes wrong and containers pile up.
    """
    client = _get_docker_client()
    containers = client.containers.list(
        all=True,  # Include stopped containers
        filters={"label": "app=autoapply-sandbox"},
    )

    count = 0
    for container in containers:
        print(f"  Removing {container.short_id} (status: {container.status})...")
        container.remove(force=True)
        count += 1

    if count:
        print(f"  ✅ Removed {count} sandbox container(s).")
    else:
        print(f"  No sandbox containers found.")

    return count

# ---------------------------------------------------------------------------
# Test / CLI entrypoint
# ---------------------------------------------------------------------------

def _test():
    """Smoke test: build image, start container, verify Kiro CLI, stop container.

    Run with: python -m sandbox.builder --test
    """
    print("\n" + "=" * 60)
    print("  SANDBOX BUILDER — SMOKE TEST")
    print("=" * 60)

    # 1. Build image
    print("\n[1/5] Building Docker image...")
    build_image()

    # 2. Start container
    print("\n[2/5] Starting container...")
    container_id = start_container()

    try:
        # 3. Run a simple command
        print("\n[3/5] Running 'node --version' inside container...")
        exit_code, stdout, stderr = run_command(container_id, "node --version")
        print(f"       exit_code={exit_code}, stdout={stdout.strip()}")
        assert exit_code == 0, f"node --version failed: {stderr}"

        # 4. Verify Kiro CLI is installed AND that KIRO_API_KEY actually
        # authenticates. Note: `kiro-cli whoami` only checks that the env var
        # is *set*, not that it's valid — it happily reports "authenticated"
        # even for garbage keys. A real chat call is the only way to confirm
        # the key works, since it makes an actual network request.
        print("\n[4/5] Running a real headless chat call to verify auth...")
        exit_code, stdout, stderr = run_command(
            container_id,
            'kiro-cli chat "reply with the word PONG only" --no-interactive --trust-all-tools',
        )
        print(f"       exit_code={exit_code}")
        if exit_code != 0 or "PONG" not in stdout:
            print(f"       stdout={stdout.strip()}")
            print(f"       stderr={stderr.strip()}")
            print("       ⚠️  Kiro CLI auth may have failed. Check KIRO_API_KEY in config/.env.")
        else:
            print(f"       ✅ Kiro CLI authenticated and responded correctly.")

        # 5. Verify Python
        print("\n[5/5] Running 'python --version' inside container...")
        exit_code, stdout, stderr = run_command(container_id, "python --version")
        print(f"       exit_code={exit_code}, stdout={stdout.strip()}")
        assert exit_code == 0, f"python --version failed: {stderr}"

        print("\n" + "=" * 60)
        print("  ✅ ALL CHECKS PASSED")
        print("=" * 60)

    finally:
        # Always clean up, even if a test fails
        print("\nCleaning up...")
        stop_container(container_id)

if __name__ == "__main__":
    if "--test" in sys.argv:
        _test()
    elif "--cleanup" in sys.argv:
        cleanup_all_sandbox_containers()
    else:
        print("Usage:")
        print("  python -m sandbox.builder --test     # Run smoke test")
        print("  python -m sandbox.builder --cleanup  # Remove all sandbox containers")
