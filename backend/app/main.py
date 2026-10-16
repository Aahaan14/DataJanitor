"""
DataJanitor — FastAPI Application Entry Point

Creates and configures the FastAPI application instance.

Design decisions
────────────────
• The `create_app()` factory pattern lets tests create isolated app instances
  with overridden settings without polluting the global state.
• Routers are included inside the factory so each call gets a fresh wiring.
• Startup events ensure required directories (uploads/, cleaned/) exist.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from app.config import get_settings
from app.api.routes.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup / shutdown lifecycle hook.

    On startup: create the upload and cleaned-file directories if they
    don't already exist. This avoids "directory not found" errors the
    first time a user uploads a file.
    """
    settings = get_settings()
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.cleaned_dir).mkdir(parents=True, exist_ok=True)
    yield
    # Shutdown: nothing to clean up yet.


def create_app() -> FastAPI:
    """Build and return a configured FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "Automatic dataset quality analysis and repair assistant. "
            "Upload a CSV, detect issues, review proposed fixes, and "
            "download a cleaned dataset."
        ),
        version=settings.version,
        lifespan=lifespan,
    )

    # ── Register routers ────────────────────────────────────────────────
    app.include_router(health_router)
    # Future phases will add: upload_router, scan_router, repair_router, …

    return app


# Uvicorn needs a module-level `app` object.
app = create_app()
