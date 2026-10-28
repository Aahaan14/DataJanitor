"""
DataJanitor — Phase 4 API tests: plan creation, approve/reject workflow,
conflicts, stale and superseded plans, custom values, and data integrity.
"""

import pytest

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
    return r.json()["dataset_id"]


async def make_plan(client, csv=CSV, body=None):
    did = await upload(client, csv)
    r = await client.post(f"/api/datasets/{did}/repair-plan", json=body) if body else \
        await client.post(f"/api/datasets/{did}/repair-plan")
    assert r.status_code == 201, r.text
    return did, r.json()


async def proposals(client, plan_id, **params):
    r = await client.get(f"/api/repair-plans/{plan_id}/proposals", params={"limit": 1000, **params})
    assert r.status_code == 200
    return r.json()["proposals"]


def find(props, issue_type, row=None, column=None):
    return next(p for p in props if p["issue_type"] == issue_type
                and (row is None or p["row_number"] == row)
                and (column is None or p["column"] == column))


async def decide(client, plan_id, pid, decision, value=None):
    body = {"decision": decision}
    if value is not None:
        body["chosen_value"] = value
    return await client.post(f"/api/repair-plans/{plan_id}/proposals/{pid}/decision", json=body)


# ── Plan creation ───────────────────────────────────────────────────────────

async def test_plan_summary_and_proposal_fields(client):
    did, plan = await make_plan(client, body=RULES)
    assert plan["status"] == "active" and plan["dataset_id"] == did
    assert plan["proposal_count"] == plan["safe_count"] + plan["ambiguous_count"] > 0
    assert plan["status_counts"] == {"pending": plan["proposal_count"], "approved": 0, "rejected": 0}
    assert plan["validation"]["ran"] and plan["validation"]["violation_count"] == 1
    assert any(g["issue_type"] == "missing_value" for g in plan["issues_without_proposal"])
    props = await proposals(client, plan["plan_id"])
    assert len({p["proposal_id"] for p in props}) == len(props)
    assert all(p["status"] == "pending" and p["approved_value"] is None for p in props)
    assert all(p["reason"] for p in props)


async def test_creating_a_plan_changes_nothing_on_disk(client, settings):
    did = await upload(client)
    path = settings.upload_path / f"{did}.csv"
    before = path.read_bytes()
    await client.post(f"/api/datasets/{did}/repair-plan")
    assert path.read_bytes() == before


async def test_plan_unknown_dataset_and_bad_rules(client):
    assert (await client.post(f"/api/datasets/{'a' * 32}/repair-plan")).status_code == 404
    did = await upload(client)
    bad = await client.post(f"/api/datasets/{did}/repair-plan",
                            json={"rules": {"rules": [{"column": "a", "regex": "([x"}]}})
    assert bad.status_code == 422


async def test_suggested_rules_endpoint(client):
    did = await upload(client, "id,age\n1,30\n2,31\n")
    body = (await client.get(f"/api/datasets/{did}/suggested-rules")).json()
    assert {r["column"]: r["dtype"] for r in body["rules"]["rules"]} == {"id": "integer", "age": "integer"}


async def test_list_filters_and_paging(client):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    safe = await proposals(client, pid, classification="safe")
    assert safe and all(p["classification"] == "safe" for p in safe)
    only_city = await proposals(client, pid, column="city")
    assert only_city and all(p["column"] == "city" for p in only_city)
    r = await client.get(f"/api/repair-plans/{pid}/proposals", params={"limit": 2, "offset": 1})
    body = r.json()
    assert len(body["proposals"]) == 2 and body["total"] == plan["proposal_count"]


async def test_unknown_plan_and_malformed_ids_404(client):
    for bad in ["a" * 32, "short", "../x"]:
        assert (await client.get(f"/api/repair-plans/{bad}")).status_code == 404


# ── Decisions ───────────────────────────────────────────────────────────────

async def test_nothing_is_approved_by_default_and_approved_list_starts_empty(client):
    _, plan = await make_plan(client)
    r = await client.get(f"/api/repair-plans/{plan['plan_id']}/approved")
    assert r.status_code == 200 and r.json()["count"] == 0


async def test_approve_safe_proposal_records_value_and_history(client):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    props = await proposals(client, pid)
    num = find(props, "numeric_format", column="salary")
    r = await decide(client, pid, num["proposal_id"], "approve")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved" and body["approved_value"] == "1200"
    assert body["original_value"] == "1,200" and body["proposed_value"] == "1200"  # kept separate
    assert body["history"][0]["decision"] == "approve"
    approved = (await client.get(f"/api/repair-plans/{pid}/approved")).json()
    assert approved["count"] == 1
    assert approved["repairs"][0]["approved_value"] == "1200"


