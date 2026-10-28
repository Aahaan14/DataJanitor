"""
DataJanitor — report content and email-record schemas (Phase 7).

PRIVACY BY CONSTRUCTION: nothing in `ReportContent` can hold a cell value.
It carries counts, ids, statuses and (optionally) file/column names only.
"""

from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class DatasetPart(BaseModel):
    dataset_id: str
    filename: Optional[str]            # None when REPORT_INCLUDE_NAMES=false
    rows: int
    columns: int
    size_bytes: int
    uploaded_at: datetime


class ScanPart(BaseModel):
    scan_id: str
    started_at: datetime
    completed_at: Optional[datetime]
    issue_total: int
    affected_rows: int
    truncated: bool
    by_severity: Dict[str, int]
    by_type: Dict[str, int]
    by_column: Optional[Dict[str, int]]   # None when names are excluded


class ReviewPart(BaseModel):
    plan_id: str
    proposals_total: int
    approved: int
    rejected: int
    pending: int
    approved_by_type: Dict[str, int]
    rejected_by_type: Dict[str, int]


class CleaningPart(BaseModel):
    cleaned_id: str
    rows_before: int
    rows_after: int
    rows_deleted: int
    cells_changed: int
    applied: int
    skipped: int
    rejected: int
    pending: int


class ValidationPart(BaseModel):
    status: str
    remaining_issue_count: int
    remaining_by_type: Dict[str, int]
    increased_issue_types: List[str]
    rule_count: int
    rule_violation_count: int


class ReportContent(BaseModel):
    kind: Literal["scan", "cleaning"]
    generated_at: datetime
    dataset: DatasetPart
    scan: ScanPart
    review: Optional[ReviewPart] = None
    cleaning: Optional[CleaningPart] = None
    final_validation: Optional[ValidationPart] = None
    notes: List[str]


class ReportPreview(BaseModel):
    """Exactly what would be emailed (plain-text version)."""
    subject: str
    text: str
    content: ReportContent


class EmailStatus(BaseModel):
    enabled: bool
    configured: bool
    problem: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_security: Optional[str] = None
    recipient_masked: Optional[str] = None
    include_names: bool


class EmailReportInfo(BaseModel):
    report_id: str
    kind: str
    trigger: str
    dataset_id: str
    scan_id: Optional[str]
    plan_id: Optional[str]
    cleaned_id: Optional[str]
    recipient_masked: str
    subject: str
    status: str
    attempts: int
    error_message: Optional[str]
    created_at: datetime
    last_attempt_at: Optional[datetime]
    sent_at: Optional[datetime]


class EmailReportList(BaseModel):
    total: int
    offset: int
    limit: int
    reports: List[EmailReportInfo]
