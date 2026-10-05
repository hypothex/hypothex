import { afterEach, describe, expect, mock, setSystemTime, test } from "bun:test";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";

import { auth } from "../../src/api/auth";
import type { RunRecord } from "../../src/api/models";
import { SEED_HINT } from "../../src/launch/command";
import { CONFIG_ERROR, SEED_HISTORY_CUT } from "../../src/launch/draft";
import { LaunchDialog, type LaunchDialogProps } from "../../src/launch/LaunchDialog";
import { LAUNCH_HOSTS_KEY } from "../../src/launch/launchApi";
import { makeRecord } from "../pages/fixtures";
import { type Call, HttpReply, mockApi, mockClipboard, renderWithClient, restoreFetch } from "../pages/helpers";
import { CMD, DGX, FIXTURE_NOW, GPU1, GPU2, MCCLEARY, PROJECT, REPO_PATH, TASK, gpu, hostRow } from "./fixtures";

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
const resendButton = (seed: number): HTMLButtonElement =>
  screen.getByRole("button", { name: `Resend seed ${seed}` }) as HTMLButtonElement;
const typeHypothesis = (text: string): void => {
  fireEvent.change(screen.getByLabelText("Hypothesis"), { target: { value: text } });
};

async function ready(host = "gpu1"): Promise<void> {
  const input = (await screen.findByRole("radio", { name: host })) as HTMLInputElement;
  await waitFor(() => expect(input.checked).toBe(true));
}

describe("host picker", () => {
  test("keeps the selected host visible when its background refresh fails", async () => {
    let failed = false;
    mockApi({
      ...HOSTS,
      "GET /api/v1/hosts": () => failed
        ? new HttpReply(500, { error: "host refresh failed", type: "IndexError" })
        : HOSTS["GET /api/v1/hosts"],
    });
    const { client } = renderWithClient(<LaunchDialog
      project={PROJECT} task={TASK} repo={REPO_PATH}
      initial={{ host: "gpu1", command: CMD, seeds: "4", gpus: 1 }}
      onClose={() => {}} onLaunched={() => {}}
    />);
    await ready();
    typeHypothesis("same selected host");
    failed = true;
    await act(() => client.refetchQueries({ queryKey: LAUNCH_HOSTS_KEY, exact: true }));
    expect((await screen.findByRole("alert")).textContent).toBe("host refresh failed");
    expect(radio("gpu1").checked).toBe(true);
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("1");
    expect(launchButton(1).disabled).toBe(false);
  });

  test("lists the hub and every host and picks the one with the most free GPUs", async () => {
    setSystemTime(new Date(FIXTURE_NOW));
    try {
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
    } finally {
      setSystemTime();
    }
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

for (const method of ["Escape", "Close", "Cancel", "backdrop"]) {
  test(`partial launch ${method} reports confirmed records once before closing`, async () => {
    const calls = mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => seedOf(c) === 4
        ? rec(4)
        : new HttpReply(400, { error: "refused", type: "RunError" }),
    });
    const { onClose, onLaunched } = renderDialog({ initial: { command: CMD, seeds: "4, 5" } });
    await ready();
    typeHypothesis("partial batch");
    fireEvent.click(launchButton(2));
    await screen.findByRole("alert");
    if (method === "Escape") fireEvent.keyDown(screen.getByLabelText("Hypothesis"), { key: "Escape" });
    else if (method === "backdrop") fireEvent.mouseDown(document.querySelector(".hx-launch")!);
    else fireEvent.click(screen.getByRole("button", { name: method }));
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(onLaunched).toHaveBeenCalledTimes(1);
    expect(onLaunched.mock.calls[0]).toEqual([[rec(4)], "gpu1"]);
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onLaunched).toHaveBeenCalledTimes(1);
    expect(posts(calls).map(seedOf)).toEqual([4, 5]);
  });
}

test("closing after a completed batch does not report its records again", async () => {
  mockApi({ ...HOSTS, "POST /api/v1/hosts/gpu1/runs": rec(4) });
  const { onLaunched } = renderDialog({ initial: { command: CMD, seeds: "4" } });
  await ready();
  typeHypothesis("one batch");
  fireEvent.click(launchButton(1));
  await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onLaunched).toHaveBeenCalledTimes(1);
});

