# Hypothex UI v5 — Design Spec

- **Date:** 2026-10-16
- **Status:** Draft, awaiting review
- **Replaces:** spec §8.1 (principles), §8.3 (screens) and the `ui-v4` visual reference.
  Everything else in §8 (task kinds, statistics, views YAML, panel data API) stays.
- **Mockup:** `docs/mockups/ui-v5/index.html` (serve the folder, open `#workspace`,
  `#table`, `#sweep`, `#run`, `#home`). Screenshots: `docs/mockups/ui-v5/shot-*.png`.

## 1. Why

The v4 UI reads as a printed journal page: a serif headline, lettered figures a–f, a
narrow centred column, and one small axis per row. On real use (agent-driven research
projects) it fails:

- Rows in "Ideas" each have their own axis, so values cannot be compared.
- Run names are hash labels (`Back-fill · 154aa747@0ede770`, `Re-score the test set · 3aaf1bc5@nogit`).
- Timeline labels overlap; the generated headline ("Idle. Back-fill leads …") says nothing useful.
- Eval tasks with 50+ score keys (`reported/<dataset>.<model>.<metric>`) have no way to see them.
- Wide screens waste two thirds of the width.

Goal: a W&B-style workspace that a researcher can read at a glance, where agents' runs
are easy to name, filter, compare and act on.

## 2. Principles (replace §8.1)

1. **One colour per run identity, everywhere.** A config group (or a run when grouping is
   off) gets one colour in the run list, every chart, the table and the run page header.
   Colours come from the validated 8-slot categorical palette (§7) in a fixed order,
   assigned to visible identities in list order; a 9th visible identity is neutral grey.
   Chrome is grey; colour is only identity, status (with an icon) and "best" (green).
2. **The run list drives every panel.** Search, filter, group, sort and the eye toggle
   live in one place (left sidebar); every chart on the page follows it. The cap is
   visible: `7/13 shown`.
3. **One axis per comparison.** All runs of a task share one axis in a panel.
4. **Names say what differs.** A run is named by the params that differ inside its task
   (§5), never by a hash. People and agents can rename runs.
5. **Panels, not prose.** Equal-size panels in collapsible sections; panel tools appear on
   hover. No generated headline sentences, no lettered figures, no explanatory text on
   the page (tooltips explain).
6. **Noise stays visible.** Seed dots and 95% test-set intervals (§8.5) are drawn on score
   panels; the best interval is a green band. Single-seed runs with no per-example
   scores show no interval and say so in the tooltip.
7. **Full width, dense, calm.** Geist 13 px UI, Geist Mono for ids, paths,
   commands and YAML. Tabular figures in tables and axes. Dark and light are equal.

## 3. Shell

```
┌ nav 216px ────┬ top bar 48px: breadcrumb · search ⌘K · live · + New run ─────────┐
│ Home          │ page header: title, 1 line of facts, tabs                          │
│ Hosts      3  ├────────────────────────────────────────────────────────────────────│
│ Queue      3  │ page body (full width, scrolls)                                    │
│ Projects      │                                                                    │
│  project      │                                                                    │
│   task  ⟳ 39  │                                                                    │
│ ◐ theme       │                                                                    │
└───────────────┴────────────────────────────────────────────────────────────────────┘
```

- Left nav: Home, Hosts, Queue (counts), then a project → task tree with run counts and
  a spinner on tasks with running runs. Collapsible (⌘.).
- Top bar: breadcrumb (project / task / run), `⌘K` palette (existing), live indicator,
  `+ New run` (opens the existing Launch dialog).

## 4. Screens

### 4.1 Home (`/`)

Status strip (projects with live runs, running, queued, failed today, lost, GPUs busy,
spent today); **Running now** table (run swatch + name, task, progress bar, latest
primary-metric value, host, launcher, ETA); **Hosts** (one row per host: GPU cells filled
by utilisation, cost today); **Tasks** table (task, project, kind, primary metric with
direction, best, 7-day Δ, best-over-time sparkline, runs, now); **Recent runs** table
(time, run, task, status with reason, score, Δ best, launcher, hypothesis). Rows link to
the task or run. Home tables show no identity swatch (colour identity is task-scoped);
the status icon carries state. Replaces the Overview page (headline, timeline, ideas,
lettered figures).

