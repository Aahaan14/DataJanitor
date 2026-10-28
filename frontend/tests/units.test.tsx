import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ProposalRow } from "../src/components/ProposalRow";
import { emptyRule, validateRules } from "../src/components/RulesEditor";
import { ToastProvider } from "../src/components/Toast";
import { toApiError } from "../src/hooks/useAsync";
import { ApiError } from "../src/services/api";
import type { RepairProposal } from "../src/types/api";
import { formatBytes, formatPercent, formatRelative, shortId } from "../src/utils/format";
import { issueLabel, statusTone } from "../src/utils/labels";

const proposal = (over: Partial<RepairProposal> = {}): RepairProposal => ({
  proposal_id: "R1abcdef123456", issue_id: "I00001", issue_type: "whitespace", action: "replace_value",
  classification: "safe", confidence: "high", column: "name", row_number: 4, original_value: " x", proposed_value: "x",
  alternatives: [], allow_custom_value: false, reason: "Trim.", status: "pending", approved_value: null,
  decided_at: null, conflicts_with: [], history: [], ...over,
});

function renderRow(p: RepairProposal, editable = true) {
  const onDecide = vi.fn().mockResolvedValue(undefined);
  render(<ToastProvider><table><tbody><ProposalRow proposal={p} editable={editable} onDecide={onDecide} /></tbody></table></ToastProvider>);
  return onDecide;
}

describe("ProposalRow", () => {
  it("a safe proposal approves with no value", async () => {
    const onDecide = renderRow(proposal());
    await userEvent.click(screen.getByRole("button", { name: /^Approve \(row 4 name\)/ }));
    expect(onDecide).toHaveBeenCalledWith(expect.objectContaining({ proposal_id: "R1abcdef123456" }), "approve", undefined);
  });

  it("an ambiguous proposal needs a choice and sends it", async () => {
    const onDecide = renderRow(proposal({ classification: "ambiguous", proposed_value: null, alternatives: ["2024-04-03", "2024-03-04"] }));
    const approve = screen.getByRole("button", { name: /^Approve choice/ });
    expect(approve).toBeDisabled();
    await userEvent.selectOptions(screen.getByRole("combobox"), "2024-03-04");
    await userEvent.click(approve);
    expect(onDecide).toHaveBeenCalledWith(expect.anything(), "approve", "2024-03-04");
  });

  it("a clear-value proposal can be approved empty or with a typed correction", async () => {
    const onDecide = renderRow(proposal({ action: "clear_value", proposed_value: null, allow_custom_value: true, original_value: "abc" }));
    await userEvent.click(screen.getByRole("button", { name: /^Approve: empty cell/ }));
    expect(onDecide).toHaveBeenLastCalledWith(expect.anything(), "approve", undefined);
    await userEvent.type(screen.getByPlaceholderText("Corrected value (optional)"), " 35 ");
    await userEvent.click(screen.getByRole("button", { name: /^Approve correction/ }));
    expect(onDecide).toHaveBeenLastCalledWith(expect.anything(), "approve", "35");
  });

  it("is read-only when the plan is closed, and explains conflicts and history", async () => {
    renderRow(proposal({ conflicts_with: ["Ra", "Rb"], history: [{ decision: "approve", decided_at: "2026-01-01T00:00:00Z", chosen_value: null }] }), false);
    expect(screen.getByRole("button", { name: /^Approve/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Reject/ })).toBeDisabled();
    expect(screen.getByText(/Conflicts with 2 other proposal/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Details" }));
    expect(screen.getByText(/Trim\./)).toBeInTheDocument();
    expect(screen.getByLabelText("Decision history")).toHaveTextContent("approved");
  });
});

describe("rules validation", () => {
  it("accepts good rules and reports each mistake", () => {
    expect(validateRules([{ ...emptyRule("age"), dtype: "integer", min_value: 0, max_value: 120 }])).toEqual([]);
    const problems = validateRules([
      { ...emptyRule("a"), dtype: "integer", min_value: 5, max_value: 1 },
      { ...emptyRule("b"), dtype: "string", min_value: 1 },
      { ...emptyRule("c"), regex: "([unclosed" },
      { ...emptyRule("d"), regex: "x".repeat(201) },
    ]);
    expect(problems).toHaveLength(4);
    expect(problems[0]).toMatch(/min cannot be greater than max/);
  });
});

describe("helpers", () => {
  it("formats sizes, percentages, ids and relative times", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(formatPercent(0.5)).toBe("50%");
    expect(formatPercent(null)).toBe("—");
    expect(shortId("0123456789abcdef")).toBe("01234567");
    const now = new Date("2026-01-01T12:00:00Z");
    expect(formatRelative("2026-01-01T11:59:50Z", now)).toBe("just now");
    expect(formatRelative("2026-01-01T11:30:00Z", now)).toBe("30 min ago");
    expect(formatRelative("2025-12-30T12:00:00Z", now)).toBe("2 d ago");
  });

  it("labels and tones", () => {
    expect(issueLabel("exact_duplicate")).toBe("Exact duplicate row");
    expect(issueLabel("brand_new_type")).toBe("Brand new type");
    expect(statusTone("completed")).toBe("green");
    expect(statusTone("failed")).toBe("red");
    expect(statusTone("superseded")).toBe("neutral");
  });

  it("wraps unknown errors as ApiError", () => {
    expect(toApiError(new Error("x"))).toBeInstanceOf(ApiError);
    const original = new ApiError(409, "plan_stale", "stale");
    expect(toApiError(original)).toBe(original);
  });
});
