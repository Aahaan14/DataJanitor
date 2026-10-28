"""
DataJanitor — repair recommendation engine (Phase 4).

Turns detected issues (and rule violations) into reviewable repair
proposals. It never changes data; it only describes what *could* change.

Principles
──────────
• SAFE = deterministic and meaning-preserving (trim spaces, remove thousands
  separators, rewrite an unambiguous date in ISO form). Even safe proposals
  stay `pending` until the user approves them.
• AMBIGUOUS = needs judgement: destructive (row deletion), several valid
  readings (03/04/2024, 12%), or a style choice (which capitalisation).
• Intelligent imputation: when sufficient statistical evidence exists, propose
  a computed value (median, mode, etc.) instead of just emptying the cell.
  The method, confidence, and reasoning are always shown.
• Identifiers, names, and dates without evidence are never imputed.
• Some issue types get NO proposal (outliers, column-level notes).
  They are counted and explained in `issues_without_proposal`.
"""

import uuid
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

import pandas as pd

from app.schemas.issues import Issue, IssueType
from app.schemas.repairs import (
    Classification, Confidence, NoProposalGroup, RepairAction, RepairProposal,
)
from app.schemas.validation import RuleViolation
from app.services import detection_service as ds
from app.services import imputation_service as imp

NO_PROPOSAL_REASONS: Dict[str, str] = {
    IssueType.SUSPICIOUS_OUTLIER.value: "An outlier is unusual, not proven wrong; review it manually.",
    IssueType.AMBIGUOUS_DATE_FORMAT.value: "The column's date convention needs a human decision.",
}


def _cell(df: pd.DataFrame, row_number: Optional[int], column: Optional[str]) -> Optional[str]:
    """Exact current text of a cell (None if empty). row_number is 1-based."""
    value = df.at[row_number - 1, column]
    return None if pd.isna(value) else str(value)


def _new_id() -> str:
    return "R" + uuid.uuid4().hex[:12]


def _make(issue: Issue, action: RepairAction, classification: Classification,
          confidence: Confidence, reason: str, *, original: Optional[str] = None,
          proposed: Optional[str] = None, alternatives: Optional[List[str]] = None,
          allow_custom: bool = False) -> RepairProposal:
    return RepairProposal(
        proposal_id=_new_id(), issue_id=issue.issue_id, issue_type=issue.issue_type,
        action=action, classification=classification, confidence=confidence,
        column=issue.column, row_number=issue.row_number, original_value=original,
        proposed_value=proposed, alternatives=alternatives or [],
        allow_custom_value=allow_custom, reason=reason,
    )


def _confidence_from_str(c: str) -> Confidence:
    return Confidence.HIGH if c == "high" else Confidence.MEDIUM if c == "medium" else Confidence.LOW


def _percent_alternatives(cleaned: str) -> List[str]:
    try:
        as_fraction = format((Decimal(cleaned) / 100).normalize(), "f")
    except InvalidOperation:
        return [cleaned]
    return [cleaned, as_fraction] if as_fraction != cleaned else [cleaned]


