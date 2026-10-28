/**
 * Centralised API client. Every network call in the app goes through here, so
 * error handling, base URL and response types live in exactly one place.
 */
import type {
  ApproveSafeResponse, AuditPage, CleanedSummary, ConfigResponse, DatasetDetail, DatasetInfo,
  DatasetList, DatasetProfile, DecisionKind, DownloadMode, EmailReportInfo, EmailReportList,
  EmailStatus, IssuePage, OutcomePage, PlanSummary, ProposalFilters, ProposalPage,
  ReportPreview, RepairProposal, RuleSet, ScanInfo, ScanList, ScanResponse, StatsResponse,
  SuggestedRulesResponse, UploadResponse,
} from "../types/api";

const BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

/** An error returned by the API (or a network failure, status 0). */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

export const NETWORK_ERROR_MESSAGE =
  "Cannot reach the DataJanitor server. Check that the backend is running and try again.";

type Query = Record<string, string | number | boolean | undefined | null>;

function qs(params?: Query): string {
  if (!params) return "";
  const parts = Object.entries(params)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
}

/** Turn an error response (our {"error":…} body or FastAPI's {"detail":…}) into an ApiError. */
function toApiError(status: number, body: unknown): ApiError {
  const b = body as { error?: { code?: string; message?: string }; detail?: unknown } | null;
  if (b?.error?.message) return new ApiError(status, b.error.code ?? "error", b.error.message);
  if (Array.isArray(b?.detail)) {
    const first = b.detail[0] as { msg?: string; loc?: unknown[] } | undefined;
    const where = first?.loc?.filter((p) => p !== "body" && p !== "query").join(".");
    return new ApiError(status, "validation_error",
      first?.msg ? `${where ? where + ": " : ""}${first.msg}` : "The request was not valid.");
  }
  return new ApiError(status, "http_error", `The server returned an unexpected error (HTTP ${status}).`);
}

