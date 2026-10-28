"""
DataJanitor — Phase 3 unit tests: each detector in isolation.

DataFrames are built the same way Phase 2 parses uploads (all text, only
empty cells = NaN), so the detectors see realistic input.
"""

import io

import pandas as pd
import pytest

from app.schemas.issues import IssueType, Severity
from app.services import detection_service as ds


def make_df(csv: str) -> pd.DataFrame:
    return pd.read_csv(
        io.StringIO(csv.strip() + "\n"), dtype=str, keep_default_na=False, na_values=[""]
    )


def _series_csv(values):
    return "x\n" + "\n".join(str(v) for v in values) + "\n"


def types(issues):
    return [i.issue_type for i in issues]


def rows(issues):
    return sorted(i.row_number for i in issues if i.row_number is not None)


# ── Missing values & placeholders ───────────────────────────────────────────

def test_missing_values_reports_each_empty_cell_with_stable_row_numbers():
    df = make_df("a,b\n1,x\n,y\n3,\n")
    issues = ds.detect_missing_values(df)
    assert {(i.column, i.row_number) for i in issues} == {("a", 2), ("b", 3)}
    assert all(i.issue_type == IssueType.MISSING_VALUE for i in issues)
    assert all(i.observed_value is None for i in issues)


def test_missing_severity_scales_with_column_share():
    df = make_df("a,b\n,1\n,2\n3,3\n")  # a is 66% empty
    assert ds.detect_missing_values(df)[0].severity == Severity.HIGH


def test_no_missing_values_gives_no_issues():
    assert ds.detect_missing_values(make_df("a\n1\n2\n")) == []


def test_placeholder_tokens_and_whitespace_only_cells():
    # two columns: a whitespace-only line in a 1-column CSV is skipped by the parser
    df = make_df("a,b\nok,1\nN/A,2\nnull,3\n   ,4\nfine,5\n")
    issues = ds.detect_placeholder_values(df)
    assert rows(issues) == [2, 3, 4]
    assert all(i.issue_type == IssueType.PLACEHOLDER_MISSING for i in issues)


# ── Duplicates ──────────────────────────────────────────────────────────────

def test_exact_duplicates_keep_first_and_point_to_it():
    df = make_df("id,n\n1,a\n2,b\n1,a\n1,a\n")
    issues = ds.detect_exact_duplicates(df)
    assert rows(issues) == [3, 4]
    assert all(i.details["duplicate_of_row"] == 1 for i in issues)


def test_exact_duplicates_none():
    assert ds.detect_exact_duplicates(make_df("a,b\n1,2\n3,4\n")) == []


def test_exact_duplicates_treat_two_empty_cells_as_equal():
    df = make_df("a,b\n1,\n1,\n")
    assert rows(ds.detect_exact_duplicates(df)) == [2]


def test_potential_duplicates_ignore_case_spacing_punctuation_and_ids():
    df = make_df("customer_id,name,city\n1,Alice Smith,Pune\n2,  alice  smith!,pune\n3,Bob,Delhi\n")
    issues = ds.detect_potential_duplicates(df)
    assert rows(issues) == [2]
    assert issues[0].details["matches_row"] == 1
    assert issues[0].details["ambiguous"] is True


def test_potential_duplicates_skip_rows_already_exact():
    df = make_df("id,name,city\n1,Al,Pune\n2,Al,Pune\n3,Al,Pune\n")
    # ids differ, so these are not exact duplicates but are potential ones
    assert rows(ds.detect_potential_duplicates(df)) == [2, 3]
    df2 = make_df("name,city\nAl,Pune\nAl,Pune\n")
    assert ds.detect_potential_duplicates(df2) == []  # reported as exact instead


def test_potential_duplicates_need_two_filled_fields():
    df = make_df("name,city,note\nAl,,\nAl,,\n").iloc[:, :3]
    df.loc[1, "name"] = "al"  # not exact, only one non-blank field
    assert ds.detect_potential_duplicates(df) == []


# ── Text consistency ────────────────────────────────────────────────────────

def test_whitespace_issue_has_deterministic_proposed_value():
    df = make_df('name\n" Alice"\n"Bob  Lee"\nCarol\n')
    issues = [i for i in ds.detect_text_inconsistencies(df) if i.issue_type == IssueType.WHITESPACE]
    assert {i.row_number: i.details["proposed_value"] for i in issues} == {1: "Alice", 2: "Bob Lee"}


