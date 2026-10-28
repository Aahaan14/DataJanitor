"""
DataJanitor — dataset registry (metadata in the database, bytes on disk).

The database never holds dataset contents; it records the file's name
(a UUID), size and SHA-256. Before every scan the stored file is re-hashed
against that record, so a tampered or replaced original is detected.
"""

import hashlib
import re
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import (
    DatasetModifiedError, DatasetNotFoundError, DatasetUnavailableError,
)
from app.database.base import utcnow
from app.models.records import CleanedRow, DatasetRow
from app.schemas.history import DatasetInfo
from app.services import audit_service, csv_service

_ID = re.compile(r"^[0-9a-f]{32}$")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_path(settings: Settings, dataset_id: str) -> Path:
    """Only ever built from a validated 32-hex id — never from user text."""
    return settings.upload_path / f"{dataset_id}.csv"


def register_upload(session: Session, *, dataset_id: str, filename: str, raw: bytes,
                    parsed: csv_service.ParsedCSV) -> DatasetRow:
    row = DatasetRow(
        id=dataset_id, original_filename=filename, size_bytes=len(raw),
        sha256=sha256_hex(raw), encoding=parsed.encoding, delimiter=parsed.delimiter,
        row_count=len(parsed.df), column_count=parsed.df.shape[1],
        status="active", uploaded_at=utcnow(),
    )
    session.add(row)
    audit_service.log(session, "dataset_uploaded", "dataset", dataset_id, dataset_id=dataset_id,
                      details={"size_bytes": len(raw), "rows": row.row_count,
                               "columns": row.column_count})
    session.commit()
    return row


def get_dataset(session: Session, dataset_id: str, *, active_only: bool = True) -> DatasetRow:
    if not _ID.fullmatch(dataset_id or ""):
        raise DatasetNotFoundError("Dataset not found.")
    row = session.get(DatasetRow, dataset_id)
    if row is None:
        raise DatasetNotFoundError("Dataset not found.")
    if active_only and row.status != "active":
        reason = "deleted" if row.status == "deleted" else "removed after the retention period"
        raise DatasetUnavailableError(f"This dataset was {reason}; its file is no longer available.")
    return row


def load_frame(session: Session, settings: Settings,
               dataset_id: str) -> Tuple[DatasetRow, bytes, pd.DataFrame]:
    """Read the stored original, verify its hash, and parse it (read-only)."""
    row = get_dataset(session, dataset_id)
    try:
        raw = file_path(settings, row.id).read_bytes()
    except OSError as exc:
        raise DatasetUnavailableError("The stored file is no longer available.") from exc
    if sha256_hex(raw) != row.sha256:
        raise DatasetModifiedError(
            "The stored file no longer matches its upload record, so it cannot be scanned.")
    parsed = csv_service.parse_bytes(raw, settings.max_rows, settings.max_columns)
    return row, raw, parsed.df


def delete_dataset(session: Session, settings: Settings, dataset_id: str) -> None:
    """
    Remove the file (and any cleaned copies derived from it) and mark the record
    deleted. Scan, proposal, decision and audit history are kept; active plans for the dataset become stale because
    their file is gone.
    """
    row = get_dataset(session, dataset_id)
    file_path(settings, row.id).unlink(missing_ok=True)
    row.status, row.file_removed_at = "deleted", utcnow()
    stale = 0
    for plan in row.plans:
        if plan.status == "active":
            plan.status = "stale"
            stale += 1
            audit_service.log(session, "plan_marked_stale", "plan", plan.id,
                              dataset_id=row.id, plan_id=plan.id,
                              details={"reason": "dataset_deleted"})
    removed = 0
    for cleaned in session.scalars(select(CleanedRow).where(CleanedRow.dataset_id == row.id)):
        (settings.cleaned_path / f"{cleaned.id}.csv").unlink(missing_ok=True)  # derived data goes too
        if cleaned.status in ("completed", "running"):
            cleaned.status, cleaned.file_removed_at = "deleted", utcnow()
            removed += 1
    audit_service.log(session, "dataset_deleted", "dataset", row.id, dataset_id=row.id,
                      details={"plans_marked_stale": stale, "cleaned_files_removed": removed})
    session.commit()


def to_info(row: DatasetRow) -> DatasetInfo:
    return DatasetInfo(
        dataset_id=row.id, filename=row.original_filename, size_bytes=row.size_bytes,
        sha256=row.sha256, encoding=row.encoding, delimiter=row.delimiter,
        row_count=row.row_count, column_count=row.column_count, status=row.status,
        uploaded_at=row.uploaded_at, file_removed_at=row.file_removed_at)


def list_datasets(session: Session, *, status: Optional[str], offset: int,
                  limit: int) -> Tuple[int, List[DatasetRow]]:
    query = select(DatasetRow)
    if status:
        query = query.where(DatasetRow.status == status)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(DatasetRow.uploaded_at.desc())
                           .offset(offset).limit(limit)).all()
    return total, list(rows)
