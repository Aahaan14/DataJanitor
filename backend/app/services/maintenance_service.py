"""
DataJanitor — file retention and cleanup.

Rules (all configurable via .env, each applied only inside its own folder):
 1. Active datasets older than UPLOAD_RETENTION_DAYS → file removed, record
    marked `expired`, active plans marked `stale`.
 2. Completed cleaned copies older than CLEANED_RETENTION_DAYS → file removed,
    record marked `expired`.
 3. Files of deleted/expired/failed records that are somehow still on disk
    → removed (both folders).
 4. Orphans — `<32 hex>.csv` files with NO database record — older than
    ORPHAN_GRACE_HOURS → removed (the grace period protects a file that is
    still being recorded).
 5. Leftover `*.tmp` files older than 1 hour (interrupted writes) → removed.
Never touched: other file names, sub-folders, symlinks, anything outside the
two folders, files of records still `running`, and ALL database history and
audit logs (kept indefinitely).
Run with dry_run=True to see what would happen without changing anything.
"""

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.database.base import utcnow
from app.models.records import CleanedRow, DatasetRow
from app.services import audit_service

_DATA_FILE = re.compile(r"^([0-9a-f]{32})\.csv$")
TMP_MAX_AGE = timedelta(hours=1)


@dataclass
class CleanupReport:
    dry_run: bool
    expired_datasets: List[str] = field(default_factory=list)
    expired_cleaned: List[str] = field(default_factory=list)
    leftover_files: List[str] = field(default_factory=list)
    orphan_files: List[str] = field(default_factory=list)
    temp_files: List[str] = field(default_factory=list)
    plans_marked_stale: int = 0

    def total_changes(self) -> int:
        return (len(self.expired_datasets) + len(self.expired_cleaned)
                + len(self.leftover_files) + len(self.orphan_files) + len(self.temp_files))


def _sweep_folder(folder: Path, known: Dict[str, str], dead: Tuple[str, ...],
                  settings: Settings, now: datetime, dry_run: bool,
                  report: CleanupReport) -> None:
    """Rules 3–5 for one folder. `known` maps record id → status."""
    if not folder.is_dir():
        return
    grace = timedelta(hours=settings.orphan_grace_hours)
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                continue
            age = timedelta(seconds=now.timestamp() - entry.stat(follow_symlinks=False).st_mtime)
            match = _DATA_FILE.match(entry.name)
            target = None
            if match:
                status = known.get(match.group(1))
                if status in dead:
                    report.leftover_files.append(entry.name)
                    target = Path(entry.path)
                elif status is None and age > grace:
                    report.orphan_files.append(entry.name)
                    target = Path(entry.path)
            elif entry.name.endswith(".tmp") and age > TMP_MAX_AGE:
                report.temp_files.append(entry.name)
                target = Path(entry.path)
            if target is not None and not dry_run:
                target.unlink(missing_ok=True)


def run_cleanup(session: Session, settings: Settings, *, dry_run: bool = False,
                now: Optional[datetime] = None) -> CleanupReport:
    now = now or utcnow()
    report = CleanupReport(dry_run=dry_run)

    # Rule 1 — uploaded datasets past retention
    cutoff = now - timedelta(days=settings.upload_retention_days)
    for row in session.scalars(select(DatasetRow).where(
            DatasetRow.status == "active", DatasetRow.uploaded_at < cutoff)):
        report.expired_datasets.append(row.id)
        if dry_run:
            continue
        (settings.upload_path / f"{row.id}.csv").unlink(missing_ok=True)
        row.status, row.file_removed_at = "expired", now
        for plan in row.plans:
            if plan.status == "active":
                plan.status = "stale"
                report.plans_marked_stale += 1
                audit_service.log(session, "plan_marked_stale", "plan", plan.id,
                                  dataset_id=row.id, plan_id=plan.id,
                                  details={"reason": "dataset_expired"})
        audit_service.log(session, "dataset_expired", "dataset", row.id, dataset_id=row.id,
                          details={"retention_days": settings.upload_retention_days})

    # Rule 2 — cleaned copies past retention
    cleaned_cutoff = now - timedelta(days=settings.cleaned_retention_days)
    for row in session.scalars(select(CleanedRow).where(
            CleanedRow.status == "completed", CleanedRow.created_at < cleaned_cutoff)):
        report.expired_cleaned.append(row.id)
        if dry_run:
            continue
        (settings.cleaned_path / f"{row.id}.csv").unlink(missing_ok=True)
        row.status, row.file_removed_at = "expired", now
        audit_service.log(session, "cleaned_expired", "cleaned", row.id,
                          dataset_id=row.dataset_id, plan_id=row.plan_id,
                          details={"retention_days": settings.cleaned_retention_days})

    # Rules 3–5 — sweep both folders (statuses read after the updates above)
    if not dry_run:
        session.flush()
    datasets = {r.id: r.status for r in session.execute(select(DatasetRow.id, DatasetRow.status))}
    cleaned = {r.id: r.status for r in session.execute(select(CleanedRow.id, CleanedRow.status))}
    _sweep_folder(settings.upload_path, datasets, ("deleted", "expired"), settings, now, dry_run, report)
    _sweep_folder(settings.cleaned_path, cleaned, ("deleted", "expired", "failed"), settings, now, dry_run, report)

    if not dry_run and report.total_changes():
        audit_service.log(session, "cleanup_run", "system", None, details={
            "expired_datasets": len(report.expired_datasets),
            "expired_cleaned": len(report.expired_cleaned),
            "leftover_files": len(report.leftover_files),
            "orphan_files": len(report.orphan_files),
            "temp_files": len(report.temp_files)})
    session.commit()
    return report
