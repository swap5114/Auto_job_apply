"""Shared LLM client — supports Ollama (local) and Claude (API) backends.

Usage:
    from skills.llm_client import llm_generate

    result = llm_generate(
        system_prompt="You are a helpful assistant.",
        user_message="Summarize this text...",
        max_tokens=4096,
    )

The backend is selected via the MODEL_BACKEND env var:
    MODEL_BACKEND=ollama   -> local Ollama (default model: qwen2.5:7b-instruct)
    MODEL_BACKEND=claude   -> Anthropic Claude API (default model: claude-sonnet-4-20250514)

Per-call overrides are possible via the `backend` and `model` parameters.
"""

import os
import json
import re
import time
import random
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_BACKEND = os.getenv("MODEL_BACKEND", "claude").lower()  # "ollama" or "claude"

# Retry config for transient provider errors (503 overload, 429 rate limit,
# 5xx, timeouts). Providers like Gemini return 503 "high demand" in bursts;
# without retries every lead in that burst fails permanently for the run.
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "5"))
LLM_BACKOFF_BASE = float(os.getenv("LLM_BACKOFF_BASE", "2.0"))
LLM_BACKOFF_MAX = float(os.getenv("LLM_BACKOFF_MAX", "30.0"))

# Substrings that mark an error as transient/retryable (matched case-insensitively).
_TRANSIENT_MARKERS = (
    "503", "429", "500", "502", "504", "529",
    "unavailable", "overloaded", "high demand", "resource_exhausted",
    "rate limit", "ratelimit", "too many requests", "timeout", "timed out",
    "temporarily", "connection", "try again",
)


def _is_transient_error(exc: Exception) -> bool:
    """True if an exception looks like a transient provider error worth retrying."""
    if isinstance(exc, LLMTruncatedError):
        return True
    msg = str(exc).lower()
    return any(marker in msg for marker in _TRANSIENT_MARKERS)


class LLMTruncatedError(RuntimeError):
    """Raised when the provider stopped generating because it hit the output
    token ceiling (finishReason == MAX_TOKENS), so the returned text is
    incomplete (e.g. JSON cut off mid-string). Distinct from a generic error
    so callers can retry with a larger max_tokens budget instead of silently
    accepting a truncated/broken response -- the root cause of resumes that
    parsed 'half-empty' or 'broke midway'."""

# Claude defaults
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Ollama defaults
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Gemini defaults
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "models/gemini-flash-lite-latest")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Vertex AI defaults (consumes GCP credits)
VERTEX_PROJECT = os.getenv("VERTEX_PROJECT", os.getenv("GCP_PROJECT", os.getenv("GOOGLE_CLOUD_PROJECT", "auto-job-apply-1859b")))
VERTEX_LOCATION = os.getenv("VERTEX_LOCATION", "us-central1")
VERTEX_MODEL = os.getenv("VERTEX_MODEL", "gemini-2.5-flash")
# Bigger Google reasoning model for higher-quality output (e.g. resume
# tailoring) — same Vertex generateContent path/region as Flash, no partner
# quota needed. Used via the "vertex_pro" backend.
VERTEX_PRO_MODEL = os.getenv("VERTEX_PRO_MODEL", "gemini-2.5-pro")
# Claude served THROUGH Vertex AI (billed to GCP credits via ADC — no
# Anthropic API key). Model ID + region per Google's Model Garden:
# https://cloud.google.com/vertex-ai/generative-ai/docs/partner-models/claude/sonnet-4-5
# IMPORTANT: Claude on Vertex is NOT served in us-central1 (where our Gemini
# model runs). It's available in us-east5 / europe-west1 / asia-southeast1 /
# the global endpoint — so Claude has its OWN region knob, defaulting to
# us-east5, independent of VERTEX_LOCATION.
VERTEX_CLAUDE_MODEL = os.getenv("VERTEX_CLAUDE_MODEL", "claude-sonnet-4-6")
# Claude Sonnet 4.6 is served on the GLOBAL endpoint (per Google Model Garden
# docs: region="global"). The global host is region-less; _call_vertex_claude
# handles that. Override VERTEX_CLAUDE_LOCATION only if you enable Claude in a
# specific region for lower latency / dedicated regional quota.
VERTEX_CLAUDE_LOCATION = os.getenv("VERTEX_CLAUDE_LOCATION", "global")
# Anthropic-on-Vertex API version string (fixed contract, not our choice).
VERTEX_ANTHROPIC_VERSION = "vertex-2023-10-16"

