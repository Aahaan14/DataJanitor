import type { ColumnProfile, DatasetPreview } from "../types/api";
import { formatNumber } from "../utils/format";
import { Badge, Cell, TableWrap, td, th } from "./ui";

export function PreviewTable({ preview }: { preview: DatasetPreview }) {
  if (!preview.rows.length) return <p className="text-sm text-slate-500">No rows in this range.</p>;
  return (
    <TableWrap>
      <thead>
        <tr>
          <th className={th}>Row</th>
          {preview.columns.map((c) => <th key={c} className={th}>{c || <em>(unnamed)</em>}</th>)}
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
        {preview.rows.map((r) => (
          <tr key={r.row_number}>
            <td className={`${td} tabular-nums text-slate-400`}>{r.row_number}</td>
            {preview.columns.map((c) => <td key={c} className={td}><Cell value={r.values[c]} /></td>)}
          </tr>
        ))}
      </tbody>
    </TableWrap>
  );
}

function statSummary(c: ColumnProfile): string {
  const s = c.stats;
  if (s.min !== undefined && s.max !== undefined) return `${s.min} → ${s.max}${s.mean !== undefined && s.mean !== null ? ` (mean ${s.mean})` : ""}`;
  if (s.earliest) return `${s.earliest} → ${s.latest}`;
  if (s.top_value !== undefined && s.top_value !== null) return `most common “${s.top_value}” ×${s.top_frequency}`;
  return "—";
}

export function ColumnProfileTable({ columns }: { columns: ColumnProfile[] }) {
  return (
    <TableWrap>
      <thead>
        <tr>
          {["Column", "Type", "Missing", "Unique", "Summary"].map((h) => <th key={h} className={th}>{h}</th>)}
        </tr>
      </thead>
      <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
        {columns.map((c) => (
          <tr key={c.name}>
            <td className={`${td} font-medium`}>{c.name || <em>(unnamed)</em>}</td>
            <td className={td}>
              <Badge tone={c.inferred_type === "mixed" ? "amber" : "indigo"}
                     title={c.parse_ratio !== null ? `${(c.parse_ratio * 100).toFixed(0)}% of values fit` : undefined}>
                {c.inferred_type}
              </Badge>
            </td>
            <td className={`${td} tabular-nums`}>
              {c.missing_count ? <span className="text-amber-700 dark:text-amber-400">{formatNumber(c.missing_count)} ({c.missing_percent}%)</span> : "0"}
            </td>
            <td className={`${td} tabular-nums`}>{formatNumber(c.unique_count)}</td>
            <td className={`${td} text-slate-600 dark:text-slate-400`}>{statSummary(c)}</td>
          </tr>
        ))}
      </tbody>
    </TableWrap>
  );
}
