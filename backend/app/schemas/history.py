"""DataJanitor — response schemas for history, audit and statistics (Phase 5)."""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from app.schemas.issues import DetectionSummary, Issue
from app.schemas.repairs import PlanSummary
from app.schemas.reports import EmailStatus


class DatasetInfo(BaseModel):
    dataset_id: str
    filename: str
    size_bytes: int
    sha256: str
    encoding: str
    delimiter: str
    row_count: int
    column_count: int
    status: str
    uploaded_at: datetime
    file_removed_at: Optional[datetime] = None


class DatasetList(BaseModel):
    total: int
    offset: int
    limit: int
    datasets: List[DatasetInfo]


class ScanInfo(BaseModel):
    scan_id: str
    dataset_id: str
    status: str
    started_at: datetime
    completed_at: Optional[datetime] = None
    issue_total: int
    stored_issue_count: int
    truncated: bool
    summary: Optional[DetectionSummary] = None
    error_message: Optional[str] = None


class ScanList(BaseModel):
    total: int
    offset: int
    limit: int
    scans: List[ScanInfo]


class DatasetDetail(BaseModel):
    dataset: DatasetInfo
    scans: List[ScanInfo]
    plans: List[PlanSummary]


class IssuePage(BaseModel):
    scan_id: str
    total: int
    offset: int
    limit: int
    issues: List[Issue]


class AuditEntry(BaseModel):
    id: int
    timestamp: datetime
    event_type: str
    entity_type: str
    entity_id: Optional[str]
    dataset_id: Optional[str]
    plan_id: Optional[str]
    actor: str
    details: Dict[str, Any]


class AuditPage(BaseModel):
    total: int
    offset: int
    limit: int
    entries: List[AuditEntry]


class StatsResponse(BaseModel):
    datasets: Dict[str, int]          # by status
    scans: Dict[str, int]             # by status
    issues_detected: int              # across completed scans
    plans: Dict[str, int]             # by status
    proposals: Dict[str, int]         # by status
    approval_rate: Optional[float]    # approved / (approved + rejected)
    cleaned_datasets: Dict[str, int] = {}  # by status
    email_reports: Dict[str, int] = {}     # by status


class ConfigResponse(BaseModel):
    """Read-only, non-secret server settings shown on the Settings page."""
    app_name: str
    version: str
    environment: str
    max_upload_size_mb: int
    max_rows: int
    max_columns: int
    preview_rows: int
    max_issues_returned: int
    max_proposals_per_plan: int
    upload_retention_days: int
    cleaned_retention_days: int
    orphan_grace_hours: int
    report_include_names: bool
    email: EmailStatus
