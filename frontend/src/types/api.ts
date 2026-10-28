/**
 * Types mirroring the DataJanitor REST API (backend/app/schemas/*).
 * Keep in sync with the backend: every response the UI reads is typed here.
 */

// ── Shared ──────────────────────────────────────────────────────────────────
export type Severity = "low" | "medium" | "high";

export type IssueType =
  | "missing_value"
  | "placeholder_missing"
  | "exact_duplicate"
  | "potential_duplicate"
  | "whitespace"
  | "inconsistent_text_format"
  | "invalid_date"
  | "inconsistent_date_format"
  | "ambiguous_date_format"
  | "invalid_numeric"
  | "numeric_format"
  | "suspicious_outlier"
  | "rule_violation";

export interface ApiErrorBody {
  error: { code: string; message: string };
}

// ── Datasets ────────────────────────────────────────────────────────────────
export type DatasetStatus = "active" | "deleted" | "expired";

export interface DatasetInfo {
  dataset_id: string;
  filename: string;
  size_bytes: number;
  sha256: string;
  encoding: string;
  delimiter: string;
  row_count: number;
  column_count: number;
  status: DatasetStatus;
  uploaded_at: string;
  file_removed_at: string | null;
}

export interface DatasetList {
  total: number;
  offset: number;
  limit: number;
  datasets: DatasetInfo[];
}

export type StatValue = number | string | null;

export interface ColumnProfile {
  name: string;
  inferred_type: "integer" | "float" | "boolean" | "datetime" | "text" | "mixed" | "empty";
  non_null_count: number;
  missing_count: number;
  missing_percent: number;
  unique_count: number;
  parse_ratio: number | null;
  stats: Record<string, StatValue>;
}

export interface PreviewRow {
  row_number: number;
  values: Record<string, string | null>;
}

export interface DatasetPreview {
  columns: string[];
  rows: PreviewRow[];
  preview_row_count: number;
}

export interface UploadResponse {
  dataset_id: string;
  filename: string;
  size_bytes: number;
  encoding: string;
  delimiter: string;
  row_count: number;
  column_count: number;
  uploaded_at: string;
  columns: ColumnProfile[];
  preview: DatasetPreview;
  warnings: string[];
}

export interface DatasetProfile {
  dataset_id: string;
  filename: string;
  row_count: number;
  column_count: number;
  encoding: string;
  delimiter: string;
  columns: ColumnProfile[];
  preview: DatasetPreview;
  preview_offset: number;
  preview_limit: number;
  warnings: string[];
}

export interface DatasetDetail {
  dataset: DatasetInfo;
  scans: ScanInfo[];
  plans: PlanSummary[];
}

// ── Scans and issues ────────────────────────────────────────────────────────
export interface DetectionSummary {
  total_issues: number;
  affected_row_count: number;
  by_type: Record<string, number>;
  by_severity: Record<string, number>;
  by_column: Record<string, number>;
}

export type ScanStatus = "running" | "completed" | "failed";

export interface ScanInfo {
  scan_id: string;
  dataset_id: string;
  status: ScanStatus;
  started_at: string;
  completed_at: string | null;
  issue_total: number;
  stored_issue_count: number;
  truncated: boolean;
  summary: DetectionSummary | null;
  error_message: string | null;
}

export interface ScanList {
  total: number;
  offset: number;
  limit: number;
  scans: ScanInfo[];
}

export interface Issue {
  issue_id: string;
  issue_type: IssueType;
  severity: Severity;
  column: string | null;
  row_number: number | null;
  observed_value: string | null;
  explanation: string;
  suggested_action: string;
  status: "detected";
  details: Record<string, unknown>;
}

export interface IssuePage {
  scan_id: string;
  total: number;
  offset: number;
  limit: number;
  issues: Issue[];
}

export interface ScanResponse {
  scan_id: string;
  status: string;
  dataset_id: string;
  scanned_at: string;
  row_count: number;
  column_count: number;
  summary: DetectionSummary;
  issues_returned: number;
  truncated: boolean;
  disclaimer: string;
  issues: Issue[];
}

// ── Validation rules ────────────────────────────────────────────────────────
export type RuleDtype = "integer" | "float" | "date" | "boolean" | "string";

export interface ColumnRule {
  column: string;
  dtype: RuleDtype | null;
  nullable: boolean;
  unique: boolean;
  min_value: number | null;
  max_value: number | null;
  min_length: number | null;
  max_length: number | null;
  allowed_values: string[] | null;
  regex: string | null;
}

export interface RuleSet {
  rules: ColumnRule[];
}

export interface SuggestedRulesResponse {
  dataset_id: string;
  rules: RuleSet;
}

export interface RuleViolation {
  column: string | null;
  row_number: number | null;
  rule: string;
  observed_value: string | null;
}

export interface ValidationSummary {
  ran: boolean;
  rule_count: number;
  violation_count: number;
  by_column: Record<string, number>;
  violations_sample: RuleViolation[];
}

// ── Repair plans ────────────────────────────────────────────────────────────
export type PlanStatus = "active" | "superseded" | "stale";
export type ProposalStatus = "pending" | "approved" | "rejected";
export type RepairAction = "replace_value" | "clear_value" | "delete_row";
export type Classification = "safe" | "ambiguous";
export type Confidence = "high" | "medium" | "low";
export type DecisionKind = "approve" | "reject";

