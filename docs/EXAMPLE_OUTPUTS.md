# Example issue patterns (illustrative)

These are examples of what to look for in `data_quality_demo.csv`, not a captured API response. Exact counts and wording depend on the detector configuration and application version.

| Input pattern | Likely detector category | Review guidance |
|---|---|---|
| Empty `age` in customer C002 | Missing value | Do not infer an age without a trusted source.
| `N/A` in `email` or `city` | Placeholder missing | Treat as missing-like only according to the detector's configured placeholder rules.
| `  Asha Rao ` and `Asha Rao` | Whitespace/text inconsistency | Trimming may be deterministic, but confirm how the value is used.
| `Mumbai` and `mumbai` | Inconsistent text format | A canonical capitalization is a convention, not proof of an error.
| Repeated C001/C007 details | Exact/potential duplicate | Verify whether this is a duplicate record or two legitimate events before deletion/merging.
| `31/02/2025` | Invalid date candidate | The date does not exist; do not invent a replacement.
| `twenty`, `unknown`, `1,200` | Numeric parsing/formatting issue | Preserve the original text until the intended meaning is known.
| Negative age/order amount | Validation/domain-rule candidate | Confirm business rules; negative values can be valid in some contexts (e.g. refunds).
| `999999` order amount | Suspicious outlier candidate | Outlier detection is a prompt to investigate, not proof of an error.

A correct demonstration explains uncertainty and shows explicit approval/rejection. Never present a detector flag as a confirmed error solely because the software emitted it.
