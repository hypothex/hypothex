import { afterEach, expect, test } from "bun:test";
import { QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { SelectedRun } from "../../src/pages/components/SelectedRun";
import { makeDetail, RUN_SVM } from "./fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(restoreFetch);
const kindURL = "GET /api/v1/tasks/toy-classifier/toy-test/kind";

test("selected training run uses actual paths/params and keeps checkpoint validation separate", async () => {
  let closed = false;
  mockApi({
    [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail({ status: "killed", params: { lr: "0.0003", config: "actual recorded config" }, artifacts: [{ kind: "checkpoint", path: "/actual/model.pt", host: "remote-gpu", step: 300, size: null, metrics: { "val/top1": 0.88 } }] }, { scores: [] }),
    [kindURL]: { kind: "training", run_view: [] },
  });
  renderWithClient(<SelectedRun runId={RUN_SVM} onClose={() => { closed = true; }} />);
  await screen.findByRole("table", { name: "Checkpoint metrics" });
  expect(screen.getByText("actual recorded config")).toBeTruthy();
  expect(screen.getByText("0.0003")).toBeTruthy();
  expect(screen.getByText("no scores")).toBeTruthy();
  expect(screen.getAllByText(/remote-gpu:\/actual\/model.pt/).length).toBeGreaterThan(0);
  const open = screen.getByRole("link", { name: /Open run/ });
  expect(open.getAttribute("href")).toBe(`/r/${RUN_SVM}`);
  expect(open.getAttribute("target")).toBe("_blank");
  fireEvent.click(screen.getByRole("button", { name: "Close selected run" }));
  expect(closed).toBe(true);
});

for (const kind of ["generic", "agent_eval", "agent_iteration", "system_bench"]) {
  test(`selected ${kind} run shows ordinary detail without training assumptions`, async () => {
    mockApi({ [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail({ params: {} }), [kindURL]: { kind, run_view: [] } });
    renderWithClient(<SelectedRun runId={RUN_SVM} onClose={() => {}} />);
    await screen.findByText("accuracy v1");
    await waitFor(() => expect(screen.getByRole("region", { name: "Selected run" }).textContent).toContain(kind));
    expect(screen.queryByRole("table", { name: "Checkpoint metrics" })).toBeNull();
    expect(screen.getByText("No parameters recorded.")).toBeTruthy();
  });
}

test("loading and failed selected runs can always be dismissed", async () => {
  let resolve!: (value: unknown) => void;
  let closed = 0;
  mockApi({ "GET /api/v1/runs/pending": () => new Promise(r => { resolve = r; }) });
  renderWithClient(<SelectedRun runId="pending" onClose={() => { closed++; }} />);
  expect(screen.getByRole("status").textContent).toContain("Loading");
  fireEvent.click(screen.getByRole("button", { name: "Close selected run" }));
  expect(closed).toBe(1);
  resolve(new HttpReply(404, { error: "missing selected run", type: "StoreError" }));
  await screen.findByRole("alert");
  fireEvent.click(screen.getByRole("button", { name: "Close selected run" }));
  expect(closed).toBe(2);
});

test("selected run without a task needs no task API and leaves no stale prior-run data", async () => {
  const calls = mockApi({ "GET /api/v1/runs/one": makeDetail({ run_id: "one", task: null, hypothesis: "first hypothesis" }), "GET /api/v1/runs/two": makeDetail({ run_id: "two", task: null, hypothesis: "second hypothesis" }) });
  const view = renderWithClient(<SelectedRun runId="one" onClose={() => {}} />);
  await screen.findByText("first hypothesis");
  view.rerender(<QueryClientProvider client={view.client}><SelectedRun runId="two" onClose={() => {}} /></QueryClientProvider>);
  await screen.findByText("second hypothesis");
  expect(screen.queryByText("first hypothesis")).toBeNull();
  expect(calls.map(call => call.url)).toEqual(["/api/v1/runs/one", "/api/v1/runs/two"]);
});

test("explicit selection focuses its heading and closing restores the selecting control", async () => {
  const trigger = document.createElement("button");
  trigger.textContent = "Select run";
  document.body.append(trigger);
  trigger.focus();
  mockApi({ "GET /api/v1/runs/focus": makeDetail({ run_id: "focus", task: null }) });
  const view = renderWithClient(<SelectedRun runId="focus" onClose={() => {}} />);
  const heading = screen.getByRole("heading", { name: "Selected run · focus" });
  expect(document.activeElement === heading).toBe(true);
  view.unmount();
  expect(document.activeElement === trigger).toBe(true);
  trigger.remove();
});
