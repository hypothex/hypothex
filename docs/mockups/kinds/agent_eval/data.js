/* Hypothex mockup, task kind "agent_eval". SAMPLE DATA, invented.
   Every attempt record is generated from one seeded model, so all aggregates on the
   page (pass rates, CIs, costs, failure counts, the matrix) come from the same rows.

   Model: target t has difficulty b_t; config c has skill a_c; seed s adds e_cs.
   P(solved) = sigmoid(a_c + e_cs - b_t). Turns, tokens, cost and time follow from
   the outcome and the config's per-turn profile. */
(function () {
  function mulberry32(a) {
    return function () {
      a |= 0; a = (a + 0x6D2B79F5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  const R = mulberry32(20260927);
  const gauss = () => { let u = 0, v = 0; while (!u) u = R(); while (!v) v = R(); return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v); };
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const pick = w => { let r = R() * w.reduce((a, b) => a + b, 0); for (let i = 0; i < w.length; i++) { r -= w[i]; if (r <= 0) return i; } return w.length - 1; };

  const FAILS = ["timeout", "loop", "invalid SMILES", "tool error", "gave up"];
  const FAIL_TIP = {
    "timeout": "Hit the budget: 30 turns or 300 s",
    "loop": "Same tool call with the same args 3 times",
    "invalid SMILES": "Submitted route has a SMILES that does not parse or is not balanced",
    "tool error": "A tool call raised and the agent did not recover",
    "gave up": "Agent ended without a route",
  };

  /* price per 1M tokens, input is the cache-weighted effective price */
  const CONFIGS = [
    { id: "mini", name: "gpt-5-mini", short: "gpt-5-mini", model: "gpt-5-mini", tools: "base", a: -0.75, pin: 0.10, pout: 1.6, c0: 3100, g: 1150, out: 360, lat: 1.9, tc: 1.05, fw: [0.10, 0.14, 0.34, 0.12, 0.30], turnK: 1.0, commit: "4be19c2" },
    { id: "sonnet", name: "claude-sonnet-5", short: "Sonnet 5", model: "claude-sonnet-5", tools: "base", a: 0.25, pin: 1.2, pout: 15, c0: 3300, g: 1000, out: 420, lat: 3.4, tc: 1.25, fw: [0.26, 0.30, 0.10, 0.12, 0.22], turnK: 1.0, commit: "4be19c2" },
    { id: "scorer", name: "claude-sonnet-5 + route scorer", short: "Sonnet 5 + scorer", model: "claude-sonnet-5", tools: "base + score_routes", a: 1.30, pin: 1.2, pout: 15, c0: 3600, g: 820, out: 380, lat: 3.3, tc: 1.35, fw: [0.30, 0.14, 0.08, 0.24, 0.24], turnK: 0.8, commit: "91ad07e" },
    { id: "opus", name: "claude-opus-5-5", short: "Opus 5.5", model: "claude-opus-5-5", tools: "base", a: 1.30, pin: 2.0, pout: 25, c0: 3300, g: 1000, out: 880, lat: 6.6, tc: 1.3, fw: [0.52, 0.12, 0.04, 0.10, 0.22], turnK: 1.0, commit: "4be19c2" },
  ];
  const SEEDS = [1, 2, 3];
  const N = 200;

  /* targets */
  const CLASSES = ["kinase inhibitor", "macrolide", "peptidomimetic", "biaryl amide", "spiro-oxindole", "steroid", "nucleoside", "β-lactam", "sulfonamide", "indole alkaloid", "PROTAC linker", "fluoroquinolone"];
  const targets = [];
  for (let i = 0; i < N; i++) {
    const b = gauss() * 1.55;
    const depth = clamp(Math.round(4.2 + b * 1.25 + gauss() * 0.9), 2, 11);
    targets.push({ id: "T-" + String(i + 1).padStart(3, "0"), b, depth, cls: CLASSES[Math.floor(R() * CLASSES.length)] });
  }

  /* attempts[c][s][t] */
  const attempts = {};
  const seedFx = {};
  CONFIGS.forEach(c => {
    attempts[c.id] = {};
    SEEDS.forEach(s => {
      const e = gauss() * 0.04;
      seedFx[c.id + s] = e;
      attempts[c.id][s] = targets.map(t => {
        const p = 1 / (1 + Math.exp(-(c.a + e - t.b)));
        const solved = R() < p;
        let fail = null, turns;
        if (solved) turns = Math.round(clamp((3.5 + t.depth * 1.35) * c.turnK + gauss() * 2.2, 3, 28));
        else {
          const w = c.fw.slice();
          if (t.b > 1) w[0] *= 1.6; /* hard targets time out more */
          fail = FAILS[pick(w)];
          turns = fail === "timeout" ? 30
            : fail === "loop" ? Math.round(clamp(11 + gauss() * 3.5, 7, 26))
            : fail === "invalid SMILES" ? Math.round(clamp(7 + gauss() * 2.5, 3, 16))
            : fail === "tool error" ? Math.round(clamp(8 + gauss() * 3, 2, 20))
            : Math.round(clamp(9 + gauss() * 3, 4, 20));
        }
        const noise = Math.exp(gauss() * 0.12);
        const tok_in = Math.round((turns * c.c0 + c.g * turns * (turns + 1) / 2) * noise);
        const tok_out = Math.round(turns * c.out * Math.exp(gauss() * 0.18));
        const tool_calls = Math.max(1, Math.round(turns * c.tc + gauss()));
        const scoreCalls = c.id === "scorer" ? Math.round(turns / 3) : 0;
        let wall = turns * c.lat * Math.exp(gauss() * 0.15) + tool_calls * 0.55 + scoreCalls * 6.8;
        if (fail === "timeout") wall = Math.min(300, Math.max(wall, 150 + R() * 150));
        wall = Math.min(wall, 300);
        const cost = tok_in / 1e6 * c.pin + tok_out / 1e6 * c.pout;
        return { solved, fail, turns, tool_calls, tok_in, tok_out, cost: +cost.toFixed(4), wall: +wall.toFixed(1) };
      });
    });
  });

  /* the attempt shown on the detail screen: Sonnet 5 + scorer, seed 2, a target it
     looped on while Opus 5.5 solved it. Its record is set to the trajectory's sums. */
  const SEL = { cfg: "scorer", seed: 2 };
  let selIdx = targets.findIndex((t, i) => !attempts.scorer[2][i].solved && attempts.opus[1][i].solved && attempts.opus[2][i].solved && t.depth >= 5 && t.depth <= 7);
  if (selIdx < 0) selIdx = 136;
  SEL.t = selIdx;
  targets[selIdx].cls = "kinase inhibitor";
  targets[selIdx].smiles = "Cc1ccc(NC(=O)c2ccc(CN3CCN(C)CC3)cc2)cc1Nc1nccc(-c2cccnc2)n1";

  /* trajectory: turn, tool, args preview, result preview, tokens in / out, ms (model + tool) */
  const traj = [
    { tool: "retro_expand", args: "target, top_k=8", res: "8 precursors, amide p .62", ti: 4410, to: 512, ms: 4820 },
    { tool: "check_stock", args: "ClC(=O)c1ccc(CN2CCN(C)CC2)cc1", res: "in stock", ti: 5480, to: 188, ms: 2710 },
    { tool: "check_stock", args: "Cc1ccc(N)cc1Nc1nccc(-c2cccnc2)n1", res: "not in stock", ti: 6320, to: 204, ms: 2640 },
    { tool: "retro_expand", args: "Cc1ccc(N)cc1Nc1nccc(…)n1", res: "6 precursors, nitro red. p .71", ti: 7690, to: 466, ms: 4960 },
    { tool: "retro_expand", args: "Cc1ccc([N+](=O)[O-])cc1Nc1nccc(…)n1", res: "5 precursors, SNAr p .48", ti: 9310, to: 431, ms: 5130 },
    { tool: "score_routes", args: "3 routes, depth 3", res: "best .71, route B", ti: 10840, to: 352, ms: 8870 },
    { tool: "check_stock", args: "Cc1ccc([N+](=O)[O-])cc1N", res: "in stock", ti: 11720, to: 176, ms: 2580 },
    { tool: "check_stock", args: "CN(C)/C=C/C(=O)c1cccnc1", res: "not in stock", ti: 12460, to: 198, ms: 2690 },
    { tool: "retro_expand", args: "CN(C)/C=C/C(=O)c1cccnc1", res: "4 precursors, DMF-DMA p .80", ti: 13950, to: 402, ms: 4710 },
    { tool: "score_routes", args: "2 routes, depth 4", res: "tool error: timeout 8 s", ti: 15210, to: 318, ms: 11240, warn: true },
    { tool: "retro_expand", args: "Cc1ccc([N+](=O)[O-])cc1Nc1nccc(…)n1", res: "5 precursors, SNAr p .48", ti: 16930, to: 455, ms: 5080, same: 5 },
    { tool: "score_routes", args: "3 routes, depth 3", res: "best .71, route B", ti: 18380, to: 341, ms: 8790, same: 6 },
    { tool: "retro_expand", args: "Cc1ccc([N+](=O)[O-])cc1Nc1nccc(…)n1", res: "loop: 3rd identical call", ti: 19970, to: 473, ms: 4210, same: 5, fail: true },
  ];
  const sum = k => traj.reduce((a, s) => a + s[k], 0);
  const cS = CONFIGS[2];
  const rec = attempts.scorer[2][selIdx];
  Object.assign(rec, {
    solved: false, fail: "loop", turns: traj.length, tool_calls: traj.length,
    tok_in: sum("ti"), tok_out: sum("to"),
    cost: +((sum("ti") / 1e6) * cS.pin + (sum("to") / 1e6) * cS.pout).toFixed(4),
    wall: +(sum("ms") / 1000).toFixed(1),
  });

  const HOST = "evalbox-2";
  const RUN_ROOT = "/scratch/hx/store/retro-agents/runs";
  const runId = (c, s) => `20260926-${["1402", "1419", "1433"][s - 1]}${String(CONFIGS.findIndex(x => x.id === c) * 7 + 11).padStart(2, "0")}-retro-bench-200-${c}-s${s}`;

  window.HX = {
    sample: true,
    project: "retro-agents",
    task: { name: "retro-bench-200", kind: "agent_eval", kind_label: "Agentic system eval", n: N, metric: "solved@v2", metric_tip: "Valid route to purchasable building blocks, found within 30 turns and 300 s. Checker v2.", dataset: "retro-bench-200 v2", budget: { turns: 30, secs: 300 } },
    configs: CONFIGS, seeds: SEEDS, targets, attempts, seedFx,
    fails: FAILS, fail_tip: FAIL_TIP,
    sel: SEL, traj,
    host: HOST, runRoot: RUN_ROOT, runId,
    repo: "/home/mira/code/retro-agents",
    created_by: { mini: "agent:sweep-7", sonnet: "agent:sweep-7", scorer: "mira", opus: "agent:sweep-7" },
    started: "2026-09-26T14:02:11Z",
  };
})();
