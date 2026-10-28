# DataJanitor demonstration workflow

## Start locally

Follow the root README Quick Start. Backend docs are at `http://127.0.0.1:8000/docs`; frontend at `http://localhost:5173`. Keep both terminals running.

## UI walkthrough

1. Upload `backend/sample_data/data_quality_demo.csv`.
2. Inspect the preview, row/column counts, and inferred column profile.
3. Run a scan. Review the issue type, row reference, explanation, severity, and suggested action.
4. Create a repair plan. Review each proposal's original value, proposed value, reason, and uncertainty.
5. Approve only defensible deterministic changes. Reject a suggestion that is wrong or unsupported; leave ambiguous values for human review.
6. Generate a cleaned output and review its validation summary.
7. Compare the downloaded output with the original sample. The original upload should remain unchanged.
8. Inspect scan history and the repair decision/audit history. Check report preview and email status; actual delivery requires valid SMTP settings.

## API-assisted walkthrough

The API's exact schemas are available from Swagger at `/docs`. The typical order is:

- `POST /api/datasets/upload` with multipart field `file`
- `POST /api/datasets/{dataset_id}/scan`
- `POST /api/datasets/{dataset_id}/repair-plan`
- `GET /api/repair-plans/{plan_id}`
- Use the approve/reject endpoints shown in Swagger for individual proposal IDs
- Use the cleaned dataset endpoint shown in Swagger to generate a separate output
- Use history endpoints to inspect persisted scans and decisions

IDs are generated at runtime; do not copy IDs from another run. Consult Swagger for the exact request body for approval/rejection and output generation rather than guessing fields.

## Demo acceptance checklist

- [ ] Original sample remains byte-for-byte unchanged.
- [ ] A scan and its issue list are visible.
- [ ] At least one proposal is approved and one is rejected, when suitable proposals exist.
- [ ] Output includes approved changes only; rejected/pending proposals are not silently applied.
- [ ] History/audit records show the decisions.
- [ ] Final validation result and remaining issues are reviewed.
- [ ] Email is described as configured/not configured based on actual settings; no delivery is claimed without confirmation.
