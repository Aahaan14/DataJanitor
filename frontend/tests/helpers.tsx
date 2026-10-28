import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import App from "../src/App";
import { api } from "../src/services/api";

/** Render the whole app at a route. Every request goes to the real test backend. */
export function renderApp(route = "/") {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  );
}

export function csvFile(text: string, name = "data.csv"): File {
  return new File([text], name, { type: "text/csv" });
}

let counter = 0;
export const uniqueName = (prefix = "sample"): string => `${prefix}-${Date.now()}-${++counter}.csv`;

/** A small messy dataset with several kinds of issues (see expectations in the tests). */
export const MESSY_CSV =
  "id,name,age,joined,city,salary\n" +
  "1,Alice Smith,30,2024-01-05,Mumbai,50000\n" +
  "2,Bob,,05/02/2024,mumbai,52000\n" +
  "3,Carol,41,2024-02-30,Mumbai,51000\n" +
  "4, alice smith,30,2024-01-05,Mumbai,50000\n" +
  '5,Dan,abc,2024-03-01,Pune,"1,200"\n' +
  "1,Alice Smith,30,2024-01-05,Mumbai,50000\n";

export async function seedDataset(csv = MESSY_CSV, name = uniqueName()) {
  return api.uploadDataset(csvFile(csv, name));
}

export async function seedPlan(csv = MESSY_CSV, rules?: Parameters<typeof api.createPlan>[1]) {
  const ds = await seedDataset(csv);
  const plan = await api.createPlan(ds.dataset_id, rules);
  return { ds, plan };
}
