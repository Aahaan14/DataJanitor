"""
DataJanitor — Phase 2 tests: CSV upload, parsing, profiling and preview.

Covers normal files, empty files, malformed CSVs, invalid extensions,
oversized files, encoding problems, and the "original is preserved" rule.
"""

import pytest

GOOD_CSV = (
    "id,name,age,joined,active\n"
    "1,Alice,30,2024-01-05,yes\n"
    "2,Bob,,2024-02-10,no\n"
    "3,Carol,41,2024-03-15,yes\n"
)


async def upload(client, content: bytes, filename: str = "data.csv"):
    return await client.post(
        "/api/datasets/upload", files={"file": (filename, content, "text/csv")}
    )


# ── Happy path ──────────────────────────────────────────────────────────────


async def test_upload_valid_csv(client):
    resp = await upload(client, GOOD_CSV.encode())
    assert resp.status_code == 201
    body = resp.json()
    assert body["row_count"] == 3
    assert body["column_count"] == 5
    assert body["encoding"] == "utf-8"
    assert body["delimiter"] == ","
    assert body["filename"] == "data.csv"
    assert len(body["dataset_id"]) == 32


async def test_preview_contains_rows_with_stable_numbers_and_nulls(client):
    body = (await upload(client, GOOD_CSV.encode())).json()
    preview = body["preview"]
    assert preview["columns"] == ["id", "name", "age", "joined", "active"]
    assert [r["row_number"] for r in preview["rows"]] == [1, 2, 3]
    assert preview["rows"][1]["values"]["age"] is None  # empty cell → null
    assert preview["rows"][0]["values"]["id"] == "1"  # text preserved


async def test_preview_is_capped(client):
    rows = "\n".join(f"{i},x" for i in range(50))
    body = (await upload(client, f"a,b\n{rows}\n".encode())).json()
    assert body["row_count"] == 50
    assert body["preview"]["preview_row_count"] == 5  # settings.preview_rows


async def test_column_profiles(client):
    body = (await upload(client, GOOD_CSV.encode())).json()
    cols = {c["name"]: c for c in body["columns"]}
    assert cols["id"]["inferred_type"] == "integer"
    assert cols["age"]["inferred_type"] == "integer"
    assert cols["age"]["missing_count"] == 1
    assert cols["age"]["missing_percent"] == pytest.approx(33.33)
    assert cols["age"]["stats"]["min"] == 30
    assert cols["age"]["stats"]["max"] == 41
    assert cols["joined"]["inferred_type"] == "datetime"
    assert cols["joined"]["stats"]["earliest"] == "2024-01-05"
    assert cols["active"]["inferred_type"] == "boolean"
    assert cols["name"]["inferred_type"] == "text"
    assert cols["name"]["unique_count"] == 3


async def test_float_and_mixed_columns(client):
    csv = "price,qty\n1.5,1\n2.5,2\n3.5,3\n4.5,4\n5.5,5\nabc,6\n"
    # 5/6 numeric = 83% → "mixed", not silently "text" or "float"
    cols = {c["name"]: c for c in (await upload(client, csv.encode())).json()["columns"]}
    assert cols["price"]["inferred_type"] == "mixed"
    assert cols["price"]["parse_ratio"] == pytest.approx(0.8333, abs=1e-3)
    assert cols["qty"]["inferred_type"] == "integer"


async def test_leading_zeros_not_altered(client):
    body = (await upload(client, b"zip,city\n02134,Boston\n00501,Holtsville\n")).json()
    assert body["preview"]["rows"][0]["values"]["zip"] == "02134"


async def test_semicolon_delimiter_detected(client):
    body = (await upload(client, b"a;b;c\n1;2;3\n4;5;6\n")).json()
    assert body["delimiter"] == ";"
    assert body["column_count"] == 3


async def test_original_file_saved_byte_for_byte(client, settings):
    raw = GOOD_CSV.encode()
    body = (await upload(client, raw)).json()
    saved = settings.upload_path / f"{body['dataset_id']}.csv"
    assert saved.read_bytes() == raw


