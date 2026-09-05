"""Database catalog seeder — bulk populates the shared companies/jobs database tables.

Syncs real, verified hiring companies from YC Startups into PostgreSQL so match_jobs.py
and search feeds have a rich 500-1000+ YC company database to match user resumes against.

Usage:
    python -m db.seed_catalog [--target 500]
"""

import argparse
import sys
import os

sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from db import repository as repo
from skills.scrape_job_boards.yc_startups import run_catalog as sync_yc


def seed_catalog(target_count: int = 500) -> dict:
    """Populate database catalog with target number of hiring YC companies."""
    print("=" * 60)
    print(f"  YC CATALOG SEEDER (Target: minimum {target_count} YC hiring startups)")
    print("=" * 60)

    # Sync YC Startups Catalog
    print("\n[1/1] Syncing YC Startups...")
    try:
        yc_res = sync_yc(max_companies=target_count)
        print(f"  ✅ YC sync: {yc_res.get('added', 0)} added, {yc_res.get('skipped', 0)} skipped")
    except Exception as e:
        print(f"  ❌ YC sync failed: {e}")

    companies = repo.get_companies()
    jobs = repo.get_jobs(open_only=True)
    summary = {
        "total_companies": len(companies),
        "total_open_jobs": len(jobs),
    }

    print("\n" + "=" * 60)
    print(f"  CATALOG SEEDING COMPLETE")
    print(f"  Total Companies in DB: {summary['total_companies']}")
    print(f"  Total Open Jobs in DB: {summary['total_open_jobs']}")
    print("=" * 60)

    return summary


def main():
    parser = argparse.ArgumentParser(description="Seed shared job/company catalog")
    parser.add_argument("--target", type=int, default=500, help="Target minimum companies count (default: 500)")
    args = parser.parse_args()

    seed_catalog(target_count=args.target)


if __name__ == "__main__":
    main()