export interface NoProposalGroup {
  issue_type: string;
  reason: string;
  count: number;
}

export interface PlanSummary {
  plan_id: string;
  dataset_id: string;
  scan_id: string;
  dataset_fingerprint: string;
  created_at: string;
  status: PlanStatus;
  row_count: number;
  column_count: number;
  issue_count: number;
  proposal_count: number;
  safe_count: number;
  ambiguous_count: number;
  status_counts: Record<ProposalStatus, number>;
  issues_without_proposal: NoProposalGroup[];
  truncated: boolean;
  validation: ValidationSummary;
}

export interface DecisionRecord {
  decision: DecisionKind;
  decided_at: string;
  chosen_value: string | null;
}

export interface RepairProposal {
  proposal_id: string;
  issue_id: string;
  issue_type: IssueType;
  action: RepairAction;
  classification: Classification;
  confidence: Confidence;
  column: string | null;
  row_number: number | null;
  original_value: string | null;
  proposed_value: string | null;
  alternatives: string[];
  allow_custom_value: boolean;
  reason: string;
  status: ProposalStatus;
  approved_value: string | null;
  decided_at: string | null;
  conflicts_with: string[];
  history: DecisionRecord[];
}

export interface ProposalPage {
  plan_id: string;
  plan_status: PlanStatus;
  total: number;
  offset: number;
  limit: number;
  proposals: RepairProposal[];
}

export interface ProposalFilters {
  status?: ProposalStatus;
  classification?: Classification;
  issue_type?: IssueType;
  column?: string;
  offset?: number;
  limit?: number;
}

export interface ApproveSafeResponse {
  approved_count: number;
  skipped: { proposal_id: string; reason: string }[];
  status_counts: Record<ProposalStatus, number>;
}

// ── Cleaned datasets ────────────────────────────────────────────────────────
export interface FinalValidation {
  status: "passed" | "issues_remaining";
  remaining_issue_count: number;
  remaining_by_type: Record<string, number>;
  remaining_by_severity: Record<string, number>;
  before_by_type: Record<string, number>;
  increased_issue_types: string[];
  rule_count: number;
  rule_violation_count: number;
  rule_violations_sample: RuleViolation[];
  note: string;
}

export type CleanedStatus = "running" | "completed" | "failed" | "expired" | "deleted";

export interface CleanedSummary {
  cleaned_id: string;
  plan_id: string;
  dataset_id: string;
  status: CleanedStatus;
  created_at: string;
  completed_at: string | null;
  rows_before: number;
  rows_after: number;
  rows_deleted: number;
  cells_changed: number;
  applied_count: number;
  skipped_count: number;
  rejected_count: number;
  pending_count: number;
  sha256: string | null;
  size_bytes: number;
  validation: FinalValidation | null;
  download_url: string | null;
  error_message: string | null;
}

export type OutcomeKind = "applied" | "skipped" | "rejected" | "pending";

export interface OutcomeEntry {
  proposal_id: string;
  outcome: OutcomeKind;
  reason: string | null;
  action: RepairAction;
  issue_type: IssueType;
  column: string | null;
  row_number: number | null;
}

export interface OutcomePage {
  cleaned_id: string;
  total: number;
  offset: number;
  limit: number;
  outcomes: OutcomeEntry[];
}

export type DownloadMode = "safe" | "raw";

// ── Email reports ───────────────────────────────────────────────────────────
export interface EmailStatus {
  enabled: boolean;
  configured: boolean;
  problem: string | null;
  smtp_host: string | null;
  smtp_security: string | null;
  recipient_masked: string | null;
  include_names: boolean;
}

export interface EmailReportInfo {
  report_id: string;
  kind: "scan" | "cleaning";
  trigger: "auto" | "manual";
  dataset_id: string;
  scan_id: string | null;
  plan_id: string | null;
  cleaned_id: string | null;
  recipient_masked: string;
  subject: string;
  status: "pending" | "sent" | "failed" | "skipped";
  attempts: number;
  error_message: string | null;
  created_at: string;
  last_attempt_at: string | null;
  sent_at: string | null;
}

export interface EmailReportList {
  total: number;
  offset: number;
  limit: number;
  reports: EmailReportInfo[];
}

export interface ReportPreview {
  subject: string;
  text: string;
  content: unknown;
}

// ── History, audit, stats, config ───────────────────────────────────────────
export interface AuditEntry {
  id: number;
  timestamp: string;
  event_type: string;
  entity_type: string;
  entity_id: string | null;
  dataset_id: string | null;
  plan_id: string | null;
  actor: string;
  details: Record<string, unknown>;
}

export interface AuditPage {
  total: number;
  offset: number;
  limit: number;
  entries: AuditEntry[];
}

export interface StatsResponse {
  datasets: Record<string, number>;
  scans: Record<string, number>;
  issues_detected: number;
  plans: Record<string, number>;
  proposals: Record<string, number>;
  approval_rate: number | null;
  cleaned_datasets: Record<string, number>;
  email_reports: Record<string, number>;
}

export interface ConfigResponse {
  app_name: string;
  version: string;
  environment: string;
  max_upload_size_mb: number;
  max_rows: number;
  max_columns: number;
  preview_rows: number;
  max_issues_returned: number;
  max_proposals_per_plan: number;
  upload_retention_days: number;
  cleaned_retention_days: number;
  orphan_grace_hours: number;
  report_include_names: boolean;
  email: EmailStatus;
}
