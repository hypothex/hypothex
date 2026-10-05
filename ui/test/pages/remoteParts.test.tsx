import { describe, expect, test } from "bun:test";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Placement, placementRows } from "../../src/pages/components/Placement";
import { QueuePanel, queueRows, queuedRunsQuery } from "../../src/pages/components/QueuePanel";
import { REMOTE_CSS } from "../../src/pages/components/remoteStyles";
import { StateBanner } from "../../src/pages/components/StateBanner";
import { StatusLine, placeParts } from "../../src/pages/components/StatusLine";
import { makeRecord } from "./fixtures";
import { mockClipboard, renderWithClient } from "./helpers";
import {
  DGX,
  GPU1,
  MCCLEARY,
  NOW,
  QUEUED_ID,
  lostRecord,
  pendingRecord,
  queuedRecord,
  runningRecord,
  staleRecord,
} from "./remoteFixtures";

describe("placementRows", () => {
  test("queued: host, GPUs to come, queue place", () => {
    expect(placementRows(queuedRecord(), "queued", GPU1)).toEqual([
      { key: "Host", value: "gpu1", note: "ssh", copy: "gpu1" },
      { key: "GPUs", value: "2×A100 80GB", note: "assigned at start" },
      { key: "Queue", value: "2 of 3", note: "since 14:21" },
    ]);
  });

  test("pending SLURM job", () => {
    expect(placementRows(pendingRecord(), "pending", MCCLEARY)).toEqual([
      { key: "Host", value: "mccleary", note: "slurm", copy: "mccleary" },
      { key: "Job", value: "4471031", note: "pending", copy: "4471031", mono: true },
      { key: "GPUs", value: "2 GPUs", note: "assigned at start" },
    ]);
  });

  test("running on an SSH host: CUDA_VISIBLE_DEVICES and pid", () => {
    expect(placementRows(runningRecord(), "running", GPU1)).toEqual([
      { key: "Host", value: "gpu1", note: "ssh", copy: "gpu1" },
      {
        key: "GPUs",
        value: "CUDA_VISIBLE_DEVICES=0",
        note: "1×A100 80GB",
        copy: "CUDA_VISIBLE_DEVICES=0",
        mono: true,
      },
      { key: "PID", value: "2291045", mono: true },
    ]);
  });

  test("stale: the pid is as of the last answer", () => {
    expect(placementRows(staleRecord(), "stale", DGX).at(-1)).toEqual({
      key: "PID",
      value: "118734",
      note: "as of 14:28",
      mono: true,
    });
  });

  test("lost SLURM run: job, node, GPUs, cost", () => {
    expect(placementRows(lostRecord(), "lost", MCCLEARY)).toEqual([
      { key: "Host", value: "mccleary", note: "slurm", copy: "mccleary" },
      { key: "Job", value: "4471023", copy: "4471023", mono: true },
      { key: "Node", value: "r814u05n01", copy: "r814u05n01", mono: true },
      {
        key: "GPUs",
        value: "CUDA_VISIBLE_DEVICES=0,1",
        note: "2 GPUs",
        copy: "CUDA_VISIBLE_DEVICES=0,1",
        mono: true,
      },
      { key: "Cost", value: "$2.17", note: "3.50 GPU h, API $0.42" },
    ]);
  });

  test("cost: unpriced GPU hours show `—` as the stat strip does; an all-zero cost shows no row", () => {
    const unpriced = { gpu_hours: 1.5, gpu_usd: 0, api_usd: 0, total_usd: 0 };
    const noRate = { ...MCCLEARY, usd_per_gpu_hour: null };
    expect(placementRows(lostRecord({ cost: unpriced }), "lost", noRate).at(-1)).toEqual({
      key: "Cost",
      value: "—",
      note: "1.50 GPU h, API $0.000, no GPU rate for this host",
    });
    const zero = { gpu_hours: 0, gpu_usd: 0, api_usd: 0, total_usd: 0 };
    expect(placementRows(lostRecord({ cost: zero }), "lost", MCCLEARY).map((r) => r.key)).not.toContain("Cost");
  });

  test("Placement draws the rows and copies a value", async () => {
    const written = mockClipboard();
    render(<Placement rows={placementRows(lostRecord(), "lost", MCCLEARY)} />);
    const keys = [...document.querySelectorAll(".place-row .k")].map((k) => k.textContent);
    expect(keys).toEqual(["Host", "Job", "Node", "GPUs", "Cost"]);
    expect(document.querySelector(".place-row .v.mono")?.textContent).toBe("4471023");
    fireEvent.click(screen.getByRole("button", { name: "Copy Job 4471023" }));
    await waitFor(() => expect(written).toEqual(["4471023"]));
  });
});