_vertex_token_cache: dict = {"token": None, "expires_at": 0}


def _get_vertex_access_token() -> str:
    """Retrieves an access token for Vertex AI calls.
    
    Uses Google Cloud Application Default Credentials (metadata server on Cloud Run),
    falling back to `gcloud auth print-access-token` for local development.
    """
    now = time.time()
    if _vertex_token_cache["token"] and now < _vertex_token_cache["expires_at"]:
        return _vertex_token_cache["token"]

    token = None
    try:
        import google.auth
        import google.auth.transport.requests

        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        token = credentials.token
    except Exception:
        import subprocess
        try:
            token = subprocess.check_output("gcloud auth print-access-token", shell=True).decode().strip()
        except Exception as e:
            raise RuntimeError(
                f"Failed to obtain Vertex AI access token. Run 'gcloud auth application-default login' "
                f"or ensure service account has access: {e}"
            )

    if not token:
        raise RuntimeError("Empty access token retrieved for Vertex AI.")

    _vertex_token_cache["token"] = token
    # Cache token for 50 minutes (GCP tokens typically last 60 minutes)
    _vertex_token_cache["expires_at"] = now + 3000
    return token


def _call_vertex(system_prompt: str, user_message: str, max_tokens: int, model: str) -> str:
    """Calls Google Vertex AI REST API (Gemini models) billed to GCP project."""
    import requests

    token = _get_vertex_access_token()
    clean_model = model.replace("models/", "")
    url = (
        f"https://{VERTEX_LOCATION}-aiplatform.googleapis.com/v1/projects/{VERTEX_PROJECT}/"
        f"locations/{VERTEX_LOCATION}/publishers/google/models/{clean_model}:generateContent"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": VERTEX_PROJECT,
    }

    gen_config = {
        "maxOutputTokens": max(max_tokens, 4096),
    }
    if "flash" in clean_model.lower():
        gen_config["thinkingConfig"] = {"thinkingBudget": 0}

    payload = {
        "contents": [{
            "role": "user",
            "parts": [{"text": user_message}]
        }],
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "generationConfig": gen_config
    }

    response = requests.post(url, headers=headers, json=payload, timeout=60)
    if response.status_code != 200:
        raise RuntimeError(
            f"Vertex AI API error {response.status_code}: {response.text}"
        )

    result = response.json()
    if not result.get("candidates"):
        raise RuntimeError(f"Vertex AI returned no candidates: {result}")

    candidate = result["candidates"][0]
    content = candidate.get("content", {})
    finish_reason = candidate.get("finishReason", "UNKNOWN")
    if not content.get("parts"):
        # Empty content with a MAX_TOKENS finish means the whole budget went
        # to (thinking) tokens with nothing emitted -- retryable with a
        # larger budget, not a hard failure.
        if finish_reason == "MAX_TOKENS":
            raise LLMTruncatedError(
                f"Vertex AI hit MAX_TOKENS with no output (max_tokens={max_tokens})."
            )
        raise RuntimeError(
            f"Vertex AI returned empty content (finish: {finish_reason}). "
            f"Try increasing max_tokens or simplifying the prompt."
        )

    text = content["parts"][0]["text"]
    # A MAX_TOKENS finish with partial text means the response was cut off
    # mid-generation -- surface it as truncated so llm_generate_json retries
    # with a bigger budget rather than trying to json.loads a broken string.
    if finish_reason == "MAX_TOKENS":
        raise LLMTruncatedError(
            f"Vertex AI response truncated at MAX_TOKENS (max_tokens={max_tokens}). "
            f"Got {len(text)} chars before cutoff."
        )
    return text.strip()