async function request<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, ...rest } = init;
  const headers: Record<string, string> = { Accept: "application/json" };
  if (json !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${BASE}${path}`, {
      ...rest,
      headers: { ...headers, ...(rest.headers as Record<string, string> | undefined) },
      body: json !== undefined ? JSON.stringify(json) : rest.body,
    });
  } catch {
    throw new ApiError(0, "network_error", NETWORK_ERROR_MESSAGE);
  }
  if (res.status === 204) return undefined as T;
  const isJson = (res.headers.get("content-type") ?? "").includes("json");
  const body: unknown = isJson ? await res.json().catch(() => null) : null;
  if (!res.ok) throw toApiError(res.status, body);
  return body as T;
}

const enc = encodeURIComponent;

export const api = {
  // ── Server ────────────────────────────────────────────────────────────────
  config: () => request<ConfigResponse>("/api/config"),
  stats: () => request<StatsResponse>("/api/stats"),
  emailStatus: () => request<EmailStatus>("/api/email/status"),

  // ── Datasets ──────────────────────────────────────────────────────────────
  /** Upload with progress. Uses XMLHttpRequest because fetch cannot report upload progress. */
  uploadDataset(file: File, onProgress?: (fraction: number) => void): Promise<UploadResponse> {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", `${BASE}/api/datasets/upload`);
      xhr.setRequestHeader("Accept", "application/json");
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
      };
      xhr.onerror = () => reject(new ApiError(0, "network_error", NETWORK_ERROR_MESSAGE));
      xhr.ontimeout = xhr.onerror;
      xhr.onload = () => {
        let body: unknown = null;
        try { body = JSON.parse(xhr.responseText); } catch { /* non-JSON error page */ }
        if (xhr.status >= 200 && xhr.status < 300) resolve(body as UploadResponse);
        else reject(toApiError(xhr.status, body));
      };
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    });
  },
  listDatasets: (p: { status?: string; offset?: number; limit?: number } = {}) =>
    request<DatasetList>(`/api/datasets${qs(p)}`),
  getDataset: (id: string) => request<DatasetDetail>(`/api/datasets/${enc(id)}`),
  datasetProfile: (id: string, offset = 0, limit = 10) =>
    request<DatasetProfile>(`/api/datasets/${enc(id)}/profile${qs({ offset, limit })}`),
  deleteDataset: (id: string) => request<void>(`/api/datasets/${enc(id)}`, { method: "DELETE" }),
  suggestedRules: (id: string) =>
    request<SuggestedRulesResponse>(`/api/datasets/${enc(id)}/suggested-rules`),

  // ── Scans ─────────────────────────────────────────────────────────────────
  runScan: (datasetId: string) =>
    request<ScanResponse>(`/api/datasets/${enc(datasetId)}/scan`, { method: "POST" }),
  listScans: (p: { dataset_id?: string; status?: string; offset?: number; limit?: number } = {}) =>
    request<ScanList>(`/api/scans${qs(p)}`),
  getScan: (id: string) => request<ScanInfo>(`/api/scans/${enc(id)}`),
  scanIssues: (id: string, p: { issue_type?: string; severity?: string; offset?: number; limit?: number } = {}) =>
    request<IssuePage>(`/api/scans/${enc(id)}/issues${qs(p)}`),

  // ── Repair plans ──────────────────────────────────────────────────────────
  createPlan: (datasetId: string, rules?: RuleSet) =>
    request<PlanSummary>(`/api/datasets/${enc(datasetId)}/repair-plan`, {
      method: "POST",
      json: rules ? { rules } : {},
    }),
  getPlan: (id: string) => request<PlanSummary>(`/api/repair-plans/${enc(id)}`),
  listProposals: (id: string, f: ProposalFilters = {}) =>
    request<ProposalPage>(`/api/repair-plans/${enc(id)}/proposals${qs({ ...f })}`),
  decide: (planId: string, proposalId: string, decision: DecisionKind, chosenValue?: string) =>
    request<RepairProposal>(
      `/api/repair-plans/${enc(planId)}/proposals/${enc(proposalId)}/decision`,
      { method: "POST", json: { decision, ...(chosenValue !== undefined ? { chosen_value: chosenValue } : {}) } }),
  approveSafe: (planId: string) =>
    request<ApproveSafeResponse>(`/api/repair-plans/${enc(planId)}/approve-safe`, { method: "POST" }),
  applyPlan: (planId: string) =>
    request<CleanedSummary>(`/api/repair-plans/${enc(planId)}/apply`, { method: "POST" }),
  planCleaned: (planId: string) =>
    request<CleanedSummary[]>(`/api/repair-plans/${enc(planId)}/cleaned`),

  // ── Cleaned datasets ──────────────────────────────────────────────────────
  getCleaned: (id: string) => request<CleanedSummary>(`/api/cleaned/${enc(id)}`),
  cleanedOutcomes: (id: string, p: { outcome?: string; offset?: number; limit?: number } = {}) =>
    request<OutcomePage>(`/api/cleaned/${enc(id)}/outcomes${qs(p)}`),
  /** Fetch the CSV as a blob (so errors show in the UI instead of a JSON page) and return it. */
  async downloadCleaned(id: string, mode: DownloadMode): Promise<{ blob: Blob; filename: string; cellsEscaped: number }> {
    let res: Response;
    try {
      res = await fetch(`${BASE}/api/cleaned/${enc(id)}/download${qs({ mode })}`);
    } catch {
      throw new ApiError(0, "network_error", NETWORK_ERROR_MESSAGE);
    }
    if (!res.ok) {
      const body: unknown = await res.json().catch(() => null);
      throw toApiError(res.status, body);
    }
    const disposition = res.headers.get("content-disposition") ?? "";
    const filename = /filename="([^"]+)"/.exec(disposition)?.[1] ?? "cleaned.csv";
    return {
      blob: await res.blob(),
      filename,
      cellsEscaped: Number(res.headers.get("x-datajanitor-cells-escaped") ?? 0),
    };
  },

  // ── History, audit, email ─────────────────────────────────────────────────
  auditLogs: (p: { event_type?: string; dataset_id?: string; plan_id?: string; offset?: number; limit?: number } = {}) =>
    request<AuditPage>(`/api/audit-logs${qs(p)}`),
  emailReports: (p: { status?: string; kind?: string; offset?: number; limit?: number } = {}) =>
    request<EmailReportList>(`/api/email-reports${qs(p)}`),
  retryEmailReport: (id: string) =>
    request<EmailReportInfo>(`/api/email-reports/${enc(id)}/retry`, { method: "POST" }),
  previewScanReport: (scanId: string) =>
    request<ReportPreview>(`/api/scans/${enc(scanId)}/report/preview`),
  previewCleanedReport: (cleanedId: string) =>
    request<ReportPreview>(`/api/cleaned/${enc(cleanedId)}/report/preview`),
  sendScanReport: (scanId: string) =>
    request<EmailReportInfo>(`/api/scans/${enc(scanId)}/report`, { method: "POST" }),
  sendCleanedReport: (cleanedId: string) =>
    request<EmailReportInfo>(`/api/cleaned/${enc(cleanedId)}/report`, { method: "POST" }),
};

export type { DatasetInfo };
