import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { NavigateContext } from "../../src/pages/components/links";
import {
  RunTimeline,
  clusterText,
  clusters,
  laneLabels,
  markKind,
  placeLabels,
  textWidth,
  timeTicks,
  timelineRows,
} from "../../src/pages/components/RunTimeline";
import type { TimelineItem } from "../../src/pages/components/types";
import { RUN_FAILED, RUN_SVM, makeOverview } from "./fixtures";

afterEach(cleanup);

function item(over: Partial<TimelineItem>): TimelineItem {
  return {
    run_id: "r",
    project: "p",
    task: "t",
    created_at: "2026-09-26T21:00:00Z",
    created_by: "human",
    status: "finished",
    archived: false,
    group_id: null,
    is_best: false,
    label: "A",
    ...over,
  };
}

describe("timelineRows", () => {
  test("one lane per launcher, agents first, items by time, failures counted", () => {
    const rows = timelineRows(makeOverview().timeline);
    expect(rows.map((r) => [r.launcher, r.agent, r.items.length, r.failed])).toEqual([
      ["agent:acceptance", true, 2, 1],
      ["human", false, 1, 0],
    ]);
    expect(rows[0]?.items.map((i) => i.run_id)).toEqual([RUN_FAILED, RUN_SVM]);
  });
});

test("markKind precedence: failed, archived, best, running, launcher", () => {
  expect(markKind(item({ status: "failed", archived: true }))).toBe("failed");
  expect(markKind(item({ status: "lost" }))).toBe("failed");
  expect(markKind(item({ archived: true, is_best: true }))).toBe("archived");
  expect(markKind(item({ is_best: true }))).toBe("best");
  expect(markKind(item({ status: "running" }))).toBe("running");
  expect(markKind(item({ created_by: "agent:tuner" }))).toBe("agent");
  expect(markKind(item({}))).toBe("human");
});

test("clusters merge neighbours with the same label", () => {
  const got = clusters([
    item({ run_id: "1", label: "A" }),
    item({ run_id: "2", label: "A", is_best: true }),
    item({ run_id: "3", label: "B" }),
    item({ run_id: "4", label: "A" }),
  ]);
  expect(got.map((c) => [c.label, c.items.length, c.best])).toEqual([
    ["A", 2, true],
    ["B", 1, false],
    ["A", 1, false],
  ]);
  expect(got.map(clusterText)).toEqual(["A, best", "B", "A"]);
});

test("timeTicks picks whole minutes for minutes and 6 h steps for a day", () => {
  const t = (iso: string) => Date.parse(iso);
  expect(timeTicks(t("2026-09-26T21:00:32Z"), t("2026-09-26T21:03:06Z"))).toEqual([
    t("2026-09-26T21:01:00Z"),
    t("2026-09-26T21:02:00Z"),
    t("2026-09-26T21:03:00Z"),
  ]);
  // 1420 min / 6 ticks = 237 min, so the first step with at most 6 ticks is 360 min
  expect(timeTicks(t("2026-09-26T00:10:00Z"), t("2026-09-26T23:50:00Z"))).toEqual([
    t("2026-09-26T06:00:00Z"),
    t("2026-09-26T12:00:00Z"),
    t("2026-09-26T18:00:00Z"),
  ]);
});

test("renders lanes, marks, cluster labels, and ticks; a mark opens its run", () => {
  const navigate = mock((_href: string) => {});
  const { container } = render(
    <NavigateContext.Provider value={navigate}>
      <RunTimeline items={makeOverview().timeline} />
    </NavigateContext.Provider>,
  );
  // the legend below the chart repeats "human"/"agent", so look inside the chart only
  const svg = container.querySelector("svg[aria-label='Runs by launcher over time']") as HTMLElement;
  const texts = ["agent:acceptance", "2 runs, 1 failed", "human", "1 run", "RBF-kernel SVM, best", "Baseline rf", "21:01", "21:02", "21:03"];
  for (const text of texts) expect(within(svg).getByText(text)).toBeTruthy();
  const kinds = [...container.querySelectorAll("[data-mark]")].map((m) => m.getAttribute("data-mark"));
  expect(kinds).toEqual(["failed", "best", "human"]);
  fireEvent.click(screen.getByRole("link", { name: "RBF-kernel SVM, finished, best, 21:03" }));
  expect(navigate).toHaveBeenCalledWith(`/r/${RUN_SVM}`);
});

