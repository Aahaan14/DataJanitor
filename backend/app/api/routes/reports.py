"""
DataJanitor — email report routes (Phase 7).

  GET  /api/email/status                        is email enabled/configured? (no secrets)
  GET  /api/scans/{scan_id}/report/preview      exactly what a scan report would contain
  GET  /api/cleaned/{id}/report/preview         ... for a cleaning report
  POST /api/scans/{scan_id}/report              send a scan report now
  POST /api/cleaned/{id}/report                 send a cleaning report now
  GET  /api/email-reports                       history of reports (filter, paged)
  GET  /api/email-reports/{report_id}           one report record
  POST /api/email-reports/{report_id}/retry     try again after a failure

Automatic reports are sent in the background after each completed scan and
each cleaning run (see scan.py, repairs.py, cleaned.py) when enabled.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.base import get_db
from app.schemas.dataset import ErrorResponse
from app.schemas.reports import EmailReportInfo, EmailReportList, EmailStatus, ReportPreview
from app.services import email_service, report_service

router = APIRouter(tags=["Email reports"])

_ERRORS = {
    404: {"model": ErrorResponse, "description": "Unknown scan, cleaned dataset or report"},
    409: {"model": ErrorResponse, "description": "Email not configured / report not available / already sent"},
}


def _preview(content) -> ReportPreview:
    return ReportPreview(subject=report_service.subject_for(content),
                         text=report_service.render_text(content), content=content)


@router.get("/api/email/status", response_model=EmailStatus, summary="Email configuration status")
def status(settings: Settings = Depends(get_settings)) -> EmailStatus:
    return email_service.email_status(settings)


@router.get("/api/scans/{scan_id}/report/preview", response_model=ReportPreview, responses=_ERRORS,
            summary="Preview a scan report (nothing is sent)")
def preview_scan_report(scan_id: str, settings: Settings = Depends(get_settings),
                        db: Session = Depends(get_db)) -> ReportPreview:
    return _preview(report_service.build_scan_report(db, settings, scan_id))


@router.get("/api/cleaned/{cleaned_id}/report/preview", response_model=ReportPreview,
            responses=_ERRORS, summary="Preview a cleaning report (nothing is sent)")
def preview_cleaning_report(cleaned_id: str, settings: Settings = Depends(get_settings),
                            db: Session = Depends(get_db)) -> ReportPreview:
    return _preview(report_service.build_cleaning_report(db, settings, cleaned_id))


@router.post("/api/scans/{scan_id}/report", response_model=EmailReportInfo, status_code=201,
             responses=_ERRORS, summary="Send a scan report now (the result is in `status`)")
def send_scan_report(scan_id: str, settings: Settings = Depends(get_settings),
                     db: Session = Depends(get_db)) -> EmailReportInfo:
    email_service.require_configured(settings)
    return email_service.to_info(
        email_service.send_report(db, settings, "scan", scan_id, trigger="manual"))


@router.post("/api/cleaned/{cleaned_id}/report", response_model=EmailReportInfo, status_code=201,
             responses=_ERRORS, summary="Send a cleaning report now (the result is in `status`)")
def send_cleaning_report(cleaned_id: str, settings: Settings = Depends(get_settings),
                         db: Session = Depends(get_db)) -> EmailReportInfo:
    email_service.require_configured(settings)
    return email_service.to_info(
        email_service.send_report(db, settings, "cleaning", cleaned_id, trigger="manual"))


@router.get("/api/email-reports", response_model=EmailReportList, summary="Email report history")
def list_email_reports(
    status: Optional[str] = Query(None, pattern="^(pending|sent|failed|skipped)$"),
    kind: Optional[str] = Query(None, pattern="^(scan|cleaning)$"),
    dataset_id: Optional[str] = None,
    offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> EmailReportList:
    total, rows = email_service.list_reports(db, status=status, kind=kind, dataset_id=dataset_id,
                                             offset=offset, limit=limit)
    return EmailReportList(total=total, offset=offset, limit=limit,
                           reports=[email_service.to_info(r) for r in rows])


@router.get("/api/email-reports/{report_id}", response_model=EmailReportInfo, responses=_ERRORS,
            summary="One email report record")
def get_email_report(report_id: str, db: Session = Depends(get_db)) -> EmailReportInfo:
    return email_service.to_info(email_service.get_report(db, report_id))


@router.post("/api/email-reports/{report_id}/retry", response_model=EmailReportInfo,
             responses=_ERRORS, summary="Retry a failed or skipped report")
def retry_email_report(report_id: str, settings: Settings = Depends(get_settings),
                       db: Session = Depends(get_db)) -> EmailReportInfo:
    return email_service.to_info(email_service.retry_report(db, settings, report_id))
