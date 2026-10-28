"""
DataJanitor — database schema initialisation.

Approach (documented choice): a small project with one SQLite file does not
need Alembic yet, so the schema is created with `Base.metadata.create_all`
(safe to run repeatedly — it only creates missing tables) and a
`schema_version` row guards against running new code on an old database.

Run it manually:   python -m app.database.init_db
The app also runs it at startup.

When the schema changes in a future version: bump SCHEMA_VERSION, add a
migration note to the README, and (if data must be kept) adopt Alembic —
the models are already SQLAlchemy 2.0 declarative, which Alembic autogenerates
from.
"""

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.database.base import Base, make_engine
from app.models.records import SchemaInfoRow

SCHEMA_VERSION = 1


class SchemaVersionError(RuntimeError):
    pass


def init_schema(engine: Engine) -> int:
    """Create missing tables and verify the schema version. Returns the version."""
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        row = session.scalar(select(SchemaInfoRow).where(SchemaInfoRow.key == "schema_version"))
        if row is None:
            session.add(SchemaInfoRow(key="schema_version", value=str(SCHEMA_VERSION)))
            session.commit()
            return SCHEMA_VERSION
        if int(row.value) != SCHEMA_VERSION:
            raise SchemaVersionError(
                f"Database schema is version {row.value}, but this code expects "
                f"{SCHEMA_VERSION}. See the README section 'Database migrations'."
            )
        return SCHEMA_VERSION


if __name__ == "__main__":
    from app.config import get_settings

    settings = get_settings()
    version = init_schema(make_engine(settings.database_url))
    print(f"Database ready (schema version {version}) at {settings.database_url}")
