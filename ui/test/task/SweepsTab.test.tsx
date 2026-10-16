import { afterEach, expect, test } from "bun:test";
import { fireEvent, screen, within } from "@testing-library/react";
import { SweepsTab } from "../../src/task/SweepsTab";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { PROJECT, makeTaskRuns } from "./fixtures";

afterEach(restoreFetch);

const gone = (id: string) => new HttpReply(404, { error: `sweep not found: ${PROJECT}/${id}`, type: "StoreError" });
function data() {
  const d = makeTaskRuns();
  d.runs = d.runs.map((r, i) => ({ ...r, sweep_id: i < 3 ? "s-new" : i < 5 ? "s-old" : null }));
  return d;
}
const routes = {
  [`GET /api/v1/projects/${PROJECT}/sweeps`]: [
    { id: "s-new", created_at: "2026-10-03T09:00:00Z", n_runs: 3, best: { params: { lr: "3e-4", beam: "10" }, group_id: "g-a", n: 2, mean: 0.911, lo: 0.905, hi: 0.917, run_ids: [] } },
    { id: "s-old", created_at: "2026-10-02T09:00:00Z", n_runs: 2, best: null },
    { id: "s-other", created_at: "2026-10-01T09:00:00Z", n_runs: 9, best: null },
  ],
  [`GET /api/v1/sweeps/${PROJECT}/s-new`]: gone("s-new"),
  [`GET /api/v1/sweeps/${PROJECT}/s-old`]: gone("s-old"),
  [`GET /api/v1/sweeps/${PROJECT}/s-pending`]: gone("s-pending"),
  "GET /api/v1/hosts": [],
};

test("lists the task's sweeps only, newest first, and opens the first", async () => {
  mockApi(routes);
  const selected: string[] = [];
  renderWithClient(<SweepsTab project={PROJECT} data={data()} sweepId={null} onSelect={(id) => selected.push(id)} />);
  const list = screen.getByRole("navigation", { name: "Sweeps" });
  const items = within(list).getAllByRole("button");
  expect(items.map((b) => b.querySelector("b")?.textContent)).toEqual(["s-new", "s-old"]);
  expect(items[0]?.getAttribute("aria-current")).toBe("true");
  expect(await within(list).findByText("lr 3e-4, beam 10 0.9110")).toBeTruthy();
  expect(await screen.findByRole("heading", { level: 2, name: "s-new" })).toBeTruthy();
  fireEvent.click(items[1] as HTMLElement);
  expect(selected).toEqual(["s-old"]);
});

test("a sweep named in the URL but without task runs yet is listed first", async () => {
  mockApi(routes);
  renderWithClient(<SweepsTab project={PROJECT} data={data()} sweepId="s-pending" onSelect={() => {}} />);
  const items = within(screen.getByRole("navigation", { name: "Sweeps" })).getAllByRole("button");
  expect(items.map((b) => b.querySelector("b")?.textContent)).toEqual(["s-pending", "s-new", "s-old"]);
  expect(await screen.findByRole("heading", { level: 2, name: "s-pending" })).toBeTruthy();
});

test("no sweeps", () => {
  mockApi(routes);
  renderWithClient(<SweepsTab project={PROJECT} data={makeTaskRuns()} sweepId={null} onSelect={() => {}} />);
  expect(screen.getByText("No sweeps")).toBeTruthy();
});
