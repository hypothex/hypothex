import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import {
  IdeaList,
  groupIdeas,
  ideaDomain,
  ideaInterval,
  ideaScore,
  ideaSub,
  pct,
} from "../../src/pages/components/IdeaList";
import {
  FailureList,
  ProjectsTable,
  RunningList,
  groupFailures,
} from "../../src/pages/components/OverviewLists";
import { PAGES_CSS } from "../../src/pages/components/styles";
import type { FailureRow, IdeaRow } from "../../src/pages/components/types";
import { RUN_FAILED, RUN_SVM, STORE, makeOverview, makeRecord } from "./fixtures";
import { mockClipboard } from "./helpers";

afterEach(cleanup);

const ideas = makeOverview().ideas;

describe("idea helpers", () => {
  test("ideaDomain spans every interval end and mean, padded by 5%", () => {
    // lo = 0.83 (rf interval), hi = 0.953 (best band); pad = 0.123 * 0.05 = 0.00615
    const [lo, hi] = ideaDomain(ideas) ?? [0, 0];
    expect(lo).toBeCloseTo(0.82385, 6);
    expect(hi).toBeCloseTo(0.95915, 6);
    expect(ideaDomain([])).toBeNull();
  });

  test("ideaScore and ideaSub", () => {
    const [svm, failed, rf] = ideas as [IdeaRow, IdeaRow, IdeaRow];
    expect([ideaScore(svm), ideaSub(svm)]).toEqual(["0.9222", "◇×3"]);
    expect([ideaScore(failed), ideaSub(failed)]).toEqual(["failed", ""]);
    expect([ideaScore(rf), ideaSub(rf)]).toEqual(["0.8852", "± 0.0064"]);
    const running: IdeaRow = { ...failed, statuses: ["running", "finished"] };
    expect(ideaScore(running)).toBe("running");
    // queued alone is waiting, not running; one running seed makes the group running
    expect(ideaScore({ ...failed, statuses: ["queued", "queued"] })).toBe("queued");
    expect(ideaScore({ ...failed, statuses: ["queued", "running"] })).toBe("running");
    const one: IdeaRow = { ...rf, primary: { mean: 0.5, std: 0, n: 1, ci_low: null, ci_high: null } };
    expect(ideaSub(one)).toBe("1 seed");
    const fast: IdeaRow = { ...rf, unit: "ms", primary: { mean: 165.6, std: 2.8, n: 3, ci_low: null, ci_high: null } };
    expect([ideaScore(fast), ideaSub(fast)]).toEqual(["166 ms", "± 2.80"]);
  });
});

test("without a test-set interval a row shows its seed CI; big means get 3 significant figures", () => {
  const [, , rf] = ideas as [IdeaRow, IdeaRow, IdeaRow];
  const bench: IdeaRow = {
    ...rf,
    test_interval: null,
    primary: { mean: 165.62, std: 2.8011, n: 3, ci_low: 158.66, ci_high: 172.58 },
  };
  expect(ideaInterval(bench)).toEqual({ lo: 158.66, hi: 172.58, how: "95% CI over 3 seeds" });
  expect(ideaSub(bench)).toBe("± 2.80");
  expect(ideaInterval({ ...bench, identical_seeds: true })).toBeNull();
  const { container } = render(<IdeaList ideas={[bench]} />);
  expect(container.querySelector("svg.iv title")?.textContent).toBe("95% CI over 3 seeds 159–173");
  expect(container.querySelectorAll("svg.iv line")).toHaveLength(3);
});

test("idea strips use percentage geometry, not a scaled viewBox", () => {
  expect(pct([0, 2], 0.5)).toBe("25%");
  expect(pct([1, 1], 1)).toBe("50%");
  const { container } = render(<IdeaList ideas={ideas} />);
  for (const svg of container.querySelectorAll("svg.iv, .idea-axis svg")) {
    expect(svg.getAttribute("viewBox")).toBeNull();
    expect(svg.getAttribute("preserveAspectRatio")).toBeNull();
  }
  expect(container.querySelector(".idea-axis text")?.getAttribute("x")).toMatch(/%$/);
});

