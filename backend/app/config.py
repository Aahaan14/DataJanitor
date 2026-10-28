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

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application-wide settings, populated from environment variables."""

    # ---- Application --------------------------------------------------------
    app_name: str = "DataJanitor"
    app_env: str = "development"
    # Debug tracebacks can disclose internals; enable explicitly for local diagnosis.
    debug: bool = False
    version: str = "0.1.0"

    # ---- Server -------------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000

    # ---- File Upload --------------------------------------------------------
    max_upload_size_mb: int = 10
    upload_dir: str = "uploads"
    cleaned_dir: str = "cleaned"
    max_rows: int = 100_000          # reject datasets larger than this
    max_columns: int = 200           # reject datasets wider than this
    preview_rows: int = 10           # rows returned in the upload preview
    max_issues_returned: int = 5000  # cap on issue records per scan response
    max_proposals_per_plan: int = 20000  # cap on repair proposals in one plan

    # ---- Database -----------------------------------------------------------
    database_url: str = "sqlite:///./datajanitor.db"

    # ---- Retention (see README "File retention and cleanup") ----------------
    upload_retention_days: int = 30      # uploaded files are removed after this
    orphan_grace_hours: int = 24         # unrecorded files are removed after this
    cleaned_retention_days: int = 7      # cleaned CSV files are removed after this

    # ---- Email reports (Phase 7) --------------------------------------------
    # Reports are only sent when EMAIL_REPORTS_ENABLED=true AND SMTP is configured.
    # Credentials come from the environment only and are never logged or returned.
    email_reports_enabled: bool = False
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"      # starttls | ssl | none (none: localhost only)
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_timeout_seconds: int = 10
    report_recipient: str = ""           # one address, or up to 5 separated by commas
    report_include_names: bool = True    # False: omit file and column names from reports

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
