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

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg2://autoapply:autoapply@localhost:5432/autoapply"
)

from db.models import Base  # noqa: E402
from db.session import get_engine  # noqa: E402


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
