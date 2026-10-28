"""
DataJanitor — approval workflow, persisted (Phase 4 logic, Phase 5 storage).

Rules enforced here (none of them applies a change to any data):
• A proposal changes state only through an explicit approve/reject call.
• Stale or superseded plans refuse every decision (409).
• Two conflicting proposals can never both be approved (409).
• A chosen/custom value must be valid for the issue type and must not break
  the plan's validation rules.
• `original_value` / `proposed_value` are never edited; the final value is
  stored as `approved_value`; every decision is a row in `decisions` and an
  entry in the audit log, committed in the same transaction as the change.
"""

from pathlib import Path
from typing import List, Optional, Set

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.exceptions import (
    ConflictingProposalError, InvalidDecisionError, PlanInactiveError,
    ProposalNotFoundError,
)
from app.database.base import utcnow
from app.models.records import DecisionRow, PlanRow, ProposalRow
from app.schemas.issues import IssueType
from app.schemas.repairs import (
    ApprovedRepair, ApprovedRepairsResponse, ApproveSafeResponse, DecisionKind,
    RepairAction, SkippedProposal,
)
from app.schemas.validation import RuleSet
from app.services import audit_service, dataset_service, plan_service, validation_service
from app.services import detection_service as ds


def refresh_status(session: Session, upload_dir: Path, plan: PlanRow) -> None:
    """Mark an active plan stale if its file changed or disappeared (audited)."""
    if plan.status != "active":
        return
    try:
        current = dataset_service.sha256_hex((upload_dir / f"{plan.dataset_id}.csv").read_bytes())
    except OSError:
        current = None
    if current != plan.fingerprint:
        plan.status = "stale"
        audit_service.log(session, "plan_marked_stale", "plan", plan.id,
                          dataset_id=plan.dataset_id, plan_id=plan.id,
                          details={"reason": "file_changed_or_missing"})
        session.commit()


def ensure_active(session: Session, upload_dir: Path, plan: PlanRow) -> None:
    refresh_status(session, upload_dir, plan)
    if plan.status == "superseded":
        raise PlanInactiveError(
            "plan_superseded",
            "A newer repair plan exists for this dataset; decisions on this one are closed.")
    if plan.status == "stale":
        raise PlanInactiveError(
            "plan_stale", "The dataset changed since this plan was created. Generate a new plan.")


def _get(session: Session, plan: PlanRow, proposal_id: str) -> ProposalRow:
    row = session.get(ProposalRow, proposal_id)
    if row is None or row.plan_id != plan.id:
        raise ProposalNotFoundError("Proposal not found in this plan.")
    return row


def _validate_custom(row: ProposalRow, value: str) -> None:
    if value == "" or value != value.strip() or any(c in value for c in "\x00\r\n"):
        raise InvalidDecisionError(
            "Value must be non-empty, without leading/trailing spaces or line breaks. "
            "To empty a cell, approve without a value.")
    if row.issue_type in (IssueType.INVALID_NUMERIC.value, IssueType.NUMERIC_FORMAT.value):
        if ds._strict_number(value) is None:
            raise InvalidDecisionError("Value must be a plain number (e.g. 1200 or 12.5).")
    elif row.issue_type in (IssueType.INVALID_DATE.value, IssueType.INCONSISTENT_DATE_FORMAT.value):
        fi = ds._classify_date(value)
        if fi is None or not ds._valid_date(value, ds.DATE_FAMILIES[fi], None):
            raise InvalidDecisionError("Value must be a valid date, e.g. 2024-03-15.")


def _resolve_value(rules: RuleSet, row: ProposalRow, chosen: Optional[str]) -> Optional[str]:
    """Final value for an approval, or InvalidDecisionError."""
    if row.action == RepairAction.DELETE_ROW.value:
        if chosen is not None:
            raise InvalidDecisionError("A row deletion does not take a value.")
        return None

    replace = row.action == RepairAction.REPLACE_VALUE.value
    if chosen is None:
        if replace and row.proposed_value is None:
            raise InvalidDecisionError(
                "This proposal has no single suggested value; send chosen_value "
                f"(one of: {row.alternatives}).")
        final = row.proposed_value if replace else None
    else:
        if not replace and not row.allow_custom_value:
            raise InvalidDecisionError("This proposal only empties the cell; it takes no value.")
        if chosen in (row.alternatives or []) or chosen == row.proposed_value:
            pass
        elif row.allow_custom_value:
            _validate_custom(row, chosen)
        else:
            raise InvalidDecisionError(
                f"chosen_value must be one of the proposed alternatives: {row.alternatives}.")
        final = chosen

    problems = validation_service.value_violations(rules, row.column_name, final)
    if problems:
        raise InvalidDecisionError(
            f"The resulting value would break the rule for '{row.column_name}': {problems[0]}.")
    return final