def _call_vertex_claude(system_prompt: str, user_message: str, max_tokens: int, model: str) -> str:
    """Call an Anthropic Claude model THROUGH Vertex AI (billed to GCP credits
    via ADC — no Anthropic API key).

    Claude-on-Vertex uses the Anthropic Messages API shape with two Vertex
    differences: the model goes in the endpoint URL (not the body), and the
    body carries "anthropic_version" instead of "model". Auth is the same ADC
    bearer token the Gemini Vertex path uses.
    """
    import requests

    token = _get_vertex_access_token()
    location = VERTEX_CLAUDE_LOCATION
    # The global endpoint uses a region-less host; regional endpoints prefix
    # the host with the region (e.g. us-east5-aiplatform.googleapis.com).
    host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
    url = (
        f"https://{host}/v1/projects/{VERTEX_PROJECT}/"
        f"locations/{location}/publishers/anthropic/models/{model}:rawPredict"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-Goog-User-Project": VERTEX_PROJECT,
    }

    payload = {
        "anthropic_version": VERTEX_ANTHROPIC_VERSION,
        "max_tokens": max(max_tokens, 1024),
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_message}],
    }

    _timeout = float(os.getenv("VERTEX_CLAUDE_TIMEOUT", "45"))
    response = requests.post(url, headers=headers, json=payload, timeout=_timeout)
    if response.status_code != 200:
        raise RuntimeError(
            f"Vertex Claude API error {response.status_code}: {response.text}"
        )

    result = response.json()
    blocks = result.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()

    stop_reason = result.get("stop_reason")
    if not text:
        if stop_reason == "max_tokens":
            raise LLMTruncatedError(
                f"Vertex Claude hit max_tokens with no output (max_tokens={max_tokens})."
            )
        raise RuntimeError(f"Vertex Claude returned empty content: {result}")
    if stop_reason == "max_tokens":
        raise LLMTruncatedError(
            f"Vertex Claude response truncated at max_tokens (max_tokens={max_tokens})."
        )
    return text


# ---------------------------------------------------------------------------
# Backend implementations
# ---------------------------------------------------------------------------


def _call_claude(system_prompt: str, user_message: str, max_tokens: int, model: str) -> str:
    """Calls the Anthropic Claude API and returns the text response."""
    from anthropic import Anthropic

    if not ANTHROPIC_API_KEY:
        raise RuntimeError(
            "MODEL_BACKEND=claude but ANTHROPIC_API_KEY is not set in config/.env"
        )

    # M-3: set an explicit timeout so a hung Claude request can't block a
    # pipeline worker thread indefinitely (the Gemini/Vertex REST paths
    # already pass timeout=60). Overridable via LLM_HTTP_TIMEOUT.
    _timeout = float(os.getenv("LLM_HTTP_TIMEOUT", "60"))
    client = Anthropic(api_key=ANTHROPIC_API_KEY, timeout=_timeout)
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    raw_text = "".join(
        block.text for block in response.content if block.type == "text"
    ).strip()
    return raw_text


def _call_ollama(system_prompt: str, user_message: str, max_tokens: int, model: str) -> str:
    """Calls a local Ollama model and returns the text response."""
    import ollama

    response = ollama.chat(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        options={"num_predict": max_tokens},
    )

    return response["message"]["content"].strip()


