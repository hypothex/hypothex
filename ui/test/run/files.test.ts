import { expect, test } from "bun:test";
import { allFiles, codeRows, dataRows, filesHost, overviewFiles } from "../../src/run/files";
import { REPO, RUN_SVM, STORE, makeDetail, makeRecord } from "../pages/fixtures";

test("overview files: run folder, logs, predictions, checkpoints; paths relative to the run folder", () => {
  const rows = overviewFiles(makeDetail());
  expect(rows.map((r) => [r.icon, r.name, r.path, r.size])).toEqual([
    ["folder", "Run folder", `${STORE}/${RUN_SVM}`, null],
    ["doc", "stdout.log", "logs/stdout.log", null],
    ["doc", "stderr.log", "logs/stderr.log", null],
    ["folder", "predictions", "predictions", null],
    ["box", "model.pkl", "model.pkl", 18494],
  ]);
  expect(rows[1]?.href).toBe(`/r/${RUN_SVM}?tab=logs&log=stdout`);
  expect(rows[1]?.copy).toBe(`${STORE}/${RUN_SVM}/logs/stdout.log`);
});

test("all files add env, config, the diff and every artifact", () => {
  const detail = makeDetail({}, { has_diff: true });
  const names = allFiles(detail).map((r) => r.name);
  expect(names).toEqual(["Run folder", "stdout.log", "stderr.log", "predictions", "env", "git.diff", "model.pkl"]);
});

test("a remote run folder copies host:path and names its host; none gives no rows", () => {
  const detail = makeDetail({}, { paths: { run_dir: "gpu1:/srv/hx/runs/r1", stdout: "gpu1:/srv/hx/runs/r1/logs/stdout.log" } });
  const rows = overviewFiles(detail);
  expect(rows[0]?.copy).toBe("gpu1:/srv/hx/runs/r1");
  expect(rows[1]?.path).toBe("logs/stdout.log");
  expect(filesHost(detail)).toBe("gpu1");
  expect(filesHost(makeDetail())).toBe("mbp.local");
  expect(overviewFiles(makeDetail({}, { paths: {} }))).toEqual([]);
});

test("code rows: the project checkout, and the working directory relative to it when it differs", () => {
  expect(codeRows(makeDetail()).map((r) => [r.name, r.path])).toEqual([["Project", REPO]]);
  const nested = makeDetail({}, { paths: { repo: REPO, cwd: `${REPO}/exp` } });
  expect(codeRows(nested).map((r) => [r.name, r.path, r.copy])).toEqual([["Project", REPO, REPO], ["cwd", "exp", `${REPO}/exp`]]);
});

test("data rows: name, version and split, host:path and size", () => {
  const remote = makeRecord({ datasets: [{ ...makeRecord().datasets[0]!, host: "gpu1", path: "/data/test.jsonl", split: null }] });
  expect(dataRows(makeRecord()).map((r) => [r.name, r.path, r.size])).toEqual([["toyset v1 test", `${REPO}/data/test.jsonl`, 26123]]);
  expect(dataRows(remote).map((r) => [r.name, r.copy])).toEqual([["toyset v1", "gpu1:/data/test.jsonl"]]);
});
