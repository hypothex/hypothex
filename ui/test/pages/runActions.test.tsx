import { afterEach, describe, expect, mock, test } from "bun:test";
import { QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { Notes, parseNotes } from "../../src/pages/components/Notes";
import { RunActions } from "../../src/pages/components/RunActions";
import { RUN_SVM, makeRecord } from "./fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const TWO_NOTES =
  "\n## 2026-09-26T21:03:56.036288+00:00 — agent:acceptance\n\nSVM beats rf.\n" +
  "\n## 2026-09-26T22:10:00+00:00 — human\n\nTry C=100.\nAnd gamma=0.1.\n";

describe("parseNotes", () => {
  test("splits header blocks", () => {
    expect(parseNotes(TWO_NOTES)).toEqual([
      { at: "2026-09-26T21:03:56.036288+00:00", author: "agent:acceptance", text: "SVM beats rf." },
      { at: "2026-09-26T22:10:00+00:00", author: "human", text: "Try C=100.\nAnd gamma=0.1." },
    ]);
  });

  test("hand-written text without headers is one entry; blank is none", () => {
    expect(parseNotes("just a thought\n")).toEqual([{ at: "", author: "", text: "just a thought" }]);
    expect(parseNotes("  \n")).toEqual([]);
  });
});

describe("Notes", () => {
  test("shows the latest note and More reveals the rest", () => {
    mockApi({});
    renderWithClient(<Notes runId={RUN_SVM} notes={TWO_NOTES} />);
    expect(screen.getByText(/Try C=100/)).toBeTruthy();
    expect(screen.queryByText("SVM beats rf.")).toBeNull();
    expect(screen.getByText("2026-09-26 22:10")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByText("SVM beats rf.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Less" })).toBeTruthy();
  });

  test("Add note posts the text as the human and closes the editor", async () => {
    const calls = mockApi({ [`POST /api/v1/runs/${RUN_SVM}/notes`]: { ok: true } });
    renderWithClient(<Notes runId={RUN_SVM} notes="" />);
    expect(screen.getByText("none")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    const save = screen.getByRole("button", { name: "Save" });
    expect(save.hasAttribute("disabled")).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: "Note" }), { target: { value: "  tried C=100  " } });
    fireEvent.click(save);
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "Note" })).toBeNull());
    const body = calls.find((c) => c.method === "POST")?.body as Record<string, unknown>;
    expect(body.text).toBe("tried C=100");
    expect(body.author).toBe("human");
    expect(body.created_by).toBe("human");
    expect(typeof body.command_id).toBe("string");
  });
});

