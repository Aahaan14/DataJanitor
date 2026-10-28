import { type ButtonHTMLAttributes, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { ApiError } from "../services/api";
import type { AsyncState } from "../hooks/useAsync";
import { statusTone, humanize, type Tone } from "../utils/labels";

// ── Buttons ─────────────────────────────────────────────────────────────────
type Variant = "primary" | "secondary" | "danger" | "ghost";
const VARIANT: Record<Variant, string> = {
  primary: "bg-indigo-600 text-white hover:bg-indigo-700 disabled:hover:bg-indigo-600",
  secondary: "border border-slate-300 bg-white text-slate-800 hover:bg-slate-50 dark:border-slate-600 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700",
  danger: "bg-red-600 text-white hover:bg-red-700 disabled:hover:bg-red-600",
  ghost: "text-slate-700 hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800",
};

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
}

export function Button({ variant = "primary", size = "md", loading, disabled, className = "", children, ...rest }: ButtonProps) {
  return (
    <button type="button" disabled={disabled || loading} aria-busy={loading || undefined}
            className={`inline-flex items-center justify-center gap-2 rounded-lg font-medium transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-indigo-500 disabled:cursor-not-allowed disabled:opacity-50 ${size === "sm" ? "px-2.5 py-1 text-xs" : "px-3.5 py-2 text-sm"} ${VARIANT[variant]} ${className}`}
            {...rest}>
      {loading && <Spinner small />}
      {children}
    </button>
  );
}

export function LinkButton({ to, children, variant = "secondary" }: { to: string; children: ReactNode; variant?: Variant }) {
  return (
    <Link to={to} className={`inline-flex items-center justify-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition ${VARIANT[variant]}`}>
      {children}
    </Link>
  );
}

