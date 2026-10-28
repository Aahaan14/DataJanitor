import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../services/api";
import { toApiError, useAsync } from "../hooks/useAsync";
import type { DatasetInfo } from "../types/api";
import { ConfirmDialog } from "../components/Modal";
import { useToast } from "../components/Toast";
import { Async, Button, EmptyState, LinkButton, PageHeader, Pagination, SelectFilter, StatusBadge, TableWrap, td, th } from "../components/ui";
import { formatBytes, formatDateTime, formatNumber } from "../utils/format";

const LIMIT = 15;

export default function DatasetsPage() {
  const toast = useToast();
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [toDelete, setToDelete] = useState<DatasetInfo | null>(null);
  const [deleting, setDeleting] = useState(false);
  const state = useAsync(() => api.listDatasets({ status, offset, limit: LIMIT }), [status, offset]);

  const remove = async () => {
    if (!toDelete) return;
    setDeleting(true);
    try {
      await api.deleteDataset(toDelete.dataset_id);
      toast.success("Dataset deleted", "The file was removed. Its history is kept.");
      setToDelete(null);
      state.reload();
    } catch (e) {
      toast.error("Could not delete", toApiError(e).message);
    } finally {
      setDeleting(false);
    }
  };

  return (
    <>
      <PageHeader title="Datasets" subtitle="Every file you have uploaded."
                  actions={<LinkButton to="/upload" variant="primary">Upload a CSV</LinkButton>} />
      <div className="mb-4">
        <SelectFilter label="Status" value={status} onChange={(v) => { setStatus(v); setOffset(0); }}
                      options={[{ value: "active", label: "Active" }, { value: "deleted", label: "Deleted" }, { value: "expired", label: "Expired" }]} />
      </div>
      <Async state={state} label="Loading datasets…">
        {(page) => page.datasets.length === 0 ? (
          <EmptyState title={status ? "No datasets with this status" : "No datasets yet"}
                      action={!status ? <LinkButton to="/upload" variant="primary">Upload a CSV</LinkButton> : undefined}>
            {status ? "Try a different filter." : "Upload a CSV to get started."}
          </EmptyState>
        ) : (
          <>
            <TableWrap>
              <thead><tr>{["File", "Size", "Rows × columns", "Status", "Uploaded", ""].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {page.datasets.map((d) => (
                  <tr key={d.dataset_id}>
                    <td className={`${td} max-w-xs break-all font-medium`}>
                      <Link to={`/datasets/${d.dataset_id}`} className="text-indigo-700 hover:underline dark:text-indigo-300">{d.filename}</Link>
                    </td>
                    <td className={td}>{formatBytes(d.size_bytes)}</td>
                    <td className={`${td} tabular-nums`}>{formatNumber(d.row_count)} × {d.column_count}</td>
                    <td className={td}><StatusBadge status={d.status} /></td>
                    <td className={`${td} whitespace-nowrap`}>{formatDateTime(d.uploaded_at)}</td>
                    <td className={`${td} text-right`}>
                      {d.status === "active" && <Button size="sm" variant="ghost" onClick={() => setToDelete(d)} aria-label={`Delete ${d.filename}`}>Delete</Button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </TableWrap>
            <Pagination total={page.total} offset={offset} limit={LIMIT} onChange={setOffset} />
          </>
        )}
      </Async>
      <ConfirmDialog open={toDelete !== null} title="Delete this dataset?" confirmLabel="Delete" danger busy={deleting}
                     onConfirm={remove} onCancel={() => setToDelete(null)}>
        <p><strong className="break-all">{toDelete?.filename}</strong> and any cleaned copies will be removed from disk.</p>
        <p>Scan results, decisions and the audit trail are kept. Open repair plans for it become stale.</p>
      </ConfirmDialog>
    </>
  );
}
