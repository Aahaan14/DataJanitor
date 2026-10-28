import type { Severity } from "../types/api";

export const humanize = (s: string): string =>
  s.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());

const ISSUE_LABELS: Record<string, string> = {
  missing_value: "Missing value",
  placeholder_missing: "Placeholder (e.g. N/A)",
  exact_duplicate: "Exact duplicate row",
  potential_duplicate: "Possible duplicate row",
  whitespace: "Extra whitespace",
  inconsistent_text_format: "Inconsistent text",
  invalid_date: "Invalid date",
  inconsistent_date_format: "Mixed date format",
  ambiguous_date_format: "Ambiguous date order",
  invalid_numeric: "Invalid number",
  numeric_format: "Number formatting",
  suspicious_outlier: "Suspicious outlier",
  rule_violation: "Rule violation",
};
export const issueLabel = (t: string): string => ISSUE_LABELS[t] ?? humanize(t);
export const ISSUE_TYPES = Object.keys(ISSUE_LABELS);

const ACTION_LABELS: Record<string, string> = {
  replace_value: "Replace value",
  clear_value: "Empty the cell",
  delete_row: "Delete row",
};
export const actionLabel = (a: string): string => ACTION_LABELS[a] ?? humanize(a);

export const SEVERITIES: Severity[] = ["high", "medium", "low"];

const EVENT_LABELS: Record<string, string> = {
  dataset_uploaded: "Dataset uploaded",
  dataset_deleted: "Dataset deleted",
  dataset_expired: "Dataset expired",
  scan_started: "Scan started",
  scan_completed: "Scan completed",
  scan_failed: "Scan failed",
  plan_created: "Repair plan created",
  plan_superseded: "Plan superseded",
  plan_marked_stale: "Plan marked stale",
  proposal_approved: "Proposal approved",
  proposal_rejected: "Proposal rejected",
  bulk_approve_safe: "Safe proposals approved",
  cleaned_started: "Cleaning started",
  cleaned_generated: "Cleaned file generated",
  cleaned_failed: "Cleaning failed",
  cleaned_downloaded: "Cleaned file downloaded",
  cleaned_expired: "Cleaned file expired",
  report_sent: "Email report sent",
  report_failed: "Email report failed",
  report_skipped: "Email report skipped",
  cleanup_run: "Cleanup run",
};
export const eventLabel = (e: string): string => EVENT_LABELS[e] ?? humanize(e);
export const EVENT_TYPES = Object.keys(EVENT_LABELS);

export type Tone = "neutral" | "green" | "amber" | "red" | "blue" | "indigo";

export const severityTone = (s: string): Tone =>
  s === "high" ? "red" : s === "medium" ? "amber" : "blue";

export function statusTone(status: string): Tone {
  switch (status) {
    case "active": case "completed": case "sent": case "approved": case "passed": case "applied":
      return "green";
    case "pending": case "running": case "skipped": case "issues_remaining":
      return "amber";
    case "failed": case "rejected": case "stale":
      return "red";
    default:
      return "neutral"; // superseded, expired, deleted, …
  }
}
