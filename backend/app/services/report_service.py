"""
DataJanitor — building and rendering scan / cleaning reports.

The content model (schemas.reports) has no field that can hold a cell value,
so a report cannot leak dataset contents. File and column names are included
only when REPORT_INCLUDE_NAMES is true. The same content renders to the
plain-text and HTML parts of the email and to the preview endpoint.
"""

import html
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.exceptions import ReportNotAvailableError
from app.database.base import utcnow
from app.models.records import CleanedRow, PlanRow, ProposalRow, ScanRow
from app.schemas.reports import (
    CleaningPart, DatasetPart, ReportContent, ReviewPart, ScanPart, ValidationPart,
)
from app.services import cleaning_service, dataset_service, scan_service

NOTES = [
    "Issues are detected candidates for review, not confirmed errors.",
    "This email contains counts and identifiers only — no cell values from your dataset.",
    "Open DataJanitor to review individual issues and decisions.",
]


def _dataset_part(session: Session, settings: Settings, dataset_id: str) -> DatasetPart:
    row = dataset_service.get_dataset(session, dataset_id, active_only=False)
    return DatasetPart(
        dataset_id=row.id, filename=row.original_filename if settings.report_include_names else None,
        rows=row.row_count, columns=row.column_count, size_bytes=row.size_bytes,
        uploaded_at=row.uploaded_at)


def _scan_part(settings: Settings, scan: ScanRow) -> ScanPart:
    summary = scan.summary or {}
    return ScanPart(
        scan_id=scan.id, started_at=scan.started_at, completed_at=scan.completed_at,
        issue_total=scan.issue_total, affected_rows=summary.get("affected_row_count", 0),
        truncated=scan.truncated, by_severity=summary.get("by_severity", {}),
        by_type=summary.get("by_type", {}),
        by_column=summary.get("by_column", {}) if settings.report_include_names else None)


def _review_part(session: Session, plan_id: str) -> ReviewPart:
    rows = session.execute(
        select(ProposalRow.status, ProposalRow.issue_type, func.count())
        .where(ProposalRow.plan_id == plan_id)
        .group_by(ProposalRow.status, ProposalRow.issue_type)).all()
    totals = {"approved": 0, "rejected": 0, "pending": 0}
    by_type: Dict[str, Dict[str, int]] = {"approved": {}, "rejected": {}}
    for status, issue_type, n in rows:
        totals[status] += n
        if status in by_type:
            by_type[status][issue_type] = n
    return ReviewPart(plan_id=plan_id, proposals_total=sum(totals.values()),
                      approved=totals["approved"], rejected=totals["rejected"],
                      pending=totals["pending"], approved_by_type=by_type["approved"],
                      rejected_by_type=by_type["rejected"])


def build_scan_report(session: Session, settings: Settings, scan_id: str) -> ReportContent:
    scan = scan_service.get_scan(session, scan_id)
    if scan.status != "completed":
        raise ReportNotAvailableError("A report is only available for a completed scan.")
    return ReportContent(
        kind="scan", generated_at=utcnow(),
        dataset=_dataset_part(session, settings, scan.dataset_id),
        scan=_scan_part(settings, scan), notes=NOTES)


def build_cleaning_report(session: Session, settings: Settings, cleaned_id: str) -> ReportContent:
    run = cleaning_service.get_cleaned(session, cleaned_id)
    if run.status not in ("completed", "expired", "deleted") or run.sha256 is None:
        raise ReportNotAvailableError("A report is only available for a completed cleaning run.")
    plan = session.get(PlanRow, run.plan_id)
    scan = scan_service.get_scan(session, plan.scan_id)
    v = run.validation or {}
    return ReportContent(
        kind="cleaning", generated_at=utcnow(),
        dataset=_dataset_part(session, settings, run.dataset_id),
        scan=_scan_part(settings, scan), review=_review_part(session, plan.id),
        cleaning=CleaningPart(
            cleaned_id=run.id, rows_before=run.rows_before, rows_after=run.rows_after,
            rows_deleted=run.rows_deleted, cells_changed=run.cells_changed,
            applied=run.applied_count, skipped=run.skipped_count,
            rejected=run.rejected_count, pending=run.pending_count),
        final_validation=ValidationPart(
            status=v.get("status", "unknown"),
            remaining_issue_count=v.get("remaining_issue_count", 0),
            remaining_by_type=v.get("remaining_by_type", {}),
            increased_issue_types=v.get("increased_issue_types", []),
            rule_count=v.get("rule_count", 0),
            rule_violation_count=v.get("rule_violation_count", 0)),
        notes=NOTES)


# ── Rendering ───────────────────────────────────────────────────────────────

def subject_for(content: ReportContent) -> str:
    """Built only from counts — never from file names or any user text."""
    if content.kind == "scan":
        return f"DataJanitor scan report: {content.scan.issue_total} issue(s) detected"
    c, v = content.cleaning, content.final_validation
    return (f"DataJanitor cleaning report: {c.applied} repair(s) applied, "
            f"final check {v.status.replace('_', ' ')}")


