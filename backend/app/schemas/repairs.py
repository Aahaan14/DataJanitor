"""
DataJanitor — schemas for repair proposals, plans and decisions (Phase 4).

Integrity rules encoded here:
• `original_value` and `proposed_value` are separate, immutable fields.
• `approved_value` is set only by an explicit approval and may differ from
  `proposed_value` (the user can pick an alternative or type a correction).
• Rejections are kept (status + history), never deleted.
"""

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from app.schemas.issues import IssueType
from app.schemas.validation import RuleSet, ValidationSummary


class RepairAction(str, Enum):
    REPLACE_VALUE = "replace_value"
    CLEAR_VALUE = "clear_value"      # set the cell to empty
    DELETE_ROW = "delete_row"


class Classification(str, Enum):
    SAFE = "safe"            # deterministic, meaning-preserving
    AMBIGUOUS = "ambiguous"  # needs human judgement


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ProposalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class PlanStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"  # a newer plan was generated for the dataset
    STALE = "stale"            # the underlying file no longer matches


class DecisionKind(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"


class DecisionRecord(BaseModel):
    decision: DecisionKind
    decided_at: datetime
    chosen_value: Optional[str] = None


class RepairProposal(BaseModel):
    proposal_id: str
    issue_id: str
    issue_type: IssueType
    action: RepairAction
    classification: Classification
    confidence: Confidence
    column: Optional[str] = None
    row_number: Optional[int] = None
    original_value: Optional[str] = Field(
        default=None, description="Exact cell text at scan time (null = was empty)"
    )
    proposed_value: Optional[str] = Field(
        default=None,
        description="Suggested replacement. null with replace_value means the "
        "user must choose; null with clear_value means 'empty the cell'.",
    )
    alternatives: List[str] = Field(default_factory=list)
    allow_custom_value: bool = False
    reason: str
    status: ProposalStatus = ProposalStatus.PENDING
    approved_value: Optional[str] = None
    decided_at: Optional[datetime] = None
    conflicts_with: List[str] = Field(default_factory=list)
    history: List[DecisionRecord] = Field(default_factory=list)


class CreatePlanRequest(BaseModel):
    rules: Optional[RuleSet] = None


class NoProposalGroup(BaseModel):
    """Findings that deliberately get no automatic repair, grouped by reason."""
    issue_type: str
    reason: str
    count: int


class PlanSummary(BaseModel):
    plan_id: str
    dataset_id: str
    scan_id: str
    dataset_fingerprint: str
    created_at: datetime
    status: PlanStatus
    row_count: int
    column_count: int
    issue_count: int
    proposal_count: int
    safe_count: int
    ambiguous_count: int
    status_counts: Dict[str, int]
    issues_without_proposal: List[NoProposalGroup] = Field(
        description="Findings with no automatic repair and why "
        "(e.g. missing values are never invented)."
    )
    truncated: bool = False
    validation: ValidationSummary


class ProposalPage(BaseModel):
    plan_id: str
    plan_status: PlanStatus
    total: int
    offset: int
    limit: int
    proposals: List[RepairProposal]


class DecisionRequest(BaseModel):
    decision: DecisionKind
    chosen_value: Optional[str] = Field(
        default=None, max_length=1000,
        description="Only with 'approve': pick an alternative or enter a correction.",
    )


class SkippedProposal(BaseModel):
    proposal_id: str
    reason: str


class ApproveSafeResponse(BaseModel):
    approved_count: int
    skipped: List[SkippedProposal]
    status_counts: Dict[str, int]


class ApprovedRepair(BaseModel):
    """What Phase 6 will apply — only explicitly approved proposals appear."""
    proposal_id: str
    action: RepairAction
    column: Optional[str]
    row_number: Optional[int]
    original_value: Optional[str]
    approved_value: Optional[str]


class ApprovedRepairsResponse(BaseModel):
    plan_id: str
    dataset_id: str
    dataset_fingerprint: str
    count: int
    repairs: List[ApprovedRepair]


class SuggestedRulesResponse(BaseModel):
    dataset_id: str
    rules: RuleSet
