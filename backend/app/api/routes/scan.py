"""
DataJanitor — scan route.

POST /api/datasets/{dataset_id}/scan
  Re-reads the stored original upload (never modifying it), runs every
  detector, saves the scan and its issues to the database, and returns the
  standardized issue records plus a summary. Browse past scans with
  GET /api/scans (see history.py).
"""

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.base import get_db
from app.schemas.dataset import ErrorResponse
from app.schemas.issues import ScanResponse
from app.services import detection_service, email_service, scan_service

router = APIRouter(prefix="/api/datasets", tags=["Scans"])


@router.post(
    "/{dataset_id}/scan",
    response_model=ScanResponse,
    summary="Scan an uploaded dataset for data-quality issues",
    responses={
        404: {"model": ErrorResponse, "description": "Unknown dataset id"},
        409: {"model": ErrorResponse, "description": "Stored file no longer matches its record"},
        410: {"model": ErrorResponse, "description": "Dataset deleted or expired"},
        422: {"model": ErrorResponse, "description": "Stored file no longer parses"},
    },
)
def scan_dataset(
    dataset_id: str,
    request: Request,
    background: BackgroundTasks,
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> ScanResponse:
    outcome = scan_service.perform_scan(db, settings, dataset_id)
    # Results are already committed; the email is sent after the response.
    email_service.queue_report(background, request.app.state.session_factory, settings,
                               "scan", outcome.scan.id)
    shown = outcome.issues[: settings.max_issues_returned]
    return ScanResponse(
        scan_id=outcome.scan.id,
        status=outcome.scan.status,
        dataset_id=dataset_id,
        scanned_at=outcome.scan.completed_at,
        row_count=len(outcome.df),
        column_count=outcome.df.shape[1],
        summary=detection_service.summarize(outcome.issues),
        issues_returned=len(shown),
        truncated=len(outcome.issues) > len(shown),
        disclaimer=detection_service.DISCLAIMER,
        issues=shown,
    )