async def test_reject_is_recorded_and_excluded_from_approved(client):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    num = find(await proposals(client, pid), "numeric_format")
    r = await decide(client, pid, num["proposal_id"], "reject")
    assert r.json()["status"] == "rejected" and r.json()["approved_value"] is None
    assert (await client.get(f"/api/repair-plans/{pid}/approved")).json()["count"] == 0
    still = find(await proposals(client, pid, status="rejected"), "numeric_format")
    assert still["proposal_id"] == num["proposal_id"]  # preserved as rejected


async def test_decision_can_be_changed_and_history_keeps_both(client):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    num = find(await proposals(client, pid), "numeric_format")
    await decide(client, pid, num["proposal_id"], "approve")
    r = await decide(client, pid, num["proposal_id"], "reject")
    assert [h["decision"] for h in r.json()["history"]] == ["approve", "reject"]
    assert r.json()["status"] == "rejected"


async def test_ambiguous_proposal_requires_a_choice(client):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    date = find(await proposals(client, pid), "inconsistent_date_format", row=2)
    assert date["proposed_value"] is None and len(date["alternatives"]) == 2
    assert (await decide(client, pid, date["proposal_id"], "approve")).status_code == 422
    assert (await decide(client, pid, date["proposal_id"], "approve", "2020-01-01")).status_code == 422
    ok = await decide(client, pid, date["proposal_id"], "approve", date["alternatives"][0])
    assert ok.status_code == 200 and ok.json()["approved_value"] == date["alternatives"][0]


async def test_clear_value_proposal_and_custom_correction(client):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    bad_date = find(await proposals(client, pid), "invalid_date")
    assert (await decide(client, pid, bad_date["proposal_id"], "approve", "not a date")).status_code == 422
    ok = await decide(client, pid, bad_date["proposal_id"], "approve", "2024-02-29")
    assert ok.json()["approved_value"] == "2024-02-29"
    again = await decide(client, pid, bad_date["proposal_id"], "approve")  # plain clear
    assert again.json()["approved_value"] is None and again.json()["status"] == "approved"


async def test_custom_value_cannot_break_validation_rules(client):
    _, plan = await make_plan(client, body=RULES)
    pid = plan["plan_id"]
    bad_age = find(await proposals(client, pid), "invalid_numeric", column="age")
    r = await decide(client, pid, bad_age["proposal_id"], "approve", "500")
    assert r.status_code == 422 and "must be <= 120" in r.json()["error"]["message"]
    assert (await decide(client, pid, bad_age["proposal_id"], "approve", "35")).status_code == 200


async def test_row_deletion_takes_no_value(client):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    dup = find(await proposals(client, pid), "exact_duplicate")
    assert (await decide(client, pid, dup["proposal_id"], "approve", "x")).status_code == 422
    ok = await decide(client, pid, dup["proposal_id"], "approve")
    assert ok.status_code == 200 and ok.json()["approved_value"] is None


async def test_placeholder_clear_rejects_custom_values(client):
    csv = "name,note\nAl,ok\nBo,N/A\nCy,fine\n"
    _, plan = await make_plan(client, csv)
    pid = plan["plan_id"]
    ph = find(await proposals(client, pid), "placeholder_missing")
    assert ph["allow_custom_value"] is False
    assert (await decide(client, pid, ph["proposal_id"], "approve", "something")).status_code == 422
    assert (await decide(client, pid, ph["proposal_id"], "approve")).status_code == 200


async def test_unknown_proposal_404_and_bad_payload_422(client):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    assert (await decide(client, pid, "Rdoesnotexist", "approve")).status_code == 404
    r = await client.post(f"/api/repair-plans/{pid}/proposals/x/decision", json={"decision": "maybe"})
    assert r.status_code == 422
    num = find(await proposals(client, pid), "numeric_format")
    assert (await decide(client, pid, num["proposal_id"], "reject", "v")).status_code == 422


# ── Conflicts ───────────────────────────────────────────────────────────────