**Empty Home** (no runs yet): one calm block, "No runs yet", with the three first
commands (`hx init`, `hx run -- <cmd>`, `hx demo --with-hosts`) and links to the docs,
the agent skill and "Add a host".

### 4.2 Task (`/t/$project/$task`), tabs: Charts · Runs · Sweeps · Examples · views · + View

Header: task name, kind tag, one facts line (primary metric + direction, best value and
run, run/config counts, running/queued, dataset).

**Charts (default tab).** Two columns: runs sidebar (340 px) and panel area.

- *Runs sidebar:* search/filter field (`lr = 3e-4`, `tag:final`, `status:running`,
  `model:resnet*`); Group is a segmented control (`By config | Each run`); Sort and
Columns are chips with a chevron; a
  "superseded hidden" chip when any run has the `superseded` tag (on by default);
  `N/M shown`. Rows: colour swatch, name (double-click to rename), sub-line (launcher
  icon + name, seed count or date, live/queued/failed counts with icons, `final` tag in
  green), primary value (± sd for groups), eye toggle. Rename: a pencil on row hover/focus
(double-click also works). The eye, chips and segments are buttons with
`aria-pressed`; rows are focusable and open the run on Enter. Hover a row → its lines are
  highlighted in every chart. Hidden rows show an empty swatch and muted text.
- *Panel toolbar* (wraps under ~1300 px): panel search; for step metrics: smoothing
  (EMA with its value shown, raw shown faint),
  x axis (step | wall time | relative time), seeds (mean | mean + band | each seed);
  `+ Panel`, `Save as view`.
