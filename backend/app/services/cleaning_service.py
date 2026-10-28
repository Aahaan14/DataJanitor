"""
DataJanitor — generate, record and serve cleaned datasets (Phase 6).

Flow for POST /apply
  1. The plan must be active (file hash re-checked) and the original upload
     must still match its recorded hash.
  2. Only proposals with status "approved" are applied — to a copy.
  3. The result is verified against the approved edits, re-validated, and
     written atomically to the cleaned folder. The original is never opened
     for writing.
  4. Every proposal gets an outcome row: applied, skipped (with reason),
     rejected or pending. Rejected and pending proposals never touch data.
Like scans, a run is saved as `running` first, then `completed`/`failed`.
"""

import os
import tempfile
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import (
    CleanedNotFoundError, CleanedUnavailableError, DatasetError, NoApprovedRepairsError,
    OutputIntegrityError,
)
from app.database.base import utcnow
from app.models.records import CleanedRow, OutcomeRow, PlanRow, ProposalRow
from app.schemas.cleaned import CleanedSummary, FinalValidation, OutcomeEntry
from app.schemas.validation import RuleSet
from app.services import (
    audit_service, dataset_service, decision_service, detection_service, plan_service,
    repair_service, scan_service, validation_service,
)
from app.services import csv_service
from app.services.dataset_service import sha256_hex

_ID_LEN = 32


def cleaned_path(settings: Settings, cleaned_id: str) -> Path:
    """Built only from a validated 32-hex id (looked up in the database first)."""
    return settings.cleaned_path / f"{cleaned_id}.csv"


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise


def final_validation(cleaned: pd.DataFrame, rules: RuleSet,
                     before_by_type: dict) -> FinalValidation:
    issues = detection_service.run_detection(cleaned)
    summary = detection_service.summarize(issues)
    violations = validation_service.validate_dataframe(cleaned, rules)
    increased = sorted(t for t, n in summary.by_type.items() if n > before_by_type.get(t, 0))
    clean = not issues and not violations
    return FinalValidation(
        status="passed" if clean else "issues_remaining",
        remaining_issue_count=summary.total_issues,
        remaining_by_type=summary.by_type, remaining_by_severity=summary.by_severity,
        before_by_type=before_by_type, increased_issue_types=increased,
        rule_count=len(rules.rules), rule_violation_count=len(violations),
        rule_violations_sample=violations[:50],
        note="Remaining issues are detected candidates, not confirmed errors. Row numbers "
             "in this report refer to the cleaned file, which differs from the original "
             "if rows were deleted.")


def generate_cleaned(session: Session, settings: Settings, plan_id: str) -> CleanedRow:
    plan = plan_service.get_plan(session, plan_id)
    decision_service.ensure_active(session, settings.upload_path, plan)
    dataset, _, original = dataset_service.load_frame(session, settings, plan.dataset_id)

    proposals = session.scalars(select(ProposalRow).where(ProposalRow.plan_id == plan.id)
                                .order_by(ProposalRow.seq)).all()
    approved = [p for p in proposals if p.status == "approved"]
    if not approved:
        raise NoApprovedRepairsError(
            "No repairs have been approved yet. Approve at least one proposal first.")

    run = CleanedRow(id=uuid.uuid4().hex, dataset_id=plan.dataset_id, plan_id=plan.id,
                     status="running", created_at=utcnow(), rows_before=len(original))
    session.add(run)
    audit_service.log(session, "cleaned_started", "cleaned", run.id,
                      dataset_id=plan.dataset_id, plan_id=plan.id,
                      details={"approved": len(approved)})
    session.commit()

    path = cleaned_path(settings, run.id)
    try:
        raw = dataset_service.file_path(settings, dataset.id).read_bytes()
        parsed = csv_service.parse_bytes(raw, settings.max_rows, settings.max_columns)
        result = repair_service.apply_repairs(original, approved)

        problems = repair_service.find_unintended_changes(
            original, result.cleaned, result.edits, result.deleted)
        if problems:
            raise OutputIntegrityError(
                "The cleaned file did not match the approved changes, so it was not saved.")

        validation = final_validation(
            result.cleaned, plan_service.ruleset_of(plan),
            (scan_service.get_scan(session, plan.scan_id).summary or {}).get("by_type", {}))
        data = repair_service.render_csv(result.cleaned, parsed.header, parsed.delimiter)
        _write_atomic(path, data)

        applied = sum(o.outcome == "applied" for o in result.outcomes)
        outcome_by_id = {o.proposal_id: o for o in result.outcomes}
        rows: List[OutcomeRow] = []
        for p in proposals:
            if p.id in outcome_by_id:
                o = outcome_by_id[p.id]
                rows.append(OutcomeRow(cleaned_id=run.id, proposal_id=p.id,
                                       outcome=o.outcome, reason=o.reason))
            else:
                rows.append(OutcomeRow(cleaned_id=run.id, proposal_id=p.id, outcome=p.status,
                                       reason="rejected by reviewer" if p.status == "rejected"
                                       else "no decision made; left unchanged"))
        session.add_all(rows)

        run.status, run.completed_at = "completed", utcnow()
        run.sha256, run.size_bytes = sha256_hex(data), len(data)
        run.rows_after, run.rows_deleted = len(result.cleaned), len(result.deleted)
        run.cells_changed = len(result.edits)
        run.applied_count = applied
        run.skipped_count = len(result.outcomes) - applied
        run.rejected_count = sum(p.status == "rejected" for p in proposals)
        run.pending_count = sum(p.status == "pending" for p in proposals)
        run.validation = validation.model_dump(mode="json")
        audit_service.log(session, "cleaned_generated", "cleaned", run.id,
                          dataset_id=plan.dataset_id, plan_id=plan.id,
                          details={"applied": run.applied_count, "skipped": run.skipped_count,
                                   "rejected": run.rejected_count, "pending": run.pending_count,
                                   "validation": validation.status})
        session.commit()
        return run
    except Exception as exc:
        session.rollback()
        path.unlink(missing_ok=True)
        message = exc.message if isinstance(exc, DatasetError) else "Unexpected error while generating the file."
        run = session.get(CleanedRow, run.id)
        run.status, run.completed_at, run.error_message = "failed", utcnow(), message[:300]
        audit_service.log(session, "cleaned_failed", "cleaned", run.id,
                          dataset_id=plan.dataset_id, plan_id=plan.id,
                          details={"error": message[:300]})
        session.commit()
        raise


