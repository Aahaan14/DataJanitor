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

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.database.base import make_engine, make_session_factory
from app.database.init_db import init_schema
from app.api.routes.cleaned import router as cleaned_router
from app.api.routes.health import router as health_router
from app.api.routes.history import router as history_router
from app.api.routes.reports import router as reports_router
from app.api.routes.repairs import router as repairs_router
from app.api.routes.scan import router as scan_router
from app.api.routes.upload import router as upload_router
from app.core.exceptions import DatasetError


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup / shutdown lifecycle hook.

    On startup: create the upload and cleaned-file directories if they
    don't already exist. This avoids "directory not found" errors the
    first time a user uploads a file.
    """
    settings: Settings = app.state.settings
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    Path(settings.cleaned_dir).mkdir(parents=True, exist_ok=True)
    init_schema(app.state.engine)  # create missing tables, verify schema version
    yield
    app.state.engine.dispose()


def create_app(settings: Settings | None = None, *, init_schema_now: bool = False) -> FastAPI:
    """
    Build and return a configured FastAPI application.

    `settings` lets tests supply an isolated configuration (own database and
    folders). `init_schema_now` creates the tables immediately — tests need
    this because HTTPX's ASGI transport does not run the lifespan hook.
    """
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.app_name,
        description=(
            "Automatic dataset quality analysis and repair assistant. "
            "Upload a CSV, detect issues, review proposed fixes, and "
            "download a cleaned dataset."
        ),
        version=settings.version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    # ── Register routers ────────────────────────────────────────────────
    # CORS: only the configured frontend origins (CORS_ORIGINS), only the methods
    # and headers the API uses. In development the Vite proxy makes this moot.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
        expose_headers=["Content-Disposition", "X-DataJanitor-Mode", "X-DataJanitor-Cells-Escaped"],
        max_age=600,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        """Set browser hardening headers on API and error responses alike."""
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    app.include_router(health_router)
    app.include_router(upload_router)
    app.include_router(scan_router)
    app.include_router(repairs_router)
    app.include_router(cleaned_router)
    app.include_router(reports_router)
    app.include_router(history_router)

    # ── Database ────────────────────────────────────────────────────────
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.session_factory = make_session_factory(app.state.engine)
    if init_schema_now:
        init_schema(app.state.engine)

    # ── Error handling ──────────────────────────────────────────────────
    @app.exception_handler(DatasetError)
    async def dataset_error_handler(_: Request, exc: DatasetError) -> JSONResponse:
        """Turn domain errors into the standard {"error": {...}} body."""
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": exc.code, "message": exc.message}},
        )

    return app


# Uvicorn needs a module-level `app` object.
app = create_app()
