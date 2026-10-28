/**
 * API client contract tests: the typed client against the REAL backend.
 * They prove that the TypeScript types match what the server actually returns.
 */
import { api, ApiError, NETWORK_ERROR_MESSAGE } from "../src/services/api";
import { csvFile, MESSY_CSV, seedDataset, seedPlan, uniqueName } from "./helpers";

const HEX32 = /^[0-9a-f]{32}$/;

describe("upload", () => {
  it("returns metadata, a column profile and a preview", async () => {
    const res = await api.uploadDataset(csvFile(MESSY_CSV, uniqueName("upload")));
    expect(res.dataset_id).toMatch(HEX32);
    expect(res.row_count).toBe(6);
    expect(res.column_count).toBe(6);
    expect(res.encoding).toBe("utf-8");
    expect(res.columns.map((c) => c.name)).toEqual(["id", "name", "age", "joined", "city", "salary"]);
    expect(res.columns.find((c) => c.name === "age")?.inferred_type).toBe("mixed");
    expect(res.preview.rows[0]).toEqual({ row_number: 1, values: expect.objectContaining({ name: "Alice Smith" }) });
  });

  it("maps server rejections to ApiError with the server's code and message", async () => {
    const bad = api.uploadDataset(csvFile("a,b\n1,2\n3,4,5,6\n", "ragged.csv"));
    await expect(bad).rejects.toMatchObject({ status: 422, code: "malformed_csv" });
    await expect(api.uploadDataset(csvFile("", "empty.csv"))).rejects.toMatchObject({ status: 400, code: "empty_file" });
    await expect(api.uploadDataset(csvFile("a\n1\n", "notes.txt"))).rejects.toMatchObject({ status: 415, code: "invalid_file_type" });
    const err = await api.uploadDataset(csvFile("a\n1\n", "notes.txt")).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe("Only .csv files are accepted.");
  });
});

describe("errors", () => {
  it("unknown ids give a typed 404", async () => {
    await expect(api.getDataset("a".repeat(32))).rejects.toMatchObject({ status: 404, code: "dataset_not_found" });
    await expect(api.getPlan("a".repeat(32))).rejects.toMatchObject({ status: 404, code: "plan_not_found" });
  });

  it("FastAPI validation errors become readable ApiErrors", async () => {
    const ds = await seedDataset();
    const err = await api.datasetProfile(ds.dataset_id, 0, 0).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422);
    expect(err.code).toBe("validation_error");
    expect(err.message.length).toBeGreaterThan(0);
  });

  it("a network failure becomes a friendly ApiError", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new TypeError("Failed to fetch")));
    const err = await api.stats().catch((e) => e);
    expect(err).toMatchObject({ status: 0, code: "network_error", message: NETWORK_ERROR_MESSAGE });
    vi.unstubAllGlobals();
  });
});