def _fmt_time(t: Optional[datetime]) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S UTC") if t else "—"


def _fmt_counts(d: Optional[Dict[str, int]]) -> str:
    if not d:
        return "none"
    return ", ".join(f"{k.replace('_', ' ')} {v}" for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))


def _size(n: int) -> str:
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} KB" if n < 1024 ** 2 else f"{n / 1024 ** 2:.1f} MB"


def _sections(content: ReportContent) -> List[tuple]:
    """(heading, [(label, value), ...]) — the single source for text and HTML."""
    d, s = content.dataset, content.scan
    sections = [("Dataset", [
        ("File", d.filename or "(hidden by configuration)"),
        ("Size", f"{d.rows} rows × {d.columns} columns, {_size(d.size_bytes)}"),
        ("Dataset ID", d.dataset_id), ("Uploaded", _fmt_time(d.uploaded_at))])]
    scan_rows = [("Scan ID", s.scan_id), ("Completed", _fmt_time(s.completed_at)),
                 ("Issues detected", f"{s.issue_total} (affecting {s.affected_rows} rows)"
                  + (" — list truncated in the app, counts are complete" if s.truncated else "")),
                 ("By severity", _fmt_counts(s.by_severity)), ("By type", _fmt_counts(s.by_type))]
    if s.by_column is not None:
        scan_rows.append(("By column", _fmt_counts(s.by_column)))
    sections.append(("Issues detected", scan_rows))

    r = content.review
    if r is None:
        sections.append(("Repair review", [("Status", "Not started — no proposals have been reviewed yet.")]))
    else:
        sections.append(("Repair review", [
            ("Plan ID", r.plan_id), ("Proposals", str(r.proposals_total)),
            ("Approved", f"{r.approved} ({_fmt_counts(r.approved_by_type)})"),
            ("Rejected", f"{r.rejected} ({_fmt_counts(r.rejected_by_type)})"),
            ("Undecided", str(r.pending))]))
    c = content.cleaning
    if c is not None:
        sections.append(("Cleaned dataset", [
            ("Cleaned ID", c.cleaned_id), ("Rows", f"{c.rows_before} → {c.rows_after} ({c.rows_deleted} deleted)"),
            ("Cells changed", str(c.cells_changed)),
            ("Repairs", f"{c.applied} applied, {c.skipped} skipped, {c.rejected} rejected, {c.pending} undecided")]))
    v = content.final_validation
    if v is not None:
        sections.append(("Final validation", [
            ("Status", v.status.replace("_", " ").upper()),
            ("Remaining issues", f"{v.remaining_issue_count} ({_fmt_counts(v.remaining_by_type)})"),
            ("Rule violations", f"{v.rule_violation_count} (rules checked: {v.rule_count})"),
            ("Got worse after repairs", ", ".join(t.replace("_", " ") for t in v.increased_issue_types) or "nothing")]))
    return sections


def render_text(content: ReportContent) -> str:
    title = "Scan report" if content.kind == "scan" else "Cleaning report"
    lines = [f"DataJanitor — {title}", f"Generated: {_fmt_time(content.generated_at)}", ""]
    for heading, rows in _sections(content):
        lines.append(heading.upper())
        lines += [f"  {label}: {value}" for label, value in rows]
        lines.append("")
    lines.append("NOTES")
    lines += [f"  - {n}" for n in content.notes]
    return "\n".join(lines) + "\n"


def render_html(content: ReportContent) -> str:
    """Self-contained HTML; every dynamic value is escaped."""
    e = html.escape
    title = "Scan report" if content.kind == "scan" else "Cleaning report"
    parts = [f'<div style="font-family:Arial,Helvetica,sans-serif;max-width:640px;color:#1b1f27">',
             f'<h2 style="margin:0 0 4px">DataJanitor — {e(title)}</h2>',
             f'<p style="color:#5d6675;margin:0 0 16px">Generated {e(_fmt_time(content.generated_at))}</p>']
    for heading, rows in _sections(content):
        parts.append(f'<h3 style="margin:18px 0 6px;font-size:15px">{e(heading)}</h3>'
                     '<table style="border-collapse:collapse;width:100%;font-size:14px">')
        for label, value in rows:
            parts.append(f'<tr><td style="padding:4px 10px 4px 0;color:#5d6675;vertical-align:top;'
                         f'white-space:nowrap">{e(label)}</td><td style="padding:4px 0">{e(value)}</td></tr>')
        parts.append("</table>")
    parts.append('<ul style="color:#5d6675;font-size:13px;margin-top:18px">'
                 + "".join(f"<li>{e(n)}</li>" for n in content.notes) + "</ul></div>")
    return "".join(parts)
