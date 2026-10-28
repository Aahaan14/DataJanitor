"""
DataJanitor — Phase 6 API tests: generating, verifying, recording and
downloading cleaned datasets.
"""

import csv
import io

import pandas as pd
import pytest
from sqlalchemy import select

from app.models.records import AuditRow, CleanedRow, OutcomeRow
from app.services import repair_service

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


def rows_of(data: bytes):
    return list(csv.reader(io.StringIO(data.decode("utf-8-sig"), newline="")))


async def upload(client, csv_text=CSV, name="d.csv"):
    r = await client.post("/api/datasets/upload", files={"file": (name, csv_text.encode(), "text/csv")})
    assert r.status_code == 201, r.text
    return r.json()["dataset_id"]


async def make_plan(client, csv_text=CSV, body=None, name="d.csv"):
    did = await upload(client, csv_text, name)
    r = await client.post(f"/api/datasets/{did}/repair-plan", json=body) if body else \
        await client.post(f"/api/datasets/{did}/repair-plan")
    assert r.status_code == 201, r.text
    return did, r.json()["plan_id"]


async def props(client, pid, **params):
    r = await client.get(f"/api/repair-plans/{pid}/proposals", params={"limit": 1000, **params})
    return r.json()["proposals"]


def pick(ps, issue_type, row=None):
    return next(p for p in ps if p["issue_type"] == issue_type and (row is None or p["row_number"] == row))


async def decide(client, pid, prop_id, decision, value=None):
    body = {"decision": decision, **({"chosen_value": value} if value is not None else {})}
    return await client.post(f"/api/repair-plans/{pid}/proposals/{prop_id}/decision", json=body)


async def apply(client, pid):
    return await client.post(f"/api/repair-plans/{pid}/apply")


async def download(client, cid, mode="raw"):
    return await client.get(f"/api/cleaned/{cid}/download", params={"mode": mode})


# ── Core guarantees ─────────────────────────────────────────────────────────

async def test_apply_changes_only_approved_cells_and_preserves_the_original(client, settings):
    did, pid = await make_plan(client)
    original_path = settings.upload_path / f"{did}.csv"
    before = original_path.read_bytes()
    ps = await props(client, pid)
    await decide(client, pid, pick(ps, "whitespace", 4)["proposal_id"], "approve")        # name row 4
    await decide(client, pid, pick(ps, "exact_duplicate")["proposal_id"], "approve")      # delete row 6
    r = await apply(client, pid)
    assert r.status_code == 201
    summary = r.json()
    assert (summary["status"], summary["applied_count"], summary["skipped_count"]) == ("completed", 2, 0)
    assert (summary["rows_before"], summary["rows_after"], summary["rows_deleted"]) == (6, 5, 1)
    assert summary["cells_changed"] == 1
    assert original_path.read_bytes() == before                                           # original untouched

    got = rows_of((await download(client, summary["cleaned_id"])).content)
    expected = rows_of(CSV.encode())
    expected[4][1] = "alice smith"        # 1-based row 4 → list index 4 (header at 0)
    del expected[6]                        # exact duplicate row 6
    assert got == expected                 # every other cell identical, byte-for-value


async def test_rejected_and_pending_proposals_never_modify_the_data(client):
    did, pid = await make_plan(client)
    ps = await props(client, pid)
    approved = pick(ps, "numeric_format")
    await decide(client, pid, approved["proposal_id"], "approve")
    for p in ps:
        if p["proposal_id"] != approved["proposal_id"] and p["issue_type"] in ("whitespace", "exact_duplicate"):
            assert (await decide(client, pid, p["proposal_id"], "reject")).status_code == 200
    summary = (await apply(client, pid)).json()
    assert summary["applied_count"] == 1 and summary["rejected_count"] == 2
    assert summary["pending_count"] == len(ps) - 3
    got = rows_of((await download(client, summary["cleaned_id"])).content)
    expected = rows_of(CSV.encode())
    expected[5][5] = "1200"               # the ONLY difference: salary on row 5
    assert got == expected


async def test_unreviewed_plan_cannot_be_applied(client, db, settings):
    _, pid = await make_plan(client)
    r = await apply(client, pid)
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_approved_repairs"
    assert db.query(CleanedRow).count() == 0
    assert not settings.cleaned_path.exists() or list(settings.cleaned_path.glob("*")) == []


async def test_all_rejected_also_cannot_be_applied(client):
    _, pid = await make_plan(client)
    for p in await props(client, pid):
        await decide(client, pid, p["proposal_id"], "reject")
    assert (await apply(client, pid)).status_code == 422