test("IdeaList draws one mark per seed and dims failed groups", () => {
  const { container } = render(<IdeaList ideas={ideas} />);
  expect(container.querySelectorAll("[data-seed]")).toHaveLength(9);
  expect(container.querySelectorAll("[data-seed='failed']")).toHaveLength(3);
  const rows = container.querySelectorAll("li.idea");
  expect(rows).toHaveLength(3);
  expect(rows[1]?.classList.contains("dim")).toBe(true);
  expect(rows[0]?.querySelector("svg.iv title")?.textContent).toBe("test-set 95% CI 0.874–0.953");
  const name = within(rows[0] as HTMLElement).getByRole("link", { name: "RBF-kernel SVM" });
  expect(name.getAttribute("href")).toBe("/t/toy-classifier/toy-test");
  expect(within(rows[2] as HTMLElement).getByText("human, 21:00")).toBeTruthy();
});

// A second task on another scale (latency in ms, lower is better), interleaved by time.
const latency = (group_id: string, mean: number, lo: number, hi: number): IdeaRow => ({
  project: "svc",
  task: "latency",
  group_id,
  label: `cache ${group_id}`,
  created_by: "human",
  created_at: "2026-09-26T21:02:00Z",
  statuses: ["finished"],
  primary: { mean, std: 0, n: 1, ci_low: null, ci_high: null },
  test_interval: { lo, hi, method: "bootstrap", n: 50 },
  identical_seeds: false,
  best_band: { lo: 166, hi: 180, method: "bootstrap", n: 50 },
  unit: "ms",
});
const mixed: IdeaRow[] = [
  ideas[0] as IdeaRow,
  latency("l1", 172, 166, 180),
  ideas[1] as IdeaRow,
  latency("l2", 220, 210, 233),
  ideas[2] as IdeaRow,
];

test("groupIdeas gives each task its own rows and domain, in first-seen order", () => {
  const groups = groupIdeas(mixed);
  expect(groups.map((g) => [g.project, g.task, g.ideas.map((i) => i.group_id)])).toEqual([
    ["toy-classifier", "toy-test", ["63c2ec5f@8f4cac4", "63c2ec5f@0000000", "5a810ddb@2bbf5a3"]],
    ["svc", "latency", ["l1", "l2"]],
  ]);
  // the accuracy domain is the one from the accuracy rows alone
  expect(groups[0]?.domain).toEqual(ideaDomain(ideas));
  const [lo, hi] = groups[1]?.domain ?? [0, 0];
  expect(lo).toBeCloseTo(166 - 67 * 0.05, 6);
  expect(hi).toBeCloseTo(233 + 67 * 0.05, 6);
});

test("IdeaList draws one axis per task, so accuracy rows keep a visible best band", () => {
  const { container } = render(<IdeaList ideas={mixed} />);
  const groups = container.querySelectorAll(".idea-group");
  expect(groups).toHaveLength(2);
  const axes = [...container.querySelectorAll(".idea-axis")];
  expect(axes.map((a) => a.querySelector(".ax-l")?.textContent)).toEqual([
    "toy-classifier / toy-test",
    "svc / latency",
  ]);
  expect(axes[1]?.querySelector(".ax-l")?.getAttribute("title")).toBe("x axis: the primary metric of svc / latency");
  const ticks = (i: number) => [...(axes[i]?.querySelectorAll("text") ?? [])].map((t) => t.textContent);
  expect(ticks(0).every((t) => Number(t) > 0.8 && Number(t) < 1)).toBe(true);
  expect(ticks(1).every((t) => Number(t) >= 160 && Number(t) <= 240)).toBe(true);
  // the best band of the accuracy task spans a real width on its own axis
  const band = groups[0]?.querySelector("li.idea svg.iv rect");
  expect(band?.getAttribute("width")).toMatch(/%$/);
  expect(Number.parseFloat(band?.getAttribute("width") ?? "0")).toBeGreaterThan(40);
  expect(within(groups[1] as HTMLElement).getAllByRole("listitem")).toHaveLength(2);
  // latency rows show their unit, accuracy rows none
  expect(within(groups[1] as HTMLElement).getByText("172 ms")).toBeTruthy();
  expect(within(groups[0] as HTMLElement).getByText("0.9222")).toBeTruthy();
});

