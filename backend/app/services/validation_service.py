"""
DataJanitor — configurable validation with Pandera (Phase 4).

Turns a user-supplied `RuleSet` into a `pandera.DataFrameSchema` and
validates the raw-text DataFrame with `lazy=True`, so *every* violation is
collected instead of stopping at the first.

Why element-wise string checks? The DataFrame holds raw text (Phase 2
decision). Coercing to numbers first would conflate "empty" with "not a
number". Each dtype rule therefore checks the text itself.

Pandera skips empty cells in checks when nullable=True, so emptiness is
governed only by the `nullable` flag — never double-reported.
"""

import re
from typing import List, Optional

import pandas as pd
import pandera.pandas as pa

from app.schemas.validation import ColumnRule, RuleSet, RuleViolation, ValidationSummary
from app.services import detection_service as ds

_INTEGER_RE = re.compile(r"^[-+]?\d+$")
_BOOLEAN_TOKENS = {"true", "false", "yes", "no", "y", "n", "t", "f", "0", "1"}
SAMPLE_SIZE = 50


def _is_valid_date(v: str) -> bool:
    fi = ds._classify_date(v)  # shape check shared with the detection engine
    return fi is not None and ds._valid_date(v, ds.DATE_FAMILIES[fi], None)


def _dtype_check(dtype: str) -> Optional[pa.Check]:
    if dtype == "integer":
        return pa.Check(lambda v: bool(_INTEGER_RE.match(v.strip())),
                        element_wise=True, error="must be an integer")
    if dtype == "float":
        return pa.Check(lambda v: ds._strict_number(v) is not None,
                        element_wise=True, error="must be a number")
    if dtype == "date":
        return pa.Check(_is_valid_date, element_wise=True, error="must be a valid date")
    if dtype == "boolean":
        return pa.Check(lambda v: v.strip().lower() in _BOOLEAN_TOKENS,
                        element_wise=True, error="must be a boolean (true/false/yes/no)")
    return None


def _column_checks(rule: ColumnRule) -> List[pa.Check]:
    checks: List[pa.Check] = []
    dtype_check = _dtype_check(rule.dtype) if rule.dtype else None
    if dtype_check is not None:
        checks.append(dtype_check)
    # Range checks ignore unparseable text: the dtype check already reports it.
    if rule.min_value is not None:
        lo = rule.min_value
        checks.append(pa.Check(
            lambda v: (n := ds._strict_number(v)) is None or n >= lo,
            element_wise=True, error=f"must be >= {lo:g}"))
    if rule.max_value is not None:
        hi = rule.max_value
        checks.append(pa.Check(
            lambda v: (n := ds._strict_number(v)) is None or n <= hi,
            element_wise=True, error=f"must be <= {hi:g}"))
    if rule.min_length is not None:
        n_min = rule.min_length
        checks.append(pa.Check(lambda v: len(v) >= n_min, element_wise=True,
                               error=f"length must be >= {n_min}"))
    if rule.max_length is not None:
        n_max = rule.max_length
        checks.append(pa.Check(lambda v: len(v) <= n_max, element_wise=True,
                               error=f"length must be <= {n_max}"))
    if rule.allowed_values is not None:
        allowed = set(rule.allowed_values)
        checks.append(pa.Check(lambda v: v in allowed, element_wise=True,
                               error=f"must be one of {sorted(allowed)[:10]}"))
    if rule.regex is not None:
        pattern = re.compile(rule.regex)
        checks.append(pa.Check(lambda v: pattern.fullmatch(v) is not None,
                               element_wise=True, error=f"must match /{rule.regex}/"))
    return checks


def build_schema(ruleset: RuleSet, *, enforce_unique: bool = True) -> pa.DataFrameSchema:
    """Translate rules to a Pandera schema (extra dataset columns are allowed)."""
    columns = {
        r.column: pa.Column(
            str,
            checks=_column_checks(r),
            nullable=r.nullable,
            unique=r.unique and enforce_unique,
            required=True,
            coerce=False,
        )
        for r in ruleset.rules
    }
    return pa.DataFrameSchema(columns, strict=False)


def validate_dataframe(df: pd.DataFrame, ruleset: RuleSet) -> List[RuleViolation]:
    """Return every rule violation (empty list = dataset passes)."""
    if not ruleset.rules:
        return []
    try:
        build_schema(ruleset).validate(df, lazy=True)
        return []
    except pa.errors.SchemaErrors as exc:
        cases = exc.failure_cases
    violations: List[RuleViolation] = []
    for _, case in cases.iterrows():
        index = case["index"]
        has_row = pd.notna(index)
        column = case["column"] if pd.notna(case["column"]) else None
        rule = str(case["check"])
        if rule == "column_in_dataframe":
            column, observed, rule = str(case["failure_case"]), None, "required column is missing"
        elif rule == "not_nullable":
            rule, observed = "value is required (empty not allowed)", None
        elif rule == "field_uniqueness":
            rule, observed = "value must be unique in the column", str(case["failure_case"])
        else:
            fc = case["failure_case"]
            observed = None if pd.isna(fc) else str(fc)
        violations.append(RuleViolation(
            column=column,
            row_number=int(index) + 1 if has_row else None,
            rule=rule,
            observed_value=ds._shorten(observed),
        ))
    return violations


def summarize_violations(violations: List[RuleViolation], rule_count: int) -> ValidationSummary:
    by_col: dict = {}
    for v in violations:
        if v.column is not None:
            by_col[v.column] = by_col.get(v.column, 0) + 1
    return ValidationSummary(
        ran=rule_count > 0, rule_count=rule_count, violation_count=len(violations),
        by_column=by_col, violations_sample=violations[:SAMPLE_SIZE],
    )


def value_violations(ruleset: RuleSet, column: str, value: Optional[str]) -> List[str]:
    """
    Check ONE proposed value against its column's rule (uniqueness ignored).
    Used to stop a manual correction from introducing a new violation.
    """
    rule = next((r for r in ruleset.rules if r.column == column), None)
    if rule is None:
        return []
    frame = pd.DataFrame({column: pd.Series([value], dtype="object")})
    try:
        build_schema(RuleSet(rules=[rule]), enforce_unique=False).validate(frame, lazy=True)
        return []
    except pa.errors.SchemaErrors as exc:
        out = []
        for _, case in exc.failure_cases.iterrows():
            check = str(case["check"])
            out.append("value is required (empty not allowed)" if check == "not_nullable" else check)
        return out


def suggest_rules(df: pd.DataFrame) -> RuleSet:
    """
    Starter rules inferred from the data (a convenience, never auto-applied):
    a dtype where every non-empty value fits, and nullable=False for columns
    with no empty cells.
    """
    from app.services.profiling_service import infer_column_type  # local: avoid cycle risk

    rules: List[ColumnRule] = []
    for col in df.columns:
        values = df[col].dropna()
        inferred, _ = infer_column_type(values)
        dtype = {"integer": "integer", "float": "float", "datetime": "date",
                 "boolean": "boolean"}.get(inferred)
        rules.append(ColumnRule(column=str(col), dtype=dtype, nullable=bool(df[col].isna().any())))
    return RuleSet(rules=rules)