def _from_issue(df: pd.DataFrame, issue: Issue) -> Tuple[Optional[RepairProposal], Optional[str]]:
    """Return (proposal, None) or (None, reason_no_proposal)."""
    t, d = issue.issue_type, issue.details
    if issue.row_number is None:
        return None, "Column-level finding; needs a human decision."
    orig = _cell(df, issue.row_number, issue.column) if issue.column else None

    if t == IssueType.WHITESPACE:
        return _make(issue, RepairAction.REPLACE_VALUE, Classification.SAFE, Confidence.HIGH,
                     "Extra spaces carry no meaning; trimming them does not change the text.",
                     original=orig, proposed=d["proposed_value"]), None

    if t == IssueType.NUMERIC_FORMAT:
        if d.get("ambiguous"):
            return _make(issue, RepairAction.REPLACE_VALUE, Classification.AMBIGUOUS,
                         Confidence.LOW,
                         "A percentage could mean the number as written or a fraction "
                         "(12% → 12 or 0.12). Choose the reading that matches this column.",
                         original=orig, alternatives=_percent_alternatives(d["candidate_value"])), None
        return _make(issue, RepairAction.REPLACE_VALUE, Classification.SAFE, Confidence.HIGH,
                     f"Removing the {d['format_kind']} formatting leaves the same number "
                     "and matches the rest of the column.",
                     original=orig, proposed=d["proposed_value"]), None

    if t == IssueType.INVALID_NUMERIC:
        # Try intelligent suggestion for invalid numerics
        suggestion = imp.suggest_for_invalid_numeric(df, issue.column, issue.row_number, orig or "")
        if suggestion is not None:
            conf = _confidence_from_str(suggestion.confidence)
            reason = (
                f"{suggestion.method}: {suggestion.explanation}"
            )
            if suggestion.context_stat:
                reason += f" [{suggestion.context_stat}]"
            return _make(issue, RepairAction.REPLACE_VALUE, Classification.AMBIGUOUS, conf,
                         reason, original=orig, proposed=suggestion.value,
                         allow_custom=True), None
        # Fallback: clear with option to type a correction
        return _make(issue, RepairAction.CLEAR_VALUE, Classification.AMBIGUOUS, Confidence.LOW,
                     "The intended number cannot be determined from the data. You can empty "
                     "the cell, or approve with a corrected number you enter yourself.",
                     original=orig, allow_custom=True), None

    if t == IssueType.INVALID_DATE:
        # Dates are not imputed without strong evidence
        return _make(issue, RepairAction.CLEAR_VALUE, Classification.AMBIGUOUS, Confidence.LOW,
                     "The intended date cannot be determined from the data. You can empty "
                     "the cell, or approve with a corrected date you enter yourself.",
                     original=orig, allow_custom=True), None

    if t == IssueType.INCONSISTENT_DATE_FORMAT:
        if d.get("dominant_format") != "YYYY-MM-DD":
            return None, "No single ISO target format to convert to; needs a human decision."
        candidates = ds.iso_date_candidates(orig or "")
        if candidates is None:
            return None, "Value has a time component; converting would lose information."
        if not candidates:
            return None, "Value is not a valid date (see the invalid_date issue)."
        if len(candidates) == 1:
            return _make(issue, RepairAction.REPLACE_VALUE, Classification.SAFE, Confidence.HIGH,
                         "Only one calendar reading is possible, so rewriting it as "
                         "YYYY-MM-DD (the column's main format) is exact.",
                         original=orig, proposed=candidates[0]), None
        return _make(issue, RepairAction.REPLACE_VALUE, Classification.AMBIGUOUS, Confidence.LOW,
                     "Day-first and month-first both give valid dates. Choose the correct one.",
                     original=orig, alternatives=candidates), None

    if t == IssueType.INCONSISTENT_TEXT_FORMAT:
        if d.get("ambiguous"):
            return _make(issue, RepairAction.REPLACE_VALUE, Classification.AMBIGUOUS,
                         Confidence.LOW,
                         "Several capitalisations are equally common; pick the form to use.",
                         original=orig, alternatives=d.get("variants", [])), None
        return _make(issue, RepairAction.REPLACE_VALUE, Classification.AMBIGUOUS,
                     Confidence.MEDIUM,
                     f"'{d['canonical_candidate']}' is the most common form in this column. "
                     "Choosing it is a style decision, so it needs your approval.",
                     original=orig, proposed=d["canonical_candidate"],
                     alternatives=d.get("variants", [])), None

    if t == IssueType.PLACEHOLDER_MISSING:
        # Try intelligent imputation for placeholders
        suggestion = imp.suggest_for_placeholder(df, issue.column, issue.row_number, orig or "")
        if suggestion is not None:
            conf = _confidence_from_str(suggestion.confidence)
            reason = f"{suggestion.method}: {suggestion.explanation}"
            if suggestion.context_stat:
                reason += f" [{suggestion.context_stat}]"
            return _make(issue, RepairAction.REPLACE_VALUE, Classification.AMBIGUOUS, conf,
                         reason, original=orig, proposed=suggestion.value,
                         allow_custom=True), None
        # Fallback: clear the cell
        return _make(issue, RepairAction.CLEAR_VALUE, Classification.AMBIGUOUS, Confidence.MEDIUM,
                     "This text usually means 'no value', but could be a genuine entry "
                     "(e.g. a category called 'None'). Emptying it makes it a true missing value.",
                     original=orig, allow_custom=True), None

    if t == IssueType.MISSING_VALUE:
        # Try intelligent imputation for missing values
        suggestion = imp.suggest_for_missing(df, issue.column, issue.row_number)
        if suggestion is not None:
            conf = _confidence_from_str(suggestion.confidence)
            reason = f"{suggestion.method}: {suggestion.explanation}"
            if suggestion.context_stat:
                reason += f" [{suggestion.context_stat}]"
            return _make(issue, RepairAction.REPLACE_VALUE, Classification.AMBIGUOUS, conf,
                         reason, original=orig, proposed=suggestion.value,
                         allow_custom=True), None
        # No suggestion possible — still create a proposal to clear (no-op for empty)
        return None, "No reliable imputation available; fill manually from a trusted source."

    if t == IssueType.EXACT_DUPLICATE:
        return _make(issue, RepairAction.DELETE_ROW, Classification.AMBIGUOUS, Confidence.HIGH,
                     f"Identical to row {d['duplicate_of_row']}. Removing the repeat is usually "
                     "right, but repeated rows can be legitimate (e.g. two identical sales).",
                     original=issue.observed_value), None

    if t == IssueType.POTENTIAL_DUPLICATE:
        return _make(issue, RepairAction.DELETE_ROW, Classification.AMBIGUOUS, Confidence.LOW,
                     f"Closely resembles row {d['matches_row']} but is not identical. Compare "
                     "both rows before removing either.",
                     original=issue.observed_value), None

    return None, NO_PROPOSAL_REASONS.get(t.value, "No automatic repair is offered.")


