"""
DataJanitor — Health endpoint tests.

Tests verify:
1. The endpoint returns HTTP 200.
2. The response body matches the HealthResponse schema.
3. The status field is "healthy".
"""

import pytest


@pytest.mark.asyncio
async def test_health_returns_200(client):
    """GET /health should return 200 OK."""
    response = await client.get("/health")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_health_response_body(client):
    """GET /health response should contain expected fields and values."""
    response = await client.get("/health")
    data = response.json()

    assert data["status"] == "healthy"
    assert data["app_name"] == "DataJanitor"
    assert "version" in data
    assert "environment" in data


@pytest.mark.asyncio
async def test_health_response_content_type(client):
    """Health endpoint should return JSON."""
    response = await client.get("/health")
    assert response.headers["content-type"] == "application/json"
