"""
DataJanitor — schemas for detected data-quality issues and scan results.

An `Issue` is a *detected candidate*, never a confirmed error. The fixed
`status="detected"` field makes that distinction explicit in every record
(Phase 4/5 add proposal and decision states elsewhere).
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class IssueType(str, Enum):
    MISSING_VALUE = "missing_value"
    PLACEHOLDER_MISSING = "placeholder_missing"
    EXACT_DUPLICATE = "exact_duplicate"
    POTENTIAL_DUPLICATE = "potential_duplicate"
    WHITESPACE = "whitespace"
    INCONSISTENT_TEXT_FORMAT = "inconsistent_text_format"
    INVALID_DATE = "invalid_date"
    INCONSISTENT_DATE_FORMAT = "inconsistent_date_format"
    AMBIGUOUS_DATE_FORMAT = "ambiguous_date_format"
    INVALID_NUMERIC = "invalid_numeric"
    NUMERIC_FORMAT = "numeric_format"
    SUSPICIOUS_OUTLIER = "suspicious_outlier"
    RULE_VIOLATION = "rule_violation"  # from user-configured validation rules (Phase 4)


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Issue(BaseModel):
    """One standardized data-quality finding."""

    issue_id: str = Field(default="", description="Unique within a scan, e.g. I00042")
    issue_type: IssueType
    severity: Severity
    column: Optional[str] = Field(default=None, description="null for row-level issues")
    row_number: Optional[int] = Field(
        default=None,
        description="Stable 1-based data-row index (same numbering as the upload "
        "preview). null for column-level issues.",
    )
    observed_value: Optional[str] = None
    explanation: str
    suggested_action: str
    status: Literal["detected"] = "detected"
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Machine-readable extras used by the repair engine "
        "(e.g. proposed_value, canonical_candidate, ambiguous).",
    )


class DetectionSummary(BaseModel):
    total_issues: int
    affected_row_count: int
    by_type: Dict[str, int]
    by_severity: Dict[str, int]
    by_column: Dict[str, int]


class ScanResponse(BaseModel):
    scan_id: str
    status: str
    dataset_id: str
    scanned_at: datetime
    row_count: int
    column_count: int
    summary: DetectionSummary
    issues_returned: int
    truncated: bool = Field(
        description="True when more issues were found than the response limit; "
        "the summary always counts all of them."
    )
    disclaimer: str
    issues: List[Issue]
