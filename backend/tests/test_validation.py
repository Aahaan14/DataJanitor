"""DataJanitor — Phase 4: Pandera-backed validation rules."""

import io

import pandas as pd
import pytest
from pydantic import ValidationError

from app.schemas.validation import ColumnRule, RuleSet
from app.services import validation_service as vs


def make_df(csv: str) -> pd.DataFrame:
    return pd.read_csv(io.StringIO(csv.strip() + "\n"), dtype=str,
                       keep_default_na=False, na_values=[""])


def rules(*rs):
    return RuleSet(rules=list(rs))


def found(df, ruleset):
    return {(v.column, v.row_number, v.rule) for v in vs.validate_dataframe(df, ruleset)}


def test_no_rules_means_no_violations():
    assert vs.validate_dataframe(make_df("a\n1\n"), RuleSet()) == []


def test_integer_and_range_rules():
    df = make_df("age\n30\nabc\n200\n-5\n")
    r = rules(ColumnRule(column="age", dtype="integer", min_value=0, max_value=120))
    assert found(df, r) == {
        ("age", 2, "must be an integer"),
        ("age", 3, "must be <= 120"),
        ("age", 4, "must be >= 0"),
    }


def test_nullable_false_flags_empty_cells_once():
    df = make_df("a,b\n1,x\n,y\n")
    r = rules(ColumnRule(column="a", dtype="integer", nullable=False))
    assert found(df, r) == {("a", 2, "value is required (empty not allowed)")}


def test_empty_cells_skip_other_checks_when_nullable():
    df = make_df("a,b\n,x\n5,y\n")
    assert vs.validate_dataframe(df, rules(ColumnRule(column="a", dtype="integer"))) == []


def test_allowed_values_regex_and_length():
    df = make_df("city,code\nPune,AB12\nX,zz\n")
    r = rules(ColumnRule(column="city", allowed_values=["Pune", "Delhi"]),
              ColumnRule(column="code", regex=r"[A-Z]{2}\d{2}", max_length=4))
    got = found(df, r)
    assert ("city", 2, "must be one of ['Delhi', 'Pune']") in got
    assert any(c == "code" and row == 2 for c, row, _ in got)
    assert not any(row == 1 for _, row, _ in got)


def test_date_and_boolean_rules():
    df = make_df("d,flag\n2024-01-05,yes\n2024-02-30,maybe\n")
    r = rules(ColumnRule(column="d", dtype="date"), ColumnRule(column="flag", dtype="boolean"))
    assert found(df, r) == {("d", 2, "must be a valid date"),
                            ("flag", 2, "must be a boolean (true/false/yes/no)")}


def test_unique_rule_reports_every_duplicate_row():
    df = make_df("id\n1\n2\n2\n3\n")
    got = found(df, rules(ColumnRule(column="id", unique=True)))
    assert {(c, r) for c, r, _ in got} == {("id", 2), ("id", 3)}


def test_missing_required_column_is_a_column_level_violation():
    got = vs.validate_dataframe(make_df("a\n1\n"), rules(ColumnRule(column="zzz")))
    assert got[0].column == "zzz" and got[0].row_number is None


def test_all_violations_collected_not_just_first():
    df = make_df("a\nx\ny\nz\n")
    assert len(vs.validate_dataframe(df, rules(ColumnRule(column="a", dtype="integer")))) == 3


def test_rule_model_validation():
    with pytest.raises(ValidationError):
        ColumnRule(column="a", dtype="integer", min_value=5, max_value=1)
    with pytest.raises(ValidationError):
        ColumnRule(column="a", regex="([unclosed")
    with pytest.raises(ValidationError):
        ColumnRule(column="a", min_value=1)  # range needs a numeric dtype
    with pytest.raises(ValidationError):
        RuleSet(rules=[ColumnRule(column="a"), ColumnRule(column="a")])
    with pytest.raises(ValidationError):
        ColumnRule(column="a", regex="x" * 201)


def test_value_violations_for_single_value():
    r = rules(ColumnRule(column="age", dtype="integer", min_value=0, max_value=120, nullable=False))
    assert vs.value_violations(r, "age", "50") == []
    assert vs.value_violations(r, "age", "500") == ["must be <= 120"]
    assert vs.value_violations(r, "age", None) == ["value is required (empty not allowed)"]
    assert vs.value_violations(r, "other", "anything") == []


def test_suggest_rules_infers_types_and_nullability():
    df = make_df("id,age,name,joined\n1,30,Al,2024-01-05\n2,,Bo,2024-01-06\n")
    by = {r.column: r for r in vs.suggest_rules(df).rules}
    assert by["id"].dtype == "integer" and by["id"].nullable is False
    assert by["age"].nullable is True
    assert by["name"].dtype is None
    assert by["joined"].dtype == "date"
