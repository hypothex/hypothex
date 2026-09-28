import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { outlineView } from "../../src/editor/YamlEditor";
import type { ViewSpec } from "../../src/api/models";
import { cliCommand, isViewName, metricOf, NEW_VIEW_TEXT, ViewEditor } from "../../src/pages/ViewEditor";

const VIEWS = "/api/v1/tasks/toy/toy-acc/views";
const GOOD = "title: acc only\npanels:\n  - type: leaderboard\n    title: board\n    data: {metrics: [accuracy]}\n";
// Same view with the metric one letter off, on line 5, as in the backend API tests; the
// message is the backend's exact, unquoted text.
const BAD = GOOD.replace("[accuracy]", "[acuracy]");
const BAD_ISSUE = {
  line: 5,
  path: "panels[0].data.metrics[0]",
  message: "unknown metric acuracy",
  suggestion: "accuracy",
};
// A view that inherits the task's own kind (generic) and adds one narrow panel.
const FROM_TEXT =
  "title: with preset\nfrom: generic\npanels:\n  - type: markdown\n    title: Note\n    text: hi\n    layout: {span: 4}\n";
// A view on this generic task that inherits another kind's preset and replaces its
// `Changes` panel by title (resolve_view keeps the preset position).
const CROSS_TEXT =
  "title: iteration board\nfrom: agent_iteration\npanels:\n  - type: markdown\n    title: Changes\n    text: see PR\n    layout: {span: 6}\n";
// `POST views/validate` returns `resolve_view(view)` (contract 2): preset panels with
// their layouts first, the view's panels replacing same-title ones or appended, no `from`.
const RESOLVED: Record<string, ViewSpec> = {
  [FROM_TEXT]: {
    title: "with preset",
    panels: [
      { type: "stat_strip", title: "Summary", layout: { span: 12, row: 1 } },
      { type: "leaderboard", title: "Leaderboard", layout: { span: 12, row: 2 } },
      { type: "markdown", title: "Note", text: "hi", layout: { span: 4, row: null } },
    ],
  },
  [CROSS_TEXT]: {
    title: "iteration board",
    panels: [
      { type: "stat_strip", title: "Summary", layout: { span: 12, row: 1 } },
      { type: "scatter", title: "Solved by version", layout: { span: 12, row: 2 } },
      { type: "scatter", title: "$ per solved", layout: { span: 6, row: 3 } },
      { type: "markdown", title: "Changes", text: "see PR", layout: { span: 6, row: null } },
      { type: "grid", title: "Flips", layout: { span: 12, row: 4 } },
      { type: "leaderboard", title: "Leaderboard", layout: { span: 12, row: 5 } },
    ],
  },
};

interface Call {
  method: string;
  url: string;
  body: Record<string, unknown> | null;
}

let calls: Call[] = [];
let docText = GOOD;
let putStatus = 200;
const realFetch = globalThis.fetch;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** A fake view server: validation fails on "acuracy"; panels come from the YAML outline. */
function fakeServer(url: string, method: string, body: Record<string, unknown> | null): Response {
  if (url.endsWith("/leaderboard")) return json(200, { primary: "accuracy/value" });
  if (url === `${VIEWS}/validate`) {
    const text = String(body?.text);
    if (text.includes("acuracy")) return json(200, { ok: false, issues: [BAD_ISSUE] });
    if (RESOLVED[text]) return json(200, { ok: true, issues: [], view: RESOLVED[text] });
    const panels = outlineView(text).panels.map((p) => ({
      type: "leaderboard",
      title: p.title,
      layout: { span: 12, row: null },
    }));
    return json(200, { ok: true, issues: [], view: { title: text.split("\n")[0].slice(7), panels } });
  }
  if (url === `${VIEWS}/query`) {
    // the editor sends the validated view, already resolved: one result per panel
    const view = body?.view as ViewSpec;
    return json(200, {
      panels: (view.panels ?? []).map((p) => ({
        type: p.type,
        title: p.title ?? "",
        rows: [],
        meta: {},
      })),
    });
  }
  if (method === "GET" && (url === `${VIEWS}/acc` || url === `${VIEWS}/overview`)) {
    return json(200, {
      info: { name: "acc", title: "acc only", origin: "file", path: "/r/acc.yaml", kind: "generic" },
      text: docText,
      view: {},
    });
  }
  if (method === "PUT") {
    if (putStatus !== 200) {
      return json(putStatus, { error: "view 'acc' is invalid", type: "ViewValidationError", issues: [BAD_ISSUE] });
    }
    return json(200, { info: {}, view: {} });
  }
  return json(404, { error: "not found", type: "StoreError" });
}

