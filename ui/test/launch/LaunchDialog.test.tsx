import { afterEach, describe, expect, mock, test } from "bun:test";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { RunRecord } from "../../src/api/models";
import { SEED_HINT } from "../../src/launch/command";
import { CONFIG_ERROR, SEED_HISTORY_CUT } from "../../src/launch/draft";
import { LaunchDialog, type LaunchDialogProps } from "../../src/launch/LaunchDialog";
import { makeRecord } from "../pages/fixtures";
import { type Call, HttpReply, mockApi, mockClipboard, renderWithClient, restoreFetch } from "../pages/helpers";
import { CMD, DGX, GPU1, GPU2, MCCLEARY, PROJECT, REPO_PATH, TASK, gpu, hostRow } from "./fixtures";

afterEach(restoreFetch);

const HOSTS = {
  "GET /api/v1/hosts": [GPU1, DGX, MCCLEARY, GPU2],
  "GET /api/v1/gpus": [],
  "GET /api/v1/queue": [],
};
const rec = (seed: number): RunRecord =>
  makeRecord({ run_id: `20261003-120000-${TASK}-s${seed}`, seed, status: "queued" });
const seedOf = (call: Call): number => (call.body as { seed: number }).seed;
const idOf = (call: Call): string => (call.body as { command_id: string }).command_id;
const posts = (calls: Call[]): Call[] => calls.filter((c) => c.method === "POST");

function renderDialog(over: Partial<LaunchDialogProps> = {}) {
  const onClose = mock(() => {});
  const onLaunched = mock((_records: RunRecord[], _host: string) => {});
  renderWithClient(
    <LaunchDialog
      project={PROJECT}
      task={TASK}
      repo={REPO_PATH}
      initial={{ command: CMD, seeds: "4, 5, 6" }}
      onClose={onClose}
      onLaunched={onLaunched}
      {...over}
    />,
  );
  return { onClose, onLaunched };
}

const radio = (name: string): HTMLInputElement => screen.getByRole("radio", { name }) as HTMLInputElement;
const rowOf = (name: string): HTMLLabelElement => radio(name).closest("label") as HTMLLabelElement;
const gpuLine = (): HTMLElement => screen.getByTitle("Seeds that start now, and seeds that wait in the hx queue");
const launchButton = (n: number): HTMLButtonElement =>
  screen.getByRole("button", { name: `Launch ${n}` }) as HTMLButtonElement;
const typeHypothesis = (text: string): void => {
  fireEvent.change(screen.getByLabelText("Hypothesis"), { target: { value: text } });
};

async function ready(host = "gpu1"): Promise<void> {
  const input = (await screen.findByRole("radio", { name: host })) as HTMLInputElement;
  await waitFor(() => expect(input.checked).toBe(true));
}

