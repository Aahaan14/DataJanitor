"""
DataJanitor — CSV upload route.

POST /api/datasets/upload
  multipart/form-data with a single `file` field.
  → 201 with dataset metadata, per-column profile and a preview.

The route stays thin: it validates, delegates to services, and shapes the
response. Parsing is CPU-bound, so it runs in a worker thread.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from fastapi.concurrency import run_in_threadpool

from app.config import Settings, get_settings
from app.core.exceptions import FileTooLargeError, StorageError
from app.database.base import get_db
from app.schemas.dataset import ErrorResponse, UploadResponse
from app.services import csv_service, dataset_service, profiling_service

router = APIRouter(prefix="/api/datasets", tags=["Datasets"])

# Multipart framing adds a little to Content-Length beyond the file itself.
_MULTIPART_OVERHEAD = 64 * 1024


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a CSV dataset",
    responses={
        400: {"model": ErrorResponse, "description": "Empty file"},
        413: {"model": ErrorResponse, "description": "File too large"},
        415: {"model": ErrorResponse, "description": "Not a .csv file"},
        422: {"model": ErrorResponse, "description": "Malformed, bad encoding, or over limits"},
    },
)
async def upload_dataset(
    request: Request,
    file: UploadFile = File(...),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> UploadResponse:
    # Cheap early rejection based on the declared size (not trusted alone —
    # the chunked reader below enforces the real limit).
    declared = request.headers.get("content-length")
    if declared and declared.isdigit():
        if int(declared) > settings.max_upload_size_bytes + _MULTIPART_OVERHEAD:
            raise FileTooLargeError(
                f"File exceeds the maximum size of {settings.max_upload_size_mb} MB."
            )

    safe_name = csv_service.sanitize_filename(file.filename)
    raw = await csv_service.read_upload_limited(file, settings.max_upload_size_bytes)

    parsed = await run_in_threadpool(
        csv_service.parse_bytes, raw, settings.max_rows, settings.max_columns
    )
    df, encoding, delimiter, warnings = (
        parsed.df, parsed.encoding, parsed.delimiter, parsed.warnings
    )

    # Only persist once the file has passed every check: file first, then its
    # database record. If the record cannot be saved, the file is removed again
    # so no unrecorded upload is left behind.
    def _persist() -> str:
        dataset_id, path = csv_service.save_original(raw, settings.upload_path)
        try:
            dataset_service.register_upload(
                db, dataset_id=dataset_id, filename=safe_name, raw=raw, parsed=parsed)
        except SQLAlchemyError as exc:
            db.rollback()
            path.unlink(missing_ok=True)
            raise StorageError("The upload could not be recorded. Please try again.") from exc
        return dataset_id

    dataset_id = await run_in_threadpool(_persist)

    return UploadResponse(
        dataset_id=dataset_id,
        filename=safe_name,
        size_bytes=len(raw),
        encoding=encoding,
        delimiter=delimiter,
        row_count=len(df),
        column_count=df.shape[1],
        uploaded_at=datetime.now(timezone.utc),
        columns=profiling_service.profile_dataframe(df),
        preview=profiling_service.build_preview(df, settings.preview_rows),
        warnings=warnings,
    )
