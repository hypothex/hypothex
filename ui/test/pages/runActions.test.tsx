import { afterEach, describe, expect, mock, test } from "bun:test";
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
    renderWithClient(<RunActions record={makeRecord()} />, { navigate });
    fireEvent.click(screen.getByRole("button", { name: "Rerun" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/r/NEW"));
    const body = calls[0]?.body as Record<string, unknown>;
    expect(typeof body.command_id).toBe("string");
    expect(body.created_by).toBe("human");
  });

  test("Stop is enabled only while the run is active", async () => {
    const calls = mockApi({ [`POST /api/v1/runs/${RUN_SVM}/stop`]: { run_id: RUN_SVM, status: "killed" } });
    renderWithClient(<RunActions record={makeRecord()} />);
    expect(screen.getByRole("button", { name: "Stop" }).hasAttribute("disabled")).toBe(true);
    cleanup();
    renderWithClient(<RunActions record={makeRecord({ status: "running", ended_at: null })} />);
    const stop = screen.getByRole("button", { name: "Stop" });
    expect(stop.hasAttribute("disabled")).toBe(false);
    fireEvent.click(stop);
    await waitFor(() => expect(calls.map((c) => c.url)).toEqual([`/api/v1/runs/${RUN_SVM}/stop`]));
  });

  test("shows the server error of a failed action", async () => {
    mockApi({
      [`POST /api/v1/runs/${RUN_SVM}/reeval`]: new HttpReply(400, {
        error: "run has no predictions to score",
        type: "EvalError",
      }),
    });
    renderWithClient(<RunActions record={makeRecord()} />);
    fireEvent.click(screen.getByRole("button", { name: "Re-evaluate" }));
    expect((await screen.findByRole("alert")).textContent).toBe("run has no predictions to score");
  });
});
