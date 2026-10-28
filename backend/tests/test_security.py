"""Phase 9 security regression tests for browser-facing API behavior."""

import pytest


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("x-content-type-options", "nosniff"),
        ("x-frame-options", "DENY"),
        ("referrer-policy", "strict-origin-when-cross-origin"),
        ("permissions-policy", "camera=(), microphone=(), geolocation=()"),
    ],
)
async def test_security_headers_are_present_on_api_responses(client, header, expected):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.headers.get(header) == expected


async def test_cors_allows_configured_frontend_origin(client):
    response = await client.options(
        "/api/datasets/upload",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


async def test_cors_does_not_reflect_untrusted_origin(client):
    response = await client.options(
        "/api/datasets/upload",
        headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.headers.get("access-control-allow-origin") != "https://attacker.example"
