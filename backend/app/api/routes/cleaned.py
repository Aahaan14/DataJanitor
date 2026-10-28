"""
DataJanitor — cleaned dataset routes (Phase 6).

  POST /api/repair-plans/{plan_id}/apply        apply APPROVED repairs to a copy
  GET  /api/repair-plans/{plan_id}/cleaned      cleaned copies made from a plan
  GET  /api/cleaned/{cleaned_id}                summary + final validation
  GET  /api/cleaned/{cleaned_id}/outcomes       applied / skipped / rejected / pending
  GET  /api/cleaned/{cleaned_id}/download       the CSV (mode=safe|raw)

The original upload is never written to by any of these.
"""

import re
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.base import get_db
from app.schemas.cleaned import CleanedSummary, OutcomePage
from app.schemas.dataset import ErrorResponse
from app.services import cleaning_service, dataset_service, email_service, plan_service

router = APIRouter(tags=["Cleaned datasets"])

_ERRORS = {
    404: {"model": ErrorResponse, "description": "Unknown plan or cleaned dataset"},
    409: {"model": ErrorResponse, "description": "Plan stale/superseded"},
    410: {"model": ErrorResponse, "description": "File deleted or expired"},
    422: {"model": ErrorResponse, "description": "Nothing approved"},
}
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._()-]")


@router.post("/api/repair-plans/{plan_id}/apply", response_model=CleanedSummary,
             status_code=201, responses=_ERRORS,
             summary="Apply the approved repairs to a separate copy")
def apply_repairs(plan_id: str, request: Request, background: BackgroundTasks,
                  settings: Settings = Depends(get_settings),
                  db: Session = Depends(get_db)) -> CleanedSummary:
    run = cleaning_service.generate_cleaned(db, settings, plan_id)
    email_service.queue_report(background, request.app.state.session_factory, settings,
                               "cleaning", run.id)
    return cleaning_service.to_summary(run)


@router.get("/api/repair-plans/{plan_id}/cleaned", response_model=List[CleanedSummary],
            responses=_ERRORS, summary="Cleaned copies generated from this plan, newest first")
def plan_cleaned(plan_id: str, db: Session = Depends(get_db)) -> List[CleanedSummary]:
    plan = plan_service.get_plan(db, plan_id)
    return [cleaning_service.to_summary(r) for r in cleaning_service.list_for_plan(db, plan.id)]


@router.get("/api/cleaned/{cleaned_id}", response_model=CleanedSummary, responses=_ERRORS,
            summary="Cleaned dataset summary with final validation")
def get_cleaned(cleaned_id: str, db: Session = Depends(get_db)) -> CleanedSummary:
    return cleaning_service.to_summary(cleaning_service.get_cleaned(db, cleaned_id))


@router.get("/api/cleaned/{cleaned_id}/outcomes", response_model=OutcomePage, responses=_ERRORS,
            summary="What happened to every proposal in this run")
def outcomes(cleaned_id: str,
             outcome: Optional[str] = Query(None, pattern="^(applied|skipped|rejected|pending)$"),
             offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000),
             db: Session = Depends(get_db)) -> OutcomePage:
    cleaning_service.get_cleaned(db, cleaned_id)
    total, items = cleaning_service.outcome_page(db, cleaned_id, outcome=outcome,
                                                 offset=offset, limit=limit)
    return OutcomePage(cleaned_id=cleaned_id, total=total, offset=offset, limit=limit,
                       outcomes=items)


@router.get("/api/cleaned/{cleaned_id}/download", responses={**_ERRORS, 200: {"content": {"text/csv": {}}}},
            summary="Download the cleaned CSV")
def download(cleaned_id: str,
             mode: str = Query("safe", pattern="^(safe|raw)$",
                               description="safe = escape spreadsheet formulas (default); "
                                           "raw = exact values"),
             settings: Settings = Depends(get_settings),
             db: Session = Depends(get_db)) -> Response:
    row, data, escaped = cleaning_service.read_download(db, settings, cleaned_id, mode)
    original = dataset_service.get_dataset(db, row.dataset_id, active_only=False)
    stem = _SAFE_NAME.sub("_", original.original_filename.rsplit(".", 1)[0])[:100] or "dataset"
    return Response(
        content=data, media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}_cleaned.csv"',
            "X-Content-Type-Options": "nosniff",
            "X-DataJanitor-Mode": mode,
            "X-DataJanitor-Cells-Escaped": str(escaped),
            "Cache-Control": "no-store",
        })