def _call_gemini(system_prompt: str, user_message: str, max_tokens: int, model: str) -> str:
    """Calls Google Gemini REST API and returns the text response."""
    import requests

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "MODEL_BACKEND=gemini but GEMINI_API_KEY is not set in config/.env"
        )

    # Use the REST API directly - more reliable than SDK
    # Model name already includes "models/" prefix
    url = f"https://generativelanguage.googleapis.com/v1beta/{model}:generateContent"
    
    headers = {"Content-Type": "application/json"}
    
    payload = {
        "contents": [{
            "parts": [{"text": user_message}]
        }],
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        },
        "generationConfig": {
            "maxOutputTokens": max_tokens
        }
    }
    
    response = requests.post(
        f"{url}?key={GEMINI_API_KEY}",
        headers=headers,
        json=payload,
        timeout=60
    )
    
    if response.status_code != 200:
        raise RuntimeError(
            f"Gemini API error {response.status_code}: {response.text}"
        )
    
    result = response.json()
    
    # Handle empty response or MAX_TOKENS finish
    if not result.get("candidates"):
        raise RuntimeError(f"Gemini returned no candidates: {result}")
    
    candidate = result["candidates"][0]
    content = candidate.get("content", {})
    finish_reason = candidate.get("finishReason", "UNKNOWN")

    if not content.get("parts"):
        if finish_reason == "MAX_TOKENS":
            raise LLMTruncatedError(
                f"Gemini hit MAX_TOKENS with no output (max_tokens={max_tokens})."
            )
        raise RuntimeError(
            f"Gemini returned empty content (finish: {finish_reason}). "
            f"Try increasing max_tokens or simplifying the prompt."
        )

    text = content["parts"][0]["text"]
    if finish_reason == "MAX_TOKENS":
        raise LLMTruncatedError(
            f"Gemini response truncated at MAX_TOKENS (max_tokens={max_tokens}). "
            f"Got {len(text)} chars before cutoff."
        )
    return text.strip()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def llm_generate(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4096,
    backend: str | None = None,
    model: str | None = None,
) -> str:
    """Generate a completion using the configured LLM backend.

    Parameters
    ----------
    system_prompt : str
        System-level instructions for the model.
    user_message : str
        The user/task message.
    max_tokens : int
        Maximum tokens to generate (default 4096).
    backend : str | None
        Override the global MODEL_BACKEND for this call ("ollama" or "claude").
    model : str | None
        Override the default model name for this call.

    Returns
    -------
    str
        Raw text response from the model.

    Raises
    ------
    RuntimeError
        If the backend is misconfigured or the API call fails.
    ValueError
        If an unknown backend is specified.
    """
    chosen_backend = (backend or MODEL_BACKEND).lower()

    if chosen_backend == "claude":
        chosen_model = model or CLAUDE_MODEL
        call = lambda: _call_claude(system_prompt, user_message, max_tokens, chosen_model)
    elif chosen_backend == "ollama":
        chosen_model = model or OLLAMA_MODEL
        call = lambda: _call_ollama(system_prompt, user_message, max_tokens, chosen_model)
    elif chosen_backend in ("vertex", "vertex_ai"):
        chosen_model = model or VERTEX_MODEL
        call = lambda: _call_vertex(system_prompt, user_message, max_tokens, chosen_model)
    elif chosen_backend in ("vertex_pro", "gemini_pro"):
        # Bigger Google reasoning model (Gemini Pro) via Vertex — same path as
        # the default Vertex/Gemini call, just a stronger model. No partner
        # quota needed (unlike Claude, which isn't available on this tier).
        chosen_model = model or VERTEX_PRO_MODEL
        call = lambda: _call_vertex(system_prompt, user_message, max_tokens, chosen_model)
    elif chosen_backend in ("vertex_claude", "claude_vertex"):
        # Claude through Vertex AI (GCP credits, ADC — no Anthropic key).
        # NOTE: Anthropic models are NOT available on this project's tier, so
        # this path will 429/404. Kept for environments where it IS enabled.
        chosen_model = model or VERTEX_CLAUDE_MODEL
        call = lambda: _call_vertex_claude(system_prompt, user_message, max_tokens, chosen_model)
    elif chosen_backend == "gemini":
        # If GEMINI_API_KEY is available and not using vertex override, use AI Studio REST
        if GEMINI_API_KEY and not os.getenv("USE_VERTEX"):
            chosen_model = model or GEMINI_MODEL
            call = lambda: _call_gemini(system_prompt, user_message, max_tokens, chosen_model)
        else:
            chosen_model = model or VERTEX_MODEL
            call = lambda: _call_vertex(system_prompt, user_message, max_tokens, chosen_model)
    else:
        raise ValueError(
            f"Unknown MODEL_BACKEND '{chosen_backend}'. Must be 'vertex', 'vertex_pro', "
            f"'vertex_claude', 'gemini', 'claude', or 'ollama'."
        )

    last_exc: Exception | None = None
    for attempt in range(LLM_MAX_RETRIES + 1):
        try:
            return call()
        except Exception as exc:
            last_exc = exc
            is_last_attempt = attempt == LLM_MAX_RETRIES
            if is_last_attempt or not _is_transient_error(exc):
                raise
            # Exponential backoff with jitter, capped at LLM_BACKOFF_MAX.
            delay = min(LLM_BACKOFF_BASE * (2 ** attempt), LLM_BACKOFF_MAX)
            delay += random.uniform(0, delay * 0.1)
            print(
                f"  ⚠️  llm_generate: transient error on attempt {attempt + 1}/"
                f"{LLM_MAX_RETRIES + 1} ({exc}) -- retrying in {delay:.1f}s"
            )
            time.sleep(delay)

    # Unreachable, but keeps type checkers happy and documents intent.
    raise last_exc  # type: ignore[misc]


