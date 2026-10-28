"""
DataJanitor — sending reports by SMTP, and recording every attempt.

Reliability rules
─────────────────
• Automatic reports run AFTER the response, in a background task with their
  own database session. Scan and cleaning results are committed first, so an
  email problem can never lose or delay them.
• Every attempt is a row in `email_reports` (pending → sent / failed /
  skipped) plus an audit entry. Failures store a short, safe message — never
  the password, never raw server text — and can be retried.
Security rules
──────────────
• Credentials come from environment variables only (SecretStr, never logged
  or returned by any endpoint).
• TLS certificates are verified. Unencrypted SMTP is accepted only for
  localhost, and never together with a login.
• Addresses are validated (no line breaks/odd characters → no header
  injection) and the subject is built from counts only.
"""

import logging
import re
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import List, Optional, Tuple

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.core.exceptions import (
    DatasetError, EmailDeliveryError, EmailNotConfiguredError, ReportAlreadySentError,
    ReportNotFoundError,
)
from app.database.base import utcnow
from app.models.records import CleanedRow, EmailReportRow, PlanRow, ScanRow
from app.schemas.reports import EmailReportInfo, EmailStatus, ReportContent
from app.services import audit_service, report_service

logger = logging.getLogger("datajanitor.email")

_ADDRESS = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)+$")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
MAX_RECIPIENTS = 5


@dataclass(frozen=True)
class EmailConfig:
    host: str
    port: int
    security: str
    user: str
    password: str
    sender: str
    recipients: Tuple[str, ...]
    timeout: int


def mask_address(address: str) -> str:
    local, _, domain = address.partition("@")
    return f"{local[:1]}***@{domain}"


def load_config(settings: Settings) -> Tuple[Optional[EmailConfig], Optional[str]]:
    """Return (config, None) or (None, problem). Problems never include secret values."""
    if not settings.email_reports_enabled:
        return None, "Email reports are disabled (EMAIL_REPORTS_ENABLED is not true)."
    host, sender = settings.smtp_host.strip(), settings.smtp_from.strip()
    recipients = tuple(r.strip() for r in settings.report_recipient.split(",") if r.strip())
    if not host or not sender or not recipients:
        return None, "SMTP is not fully configured (SMTP_HOST, SMTP_FROM and REPORT_RECIPIENT are required)."
    if not _ADDRESS.match(sender) or not recipients or any(not _ADDRESS.match(r) for r in recipients):
        return None, "SMTP_FROM or REPORT_RECIPIENT is not a valid email address."
    if len(recipients) > MAX_RECIPIENTS:
        return None, f"At most {MAX_RECIPIENTS} recipients are allowed."
    if not re.fullmatch(r"[A-Za-z0-9.\-]+", host):
        return None, "SMTP_HOST is not a valid host name."
    security = settings.smtp_security.strip().lower()
    if security not in ("starttls", "ssl", "none"):
        return None, "SMTP_SECURITY must be starttls, ssl or none."
    user, password = settings.smtp_user.strip(), settings.smtp_password.get_secret_value()
    if security == "none" and (host.lower() not in _LOCAL_HOSTS or user):
        return None, "Unencrypted SMTP is only allowed for localhost and without a login."
    if not 1 <= settings.smtp_port <= 65535:
        return None, "SMTP_PORT is not valid."
    return EmailConfig(host, settings.smtp_port, security, user, password, sender,
                       recipients, max(1, settings.smtp_timeout_seconds)), None


def email_status(settings: Settings) -> EmailStatus:
    cfg, problem = load_config(settings)
    return EmailStatus(
        enabled=settings.email_reports_enabled, configured=cfg is not None,
        problem=None if cfg else problem,
        smtp_host=cfg.host if cfg else None, smtp_security=cfg.security if cfg else None,
        recipient_masked=", ".join(mask_address(r) for r in cfg.recipients) if cfg else None,
        include_names=settings.report_include_names)


def compose(cfg: EmailConfig, content: ReportContent,
            attachment: Optional[Tuple[str, bytes]] = None) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = report_service.subject_for(content)
    msg["From"] = cfg.sender
    msg["To"] = ", ".join(cfg.recipients)
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=cfg.sender.split("@", 1)[1])
    msg.set_content(report_service.render_text(content))
    msg.add_alternative(report_service.render_html(content), subtype="html")
    if attachment is not None:
        filename, data = attachment
        msg.add_attachment(data, maintype="text", subtype="csv", filename=filename)
    return msg


