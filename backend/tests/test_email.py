"""
DataJanitor — Phase 7 tests: report content and privacy, configuration,
real SMTP delivery (in-process stub), failure isolation, retries, audit.
"""

import logging
import smtplib
import socket
import ssl
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from pydantic import SecretStr

from app.config import Settings
from app.models.records import AuditRow, EmailReportRow, ScanRow
from app.schemas.reports import DatasetPart, ReportContent, ScanPart
from app.services import detection_service, email_service, report_service
from tests.smtp_stub import StubSMTPServer

MARKER = "ZEBRA-QUOKKA-77"
PASSWORD = "s3cr3t-app-passw0rd"
CSV = (
    "id,name,age,city,note\n"
    f"1,Alice Smith,30,Mumbai,{MARKER}\n"
    "2,Bob,,mumbai,ok\n"
    "3,Carol,abc,Mumbai,ok\n"
    "4, alice smith,30,Mumbai,ok\n"
    "5,Dan,31,Pune,\"1,200\"\n"
    f"1,Alice Smith,30,Mumbai,{MARKER}\n"
)


@pytest.fixture
def smtp():
    server = StubSMTPServer().start()
    yield server
    server.stop()


def enable(settings: Settings, port: int, **overrides) -> Settings:
    values = dict(email_reports_enabled=True, smtp_host="127.0.0.1", smtp_port=port,
                  smtp_security="none", smtp_from="janitor@example.com",
                  report_recipient="owner@example.com")
    values.update(overrides)
    if isinstance(values.get("smtp_password"), str):
        values["smtp_password"] = SecretStr(values["smtp_password"])   # as pydantic does when loading .env
    for k, v in values.items():
        setattr(settings, k, v)
    return settings


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def upload(client, csv=CSV, name="payroll_secret.csv"):
    r = await client.post("/api/datasets/upload", files={"file": (name, csv.encode(), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()["dataset_id"]


async def scan(client, did):
    r = await client.post(f"/api/datasets/{did}/scan")
    assert r.status_code == 200, r.text
    return r.json()


async def cleaned_run(client, did):
    pid = (await client.post(f"/api/datasets/{did}/repair-plan")).json()["plan_id"]
    ps = (await client.get(f"/api/repair-plans/{pid}/proposals", params={"limit": 1000})).json()["proposals"]
    ws = next(p for p in ps if p["issue_type"] == "whitespace")
    dup = next(p for p in ps if p["issue_type"] == "exact_duplicate")
    await client.post(f"/api/repair-plans/{pid}/proposals/{ws['proposal_id']}/decision", json={"decision": "approve"})
    await client.post(f"/api/repair-plans/{pid}/proposals/{dup['proposal_id']}/decision", json={"decision": "reject"})
    r = await client.post(f"/api/repair-plans/{pid}/apply")
    assert r.status_code == 201, r.text
    return r.json()["cleaned_id"]


def bodies(msg):
    text = msg.get_body(preferencelist=("plain",)).get_content()
    html = msg.get_body(preferencelist=("html",)).get_content()
    return text, html


# ── Disabled by default / configuration ─────────────────────────────────────

async def test_disabled_by_default_sends_and_records_nothing(client, db):
    did = await upload(client)
    await scan(client, did)
    assert db.query(EmailReportRow).count() == 0
    status = (await client.get("/api/email/status")).json()
    assert status["enabled"] is False and status["configured"] is False
    sid = (await client.get("/api/scans")).json()["scans"][0]["scan_id"]
    r = await client.post(f"/api/scans/{sid}/report")
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_not_configured"


@pytest.mark.parametrize("overrides,fragment", [
    ({"smtp_host": ""}, "not fully configured"),
    ({"smtp_from": ""}, "not fully configured"),
    ({"report_recipient": ""}, "not fully configured"),
    ({"report_recipient": "not-an-address"}, "valid email address"),
    ({"report_recipient": "a@b.com\nBcc: evil@x.com"}, "valid email address"),
    ({"report_recipient": "a@example.com,b@example.com,c@example.com,d@example.com,e@example.com,f@example.com"}, "At most"),
    ({"smtp_from": "x@y.com\r\nSubject: hi"}, "valid email address"),
    ({"smtp_security": "tls1"}, "SMTP_SECURITY"),
    ({"smtp_host": "mail.example.com", "smtp_security": "none"}, "only allowed for localhost"),
    ({"smtp_user": "me", "smtp_security": "none"}, "only allowed for localhost"),
    ({"smtp_host": "bad host;rm -rf"}, "valid host name"),
    ({"smtp_port": 0}, "SMTP_PORT"),
])
def test_invalid_configuration_is_rejected_with_a_safe_message(settings, overrides, fragment):
    enable(settings, 2525, **overrides)
    cfg, problem = email_service.load_config(settings)
    assert cfg is None and fragment in problem
    assert PASSWORD not in problem


def test_valid_configurations_are_accepted(settings):
    enable(settings, 587, smtp_host="smtp.gmail.com", smtp_security="starttls",
           smtp_user="me@gmail.com", smtp_password=PASSWORD,
           report_recipient="a@example.com, b@example.com")
    cfg, problem = email_service.load_config(settings)
    assert problem is None and cfg.recipients == ("a@example.com", "b@example.com")
    assert cfg.password == PASSWORD
    enable(settings, 25, smtp_user="", smtp_password="", smtp_host="127.0.0.1")  # localhost, no encryption, no login
    assert email_service.load_config(settings)[1] is None


async def test_status_endpoint_hides_secrets(client, settings):
    enable(settings, 587, smtp_host="smtp.example.com", smtp_security="starttls",
           smtp_user="me@example.com", smtp_password=PASSWORD)
    r = await client.get("/api/email/status")
    body = r.json()
    assert body["configured"] is True and body["recipient_masked"] == "o***@example.com"
    assert body["smtp_host"] == "smtp.example.com"
    assert PASSWORD not in r.text and "owner@example.com" not in r.text
    assert PASSWORD not in repr(settings) and PASSWORD not in str(settings.model_dump())


# ── Report content and privacy ──────────────────────────────────────────────

async def test_scan_preview_contains_counts_and_never_cell_values(client):
    did = await upload(client)
    sid = (await scan(client, did))["scan_id"]
    r = await client.get(f"/api/scans/{sid}/report/preview")
    assert r.status_code == 200
    body = r.json()
    assert MARKER not in r.text and "1,200" not in body["text"]
    assert "Alice" not in r.text and "Carol" not in r.text
    assert body["content"]["kind"] == "scan" and body["content"]["review"] is None
    assert body["content"]["scan"]["issue_total"] > 0
    text = body["text"]
    for needle in ("DATASET", "ISSUES DETECTED", "REPAIR REVIEW", "Not started", "NOTES", did, sid):
        assert needle in text
    assert "payroll" not in body["subject"]            # subject is built from counts only


async def test_names_can_be_excluded_from_reports(client, settings):
    settings.report_include_names = False
    did = await upload(client)
    sid = (await scan(client, did))["scan_id"]
    body = (await client.get(f"/api/scans/{sid}/report/preview")).json()
    assert body["content"]["dataset"]["filename"] is None and body["content"]["scan"]["by_column"] is None
    for hidden in ("payroll_secret", "By column", "salary", "name:", "city:"):
        assert hidden not in body["text"]
    settings.report_include_names = True
    body = (await client.get(f"/api/scans/{sid}/report/preview")).json()
    assert "payroll_secret.csv" in body["text"] and "By column" in body["text"]


async def test_cleaning_preview_covers_review_cleaning_and_final_validation(client):
    did = await upload(client)
    cid = await cleaned_run(client, did)
    r = await client.get(f"/api/cleaned/{cid}/report/preview")
    body = r.json()
    c = body["content"]
    assert c["kind"] == "cleaning"
    assert (c["review"]["approved"], c["review"]["rejected"]) == (1, 1)
    assert c["review"]["approved_by_type"] == {"whitespace": 1}
    assert c["review"]["rejected_by_type"] == {"exact_duplicate": 1}
    assert c["cleaning"]["applied"] == 1 and c["cleaning"]["rows_deleted"] == 0
    assert c["final_validation"]["status"] in ("passed", "issues_remaining")
    for needle in ("REPAIR REVIEW", "CLEANED DATASET", "FINAL VALIDATION", "Approved: 1", "Rejected: 1"):
        assert needle in body["text"]
    assert MARKER not in r.text and "Cleaning report" in body["text"]
    assert body["subject"].startswith("DataJanitor cleaning report: 1 repair(s) applied")


async def test_reports_unavailable_for_failed_scans_and_unknown_ids(client, monkeypatch):
    did = await upload(client)
    monkeypatch.setattr(detection_service, "run_detection", lambda df: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        await client.post(f"/api/datasets/{did}/scan")
    monkeypatch.undo()
    failed = (await client.get("/api/scans", params={"status": "failed"})).json()["scans"][0]["scan_id"]
    r = await client.get(f"/api/scans/{failed}/report/preview")
    assert r.status_code == 409 and r.json()["error"]["code"] == "report_not_available"
    assert (await client.get(f"/api/scans/{'a' * 32}/report/preview")).status_code == 404
    assert (await client.get(f"/api/cleaned/{'a' * 32}/report/preview")).status_code == 404


def test_html_rendering_escapes_everything():
    now = datetime.now(timezone.utc)
    evil = '<script>alert(1)</script>&"'
    content = ReportContent(
        kind="scan", generated_at=now,
        dataset=DatasetPart(dataset_id="d" * 32, filename=evil, rows=1, columns=1, size_bytes=5, uploaded_at=now),
        scan=ScanPart(scan_id="s" * 32, started_at=now, completed_at=now, issue_total=1, affected_rows=1,
                      truncated=False, by_severity={"low": 1}, by_type={"x<b>": 1}, by_column={evil: 1}),
        notes=[evil])
    html = report_service.render_html(content)
    assert "<script>" not in html and "&lt;script&gt;" in html and "x&lt;b&gt;" in html


# ── Real SMTP delivery ──────────────────────────────────────────────────────

async def test_manual_scan_report_is_delivered_and_recorded(client, settings, smtp, db):
    enable(settings, smtp.port)
    did = await upload(client)
    sid = (await scan(client, did))["scan_id"]
    smtp.messages.clear(); smtp.envelopes.clear()                   # ignore the automatic one
    r = await client.post(f"/api/scans/{sid}/report")
    assert r.status_code == 201
    info = r.json()
    assert (info["status"], info["attempts"], info["trigger"], info["kind"]) == ("sent", 1, "manual", "scan")
    assert info["recipient_masked"] == "o***@example.com" and info["sent_at"] and info["error_message"] is None
    assert len(smtp.messages) == 1
    msg = smtp.messages[0]
    assert msg["From"] == "janitor@example.com" and msg["To"] == "owner@example.com"
    assert msg["Subject"].startswith("DataJanitor scan report:") and msg["Message-ID"] and msg["Date"]
    assert msg.is_multipart() and msg.get_content_type() == "multipart/alternative"
    assert list(msg.iter_attachments()) == []
    text, html = bodies(msg)
    assert sid in text and did in text and MARKER not in text + html and "Carol" not in text + html
    assert "<table" in html
    assert [r.upper() for r in smtp.envelopes[0][1]] == ["RCPT TO:<OWNER@EXAMPLE.COM>"]
    events = [a.event_type for a in db.scalars(select(AuditRow).order_by(AuditRow.id))]
    assert "report_sent" in events


async def test_automatic_reports_after_scan_plan_and_cleaning(client, settings, smtp):
    enable(settings, smtp.port)
    did = await upload(client)
    await scan(client, did)
    assert len(smtp.messages) == 1 and smtp.messages[0]["Subject"].startswith("DataJanitor scan report")
    cid = await cleaned_run(client, did)                  # plan creation (scan) + apply (cleaning)
    subjects = [m["Subject"] for m in smtp.messages]
    assert len(subjects) == 3
    assert subjects[1].startswith("DataJanitor scan report") and subjects[2].startswith("DataJanitor cleaning report")
    reports = (await client.get("/api/email-reports")).json()
    assert reports["total"] == 3 and {r["trigger"] for r in reports["reports"]} == {"auto"}
    assert {r["kind"] for r in reports["reports"]} == {"scan", "cleaning"}
    assert [r for r in reports["reports"] if r["kind"] == "cleaning"][0]["cleaned_id"] == cid
    cleaning_msg = smtp.messages[2]
    text, _ = bodies(cleaning_msg)
    assert "FINAL VALIDATION" in text and MARKER not in text
    attachments = [part for part in cleaning_msg.iter_attachments()]
    assert len(attachments) == 1
    attachment = attachments[0]
    assert attachment.get_content_type() == "text/csv"
    assert attachment.get_filename().startswith("datajanitor_cleaned_")
    assert attachment.get_filename().endswith(".csv")
    attached_csv = attachment.get_payload(decode=True).decode("utf-8-sig")
    assert "Alice Smith" in attached_csv and "ZEBRA-QUOKKA-77" in attached_csv
    assert ", alice smith" not in attached_csv  # approved whitespace repair applied


async def test_no_email_for_a_failed_scan(client, settings, smtp, monkeypatch):
    enable(settings, smtp.port)
    did = await upload(client)
    monkeypatch.setattr(detection_service, "run_detection", lambda df: (_ for _ in ()).throw(RuntimeError("x")))
    with pytest.raises(RuntimeError):
        await client.post(f"/api/datasets/{did}/scan")
    assert smtp.messages == [] and (await client.get("/api/email-reports")).json()["total"] == 0


# ── Failures never lose results ─────────────────────────────────────────────

async def test_smtp_server_down_does_not_affect_the_scan(client, settings, db):
    enable(settings, free_port())                          # nothing is listening there
    did = await upload(client)
    body = await scan(client, did)                         # still a full 200 response
    assert body["status"] == "completed" and body["summary"]["total_issues"] > 0
    scan_row = db.get(ScanRow, body["scan_id"])
    assert scan_row.status == "completed" and scan_row.issue_total == body["summary"]["total_issues"]
    rep = db.scalars(select(EmailReportRow)).one()
    db.refresh(rep)
    assert (rep.status, rep.attempts) == ("failed", 1)
    assert rep.error_message == "Could not connect to the SMTP server (timeout or network error)."
    assert "report_failed" in [a.event_type for a in db.scalars(select(AuditRow))]


async def test_recipient_refused_and_data_failure_messages_are_safe(client, settings, smtp):
    enable(settings, smtp.port)
    did = await upload(client)
    sid = (await scan(client, did))["scan_id"]
    smtp.reject_recipients = True
    a = (await client.post(f"/api/scans/{sid}/report")).json()
    assert a["status"] == "failed" and a["error_message"] == "The SMTP server refused the recipient address."
    smtp.reject_recipients, smtp.fail_data = False, True
    b = (await client.post(f"/api/scans/{sid}/report")).json()
    assert b["status"] == "failed" and b["error_message"] == "The SMTP server returned an error (code 554)."
    assert "secret-server-detail" not in a["error_message"] + b["error_message"]


async def test_unexpected_errors_are_contained_and_recorded(client, settings, monkeypatch, db):
    enable(settings, 2525)
    monkeypatch.setattr(email_service, "deliver", lambda cfg, msg: (_ for _ in ()).throw(RuntimeError("boom")))
    did = await upload(client)
    body = await scan(client, did)
    assert body["status"] == "completed"
    rep = db.scalars(select(EmailReportRow)).one()
    db.refresh(rep)
    assert rep.status == "failed" and rep.error_message == "Unexpected error while sending the report."


async def test_a_crash_while_building_the_automatic_report_is_swallowed(client, settings, monkeypatch, caplog):
    enable(settings, 2525)
    monkeypatch.setattr(email_service, "send_report", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    did = await upload(client)
    with caplog.at_level(logging.ERROR, logger="datajanitor.email"):
        body = await scan(client, did)
    assert body["status"] == "completed"
    assert any("could not be processed" in r.message for r in caplog.records)


# ── Retry ───────────────────────────────────────────────────────────────────

async def test_failed_report_can_be_retried_until_sent(client, settings, smtp):
    enable(settings, smtp.port)
    did = await upload(client)
    sid = (await scan(client, did))["scan_id"]
    smtp.reject_recipients = True
    failed = (await client.post(f"/api/scans/{sid}/report")).json()
    smtp.reject_recipients = False
    before = len(smtp.messages)
    again = await client.post(f"/api/email-reports/{failed['report_id']}/retry")
    assert again.status_code == 200
    assert (again.json()["status"], again.json()["attempts"]) == ("sent", 2)
    assert len(smtp.messages) == before + 1
    twice = await client.post(f"/api/email-reports/{failed['report_id']}/retry")
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "report_already_sent"
    assert (await client.post(f"/api/email-reports/{'a' * 32}/retry")).status_code == 404
    one = (await client.get(f"/api/email-reports/{failed['report_id']}")).json()
    assert one["status"] == "sent" and one["attempts"] == 2


async def test_misconfigured_email_is_skipped_then_retried_after_fixing(client, settings, smtp):
    enable(settings, smtp.port, smtp_host="")                         # enabled but incomplete
    did = await upload(client)
    await scan(client, did)
    rep = (await client.get("/api/email-reports")).json()["reports"][0]
    assert rep["status"] == "skipped" and "not fully configured" in rep["error_message"]
    still = await client.post(f"/api/email-reports/{rep['report_id']}/retry")
    assert still.status_code == 409 and still.json()["error"]["code"] == "email_not_configured"
    enable(settings, smtp.port)
    fixed = (await client.post(f"/api/email-reports/{rep['report_id']}/retry")).json()
    assert fixed["status"] == "sent" and len(smtp.messages) == 1


async def test_report_history_filters_paging_and_stats(client, settings, smtp):
    enable(settings, smtp.port)
    did = await upload(client)
    sid = (await scan(client, did))["scan_id"]
    smtp.fail_data = True
    await client.post(f"/api/scans/{sid}/report")
    smtp.fail_data = False
    assert (await client.get("/api/email-reports", params={"status": "failed"})).json()["total"] == 1
    assert (await client.get("/api/email-reports", params={"status": "sent"})).json()["total"] == 1
    assert (await client.get("/api/email-reports", params={"kind": "cleaning"})).json()["total"] == 0
    assert (await client.get("/api/email-reports", params={"dataset_id": did, "limit": 1})).json()["reports"].__len__() == 1
    assert (await client.get("/api/email-reports", params={"status": "weird"})).status_code == 422
    assert (await client.get("/api/stats")).json()["email_reports"] == {"failed": 1, "sent": 1}


# ── TLS / authentication paths (SMTP class replaced to observe the calls) ───

class FakeSMTP:
    instances = []
    login_error = None
    ssl_error = None

    def __init__(self, host, port, timeout=None, context=None):
        self.host, self.port, self.timeout, self.context = host, port, timeout, context
        self.calls, self.sent = [], []
        FakeSMTP.instances.append(self)
        if FakeSMTP.ssl_error:
            raise FakeSMTP.ssl_error

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, context=None):
        self.calls.append("starttls")
        self.tls_context = context

    def login(self, user, password):
        self.calls.append(("login", user, password))
        if FakeSMTP.login_error:
            raise FakeSMTP.login_error

    def send_message(self, msg):
        self.calls.append("send")
        self.sent.append(msg)


@pytest.fixture
def fake_smtp(monkeypatch):
    FakeSMTP.instances, FakeSMTP.login_error, FakeSMTP.ssl_error = [], None, None
    monkeypatch.setattr(email_service.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


async def test_starttls_verifies_certificates_and_logs_in(client, settings, fake_smtp):
    enable(settings, 587, smtp_host="smtp.example.com", smtp_security="starttls",
           smtp_user="me@example.com", smtp_password=PASSWORD, smtp_timeout_seconds=7)
    did = await upload(client)
    await scan(client, did)
    s = fake_smtp.instances[0]
    assert (s.host, s.port, s.timeout) == ("smtp.example.com", 587, 7)
    assert s.calls == ["ehlo", "starttls", "ehlo", ("login", "me@example.com", PASSWORD), "send"]
    assert s.tls_context.verify_mode == ssl.CERT_REQUIRED and s.tls_context.check_hostname is True


async def test_ssl_mode_uses_a_verifying_context(client, settings, fake_smtp):
    enable(settings, 465, smtp_host="smtp.example.com", smtp_security="ssl")
    did = await upload(client)
    await scan(client, did)
    s = fake_smtp.instances[0]
    assert "starttls" not in s.calls and s.calls[-1] == "send"
    assert s.context.verify_mode == ssl.CERT_REQUIRED and s.context.check_hostname is True


async def test_login_failure_never_exposes_credentials_or_server_text(client, settings, fake_smtp, caplog, db):
    enable(settings, 587, smtp_host="smtp.example.com", smtp_security="starttls",
           smtp_user="me@example.com", smtp_password=PASSWORD)
    fake_smtp.login_error = smtplib.SMTPAuthenticationError(535, b"bad credentials secret-server-text")
    did = await upload(client)
    with caplog.at_level(logging.DEBUG):
        await scan(client, did)
    rep = (await client.get("/api/email-reports")).json()["reports"][0]
    assert rep["status"] == "failed" and rep["error_message"] == "SMTP login was rejected (code 535)."
    everything = repr(rep) + " ".join(str(a.details) for a in db.scalars(select(AuditRow))) + caplog.text
    assert PASSWORD not in everything and "secret-server-text" not in everything
    assert not any(c[0] == "send" for c in fake_smtp.instances[0].calls if isinstance(c, tuple))


@pytest.mark.parametrize("exc,message", [
    (ssl.SSLCertVerificationError("certificate verify failed"), "A secure (TLS) connection"),
    (TimeoutError("timed out"), "Could not connect to the SMTP server"),
    (ConnectionRefusedError(), "Could not connect to the SMTP server"),
    (smtplib.SMTPServerDisconnected("gone"), "The SMTP server reported an error."),
])
async def test_connection_errors_are_translated(client, settings, fake_smtp, exc, message):
    enable(settings, 587, smtp_host="smtp.example.com", smtp_security="starttls")
    fake_smtp.ssl_error = exc
    did = await upload(client)
    await scan(client, did)
    rep = (await client.get("/api/email-reports")).json()["reports"][0]
    assert rep["status"] == "failed" and rep["error_message"].startswith(message)


# ── Composition ─────────────────────────────────────────────────────────────

async def test_message_has_no_header_injection_surface(client, settings, smtp):
    enable(settings, smtp.port)
    did = await upload(client, name="x.csv")
    sid = (await scan(client, did))["scan_id"]
    msg = smtp.messages[0]
    for header in ("Subject", "From", "To"):
        assert "\n" not in str(msg[header]) and "\r" not in str(msg[header])
    assert msg["Bcc"] is None and msg["Cc"] is None
    assert str(msg["Message-ID"]).endswith("@example.com>")
