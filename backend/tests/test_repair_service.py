"""DataJanitor — Phase 6 unit tests: applying repairs, output verification, CSV rendering, escaping."""

import csv
import io
from types import SimpleNamespace as P

import numpy as np
import pandas as pd
import pytest

from app.services import csv_service
from app.services import detection_service as ds
from app.services import repair_service as rs


def frame(csv_text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(csv_text.strip() + "\n"), dtype=str,
                       keep_default_na=False, na_values=[""])


def replace(pid, row, col, orig, new):
    return P(id=pid, action="replace_value", row_number=row, column_name=col,
             original_value=orig, approved_value=new)


def clear(pid, row, col, orig):
    return P(id=pid, action="clear_value", row_number=row, column_name=col,
             original_value=orig, approved_value=None)


def delete(df, pid, row):
    return P(id=pid, action="delete_row", row_number=row, column_name=None,
             original_value=ds._row_summary(df.loc[row - 1]), approved_value=None)


def by_id(result):
    return {o.proposal_id: o for o in result.outcomes}


# ── Applying repairs ────────────────────────────────────────────────────────

def test_replace_clear_and_delete_applied_to_a_copy():
    df = frame("a,b\nx, y\nq,2\nz,3\n")
    snapshot = df.copy(deep=True)
    res = rs.apply_repairs(df, [replace("R1", 1, "b", " y", "y"), clear("R2", 2, "a", "q"),
                                delete(df, "R3", 3)])
    assert res.cleaned["b"].tolist() == ["y", "2"]
    assert res.cleaned["a"][0] == "x" and pd.isna(res.cleaned["a"][1])   # row 2 'a' cleared
    assert len(res.cleaned) == 2                                         # row 3 deleted
    assert all(o.outcome == "applied" for o in res.outcomes)
    pd.testing.assert_frame_equal(df, snapshot)  # the input was never modified


def test_nothing_approved_means_identical_output():
    df = frame("a,b\nx,1\ny,2\n")
    res = rs.apply_repairs(df, [])
    pd.testing.assert_frame_equal(res.cleaned, df)
    assert res.outcomes == [] and res.edits == {} and res.deleted == set()


def test_deleting_a_row_keeps_other_rows_in_order():
    df = frame("a\n1\n2\n3\n4\n")
    res = rs.apply_repairs(df, [delete(df, "R1", 2)])
    assert res.cleaned["a"].tolist() == ["1", "3", "4"]


def test_skip_when_cell_changed_since_review():
    df = frame("a\nnew value\nb\n")
    res = rs.apply_repairs(df, [replace("R1", 1, "a", "old value", "x")])
    assert by_id(res)["R1"].outcome == "skipped"
    assert "no longer matches" in by_id(res)["R1"].reason
    assert res.cleaned["a"].tolist() == ["new value", "b"]


def test_skip_unknown_row_or_column():
    df = frame("a\n1\n2\n")
    res = rs.apply_repairs(df, [replace("R1", 9, "a", "1", "x"), replace("R2", 1, "zzz", "1", "x"),
                                replace("R3", 0, "a", "1", "x")])
    assert [by_id(res)[k].reason for k in ("R1", "R2", "R3")] == [
        "row not found", "column not found", "row not found"]
    assert res.cleaned["a"].tolist() == ["1", "2"]


def test_same_cell_twice_first_wins_second_skipped():
    df = frame("a\n x\n")
    res = rs.apply_repairs(df, [replace("R1", 1, "a", " x", "x"), replace("R2", 1, "a", " x", "X")])
    assert by_id(res)["R1"].outcome == "applied"
    assert by_id(res)["R2"].outcome == "skipped" and "already changed" in by_id(res)["R2"].reason
    assert res.cleaned["a"].tolist() == ["x"]


def test_edit_on_a_deleted_row_is_skipped_not_applied():
    df = frame("a\nx\n y\n")
    res = rs.apply_repairs(df, [delete(df, "R1", 2), replace("R2", 2, "a", " y", "y")])
    assert by_id(res)["R2"].outcome == "skipped" and "deleted by repair R1" in by_id(res)["R2"].reason
    assert res.cleaned["a"].tolist() == ["x"]


def test_double_delete_and_changed_row_skipped():
    df = frame("a,b\n1,2\n3,4\n")
    d1, d2 = delete(df, "R1", 1), delete(df, "R2", 1)
    stale = P(id="R3", action="delete_row", row_number=2, column_name=None,
              original_value="9 | 9", approved_value=None)
    res = rs.apply_repairs(df, [d1, d2, stale])
    assert [by_id(res)[k].outcome for k in ("R1", "R2", "R3")] == ["applied", "skipped", "skipped"]
    assert res.cleaned["a"].tolist() == ["3"]


def test_replace_without_an_approved_value_is_skipped():
    df = frame("a\nx\n")
    res = rs.apply_repairs(df, [replace("R1", 1, "a", "x", None)])
    assert by_id(res)["R1"].outcome == "skipped"
    assert res.cleaned["a"].tolist() == ["x"]


def test_empty_original_cell_can_be_filled_when_it_was_reviewed_as_empty():
    df = frame("a,b\n,1\n")
    res = rs.apply_repairs(df, [replace("R1", 1, "a", None, "filled")])
    assert res.cleaned["a"].tolist() == ["filled"]


# ── Independent verification ────────────────────────────────────────────────