// ── Layout pieces ───────────────────────────────────────────────────────────
export function Card({ title, actions, children, className = "" }: { title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-700 dark:bg-slate-900 ${className}`}>
      {(title || actions) && (
        <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-100 px-4 py-3 dark:border-slate-800">
          <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions, back }: { title: ReactNode; subtitle?: ReactNode; actions?: ReactNode; back?: { to: string; label: string } }) {
  return (
    <div className="mb-6">
      {back && <Link to={back.to} className="mb-2 inline-block text-sm text-indigo-600 hover:underline dark:text-indigo-400">← {back.label}</Link>}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="break-words text-2xl font-bold tracking-tight">{title}</h1>
          {subtitle && <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">{subtitle}</p>}
        </div>
        {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
      </div>
    </div>
  );
}

const TONE: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300",
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300",
  red: "bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300",
  blue: "bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300",
  indigo: "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-300",
};

export function Badge({ tone = "neutral", children, title }: { tone?: Tone; children: ReactNode; title?: string }) {
  return <span title={title} className={`inline-flex items-center whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${TONE[tone]}`}>{children}</span>;
}

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={statusTone(status)}>{humanize(status)}</Badge>;
}

export function StatCard({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-900">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">{label}</p>
      <p className={`mt-1 text-2xl font-bold ${tone === "red" ? "text-red-600 dark:text-red-400" : tone === "green" ? "text-emerald-600 dark:text-emerald-400" : ""}`}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
    </div>
  );
}

// ── States: loading / error / empty / banners ───────────────────────────────
export function Spinner({ small }: { small?: boolean }) {
  return (
    <span role="status" aria-label="Loading"
          className={`inline-block animate-spin rounded-full border-2 border-current border-t-transparent ${small ? "h-3.5 w-3.5" : "h-6 w-6"}`} />
  );
}

export function LoadingBlock({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-3 py-12 text-slate-500 dark:text-slate-400" aria-live="polite">
      <Spinner /> <span className="text-sm">{label}</span>
    </div>
  );
}

export function ErrorState({ error, onRetry, title = "Something went wrong" }: { error: ApiError; onRetry?: () => void; title?: string }) {
  const notFound = error.status === 404 || error.status === 410;
  return (
    <div role="alert" className="rounded-xl border border-red-200 bg-red-50 p-6 text-center dark:border-red-900 dark:bg-red-950/40">
      <p className="font-semibold text-red-900 dark:text-red-200">{notFound ? "Not available" : title}</p>
      <p className="mx-auto mt-1 max-w-xl text-sm text-red-800 dark:text-red-300">{error.message}</p>
      {error.code !== "network_error" && error.code !== "unknown_error" && (
        <p className="mt-1 text-xs text-red-700/70 dark:text-red-400/70">Error code: {error.code}</p>
      )}
      {onRetry && !notFound && <div className="mt-4"><Button variant="secondary" onClick={onRetry}>Try again</Button></div>}
    </div>
  );
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center dark:border-slate-700">
      <p className="font-semibold">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-md text-sm text-slate-600 dark:text-slate-400">{children}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}

const BANNER: Record<"info" | "success" | "warning" | "error", string> = {
  info: "border-indigo-200 bg-indigo-50 text-indigo-900 dark:border-indigo-900 dark:bg-indigo-950/50 dark:text-indigo-200",
  success: "border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200",
  warning: "border-amber-200 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200",
  error: "border-red-200 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200",
};

export function Banner({ kind = "info", title, children }: { kind?: keyof typeof BANNER; title?: string; children?: ReactNode }) {
  return (
    <div role={kind === "error" ? "alert" : "status"} className={`rounded-lg border px-4 py-3 text-sm ${BANNER[kind]}`}>
      {title && <p className="font-semibold">{title}</p>}
      {children && <div className={title ? "mt-0.5" : ""}>{children}</div>}
    </div>
  );
}

/**
 * Renders loading / error / content for an AsyncState so pages stay declarative.
 * Once data exists the SAME wrapper element is always rendered, so a refresh never
 * remounts the content (which would lose typed values, selections and focus).
 * With `dim`, stale content is greyed while it refreshes (used for filtered lists).
 */
export function Async<T>({ state, children, label, dim = true }: { state: AsyncState<T>; children: (data: T) => ReactNode; label?: string; dim?: boolean }) {
  if (state.loading && state.data === undefined) return <LoadingBlock label={label} />;
  if (state.error) return <ErrorState error={state.error} onRetry={state.reload} />;
  if (state.data === undefined) return null;
  const refreshing = state.loading;
  return (
    <div aria-busy={refreshing || undefined} className={refreshing && dim ? "opacity-60 transition-opacity" : undefined}>
      {children(state.data)}
    </div>
  );
}

// ── Tables, paging, tabs, form bits ─────────────────────────────────────────
export function TableWrap({ children }: { children: ReactNode }) {
  return <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-700"><table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-700">{children}</table></div>;
}
export const th = "whitespace-nowrap bg-slate-50 px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-800 dark:text-slate-400";
export const td = "px-3 py-2 align-top";

export function Pagination({ total, offset, limit, onChange }: { total: number; offset: number; limit: number; onChange: (offset: number) => void }) {
  if (total <= limit) return null;
  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);
  return (
    <nav aria-label="Pagination" className="mt-3 flex items-center justify-between gap-3 text-sm">
      <span className="text-slate-600 dark:text-slate-400">
        {offset + 1}–{Math.min(offset + limit, total)} of {total}
      </span>
      <div className="flex items-center gap-2">
        <Button size="sm" variant="secondary" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Previous</Button>
        <span aria-live="polite">Page {page} of {pages}</span>
        <Button size="sm" variant="secondary" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>Next</Button>
      </div>
    </nav>
  );
}

export function Tabs<K extends string>({ tabs, active, onChange }: { tabs: { key: K; label: string; count?: number }[]; active: K; onChange: (k: K) => void }) {
  return (
    <div role="tablist" className="mb-4 flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-slate-700">
      {tabs.map((t) => (
        <button key={t.key} role="tab" aria-selected={active === t.key} onClick={() => onChange(t.key)}
                className={`whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium ${active === t.key ? "border-indigo-600 text-indigo-700 dark:border-indigo-400 dark:text-indigo-300" : "border-transparent text-slate-600 hover:text-slate-900 dark:text-slate-400 dark:hover:text-slate-100"}`}>
          {t.label}{t.count !== undefined && <span className="ml-1.5 text-xs text-slate-400">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}

export const inputClass =
  "w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-sm shadow-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-60 dark:border-slate-600 dark:bg-slate-800";

export function SelectFilter({ label, value, onChange, options }: { label: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <label className="flex flex-col gap-1 text-xs font-medium text-slate-600 dark:text-slate-400">
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)} className={inputClass + " min-w-36"}>
        <option value="">All</option>
        {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>
    </label>
  );
}

export function BreakdownBars({ data, labelFor = humanize, tone = "indigo" }: { data: Record<string, number>; labelFor?: (k: string) => string; tone?: "indigo" | "red" | "amber" }) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  const max = Math.max(1, ...entries.map(([, n]) => n));
  if (!entries.length) return <p className="text-sm text-slate-500">None</p>;
  const bar = tone === "red" ? "bg-red-500" : tone === "amber" ? "bg-amber-500" : "bg-indigo-500";
  return (
    <ul className="space-y-2">
      {entries.map(([k, n]) => (
        <li key={k} className="text-sm">
          <div className="mb-0.5 flex justify-between gap-2"><span className="truncate">{labelFor(k)}</span><span className="font-medium tabular-nums">{n}</span></div>
          <div className="h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800" role="presentation">
            <div className={`h-full rounded-full ${bar}`} style={{ width: `${(n / max) * 100}%` }} />
          </div>
        </li>
      ))}
    </ul>
  );
}

/** A cell value shown verbatim, with visible markers for empty / whitespace-padded text. */
export function Cell({ value }: { value: string | null | undefined }) {
  if (value === null || value === undefined) return <span className="italic text-slate-400">empty</span>;
  if (value === "") return <span className="italic text-slate-400">(blank)</span>;
  const padded = value !== value.trim();
  return <span className={`break-words font-mono text-[13px] ${padded ? "rounded bg-amber-100 px-0.5 dark:bg-amber-950" : ""}`} title={padded ? "Contains leading or trailing spaces" : undefined}>{padded ? `“${value}”` : value}</span>;
}
