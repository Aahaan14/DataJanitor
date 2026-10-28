import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import { toApiError, useAsync } from "../hooks/useAsync";
import { useToast } from "../components/Toast";
import { Async, Button, EmptyState, PageHeader, Pagination, SelectFilter, StatusBadge, Tabs, TableWrap, td, th } from "../components/ui";
import { EVENT_TYPES, eventLabel, humanize } from "../utils/labels";
import { formatDateTime, formatNumber, shortId } from "../utils/format";

type Tab = "scans" | "audit" | "emails";
const LIMIT = 20;

function ScansTab() {
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const state = useAsync(() => api.listScans({ status, offset, limit: LIMIT }), [status, offset]);
  return (
    <>
      <div className="mb-4"><SelectFilter label="Status" value={status} onChange={(v) => { setStatus(v); setOffset(0); }}
        options={["completed", "failed", "running"].map((v) => ({ value: v, label: humanize(v) }))} /></div>
      <Async state={state} label="Loading scans…">
        {(page) => page.scans.length === 0 ? <EmptyState title="No scans yet">Run a scan from a dataset page.</EmptyState> : (
          <>
            <TableWrap>
              <thead><tr>{["Started", "Status", "Issues", "Dataset", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {page.scans.map((s) => (
                  <tr key={s.scan_id}>
                    <td className={`${td} whitespace-nowrap`}>{formatDateTime(s.started_at)}</td>
                    <td className={td}><StatusBadge status={s.status} /></td>
                    <td className={`${td} tabular-nums`}>{s.status === "completed" ? formatNumber(s.issue_total) : "—"}</td>
                    <td className={td}><Link className="text-indigo-700 hover:underline dark:text-indigo-300" to={`/datasets/${s.dataset_id}`}>{shortId(s.dataset_id)}</Link></td>
                    <td className={td}><Link className="text-indigo-700 hover:underline dark:text-indigo-300" to={`/scans/${s.scan_id}`}>Open</Link></td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
            <Pagination total={page.total} offset={offset} limit={LIMIT} onChange={setOffset} />
          </>
        )}
      </Async>
    </>
  );
}

function AuditTab() {
  const [eventType, setEventType] = useState("");
  const [offset, setOffset] = useState(0);
  const state = useAsync(() => api.auditLogs({ event_type: eventType, offset, limit: LIMIT }), [eventType, offset]);
  return (
    <>
      <p className="mb-3 text-sm text-slate-600 dark:text-slate-400">An append-only record of what happened and when. It stores identifiers and counts, never the values in your data.</p>
      <div className="mb-4"><SelectFilter label="Event" value={eventType} onChange={(v) => { setEventType(v); setOffset(0); }}
        options={EVENT_TYPES.map((e) => ({ value: e, label: eventLabel(e) }))} /></div>
      <Async state={state} label="Loading audit log…">
        {(page) => page.entries.length === 0 ? <EmptyState title="No events">Nothing has been recorded for this filter.</EmptyState> : (
          <>
            <TableWrap>
              <thead><tr>{["When", "Event", "Item", "Details"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {page.entries.map((e) => (
                  <tr key={e.id}>
                    <td className={`${td} whitespace-nowrap`}>{formatDateTime(e.timestamp)}</td>
                    <td className={td}>{eventLabel(e.event_type)}</td>
                    <td className={`${td} font-mono text-xs`}>{e.entity_type} {shortId(e.entity_id)}</td>
                    <td className={td}>
                      {Object.keys(e.details).length ? (
                        <details><summary className="cursor-pointer text-xs text-indigo-700 dark:text-indigo-300">Show</summary>
                          <pre className="mt-1 whitespace-pre-wrap text-xs">{JSON.stringify(e.details, null, 1)}</pre></details>
                      ) : <span className="text-slate-400">—</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
            <Pagination total={page.total} offset={offset} limit={LIMIT} onChange={setOffset} />
          </>
        )}
      </Async>
    </>
  );
}

function EmailsTab() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [retrying, setRetrying] = useState<string | null>(null);
  const state = useAsync(() => api.emailReports({ status, offset, limit: LIMIT }), [status, offset]);

  const retry = async (id: string) => {
    setRetrying(id);
    try {
      const r = await api.retryEmailReport(id);
      r.status === "sent" ? toast.success("Report sent") : toast.error("Still failing", r.error_message ?? "Check the email settings.");
      state.reload();
    } catch (e) {
      toast.error("Could not retry", toApiError(e).message);
    } finally { setRetrying(null); }
  };

  return (
    <>
      <div className="mb-4"><SelectFilter label="Status" value={status} onChange={(v) => { setStatus(v); setOffset(0); }}
        options={["sent", "failed", "skipped", "pending"].map((v) => ({ value: v, label: humanize(v) }))} /></div>
      <Async state={state} label="Loading email reports…">
        {(page) => page.reports.length === 0 ? <EmptyState title="No email reports">Reports are sent automatically after scans and cleaning runs once email is configured (see Settings).</EmptyState> : (
          <>
            <TableWrap>
              <thead><tr>{["When", "Report", "Status", "To", "Detail", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {page.reports.map((r) => (
                  <tr key={r.report_id}>
                    <td className={`${td} whitespace-nowrap`}>{formatDateTime(r.created_at)}</td>
                    <td className={td}>{humanize(r.kind)} · {r.trigger}</td>
                    <td className={td}><StatusBadge status={r.status} /></td>
                    <td className={td}>{r.recipient_masked || "—"}</td>
                    <td className={`${td} max-w-xs text-slate-600 dark:text-slate-400`}>{r.error_message ?? (r.status === "sent" ? `Sent ${formatDateTime(r.sent_at)}` : "")}</td>
                    <td className={td}>{(r.status === "failed" || r.status === "skipped") && <Button size="sm" variant="secondary" loading={retrying === r.report_id} onClick={() => retry(r.report_id)}>Retry</Button>}</td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
            <Pagination total={page.total} offset={offset} limit={LIMIT} onChange={setOffset} />
          </>
        )}
      </Async>
    </>
  );
}

export default function HistoryPage() {
  const [tab, setTab] = useState<Tab>("scans");
  return (
    <>
      <PageHeader title="History" subtitle="Scans, the audit trail and email reports." />
      <Tabs<Tab> active={tab} onChange={setTab} tabs={[{ key: "scans", label: "Scans" }, { key: "audit", label: "Audit log" }, { key: "emails", label: "Email reports" }]} />
      {tab === "scans" && <ScansTab />}
      {tab === "audit" && <AuditTab />}
      {tab === "emails" && <EmailsTab />}
    </>
  );
}
