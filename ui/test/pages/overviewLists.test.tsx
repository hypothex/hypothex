import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { IdeaList, ideaDomain, ideaScore, ideaSub } from "../../src/pages/components/IdeaList";
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