def deliver(cfg: EmailConfig, msg: EmailMessage) -> None:
    """Send one message. Raises EmailDeliveryError with a safe message on any failure."""
    context = ssl.create_default_context()  # verifies certificates and host names
    try:
        if cfg.security == "ssl":
            server = smtplib.SMTP_SSL(cfg.host, cfg.port, timeout=cfg.timeout, context=context)
        else:
            server = smtplib.SMTP(cfg.host, cfg.port, timeout=cfg.timeout)
        with server:
            server.ehlo()
            if cfg.security == "starttls":
                server.starttls(context=context)
                server.ehlo()
            if cfg.user:
                server.login(cfg.user, cfg.password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailDeliveryError(f"SMTP login was rejected (code {exc.smtp_code}).") from None
    except smtplib.SMTPRecipientsRefused:
        raise EmailDeliveryError("The SMTP server refused the recipient address.") from None
    except smtplib.SMTPSenderRefused:
        raise EmailDeliveryError("The SMTP server refused the sender address.") from None
    except (ssl.SSLError, ssl.CertificateError):
        raise EmailDeliveryError("A secure (TLS) connection to the SMTP server could not be established.") from None
    except smtplib.SMTPResponseException as exc:
        raise EmailDeliveryError(f"The SMTP server returned an error (code {exc.smtp_code}).") from None
    except smtplib.SMTPException:
        raise EmailDeliveryError("The SMTP server reported an error.") from None
    except (TimeoutError, OSError):
        raise EmailDeliveryError("Could not connect to the SMTP server (timeout or network error).") from None


# ── Orchestration ───────────────────────────────────────────────────────────

def _build(session: Session, settings: Settings, kind: str, target_id: str) -> ReportContent:
    if kind == "scan":
        return report_service.build_scan_report(session, settings, target_id)
    return report_service.build_cleaning_report(session, settings, target_id)


def _targets(session: Session, kind: str, target_id: str) -> dict:
    if kind == "scan":
        scan = session.get(ScanRow, target_id)
        return {"dataset_id": scan.dataset_id, "scan_id": scan.id}
    run = session.get(CleanedRow, target_id)
    plan = session.get(PlanRow, run.plan_id)
    return {"dataset_id": run.dataset_id, "scan_id": plan.scan_id, "plan_id": plan.id,
            "cleaned_id": run.id}


def _cleaned_csv_attachment(session: Session, settings: Settings, cleaned_id: str) -> Tuple[str, bytes]:
    """Read and verify the generated CSV, then neutralize spreadsheet formulas for email."""
    from app.services import cleaning_service, dataset_service, repair_service

    cleaned = cleaning_service.get_cleaned(session, cleaned_id)
    if cleaned.status != "completed":
        raise DatasetError("The cleaned dataset is not available for email attachment.")
    path = cleaning_service.cleaned_path(settings, cleaned.id)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise DatasetError("The cleaned dataset file is no longer available.") from exc
    if not cleaned.sha256 or dataset_service.sha256_hex(data) != cleaned.sha256:
        raise DatasetError("The cleaned dataset failed its integrity check and was not attached.")
    dataset = dataset_service.get_dataset(session, cleaned.dataset_id, active_only=False)
    safe_data, _ = repair_service.sanitize_for_spreadsheet(data, dataset.delimiter)
    # Avoid exposing original filenames or column names in attachment metadata.
    return f"datajanitor_cleaned_{cleaned.id[:8]}.csv", safe_data


def _attempt(session: Session, settings: Settings, row: EmailReportRow) -> EmailReportRow:
    """Build, send and record one attempt for an existing report row."""
    cfg, problem = load_config(settings)
    now = utcnow()
    row.attempts += 1
    row.last_attempt_at = now
    if cfg is None:
        row.status, row.error_message = "skipped", (problem or "")[:200]
        event = "report_skipped"
    else:
        row.recipient_masked = ", ".join(mask_address(r) for r in cfg.recipients)[:120]
        try:
            content = _build(session, settings, row.kind,
                             row.scan_id if row.kind == "scan" else row.cleaned_id)
            row.subject = report_service.subject_for(content)[:200]
            attachment = (_cleaned_csv_attachment(session, settings, row.cleaned_id)
                          if row.kind == "cleaning" and row.cleaned_id else None)
            deliver(cfg, compose(cfg, content, attachment=attachment))
            row.status, row.error_message, row.sent_at = "sent", None, utcnow()
            event = "report_sent"
        except EmailDeliveryError as exc:
            row.status, row.error_message = "failed", exc.message[:200]
            event = "report_failed"
        except DatasetError as exc:
            row.status, row.error_message = "failed", exc.message[:200]
            event = "report_failed"
        except Exception:  # noqa: BLE001 — never leave a report stuck as "pending"
            logger.exception("Unexpected error while sending report %s", row.id)
            row.status, row.error_message = "failed", "Unexpected error while sending the report."
            event = "report_failed"
    audit_service.log(session, event, "report", row.id, dataset_id=row.dataset_id,
                      plan_id=row.plan_id,
                      details={"kind": row.kind, "trigger": row.trigger, "attempt": row.attempts,
                               "error": row.error_message})
    session.commit()
    return row


def send_report(session: Session, settings: Settings, kind: str, target_id: str,
                *, trigger: str) -> EmailReportRow:
    """Create a report row (committed first, status pending) and attempt delivery."""
    content = _build(session, settings, kind, target_id)  # validates the target; may raise 404/409
    row = EmailReportRow(
        id=uuid.uuid4().hex, kind=kind, trigger=trigger, status="pending", attempts=0,
        subject=report_service.subject_for(content)[:200], created_at=utcnow(),
        **_targets(session, kind, target_id))
    session.add(row)
    session.commit()
    return _attempt(session, settings, row)


def retry_report(session: Session, settings: Settings, report_id: str) -> EmailReportRow:
    row = get_report(session, report_id)
    if row.status in ("sent", "pending"):
        raise ReportAlreadySentError(
            "This report was already sent." if row.status == "sent" else "This report is still being sent.")
    cfg, problem = load_config(settings)
    if cfg is None:
        raise EmailNotConfiguredError(problem or "Email is not configured.")
    return _attempt(session, settings, row)


def require_configured(settings: Settings) -> None:
    cfg, problem = load_config(settings)
    if cfg is None:
        raise EmailNotConfiguredError(problem or "Email is not configured.")


def queue_report(background: BackgroundTasks, session_factory: sessionmaker, settings: Settings,
                 kind: str, target_id: str) -> None:
    """Schedule an automatic report to run after the response. No-op when emails are disabled."""
    if settings.email_reports_enabled:
        background.add_task(_run_auto, session_factory, settings, kind, target_id)


def _run_auto(session_factory: sessionmaker, settings: Settings, kind: str, target_id: str) -> None:
    """Background entry point: must never raise into the server."""
    try:
        with session_factory() as session:
            send_report(session, settings, kind, target_id, trigger="auto")
    except Exception:  # noqa: BLE001 — a failed email must not affect anything else
        logger.exception("Automatic %s report could not be processed", kind)


# ── Queries ─────────────────────────────────────────────────────────────────

def get_report(session: Session, report_id: str) -> EmailReportRow:
    row = session.get(EmailReportRow, report_id) if report_id and len(report_id) == 32 else None
    if row is None:
        raise ReportNotFoundError("Email report not found.")
    return row


def to_info(row: EmailReportRow) -> EmailReportInfo:
    return EmailReportInfo(
        report_id=row.id, kind=row.kind, trigger=row.trigger, dataset_id=row.dataset_id,
        scan_id=row.scan_id, plan_id=row.plan_id, cleaned_id=row.cleaned_id,
        recipient_masked=row.recipient_masked, subject=row.subject, status=row.status,
        attempts=row.attempts, error_message=row.error_message, created_at=row.created_at,
        last_attempt_at=row.last_attempt_at, sent_at=row.sent_at)


def list_reports(session: Session, *, status: Optional[str], kind: Optional[str],
                 dataset_id: Optional[str], offset: int, limit: int) -> Tuple[int, List[EmailReportRow]]:
    query = select(EmailReportRow)
    for column, value in ((EmailReportRow.status, status), (EmailReportRow.kind, kind),
                          (EmailReportRow.dataset_id, dataset_id)):
        if value:
            query = query.where(column == value)
    total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = session.scalars(query.order_by(EmailReportRow.created_at.desc())
                           .offset(offset).limit(limit)).all()
    return total, list(rows)