def test_case_variants_flag_minority_with_canonical_candidate():
    df = make_df("city\nPune\nPune\nPune\npune\nPUNE\n")
    issues = [i for i in ds.detect_text_inconsistencies(df)
              if i.issue_type == IssueType.INCONSISTENT_TEXT_FORMAT]
    assert rows(issues) == [4, 5]
    assert all(i.details["canonical_candidate"] == "Pune" for i in issues)


def test_case_variants_tie_is_ambiguous_and_proposes_nothing():
    df = make_df("city\nPune\npune\n")
    issues = [i for i in ds.detect_text_inconsistencies(df)
              if i.issue_type == IssueType.INCONSISTENT_TEXT_FORMAT]
    assert rows(issues) == [1, 2]
    assert all(i.details["ambiguous"] and i.details["canonical_candidate"] is None for i in issues)


def test_whitespace_detected_in_numeric_column_but_no_case_check():
    df = make_df('n\n" 41"\n30\n31\n')
    found = ds.detect_text_inconsistencies(df)
    assert types(found) == [IssueType.WHITESPACE]


# ── Dates ───────────────────────────────────────────────────────────────────

def test_impossible_and_unrecognisable_dates_flagged():
    df = make_df("d\n2024-01-05\n2024-02-30\nyesterday\n2024-03-01\n2024-04-01\n")
    bad = [i for i in ds.detect_date_issues(df) if i.issue_type == IssueType.INVALID_DATE]
    assert rows(bad) == [2, 3]
    assert all(i.severity == Severity.HIGH for i in bad)


def test_mixed_date_formats_flag_minority():
    df = make_df("d\n2024-01-05\n2024-01-06\n2024-01-07\n2024/01/08\n")
    inc = [i for i in ds.detect_date_issues(df)
           if i.issue_type == IssueType.INCONSISTENT_DATE_FORMAT]
    assert rows(inc) == [4]
    assert inc[0].details["dominant_format"] == "YYYY-MM-DD"


def test_ambiguous_slash_dates_flagged_not_reinterpreted():
    df = make_df("d\n03/04/2024\n05/06/2024\n01/02/2024\n")
    found = ds.detect_date_issues(df)
    assert types(found) == [IssueType.AMBIGUOUS_DATE_FORMAT]
    assert found[0].row_number is None  # column-level issue


def test_day_first_inferred_from_evidence_makes_month_13_invalid():
    df = make_df("d\n25/12/2024\n03/04/2024\n13/01/2024\n")
    assert [i for i in ds.detect_date_issues(df) if i.issue_type == IssueType.INVALID_DATE] == []
    assert [i for i in ds.detect_date_issues(df) if i.issue_type == IssueType.AMBIGUOUS_DATE_FORMAT] == []


def test_conflicting_day_month_order_reported():
    df = make_df("d\n25/12/2024\n12/25/2024\n")
    found = ds.detect_date_issues(df)
    assert any(i.issue_type == IssueType.INCONSISTENT_DATE_FORMAT and i.row_number is None for i in found)


def test_non_date_columns_ignored_by_date_detector():
    assert ds.detect_date_issues(make_df("a\nhello\nworld\n12\n")) == []


def test_month_name_dates_validated():
    df = make_df('d\n"5 Jan 2024"\n"6 Feb 2024"\n"31 Feb 2024"\n')
    assert rows([i for i in ds.detect_date_issues(df)
                 if i.issue_type == IssueType.INVALID_DATE]) == [3]


# ── Numerics ────────────────────────────────────────────────────────────────

def test_invalid_numeric_in_mostly_numeric_column():
    df = make_df(_series_csv(list(range(20, 40)) + ["abc"]))  # 20/21 = 95% numeric
    issues = ds.detect_invalid_numerics(df)
    assert rows(issues) == [21]
    assert issues[0].issue_type == IssueType.INVALID_NUMERIC
    assert issues[0].severity == Severity.HIGH
    assert "abc" in issues[0].explanation


def test_invalid_numeric_severity_is_medium_when_column_is_less_clean():
    df = make_df(_series_csv([1, 2, 3, 4, 5, 6, 7, 8, "abc"]))  # 89% numeric
    assert ds.detect_invalid_numerics(df)[0].severity == Severity.MEDIUM


