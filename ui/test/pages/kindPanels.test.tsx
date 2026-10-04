import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, screen, within } from "@testing-library/react";
import {
  KindPanels,
  kindPanelCount,
  pickExample,
  readsTraces,
  runViewPanels,
  scopeToRun,
  sentenceCase,
  withoutSweeps,
} from "../../src/pages/components/KindPanels";
import { LogView } from "../../src/pages/components/LogView";
import type { PanelSpec } from "../../src/pages/components/types";
import { fakeRegistry, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const TRACES = [
  { example_id: "T-001", turns: 3, failed: false },
  { example_id: "T-014", turns: 13, failed: true },
];

const SPECS: PanelSpec[] = [
  { type: "curves", title: "Curves", data: { metrics: ["loss"] }, layout: { span: 12, row: null } },
  { type: "trace", title: "Trajectory", data: {}, layout: { span: 12, row: null } },
];

function traceRoutes(example: string): Record<string, unknown> {
  return {
    "POST /api/v1/tasks/p/t/views/query": {
      panels: [{ type: "curves", title: "Curves", rows: [{}, {}, {}], meta: {} }],
    },
    "GET /api/v1/runs/R/traces": TRACES,
    [`GET /api/v1/runs/R/traces/${example}`]: {
      type: "trace",
      title: "",
      rows: Array.from({ length: example === "T-014" ? 13 : 3 }, (_, i) => ({ turn: i + 1 })),
      meta: { run_id: "R", example_id: example },
    },
  };
}

describe("helpers", () => {
  test("scopeToRun adds the run filter and keeps the rest", () => {
    expect(
      scopeToRun({ type: "curves", title: "Loss", data: { metrics: ["loss"], filter: { status: ["finished"] } } }, "R"),
    ).toEqual({
      type: "curves",
      title: "Loss",
      data: { metrics: ["loss"], filter: { status: ["finished"], run_id: "R" } },
    });
    expect(scopeToRun({ type: "table" }, "R")).toEqual({ type: "table", data: { filter: { run_id: "R" } } });
  });

  test("scopeToRun leaves the cross-config grid unscoped", () => {
    const grid: PanelSpec = { type: "grid", title: "same item across configs" };
    expect(scopeToRun(grid, "R")).toEqual({ type: "grid", title: "same item across configs" });
    expect(scopeToRun(grid, "R")).toBe(grid);
  });

  test("pickExample prefers a failed trace; kindPanelCount counts one trace section", () => {
    expect(pickExample(TRACES)).toBe("T-014");
    expect(pickExample([{ example_id: "a", turns: 1, failed: false }])).toBe("a");
    expect(pickExample([])).toBeNull();
    expect(kindPanelCount([...SPECS, { type: "trace", title: "again" }])).toBe(2);
  });
});

test("runViewPanels: sentence-case titles; no trace panels for a run without traces", () => {
  const agent: PanelSpec[] = [
    { type: "trace", title: "steps" },
    { type: "grid", title: "same item across configs" },
    { type: "table", title: "tokens per turn", data: { source: "traces" } },
  ];
  expect(sentenceCase("tokens per turn")).toBe("Tokens per turn");
  expect(sentenceCase("")).toBe("");
  expect(agent.map(readsTraces)).toEqual([true, false, true]);
  expect(runViewPanels(agent, 0).map((p) => p.title)).toEqual(["Same item across configs"]);
  expect(runViewPanels(agent, 2).map((p) => p.title)).toEqual([
    "Steps",
    "Same item across configs",
    "Tokens per turn",
  ]);
  // traces not loaded yet: keep every panel
  expect(runViewPanels(agent)).toHaveLength(3);
});

test("KindPanels queries scoped panels and shows the failed trace first", async () => {
  const calls = mockApi(traceRoutes("T-014"));
  renderWithClient(
    <KindPanels project="p" task="t" runId="R" specs={SPECS} startIndex={1} />,
    { registry: fakeRegistry(["curves", "trace"]) },
  );
  const curves = await screen.findByRole("region", { name: "b Curves" });
  expect(within(curves).getByTestId("panel-curves").textContent).toBe("Curves:3");
  const trace = await screen.findByRole("region", { name: "c Trajectory · T-014" });
  expect((await within(trace).findByTestId("panel-trace")).textContent).toBe(":13");
  const picker = within(trace).getByRole("navigation", { name: "Traced examples" });
  expect(within(picker).getByRole("link", { name: "T-001" }).getAttribute("href")).toBe("/r/R?example=T-001");
  const failed = within(picker).getByRole("link", { name: "T-014" });
  expect(failed.getAttribute("aria-current")).toBe("true");
  expect(failed.className).toBe("failed");
  const body = calls.find((c) => c.method === "POST")?.body as {
    view: { title: string; panels: PanelSpec[] };
  };
  expect(body.view.title).toBe("run");
  expect(body.view.panels).toHaveLength(1);
  expect(body.view.panels[0]?.data?.filter).toEqual({ run_id: "R" });
});

test("KindPanels scopes the table to the run but not the grid", async () => {
  const calls = mockApi({
    "POST /api/v1/tasks/p/t/views/query": {
      panels: [
        { type: "grid", title: "same item across configs", rows: [{}, {}, {}, {}], meta: {} },
        { type: "table", title: "tokens per turn", rows: [{}], meta: {} },
      ],
    },
  });
  const agentSpecs: PanelSpec[] = [
    { type: "grid", title: "same item across configs" },
    { type: "table", title: "tokens per turn", data: { source: "traces" } },
  ];
  renderWithClient(
    <KindPanels project="p" task="t" runId="R" specs={agentSpecs} startIndex={0} />,
    { registry: fakeRegistry(["grid", "table"]) },
  );
  const grid = await screen.findByRole("region", { name: "a same item across configs" });
  expect(within(grid).getByTestId("panel-grid").textContent).toBe("same item across configs:4");
  const body = calls.find((c) => c.method === "POST")?.body as {
    view: { title: string; panels: PanelSpec[] };
  };
  expect(body.view.panels[0]).toEqual({ type: "grid", title: "same item across configs" });
  expect(body.view.panels[1]?.data).toEqual({ source: "traces", filter: { run_id: "R" } });
});

describe("sweep metrics stay out of the run's over-time curves (UI-F10b)", () => {
  const point = (name: string, step: number) => ({ run_id: "R", group_id: "g", seed: 1, name, step, value: 1 });
  const rows = [point("cpu_pct", 0), point("cpu_pct", 33), point("sweep/rps", 1), point("sweep/rps", 128)];
  const overTime: PanelSpec = { type: "curves", title: "over time" };

  test("withoutSweeps drops sweep/* rows of a curves panel without a metric list", () => {
    const result = { type: "curves" as const, title: "over time", rows, meta: { metrics: ["cpu_pct", "sweep/rps"] } };
    const out = withoutSweeps(result, overTime);
    expect(out.rows.map((r) => r.name)).toEqual(["cpu_pct", "cpu_pct"]);
    expect(out.meta.metrics).toEqual(["cpu_pct"]);
    // a panel that names the sweep metric keeps it; other panel types are left alone
    const listed: PanelSpec = { type: "curves", data: { metrics: ["sweep/rps"] } };
    expect(withoutSweeps(result, listed)).toBe(result);
    const table = { type: "table" as const, title: "t", rows, meta: {} };
    expect(withoutSweeps(table, { type: "table" })).toBe(table);
  });

  test("KindPanels draws the over-time panel without the sweep", async () => {
    mockApi({
      "POST /api/v1/tasks/p/t/views/query": { panels: [{ type: "curves", title: "over time", rows, meta: {} }] },
    });
    renderWithClient(<KindPanels project="p" task="t" runId="R" specs={[overTime]} startIndex={0} />, {
      registry: fakeRegistry(["curves"]),
    });
    const panel = await screen.findByRole("region", { name: "a over time" });
    expect(within(panel).getByTestId("panel-curves").textContent).toBe("over time:2");
  });
});

test("an explicit ?example= wins over the failed one", async () => {
  const calls = mockApi(traceRoutes("T-001"));
  renderWithClient(
    <KindPanels project="p" task="t" runId="R" specs={SPECS} example="T-001" startIndex={0} />,
    { registry: fakeRegistry(["curves", "trace"]) },
  );
  await screen.findByRole("region", { name: "b Trajectory · T-001" });
  expect(calls.some((c) => c.url === "/api/v1/runs/R/traces/T-001")).toBe(true);
  expect(calls.some((c) => c.url === "/api/v1/runs/R/traces/T-014")).toBe(false);
});

test("LogView shows the tail, its size, and a close link", async () => {
  mockApi({
    "GET /api/v1/runs/R/logs?stream=stderr": { stream: "stderr", text: "Traceback: boom\n", offset: 1500, size: 1500 },
  });
  renderWithClient(<LogView runId="R" stream="stderr" letter="a" />);
  const region = screen.getByRole("region", { name: "a stderr" });
  expect((await within(region).findByText("Traceback: boom")).tagName).toBe("PRE");
  expect(region.querySelector(".aside")?.textContent).toBe("1.5 KB");
  expect(within(region).getByRole("link", { name: "close" }).getAttribute("href")).toBe("/r/R");
});
