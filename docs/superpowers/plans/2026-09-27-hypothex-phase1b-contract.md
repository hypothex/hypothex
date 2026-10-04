# Hypothex Phase 1b — Interface Contract

Binding for both phase 1b plans (backend and frontend). Spec: `docs/superpowers/specs/2026-09-26-hypothex-design.md` section 8. Mockups: `docs/mockups/ui-v4/`, `docs/mockups/kinds/*/`. Phase 1a code is on `main`; read it before planning (`src/hypothex/`).

Any name, field, or route below is exact. A plan may add private helpers but must not rename or reshape anything listed here.

## 1. Python modules (backend)

### 1.1 `hypothex.core.stats` (new, pure functions, no scipy)

```python
Z95 = 1.959963984540054
def wilson_interval(successes: int, n: int, z: float = Z95) -> tuple[float, float]: ...
def binom_two_sided_p(k: int, n: int) -> float: ...            # exact, p=0.5; used by sign test
def sign_test(fixed: int, broken: int) -> float: ...           # two-sided exact p on discordant pairs; 1.0 if both 0
def bootstrap_mean_interval(values: Sequence[float], resamples: int = 1000, seed: int = 0) -> tuple[float, float]: ...
def paired_bootstrap_p(a: Sequence[float], b: Sequence[float], resamples: int = 1000, seed: int = 0) -> float: ...
def welch_p(a: Sequence[float], b: Sequence[float]) -> float | None: ...   # None if either n<2 or both variances 0
def examples_needed(fixed: int, broken: int, n_total: int, alpha: float = 0.05, max_n: int = 100_000) -> int | None: ...
def quantile(values: Sequence[float], q: float) -> float: ...  # linear interpolation (numpy "linear")
def ecdf_points(values: Sequence[float], max_points: int = 200) -> list[tuple[float, float]]: ...
```
`welch_p` uses the Student-t CDF via the regularized incomplete beta function (implemented with a continued fraction, Numerical Recipes `betacf`), tested against known values.

### 1.2 `hypothex.core.records` changes

```python
class GitInfo(BaseModel):          # add fields; dirty now = tracked changes only
    repo: str | None = None; commit: str | None = None; branch: str | None = None
    dirty: bool = False
    untracked_count: int = 0
    untracked: list[str] = []      # first 20 paths
class Artifact(BaseModel):         # add
    step: int | None = None
    metrics: dict[str, float] = {}
class UsageTotals(BaseModel):
    tokens_in: int = 0; tokens_out: int = 0; usd: float = 0.0; seconds: float = 0.0; calls: int = 0
class RunRecord(BaseModel):        # add
    usage: UsageTotals | None = None
```

### 1.3 `hypothex.core.config` changes

```python
TaskKind = Literal["generic", "training", "agent_eval", "agent_iteration", "system_bench"]
class TaskSpec(_Strict):           # add
    kind: TaskKind = "generic"
    views: dict[str, dict[str, Any]] = {}    # inline view bodies; validated by core.views
    baseline: str | None = None              # group selector, e.g. "tag:baseline" or a group_id
    version_param: str = "version"           # agent_iteration ordering param
```
Two YAML guards live here and are used by both `load_project_config` and `views.validate_view_text`: `scan_yaml(text) -> YamlScan(problem, first_anchor, views_anchor, cycle)` streams the `yaml.parse` events before anything is composed or loaded and stops with `problem = ("YAML nested too deeply (over 64 levels)", line)` or `("YAML too large (over 100000 events)", line)`; `has_cycle(data) -> bool` walks the loaded value iteratively and finds a dict/list that contains itself (`YAML aliases must not form a cycle`, line of the first alias to a still-open collection, else none). `load_project_config` raises `ConfigError("<path>: <message> (line N)")` for the scan problem, then for any anchor or alias at or under `tasks.<task>.views` (`YAML anchors and aliases are not allowed in views`; keys written as aliases, `*vk:`, are resolved to the scalar their anchor names), then for a cycle anywhere; other anchors in `hypothex.yaml` stay allowed. Because `refresh_project` keeps the last good config, the view helpers (`view_document`, so `GET .../views/{name}` and `hx view show`) re-load `hypothex.yaml` when a name is not found and raise that `ConfigError` (API 400, CLI exit 1), never a 500.

### 1.4 `hypothex.core.views` (new)

