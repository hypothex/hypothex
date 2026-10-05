/* Phase 3 mockup: team and output. All numbers are INVENTED sample data. */
(function () {
  const NOW = "2026-10-04T14:32:00Z";

  /* ------------------------------------------------------------------ who is looking */
  const me = { user: "sv", scope: "admin", session_id: "s_4b1e09c2d7a3", client: "browser", auth: "on", public_url: "https://hub.tail1234.ts.net" };
  const collaborator = { user: "alice", scope: "launch", session_id: "s_91d0aa3f62c8", client: "browser", auth: "on", public_url: me.public_url };

  /* ------------------------------------------------------------------ users and sessions */
  const users = [
    { name: "sv", role: "admin", created_at: "2026-09-12T08:01:00Z", created_by: "local", disabled_at: null },
    { name: "alice", role: "launch", created_at: "2026-09-30T10:22:00Z", created_by: "sv", disabled_at: null },
    { name: "bo", role: "read", created_at: "2026-10-02T16:40:00Z", created_by: "sv", disabled_at: null },
  ];
  const sessions = [
    { id: "s_4b1e09c2d7a3", user: "sv", scope: "admin", client: "browser", device: "MacBook", last_seen: "2m", created: "2026-09-12" },
    { id: "s_7f20c1b9e4d0", user: "sv", scope: "admin", client: "cli", device: "lab-laptop", last_seen: "1h", created: "2026-09-12" },
    { id: "s_91d0aa3f62c8", user: "alice", scope: "launch", client: "browser", device: "MacBook Air", last_seen: "12m", created: "2026-09-30" },
    { id: "s_c3e8f0172ab5", user: "alice", scope: "launch", client: "agent", device: "claude", last_seen: "3h", created: "2026-10-01" },
    { id: "s_0d5a7e91b2f4", user: "bo", scope: "read", client: "browser", device: "iPad", last_seen: "2d", created: "2026-10-02" },
  ];
  const pairing = {
    offer_id: "p_3f9a2c71e0b4",
    url: "https://hub.tail1234.ts.net/pair#p_3f9a2c71e0b4.kX2mQ9vR7tLw4pYc8zNf1aJ3sD6hG0eUiBqTnW5oVyM",
    expires_in: 299,
    /* 25 x 25 modules; 1 = dark. A stand-in pattern, not a scannable code. */
    qr: (function () {
      let s = 11; const rnd = () => ((s = (s * 16807) % 2147483647) / 2147483647);
      const n = 25, m = [];
      for (let y = 0; y < n; y++) { const row = []; for (let x = 0; x < n; x++) row.push(rnd() > 0.52 ? 1 : 0); m.push(row); }
      const finder = (ox, oy) => { for (let y = 0; y < 7; y++) for (let x = 0; x < 7; x++) {
        const edge = x === 0 || y === 0 || x === 6 || y === 6, core = x >= 2 && x <= 4 && y >= 2 && y <= 4;
        m[oy + y][ox + x] = edge || core ? 1 : 0; } };
      finder(0, 0); finder(n - 7, 0); finder(0, n - 7);
      return m;
    })(),
  };

  /* ------------------------------------------------------------------ notifications */
  const notify = {
    channels: {
      slack: { configured: true, env: "HYPOTHEX_SLACK_WEBHOOK", set: true },
      email: { configured: true, env: "HYPOTHEX_SMTP_PASSWORD", set: false, host: "smtp.lab.org", to: ["sv@lab.org"] },
    },
    projects: {
      deepretro: { events: ["finished", "failed", "lost"], channels: ["slack", "email"], min_seconds: 300, fold_sweeps: true },
      "rxn-forward": { events: ["failed", "lost", "killed"], channels: ["slack"], min_seconds: 0, fold_sweeps: true },
    },
    default: null,
    digest: { enabled: true, weekday: "sun", hour: 9, timezone: "Europe/London", channels: ["slack"], projects: "all" },
    recent: [
      { at: "14:02", kind: "run", target: "01J8Z3K7-clf-a1b2", channel: "slack", status: "sent", attempts: 1, error: null },
      { at: "13:40", kind: "sweep", target: "s-7f3a", channel: "slack", status: "sent", attempts: 1, error: null },
      { at: "13:12", kind: "run", target: "01J8Z2QF-clf-c2b9", channel: "email", status: "skipped", attempts: 0, error: "unset:HYPOTHEX_SMTP_PASSWORD" },
      { at: "12:55", kind: "run", target: "01J8YX0M-tr-77fe", channel: "slack", status: "failed", attempts: 3, error: "http_404" },
      { at: "12:31", kind: "run", target: "01J8YT4C-tr-9d0c", channel: "slack", status: "pending", attempts: 2, error: "http_429" },
      { at: "09:00", kind: "digest", target: "2026-W40", channel: "slack", status: "sent", attempts: 1, error: null },
    ],
  };

  /* ------------------------------------------------------------------ storage (bytes) */
  const GB = 1e9, TB = 1e12;
  const storage = {
    total: 1.84 * TB,
    cleanable: 412 * GB,
    by_project: [
      { project: "deepretro", local: 210 * GB, remote: 910 * GB },
      { project: "rxn-forward", local: 88 * GB, remote: 446 * GB },
      { project: "toy-classifier", local: 186 * GB, remote: 0 },
    ],
    by_host: [
      { host: "gpu1", bytes: 812 * GB, kind: "ssh" },
      { host: "local", bytes: 484 * GB, kind: "hub" },
      { host: "mccleary", bytes: 371 * GB, kind: "slurm" },
      { host: "dgx", bytes: 173 * GB, kind: "ssh" },
    ],
    by_kind: { checkpoint: 1.52 * TB, run: 214 * GB, pulled: 106 * GB },
    largest: [
      { run: "01J7QK2D-tr-5e9a", host: "mccleary", kind: "checkpoint", path: "/gpfs/sv/hx/runs/01J7QK2D-tr-5e9a/artifacts/ckpt", bytes: 96.4 * GB, age: "41d", starred: false, archived: true },
      { run: "01J8B0MZ-tr-a3c1", host: "gpu1", kind: "checkpoint", path: "/scratch/sv/hx/runs/01J8B0MZ-tr-a3c1/artifacts/ckpt", bytes: 88.1 * GB, age: "9d", starred: true, archived: false },
      { run: "01J7MZ81-tr-0a6d", host: "gpu1", kind: "checkpoint", path: "/scratch/sv/hx/runs/01J7MZ81-tr-0a6d/artifacts/ckpt", bytes: 74.0 * GB, age: "52d", starred: false, archived: true },
      { run: "01J7T3VE-tr-d1f4", host: "dgx", kind: "checkpoint", path: "/raid/sv/hx/runs/01J7T3VE-tr-d1f4/artifacts/ckpt", bytes: 61.7 * GB, age: "38d", starred: false, archived: true },
      { run: "01J8D7HC-tr-52c9", host: "local", kind: "pulled", path: "~/.hypothex/store/deepretro/runs/01J8D7HC-tr-52c9/pulled/ckpt", bytes: 44.2 * GB, age: "6d", starred: false, archived: false },
      { run: "01J7KD0P-tr-8b5f", host: "mccleary", kind: "checkpoint", path: "/gpfs/sv/hx/runs/01J7KD0P-tr-8b5f/artifacts/ckpt", bytes: 39.9 * GB, age: "47d", starred: false, archived: true },
      { run: "01J8F2AA-tr-7e3f", host: "gpu1", kind: "checkpoint", path: "/scratch/sv/hx/runs/01J8F2AA-tr-7e3f/artifacts/ckpt", bytes: 33.5 * GB, age: "3d", starred: true, archived: false },
      { run: "01J7R1C9-tr-4d2e", host: "local", kind: "run", path: "~/.hypothex/store/rxn-forward/runs/01J7R1C9-tr-4d2e", bytes: 21.8 * GB, age: "44d", starred: false, archived: true },
    ],
    plan: {
      plan_id: "cp-8e41c0d2",
      total: 412.3 * GB,
      paths: 37, // 6 items listed + more.n (31): a CleanItem is a path, never a file count
      hosts: ["gpu1", "mccleary", "local"],
      expires: "15:32",
      items: [
        { run: "01J7QK2D-tr-5e9a", host: "mccleary", path: "/gpfs/sv/hx/runs/01J7QK2D-tr-5e9a/artifacts/ckpt", bytes: 96.4 * GB, reason: "archived 41d, checkpoint" },
        { run: "01J7MZ81-tr-0a6d", host: "gpu1", path: "/scratch/sv/hx/runs/01J7MZ81-tr-0a6d/artifacts/ckpt", bytes: 74.0 * GB, reason: "archived 52d, checkpoint" },
        { run: "01J7KD0P-tr-8b5f", host: "mccleary", path: "/gpfs/sv/hx/runs/01J7KD0P-tr-8b5f/artifacts/ckpt", bytes: 39.9 * GB, reason: "archived 47d, checkpoint" },
        { run: "01J7N4T2-tr-b46a", host: "gpu1", path: "/scratch/sv/hx/runs/01J7N4T2-tr-b46a/artifacts/ckpt", bytes: 31.2 * GB, reason: "archived 50d, checkpoint" },
        { run: "01J7P8E0-tr-71f2", host: "gpu1", path: "/scratch/sv/hx/runs/01J7P8E0-tr-71f2/artifacts/ckpt", bytes: 28.8 * GB, reason: "archived 49d, checkpoint" },
        { run: "01J7R1C9-tr-4d2e", host: "local", path: "~/.hypothex/store/rxn-forward/runs/01J7R1C9-tr-4d2e/pulled/ckpt", bytes: 17.6 * GB, reason: "archived 44d, pulled" },
      ],
      more: { n: 31, bytes: 124.4 * GB },
      refused: [
        { run: "01J7T3VE-tr-d1f4", host: "dgx", path: "/raid/sv/hx/runs/01J7T3VE-tr-d1f4/artifacts/ckpt", bytes: 61.7 * GB, reason: "used by 01J8E5WQ-tr-c7d4" },
        { run: "01J6ZZ10-tr-e2d5", host: "local", path: "~/code/deepretro", bytes: 2.1 * GB, reason: "protected" },
      ],
    },
    result: { freed: 409.8 * GB, skipped: 2, deleted: 35 },
  };

  /* ------------------------------------------------------------------ notebook */
  const notebook = {
    project: "deepretro",
    days: [
      { day: "2026-10-04", entries: 3 },
      { day: "2026-10-03", entries: 5 },
      { day: "2026-10-02", entries: 2 },
      { day: "2026-09-30", entries: 1 },
      { day: "2026-09-29", entries: 4 },
      { day: "2026-09-27", entries: 2 },
    ],
    chips: {
      "01J8Z3K7-clf-a1b2": { status: "finished", primary: 0.913, task: "uspto50k-topk" },
      "01J8Z6RR-tr-0f3c": { status: "running", primary: null, task: "uspto50k-topk" },
      "01J8YX0M-tr-77fe": { status: "failed", primary: null, task: "uspto50k-top1" },
      "01J7AAAA-old-0001": { status: null, primary: null, task: null },
    },
    digest: {
      week: "2026-W40",
      counts: { started: 12, finished: 9, failed: 2, lost: 1 },
      gpu_h: 41.2, usd: 86.5, gpu_pricing_complete: true,
      incomplete_cost: { usd: 0.25, gpu_pricing_complete: false },
      tasks: [
        { task: "uspto50k-topk", before: 0.598, after: 0.613, mark: "▲", best: "lr 3e-4, beam 10" },
        { task: "uspto50k-top1", before: 0.512, after: 0.512, mark: "·", best: "base" },
      ],
      by: { "agent:claude@alice": 7, "human:sv": 3, "human:alice": 2 },
    },
    entries: [
      { at: "09:14", author: "alice", text: "Beam 10 holds at lr 3e-4: [[run:01J8Z3K7-clf-a1b2]] is inside the best band on all 3 seeds.\nNext: rerun with the template-free decoder, [[run:01J8Z6RR-tr-0f3c]] is going." },
      { at: "11:02", author: "sv", text: "The top-1 regression came from the tokenizer change, not the data: [[run:01J8YX0M-tr-77fe]] fails at load. Older ckpt [[run:01J7AAAA-old-0001]] is gone from the store." },
    ],
    conflict: {
      by: "sv", age: "1m",
      theirs: [
        "## 2026-10-04T11:02:41Z — human:sv",
        "The top-1 regression came from the tokenizer change, not the data.",
        "Fixed in 8f4cac4; [[run:01J8YX0M-tr-77fe]] reruns tonight.",
      ],
      mine: [
        "## 2026-10-04T11:02:41Z — human:sv",
        "The top-1 regression came from the tokenizer change, not the data.",
        "alice: confirmed on seed 2 as well.",
      ],
    },
  };

  /* ------------------------------------------------------------------ task, leaderboard, baselines */
  const task = {
    project: "deepretro", task: "uspto50k-topk", primary: "top-10", version: "v2",
    headline: "lr 3e-4, beam 10: 0.613 top‑10, +0.015 over RetroBridge",
    rows: [
      { label: "lr 3e-4, beam 10", who: "agent:claude@alice", group: "g-7e3f", mean: 0.6131, std: 0.0042, n: 3, lo: 0.6063, hi: 0.6198, top1: 0.5207, best: true, seeds: [0.6094, 0.6126, 0.6173] },
      { label: "lr 3e-4, beam 5", who: "agent:claude@alice", group: "g-5b11", mean: 0.6102, std: 0.0031, n: 3, lo: 0.6034, hi: 0.6169, top1: 0.5188, within: true, seeds: [0.6071, 0.6104, 0.6131] },
      { label: "+aug", who: "human:sv", group: "g-a3c1", mean: 0.6047, std: 0.0055, n: 3, lo: 0.5979, hi: 0.6115, top1: 0.5122, seeds: [0.5990, 0.6051, 0.6100] },
      { label: "base", who: "human:sv", group: "g-0a6d", mean: 0.5974, std: null, n: 1, lo: 0.5906, hi: 0.6042, top1: 0.5120, seeds: [0.5974] },
    ],
    baselines: [
      { name: "RetroBridge", value: 0.598, top1: 0.503, source: "arXiv:2403.12345", url: "https://arxiv.org/abs/2403.12345", match: true },
      { name: "Chemformer", value: 0.571, top1: 0.541, source: "doi:10.1088/2632-2153/ac3ffb", url: "https://doi.org/10.1088/2632-2153/ac3ffb", match: false },
    ],
    latex: [
      "% requires \\usepackage{booktabs}",
      "\\begin{tabular}{lrll}",
      "\\toprule",
      "Method & $n$ & top-10 $\\uparrow$ & top-1 $\\uparrow$ \\\\",
      "\\midrule",
      "\\textbf{lr 3e-4, beam 10} & 3 & \\textbf{0.613 $\\pm$ 0.004} [0.606, 0.620] & \\textbf{0.521 $\\pm$ 0.003} \\\\",
    ],
  };

  /* ------------------------------------------------------------------ run */
  const run = {
    run_id: "01J7P2KD-tr-3a90", project: "deepretro", task: "uspto50k-topk",
    title: "lr 1e-3, beam 5 at 40k steps",
    status: "finished", took: "2h 41m", seed: 2, at: "06:12:09 UTC", created_by: "human:alice", owner: "alice", host: "gpu1", archived: true,
    run_dir: "/scratch/sv/hx/runs/01J7P2KD-tr-3a90",
    artifacts: [
      { path: "artifacts/ckpt/step-40000.pt", kind: "checkpoint", note: "step 40000", bytes: "4.2 GB", cleaned: { at: "2026-10-04", bytes: "4.2 GB", by: "sv", plan: "cp-8e41c0d2" } },
      { path: "artifacts/ckpt/best.pt", kind: "checkpoint", note: "step 36000", bytes: "4.2 GB", cleaned: null },
      { path: "artifacts/predictions.jsonl", kind: "predictions", note: "5,007 rows", bytes: "18.5 MB", cleaned: null },
    ],
    scores: [{ k: "top-10", v: "0.5931", note: "v2" }, { k: "top-1", v: "0.5034", note: "v2" }],
  };

  window.HX = { now: NOW, hub: "hub.tail1234.ts.net", me, collaborator, users, sessions, pairing, notify, storage, notebook, task, run };
})();
