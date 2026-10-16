"""
DataJanitor — Pydantic response schemas for the health endpoint.

Keeping API shapes in dedicated schema files (rather than inline dicts)
provides automatic OpenAPI documentation and runtime validation of every
response the server sends.
"""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response model for GET /health."""
    status: str
    app_name: str
    version: str
    environment: str
