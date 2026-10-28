import { Link } from "react-router-dom";
import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { Async, Card, EmptyState, LinkButton, PageHeader, StatCard, StatusBadge } from "../components/ui";
import { eventLabel } from "../utils/labels";
import { formatBytes, formatNumber, formatPercent, formatRelative } from "../utils/format";

export default function DashboardPage() {
  const state = useAsync(async () => {
    const [stats, datasets, audit] = await Promise.all([
      api.stats(), api.listDatasets({ status: "active", limit: 5 }), api.auditLogs({ limit: 8 }),
    ]);
    return { stats, datasets, audit };
  }, []);

  return (
    <>
      <PageHeader title="Dashboard" subtitle="Data quality at a glance. Nothing is ever changed without your approval."
                  actions={<LinkButton to="/upload" variant="primary">Upload a CSV</LinkButton>} />
      <Async state={state} label="Loading dashboard…">
        {({ stats, datasets, audit }) => {
          const scans = stats.scans;
          const proposals = stats.proposals;
          const emailsSent = stats.email_reports.sent ?? 0;
          const emailsFailed = stats.email_reports.failed ?? 0;
          if (datasets.total === 0 && Object.keys(stats.datasets).length === 0) {
            return (
              <EmptyState title="No datasets yet" action={<LinkButton to="/upload" variant="primary">Upload your first CSV</LinkButton>}>
                Upload a CSV file and DataJanitor will profile it, find data-quality issues and suggest fixes you can review.
              </EmptyState>
            );
          }
          return (
            <div className="space-y-6">
              <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
                <StatCard label="Datasets" value={formatNumber(stats.datasets.active ?? 0)} hint="active uploads" />
                <StatCard label="Scans" value={formatNumber(scans.completed ?? 0)}
                          hint={scans.failed ? `${scans.failed} failed` : "completed"} tone={scans.failed ? "red" : undefined} />
                <StatCard label="Issues detected" value={formatNumber(stats.issues_detected)} hint="across all scans" />
                <StatCard label="Approval rate" value={formatPercent(stats.approval_rate)} hint="of decided proposals" />
                <StatCard label="Approved repairs" value={formatNumber(proposals.approved ?? 0)} tone="green" />
                <StatCard label="Rejected" value={formatNumber(proposals.rejected ?? 0)} />
                <StatCard label="Awaiting review" value={formatNumber(proposals.pending ?? 0)} hint="pending proposals" />
                <StatCard label="Cleaned files" value={formatNumber(stats.cleaned_datasets.completed ?? 0)}
                          hint={`${emailsSent} emails sent${emailsFailed ? `, ${emailsFailed} failed` : ""}`} />
              </div>

              <div className="grid gap-6 lg:grid-cols-2">
                <Card title="Recent datasets" actions={<Link to="/datasets" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">View all</Link>}>
                  {datasets.datasets.length === 0 ? <p className="text-sm text-slate-500">No active datasets.</p> : (
                    <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                      {datasets.datasets.map((d) => (
                        <li key={d.dataset_id} className="flex items-center justify-between gap-3 py-2">
                          <div className="min-w-0">
                            <Link to={`/datasets/${d.dataset_id}`} className="block truncate font-medium text-indigo-700 hover:underline dark:text-indigo-300">{d.filename}</Link>
                            <p className="text-xs text-slate-500">{formatNumber(d.row_count)} rows × {d.column_count} cols · {formatBytes(d.size_bytes)}</p>
                          </div>
                          <span className="shrink-0 text-xs text-slate-500">{formatRelative(d.uploaded_at)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>

                <Card title="Recent activity" actions={<Link to="/history" className="text-sm text-indigo-600 hover:underline dark:text-indigo-400">Full history</Link>}>
                  {audit.entries.length === 0 ? <p className="text-sm text-slate-500">No activity yet.</p> : (
                    <ul className="divide-y divide-slate-100 dark:divide-slate-800">
                      {audit.entries.map((e) => (
                        <li key={e.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                          <span>{eventLabel(e.event_type)}</span>
                          <span className="shrink-0 text-xs text-slate-500">{formatRelative(e.timestamp)}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Card>
              </div>

              {(stats.plans.active ?? 0) > 0 && (
                <p className="text-sm text-slate-600 dark:text-slate-400">
                  <StatusBadge status="active" /> {stats.plans.active} repair plan(s) open for review.
                </p>
              )}
            </div>
          );
        }}
      </Async>
    </>
  );
}
