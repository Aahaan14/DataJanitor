import { useState } from "react";
import type { ColumnRule, RuleDtype } from "../types/api";
import { Button, inputClass } from "./ui";

export function emptyRule(column: string): ColumnRule {
  return { column, dtype: null, nullable: true, unique: false, min_value: null, max_value: null,
           min_length: null, max_length: null, allowed_values: null, regex: null };
}

/** Client-side checks that mirror the server rules, so mistakes are caught before sending. */
export function validateRules(rules: ColumnRule[]): string[] {
  const problems: string[] = [];
  for (const r of rules) {
    if ((r.min_value !== null || r.max_value !== null) && r.dtype !== "integer" && r.dtype !== "float")
      problems.push(`${r.column}: min/max need type integer or float.`);
    if (r.min_value !== null && r.max_value !== null && r.min_value > r.max_value)
      problems.push(`${r.column}: min cannot be greater than max.`);
    if (r.regex) {
      if (r.regex.length > 200) problems.push(`${r.column}: pattern is longer than 200 characters.`);
      try { new RegExp(r.regex); } catch { problems.push(`${r.column}: the pattern is not a valid regular expression.`); }
    }
  }
  return problems;
}

const DTYPES: { value: RuleDtype | ""; label: string }[] = [
  { value: "", label: "Any" }, { value: "integer", label: "Whole number" }, { value: "float", label: "Number" },
  { value: "date", label: "Date" }, { value: "boolean", label: "Yes / No" }, { value: "string", label: "Text" },
];

const num = (v: string): number | null => (v.trim() === "" || Number.isNaN(Number(v)) ? null : Number(v));

function RuleCard({ rule, columns, taken, onChange, onRemove }: {
  rule: ColumnRule; columns: string[]; taken: Set<string>; onChange: (r: ColumnRule) => void; onRemove: () => void;
}) {
  const [allowed, setAllowed] = useState((rule.allowed_values ?? []).join(", "));
  const numeric = rule.dtype === "integer" || rule.dtype === "float";
  const set = (patch: Partial<ColumnRule>) => onChange({ ...rule, ...patch });
  const id = (s: string) => `${s}-${rule.column}`;
  return (
    <fieldset className="rounded-lg border border-slate-200 p-3 dark:border-slate-700">
      <legend className="px-1 text-sm font-semibold">{rule.column || "New rule"}</legend>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-xs font-medium text-slate-600 dark:text-slate-400" htmlFor={id("col")}>Column
          <select id={id("col")} className={inputClass} value={rule.column} onChange={(e) => set({ column: e.target.value })}>
            {columns.filter((c) => c === rule.column || !taken.has(c)).map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label className="text-xs font-medium text-slate-600 dark:text-slate-400" htmlFor={id("type")}>Must be
          <select id={id("type")} className={inputClass} value={rule.dtype ?? ""}
                  onChange={(e) => set({ dtype: (e.target.value || null) as RuleDtype | null })}>
            {DTYPES.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
          </select>
        </label>
        {numeric && <>
          <label className="text-xs font-medium text-slate-600 dark:text-slate-400" htmlFor={id("min")}>Minimum
            <input id={id("min")} className={inputClass} inputMode="decimal" defaultValue={rule.min_value ?? ""}
                   onChange={(e) => set({ min_value: num(e.target.value) })} /></label>
          <label className="text-xs font-medium text-slate-600 dark:text-slate-400" htmlFor={id("max")}>Maximum
            <input id={id("max")} className={inputClass} inputMode="decimal" defaultValue={rule.max_value ?? ""}
                   onChange={(e) => set({ max_value: num(e.target.value) })} /></label>
        </>}
        <label className="text-xs font-medium text-slate-600 dark:text-slate-400 sm:col-span-2" htmlFor={id("allowed")}>Allowed values (comma-separated, optional)
          <input id={id("allowed")} className={inputClass} value={allowed} placeholder="e.g. Pune, Mumbai, Delhi"
                 onChange={(e) => {
                   setAllowed(e.target.value);
                   const list = e.target.value.split(",").map((v) => v.trim()).filter(Boolean);
                   set({ allowed_values: list.length ? list : null });
                 }} /></label>
        <label className="text-xs font-medium text-slate-600 dark:text-slate-400 sm:col-span-2" htmlFor={id("regex")}>Must match pattern (regular expression, optional)
          <input id={id("regex")} className={inputClass + " font-mono"} defaultValue={rule.regex ?? ""} placeholder="e.g. [A-Z]{2}\d{4}"
                 onChange={(e) => set({ regex: e.target.value || null })} /></label>
      </div>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2"><input type="checkbox" checked={!rule.nullable} onChange={(e) => set({ nullable: !e.target.checked })} /> Required (no empty cells)</label>
          <label className="flex items-center gap-2"><input type="checkbox" checked={rule.unique} onChange={(e) => set({ unique: e.target.checked })} /> Values must be unique</label>
        </div>
        <Button size="sm" variant="ghost" onClick={onRemove} aria-label={`Remove rule for ${rule.column}`}>Remove</Button>
      </div>
    </fieldset>
  );
}

export function RulesEditor({ columns, rules, onChange }: { columns: string[]; rules: ColumnRule[]; onChange: (r: ColumnRule[]) => void }) {
  const taken = new Set(rules.map((r) => r.column));
  const free = columns.filter((c) => !taken.has(c));
  return (
    <div className="space-y-3">
      {rules.map((r, i) => (
        <RuleCard key={`${i}-${r.column}`} rule={r} columns={columns} taken={taken}
                  onChange={(next) => onChange(rules.map((x, j) => (j === i ? next : x)))}
                  onRemove={() => onChange(rules.filter((_, j) => j !== i))} />
      ))}
      {rules.length === 0 && <p className="text-sm text-slate-500">No rules yet. Rules let DataJanitor flag values that break your own constraints.</p>}
      <Button variant="secondary" size="sm" disabled={!free.length} onClick={() => onChange([...rules, emptyRule(free[0]!)])}>
        + Add a rule
      </Button>
    </div>
  );
}
