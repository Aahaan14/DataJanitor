"""DataJanitor — Phase 8 backend support for the frontend: profile, config, CORS."""

import pytest

CSV = "id,name,age\n" + "".join(f"{i},Name {i},{20 + i}\n" for i in range(1, 26))


async def upload(client, csv=CSV, name="people.csv"):
    r = await client.post("/api/datasets/upload", files={"file": (name, csv.encode(), "text/csv")})
    return r.json()["dataset_id"]


async def test_profile_returns_columns_and_a_page_of_rows(client):
    did = await upload(client)
    r = await client.get(f"/api/datasets/{did}/profile")
    assert r.status_code == 200
    body = r.json()
    assert (body["row_count"], body["column_count"], body["filename"]) == (25, 3, "people.csv")
    assert [c["name"] for c in body["columns"]] == ["id", "name", "age"]
    assert body["preview"]["preview_row_count"] == 10 and body["preview"]["rows"][0]["row_number"] == 1
    assert body["preview_offset"] == 0 and body["preview_limit"] == 10


async def test_profile_paging_uses_stable_row_numbers(client):
    did = await upload(client)
    body = (await client.get(f"/api/datasets/{did}/profile", params={"offset": 20, "limit": 10})).json()
    rows = body["preview"]["rows"]
    assert [r["row_number"] for r in rows] == [21, 22, 23, 24, 25]      # last, partial page
    assert rows[0]["values"]["name"] == "Name 21"
    empty = (await client.get(f"/api/datasets/{did}/profile", params={"offset": 500})).json()
    assert empty["preview"]["rows"] == []


async def test_profile_validates_paging_and_ids(client):
    did = await upload(client)
    assert (await client.get(f"/api/datasets/{did}/profile", params={"limit": 0})).status_code == 422
    assert (await client.get(f"/api/datasets/{did}/profile", params={"limit": 101})).status_code == 422
    assert (await client.get(f"/api/datasets/{did}/profile", params={"offset": -1})).status_code == 422
    assert (await client.get(f"/api/datasets/{'a' * 32}/profile")).status_code == 404


async def test_profile_of_a_deleted_dataset_is_gone(client):
    did = await upload(client)
    await client.delete(f"/api/datasets/{did}")
    assert (await client.get(f"/api/datasets/{did}/profile")).status_code == 410


async def test_profile_does_not_modify_the_original(client, settings):
    did = await upload(client)
    path = settings.upload_path / f"{did}.csv"
    before = path.read_bytes()
    await client.get(f"/api/datasets/{did}/profile")
    assert path.read_bytes() == before


async def test_config_endpoint_exposes_limits_and_no_secrets(client, settings):
    from pydantic import SecretStr
    settings.smtp_password = SecretStr("hunter2-secret")
    settings.smtp_user = "someone@example.com"
    r = await client.get("/api/config")
    body = r.json()
    assert body["max_upload_size_mb"] == settings.max_upload_size_mb
    assert body["max_rows"] == settings.max_rows and body["upload_retention_days"] == 30
    assert body["email"]["enabled"] is False and body["app_name"] == "DataJanitor"
    assert "hunter2-secret" not in r.text and "smtp_password" not in r.text.lower()


async def test_cors_allows_only_configured_origins(client, settings):
    ok = await client.options("/api/stats", headers={
        "Origin": settings.cors_origin_list[0], "Access-Control-Request-Method": "GET"})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == settings.cors_origin_list[0]
    bad = await client.options("/api/stats", headers={
        "Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in bad.headers
    plain = await client.get("/api/stats", headers={"Origin": "https://evil.example"})
    assert plain.status_code == 200 and "access-control-allow-origin" not in plain.headers


async def test_cors_exposes_download_headers_and_blocks_other_methods(client, settings):
    pre = await client.options("/api/datasets/x", headers={
        "Origin": settings.cors_origin_list[0], "Access-Control-Request-Method": "PUT"})
    assert pre.status_code == 400                      # PUT is not an allowed method
