export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat().format(n);
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatRelative(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "—";
  const seconds = Math.round((now.getTime() - new Date(iso).getTime()) / 1000);
  if (Number.isNaN(seconds)) return "—";
  if (seconds < 45) return "just now";
  if (seconds < 3600) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h ago`;
  return `${Math.round(seconds / 86400)} d ago`;
}

export function formatPercent(fraction: number | null | undefined, digits = 0): string {
  return fraction === null || fraction === undefined ? "—" : `${(fraction * 100).toFixed(digits)}%`;
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : "—";
}

export function sum(record: Record<string, number> | undefined): number {
  return record ? Object.values(record).reduce((a, b) => a + b, 0) : 0;
}
