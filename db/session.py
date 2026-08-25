"""Database engine + session management for the Postgres-backed multi-tenant store.

DATABASE_URL is read from the environment (config/.env in local/dev, Secret
Manager-injected env var in Cloud Run). Falls back to a local docker-compose
Postgres for development.

Usage:
    from db.session import get_session, SessionLocal

    with get_session() as session:
        session.add(obj)
        session.commit()
"""

import os
from contextlib import contextmanager
from typing import Generator

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "config", ".env"))

DEFAULT_LOCAL_DATABASE_URL = (
    "postgresql+psycopg2://autoapply:autoapply@localhost:5432/autoapply"
)

DATABASE_URL = os.getenv("DATABASE_URL", DEFAULT_LOCAL_DATABASE_URL)

# pool_pre_ping avoids handing out dead connections (relevant once Cloud SQL's
# Serverless VPC connector is in play and connections can be recycled server-side).
engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Context-managed session: commits on clean exit, rolls back on exception."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_engine():
    return engine
