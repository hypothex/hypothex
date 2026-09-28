/* Hypothex mockup, kind "training". SAMPLE DATA, invented.
   Curves come from a seeded generator so the numbers stay internally consistent:
   checkpoints read the val curve at their step, test top-1 = val top-1 minus a small
   val/test gap, the best checkpoint is the argmax of val top-1 over checkpoints. */
(function () {
  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function gauss(r) { let u = 0, v = 0; while (u === 0) u = r(); v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
  const r4 = v => Math.round(v * 1e4) / 1e4;

  const STEPS = 20000, VAL_EVERY = 500, CKPT_EVERY = 2000, LOG_EVERY = 50, SYS_EVERY = 100, WARMUP = 1000;
  const N_TEST = 40000;

  const configs = [
    { id: "base", name: "base", lr: 3e-4, aug: false, sec_per_step: 0.94, created_by: "shreyas",
      v: { inf: 0.8958, v0: 0.62, tau: 2500, of: 0.0060 }, vl: { inf: 0.140, l0: 0.46, tau: 2300, of: 0.020 }, tl: { inf: 0.074, l0: 0.58, tau: 2600 }, util: 95, mem: 61.4 },
    { id: "lr1e-4", name: "lr 1e-4", lr: 1e-4, aug: false, sec_per_step: 0.94, created_by: "agent:tuner",
      v: { inf: 0.8966, v0: 0.62, tau: 4300, of: 0.0 }, vl: { inf: 0.143, l0: 0.46, tau: 4200, of: 0.0 }, tl: { inf: 0.101, l0: 0.58, tau: 4600 }, util: 95, mem: 61.4 },
    { id: "aug", name: "+aug", lr: 3e-4, aug: true, sec_per_step: 1.02, created_by: "agent:tuner",
      v: { inf: 0.9098, v0: 0.60, tau: 3100, of: 0.0 }, vl: { inf: 0.121, l0: 0.47, tau: 3000, of: 0.0 }, tl: { inf: 0.129, l0: 0.61, tau: 3200 }, util: 86, mem: 64.2 },
  ];

  const HOSTS = { base: "gpu-a01", "lr1e-4": "gpu-a02", aug: "gpu-a03" };
  const HEX = ["a3c1", "5e07", "d94b", "71f2", "0c8e", "b46a", "e2d5", "9f30", "48ac"];
  const T0 = Date.parse("2026-09-24T23:15:02Z");

  function lrAt(peak, s) {
    if (s < WARMUP) return peak * s / WARMUP;
    const p = (s - WARMUP) / (STEPS - WARMUP);
    return peak * (0.1 + 0.9 * 0.5 * (1 + Math.cos(Math.PI * p)));
  }

  const runs = [];
  let k = 0;
  configs.forEach((c, ci) => {
    [1, 2, 3].forEach(seed => {
      const r = rng(1000 * (ci + 1) + seed * 41);
      const hex = HEX[k];
      const started = new Date(T0 + k * 2000);
      const stamp = started.toISOString().replace(/[-:]/g, "").slice(0, 15).replace("T", "-");
      const id = `${stamp}-uspto-forward-top1-${hex}`;
      const diverged = c.id === "base" && seed === 2;
      const killed = c.id === "aug" && seed === 3;
      const stop = killed ? 14000 : STEPS;
      const off = { v: gauss(r) * 0.0014, vl: gauss(r) * 0.003, tl: gauss(r) * 0.003 };
      const SPIKE = 9000;
      /* divergence: loss spike at 9k, partial recovery, lasting penalty */
      const pen = s => (diverged && s >= SPIKE ? Math.exp(-(s - SPIKE) / 520) : 0);
      const penLong = s => (diverged && s >= SPIKE ? 1 - Math.exp(-(s - SPIKE) / 900) : 0);

      const train = [];
      for (let s = LOG_EVERY; s <= stop; s += LOG_EVERY) {
        let base = c.tl.inf + off.tl + (c.tl.l0 - c.tl.inf) * Math.exp(-s / c.tl.tau);
        base += 2.75 * pen(s) + 0.052 * penLong(s);
        train.push([s, r4(base * Math.exp(gauss(r) * 0.075))]);
      }
      const val = [];
      for (let s = VAL_EVERY; s <= stop; s += VAL_EVERY) {
        const x = s / STEPS;
        let top1 = c.v.inf + off.v - (c.v.inf - c.v.v0) * Math.exp(-s / c.v.tau) - c.v.of * x * x * x;
        let loss = c.vl.inf + off.vl + (c.vl.l0 - c.vl.inf) * Math.exp(-s / c.vl.tau) + c.vl.of * x * x * x;
        top1 -= 0.45 * pen(s) + 0.029 * penLong(s);
        loss += 0.95 * pen(s) + 0.058 * penLong(s);
        val.push([s, r4(top1 + gauss(r) * 0.0009), r4(loss * Math.exp(gauss(r) * 0.012))]);
      }
      const lr = [];
      for (let s = 0; s <= stop; s += SYS_EVERY) lr.push([s, +lrAt(c.lr, s).toExponential(3)]);
      const sys = [];
      for (let s = SYS_EVERY; s <= stop; s += SYS_EVERY) {
        const evalDip = s % VAL_EVERY === 0;
        const ckptDip = s % CKPT_EVERY === 0;
        let u = c.util + gauss(r) * 1.6;
        if (evalDip) u = 38 + gauss(r) * 4;
        if (ckptDip) u = 22 + gauss(r) * 3;
        const m = s < 300 ? c.mem * (s / 300) : c.mem + gauss(r) * 0.15 + (evalDip ? 1.8 : 0);
        sys.push([s, Math.max(0, Math.min(100, Math.round(u))), Math.round(m * 10) / 10]);
      }
      const gap = 0.0026 + gauss(r) * 0.0006; /* val/test gap for this run */
      const dir = `/scratch/shreyas/hx/rxn-forward/runs/${id}`;
      const ckpts = [];
      for (let s = CKPT_EVERY; s <= stop; s += CKPT_EVERY) {
        const v = val.find(p => p[0] === s);
        ckpts.push({ step: s, val_top1: v[1], val_loss: v[2], size_gb: 0.54, path: `${dir}/ckpt/step_${String(s).padStart(6, "0")}.pt`, sha: hex + ((s * 2654435761) >>> 0).toString(16).slice(0, 8) });
      }
      const best = ckpts.reduce((a, b) => (b.val_top1 > a.val_top1 ? b : a));
      best.best = true;
      /* test counts are integers out of N_TEST */
      const testOf = v => Math.round((v - gap) * N_TEST) / N_TEST;
      best.test_top1 = testOf(best.val_top1);
      const last = ckpts[ckpts.length - 1];
      if (!killed) last.test_top1 = testOf(val[val.length - 1][1]);

      const secs = stop * c.sec_per_step;
      runs.push({
        run_id: id, config: c.id, seed, host: HOSTS[c.id], gpu: `cuda:${seed - 1}`, gpu_name: "A100 80GB",
        status: killed ? "killed" : "finished", exit_code: killed ? 137 : 0,
        event: diverged ? { kind: "diverged", step: SPIKE, peak: Math.max(...train.filter(p => p[0] >= SPIKE && p[0] < SPIKE + 400).map(p => p[1])) } : killed ? { kind: "killed", step: stop, why: "preempted, SIGKILL" } : null,
        created_by: c.created_by,
        started_at: started.toISOString(), ended_at: new Date(started.getTime() + secs * 1000).toISOString(),
        steps: stop,
        final_top1: killed ? null : last.test_top1,
        best_step: best.step, best_top1: best.test_top1,
        command: ["python", "train.py", "--config", `configs/${c.id}.yaml`, "--seed", String(seed)],
        command_template: ["python", "train.py", "--config", `configs/${c.id}.yaml`, "--seed", "{seed}"],
        git: { branch: "main", commit: c.id === "base" ? "3d9e1a7" : "b82f04c", dirty: false },
        paths: {
          repo: "/home/shreyas/code/rxn-forward",
          run_dir: dir,
          stdout: `${dir}/logs/stdout.log`, stderr: `${dir}/logs/stderr.log`,
          metrics: `${dir}/metrics.jsonl`, config: `${dir}/config.yaml`, env: `${dir}/env`,
          ckpt_dir: `${dir}/ckpt`,
        },
        train, val, lr, sys, ckpts,
      });
      k++;
    });
  });

  window.HX = {
    sample: true,
    project: "rxn-forward", task: "uspto-forward-top1", kind: "training",
    dataset: { name: "uspto-mit", version: "v2", n_train: 409035, n_val: 30000, n_test: N_TEST, host: "nfs-01", path: "/data/uspto-mit/v2", hash: "sha256:9b1f0c4e2a77d315" },
    metric: { name: "top1", version: "v1" },
    schedule: { steps: STEPS, warmup: WARMUP, kind: "cosine", floor: 0.1, val_every: VAL_EVERY, ckpt_every: CKPT_EVERY },
    configs: configs.map(c => ({ id: c.id, name: c.name, lr: c.lr, aug: c.aug, created_by: c.created_by, commit: c.id === "base" ? "3d9e1a7" : "b82f04c" })),
    runs,
  };
})();