async def test_custom_and_alternative_choices_end_up_in_the_file(client):
    _, pid = await make_plan(client, body=RULES)
    ps = await props(client, pid)
    bad_age = pick(ps, "invalid_numeric")
    await decide(client, pid, bad_age["proposal_id"], "approve", "35")                     # typed correction
    date = pick(ps, "inconsistent_date_format", 2)
    await decide(client, pid, date["proposal_id"], "approve", date["alternatives"][0])     # chosen reading
    bad_date = pick(ps, "invalid_date")
    await decide(client, pid, bad_date["proposal_id"], "approve")                          # clear cell
    s = (await apply(client, pid)).json()
    got = rows_of((await download(client, s["cleaned_id"])).content)
    assert got[5][2] == "35" and got[2][3] == date["alternatives"][0] and got[3][3] == ""


# ── Outcomes (applied / rejected / skipped / pending) ───────────────────────

async def test_every_proposal_gets_an_outcome_row(client, db):
    _, pid = await make_plan(client)
    ps = await props(client, pid)
    await decide(client, pid, pick(ps, "numeric_format")["proposal_id"], "approve")
    await decide(client, pid, pick(ps, "exact_duplicate")["proposal_id"], "reject")
    s = (await apply(client, pid)).json()
    page = (await client.get(f"/api/cleaned/{s['cleaned_id']}/outcomes", params={"limit": 1000})).json()
    assert page["total"] == len(ps)
    kinds = {o["proposal_id"]: o["outcome"] for o in page["outcomes"]}
    assert sorted(set(kinds.values())) == ["applied", "pending", "rejected"]
    rej = (await client.get(f"/api/cleaned/{s['cleaned_id']}/outcomes", params={"outcome": "rejected"})).json()
    assert rej["total"] == 1 and rej["outcomes"][0]["reason"] == "rejected by reviewer"
    assert (await client.get(f"/api/cleaned/{s['cleaned_id']}/outcomes", params={"outcome": "nope"})).status_code == 422
    assert db.query(OutcomeRow).filter_by(cleaned_id=s["cleaned_id"]).count() == len(ps)


async def test_a_skipped_repair_is_reported_not_silently_dropped(client, monkeypatch):
    _, pid = await make_plan(client)
    ps = await props(client, pid)
    await decide(client, pid, pick(ps, "numeric_format")["proposal_id"], "approve")
    original = repair_service.apply_repairs

    def stale_reviewed_value(df, approved):
        for p in approved:
            p.original_value = "a different value"   # simulate: cell no longer matches review
        return original(df, approved)
    monkeypatch.setattr(repair_service, "apply_repairs", stale_reviewed_value)
    s = (await apply(client, pid)).json()
    assert (s["applied_count"], s["skipped_count"], s["cells_changed"]) == (0, 1, 0)
    skipped = (await client.get(f"/api/cleaned/{s['cleaned_id']}/outcomes", params={"outcome": "skipped"})).json()
    assert "no longer matches" in skipped["outcomes"][0]["reason"]
    assert rows_of((await download(client, s["cleaned_id"])).content) == rows_of(CSV.encode())


# ── Verification and final validation ───────────────────────────────────────

async def test_final_validation_matches_a_fresh_scan_of_the_cleaned_file(client):
    _, pid = await make_plan(client, body=RULES)
    ps = await props(client, pid)
    await client.post(f"/api/repair-plans/{pid}/approve-safe")
    await decide(client, pid, pick(ps, "exact_duplicate")["proposal_id"], "approve")
    s = (await apply(client, pid)).json()
    v = s["validation"]
    assert v["status"] == "issues_remaining" and v["remaining_issue_count"] > 0
    assert v["rule_count"] == 1
    # A real side effect the check is designed to surface: deleting the duplicate
    # "Alice Smith" row leaves one "Alice Smith" and one "alice smith" — a tie, so
    # BOTH rows are now flagged where only one was before.
    assert v["increased_issue_types"] == ["inconsistent_text_format"]
    assert v["before_by_type"]["inconsistent_text_format"] < v["remaining_by_type"]["inconsistent_text_format"]
    assert "exact_duplicate" not in v["remaining_by_type"]
    assert v["before_by_type"]["exact_duplicate"] == 1
    cleaned_bytes = (await download(client, s["cleaned_id"])).content
    did2 = await upload(client, cleaned_bytes.decode("utf-8-sig"), "again.csv")
    rescan = (await client.post(f"/api/datasets/{did2}/scan")).json()
    assert rescan["summary"]["total_issues"] == v["remaining_issue_count"]   # independent confirmation
    assert rescan["summary"]["by_type"] == v["remaining_by_type"]


