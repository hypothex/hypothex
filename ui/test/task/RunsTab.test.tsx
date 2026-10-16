import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import type { TaskRuns } from "../../src/api/models";
import { fmtDate } from "../../src/pages/components/format";
import { RunsTab } from "../../src/task/RunsTab";
import { type Selection, parseSelection } from "../../src/task/useRunSelection";
import { type Call, HttpReply, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";
import { PROJECT, TASK, makeTaskRun, makeTaskRuns } from "./fixtures";

afterEach(restoreFetch);

interface Log {
  patches: Partial<Selection>[];
  charts: number;
  opened: string[];
}

function Harness({ data, log }: { data: TaskRuns; log: Log }) {
  const [sel, setSel] = useState<Selection>(parseSelection(new URLSearchParams(), { sortDir: "desc" }));
  return (
    <RunsTab
      project={PROJECT}
      task={TASK}
      data={data}
      selection={sel}
      onSelection={(p) => {
        log.patches.push(p);
        setSel((s) => ({ ...s, ...p }));
      }}
      onOpenCharts={() => {
        log.charts += 1;
      }}
      onOpenRun={(id) => log.opened.push(id)}
    />
  );
}

function setup(data: TaskRuns = makeTaskRuns()): Log {
  const log: Log = { patches: [], charts: 0, opened: [] };
  renderWithClient(<Harness data={data} log={log} />);
  return log;
}

const table = () => screen.getByRole("table", { name: "Runs" });
const headers = () => within(table()).getAllByRole("columnheader").map((h) => h.textContent ?? "");
const bodyRows = () => within(table()).getAllByRole("row").slice(1) as HTMLElement[];
const cell = (row: HTMLElement, label: string) => within(row).getAllByRole("cell")[headers().indexOf(label)] as HTMLElement;
const nameOf = (row: HTMLElement) => within(row).getAllByRole("link")[0]?.textContent;
const pick = (name: string) => fireEvent.click(screen.getByRole("checkbox", { name: `Select ${name}` }));

describe("RunsTab", () => {
  test("one row per config with every column", () => {
    setup();
    expect(headers().slice(2)).toEqual(["Name", "Status", "lr", "beam", "top1", "95% CI", "Δ best", "Launcher", "Host", "GPU-h", "Started", "Commit", "Tags"]);
    const [a, b, c] = bodyRows() as [HTMLElement, HTMLElement, HTMLElement];
    expect(bodyRows()).toHaveLength(3);
    expect(nameOf(a)).toBe("lr 3e-4 · beam 10");
    expect(cell(a, "top1").textContent).toBe("0.9110 ± 0.0014");
    expect(cell(a, "top1").className).toContain("best");
    expect(cell(a, "95% CI").textContent).toBe("0.905–0.917");
    expect(cell(a, "Δ best").textContent).toBe("—");
    expect(within(cell(a, "Status")).getByTitle("2 finished")).toBeTruthy();
    expect(within(cell(a, "Status")).getByTitle("1 running")).toBeTruthy();
    expect(cell(a, "lr").textContent).toBe("3e-4");
    expect(cell(a, "GPU-h").textContent).toBe("3.0");
    expect(cell(a, "Started").textContent).toBe(fmtDate("2026-10-03T09:00:05Z"));
    expect(cell(a, "Commit").textContent).toBe("8f4cac4");
    expect(cell(a, "Tags").textContent).toBe("final");
    const delta = within(cell(b, "Δ best")).getByTitle(/outside the best config's interval/);
    expect(delta.textContent).toBe("−0.0130");
    expect(delta.className).not.toContain("muted");
    expect(cell(b, "Host").textContent).toBe("dgx");
    expect(cell(c, "top1").textContent).toBe("—");
    expect(cell(c, "95% CI").textContent).toBe("");
  });

  test("a config expands to its seeds", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Expand lr 3e-4 · beam 10" }));
    expect(screen.getByRole("button", { name: "Collapse lr 3e-4 · beam 10" }).getAttribute("aria-expanded")).toBe("true");
    const seeds = bodyRows().slice(1, 4);
    expect(seeds.map((r) => within(r).getByText(/^seed /).textContent)).toEqual(["seed 1", "seed 2", "seed 3"]);
    expect(seeds.map((r) => cell(r, "top1").textContent)).toEqual(["0.9120", "0.9100", "—"]);
    expect(within(cell(seeds[2] as HTMLElement, "Status")).getByText("running")).toBeTruthy();
  });

  test("click a header to sort, again to flip; names open the latest run", () => {
    const log = setup();
    fireEvent.click(within(table()).getByRole("button", { name: "Host" }));
    expect(bodyRows().map(nameOf)).toEqual(["lr 3e-4 · beam 10", "lr 1e-3 · beam 1", "lr 1e-4 · beam 10"]);
    expect(within(table()).getAllByRole("columnheader").find((h) => h.textContent?.startsWith("Host"))?.getAttribute("aria-sort")).toBe("descending");
    fireEvent.click(within(table()).getByRole("button", { name: /^Host/ }));
    expect(bodyRows().map(nameOf)).toEqual(["lr 1e-4 · beam 10", "lr 3e-4 · beam 10", "lr 1e-3 · beam 1"]);
    fireEvent.click(within(bodyRows()[0] as HTMLElement).getAllByRole("link")[0] as HTMLElement);
    expect(log.opened).toEqual(["run-b2"]);
  });

  test("the column chooser hides a column and remembers it for the task", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Columns 12" }));
    fireEvent.click(within(screen.getByRole("group", { name: "Columns" })).getByRole("checkbox", { name: "Host" }));
    expect(headers()).not.toContain("Host");
    expect(JSON.parse(localStorage.getItem(`hx.runs.columns.${PROJECT}/${TASK}`) ?? "[]")).toEqual(["host"]);
    cleanup();
    setup();
    expect(headers()).not.toContain("Host");
    expect(screen.getByRole("button", { name: "Columns 11" })).toBeTruthy();
  });

  test("Compare keeps only the selected configs visible and opens Charts", () => {
    const log = setup();
    pick("lr 3e-4 · beam 10");
    pick("lr 1e-4 · beam 10");
    expect(screen.getByText("2 selected")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Compare" }));
    expect(log.patches.at(-1)).toEqual({ hidden: ["g-c", "g-d"] });
    expect(log.charts).toBe(1);
  });

  test("Tag adds the tag to every run of the selection, one command id per run", async () => {
    const calls = mockApi({ "POST /api/v1/runs/run-b1/tags": makeTaskRun(), "POST /api/v1/runs/run-b2/tags": makeTaskRun() });
    setup();
    pick("lr 1e-4 · beam 10");
    fireEvent.click(screen.getByRole("button", { name: "Tag" }));
    const form = screen.getByRole("form", { name: "Tag runs" });
    fireEvent.change(within(form).getByRole("textbox", { name: "Tag" }), { target: { value: " keep " } });
    fireEvent.click(within(form).getByRole("button", { name: "Add to 2 runs" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls.map((c) => [c.url, (c.body as { add: string[] }).add])).toEqual([
      ["/api/v1/runs/run-b1/tags", ["keep"]],
      ["/api/v1/runs/run-b2/tags", ["keep"]],
    ]);
    expect((calls[0]?.body as { command_id: string }).command_id.endsWith(":run-b1")).toBe(true);
    await waitFor(() => expect(screen.queryByRole("form", { name: "Tag runs" })).toBeNull());
  });

  test("Archive archives every run of the selection", async () => {
    const calls = mockApi({ "POST /api/v1/runs/run-c1/archive": makeTaskRun(), "POST /api/v1/runs/run-c2/archive": makeTaskRun() });
    setup();
    pick("lr 1e-3 · beam 1");
    fireEvent.click(screen.getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls.map((c: Call) => [c.url, (c.body as { on: boolean }).on])).toEqual([
      ["/api/v1/runs/run-c1/archive", true],
      ["/api/v1/runs/run-c2/archive", true],
    ]);
  });

  test("Rename works on one selected config and renames each of its runs", async () => {
    const calls = mockApi(Object.fromEntries(["run-a1", "run-a2", "run-a3"].map((id) => [`POST /api/v1/runs/${id}/name`, makeTaskRun({ run_id: id })])));
    setup();
    pick("lr 3e-4 · beam 10");
    pick("lr 1e-4 · beam 10");
    expect((screen.getByRole("button", { name: "Rename" }) as HTMLButtonElement).disabled).toBe(true);
    pick("lr 1e-4 · beam 10");
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const form = screen.getByRole("form", { name: "Rename" });
    const input = within(form).getByRole("textbox", { name: "Name" }) as HTMLInputElement;
    expect(input.value).toBe("lr 3e-4 · beam 10");
    fireEvent.change(input, { target: { value: "wide beam" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(calls).toHaveLength(3));
    expect(calls.map((c) => (c.body as { name: string }).name)).toEqual(["wide beam", "wide beam", "wide beam"]);
  });

  test("Rename checks the name first and shows the server's refusal inline", async () => {
    const calls = mockApi({ "POST /api/v1/runs/run-b1/name": new HttpReply(422, { detail: "name is too long" }) });
    setup();
    pick("lr 1e-4 · beam 10");
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    const form = screen.getByRole("form", { name: "Rename" });
    const input = within(form).getByRole("textbox", { name: "Name" });
    fireEvent.change(input, { target: { value: "x".repeat(81) } });
    fireEvent.click(within(form).getByRole("button", { name: "Save name" }));
    expect(within(form).getByRole("alert").textContent).toBe("At most 80 characters");
    expect(calls).toHaveLength(0);
    fireEvent.change(input, { target: { value: "lr 1e-4 · beam 10" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save name" }));
    expect(screen.queryByRole("form", { name: "Rename" })).toBeNull();
    expect(calls).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.change(within(screen.getByRole("form", { name: "Rename" })).getByRole("textbox", { name: "Name" }), { target: { value: "short beam" } });
    fireEvent.click(screen.getByRole("button", { name: "Save name" }));
    await waitFor(() => expect(within(screen.getByRole("form", { name: "Rename" })).getByRole("alert").textContent).toContain("name is too long"));
    expect(calls).toHaveLength(1);
  });

  test("Escape or a press outside closes the column chooser", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Columns 12" }));
    fireEvent.keyDown(within(screen.getByRole("group", { name: "Columns" })).getByRole("checkbox", { name: "Host" }), { key: "Escape" });
    expect(screen.queryByRole("group", { name: "Columns" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Columns 12" }));
    fireEvent.mouseDown(document.body);
    expect(screen.queryByRole("group", { name: "Columns" })).toBeNull();
  });

  test("Each run lists runs without expanders; an empty task says so", () => {
    setup();
    fireEvent.click(screen.getByRole("button", { name: "Each run" }));
    expect(bodyRows()).toHaveLength(7);
    expect(screen.queryByRole("button", { name: /^Expand / })).toBeNull();
    cleanup();
    setup(makeTaskRuns({ runs: [], groups: [] }));
    expect(screen.getByText("No runs yet")).toBeTruthy();
  });
});
