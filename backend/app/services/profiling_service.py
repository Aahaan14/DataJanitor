"""
DataJanitor — dataset profiling (read-only).

Builds per-column metadata, type inference, basic statistics and a preview.
Nothing here modifies the DataFrame.

Type inference is deliberately conservative and transparent:
  integer / float / boolean / datetime — every non-missing value fits.
  mixed — at least 80% fit numeric or date but some do not. These are the
          columns Phase 3 will inspect for invalid values.
  text  — everything else.   empty — no non-missing values.
`parse_ratio` exposes how well values fit, so the type is never a black box.
"""

import re
import warnings
from typing import Dict, List, Optional, Tuple

import pandas as pd

from app.schemas.dataset import ColumnProfile, DatasetPreview, PreviewRow, StatValue

MIXED_THRESHOLD = 0.8
SEMANTIC_NUMERIC_THRESHOLD = 0.6
_SEMANTIC_NUMERIC_NAME = re.compile(r"(^|[_\s-])(unit[_\s-]?price|price|amount|cost|total|subtotal|revenue|salary|wage|age|quantity|qty|count|discount|tax|rate|score|weight|height|length|width|duration)([_\s-]|$)", re.IGNORECASE)
_BOOLEAN_TOKENS = {"true", "false", "yes", "no", "y", "n", "t", "f"}
_HAS_DIGIT = re.compile(r"\d")


def _clean(value: object) -> StatValue:
    """Convert numpy/pandas scalars (and NaN) to JSON-safe Python values."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float):
        return round(value, 4)
    return value


def _numeric_series(values: pd.Series) -> pd.Series:
    """Parse common numeric display formats for profiling without mutating raw data.

    Commas are treated as thousands separators only when grouped in threes;
    currency symbols are stripped only from the beginning of a value. Percent
    values remain text because their intended scale (e.g. 12 vs 0.12) is unclear.
    """
    cleaned = values.astype("string").str.strip()
    cleaned = cleaned.str.replace(r"^([$€£₹¥])\s*", "", regex=True)
    cleaned = cleaned.str.replace(r"(?<=\d),(?=\d{3}(?:\D|$))", "", regex=True)
    return pd.to_numeric(cleaned, errors="coerce")


def _date_series(values: pd.Series) -> pd.Series:
    """Parse plausible date strings; others become NaT. Never raises."""
    candidate = values.str.strip()
    plausible = candidate.str.contains(_HAS_DIGIT) & (candidate.str.len() >= 6)
    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns]")
    if plausible.any():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            parsed.loc[plausible] = pd.to_datetime(
                candidate[plausible], errors="coerce", format="mixed"
            )
    return parsed


def infer_column_type(values: pd.Series, name: Optional[str] = None) -> Tuple[str, Optional[float]]:
    """Return (inferred_type, parse_ratio) for non-missing strings. Semantic numeric headers get a lower mixed threshold."""
    if values.empty:
        return "empty", None

    lowered = values.str.strip().str.lower()
    if lowered.isin(_BOOLEAN_TOKENS).all():
        return "boolean", 1.0

    numeric_ratio = float(_numeric_series(values).notna().mean())
    if numeric_ratio == 1.0:
        as_num = _numeric_series(values)
        is_int = (as_num == as_num.round()).all() and not values.str.contains(
            r"[.eE]"
        ).any()
        return ("integer" if is_int else "float"), 1.0
    numeric_threshold = SEMANTIC_NUMERIC_THRESHOLD if name and _SEMANTIC_NUMERIC_NAME.search(str(name)) else MIXED_THRESHOLD
    if numeric_ratio >= numeric_threshold:
        return "mixed", round(numeric_ratio, 4)

    date_ratio = float(_date_series(values).notna().mean())
    if date_ratio == 1.0:
        return "datetime", 1.0
    if date_ratio >= MIXED_THRESHOLD:
        return "mixed", round(date_ratio, 4)

    return "text", None


def _numeric_stats(values: pd.Series) -> Dict[str, StatValue]:
    nums = _numeric_series(values).dropna()
    if nums.empty:
        return {}
    return {
        "min": _clean(nums.min()),
        "max": _clean(nums.max()),
        "mean": _clean(nums.mean()),
        "median": _clean(nums.median()),
        "std": _clean(nums.std()) if len(nums) > 1 else None,
    }


def _text_stats(values: pd.Series) -> Dict[str, StatValue]:
    if values.empty:
        return {}
    counts = values.value_counts()
    lengths = values.str.len()
    return {
        "top_value": _clean(counts.index[0]),
        "top_frequency": _clean(counts.iloc[0]),
        "min_length": _clean(lengths.min()),
        "max_length": _clean(lengths.max()),
    }


def _datetime_stats(values: pd.Series) -> Dict[str, StatValue]:
    dates = _date_series(values).dropna()
    if dates.empty:
        return {}
    return {"earliest": str(dates.min().date()), "latest": str(dates.max().date())}


def profile_column(name: str, series: pd.Series) -> ColumnProfile:
    total = len(series)
    values = series.dropna()
    missing = total - len(values)
    inferred, ratio = infer_column_type(values, name=name)

    if inferred in ("integer", "float"):
        stats = _numeric_stats(values)
    elif inferred == "datetime":
        stats = _datetime_stats(values)
    elif inferred == "mixed":
        stats = _numeric_stats(values) or _text_stats(values)
    elif inferred == "empty":
        stats = {}
    else:
        stats = _text_stats(values)

    return ColumnProfile(
        name=str(name),
        inferred_type=inferred,
        non_null_count=int(len(values)),
        missing_count=int(missing),
        missing_percent=round(100 * missing / total, 2) if total else 0.0,
        unique_count=int(values.nunique()),
        parse_ratio=ratio,
        stats=stats,
    )


def profile_dataframe(df: pd.DataFrame) -> List[ColumnProfile]:
    return [profile_column(col, df[col]) for col in df.columns]


def build_preview(df: pd.DataFrame, n_rows: int, offset: int = 0) -> DatasetPreview:
    """`n_rows` rows starting at `offset`. Missing cells become null; text is untouched."""
    head = df.iloc[offset: offset + n_rows]
    rows = [
        PreviewRow(
            row_number=int(idx) + 1,
            values={str(c): (None if pd.isna(v) else v) for c, v in rec.items()},
        )
        for idx, rec in zip(head.index, head.to_dict(orient="records"))
    ]
    return DatasetPreview(
        columns=[str(c) for c in df.columns],
        rows=rows,
        preview_row_count=len(rows),
    )
