import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../services/api";
import { toApiError, useAsync } from "../hooks/useAsync";
import type { ColumnRule, DatasetDetail } from "../types/api";
import { ColumnProfileTable, PreviewTable } from "../components/DataTables";
import { ConfirmDialog, Modal } from "../components/Modal";
import { RulesEditor, validateRules } from "../components/RulesEditor";
import { useToast } from "../components/Toast";
import {
  Async, Badge, Banner, Button, Card, EmptyState, LoadingBlock, PageHeader, Pagination, StatCard, StatusBadge,
  Tabs, TableWrap, td, th,
} from "../components/ui";
import { formatBytes, formatDateTime, formatNumber, shortId } from "../utils/format";

const PREVIEW_LIMIT = 10;
type Tab = "overview" | "scans" | "plans";

function CreatePlanDialog({ datasetId, columns, open, onClose }: { datasetId: string; columns: string[]; open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [useRules, setUseRules] = useState(false);
  const [rules, setRules] = useState<ColumnRule[]>([]);
  const [loadedRules, setLoadedRules] = useState(false);
  const [busy, setBusy] = useState(false);
  const problems = useRules ? validateRules(rules) : [];

  useEffect(() => {
    if (!open || loadedRules) return;
    api.suggestedRules(datasetId).then((r) => { setRules(r.rules.rules as ColumnRule[]); setLoadedRules(true); }, () => setLoadedRules(true));
  }, [open, loadedRules, datasetId]);

  const submit = async () => {
    setBusy(true);
    try {
      const plan = await api.createPlan(datasetId, useRules ? { rules } : undefined);
      toast.success("Repair plan created", `${plan.proposal_count} proposal(s) ready for your review.`);
      navigate(`/plans/${plan.plan_id}`);
    } catch (e) {
      toast.error("Could not create the plan", toApiError(e).message);
      setBusy(false);
    }
  };

  return (
    <Modal open={open} onClose={onClose} title="Create a repair plan" wide
           footer={<>
             <Button variant="secondary" onClick={onClose} disabled={busy}>Cancel</Button>
             <Button onClick={submit} loading={busy} disabled={problems.length > 0}>Create plan</Button>
           </>}>
      <div className="space-y-4 text-sm">
        <p>DataJanitor scans the dataset and proposes fixes. <strong>Nothing is changed</strong> — you review and approve each proposal afterwards.</p>
        <label className="flex items-start gap-2">
          <input type="checkbox" className="mt-1" checked={useRules} onChange={(e) => setUseRules(e.target.checked)} />
          <span><span className="font-medium">Also check my validation rules</span><br />
            <span className="text-slate-600 dark:text-slate-400">Flag values that break constraints such as “age must be between 0 and 120”.</span></span>
        </label>
        {useRules && (!loadedRules ? <LoadingBlock label="Loading suggested rules…" /> : (
          <div className="space-y-2">
            <RulesEditor columns={columns} rules={rules} onChange={setRules} />
            {problems.map((p) => <p key={p} role="alert" className="text-sm text-red-700 dark:text-red-400">{p}</p>)}
          </div>
        ))}
      </div>
    </Modal>
  );
}

function Overview({ datasetId, detail }: { datasetId: string; detail: DatasetDetail }) {
  const [offset, setOffset] = useState(0);
  const profile = useAsync(() => api.datasetProfile(datasetId, offset, PREVIEW_LIMIT), [datasetId, offset]);
  const d = detail.dataset;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Rows" value={formatNumber(d.row_count)} />
        <StatCard label="Columns" value={d.column_count} />
        <StatCard label="Size" value={formatBytes(d.size_bytes)} />
        <StatCard label="Encoding" value={d.encoding} hint={`delimiter “${d.delimiter === "\t" ? "tab" : d.delimiter}”`} />
      </div>
      {d.status !== "active" ? (
        <Banner kind="warning" title="The file is no longer stored">
          This dataset was {d.status} on {formatDateTime(d.file_removed_at)}. Its scan and decision history remains available.
        </Banner>
      ) : (
        <Async state={profile} label="Reading the file…">
          {(p) => (
            <>
              {p.warnings.map((w) => <Banner key={w} kind="warning">{w}</Banner>)}
              <Card title="Columns"><ColumnProfileTable columns={p.columns} /></Card>
              <Card title="Data preview">
                <PreviewTable preview={p.preview} />
                <Pagination total={p.row_count} offset={offset} limit={PREVIEW_LIMIT} onChange={setOffset} />
              </Card>
            </>
          )}
        </Async>
      )}
    </div>
  );
}

