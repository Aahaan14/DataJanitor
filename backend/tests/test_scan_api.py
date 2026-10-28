"""DataJanitor — Phase 3 API tests for POST /api/datasets/{id}/scan."""

MESSY_CSV = (
    "id,name,age,joined,city\n"
    "1,Alice,30,2024-01-05,Pune\n"
    "2,Bob,,2024-02-30,pune\n"
    "3,Carol,31,2024-03-01,Pune\n"
    "1,Alice,30,2024-01-05,Pune\n"
)


async def upload(client, content: str):
    resp = await client.post(
        "/api/datasets/upload", files={"file": ("d.csv", content.encode(), "text/csv")}
    )
    assert resp.status_code == 201
    return resp.json()["dataset_id"]


async def test_scan_returns_issues_and_summary(client):
    dataset_id = await upload(client, MESSY_CSV)
    resp = await client.post(f"/api/datasets/{dataset_id}/scan")
    assert resp.status_code == 200
    body = resp.json()
    assert body["dataset_id"] == dataset_id
    assert body["row_count"] == 4 and body["column_count"] == 5
    assert body["truncated"] is False
    assert body["issues_returned"] == body["summary"]["total_issues"] == len(body["issues"])
    assert "not confirmed errors" in body["disclaimer"]
    kinds = {i["issue_type"] for i in body["issues"]}
    assert {"missing_value", "exact_duplicate", "invalid_date"} <= kinds
    first = body["issues"][0]
    assert set(first) >= {
        "issue_id", "issue_type", "severity", "column", "row_number",
        "observed_value", "explanation", "suggested_action", "status",
    }


async def test_scan_never_modifies_original_file(client, settings):
    dataset_id = await upload(client, MESSY_CSV)
    path = settings.upload_path / f"{dataset_id}.csv"
    before = path.read_bytes()
    await client.post(f"/api/datasets/{dataset_id}/scan")
    await client.post(f"/api/datasets/{dataset_id}/scan")
    assert path.read_bytes() == before


async def test_scan_is_repeatable_with_same_ids(client):
    dataset_id = await upload(client, MESSY_CSV)
    a = (await client.post(f"/api/datasets/{dataset_id}/scan")).json()["issues"]
    b = (await client.post(f"/api/datasets/{dataset_id}/scan")).json()["issues"]
    assert [(i["issue_id"], i["issue_type"], i["row_number"]) for i in a] == \
           [(i["issue_id"], i["issue_type"], i["row_number"]) for i in b]


async def test_scan_clean_dataset(client):
    dataset_id = await upload(client, "id,name\n1,Al\n2,Bo\n3,Cy\n")
    body = (await client.post(f"/api/datasets/{dataset_id}/scan")).json()
    assert body["summary"]["total_issues"] == 0 and body["issues"] == []


async def test_scan_truncates_but_summary_counts_everything(client, settings):
    settings.max_issues_returned = 2
    dataset_id = await upload(client, MESSY_CSV)
    body = (await client.post(f"/api/datasets/{dataset_id}/scan")).json()
    assert body["truncated"] is True
    assert body["issues_returned"] == 2 == len(body["issues"])
    assert body["summary"]["total_issues"] > 2


async def test_scan_unknown_dataset_404(client):
    resp = await client.post(f"/api/datasets/{'a' * 32}/scan")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "dataset_not_found"


async def test_scan_rejects_malformed_ids_without_touching_filesystem(client):
    for bad in ["short", "A" * 32, "..%2F..%2Fetc%2Fpasswd", "g" * 32, "a" * 33]:
        resp = await client.post(f"/api/datasets/{bad}/scan")
        assert resp.status_code in (404,)  # never 200/500


async def test_scan_does_not_follow_path_traversal(client, settings):
    (settings.upload_path.parent / "secret.csv").write_text("a,b\n1,2\n")
    resp = await client.post("/api/datasets/..%2Fsecret/scan")
    assert resp.status_code == 404