describe("queue", () => {
  const others = [
    queuedRecord({
      run_id: "20261003-142500-toy-test-93e7",
      hypothesis: "lr 1e-3 with beam 5",
      created_at: "2026-10-03T14:25:00Z",
      executor: { ...queuedRecord().executor, queue_position: 3 },
    }),
    queuedRecord(),
    queuedRecord({
      run_id: "20261003-142000-toy-test-b7e0",
      hypothesis: "aug plus seed 5",
      created_by: "human:shreyas",
      created_at: "2026-10-03T14:20:00Z",
      executor: { ...queuedRecord().executor, queue_position: 1 },
    }),
    queuedRecord({
      run_id: "20261003-140000-toy-test-dd01",
      environment_id: "env-dgx",
      host: "dgx-h100-07",
      executor: { ...queuedRecord().executor, host: "dgx-h100-07", queue_position: 1 },
    }),
    runningRecord(),
  ];

  test("queueRows keeps the queued runs of this run's environment (its host), in queue order", () => {
    expect(queueRows(others, "env-gpu1", NOW)).toEqual([
      {
        position: 1,
        runId: "20261003-142000-toy-test-b7e0",
        label: "aug plus seed 5 · seed 3",
        createdBy: "human:shreyas",
        gpus: 2,
        waiting: "14m",
      },
      { position: 2, runId: QUEUED_ID, label: "lr 1e-3 with beam 1 · seed 3", createdBy: "agent:tuner", gpus: 2, waiting: "12m" },
      {
        position: 3,
        runId: "20261003-142500-toy-test-93e7",
        label: "lr 1e-3 with beam 5 · seed 3",
        createdBy: "agent:tuner",
        gpus: 2,
        waiting: "9m",
      },
    ]);
  });

  test("queueRows keeps the page's own run when the list lacks it; the query names the environment", () => {
    expect(queuedRunsQuery("env-gpu1")).toEqual({ status: "queued", environment_id: "env-gpu1" });
    // the list was read just before this run was indexed: it still shows, at its position
    const without = others.filter((r) => r.run_id !== QUEUED_ID);
    expect(queueRows(without, "env-gpu1", NOW, queuedRecord()).map((r) => [r.position, r.runId])).toEqual([
      [1, "20261003-142000-toy-test-b7e0"],
      [2, QUEUED_ID],
      [3, "20261003-142500-toy-test-93e7"],
    ]);
    // listed once when the list has it; never added when it is not queued or on another host
    expect(queueRows(others, "env-gpu1", NOW, queuedRecord()).filter((r) => r.runId === QUEUED_ID)).toHaveLength(1);
    expect(queueRows(without, "env-gpu1", NOW, runningRecord())).toHaveLength(2);
    expect(queueRows(without, "env-dgx", NOW, queuedRecord()).map((r) => r.runId)).toEqual([
      "20261003-140000-toy-test-dd01",
    ]);
  });

  test("QueuePanel GPU cells are the hosts grid's: index order, one wide cell per run, run over external", () => {
    const g = GPU1.gpus[0]!;
    const run = "20261003-150000-toy-test-ab12";
    const gpus = [
      { ...g, index: 3, run_id: null, external: false, util: 0 },
      { ...g, index: 1, run_id: run, external: false, util: 80 },
      { ...g, index: 0, run_id: null, external: true, util: 40 },
      { ...g, index: 2, run_id: run, external: true, util: 61 },
    ];
    renderWithClient(<QueuePanel host={{ ...GPU1, gpus }} hostName="gpu1" runId={QUEUED_ID} rows={[]} />);
    const cells = [...document.querySelectorAll<HTMLElement>(".gpu-cells li")];
    expect(cells.map((c) => [c.className, c.textContent, c.style.gridColumn, c.title])).toEqual([
      ["c ext", "external40%", "", "GPU 0: process outside hx, 40% busy"],
      ["c run", "ab1271% ×2", "span 2", "GPU 1–2: hx run, 71% busy"],
      ["c free", "free0%", "", "GPU 3: free, 0% busy"],
    ]);
  });

  test("QueuePanel shows the GPUs and marks this run", () => {
    renderWithClient(
      <QueuePanel host={GPU1} hostName="gpu1" runId={QUEUED_ID} rows={queueRows(others, "env-gpu1", NOW)} />,
    );
    const cells = [...document.querySelectorAll(".gpu-cells li")].map((c) => [c.className, c.textContent]);
    expect(cells).toEqual([
      ["c run", "6b0e92%"],
      ["c ext", "external63%"],
      ["c free", "free0%"],
    ]);
    const rows = [...document.querySelectorAll(".queue-t tbody tr")];
    expect(rows.map((r) => r.querySelector("td")?.textContent)).toEqual(["1", "2", "3"]);
    const me = document.querySelector('.queue-t tr[aria-current="true"]');
    expect(me?.querySelector("b")?.textContent).toBe("f2c8");
    expect(screen.getByRole("link", { name: "b7e0" }).getAttribute("href")).toBe(
      "/r/20261003-142000-toy-test-b7e0",
    );
  });

  test("QueuePanel with no queued runs and no hosts list", () => {
    renderWithClient(<QueuePanel host={null} hostName="gpu1" runId={QUEUED_ID} rows={[]} />);
    expect(document.querySelector(".gpu-cells")).toBeNull();
    expect(screen.getByText("No queued runs on gpu1")).toBeTruthy();
  });
});

