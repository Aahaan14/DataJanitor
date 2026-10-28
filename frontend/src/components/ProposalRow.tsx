import { useState } from "react";
import type { RepairProposal } from "../types/api";
import { actionLabel, issueLabel } from "../utils/labels";
import { formatDateTime, shortId } from "../utils/format";
import { Badge, Button, Cell, StatusBadge, inputClass, td } from "./ui";

interface Props {
  proposal: RepairProposal;
  /** false when the plan is stale/superseded: decisions are closed. */
  editable: boolean;
  onDecide: (p: RepairProposal, decision: "approve" | "reject", chosenValue?: string) => Promise<void>;
}

const uniq = (xs: (string | null)[]): string[] => [...new Set(xs.filter((x): x is string => x !== null))];

/** What the change would look like: original → result. */
function Change({ p }: { p: RepairProposal }) {
  if (p.action === "delete_row")
    return <div><Badge tone="red">Delete row</Badge><div className="mt-1 text-xs text-slate-500"><Cell value={p.original_value} /></div></div>;
  const result = p.action === "clear_value"
    ? <span className="italic text-slate-500">(empty the cell)</span>
    : p.proposed_value !== null ? <Cell value={p.proposed_value} /> : <span className="italic text-amber-700 dark:text-amber-400">choose a value →</span>;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <Cell value={p.original_value} /><span aria-label="becomes" className="text-slate-400">→</span>{result}
    </div>
  );
}

export function ProposalRow({ proposal: p, editable, onDecide }: Props) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const options = uniq([p.proposed_value, ...p.alternatives]);
  const needsChoice = p.action === "replace_value" && p.proposed_value === null;
  const showSelect = options.length > 1 || (needsChoice && options.length > 0);
  const [choice, setChoice] = useState(p.proposed_value ?? "");
  const [custom, setCustom] = useState("");

  const chosen = (): string | undefined => {
    if (showSelect && choice) return choice;
    if (p.allow_custom_value && custom.trim()) return custom.trim();
    return undefined;
  };
  const canApprove = editable && (!needsChoice || chosen() !== undefined);
  const approveLabel =
    p.action === "delete_row" ? "Approve deletion"
    : p.action === "clear_value" ? (custom.trim() ? "Approve correction" : "Approve: empty cell")
    : needsChoice ? "Approve choice" : "Approve";

  const run = async (decision: "approve" | "reject") => {
    setBusy(decision);
    try { await onDecide(p, decision, decision === "approve" ? chosen() : undefined); }
    finally { setBusy(null); }
  };

  return (
    <>
      <tr className={p.status === "approved" ? "bg-emerald-50/50 dark:bg-emerald-950/20" : p.status === "rejected" ? "bg-slate-50 opacity-80 dark:bg-slate-900/60" : ""}>
        <td className={`${td} tabular-nums text-slate-500`}>{p.row_number ?? "—"}</td>
        <td className={td}>{p.column ?? <span className="text-slate-400">whole row</span>}</td>
        <td className={td}>
          <div className="whitespace-nowrap">{issueLabel(p.issue_type)}</div>
          <div className="mt-1 flex flex-wrap gap-1">
            <Badge tone={p.classification === "safe" ? "green" : "amber"} title={p.classification === "safe" ? "Deterministic, meaning-preserving" : "Needs your judgement"}>{p.classification}</Badge>
            <Badge tone="neutral" title="Confidence">{p.confidence}</Badge>
          </div>
        </td>
        <td className={`${td} min-w-56`}>
          <Change p={p} />
          {p.status === "approved" && p.action !== "delete_row" && (
            <p className="mt-1 text-xs text-emerald-800 dark:text-emerald-300">Will be applied as: {p.approved_value === null ? "(empty)" : <Cell value={p.approved_value} />}</p>
          )}
        </td>
        <td className={td}><StatusBadge status={p.status} /></td>
        <td className={`${td} min-w-64`}>
          <div className="space-y-2">
            {editable && (showSelect || p.allow_custom_value) && (
              <div className="space-y-1.5">
                {showSelect && (
                  <select aria-label={`Value for row ${p.row_number} ${p.column ?? ""}`} className={inputClass} value={choice} onChange={(e) => setChoice(e.target.value)}>
                    {needsChoice && <option value="">Choose a value…</option>}
                    {options.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                )}
                {p.allow_custom_value && (
                  <input aria-label={`Corrected value for row ${p.row_number} ${p.column ?? ""}`} className={inputClass} value={custom}
                         onChange={(e) => setCustom(e.target.value)} placeholder="Corrected value (optional)" />
                )}
              </div>
            )}
            <div className="flex flex-wrap gap-1.5">
              <Button size="sm" onClick={() => run("approve")} loading={busy === "approve"} disabled={!canApprove || busy !== null}
                      aria-label={`${approveLabel} (row ${p.row_number ?? ""} ${p.column ?? ""})`}>{approveLabel}</Button>
              <Button size="sm" variant="secondary" onClick={() => run("reject")} loading={busy === "reject"} disabled={!editable || busy !== null || p.status === "rejected"}
                      aria-label={`Reject (row ${p.row_number ?? ""} ${p.column ?? ""})`}>Reject</Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? "Hide" : "Details"}</Button>
            </div>
            {p.conflicts_with.length > 0 && (
              <p className="text-xs text-amber-700 dark:text-amber-400">Conflicts with {p.conflicts_with.length} other proposal(s) — only one can be approved.</p>
            )}
          </div>
        </td>
      </tr>
      {open && (
        <tr className="bg-slate-50 dark:bg-slate-900/60">
          <td colSpan={6} className="px-4 py-3 text-sm">
            <p><span className="font-semibold">Why: </span>{p.reason}</p>
            <p className="mt-1 text-xs text-slate-500">Proposal {shortId(p.proposal_id)} · {actionLabel(p.action)} · from issue {p.issue_id}</p>
            {p.history.length > 0 && (
              <ul className="mt-2 space-y-0.5 text-xs text-slate-600 dark:text-slate-400" aria-label="Decision history">
                {p.history.map((h) => (
                  <li key={h.decided_at + h.decision}>{formatDateTime(h.decided_at)} — {h.decision}d{h.chosen_value !== null ? ` with “${h.chosen_value}”` : ""}</li>
                ))}
              </ul>
            )}
          </td>
        </tr>
      )}
    </>
  );
}
