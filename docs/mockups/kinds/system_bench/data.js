/* Sample data for the system_bench mockup. Invented, deterministic (seeded RNG).
   Stands in for what the API would return: run records, raw latency samples
   (samples.parquet), 1 Hz utilisation (util.csv) and a concurrency sweep.
   Every summary number on the page is computed from these arrays. */
(function (root) {
  /* ---------------------------------------------------------------- rng */
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function normal(r) { let u = 0, v = 0; while (u === 0) u = r(); while (v === 0) v = r(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); }
  const logn = (r, med, sig) => med * Math.exp(sig * normal(r));

  /* ---------------------------------------------------------------- task */
  const TASK = {
    project: "route-search",
    task: "route-api-latency",
    kind: "system_bench",
    requests: 5000,
    warmup: 200,
    concurrency: 16,
    timeout_ms: 1000,
    host: "gpu-box-1",
    gpu: "1× L40S",
    endpoint: "POST /v2/route",
    primary: "p95",
  };

  /* ---------------------------------------------------------------- versions */
  const VERSIONS = [
    { id: "baseline", name: "baseline", branch: "main", commit: "a1b2c3d9e8f70615", by: "human", note: "main@a1b2" },
    { id: "cache", name: "cache-enabled", branch: "feat/route-cache", commit: "c7e41f02b6a95d38", by: "agent:bench", note: "LRU 50k" },
    { id: "async", name: "async-worker", branch: "feat/async-worker", commit: "9d03b5e4417ac2f0", by: "agent:bench", note: "4 workers, batch 8" },
  ];

  /* per-request latency model, ms. t = seconds since measurement start */
  const MODEL = {
    baseline: (r, t) => (r() < 0.006 ? 80 + 140 * r() : 0) + logn(r, 118, 0.40),
    cache: (r, t) => {
      const hit = r() < 0.66 - 0.28 * Math.exp(-t / 2.5);
      return hit ? { ms: logn(r, 14, 0.35), hit } : { ms: (r() < 0.006 ? 80 + 140 * r() : 0) + logn(r, 124, 0.40), hit };
    },
    async: (r, t) => (r() < 0.003 ? 60 + 90 * r() : 0) + logn(r, 104, 0.28),
  };
  const ERR503 = { baseline: 0, cache: 0, async: 0.0008 };
  const GPU_PER_RPS = { baseline: 0.372, cache: 0.372, async: 0.452 };
  const CPU_BASE = { baseline: 23, cache: 16, async: 31 };
  const CPU_PER_RPS = { baseline: 0.145, cache: 0.062, async: 0.178 };

  /* ---------------------------------------------------------------- runs */
  const SPEC = [
    ["baseline", 1, "20260927-091204-route-api-latency-7c1e", "2026-09-27T09:12:04Z", 1.004, null],
    ["baseline", 2, "20260927-091412-route-api-latency-b83a", "2026-09-27T09:14:12Z", 0.991, null],
    ["baseline", 3, "20260927-091620-route-api-latency-04d9", "2026-09-27T09:16:20Z", 1.009, null],
    ["cache", 1, "20260927-093045-route-api-latency-e5f2", "2026-09-27T09:30:45Z", 0.996, null],
    ["cache", 2, "20260927-093233-route-api-latency-19ac", "2026-09-27T09:32:33Z", 1.007, null],
    ["cache", 3, "20260927-093421-route-api-latency-d4c7", "2026-09-27T09:34:21Z", 1.002, { t0: 5.5, t1: 12.0, steal: 23, slow: 2.1 }],
    ["async", 1, "20260927-095010-route-api-latency-3a60", "2026-09-27T09:50:10Z", 0.998, null],
    ["async", 2, "20260927-095158-route-api-latency-8e2b", "2026-09-27T09:51:58Z", 1.006, null],
    ["async", 3, "20260927-095346-route-api-latency-f1d5", "2026-09-27T09:53:46Z", 0.993, null],
  ];

  function simulate(vid, seed, drift, nn) {
    const r = mulberry32(seed);
    const C = TASK.concurrency, N = TASK.requests + TASK.warmup;
    const free = new Float64Array(C);
    const t = new Float32Array(TASK.requests), lat = new Float32Array(TASK.requests), err = new Uint8Array(TASK.requests), hit = new Uint8Array(TASK.requests);
    let k = 0, tStart = 0;
    for (let i = 0; i < N; i++) {
      let w = 0; for (let j = 1; j < C; j++) if (free[j] < free[w]) w = j;
      const s = free[w];
      if (i === TASK.warmup) tStart = s;
      const tm = i >= TASK.warmup ? s - tStart : 0;
      let out = MODEL[vid](r, tm), ms, h = 0;
      if (typeof out === "object") { ms = out.ms; h = out.hit ? 1 : 0; } else ms = out;
      ms *= drift;
      if (nn && tm >= nn.t0 && tm <= nn.t1) { ms *= h ? 1 + (nn.slow - 1) * 0.55 : nn.slow * (0.85 + 0.3 * r()); if (r() < 0.015) ms += 600 + 300 * r(); }
      let e = 0;
      if (ms > TASK.timeout_ms) { ms = TASK.timeout_ms; e = 1; }
      else if (r() < ERR503[vid]) { ms = 2 + 3 * r(); e = 2; }
      free[w] = s + ms / 1000 + 0.0004;
      if (i >= TASK.warmup) { t[k] = (free[w] - tStart); lat[k] = ms; err[k] = e; hit[k] = h; k++; }
    }
    return { t, lat, err, hit };
  }

  function utilisation(vid, sm, seed, nn) {
    const r = mulberry32(seed ^ 0x5bd1e995);
    const dur = Math.max(...sm.t);
    const n = Math.ceil(dur);
    const done = new Array(n).fill(0), gpuReq = new Array(n).fill(0), hits = new Array(n).fill(0);
    for (let i = 0; i < sm.t.length; i++) {
      const b = Math.min(n - 1, Math.floor(sm.t[i]));
      done[b]++; if (!sm.hit[i]) gpuReq[b]++; else hits[b]++;
    }
    const cpu = [], gpu = [], mem = [], steal = [];
    let cached = 0;
    for (let s = 0; s < n; s++) {
      const frac = s === n - 1 ? Math.max(0.2, dur - s) : 1;
      const rps = done[s] / frac, grps = gpuReq[s] / frac;
      const inNN = nn && s + 0.5 >= nn.t0 && s + 0.5 <= nn.t1;
      steal.push(+(inNN ? nn.steal + 3 * normal(r) : 0.3 + 0.25 * r()).toFixed(1));
      cpu.push(+Math.min(99, CPU_BASE[vid] + CPU_PER_RPS[vid] * rps + 1.6 * normal(r) + (inNN ? 9 : 0)).toFixed(1));
      gpu.push(+Math.min(99, GPU_PER_RPS[vid] * grps + 1.8 * normal(r)).toFixed(1));
      if (vid === "cache") cached += gpuReq[s];
      const base = vid === "async" ? 7.0 : 6.1;
      mem.push(+(base + (vid === "cache" ? cached * 0.00082 : 0) + 0.04 * normal(r)).toFixed(2));
    }
    return { dt: 1, cpu, gpu, mem, steal };
  }

  const RUNS = SPEC.map(([vid, rep, id, at, drift, nn], i) => {
    const v = VERSIONS.find(x => x.id === vid);
    const seed = 9001 + i * 7919;
    const sm = simulate(vid, seed, drift, nn);
    const dur = Math.max(...sm.t);
    const util = utilisation(vid, sm, seed, nn);
    const attempts = vid === "cache" && rep === 3
      ? [{ n: 1, status: "failed", exit: 1, secs: 2.1, why: "server not ready: connect :8080 refused" }, { n: 2, status: "finished", exit: 0, secs: +(dur + 6.4).toFixed(1) }]
      : [{ n: 1, status: "finished", exit: 0, secs: +(dur + 6.4).toFixed(1) }];
    return {
      run_id: id, version: vid, repeat: rep, created_at: at, created_by: v.by,
      commit: v.commit, branch: v.branch, host: TASK.host, status: "finished",
      duration_s: +dur.toFixed(2), samples: sm, util, noisy: nn, attempts,
      flag: nn ? { kind: "noisy neighbour", t0: nn.t0, t1: nn.t1, steal: nn.steal } : null,
    };
  });

  /* ---------------------------------------------------------------- concurrency sweep (one per version, after r3) */
  const CONC = [1, 2, 4, 8, 16, 32, 64, 128];
  const XMAX = { baseline: 196, cache: 520, async: 312 };             /* saturation, req/s */
  const SWEEP = {};
  VERSIONS.forEach((v, vi) => {
    const r = mulberry32(777 + vi);
    const n = 3.2, X = (c, R0) => 1 / Math.pow(Math.pow(R0 / c, n) + Math.pow(1 / XMAX[v.id], n), 1 / n);
    /* calibrate unloaded latency so the curve passes through the clean repeats at c = 16 */
    const clean = RUNS.filter(u => u.version === v.id && !u.noisy);
    const x16 = clean.reduce((a, u) => a + u.samples.err.filter(e => !e).length / u.duration_s, 0) / clean.length;
    let lo = 0.001, hi = 1;
    for (let it = 0; it < 60; it++) { const m = (lo + hi) / 2; if (X(16, m) > x16) lo = m; else hi = m; }
    const R0 = (lo + hi) / 2;
    SWEEP[v.id] = CONC.map(c => {
      const x = c === 16 ? x16 : X(c, R0);
      return { c, rps: +(x * (c === 16 ? 1 : 1 + 0.012 * normal(r))).toFixed(1) };
    });
  });

  /* ---------------------------------------------------------------- where things are */
  const STORE = "/data/hx/store/route-search/runs";
  const REPO = "/home/shreyas/route-api";
  const paths = id => ({
    run_dir: `${STORE}/${id}`,
    samples: `${STORE}/${id}/samples.parquet`,
    util: `${STORE}/${id}/util.csv`,
    stdout: `${STORE}/${id}/logs/stdout.log`,
    stderr: `${STORE}/${id}/logs/stderr.log`,
    server: `${STORE}/${id}/logs/server.log`,
    env: `${STORE}/${id}/env.json`,
    diff: `${STORE}/${id}/git.diff`,
  });
  const COMMAND = ["python", "bench/load.py", "--url", "http://127.0.0.1:8080/v2/route", "-n", "5000", "-c", "16", "--warmup", "200", "--timeout", "1s", "--out", "{run_dir}/samples.parquet"];
  const SERVER = { baseline: "uvicorn app:app --workers 1", cache: "uvicorn app:app --workers 1 --route-cache 50000", async: "uvicorn app:app --workers 4 --batch 8" };

  root.HX = { task: TASK, versions: VERSIONS, runs: RUNS, sweep: SWEEP, conc: CONC, store: STORE, repo: REPO, paths, command: COMMAND, server: SERVER, selected: "20260927-093421-route-api-latency-d4c7" };
})(typeof window !== "undefined" ? window : globalThis);