def _approved_ids(session: Session, plan: PlanRow, among: List[str]) -> List[str]:
    if not among:
        return []
    return list(session.scalars(select(ProposalRow.id).where(
        ProposalRow.plan_id == plan.id, ProposalRow.id.in_(among),
        ProposalRow.status == "approved")))


def _record(session: Session, plan: PlanRow, row: ProposalRow, kind: DecisionKind,
            value: Optional[str], via: str = "manual") -> None:
    now = utcnow()
    row.status = "approved" if kind == DecisionKind.APPROVE else "rejected"
    row.approved_value = value if kind == DecisionKind.APPROVE else None
    row.decided_at = now
    session.add(DecisionRow(proposal_id=row.id, decision=kind.value,
                            chosen_value=value, decided_at=now))
    audit_service.log(session, f"proposal_{row.status}", "proposal", row.id,
                      dataset_id=plan.dataset_id, plan_id=plan.id,
                      details={"action": row.action, "classification": row.classification,
                               "via": via})


def decide(session: Session, upload_dir: Path, plan: PlanRow, proposal_id: str,
           kind: DecisionKind, chosen_value: Optional[str]) -> ProposalRow:
    ensure_active(session, upload_dir, plan)
    row = _get(session, plan, proposal_id)
    if kind == DecisionKind.REJECT:
        if chosen_value is not None:
            raise InvalidDecisionError("A rejection does not take a value.")
        _record(session, plan, row, kind, None)
    else:
        final = _resolve_value(plan_service.ruleset_of(plan), row, chosen_value)
        blockers = _approved_ids(session, plan, row.conflicts_with or [])
        if blockers:
            raise ConflictingProposalError(
                "Conflicts with already-approved proposal(s) " + ", ".join(blockers)
                + ". Reject those first if you prefer this one.")
        _record(session, plan, row, kind, final)
    session.commit()
    return session.scalar(select(ProposalRow).options(selectinload(ProposalRow.decisions))
                          .where(ProposalRow.id == row.id))


def approve_all_safe(session: Session, upload_dir: Path, plan: PlanRow) -> ApproveSafeResponse:
    """Explicit bulk action: approve every pending SAFE proposal that has no conflict."""
    ensure_active(session, upload_dir, plan)
    rules = plan_service.ruleset_of(plan)
    approved: Set[str] = set(session.scalars(select(ProposalRow.id).where(
        ProposalRow.plan_id == plan.id, ProposalRow.status == "approved")))
    pending = session.scalars(select(ProposalRow).where(
        ProposalRow.plan_id == plan.id, ProposalRow.status == "pending",
        ProposalRow.classification == "safe").order_by(ProposalRow.seq)).all()
    count, skipped = 0, []
    for row in pending:
        blockers = [c for c in (row.conflicts_with or []) if c in approved]
        if blockers:
            skipped.append(SkippedProposal(proposal_id=row.id,
                                           reason="conflicts with " + ", ".join(blockers)))
            continue
        try:
            final = _resolve_value(rules, row, None)
        except InvalidDecisionError as exc:
            skipped.append(SkippedProposal(proposal_id=row.id, reason=exc.message))
            continue
        _record(session, plan, row, DecisionKind.APPROVE, final, via="approve_safe")
        approved.add(row.id)
        count += 1
    audit_service.log(session, "bulk_approve_safe", "plan", plan.id, dataset_id=plan.dataset_id,
                      plan_id=plan.id, details={"approved": count, "skipped": len(skipped)})
    session.commit()
    return ApproveSafeResponse(approved_count=count, skipped=skipped,
                               status_counts=plan_service.plan_summary(session, plan).status_counts)


def approved_repairs(session: Session, upload_dir: Path, plan: PlanRow) -> ApprovedRepairsResponse:
    """Only explicitly approved proposals — the input to Phase 6."""
    ensure_active(session, upload_dir, plan)
    rows = session.scalars(select(ProposalRow).where(
        ProposalRow.plan_id == plan.id, ProposalRow.status == "approved")
        .order_by(ProposalRow.seq)).all()
    repairs = [ApprovedRepair(
        proposal_id=r.id, action=r.action, column=r.column_name, row_number=r.row_number,
        original_value=r.original_value, approved_value=r.approved_value) for r in rows]
    return ApprovedRepairsResponse(plan_id=plan.id, dataset_id=plan.dataset_id,
                                   dataset_fingerprint=plan.fingerprint,
                                   count=len(repairs), repairs=repairs)