- *Sections* (collapsible, `+ Add panel` on hover):
  - **Scores** (grid `auto-fit`, fills the row; other panel grids min 330 px): primary metric as dot + 95% CI + seed dots per visible identity on one
    axis with the best band; for training kinds also score vs GPU-hours with the Pareto front.
  - **Step metrics**: one line panel per logged metric, sectioned by the first `/`
    prefix (`train/`, `val/`, `sys/`), synced crosshair, one tooltip listing every run at
    that step (sorted by value, max 8).
  - **Score keys** (eval tasks): keys are split as `<prefix>/<A>.<B>.<metric>`; one
    section per `<metric>` (the primary's section first and open, others closed), one
    horizontal bar panel per `<A>.<B>` (bars from zero, run colours, value at bar end,
    best value green, CI whiskers on the primary). Keys without dots form one section
    with a panel per key. Large key sets stay usable: sections are closed by default and
    panel search filters by title.
  - **Compare** (eval tasks whose keys have two or more parts, shown first): one panel
    that puts chosen datasets side by side. Controls inside the panel: **Datasets**
    (multi-select chips; default = the first four), **Model** (single select; default = the primary's model) and **Metrics**
    (multi-select; default = the primary's metric). It renders as a **table** by default:
    one row per selected dataset, one column per visible run (header = swatch + run
    name); with several metrics, rows are grouped under a metric header row. Best value
    per row in green, tabular figures, columns sized to content (horizontal scroll when
    wide). A
    `Table | Bars` switch in the panel header shows the same selection as grouped
    horizontal bars instead (one group per dataset, one bar per run in its identity
    colour, one facet per metric, zero-based axes, legend). More than one Compare panel can be
    added (`+ Panel` → Compare), and "Save as view" stores them as a new view panel type
    `compare` (`data: {datasets: [..], model: str, metrics: [..]}`, `render: table | bars`), validated like other
    panels. Key parts: `<prefix>/<dataset>.<model>.<metric>`; a key with one dot is
    `<dataset>.<metric>` (no model control). A task may name the parts in
    `hypothex.yaml` (`score_keys: "{dataset}.{model}.{metric}"`); the UI labels the
    controls with those names, else "Datasets / Model / Metrics".
  - The task kind's preset panels (training curves, agent_eval scatter/grid/trace,
    system_bench distributions, agent_iteration versions) and custom views render in the
    same panel chrome (§6), not as lettered figures.

**Runs.** The full table. Columns: select, swatch, name, status (counts per state for
groups), each varying param, primary mean ± sd, 95% CI, Δ best (muted when inside the
best interval), launcher, host, GPU-h, started, commit, tags. Group by config (rows
expand to seeds), sortable columns, column chooser, and bulk actions on selection:
Compare, Tag, Archive, Rename.

**Sweeps.** Per sweep: header (id, grid shape, launcher, progress bar, Add seeds, Cancel
queued); parallel coordinates (one line per finished run, sequential colour by the
primary metric); mean-per-cell table (2 params) shaded by value; "What matters" (share
of variance per param); best cell with the paired comparison to the next cell.

**Examples** and **view editor**: existing behaviour, restyled with the new chrome.

### 4.3 Run (`/r/$runId`), tabs: Overview · Charts · Logs · Files · Examples

White canvas, two columns: main content and a 300 px properties sidebar (no boxed
cards for facts).

Header: colour swatch, run name (click to rename; "Reset name" restores the derived
name; a renamed run shows the derived name in one muted line), status pill (icon + word,
tinted), then Compare, Rerun and a `⋯` menu (Re-infer, Re-evaluate, Stop, Archive). One
line with the hypothesis. Tabs.

Overview, main column:
- **Scores**: one strip of tiles (one per metric@version of the task; the primary
  first and marked "primary", old versions marked "old version"); each tile shows the
  value and its Δ vs the config mean (green up / red down in the metric's direction,
  muted when |Δ| is under one sd of the config's seeds; the tooltip says why).
- **Where it ranks**: one axis for the primary metric with this run (large dot), its
  sibling seeds (faint dots), the other configs (ticks) and the best config's 95%
  interval (green band), plus a one-line legend and a one-line summary
  (`2nd of 3 seeds · config is best of 12`).
- **Curves**: up to three step-metric panels (this run in colour, sibling seeds grey),
  "All charts" opens the Charts tab.
- **Files**: list rows with icon, name, path relative to the run folder, size, and a
  Copy button on hover (run folder, logs, predictions, checkpoints).

Sidebar: Status (with exit code or reason), Launcher, Host + GPUs, Started, Duration,
Commit, Sweep (link), Cost; **Config** (params; values that vary in the task tinted
with the run's identity colour); **Tags** (chips + Add); **Notes** (inline editor); run id and folder name
in small mono. State banners for queued/stale/lost stay (existing logic) above the
tabs. Charts tab: all step metrics. Logs tab: the existing log viewer. Files tab:
artifacts list.

### 4.4 Hosts (`/hosts`) and Queue (`/queue`)

The existing Hosts panel and queue data as full pages in the new chrome (GPU grid per
host, state, version, cost, queue positions with stop).

## 5. Run names

### 5.1 Derived name (no rename)

Computed server-side per task (so the UI, CLI and MCP agree) by
`hypothex.core.naming.derive_names(runs) -> dict[run_id, str]`:

1. Collect run `params` (and `vars`) across the task's runs.
2. Varying keys: keys whose value differs between runs, excluding values that are long
   (> 24 chars), hex hashes (≥ 16 hex chars), URLs, or paths.
3. Name = `key value` pairs of varying keys joined with ` · ` in first-seen key order
   (`db v3`, `lr 3e-4 · beam 10`); for single-key tasks where the value is
   self-describing the key is still shown (consistent, scannable).
4. A run's seed is appended in run views (`· seed 2`), not in group names.
5. Fallback when nothing varies: the existing `group_label` (first clause of the
   hypothesis), then the first tag, then the short run id.

### 5.2 Rename

- New mutable run field `name: str | None` (1–80 chars, trimmed, no newlines). Runs stay
  immutable except tags, star, archive, notes, added scores **and name** (spec §2 rule
  updated).
- Display name = `name` if set, else the derived name. A config group's display name =
  the `name` of its most recently renamed run, else the derived group name.
- API: `POST /api/v1/runs/{id}/name {"name": str | null}` (null resets), forwarded to the
  owning host like tags; emits a `run.renamed` event so open UIs update live. Bulk rename
  of a group renames each run in it.
- CLI: `hx rename <run_id> "<name>"`, `hx rename <run_id> --reset` (flat command like `hx tag`).
- MCP: `rename_run(run_id, name)`; the agent skill tells agents to name runs by what they
  change and to rename when a name is wrong.
- Index: `name` is stored in the index and searchable from `⌘K` and the sidebar filter.

## 6. Components

| Component | Responsibility |
|---|---|
| `AppShell` | nav tree, top bar, routes |
| `RunsSidebar` | filter/group/sort/visibility state for one task; the source of truth for the panels |
| `useRunSelection` | that state, in the URL (`?filter=&group=&sort=&hide=`) so views are shareable |
| `colorFor(identity, visibleOrder)` | the palette rule of principle 1 |
| `PanelSection`, `Panel` | collapsible section; panel chrome with title, hover tools (full screen, edit, more) |
| `Fit` | measures its width and renders a chart at real pixel size (no SVG scaling) |
| Charts | all axes use nice ticks (1/2/2.5/5 × 10ⁿ); `LineChart` (synced crosshair with a marker per series at the hovered step), `ParallelCoords` (a `Fit` chart, haloed axis labels, per-line tooltip), `DotCIChart`, `BarPanel`, `ScatterPareto`, `ParallelCoords`, `ScoreStrip`, `Sparkline` |
| `RunName` | display + inline rename, used in header, sidebar, tables |
| `ComparePanel` | dataset/model/metric pickers + table (default) or grouped bars; saved as view panel type `compare` |
| Pages | `Home`, `Task` (`Charts`, `Runs`, `Sweeps`, `Examples`), `Run`, `Sweep`, `Hosts`, `Queue`, `ViewEditor` |

The existing panel types (`stat_strip`, `leaderboard`, `curves`, `scatter`,
`distribution`, `grid`, `table`, `trace`, `markdown`, `vega_lite`), the views YAML, the
`views/query` API, the WebSocket event stream, the Launch dialog and the command palette
keep their contracts; only their rendering and chrome change.

## 7. Tokens

Neutral zinc greys, white panels, one radius per level.
Light: page `#f7f7f8`, panel `#ffffff`, panel-2 `#fafafa`, hover `#f1f1f3`, line
`#e7e7ea`, ink `#18181b` / `#52525b` / `#8b8b94`, focus `#2a78d6`. Dark: page `#111113`,
panel `#18181b`, line `#27272a`, ink `#ededef` / `#a1a1aa` / `#71717a`. Identity palette
(validated, adjacent CVD ΔE ≥ 8 in both modes): light `#2a78d6 #eb6834 #1baf7a #eda100
#e87ba4 #008300 #6250d6 #e34948`, dark `#3987e5 #d95926 #199e70 #c98500 #d55181 #008300
#9085e9 #e66767`, neutral `#c4c4cc` / `#4a4a52`. Status (always with an icon): ok
`#138a43` (wash `#e9f6ee`), fail `#d03b3b`, warn `#b97800`, running `#2a78d6`. Radius
10 px panels, 7 px controls; no drop shadows except popovers. Project avatars: 18 px
rounded squares, initials in one of 8 hues (hashed from the project name) on a 14 %
(light) / 22 % (dark) tint of the same hue. `select` and range controls are styled
(chevron, control radius), never OS-default.
Fonts: Geist 400/500/600 for UI, Geist Mono 400/500 for ids, paths, commands and YAML
(both already self-hosted in `ui/`, OFL); 13 px base, tabular figures throughout.

## 8. Fixes found during the redesign

- **Interval on the wrong field.** A user's eval task showed value `0.0` with a
  95% interval near `1.0` (Wilson): the interval is computed on
  a different per-example field than the primary key. The interval must be computed on
  the primary key's own per-example field, or omitted. Root-cause and test in the plan.

## 9. Testing

- Unit (bun test): naming rule, colour rule, key splitting into sections, compare panel (defaults, toggles, keep-one rule, missing keys), `Fit`, every
  chart's geometry (ticks, ranges, zero-based bars), sidebar state ↔ URL, rename flow.
- Python: `compare` panel type validation and query,  `derive_names`, rename API/CLI/MCP, forwarding to hosts, event, index search,
  the interval fix.
- Playwright e2e in light and dark against `hx demo` and `hx demo --with-hosts`: every
  screen renders without overflow at 1280, 1440 and 2000 px; text size is constant
  across widths; rename round-trip; hide/show updates every panel.
- v4-specific tests (verbatim token copy, lettered figures, headline strings) are
  replaced, not kept.

## 10. Out of scope

Reports, run comparer panel beyond the existing Compare/Examples page, drag-to-resize
panels, per-panel settings cascade, artifacts browser beyond the Files list.
