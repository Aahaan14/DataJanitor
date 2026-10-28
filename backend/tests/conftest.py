"""
DataJanitor — Test configuration and shared fixtures.

The `client` fixture provides an HTTPX AsyncClient wired to the FastAPI app
so tests can send requests without actually starting a server process.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings, get_settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Settings that write uploads into a throw-away temp directory."""
    return Settings(
        upload_dir=str(tmp_path / "uploads"),
        cleaned_dir=str(tmp_path / "cleaned"),
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        max_upload_size_mb=1,
        max_rows=500,
        max_columns=20,
        preview_rows=5,
    )


@pytest.fixture
def app(settings):
    """Create a fresh FastAPI app (with isolated settings) for each test."""
    application = create_app(settings, init_schema_now=True)
    application.dependency_overrides[get_settings] = lambda: settings
    yield application
    application.state.engine.dispose()


@pytest.fixture
def db(app):
    """A database session for tests that inspect or seed the database directly."""
    with app.state.session_factory() as session:
        yield session


@pytest.fixture
async def client(app):
    """Async HTTP client bound to the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
