"""
DataJanitor — applying approved repairs (pure data logic, no database).

Guarantees
──────────
• The input DataFrame is never modified; edits go to a copy.
• Only proposals handed in (the explicitly approved ones) can change data.
• Every change is double-checked: the cell must still hold the exact value
  that was reviewed, and no two repairs may touch the same cell or edit a
  row that another repair deletes. Anything else is *skipped* with a reason.
• After applying, `find_unintended_changes` re-derives the expected result
  independently and reports any cell that differs from it.

CSV output is UTF-8 with BOM (so Excel shows accents correctly), CRLF line
endings, the delimiter and header text of the original. Values are kept
exactly; only CSV formatting (quoting, line endings, blank lines) may be
normalised.
"""

import csv
import io
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

import pandas as pd

from app.schemas.repairs import RepairAction
from app.services import detection_service as ds

Cell = Tuple[int, str]  # (0-based DataFrame index, column name)

_FORMULA_STARTS = ("=", "+", "-", "@", "\t", "\r")


@dataclass
class Outcome:
    proposal_id: str
    outcome: str                 # "applied" | "skipped"
    reason: Optional[str] = None


@dataclass
class ApplyResult:
    cleaned: pd.DataFrame
    outcomes: List[Outcome]
    edits: Dict[Cell, Optional[str]] = field(default_factory=dict)
    deleted: Set[int] = field(default_factory=set)


def _current(df: pd.DataFrame, idx: int, col: str) -> Optional[str]:
    value = df.at[idx, col]
    return None if pd.isna(value) else str(value)


def apply_repairs(original: pd.DataFrame, approved: Sequence) -> ApplyResult:
    """
    Apply approved proposals (ORM rows or look-alikes with id, action,
    row_number, column_name, original_value, approved_value) to a COPY.
    """
    n_rows = len(original)
    result: Dict[str, Outcome] = {}
    edits: Dict[Cell, Optional[str]] = {}
    edit_owner: Dict[Cell, str] = {}
    deleted: Dict[int, str] = {}

    def skip(p, reason: str) -> None:
        result[p.id] = Outcome(p.id, "skipped", reason)

    # Pass 1 — row deletions
    for p in approved:
        if p.action != RepairAction.DELETE_ROW.value:
            continue
        idx = (p.row_number or 0) - 1
        if not 0 <= idx < n_rows:
            skip(p, "row not found")
        elif ds._row_summary(original.loc[idx]) != p.original_value:
            skip(p, "row no longer matches the row that was reviewed")
        elif idx in deleted:
            skip(p, f"row already deleted by repair {deleted[idx]}")
        else:
            deleted[idx] = p.id
            result[p.id] = Outcome(p.id, "applied")

    # Pass 2 — cell edits
    for p in approved:
        if p.action == RepairAction.DELETE_ROW.value:
            continue
        idx = (p.row_number or 0) - 1
        col = p.column_name
        if col not in original.columns:
            skip(p, "column not found")
        elif not 0 <= idx < n_rows:
            skip(p, "row not found")
        elif idx in deleted:
            skip(p, f"row is deleted by repair {deleted[idx]}")
        elif _current(original, idx, col) != p.original_value:
            skip(p, "cell no longer matches the value that was reviewed")
        elif (idx, col) in edits:
            skip(p, f"cell already changed by repair {edit_owner[(idx, col)]}")
        elif p.action == RepairAction.REPLACE_VALUE.value and p.approved_value is None:
            skip(p, "no approved value recorded")
        else:
            edits[(idx, col)] = p.approved_value  # None empties the cell
            edit_owner[(idx, col)] = p.id
            result[p.id] = Outcome(p.id, "applied")

    cleaned = original.copy(deep=True)
    for (idx, col), value in edits.items():
        cleaned.at[idx, col] = value
    cleaned = cleaned.drop(index=list(deleted))
    return ApplyResult(cleaned, [result[p.id] for p in approved], edits, set(deleted))


def find_unintended_changes(original: pd.DataFrame, cleaned: pd.DataFrame,
                            edits: Dict[Cell, Optional[str]], deleted: Set[int]) -> List[str]:
    """
    Independently verify the output. Returns problem descriptions (counts
    only, no cell values); an empty list means the output is exactly
    "original, minus deleted rows, plus the approved edits".
    """
    problems: List[str] = []
    if list(cleaned.columns) != list(original.columns):
        return ["columns differ from the original"]
    expected_index = [i for i in original.index if i not in deleted]
    if list(cleaned.index) != expected_index:
        return ["the set or order of rows differs from the expected result"]

    before = original.loc[expected_index]
    differs = ~((before == cleaned) | (before.isna() & cleaned.isna()))
    changed: Set[Cell] = {(idx, col) for col in differs.columns
                          for idx in differs.index[differs[col]]}

    unexpected = changed - set(edits)
    if unexpected:
        problems.append(f"{len(unexpected)} cell(s) changed without an approved repair")
    for (idx, col), value in edits.items():
        got = cleaned.at[idx, col]
        got = None if pd.isna(got) else got
        if got != value:
            problems.append("an approved edit is missing or has the wrong value")
            break
    return problems


# ── CSV output ──────────────────────────────────────────────────────────────

def render_csv(df: pd.DataFrame, header: List[str], delimiter: str) -> bytes:
    """Faithful CSV bytes (UTF-8 with BOM, CRLF). Empty cells are written as empty fields."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(header)
    for row in df.itertuples(index=False, name=None):
        writer.writerow([None if pd.isna(v) else v for v in row])
    return buffer.getvalue().encode("utf-8-sig")


def escape_formula(value: str) -> Tuple[str, bool]:
    """
    Neutralise spreadsheet formula injection: a text cell that starts with
    = + - @ (or tab/CR) is prefixed with an apostrophe so Excel/Sheets show
    it as text instead of executing it. Plain numbers such as -5 are left
    alone. Returns (value, was_escaped).
    """
    core = value.lstrip(" ")
    if core and core[0] in _FORMULA_STARTS and ds._strict_number(core) is None:
        return "'" + value, True
    return value, False


def sanitize_for_spreadsheet(csv_bytes: bytes, delimiter: str) -> Tuple[bytes, int]:
    """Escape every field (header included) of a CSV; returns (bytes, cells_escaped)."""
    text = csv_bytes.decode("utf-8-sig")
    out = io.StringIO(newline="")
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\r\n")
    escaped = 0
    for record in csv.reader(io.StringIO(text, newline=""), delimiter=delimiter):
        row = []
        for field_value in record:
            safe, was = escape_formula(field_value)
            escaped += was
            row.append(safe)
        writer.writerow(row)
    return out.getvalue().encode("utf-8-sig"), escaped
