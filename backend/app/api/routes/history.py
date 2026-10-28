"""
DataJanitor — history, audit and statistics routes (Phase 5).

  GET    /api/datasets                  uploaded datasets (paged)
  GET    /api/datasets/{id}             one dataset + its scans and plans
  GET    /api/datasets/{id}/profile     column profile + a page of rows (re-read from the original)
  GET    /api/config                    server limits and retention (read-only, no secrets)
  DELETE /api/datasets/{id}             remove the file; history is kept
  GET    /api/scans                     scan history (filter by dataset/status)
  GET    /api/scans/{scan_id}           one scan summary
  GET    /api/scans/{scan_id}/issues    stored issues (filter, paged)
  GET    /api/audit-logs                append-only audit trail, newest first
  GET    /api/stats                     dashboard metrics

All read-only except DELETE, which never touches scan/decision/audit history.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.base import get_db
from app.models.records import (
    AuditRow, CleanedRow, DatasetRow, EmailReportRow, PlanRow, ProposalRow, ScanRow,
)
from app.schemas.dataset import DatasetProfile, ErrorResponse
from app.schemas.history import (
    AuditEntry, AuditPage, ConfigResponse, DatasetDetail, DatasetInfo, DatasetList, IssuePage, ScanInfo,
    ScanList, StatsResponse,
)
from app.services import (
    dataset_service, email_service, plan_service, profiling_service, scan_service,
)

router = APIRouter(tags=["History"])

_NOT_FOUND = {404: {"model": ErrorResponse}}


@router.get("/api/datasets", response_model=DatasetList, summary="List uploaded datasets")
def list_datasets(status: Optional[str] = Query(None, pattern="^(active|deleted|expired)$"),
                  offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                  db: Session = Depends(get_db)) -> DatasetList:
    total, rows = dataset_service.list_datasets(db, status=status, offset=offset, limit=limit)
    return DatasetList(total=total, offset=offset, limit=limit,
                       datasets=[dataset_service.to_info(r) for r in rows])


@router.get("/api/datasets/{dataset_id}", response_model=DatasetDetail, responses=_NOT_FOUND,
            summary="One dataset with its scan and repair-plan history")
def get_dataset(dataset_id: str, settings: Settings = Depends(get_settings),
                db: Session = Depends(get_db)) -> DatasetDetail:
    from app.services import decision_service  # refresh staleness before reporting

    row = dataset_service.get_dataset(db, dataset_id, active_only=False)
    plans = plan_service.list_plans(db, row.id)
    for plan in plans:
        decision_service.refresh_status(db, settings.upload_path, plan)
    return DatasetDetail(
        dataset=dataset_service.to_info(row),
        scans=[scan_service.to_info(s) for s in row.scans[:20]],
        plans=[plan_service.plan_summary(db, p) for p in plans])


@router.get("/api/datasets/{dataset_id}/profile", response_model=DatasetProfile,
            responses={**_NOT_FOUND, 410: {"model": ErrorResponse}},
            summary="Column profile and a page of rows for a stored dataset")
def dataset_profile(dataset_id: str, offset: int = Query(0, ge=0),
                    limit: int = Query(10, ge=1, le=100),
                    settings: Settings = Depends(get_settings),
                    db: Session = Depends(get_db)) -> DatasetProfile:
    row, _, df = dataset_service.load_frame(db, settings, dataset_id)
    parsed_warnings = []
    if row.encoding not in ("utf-8", "utf-8-sig"):
        parsed_warnings.append(f"File is not UTF-8; it was decoded as {row.encoding}.")
    return DatasetProfile(
        dataset_id=row.id, filename=row.original_filename, row_count=len(df),
        column_count=df.shape[1], encoding=row.encoding, delimiter=row.delimiter,
        columns=profiling_service.profile_dataframe(df),
        preview=profiling_service.build_preview(df, limit, offset),
        preview_offset=offset, preview_limit=limit, warnings=parsed_warnings)


@router.delete("/api/datasets/{dataset_id}", status_code=204, responses=_NOT_FOUND,
               summary="Delete the stored file (history and audit trail are kept)")
def delete_dataset(dataset_id: str, settings: Settings = Depends(get_settings),
                   db: Session = Depends(get_db)) -> Response:
    dataset_service.delete_dataset(db, settings, dataset_id)
    return Response(status_code=204)


@router.get("/api/scans", response_model=ScanList, summary="Scan history, newest first")
def list_scans(dataset_id: Optional[str] = None,
               status: Optional[str] = Query(None, pattern="^(running|completed|failed)$"),
               offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
               db: Session = Depends(get_db)) -> ScanList:
    total, rows = scan_service.list_scans(db, dataset_id=dataset_id, status=status,
                                          offset=offset, limit=limit)
    return ScanList(total=total, offset=offset, limit=limit,
                    scans=[scan_service.to_info(r) for r in rows])


@router.get("/api/scans/{scan_id}", response_model=ScanInfo, responses=_NOT_FOUND,
            summary="One scan")
def get_scan(scan_id: str, db: Session = Depends(get_db)) -> ScanInfo:
    return scan_service.to_info(scan_service.get_scan(db, scan_id))


@router.get("/api/scans/{scan_id}/issues", response_model=IssuePage, responses=_NOT_FOUND,
            summary="Issues stored for a scan")
def scan_issues(scan_id: str, issue_type: Optional[str] = None, severity: Optional[str] = None,
                offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000),
                db: Session = Depends(get_db)) -> IssuePage:
    scan_service.get_scan(db, scan_id)
    total, rows = scan_service.list_issues(db, scan_id, issue_type=issue_type,
                                           severity=severity, offset=offset, limit=limit)
    return IssuePage(scan_id=scan_id, total=total, offset=offset, limit=limit,
                     issues=[scan_service.issue_to_schema(r) for r in rows])


@router.get("/api/audit-logs", response_model=AuditPage, summary="Audit trail, newest first")
def audit_logs(event_type: Optional[str] = None, entity_type: Optional[str] = None,
               entity_id: Optional[str] = None, dataset_id: Optional[str] = None,
               plan_id: Optional[str] = None,
               offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
               db: Session = Depends(get_db)) -> AuditPage:
    query = select(AuditRow)
    for column, value in ((AuditRow.event_type, event_type), (AuditRow.entity_type, entity_type),
                          (AuditRow.entity_id, entity_id), (AuditRow.dataset_id, dataset_id),
                          (AuditRow.plan_id, plan_id)):
        if value:
            query = query.where(column == value)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(AuditRow.id.desc()).offset(offset).limit(limit)).all()
    return AuditPage(total=total, offset=offset, limit=limit, entries=[
        AuditEntry(id=r.id, timestamp=r.timestamp, event_type=r.event_type,
                   entity_type=r.entity_type, entity_id=r.entity_id,
                   dataset_id=r.dataset_id, plan_id=r.plan_id, actor=r.actor,
                   details=r.details or {}) for r in rows])


def _counts(db: Session, column) -> dict:
    return {k: n for k, n in db.execute(select(column, func.count()).group_by(column)).all()}


@router.get("/api/config", response_model=ConfigResponse, summary="Server limits and retention (no secrets)")
def server_config(settings: Settings = Depends(get_settings)) -> ConfigResponse:
    return ConfigResponse(
        app_name=settings.app_name, version=settings.version, environment=settings.app_env,
        max_upload_size_mb=settings.max_upload_size_mb, max_rows=settings.max_rows,
        max_columns=settings.max_columns, preview_rows=settings.preview_rows,
        max_issues_returned=settings.max_issues_returned,
        max_proposals_per_plan=settings.max_proposals_per_plan,
        upload_retention_days=settings.upload_retention_days,
        cleaned_retention_days=settings.cleaned_retention_days,
        orphan_grace_hours=settings.orphan_grace_hours,
        report_include_names=settings.report_include_names,
        email=email_service.email_status(settings))


@router.get("/api/stats", response_model=StatsResponse, summary="Dashboard metrics")
def stats(db: Session = Depends(get_db)) -> StatsResponse:
    proposals = _counts(db, ProposalRow.status)
    decided = proposals.get("approved", 0) + proposals.get("rejected", 0)
    issues = db.scalar(select(func.coalesce(func.sum(ScanRow.issue_total), 0))
                       .where(ScanRow.status == "completed")) or 0
    return StatsResponse(
        datasets=_counts(db, DatasetRow.status), scans=_counts(db, ScanRow.status),
        issues_detected=int(issues), plans=_counts(db, PlanRow.status), proposals=proposals,
        cleaned_datasets=_counts(db, CleanedRow.status),
        email_reports=_counts(db, EmailReportRow.status),
        approval_rate=round(proposals.get("approved", 0) / decided, 4) if decided else None)
