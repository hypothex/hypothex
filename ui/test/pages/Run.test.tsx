import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, screen, waitFor } from "@testing-library/react";
import { RunPage, asLogStream } from "../../src/pages/Run";
import { RUN_SVM, SVM_HYPOTHESIS, makeBoard, makeDetail } from "./fixtures";
import { HttpReply, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const TASK = "/api/v1/tasks/toy-classifier/toy-test";

function routes(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail(),
    [`GET ${TASK}/kind`]: {
      kind: "generic",
      run_view: [{ type: "curves", title: "Metrics", data: {}, layout: { span: 12, row: null } }],
    },
    [`GET ${TASK}/leaderboard`]: makeBoard(),
    [`POST ${TASK}/views/query`]: { panels: [{ type: "curves", title: "Metrics", rows: [{}, {}], meta: {} }] },
    ...extra,
  };
}

const registry = fakeRegistry(["curves"]);

function regionNames(): (string | null)[] {
  return screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
}

function statValues(): (string | null)[] {
  return [...document.querySelectorAll(".stats dd")].map((d) => d.textContent);
}

test("asLogStream accepts only known streams", () => {
  expect(asLogStream("stderr")).toBe("stderr");
  expect(asLogStream("../etc/passwd")).toBeNull();
  expect(asLogStream(undefined)).toBeNull();
});

