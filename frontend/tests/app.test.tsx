/**
 * UI tests: the whole application rendered in jsdom, talking to the REAL backend.
 * Data is created through the real API; nothing is mocked except the browser's
 * file-save step (jsdom cannot save files).
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { api } from "../src/services/api";
import { csvFile, MESSY_CSV, renderApp, seedDataset, seedPlan, uniqueName } from "./helpers";

const rowCsv = (n: number) => "id,name,age\n" + Array.from({ length: n }, (_, i) => `${i + 1},Name ${i + 1},${20 + i}`).join("\n") + "\n";

describe("settings and shell", () => {
  it("shows the real server configuration", async () => {
    renderApp("/settings");
    expect(await screen.findByText("Upload limits")).toBeInTheDocument();
    expect(screen.getByText("10 MB")).toBeInTheDocument();
    expect(screen.getByText("Off")).toBeInTheDocument();                        // email disabled on the test server
    expect(screen.getByRole("link", { name: "Open /docs" })).toHaveAttribute("href", expect.stringMatching(/\/docs$/));
    expect(screen.getAllByRole("link", { name: "Upload" }).length).toBeGreaterThan(0);
  });

  it("unknown pages and unknown ids show clear, non-crashing states", async () => {
    const first = renderApp("/nowhere");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    first.unmount();
    renderApp(`/datasets/${"a".repeat(32)}`);
    expect(await screen.findByText("Not available")).toBeInTheDocument();
    expect(screen.getByText("Dataset not found.")).toBeInTheDocument();
    expect(screen.getByText(/dataset_not_found/)).toBeInTheDocument();
  });
});

describe("upload", () => {
  it("uploads a CSV, shows its profile and preview, and continues to a scan", async () => {
    const user = userEvent.setup();
    renderApp("/upload");
    const name = uniqueName("ui-upload");
    await user.upload(await screen.findByLabelText("Choose a CSV file"), csvFile(MESSY_CSV, name));
    expect(screen.getByText(name)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /upload & analyse/i }));

    expect(await screen.findByText(new RegExp(`“${name}” was uploaded`))).toBeInTheDocument();
    expect(screen.getAllByText("Alice Smith").length).toBeGreaterThan(0);        // preview cell from the real file
    expect(screen.getByRole("heading", { name: "Columns" })).toBeInTheDocument();
    expect(screen.getAllByText("mixed").length).toBeGreaterThan(0);              // age has a non-numeric value

    await user.click(screen.getByRole("button", { name: "Run a scan now" }));
    expect(await screen.findByRole("heading", { name: "Scan results" })).toBeInTheDocument();
    expect(await screen.findByText(/not a real calendar date/i)).toBeInTheDocument();
  });

  it("rejects a non-CSV file in the browser before uploading", async () => {
    const user = userEvent.setup({ applyAccept: false });
    renderApp("/upload");
    await user.upload(await screen.findByLabelText("Choose a CSV file"), new File(["hello"], "notes.txt", { type: "text/plain" }));
    expect(await screen.findByText("Only .csv files are accepted.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upload & analyse/i })).toBeDisabled();
  });

  it("shows the server's explanation when a CSV is malformed", async () => {
    const user = userEvent.setup();
    renderApp("/upload");
    await user.upload(await screen.findByLabelText("Choose a CSV file"), csvFile("a,b\n1,2\n3,4,5,6\n", uniqueName("ragged")));
    await user.click(screen.getByRole("button", { name: /upload & analyse/i }));
    expect(await screen.findByText("This file cannot be used")).toBeInTheDocument();
    expect(screen.getByText(/The CSV is malformed/)).toBeInTheDocument();
    expect(screen.queryByText(/was uploaded/)).not.toBeInTheDocument();
  });
});

describe("datasets", () => {
  it("lists uploads, shows an empty state for a filter, and deletes with confirmation", async () => {
    const user = userEvent.setup();
    const name = uniqueName("ui-list");
    await seedDataset(MESSY_CSV, name);
    renderApp("/datasets");
    expect(await screen.findByText(name)).toBeInTheDocument();

    await user.selectOptions(screen.getByLabelText("Status"), "expired");
    expect(await screen.findByText("No datasets with this status")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Status"), "");

    await user.click(await screen.findByRole("button", { name: `Delete ${name}` }));
    const dialog = screen.getByRole("dialog", { name: "Delete this dataset?" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Dataset deleted")).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("button", { name: `Delete ${name}` })).not.toBeInTheDocument());
  });

  it("shows the profile, pages through the preview and creates a plan with rules", async () => {
    const user = userEvent.setup();
    const ds = await seedDataset(rowCsv(25), uniqueName("ui-detail"));
    renderApp(`/datasets/${ds.dataset_id}`);

    expect(await screen.findByRole("heading", { name: ds.filename })).toBeInTheDocument();
    expect(await screen.findByText("Name 1")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Next" }));
    expect(await screen.findByText("Name 11")).toBeInTheDocument();
    expect(screen.queryByText("Name 1")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: /Scans/ }));
    expect(screen.getByText("No scans yet")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Create repair plan" }));
    const dialog = await screen.findByRole("dialog", { name: "Create a repair plan" });
    await user.click(within(dialog).getByLabelText(/Also check my validation rules/));
    expect(await within(dialog).findByRole("group", { name: "age" })).toBeInTheDocument();   // suggested rule from the data
    await user.click(within(dialog).getByRole("button", { name: "Create plan" }));

    expect(await screen.findByRole("heading", { name: "Review repairs" })).toBeInTheDocument();
    expect(await screen.findByText("Nothing to repair")).toBeInTheDocument();                // 25 clean rows
  });

  it("blocks a rule whose minimum is above its maximum", async () => {
    const user = userEvent.setup();
    const ds = await seedDataset(rowCsv(5), uniqueName("ui-rules"));
    renderApp(`/datasets/${ds.dataset_id}`);
    await user.click(await screen.findByRole("button", { name: "Create repair plan" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByLabelText(/Also check my validation rules/));
    const age = await within(dialog).findByRole("group", { name: "age" });
    await user.type(within(age).getByLabelText("Minimum"), "50");
    await user.type(within(age).getByLabelText("Maximum"), "10");
    expect(await within(dialog).findByText(/min cannot be greater than max/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Create plan" })).toBeDisabled();
  });
});

describe("scan results", () => {
  it("filters issues by severity and previews the email report", async () => {
    const user = userEvent.setup();
    const ds = await seedDataset(MESSY_CSV, uniqueName("ui-scan"));
    const scan = await api.runScan(ds.dataset_id);
    renderApp(`/scans/${scan.scan_id}`);

    expect(await screen.findByText("Issues detected")).toBeInTheDocument();
    expect(await screen.findByText(/is empty/)).toBeInTheDocument();             // a missing-value row
    await user.selectOptions(screen.getByLabelText("Severity"), "high");
    expect(await screen.findByText(/not a real calendar date/)).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/is empty/)).not.toBeInTheDocument());   // list refreshed, not just dimmed

    await user.click(screen.getByRole("button", { name: "Email report" }));
    const dialog = await screen.findByRole("dialog", { name: "Email report preview" });
    expect(await within(dialog).findByText(/DataJanitor scan report/)).toBeInTheDocument();
    expect(within(dialog).getByText(/Email is not configured/)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: /Send this report/ })).not.toBeInTheDocument();
    expect(dialog).not.toHaveTextContent("Alice");                                // counts only, never cell values
  });
});

describe("repair review → cleaned dataset", () => {
  it("approves safe fixes, makes a choice, rejects, reports a conflict, applies and downloads", async () => {
    const user = userEvent.setup();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined); // jsdom cannot save files
    const { plan } = await seedPlan();
    renderApp(`/plans/${plan.plan_id}`);
    expect(await screen.findByRole("heading", { name: "Review repairs" })).toBeInTheDocument();

    // 1. bulk-approve the safe proposals (with confirmation)
    await user.click(await screen.findByRole("button", { name: /Approve all safe \(\d+\)/ }));
    const confirm = screen.getByRole("dialog", { name: "Approve all safe proposals?" });
    await user.click(within(confirm).getByRole("button", { name: /^Approve \d+$/ }));
    expect(await screen.findByText(/safe proposal\(s\) approved/)).toBeInTheDocument();

    // 2. an ambiguous date needs a choice before it can be approved
    const approveChoice = await screen.findByRole("button", { name: /^Approve choice \(row 2 joined\)/ });
    expect(approveChoice).toBeDisabled();
    const select = screen.getByLabelText("Value for row 2 joined");
    await user.selectOptions(select, within(select).getAllByRole("option")[1]!);
    expect(approveChoice).toBeEnabled();
    await user.click(approveChoice);
    // two safe fixes were already approved; the date makes three "Will be applied as" lines
    await waitFor(() => expect(screen.getAllByText(/Will be applied as:/).length).toBeGreaterThanOrEqual(3));

    // 3. approving a deletion that conflicts with an approved edit on the same row is refused
    await user.click(await screen.findByRole("button", { name: /^Approve deletion \(row 4/ }));
    expect(await screen.findByText(/Conflicts with already-approved/)).toBeInTheDocument();

    // 4. reject the exact duplicate
    await user.click(await screen.findByRole("button", { name: /^Reject \(row 6/ }));
    await waitFor(async () => expect((await api.listProposals(plan.plan_id, { status: "rejected" })).total).toBe(1));

    // 5. apply → cleaned page
    await user.click(screen.getByRole("button", { name: /^Apply \d+ approved repair/ }));
    const applyDialog = screen.getByRole("dialog", { name: "Apply the approved repairs?" });
    expect(within(applyDialog).getByText(/separate copy/)).toBeInTheDocument();
    await user.click(within(applyDialog).getByRole("button", { name: "Create cleaned copy" }));

    expect(await screen.findByRole("heading", { name: "Cleaned dataset" })).toBeInTheDocument();
    expect(await screen.findByText(/issue\(s\) remain/)).toBeInTheDocument();     // final validation is honest
    expect(screen.getByText("Before the repairs")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Download CSV (safe for Excel)" }));
    expect(await screen.findByText("Download started")).toBeInTheDocument();

    // 6. every proposal's outcome is listed; rejected ones never touched the data
    await user.selectOptions(screen.getByLabelText("Outcome"), "rejected");
    const outcomes = screen.getByRole("heading", { name: "What happened to each proposal" }).closest("section")!;
    expect(await within(outcomes).findByText("Exact duplicate row")).toBeInTheDocument();   // (the charts above also name it)
    expect(within(outcomes).getByText("rejected by reviewer")).toBeInTheDocument();
    expect(within(outcomes).queryByText("applied")).not.toBeInTheDocument();                 // the filter really applied
  });

  it("closes decisions on a plan that a newer plan has replaced", async () => {
    const { ds, plan } = await seedPlan();
    await api.createPlan(ds.dataset_id);
    renderApp(`/plans/${plan.plan_id}`);
    expect(await screen.findByText("A newer plan replaced this one")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Approve all safe/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Apply/ })).not.toBeInTheDocument();
    const approve = (await screen.findAllByRole("button", { name: /^Approve/ }))[0]!;
    expect(approve).toBeDisabled();
  });

  it("lets a user type a corrected value for an invalid entry", async () => {
    const user = userEvent.setup();
    const csv = "id,age\n" + Array.from({ length: 20 }, (_, i) => `${i + 1},${30 + i}`).join("\n") + "\n21,abc\n";
    const { plan } = await seedPlan(csv);
    renderApp(`/plans/${plan.plan_id}`);
    const input = await screen.findByLabelText("Corrected value for row 21 age");
    await user.type(input, "35");
    await user.click(screen.getByRole("button", { name: /^Approve correction \(row 21 age\)/ }));
    expect(await screen.findByText(/Will be applied as:/)).toBeInTheDocument();
    const approved = await api.listProposals(plan.plan_id, { status: "approved" });
    expect(approved.proposals[0]).toMatchObject({ approved_value: "35", original_value: "abc" });

    await user.clear(input);
    await user.type(input, "not-a-number");
    await user.click(screen.getByRole("button", { name: /^Approve correction \(row 21 age\)/ }));
    expect(await screen.findByText(/Value must be a plain number/)).toBeInTheDocument();   // the server's validation is shown
  });
});

describe("history and dashboard", () => {
  it("shows scans, the audit trail and email reports", async () => {
    const user = userEvent.setup();
    const ds = await seedDataset(MESSY_CSV, uniqueName("ui-history"));
    await api.runScan(ds.dataset_id);
    renderApp("/history");

    expect((await screen.findAllByText("Completed")).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("tab", { name: "Audit log" }));
    expect((await screen.findAllByText("Dataset uploaded")).length).toBeGreaterThan(0);
    await user.selectOptions(screen.getByLabelText("Event"), "cleanup_run");
    expect(await screen.findByText("No events")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Email reports" }));
    expect(await screen.findByText("No email reports")).toBeInTheDocument();
  });

  it("the dashboard reflects what is really in the database", async () => {
    await seedPlan();
    const stats = await api.stats();
    renderApp("/");
    expect(await screen.findByText("Recent datasets")).toBeInTheDocument();
    expect(screen.getByText("Approval rate")).toBeInTheDocument();
    expect(screen.getByText(new Intl.NumberFormat().format(stats.issues_detected).replace(/^/, ""))).toBeInTheDocument();
    expect(screen.getByText("Recent activity")).toBeInTheDocument();
    expect(screen.getAllByText(/Repair plan created|Scan completed|Dataset uploaded/).length).toBeGreaterThan(0);
  });
});
