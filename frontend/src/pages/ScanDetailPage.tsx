import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../services/api";
import { toApiError, useAsync } from "../hooks/useAsync";
import { ReportDialog } from "../components/ReportDialog";
import { useToast } from "../components/Toast";
import {
  Async, Badge, Banner, BreakdownBars, Button, Card, Cell, EmptyState, PageHeader, Pagination, SelectFilter,
  StatCard, StatusBadge, TableWrap, td, th,
} from "../components/ui";
import { ISSUE_TYPES, SEVERITIES, humanize, issueLabel, severityTone } from "../utils/labels";
import { formatDateTime, formatNumber, shortId } from "../utils/format";

const LIMIT = 25;

export default function ScanDetailPage() {
  const { scanId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const scan = useAsync(() => api.getScan(scanId), [scanId]);
  const email = useAsync(() => api.emailStatus(), []);
  const [issueType, setIssueType] = useState("");
  const [severity, setSeverity] = useState("");
  const [offset, setOffset] = useState(0);
  const [reportOpen, setReportOpen] = useState(false);
  const [planning, setPlanning] = useState(false);
  const completed = scan.data?.status === "completed";
  const issues = useAsync(
    () => (completed ? api.scanIssues(scanId, { issue_type: issueType, severity, offset, limit: LIMIT }) : Promise.resolve(null)),
    [scanId, completed, issueType, severity, offset]);

  const createPlan = async (datasetId: string) => {
    setPlanning(true);
    try {
      const plan = await api.createPlan(datasetId);
      navigate(`/plans/${plan.plan_id}`);
    } catch (e) {
      toast.error("Could not create the plan", toApiError(e).message);
      setPlanning(false);
    }
  };

  return (
    <Async state={scan} label="Loading scan…">
      {(s) => {
        const sum = s.summary;
        return (
          <>
            <PageHeader back={{ to: `/datasets/${s.dataset_id}`, label: "Dataset" }} title="Scan results"
                        subtitle={<>Scan {shortId(s.scan_id)} · {formatDateTime(s.started_at)} · <StatusBadge status={s.status} /></>}
                        actions={completed ? <>
                          <Button onClick={() => createPlan(s.dataset_id)} loading={planning}>Create repair plan</Button>
                          <Button variant="secondary" onClick={() => setReportOpen(true)}>Email report</Button>
                        </> : undefined} />

            {s.status === "failed" && <Banner kind="error" title="This scan failed">{s.error_message ?? "No details were recorded."}</Banner>}
            {s.status === "running" && <Banner kind="info" title="This scan is still running">Reload in a moment.</Banner>}

            {completed && sum && (
              <div className="space-y-6">
                <Banner kind="info">Issues are <strong>detected candidates</strong>, not confirmed errors. Nothing has been changed in your data.</Banner>
                {s.truncated && <Banner kind="warning" title="Only part of the list is stored">
                  {formatNumber(s.stored_issue_count)} of {formatNumber(s.issue_total)} issues are listed below; the counts on this page are complete.
                </Banner>}
                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <StatCard label="Issues detected" value={formatNumber(sum.total_issues)} tone={sum.total_issues ? undefined : "green"} />
                  <StatCard label="Rows affected" value={formatNumber(sum.affected_row_count)} />
                  <StatCard label="High severity" value={sum.by_severity.high ?? 0} tone={sum.by_severity.high ? "red" : undefined} />
                  <StatCard label="Issue types" value={Object.keys(sum.by_type).length} />
                </div>

                {sum.total_issues === 0 ? (
                  <EmptyState title="No issues found">This dataset looks clean to every check DataJanitor runs.</EmptyState>
                ) : (
                  <>
                    <div className="grid gap-4 lg:grid-cols-3">
                      <Card title="By severity"><BreakdownBars data={sum.by_severity} tone="red" /></Card>
                      <Card title="By type"><BreakdownBars data={sum.by_type} labelFor={issueLabel} /></Card>
                      <Card title="By column"><BreakdownBars data={sum.by_column} labelFor={(k) => k || "(unnamed)"} tone="amber" /></Card>
                    </div>

                    <Card title="Issues">
                      <div className="mb-4 flex flex-wrap gap-3">
                        <SelectFilter label="Type" value={issueType} onChange={(v) => { setIssueType(v); setOffset(0); }}
                                      options={ISSUE_TYPES.map((t) => ({ value: t, label: issueLabel(t) }))} />
                        <SelectFilter label="Severity" value={severity} onChange={(v) => { setSeverity(v); setOffset(0); }}
                                      options={SEVERITIES.map((v) => ({ value: v, label: humanize(v) }))} />
                      </div>
                      <Async state={issues} label="Loading issues…">
                        {(page) => !page || page.issues.length === 0 ? (
                          <p className="text-sm text-slate-500">No issues match these filters.</p>
                        ) : (
                          <>
                            <TableWrap>
                              <thead><tr>{["Severity", "Type", "Column", "Row", "Observed value", "What we found"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
                              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                                {page.issues.map((i) => (
                                  <tr key={i.issue_id}>
                                    <td className={td}><Badge tone={severityTone(i.severity)}>{i.severity}</Badge></td>
                                    <td className={`${td} whitespace-nowrap`}>{issueLabel(i.issue_type)}</td>
                                    <td className={td}>{i.column ?? <span className="text-slate-400">row</span>}</td>
                                    <td className={`${td} tabular-nums`}>{i.row_number ?? "—"}</td>
                                    <td className={`${td} max-w-xs`}><Cell value={i.observed_value} /></td>
                                    <td className={`${td} min-w-64`}>
                                      <p>{i.explanation}</p>
                                      <p className="mt-0.5 text-xs text-slate-500">Suggested: {i.suggested_action}</p>
                                    </td>
                                  </tr>
                                ))}
                              </tbody>
                            </TableWrap>
                            <Pagination total={page.total} offset={offset} limit={LIMIT} onChange={setOffset} />
                          </>
                        )}
                      </Async>
                    </Card>
                  </>
                )}
              </div>
            )}
            <p className="mt-6 text-sm text-slate-500"><Link to={`/datasets/${s.dataset_id}`} className="text-indigo-600 hover:underline dark:text-indigo-400">Back to the dataset</Link></p>
            <ReportDialog kind="scan" targetId={scanId} emailConfigured={email.data?.configured ?? false} open={reportOpen} onClose={() => setReportOpen(false)} />
          </>
        );
      }}
    </Async>
  );
}
