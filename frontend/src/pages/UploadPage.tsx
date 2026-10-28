import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../services/api";
import { toApiError, useAsync } from "../hooks/useAsync";
import type { UploadResponse } from "../types/api";
import { FileDropzone } from "../components/FileDropzone";
import { ColumnProfileTable, PreviewTable } from "../components/DataTables";
import { useToast } from "../components/Toast";
import { Banner, Button, Card, LinkButton, PageHeader, StatCard } from "../components/ui";
import { formatBytes, formatNumber } from "../utils/format";

export default function UploadPage() {
  const toast = useToast();
  const navigate = useNavigate();
  const config = useAsync(() => api.config(), []);
  const maxMb = config.data?.max_upload_size_mb ?? 10;

  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(null);
  const [scanning, setScanning] = useState(false);

  const choose = (f: File | null) => {
    setResult(null);
    if (f && !f.name.toLowerCase().endsWith(".csv")) {
      setFile(null); setProblem("Only .csv files are accepted."); return;
    }
    if (f && f.size > maxMb * 1024 * 1024) {
      setFile(null); setProblem(`This file is ${formatBytes(f.size)}; the limit is ${maxMb} MB.`); return;
    }
    setProblem(null);
    setFile(f);
  };

  const upload = async () => {
    if (!file) return;
    setProblem(null);
    setProgress(0);
    try {
      const res = await api.uploadDataset(file, setProgress);
      setResult(res);
      setFile(null);
      toast.success("Upload complete", `${res.filename}: ${formatNumber(res.row_count)} rows analysed.`);
    } catch (e) {
      setProblem(toApiError(e).message);
    } finally {
      setProgress(null);
    }
  };

  const scanNow = async () => {
    if (!result) return;
    setScanning(true);
    try {
      const scan = await api.runScan(result.dataset_id);
      navigate(`/scans/${scan.scan_id}`);
    } catch (e) {
      toast.error("Scan failed", toApiError(e).message);
      setScanning(false);
    }
  };

  const uploading = progress !== null;
  return (
    <>
      <PageHeader title="Upload a dataset" subtitle="Your original file is stored untouched. Every change is a proposal you approve." />
      <div className="space-y-4">
        <FileDropzone file={file} onFile={choose} disabled={uploading} maxMb={maxMb} />
        {problem && <Banner kind="error" title="This file cannot be used">{problem}</Banner>}
        {uploading && (
          <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((progress ?? 0) * 100)} aria-label="Upload progress">
            <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
              <div className="h-full bg-indigo-600 transition-all" style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} />
            </div>
            <p className="mt-1 text-xs text-slate-500">{progress! >= 1 ? "Analysing the file…" : `Uploading ${Math.round((progress ?? 0) * 100)}%`}</p>
          </div>
        )}
        <div className="flex justify-end">
          <Button onClick={upload} disabled={!file} loading={uploading}>Upload &amp; analyse</Button>
        </div>
      </div>

      {result && (
        <div className="mt-8 space-y-4" aria-live="polite">
          <Banner kind="success" title={`“${result.filename}” was uploaded`}>
            It is saved as an untouched original. Next, scan it for data-quality issues.
          </Banner>
          {result.warnings.map((w) => <Banner key={w} kind="warning">{w}</Banner>)}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <StatCard label="Rows" value={formatNumber(result.row_count)} />
            <StatCard label="Columns" value={result.column_count} />
            <StatCard label="Size" value={formatBytes(result.size_bytes)} />
            <StatCard label="Encoding" value={result.encoding} hint={`delimiter “${result.delimiter === "\t" ? "tab" : result.delimiter}”`} />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button onClick={scanNow} loading={scanning}>Run a scan now</Button>
            <LinkButton to={`/datasets/${result.dataset_id}`}>Open dataset</LinkButton>
          </div>
          <Card title="Columns"><ColumnProfileTable columns={result.columns} /></Card>
          <Card title={`Preview (first ${result.preview.preview_row_count} rows)`}><PreviewTable preview={result.preview} /></Card>
          <p className="text-sm text-slate-500"><Link to="/datasets" className="text-indigo-600 hover:underline dark:text-indigo-400">See all datasets</Link></p>
        </div>
      )}
    </>
  );
}
