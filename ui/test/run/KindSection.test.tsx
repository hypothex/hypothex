/** The old KindPanels behaviours (scoped panels, unscoped grid, trace picker), in v5 panel chrome. */
import { afterEach, expect, test } from "bun:test";
import { act, cleanup, screen, waitFor } from "@testing-library/react";
import type { PanelSpec } from "../../src/api/models";
import { KindSection, runPanelSpecs } from "../../src/run/KindSection";
import { fakeRegistry, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const TRACES = [
  { example_id: "T-001", turns: 3, failed: false },
  { example_id: "T-014", turns: 13, failed: true },
];

function traceRoutes(example: string): Record<string, unknown> {
  return {
    "GET /api/v1/runs/R/traces": TRACES,
    [`GET /api/v1/runs/R/traces/${example}`]: {
      type: "trace",
      title: "",
      rows: Array.from({ length: example === "T-014" ? 13 : 3 }, (_, i) => ({ turn: i + 1 })),
      meta: { run_id: "R", example_id: example },
    },
  };
}

test("runPanelSpecs drops curves (the Charts tab draws step metrics)", () => {
  const kind = { kind: "agent_eval" as const, run_view: [{ type: "curves" as const, title: "metrics" }, { type: "trace" as const, title: "steps" }] };
  expect(runPanelSpecs(kind, 2, []).map((p) => [p.type, p.title])).toEqual([["trace", "Steps"]]);
  expect(runPanelSpecs(kind, 0, [])).toEqual([]);
  expect(runPanelSpecs(null, undefined, [])).toEqual([]);
});

test("scoped panels, and the trace panel shows the failed trace first with a picker", async () => {
  const calls = mockApi({
    ...traceRoutes("T-014"),
    "POST /api/v1/tasks/p/t/views/query": { panels: [{ type: "table", title: "Tokens per turn", rows: [{}, {}], meta: {} }] },
  });
  const specs: PanelSpec[] = [{ type: "table", title: "Tokens per turn", data: { source: "traces" } }, { type: "trace", title: "Trajectory" }];
  renderWithClient(<KindSection project="p" task="t" runId="R" specs={specs} />, { registry: fakeRegistry(["table", "trace"]) });
  expect((await screen.findByTestId("panel-table")).textContent).toBe("Tokens per turn:2");
  expect(await screen.findByText("Trajectory · T-014")).toBeTruthy();
  expect((await screen.findByTestId("panel-trace")).textContent).toBe(":13");
  const picker = screen.getByRole("navigation", { name: "Traced examples" });
  expect(picker.querySelector('a[aria-current="true"]')?.textContent).toBe("T-014");
  expect(screen.getByRole("link", { name: "T-001" }).getAttribute("href")).toBe("/r/R?example=T-001");
  const body = calls.find((c) => c.method === "POST")?.body as { view: { panels: PanelSpec[] } };
  expect(body.view.panels[0]?.data).toEqual({ source: "traces", filter: { run_id: "R" } });
});

test("the cross-config grid stays unscoped; an explicit ?example= wins over the failed one", async () => {
  const calls = mockApi({ ...traceRoutes("T-001"), "POST /api/v1/tasks/p/t/views/query": { panels: [{ type: "grid", title: "Comparison", rows: [], meta: {} }] } });
  renderWithClient(
    <KindSection project="p" task="t" runId="R" example="T-001" currentGroupId="g"
      specs={[{ type: "trace", title: "Trajectory" }, { type: "grid", title: "Comparison" }]} />,
    { registry: { ...fakeRegistry(["trace"]), grid: ({ selectedItemId, currentGroupId }: { selectedItemId?: string; currentGroupId?: string }) => <p>{`compare ${selectedItemId}/${currentGroupId}`}</p> } },
  );
  expect(await screen.findByText("compare T-001/g")).toBeTruthy();
  const titles = screen.getAllByText(/^(Trajectory · T-001|Comparison)$/).map((e) => e.textContent);
  expect(titles).toEqual(["Trajectory · T-001", "Comparison"]);
  const body = calls.find((c) => c.method === "POST")?.body as { view: { panels: PanelSpec[] } };
  expect(body.view.panels[0]).toEqual({ type: "grid", title: "Comparison" });
});

test("while traces load, and with no traces, the grid never shows every target", async () => {
  let release!: (traces: typeof TRACES) => void;
  const pending = new Promise<typeof TRACES>((resolve) => {
    release = resolve;
  });
  mockApi({
    "GET /api/v1/runs/R/traces": () => pending,
    "POST /api/v1/tasks/p/t/views/query": { panels: [{ type: "grid", title: "Comparison", rows: [{ item_id: "other" }], meta: {} }] },
  });
  const { client } = renderWithClient(
    <KindSection project="p" task="t" runId="R" specs={[{ type: "trace", title: "Trajectory" }, { type: "grid", title: "Comparison" }]} />,
    { registry: fakeRegistry(["grid", "trace"]) },
  );
  await waitFor(() => expect(client.getQueryCache().getAll().some((q) => q.state.status === "success")).toBe(true));
  expect(screen.queryByTestId("panel-grid")).toBeNull();
  await act(async () => {
    release([]);
  });
  expect(await screen.findByText("No traced example available for comparison")).toBeTruthy();
  expect(screen.queryByTestId("panel-grid")).toBeNull();
});
