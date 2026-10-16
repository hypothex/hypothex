/** A RunContext for tab and sidebar tests, built the way RunPage builds it. */
import type { RunDetail, TaskRuns } from "../../src/api/models";
import { type RunContext, runIdentity } from "../../src/run/runContext";
import { runTitle } from "../../src/run/RunName";
import { makeDetail } from "../pages/fixtures";
import { makeTaskRuns } from "./taskRunsFixtures";

export function makeCtx(over: Partial<RunContext> = {}, detail: RunDetail = makeDetail(), data: TaskRuns | null = makeTaskRuns()): RunContext {
  const identity = runIdentity(data, detail.record.run_id);
  return {
    runId: detail.record.run_id,
    detail,
    record: detail.record,
    phase: "local",
    host: null,
    hostsLoaded: false,
    remote: false,
    now: Date.parse("2026-09-26T21:10:00Z"),
    lostWhy: null,
    hubEnvId: null,
    taskRuns: data,
    identity,
    title: runTitle(identity.run, detail.record),
    kind: { kind: "generic", run_view: [] },
    kindError: null,
    inferStage: undefined,
    compareHref: undefined,
    example: undefined,
    log: null,
    ...over,
  };
}

/** Text of a sidebar property's value, by its label. */
export function propValue(label: string): string | null {
  const row = [...document.querySelectorAll(".rside .prop")].find((r) => r.querySelector(".k")?.textContent === label);
  return row?.querySelector(".v")?.textContent ?? null;
}
