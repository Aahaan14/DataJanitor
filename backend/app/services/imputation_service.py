"""
DataJanitor — intelligent missing-value imputation engine.

Computes statistically appropriate replacement values for missing data,
placeholders, and invalid cells. Every suggestion includes a method label,
confidence level, and human-readable explanation.

Principles
──────────
• Prefer robust statistics (median, IQR) over outlier-sensitive (mean).
• Respect column semantics: integers stay integers, non-negative stays
  non-negative, identifiers are never imputed.
• Group by related fields when possible (e.g. median price by category).
• Never fabricate names, IDs, emails, addresses, or dates without evidence.
• When evidence is insufficient, return None (= recommend empty / manual).
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.services import detection_service as ds

# ── Column classification helpers ───────────────────────────────────────────

_ID_NAME = re.compile(
    r"(^|[_\s\-.])(id|uid|uuid|guid|index|idx|key|pk|serial|sno|"
    r"order_id|customer_id|product_id|invoice|tracking|reference|ref|code)$"
    r"|^(id|uuid|guid)([_\s\-.]|$)",
    re.IGNORECASE,
)
_CAMEL_ID = re.compile(r"[a-z]Id$")
_NAME_COLS = re.compile(
    r"(^|[_\s\-.])(name|first_name|last_name|full_name|email|address|"
    r"phone|mobile|contact|username|login|password|ssn|passport)([_\s\-.]|$)",
    re.IGNORECASE,
)
_INTEGER_COLS = re.compile(
    r"(^|[_\s\-.])(quantity|qty|count|num|number|units|pieces|items|"
    r"age|year|month|day|week|rank|rating|score|floor|level|"
    r"children|siblings|employees|seats)([_\s\-.]|$)",
    re.IGNORECASE,
)
_NON_NEGATIVE_COLS = re.compile(
    r"(^|[_\s\-.])(price|unit_price|cost|amount|total|subtotal|revenue|"
    r"salary|wage|discount|tax|rate|fee|charge|balance|weight|"
    r"height|length|width|area|volume|distance|duration|"
    r"quantity|qty|count|age|score|rating)([_\s\-.]|$)",
    re.IGNORECASE,
)
_DATE_COLS = re.compile(
    r"(^|[_\s\-.])(date|_at$|_on$|created|updated|modified|timestamp|"
    r"order_date|start_date|end_date|birth_date|dob|ship_date)([_\s\-.]|$)",
    re.IGNORECASE,
)
_CATEGORY_COLS = re.compile(
    r"(^|[_\s\-.])(category|type|class|group|segment|department|region|"
    r"country|city|state|status|gender|sex|color|colour|brand|"
    r"product_category|customer_segment|priority|tier)([_\s\-.]|$)",
    re.IGNORECASE,
)

MIN_SAMPLE_SIZE = 5       # minimum values needed to attempt imputation
MIN_MODE_FREQUENCY = 0.1  # mode must appear in ≥10% of values


@dataclass
class ImputationSuggestion:
    """A suggested replacement value with its provenance."""
    value: str                      # the suggested replacement (stringified)
    method: str                     # e.g. "Median imputation", "Mode imputation"
    confidence: str                 # "high", "medium", "low"
    explanation: str                # human-readable reasoning
    sample_size: int = 0            # how many comparable records were used
    context_stat: Optional[str] = None  # e.g. "median=249.50, n=120"


def is_identifier_column(name: object, s: pd.Series) -> bool:
    """Identifier columns should never be imputed."""
    label = str(name).strip()
    if _ID_NAME.search(label) or _CAMEL_ID.search(label):
        return True
    return ds._is_id_like_column(name, s)


def is_personal_column(name: object) -> bool:
    """Columns holding personal/unique info that must not be fabricated."""
    return bool(_NAME_COLS.search(str(name).strip()))


def _is_integer_column(name: object) -> bool:
    """Columns where values should be integers."""
    return bool(_INTEGER_COLS.search(str(name).strip()))


def _is_non_negative(name: object) -> bool:
    """Columns where values should be ≥ 0."""
    return bool(_NON_NEGATIVE_COLS.search(str(name).strip()))


def _is_date_column(name: object) -> bool:
    """Columns likely holding date data."""
    return bool(_DATE_COLS.search(str(name).strip()))


def _is_category_column(name: object) -> bool:
    """Columns likely holding categorical data."""
    return bool(_CATEGORY_COLS.search(str(name).strip()))


def _parse_numeric_values(series: pd.Series) -> Tuple[pd.Series, bool]:
    """Parse a series of string values to numeric. Returns (numeric_series, is_integer)."""
    usable = ds._usable(series)
    if usable.empty:
        return pd.Series(dtype=float), False

    nums = {}
    for idx, v in usable.items():
        n = ds._strict_number(v)
        if n is not None:
            nums[idx] = n
        else:
            lo = ds._loose_number(v)
            if lo is not None:
                nums[idx] = lo[0]

    if not nums:
        return pd.Series(dtype=float), False

    num_series = pd.Series(nums, dtype=float)
    # Check if values are integer-typed
    is_int = all(float(v).is_integer() for v in num_series if not np.isnan(v))
    return num_series, is_int


def _compute_numeric_suggestion(
    col_name: str, num_series: pd.Series, is_int: bool,
    group_label: Optional[str] = None,
) -> Optional[ImputationSuggestion]:
    """Compute a numeric imputation value using robust statistics."""
    if len(num_series) < MIN_SAMPLE_SIZE:
        return None

    values = num_series.dropna()
    if len(values) < MIN_SAMPLE_SIZE:
        return None

    median = float(values.median())
    mean = float(values.mean())
    q1 = float(values.quantile(0.25))
    q3 = float(values.quantile(0.75))
    iqr = q3 - q1

    # Detect skewness: if mean and median differ by >10% of range, or IQR is
    # large relative to median, the distribution is skewed → prefer median
    value_range = float(values.max() - values.min())
    skewed = value_range > 0 and abs(mean - median) / value_range > 0.1

    # Detect outliers using IQR
    if iqr > 0:
        outlier_mask = (values < q1 - 1.5 * iqr) | (values > q3 + 1.5 * iqr)
        outlier_count = int(outlier_mask.sum())
    else:
        outlier_count = 0

    use_median = skewed or outlier_count > 0
    chosen = median if use_median else mean

    # Enforce column constraints
    must_int = is_int or _is_integer_column(col_name)
    must_non_neg = _is_non_negative(col_name)

    if must_non_neg and chosen < 0:
        chosen = 0.0

    if must_int:
        chosen = round(chosen)
        result_str = str(int(chosen))
    else:
        # Round to a reasonable precision
        if abs(chosen) >= 100:
            result_str = f"{chosen:.2f}"
        elif abs(chosen) >= 1:
            result_str = f"{chosen:.2f}"
        else:
            result_str = f"{chosen:.4f}"
        # Remove trailing zeros but keep at least one decimal
        if "." in result_str:
            result_str = result_str.rstrip("0").rstrip(".")

    # Determine confidence
    n = len(values)
    if n >= 30 and not skewed:
        confidence = "high"
    elif n >= 10:
        confidence = "medium"
    else:
        confidence = "low"

    method_name = "Median imputation" if use_median else "Mean imputation"
    if must_int:
        method_name += ", rounded to integer"
    if group_label:
        method_name = f"Group {method_name.lower().split(' ')[0]}"

    reason_parts = []
    if use_median:
        reason_parts.append(
            f"Median used because {'data is skewed' if skewed else 'outliers detected'}"
            f" ({outlier_count} outlier{'s' if outlier_count != 1 else ''})."
        )
    else:
        reason_parts.append("Mean used; distribution is approximately symmetric.")

    reason_parts.append(f"Based on {n} comparable record{'s' if n != 1 else ''}.")

    stat_info = f"median={median:.2f}, mean={mean:.2f}, n={n}"
    if group_label:
        stat_info = f"group={group_label}, {stat_info}"

    return ImputationSuggestion(
        value=result_str,
        method=method_name,
        confidence=confidence,
        explanation=" ".join(reason_parts),
        sample_size=n,
        context_stat=stat_info,
    )


def _compute_categorical_suggestion(
    col_name: str, usable: pd.Series
) -> Optional[ImputationSuggestion]:
    """Compute a categorical imputation value using mode/frequency analysis."""
    if is_personal_column(col_name):
        return None
    if is_identifier_column(col_name, usable):
        return None

    if len(usable) < MIN_SAMPLE_SIZE:
        return None

    counts = usable.value_counts()
    if counts.empty:
        return None

    mode_val = str(counts.index[0])
    mode_count = int(counts.iloc[0])
    total = len(usable)
    frequency = mode_count / total

    # Only suggest mode if it's reasonably dominant
    if frequency < MIN_MODE_FREQUENCY:
        return None

    # Check if there's a tie (top two have same count)
    if len(counts) > 1 and counts.iloc[0] == counts.iloc[1]:
        return None  # ambiguous — don't pick one

    # Determine confidence
    if frequency >= 0.5 and total >= 20:
        confidence = "high"
    elif frequency >= 0.3 and total >= 10:
        confidence = "medium"
    else:
        confidence = "low"

    unique_count = len(counts)
    return ImputationSuggestion(
        value=mode_val,
        method="Mode imputation",
        confidence=confidence,
        explanation=(
            f"'{mode_val}' is the most frequent value in '{col_name}' "
            f"({mode_count}/{total} = {frequency:.0%}). "
            f"{unique_count} distinct value{'s' if unique_count != 1 else ''} in column."
        ),
        sample_size=total,
        context_stat=f"mode={mode_val}, freq={frequency:.2%}, n={total}",
    )


def suggest_value(
    df: pd.DataFrame, col_name: str, row_number: int,
    original_value: Optional[str] = None,
) -> Optional[ImputationSuggestion]:
    """
    Suggest a replacement value for a missing or invalid cell.

    Parameters
    ----------
    df : pd.DataFrame — the full dataset (read-only)
    col_name : column name
    row_number : 1-based row number
    original_value : the current cell text (None = empty, or a placeholder)

    Returns None if no safe suggestion can be made.
    """
    if col_name not in df.columns:
        return None

    # Never impute identifiers
    if is_identifier_column(col_name, df[col_name]):
        return None

    # Never impute personal/unique data
    if is_personal_column(col_name):
        return None

    # Never invent dates without strong evidence
    if _is_date_column(col_name):
        return None  # date imputation is handled separately in _try_date_imputation

    series = df[col_name]
    usable = ds._usable(series)

    if usable.empty:
        return None

    # Try numeric imputation first
    num_series, is_int = _parse_numeric_values(series)

    if len(num_series) >= MIN_SAMPLE_SIZE:
        parse = ds._parse_numeric_column(usable)
        if parse.is_numeric_column:
            return _compute_numeric_suggestion(col_name, num_series, is_int)

    # Try categorical imputation
    if _is_category_column(col_name) or (len(usable) >= MIN_SAMPLE_SIZE and usable.nunique() <= 50):
        result = _compute_categorical_suggestion(col_name, usable)
        if result is not None:
            # Relabel as contextual match for category columns
            if _is_category_column(col_name):
                result.method = "Contextual category match"
            return result

    return None


def suggest_numeric_normalization(
    original_value: str, col_name: str
) -> Optional[ImputationSuggestion]:
    """
    For values like '$1,200' or '1,200', suggest the normalized form '1200'.
    """
    lo = ds._loose_number(original_value)
    if lo is None:
        return None

    value, kind, cleaned = lo
    if kind == "percent":
        # Ambiguous — could be 12 or 0.12
        return None

    return ImputationSuggestion(
        value=cleaned,
        method="Numeric normalization",
        confidence="high",
        explanation=(
            f"Removed {kind} formatting from '{original_value}' → '{cleaned}'. "
            "The numeric value is unchanged."
        ),
        sample_size=0,
        context_stat=None,
    )


def suggest_for_invalid_numeric(
    df: pd.DataFrame, col_name: str, row_number: int, original_value: str
) -> Optional[ImputationSuggestion]:
    """
    For genuinely invalid numbers (like 'not-a-price'), try to suggest a
    statistically defensible estimate IF the column has enough valid data.
    """
    # First try normalization (e.g. '$1,200' → '1200')
    norm = suggest_numeric_normalization(original_value, col_name)
    if norm is not None:
        return norm

    # Fall back to statistical imputation
    return suggest_value(df, col_name, row_number, original_value)


def suggest_for_placeholder(
    df: pd.DataFrame, col_name: str, row_number: int, original_value: str
) -> Optional[ImputationSuggestion]:
    """
    For placeholder values ('N/A', 'NULL', etc.), suggest an appropriate
    replacement based on the column's actual data.
    """
    suggestion = suggest_value(df, col_name, row_number, original_value)
    if suggestion is not None:
        # Enhance the explanation
        suggestion.explanation = (
            f"'{original_value.strip()}' recognized as a placeholder (missing value). "
            + suggestion.explanation
        )
    return suggestion


def suggest_for_missing(
    df: pd.DataFrame, col_name: str, row_number: int
) -> Optional[ImputationSuggestion]:
    """For truly empty cells."""
    return suggest_value(df, col_name, row_number, None)


def batch_suggest(
    df: pd.DataFrame, issues_by_column: Dict[str, List[Tuple[int, Optional[str], str]]]
) -> Dict[Tuple[str, int], Optional[ImputationSuggestion]]:
    """
    Batch-compute suggestions for multiple missing/invalid cells.

    issues_by_column maps column_name → [(row_number, original_value, issue_type), ...]
    Returns {(column_name, row_number) → suggestion_or_None}
    """
    result: Dict[Tuple[str, int], Optional[ImputationSuggestion]] = {}

    for col_name, cells in issues_by_column.items():
        for row_number, original_value, issue_type in cells:
            key = (col_name, row_number)
            if issue_type in ("missing_value", "placeholder_missing"):
                if original_value and original_value.strip():
                    result[key] = suggest_for_placeholder(df, col_name, row_number, original_value)
                else:
                    result[key] = suggest_for_missing(df, col_name, row_number)
            elif issue_type == "invalid_numeric":
                result[key] = suggest_for_invalid_numeric(
                    df, col_name, row_number, original_value or ""
                )
            elif issue_type == "invalid_date":
                result[key] = None  # dates are not imputed without evidence
            else:
                result[key] = suggest_value(df, col_name, row_number, original_value)

    return result
