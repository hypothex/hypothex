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
Line numbers come from PyYAML node marks (`yaml.compose`). Metric-name suggestions use `difflib.get_close_matches`.
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
- `stat_strip`: `{label, value, unit, tooltip}`; `meta.headline: str`.
- `leaderboard`: one row per seed group = `LeaderboardRow` fields (1.7) as JSON.
- `curves`: `{run_id, group_id, seed, name, step, value}`; `meta.checkpoints: [{run_id, step, value, best: bool}]`, `meta.events: [{run_id, step, kind: "spike"|"killed"|"failed"}]`, `meta.groups: [{group_id, label}]`.
- `scatter`: `{group_id, label, x, x_lo, x_hi, y, y_lo, y_hi, seeds: [{x, y}], pareto: bool}`.
- `distribution`: `{group_id, label, n, p50, p95, p99, ecdf: [[x, y], ...], seeds: [{run_id, p50, p95, p99}]}`.
- `grid`: `{item_id, group_id, value}` (value = fraction of seeds solved, 0..1); `meta.items: [item_id...]` ordered by difficulty (mean value asc), `meta.groups`.
- `table`, `vega_lite`: rows from `iter_rows` restricted to `fields`; `vega_lite` adds `meta.spec` (the spec with `data.values` left empty; the UI injects rows).
- `trace`: `{turn, tool, args, result, tokens_in, tokens_out, seconds, error}`; `meta.run_id`, `meta.example_id`, `meta.failed_turn`.
- `markdown`: `[]`; `meta.text`.
Spike detection for curves: a point is a spike if `value > 5 × median(previous 20 values)` for metrics whose name contains `loss`.

### 1.7 `hypothex.core.leaderboard` changes

```python
class NoiseInterval(BaseModel): lo: float; hi: float; method: Literal["wilson","bootstrap"]; n: int
class VersusBest(BaseModel): delta: float; p: float | None; fixed: int | None; broken: int | None; test: Literal["sign","paired_bootstrap","welch"] | None; examples_needed: int | None
class LeaderboardRow(...):           # add
    label: str                         # short name: group hypothesis first clause, or tag, or "group <id>"
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
def log_trace(self, example_id: str, steps: Iterable[Mapping[str, Any]]) -> None       # traces/<example_id>.jsonl (overwrite)
def log_usage(self, tokens_in: int = 0, tokens_out: int = 0, usd: float = 0.0, seconds: float = 0.0, example_id: str | None = None) -> None   # usage.jsonl
def log_samples(self, name: str, values: Iterable[float]) -> None                      # samples/<name>.jsonl, append {"value": v}
def log_checkpoint(self, path: str | os.PathLike[str], step: int, metrics: Mapping[str, float] | None = None, host: str = "local") -> None  # artifacts.jsonl kind=checkpoint + step + metrics
```
`execute_run` finalisation sums `usage.jsonl` into `RunRecord.usage`. Example-id file names are sanitised (`[^A-Za-z0-9_.-]` → `_`).

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
| POST | `/tasks/{project}/{task}/views/validate` | `{text}` | `{ok, issues, view?}` |
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
- Build: `bun run build` writes to `src/hypothex/ui_dist/` (git-ignored; built in CI and before packaging). `hatch` includes `ui_dist` in the wheel via `[tool.hatch.build.targets.wheel.force-include]` only when present.
- Types: `ui/src/api/types.ts` generated from `/api/openapi.json` with `bunx openapi-typescript`, checked in; `bun run gen:types` regenerates.
- Routes: `/` Overview, `/t/:project/:task` Task (view tabs, `?view=<name>`), `/t/:project/:task/edit/:view` View editor (`new` for a new view), `/r/:runId` Run, `/x/:a/:b` Examples (query `metric`).
- Design tokens: copied verbatim from `docs/mockups/ui-v4/index.html` into `ui/src/styles/tokens.css` (light + `[data-theme=dark]`).
- Panels: one component per `PanelType` in `ui/src/panels/<Type>.tsx`, each taking `{result: PanelResult}`; registry `ui/src/panels/index.ts` maps type → component. Unknown type renders a small error box.
- Live updates: `useEventStream()` subscribes to `/api/v1/ws` with `after_sequence` replay and invalidates TanStack Query keys by event (`run.*` → runs, leaderboard, overview, views/query).
- Copy rule: terse; explanations only in `title` tooltips.

## 5. Plans

- `docs/superpowers/plans/2026-09-27-hypothex-phase1b-backend.md` — sections 1–3 (+ `hx serve` serving the built UI, fixtures).
- `docs/superpowers/plans/2026-09-27-hypothex-phase1b-frontend.md` — section 4, depends on the backend plan being merged (uses `hx demo` for fixtures).