def extract_json_object(raw: str) -> str:
    """Pull the first complete, balanced JSON object out of a model response.

    Robust to the common ways providers wrap/pollute JSON output:
      - ```json ... ``` code fences,
      - leading prose ("Here is the JSON:") before the object,
      - trailing prose/notes after the closing brace.

    Scans for the first '{' and walks braces (respecting string literals and
    escapes) to find its matching '}', returning exactly that substring. Falls
    back to the fence-stripped whole string if no balanced object is found, so
    a genuinely-plain JSON string still round-trips.
    """
    s = raw.strip()
    # Strip a leading/trailing code fence if the whole thing is fenced.
    if s.startswith("```"):
        s = re.sub(r"^```(json)?\s*", "", s)
        s = re.sub(r"\s*```$", "", s).strip()

    start = s.find("{")
    if start == -1:
        return s

    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
    # Unbalanced (likely truncated) -- return from the first brace so the
    # caller's json.loads raises a clear JSONDecodeError.
    return s[start:]


def llm_generate_json(
    system_prompt: str,
    user_message: str,
    max_tokens: int = 4096,
    backend: str | None = None,
    model: str | None = None,
) -> dict:
    """Like llm_generate but parses the response as JSON.

    Production hardening for the resume/tailor path:
      - Extracts the first balanced JSON object (tolerant of code fences and
        leading/trailing prose), instead of assuming the whole response is
        clean JSON.
      - On a JSONDecodeError (usually a response cut off mid-object) OR an
        LLMTruncatedError, retries ONCE with a doubled max_tokens budget
        before giving up -- so a resume that would have parsed 'half-empty'
        gets a real second chance instead of silently degrading.

    Raises json.JSONDecodeError if the response still isn't valid JSON after
    the retry, or the underlying provider error if generation fails outright.
    """
    budget = max_tokens
    last_decode_err: json.JSONDecodeError | None = None

    for attempt in range(2):
        try:
            raw = llm_generate(system_prompt, user_message, budget, backend, model)
        except LLMTruncatedError:
            # Whole generation truncated -- bump the budget and retry once.
            if attempt == 0:
                budget = min(budget * 2, 16384)
                print(f"  ⚠️  llm_generate_json: output truncated, retrying with max_tokens={budget}")
                continue
            raise

        candidate = extract_json_object(raw)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError as e:
            last_decode_err = e
            if attempt == 0:
                budget = min(budget * 2, 16384)
                print(f"  ⚠️  llm_generate_json: invalid/truncated JSON, retrying with max_tokens={budget}")
                continue
            raise

    # Unreachable, but keeps type checkers happy.
    assert last_decode_err is not None
    raise last_decode_err
