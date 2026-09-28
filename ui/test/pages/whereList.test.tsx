import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WhereList, buildWhere, gitLine } from "../../src/pages/components/WhereList";
import { REPO, RUN_SVM, STORE, makeDetail } from "./fixtures";
import { mockClipboard } from "./helpers";

afterEach(cleanup);

const DIR = `${STORE}/${RUN_SVM}`;

describe("buildWhere", () => {
  test("local run: repo with its dataset, run folder with relative children", () => {
    const [project, run, ...rest] = buildWhere(makeDetail());
    expect(rest).toEqual([]);
    expect(project).toEqual({
      title: "Project",
      host: "local",
      rows: [
        { display: REPO, copy: REPO, indent: false },
        {
          display: "data/test.jsonl",
          copy: `${REPO}/data/test.jsonl`,
          indent: true,
          note: "toyset v1 test, 26.1 KB",
        },
      ],
    });
    expect(run?.title).toBe("Run");
    expect(run?.rows.map((r) => r.display)).toEqual([
      DIR,
      "logs/stdout.log",
      "logs/stderr.log",
      "predictions",
      "env",
      "model.pkl",
    ]);
    expect(run?.rows[2]).toEqual({
      display: "logs/stderr.log",
      copy: `${DIR}/logs/stderr.log`,
      indent: true,
      href: `/r/${RUN_SVM}?log=stderr`,
    });
    expect(run?.rows[5]?.note).toBe("checkpoint, 18.5 KB");
  });

  test("remote data gets its own group; a tracked diff is listed", () => {
    const detail = makeDetail(
      {
        datasets: [
          {
            name: "uspto",
            version: "v2",
            split: null,
            host: "nfs-01",
            path: "/data/uspto/v2",
            hash: null,
            hash_mode: null,
            size: null,
            checked_at: null,
          },
        ],
        artifacts: [
          { kind: "checkpoint", path: "/scratch/ckpt/step_18000.pt", host: "gpu-a03", size: null, step: 18000, metrics: {} },
        ],
      },
      { has_diff: true },
    );
    const groups = buildWhere(detail);
    expect(groups.map((g) => g.title)).toEqual(["Project", "Data", "Run"]);
    expect(groups[1]).toEqual({
      title: "Data",
      host: "nfs-01",
      rows: [{ display: "nfs-01:/data/uspto/v2", copy: "nfs-01:/data/uspto/v2", indent: false, note: "uspto v2" }],
    });
    const run = groups[2]?.rows ?? [];
    expect(run.find((r) => r.display === "git.diff")?.note).toBe("tracked diff");
    expect(run.at(-1)).toEqual({
      display: "gpu-a03:/scratch/ckpt/step_18000.pt",
      copy: "gpu-a03:/scratch/ckpt/step_18000.pt",
      indent: false,
      note: "checkpoint, step 18000",
    });
  });
});

test("a long artifact path outside the run folder shows its tail, full path as tooltip and copy", () => {
  const long = "/scratch/shreyas/hx/rxn-forward/runs/20260925-131516-uspto-forward-to-5a7a/ckpt/step_002000.pt";
  const detail = makeDetail(
    {
      artifacts: [{ kind: "checkpoint", path: long, host: "gpu-a03", size: null, step: 2000, metrics: {} }],
    },
    {},
  );
  const row = buildWhere(detail).at(-1)?.rows.at(-1);
  expect(row?.display).toBe("gpu-a03:…/ckpt/step_002000.pt");
  expect(row?.copy).toBe(`gpu-a03:${long}`);
  expect(row?.title).toBe(`gpu-a03:${long}`);
});

test("gitLine separates tracked changes from untracked files", () => {
  const base = { repo: null, commit: "8f4cac43877b", branch: "main" };
  expect(gitLine({ ...base, dirty: false, untracked_count: 0 })).toEqual({
    ref: "main @ 8f4cac4",
    state: "clean",
    text: "tracked clean",
    untracked: [],
  });
  expect(gitLine({ ...base, dirty: false, untracked_count: 2, untracked: ["a.py", "b.txt"] })).toEqual({
    ref: "main @ 8f4cac4",
    state: "untracked",
    text: "untracked files only",
    untracked: ["a.py", "b.txt"],
  });
  expect(gitLine({ ...base, dirty: true, untracked_count: 1, untracked: ["a.py"] })?.text).toBe(
    "tracked changes, 1 untracked",
  );
  expect(gitLine({ ...base, branch: null, dirty: false })?.ref).toBe("detached @ 8f4cac4");
  expect(gitLine({ ...base, commit: null, dirty: false })).toBeNull();
});

test("WhereList shows command, git state, links, and copies full paths", async () => {
  const written = mockClipboard();
  render(<WhereList detail={makeDetail()} />);
  expect(screen.getByText("python train_eval.py --model svm --seed=3")).toBeTruthy();
  expect(screen.getByText("python train_eval.py --model svm --seed={seed}")).toBeTruthy();
  const untracked = screen.getByText("untracked files only");
  expect(untracked.parentElement?.getAttribute("title")).toBe("scratch.py\nnotes.txt");
  expect(screen.getByRole("link", { name: "logs/stderr.log" }).getAttribute("href")).toBe(
    `/r/${RUN_SVM}?log=stderr`,
  );
  fireEvent.click(screen.getByRole("button", { name: "Copy data/test.jsonl" }));
  await waitFor(() => expect(written).toEqual([`${REPO}/data/test.jsonl`]));
});
