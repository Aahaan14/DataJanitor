import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { DownloadButtons } from "../components/DownloadButtons";
import { ReportDialog } from "../components/ReportDialog";
import {
  Async, Badge, Banner, BreakdownBars, Button, Card, EmptyState, PageHeader, Pagination, SelectFilter, StatCard,
  StatusBadge, TableWrap, td, th,
} from "../components/ui";
import { actionLabel, humanize, issueLabel, statusTone } from "../utils/labels";
import { formatBytes, formatDateTime, formatNumber, shortId } from "../utils/format";

const LIMIT = 25;

export default function CleanedDetailPage() {
  const { cleanedId = "" } = useParams();
  const cleaned = useAsync(() => api.getCleaned(cleanedId), [cleanedId]);
  const email = useAsync(() => api.emailStatus(), []);
  const [outcome, setOutcome] = useState("");
  const [offset, setOffset] = useState(0);
  const [reportOpen, setReportOpen] = useState(false);
  const outcomes = useAsync(() => api.cleanedOutcomes(cleanedId, { outcome, offset, limit: LIMIT }), [cleanedId, outcome, offset]);

  return (
    <Async state={cleaned} label="Loading cleaned dataset…">
      {(c) => {
        const ready = c.status === "completed";
        const v = c.validation;
        return (
          <>
            <PageHeader back={{ to: `/plans/${c.plan_id}`, label: "Repair plan" }} title="Cleaned dataset"
                        subtitle={<>Run {shortId(c.cleaned_id)} · {formatDateTime(c.created_at)} · <StatusBadge status={c.status} /></>}
                        actions={ready ? <Button variant="secondary" onClick={() => setReportOpen(true)}>Email report</Button> : undefined} />

            {c.status === "failed" && <Banner kind="error" title="This run failed">{c.error_message ?? "No details were recorded."} Nothing was saved.</Banner>}
            {(c.status === "expired" || c.status === "deleted") && (
              <Banner kind="warning" title="The cleaned file is no longer stored">
                It was {c.status}. The counts and outcomes below are kept; apply the repairs again to make a new copy.
              </Banner>
            )}

            {(ready || v) && (
              <div className="mt-4 space-y-6">
                {ready && (
                  <Card title="Download">
                    <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">
                      Your original upload is untouched — this is a separate copy ({formatBytes(c.size_bytes)}).
                      <strong> Safe for Excel</strong> adds an apostrophe to text that starts with = + - or @, so spreadsheets cannot run it as a formula.
                      <strong> Raw</strong> keeps the exact values.
                    </p>
                    <DownloadButtons cleanedId={c.cleaned_id} />
                  </Card>
                )}

                <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                  <StatCard label="Rows" value={`${formatNumber(c.rows_before)} → ${formatNumber(c.rows_after)}`} hint={`${c.rows_deleted} deleted`} />
                  <StatCard label="Cells changed" value={formatNumber(c.cells_changed)} />
                  <StatCard label="Repairs applied" value={c.applied_count} tone="green" hint={c.skipped_count ? `${c.skipped_count} skipped` : undefined} />
                  <StatCard label="Not applied" value={c.rejected_count + c.pending_count} hint={`${c.rejected_count} rejected · ${c.pending_count} undecided`} />
                </div>

                {v && (
                  <Card title="Final validation" actions={<StatusBadge status={v.status} />}>
                    {v.status === "passed"
                      ? <Banner kind="success" title="All checks passed">The cleaned data has no remaining detected issues or rule violations.</Banner>
                      : <Banner kind="warning" title={`${formatNumber(v.remaining_issue_count)} issue(s) remain`}>
                          {v.rule_violation_count > 0 && <>{v.rule_violation_count} validation-rule violation(s). </>}
                          Remaining issues are candidates for review, not confirmed errors.
                        </Banner>}
                    {v.increased_issue_types.length > 0 && (
                      <div className="mt-3"><Banner kind="warning" title="Some issue types increased after the repairs">
                        {v.increased_issue_types.map(issueLabel).join(", ")}. A repair can change which spelling or value is most common, so check these.
                      </Banner></div>
                    )}
                    <div className="mt-4 grid gap-6 sm:grid-cols-2">
                      <div><h3 className="mb-2 text-sm font-semibold">Before the repairs</h3><BreakdownBars data={v.before_by_type} labelFor={issueLabel} /></div>
                      <div><h3 className="mb-2 text-sm font-semibold">After the repairs</h3><BreakdownBars data={v.remaining_by_type} labelFor={issueLabel} tone="amber" /></div>
                    </div>
                    <p className="mt-3 text-xs text-slate-500">{v.note}</p>
                  </Card>
                )}
              </div>
            )}

            <Card title="What happened to each proposal" className="mt-6">
              <div className="mb-4">
                <SelectFilter label="Outcome" value={outcome} onChange={(x) => { setOutcome(x); setOffset(0); }}
                              options={["applied", "skipped", "rejected", "pending"].map((o) => ({ value: o, label: humanize(o) }))} />
              </div>
              <Async state={outcomes} label="Loading outcomes…">
                {(page) => page.outcomes.length === 0 ? (
                  <EmptyState title="No proposals match">{c.status === "failed" ? "No outcomes were recorded for a failed run." : "Try a different filter."}</EmptyState>
                ) : (
                  <>
                    <TableWrap>
                      <thead><tr>{["Outcome", "Issue", "Action", "Column", "Row", "Note"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                        {page.outcomes.map((o) => (
                          <tr key={o.proposal_id}>
                            <td className={td}><Badge tone={statusTone(o.outcome)}>{o.outcome}</Badge></td>
                            <td className={td}>{issueLabel(o.issue_type)}</td>
                            <td className={td}>{actionLabel(o.action)}</td>
                            <td className={td}>{o.column ?? "—"}</td>
                            <td className={`${td} tabular-nums`}>{o.row_number ?? "—"}</td>
                            <td className={`${td} text-slate-600 dark:text-slate-400`}>{o.reason ?? ""}</td>
                          </tr>
                        ))}
                      </tbody>
                    </TableWrap>
                    <Pagination total={page.total} offset={offset} limit={LIMIT} onChange={setOffset} />
                  </>
                )}
              </Async>
            </Card>
            <p className="mt-6 text-sm"><Link to={`/datasets/${c.dataset_id}`} className="text-indigo-600 hover:underline dark:text-indigo-400">Back to the dataset</Link></p>
            <ReportDialog kind="cleaning" targetId={cleanedId} emailConfigured={email.data?.configured ?? false} open={reportOpen} onClose={() => setReportOpen(false)} />
          </>
        );
      }}
    </Async>
  );
}
