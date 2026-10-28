"""
DataJanitor — database foundation: engine, sessions, base class, UTC timestamps.

Design decisions
────────────────
• SQLAlchemy 2.0 ORM with SQLite; the URL comes from settings so another
  database can be used later without code changes.
• Foreign keys are enforced (SQLite has them off by default).
• Timestamps are stored as naive UTC and always returned timezone-aware, so
  the API never mixes local and UTC times.
• Sessions are request-scoped (see `get_db`) and committed explicitly by the
  service that owns the unit of work.
"""

from datetime import datetime, timezone
from typing import Iterator

from fastapi import Request
from sqlalchemy import DateTime, create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """Declarative base for every ORM model."""


class UTCDateTime(TypeDecorator):
    """Store UTC without tzinfo; return timezone-aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use UTC-aware values.")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_engine(database_url: str) -> Engine:
    is_sqlite = database_url.startswith("sqlite")
    engine = create_engine(
        database_url,
        # FastAPI runs sync code in worker threads; each request gets its own session.
        connect_args={"check_same_thread": False} if is_sqlite else {},
    )
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    return engine


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, rolled back on error."""
    session = request.app.state.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
