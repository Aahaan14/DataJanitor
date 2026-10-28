import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../services/api";
import { toApiError, useAsync } from "../hooks/useAsync";
import type { Classification, IssueType, ProposalStatus, RepairProposal } from "../types/api";
import { ConfirmDialog } from "../components/Modal";
import { ProposalRow } from "../components/ProposalRow";
import { useToast } from "../components/Toast";
import {
  Async, Banner, Button, Card, EmptyState, PageHeader, Pagination, SelectFilter, StatCard, StatusBadge,
  TableWrap, th,
} from "../components/ui";
import { ISSUE_TYPES, humanize, issueLabel } from "../utils/labels";
import { formatDateTime, formatNumber, shortId } from "../utils/format";

const LIMIT = 25;

export default function PlanReviewPage() {
  const { planId = "" } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const [version, setVersion] = useState(0);
  const bump = () => setVersion((v) => v + 1);

  const [status, setStatus] = useState("");
  const [classification, setClassification] = useState("");
  const [issueType, setIssueType] = useState("");
  const [offset, setOffset] = useState(0);
  const [confirmSafe, setConfirmSafe] = useState(false);
  const [confirmApply, setConfirmApply] = useState(false);
  const [busy, setBusy] = useState(false);

  const plan = useAsync(() => api.getPlan(planId), [planId, version]);
  const proposals = useAsync(
    () => api.listProposals(planId, {
      status: (status || undefined) as ProposalStatus | undefined,
      classification: (classification || undefined) as Classification | undefined,
      issue_type: (issueType || undefined) as IssueType | undefined,
      offset, limit: LIMIT,
    }),
    [planId, status, classification, issueType, offset]);
  const pendingSafe = useAsync(
    () => api.listProposals(planId, { status: "pending", classification: "safe", limit: 1 }).then((p) => p.total),
    [planId, version]);
  const cleaned = useAsync(() => api.planCleaned(planId), [planId, version]);

  const decide = async (p: RepairProposal, decision: "approve" | "reject", chosenValue?: string) => {
    try {
      const updated = await api.decide(planId, p.proposal_id, decision, chosenValue);
      proposals.setData((prev) => prev && { ...prev, proposals: prev.proposals.map((x) => (x.proposal_id === updated.proposal_id ? updated : x)) });
      bump();
    } catch (e) {
      const err = toApiError(e);
      toast.error(err.code === "conflicting_proposal" ? "Conflicting proposal" : "Could not save the decision", err.message);
      if (err.status === 409 && err.code !== "conflicting_proposal") { bump(); proposals.reload(); }
    }
  };

  const approveSafe = async () => {
    setBusy(true);
    try {
      const r = await api.approveSafe(planId);
      toast.success(`${r.approved_count} safe proposal(s) approved`,
        r.skipped.length ? `${r.skipped.length} skipped because they conflict with another approved change.` : undefined);
      setConfirmSafe(false);
      bump(); proposals.reload();
    } catch (e) {
      toast.error("Could not approve", toApiError(e).message);
    } finally { setBusy(false); }
  };

  const apply = async () => {
    setBusy(true);
    try {
      const run = await api.applyPlan(planId);
      toast.success("Cleaned copy created", `${run.applied_count} repair(s) applied to a separate copy.`);
      navigate(`/cleaned/${run.cleaned_id}`);
    } catch (e) {
      toast.error("Could not apply the repairs", toApiError(e).message);
      setBusy(false); setConfirmApply(false);
    }
  };

  const resetPaging = <T,>(set: (v: T) => void) => (v: T) => { set(v); setOffset(0); };

  return (
    <Async state={plan} label="Loading repair plan…" dim={false}>
      {(p) => {
        const editable = p.status === "active";
        const counts = p.status_counts;
        const safePending = pendingSafe.data ?? 0;
        return (
          <>
            <PageHeader back={{ to: `/datasets/${p.dataset_id}`, label: "Dataset" }} title="Review repairs"
                        subtitle={<>Plan {shortId(p.plan_id)} · created {formatDateTime(p.created_at)} · <StatusBadge status={p.status} /></>}
                        actions={editable ? <>
                          <Button variant="secondary" onClick={() => setConfirmSafe(true)} disabled={safePending === 0}>Approve all safe ({safePending})</Button>
                          <Button onClick={() => setConfirmApply(true)} disabled={counts.approved === 0}>Apply {counts.approved} approved repair(s)</Button>
                        </> : undefined} />

            {!editable && (
              <div className="mb-4"><Banner kind="warning" title={p.status === "stale" ? "This plan is out of date" : "A newer plan replaced this one"}>
                {p.status === "stale" ? "The dataset file changed or was removed since this plan was made, so decisions are closed. "
                  : "Decisions on this plan are closed. "}
                <Link className="font-medium underline" to={`/datasets/${p.dataset_id}`}>Create a new plan</Link> to continue.
              </Banner></div>
            )}
            {p.truncated && <div className="mb-4"><Banner kind="warning" title="Large plan">Only the first proposals are included. Apply these, then create a new plan for the rest.</Banner></div>}

            <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-5">
              <StatCard label="Proposals" value={formatNumber(p.proposal_count)} hint={`${p.safe_count} safe · ${p.ambiguous_count} need judgement`} />
              <StatCard label="Approved" value={counts.approved} tone="green" />
              <StatCard label="Rejected" value={counts.rejected} />
              <StatCard label="Undecided" value={counts.pending} />
              <StatCard label="Rule violations" value={p.validation.ran ? p.validation.violation_count : "—"} hint={p.validation.ran ? `${p.validation.rule_count} rule(s) checked` : "no rules used"} />
            </div>

            <Card title="Proposals" className="mb-6">
              <div className="mb-4 flex flex-wrap gap-3">
                <SelectFilter label="Status" value={status} onChange={resetPaging(setStatus)}
                              options={["pending", "approved", "rejected"].map((v) => ({ value: v, label: humanize(v) }))} />
                <SelectFilter label="Kind" value={classification} onChange={resetPaging(setClassification)}
                              options={[{ value: "safe", label: "Safe" }, { value: "ambiguous", label: "Needs judgement" }]} />
                <SelectFilter label="Issue type" value={issueType} onChange={resetPaging(setIssueType)}
                              options={ISSUE_TYPES.map((t) => ({ value: t, label: issueLabel(t) }))} />
              </div>
              <Async state={proposals} label="Loading proposals…">
                {(page) => page.proposals.length === 0 ? (
                  <EmptyState title={p.proposal_count === 0 ? "Nothing to repair" : "No proposals match these filters"}>
                    {p.proposal_count === 0 ? "No automatic repairs are suggested. See below for findings that need manual attention." : "Try changing the filters."}
                  </EmptyState>
                ) : (
                  <>
                    <TableWrap>
                      <thead><tr>{["Row", "Column", "Issue", "Proposed change", "Status", "Your decision"].map((h) => <th key={h} className={th}>{h}</th>)}</tr></thead>
                      <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                        {page.proposals.map((x) => <ProposalRow key={x.proposal_id} proposal={x} editable={editable} onDecide={decide} />)}
                      </tbody>
                    </TableWrap>
                    <Pagination total={page.total} offset={offset} limit={LIMIT} onChange={setOffset} />
                  </>
                )}
              </Async>
            </Card>

            <div className="grid gap-6 lg:grid-cols-2">
              <Card title="Not repaired automatically">
                {p.issues_without_proposal.length === 0 ? <p className="text-sm text-slate-500">Every finding has a proposal.</p> : (
                  <ul className="space-y-2 text-sm">
                    {p.issues_without_proposal.map((g) => (
                      <li key={g.issue_type + g.reason}><span className="font-medium">{g.count}× {issueLabel(g.issue_type)}</span><br /><span className="text-slate-600 dark:text-slate-400">{g.reason}</span></li>
                    ))}
                  </ul>
                )}
              </Card>
              <Card title="Cleaned copies from this plan">
                <Async state={cleaned}>
                  {(list) => list.length === 0 ? <p className="text-sm text-slate-500">None yet. Approve repairs, then apply them.</p> : (
                    <ul className="divide-y divide-slate-100 text-sm dark:divide-slate-800">
                      {list.map((c) => (
                        <li key={c.cleaned_id} className="flex items-center justify-between gap-2 py-2">
                          <Link className="text-indigo-700 hover:underline dark:text-indigo-300" to={`/cleaned/${c.cleaned_id}`}>{formatDateTime(c.created_at)}</Link>
                          <span className="flex items-center gap-2"><span className="text-xs text-slate-500">{c.applied_count} applied</span><StatusBadge status={c.status} /></span>
                        </li>
                      ))}
                    </ul>
                  )}
                </Async>
              </Card>
            </div>

            <ConfirmDialog open={confirmSafe} title="Approve all safe proposals?" confirmLabel={`Approve ${safePending}`} busy={busy} onConfirm={approveSafe} onCancel={() => setConfirmSafe(false)}>
              <p>Safe proposals are exact, meaning-preserving fixes (for example trimming stray spaces).</p>
              <p>Proposals that need your judgement are <strong>not</strong> included. You can still change any decision afterwards.</p>
            </ConfirmDialog>
            <ConfirmDialog open={confirmApply} title="Apply the approved repairs?" confirmLabel="Create cleaned copy" busy={busy} onConfirm={apply} onCancel={() => setConfirmApply(false)}>
              <p><strong>{counts.approved}</strong> approved repair(s) will be applied to a <strong>separate copy</strong>. Your original upload is never changed.</p>
              <p>{counts.rejected} rejected and {counts.pending} undecided proposal(s) will not touch the data.</p>
            </ConfirmDialog>
          </>
        );
      }}
    </Async>
  );
}
