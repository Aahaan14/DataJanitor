"""
DataJanitor — Phase 5 tests: persistence, scan history, audit trail,
dataset lifecycle, failure handling.
"""

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from app.config import get_settings
from app.database.base import make_engine
from app.database.init_db import SCHEMA_VERSION, SchemaVersionError, init_schema
from app.main import create_app
from app.models.records import (
    AuditRow, DatasetRow, DecisionRow, IssueRow, PlanRow, ProposalRow, RuleRow, ScanRow,
)
from app.services import dataset_service, detection_service

CSV = (
    "id,name,age,joined,city,salary\n"
    "1,Alice Smith,30,2024-01-05,Mumbai,50000\n"
    "2,Bob,,05/02/2024,mumbai,52000\n"
    "3,Carol,41,2024-02-30,Mumbai,51000\n"
    "4,alice smith ,30,2024-01-05,Mumbai,50000\n"
    "5,Dan,abc,2024-03-01,Pune,\"1,200\"\n"
    "1,Alice Smith,30,2024-01-05,Mumbai,50000\n"
)
RULES = {"rules": {"rules": [{"column": "age", "dtype": "integer", "min_value": 0, "max_value": 120}]}}


async def upload(client, csv=CSV):
    r = await client.post("/api/datasets/upload", files={"file": ("d.csv", csv.encode(), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()["dataset_id"]


async def make_plan(client, body=None):
    did = await upload(client)
    r = await client.post(f"/api/datasets/{did}/repair-plan", json=body) if body else \
        await client.post(f"/api/datasets/{did}/repair-plan")
    assert r.status_code == 201, r.text
    return did, r.json()


async def proposals(client, plan_id, **params):
    r = await client.get(f"/api/repair-plans/{plan_id}/proposals", params={"limit": 1000, **params})
    return r.json()["proposals"]


def events(db):
    return [r.event_type for r in db.scalars(select(AuditRow).order_by(AuditRow.id))]


# ── Schema initialisation ───────────────────────────────────────────────────

def test_init_schema_creates_tables_and_is_idempotent(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'x.db'}")
    assert init_schema(engine) == SCHEMA_VERSION
    assert init_schema(engine) == SCHEMA_VERSION
    with engine.connect() as c:
        tables = {r[0] for r in c.execute(text("select name from sqlite_master where type='table'"))}
    assert {"datasets", "scans", "issues", "repair_plans", "validation_rules",
            "repair_proposals", "decisions", "audit_logs", "schema_info"} <= tables
    engine.dispose()


def test_schema_version_mismatch_is_refused(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'x.db'}")
    init_schema(engine)
    with engine.begin() as c:
        c.execute(text("update schema_info set value='999' where key='schema_version'"))
    with pytest.raises(SchemaVersionError):
        init_schema(engine)
    engine.dispose()


def test_foreign_keys_are_enforced(db):
    db.add(ProposalRow(id="Rx", plan_id="f" * 32, seq=0, issue_id="I1", issue_type="x",
                       action="x", classification="safe", confidence="high", reason="r"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# ── Uploads are recorded (metadata only) ────────────────────────────────────

async def test_upload_creates_dataset_row_with_hash_and_audit(client, db, settings):
    did = await upload(client)
    row = db.get(DatasetRow, did)
    assert row.status == "active" and row.original_filename == "d.csv"
    assert row.row_count == 6 and row.column_count == 6
    assert row.sha256 == dataset_service.sha256_hex((settings.upload_path / f"{did}.csv").read_bytes())
    assert row.uploaded_at.tzinfo is not None  # timezone-aware UTC
    assert "dataset_uploaded" in events(db)


async def test_database_stores_no_dataset_contents(client, db, app):
    marker = "ZEBRA-QUOKKA-77"
    did = await upload(client, f"id,note\n1,{marker}\n2,fine\n3,fine\n")
    await client.post(f"/api/datasets/{did}/scan")
    raw_db = open(app.state.engine.url.database, "rb").read()
    assert marker.encode() not in raw_db


async def test_upload_db_failure_removes_file_and_reports_cleanly(client, settings, monkeypatch):
    def boom(*a, **k):
        raise OperationalError("insert", {}, Exception("disk I/O error /secret/path"))
    monkeypatch.setattr(dataset_service, "register_upload", boom)
    r = await client.post("/api/datasets/upload", files={"file": ("d.csv", CSV.encode(), "text/csv")})
    assert r.status_code == 500 and r.json()["error"]["code"] == "database_error"
    assert "secret" not in r.text and "disk I/O" not in r.text
    assert list(settings.upload_path.glob("*.csv")) == []


# ── Scan history ────────────────────────────────────────────────────────────

async def test_scan_is_persisted_with_issues_and_summary(client, db):
    did = await upload(client)
    body = (await client.post(f"/api/datasets/{did}/scan")).json()
    scan = db.get(ScanRow, body["scan_id"])
    assert scan.status == "completed" and scan.dataset_id == did
    assert scan.issue_total == body["summary"]["total_issues"] > 0
    assert scan.completed_at >= scan.started_at
    assert db.query(IssueRow).filter_by(scan_id=scan.id).count() == scan.stored_issue_count
    assert events(db)[-2:] == ["scan_started", "scan_completed"]


async def test_scan_history_endpoints(client):
    did = await upload(client)
    a = (await client.post(f"/api/datasets/{did}/scan")).json()["scan_id"]
    b = (await client.post(f"/api/datasets/{did}/scan")).json()["scan_id"]
    hist = (await client.get("/api/scans", params={"dataset_id": did})).json()
    assert hist["total"] == 2 and [s["scan_id"] for s in hist["scans"]] == [b, a]  # newest first
    one = (await client.get(f"/api/scans/{a}")).json()
    assert one["status"] == "completed" and one["summary"]["total_issues"] == one["issue_total"]
    only_failed = (await client.get("/api/scans", params={"status": "failed"})).json()
    assert only_failed["total"] == 0
    assert (await client.get("/api/scans", params={"status": "weird"})).status_code == 422


async def test_scan_issues_endpoint_filters_and_pages(client):
    did = await upload(client)
    sid = (await client.post(f"/api/datasets/{did}/scan")).json()["scan_id"]
    allr = (await client.get(f"/api/scans/{sid}/issues", params={"limit": 1000})).json()
    assert allr["total"] == len(allr["issues"]) > 3
    dates = (await client.get(f"/api/scans/{sid}/issues", params={"issue_type": "invalid_date"})).json()
    assert dates["total"] == 1 and dates["issues"][0]["status"] == "detected"
    page = (await client.get(f"/api/scans/{sid}/issues", params={"limit": 2, "offset": 1})).json()
    assert len(page["issues"]) == 2 and page["total"] == allr["total"]


async def test_unknown_scan_404(client):
    assert (await client.get(f"/api/scans/{'a' * 32}")).status_code == 404
    assert (await client.get("/api/scans/nope")).status_code == 404


async def test_stored_issues_capped_but_total_kept(client, db, settings):
    settings.max_issues_returned = 2
    did = await upload(client)
    body = (await client.post(f"/api/datasets/{did}/scan")).json()
    scan = db.get(ScanRow, body["scan_id"])
    assert scan.stored_issue_count == 2 and scan.truncated is True
    assert scan.issue_total > 2 and body["summary"]["total_issues"] == scan.issue_total


async def test_failed_scan_is_recorded_with_safe_message(client, db, monkeypatch):
    did = await upload(client)

    def boom(df):
        raise RuntimeError("secret internal detail /etc/passwd")
    monkeypatch.setattr(detection_service, "run_detection", boom)
    with pytest.raises(RuntimeError):
        await client.post(f"/api/datasets/{did}/scan")
    scan = db.scalars(select(ScanRow).where(ScanRow.dataset_id == did)).one()
    assert scan.status == "failed" and scan.completed_at is not None
    assert "secret" not in scan.error_message
    assert "scan_failed" in events(db)
    assert db.query(IssueRow).count() == 0  # nothing half-saved


async def test_tampered_file_is_refused_and_scan_marked_failed(client, db, settings):
    did = await upload(client)
    path = settings.upload_path / f"{did}.csv"
    path.write_bytes(path.read_bytes() + b"9,Zed,1,2024-01-01,Pune,1\n")
    r = await client.post(f"/api/datasets/{did}/scan")
    assert r.status_code == 409 and r.json()["error"]["code"] == "dataset_modified"
    scan = db.scalars(select(ScanRow).where(ScanRow.dataset_id == did)).one()
    assert scan.status == "failed"
    assert (await client.get("/api/scans", params={"status": "failed"})).json()["total"] == 1


# ── Plans and decisions survive a restart ───────────────────────────────────

async def test_plan_and_decisions_survive_application_restart(settings):
    app1 = create_app(settings, init_schema_now=True)
    app1.dependency_overrides[get_settings] = lambda: settings
    async with AsyncClient(transport=ASGITransport(app=app1), base_url="http://t") as c1:
        did, plan = await make_plan(c1, RULES)
        pid = plan["plan_id"]
        props = await proposals(c1, pid)
        num = next(p for p in props if p["issue_type"] == "numeric_format")
        rej = next(p for p in props if p["issue_type"] == "exact_duplicate")
        await c1.post(f"/api/repair-plans/{pid}/proposals/{num['proposal_id']}/decision",
                      json={"decision": "approve"})
        await c1.post(f"/api/repair-plans/{pid}/proposals/{rej['proposal_id']}/decision",
                      json={"decision": "reject"})
    app1.state.engine.dispose()

    app2 = create_app(settings, init_schema_now=True)  # "restart": brand-new app, same database
    app2.dependency_overrides[get_settings] = lambda: settings
    async with AsyncClient(transport=ASGITransport(app=app2), base_url="http://t") as c2:
        summary = (await c2.get(f"/api/repair-plans/{pid}")).json()
        assert summary["status"] == "active"
        assert summary["status_counts"]["approved"] == 1 and summary["status_counts"]["rejected"] == 1
        assert summary["validation"]["rule_count"] == 1
        approved = (await c2.get(f"/api/repair-plans/{pid}/approved")).json()
        assert [r["approved_value"] for r in approved["repairs"]] == ["1200"]
        rejected = await proposals(c2, pid, status="rejected")
        assert rejected[0]["proposal_id"] == rej["proposal_id"]  # rejection preserved
        assert rejected[0]["history"][0]["decision"] == "reject"
    app2.state.engine.dispose()


async def test_db_rows_keep_original_and_proposed_separate(client, db):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    num = next(p for p in await proposals(client, pid) if p["issue_type"] == "numeric_format")
    await client.post(f"/api/repair-plans/{pid}/proposals/{num['proposal_id']}/decision",
                      json={"decision": "approve"})
    row = db.get(ProposalRow, num["proposal_id"])
    assert (row.original_value, row.proposed_value, row.approved_value) == ("1,200", "1200", "1200")
    assert row.status == "approved" and row.decided_at.tzinfo is not None
    assert db.query(DecisionRow).filter_by(proposal_id=row.id).count() == 1


async def test_rules_are_stored_per_plan_and_decision_history_is_complete(client, db):
    _, plan = await make_plan(client, RULES)
    pid = plan["plan_id"]
    rules = db.scalars(select(RuleRow).where(RuleRow.plan_id == pid)).all()
    assert [(r.column_name, r.definition["max_value"]) for r in rules] == [("age", 120.0)]
    num = next(p for p in await proposals(client, pid) if p["issue_type"] == "numeric_format")
    url = f"/api/repair-plans/{pid}/proposals/{num['proposal_id']}/decision"
    for d in ("approve", "reject", "approve"):
        await client.post(url, json={"decision": d})
    assert [d.decision for d in db.scalars(
        select(DecisionRow).where(DecisionRow.proposal_id == num["proposal_id"]).order_by(DecisionRow.id)
    )] == ["approve", "reject", "approve"]


async def test_plan_scan_is_linked_in_history(client, db):
    did, plan = await make_plan(client)
    row = db.get(PlanRow, plan["plan_id"])
    assert db.get(ScanRow, row.scan_id).status == "completed"
    assert (await client.get("/api/scans", params={"dataset_id": did})).json()["total"] == 1


# ── Audit trail ─────────────────────────────────────────────────────────────

async def test_full_workflow_is_audited_in_order(client, db):
    did, plan = await make_plan(client)
    pid = plan["plan_id"]
    await client.post(f"/api/repair-plans/{pid}/approve-safe")
    assert events(db) == ["dataset_uploaded", "scan_started", "scan_completed", "plan_created",
                          "proposal_approved", "proposal_approved", "bulk_approve_safe"]


async def test_audit_details_never_contain_cell_values(client, db):
    _, plan = await make_plan(client)
    await client.post(f"/api/repair-plans/{plan['plan_id']}/approve-safe")
    blob = " ".join(str(r.details) for r in db.scalars(select(AuditRow)))
    for value in ("Alice", "1,200", "alice smith", "Mumbai"):
        assert value not in blob


async def test_audit_log_endpoint_filters_pages_and_orders(client):
    did, plan = await make_plan(client)
    await client.post(f"/api/repair-plans/{plan['plan_id']}/approve-safe")
    allr = (await client.get("/api/audit-logs", params={"limit": 500})).json()
    ids = [e["id"] for e in allr["entries"]]
    assert ids == sorted(ids, reverse=True)  # newest first
    approved = (await client.get("/api/audit-logs", params={"event_type": "proposal_approved"})).json()
    assert approved["total"] == 2 and all(e["plan_id"] == plan["plan_id"] for e in approved["entries"])
    by_ds = (await client.get("/api/audit-logs", params={"dataset_id": did})).json()
    assert by_ds["total"] == allr["total"]
    page = (await client.get("/api/audit-logs", params={"limit": 2, "offset": 1})).json()
    assert len(page["entries"]) == 2


async def test_superseding_a_plan_is_audited(client, db):
    did, plan = await make_plan(client)
    await client.post(f"/api/datasets/{did}/repair-plan")
    e = db.scalars(select(AuditRow).where(AuditRow.event_type == "plan_superseded")).one()
    assert e.plan_id == plan["plan_id"] and "superseded_by" in e.details


async def test_stale_plan_detection_is_audited_once(client, db, settings):
    did, plan = await make_plan(client)
    (settings.upload_path / f"{did}.csv").unlink()
    for _ in range(3):
        await client.get(f"/api/repair-plans/{plan['plan_id']}")
    assert events(db).count("plan_marked_stale") == 1


# ── Dataset lifecycle ───────────────────────────────────────────────────────

async def test_dataset_list_and_detail(client):
    did, plan = await make_plan(client)
    lst = (await client.get("/api/datasets")).json()
    assert lst["total"] == 1 and lst["datasets"][0]["dataset_id"] == did
    detail = (await client.get(f"/api/datasets/{did}")).json()
    assert detail["dataset"]["filename"] == "d.csv"
    assert len(detail["scans"]) == 1 and detail["plans"][0]["plan_id"] == plan["plan_id"]
    assert (await client.get("/api/datasets", params={"status": "deleted"})).json()["total"] == 0


async def test_delete_removes_file_keeps_history_and_stales_plans(client, db, settings):
    did, plan = await make_plan(client)
    pid = plan["plan_id"]
    r = await client.delete(f"/api/datasets/{did}")
    assert r.status_code == 204
    assert not (settings.upload_path / f"{did}.csv").exists()
    row = db.get(DatasetRow, did)
    db.refresh(row)
    assert row.status == "deleted" and row.file_removed_at is not None
    assert db.query(ScanRow).filter_by(dataset_id=did).count() == 1           # history kept
    assert db.query(ProposalRow).filter_by(plan_id=pid).count() > 0
    assert (await client.get(f"/api/repair-plans/{pid}")).json()["status"] == "stale"
    assert (await client.post(f"/api/datasets/{did}/scan")).status_code == 410
    assert (await client.post(f"/api/datasets/{did}/repair-plan")).status_code == 410
    assert (await client.get(f"/api/datasets/{did}")).json()["dataset"]["status"] == "deleted"
    assert "dataset_deleted" in events(db)
    assert (await client.delete(f"/api/datasets/{did}")).status_code == 410


async def test_delete_unknown_dataset_404(client):
    assert (await client.delete(f"/api/datasets/{'b' * 32}")).status_code == 404


async def test_stats_endpoint(client):
    empty = (await client.get("/api/stats")).json()
    assert empty["approval_rate"] is None and empty["issues_detected"] == 0
    did, plan = await make_plan(client)
    await client.post(f"/api/repair-plans/{plan['plan_id']}/approve-safe")
    s = (await client.get("/api/stats")).json()
    assert s["datasets"] == {"active": 1} and s["scans"] == {"completed": 1}
    assert s["plans"] == {"active": 1} and s["proposals"]["approved"] == 2
    assert s["issues_detected"] > 0 and s["approval_rate"] == 1.0
