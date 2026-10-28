"""
DataJanitor — data-quality detection engine (read-only).

Each detector is a separate pure function: DataFrame in → list[Issue] out.
Nothing here modifies the DataFrame or the stored file. Every finding is a
*detected candidate*, not a confirmed error.

Conventions
───────────
• The DataFrame holds raw strings (NaN = empty cell), exactly as parsed in
  Phase 2. `row_number` = DataFrame index + 1 and never changes.
• "Usable" values are non-empty and not placeholder tokens (NA, null, …);
  placeholders are reported once by their own detector and then ignored by
  the others so one bad cell does not produce several unrelated issues.
• `details` carries machine-readable hints for Phase 4. A `proposed_value`
  appears ONLY when the fix is deterministic (e.g. trimming whitespace).
  Anything ambiguous is marked `"ambiguous": True` and never gets a guess.

Statistical outlier method and its limits are documented on
`detect_outliers`.
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from app.schemas.issues import DetectionSummary, Issue, IssueType, Severity

# ── Tunable constants ───────────────────────────────────────────────────────
PLACEHOLDER_TOKENS = {
    "na", "n/a", "#n/a", "nan", "null", "none", "nil", "missing", "unknown",
    "undefined", "-", "--", "?", "tbd",
}
MAX_OBSERVED_LEN = 200
NUMERIC_COLUMN_THRESHOLD = 0.6   # share of usable values that must parse as numbers
SEMANTIC_NUMERIC_COLUMN_THRESHOLD = 0.3  # lower threshold when the header declares numeric meaning
_NUMERIC_NAME_RE = re.compile(r"(^|[_\s-])(unit[_\s-]?price|price|amount|cost|total|subtotal|revenue|salary|wage|age|quantity|qty|count|discount|tax|rate|score|weight|height|length|width|duration)([_\s-]|$)", re.IGNORECASE)
DATE_COLUMN_THRESHOLD = 0.6      # share that must look like dates
OUTLIER_MIN_VALUES = 8
OUTLIER_MIN_UNIQUE = 5
IQR_K = 1.5
IQR_EXTREME_K = 3.0
MODIFIED_Z_THRESHOLD = 3.5

DISCLAIMER = (
    "These are detected candidates for review, not confirmed errors. "
    "Nothing has been changed in your dataset."
)


# ── Small helpers ───────────────────────────────────────────────────────────

def _row(idx) -> int:
    return int(idx) + 1


def _shorten(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value if len(value) <= MAX_OBSERVED_LEN else value[:MAX_OBSERVED_LEN] + "…"


def _issue(
    issue_type: IssueType,
    severity: Severity,
    column: Optional[str],
    row_number: Optional[int],
    observed: Optional[str],
    explanation: str,
    action: str,
    details: Optional[dict] = None,
) -> Issue:
    return Issue(
        issue_type=issue_type,
        severity=severity,
        column=None if column is None else str(column),
        row_number=row_number,
        observed_value=_shorten(observed),
        explanation=explanation,
        suggested_action=action,
        details=details or {},
    )


def _placeholder_mask(s: pd.Series) -> pd.Series:
    """True for non-empty cells that are whitespace-only or a placeholder token."""
    flags = [
        isinstance(v, str) and (v.strip() == "" or v.strip().lower() in PLACEHOLDER_TOKENS)
        for v in s.astype("object").tolist()
    ]
    return pd.Series(flags, index=s.index, dtype=bool)


def _usable(s: pd.Series) -> pd.Series:
    """Non-empty, non-placeholder values."""
    s = s.astype("object")
    return s[s.notna() & ~_placeholder_mask(s)]


def _row_summary(row: pd.Series) -> str:
    cells = [str(v) for v in row.tolist() if pd.notna(v)][:3]
    return " | ".join(cells)


_ID_NAME = re.compile(
    r"(^|[_\s\-.])(id|uid|uuid|guid|index|idx|key|pk|serial|sno)$"
    r"|^(id|uuid|guid)([_\s\-.]|$)",
    re.IGNORECASE,
)
_CAMEL_ID = re.compile(r"[a-z]Id$")


def _is_id_like_column(name: object, s: pd.Series) -> bool:
    """Identifier columns (by name, or unique consecutive integers)."""
    label = str(name).strip()
    if _ID_NAME.search(label) or _CAMEL_ID.search(label):
        return True
    vals = _usable(s)
    if len(vals) < 3 or vals.nunique() != len(vals):
        return False
    nums = [_strict_number(v) for v in vals]
    if any(n is None or n != int(n) for n in nums):
        return False
    ordered = sorted(int(n) for n in nums)
    return all(b - a == 1 for a, b in zip(ordered, ordered[1:]))


# ── Number parsing ──────────────────────────────────────────────────────────
_NUMBER_RE = re.compile(r"^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?$")
_THOUSANDS_RE = re.compile(r"^[-+]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_CURRENCY = "$€£₹¥"
_DECIMAL_COMMA_RE = re.compile(r"^[-+]?\d+,\d{1,2}$")


def _strict_number(v: str) -> Optional[float]:
    t = v.strip()
    return float(t) if _NUMBER_RE.match(t) else None


def _loose_number(v: str) -> Optional[Tuple[float, str, str]]:
    """
    Parse unambiguous-looking formatted numbers.
    Returns (value, kind, cleaned_text) or None.
    kind ∈ {"thousands", "currency", "percent"}.
    """
    t = v.strip()
    if t.endswith("%"):
        core = t[:-1].strip()
        n = _strict_number(core)
        return (n, "percent", core) if n is not None else None
    if t and t[0] in _CURRENCY:
        core = t[1:].strip()
        if _THOUSANDS_RE.match(core):
            core = core.replace(",", "")
        n = _strict_number(core)
        return (n, "currency", core) if n is not None else None
    if _THOUSANDS_RE.match(t):
        core = t.replace(",", "")
        return float(core), "thousands", core
    return None


@dataclass
class NumericParse:
    values: Dict[object, float]            # index → numeric value (strict + loose)
    loose: Dict[object, Tuple[float, str, str]]
    bad: List[object]                      # indexes that did not parse
    ratio: float                           # parsed / usable

    @property
    def is_numeric_column(self) -> bool:
        return self.ratio >= NUMERIC_COLUMN_THRESHOLD and bool(self.values)


_LEADING_ZERO_RE = re.compile(r"^0\d")


def _parse_numeric_column(usable: pd.Series) -> NumericParse:
    values: Dict[object, float] = {}
    loose: Dict[object, Tuple[float, str, str]] = {}
    bad: List[object] = []
    for idx, v in usable.items():
        n = _strict_number(v)
        if n is not None:
            values[idx] = n
            continue
        lo = _loose_number(v)
        if lo is not None:
            values[idx] = lo[0]
            loose[idx] = lo
        else:
            bad.append(idx)
    ratio = len(values) / len(usable) if len(usable) else 0.0
    return NumericParse(values, loose, bad, ratio)


def _looks_like_code(usable: pd.Series) -> bool:
    """Zip/phone-style codes with leading zeros must not be treated as numbers."""
    if usable.empty:
        return False
    return usable.str.match(_LEADING_ZERO_RE).mean() >= 0.2


# ═══════════════════════════════════════════════════════════════════════════
# 1. Missing values
# ═══════════════════════════════════════════════════════════════════════════

def detect_missing_values(df: pd.DataFrame) -> List[Issue]:
    """Report every empty cell (one issue per cell)."""
    issues: List[Issue] = []
    n = len(df)
    for col in df.columns:
        mask = df[col].isna()
        count = int(mask.sum())
        if not count:
            continue
        pct = 100 * count / n
        severity = Severity.HIGH if pct >= 50 else Severity.MEDIUM if pct >= 10 else Severity.LOW
        for idx in df.index[mask]:
            issues.append(_issue(
                IssueType.MISSING_VALUE, severity, col, _row(idx), None,
                f"Cell is empty ({pct:.1f}% of '{col}' is missing).",
                "Review. Fill from a trusted source or leave blank; "
                "no value is invented automatically.",
                {"column_missing_percent": round(pct, 2)},
            ))
    return issues


def detect_placeholder_values(df: pd.DataFrame) -> List[Issue]:
    """Report cells holding placeholder text such as 'N/A', 'null' or just spaces."""
    issues: List[Issue] = []
    for col in df.columns:
        s = df[col].astype("object")
        mask = s.notna() & _placeholder_mask(s)
        for idx in s.index[mask]:
            raw = s[idx]
            blank = raw.strip() == ""
            issues.append(_issue(
                IssueType.PLACEHOLDER_MISSING, Severity.MEDIUM, col, _row(idx), raw,
                "Cell contains only whitespace." if blank else
                f"'{raw.strip()}' is a placeholder that usually means 'no value'.",
                "Confirm it means missing, then treat it as empty.",
                {"ambiguous": False, "meaning": "missing"},
            ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════
# 2. Duplicates
# ═══════════════════════════════════════════════════════════════════════════

def detect_exact_duplicates(df: pd.DataFrame) -> List[Issue]:
    """Rows identical to an earlier row in every column (first copy is kept)."""
    if df.shape[1] == 0 or not df.duplicated(keep="first").any():
        return []
    groups = df.groupby(list(df.columns), dropna=False, sort=False).ngroup()
    first = pd.Series(df.index, index=df.index).groupby(groups).transform("first")
    issues: List[Issue] = []
    for idx in df.index[df.duplicated(keep="first")]:
        original = _row(first[idx])
        issues.append(_issue(
            IssueType.EXACT_DUPLICATE, Severity.MEDIUM, None, _row(idx),
            _row_summary(df.loc[idx]),
            f"Row is identical to row {original} in every column.",
            "Review and remove the repeated row if it is not a legitimate repeat.",
            {"duplicate_of_row": original},
        ))
    return issues


def _normalize_text(v: str) -> str:
    v = unicodedata.normalize("NFKC", v).lower()
    v = re.sub(r"[^\w\s]", "", v)
    return re.sub(r"\s+", " ", v).strip()


def detect_potential_duplicates(df: pd.DataFrame) -> List[Issue]:
    """
    Rows that match after normalising case, punctuation and whitespace, even
    though they are not byte-identical (e.g. 'Alice Smith ' vs 'alice smith').

    Identifier-like columns are ignored so a differing ID does not hide a
    repeated record. Rows with fewer than two non-blank compared fields are
    skipped. These matches are *possible* duplicates and always need review.
    """
    cols = [c for c in df.columns if not _is_id_like_column(c, df[c])]
    if len(cols) < 2 or len(df) < 2:
        return []

    normalized = {}
    for c in cols:
        s = df[c].astype("object")
        blank = s.isna() | _placeholder_mask(s)
        normalized[c] = s.fillna("").map(_normalize_text).where(~blank, "")
    norm = pd.DataFrame(normalized)

    already_exact = df.duplicated(keep="first")
    eligible = ((norm != "").sum(axis=1) >= 2) & ~already_exact
    if eligible.sum() < 2:
        return []

    sig = norm[cols[0]].str.cat([norm[c] for c in cols[1:]], sep="\x1f")[eligible]
    first = pd.Series(sig.index, index=sig.index).groupby(sig.values).transform("first")

    issues: List[Issue] = []
    for idx in sig.index[sig.index != first]:
        match = _row(first[idx])
        issues.append(_issue(
            IssueType.POTENTIAL_DUPLICATE, Severity.MEDIUM, None, _row(idx),
            _row_summary(df.loc[idx]),
            f"Row closely matches row {match} once case, punctuation and spacing "
            "are ignored. It may be the same record entered differently.",
            "Compare both rows manually before merging or removing either.",
            {"matches_row": match, "ambiguous": True, "columns_compared": len(cols)},
        ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════
# 3. Text format and whitespace
# ═══════════════════════════════════════════════════════════════════════════

def detect_text_inconsistencies(df: pd.DataFrame) -> List[Issue]:
    """
    Whitespace problems, plus the same value written in different cases
    ('Mumbai' / 'mumbai') within a column. The capitalisation check is skipped
    for numeric columns; the whitespace check applies everywhere.
    """
    issues: List[Issue] = []
    for col in df.columns:
        usable = _usable(df[col])
        if usable.empty:
            continue

        collapsed = usable.map(lambda v: " ".join(v.split()))

        # (a) deterministic whitespace fixes
        for idx in usable.index[usable != collapsed]:
            raw = usable[idx]
            kind = "leading/trailing spaces" if raw != raw.strip() else "repeated spaces"
            issues.append(_issue(
                IssueType.WHITESPACE, Severity.LOW, col, _row(idx), raw,
                f"Value has {kind}.",
                "Trim and collapse whitespace.",
                {"proposed_value": collapsed[idx], "ambiguous": False},
            ))

        # (b) same text, different capitalisation (meaningless for numbers)
        if _parse_numeric_column(usable).is_numeric_column:
            continue
        for _, grp in collapsed.groupby(collapsed.str.lower()):
            forms = grp.value_counts()
            if len(forms) < 2:
                continue
            tie = bool(forms.iloc[0] == forms.iloc[1])
            canonical = None if tie else forms.index[0]
            for idx, v in grp.items():
                if canonical is not None and v == canonical:
                    continue
                issues.append(_issue(
                    IssueType.INCONSISTENT_TEXT_FORMAT, Severity.LOW, col, _row(idx), v,
                    "Same text appears with different capitalisation in this column"
                    + (" (no form is clearly dominant)." if tie
                       else f"; most common form is '{canonical}'."),
                    "Pick one consistent form." if tie
                    else f"Consider standardising to '{canonical}'.",
                    {"canonical_candidate": canonical, "ambiguous": tie,
                     "variants": [str(f) for f in forms.index[:5]]},
                ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════
# 4. Dates
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DateFamily:
    name: str
    regex: "re.Pattern[str]"
    formats: Tuple[str, ...]
    ambiguous: bool = False       # day/month order unknown from shape alone
    strip_commas: bool = False


DATE_FAMILIES: Tuple[DateFamily, ...] = (
    DateFamily("YYYY-MM-DD", re.compile(r"^\d{4}-\d{1,2}-\d{1,2}$"), ("%Y-%m-%d",)),
    DateFamily("YYYY/MM/DD", re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$"), ("%Y/%m/%d",)),
    DateFamily("DD/MM/YYYY or MM/DD/YYYY", re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$"),
               ("%d/%m/%Y", "%m/%d/%Y"), ambiguous=True),
    DateFamily("DD-MM-YYYY or MM-DD-YYYY", re.compile(r"^\d{1,2}-\d{1,2}-\d{4}$"),
               ("%d-%m-%Y", "%m-%d-%Y"), ambiguous=True),
    DateFamily("DD.MM.YYYY", re.compile(r"^\d{1,2}\.\d{1,2}\.\d{4}$"), ("%d.%m.%Y",)),
    DateFamily("D Mon YYYY", re.compile(r"^\d{1,2} [A-Za-z]{3,9},? \d{4}$"),
               ("%d %b %Y", "%d %B %Y"), strip_commas=True),
    DateFamily("Mon D, YYYY", re.compile(r"^[A-Za-z]{3,9} \d{1,2}, \d{4}$"),
               ("%b %d %Y", "%B %d %Y"), strip_commas=True),
    DateFamily("ISO date-time", re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?$"),
               ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M")),
)


def _classify_date(value: str) -> Optional[int]:
    """Index of the date family the text is *shaped* like, else None."""
    t = value.strip()
    for i, fam in enumerate(DATE_FAMILIES):
        if fam.regex.match(t):
            return i
    return None


def _valid_date(value: str, fam: DateFamily, order: Optional[str]) -> bool:
    t = value.strip()
    if fam.strip_commas:
        t = t.replace(",", "")
    formats = fam.formats
    if fam.ambiguous and order == "dmy":
        formats = formats[:1]
    elif fam.ambiguous and order == "mdy":
        formats = formats[1:]
    for f in formats:
        try:
            datetime.strptime(t, f)
            return True
        except ValueError:
            continue
    return False


def _date_order(values: List[str]) -> Optional[str]:
    """dmy / mdy / 'mixed' from values > 12, or None when undeterminable."""
    first_big = second_big = False
    for v in values:
        a, b, *_ = re.split(r"[/\-]", v.strip())
        first_big |= int(a) > 12
        second_big |= int(b) > 12
    if first_big and second_big:
        return "mixed"
    return "dmy" if first_big else "mdy" if second_big else None


def iso_date_candidates(value: str) -> Optional[List[str]]:
    """
    Every valid YYYY-MM-DD reading of a date string.

    []   → not a valid date.      None → has a time component (not converted).
    One item → unambiguous; two different items → day/month order is ambiguous.
    """
    fi = _classify_date(value)
    if fi is None:
        return []
    fam = DATE_FAMILIES[fi]
    if fam.name == "ISO date-time":
        return None
    t = value.strip().replace(",", "") if fam.strip_commas else value.strip()
    found: List[str] = []
    for f in fam.formats:
        try:
            iso = datetime.strptime(t, f).strftime("%Y-%m-%d")
        except ValueError:
            continue
        if iso not in found:
            found.append(iso)
    return found


def detect_date_issues(df: pd.DataFrame) -> List[Issue]:
    """
    For columns where most values look like dates: report impossible or
    unrecognisable dates, mixed formats, and ambiguous day/month order.
    Ambiguous dates (e.g. 03/04/2024) are flagged, never reinterpreted.
    """
    issues: List[Issue] = []
    for col in df.columns:
        usable = _usable(df[col])
        if usable.empty:
            continue
        family = {idx: _classify_date(v) for idx, v in usable.items()}
        shaped = [i for i in family.values() if i is not None]
        if len(shaped) / len(usable) < DATE_COLUMN_THRESHOLD:
            continue

        # day/month order per ambiguous family, from the column's own evidence
        orders: Dict[int, Optional[str]] = {}
        for fi in set(shaped):
            if DATE_FAMILIES[fi].ambiguous:
                vals = [usable[i] for i, f in family.items() if f == fi]
                orders[fi] = _date_order(vals)

        valid_family: Dict[object, int] = {}
        for idx, v in usable.items():
            fi = family[idx]
            if fi is None:
                issues.append(_issue(
                    IssueType.INVALID_DATE, Severity.HIGH, col, _row(idx), v,
                    "Value is not recognisable as a date in a column of dates.",
                    "Correct the value or mark it missing.", {"ambiguous": False}))
            elif not _valid_date(v, DATE_FAMILIES[fi], orders.get(fi)):
                issues.append(_issue(
                    IssueType.INVALID_DATE, Severity.HIGH, col, _row(idx), v,
                    "Looks like a date but is not a real calendar date "
                    "(e.g. 30 February or month 13).",
                    "Check the source record; the correct date cannot be inferred.",
                    {"ambiguous": False}))
            else:
                valid_family[idx] = fi

        # mixed formats: flag values outside the dominant format
        counts = pd.Series(list(valid_family.values())).value_counts()
        if len(counts) > 1:
            tie = bool(counts.iloc[0] == counts.iloc[1])
            dominant = None if tie else int(counts.index[0])
            for idx, fi in valid_family.items():
                if dominant is not None and fi == dominant:
                    continue
                issues.append(_issue(
                    IssueType.INCONSISTENT_DATE_FORMAT, Severity.MEDIUM, col, _row(idx),
                    usable[idx],
                    f"Date written as {DATE_FAMILIES[fi].name}; "
                    + ("no single format dominates this column."
                       if tie else f"most values use {DATE_FAMILIES[dominant].name}."),
                    "Standardise to one date format.",
                    {"value_format": DATE_FAMILIES[fi].name,
                     "dominant_format": None if tie else DATE_FAMILIES[dominant].name,
                     "ambiguous": True}))

        # column-level notes on day/month order
        for fi, order in orders.items():
            example = next(usable[i] for i, f in family.items() if f == fi)
            if order is None:
                issues.append(_issue(
                    IssueType.AMBIGUOUS_DATE_FORMAT, Severity.LOW, col, None, example,
                    f"{DATE_FAMILIES[fi].name} dates cannot be read unambiguously: every "
                    "day and month is 12 or below, so day-first and month-first both fit.",
                    "Confirm the intended order before converting dates.",
                    {"ambiguous": True}))
            elif order == "mixed":
                issues.append(_issue(
                    IssueType.INCONSISTENT_DATE_FORMAT, Severity.MEDIUM, col, None, example,
                    "Some dates here can only be day-first and others only month-first.",
                    "Check which convention each source row used.",
                    {"ambiguous": True}))
    return issues


# ═══════════════════════════════════════════════════════════════════════════
# 5. Numeric validity
# ═══════════════════════════════════════════════════════════════════════════

def _numeric_candidates(df: pd.DataFrame):
    """Yield numeric-looking columns, including columns whose names declare numeric meaning.

    Semantic headers such as Unit_Price are checked even when several cells are
    invalid; otherwise the very values we need to flag can push the parse ratio
    below the generic threshold and cause the whole column to be ignored.
    """
    for col in df.columns:
        usable = _usable(df[col])
        if usable.empty or _looks_like_code(usable):
            continue
        parse = _parse_numeric_column(usable)
        semantic_numeric = bool(_NUMERIC_NAME_RE.search(str(col)))
        threshold = SEMANTIC_NUMERIC_COLUMN_THRESHOLD if semantic_numeric else NUMERIC_COLUMN_THRESHOLD
        if parse.values and parse.ratio >= threshold:
            yield col, usable, parse


def detect_invalid_numerics(df: pd.DataFrame) -> List[Issue]:
    """
    In columns that are mostly numeric: report text that is not a number, and
    formatted numbers ('1,200', '$5', '12%') that need normalising.
    """
    issues: List[Issue] = []
    for col, usable, parse in _numeric_candidates(df):
        severity = Severity.HIGH if parse.ratio >= 0.95 else Severity.MEDIUM
        for idx in parse.bad:
            v = usable[idx]
            hint = (" It may use a decimal comma, which cannot be assumed."
                    if _DECIMAL_COMMA_RE.match(v.strip()) else "")
            issues.append(_issue(
                IssueType.INVALID_NUMERIC, severity, col, _row(idx), v,
                f"'{v.strip()}' is not a valid number, but {parse.ratio:.0%} of "
                f"'{col}' is numeric.{hint}",
                "Correct the value or mark it missing; the intended number "
                "cannot be inferred.",
                {"ambiguous": False, "column_numeric_ratio": round(parse.ratio, 4)},
            ))
        for idx, (_, kind, cleaned) in parse.loose.items():
            ambiguous = kind == "percent"
            issues.append(_issue(
                IssueType.NUMERIC_FORMAT, Severity.LOW, col, _row(idx), usable[idx],
                f"Number is written with {kind} formatting, unlike the rest of the column.",
                "Review the unit (12% could mean 12 or 0.12)." if ambiguous
                else "Remove the formatting characters.",
                {"proposed_value": None if ambiguous else cleaned,
                 "candidate_value": cleaned, "format_kind": kind, "ambiguous": ambiguous},
            ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════
# 6. Semantic numeric range validation
# ═══════════════════════════════════════════════════════════════════════════


def detect_numeric_range_issues(df: pd.DataFrame) -> List[Issue]:
    """Flag clearly invalid values for common non-negative business measures.

    These are review findings, not automatic repairs. Domain-specific limits
    should be configured for a dataset rather than guessed from its values.
    """
    issues: List[Issue] = []
    for col, usable, parse in _numeric_candidates(df):
        label = re.sub(r"[^a-z0-9]+", "_", str(col).strip().lower()).strip("_")
        if re.search(r"(^|_)(unit_price|price|amount|cost|total|subtotal|revenue|salary|wage|quantity|qty|count|discount|tax|weight|height|length|width)(_|$)", label):
            lower_bound = 0.0
            rule = "non_negative"
        elif re.search(r"(^|_)age(_|$)", label):
            lower_bound = 0.0
            rule = "age_0_to_130"
        else:
            continue

        for idx, value in parse.values.items():
            invalid = value < lower_bound
            if rule == "age_0_to_130":
                invalid = invalid or value > 130
            if not invalid:
                continue
            limit_text = "0–130" if rule == "age_0_to_130" else "0 or greater"
            issues.append(_issue(
                IssueType.RULE_VIOLATION, Severity.HIGH, col, _row(idx), usable[idx],
                f"Value {value:g} is outside the expected range for '{col}' ({limit_text}).",
                "Verify against the source data and correct only after review.",
                {"rule": rule, "minimum": 0, "maximum": 130 if rule == "age_0_to_130" else None,
                 "ambiguous": True},
            ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════
# 7. Outliers
# ═══════════════════════════════════════════════════════════════════════════

def detect_outliers(df: pd.DataFrame) -> List[Issue]:
    """
    Flag values that are statistically unusual within a numeric column.

    Method: a value is flagged only if BOTH hold —
      1. it lies outside Tukey's fences, Q1 − 1.5·IQR … Q3 + 1.5·IQR, and
      2. its modified z-score, 0.6745·(x − median)/MAD, exceeds 3.5.
    Both measures use quartiles/median, so the outliers themselves do not
    distort the thresholds (unlike a mean/std z-score). Requiring agreement
    reduces false alarms. Severity is 'medium' only beyond 3·IQR.

    Limitations (important):
      • An outlier is *unusual*, not *wrong*; salaries, sales and ages have
        real extreme values. Every flag needs human review.
      • Skewed or multi-modal distributions produce many legitimate flags.
      • Columns with < 8 values, < 5 distinct values, IQR = 0 or MAD = 0 are
        skipped, because the statistics are meaningless there.
      • Identifier-like columns are skipped. Each column is judged alone; no
        multivariate relationships are considered.
    """
    issues: List[Issue] = []
    for col, usable, parse in _numeric_candidates(df):
        if _is_id_like_column(col, df[col]):
            continue
        x = pd.Series(parse.values, dtype=float)
        if len(x) < OUTLIER_MIN_VALUES or x.nunique() < OUTLIER_MIN_UNIQUE:
            continue
        q1, q3 = x.quantile(0.25), x.quantile(0.75)
        iqr = q3 - q1
        median = x.median()
        mad = float(np.median(np.abs(x - median)))
        if iqr == 0 or mad == 0:
            continue
        low, high = q1 - IQR_K * iqr, q3 + IQR_K * iqr
        mod_z = 0.6745 * (x - median) / mad
        flagged = ((x < low) | (x > high)) & (mod_z.abs() > MODIFIED_Z_THRESHOLD)
        for idx in x.index[flagged]:
            extreme = x[idx] < q1 - IQR_EXTREME_K * iqr or x[idx] > q3 + IQR_EXTREME_K * iqr
            issues.append(_issue(
                IssueType.SUSPICIOUS_OUTLIER,
                Severity.MEDIUM if extreme else Severity.LOW,
                col, _row(idx), usable[idx],
                f"Value is statistically unusual for '{col}' (outside the "
                f"{low:.4g} to {high:.4g} range; robust z-score {mod_z[idx]:.1f}). "
                "It may be legitimate; this is not evidence of an error.",
                "Review against the source; keep it if it is genuine.",
                {"method": "IQR + modified z-score", "lower_fence": round(float(low), 4),
                 "upper_fence": round(float(high), 4),
                 "modified_z": round(float(mod_z[idx]), 2),
                 "median": round(float(median), 4), "ambiguous": True},
            ))
    return issues


# ═══════════════════════════════════════════════════════════════════════════
# Orchestration
# ═══════════════════════════════════════════════════════════════════════════

DETECTORS: Tuple[Callable[[pd.DataFrame], List[Issue]], ...] = (
    detect_missing_values,
    detect_placeholder_values,
    detect_exact_duplicates,
    detect_potential_duplicates,
    detect_text_inconsistencies,
    detect_date_issues,
    detect_invalid_numerics,
    detect_numeric_range_issues,
    detect_outliers,
)


def summarize(issues: List[Issue]) -> DetectionSummary:
    by_type: Dict[str, int] = {}
    by_sev: Dict[str, int] = {}
    by_col: Dict[str, int] = {}
    rows = set()
    for i in issues:
        by_type[i.issue_type.value] = by_type.get(i.issue_type.value, 0) + 1
        by_sev[i.severity.value] = by_sev.get(i.severity.value, 0) + 1
        if i.column is not None:
            by_col[i.column] = by_col.get(i.column, 0) + 1
        if i.row_number is not None:
            rows.add(i.row_number)
    return DetectionSummary(
        total_issues=len(issues), affected_row_count=len(rows),
        by_type=by_type, by_severity=by_sev, by_column=by_col,
    )


def run_detection(df: pd.DataFrame) -> List[Issue]:
    """Run every detector and assign scan-unique issue ids (I00001, …)."""
    issues: List[Issue] = []
    for detector in DETECTORS:
        issues.extend(detector(df))
    return [i.model_copy(update={"issue_id": f"I{n:05d}"}) for n, i in enumerate(issues, 1)]