def get_cleaned(session: Session, cleaned_id: str) -> CleanedRow:
    row = session.get(CleanedRow, cleaned_id) if cleaned_id and len(cleaned_id) == _ID_LEN else None
    if row is None:
        raise CleanedNotFoundError("Cleaned dataset not found.")
    return row


def to_summary(row: CleanedRow) -> CleanedSummary:
    return CleanedSummary(
        cleaned_id=row.id, plan_id=row.plan_id, dataset_id=row.dataset_id, status=row.status,
        created_at=row.created_at, completed_at=row.completed_at, rows_before=row.rows_before,
        rows_after=row.rows_after, rows_deleted=row.rows_deleted, cells_changed=row.cells_changed,
        applied_count=row.applied_count, skipped_count=row.skipped_count,
        rejected_count=row.rejected_count, pending_count=row.pending_count,
        sha256=row.sha256, size_bytes=row.size_bytes,
        validation=FinalValidation(**row.validation) if row.validation else None,
        download_url=f"/api/cleaned/{row.id}/download" if row.status == "completed" else None,
        error_message=row.error_message)


def list_for_plan(session: Session, plan_id: str) -> List[CleanedRow]:
    return list(session.scalars(select(CleanedRow).where(CleanedRow.plan_id == plan_id)
                                .order_by(CleanedRow.created_at.desc())))


def outcome_page(session: Session, cleaned_id: str, *, outcome: Optional[str], offset: int,
                 limit: int) -> Tuple[int, List[OutcomeEntry]]:
    query = (select(OutcomeRow, ProposalRow).join(ProposalRow, ProposalRow.id == OutcomeRow.proposal_id)
             .where(OutcomeRow.cleaned_id == cleaned_id))
    if outcome:
        query = query.where(OutcomeRow.outcome == outcome)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.execute(query.order_by(OutcomeRow.id).offset(offset).limit(limit)).all()
    return total, [OutcomeEntry(proposal_id=p.id, outcome=o.outcome, reason=o.reason,
                                action=p.action, issue_type=p.issue_type, column=p.column_name,
                                row_number=p.row_number) for o, p in rows]


def read_download(session: Session, settings: Settings, cleaned_id: str,
                  mode: str) -> Tuple[CleanedRow, bytes, int]:
    """Return (record, bytes, cells_escaped). `safe` neutralises spreadsheet formulas."""
    row = get_cleaned(session, cleaned_id)
    if row.status != "completed":
        raise CleanedUnavailableError(
            "This cleaned file is not available (failed, expired or deleted).")
    try:
        data = cleaned_path(settings, row.id).read_bytes()
    except OSError as exc:
        raise CleanedUnavailableError("The cleaned file is no longer available.") from exc
    if sha256_hex(data) != row.sha256:
        raise OutputIntegrityError("The stored cleaned file no longer matches its record.")
    escaped = 0
    if mode == "safe":
        delimiter = dataset_service.get_dataset(session, row.dataset_id, active_only=False).delimiter
        data, escaped = repair_service.sanitize_for_spreadsheet(data, delimiter)
    audit_service.log(session, "cleaned_downloaded", "cleaned", row.id, dataset_id=row.dataset_id,
                      plan_id=row.plan_id, details={"mode": mode, "cells_escaped": escaped})
    session.commit()
    return row, data, escaped
