import { afterEach, describe, expect, spyOn, test } from "bun:test";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import type { TaskRuns } from "../../src/api/models";
import { getHighlight } from "../../src/task/highlight";
import { RunsSidebar } from "../../src/task/RunsSidebar";
import { type Selection, parseSelection } from "../../src/task/useRunSelection";
import { type Call, HttpReply, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { makeTaskGroup, makeTaskRun, makeTaskRuns } from "./fixtures";

afterEach(restoreFetch);

function Harness({ data, url, opened, patches }: { data: TaskRuns; url: string; opened: string[]; patches: Partial<Selection>[] }) {
  const [sel, setSel] = useState<Selection>(parseSelection(new URLSearchParams(url), { sortDir: "desc" }));
  return (
    <RunsSidebar
      data={data}
      selection={sel}
      onChange={(p) => {
        patches.push(p);
        setSel((s) => ({ ...s, ...p }));
      }}
      onOpen={(id) => opened.push(id)}
    />
  );
}

function setup(data: TaskRuns = makeTaskRuns(), url = "") {
  const opened: string[] = [];
  const patches: Partial<Selection>[] = [];
  renderWithClient(<Harness data={data} url={url} opened={opened} patches={patches} />);
  return { opened, patches };
}

const rows = () => within(screen.getByRole("list", { name: "Run list" })).getAllByRole("listitem");
const row = (i: number) => rows()[i] as HTMLElement;
const nameText = (r: HTMLElement) => r.querySelector<HTMLElement>(".rn-t") as HTMLElement;
const nameOf = (r: HTMLElement) => nameText(r).textContent;
const pause = (ms: number) => act(() => new Promise<void>((resolve) => setTimeout(resolve, ms)));

/** g-b's two runs renamed to "wide beam". */
function renamedB(): TaskRuns {
  const data = makeTaskRuns();
  data.runs = data.runs.map((r) => (r.group_id === "g-b" ? { ...r, name: "wide beam", renamed: true } : r));
  data.groups = data.groups.map((g) => (g.group_id === "g-b" ? { ...g, name: "wide beam" } : g));
  return data;
}

describe("RunsSidebar", () => {
  test("rows: best first, mean ± sd, seeds, live counts, final tag, N/M shown", () => {
    setup();
    expect(screen.getByRole("complementary", { name: "Runs" })).toBeTruthy();
    expect(rows().map(nameOf)).toEqual(["lr 3e-4 · beam 10", "lr 1e-4 · beam 10", "lr 1e-3 · beam 1"]);
    const a = row(0);
    expect(a.className).toContain("best");
    expect(a.tabIndex).toBe(0);
    expect(within(a).getByText("0.9110")).toBeTruthy();
    expect(within(a).getByText("± 0.0014")).toBeTruthy();
    expect(within(a).getByText("3 seeds")).toBeTruthy();
    expect(within(a).getByText("final")).toBeTruthy();
    expect(within(a).getByText("tuner")).toBeTruthy();
    expect(within(a).getByTitle("1 running").textContent).toContain("1");
    expect(within(a).getByTitle("lr 3e-4 · beam 10")).toBeTruthy();
    const c = row(2);
    expect(within(c).getByTitle("1 queued").textContent).toContain("1");
    expect(within(c).getByTitle("1 failed").textContent).toContain("1");
    expect(within(c).getByText("—")).toBeTruthy();
    expect(screen.getByText("3/4 shown")).toBeTruthy();
  });

  test("the superseded chip hides tagged configs by default and shows them when pressed", () => {
    const { patches } = setup();
    const chip = screen.getByRole("button", { name: "1 superseded hidden" });
    expect(chip.getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(chip);
    expect(patches.at(-1)).toEqual({ showSuperseded: true });
    expect(screen.getByRole("button", { name: "Superseded shown" }).getAttribute("aria-pressed")).toBe("false");
    expect(rows()).toHaveLength(4);
    expect(screen.getByText("4/4 shown")).toBeTruthy();
  });

  test("no superseded chip when no run carries the tag", () => {
    const data = makeTaskRuns();
    data.runs = data.runs.map((r) => ({ ...r, tags: r.tags.filter((t) => t !== "superseded") }));
    setup(data);
    expect(screen.queryByRole("button", { name: /superseded/i })).toBeNull();
    expect(screen.getByText("4/4 shown")).toBeTruthy();
  });

  test("the eye hides and shows a config in every panel", () => {
    const { patches, opened } = setup();
    const eye = screen.getByRole("button", { name: "Hide lr 1e-4 · beam 10" });
    expect(eye.getAttribute("aria-pressed")).toBe("true");
    expect(eye.getAttribute("data-identity")).toBe("g-b");
    fireEvent.click(eye);
    expect(patches.at(-1)).toEqual({ hidden: ["g-b"] });
    const show = screen.getByRole("button", { name: "Show lr 1e-4 · beam 10" });
    expect(show.getAttribute("aria-pressed")).toBe("false");
    expect(row(1).className).toContain("off");
    expect(row(1).querySelector<HTMLElement>(".sw")?.style.background).toBe("");
    expect(screen.getByText("2/4 shown")).toBeTruthy();
    fireEvent.click(show);
    expect(patches.at(-1)).toEqual({ hidden: [] });
    expect(opened).toEqual([]);
  });

  test("a row opens the group's latest run on click and Enter; eye and pencil do not", async () => {
    const { opened } = setup();
    fireEvent.click(within(row(1)).getByText("2 seeds"));
    expect(opened).toEqual(["run-b2"]);
    fireEvent.keyDown(row(0), { key: "Enter" });
    expect(opened).toEqual(["run-b2", "run-a3"]);
    fireEvent.click(screen.getByRole("button", { name: "Hide lr 1e-4 · beam 10" }));
    fireEvent.click(screen.getByRole("button", { name: "Rename lr 3e-4 · beam 10" }));
    fireEvent.keyDown(screen.getByRole("textbox", { name: "Run name" }), { key: "Enter" });
    // a click on the name waits out a possible double click, then opens
    fireEvent.click(nameText(row(1)), { detail: 1 });
    expect(opened).toEqual(["run-b2", "run-a3"]);
    await waitFor(() => expect(opened).toEqual(["run-b2", "run-a3", "run-b2"]));
  });

  test("a modified or middle click opens the run in a new tab", () => {
    const open = spyOn(window, "open").mockImplementation(() => null);
    try {
      const { opened } = setup();
      fireEvent.click(within(row(1)).getByText("2 seeds"), { ctrlKey: true });
      fireEvent.click(nameText(row(1)), { metaKey: true });
      fireEvent(nameText(row(1)), new MouseEvent("auxclick", { bubbles: true, button: 1 }));
      expect(open.mock.calls.map((c) => c[0])).toEqual(["/r/run-b2", "/r/run-b2", "/r/run-b2"]);
      expect(opened).toEqual([]);
    } finally {
      open.mockRestore();
    }
  });

  test("rename: double-click on the name opens the editor without opening the run, Escape cancels, Enter renames every run of the config", async () => {
    const calls = mockApi(
      Object.fromEntries(
        ["run-a1", "run-a2", "run-a3"].map((id) => [
          `POST /api/v1/runs/${id}/name`,
          (c: Call) => makeTaskRun({ run_id: id, name: (c.body as { name: string }).name }),
        ]),
      ),
    );
    const { opened } = setup();
    const name = nameText(row(1));
    fireEvent.click(name, { detail: 1 });
    fireEvent.click(name, { detail: 2 });
    fireEvent.doubleClick(name);
    let input = screen.getByRole("textbox", { name: "Run name" }) as HTMLInputElement;
    expect(input.value).toBe("lr 1e-4 · beam 10");
    await pause(400);
    expect(opened).toEqual([]);
    fireEvent.keyDown(input, { key: "Escape" });
    expect(screen.queryByRole("textbox", { name: "Run name" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Rename lr 3e-4 · beam 10" }));
    input = screen.getByRole("textbox", { name: "Run name" }) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "  wide beam  " } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(nameOf(row(0))).toBe("wide beam");
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(calls.map((c) => [c.url, (c.body as { name: string | null }).name])).toEqual([
      ["/api/v1/runs/run-a1/name", "wide beam"],
      ["/api/v1/runs/run-a2/name", "wide beam"],
      ["/api/v1/runs/run-a3/name", "wide beam"],
    ]);
    expect(opened).toEqual([]);
  });

  test("Each run: a run renames alone, with its seed as the derived name", async () => {
    const calls = mockApi({ "POST /api/v1/runs/run-b1/name": (c: Call) => makeTaskRun({ run_id: "run-b1", name: (c.body as { name: string }).name }) });
    setup(makeTaskRuns(), "group=run");
    fireEvent.click(screen.getByRole("button", { name: "Rename lr 1e-4 · beam 10 · seed 1" }));
    const input = screen.getByRole("textbox", { name: "Run name" }) as HTMLInputElement;
    expect(input.value).toBe("lr 1e-4 · beam 10 · seed 1");
    fireEvent.change(input, { target: { value: "b one" } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]?.url).toBe("/api/v1/runs/run-b1/name");
  });

  test("an empty name resets every run of a renamed config", async () => {
    const reply = (id: string) => (c: Call) => makeTaskRun({ run_id: id, name: (c.body as { name: string | null }).name ?? "" });
    const calls = mockApi({ "POST /api/v1/runs/run-b1/name": reply("run-b1"), "POST /api/v1/runs/run-b2/name": reply("run-b2") });
    setup(renamedB());
    fireEvent.click(screen.getByRole("button", { name: "Rename wide beam" }));
    const input = screen.getByRole("textbox", { name: "Run name" });
    fireEvent.change(input, { target: { value: "   " } });
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls.map((c) => [c.url, (c.body as { name: string | null }).name])).toEqual([
      ["/api/v1/runs/run-b1/name", null],
      ["/api/v1/runs/run-b2/name", null],
    ]);
  });

  test("a rejected name shows the server's message on the row and keeps the old name", async () => {
    mockApi({
      "POST /api/v1/runs/run-b1/name": new HttpReply(422, { error: "name is longer than 80 characters", type: "ValueError" }),
    });
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Rename lr 1e-4 · beam 10" }));
    const input = screen.getByRole("textbox", { name: "Run name" });
    fireEvent.change(input, { target: { value: "too long for the server" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect((await within(row(1)).findByRole("alert")).textContent).toBe("name is longer than 80 characters");
    expect(nameOf(row(1))).toBe("lr 1e-4 · beam 10");
  });

  test("sort chip: pick a key, pick it again to flip the direction", () => {
    const { patches } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Sort top1 ↓" }));
    const menu = screen.getByRole("menu", { name: "Sort by" });
    expect(within(menu).getAllByRole("menuitemradio").map((b) => b.textContent)).toEqual(["top1 ↓", "final", "created"]);
    fireEvent.click(within(menu).getByRole("menuitemradio", { name: "created" }));
    expect(patches.at(-1)).toEqual({ sort: { key: "created", dir: "desc" } });
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Sort created ↓" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "created ↓" }));
    expect(patches.at(-1)).toEqual({ sort: { key: "created", dir: "asc" } });
  });

  test("a menu takes focus: first item on open, arrows move, Escape returns to the chip", () => {
    setup();
    const chip = screen.getByRole("button", { name: "Sort top1 ↓" });
    chip.focus();
    fireEvent.click(chip);
    const items = within(screen.getByRole("menu", { name: "Sort by" })).getAllByRole("menuitemradio");
    expect(document.activeElement === (items[0])).toBe(true);
    fireEvent.keyDown(items[0]!, { key: "ArrowDown" });
    expect(document.activeElement === (items[1])).toBe(true);
    fireEvent.keyDown(items[1]!, { key: "ArrowUp" });
    fireEvent.keyDown(items[0]!, { key: "ArrowUp" });
    expect(document.activeElement === (items[items.length - 1])).toBe(true);
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    expect(document.activeElement === (chip)).toBe(true);
  });

  test("a menu closes on Escape and on a press outside it", () => {
    setup();
    const chip = screen.getByRole("button", { name: "Sort top1 ↓" });
    fireEvent.click(chip);
    expect(chip.getAttribute("aria-expanded")).toBe("true");
    fireEvent.keyDown(screen.getByRole("menuitemradio", { name: "final" }), { key: "Escape" });
    expect(screen.queryByRole("menu")).toBeNull();
    fireEvent.click(chip);
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  test("Columns chip picks the score key each row shows", () => {
    const { patches } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Columns top1" }));
    const menu = screen.getByRole("menu", { name: "Value column" });
    expect(within(menu).getAllByRole("menuitemradio").map((b) => b.textContent)).toEqual(["top1", "final"]);
    fireEvent.click(within(menu).getByRole("menuitemradio", { name: "final" }));
    expect(patches.at(-1)).toEqual({ column: "top1/final" });
    expect(within(row(0)).getByText("0.9075")).toBeTruthy();
    expect(within(row(0)).queryByText("± 0.0014")).toBeNull();
    expect(screen.getByRole("button", { name: "Columns final" })).toBeTruthy();
  });

  test("a column key the task no longer has shows the primary", () => {
    setup(makeTaskRuns(), "col=gone/value");
    expect(screen.getByRole("button", { name: "Columns top1" })).toBeTruthy();
    expect(within(row(0)).getByText("0.9110")).toBeTruthy();
  });

  test("Each run lists runs with their seed; the filter narrows the list", () => {
    const { patches } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Each run" }));
    expect(patches.at(-1)).toEqual({ group: "run" });
    expect(nameOf(row(0))).toBe("lr 3e-4 · beam 10 · seed 1");
    fireEvent.change(screen.getByRole("searchbox", { name: "Filter runs" }), { target: { value: "status:queued" } });
    expect(patches.at(-1)).toEqual({ filter: "status:queued" });
    expect(rows().map(nameOf)).toEqual(["lr 1e-3 · beam 1 · seed 2"]);
  });

  test("hover and focus put the identity in the highlight store", () => {
    setup();
    fireEvent.mouseEnter(row(1));
    expect(getHighlight()).toBe("g-b");
    fireEvent.mouseLeave(row(1));
    expect(getHighlight()).toBeNull();
    fireEvent.focus(row(2));
    expect(getHighlight()).toBe("g-c");
    fireEvent.blur(row(2));
    expect(getHighlight()).toBeNull();
  });

  test("a row that leaves the list takes its highlight with it", () => {
    setup();
    fireEvent.mouseEnter(row(2));
    expect(getHighlight()).toBe("g-c");
    fireEvent.change(screen.getByRole("searchbox", { name: "Filter runs" }), { target: { value: "beam=10" } });
    expect(rows()).toHaveLength(2);
    expect(getHighlight()).toBeNull();
  });

  test("a ninth visible identity is neutral grey", () => {
    const data = makeTaskRuns({ runs: [], groups: [] });
    for (let i = 0; i < 9; i++) {
      data.runs.push(makeTaskRun({ run_id: `run-${i}`, group_id: `g-${i}`, primary: 0.9 - i * 0.01 }));
      data.groups.push(makeTaskGroup({ group_id: `g-${i}`, name: `cfg ${i}`, run_ids: [`run-${i}`], primary: { mean: 0.9 - i * 0.01, std: 0, n: 1, ci_low: null, ci_high: null } }));
    }
    setup(data);
    const swatch = (i: number) => row(i).querySelector<HTMLElement>(".sw")?.style.background;
    expect(swatch(0)).toBe("var(--c1)");
    expect(swatch(7)).toBe("var(--c8)");
    expect(swatch(8)).toBe("var(--c0)");
  });

  test("empty task and empty filter result", () => {
    setup(makeTaskRuns({ runs: [], groups: [] }));
    expect(screen.getByText("No runs yet")).toBeTruthy();
    expect(screen.getByText("0/0 shown")).toBeTruthy();
  });

  test("a filter whose only matches are superseded says how many the chip hides, and the hint shows them", () => {
    const { patches } = setup(makeTaskRuns(), "filter=baseline");
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByText("0/4 shown")).toBeTruthy();
    const hint = screen.getByRole("button", { name: "1 hidden by superseded" });
    fireEvent.click(hint);
    expect(patches.at(-1)).toEqual({ showSuperseded: true });
  });

  test("a filter that matches nothing says so", () => {
    setup(makeTaskRuns(), "filter=status:killed");
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
    expect(screen.getByText("No runs match")).toBeTruthy();
    expect(screen.getByText("0/4 shown")).toBeTruthy();
  });
});
