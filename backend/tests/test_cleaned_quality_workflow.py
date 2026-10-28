"""Regression tests for approved repairs producing a cleaner CSV-ready frame.

These tests deliberately keep the human-approval boundary: detection creates
proposals, and only proposals explicitly passed to apply_repairs may change data.
"""

import io
from types import SimpleNamespace as P

import pandas as pd

from app.schemas.issues import IssueType
from app.services import detection_service as ds
from app.services import profiling_service as ps
from app.services import recommendation_service as rec
from app.services import repair_service as repair


def read_frame(text: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, na_values=[""])


def test_unit_price_profile_recognizes_currency_and_thousands_separators():
    df = read_frame('Unit_Price\n"$1,200"\n"$25.50"\n30\nnot-a-price\n')
    profile = ps.profile_column("Unit_Price", df["Unit_Price"])
    assert profile.inferred_type == "mixed"
    assert profile.parse_ratio is not None and profile.parse_ratio >= 0.6


def test_scan_proposes_numeric_normalization_placeholder_clear_and_exact_duplicate_removal():
    df = read_frame(
        'Unit_Price,Order_Date,Status,SKU\n'
        '"$1,200",2024-01-01,ok,A1\n'
        '"$25.50",2024/01/02,N/A,A2\n'
        '"$25.50",2024/01/02,N/A,A2\n'
        'not-a-price,2024-01-04,ok,A4\n'
    )
    issues = ds.run_detection(df)
    proposals, skipped, truncated = rec.build_proposals(df, issues, [], 1000)
    assert not truncated

    numeric = [p for p in proposals if p.issue_type == IssueType.NUMERIC_FORMAT
               and p.original_value == "$1,200"]
    assert len(numeric) == 1
    assert numeric[0].proposed_value == "1200"

    placeholder = [p for p in proposals if p.issue_type == IssueType.PLACEHOLDER_MISSING
                   and p.column == "Status" and p.row_number == 2]
    assert len(placeholder) == 1
    assert placeholder[0].action.value == "clear_value"

    duplicate = [p for p in proposals if p.issue_type == IssueType.EXACT_DUPLICATE]
    assert len(duplicate) == 1 and duplicate[0].row_number == 3
    assert duplicate[0].action.value == "delete_row"

    # Missing/invalid values are never guessed. They remain findings for review.
    assert any(i.issue_type == IssueType.INVALID_NUMERIC and i.row_number == 4 for i in issues)
    assert any(g.issue_type == IssueType.INVALID_NUMERIC.value for g in skipped)


def test_only_approved_repairs_change_output_and_final_detection_reports_unresolved_values():
    df = read_frame(
        'Unit_Price,Order_Date,Status,SKU\n'
        '"$1,200",2024-01-01,ok,A1\n'
        '"$25.50",2024/01/02,N/A,A2\n'
        '"$25.50",2024/01/02,N/A,A2\n'
        'not-a-price,2024-01-04,ok,A4\n'
    )
    original_snapshot = df.copy(deep=True)
    issues = ds.run_detection(df)
    proposals, _, _ = rec.build_proposals(df, issues, [], 1000)

    # Approve only the deterministic currency normalization and exact duplicate
    # removal. The placeholder clear is intentionally not approved here.
    selected = [p for p in proposals if
                (p.issue_type == IssueType.NUMERIC_FORMAT and p.original_value == "$1,200") or
                p.issue_type == IssueType.EXACT_DUPLICATE]
    approved = [P(id=p.proposal_id, action=p.action.value, row_number=p.row_number,
                  column_name=p.column, original_value=p.original_value,
                  approved_value=p.proposed_value) for p in selected]
    result = repair.apply_repairs(df, approved)

    assert len(result.cleaned) == 3
    assert result.cleaned.iloc[0]["Unit_Price"] == "1200"
    assert result.cleaned.duplicated(keep="first").sum() == 0
    assert result.cleaned.iloc[1]["Status"] == "N/A"  # unapproved proposal unchanged
    assert result.cleaned.iloc[2]["Unit_Price"] == "not-a-price"
    pd.testing.assert_frame_equal(df, original_snapshot)  # source is untouched

    remaining = ds.run_detection(result.cleaned)
    assert any(i.issue_type == IssueType.PLACEHOLDER_MISSING for i in remaining)
    assert any(i.issue_type == IssueType.INVALID_NUMERIC for i in remaining)