test("partial close reports only confirmed runs while an unanswered seed stays unknown", async () => {
  const calls = mockApi({
    ...HOSTS,
    "POST /api/v1/hosts/gpu1/runs": (c: Call) => seedOf(c) === 4
      ? rec(4)
      : new HttpReply(503, { error: "unknown outcome", type: "IndexError" }),
  });
  const { onLaunched } = renderDialog({ initial: { command: CMD, seeds: "4, 5" } });
  await ready();
  typeHypothesis("partial batch");
  fireEvent.click(launchButton(2));
  await screen.findByRole("alert");
  expect(resendButton(5)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onLaunched.mock.calls).toEqual([[[rec(4)], "gpu1"]]);
  expect(posts(calls).map(seedOf)).toEqual([4, 5]);
});

test("partial-close feedback cannot cross a credential generation", async () => {
  mockApi({
    ...HOSTS,
    "POST /api/v1/hosts/gpu1/runs": (c: Call) => seedOf(c) === 4
      ? rec(4)
      : new HttpReply(503, { error: "unknown outcome", type: "IndexError" }),
  });
  const { onClose, onLaunched } = renderDialog({ initial: { command: CMD, seeds: "4, 5" } });
  await ready();
  typeHypothesis("partial batch");
  fireEvent.click(launchButton(2));
  await screen.findByRole("alert");
  act(() => auth.select(null));
  fireEvent.click(screen.getByRole("button", { name: "Close" }));
  expect(onClose).toHaveBeenCalledTimes(1);
  expect(onLaunched).not.toHaveBeenCalled();
});

