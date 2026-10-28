import { api } from "../services/api";
import { useAsync } from "../hooks/useAsync";
import { useTheme, type Theme } from "../hooks/useTheme";
import { Async, Badge, Banner, Card, PageHeader, inputClass } from "../components/ui";

const DOCS_URL = `${(import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "")}/docs`;

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-slate-100 py-2 text-sm last:border-0 dark:border-slate-800">
      <dt className="text-slate-600 dark:text-slate-400">{label}</dt>
      <dd className="text-right font-medium tabular-nums">{value}</dd>
    </div>
  );
}

export default function SettingsPage() {
  const config = useAsync(() => api.config(), []);
  const [theme, setTheme] = useTheme();

  return (
    <>
      <PageHeader title="Settings" subtitle="Server limits are set in the backend .env file; this page shows what is currently in effect." />
      <Async state={config} label="Loading settings…">
        {(c) => (
          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Upload limits">
              <dl>
                <Row label="Maximum file size" value={`${c.max_upload_size_mb} MB`} />
                <Row label="Maximum rows" value={c.max_rows.toLocaleString()} />
                <Row label="Maximum columns" value={c.max_columns} />
                <Row label="Preview rows after upload" value={c.preview_rows} />
                <Row label="Issues stored per scan" value={c.max_issues_returned.toLocaleString()} />
                <Row label="Proposals per plan" value={c.max_proposals_per_plan.toLocaleString()} />
              </dl>
            </Card>

            <Card title="File retention">
              <dl>
                <Row label="Uploaded files kept for" value={`${c.upload_retention_days} days`} />
                <Row label="Cleaned files kept for" value={`${c.cleaned_retention_days} days`} />
                <Row label="Unrecorded files removed after" value={`${c.orphan_grace_hours} hours`} />
              </dl>
              <p className="mt-3 text-xs text-slate-500">Cleanup runs with <code>python -m app.maintenance cleanup</code>. Scan results, decisions and the audit trail are never deleted by it.</p>
            </Card>

            <Card title="Email reports" actions={<Badge tone={c.email.configured ? "green" : c.email.enabled ? "amber" : "neutral"}>{c.email.configured ? "Configured" : c.email.enabled ? "Needs attention" : "Off"}</Badge>}>
              {c.email.configured ? (
                <dl>
                  <Row label="SMTP server" value={c.email.smtp_host} />
                  <Row label="Security" value={c.email.smtp_security} />
                  <Row label="Sending to" value={c.email.recipient_masked} />
                  <Row label="File and column names in reports" value={c.email.include_names ? "Included" : "Hidden"} />
                </dl>
              ) : (
                <div className="space-y-3 text-sm">
                  {c.email.problem && <Banner kind={c.email.enabled ? "warning" : "info"}>{c.email.problem}</Banner>}
                  <p>To receive a report after every scan and cleaning run, set these in the backend <code>.env</code> and restart it:</p>
                  <pre className="overflow-x-auto rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-800">{`EMAIL_REPORTS_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_SECURITY=starttls
SMTP_USER=you@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_FROM=you@gmail.com
REPORT_RECIPIENT=you@example.com`}</pre>
                </div>
              )}
              <p className="mt-3 text-xs text-slate-500">Passwords stay on the server and are never sent to this page. Scan emails contain summaries; cleaning emails attach the generated cleaned CSV.</p>
            </Card>

            <div className="space-y-6">
              <Card title="Appearance">
                <label className="block text-sm font-medium" htmlFor="theme">Theme
                  <select id="theme" value={theme} onChange={(e) => setTheme(e.target.value as Theme)} className={`${inputClass} mt-1`}>
                    <option value="system">Match my system</option>
                    <option value="light">Light</option>
                    <option value="dark">Dark</option>
                  </select>
                </label>
              </Card>
              <Card title="About">
                <dl>
                  <Row label="Application" value={`${c.app_name} ${c.version}`} />
                  <Row label="Environment" value={c.environment} />
                  <Row label="API documentation" value={<a className="text-indigo-700 underline dark:text-indigo-300" href={DOCS_URL} target="_blank" rel="noreferrer">Open /docs</a>} />
                </dl>
              </Card>
            </div>
          </div>
        )}
      </Async>
    </>
  );
}
