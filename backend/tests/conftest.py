"""
DataJanitor — Test configuration and shared fixtures.

The `client` fixture provides an HTTPX AsyncClient wired to the FastAPI app
so tests can send requests without actually starting a server process.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest.fixture
def app():
    """Create a fresh FastAPI app for each test."""
    return create_app()


@pytest.fixture
async def client(app):
    """Async HTTP client bound to the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