describe("RunActions", () => {
  test("Rerun posts a command_id and opens the new run", async () => {
    const calls = mockApi({ [`POST /api/v1/runs/${RUN_SVM}/rerun`]: { run_id: "NEW" } });
    const navigate = mock((_href: string) => {});
    renderWithClient(<RunActions served record={makeRecord()} />, { navigate });
    fireEvent.click(screen.getByRole("button", { name: "Rerun" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/r/NEW"));
    const body = calls[0]?.body as Record<string, unknown>;
    expect(typeof body.command_id).toBe("string");
    expect(body.created_by).toBe("human");
  });

  test("Stop is enabled only while the run is active", async () => {
    const calls = mockApi({ [`POST /api/v1/runs/${RUN_SVM}/stop`]: { run_id: RUN_SVM, status: "killed" } });
    renderWithClient(<RunActions served record={makeRecord()} />);
    expect(screen.getByRole("button", { name: "Stop" }).hasAttribute("disabled")).toBe(true);
    cleanup();
    renderWithClient(<RunActions served record={makeRecord({ status: "running", ended_at: null })} />);
    const stop = screen.getByRole("button", { name: "Stop" });
    expect(stop.hasAttribute("disabled")).toBe(false);
    fireEvent.click(stop);
    fireEvent.click(screen.getByRole("button", { name: "Stop ✓?" }));
    await waitFor(() => expect(calls.map((c) => c.url)).toEqual([`/api/v1/runs/${RUN_SVM}/stop`]));
    expect((calls[0]?.body as Record<string, unknown>).only_queued).not.toBe(true);
  });

  test("shows the server error of a failed action", async () => {
    mockApi({
      [`POST /api/v1/runs/${RUN_SVM}/reeval`]: new HttpReply(400, {
        error: "run has no predictions to score",
        type: "EvalError",
      }),
    });
    renderWithClient(<RunActions served record={makeRecord()} />);
    fireEvent.click(screen.getByRole("button", { name: "Re-evaluate" }));
    expect((await screen.findByRole("alert")).textContent).toBe("run has no predictions to score");
  });
});

test("Re-infer requires a confirmed infer stage (UI-F7)", async () => {
  const calls = mockApi({ [`POST /api/v1/runs/${RUN_SVM}/reinfer`]: { run_id: "INFER" } });
  for (const inferStage of [undefined, false]) {
    const view = renderWithClient(<RunActions served record={makeRecord()} inferStage={inferStage} />);
    const button = screen.getByRole("button", { name: "Re-infer" });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.title).toBe(inferStage === false ? "Task has no infer stage" : "Infer stage not loaded");
    fireEvent.click(button);
    view.unmount();
  }
  expect(calls).toHaveLength(0);
  const navigate = mock((_href: string) => {});
  renderWithClient(<RunActions served record={makeRecord()} inferStage={true} />, { navigate });
  fireEvent.click(screen.getByRole("button", { name: "Re-infer" }));
  await waitFor(() => expect(navigate).toHaveBeenCalledWith("/r/INFER"));
});

test("run re-evaluation reports skipped reasons, counts and warnings (UI-F3)", async () => {
  mockApi({
    [`POST /api/v1/runs/${RUN_SVM}/reeval`]: {
      evaluated: [], skipped: { [RUN_SVM]: "no predictions" }, warnings: [],
    },
  });
  renderWithClient(<RunActions served record={makeRecord()} />);
  fireEvent.click(screen.getByRole("button", { name: "Re-evaluate" }));
  expect((await screen.findByRole("status", { name: "Re-evaluate" })).textContent).toBe(
    "0 re-scored · 1 skipped: no predictions",
  );
  mockApi({
    [`POST /api/v1/runs/${RUN_SVM}/reeval`]: {
      evaluated: [RUN_SVM], skipped: {}, warnings: ["metric version changed"],
    },
  });
  fireEvent.click(screen.getByRole("button", { name: "Re-evaluate" }));
  expect(screen.queryByRole("status", { name: "Re-evaluate" })).toBeNull();
  await waitFor(() => expect(screen.getByRole("status", { name: "Re-evaluate" }).textContent).toBe(
    "1 re-scored · 1 warning",
  ));
  expect(screen.getByRole("status", { name: "Re-evaluate" }).title).toContain("metric version changed");
});

test("an old run's pending re-evaluation never becomes the new run's feedback", async () => {
  let finish!: (value: unknown) => void;
  const response = new Promise((resolve) => { finish = resolve; });
  const calls = mockApi({ [`POST /api/v1/runs/${RUN_SVM}/reeval`]: () => response });
  const view = renderWithClient(<RunActions served record={makeRecord()} />);
  fireEvent.click(screen.getByRole("button", { name: "Re-evaluate" }));
  await waitFor(() => expect(calls).toHaveLength(1));
  view.rerender(
    <QueryClientProvider client={view.client}>
      <RunActions served record={makeRecord({ run_id: "OTHER" })} />
    </QueryClientProvider>,
  );
  finish({ evaluated: [RUN_SVM], skipped: {}, warnings: [] });
  await waitFor(() => expect(screen.getByRole("button", { name: "Re-evaluate" }).hasAttribute("disabled")).toBe(false));
  expect(screen.queryByRole("status", { name: "Re-evaluate" })).toBeNull();
});

test("unserved run actions are disabled with a known-unmapped explanation", () => {
  mockApi({});
  renderWithClient(<RunActions record={makeRecord({ status: "running" })} served={false} hostsLoaded />);
  for (const name of ["Rerun", "Re-infer", "Re-evaluate", "Stop"]) {
    const button = screen.getByRole("button", { name });
    expect(button.hasAttribute("disabled")).toBe(true);
    expect(button.title).toContain("No configured host");
  }
});

test("Re-infer needs both a serving host and an infer stage after integration", () => {
  const calls = mockApi({});
  const tree = (served: boolean, inferStage: boolean) => (
    <RunActions record={makeRecord()} served={served} hostsLoaded inferStage={inferStage} />
  );
  const { client, rerender } = renderWithClient(tree(false, true));
  const button = screen.getByRole("button", { name: "Re-infer" });
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(button.title).toContain("No configured host");
  fireEvent.click(button);
  rerender(<QueryClientProvider client={client}>{tree(true, false)}</QueryClientProvider>);
  expect(button.hasAttribute("disabled")).toBe(true);
  expect(button.title).toBe("Task has no infer stage");
  fireEvent.click(button);
  rerender(<QueryClientProvider client={client}>{tree(true, true)}</QueryClientProvider>);
  expect(button.hasAttribute("disabled")).toBe(false);
  expect(calls).toHaveLength(0);
});
test("Stop requires two clicks and disarms on Escape and blur", async () => {
  const calls = mockApi({ [`POST /api/v1/runs/${RUN_SVM}/stop`]: {} });
  renderWithClient(<RunActions served record={makeRecord({ status: "running" })} />);
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  expect(calls).toHaveLength(0);
  fireEvent.keyDown(screen.getByRole("button", { name: "Stop ✓?" }), { key: "Escape" });
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  fireEvent.blur(screen.getByRole("button", { name: "Stop ✓?" }));
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  fireEvent.click(screen.getByRole("button", { name: "Stop ✓?" }));
  await waitFor(() => expect(calls).toHaveLength(1));
});

test("Stop disarms when the record changes or its serving status is revoked", () => {
  mockApi({});
  const first = makeRecord({ status: "running" });
  const { rerender, client } = renderWithClient(<RunActions served record={first} />);
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  rerender(<QueryClientProvider client={client}><RunActions served record={{ ...first, run_id: "second" }} /></QueryClientProvider>);
  expect(screen.getByRole("button", { name: "Stop" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  rerender(<QueryClientProvider client={client}><RunActions record={{ ...first, run_id: "second" }} served={false} hostsLoaded /></QueryClientProvider>);
  expect(screen.getByRole("button", { name: "Stop" }).hasAttribute("disabled")).toBe(true);
});

test("armed Stop expires after three seconds without sending anything", async () => {
  const calls = mockApi({});
  renderWithClient(<RunActions served record={makeRecord({ status: "running" })} />);
  fireEvent.click(screen.getByRole("button", { name: "Stop" }));
  expect(screen.getByRole("button", { name: "Stop ✓?" })).toBeTruthy();
  await waitFor(() => expect(screen.queryByRole("button", { name: "Stop ✓?" }) === null).toBe(true), { timeout: 3500 });
  expect(calls).toHaveLength(0);
});
