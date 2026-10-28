# DataJanitor — concise viva guide

## 30-second overview

DataJanitor is a Python-first dataset quality assistant. A user uploads a CSV, reviews a preview and scan results, creates a repair plan, explicitly approves or rejects proposed changes, and can generate a separately stored cleaned file. Scan history and decisions are persisted for traceability. The original upload is not silently rewritten.

## Architecture

- **Frontend:** React + TypeScript + Vite + Tailwind CSS; reusable pages/components call a centralized typed API client.
- **API:** FastAPI routes validate requests and delegate work to services. Pydantic schemas define request/response shapes.
- **Data processing:** Pandas-based CSV/profile/detection services; Pandera-backed configurable validation; scikit-learn/statistical logic is used for selected anomaly checks.
- **Persistence:** SQLAlchemy ORM with SQLite stores metadata, scan results, proposals, decisions, outcomes, and report records. CSV files are stored separately from the database.
- **Reporting:** SMTP settings come from environment configuration; report failures are recorded separately from scan results.
- **Testing:** Pytest/HTTPX for backend API and service coverage; Vitest/Testing Library for frontend behavior and API-client tests.

## Important design decisions

1. **Human-in-the-loop repairs:** detection and recommendation are separate from applying changes. Approval is explicit.
2. **Preserve the source:** cleaning produces a separate output; it does not overwrite the uploaded file.
3. **Auditability:** approve/reject decisions and outcomes are persisted so the workflow can be reviewed.
4. **Explainability:** issues include a type and explanation; uncertain suggestions should be left for human review.
5. **Separation of concerns:** routes handle HTTP, services implement business logic, schemas validate data, and ORM models persist records.
6. **Defensive input handling:** upload restrictions, file/path handling, CORS configuration, and browser security headers reduce avoidable risks.

## Short viva questions and answers

**Why not automatically fix every issue?** Because an anomaly or unusual value is not necessarily wrong. Human approval prevents unsupported assumptions from corrupting data.

**Why keep the original CSV?** It provides a reliable source for comparison and recovery and makes the cleaning process auditable.

**Why SQLite?** It is easy to run for a local student project and persists structured history without requiring a separate database server. A multi-user deployment may need a managed database.

**Why FastAPI?** It provides typed request/response validation, REST endpoints, and interactive OpenAPI documentation.

**What does Pandera do?** It applies explicit dataframe/schema rules such as expected types, nullability, ranges, allowed values, and uniqueness.

**Are outliers errors?** No. They are unusual observations that need context. The application should communicate uncertainty rather than label them as proven errors.

**How are decisions tracked?** Repair proposals, user decisions, cleaning outcomes, and scan history are stored in the database.

**What if SMTP fails?** The report attempt can be recorded as failed; the completed scan results should remain available.

**How would you scale it?** Add authentication/authorization, use managed database/object storage, add background job processing and quotas, improve retention controls, and deploy behind HTTPS with monitoring.

## Known limitations and future work

- This is a student/local-first application, not a security-audited multi-tenant service. Do not expose it publicly without authentication, authorization, HTTPS, operational controls, and a deployment review.
- CSV type inference and data-quality rules are necessarily heuristic; domain-specific validation must be configured by the user.
- Potential duplicates, case normalization, invalid-looking values, and statistical outliers can require domain knowledge.
- The default SQLite configuration is suitable for local use, not necessarily high-concurrency deployment.
- SMTP delivery depends on provider configuration, credentials, network access, and provider policy.
- Retention/cleanup settings should be reviewed against the data sensitivity and operational needs of any real deployment.
- Future work: user accounts/roles, richer rule templates, background processing for large files, configurable domain schemas, richer dataset comparisons, deployment automation, and accessibility/usability testing.
