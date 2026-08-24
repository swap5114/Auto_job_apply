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

# ---------------------------------------------------------------------------
# Build orchestrator (Task 2)
# ---------------------------------------------------------------------------

# File-convention names Kiro is instructed to write inside /workspace so the
# orchestrator (outside the container) can detect state changes without
# scraping free-text chat output. Simple, inspectable, easy to debug.
NEEDS_SECRETS_FILENAME = ".needs_secrets.json"
BUILD_STATUS_FILENAME = ".build_status.json"

CONTAINER_NEEDS_SECRETS_PATH = f"{CONTAINER_WORKSPACE}/{NEEDS_SECRETS_FILENAME}"
CONTAINER_BUILD_STATUS_PATH = f"{CONTAINER_WORKSPACE}/{BUILD_STATUS_FILENAME}"

# How many generate -> build -> fix loops to allow before giving up.
# Each loop is one Kiro CLI turn — this is the main cost/time control knob.
# Overridable via DEMO_MAX_RETRIES in config/.env.
DEFAULT_MAX_ATTEMPTS = int(os.getenv("DEMO_MAX_RETRIES", "2"))

# Timeout for a single Kiro CLI turn. Building a small project can take
# several minutes (npm installs, etc.) so this is longer than a plain shell
# command's default COMMAND_TIMEOUT.
KIRO_TURN_TIMEOUT = int(os.getenv("KIRO_TURN_TIMEOUT", "900"))  # 15 min

# ---------------------------------------------------------------------------
# GitHub deploy (Task 4)
# ---------------------------------------------------------------------------

# Prefix for auto-created demo repo names, e.g. "demo-acme-corp-a1b2c3d4".
# Overridable via DEMO_PROJECT_PREFIX in config/.env (already present there
# from earlier planning).
DEMO_REPO_PREFIX = os.getenv("DEMO_PROJECT_PREFIX", "demo-")

# Whether created repos are public or private. Public is simpler for sharing
# a live Vercel-deployed link in outreach; flip to True if you'd rather keep
# demo code private and only share the deployed URL.
DEMO_REPO_PRIVATE = os.getenv("DEMO_REPO_PRIVATE", "false").lower() == "true"

# Internal convention files that must NEVER be pushed to a demo's public
# GitHub repo — most importantly .secrets.env, which holds real user-provided
# API keys. These are stripped from the exported project directory before
# `git init` ever runs, and also gitignored as a second line of defense.
INTERNAL_FILES_TO_STRIP = [
    ".secrets.env",
    BUILD_STATUS_FILENAME,
    NEEDS_SECRETS_FILENAME,
    "_prompt.txt",
]

# Timeout (seconds) for git/gh subprocess calls on the host machine.
GIT_COMMAND_TIMEOUT = 120

# ---------------------------------------------------------------------------
# Vercel deploy (Task 5)
# ---------------------------------------------------------------------------

VERCEL_API_BASE = "https://api.vercel.com"

# How long to poll a deployment for READY/ERROR before giving up.
VERCEL_DEPLOY_POLL_TIMEOUT = int(os.getenv("VERCEL_DEPLOY_POLL_TIMEOUT", "180"))  # 3 min
VERCEL_DEPLOY_POLL_INTERVAL = 5  # seconds between status checks

# Timeout for individual Vercel API HTTP calls.
VERCEL_HTTP_TIMEOUT = 30

# ---------------------------------------------------------------------------
# Render deploy (Task 6) — backend hosting for full-stack demos
# ---------------------------------------------------------------------------

RENDER_API_BASE = "https://api.render.com/v1"

# Region for created services. "oregon" is Render's default/cheapest region
# and was used during verification — kept as the default for consistency.
RENDER_DEFAULT_REGION = os.getenv("RENDER_REGION", "oregon")

# How long to poll a deploy for live/failed before giving up. Render's free
# tier build+deploy for a small app took ~45s during verification; allow
# generous headroom for slower installs (Node with many deps, etc.).
RENDER_DEPLOY_POLL_TIMEOUT = int(os.getenv("RENDER_DEPLOY_POLL_TIMEOUT", "300"))  # 5 min
RENDER_DEPLOY_POLL_INTERVAL = 10  # seconds between status checks

RENDER_HTTP_TIMEOUT = 30

# Terminal deploy statuses (from Render's own deploy status enum) that mean
# "stop polling" — either success or a form of failure/cancellation.
RENDER_TERMINAL_STATUSES = ("live", "build_failed", "update_failed", "canceled", "deactivated")
