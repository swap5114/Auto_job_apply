# =============================================================================
# Sandbox build environment for Kiro CLI
# =============================================================================
# This image provides a complete development environment where Kiro CLI can
# autonomously build full-stack projects (React, Next.js, Python, Node, etc.)
#
# Key components:
#   - Ubuntu 22.04 as base (stable, well-supported)
#   - Node.js 20 LTS (frontend builds, npm/yarn/pnpm)
#   - Python 3.11 (backend projects, pip)
#   - Git (pushing to GitHub)
#   - Kiro CLI (the AI coding agent)
# =============================================================================

FROM ubuntu:24.04

# Prevent interactive prompts during apt installs
ENV DEBIAN_FRONTEND=noninteractive

# ---------------------------------------------------------------------------
# 1. System dependencies
# ---------------------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Basics
    curl \
    wget \
    git \
    ca-certificates \
    gnupg \
    # unzip — required by the Kiro CLI installer script
    unzip \
    # Build tools (some npm packages need these to compile native modules)
    build-essential \
    # Python — use the distro's default python3 package rather than pinning
    # to "python3.11" by name. Ubuntu 24.04 (Noble) ships Python 3.12 and
    # doesn't publish a "python3.11" package in its default repos, so a
    # hardcoded version number breaks on newer base images.
    python3 \
    python3-venv \
    python3-pip \
    # Cleanup to keep image size down
    && rm -rf /var/lib/apt/lists/*

# Make whatever python3 got installed available as the plain "python" command
RUN update-alternatives --install /usr/bin/python python /usr/bin/python3 1

# ---------------------------------------------------------------------------
# 2. Node.js 20 LTS (via NodeSource)
# ---------------------------------------------------------------------------
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install common package managers globally
RUN npm install -g yarn pnpm

# ---------------------------------------------------------------------------
# 3. Kiro CLI
# ---------------------------------------------------------------------------
# Install Kiro CLI using the official installer.
# The --print flag lets it run headlessly (no interactive prompts).
RUN curl -fsSL https://cli.kiro.dev/install | bash

# Make sure kiro is in PATH (the installer puts it in /root/.local/bin)
ENV PATH="/root/.local/bin:${PATH}"

# The installer names the binary "kiro-cli", but the docs/prompts we use
# refer to it as "kiro". Symlink so both names work.
RUN ln -s /root/.local/bin/kiro-cli /root/.local/bin/kiro

# ---------------------------------------------------------------------------
# 4. Create workspace directory
# ---------------------------------------------------------------------------
RUN mkdir -p /workspace
WORKDIR /workspace

# ---------------------------------------------------------------------------
# 5. Default command — keep container alive so we can exec into it
# ---------------------------------------------------------------------------
# "tail -f /dev/null" keeps the container running without doing anything.
# Our Python code will use docker exec to run commands inside it.
CMD ["tail", "-f", "/dev/null"]