describe("RunPage", () => {
  test("renders title, crumb, stats, kind panels, then Where, Scores, Notes", async () => {
    const calls = mockApi(routes());
    renderWithClient(<RunPage runId={RUN_SVM} />, { registry });
    const h1 = await screen.findByRole("heading", { level: 1 });
    expect(h1.textContent).toBe(SVM_HYPOTHESIS);
    expect(h1.className).toBe("headline long");
    await screen.findByRole("region", { name: "a Metrics" });
    await waitFor(() =>
      expect(document.querySelector(".crumb")?.textContent).toBe(
        `toy-classifier/toy-test/RBF-kernel SVM/${RUN_SVM}generic`,
      ),
    );
    expect(regionNames()).toEqual(["a Metrics", "b Where", "c Scores", "d Notes"]);
    // the leaderboard loads in parallel; the strip fills in once it arrives
    await waitFor(() => expect(statValues()).toEqual(["0.9222", "0.874–0.953", "◇×3", "0.8 s"]));
    expect(screen.getByRole("link", { name: "toy-test" }).getAttribute("href")).toBe("/t/toy-classifier/toy-test");
    const query = calls.find((c) => c.method === "POST")?.body as {
      view: { title: string; panels: { data: { filter: Record<string, string> } }[] };
    };
    expect(query.view.panels[0]?.data.filter).toEqual({ run_id: RUN_SVM });
  });

  test("opens the requested log above the kind panels", async () => {
    mockApi(
      routes({
        [`GET /api/v1/runs/${RUN_SVM}/logs?stream=stderr`]: {
          stream: "stderr",
          text: "Traceback: boom",
          offset: 15,
          size: 15,
        },
      }),
    );
    renderWithClient(<RunPage runId={RUN_SVM} log="stderr" />, { registry });
    await screen.findByRole("region", { name: "b Metrics" });
    expect(regionNames()).toEqual(["a stderr", "b Metrics", "c Where", "d Scores", "e Notes"]);
    expect(await screen.findByText("Traceback: boom")).toBeTruthy();
  });

  test("renders a run that has no task", async () => {
    const calls = mockApi({ [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail({ task: null }) });
    renderWithClient(<RunPage runId={RUN_SVM} />, { registry });
    await screen.findByRole("region", { name: "a Where" });
    expect(regionNames()).toEqual(["a Where", "b Scores", "c Notes"]);
    expect(calls.map((c) => c.url)).toEqual([`/api/v1/runs/${RUN_SVM}`]);
    expect(document.querySelector(".crumb")?.textContent).toBe(
      `toy-classifier/RBF-kernel SVM/${RUN_SVM}`,
    );
    expect(statValues()).toEqual(["0.8 s"]);
  });

  test("shows the error for an unknown run", async () => {
    mockApi({ "GET /api/v1/runs/nope": new HttpReply(404, { error: "no run with id nope", type: "StoreError" }) });
    renderWithClient(<RunPage runId="nope" />, { registry });
    expect((await screen.findByRole("alert")).textContent).toBe("no run with id nope");
  });
});

test("a missing run has a not-found heading and an overview recovery link (UI-F14)", async () => {
  mockApi({ "GET /api/v1/runs/nope": new HttpReply(404, { error: "no run with id nope", type: "StoreError" }) });
  renderWithClient(<RunPage runId="nope" />, { registry });
  expect((await screen.findByRole("heading", { name: "Not found" })).textContent).toBe("Not found");
  expect(screen.getByRole("link", { name: "All projects" }).getAttribute("href")).toBe("/");
  expect(screen.queryByRole("button", { name: "Rerun" })).toBeNull();
  expect(screen.getAllByRole("alert")).toHaveLength(1);
});

test("a run service failure is not presented as not found", async () => {
  mockApi({ "GET /api/v1/runs/nope": new HttpReply(500, { error: "index unavailable", type: "StoreError" }) });
  renderWithClient(<RunPage runId="nope" />, { registry });
  expect((await screen.findByRole("alert")).textContent).toBe("index unavailable");
  expect(screen.queryByRole("heading", { name: "Not found" })).toBeNull();
});

test("the run page reads task stages before enabling Re-infer (UI-F7)", async () => {
  mockApi(routes({ [`GET ${TASK}`]: { stages: { infer: { command: ["python", "infer.py"] } } } }));
  renderWithClient(<RunPage runId={RUN_SVM} />, { registry });
  const button = await screen.findByRole("button", { name: "Re-infer" });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  cleanup();
  mockApi(routes({ [`GET ${TASK}`]: { stages: {} } }));
  renderWithClient(<RunPage runId={RUN_SVM} />, { registry });
  const missing = await screen.findByRole("button", { name: "Re-infer" });
  await waitFor(() => expect(missing.title).toBe("Task has no infer stage"));
  expect(missing.hasAttribute("disabled")).toBe(true);
});

test("run history metadata narrows the active views query before reading curves", async () => {
  const detail = { ...makeDetail(), metric_names: ["loss", "sweep/rps", "step", "lr"] };
  const calls = mockApi(routes({ [`GET /api/v1/runs/${RUN_SVM}`]: detail, [`GET ${TASK}`]: { stages: {} } }));
  renderWithClient(<RunPage runId={RUN_SVM} />, { registry });
  await screen.findByRole("region", { name: "a Metrics" });
  const body = calls.find((c) => c.method === "POST")?.body as {
    view: { panels: { data: { metrics: string[]; max_points: number } }[] };
  };
  expect(body.view.panels[0]?.data.metrics).toEqual(["loss", "lr"]);
  expect(body.view.panels[0]?.data.max_points).toBe(500);
  expect(calls.some((c) => /\/runs\/[^/]+\/metrics/.test(c.url))).toBe(false);
});

test("an unreadable task never grants infer capability", async () => {
  mockApi(routes({ [`GET ${TASK}`]: new HttpReply(500, { error: "task unavailable", type: "StoreError" }) }));
  renderWithClient(<RunPage runId={RUN_SVM} />, { registry });
  const button = await screen.findByRole("button", { name: "Re-infer" });
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(button.title).toBe("Infer stage not loaded");
});

test("a failed task refresh revokes previously cached infer capability", async () => {
  mockApi(routes({ [`GET ${TASK}`]: { stages: { infer: { command: ["infer"] } } } }));
  const view = renderWithClient(<RunPage runId={RUN_SVM} />, { registry });
  const button = await screen.findByRole("button", { name: "Re-infer" });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
  mockApi(routes({ [`GET ${TASK}`]: new HttpReply(500, { error: "task unavailable", type: "StoreError" }) }));
  await view.client.refetchQueries({ queryKey: ["task", "toy-classifier", "toy-test"] });
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(true));
  expect(button.title).toBe("Infer stage not loaded");
});