def test_inf_and_nan_text_are_not_numbers():
    df = make_df("v\n1\n2\n3\ninf\n")
    assert rows(ds.detect_invalid_numerics(df)) == [4]


def test_formatted_numbers_get_proposed_value_except_percent():
    df = make_df('v\n10\n20\n"1,200"\n$5\n12%\n30\n')
    by_row = {i.row_number: i for i in ds.detect_invalid_numerics(df)}
    assert by_row[3].details["proposed_value"] == "1200"
    assert by_row[4].details["proposed_value"] == "5"
    assert by_row[5].details["proposed_value"] is None  # 12% is ambiguous
    assert by_row[5].details["ambiguous"] is True


def test_decimal_comma_is_flagged_not_converted():
    df = make_df('v\n1.5\n2.5\n3.5\n"12,5"\n')
    issue = ds.detect_invalid_numerics(df)[0]
    assert issue.issue_type == IssueType.INVALID_NUMERIC
    assert "decimal comma" in issue.explanation


def test_text_columns_not_checked_for_numbers():
    assert ds.detect_invalid_numerics(make_df("n\nAlice\nBob\nCarol\n")) == []


def test_leading_zero_codes_not_treated_as_numbers():
    df = make_df("zip\n02134\n00501\n10001\nabc\n")
    assert ds.detect_invalid_numerics(df) == []


# ── Outliers ────────────────────────────────────────────────────────────────

def test_obvious_outlier_flagged_with_method_details():
    df = make_df(_series_csv([10, 11, 12, 13, 14, 15, 11, 12, 13, 500]))
    issues = ds.detect_outliers(df)
    assert rows(issues) == [10]
    d = issues[0].details
    assert d["method"] == "IQR + modified z-score" and d["ambiguous"] is True
    assert issues[0].severity == Severity.MEDIUM
    assert "not evidence of an error" in issues[0].explanation


def test_no_outliers_in_well_behaved_data():
    df = make_df(_series_csv([10, 11, 12, 13, 14, 15, 11, 12, 13, 14]))
    assert ds.detect_outliers(df) == []


def test_outlier_detection_skipped_for_small_samples():
    assert ds.detect_outliers(make_df(_series_csv([1, 2, 3, 1000]))) == []


def test_outlier_detection_skipped_when_spread_is_zero():
    assert ds.detect_outliers(make_df(_series_csv([5] * 9 + [900]))) == []


def test_id_like_columns_never_flagged_as_outliers():
    df = make_df("user_id\n" + "\n".join(str(i) for i in list(range(1, 11)) + [9999]) + "\n")
    assert ds.detect_outliers(df) == []


# ── Orchestration & output contract ─────────────────────────────────────────

MESSY = """
id,name,age,joined,city
1,Alice,30,2024-01-05,Pune
2,Bob,,2024-02-30,pune
3,Carol,31,2024-03-01,Pune
1,Alice,30,2024-01-05,Pune
"""


def test_run_detection_assigns_unique_sequential_ids_and_standard_fields():
    issues = ds.run_detection(make_df(MESSY))
    ids = [i.issue_id for i in issues]
    assert ids == [f"I{n:05d}" for n in range(1, len(ids) + 1)]
    for i in issues:
        assert i.status == "detected"
        assert i.explanation and i.suggested_action and i.severity and i.issue_type


def test_run_detection_does_not_modify_dataframe():
    df = make_df(MESSY)
    before = df.copy(deep=True)
    ds.run_detection(df)
    pd.testing.assert_frame_equal(df, before)


def test_clean_dataset_has_no_issues():
    df = make_df("id,name,age\n1,Al,30\n2,Bo,31\n3,Cy,32\n")
    assert ds.run_detection(df) == []


def test_observed_values_are_truncated():
    long = "x" * 500
    df = make_df(f"a\n{long}\n{long.upper()}\n")
    issues = [i for i in ds.run_detection(df) if i.observed_value]
    assert issues and all(len(i.observed_value) <= ds.MAX_OBSERVED_LEN + 1 for i in issues)


def test_summary_counts():
    issues = ds.run_detection(make_df(MESSY))
    s = ds.summarize(issues)
    assert s.total_issues == len(issues)
    assert s.by_type["exact_duplicate"] == 1
    assert s.by_type["invalid_date"] == 1
    assert sum(s.by_severity.values()) == len(issues)