async def test_no_regressions_reported_when_repairs_only_remove_problems(client):
    _, pid = await make_plan(client)
    await client.post(f"/api/repair-plans/{pid}/approve-safe")          # trims + number format only
    v = (await apply(client, pid)).json()["validation"]
    assert v["increased_issue_types"] == []
    assert v["remaining_issue_count"] < sum(v["before_by_type"].values())


async def test_clean_data_reports_passed(client):
    _, pid = await make_plan(client, "id,name\n1, Al\n2,Bo\n3,Cy\n")
    await client.post(f"/api/repair-plans/{pid}/approve-safe")
    s = (await apply(client, pid)).json()
    assert s["validation"]["status"] == "passed" and s["validation"]["remaining_issue_count"] == 0


async def test_unintended_change_blocks_the_output(client, db, settings, monkeypatch):
    _, pid = await make_plan(client)
    await decide(client, pid, pick(await props(client, pid), "numeric_format")["proposal_id"], "approve")
    original = repair_service.apply_repairs

    def buggy(df, approved):
        res = original(df, approved)
        res.cleaned.at[0, "name"] = "CORRUPTED"          # a cell nobody approved
        return res
    monkeypatch.setattr(repair_service, "apply_repairs", buggy)
    r = await apply(client, pid)
    assert r.status_code == 500 and r.json()["error"]["code"] == "output_integrity_error"
    run = db.scalars(select(CleanedRow)).one()
    assert run.status == "failed" and run.sha256 is None
    assert list(settings.cleaned_path.glob("*.csv")) == []                       # nothing saved
    assert "cleaned_failed" in [a.event_type for a in db.scalars(select(AuditRow))]


# ── Plan state, history, audit ──────────────────────────────────────────────

async def test_stale_or_superseded_plan_cannot_be_applied(client, settings):
    did, pid = await make_plan(client)
    await decide(client, pid, pick(await props(client, pid), "numeric_format")["proposal_id"], "approve")
    await client.post(f"/api/datasets/{did}/repair-plan")                       # supersedes pid
    r = await apply(client, pid)
    assert r.status_code == 409 and r.json()["error"]["code"] == "plan_superseded"
    did2, pid2 = await make_plan(client)
    await decide(client, pid2, pick(await props(client, pid2), "numeric_format")["proposal_id"], "approve")
    path = settings.upload_path / f"{did2}.csv"
    path.write_bytes(path.read_bytes() + b"9,Z,1,2024-01-01,Pune,1\n")
    assert (await apply(client, pid2)).status_code == 409


async def test_unknown_ids(client):
    assert (await client.post(f"/api/repair-plans/{'a' * 32}/apply")).status_code == 404
    for path in ("", "/outcomes", "/download"):
        r = await client.get(f"/api/cleaned/{'a' * 32}{path}")
        assert r.status_code == 404 and r.json()["error"]["code"] == "cleaned_not_found"
    assert (await client.get("/api/cleaned/../../etc/passwd")).status_code in (404, 422)


async def test_applying_twice_creates_two_independent_runs(client):
    _, pid = await make_plan(client)
    ps = await props(client, pid)
    await decide(client, pid, pick(ps, "numeric_format")["proposal_id"], "approve")
    first = (await apply(client, pid)).json()
    await decide(client, pid, pick(ps, "whitespace", 4)["proposal_id"], "approve")
    second = (await apply(client, pid)).json()
    assert first["cleaned_id"] != second["cleaned_id"]
    assert (first["applied_count"], second["applied_count"]) == (1, 2)
    listing = (await client.get(f"/api/repair-plans/{pid}/cleaned")).json()
    assert [c["cleaned_id"] for c in listing] == [second["cleaned_id"], first["cleaned_id"]]
    # the first file is unchanged by the second run
    assert rows_of((await download(client, first["cleaned_id"])).content)[4][1] == "alice smith "


async def test_runs_are_audited_without_cell_values(client, db):
    _, pid = await make_plan(client)
    await decide(client, pid, pick(await props(client, pid), "numeric_format")["proposal_id"], "approve")
    s = (await apply(client, pid)).json()
    await download(client, s["cleaned_id"])
    events = [a.event_type for a in db.scalars(select(AuditRow).order_by(AuditRow.id))]
    assert events[-3:] == ["cleaned_started", "cleaned_generated", "cleaned_downloaded"]
    blob = " ".join(str(a.details) for a in db.scalars(select(AuditRow)))
    assert "1,200" not in blob and "Alice" not in blob