beforeEach(() => {
  calls = [];
  docText = GOOD;
  putStatus = 200;
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ method, url, body });
    return fakeServer(url, method, body);
  }) as unknown as typeof fetch;
});

afterEach(() => {
  cleanup();
  globalThis.fetch = realFetch;
});

function renderEditor(view: string, onSaved = mock((_name: string) => {})) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ViewEditor
        project="toy"
        task="toy-acc"
        view={view}
        onSaved={onSaved}
        renderPanel={(r) => <p>{`${r.type} body`}</p>}
      />
    </QueryClientProvider>,
  );
  return onSaved;
}

const validateCalls = () => calls.filter((c) => c.url === `${VIEWS}/validate`);
const status = () => screen.getByTestId("ed-status").textContent ?? "";
const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

describe("helpers", () => {
  test("cliCommand writes a heredoc file and adds it", () => {
    expect(cliCommand("toy", "toy-acc", "acc", "title: a\npanels: []")).toBe(
      "cat > /tmp/hx-view-acc.yaml <<'YAML'\ntitle: a\npanels: []\nYAML\n" +
        "hx view add toy-acc --file /tmp/hx-view-acc.yaml --name acc -p toy",
    );
  });

  test("cliCommand picks a heredoc tag that is not a line of the text", () => {
    const out = cliCommand("p", "t", "v", "text: |\n  YAML\nYAML\n");
    expect(out.split("\n")[0]).toBe("cat > /tmp/hx-view-v.yaml <<'YAML_'");
    expect(out.split("\n")[4]).toBe("YAML_");
  });

  test("isViewName and metricOf", () => {
    expect(["acc", "route_quality", "a-1"].map(isViewName)).toEqual([true, true, true]);
    expect(["", "overview", "Bad", "-x", "a b"].map(isViewName)).toEqual([false, false, false, false, false]);
    expect([metricOf("accuracy/value"), metricOf("solved@v2/value"), metricOf("")]).toEqual([
      "accuracy",
      "solved@v2",
      "metric",
    ]);
  });

});

