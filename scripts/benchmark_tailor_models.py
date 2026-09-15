"""Offline model benchmark for resume tailoring — Gemini Flash vs Gemini Pro
(both via Vertex / GCP credits).

WHY THIS EXISTS
---------------
Production tailors a resume with a SINGLE call to ONE configured model
(skills/tailor_resume.TAILOR_BACKEND). This script is how we CHOOSE that model:
run both models over a set of (resume, job-description) pairs, score each
tailored resume by ATS keyword coverage, and disqualify any output that
fabricates content not in the base resume. It prints a per-sample table and an
aggregate winner, so the decision is data-driven — not a guess, and NOT a
runtime cost in production.

(Claude via Vertex is NOT on this project's tier, so we compare Google's own
models: the fast/cheap Flash vs the bigger/better Pro.)

Once a winner is clear, pin it:
    TAILOR_BACKEND=vertex_pro   # or vertex (Flash) for faster/cheaper
in config/.env, and production keeps making exactly one call.

USAGE
-----
    # Use the built-in sample resume + JDs:
    python -m scripts.benchmark_tailor_models

    # Use a real user's primary resume from the DB (by their user_id):
    python -m scripts.benchmark_tailor_models --user-id <uuid>

    # Add your own JD files (one JD per file):
    python -m scripts.benchmark_tailor_models jd1.txt jd2.txt

    # Repeat each sample N times to see variance:
    python -m scripts.benchmark_tailor_models --runs 3

Everything runs against Vertex with ADC — no API keys. Claude must be enabled
in Vertex Model Garden for the project or its column shows errors (and Gemini
wins by default).
"""

import argparse
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from skills.tailor_resume import (
    build_tailor_message,
    _tailor_once,
    find_fabrications,
    keyword_coverage,
)
from skills.llm_client import MODEL_BACKEND, VERTEX_MODEL, VERTEX_PRO_MODEL


# The two candidates: Google's fast model vs the bigger reasoning model.
CANDIDATES = [
    ("flash", "vertex"),       # Gemini 2.5 Flash (fast/cheap default)
    ("pro", "vertex_pro"),     # Gemini 2.5 Pro (bigger/better)
]


SAMPLE_RESUME = {
    "name": "Sample Candidate",
    "contact": {"email": "sample@example.com", "github": "https://github.com/sample"},
    "summary": "Backend engineer focused on APIs, data pipelines, and reliability.",
    "experience": [
        {
            "company": "Acme Corp",
            "title": "Software Engineer",
            "start_date": "2022",
            "end_date": "2025",
            "bullets": [
                "Built REST APIs in Python and Node.js serving 2M requests/day",
                "Designed PostgreSQL schemas and optimized slow queries by 40%",
                "Added observability with structured logging and tracing",
            ],
        }
    ],
    "projects": [
        {
            "name": "PipelineKit",
            "tech_stack": ["Python", "Docker", "Redis"],
            "bullets": ["Open-source ETL toolkit with 300+ GitHub stars"],
        }
    ],
    "education": [{"institution": "State University", "degree": "BS Computer Science"}],
    "skills": {"Languages": ["Python", "JavaScript", "SQL"], "Tools": ["Docker", "Git", "AWS"]},
    "certifications": [],
}

SAMPLE_JDS = [
    (
        "Backend Engineer",
        "Cloudflare",
        "We need a backend engineer strong in Python, FastAPI, PostgreSQL, Redis, "
        "and Docker. You'll design REST APIs, optimize database queries, and own "
        "observability (logging, tracing, metrics) for high-throughput services.",
    ),
    (
        "Full-Stack Engineer",
        "Vercel",
        "Looking for a full-stack engineer comfortable with Node.js, TypeScript, "
        "React, and AWS. Experience building and scaling REST APIs and CI/CD "
        "pipelines is a strong plus.",
    ),
]


def _load_resume(user_id: str | None) -> dict:
    if not user_id:
        return SAMPLE_RESUME
    from db import repository as repo
    primary = repo.get_primary_resume(user_id)
    if not primary or not primary.get("parsed_json"):
        print(f"  ⚠️  no primary resume for user {user_id}; using the bundled sample.")
        return SAMPLE_RESUME
    return primary["parsed_json"]


