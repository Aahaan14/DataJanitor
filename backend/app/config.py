"""
DataJanitor — Application Configuration

Loads settings from environment variables (via .env file) with sensible
defaults for local development.  Uses pydantic-settings so every value is
validated at startup — a typo in .env will surface immediately.

Design decision: a single Settings object is the source of truth for all
configurable values.  Services import `get_settings()` instead of reading
os.environ directly, which makes testing easier (you can override the
dependency).
"""

from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings, populated from environment variables."""

    # ---- Application --------------------------------------------------------
    app_name: str = "DataJanitor"
    app_env: str = "development"
    debug: bool = True
    version: str = "0.1.0"

    # ---- Server -------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000

    # ---- File Upload --------------------------------------------------------
    max_upload_size_mb: int = 10
    upload_dir: str = "uploads"
    cleaned_dir: str = "cleaned"

    # ---- Database -----------------------------------------------------------
    database_url: str = "sqlite:///./datajanitor.db"

    # ---- Email (Phase 7) ----------------------------------------------------
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    report_recipient: str = ""

    # ---- CORS (Phase 8+) ----------------------------------------------------
    cors_origins: str = "http://localhost:5173"

    # ---- Derived properties --------------------------------------------------

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def upload_path(self) -> Path:
        return Path(self.upload_dir)

    @property
    def cleaned_path(self) -> Path:
        return Path(self.cleaned_dir)

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",          # ignore unknown env vars
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance (created once per process)."""
    return Settings()
