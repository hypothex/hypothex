import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { RunName, nameProblem, nameToSend, runTitle, withSeed } from "../../src/run/RunName";
import { RUN_RF, RUN_SVM, makeRecord } from "../pages/fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const NAME_ROUTE = `POST /api/v1/runs/${RUN_SVM}/name`;
const PROPS = { runId: RUN_SVM, display: "model svm · seed 3", derived: "model svm · seed 3", renamed: false };

describe("names", () => {
  test("withSeed appends the seed in run views", () => {
    expect(withSeed("lr 3e-4 · beam 10", 2)).toBe("lr 3e-4 · beam 10 · seed 2");
    expect(withSeed("db v3", null)).toBe("db v3");
  });

  test("runTitle: a rename shows as typed; the derived name carries the seed", () => {
    const run = { name: "svm, tuned C", derived_name: "model svm", renamed: true, seed: 3 };
    expect(runTitle(run, makeRecord())).toEqual({ display: "svm, tuned C", derived: "model svm · seed 3", renamed: true });
    expect(runTitle({ ...run, name: "model svm", renamed: false }, makeRecord())).toEqual({
      display: "model svm · seed 3",
      derived: "model svm · seed 3",
      renamed: false,
    });
  });

  test("runTitle without the task's runs: the record's name, else the hypothesis clause", () => {
    expect(runTitle(null, makeRecord()).display).toBe("RBF-kernel SVM · seed 3");
    expect(runTitle(null, makeRecord({ name: "mine" }))).toEqual({
      display: "mine",
      derived: "RBF-kernel SVM · seed 3",
      renamed: true,
    });
    expect(runTitle(null, makeRecord({ hypothesis: "", seed: null })).display).toBe("run 6f71");
  });

  test("nameProblem and nameToSend", () => {
    expect(nameProblem("a\nb")).toBe("One line only");
    expect(nameProblem("x".repeat(81))).toBe("At most 80 characters");
    expect(nameProblem("  ok  ")).toBeNull();
    expect(nameToSend("   ", "model svm · seed 3")).toBeNull();
    expect(nameToSend("model svm · seed 3", "model svm · seed 3")).toBeNull();
    expect(nameToSend("  svm, tuned C ", "model svm · seed 3")).toBe("svm, tuned C");
  });
});

describe("RunName", () => {
  test("click, type, Enter: the new name shows at once and is posted", async () => {
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const calls = mockApi({
      [NAME_ROUTE]: async () => {
        await gate;
        return makeRecord({ name: "svm, tuned C" });
      },
    });
    renderWithClient(<RunName {...PROPS} />);
    fireEvent.click(screen.getByText("model svm · seed 3"));
    const input = screen.getByRole("textbox", { name: "Run name" }) as HTMLInputElement;
    expect(input.value).toBe("model svm · seed 3");
    fireEvent.change(input, { target: { value: "svm, tuned C" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText("svm, tuned C")).toBeTruthy();
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]?.body).toMatchObject({ name: "svm, tuned C" });
    release();
  });

  test("the pencil opens the editor; Escape and Cancel close it without a request", () => {
    const calls = mockApi({});
    renderWithClient(<RunName {...PROPS} />);
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Run name" }), { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Run name" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("textbox", { name: "Run name" })).toBeNull();
    expect(calls).toHaveLength(0);
  });

  test("saving the unchanged name sends nothing", () => {
    const calls = mockApi({});
    renderWithClient(<RunName {...PROPS} />);
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.queryByRole("textbox", { name: "Run name" })).toBeNull();
    expect(calls).toHaveLength(0);
  });

  test("Reset name posts null and shows the derived name; only a renamed run offers it", async () => {
    const calls = mockApi({ [NAME_ROUTE]: makeRecord() });
    const view = renderWithClient(<RunName {...PROPS} />);
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    expect(screen.queryByRole("button", { name: "Reset name" })).toBeNull();
    view.unmount();
    renderWithClient(<RunName {...PROPS} display="svm, tuned C" renamed />);
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.click(screen.getByRole("button", { name: "Reset name" }));
    expect(screen.getByText("model svm · seed 3")).toBeTruthy();
    await waitFor(() => expect(calls[0]?.body).toMatchObject({ name: null }));
  });

  test("a refused name goes back and shows the server's reason", async () => {
    mockApi({ [NAME_ROUTE]: new HttpReply(422, { error: "name has a newline", type: "ValueError" }) });
    renderWithClient(<RunName {...PROPS} />);
    fireEvent.click(screen.getByText("model svm · seed 3"));
    fireEvent.change(screen.getByRole("textbox", { name: "Run name" }), { target: { value: "new" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("name has a newline");
    expect(screen.getByText("model svm · seed 3")).toBeTruthy();
  });

  test("too long a name is refused before any request and the editor stays open", () => {
    const calls = mockApi({});
    renderWithClient(<RunName {...PROPS} />);
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Run name" }), { target: { value: "x".repeat(81) } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Run name" }), { key: "Enter" });
    expect(screen.getByRole("alert").textContent).toBe("At most 80 characters");
    expect(screen.getByRole("textbox", { name: "Run name" })).toBeTruthy();
    expect(calls).toHaveLength(0);
  });

  test("runIds: a config's rename goes to each of its runs, in order", async () => {
    const calls = mockApi({
      [NAME_ROUTE]: makeRecord({ name: "wide" }),
      [`POST /api/v1/runs/${RUN_RF}/name`]: makeRecord({ run_id: RUN_RF, name: "wide" }),
    });
    renderWithClient(<RunName {...PROPS} runIds={[RUN_SVM, RUN_RF]} />);
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Run name" }), { target: { value: " wide " } });
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Run name" }), { key: "Enter" });
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls.map((c) => [c.url, (c.body as { name: string | null }).name])).toEqual([
      [`/api/v1/runs/${RUN_SVM}/name`, "wide"],
      [`/api/v1/runs/${RUN_RF}/name`, "wide"],
    ]);
  });

  test("runIds: a refused run stops the rest and the old name comes back", async () => {
    const calls = mockApi({
      [NAME_ROUTE]: makeRecord({ name: "wide" }),
      [`POST /api/v1/runs/${RUN_RF}/name`]: new HttpReply(503, { error: "host gpu1 is down", type: "HostError" }),
    });
    renderWithClient(<RunName {...PROPS} runIds={[RUN_SVM, RUN_RF, "run-third"]} />);
    fireEvent.click(screen.getByText("model svm · seed 3"));
    fireEvent.change(screen.getByRole("textbox", { name: "Run name" }), { target: { value: "wide" } });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect((await screen.findByRole("alert")).textContent).toBe("host gpu1 is down");
    expect(screen.getByText("model svm · seed 3")).toBeTruthy();
    expect(calls).toHaveLength(2);
  });

  test('editOn="dblclick": one click on the text does not edit, a double click does', () => {
    mockApi({});
    renderWithClient(<RunName {...PROPS} editOn="dblclick" />);
    fireEvent.click(screen.getByText("model svm · seed 3"));
    expect(screen.queryByRole("textbox", { name: "Run name" })).toBeNull();
    fireEvent.doubleClick(screen.getByText("model svm · seed 3"));
    expect(screen.getByRole("textbox", { name: "Run name" })).toBeTruthy();
  });
});
