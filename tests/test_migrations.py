"""Migration up/down test -- verifies Alembic's upgrade/downgrade cycle works
cleanly against a real Postgres, independent of the ORM-driven schema the
other repository tests use (tests/conftest.py creates tables straight from
db.models for speed; this test specifically exercises the Alembic migration
files themselves, since that's what actually runs in staging/prod).
"""

import os
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, inspect, text

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Must match conftest.py's default -- see that file's comment for why this
# is a dedicated "autoapply_test" database, never the real dev/prod one.
# This module is the single most destructive one in the whole test suite
# (DROP SCHEMA public CASCADE, twice per test run), so getting this default
# wrong here specifically is the highest-risk version of the mistake.
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg2://autoapply:autoapply@localhost:5432/autoapply_test"
)

EXPECTED_TABLES = {
    "companies", "jobs", "users", "resumes", "search_criteria", "leads",
    "gmail_accounts", "subscriptions", "usage_counters", "enrichment_cache",
    "research_cache", "notifications", "pipeline_runs", "alembic_version",
}


def _assert_safe_to_wipe(database_url: str) -> None:
    """Same guard as tests/conftest.py's -- this module is the most
    destructive one in the whole suite (DROP SCHEMA public CASCADE, twice
    per test run) and manages its own DB connection independent of
    conftest.py's, so it needs its own copy of this check rather than
    relying on conftest.py's import-time guard alone.
    """
    db_name = database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if "test" not in db_name.lower():
        raise RuntimeError(
            f"Refusing to run migration tests against database '{db_name}' -- "
            f"this module runs DROP SCHEMA public CASCADE. Point DATABASE_URL "
            f"at a dedicated test database (e.g. 'autoapply_test')."
        )


_assert_safe_to_wipe(DATABASE_URL)


def _run_alembic(*args):
    env = os.environ.copy()
    env["DATABASE_URL"] = DATABASE_URL
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"alembic {' '.join(args)} failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    return result


@pytest.fixture(autouse=True)
def _isolate_from_other_tests():
    """This test manages its own schema lifecycle via Alembic (not the
    create_all/drop_all fixtures in conftest.py), so drop everything first
    to start from a truly empty database regardless of test order.

    Afterward, the schema is restored to head (tables present) rather than
    left empty -- conftest.py's autouse _clean_tables fixture runs on every
    test (including in other files) and truncates by table name, which
    requires the tables to actually exist. Leaving the DB empty here would
    break the next test to run, regardless of which file it's in.
    """
    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    yield

    engine = create_engine(DATABASE_URL)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    _run_alembic("upgrade", "head")


def test_migration_upgrade_creates_all_tables():
    _run_alembic("upgrade", "head")

    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    engine.dispose()

    assert EXPECTED_TABLES.issubset(tables), f"Missing tables: {EXPECTED_TABLES - tables}"


def test_migration_downgrade_removes_all_tables():
    _run_alembic("upgrade", "head")
    _run_alembic("downgrade", "base")

    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names()) - {"alembic_version"}
    engine.dispose()

    assert tables == set(), f"Tables remained after downgrade: {tables}"


def test_migration_upgrade_is_idempotent_reentrant():
    """Upgrading twice in a row (already at head) must not error."""
    _run_alembic("upgrade", "head")
    _run_alembic("upgrade", "head")

    engine = create_engine(DATABASE_URL)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    engine.dispose()

    assert EXPECTED_TABLES.issubset(tables)