async def test_path_in_filename_is_neutralised(client, settings):
    resp = await upload(client, GOOD_CSV.encode(), "../../etc/evil.csv")
    assert resp.status_code == 201
    assert resp.json()["filename"] == "evil.csv"
    files = list(settings.upload_path.iterdir())
    assert len(files) == 1 and files[0].parent == settings.upload_path


# ── Encodings ───────────────────────────────────────────────────────────────


async def test_utf8_bom_handled(client):
    body = (await upload(client, b"\xef\xbb\xbf" + GOOD_CSV.encode())).json()
    assert body["encoding"] == "utf-8-sig"
    assert body["preview"]["columns"][0] == "id"  # BOM not glued to header


async def test_latin1_file_decoded_with_warning(client):
    raw = "name,city\nJosé,Málaga\nZoë,Zürich\n".encode("cp1252")
    resp = await upload(client, raw)
    assert resp.status_code == 201
    body = resp.json()
    assert body["encoding"] != "utf-8"
    assert any("not UTF-8" in w for w in body["warnings"])
    assert body["preview"]["rows"][0]["values"]["name"] == "José"


async def test_utf16_file_with_bom(client):
    resp = await upload(client, GOOD_CSV.encode("utf-16"))
    assert resp.status_code == 201
    assert resp.json()["encoding"] == "utf-16"


async def test_binary_file_rejected(client):
    resp = await upload(client, b"PK\x03\x04\x00\x00\x00\x00binary\x00\x00data", "x.csv")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "unsupported_encoding"


# ── Rejections ──────────────────────────────────────────────────────────────


async def test_empty_file_rejected(client):
    resp = await upload(client, b"")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "empty_file"


async def test_whitespace_only_file_rejected(client):
    resp = await upload(client, b"  \n \n")
    assert resp.status_code == 400


async def test_header_only_file_rejected(client):
    resp = await upload(client, b"a,b,c\n")
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "empty_file"


@pytest.mark.parametrize("name", ["data.txt", "data.xlsx", "data.csv.exe", "noextension"])
async def test_invalid_extension_rejected(client, name):
    resp = await upload(client, GOOD_CSV.encode(), name)
    assert resp.status_code == 415
    assert resp.json()["error"]["code"] == "invalid_file_type"


async def test_extension_check_is_case_insensitive(client):
    assert (await upload(client, GOOD_CSV.encode(), "DATA.CSV")).status_code == 201


async def test_oversized_file_rejected(client, settings):
    big = b"a,b\n" + b"1,2\n" * (settings.max_upload_size_bytes // 4 + 10)
    resp = await upload(client, big)
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "file_too_large"


async def test_malformed_csv_rejected(client):
    # Row 3 has more fields than the header → parser error
    resp = await upload(client, b"a,b\n1,2\n3,4,5,6\n")
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "malformed_csv"


async def test_too_many_rows_rejected(client, settings):
    rows = "\n".join("1,2" for _ in range(settings.max_rows + 1))
    resp = await upload(client, f"a,b\n{rows}\n".encode())
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "dataset_limit_exceeded"


async def test_too_many_columns_rejected(client, settings):
    n = settings.max_columns + 1
    header = ",".join(f"c{i}" for i in range(n))
    row = ",".join("1" for _ in range(n))
    resp = await upload(client, f"{header}\n{row}\n".encode())
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "dataset_limit_exceeded"


async def test_rejected_upload_leaves_no_file_behind(client, settings):
    await upload(client, b"a,b\n1,2\n3,4,5,6\n")
    await upload(client, b"", "empty.csv")
    assert not settings.upload_path.exists() or list(settings.upload_path.iterdir()) == []


async def test_missing_file_field_returns_422(client):
    resp = await client.post("/api/datasets/upload")
    assert resp.status_code == 422


async def test_duplicate_headers_warn(client):
    body = (await upload(client, b"a,a\n1,2\n")).json()
    assert any("Duplicate column" in w for w in body["warnings"])
