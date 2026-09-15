"""Live smoke test for the configured tailoring model on Vertex.

Fires ONE real request (via ADC — no API keys) to whatever TAILOR_BACKEND
points at (default: Gemini 2.5 Pro / "vertex_pro"), to confirm the model is
reachable and the region/model ID are correct. Prints the resolved config,
the reply, and a clear PASS/FAIL.

Usage:
    python -m scripts.smoke_test_vertex_claude
    python -m scripts.smoke_test_vertex_claude vertex_pro
    python -m scripts.smoke_test_vertex_claude vertex        # Flash

Prereqs:
  - Application Default Credentials: `gcloud auth application-default login`
    (or a service account with Vertex AI User on the project).
"""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from skills import llm_client as llm
from skills.tailor_resume import TAILOR_BACKEND


def main() -> None:
    backend = sys.argv[1] if len(sys.argv) > 1 else (TAILOR_BACKEND or "vertex_pro")

    model = {
        "vertex_pro": llm.VERTEX_PRO_MODEL,
        "gemini_pro": llm.VERTEX_PRO_MODEL,
        "vertex": llm.VERTEX_MODEL,
        "vertex_ai": llm.VERTEX_MODEL,
        "vertex_claude": llm.VERTEX_CLAUDE_MODEL,
        "claude_vertex": llm.VERTEX_CLAUDE_MODEL,
    }.get(backend, backend)

    print("=" * 68)
    print("  VERTEX TAILORING-MODEL SMOKE TEST")
    print("=" * 68)
    print(f"  project : {llm.VERTEX_PROJECT}")
    print(f"  backend : {backend}")
    print(f"  model   : {model}")
    print("-" * 68)

    try:
        reply = llm.llm_generate(
            system_prompt="You are a terse assistant. Reply with a single short sentence.",
            user_message="In one sentence, confirm you can tailor resumes.",
            max_tokens=256,
            backend=backend,
        )
    except Exception as e:
        print(f"  FAIL: {e}")
        print("\n  Common causes:")
        print("   - 429 RESOURCE_EXHAUSTED: no quota for that model. Gemini models are")
        print("     enabled by default; partner (Claude) models are not on this tier.")
        print("   - 404 NOT_FOUND: wrong model ID or region for this backend.")
        print("   - 401/403: run `gcloud auth application-default login`.")
        sys.exit(1)

    print(f"  reply   : {reply}")
    print(f"\n  PASS - {backend} is working.")
    print("=" * 68)


if __name__ == "__main__":
    main()