async def test_conflicting_proposals_cannot_both_be_approved(client):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    props = await proposals(client, pid)
    ws = find(props, "whitespace", row=4)
    ci = find(props, "inconsistent_text_format", row=4, column="name")
    assert ci["proposal_id"] in ws["conflicts_with"]
    assert (await decide(client, pid, ws["proposal_id"], "approve")).status_code == 200
    r = await decide(client, pid, ci["proposal_id"], "approve", "Alice Smith")
    assert r.status_code == 409 and r.json()["error"]["code"] == "conflicting_proposal"
    # resolving: reject the first, then the second is allowed
    await decide(client, pid, ws["proposal_id"], "reject")
    assert (await decide(client, pid, ci["proposal_id"], "approve", "Alice Smith")).status_code == 200


async def test_row_delete_conflicts_with_edit_on_same_row(client):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    props = await proposals(client, pid)
    dup = find(props, "potential_duplicate", row=4)
    ws = find(props, "whitespace", row=4)
    assert (await decide(client, pid, dup["proposal_id"], "approve")).status_code == 200
    assert (await decide(client, pid, ws["proposal_id"], "approve")).status_code == 409


async def test_approve_safe_approves_only_safe_and_skips_conflicts(client):
    _, plan = await make_plan(client)
    pid = plan["plan_id"]
    props = await proposals(client, pid)
    r = await client.post(f"/api/repair-plans/{pid}/approve-safe")
    assert r.status_code == 200
    body = r.json()
    after = await proposals(client, pid)
    approved = [p for p in after if p["status"] == "approved"]
    assert body["approved_count"] == len(approved) > 0
    assert all(p["classification"] == "safe" for p in approved)
    assert all(p["status"] == "pending" for p in after if p["classification"] == "ambiguous")
    # whitespace(row 4) conflicts with delete/case proposals, none of which are safe → approved
    assert any(p["issue_type"] == "whitespace" for p in approved)


# ── Stale and superseded plans ──────────────────────────────────────────────

async def test_new_plan_supersedes_old_one(client):
    did, plan1 = await make_plan(client)
    r2 = await client.post(f"/api/datasets/{did}/repair-plan")
    assert r2.status_code == 201
    assert (await client.get(f"/api/repair-plans/{plan1['plan_id']}")).json()["status"] == "superseded"
    num = find(await proposals(client, plan1["plan_id"]), "numeric_format")
    r = await decide(client, plan1["plan_id"], num["proposal_id"], "approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "plan_superseded"
    assert (await client.get(f"/api/repair-plans/{r2.json()['plan_id']}")).json()["status"] == "active"


async def test_plan_goes_stale_if_the_dataset_file_changes(client, settings):
    did, plan = await make_plan(client)
    pid = plan["plan_id"]
    num = find(await proposals(client, pid), "numeric_format")
    path = settings.upload_path / f"{did}.csv"
    path.write_bytes(path.read_bytes() + b"9,Zed,50,2024-01-01,Pune,1\n")
    r = await decide(client, pid, num["proposal_id"], "approve")
    assert r.status_code == 409 and r.json()["error"]["code"] == "plan_stale"
    assert (await client.get(f"/api/repair-plans/{pid}")).json()["status"] == "stale"
    assert (await client.get(f"/api/repair-plans/{pid}/approved")).status_code == 409
    assert (await client.post(f"/api/repair-plans/{pid}/approve-safe")).status_code == 409


async def test_plan_stale_when_file_deleted(client, settings):
    did, plan = await make_plan(client)
    (settings.upload_path / f"{did}.csv").unlink()
    r = await client.post(f"/api/repair-plans/{plan['plan_id']}/approve-safe")
    assert r.status_code == 409


# ── Integrity ───────────────────────────────────────────────────────────────

async def test_full_workflow_never_modifies_original_upload(client, settings):
    did, plan = await make_plan(client, body=RULES)
    pid = plan["plan_id"]
    path = settings.upload_path / f"{did}.csv"
    before = path.read_bytes()
    await client.post(f"/api/repair-plans/{pid}/approve-safe")
    for p in await proposals(client, pid, status="pending"):
        await decide(client, pid, p["proposal_id"], "reject")
    await client.get(f"/api/repair-plans/{pid}/approved")
    assert path.read_bytes() == before


async def test_plan_with_too_many_proposals_is_truncated_and_flagged(client, settings):
    settings.max_proposals_per_plan = 3
    csv = "n\n" + "\n".join(f'" v{i}"' for i in range(10)) + "\n"
    _, plan = await make_plan(client, csv)
    assert plan["truncated"] is True and plan["proposal_count"] == 3
