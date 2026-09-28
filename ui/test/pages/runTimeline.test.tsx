import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { NavigateContext } from "../../src/pages/components/links";
import {
  RunTimeline,
  clusterText,
  clusters,
  markKind,
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
