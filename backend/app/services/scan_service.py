"""
DataJanitor — scans: run detection, persist the outcome, expose history.

Lifecycle: a scan row is created as `running` and committed BEFORE any work
starts, then becomes `completed` (with its issues and summary) or `failed`
(with a short, safe error message). So history always shows what was
attempted, even if the process dies mid-scan.
"""

import uuid
from dataclasses import dataclass
from typing import List, Optional, Tuple

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import DatasetError, DatasetNotFoundError
from app.database.base import utcnow
from app.models.records import IssueRow, ScanRow
from app.schemas.history import ScanInfo
from app.schemas.issues import DetectionSummary, Issue
from app.services import audit_service, dataset_service, detection_service


@dataclass
class ScanOutcome:
    scan: ScanRow
    raw: bytes
    df: pd.DataFrame
    issues: List[Issue]


def perform_scan(session: Session, settings: Settings, dataset_id: str) -> ScanOutcome:
    dataset = dataset_service.get_dataset(session, dataset_id)  # 404/410 before any scan row
    scan = ScanRow(id=uuid.uuid4().hex, dataset_id=dataset.id, status="running",
                   started_at=utcnow())
    session.add(scan)
    audit_service.log(session, "scan_started", "scan", scan.id, dataset_id=dataset.id)
    session.commit()

    try:
        _, raw, df = dataset_service.load_frame(session, settings, dataset_id)
        issues = detection_service.run_detection(df)
        stored = issues[: settings.max_issues_returned]
        session.add_all(IssueRow(
            scan_id=scan.id, issue_id=i.issue_id, issue_type=i.issue_type.value,
            severity=i.severity.value, column_name=i.column, row_number=i.row_number,
            observed_value=i.observed_value, explanation=i.explanation,
            suggested_action=i.suggested_action, details=i.details) for i in stored)
        scan.status, scan.completed_at = "completed", utcnow()
        scan.issue_total, scan.stored_issue_count = len(issues), len(stored)
        scan.truncated = len(issues) > len(stored)
        scan.summary = detection_service.summarize(issues).model_dump(mode="json")
        audit_service.log(session, "scan_completed", "scan", scan.id, dataset_id=dataset.id,
                          details={"issues": len(issues), "truncated": scan.truncated})
        session.commit()
        return ScanOutcome(scan, raw, df, issues)
    except Exception as exc:
        session.rollback()
        message = exc.message if isinstance(exc, DatasetError) else "Unexpected error during scan."
        scan = session.get(ScanRow, scan.id)
        scan.status, scan.completed_at = "failed", utcnow()
        scan.error_message = message[:300]
        audit_service.log(session, "scan_failed", "scan", scan.id, dataset_id=dataset.id,
                          details={"error": message[:300]})
        session.commit()
        raise


def get_scan(session: Session, scan_id: str) -> ScanRow:
    row = session.get(ScanRow, scan_id) if scan_id and len(scan_id) == 32 else None
    if row is None:
        raise DatasetNotFoundError("Scan not found.")
    return row


def to_info(row: ScanRow) -> ScanInfo:
    return ScanInfo(
        scan_id=row.id, dataset_id=row.dataset_id, status=row.status,
        started_at=row.started_at, completed_at=row.completed_at,
        issue_total=row.issue_total, stored_issue_count=row.stored_issue_count,
        truncated=row.truncated,
        summary=DetectionSummary(**row.summary) if row.summary else None,
        error_message=row.error_message)


def issue_to_schema(r: IssueRow) -> Issue:
    return Issue(issue_id=r.issue_id, issue_type=r.issue_type, severity=r.severity,
                 column=r.column_name, row_number=r.row_number, observed_value=r.observed_value,
                 explanation=r.explanation, suggested_action=r.suggested_action,
                 details=r.details or {})


def list_scans(session: Session, *, dataset_id: Optional[str], status: Optional[str],
               offset: int, limit: int) -> Tuple[int, List[ScanRow]]:
    query = select(ScanRow)
    if dataset_id:
        query = query.where(ScanRow.dataset_id == dataset_id)
    if status:
        query = query.where(ScanRow.status == status)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(ScanRow.started_at.desc())
                           .offset(offset).limit(limit)).all()
    return total, list(rows)


def list_issues(session: Session, scan_id: str, *, issue_type: Optional[str],
                severity: Optional[str], offset: int, limit: int) -> Tuple[int, List[IssueRow]]:
    query = select(IssueRow).where(IssueRow.scan_id == scan_id)
    if issue_type:
        query = query.where(IssueRow.issue_type == issue_type)
    if severity:
        query = query.where(IssueRow.severity == severity)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(IssueRow.id).offset(offset).limit(limit)).all()
    return total, list(rows)