export default function DatasetDetailPage() {
  const { datasetId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const state = useAsync(() => api.getDataset(datasetId), [datasetId]);
  const [tab, setTab] = useState<Tab>("overview");
  const [scanning, setScanning] = useState(false);
  const [planOpen, setPlanOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const columnsState = useAsync(() => api.datasetProfile(datasetId, 0, 1).then((p) => p.columns.map((c) => c.name)).catch(() => [] as string[]), [datasetId]);

  const scan = async () => {
    setScanning(true);
    try {
      const r = await api.runScan(datasetId);
      navigate(`/scans/${r.scan_id}`);
    } catch (e) {
      toast.error("Scan failed", toApiError(e).message);
      setScanning(false);
    }
  };

  const remove = async () => {
    setDeleting(true);
    try {
      await api.deleteDataset(datasetId);
      toast.success("Dataset deleted");
      navigate("/datasets");
    } catch (e) {
      toast.error("Could not delete", toApiError(e).message);
      setDeleting(false);
    }
  };

  return (
    <Async state={state} label="Loading dataset…">
      {(detail) => {
        const d = detail.dataset;
        const active = d.status === "active";
        return (
          <>
            <PageHeader back={{ to: "/datasets", label: "All datasets" }}
                        title={<span className="break-all">{d.filename}</span>}
                        subtitle={<>Uploaded {formatDateTime(d.uploaded_at)} · <StatusBadge status={d.status} /> · ID {shortId(d.dataset_id)}</>}
                        actions={active ? <>
                          <Button onClick={scan} loading={scanning}>Run scan</Button>
                          <Button variant="secondary" onClick={() => setPlanOpen(true)}>Create repair plan</Button>
                          <Button variant="ghost" onClick={() => setConfirmDelete(true)}>Delete</Button>
                        </> : undefined} />
            <Tabs<Tab> active={tab} onChange={setTab} tabs={[
              { key: "overview", label: "Overview" },
              { key: "scans", label: "Scans", count: detail.scans.length },
              { key: "plans", label: "Repair plans", count: detail.plans.length },
            ]} />

            {tab === "overview" && <Overview datasetId={datasetId} detail={detail} />}

            {tab === "scans" && (detail.scans.length === 0 ? (
              <EmptyState title="No scans yet" action={active ? <Button onClick={scan} loading={scanning}>Run the first scan</Button> : undefined}>
                A scan looks for missing values, duplicates, inconsistent formats, invalid values and outliers.
              </EmptyState>
            ) : (
              <TableWrap>
                <thead><tr>{["Started", "Status", "Issues", "Scan"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {detail.scans.map((s) => (
                    <tr key={s.scan_id}>
                      <td className={td}>{formatDateTime(s.started_at)}</td>
                      <td className={td}><StatusBadge status={s.status} /></td>
                      <td className={`${td} tabular-nums`}>{s.status === "completed" ? formatNumber(s.issue_total) : "—"}</td>
                      <td className={td}><Link className="text-indigo-700 hover:underline dark:text-indigo-300" to={`/scans/${s.scan_id}`}>View {shortId(s.scan_id)}</Link></td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            ))}

            {tab === "plans" && (detail.plans.length === 0 ? (
              <EmptyState title="No repair plans yet" action={active ? <Button onClick={() => setPlanOpen(true)}>Create a repair plan</Button> : undefined}>
                A repair plan turns detected issues into proposals you can approve or reject.
              </EmptyState>
            ) : (
              <TableWrap>
                <thead><tr>{["Created", "Status", "Proposals", "Approved", "Rejected", "Pending", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {detail.plans.map((p) => (
                    <tr key={p.plan_id}>
                      <td className={td}>{formatDateTime(p.created_at)}</td>
                      <td className={td}><StatusBadge status={p.status} /></td>
                      <td className={`${td} tabular-nums`}>{p.proposal_count}</td>
                      <td className={`${td} tabular-nums`}>{p.status_counts.approved}</td>
                      <td className={`${td} tabular-nums`}>{p.status_counts.rejected}</td>
                      <td className={`${td} tabular-nums`}>{p.status_counts.pending}</td>
                      <td className={td}><Link className="text-indigo-700 hover:underline dark:text-indigo-300" to={`/plans/${p.plan_id}`}>{p.status === "active" ? "Review" : "View"}</Link></td>
                    </tr>
                  ))}
                </tbody>
              </TableWrap>
            ))}

            {active && <CreatePlanDialog datasetId={datasetId} columns={columnsState.data ?? []} open={planOpen} onClose={() => setPlanOpen(false)} />}
            <ConfirmDialog open={confirmDelete} title="Delete this dataset?" confirmLabel="Delete" danger busy={deleting} onConfirm={remove} onCancel={() => setConfirmDelete(false)}>
              <p>The file and any cleaned copies are removed. Scan results, decisions and the audit trail are kept.</p>
            </ConfirmDialog>
            {!active && <Badge tone="neutral">Read-only</Badge>}
          </>
        );
      }}
    </Async>
  );
}