async def test_stats_include_cleaned_runs(client):
    _, pid = await make_plan(client)
    await decide(client, pid, pick(await props(client, pid), "numeric_format")["proposal_id"], "approve")
    await apply(client, pid)
    assert (await client.get("/api/stats")).json()["cleaned_datasets"] == {"completed": 1}


# ── Download: formula injection, headers, availability ──────────────────────

EVIL = (
    "id,name,qty,phone\n"
    "1,=HYPERLINK(\"http://evil.test\"),-5,+91 98765 43210\n"
    "2, padded,7,@SUM(A1)\n"
    "3,fine,+3,-2+3\n"
)


async def evil_cleaned(client):
    _, pid = await make_plan(client, EVIL, name="my data (v1).csv")
    ps = await props(client, pid)
    await decide(client, pid, pick(ps, "whitespace")["proposal_id"], "approve")
    return (await apply(client, pid)).json()["cleaned_id"]


async def test_download_safe_mode_neutralises_formulas_but_keeps_numbers(client):
    cid = await evil_cleaned(client)
    r = await download(client, cid, "safe")
    rows = rows_of(r.content)
    assert rows[1][1] == "'=HYPERLINK(\"http://evil.test\")"
    assert rows[1][2] == "-5" and rows[3][2] == "+3"                 # real numbers untouched
    assert rows[1][3] == "'+91 98765 43210" and rows[2][3] == "'@SUM(A1)" and rows[3][3] == "'-2+3"
    assert rows[2][1] == "padded"                                    # approved repair still applied
    assert r.headers["x-datajanitor-mode"] == "safe" and int(r.headers["x-datajanitor-cells-escaped"]) == 4


async def test_download_is_safe_by_default_and_raw_keeps_exact_values(client):
    cid = await evil_cleaned(client)
    default = await client.get(f"/api/cleaned/{cid}/download")
    assert default.headers["x-datajanitor-mode"] == "safe"
    raw = await download(client, cid, "raw")
    assert rows_of(raw.content)[1][1] == '=HYPERLINK("http://evil.test")'
    assert raw.headers["x-datajanitor-cells-escaped"] == "0"
    assert (await client.get(f"/api/cleaned/{cid}/download", params={"mode": "evil"})).status_code == 422


async def test_download_headers_are_safe(client):
    cid = await evil_cleaned(client)
    r = await download(client, cid)
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="my_data_(v1)_cleaned.csv"'
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["cache-control"] == "no-store"
    assert r.content.startswith(b"\xef\xbb\xbf")


async def test_tampered_cleaned_file_is_refused(client, settings):
    cid = await evil_cleaned(client)
    path = settings.cleaned_path / f"{cid}.csv"
    path.write_bytes(path.read_bytes() + b"9,x,x,x\r\n")
    r = await download(client, cid)
    assert r.status_code == 500 and r.json()["error"]["code"] == "output_integrity_error"


async def test_deleting_the_dataset_removes_cleaned_copies(client, db, settings):
    did, pid = await make_plan(client)
    await decide(client, pid, pick(await props(client, pid), "numeric_format")["proposal_id"], "approve")
    cid = (await apply(client, pid)).json()["cleaned_id"]
    assert (settings.cleaned_path / f"{cid}.csv").exists()
    assert (await client.delete(f"/api/datasets/{did}")).status_code == 204
    assert not (settings.cleaned_path / f"{cid}.csv").exists()
    r = await download(client, cid)
    assert r.status_code == 410 and r.json()["error"]["code"] == "cleaned_unavailable"
    assert (await client.get(f"/api/cleaned/{cid}")).json()["status"] == "deleted"   # record kept
    assert (await apply(client, pid)).status_code == 409                              # plan went stale


async def test_semicolon_and_latin1_files_keep_their_delimiter(client):
    raw = "n;city\n José;Málaga\nZoë;Zürich\n".encode("cp1252")
    did = (await client.post("/api/datasets/upload", files={"file": ("e.csv", raw, "text/csv")})).json()["dataset_id"]
    pid = (await client.post(f"/api/datasets/{did}/repair-plan")).json()["plan_id"]
    await client.post(f"/api/repair-plans/{pid}/approve-safe")
    cid = (await apply(client, pid)).json()["cleaned_id"]
    text = (await download(client, cid, "raw")).content.decode("utf-8-sig")
    assert text == "n;city\r\nJosé;Málaga\r\nZoë;Zürich\r\n"
