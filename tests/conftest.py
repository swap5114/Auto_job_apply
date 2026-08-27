"""Shared pytest fixtures for the db-backed test suite.

Tests run against a real Postgres instance (the docker-compose `db` service
by default). DATABASE_URL can be overridden to point at any other Postgres,
e.g. the ephemeral instance Cloud Build CI will spin up per Phase 0's plan.

Each test gets a clean schema: we run Alembic's migrations up to head before
the test session, and every test wraps its work in a savepoint-like pattern by
truncating all tables between tests. This keeps tests independent without the
overhead of a full drop/recreate per test.
"""

import os
import sys

import pytest
from sqlalchemy import text

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# IMPORTANT: this must be a DIFFERENT database than the one dev/prod actually
# uses (db/session.py's DEFAULT_LOCAL_DATABASE_URL) -- this fixture file
# drops the entire schema on session teardown (see _apply_schema below), and
# test_migrations.py drops the whole public SCHEMA outright. Pointing tests
# at the same "autoapply" database real dev work uses turns every local test
# run into a live risk of wiping real data (this happened once already:
# running the full suite against the shared dev DB silently dropped every
# app table). "autoapply_test" is a separate database inside the same local
# Postgres instance/container (not a second container -- `CREATE DATABASE
# autoapply_test;` against the existing docker-compose `db` service), so
# tests get a real, disposable Postgres without needing extra infra.
#
# DATABASE_URL can still be overridden externally (e.g. CI's ephemeral
# Postgres, per Phase 0's plan) -- this default only applies when nothing
# else set it.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg2://autoapply:autoapply@localhost:5432/autoapply_test"
)

from db.models import Base  # noqa: E402
from db.session import get_engine, DATABASE_URL  # noqa: E402


def _assert_safe_to_wipe(database_url: str) -> None:
    """Last-resort guard against ever running this suite's destructive
    fixtures (drop_all, TRUNCATE ... CASCADE, and test_migrations.py's
    DROP SCHEMA) against a database that isn't clearly a disposable test
    database -- e.g. a real dev/staging/prod DATABASE_URL set by mistake in
    the environment or a CI misconfiguration. This is deliberately a crude,
    name-based check (the DB name must contain "test"), not a foolproof
    one -- it exists purely to fail loudly instead of silently wiping real
    data a second time (this already happened once with the dev DB).
    """
    db_name = database_url.rsplit("/", 1)[-1].split("?", 1)[0]
    if "test" not in db_name.lower():
        raise RuntimeError(
            f"Refusing to run the test suite against database '{db_name}' -- "
            f"this database name doesn't contain 'test', and this suite drops/"
            f"truncates tables destructively. Point DATABASE_URL at a "
            f"dedicated test database (e.g. 'autoapply_test') before running "
            f"tests. See tests/conftest.py's module docstring."
        )


_assert_safe_to_wipe(DATABASE_URL)


@pytest.fixture(scope="session", autouse=True)
def _apply_schema():
    """Create all tables once for the test session (equivalent to `alembic
    upgrade head` but driven straight from the models, so the test suite
    doesn't depend on migration file naming/state).
    """
    engine = get_engine()
    Base.metadata.create_all(engine)
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate every table before each test so tests don't leak state."""
    engine = get_engine()
    with engine.begin() as conn:
        table_names = [t.name for t in Base.metadata.sorted_tables]
        if table_names:
            quoted = ", ".join(f'"{name}"' for name in table_names)
            conn.execute(text(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE"))
    yield