def test_verification_accepts_exact_result_including_empty_cells():
    df = frame("a,b\n,1\nx,\n y,3\n")
    res = rs.apply_repairs(df, [replace("R1", 3, "a", " y", "y"), delete(df, "R2", 2)])
    assert rs.find_unintended_changes(df, res.cleaned, res.edits, res.deleted) == []


def test_verification_detects_an_extra_changed_cell():
    df = frame("a,b\nx,1\ny,2\n")
    res = rs.apply_repairs(df, [replace("R1", 1, "a", "x", "X")])
    tampered = res.cleaned.copy()
    tampered.at[1, "b"] = "999"
    problems = rs.find_unintended_changes(df, tampered, res.edits, res.deleted)
    assert any("without an approved repair" in p for p in problems)


def test_verification_detects_a_missing_or_wrong_edit():
    df = frame("a\nx\ny\n")
    res = rs.apply_repairs(df, [replace("R1", 1, "a", "x", "X")])
    wrong = res.cleaned.copy()
    wrong.at[0, "a"] = "Z"
    assert rs.find_unintended_changes(df, wrong, res.edits, res.deleted)
    untouched = df.copy()
    assert rs.find_unintended_changes(df, untouched, res.edits, res.deleted)


def test_verification_detects_extra_or_missing_rows_and_column_changes():
    df = frame("a,b\n1,2\n3,4\n5,6\n")
    res = rs.apply_repairs(df, [delete(df, "R1", 2)])
    assert rs.find_unintended_changes(df, res.cleaned.iloc[:1], res.edits, res.deleted)       # row lost
    assert rs.find_unintended_changes(df, df, res.edits, res.deleted)                         # row kept
    assert rs.find_unintended_changes(df, res.cleaned.rename(columns={"a": "A"}), res.edits, res.deleted)


# ── CSV rendering ───────────────────────────────────────────────────────────

def parse(data: bytes):
    return csv_service.parse_bytes(data, 1000, 50)


def test_render_uses_bom_crlf_and_original_header_and_delimiter():
    df = pd.DataFrame({"a": ["1"], "b": ["2"]}, dtype="object")
    out = rs.render_csv(df, ["a", "b"], ";")
    assert out.startswith(b"\xef\xbb\xbf") and out.endswith(b"\r\n")
    assert out.decode("utf-8-sig") == "a;b\r\n1;2\r\n"


def test_render_round_trips_awkward_values_exactly():
    awkward = ['say "hi"', "a,b", "line1\nline2", "  padded  ", "007", "N/A", "=1+1", "ünï-çødé", "x;y"]
    df = pd.DataFrame({"v": awkward, "w": [None] * len(awkward)}, dtype="object")
    back = parse(rs.render_csv(df, ["v", "w"], ",")).df
    assert back["v"].tolist() == awkward
    assert back["w"].isna().all()


def test_render_keeps_a_row_whose_only_value_is_empty():
    df = pd.DataFrame({"a": ["x", None, "z"]}, dtype="object")
    back = parse(rs.render_csv(df, ["a"], ",")).df
    assert len(back) == 3 and pd.isna(back["a"][1])


def test_duplicate_and_blank_header_names_survive_via_original_header_text():
    raw = b"a,a,\n1,2,3\n"
    parsed = parse(raw)
    assert parsed.header == ["a", "a", ""]
    out = rs.render_csv(parsed.df, parsed.header, parsed.delimiter)
    assert out.decode("utf-8-sig").splitlines()[0] == "a,a,"


@pytest.mark.parametrize("raw", [
    b"id,name\r\n1,Al\r\n2,Bo\r\n",
    b"a;b\n1;2\n3;\n",
    "n,city\nJos\u00e9,M\u00e1laga\n".encode("utf-8"),
    "n,city\nJos\u00e9,M\u00e1laga\n".encode("cp1252"),
])
def test_untouched_data_round_trips_value_for_value(raw):
    original = parse(raw)
    again = parse(rs.render_csv(original.df, original.header, original.delimiter))
    pd.testing.assert_frame_equal(original.df.reset_index(drop=True), again.df.reset_index(drop=True))
    assert again.header == original.header


# ── Formula injection ───────────────────────────────────────────────────────

@pytest.mark.parametrize("value,escaped", [
    ("=1+1", True), ("+cmd|' /C calc'!A0", True), ("-2+3", True), ("@SUM(A1)", True),
    ("\t=1", True), (" =1+1", True), ("+91 98765 43210", True),
    ("-5", False), ("+5", False), ("3.14", False), ("-0.5e3", False),
    ("plain", False), ("a=b", False), ("", False), ("'=already", False),
])
def test_escape_formula(value, escaped):
    out, was = rs.escape_formula(value)
    assert was is escaped
    assert out == ("'" + value if escaped else value)


def test_sanitize_escapes_headers_quoted_and_multiline_fields_and_counts():
    raw = rs.render_csv(
        pd.DataFrame({"=evil": ['=HYPERLINK("http://x")', "-7", "ok\n=hidden", "@a"]}, dtype="object"),
        ["=evil"], ",")
    safe, n = rs.sanitize_for_spreadsheet(raw, ",")
    rows = list(csv.reader(io.StringIO(safe.decode("utf-8-sig"), newline="")))
    assert rows[0] == ["'=evil"]
    assert rows[1] == ['\'=HYPERLINK("http://x")'] and rows[2] == ["-7"]
    assert rows[3] == ["ok\n=hidden"]            # only the first character matters
    assert rows[4] == ["'@a"] and n == 3
    assert safe.startswith(b"\xef\xbb\xbf")