test("IdeaList marks queued seeds apart from running ones", () => {
  const [, failed] = ideas as [IdeaRow, IdeaRow];
  const row: IdeaRow = { ...failed, primary: null, statuses: ["queued", "running", "queued"] };
  const { container } = render(<IdeaList ideas={[row]} />);
  const marks = [...container.querySelectorAll("[data-seed]")].map((m) => m.getAttribute("data-seed"));
  expect(marks).toEqual(["queued", "running", "queued"]);
});

test("RunningList puts queued runs in a waiting group after the running ones", () => {
  const runs = [
    makeRecord({ run_id: "q1", status: "queued", ended_at: null, hypothesis: "queued one" }),
    makeRecord({ run_id: "r1", status: "running", ended_at: null, hypothesis: "running one" }),
    makeRecord({ run_id: "q2", status: "queued", ended_at: null, hypothesis: "queued two" }),
  ];
  render(<RunningList runs={runs} />);
  const names = (label: string) =>
    within(screen.getByRole("list", { name: label }))
      .getAllByRole("link")
      .map((a) => a.textContent);
  expect(names("running")).toEqual(["running one"]);
  expect(names("waiting")).toEqual(["queued one", "queued two"]);
  expect(screen.getByText("waiting 2")).toBeTruthy();
  cleanup();
  // only queued runs: no running list, just the waiting group
  render(<RunningList runs={[runs[0]!]} />);
  expect(screen.queryByRole("list", { name: "running" })).toBeNull();
  expect(names("waiting")).toEqual(["queued one"]);
});

test("RunningList shows none, or one link per run", () => {
  const { rerender } = render(<RunningList runs={[]} />);
  expect(screen.getByText("none")).toBeTruthy();
  rerender(<RunningList runs={[makeRecord({ status: "running", ended_at: null })]} />);
  expect(screen.getByRole("link", { name: "RBF-kernel SVM" }).getAttribute("href")).toBe(`/r/${RUN_SVM}`);
});

test("FailureList links to stderr and copies its path", async () => {
  const written = mockClipboard();
  render(<FailureList failures={makeOverview().failures} />);
  expect(screen.getByText("SVM, exit 2")).toBeTruthy();
  expect(screen.getByText("21:01:58 UTC, retry ok")).toBeTruthy();
  expect(screen.getByTitle(`${STORE}/${RUN_FAILED}/logs/stderr.log`).textContent).toBe(`…/${RUN_FAILED}/logs/stderr.log`);
  const open = screen.getByRole("link", { name: "Open stderr" });
  expect(open.getAttribute("href")).toBe(`/r/${RUN_FAILED}?log=stderr`);
  fireEvent.click(screen.getByRole("button", { name: "Copy stderr path" }));
  await waitFor(() => expect(written).toEqual([`${STORE}/${RUN_FAILED}/logs/stderr.log`]));
});

const fail = (run_id: string, label: string, exit_code: number | null, at: string): FailureRow => ({
  run_id,
  label,
  exit_code,
  created_at: `2026-10-03T${at}Z`,
  stderr_path: `${STORE}/${run_id}/logs/stderr.log`,
  retried_ok: true,
});
const FAILS = [
  fail("svm-3", "RBF-kernel SVM", 2, "03:02:02"),
  fail("cache-1", "cache-enabled", 1, "02:00:00"),
  fail("svm-2", "RBF-kernel SVM", 2, "03:02:01"),
  fail("svm-x", "RBF-kernel SVM", 1, "03:01:59"),
  fail("svm-1", "RBF-kernel SVM", 2, "03:01:58"),
];

test("groupFailures joins rows with the same label and exit code, in first-seen order", () => {
  expect(groupFailures(FAILS).map((g) => g.map((f) => f.run_id))).toEqual([
    ["svm-3", "svm-2", "svm-1"],
    ["cache-1"],
    ["svm-x"],
  ]);
  expect(groupFailures([])).toEqual([]);
});

