/* Hypothex mockup: user-defined views. ALL NUMBERS ARE INVENTED sample data.
   Task retro-bench-200: a retrosynthesis agent is asked to find a route for each of
   200 target molecules. solved@v2 = share of targets with a verified route to
   purchasable stock. Each config ran 3 seeds. */
window.HXV = {
  project: "deepretro",
  task: "retro-bench-200",
  dataset: { name: "retro-bench", version: "v1", n: 200 },
  primary: "solved@v2",

  /* per config: seed scores, route length and solve time per seed (medians over the
     run's solved targets), tokens per target, and solved counts per depth bin
     (mean over seeds). Bin counts sum to 200 x the mean of the seeds. */
  configs: [
    { id: "mcts-128+critic", who: "agent:retro-planner", seeds: [0.735, 0.720, 0.745], len: [4.5, 4.7, 4.6], time: [155, 170, 161], tokens: 41.2, bins: [56.3, 56.7, 25.7, 8.0], lbl: { dx: -10, dy: 17, a: "end" } },
    { id: "mcts-128", who: "human", seeds: [0.700, 0.715, 0.690], len: [4.8, 5.0, 4.9], time: [178, 191, 183], tokens: 36.9, bins: [56.0, 54.3, 23.0, 7.0], lbl: { dx: 0, dy: -20, a: "middle" } },
    { id: "mcts-64", who: "human", seeds: [0.655, 0.670, 0.660], len: [5.1, 5.3, 5.2], time: [92, 99, 97], tokens: 19.8, bins: [55.3, 50.7, 20.0, 6.3], lbl: { dx: 8, dy: -11, a: "start" } },
    { id: "beam-8", who: "human", seeds: [0.610, 0.610, 0.610], len: [5.6, 5.6, 5.6], time: [70.1, 72.4, 70.5], tokens: 14.1, bins: [55.0, 46.0, 17.0, 4.0], lbl: { dx: 10, dy: -8, a: "start" } },
    { id: "beam-4", who: "human", seeds: [0.565, 0.565, 0.565], len: [6.1, 6.1, 6.1], time: [37.2, 38.5, 38.3], tokens: 7.6, bins: [54.0, 41.0, 14.0, 4.0], lbl: { dx: 10, dy: -8, a: "start" } },
    { id: "greedy", who: "human", seeds: [0.480, 0.480, 0.480], len: [7.8, 7.8, 7.8], time: [13.6, 14.1, 14.3], tokens: 2.3, bins: [50.0, 31.0, 12.0, 3.0], lbl: { dx: 4, dy: -11, a: "start" } },
  ],
  bins: [{ k: "1–2", n: 58 }, { k: "3–4", n: 71 }, { k: "5–6", n: 46 }, { k: "7–8", n: 25 }],

  /* paired sign test, best vs runner-up, seed 1 vs seed 1, per target */
  pair: { fixed: 11, broken: 5 },

  views: [
    { id: "overview", title: "overview", preset: "agent_eval", panels: 6 },
    { id: "route_quality", title: "route quality", by: "agent:retro-planner", panels: 5 },
  ],
};

/* The task block of hypothex.yaml, as the editor shows it. Lines 1-37 (project,
   datasets, metrics) are folded. {fold: text, n} is a folded region of n lines.
   The bad-metric variant is made by swapping the scatter y metric. */
window.HXV.yaml = [
  { fold: "project, datasets, metrics", n: 37 },
  "tasks:",
  "  retro-bench-200:",
  "    kind: agent_eval",
  "    dataset: retro-bench",
  "    metrics: [solved, route_len, solve_time, tokens]",
  "    primary: solved/value",
  "    views:",
  "      overview:                  # hx view init --from agent_eval",
  { fold: "from: agent_eval, 6 panels", n: 38 },
  "      route_quality:             # added by agent:retro-planner",
  "        title: route quality",
  "        runs: {status: finished}",
  "        panels:",
  "          - type: stat_strip",
  "            title: Best config",
  "            data:",
  "              metrics:",
  "                - solved@v2",
  "                - route_len@v1/median",
  "                - solve_time@v1/median",
  "                - tokens@v1/mean",
  "              pick: best           # by task primary",
  "            layout: {span: 12, row: 1}",
  "",
  "          - type: leaderboard",
  "            title: Solved",
  "            data: {y: solved@v2, group_by: config}",
  "            noise: [seed, test_set]",
  "            layout: {span: 7, row: 2}",
  "",
  "          - type: scatter",
  "            title: Length vs time",
  "            data:",
  "              x: solve_time@v1/median",
  "              y: route_len@v1/median",
  "              group_by: config",
  "            pareto: {x: min, y: min}",
  "            layout: {span: 5, row: 2}",
  "",
  "          - type: vega_lite",
  "            title: Solved by depth",
  "            data:",
  "              source: predictions  # per-target rows",
  "              fields: [config, ref_steps, solved]",
  "            spec:",
  "              encoding:",
  "                x:",
  "                  field: ref_steps",
  "                  bin: {extent: [1, 9], step: 2}",
  "                  title: ref steps",
  "                y:",
  "                  field: config",
  "                  sort: {op: mean, field: solved, order: descending}",
  "              layer:",
  "                - mark: rect",
  "                  encoding:",
  "                    color: {aggregate: mean, field: solved}",
  "                - mark: text",
  "                  encoding:",
  "                    text: {aggregate: mean, field: solved, format: .2f}",
  "            layout: {span: 8, row: 3}",
  "",
  "          - type: markdown",
  "            title: Note",
  "            text: |",
  "              Critic gain is largest on 5+ step targets: **+0.05**.",
  "              Next: mcts-256+critic, 3 seeds.",
  "            layout: {span: 4, row: 3}",
];

/* known metrics for validation and hover */
window.HXV.metrics = {
  solved: { v: "v2", keys: ["value"], d: "route to purchasable stock, verified" },
  route_len: { v: "v1", keys: ["median", "mean"], d: "reactions in the found route" },
  solve_time: { v: "v1", keys: ["median", "p90"], d: "wall seconds per target" },
  tokens: { v: "v1", keys: ["mean"], d: "LLM tokens per target, thousands" },
};