describe("full workflow against the real backend", () => {
  it("upload → scan → plan → decisions → apply → download → history", async () => {
    const ds = await seedDataset();
    const id = ds.dataset_id;

    const profile = await api.datasetProfile(id, 3, 2);
    expect(profile.preview.rows.map((r) => r.row_number)).toEqual([4, 5]);

    const scan = await api.runScan(id);
    expect(scan.status).toBe("completed");
    expect(scan.summary.total_issues).toBeGreaterThan(5);
    expect(scan.issues[0]).toMatchObject({ status: "detected" });
    const stored = await api.getScan(scan.scan_id);
    expect(stored.issue_total).toBe(scan.summary.total_issues);
    const dateIssues = await api.scanIssues(scan.scan_id, { issue_type: "invalid_date" });
    expect(dateIssues.total).toBe(1);

    const rules = await api.suggestedRules(id);
    expect(rules.rules.rules.find((r) => r.column === "id")?.dtype).toBe("integer");

    const plan = await api.createPlan(id, {
      rules: [{ column: "age", dtype: "integer", nullable: true, unique: false, min_value: 0, max_value: 120,
                min_length: null, max_length: null, allowed_values: null, regex: null }],
    });
    expect(plan.status).toBe("active");
    expect(plan.validation).toMatchObject({ ran: true, rule_count: 1, violation_count: 1 });
    expect(plan.status_counts.pending).toBe(plan.proposal_count);

    const all = await api.listProposals(plan.plan_id, { limit: 100 });
    expect(all.total).toBe(plan.proposal_count);
    const ws = all.proposals.find((p) => p.issue_type === "whitespace")!;
    const date = all.proposals.find((p) => p.issue_type === "inconsistent_date_format")!;
    expect(date.proposed_value).toBeNull();
    expect(date.alternatives).toHaveLength(2);

    // an ambiguous proposal needs a choice
    await expect(api.decide(plan.plan_id, date.proposal_id, "approve")).rejects.toMatchObject({ status: 422, code: "invalid_decision" });
    const picked = await api.decide(plan.plan_id, date.proposal_id, "approve", date.alternatives[0]);
    expect(picked).toMatchObject({ status: "approved", approved_value: date.alternatives[0] });

    const safe = await api.approveSafe(plan.plan_id);
    expect(safe.approved_count).toBeGreaterThan(0);
    const approvedWs = (await api.listProposals(plan.plan_id, { status: "approved" })).proposals.find((p) => p.proposal_id === ws.proposal_id);
    expect(approvedWs?.approved_value).toBe("alice smith");

    const run = await api.applyPlan(plan.plan_id);
    expect(run.status).toBe("completed");
    expect(run.applied_count).toBe(safe.approved_count + 1);
    expect(run.validation).not.toBeNull();
    expect(run.download_url).toContain(run.cleaned_id);

    const out = await api.cleanedOutcomes(run.cleaned_id, { outcome: "applied" });
    expect(out.total).toBe(run.applied_count);
    expect((await api.planCleaned(plan.plan_id))[0]?.cleaned_id).toBe(run.cleaned_id);

    const raw = await api.downloadCleaned(run.cleaned_id, "raw");
    expect(raw.filename).toMatch(/_cleaned\.csv$/);
    const text = (await raw.blob.text()).replace(/^\uFEFF/, "");
    expect(text.split("\r\n")[0]).toBe("id,name,age,joined,city,salary");
    expect(text).toContain("4,alice smith,30");            // trimmed by the approved repair
    expect(text).toContain("5,Dan,abc,2024-03-01,Pune,1200");

    const detail = await api.getDataset(id);
    expect(detail.scans.length).toBeGreaterThan(0);
    expect(detail.plans[0]?.plan_id).toBe(plan.plan_id);
    expect((await api.stats()).cleaned_datasets.completed).toBeGreaterThan(0);
    const audit = await api.auditLogs({ plan_id: plan.plan_id, limit: 50 });
    expect(audit.entries.map((e) => e.event_type)).toEqual(expect.arrayContaining(["plan_created", "proposal_approved", "cleaned_generated"]));
  });

  it("the downloadable file is safe by default and the original is untouched in the profile", async () => {
    const csv = "id,note\n1, padded\n2,=1+1\n3,-5\n";
    const { ds, plan } = await seedPlan(csv);
    await api.approveSafe(plan.plan_id);
    const run = await api.applyPlan(plan.plan_id);
    const safe = await api.downloadCleaned(run.cleaned_id, "safe");
    const text = await safe.blob.text();
    expect(text).toContain("2,'=1+1");
    expect(text).toContain("3,-5");
    expect(safe.cellsEscaped).toBe(1);
    const profile = await api.datasetProfile(ds.dataset_id);
    expect(profile.preview.rows[0]?.values.note).toBe(" padded");      // original still has the spaces
  });

  it("a newer plan supersedes an older one and closes its decisions", async () => {
    const { ds, plan } = await seedPlan();
    await api.createPlan(ds.dataset_id);
    expect((await api.getPlan(plan.plan_id)).status).toBe("superseded");
    const any = (await api.listProposals(plan.plan_id, { limit: 1 })).proposals[0]!;
    await expect(api.decide(plan.plan_id, any.proposal_id, "reject")).rejects.toMatchObject({ status: 409, code: "plan_superseded" });
  });

  it("server info endpoints are typed correctly", async () => {
    const cfg = await api.config();
    expect(cfg).toMatchObject({ app_name: "DataJanitor", max_upload_size_mb: 10 });
    expect(cfg.email.enabled).toBe(false);
    expect(await api.emailStatus()).toMatchObject({ enabled: false, configured: false });
    await expect(api.sendScanReport("a".repeat(32))).rejects.toMatchObject({ status: 409, code: "email_not_configured" });
  });

  it("deleting a dataset keeps its history", async () => {
    const ds = await seedDataset();
    const scan = await api.runScan(ds.dataset_id);
    await api.deleteDataset(ds.dataset_id);
    await expect(api.runScan(ds.dataset_id)).rejects.toMatchObject({ status: 410, code: "dataset_unavailable" });
    expect((await api.getScan(scan.scan_id)).status).toBe("completed");
    expect((await api.getDataset(ds.dataset_id)).dataset.status).toBe("deleted");
  });
});
