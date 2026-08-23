"""Sandbox configuration constants.

Centralizes Docker image settings, resource limits, and timeouts so
they're easy to tune without touching the builder logic.
"""

import os

# ---------------------------------------------------------------------------
# Docker image
# ---------------------------------------------------------------------------

# Name and tag for the sandbox image. When you rebuild, bump the tag.
IMAGE_NAME = "autoapply-sandbox"
IMAGE_TAG = "latest"
IMAGE_FULL = f"{IMAGE_NAME}:{IMAGE_TAG}"

# Path to the Dockerfile (relative to project root)
DOCKERFILE_DIR = os.path.join(os.path.dirname(__file__))

# ---------------------------------------------------------------------------
# Container resource limits
# ---------------------------------------------------------------------------

# Memory limit — prevents a runaway build from eating all your RAM.
# Format: "2g" = 2 GB, "512m" = 512 MB
MEMORY_LIMIT = "4g"

# CPU quota — how many CPUs the container can use.
# 2.0 = two full cores. On a 4-core machine, this leaves 2 for your system.
CPU_LIMIT = 2.0

# ---------------------------------------------------------------------------
# Timeouts
# ---------------------------------------------------------------------------

# Max time (seconds) a single command can run inside the container.
# Kiro CLI builds can take a while — 10 minutes is generous for a demo project.
COMMAND_TIMEOUT = 600

# Max time (seconds) for the entire build lifecycle (all commands combined).
# 30 minutes should cover even complex full-stack builds.
BUILD_TIMEOUT = 1800

# ---------------------------------------------------------------------------
# Paths inside the container
# ---------------------------------------------------------------------------

# Where projects are built inside the container
CONTAINER_WORKSPACE = "/workspace"

# Where build output lands on your host machine (relative to project root)
HOST_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "sandbox_output")

# ---------------------------------------------------------------------------
# Kiro CLI
# ---------------------------------------------------------------------------

# The env var *name* Kiro CLI expects for authentication (not the key value
# itself — the actual key lives only in config/.env, which is gitignored).
KIRO_API_KEY_ENV = "KIRO_API_KEY"