describe("host picker", () => {
  test("lists the hub and every host and picks the one with the most free GPUs", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready("gpu1");
    expect(screen.getByRole("dialog", { name: "New run" })).toBeTruthy();
    expect(screen.getByText(`${PROJECT} / ${TASK}`)).toBeTruthy();
    const group = screen.getByRole("radiogroup", { name: "Host" });
    expect(within(group).getAllByRole("radio").map((r) => r.getAttribute("aria-label"))).toEqual([
      "local",
      "gpu1",
      "dgx",
      "mccleary",
      "gpu2",
    ]);
    expect(rowOf("gpu1").textContent).toContain("1 free");
    expect(rowOf("gpu1").textContent).toContain("q 3");
    expect(rowOf("gpu1").title).toBe("gpu1: 8 GPU (A100 80GB), 1 free, 3 queued");
    expect(rowOf("gpu1").querySelectorAll(".mini i.free")).toHaveLength(1);
    expect(rowOf("gpu1").querySelectorAll(".mini i.other")).toHaveLength(2);
    expect(rowOf("local").textContent).toContain("no GPU");
    expect(rowOf("mccleary").textContent).toContain("4 run, 6 pend");
    expect(radio("dgx").disabled).toBe(true);
    expect(rowOf("dgx").textContent).toContain("stale 4m");
    expect(rowOf("dgx").title).toBe("dgx stale 4m: no heartbeat");
    expect(radio("gpu2").disabled).toBe(true);
    expect(rowOf("gpu2").title).toBe("installing hx on gpu2");
  });

  test("a host without this project is disabled with the fix", async () => {
    mockApi({ ...HOSTS, "GET /api/v1/hosts": [GPU1, hostRow("gpu3", { projects: ["other"], gpus: [gpu(0)] })] });
    renderDialog();
    await ready("gpu1");
    expect(radio("gpu3").disabled).toBe(true);
    expect(rowOf("gpu3").textContent).toContain("no path");
    expect(rowOf("gpu3").title).toBe("no path for rxn-forward on gpu3: hx hosts map rxn-forward gpu3 <path>");
  });

  test("keeps the initial host when it can take the run", async () => {
    mockApi(HOSTS);
    renderDialog({ initial: { command: CMD, seeds: "4, 5, 6", host: "mccleary" } });
    await ready("mccleary");
  });

  test("a failing hosts list shows the error and nothing can launch", async () => {
    mockApi({ "GET /api/v1/hosts": new HttpReply(500, { error: "hub index locked", type: "IndexError" }) });
    renderDialog();
    expect((await screen.findByRole("alert")).textContent).toBe("hub index locked");
    typeHypothesis("x");
    expect(launchButton(3).disabled).toBe(true);
    expect(launchButton(3).title).toBe("pick a host");
    expect((screen.getByRole("button", { name: "Copy as CLI" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("GPUs and queue", () => {
  test("shows the GPU plan, the queue position, the preview and the summary", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("1");
    expect(gpuLine().textContent).toBe("1 now, CUDA_VISIBLE_DEVICES=5, 2 queued");
    expect(screen.getByText("pos 4–5")).toBeTruthy();
    expect(screen.getByLabelText("Preview").textContent).toBe(
      "gpu1: CUDA_VISIBLE_DEVICES=5 python train.py --lr 3e-4 --seed 4",
    );
    expect(screen.getAllByText("×3")).toHaveLength(2);
    expect(screen.getByText("3 × 1 GPU on gpu1")).toBeTruthy();
    expect(launchButton(3).disabled).toBe(true);
    expect(launchButton(3).title).toBe("hypothesis required");
    typeHypothesis("beam 10 holds on 3 new seeds");
    expect(launchButton(3).disabled).toBe(false);
    expect(launchButton(3).title).toBe("Launch 3 on gpu1");
  });

  test("the stepper moves seeds into the queue and stops at the host's GPU count", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    const more = screen.getByRole("button", { name: "More GPUs per run" }) as HTMLButtonElement;
    fireEvent.click(more);
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("2");
    expect(gpuLine().textContent).toBe("0 now, 3 queued");
    expect(screen.getByText("pos 4–6")).toBeTruthy();
    expect(screen.getByLabelText("Preview").textContent).toBe("gpu1: python train.py --lr 3e-4 --seed 4");
    for (let i = 0; i < 10; i += 1) fireEvent.click(more);
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("8");
    expect(more.disabled).toBe(true);
  });

  test("queue off: seeds that cannot start block Launch", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    typeHypothesis("x");
    fireEvent.click(screen.getByRole("checkbox", { name: "wait for GPUs" }));
    expect(gpuLine().textContent).toBe("1 now, CUDA_VISIBLE_DEVICES=5, 2 won't start");
    expect(launchButton(3).disabled).toBe(true);
    expect(launchButton(3).title).toBe("2 won't start: 1 GPU free; turn on Queue");
    expect(screen.queryByText(/^pos /)).toBeNull();
  });

  test("a SLURM host swaps GPUs and Queue for sbatch fields", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    fireEvent.click(radio("mccleary"));
    await waitFor(() => expect(radio("mccleary").checked).toBe(true));
    expect(screen.queryByRole("checkbox", { name: "wait for GPUs" })).toBeNull();
    expect(screen.queryByLabelText("GPUs per run")).toBeNull();
    fireEvent.change(screen.getByLabelText("partition"), { target: { value: "gpu" } });
    fireEvent.change(screen.getByLabelText("time"), { target: { value: "08:00:00" } });
    fireEvent.click(screen.getByRole("button", { name: "More GPUs per job" }));
    expect(screen.getByLabelText("GPUs per job").textContent).toBe("2");
    expect(screen.getByText("sbatch --partition gpu --time 08:00:00 --gpus 2")).toBeTruthy();
    expect(screen.getByText("3 jobs × 2 GPU, ≤ 08:00:00")).toBeTruthy();
    expect(screen.getByLabelText("Preview").textContent).toBe("mccleary: python train.py --lr 3e-4 --seed 4");
    fireEvent.change(screen.getByLabelText("time"), { target: { value: "8h" } });
    expect(screen.getByText("time: use h:mm:ss or d-hh:mm:ss")).toBeTruthy();
    typeHypothesis("x");
    expect(launchButton(3).title).toBe("time: use h:mm:ss or d-hh:mm:ss");
  });

  test("the hub: no queue, GPUs from its own nvidia-smi, launches through /api/v1/runs", async () => {
    const calls = mockApi({ ...HOSTS, "POST /api/v1/runs": (c: Call) => rec(seedOf(c)) });
    const { onLaunched } = renderDialog();
    await ready();
    fireEvent.click(radio("local"));
    await waitFor(() => expect(radio("local").checked).toBe(true));
    expect(screen.queryByRole("checkbox", { name: "wait for GPUs" })).toBeNull();
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("0");
    expect((screen.getByRole("button", { name: "More GPUs per run" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByLabelText("Preview").textContent).toBe("local: python train.py --lr 3e-4 --seed 4");
    expect(screen.getByText("3 runs on local, no GPU")).toBeTruthy();
    typeHypothesis("cpu smoke test");
    fireEvent.click(launchButton(3));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    expect(
      posts(calls).map((c) => {
        const body = c.body as { gpus: number; queue: boolean };
        return [c.url, body.gpus, body.queue];
      }),
    ).toEqual([
      ["/api/v1/runs", 0, false],
      ["/api/v1/runs", 0, false],
      ["/api/v1/runs", 0, false],
    ]);
    expect(onLaunched.mock.calls[0]?.[1]).toBe("local");
  });
});

describe("seeds and command", () => {
  test("the template marks {seed} and carries the quoting hint as a tooltip", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    const marks = screen.getByTestId("template-highlight").querySelectorAll("mark.tok");
    expect(marks).toHaveLength(1);
    expect(marks[0]?.textContent).toBe("{seed}");
    expect(marks[0]?.getAttribute("title")).toBe(SEED_HINT);
    const box = screen.getByLabelText("Command") as HTMLTextAreaElement;
    expect(box.value).toBe(CMD);
    expect(box.closest(".tmpl")?.getAttribute("title")).toBe(SEED_HINT);
    fireEvent.change(box, { target: { value: "python train.py --lr 3e-4" } });
    expect(screen.getByText("no {seed} in the command: every seed runs the same command")).toBeTruthy();
    expect(screen.getByTestId("template-highlight").querySelectorAll("mark.tok")).toHaveLength(0);
    fireEvent.change(box, { target: { value: "python 'oops" } });
    expect(screen.getByText("command: unclosed ' quote")).toBeTruthy();
    expect(screen.getByLabelText("Preview").textContent).toBe("·");
  });

  test("seeds: the count follows the list and a bad seed is named", async () => {
    mockApi(HOSTS);
    renderDialog();
    await ready();
    const seeds = screen.getByLabelText("Seeds");
    fireEvent.change(seeds, { target: { value: "1-5" } });
    expect(launchButton(5)).toBeTruthy();
    expect(screen.getAllByText("×5")).toHaveLength(2);
    fireEvent.change(seeds, { target: { value: "4, x" } });
    expect(screen.getByText("bad seed x")).toBeTruthy();
    expect(launchButton(0).disabled).toBe(true);
  });
});

describe("template defaults", () => {
  test("{config} from a template run's --config blocks Launch until the command names the file", async () => {
    mockApi(HOSTS);
    renderDialog({ initial: { command: "python train.py --config {config} --seed {seed}", seeds: "4, 5, 6" } });
    await ready();
    typeHypothesis("aug config holds");
    expect(screen.getByText(`command: ${CONFIG_ERROR}`)).toBeTruthy();
    expect(launchButton(3).disabled).toBe(true);
    expect(launchButton(3).title).toBe(`command: ${CONFIG_ERROR}`);
    fireEvent.change(screen.getByLabelText("Command"), {
      target: { value: "python train.py --config configs/aug.yaml --seed {seed}" },
    });
    expect(launchButton(3).disabled).toBe(false);
  });

  test("{config} carried as a var fills, so Launch is enabled", async () => {
    mockApi(HOSTS);
    renderDialog({
      initial: { command: "python train.py --config {config} --seed {seed}", seeds: "4, 5, 6" },
      carry: { params: {}, vars: { config: "configs/aug.yaml" } },
    });
    await ready();
    typeHypothesis("aug config holds");
    expect(launchButton(3).disabled).toBe(false);
  });

  test("a seeds note is shown next to the seeds", async () => {
    mockApi(HOSTS);
    renderDialog({ initial: { command: CMD, seeds: "" }, seedsNote: SEED_HISTORY_CUT });
    await ready();
    expect(screen.getByText(SEED_HISTORY_CUT)).toBeTruthy();
  });
});

describe("Copy as CLI", () => {
  test("copies the exact hx launch lines, one per seed", async () => {
    const written = mockClipboard();
    mockApi(HOSTS);
    renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    fireEvent.click(screen.getByRole("button", { name: "Copy as CLI" }));
    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toBe(
      [4, 5, 6]
        .map(
          (s) =>
            `hx launch --repo ${REPO_PATH} -t ${TASK} --host gpu1 --gpus 1 --queue --seed ${s} -H 'beam 10 holds' -- python train.py --lr 3e-4 --seed '{seed}'`,
        )
        .join("\n"),
    );
    expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
  });

  test("after a refused seed, the preview and Copy as CLI cover only the seeds not launched", async () => {
    const written = mockClipboard();
    let refuse = true;
    mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => {
        if (seedOf(c) === 5 && refuse) {
          refuse = false;
          return new HttpReply(400, { error: "runner busy", type: "RunError" });
        }
        return rec(seedOf(c));
      },
    });
    renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    expect(screen.getByLabelText("Preview").textContent).toBe(
      "gpu1: CUDA_VISIBLE_DEVICES=5 python train.py --lr 3e-4 --seed 4",
    );
    fireEvent.click(launchButton(3));
    await screen.findByRole("alert");
    // seed 4 started: the preview shows seed 5, and the count and the copied lines skip seed 4
    expect(screen.getByLabelText("Preview").textContent).toBe(
      "gpu1: CUDA_VISIBLE_DEVICES=5 python train.py --lr 3e-4 --seed 5",
    );
    expect(document.querySelector(".hx-launch .prev .xn")?.textContent).toBe("×2");
    fireEvent.click(screen.getByRole("button", { name: "Copy as CLI" }));
    await waitFor(() => expect(written).toHaveLength(1));
    expect(written[0]).toBe(
      [5, 6]
        .map(
          (s) =>
            `hx launch --repo ${REPO_PATH} -t ${TASK} --host gpu1 --gpus 1 --queue --seed ${s} -H 'beam 10 holds' -- python train.py --lr 3e-4 --seed '{seed}'`,
        )
        .join("\n"),
    );
    expect(launchButton(2).disabled).toBe(false);
  });

  test("a blocked clipboard says so", async () => {
    mockClipboard(true);
    mockApi(HOSTS);
    renderDialog();
    await ready();
    fireEvent.click(screen.getByRole("button", { name: "Copy as CLI" }));
    expect(await screen.findByRole("button", { name: "Clipboard blocked" })).toBeTruthy();
  });
});

describe("Launch", () => {
  test("sends one POST per seed with ids from one attempt; a double click launches once", async () => {
    const calls = mockApi({ ...HOSTS, "POST /api/v1/hosts/gpu1/runs": (c: Call) => rec(seedOf(c)) });
    const { onLaunched } = renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    const launch = launchButton(3);
    fireEvent.click(launch);
    fireEvent.click(launch);
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const sent = posts(calls);
    expect(sent.map(seedOf)).toEqual([4, 5, 6]);
    const base = idOf(sent[0] as Call).replace(/\.s4$/, "");
    expect(sent.map(idOf)).toEqual([`${base}.s4`, `${base}.s5`, `${base}.s6`]);
    expect(sent[0]?.body).toEqual({
      command_id: `${base}.s4`,
      created_by: "human",
      project: PROJECT,
      task: TASK,
      command: ["python", "train.py", "--lr", "3e-4", "--seed", "{seed}"],
      hypothesis: "beam 10 holds",
      seed: 4,
      tags: [],
      params: {},
      vars: {},
      gpus: 1,
      queue: true,
    });
    const [records, host] = onLaunched.mock.calls[0] as [RunRecord[], string];
    expect(records.map((r) => r.seed)).toEqual([4, 5, 6]);
    expect(host).toBe("gpu1");
    // a host launch names the project; the hub's repo path never leaves this machine
    expect(sent.every((c) => !("repo" in (c.body as Record<string, unknown>)))).toBe(true);
    expect(sent.every((c) => !("commit" in (c.body as Record<string, unknown>)))).toBe(true);
  });

  test("a partial launch on the hub: the retry needs GPUs only for the seeds not started", async () => {
    let held = false;
    let refuse = true;
    const calls = mockApi({
      ...HOSTS,
      // after seed 4 starts, it holds GPU 0 of the hub's two
      "GET /api/v1/gpus": () => (held ? [gpu(0, { run_id: "r-s4" }), gpu(1)] : [gpu(0), gpu(1)]),
      "POST /api/v1/runs": (c: Call) => {
        if (seedOf(c) === 4) held = true;
        if (seedOf(c) === 5 && refuse) {
          refuse = false;
          return new HttpReply(503, { error: "index busy", type: "IndexError" });
        }
        return rec(seedOf(c));
      },
    });
    const { onLaunched } = renderDialog({ initial: { command: CMD, seeds: "4, 5", host: "local" } });
    await ready("local");
    typeHypothesis("two seeds on the hub");
    fireEvent.click(launchButton(2));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "seed 5: index busy. 1 of 2 launched; seed 5 may have started: the form is locked and Launch re-sends it under the same id.",
    );
    // the hub now has 1 free GPU and 1 seed to send: Launch stays enabled
    await waitFor(() => expect(gpuLine().textContent).toBe("1 now, CUDA_VISIBLE_DEVICES=1"));
    expect(launchButton(1).disabled).toBe(false);
    fireEvent.click(launchButton(1));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const seeds = posts(calls).map(seedOf);
    expect(seeds).toEqual([4, 5, 5]);
    expect((onLaunched.mock.calls[0] as [RunRecord[], string])[0].map((r) => r.seed)).toEqual([4, 5]);
  });

  test("after a refused seed, Launch sends only the seeds not launched, with the same command ids", async () => {
    let refuse = true;
    const calls = mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => {
        if (seedOf(c) === 5 && refuse) {
          refuse = false;
          return new HttpReply(400, { error: "runner busy", type: "RunError" });
        }
        return rec(seedOf(c));
      },
    });
    const { onLaunched } = renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    fireEvent.click(launchButton(3));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "seed 5: runner busy. 1 of 3 launched; Launch sends the other 2.",
    );
    expect(onLaunched).not.toHaveBeenCalled();
    const first = posts(calls).map(idOf);
    expect(first).toHaveLength(2);
    fireEvent.click(launchButton(2));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const second = posts(calls).slice(2);
    expect(second.map(seedOf)).toEqual([5, 6]);
    expect(idOf(second[0] as Call)).toBe(first[1]);
    const [records] = onLaunched.mock.calls[0] as [RunRecord[], string];
    expect(records.map((r) => r.seed)).toEqual([4, 5, 6]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  test("after a partial launch the host is locked, and onLaunched names the host every seed runs on", async () => {
    let refuse = true;
    const calls = mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => {
        if (seedOf(c) === 5 && refuse) {
          refuse = false;
          return new HttpReply(400, { error: "runner busy", type: "RunError" });
        }
        return rec(seedOf(c));
      },
    });
    const { onLaunched } = renderDialog();
    await ready();
    expect(radio("mccleary").disabled).toBe(false);
    expect(radio("local").disabled).toBe(false);
    typeHypothesis("beam 10 holds");
    fireEvent.click(launchButton(3));
    await screen.findByRole("alert");
    // seed 4 runs on gpu1: the rest may not go to another host
    expect(radio("gpu1").checked).toBe(true);
    expect(radio("gpu1").disabled).toBe(false);
    for (const name of ["local", "mccleary"]) {
      expect(radio(name).disabled).toBe(true);
      expect(rowOf(name).title).toBe("seeds started on gpu1: the rest go there");
    }
    fireEvent.click(radio("mccleary"));
    expect(radio("gpu1").checked).toBe(true);
    fireEvent.click(launchButton(2));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const sent = posts(calls);
    expect(sent).toHaveLength(4);
    expect(sent.every((c) => c.url.endsWith("/api/v1/hosts/gpu1/runs"))).toBe(true);
    const [records, host] = onLaunched.mock.calls[0] as [RunRecord[], string];
    expect(records.map((r) => r.seed)).toEqual([4, 5, 6]);
    expect(host).toBe("gpu1");
  });

  test("when the first seed is refused, no host is locked and the retry can go to another host", async () => {
    const gpu3 = hostRow("gpu3", { gpus: [gpu(0), gpu(1), gpu(2)] });
    const calls = mockApi({
      ...HOSTS,
      "GET /api/v1/hosts": [GPU1, DGX, MCCLEARY, GPU2, gpu3],
      // not connected: the hub forwarded nothing, so nothing started
      "POST /api/v1/hosts/gpu1/runs": () =>
        new HttpReply(503, { error: "host unreachable", type: "HostUnavailableError" }),
      "POST /api/v1/hosts/gpu3/runs": (c: Call) => rec(seedOf(c)),
    });
    const { onLaunched } = renderDialog({ initial: { command: CMD, seeds: "4, 5, 6", host: "gpu1" } });
    await ready("gpu1");
    typeHypothesis("beam 10 holds");
    fireEvent.click(launchButton(3));
    expect((await screen.findByRole("alert")).textContent).toContain("seed 4: host unreachable");
    expect(posts(calls)).toHaveLength(1);
    // no seed started on gpu1: every host the run fits stays open
    for (const name of ["local", "mccleary", "gpu3"]) {
      expect(radio(name).disabled).toBe(false);
      expect(rowOf(name).title).not.toBe("seeds started on gpu1: the rest go there");
    }
    fireEvent.click(radio("gpu3"));
    expect(radio("gpu3").checked).toBe(true);
    fireEvent.click(launchButton(3));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const retry = posts(calls).slice(1);
    expect(retry.map(seedOf)).toEqual([4, 5, 6]);
    expect(retry.every((c) => c.url.endsWith("/api/v1/hosts/gpu3/runs"))).toBe(true);
    const [records, host] = onLaunched.mock.calls[0] as [RunRecord[], string];
    expect(records.map((r) => r.seed)).toEqual([4, 5, 6]);
    expect(host).toBe("gpu3");
  });

  test("a partial launch, then an edit: Launch sends only the seeds not launched, under a new attempt", async () => {
    let refuse = true;
    const calls = mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => {
        if (seedOf(c) === 5 && refuse) {
          refuse = false;
          return new HttpReply(400, { error: "runner busy", type: "RunError" });
        }
        return rec(seedOf(c));
      },
    });
    const { onLaunched } = renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    fireEvent.click(launchButton(3));
    await screen.findByRole("alert");
    const first = posts(calls);
    expect(first.map(seedOf)).toEqual([4, 5]);
    typeHypothesis("beam 10 holds, take 2");
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(launchButton(2));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const second = posts(calls).slice(2);
    // seed 4 started already: a new attempt id must not start it twice
    expect(second.map(seedOf)).toEqual([5, 6]);
    expect(idOf(second[0] as Call)).not.toBe(idOf(first[1] as Call));
    const [records] = onLaunched.mock.calls[0] as [RunRecord[], string];
    expect(records.map((r) => r.seed)).toEqual([4, 5, 6]);
  });

  test("editing the form after a failure starts a new attempt id", async () => {
    let refuse = true;
    const calls = mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => {
        if (refuse) {
          refuse = false;
          return new HttpReply(400, { error: "runner busy", type: "RunError" });
        }
        return rec(seedOf(c));
      },
    });
    const { onLaunched } = renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    fireEvent.click(launchButton(3));
    await screen.findByRole("alert");
    typeHypothesis("beam 10 holds, take 2");
    expect(screen.queryByRole("alert")).toBeNull();
    fireEvent.click(launchButton(3));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    const ids = posts(calls).map(idOf);
    expect(ids).toHaveLength(4);
    expect(ids[0]?.endsWith(".s4")).toBe(true);
    expect(ids[1]?.endsWith(".s4")).toBe(true);
    expect(ids[1]).not.toBe(ids[0]);
  });

  test("a launch whose answer is lost locks the form; Launch re-sends it with the same ids, so no seed starts twice", async () => {
    const started: number[] = [];
    const byId = new Map<string, RunRecord>();
    let drops = 3;
    const calls = mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => {
        // the server keeps one run per command_id, like the hub's receipts
        let r = byId.get(idOf(c));
        if (r === undefined) {
          r = rec(seedOf(c));
          byId.set(idOf(c), r);
          started.push(seedOf(c));
        }
        if (seedOf(c) === 4 && drops > 0) {
          drops -= 1;
          throw new TypeError("connection reset"); // seed 4 started; its answer is lost
        }
        return r;
      },
    });
    const { onLaunched } = renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    fireEvent.click(launchButton(3));
    expect((await screen.findByRole("alert", {}, { timeout: 3000 })).textContent).toBe(
      "seed 4: Cannot reach hx serve. 0 of 3 launched; seed 4 may have started: the form is locked and Launch re-sends it under the same id.",
    );
    // an edit would give seed 4 a new command id and start it a second time
    const hyp = screen.getByLabelText("Hypothesis") as HTMLInputElement;
    expect((hyp.closest("fieldset") as HTMLFieldSetElement).disabled).toBe(true);
    typeHypothesis("beam 10 holds, take 2");
    expect(hyp.value).toBe("beam 10 holds");
    fireEvent.click(radio("mccleary"));
    expect(radio("gpu1").checked).toBe(true);
    // pasted lines would start seed 4 again too
    expect((screen.getByRole("button", { name: "Copy as CLI" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(launchButton(3));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    expect(started).toEqual([4, 5, 6]);
    const ids = posts(calls).map(idOf);
    expect(new Set(ids.filter((id) => id.endsWith(".s4"))).size).toBe(1);
    const [records, host] = onLaunched.mock.calls[0] as [RunRecord[], string];
    expect(records.map((r) => r.seed)).toEqual([4, 5, 6]);
    expect(host).toBe("gpu1");
  });

  test("while seeds are sent, the host and the fields are locked to the launch in progress", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let refuse = true;
    const calls = mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": async (c: Call) => {
        if (seedOf(c) === 4) await gate;
        if (seedOf(c) === 5 && refuse) {
          refuse = false;
          return new HttpReply(400, { error: "runner busy", type: "RunError" });
        }
        return rec(seedOf(c));
      },
    });
    const { onLaunched } = renderDialog();
    await ready();
    typeHypothesis("beam 10 holds");
    fireEvent.click(launchButton(3));
    await screen.findByRole("button", { name: "Launching 0/3" });
    fireEvent.click(radio("mccleary"));
    typeHypothesis("changed mid-launch");
    expect(radio("gpu1").checked).toBe(true);
    expect((screen.getByLabelText("Hypothesis") as HTMLInputElement).value).toBe("beam 10 holds");
    release();
    await screen.findByRole("alert");
    // seed 4 runs on gpu1, and gpu1 is still the host Launch sends the rest to
    expect(radio("gpu1").checked).toBe(true);
    expect(launchButton(2).disabled).toBe(false);
    fireEvent.click(launchButton(2));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    expect(posts(calls).every((c) => c.url.endsWith("/api/v1/hosts/gpu1/runs"))).toBe(true);
    expect(posts(calls).every((c) => (c.body as { hypothesis: string }).hypothesis === "beam 10 holds")).toBe(true);
    expect((onLaunched.mock.calls[0] as [RunRecord[], string])[1]).toBe("gpu1");
  });

  test("Escape, Close and Cancel call onClose", async () => {
    mockApi(HOSTS);
    const { onClose } = renderDialog();
    await ready();
    fireEvent.keyDown(screen.getByLabelText("Hypothesis"), { key: "Escape" });
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onClose).toHaveBeenCalledTimes(3);
  });
});
