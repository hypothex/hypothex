import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import type { RunRecord } from "../../src/api/models";
import { SweepRuns, runsForHosts } from "../../src/pages/components/SweepRuns";
import { renderWithClient } from "./helpers";
import { HOSTS, NOW, RUNS, STALE, rid, run } from "./sweepFixtures";

afterEach(cleanup);

const NAMES = ["lr", "beam"];
const cellsOf = (row: Element): (string | null)[] => [...row.querySelectorAll("td")].map((td) => td.textContent);
const bodyRows = (): HTMLElement[] => screen.getAllByRole("row").slice(1);
const firstCells = (): (string | null | undefined)[] => bodyRows().map((r) => r.querySelector("td")?.textContent);

describe("SweepRuns", () => {
  test("a terminal GPU run without timing data shows missing GPU time, not a known zero", () => {
    const missing = { ...run("c2"), started_at: null, cost: null, usage: null };
    renderWithClient(<SweepRuns runs={[missing]} names={NAMES} stale={new Map()} hosts={HOSTS} now={NOW} />);
    expect(cellsOf(bodyRows()[0] as HTMLElement).slice(-2)).toEqual(["—", "—"]);
  });
  test("terminal zero GPU time is known and unavailable terminal cost is missing", () => {
    const finished = { ...run("a1"), executor: { ...run("a1").executor, gpus: [] }, gpus_requested: 0, cost: null, usage: null };
    const killed = { ...finished, run_id: rid("killed"), status: "killed" as const };
    const lost = { ...finished, run_id: rid("lost"), status: "lost" as const };
    renderWithClient(<SweepRuns runs={[finished, killed, lost, run("a2")]} names={NAMES} stale={new Map()} hosts={HOSTS} now={NOW} />);
    fireEvent.click(screen.getByRole("button", { name: "+ 1 finished" }));
    for (const id of ["a1", "killed", "lost"]) {
      expect(cellsOf(screen.getByRole("link", { name: id }).closest("tr") as Element).slice(-2)).toEqual(["0.0", "—"]);
    }
    expect(cellsOf(screen.getByRole("link", { name: "a2" }).closest("tr") as Element).slice(-2)).toEqual(["·", "·"]);
    expect(runsForHosts([finished, killed, lost, run("c2")], new Map()).map(({ record }) => record.status)).toEqual(["lost", "failed", "killed", "finished"]);
  });
  test("lists unfinished runs: running and stale first, then queued, then failed", () => {
    renderWithClient(<SweepRuns runs={RUNS} names={NAMES} stale={STALE} hosts={HOSTS} now={NOW} />);
    expect(screen.getAllByRole("columnheader").map((th) => th.textContent)).toEqual([
      "run",
      "lr",
      "beam",
      "seed",
      "state",
      "host",
      "GPU-h",
      "cost",
    ]);
    expect(bodyRows().map(cellsOf)).toEqual([
      ["b2", "1e-4", "10", "2", "stale 4m", "dgx", "1.0", "·"],
      ["a2", "1e-4", "5", "2", "queued, pos 2", "gpu1", "·", "·"],
      ["c2", "3e-4", "5", "2", "failed, exit 1", "gpu1", "0.2", "$0.42"],
    ]);
    expect(screen.getByRole("link", { name: "b2" }).querySelector("svg")?.getAttribute("data-glyph")).toBe("stale");
    expect(screen.getByRole("link", { name: "b2" }).getAttribute("href")).toBe(`/r/${rid("b2")}`);
  });

  test("the finished runs open from one row", () => {
    renderWithClient(<SweepRuns runs={RUNS} names={NAMES} stale={STALE} hosts={HOSTS} now={NOW} />);
    const more = screen.getByRole("button", { name: "+ 5 finished" });
    expect(more.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(more);
    expect(firstCells()).toEqual(["b2", "a2", "c2", "a1", "b1", "c1", "d1", "d2"]);
    expect(cellsOf(bodyRows()[6] as HTMLElement)).toEqual(["d1", "3e-4", "10", "1", "finished", "dgx", "2.0", "$2.40"]);
    expect(screen.getByRole("button", { name: "hide finished" }).getAttribute("aria-expanded")).toBe("true");
  });

  test("queued runs follow their queue position", () => {
    const a2 = run("a2");
    const first: RunRecord = { ...a2, run_id: rid("q1"), seed: 3, executor: { ...a2.executor, queue_position: 1 } };
    renderWithClient(<SweepRuns runs={[a2, first]} names={NAMES} stale={STALE} hosts={HOSTS} now={NOW} />);
    expect(firstCells()).toEqual(["q1", "a2"]);
    expect(screen.queryByRole("button", { name: /finished/ })).toBeNull();
  });

  test("a queued run on a host that is not connected is stale; hosts are named by environment", () => {
    // a2 waits in the dgx queue; dgx is stale, so it shows stale like b2 (and like its run page)
    const a2: RunRecord = { ...run("a2"), environment_id: "env-dgx" };
    renderWithClient(<SweepRuns runs={[a2]} names={NAMES} stale={STALE} hosts={HOSTS} now={NOW} />);
    expect(cellsOf(bodyRows()[0] as HTMLElement)).toEqual(["a2", "1e-4", "5", "2", "stale 4m", "dgx", "·", "·"]);
    cleanup();
    // without the hosts list the column shows the machine's own hostname (executor.host is never the hub's name)
    renderWithClient(<SweepRuns runs={[run("b2")]} names={NAMES} stale={new Map()} hosts={undefined} now={NOW} />);
    expect(cellsOf(bodyRows()[0] as HTMLElement)[5]).toBe("dgx-h100-07");
  });

  test("no runs yet", () => {
    renderWithClient(<SweepRuns runs={[]} names={NAMES} stale={STALE} hosts={HOSTS} now={NOW} />);
    expect(screen.getByText("No runs indexed yet")).toBeTruthy();
  });
});
