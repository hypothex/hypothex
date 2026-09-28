import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { IdeaList, groupIdeas, ideaDomain, ideaScore, ideaSub, pct } from "../../src/pages/components/IdeaList";
import { FailureList, ProjectsTable, RunningList } from "../../src/pages/components/OverviewLists";
import type { IdeaRow } from "../../src/pages/components/types";
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
    const one: IdeaRow = { ...rf, primary: { mean: 0.5, std: 0, n: 1, ci_low: null, ci_high: null } };
    expect(ideaSub(one)).toBe("1 seed");
  });
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
  expect(rows[0]?.querySelector("svg.iv title")?.textContent).toBe("95% CI 0.874–0.953");
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
  expect(screen.getByText("…/20260926-210158-toy-test-58c5/logs/stderr.log")).toBeTruthy();
  const open = screen.getByRole("link", { name: "Open stderr" });
  expect(open.getAttribute("href")).toBe(`/r/${RUN_FAILED}?log=stderr`);
  fireEvent.click(screen.getByRole("button", { name: "Copy stderr path" }));
  await waitFor(() => expect(written).toEqual([`${STORE}/${RUN_FAILED}/logs/stderr.log`]));
});

test("ProjectsTable links each task and shows runs and best", () => {
  render(<ProjectsTable projects={makeOverview().projects} />);
  const link = screen.getByRole("link", { name: "toy-classifier / toy-test" });
  expect(link.getAttribute("href")).toBe("/t/toy-classifier/toy-test");
  const cells = screen.getAllByRole("cell").map((c) => c.textContent);
  expect(cells).toEqual(["toy-classifier / toy-test", "12", "0.9222"]);
});