test("an empty window says so", () => {
  render(<RunTimeline items={[]} />);
  expect(screen.getByText("no runs in this window")).toBeTruthy();
});

describe("label collision avoidance", () => {
  const cand = (key: string, x: number, w = 60, priority = 1) => ({ key, text: key, x, w, priority });
  const overlaps = (ps: { cx: number; w: number; tier: number }[]) =>
    ps.some((a, i) =>
      ps.some((b, j) => i < j && a.tier === b.tier && a.cx - a.w / 2 < b.cx + b.w / 2 && b.cx - b.w / 2 < a.cx + a.w / 2),
    );

  test("labels far apart keep their x on the tier above", () => {
    const { placed, dropped } = placeLabels([cand("a", 100), cand("b", 400)], 0, 1000);
    expect(dropped).toEqual([]);
    expect(placed.map((p) => [p.key, p.cx, p.tier])).toEqual([
      ["b", 400, 0],
      ["a", 100, 0],
    ]);
  });

  test("stacked labels slide, then use the tier below, then drop; none overlap", () => {
    const cs = [cand("a", 500), cand("b", 505), cand("c", 510), cand("d", 515), cand("e", 520, 60, 5)];
    const { placed, dropped } = placeLabels(cs, 0, 1000);
    expect(overlaps(placed)).toBe(false);
    // the high-priority label keeps its own spot above the lane
    expect(placed.find((p) => p.key === "e")).toMatchObject({ cx: 520, tier: 0 });
    expect(new Set(placed.map((p) => p.tier))).toEqual(new Set([0, 1]));
    expect(placed.length + dropped.length).toBe(5);
    expect(dropped.length).toBeGreaterThan(0);
    for (const p of placed) expect(Math.abs(p.cx - p.x)).toBeLessThanOrEqual(p.w / 2 + 12);
  });

  test("labels stay inside the lane", () => {
    const { placed } = placeLabels([cand("edge", 995, 80)], 0, 1000);
    expect(placed[0]?.cx).toBe(960);
  });

  test("laneLabels puts the best first and sums the rest into +N with a tooltip list", () => {
    const at = [300, 302, 304, 306, 308];
    const cs = at.map((_, i) => ({ label: `idea ${i}`, items: [item({ run_id: String(i) })], best: i === 0 }));
    const out = laneLabels(cs, (c) => at[cs.indexOf(c)] ?? 0, 0, 1000);
    expect(out.placed.find((p) => p.best)?.text).toBe("idea 0, best");
    expect(out.more?.text).toBe(`+${5 - out.placed.length}`);
    expect(out.more?.names).toHaveLength(5 - out.placed.length);
    expect(overlaps([...out.placed, ...(out.more ? [out.more] : [])])).toBe(false);
  });

  test("nearby clusters with the same text are labelled once", () => {
    const cs = ["A", "B", "A"].map((label, i) => ({ label, items: [item({ run_id: String(i) })], best: false }));
    const xs = [100, 110, 120];
    const out = laneLabels(cs, (c) => xs[cs.indexOf(c)] ?? 0, 0, 1000);
    expect(out.placed.map((p) => p.text).sort()).toEqual(["A", "B"]);
    // far apart, the same text is two labels
    const far = laneLabels(cs, (c) => [100, 500, 900][cs.indexOf(c)] ?? 0, 0, 1000);
    expect(far.placed.map((p) => p.text).sort()).toEqual(["A", "A", "B"]);
  });

  test("the rendered lane shows +N with the hidden names as its title", () => {
    const many = ["alpha idea", "beta idea", "gamma idea", "delta idea", "eps idea"].map((label, i) =>
      item({ run_id: `r${i}`, label, created_at: `2026-09-26T21:00:0${i}Z` }),
    );
    const far = item({ run_id: "late", label: "late", created_at: "2026-09-26T23:00:00Z" });
    const { container } = render(<RunTimeline items={[...many, far]} />);
    const more = container.querySelector("text.cl.more");
    const n = Number(more?.lastChild?.textContent?.slice(1));
    expect(n).toBeGreaterThan(0);
    expect(more?.querySelector("title")?.textContent?.split("\n")).toHaveLength(n);
    expect(textWidth("abcd")).toBe(27);
  });
});
