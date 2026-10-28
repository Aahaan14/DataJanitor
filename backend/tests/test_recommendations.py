"""DataJanitor — Phase 4: repair recommendation engine (no HTTP)."""

import io

import pandas as pd

from app.schemas.issues import IssueType
from app.schemas.repairs import Classification, RepairAction
from app.schemas.validation import RuleViolation
from app.services import detection_service as ds
from app.services import recommendation_service as rs


def make_df(csv: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(csv.strip() + "\n"), dtype=str,
                       keep_default_na=False, na_values=[""])


def plan_for(csv: str, violations=None):
    df = make_df(csv)
    props, skipped, trunc = rs.build_proposals(df, ds.run_detection(df), violations or [], 1000)
    return df, props, skipped, trunc


def of_type(props, t):
    return [p for p in props if p.issue_type == t]


def test_whitespace_is_safe_and_exact():
    _, props, *_ = plan_for('name,n\n" Alice ",1\nBob,2\n')
    p = of_type(props, IssueType.WHITESPACE)[0]
    assert p.classification == Classification.SAFE
    assert (p.original_value, p.proposed_value) == (" Alice ", "Alice")
    assert p.action == RepairAction.REPLACE_VALUE


def test_thousands_separator_safe_percent_ambiguous_with_alternatives():
    _, props, *_ = plan_for('v\n10\n20\n"1,200"\n12%\n30\n')
    fmt = {p.original_value: p for p in of_type(props, IssueType.NUMERIC_FORMAT)}
    assert fmt["1,200"].classification == Classification.SAFE
    assert fmt["1,200"].proposed_value == "1200"
    assert fmt["12%"].classification == Classification.AMBIGUOUS
    assert fmt["12%"].proposed_value is None
    assert fmt["12%"].alternatives == ["12", "0.12"]


def test_invalid_values_only_offer_clearing_never_a_guess():
    _, props, *_ = plan_for("age\n" + "\n".join(map(str, range(20, 40))) + "\nabc\n")
    p = of_type(props, IssueType.INVALID_NUMERIC)[0]
    assert p.action == RepairAction.CLEAR_VALUE and p.proposed_value is None
    assert p.allow_custom_value and p.confidence.value == "low"


def test_missing_values_and_outliers_get_no_proposal_but_are_explained():
    _, props, skipped, _ = plan_for("a,b\n1,x\n,y\n3,z\n")
    assert props == []
    groups = {g.issue_type: g for g in skipped}
    assert "never invented" in groups["missing_value"].reason


def test_date_conversion_unambiguous_vs_ambiguous():
    csv = "d\n2024-01-05\n2024-01-06\n2024-01-07\n2024-01-08\n2024/03/09\n25/12/2024\n03/04/2024\n"
    _, props, *_ = plan_for(csv)
    by = {p.original_value: p for p in of_type(props, IssueType.INCONSISTENT_DATE_FORMAT)}
    assert by["2024/03/09"].proposed_value == "2024-03-09"
    assert by["2024/03/09"].classification == Classification.SAFE
    assert by["25/12/2024"].proposed_value == "2024-12-25"  # only day-first is valid
    assert by["03/04/2024"].classification == Classification.AMBIGUOUS
    assert by["03/04/2024"].proposed_value is None
    assert by["03/04/2024"].alternatives == ["2024-04-03", "2024-03-04"]


def test_text_case_canonical_needs_approval_ties_offer_choices():
    _, props, *_ = plan_for("c\nPune\nPune\nPune\npune\n")
    p = of_type(props, IssueType.INCONSISTENT_TEXT_FORMAT)[0]
    assert p.classification == Classification.AMBIGUOUS and p.proposed_value == "Pune"
    _, tie, *_ = plan_for("c\nPune\npune\n")
    t = of_type(tie, IssueType.INCONSISTENT_TEXT_FORMAT)
    assert all(x.proposed_value is None and x.alternatives for x in t)


def test_duplicate_removal_is_always_ambiguous_and_never_deletes_the_first_copy():
    _, props, *_ = plan_for("id,n\n1,a\n2,b\n1,a\n")
    p = of_type(props, IssueType.EXACT_DUPLICATE)[0]
    assert p.action == RepairAction.DELETE_ROW and p.row_number == 3
    assert p.classification == Classification.AMBIGUOUS
    assert all(x.row_number != 1 for x in props if x.action == RepairAction.DELETE_ROW)


def test_original_and_proposed_values_are_stored_separately_and_unique_ids():
    _, props, *_ = plan_for('name,n\n" Alice ",1\n"Bob  Lee",2\n')
    assert len({p.proposal_id for p in props}) == len(props)
    assert all(p.original_value != p.proposed_value for p in props)


def test_conflicts_same_cell_and_row_delete_vs_cell_edit():
    csv = "id,name,city\n1,Alice Smith,Pune\n2,alice smith ,Pune\n3,Zed,Delhi\n"
    _, props, *_ = plan_for(csv)
    ws = [p for p in props if p.issue_type == IssueType.WHITESPACE][0]
    ci = [p for p in props if p.issue_type == IssueType.INCONSISTENT_TEXT_FORMAT
          and p.row_number == 2][0]  # same cell as the whitespace proposal
    dup = [p for p in props if p.issue_type == IssueType.POTENTIAL_DUPLICATE][0]
    assert ci.proposal_id in ws.conflicts_with and ws.proposal_id in ci.conflicts_with
    assert dup.proposal_id in ws.conflicts_with and ws.proposal_id in dup.conflicts_with


def test_rule_violation_proposals_skip_missing_unique_and_covered_cells():
    df = make_df("age,id\n200,1\n,2\n abc,3\n")
    vs = [RuleViolation(column="age", row_number=1, rule="must be <= 120", observed_value="200"),
          RuleViolation(column="age", row_number=2, rule="value is required (empty not allowed)"),
          RuleViolation(column="id", row_number=1, rule="value must be unique in the column")]
    props, skipped, _ = rs.build_proposals(df, [], vs, 100)
    assert [(p.row_number, p.issue_type) for p in props] == [(1, IssueType.RULE_VIOLATION)]
    assert props[0].action == RepairAction.CLEAR_VALUE and props[0].allow_custom_value
    assert sum(g.count for g in skipped) == 2


def test_proposal_cap_truncates_and_flags():
    csv = "n\n" + "\n".join(f'" v{i}"' for i in range(30)) + "\n"
    df = make_df(csv)
    props, _, truncated = rs.build_proposals(df, ds.run_detection(df), [], 10)
    assert len(props) == 10 and truncated is True