describe("status line and state bar", () => {
  test("placeParts per phase", () => {
    expect(placeParts(makeRecord(), "local", null)).toEqual(["mbp.local"]);
    expect(placeParts(queuedRecord(), "queued", GPU1)).toEqual(["2 of 3 on gpu1", "needs 2 GPU, 1 free"]);
    // without the hosts list: the machine's own hostname
    expect(placeParts(queuedRecord(), "queued", null)).toEqual(["2 in queue on sv-a100-01", "needs 2 GPU"]);
    const unplaced = queuedRecord({ executor: { ...queuedRecord().executor, queue_position: null } });
    expect(placeParts(unplaced, "queued", GPU1)).toEqual(["queued on gpu1", "needs 2 GPU, 1 free"]);
    expect(placeParts(pendingRecord(), "pending", MCCLEARY)).toEqual(["mccleary, job 4471031 pending"]);
    expect(placeParts(runningRecord(), "running", GPU1)).toEqual(["gpu1, pid 2291045"]);
    expect(placeParts(lostRecord(), "lost", MCCLEARY)).toEqual(["mccleary, job 4471023"]);
  });

  test("StatusLine of a stale run: stale chip, time gone, host and pid", () => {
    render(<StatusLine record={staleRecord()} phase="stale" host={DGX} now={NOW} />);
    const parts = [...(document.querySelector(".status")?.children ?? [])].map((c) => c.textContent);
    expect(parts).toEqual(["stale", "5m", "seed 3", "11:03:55 UTC", "agent:acceptance", "dgx, pid 118734"]);
    expect(document.querySelector(".status .st")?.className).toBe("st stale");
  });

  test("StatusLine of a hub run is unchanged", () => {
    render(<StatusLine record={makeRecord()} />);
    const parts = [...(document.querySelector(".status")?.children ?? [])].map((c) => c.textContent);
    expect(parts).toEqual(["finished", "0.8 s", "seed 3", "21:03:06 UTC", "agent:acceptance", "mbp.local", "best", "svm"]);
  });

  test("StateBanner of a stale run", () => {
    render(<StateBanner record={staleRecord()} phase="stale" host={DGX} conn="stale" now={NOW} />);
    const bar = screen.getByRole("status");
    expect(bar.className).toBe("state-bar");
    expect([...bar.children].map((c) => c.textContent)).toEqual([
      "dgx unreachable 5m",
      "since 14:28:02 UTC",
      "no ping for 60 s",
      "stale",
    ]);
  });

  test("StateBanner of a lost run names the reason", () => {
    render(<StateBanner record={lostRecord()} phase="lost" host={MCCLEARY} conn="connected" now={NOW} />);
    const bar = screen.getByRole("status");
    expect(bar.className).toBe("state-bar lost");
    expect([...bar.children].map((c) => c.textContent)).toEqual([
      "SLURM job 4471023 lost",
      "r814u05n01",
      "02:14:37 UTC",
      "no exit code",
    ]);
    expect(bar.querySelector("b")?.getAttribute("title")).toBe(
      "The env server marked this run lost. Its run.lost event has the reason.",
    );
  });

  test("StateBanner of a lost run shows the run.lost reason first when the tab saw it", () => {
    const why = "SLURM ended job 4471023 with NODE_FAIL on r814u05n01; no exit record";
    render(
      <StateBanner record={lostRecord()} phase="lost" host={MCCLEARY} conn="connected" now={NOW} reason={why} />,
    );
    const bar = screen.getByRole("status");
    expect([...bar.children].map((c) => c.textContent)).toEqual([
      "SLURM job 4471023 lost",
      why,
      "r814u05n01",
      "02:14:37 UTC",
      "no exit code",
    ]);
    expect(bar.querySelector("b")?.getAttribute("title")).toBe("Reason from the run's run.lost event.");
  });

  test("StateBanner draws nothing for a running run", () => {
    const { container } = render(
      <StateBanner record={runningRecord()} phase="running" host={GPU1} conn="connected" now={NOW} />,
    );
    expect(container.innerHTML).toBe("");
  });
});

test("remote CSS stays inside .page", () => {
  const rules = REMOTE_CSS.split("\n").filter((line) => line.trim() !== "");
  expect(rules.length).toBeGreaterThan(10);
  expect(rules.filter((line) => !line.startsWith(".page "))).toEqual([]);
});

test("queue labels distinguish equal hypotheses by params and seed, preserving global rank", () => {
  const base = makeRecord({ status: "queued", hypothesis: "same", seed: 3, params: { lr: "0.1" }, executor: { ...makeRecord().executor, queue_position: 17 } });
  const rows = queueRows([base, { ...base, run_id: "other", params: { lr: "0.2" } }], base.environment_id);
  expect(rows[0]?.position).toBe(17);
  expect(rows[0]?.label).toContain("lr=0.1");
  expect(rows[0]?.label).toContain("seed 3");
  expect(rows[0]?.label).not.toBe(rows[1]?.label);
});
