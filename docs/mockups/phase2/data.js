/* Phase 2 mockup: remote machines. All numbers are INVENTED sample data. */
(function () {
  /* deterministic noise, so every screenshot draws the same curves */
  let s = 7;
  const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
  const noise = a => (rnd() - 0.5) * 2 * a;

  /* a training curve up to `upto` steps: train loss every 100, val top-1 every 500 */
  function curve(upto, peak, seedShift) {
    const train = [], val = [];
    for (let k = 0; k <= upto; k += 100) {
      const t = k / 20000;
      train.push([k, +(0.09 + 0.42 * Math.exp(-t * 5.2) + seedShift * 0.01 + noise(0.012)).toFixed(4)]);
    }
    for (let k = 500; k <= upto; k += 500) {
      const t = k / 20000;
      val.push([k, +(peak - 0.11 * Math.exp(-t * 6.5) + noise(0.0016)).toFixed(4)]);
    }
    return { train, val };
  }

  const NOW = "2026-10-03T14:32:00Z";
  const HUB_HX = "0.5.0";

  /* ------------------------------------------------------------------ hosts */
  const hosts = [
    {
      id: "hub", name: "this Mac", kind: "hub", addr: "shreyas-mbp.local", state: "connected", seen: "14:32:00",
      hx: "0.5.0", gpu_name: "M3 Max", gpus: 1, rate: null, gpu_h_today: 0, queue: 0,
      cells: [{ i: 0, gpu: "mps", run: "7c1a", label: "eval +aug, beam 10", who: "human:shreyas", util: 41, mem: 22 }],
    },
    {
      id: "gpu1", name: "gpu1", kind: "ssh", addr: "shreyas@gpu1.lab.internal", state: "connected", seen: "14:31:58",
      hx: "0.4.1", gpu_name: "A100 80GB", gpus: 8, rate: 1.10, gpu_h_today: 96.4, queue: 3,
      root: "/scratch/shreyas/hx",
      cells: [
        { i: 0, run: "6b0e", label: "lr 1e-3, beam 5, seed 2", who: "agent:tuner", util: 92, mem: 71, span: 2, utils: [92, 89] },
        { i: 2, run: "1d77", label: "lr 1e-4, beam 10, seed 2", who: "agent:tuner", util: 84, mem: 66 },
        { i: 3, other: true, pid: 30117, user: "jlee", proc: "python", util: 63, mem: 41 },
        { i: 4, run: "52c9", label: "+aug, seed 4", who: "human:shreyas", util: 77, mem: 64 },
        { i: 5, free: true },
        { i: 6, run: "3fa2", label: "eval beam 10", who: "agent:tuner", util: 35, mem: 18 },
        { i: 7, other: true, pid: 2210, user: "root", proc: "ollama", util: 9, mem: 18 },
      ],
    },
    {
      id: "dgx", name: "dgx", kind: "ssh", addr: "shreyas@dgx-03.cs.example.edu", state: "stale", seen: "14:28:02",
      hx: "0.5.0", gpu_name: "H100 80GB", gpus: 8, rate: 2.90, gpu_h_today: 71.2, queue: 2,
      root: "/raid/shreyas/hx",
      cells: [
        { i: 0, run: "8e41", label: "+aug 4-GPU, seed 1", who: "human:shreyas", util: 95, mem: 74, span: 4, utils: [96, 95, 94, 95] },
        { i: 4, run: "a9d3", label: "lr 1e-3, beam 10, seed 2", who: "agent:tuner", util: 88, mem: 70, span: 2, utils: [88, 87] },
        { i: 6, run: "0f6c", label: "lr 3e-4, ablate SMILES aug", who: "agent:tuner", util: 81, mem: 66 },
        { i: 7, free: true },
      ],
    },
    {
      id: "mccleary", name: "mccleary", kind: "slurm", addr: "sv482@mccleary.ycrc.yale.edu", state: "connected", seen: "14:31:40",
      hx: "0.5.0", partition: "gpu", rate: 0.50, gpu_h_today: 38.0, queue: 0,
      root: "/vast/palmer/scratch/sv482/hx",
      slurm: { running: 4, pending: 6, gpus_running: 8, oldest_pending: "18m", fairshare: 0.41 },
    },
    {
      id: "gpu2", name: "gpu2", kind: "ssh", addr: "shreyas@gpu2.lab.internal", state: "bootstrapping", seen: "14:31:51",
      hx: null, gpu_name: "A6000 48GB", gpus: 4, rate: 0.80, gpu_h_today: 0, queue: 0,
      boot: { step: 3, steps: ["ssh key", "python 3.11", "uv, hx 0.5.0", "CUDA probe", "register"] },
      cells: [],
    },
  ];

  /* ------------------------------------------------------------------ sweep: lr × beam × 3 seeds */
  const LRS = ["1e-4", "3e-4", "1e-3"], BEAMS = [1, 5, 10];
  /* per-cell seed scores; null = not finished. st: f finished, r running, q queued, x failed */
  const grid = {
    "1e-4|1":  { runs: [["a3c1", "f", 0.8917, "gpu1"], ["5e07", "f", 0.8931, "gpu1"], ["d94b", "f", 0.8915, "dgx"]] },
    "1e-4|5":  { runs: [["71f2", "f", 0.8979, "gpu1"], ["0c8e", "f", 0.8992, "mccleary"], ["b46a", "f", 0.8990, "mccleary"]] },
    "1e-4|10": { runs: [["e5a0", "f", 0.8996, "dgx"], ["1d77", "r", null, "gpu1"], ["c2b9", "q", null, "gpu1"]] },
    "3e-4|1":  { runs: [["9f30", "f", 0.9046, "dgx"], ["48ac", "f", 0.9031, "dgx"], ["e2d5", "f", 0.9052, "mccleary"]] },
    "3e-4|5":  { runs: [["5b11", "f", 0.9101, "mccleary"], ["c7d4", "f", 0.9117, "dgx"], ["2a90", "f", 0.9106, "gpu1"]] },
    "3e-4|10": { runs: [["7e3f", "f", 0.9118, "dgx"], ["f0a1", "f", 0.9130, "mccleary"], ["66cd", "f", 0.9115, "gpu1"]] },
    "1e-3|1":  { runs: [["4d2e", "f", 0.8806, "mccleary"], ["8b5f", "f", 0.8829, "gpu1"], ["f2c8", "q", null, "gpu1"]] },
    "1e-3|5":  { runs: [["0a6d", "f", 0.8871, "dgx"], ["6b0e", "r", null, "gpu1"], ["93e7", "q", null, "gpu1"]] },
    "1e-3|10": { runs: [["d1f4", "f", 0.8880, "mccleary"], ["a9d3", "r", null, "dgx"], ["b8c3", "x", null, "mccleary"]] },
  };
  const sweep = {
    id: "s-7f3a", name: "lr × beam", created_by: "agent:tuner", started: "09:12", eta: "1h 40m",
    lrs: LRS, beams: BEAMS, seeds: [1, 2, 3], grid,
    gpus_per_run: 2,
    gpu_h: { gpu1: 41.2, dgx: 38.4, mccleary: 22.0 },
    template: "python train.py --config configs/aug.yaml --lr {lr} --beam {beam} --seed {seed}",
    failed_why: { b8c3: "loss NaN at step 3.1k, exit 1" },
    p_best: 0.24,
  };

  /* ------------------------------------------------------------------ the four run states */
  const runs = {
    queued: {
      run_id: "20261003-142104-uspto-forward-top1-f2c8", short: "f2c8", title: "lr 1e-3, beam 1, seed 3",
      hypothesis: "lr 1e-3 trains faster without hurting top-1", sweep: "s-7f3a", created_by: "agent:tuner",
      state: "queued", host: "gpu1", gpus: 2, queued_at: "14:21:04", pos: 2, of: 3, free: 1,
      command: "python train.py --config configs/aug.yaml --lr 1e-3 --beam 1 --seed 3",
      repo: "/home/shreyas/code/rxn-forward", run_dir: "/scratch/shreyas/hx/rxn-forward/runs/20261003-142104-uspto-forward-top1-f2c8",
      git: { branch: "main", commit: "b82f04c" },
      ahead: [{ pos: 1, run: "b7e0", label: "+aug, seed 5", who: "human:shreyas", gpus: 2, wait: "14m" }],
      behind: [{ pos: 3, run: "93e7", label: "lr 1e-3, beam 5, seed 3", who: "agent:tuner", gpus: 2, wait: "9m" }],
    },
    running: {
      run_id: "20261003-123940-uspto-forward-top1-c90b", short: "c90b", title: "+aug long, seed 1",
      hypothesis: "40k steps lifts +aug past 0.915 top-1", created_by: "human:shreyas",
      state: "running", host: "mccleary", gpus: 2, started: "12:39:40", elapsed: "1h 52m",
      step: 6200, steps: 40000, peak: 0.913, gpu_util: 88, gpu_mem: 69,
      slurm: { job: "48213077", node: "r209u14n01", partition: "gpu", time: "1:52:20", limit: "8:00:00", gres: "gpu:a100:2" },
      cvd: "0,1", pid: 2291045, heartbeat: "14:31:52",
      command: "python train.py --config configs/aug.yaml --steps 40000 --seed 1",
      repo: "/home/sv482/code/rxn-forward", run_dir: "/vast/palmer/scratch/sv482/hx/rxn-forward/runs/20261003-123940-uspto-forward-top1-c90b",
      git: { branch: "long-sched", commit: "e41a9d0" },
    },
    stale: {
      run_id: "20261003-110355-uspto-forward-top1-a9d3", short: "a9d3", title: "lr 1e-3, beam 10, seed 2",
      hypothesis: "lr 1e-3 trains faster without hurting top-1", sweep: "s-7f3a", created_by: "agent:tuner",
      state: "stale", host: "dgx", gpus: 2, started: "11:03:55", last_event: "14:28:02", unreachable: "6m",
      step: 9400, steps: 20000, peak: 0.889, gpu_util: 88, gpu_mem: 70,
      cvd: "4,5", pid: 118734, retry_in: "30s", tries: 7,
      command: "python train.py --config configs/aug.yaml --lr 1e-3 --beam 10 --seed 2",
      repo: "/home/shreyas/code/rxn-forward", run_dir: "/raid/shreyas/hx/rxn-forward/runs/20261003-110355-uspto-forward-top1-a9d3",
      git: { branch: "main", commit: "b82f04c" },
    },
    lost: {
      run_id: "20261003-012210-uspto-forward-top1-5e9a", short: "5e9a", title: "+aug long, seed 2",
      hypothesis: "40k steps lifts +aug past 0.915 top-1", created_by: "human:shreyas",
      state: "lost", host: "mccleary", gpus: 2, started: "01:22:10", last_event: "02:14:37",
      step: 12400, steps: 40000, peak: 0.911, ckpt: 12000,
      reason: "NODE_FAIL", reason_long: "SLURM ended job 48211932 with NODE_FAIL on r208u06n02 at 02:14. No exit code, no final metrics.",
      slurm: { job: "48211932", node: "r208u06n02", partition: "gpu", time: "0:52:27", limit: "8:00:00", gres: "gpu:a100:2" },
      cvd: "0,1",
      command: "python train.py --config configs/aug.yaml --steps 40000 --seed 2",
      repo: "/home/sv482/code/rxn-forward", run_dir: "/vast/palmer/scratch/sv482/hx/rxn-forward/runs/20261003-012210-uspto-forward-top1-5e9a",
      git: { branch: "long-sched", commit: "e41a9d0" },
    },
  };
  runs.running.curve = curve(runs.running.step, runs.running.peak, 0);
  runs.stale.curve = curve(runs.stale.step, runs.stale.peak, 1);
  runs.lost.curve = curve(runs.lost.step, runs.lost.peak, -1);

  /* ------------------------------------------------------------------ overview context */
  const ideas = [
    { name: "lr × beam sweep", who: "agent:tuner", at: "09:12", score: 0.9121, sub: "best of 9", runs: 27, best: true },
    { name: "+aug", who: "agent:tuner", at: "yesterday", score: 0.9067, sub: "± 0.0023", runs: 3 },
    { name: "+aug long, 40k steps", who: "human:shreyas", at: "01:22", score: null, sub: "1 running, 1 lost", runs: 2 },
    { name: "lr 1e-4", who: "agent:tuner", at: "yesterday", score: 0.8915, sub: "± 0.0021", runs: 3 },
    { name: "base", who: "human:shreyas", at: "2 Oct", score: 0.8874, sub: "± 0.0068", runs: 3 },
  ];

  window.HX = {
    now: NOW, hub_hx: HUB_HX, project: "rxn-forward", task: "uspto-forward-top1",
    metric: { name: "top-1", version: "v1" }, n_test: 40000,
    hosts, sweep, runs, ideas,
    failures: [{ run: "b8c3", label: "lr 1e-3, beam 10, seed 3", why: "NaN at 3.1k, exit 1", host: "mccleary", at: "13:05" }, { run: "5e9a", label: "+aug long, seed 2", why: "lost, NODE_FAIL", host: "mccleary", at: "02:14" }],
    launch: {
      command: "python train.py --config configs/aug.yaml --lr 3e-4 --beam 10 --seed {seed}",
      hypothesis: "beam 10 at lr 3e-4 holds on 3 new seeds",
      seeds: "4, 5, 6",
    },
  };
})();
