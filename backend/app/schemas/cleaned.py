"""DataJanitor — schemas for cleaned-dataset generation (Phase 6)."""

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel

from app.schemas.validation import RuleViolation


class FinalValidation(BaseModel):
    """Re-scan of the cleaned data: what is still wrong, and did anything get worse?"""
    status: str                              # "passed" | "issues_remaining"
    remaining_issue_count: int
    remaining_by_type: Dict[str, int]
    remaining_by_severity: Dict[str, int]
    before_by_type: Dict[str, int]
    increased_issue_types: List[str]         # types with MORE issues than before the repairs
    rule_count: int
    rule_violation_count: int
    rule_violations_sample: List[RuleViolation]
    note: str


class CleanedSummary(BaseModel):
    cleaned_id: str
    plan_id: str
    dataset_id: str
    status: str                              # running|completed|failed|expired|deleted
    created_at: datetime
    completed_at: Optional[datetime] = None
    rows_before: int
    rows_after: int
    rows_deleted: int
    cells_changed: int
    applied_count: int
    skipped_count: int
    rejected_count: int
    pending_count: int
    sha256: Optional[str] = None
    size_bytes: int
    validation: Optional[FinalValidation] = None
    download_url: Optional[str] = None
    error_message: Optional[str] = None


class OutcomeEntry(BaseModel):
    proposal_id: str
    outcome: str                             # applied|skipped|rejected|pending
    reason: Optional[str]
    action: str
    issue_type: str
    column: Optional[str]
    row_number: Optional[int]


class OutcomePage(BaseModel):
    cleaned_id: str
    total: int
    offset: int
    limit: int
    outcomes: List[OutcomeEntry]