describe("GPUs and queue", () => {
  test("a CPU template (0 GPUs) stays at 0 on GPU and SLURM hosts and sends gpus 0", async () => {
    const calls = mockApi({ ...HOSTS, "POST /api/v1/hosts/gpu1/runs": (c: Call) => rec(seedOf(c)) });
    renderDialog({ initial: { command: CMD, seeds: "4", gpus: 0 } });
    await ready("gpu1");
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("0");
    fireEvent.click(radio("mccleary"));
    expect(screen.getByLabelText("GPUs per job").textContent).toBe("0");
    fireEvent.click(radio("gpu1"));
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("0");
    // a 0 the hub forced (no GPUs there) goes back to 1 on a GPU host
    fireEvent.click(radio("local"));
    fireEvent.click(radio("gpu1"));
    expect(screen.getByLabelText("GPUs per run").textContent).toBe("1");
    fireEvent.click(screen.getByRole("button", { name: "Fewer GPUs per run" }));
    typeHypothesis("cpu only");
    fireEvent.click(launchButton(1));
    await waitFor(() => expect(posts(calls)).toHaveLength(1));
    expect(posts(calls)[0]?.body).toMatchObject({ gpus: 0 });
  });

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
    expect(screen.getByText("time: e.g. 30, 1:30:00 or 2-01:30:00")).toBeTruthy();
    typeHypothesis("x");
    expect(launchButton(3).title).toBe("time: e.g. 30, 1:30:00 or 2-01:30:00");
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
      "seed 5: index busy. 1 of 2 launched; seed 5 may have started: the form is locked; Resend seed 5 sends it again under the same id.",
    );
    // the hub now has 1 free GPU and 1 seed to send
    await waitFor(() => expect(gpuLine().textContent).toBe("1 now, CUDA_VISIBLE_DEVICES=1"));
    expect(resendButton(5).disabled).toBe(false);
    fireEvent.click(resendButton(5));
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

  test("a launch whose answer is lost locks the form; Resend sends it again with the same id, so no seed starts twice", async () => {
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
      "seed 4: Cannot reach hx serve. 0 of 3 launched; seed 4 may have started: the form is locked; Resend seed 4 sends it again under the same id.",
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
    // Resend settles seed 4 alone; then the form is free again and Launch sends the rest
    fireEvent.click(resendButton(4));
    await waitFor(() => expect(launchButton(2).disabled).toBe(false));
    expect(screen.queryByRole("alert")).toBeNull();
    expect(posts(calls).slice(3).map(seedOf)).toEqual([4]);
    expect(onLaunched).not.toHaveBeenCalled();
    fireEvent.click(launchButton(2));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    expect(started).toEqual([4, 5, 6]);
    const ids = posts(calls).map(idOf);
    expect(new Set(ids.filter((id) => id.endsWith(".s4"))).size).toBe(1);
    const [records, host] = onLaunched.mock.calls[0] as [RunRecord[], string];
    expect(records.map((r) => r.seed)).toEqual([4, 5, 6]);
    expect(host).toBe("gpu1");
  });

  test("a seed that may have started stays locked when its resend finds the host gone; it starts once", async () => {
    const started: number[] = [];
    const byId = new Map<string, RunRecord>();
    let drops = 3;
    let hostDown = false;
    const calls = mockApi({
      ...HOSTS,
      "POST /api/v1/hosts/gpu1/runs": (c: Call) => {
        if (hostDown) return new HttpReply(503, { error: "gpu1 is not connected", type: "HostUnavailableError" });
        let r = byId.get(idOf(c));
        if (r === undefined) {
          r = rec(seedOf(c));
          byId.set(idOf(c), r);
          started.push(seedOf(c));
        }
        if (drops > 0) {
          drops -= 1;
          if (drops === 0) hostDown = true; // the connection to gpu1 drops with the last answer
          throw new TypeError("connection reset");
        }
        return r;
      },
    });
    const { onLaunched } = renderDialog({ initial: { command: CMD, seeds: "4" } });
    await ready();
    typeHypothesis("beam 10 holds");
    fireEvent.click(launchButton(1));
    await screen.findByRole("alert", {}, { timeout: 3000 });
    fireEvent.click(resendButton(4));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toStartWith("seed 4: gpu1 is not connected."));
    // the refusal answers the resend, not the first try: seed 4 may still run, so no edit may give it a new id
    expect(screen.getByRole("alert").textContent).toContain("seed 4 may have started");
    const hyp = screen.getByLabelText("Hypothesis") as HTMLInputElement;
    expect((hyp.closest("fieldset") as HTMLFieldSetElement).disabled).toBe(true);
    typeHypothesis("beam 10 holds, take 2");
    expect(hyp.value).toBe("beam 10 holds");
    hostDown = false;
    fireEvent.click(resendButton(4));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    expect(started).toEqual([4]);
    expect(new Set(posts(calls).map(idOf)).size).toBe(1);
  });

  test("a seed that may have started and took the last free GPU can still be resent, alone", async () => {
    let held = false;
    let drops = 3;
    const calls = mockApi({
      ...HOSTS,
      // the hub has two GPUs; once seed 4 starts it holds GPU 0
      "GET /api/v1/gpus": () => (held ? [gpu(0, { run_id: "r-s4" }), gpu(1)] : [gpu(0), gpu(1)]),
      "POST /api/v1/runs": (c: Call) => {
        if (seedOf(c) === 4) held = true;
        if (seedOf(c) === 4 && drops > 0) {
          drops -= 1;
          throw new TypeError("connection reset"); // seed 4 started; its answer is lost
        }
        return rec(seedOf(c));
      },
    });
    const { onLaunched } = renderDialog({ initial: { command: CMD, seeds: "4, 5", host: "local" } });
    await ready("local");
    typeHypothesis("two seeds on the hub");
    fireEvent.click(launchButton(2));
    await screen.findByRole("alert", {}, { timeout: 3000 });
    // GPU 0 is taken (by seed 4, maybe): a plan for seeds 4 and 5 has room for one only
    await waitFor(() => expect(gpuLine().textContent).toContain("1 won't start"));
    expect(resendButton(4).disabled).toBe(false);
    fireEvent.click(resendButton(4));
    // only seed 4 is sent; seed 5 waits for a plan of its own
    await waitFor(() => expect(launchButton(1).disabled).toBe(false));
    expect(posts(calls).map(seedOf)).toEqual([4, 4, 4, 4]);
    expect(onLaunched).not.toHaveBeenCalled();
    fireEvent.click(launchButton(1));
    await waitFor(() => expect(onLaunched).toHaveBeenCalledTimes(1));
    expect((onLaunched.mock.calls[0] as [RunRecord[], string])[0].map((r) => r.seed)).toEqual([4, 5]);
    expect(new Set(posts(calls).filter((c) => seedOf(c) === 4).map(idOf)).size).toBe(1);
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

test("a disconnected template host stays selected with its requested GPUs", async () => {
  mockApi(HOSTS);
  renderDialog({ templateEnvironment: DGX.state.environment_id!, initial: { command: CMD, seeds: "4", gpus: 2 } });
  await ready("dgx");
  expect(screen.getByLabelText("GPUs per run").textContent).toBe("2");
  expect(radio("local").checked).toBe(false);
  typeHypothesis("repeat");
  expect(launchButton(1).disabled).toBe(true);
});

test("an unknown template environment requires a deliberate host choice", async () => {
  mockApi(HOSTS);
  renderDialog({ templateEnvironment: "removed-env", initial: { command: CMD, seeds: "4", gpus: 2 } });
  await screen.findByText(/Template environment removed-env has no configured host/);
  expect(screen.getAllByRole("radio").some((r) => (r as HTMLInputElement).checked)).toBe(false);
  fireEvent.click(radio("gpu1"));
  expect(radio("gpu1").checked).toBe(true);
});

test("SLURM configured default reaches the form and payload and refetch preserves edits", async () => {
  const defaults = { partition: "gpu", account: null, time: "08:00:00", gpus: 2, extra: [] };
  const slurm = { ...MCCLEARY, slurm: { pending: 0, running: 0, defaults } };
  const calls = mockApi({ ...HOSTS, "GET /api/v1/hosts": [slurm], "POST /api/v1/hosts/mccleary/runs": rec(4) });
  const { client } = renderWithClient(<LaunchDialog project={PROJECT} task={TASK} repo={REPO_PATH} initial={{ host: "mccleary", command: CMD, seeds: "4" }} onClose={() => {}} onLaunched={() => {}} />);
  await ready("mccleary");
  expect(screen.getByLabelText("GPUs per job").textContent).toBe("2");
  fireEvent.click(screen.getByRole("button", { name: "More GPUs per job" }));
  await client.invalidateQueries({ queryKey: ["hosts"] });
  expect(screen.getByLabelText("GPUs per job").textContent).toBe("3");
  typeHypothesis("configured default");
  fireEvent.click(launchButton(1));
  await waitFor(() => expect(posts(calls)).toHaveLength(1));
  expect(posts(calls)[0]?.body).toMatchObject({ gpus: 3, slurm: { gpus: 3 } });
});

test("preview fills carried vars while conflicting params and unknown slots stay out", async () => {
  mockApi(HOSTS);
  renderDialog({ initial: { command: "python {config} {unknown} --seed={seed}", seeds: "4" }, carry: { params: { config: "wrong" }, vars: { config: "a b.yaml" } } });
  await ready();
  const preview = screen.getByLabelText("Preview");
  expect(preview.textContent).toContain("'a b.yaml' {unknown} --seed=4");
  expect(preview.textContent).not.toContain("wrong");
});

test("preview substitutes original seed slots only, leaving seed text inside vars literal", async () => {
  mockApi(HOSTS);
  renderDialog({ initial: { command: "python {config} --seed={seed}", seeds: "9" }, carry: { params: {}, vars: { config: "models/{seed}/config.json" } } });
  await ready();
  const preview = screen.getByLabelText("Preview");
  expect(preview.textContent).toContain("models/{seed}/config.json --seed=9");
  expect(Array.from(preview.querySelectorAll("b.tok"), (node) => node.textContent)).toEqual(["9"]);
});

test("an oversized template GPU request is retained but cannot launch even with Queue", async () => {
  mockApi(HOSTS);
  renderDialog({ initial: { host: "gpu1", command: CMD, seeds: "4", gpus: 99 } });
  await ready("gpu1");
  expect(screen.getByLabelText("GPUs per run").textContent).toBe("99");
  typeHypothesis("repeat oversized request");
  expect(launchButton(1).disabled).toBe(true);
  expect(launchButton(1).getAttribute("title")).toContain("99 GPUs requested; gpu1 has");
});