test("FailureList shows one block per group with a ×N count, newest row first", () => {
  const { container } = render(<FailureList failures={FAILS} />);
  const blocks = [...container.querySelectorAll(".fail-b")];
  expect(blocks.map((b) => b.querySelector(".x")?.textContent)).toEqual(["×3", "×", "×"]);
  expect(blocks[0]?.querySelector("b")?.textContent).toBe("RBF-kernel SVM, exit 2");
  expect(within(blocks[0] as HTMLElement).getByRole("link", { name: "Open stderr" }).getAttribute("href")).toBe(
    "/r/svm-3?log=stderr",
  );
  expect(blocks[0]?.getAttribute("title")).toBe("svm-3 03:02:02 UTC\nsvm-2 03:02:01 UTC\nsvm-1 03:01:58 UTC");
  expect(blocks[1]?.getAttribute("title")).toBeNull();
});

test("FailureList shows retry ok only when every row was retried, else retried ×k", () => {
  const rows = (flags: boolean[]): FailureRow[] =>
    flags.map((ok, i) => ({ ...fail(`svm-${i}`, "RBF-kernel SVM", 2, `03:02:0${i}`), retried_ok: ok }));
  const small = (flags: boolean[]): string | null | undefined => {
    const { container } = render(<FailureList failures={rows(flags)} />);
    const text = container.querySelector(".fail-b .small")?.textContent;
    cleanup();
    return text;
  };
  expect(small([true, true, true])).toBe("03:02:00 UTC, retry ok");
  expect(small([true, false, true])).toBe("03:02:00 UTC, retried ×2");
  expect(small([false, false, false])).toBe("03:02:00 UTC");
  expect(small([true])).toBe("03:02:00 UTC, retry ok");
});

test("FailureList paths break only after a slash", () => {
  const { container } = render(<FailureList failures={makeOverview().failures} />);
  const path = container.querySelector(".fail-b .p") as HTMLElement;
  // …/<id>/logs/stderr.log: a break chance after each of the 3 slashes, none inside a word
  expect(path.querySelectorAll("wbr")).toHaveLength(3);
  expect(path.style.wordBreak).toBe("normal");
  expect(path.textContent).toBe(`…/${RUN_FAILED}/logs/stderr.log`);
  expect(path.getAttribute("title")).toBe(`${STORE}/${RUN_FAILED}/logs/stderr.log`);
});

test("ProjectsTable links each task and shows runs and best", () => {
  render(<ProjectsTable projects={makeOverview().projects} />);
  const link = screen.getByRole("link", { name: "toy-classifier / toy-test" });
  expect(link.getAttribute("href")).toBe("/t/toy-classifier/toy-test");
  const cells = screen.getAllByRole("cell").map((c) => c.textContent);
  expect(cells).toEqual(["toy-classifier / toy-test", "12", "0.9222"]);
});

test("ProjectsTable shows the best value with the task's unit", () => {
  const [row] = makeOverview().projects;
  render(<ProjectsTable projects={[{ ...row!, best: 165.62, unit: "ms" }]} />);
  expect(screen.getAllByRole("cell").map((c) => c.textContent)[2]).toBe("166 ms");
});

test("ProjectsTable keeps numeric columns fixed and allows complete project/task names to wrap", () => {
  const { container } = render(<ProjectsTable projects={makeOverview().projects} />);
  const table = container.querySelector("table.projects");
  expect([...(table?.querySelectorAll("col") ?? [])].map((c) => c.className)).toEqual(["", "c-runs", "c-best"]);
  expect(table?.querySelector("td.nm a")?.getAttribute("title")).toBe("toy-classifier / toy-test");
  for (const rule of [".page .projects { table-layout: fixed; }", ".page .projects td + td"]) {
    expect(PAGES_CSS).toContain(rule);
  }
  const nameRule = PAGES_CSS.match(/\.page \.projects td\.nm\s*\{([^}]+)\}/)?.[1] ?? "";
  expect(nameRule).toContain("white-space: normal");
  expect(nameRule).toContain("overflow-wrap: anywhere");
  expect(nameRule).not.toContain("overflow: hidden");
  expect(nameRule).not.toContain("ellipsis");
});