describe("ViewEditor", () => {
  test("loads the view, validates it once, previews it, and selects panels", async () => {
    renderEditor("acc");
    await waitFor(() => expect(status()).toContain("✓ valid · 1 panel"));
    expect(validateCalls().map((c) => c.body?.text)).toEqual([GOOD]);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Edit acc only");
    const board = await screen.findByRole("region", { name: "board" });
    expect(board.textContent).toContain("leaderboard body");
    expect(button("Save").disabled).toBe(true);
    expect(button("Discard").disabled).toBe(true);
    fireEvent.click(board);
    await waitFor(() => expect(screen.getByTestId("ruler-label").textContent).toBe("a: span 12, row 1"));
  });

  test("palette inserts at the cursor, validation is debounced, Save PUTs the text", async () => {
    const onSaved = renderEditor("acc");
    await waitFor(() => expect(status()).toContain("✓ valid"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/leaderboard"))).toBe(true));
    fireEvent.click(button("stat strip"));
    fireEvent.click(button("table"));
    const expected =
      GOOD +
      "  - type: stat_strip\n    title: New stat strip\n    data: {metrics: [accuracy], pick: best}\n" +
      "    layout: {span: 12}\n" +
      "  - type: table\n    title: New table\n    data: {source: runs, fields: [run_id, status, created_by]}\n" +
      "    layout: {span: 12}\n";
    expect(screen.getByText("● unsaved")).toBeDefined();
    await waitFor(() => expect(status()).toContain("✓ valid · 3 panels"));
    // Two edits inside one 300 ms window: one validate call for the final text.
    expect(validateCalls().map((c) => c.body?.text)).toEqual([GOOD, expected]);
    await waitFor(() => expect(button("Save").disabled).toBe(false));
    fireEvent.click(button("Save"));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("acc"));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.url).toBe(`${VIEWS}/acc`);
    expect(put?.body?.text).toBe(expected);
    expect(typeof put?.body?.command_id).toBe("string");
    expect(screen.queryByText("● unsaved")).toBeNull();
    expect(button("Save").disabled).toBe(true);
  });

  test("an invalid view marks the line, blocks Save, and Discard restores the text", async () => {
    docText = BAD;
    const container = document.body;
    renderEditor("acc");
    await waitFor(() => expect(status()).toContain("✕ 1 error"));
    expect(button("ln 5")).toBeDefined();
    await waitFor(() => expect(container.querySelector(".cm-lintRange-error")?.textContent).toBe("acuracy"));
    fireEvent.click(button("markdown"));
    expect(screen.getByText("● unsaved")).toBeDefined();
    await waitFor(() => expect(validateCalls().length).toBe(2));
    await waitFor(() => expect(status()).toContain("✕ 1 error"));
    expect(button("Save").disabled).toBe(true);
    expect(button("Save").title).toBe("Fix 1 error to save");
    fireEvent.click(button("Discard"));
    expect(screen.queryByText("● unsaved")).toBeNull();
    expect(button("Discard").disabled).toBe(true);
  });

  test("a new view needs a valid name; Copy as CLI copies the command", async () => {
    const writeText = mock(async (_s: string) => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const onSaved = renderEditor("new");
    await waitFor(() => expect(status()).toContain("✓ valid · 0 panels"));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("New view");
    expect(calls.some((c) => c.method === "GET" && c.url.includes("/views/"))).toBe(false);
    const nameBox = screen.getByLabelText("Name");
    expect(button("Save").disabled).toBe(true);
    expect(button("Copy as CLI").disabled).toBe(true);
    fireEvent.change(nameBox, { target: { value: "overview" } });
    expect(button("Save").disabled).toBe(true);
    fireEvent.change(nameBox, { target: { value: "acc2" } });
    expect(button("Save").disabled).toBe(false);
    await act(async () => fireEvent.click(button("Copy as CLI")));
    expect(writeText).toHaveBeenCalledWith(cliCommand("toy", "toy-acc", "acc2", NEW_VIEW_TEXT));
    expect(screen.getByRole("button", { name: "Copied" })).toBeDefined();
    fireEvent.click(button("Save"));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("acc2"));
    expect(calls.find((c) => c.method === "PUT")?.url).toBe(`${VIEWS}/acc2`);
  });

  test("the overview preset saves only under a new name, even unchanged", async () => {
    const onSaved = renderEditor("overview");
    await waitFor(() => expect(status()).toContain("✓ valid · 1 panel"));
    expect(screen.queryByText("● unsaved")).toBeNull();
    expect(button("Save").disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "acc_copy" } });
    expect(button("Save").disabled).toBe(false);
    fireEvent.click(button("Save"));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("acc_copy"));
    const put = calls.find((c) => c.method === "PUT");
    expect([put?.url, put?.body?.text]).toEqual([`${VIEWS}/acc_copy`, GOOD]);
  });

  const asides = async (title: string) =>
    (await screen.findByRole("region", { name: title })).querySelector(".aside")?.textContent;

  test("a from: view previews the resolved panels with the preset's layouts and counts them", async () => {
    docText = FROM_TEXT;
    renderEditor("acc");
    await waitFor(() => expect(status()).toContain("✓ valid · 3 panels"));
    expect(await asides("Summary")).toBe("12/12");
    expect(await asides("Leaderboard")).toBe("12/12");
    expect(await asides("Note")).toBe("4/12");
    // the resolved view is what gets previewed; no extra preset fetch
    const query = calls.find((c) => c.url === `${VIEWS}/query`);
    const sent = (query?.body?.view as ViewSpec).panels ?? [];
    expect(sent.map((p) => p.title)).toEqual(["Summary", "Leaderboard", "Note"]);
    expect(calls.some((c) => c.method === "GET" && c.url === `${VIEWS}/overview`)).toBe(false);
  });

  test("a from: of another kind previews that kind's resolved panels", async () => {
    // the task is generic; the view inherits agent_iteration and replaces its Changes panel
    docText = CROSS_TEXT;
    renderEditor("acc");
    await waitFor(() => expect(status()).toContain("✓ valid · 6 panels"));
    expect(await asides("Solved by version")).toBe("12/12");
    expect(await asides("$ per solved")).toBe("6/12");
    expect(await asides("Changes")).toBe("6/12");
    const changes = await screen.findByRole("region", { name: "Changes" });
    expect(changes.textContent).toContain("markdown body");
    expect(await asides("Leaderboard")).toBe("12/12");
    const query = calls.find((c) => c.url === `${VIEWS}/query`);
    expect((query?.body?.view as ViewSpec).panels?.length).toBe(6);
    expect(calls.some((c) => c.method === "GET" && c.url === `${VIEWS}/overview`)).toBe(false);
  });

  test("a 400 from Save shows the error and the server's issues", async () => {
    putStatus = 400;
    const onSaved = renderEditor("acc");
    await waitFor(() => expect(status()).toContain("✓ valid"));
    fireEvent.click(button("markdown"));
    await waitFor(() => expect(button("Save").disabled).toBe(false));
    fireEvent.click(button("Save"));
    expect((await screen.findByRole("alert")).textContent).toBe("view 'acc' is invalid");
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByText("● unsaved")).toBeDefined();
  });
});