def _from_violation(df: pd.DataFrame, v: RuleViolation, issue_id: str,
                    covered_cells: set) -> Tuple[Optional[RepairProposal], Optional[str]]:
    if v.row_number is None or v.column is None:
        return None, "Column-level rule violation; needs a human decision."
    if v.rule.startswith("value must be unique"):
        return None, "Which duplicate to change cannot be determined."
    orig = _cell(df, v.row_number, v.column)
    if orig is None:
        return None, "Required value is missing; values are never invented."
    if (v.row_number, v.column) in covered_cells:
        return None, "Cell already has a repair proposal from a detected issue."
    source = Issue(issue_id=issue_id, issue_type=IssueType.RULE_VIOLATION,
                   severity="medium", column=v.column, row_number=v.row_number,
                   observed_value=v.observed_value, explanation=v.rule, suggested_action="")
    prop = _make(source, RepairAction.CLEAR_VALUE, Classification.AMBIGUOUS, Confidence.LOW,
                 f"Breaks the rule for '{v.column}': {v.rule}. The correct value cannot be "
                 "determined; empty the cell or enter a corrected value.",
                 original=orig, allow_custom=True)
    return prop, None


def _mark_conflicts(proposals: List[RepairProposal]) -> None:
    """Two proposals conflict if they edit the same cell, or one deletes the row the other edits."""
    by_cell: Dict[Tuple[int, str], List[RepairProposal]] = {}
    by_row: Dict[int, List[RepairProposal]] = {}
    for p in proposals:
        if p.row_number is None:
            continue
        by_row.setdefault(p.row_number, []).append(p)
        if p.action != RepairAction.DELETE_ROW:
            by_cell.setdefault((p.row_number, p.column), []).append(p)
    conflicts: Dict[str, set] = {p.proposal_id: set() for p in proposals}
    for group in by_cell.values():
        for p in group:
            conflicts[p.proposal_id].update(q.proposal_id for q in group if q is not p)
    for group in by_row.values():
        deletes = [p for p in group if p.action == RepairAction.DELETE_ROW]
        edits = [p for p in group if p.action != RepairAction.DELETE_ROW]
        for dl in deletes:
            for ed in edits:
                conflicts[dl.proposal_id].add(ed.proposal_id)
                conflicts[ed.proposal_id].add(dl.proposal_id)
    for p in proposals:
        p.conflicts_with = sorted(conflicts[p.proposal_id])


def build_proposals(
    df: pd.DataFrame, issues: List[Issue], violations: List[RuleViolation], max_proposals: int
) -> Tuple[List[RepairProposal], List[NoProposalGroup], bool]:
    """
    Returns (proposals, findings_without_proposal, truncated).
    Rule violations are given ids V00001… in the `issue_id` field.
    """
    proposals: List[RepairProposal] = []
    skipped: Dict[Tuple[str, str], int] = {}

    def skip(label: str, reason: str) -> None:
        skipped[(label, reason)] = skipped.get((label, reason), 0) + 1

    for issue in issues:
        prop, reason = _from_issue(df, issue)
        if prop is None:
            skip(issue.issue_type.value, reason)
        else:
            proposals.append(prop)

    covered = {(p.row_number, p.column) for p in proposals if p.column is not None}
    for n, v in enumerate(violations, 1):
        prop, reason = _from_violation(df, v, f"V{n:05d}", covered)
        if prop is None:
            skip(IssueType.RULE_VIOLATION.value, reason)
        else:
            proposals.append(prop)

    truncated = len(proposals) > max_proposals
    proposals = proposals[:max_proposals]
    _mark_conflicts(proposals)
    groups = [NoProposalGroup(issue_type=k[0], reason=k[1], count=n)
              for k, n in sorted(skipped.items())]
    return proposals, groups, truncated
