"""GCP Cloud Run Jobs execution engine — runs demo builds on Google Cloud Platform.

This module provides support for executing sandbox build tasks on GCP Cloud Run
Jobs when ENABLE_GCP_SANDBOX=true in environment config.

When triggered, it launches an ephemeral Cloud Run Job container execution on GCP,
passing user prompt, GitHub tokens, and project specs via environment variables.

Uses the `google-cloud-run` Python SDK (or gcloud CLI fallback).
"""

import os
import sys
import json
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Check if GCP sandbox mode is enabled
ENABLE_GCP_SANDBOX = os.getenv("ENABLE_GCP_SANDBOX", "false").lower() == "true"
GCP_PROJECT_ID = os.getenv("GCP_PROJECT_ID") or os.getenv("GOOGLE_CLOUD_PROJECT", "")
GCP_REGION = os.getenv("GCP_REGION", "us-central1")
GCP_JOB_NAME = os.getenv("GCP_BUILD_JOB_NAME", "demo-builder-worker")


def is_gcp_sandbox_enabled() -> bool:
    """Return True if GCP Cloud Run Jobs sandbox execution is enabled."""
    return ENABLE_GCP_SANDBOX and bool(GCP_PROJECT_ID)


def launch_gcp_cloud_run_job(
    build_id: str,
    demo_project: Dict[str, Any],
    company: str = "",
    github_token: Optional[str] = None,
    max_attempts: int = 2,
) -> Dict[str, Any]:
    """Launch an ephemeral GCP Cloud Run Job execution.

    Args:
        build_id: Short unique build identifier.
        demo_project: Demo project spec dictionary.
        company: Company/lead name.
        github_token: User's connected GitHub access token.
        max_attempts: Maximum LLM self-healing retries.

    Returns:
        Dict containing job execution metadata (execution_name, status).
    """
    if not is_gcp_sandbox_enabled():
        raise RuntimeError("GCP Sandbox mode is not enabled or GCP_PROJECT_ID is missing.")

    try:
        from google.cloud import run_v2

        client = run_v2.JobsClient()
        parent_job = f"projects/{GCP_PROJECT_ID}/locations/{GCP_REGION}/jobs/{GCP_JOB_NAME}"

        env_vars = [
            run_v2.EnvVar(name="BUILD_ID", value=build_id),
            run_v2.EnvVar(name="DEMO_TITLE", value=demo_project.get("title", "")),
            run_v2.EnvVar(name="COMPANY", value=company),
            run_v2.EnvVar(name="DEMO_PROJECT_JSON", value=json.dumps(demo_project)),
            run_v2.EnvVar(name="MAX_ATTEMPTS", value=str(max_attempts)),
        ]

        if github_token:
            env_vars.append(run_v2.EnvVar(name="USER_GITHUB_TOKEN", value=github_token))

        container_override = run_v2.RunJobRequest.Overrides.ContainerOverride(env=env_vars)
        overrides = run_v2.RunJobRequest.Overrides(container_overrides=[container_override])

        request = run_v2.RunJobRequest(name=parent_job, overrides=overrides)
        operation = client.run_job(request=request)

        execution_name = operation.metadata.name if hasattr(operation, "metadata") else build_id
        logger.info(f"Triggered GCP Cloud Run Job execution: {execution_name} for build_id={build_id}")

        return {
            "status": "triggered",
            "execution_name": execution_name,
            "build_id": build_id,
            "backend": "gcp_cloud_run_job",
        }

    except Exception as exc:
        logger.warning(f"Failed to launch GCP Cloud Run Job via SDK ({exc}). Falling back to local Docker execution.")
        raise
