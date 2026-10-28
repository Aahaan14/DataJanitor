"""
DataJanitor — repair plans in the database (replaces the Phase 4 in-memory store).

Creating a plan = one scan (recorded in scan history) + validation +
proposal generation, all saved in a single transaction together with the
audit entries. Reading uses SQL filters/paging, so large plans stay cheap.
"""

import re
import uuid
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.config import Settings
from app.core.exceptions import PlanNotFoundError
from app.database.base import utcnow
from app.models.records import PlanRow, ProposalRow, RuleRow
from app.schemas.repairs import (
    DecisionKind, DecisionRecord, NoProposalGroup, PlanSummary, ProposalPage,
    RepairProposal,
)
from app.schemas.validation import ColumnRule, RuleSet, ValidationSummary
from app.services import (
    audit_service, recommendation_service, scan_service, validation_service,
)

_PLAN_ID = re.compile(r"^[0-9a-f]{32}$")


def get_plan(session: Session, plan_id: str) -> PlanRow:
    row = session.get(PlanRow, plan_id) if _PLAN_ID.fullmatch(plan_id or "") else None
    if row is None:
        raise PlanNotFoundError("Repair plan not found.")
    return row


def ruleset_of(plan: PlanRow) -> RuleSet:
    return RuleSet(rules=[ColumnRule(**r.definition) for r in plan.rules])


def create_plan(session: Session, settings: Settings, dataset_id: str,
                rules: RuleSet) -> PlanSummary:
    outcome = scan_service.perform_scan(session, settings, dataset_id)
    violations = validation_service.validate_dataframe(outcome.df, rules)
    proposals, no_proposal, truncated = recommendation_service.build_proposals(
        outcome.df, outcome.issues, violations, settings.max_proposals_per_plan)

    plan_id = uuid.uuid4().hex
    # Any older active plan for this dataset can no longer be acted on.
    for old in session.scalars(select(PlanRow).where(
            PlanRow.dataset_id == dataset_id, PlanRow.status == "active")):
        old.status = "superseded"
        audit_service.log(session, "plan_superseded", "plan", old.id, dataset_id=dataset_id,
                          plan_id=old.id, details={"superseded_by": plan_id})

    plan = PlanRow(
        id=plan_id, dataset_id=dataset_id, scan_id=outcome.scan.id,
        fingerprint=outcome.scan.dataset.sha256, status="active", created_at=utcnow(),
        row_count=len(outcome.df), column_count=outcome.df.shape[1],
        issue_count=len(outcome.issues) + len(violations), truncated=truncated,
        no_proposal=[g.model_dump() for g in no_proposal],
        validation=validation_service.summarize_violations(
            violations, len(rules.rules)).model_dump(mode="json"),
    )
    session.add(plan)
    session.add_all(RuleRow(plan_id=plan_id, column_name=r.column,
                            definition=r.model_dump(mode="json")) for r in rules.rules)
    session.add_all(ProposalRow(
        id=p.proposal_id, plan_id=plan_id, seq=n, issue_id=p.issue_id,
        issue_type=p.issue_type.value, action=p.action.value,
        classification=p.classification.value, confidence=p.confidence.value,
        column_name=p.column, row_number=p.row_number, original_value=p.original_value,
        proposed_value=p.proposed_value, alternatives=p.alternatives,
        allow_custom_value=p.allow_custom_value, reason=p.reason,
        conflicts_with=p.conflicts_with, status="pending") for n, p in enumerate(proposals))
    audit_service.log(session, "plan_created", "plan", plan_id, dataset_id=dataset_id,
                      plan_id=plan_id, details={"scan_id": outcome.scan.id,
                                                "proposals": len(proposals),
                                                "rules": len(rules.rules)})
    session.commit()
    return plan_summary(session, plan)


def plan_summary(session: Session, plan: PlanRow) -> PlanSummary:
    counts = session.execute(
        select(ProposalRow.status, ProposalRow.classification, func.count())
        .where(ProposalRow.plan_id == plan.id)
        .group_by(ProposalRow.status, ProposalRow.classification)).all()
    status_counts: Dict[str, int] = {"pending": 0, "approved": 0, "rejected": 0}
    safe = ambiguous = 0
    for status, classification, n in counts:
        status_counts[status] += n
        if classification == "safe":
            safe += n
        else:
            ambiguous += n
    return PlanSummary(
        plan_id=plan.id, dataset_id=plan.dataset_id, scan_id=plan.scan_id,
        dataset_fingerprint=plan.fingerprint,
        created_at=plan.created_at, status=plan.status, row_count=plan.row_count,
        column_count=plan.column_count, issue_count=plan.issue_count,
        proposal_count=safe + ambiguous, safe_count=safe, ambiguous_count=ambiguous,
        status_counts=status_counts,
        issues_without_proposal=[NoProposalGroup(**g) for g in plan.no_proposal],
        truncated=plan.truncated, validation=ValidationSummary(**plan.validation))


def to_schema(row: ProposalRow) -> RepairProposal:
    return RepairProposal(
        proposal_id=row.id, issue_id=row.issue_id, issue_type=row.issue_type,
        action=row.action, classification=row.classification, confidence=row.confidence,
        column=row.column_name, row_number=row.row_number,
        original_value=row.original_value, proposed_value=row.proposed_value,
        alternatives=row.alternatives or [], allow_custom_value=row.allow_custom_value,
        reason=row.reason, status=row.status, approved_value=row.approved_value,
        decided_at=row.decided_at, conflicts_with=row.conflicts_with or [],
        history=[DecisionRecord(decision=DecisionKind(d.decision), decided_at=d.decided_at,
                                chosen_value=d.chosen_value) for d in row.decisions])


def proposal_page(session: Session, plan: PlanRow, *, offset: int, limit: int,
                  status: Optional[str] = None, classification: Optional[str] = None,
                  issue_type: Optional[str] = None, column: Optional[str] = None) -> ProposalPage:
    query = select(ProposalRow).where(ProposalRow.plan_id == plan.id)
    if status:
        query = query.where(ProposalRow.status == status)
    if classification:
        query = query.where(ProposalRow.classification == classification)
    if issue_type:
        query = query.where(ProposalRow.issue_type == issue_type)
    if column:
        query = query.where(ProposalRow.column_name == column)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.options(selectinload(ProposalRow.decisions))
                           .order_by(ProposalRow.seq).offset(offset).limit(limit)).all()
    return ProposalPage(plan_id=plan.id, plan_status=plan.status, total=total,
                        offset=offset, limit=limit, proposals=[to_schema(r) for r in rows])


def list_plans(session: Session, dataset_id: str, limit: int = 20) -> List[PlanRow]:
    return list(session.scalars(select(PlanRow).where(PlanRow.dataset_id == dataset_id)
                                .order_by(PlanRow.created_at.desc()).limit(limit)))
