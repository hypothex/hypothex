import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { QueryResponse, ViewDetail, ViewInfo } from "../../src/pages/components/types";
import { TaskPage, boardMeta } from "../../src/pages/Task";
import { makeBoard } from "./fixtures";
import { type Call, HttpReply, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const BASE = "/api/v1/tasks/toy-classifier/toy-test";

const VIEWS: ViewInfo[] = [
  { name: "overview", title: "Overview", origin: "preset", path: null, kind: "generic" },
  {
    name: "route-quality",
    title: "route quality",
    origin: "file",
    path: "/repo/.hypothex/views/toy-test/route-quality.yaml",
    kind: null,
  },
];

function detail(info: ViewInfo): ViewDetail {
  return {
    info,
    text: `title: ${info.title}\n`,
    view: {
      title: info.title,
      panels: [
        { type: "stat_strip", title: "Best", data: {}, layout: { span: 4, row: null } },
        { type: "leaderboard", title: "All ideas", data: {}, layout: { span: 8, row: null } },
      ],
    },
  };
}

const PANELS: QueryResponse = {
  panels: [
    { type: "stat_strip", title: "Best", rows: [{ label: "solved v2", value: "0.733" }], meta: {} },
    { type: "leaderboard", title: "All ideas", rows: [{}, {}], meta: {} },
  ],
};

function routes(view: string): Record<string, unknown> {
  const info = VIEWS.find((v) => v.name === view) as ViewInfo;
  return {
    [`GET ${BASE}/leaderboard`]: makeBoard(),
    [`GET ${BASE}/views`]: VIEWS,
    [`GET ${BASE}/views/${view}`]: detail(info),
    [`POST ${BASE}/views/query`]: PANELS,
    [`POST ${BASE}/reeval`]: { evaluated: 12 },
  };
}

const registry = fakeRegistry(["stat_strip", "leaderboard"]);

test("boardMeta counts configs and runs and lists metric versions", () => {
  expect(boardMeta(makeBoard())).toEqual(["2 configs, 6 runs", "accuracy v1", "macro_f1 v1"]);
  expect(boardMeta({ ...makeBoard(), needs_reeval: ["r1"] }).at(-1)).toBe("1 need re-eval");
});

describe("TaskPage", () => {
  test("renders headline, tabs, and the active view's lettered panels", async () => {
    const calls = mockApi(routes("route-quality"));
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" view="route-quality" />, {
      registry,
    });
    const h1 = await screen.findByRole("heading", { level: 1, name: "SVM +0.037 over rf, p = 0.15" });
    expect(h1).toBeTruthy();
    expect(screen.getByText("generic")).toBeTruthy();
    expect(screen.getByText("2 configs, 6 runs")).toBeTruthy();

    const tabs = screen.getByRole("navigation", { name: "Views" });
    const overview = within(tabs).getByRole("link", { name: "Overview preset" });
    expect(overview.getAttribute("href")).toBe("/t/toy-classifier/toy-test");
    expect(overview.getAttribute("aria-current")).toBeNull();
    const active = within(tabs).getByRole("link", { name: "route quality" });
    expect(active.getAttribute("href")).toBe("/t/toy-classifier/toy-test?view=route-quality");
    expect(active.getAttribute("aria-current")).toBe("page");
    expect(within(tabs).getByRole("link", { name: "+ view" }).getAttribute("href")).toBe(
      "/t/toy-classifier/toy-test/edit/new",
    );
    expect(within(tabs).getByRole("link", { name: "Edit" }).getAttribute("href")).toBe(
      "/t/toy-classifier/toy-test/edit/route-quality",
    );

    const best = await screen.findByRole("region", { name: "a Best" });
    expect(best.style.gridColumn).toBe("span 4");
    const ideas = screen.getByRole("region", { name: "b All ideas" });
    expect(ideas.style.gridColumn).toBe("span 8");
    expect(within(ideas).getByTestId("panel-leaderboard").textContent).toBe("All ideas:2");
    expect(within(tabs).getByText("2 panels")).toBeTruthy();

    const query = calls.find((c: Call) => c.url === `${BASE}/views/query`);
    expect(query?.body).toEqual({ name: "route-quality" });
  });

  test("defaults to the overview preset, which has no Edit button", async () => {
    const calls = mockApi(routes("overview"));
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    const tabs = screen.getByRole("navigation", { name: "Views" });
    expect(within(tabs).getByRole("link", { name: "Overview preset" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(within(tabs).queryByRole("link", { name: "Edit" })).toBeNull();
    expect(calls.find((c) => c.url === `${BASE}/views/query`)?.body).toEqual({ name: "overview" });
  });

  test("Re-evaluate all posts to the task reeval route with a command_id", async () => {
    const calls = mockApi(routes("overview"));
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "Re-evaluate all" }));
    await waitFor(() => expect(calls.some((c) => c.url === `${BASE}/reeval`)).toBe(true));
    const body = calls.find((c) => c.url === `${BASE}/reeval`)?.body as Record<string, unknown>;
    expect(typeof body.command_id).toBe("string");
    expect(body.created_by).toBe("human");
  });

  test("shows the error for an unknown view", async () => {
    mockApi({
      ...routes("overview"),
      [`GET ${BASE}/views/nope`]: new HttpReply(404, { error: "no view 'nope' for toy-test", type: "StoreError" }),
      [`POST ${BASE}/views/query`]: new HttpReply(404, { error: "no view 'nope' for toy-test", type: "StoreError" }),
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" view="nope" />, { registry });
    expect((await screen.findByRole("alert")).textContent).toBe("no view 'nope' for toy-test");
    expect(screen.queryByRole("region")).toBeNull();
  });
});