def _load_extra_jds(paths: list[str]) -> list[tuple[str, str, str]]:
    out = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read().strip()
            if text:
                out.append((os.path.basename(p), "the company", text))
        except Exception as e:
            print(f"  ⚠️  couldn't read JD file {p}: {e}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Benchmark Gemini Flash vs Pro for resume tailoring.")
    ap.add_argument("jd_files", nargs="*", help="Optional JD text files (one JD each).")
    ap.add_argument("--user-id", default=None, help="Use this user's primary resume from the DB.")
    ap.add_argument("--runs", type=int, default=1, help="Repeat each sample N times (variance).")
    args = ap.parse_args()

    resume = _load_resume(args.user_id)
    jds = list(SAMPLE_JDS) + _load_extra_jds(args.jd_files)

    print("=" * 74)
    print("  RESUME TAILORING MODEL BENCHMARK  (Gemini Flash vs Pro, via Vertex)")
    print(f"  flash={VERTEX_MODEL}   pro={VERTEX_PRO_MODEL}")
    print("=" * 74)

    # Aggregate wins + score sums per model.
    wins = {name: 0 for name, _ in CANDIDATES}
    ties = 0
    score_sum = {name: 0.0 for name, _ in CANDIDATES}
    score_n = {name: 0 for name, _ in CANDIDATES}

    header = f"{'JD':<28}{'run':<5}" + "".join(f"{name+' ATS':<14}" for name, _ in CANDIDATES) + "winner"
    print("\n" + header)
    print("-" * len(header))

    for (role, company, jd) in jds:
        base_message = build_tailor_message(resume, company, role, jd)
        for run in range(1, args.runs + 1):
            row_scores: dict[str, float] = {}
            for name, backend in CANDIDATES:
                t0 = time.time()
                candidate, score = _tailor_once(base_message, jd, resume, backend)
                dt = time.time() - t0
                # score is -1 when the call failed or fabricated (disqualified).
                row_scores[name] = score
                if candidate is not None:
                    score_sum[name] += score
                    score_n[name] += 1
                label = f"{score:.1f}% ({dt:.0f}s)" if candidate is not None else "FAIL/fab"
                row_scores[name + "_label"] = label  # type: ignore

            # Winner: highest clean score; tie -> the default (first candidate).
            best_name = None
            best_val = -1.0
            for name, _ in CANDIDATES:
                if row_scores[name] > best_val:
                    best_val, best_name = row_scores[name], name
            # Detect a true tie between the top two clean scores.
            top_two = sorted((row_scores[n] for n, _ in CANDIDATES), reverse=True)
            if len(top_two) >= 2 and top_two[0] == top_two[1] and top_two[0] >= 0:
                ties += 1
                winner = f"tie -> {CANDIDATES[0][0]}"
            elif best_val < 0:
                winner = "none (all failed)"
            else:
                wins[best_name] += 1  # type: ignore
                winner = best_name  # type: ignore

            cells = "".join(f"{row_scores[name+'_label']:<14}" for name, _ in CANDIDATES)  # type: ignore
            print(f"{role[:26]:<28}{run:<5}{cells}{winner}")

    print("\n" + "=" * 74)
    print("  RESULTS")
    for name, _ in CANDIDATES:
        avg = (score_sum[name] / score_n[name]) if score_n[name] else 0.0
        print(f"    {name:<8} wins={wins[name]:<3} avg ATS={avg:5.1f}%  (clean runs: {score_n[name]})")
    if ties:
        print(f"    ties={ties}")

    # Recommendation.
    ranked = sorted(CANDIDATES, key=lambda c: (wins[c[0]], score_sum[c[0]]), reverse=True)
    top_name, top_backend = ranked[0]
    print("\n  RECOMMENDATION")
    print(f"    Use {top_name.upper()}. Set  TAILOR_BACKEND={top_backend}  in config/.env.")
    print("=" * 74)


if __name__ == "__main__":
    main()
