"""Debug script: run the full generate -> sandbox build -> deploy pipeline."""
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))
os.environ["PYTHONIOENCODING"] = "utf-8"

# Force UTF-8 for emoji prints
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(encoding="utf-8")
    except Exception:
        pass

from skills.build_demo import (
    generate_demo_app, build_in_sandbox, deploy_to_vercel,
    _sanitize_project_name, get_config
)

demo_project = {
    "title": "High-Velocity Memecoin Order Flow Simulator",
    "description": "A real-time dashboard that simulates high-frequency memecoin order book updates.",
    "tech_stack": ["React", "Tailwind CSS"],
    "deliverable": "Live web app link",
}
lead = {"company": "Axiom", "role": "Frontend Engineer", "jd_text": "high-performance trading UI"}

print("=== STEP 1: Generate ===")
try:
    files = generate_demo_app(demo_project, lead)
    print(f"Generated {len(files)} files: {sorted(files.keys())}")
except Exception as e:
    print(f"GENERATION FAILED: {e}")
    sys.exit(1)

print("\n=== STEP 2: Sandbox Build ===")
result = build_in_sandbox(files)
print(f"ok={result['ok']}")
print(f"logs (last 2000 chars):\n{result['logs'][-2000:]}")

if not result["ok"]:
    print("\nBUILD FAILED - stopping here")
    sys.exit(1)

print("\n=== STEP 3: Deploy ===")
cfg = get_config()
project_name = _sanitize_project_name(cfg.project_prefix, "Axiom")
try:
    url = deploy_to_vercel(files, project_name)
    print(f"\nDEPLOYED: {url}")
except Exception as e:
    print(f"\nDEPLOY FAILED: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