```python
PanelType = Literal["stat_strip","leaderboard","curves","scatter","distribution","grid","table","trace","markdown","vega_lite"]
Source = Literal["runs","scores","metrics","predictions","samples","usage","traces"]
class RunFilter(BaseModel): status: list[str] | None = None; tags: list[str] | None = None; created_by: str | None = None; since: datetime | None = None
class PanelLayout(BaseModel): span: int = 12 (1..12); row: int | None = None
class PanelData(BaseModel, extra="forbid"):
    metrics: list[str] | None = None; x: str | None = None; y: str | None = None
    group_by: Literal["group","config","run","seed"] | None = None
    filter: dict[str, Any] | None = None; pick: Literal["best","latest","all"] | None = None
    source: Source | None = None; fields: list[str] | None = None
    run_id: str | None = None; example_id: str | None = None   # trace
    step_metric: str | None = None                              # curves x (default "step")
class PanelSpec(BaseModel, extra="forbid"):
    type: PanelType; title: str = ""; data: PanelData = PanelData(); layout: PanelLayout = PanelLayout()
    noise: list[Literal["seed","test_set"]] = ["seed","test_set"]   # leaderboard
    pareto: dict[str, Literal["min","max"]] | None = None           # scatter, e.g. {x: min, y: max}
    spec: dict[str, Any] | None = None                              # vega_lite
    text: str | None = None                                         # markdown
    scale: Literal["linear","log"] = "linear"                       # distribution/scatter x
    render: Literal["chart","table"] = "chart"                      # distribution: "table" = percentile table with Δ vs baseline
class ViewSpec(BaseModel, extra="forbid"):
    title: str; from_: TaskKind | None = Field(None, alias="from"); runs: RunFilter = RunFilter(); panels: list[PanelSpec] = []
class ValidationIssue(BaseModel): line: int | None; path: str; message: str; suggestion: str | None = None
class ViewInfo(BaseModel): name: str; title: str; origin: Literal["preset","inline","file"]; path: str | None; kind: TaskKind | None

PRESET_DIR = <package>/views/presets     # one YAML per kind: generic.yaml, training.yaml, ...
def load_preset(kind: TaskKind) -> ViewSpec: ...
def resolve_view(view: ViewSpec) -> ViewSpec: ...          # applies `from`: preset panels first, then view panels replace same-title panels and append new ones
def views_dir(repo: Path, task: str) -> Path: ...          # <repo>/.hypothex/views/<task>/
def list_views(repo: Path, config: ProjectConfig, task: str) -> list[ViewInfo]: ...  # "overview" (preset of task kind) first, then inline, then files (file wins on name clash)
def get_view(repo: Path, config: ProjectConfig, task: str, name: str) -> ViewSpec: ...  # resolved
def validate_view_text(text: str, known_metrics: set[str], known_fields: dict[str, set[str]]) -> tuple[ViewSpec | None, list[ValidationIssue]]: ...
def save_view(repo: Path, task: str, name: str, text: str) -> Path: ...   # atomic write; caller validates first
def delete_view(repo: Path, task: str, name: str) -> None: ...
def view_context(ctx: Context, project: str, task: str) -> tuple[set[str], dict[str, set[str]]]: ...  # metrics + fields per source seen in runs
```
Line numbers come from PyYAML node marks (`yaml.compose`). Metric-name suggestions use `difflib.get_close_matches`. Each `data.filter` key is checked against the fields of the rows it filters (`table`/`vega_lite`: the panel's source, with `version` on `runs`; other panels: `runs` rows without `version`), only when those fields are known: `unknown filter key <key> in <source>`. The metric column of a filter (`scores`: `metric`; `metrics` and `samples`: `name`) is checked against the known metrics: `unknown metric <name>`, with a nearest-name suggestion.
`validate_view_text` runs the 1.3 guards before `yaml.compose`: a `scan_yaml` problem (`YAML nested too deeply (over 64 levels)` / `YAML too large (over 100000 events)`), then any anchor or alias (`&a`, `*a`, `<<: *a`: `YAML anchors and aliases are not allowed`), each `(None, [ValidationIssue(line, "", message)])`; then `has_cycle` on the loaded value (`YAML aliases must not form a cycle`). `vega_spec_problems(spec, at=())` (also run by the panel engine) is bounded: more than 64 nested mappings/lists or 10,000 values gives the one problem `vega_lite spec is too deep (over 64 levels)` / `vega_lite spec is too large (over 10000 values)`, never a `RecursionError`. The API answers PUT with 400 + issues and `validate` with `{ok: false, issues}`; never a 500.
View names match `^[a-z0-9][a-z0-9_-]*$`; `overview` is reserved for the preset.

### 1.5 `hypothex.core.sources` (new)

```python
def iter_rows(ctx: Context, runs: list[RunRecord], source: Source, fields: list[str] | None = None) -> Iterator[dict[str, Any]]: ...
```
Every row carries `run_id`, `group_id`, `seed`. Per source: runs (record fields flattened: status, created_at, created_by, params.*, vars.*, usage.*), scores (metric, version, key, value), metrics (name, step, value, t), predictions (id, prediction, reference, meta.*, and per-example score fields as `<metric>@<version>.<field>`), samples (name, value), usage (example_id, tokens_in, tokens_out, usd, seconds), traces (example_id, turn, tool, args, result, tokens_in, tokens_out, seconds, error).
`group_id` is the leaderboard's `group_id` for the run (`<hash8>@<commit7>`).

### 1.6 `hypothex.core.panels` (new — query engine)

```python
class PanelResult(BaseModel):
    type: PanelType; title: str
    rows: list[dict[str, Any]]      # shape per type below
    meta: dict[str, Any] = {}       # axis domains, headline, units, warnings
def query_panel(ctx: Context, project: str, task: str, panel: PanelSpec, runs_filter: RunFilter | None = None) -> PanelResult: ...
def query_view(ctx: Context, project: str, task: str, view: ViewSpec) -> list[PanelResult]: ...
```
Row shapes (keys exact):
- `stat_strip`: `{label, value, unit, tooltip}`; `meta.headline: str`. With `data.metrics`, one row per reference (mean over the selected runs after `filter`/`pick`); without it, the task's stat strip.
- `leaderboard`: one row per seed group = `LeaderboardRow` fields (1.7) as JSON.
- `curves`: `{run_id, group_id, seed, name, step, value}`; `meta.checkpoints: [{run_id, step, value, best: bool}]`, `meta.events: [{run_id, step, kind: "spike"|"killed"|"failed"|"nonfinite"}]`, `meta.groups: [{group_id, label}]`.
- `scatter`: `{group_id, label, x, x_lo, x_hi, y, y_lo, y_hi, seeds: [{x, y}], pareto: bool, regression: bool}`; `meta.x, meta.y` (resolved; `data.y` defaults to the task primary), `meta.x_type: "quantitative"|"ordinal"`, `meta.y_higher_is_better: bool` (the y direction, rule below), `meta.best_group: str | null` (the `group_id` of the row with the best mean y in that direction, first row on a tie, null without rows). Both are sent whatever `pareto` says; the UI uses them to mark the best group and never assumes higher is better. Ordinal when `data.x` is a `params.`/`vars.` field with a non-numeric value: `x` is the raw string, rows are in natural order (`v9` before `v10`), `x_lo`/`x_hi` are null, no Pareto front. `regression` is true only when `meta.x_type == "ordinal"` and the row's y is worse than the best y among all earlier rows by more than that earlier best row's CI allows: higher-is-better `y_hi < best_earlier.y_lo`, lower-is-better `y_lo > best_earlier.y_hi` (a null bound on either side → false; ties keep the earlier row as best). Direction (also `meta.y_higher_is_better`): the task primary uses `Leaderboard.higher_is_better`; `usage.*` is lower-is-better; another configured metric uses its `higher_is_better`; any other name is lower-is-better when it contains `loss` or `error`. Quantitative x → always false.
- `distribution`: `{group_id, label, n, p50, p95, p99, ecdf: [[x, y], ...], seeds: [{run_id, p50, p95, p99}], vs_baseline: {p50: [delta_rel, lo, hi], p95: [...], p99: [...]} | null}`; `meta.name, meta.scale, meta.render` (`panel.render`), `meta.baseline` (the baseline row's `group_id` or null). The baseline is the row the task's `TaskSpec.baseline` selects (`tag:<t>`: the first group with a run tagged `<t>`; else a group_id, group_id prefix, or config_hash); the baseline row itself, every row when no baseline is configured or none matches, and every row when a baseline percentile is 0 get null. `delta_rel = (row.pXX − base.pXX) / base.pXX` on the pooled percentiles; `lo`/`hi` are the 2.5th/97.5th percentiles of a percentile bootstrap over the per-seed percentile values of both groups (1000 resamples, each percentile with its own `random.Random(0)`; per resample: draw the row's seeds with replacement, then the baseline's, take `(mean_row − mean_base) / mean_base`); `lo`/`hi` are null when either side has < 2 repeats.
- `grid`: `{item_id, group_id, value}` (value = fraction of seeds solved, 0..1); `meta.items: [item_id...]` ordered by difficulty (mean value asc), `meta.groups`.
- `table`, `vega_lite`: rows from `iter_rows`, then `data.filter` on the full row, then restricted to `fields`; `vega_lite` adds `meta.spec` (the spec with `data.values` left empty; the UI injects rows). Every `runs` row gets the synthetic field `version` (the `version_param` param, else the group's first-run creation time) on the full row before the filter, whatever `fields` lists, so `{source: runs, fields: [status], filter: {version: p10}}` selects the p10 runs.
- `trace`: `{turn, tool, args, result, tokens_in, tokens_out, seconds, error}`; `meta.run_id`, `meta.example_id`, `meta.failed_turn`.
- `markdown`: `[]`; `meta.text`.
Spike detection for curves: a point is a spike if `value > 5 × median(previous 20 values)` for metrics whose name contains `loss` (applied exactly: a zero median makes any positive value a spike).

### 1.7 `hypothex.core.leaderboard` changes

```python
class NoiseInterval(BaseModel): lo: float; hi: float; method: Literal["wilson","bootstrap"]; n: int
class VersusBest(BaseModel): delta: float; p: float | None; fixed: int | None; broken: int | None; test: Literal["sign","paired_bootstrap","welch"] | None; examples_needed: int | None
class LeaderboardRow(...):           # add
    label: str                         # short name: for agent_iteration tasks, the group's `version_param` value when set; otherwise group hypothesis first clause, or tag, or "group <id>"
    seed_values: dict[str, list[float]]   # per metric/key, one value per seed (run order)
    identical_seeds: bool              # n>1 and all primary seed values equal
    test_interval: NoiseInterval | None
    vs_best: VersusBest | None         # None for the best row
    created_by: list[str]; usage: UsageTotals | None   # summed across the group's runs
class Leaderboard(...):              # add
    headline: str; kind: TaskKind; stat_strip: list[dict[str, Any]]
```
`build_leaderboard` keeps its signature and gains keyword `per_example: dict[str, dict[str, dict[str, Any]]] | None = None` (run_id → example_id → per-example fields of the primary metric), used for test intervals and paired tests. `queries.get_leaderboard` loads it.

### 1.8 `hypothex.core.headlines` (new)

```python
def task_headline(board: Leaderboard) -> str: ...   # per kind, e.g. "SVM +0.037 over rf, p = 0.15"; system_bench: "<best> p95 −29% vs baseline [−31, −27]"; agent_iteration: "<best> 0.663, +0.263 over <first> [0.206, 0.321]"; no runs: "No scored runs yet"
def overview_headline(summary: "OverviewSummary") -> str: ...   # e.g. "Idle. SVM leads toy-test by 0.037, p = 0.15" / "2 running. ..."
```
Formatting: 3 significant decimals for metrics in [0,1], `p = 0.15` two decimals (`p < 0.001` when tiny).

### 1.9 `hypothex.core.overview` (new)

```python
class TimelineItem(BaseModel): run_id; project; task: str | None; created_at: datetime; created_by: str; status: RunStatus; archived: bool; group_id: str | None; is_best: bool; label: str
class IdeaRow(BaseModel): project; task: str | None; group_id: str; label: str; created_by: str; created_at: datetime; statuses: list[RunStatus]; primary: Stats | None; test_interval: NoiseInterval | None; identical_seeds: bool; best_band: NoiseInterval | None
class FailureRow(BaseModel): run_id; label; exit_code: int | None; created_at: datetime; stderr_path: str; retried_ok: bool
class ProjectRow(BaseModel): project; task; runs: int; best: float | None; kind: TaskKind
class OverviewSummary(BaseModel): headline: str; counts: dict[str, int]; timeline: list[TimelineItem]; ideas: list[IdeaRow]; running: list[RunRecord]; failures: list[FailureRow]; projects: list[ProjectRow]
def build_overview(ctx: Context, since: datetime | None = None) -> OverviewSummary: ...   # default since = 24 h ago
```

### 1.10 SDK additions (`hypothex.sdk.Run`, same no-op pattern in `NoopRun`)

```python
def log_trace(self, example_id: str, steps: Iterable[Mapping[str, Any]]) -> None       # traces/<safe_stem(example_id)>.jsonl (overwrite)
def log_usage(self, tokens_in: int = 0, tokens_out: int = 0, usd: float = 0.0, seconds: float = 0.0, example_id: str | None = None) -> None   # usage.jsonl
def log_samples(self, name: str, values: Iterable[float]) -> None                      # samples/<safe_stem(name)>.jsonl, append {"name": name, "value": v}
def log_checkpoint(self, path: str | os.PathLike[str], step: int, metrics: Mapping[str, float] | None = None, host: str = "local") -> None  # artifacts.jsonl kind=checkpoint + step + metrics
```
`execute_run` finalisation sums `usage.jsonl` into `RunRecord.usage`. Example-id and sample-name file stems come from `store.safe_stem(name)`: `[^A-Za-z0-9_.-]` → `_`; `-` + the first 8 hex digits of `sha1(name)` are appended when that changes the name OR when the name already ends in `-[0-9a-f]{8}` (`a/b` → `a_b-3ec69c85`, `a_b-3ec69c85` → `a_b-3ec69c85-d64fa8bc`, `a_b` stays `a_b`). So an unhashed stem never looks hashed, and two distinct names share a stem only on an 8-hex-digit sha1 prefix collision. Every trace row stores the original `example_id` and every sample row the original `name` (`{"name", "value"}`); readers report those, not the stem. Collision check: before `log_trace` / `log_samples` write, `store.check_stem_owner(path, key, original)` reads the existing file's first line, and if it stores a different original under `key` (`example_id` / `name`), raises `StoreError("id collision: <file> already holds <key> '<stored>', not '<original>'")` and writes nothing. An empty trace still creates its file (one marker line `{"example_id": <id>}`).

### 1.11 Demo data (`hypothex.demo`)

```python
def seed_demo(home: Path, kinds: Iterable[TaskKind] = ("generic","training","agent_eval","agent_iteration","system_bench")) -> dict[str, str]: ...  # returns {kind: "project/task"}
```
Writes real projects (repo dirs under `<home>/demo-repos/`) and runs through the public store/Context APIs so every file matches production layout. Deterministic (fixed seeds). Numbers mirror the mockups in `docs/mockups/kinds/*/data.js`. Used by UI tests, Playwright, docs screenshots. CLI: `hx demo [--kinds ...]` (hidden from `--help`).

## 2. HTTP API additions (`/api/v1`)

| Method | Path | Body / query | Returns |
|---|---|---|---|
| GET | `/overview` | `since` (ISO, optional) | `OverviewSummary` |
| GET | `/tasks/{project}/{task}/views` | | `list[ViewInfo]` |
| GET | `/tasks/{project}/{task}/views/{name}` | | `{info: ViewInfo, text: str, view: ViewSpec}` (text = YAML as stored; presets serialised) |
| PUT | `/tasks/{project}/{task}/views/{name}` | `{text, command_id?}` | `{info, view}`; 400 with `{error, issues: [ValidationIssue]}` if invalid |
| DELETE | `/tasks/{project}/{task}/views/{name}` | | `{ok: true}`; 400 for `overview` |
| POST | `/tasks/{project}/{task}/views/validate` | `{text}` | `{ok, issues, view? (resolved)}` — `view` is `resolve_view(view)` serialised by alias, so `from:` preset panels (with layouts) come first; the preset is the one `from` names, whatever the task's kind |
| POST | `/tasks/{project}/{task}/views/query` | `{view?: ViewSpec, name?: str, panel?: PanelSpec}` | `{panels: [PanelResult]}` |
| GET | `/tasks/{project}/{task}/leaderboard` | existing | `Leaderboard` (with 1.7 additions) |
| GET | `/runs/{id}/traces` | | `[{example_id, turns, failed}]` |
| GET | `/runs/{id}/traces/{example_id}` | | `PanelResult` of type `trace` |
| GET | `/tasks/{project}/{task}/kind` | | `{kind, run_view: [PanelSpec]}` — run-detail panels for the kind |

All existing routes keep working. Errors keep the `{error, type}` shape.

## 3. CLI and MCP additions

CLI (`--json` everywhere): `hx view list <task>`, `hx view show <task> <name>`, `hx view init <task> --from <kind> --name <name>`, `hx view add <task> --file <path> [--name]`, `hx view validate <task> <file>`, `hx view rm <task> <name>`, hidden `hx demo`.
MCP tools: `list_views(task, project=None)`, `get_view(task, name, project=None)`, `add_view(task, name, yaml_text, project=None)` (validates; returns issues on failure), `query_view(task, name, project=None)`.

## 4. Frontend (`ui/`)

- Bun + Vite + React 19 + TypeScript (strict). TanStack Router (file-free, code routes) + TanStack Query. CodeMirror 6 (`@codemirror/lang-yaml`, lint gutter) for the view editor. `vega-embed` for `vega_lite`. `d3-scale`, `d3-shape`, `d3-array`, `d3-format` for chart math. No Tailwind, no component kit.
- Tests: `bun test` with `happy-dom` + `@testing-library/react` for components; Playwright (`bunx playwright test`) smoke tests against `hx serve` on a demo home.
- Build: `bun run build` writes to `src/hypothex/ui_dist/` (git-ignored; built in CI and before packaging). `hatch` includes `ui_dist` in the wheel only when present, via `artifacts = ["src/hypothex/ui_dist/**"]` under `[tool.hatch.build.targets.wheel]` (not `force-include`, which fails the build when the folder is missing).
- Types: `ui/src/api/types.ts` generated from `/api/openapi.json` with `bunx openapi-typescript`, checked in; `bun run gen:types` regenerates.
- Routes: `/` Overview, `/t/:project/:task` Task (view tabs, `?view=<name>`), `/t/:project/:task/edit/:view` View editor (`new` for a new view), `/r/:runId` Run, `/x/:a/:b` Examples (query `metric`).
- Design tokens: copied verbatim from `docs/mockups/ui-v4/index.html` into `ui/src/styles/tokens.css` (light + `[data-theme=dark]`).
- Panels: one component per `PanelType` in `ui/src/panels/<Type>.tsx`, each taking `{result: PanelResult}`; registry `ui/src/panels/index.ts` maps type → component. Unknown type renders a small error box.
- Live updates: `useEventStream()` subscribes to `/api/v1/ws` with `after_sequence` replay and invalidates TanStack Query keys by event (`run.*` → runs, leaderboard, overview, views/query).
- Copy rule: terse; explanations only in `title` tooltips.

## 5. Plans

- `docs/superpowers/plans/2026-09-27-hypothex-phase1b-backend.md` — sections 1–3 (+ `hx serve` serving the built UI, fixtures).
- `docs/superpowers/plans/2026-09-27-hypothex-phase1b-frontend.md` — section 4, depends on the backend plan being merged (uses `hx demo` for fixtures).

## QA additions (2026-09-28)

Additive changes found in QA. Nothing above is renamed or removed.

- **Row labels** (1.5, 1.6). Every `iter_rows` row carries `label` next to `group_id`: the seed group's short name, the `LeaderboardRow.label` rule (`agent_iteration`: the `version_param` value; else the first clause of the newest non-empty hypothesis, a tag, or `group <id>`). `iter_rows(..., labels=None)` takes a `group_id → label` map; the panel engine passes the leaderboard's labels, so `table`/`vega_lite` rows match the leaderboard. `select_fields` always keeps `run_id`, `group_id`, `label`, `seed`; `label` is a valid `fields` entry and `data.filter` key. A `table` with `fields` adds `meta.columns` (the listed fields, in order); the UI draws only those columns, so the always-kept keys show only when listed. The `agent_eval`/`agent_iteration` run view's `tokens per turn` table lists `fields: [turn, tokens_in, tokens_out, seconds]`. The `agent_eval` (Failures) and `system_bench` (Error rate, Repeat spread) presets encode `y` by `label`.
- **`groups` source** (1.4 `Source`, 1.6 `table`/`vega_lite`). `Source` gains `"groups"`: task-level, one row per seed group of the selected runs, built by `panels.group_rows` (`iter_rows` refuses it). Keys (`views.GROUP_FIELDS`): `group_id, label, version, run_id (latest), n (runs), commit (7 chars | null), created_by (comma-joined), hypothesis (newest non-empty), primary (leaderboard mean | null), primary_lo, primary_hi (test-set interval, else seed t-interval), delta_prev (primary − previous row's primary; null for the first row or a missing side), changes`. Rows are in version order: groups with a `version_param` value first (natural order), then by first-run time. `changes` = `params`/`vars` keys (version param excluded) that differ from the previous row's latest run, `key: old → new` joined by `; ` (comma-separated values give `tools: +a −b`; a missing side is `—`); with none, the short commit. The first row's `changes` is `""` (nothing to compare with; the UI shows `—`). `fields` keeps exactly the listed keys (no `run_id`/`seed` added); `data.filter` reads the full row. The `agent_iteration` preset's Changes table uses `{source: groups, fields: [version, changes, commit, delta_prev, primary, n]}`.
- **Curves events** (1.6 `curves`). Each `meta.events` entry gains `label`: kind plus a short x, `"spike 9k"`, `"killed 14k"`, `"failed 950"` (`panels.short_step`: `k`/`M`, one decimal below 10). Consecutive spike points of one loss series form one episode, and overlapping episodes of a run's loss series (train and val loss) merge, so a spike is one event at the episode's first x. A `nonfinite` event marks a divergence: `sdk.Run.log` does not write a `NaN` or infinite value to `metrics.jsonl` but appends `{name, step, value: "nan"|"inf"|"-inf", t}` to `<run_dir>/metrics_nonfinite.jsonl`; each distinct x of a run's rows for a shown metric (all but `step_metric` when `data.metrics` is unset; a step with no `step_metric` value is dropped) is one event labelled `"NaN 9k"`, and the UI draws it like a spike. The `training` preset's Curves panel lists `metrics: [train/loss, val/loss, val/top1, lr]` in that order (no `sys/*`; GPU stays in the GPU sparklines).
- **Overview headline** (1.8). When the focus task is `system_bench`, `overview_headline` leads with that task's headline (`"1 running. async-worker p95 −29% vs baseline [−32, −26]"`), not an absolute gap (`"leads … by 45.0"`).
- **Units and value formats** (1.3, 1.6, 1.7, 1.8). `MetricSpec.unit: str = ""` (max 8 chars, display only). `headlines` adds `ValueFormat = Literal["fraction","number","percent_delta"]`, `metric_unit(ref, configured="")` (configured wins; else `usd`/`cost` → `$`, `token` → `tokens`, `latency` or an `ms` word → `ms`, `seconds`/`sec`/`_s` → `s`, else `""`), `value_format(unit, values, higher_is_better)` (`percent_delta` for a lower-is-better `ms`/`s`; `number` for any other unit or a value outside [0,1]; else `fraction`), `fmt_sig3`, `fmt_metric(x, unit, fmt, suffix=True)` (`fraction`: 3 decimals; else 3 significant figures + unit: `166 ms`, `$332`; dollars 0.01–100 keep cents: `$0.55`), `fmt_metric_delta(delta, base, unit, fmt)` (`percent_delta`: `+27%` of `base`; `number`: `−45 ms`; `fraction`: `+0.017`). `Leaderboard` gains `unit: str = ""` and `value_format: ValueFormat = "fraction"` (primary metric; values = group means); `VersusBest` gains `delta_rel: float | None` (`delta / |best mean|`, null when that mean is 0). Headlines and stat strips use them: `"fast p95 310 ms"`, stat `{value: "166 vs 233", unit: "ms"}`, `{value: "$0.55", unit: ""}` (`$` is a prefix in `value`; other units go in `unit`; relative % values have no unit). Overview (1.8): `IdeaRow` and `ProjectRow` gain `unit: str = ""` (the task's `Leaderboard.unit`; `""` for runs without a task); the UI shows the Best column and idea scores with it (`166 ms`, `$0.55`). Panel meta: `leaderboard` and `stat_strip` add `unit`, `value_format`; `scatter` adds `x_unit`, `y_unit`; `distribution` adds `unit`. `stat_strip` rows from `data.metrics` use `fmt_metric` and the ref's unit.
- **Per-run labels** (1.6). With `data.group_by: run`, every panel labels a run `<group label> r<n>` (`baseline r1`), `n` = the run's 1-based position in its seed group among the selected runs, oldest first. `curves` `meta.groups` entries then also carry `seed_group` (the run's `group_id`) and `repeat` (`n`).
