"""Artifact storage abstraction for resume files (PDF / Markdown / original
uploads).

Design
------
Structured resume JSON stays in Postgres (small, queryable, transactional).
BINARY / rendered artifacts — the PDF and Markdown we generate, and the
original uploaded file — do NOT belong in Postgres (bloat, slow backups) and
CANNOT live on Cloud Run's ephemeral, per-instance local disk (a file written
on instance A won't exist when instance B serves it). They go here instead.

Backends
--------
  - GCS (production): set RESUME_STORAGE_BACKEND=gcs and RESUME_GCS_BUCKET.
    Objects are stored at gs://<bucket>/<key>. Read/write via the
    google-cloud-storage client (added to requirements).
  - Local disk (dev/tests, default): files under <repo>/resumes/. Keeps the
    existing local workflow working with zero config.

The public API is intentionally tiny and backend-agnostic:
    put_bytes(key, data, content_type) -> stored key
    get_bytes(key) -> bytes | None
    exists(key) -> bool
    delete(key) -> None

`key` is a forward-slash path like "tailored/<user_id>/<resume_id>.pdf".
Callers never branch on the backend; swapping GCS in/out is one env var.
"""

import os
import threading

# Local-disk root (default backend). Kept as the existing resumes/ dir so
# nothing about local dev changes.
_LOCAL_ROOT = os.path.join(os.path.dirname(__file__), "..", "resumes")

_BACKEND = os.getenv("RESUME_STORAGE_BACKEND", "local").lower()
_GCS_BUCKET = os.getenv("RESUME_GCS_BUCKET", "")

_gcs_client = None
_gcs_lock = threading.Lock()


def backend() -> str:
    """Return the active backend name ("gcs" or "local")."""
    if _BACKEND == "gcs" and _GCS_BUCKET:
        return "gcs"
    return "local"


# ---------------------------------------------------------------------------
# GCS backend
# ---------------------------------------------------------------------------

def _get_bucket():
    """Lazily construct a cached GCS bucket handle. Raises RuntimeError with
    an actionable message if the client/bucket can't be initialized."""
    global _gcs_client
    with _gcs_lock:
        if _gcs_client is None:
            try:
                from google.cloud import storage  # type: ignore
            except Exception as e:  # pragma: no cover - import guard
                raise RuntimeError(
                    "RESUME_STORAGE_BACKEND=gcs but google-cloud-storage isn't "
                    f"installed: {e}. Add it to requirements or use the local backend."
                )
            _gcs_client = storage.Client()
        return _gcs_client.bucket(_GCS_BUCKET)


# ---------------------------------------------------------------------------
# Local backend
# ---------------------------------------------------------------------------

def _local_path(key: str) -> str:
    # Normalize the key into a safe path under _LOCAL_ROOT.
    safe = key.replace("\\", "/").lstrip("/")
    return os.path.join(_LOCAL_ROOT, *safe.split("/"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def put_bytes(key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """Store `data` at `key`. Returns the key (the stable reference callers
    persist alongside the resume row)."""
    if backend() == "gcs":
        blob = _get_bucket().blob(key)
        blob.upload_from_string(data, content_type=content_type)
        return key

    path = _local_path(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return key


def get_bytes(key: str) -> bytes | None:
    """Fetch the object at `key`, or None if it doesn't exist."""
    if not key:
        return None
    if backend() == "gcs":
        blob = _get_bucket().blob(key)
        if not blob.exists():
            return None
        return blob.download_as_bytes()

    path = _local_path(key)
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        return f.read()


def exists(key: str) -> bool:
    if not key:
        return False
    if backend() == "gcs":
        return _get_bucket().blob(key).exists()
    return os.path.exists(_local_path(key))


def delete(key: str) -> None:
    if not key:
        return
    if backend() == "gcs":
        blob = _get_bucket().blob(key)
        if blob.exists():
            blob.delete()
        return
    path = _local_path(key)
    if os.path.exists(path):
        os.remove(path)


# ---------------------------------------------------------------------------
# Key helpers — one place that owns the object-key layout.
# ---------------------------------------------------------------------------

def tailored_key(user_id: str, resume_id: str, ext: str) -> str:
    """Object key for a per-lead tailored artifact, namespaced by user."""
    ext = ext.lstrip(".")
    return f"tailored/{user_id}/{resume_id}.{ext}"


def original_upload_key(user_id: str, resume_id: str, ext: str) -> str:
    """Object key for a user's originally-uploaded resume file."""
    ext = ext.lstrip(".")
    return f"uploads/{user_id}/{resume_id}.{ext}"
