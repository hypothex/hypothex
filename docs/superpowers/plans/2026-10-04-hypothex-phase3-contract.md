# Hypothex Phase 3 — Interface Contract

Binding for the phase 3 plans (backend, frontend). Spec: `docs/superpowers/specs/2026-09-26-hypothex-design.md` sections **9** (phase 3 design summary), **13** (phase 3 row), 3.4 (Postgres + Alembic), 5.3 (auth failures stop retrying until re-pair), 5.4 (`route: url` lab server), 7.2 (`hx export`, `hx storage`), 7.3 (phase 3 auth), 7.4 (`/mcp` on the server), 12 (`daemon/` notifier). Phases 1a, 1b, and 2 are on `main`; read the real code (`src/hypothex/`, `ui/src/`) before planning. Names below are exact; plans may add private helpers but must not rename or reshape these.

Prerequisite: the phase 2 frontend (Sweep page `/s/:project/:id`, Launch dialog) is merged to `main` before the phase 3 frontend plan starts. The phase 3 backend plan depends only on `main` as of `738c711`.

Hard rules: no test or step ever connects to a real Slack workspace, SMTP server, Tailscale tailnet, Postgres server outside Docker, SSH host, or SLURM cluster, and nothing reads or writes `~/.ssh`. Tests use a fake SMTP server, a fake webhook receiver, a fake `tailscale` binary, a fake clock, in-process env servers (`route: url`), and a throwaway Postgres container (marker `docker`). A session-wide network guard refuses every socket connect to a non-loopback address.

## 0. Phase 3 scope (every item the spec assigns to phase 3)

| # | Item | Spec | Contract section |
|---|---|---|---|
| 1 | Lab notebook: `<store>/<project>/notebook/YYYY-MM-DD.md`, `[[run:<id>]]` chips, UI edit, `hx note --project` | 9 | 1.4 |
| 2 | Paper baselines: `baselines:` per task (`name`, value per metric key, `source`, `metric_version_equivalent`) | 9 | 1.5 |
| 3 | Notifications: Slack incoming webhook + email (SMTP) on finish/fail/lost, per-project opt-in, `~/.hypothex/config.yaml`, secrets from env vars | 9, 12 | 1.1, 1.7 |
| 4 | Weekly summary per project: runs started/finished/failed, leaderboard changes, top new notes (+ cost); Slack/email; saved to the notebook | 9 | 1.8 |
| 5 | Export: leaderboard and compare → LaTeX (booktabs), Markdown (+ CSV), best bolded, `mean ± std`, test-set CI | 7.2, 9 | 1.6 |
| 6 | Storage: bytes per project/run/artifact, local + remote; `hx storage clean --archived --older-than 30d --dry-run`; only artifacts of archived, unstarred runs; UI always dry-run first | 7.2, 9 | 1.9 |
| 7 | Team/server mode: hub on an always-on server with Postgres; Alembic; runs record `created_by` (human user or agent) | 3.4, 9 | 1.11, 1.12 |
| 8 | Auth and devices: `hx pair` one-time URL + QR (secret in `#fragment`, 5 min), revocable sessions (cookie / bearer), WebSocket tickets, scopes `read`/`launch`/`admin` on every method, pairing never widens scope | 7.3, 9 | 1.10 |
| 9 | Tailscale access (`tailscale serve` HTTPS), no custom relay; `route: url` hosts such as a lab server | 5.4, 9 | 1.13 |
| 10 | Hub-to-host auth failures stop retrying until the user re-pairs | 5.3 | 1.13 |
| 11 | `/mcp` over HTTP behind auth with per-tool scopes | 7.4, 9 | 1.10, 5 |
| 12 | SDK `run.log_cost(...)` (named in section 9, not yet shipped) | 9 | 1.14 |
| 13 | Collaborators: a few people share one hub; run ownership | 9, 13 | 1.12 |

Done when (spec 13): a collaborator pairs a laptop with a server hub, sees the same projects, and launches a run on a shared environment (section 11 turns this into an automated acceptance test).

## 1. Python modules

### 1.1 `hypothex.core.settings` — the hub's `config.yaml`

```python
SETTINGS_FILENAME = "config.yaml"                       # <home>/config.yaml (spec 9 "~/.hypothex/config.yaml")
ENV_NAME = r"^[A-Z_][A-Z0-9_]{0,63}$"                   # an environment variable NAME, never a value
NotifyEvent = Literal["finished", "failed", "lost", "killed"]
Channel = Literal["slack", "email"]
Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
class SlackSettings(BaseModel, extra="forbid"): webhook_env: str = Field("HYPOTHEX_SLACK_WEBHOOK", pattern=ENV_NAME)
class EmailSettings(BaseModel, extra="forbid"):
    host: str; port: int = Field(587, ge=1, le=65535); security: Literal["starttls", "ssl", "none"] = "starttls"
    username: str | None = None; password_env: str | None = Field("HYPOTHEX_SMTP_PASSWORD", pattern=ENV_NAME)
    sender: str; to: list[str] = Field(min_length=1); timeout: float = Field(20, gt=0, le=120)
class ProjectRule(BaseModel, extra="forbid"):
    events: list[NotifyEvent] = ["finished", "failed", "lost"]; channels: list[Channel] = Field(["slack"], min_length=1)
    min_seconds: float = Field(0, ge=0)   # finished runs shorter than this are skipped; failed/lost/killed always notify
    fold_sweeps: bool = True              # sweep runs give one notice per sweep when it has no active run left
class NotifySettings(BaseModel, extra="forbid"):
    slack: SlackSettings | None = None; email: EmailSettings | None = None
    projects: dict[str, ProjectRule] = {}; default: ProjectRule | None = None   # None: unlisted projects get nothing (opt-in)
    max_age_hours: float = Field(24, gt=0)   # a run that ended longer ago than this when first seen gets no notice
class DigestSettings(BaseModel, extra="forbid"):
    enabled: bool = False; weekday: Weekday = "mon"; hour: int = Field(9, ge=0, le=23); timezone: str | None = None   # IANA; None = hub local
    channels: list[Channel] = ["slack"]; projects: list[str] | Literal["all"] = "all"; save_to_notebook: bool = True; top_notes: int = Field(5, ge=0, le=20)
class ServerSettings(BaseModel, extra="forbid"):
    auth: Literal["off", "on"] = "off"; public_url: str | None = Field(None, pattern=r"^https?://[^/\s]+$")
    session_days: int = Field(90, ge=1, le=365)
    index_url: str | None = None          # None = SQLite <home>/index.db; "postgresql+psycopg://user@host:5432/db" (no password in the URL)
    index_password_env: str = Field("HYPOTHEX_INDEX_PASSWORD", pattern=ENV_NAME)
class StorageSettings(BaseModel, extra="forbid"): older_than_days: int = Field(30, ge=0); kinds: list[str] = ["checkpoint"]; plan_ttl_minutes: int = Field(60, ge=1, le=1440)
class Settings(BaseModel, extra="forbid"): server: ServerSettings = ServerSettings(); notify: NotifySettings = NotifySettings(); digest: DigestSettings = DigestSettings(); storage: StorageSettings = StorageSettings()
def settings_path(layout: Layout) -> Path: ...
def load_settings(layout: Layout) -> Settings: ...      # missing file -> defaults; scan_yaml + has_cycle guards; ConfigError names the line
def save_settings(layout: Layout, settings: Settings) -> None: ...   # atomic, mode 0600
SECRETS_FILENAME = "secrets.env"                        # <home>/secrets.env: KEY=VALUE lines, # comments
def resolve_secret(layout: Layout, name: str) -> SecretStr | None: ...   # os.environ[name], else secrets.env; None when unset or empty
class SecretsFileError(ConfigError): ...                # secrets.env readable by group/other or not owned by the user: refused, names `chmod 600`
```
`load_settings` refuses a literal secret: any key named `webhook`, `webhook_url`, `password`, `token`, `secret`, or `url` under `notify.slack`/`notify.email` fails `extra="forbid"` with the hint "use <key>_env: NAME (the variable holding it)"; the offending value is never echoed. `index_url` with a password (`user:pw@`, or a `password`/`sslpassword` query parameter, which libpq takes as the password) is a `ConfigError` that prints the URL with the password replaced by `***`; `redact_url` hides both forms wherever a URL is shown (index errors, `hx db`). `SecretStr` is pydantic's (repr `'**********'`); callers call `.get_secret_value()` only at the socket.

### 1.2 Run ownership and identity (`hypothex.core.records`, `hypothex.core.index`, `hypothex.core.sweeps`)

```python
class RunRecord(...):   # add
    owner: str | None = None        # user name of the principal that created the run; None = auth off or before phase 3
class SweepSpec(...):   # add
    owner: str | None = None
# hypothex.core.index
SCHEMA_VERSION = 3                  # RunRow.owner column (indexed)
def Index.list_runs(..., owner: str | None = None) -> list[RunRecord]: ...   # additive keyword
# hypothex.core.execution
class RunRequest(...):  # add
    owner: str | None = None        # copied to RunRecord.owner
# hypothex.api.app
class ActionBody(...):  # add
    owner: str | None = None        # honoured only from the host principal (a hub forwarding); else replaced by the caller
```
`created_by` with auth on is set by the server from the principal, never from the request body: `human:<user>` for browser and CLI sessions, `agent:<agent>@<user>` when the request carries `X-Hypothex-Agent: <agent>` (CLI sends it when `HYPOTHEX_AGENT` is set; MCP sends `mcp` or the tool's `agent` argument). Existing readers that test `created_by.startswith("agent")` keep working. With auth off, phase 1–2 behaviour is unchanged (`human`, `agent:<name>`). A hub forwards `owner` and `created_by` to hosts in `HostLaunchBody`/`SweepBody`; an env server accepts those two fields only from the host principal (its `TokenGuard` token or a `client: "host"` session with `admin` scope; `AuthStore.redeem` refuses `client="host"` on an offer below `admin`), else ignores them.

### 1.3 `hypothex.auth.ownership`

```python
RunAction = Literal["stop", "archive", "tag", "star", "note", "rerun", "reinfer", "reeval", "cancel_queued", "extend", "pull"]
OWNER_ACTIONS = frozenset({"stop", "archive", "cancel_queued"})   # owner or admin
def may_act(principal: Principal, owner: str | None, action: RunAction) -> bool: ...
def require_act(principal: Principal, owner: str | None, action: RunAction) -> None: ...   # ScopeError (403) "run owned by <owner>; stop needs owner or admin"
def require_local_exec(principal: Principal) -> None: ...   # ScopeError (403) "runs on this machine need admin; launch on a host" unless admin
```
Rules: a run that executes on the serving machine (a launch, a host launch to `local`, a rerun or reinfer of a local run, a sweep or extension placed here; HTTP and MCP alike) needs `require_local_exec`: its command runs as the server's Unix user and can read that user's files, `serve/server.json` (the owner's admin token) included, so starting one is admin trust. `admin` covers the owner, every caller with auth off, and a hub forwarding to its host; a `launch` collaborator launches on hosts. Every action needs `launch`. `OWNER_ACTIONS` also need `principal.user == owner` or `admin`; `owner is None` (legacy or auth-off runs) counts as the hub owner's, so only `admin` may stop or archive them. Rerun/reinfer create a new run owned by the caller.

### 1.4 `hypothex.core.notebook`

```python
NOTEBOOK_DIR = "notebook"                               # <store>/<project>/notebook/YYYY-MM-DD.md
DAY_PATTERN = r"^\d{4}-\d{2}-\d{2}$"
RUN_LINK = re.compile(r"\[\[run:([A-Za-z0-9][A-Za-z0-9_.-]{0,79})\]\]")
NOTEBOOK_MAX_BYTES = 1024 * 1024                        # per day file
class RunChip(BaseModel): run_id: str; status: RunStatus | None; task: str | None; label: str; primary: float | None   # status None = unknown run id
class NotebookDay(BaseModel): project: str; day: date; text: str; hash: str; runs: list[RunChip]; updated_at: datetime | None   # hash = "sha256:<hex>" of the file bytes ("" when missing)
class NotebookConflictError(HypothexError): current: NotebookDay   # API 409 with {error, type, current}
class NotebookTooLargeError(HypothexError): ...                    # API 413
def notebook_dir(layout: Layout, project: str) -> Path: ...
def today(now: datetime | None = None, tz: str | None = None) -> date: ...    # hub-local date (DigestSettings.timezone when set)
def hub_today(ctx: Context, now: datetime | None = None) -> date: ...         # today(now, config.yaml digest.timezone): the one "today" of append_entry, the API's `today` day, MCP, CLI, UI
def list_days(ctx: Context, project: str) -> list[dict[str, Any]]: ...       # [{day, bytes, entries}] newest first
def read_day(ctx: Context, project: str, day: date) -> NotebookDay: ...
def append_entry(ctx: Context, project: str, text: str, author: str, *, day: date | None = None, now: datetime | None = None) -> NotebookDay: ...   # project lock; fsutil.append_note_file format "## <iso> — <author>"
def write_day(ctx: Context, project: str, day: date, text: str, *, base_hash: str, author: str) -> NotebookDay: ...   # whole-file replace; NotebookConflictError when the file hash != base_hash
def run_links(text: str) -> list[str]: ...              # unique ids in order of first use
```
Unknown project → `StoreError` (404). The API's `{day}` is `YYYY-MM-DD` or `today` (resolved by the hub with `hub_today`; clients never compute it). Both writes emit `notebook.updated` `{project, day, author}` with `project=` set. Notebook files are hub-local (never mirrored to hosts) and are files of record: `hx reindex` does not touch them.

### 1.5 Paper baselines (`hypothex.core.config`, `hypothex.core.leaderboard`)

```python
BASELINE_SOURCE = r"^(arXiv:\d{4}\.\d{4,5}(v\d+)?|doi:10\.\d{4,9}/\S+|https://\S+)$"
class BaselineSpec(_Strict):
    name: str = Field(min_length=1, max_length=64)
    values: dict[str, float] = Field(min_length=1)       # metric ref "metric/key" -> value (finite)
    std: dict[str, float] = {}                            # optional published std, same keys
    source: str = Field(pattern=BASELINE_SOURCE)
    metric_version_equivalent: dict[str, str] = {}        # metric name -> our version it matches, e.g. {topk: v2}; a bare string means every metric of the task
    note: str = Field("", max_length=200)
class TaskSpec(...):   # add
    baselines: list[BaselineSpec] = []
class BaselineRow(BaseModel):
    name: str; values: dict[str, float]; std: dict[str, float]; source: str; source_url: str
    version_match: dict[str, bool]     # metric name -> metric_version_equivalent == the leaderboard's version for it (missing -> False)
    primary: float | None; delta_vs_best: float | None   # best group's primary mean minus this value, sign by higher_is_better
class Leaderboard(...):   # add
    baselines: list[BaselineRow] = []
def baseline_url(source: str) -> str: ...   # arXiv:X -> https://arxiv.org/abs/X; doi:X -> https://doi.org/X; https kept
```
`ProjectConfig._check_references` adds: every `values`/`std` key names a metric of the task (`parse_metric_key`), names are unique per task, values finite. Baselines never count as a seed group, never become "best", and never enter `vs_best`.

### 1.6 `hypothex.core.export`

```python
ExportFormat = Literal["latex", "markdown", "csv"]
NoiseMode = Literal["both", "seed", "test", "none"]
class ExportOptions(BaseModel, extra="forbid"):
    format: ExportFormat = "markdown"; metrics: list[str] | None = None   # metric refs; default: task primary, then the other keys present, sorted
    noise: NoiseMode = "both"; digits: int = Field(3, ge=0, le=6); percent: bool = False   # percent: x100 for value_format "fraction"
    top: int | None = Field(None, ge=1); groups: list[str] | None = None; baselines: bool = True
    caption: str | None = None; label: str | None = None; standalone: bool = False; mark_noise: bool = True
class ExportCell(BaseModel): mean: float | None; std: float | None; n: int; identical: bool; lo: float | None; hi: float | None; method: Literal["wilson", "bootstrap"] | None; n_examples: int | None; best: bool
class ExportRow(BaseModel): kind: Literal["group", "run", "baseline"]; label: str; key: str; n: int; cells: dict[str, ExportCell]; within_noise: bool; version_mismatch: bool; source: str | None
class ExportTable(BaseModel): title: str; columns: list[str]; higher_is_better: dict[str, bool]; rows: list[ExportRow]; footnotes: list[str]
def leaderboard_table(board: Leaderboard, opts: ExportOptions) -> ExportTable: ...
def compare_table(ctx: Context, run_ids: list[str], opts: ExportOptions) -> ExportTable: ...   # one row per run (kind "run"), n = 1, scores at the task's current versions; RunError when a shown metric has different versions or directions across the runs' projects (never merged into one column); every column, here and in leaderboard_table, ranks by the leaderboard's own per-key rule (a system_bench percentile key such as latency/p95 is lower-first)
def render(table: ExportTable, opts: ExportOptions) -> str: ...
def export_task(ctx: Context, task: str, project: str | None, opts: ExportOptions) -> str: ...
def export_compare(ctx: Context, run_ids: list[str], opts: ExportOptions) -> str: ...
def latex_escape(text: str) -> str: ...   # & % $ # _ { } ~ ^ \ escaped; output is ASCII + LaTeX commands
```
Formats (deterministic: same input, byte-identical output; golden files):
- Seed noise: `mean ± std` with `n` in its own column; `n = 1` shows the mean only and the row gets `¹` (single seed); identical seeds show `mean (◇×n)`, never `± 0` (LaTeX `$\diamond{\times}n$`).
- Test-set noise: the primary column adds `[lo, hi]` (95%, `NoiseInterval`); other metrics have none (no per-example data per key). `noise="seed"|"test"|"none"` drops the other parts.
- Best: per column, the best group mean by `higher_is_better` is bold (`**…**` / `\textbf{…}`); ties all bold; `†` marks rows `within_noise_of_best`; baselines are listed after a rule (`\midrule` / a separator row), never bold, `‡` when `version_match` is false for a shown metric. Header arrows `↑`/`↓` (`$\uparrow$`/`$\downarrow$`).
- LaTeX: `tabular` with booktabs rules (`\toprule`, `\midrule`, `\bottomrule`); `standalone=True` wraps it in `table` with `\caption`/`\label` and prints footnotes below; otherwise footnotes are `% ` comment lines. Requires `\usepackage{booktabs}` (first line comment says so).
- CSV: long format, header `kind,label,key,n,metric,mean,std,identical,ci_lo,ci_hi,ci_method,n_examples,best,within_noise,version_mismatch,source`; numbers in full precision (`repr`), empty for missing.
- Missing value: `—` (Markdown), `--` (LaTeX), empty (CSV). Never `nan`.

### 1.7 `hypothex.notify` — channels, messages, notifier (hub only)

```python
# hypothex.notify.messages
NoticeKind = Literal["run", "sweep", "digest", "test"]
class Notice(BaseModel):
    id: str                            # 16 hex of sha256(kind, project, run_id|sweep_id|week, status, n)
    kind: NoticeKind; project: str | None; run_id: str | None = None; sweep_id: str | None = None; status: str | None = None
    title: str                         # one line, e.g. "✓ toy/clf 01J8Z3K7-clf-a1b2 acc 0.913"
    lines: list[str]                   # terse facts: "0.4 GPU-h · $0.84 · 12m", "exit 1 · <last stderr line, 200 chars>"
    url: str | None                    # <public_url or hub url>/r/<run_id> or /s/<project>/<id>
    created_at: datetime
def run_notice(ctx: Context, record: RunRecord, *, base_url: str | None) -> Notice: ...
def sweep_notice(ctx: Context, summary: SweepSummary, *, base_url: str | None) -> Notice: ...
def test_notice(channel: Channel) -> Notice: ...
def render_slack(notice: Notice) -> dict[str, Any]: ...       # {"text": "<title>\n<lines…>\n<url>"}
def render_email(notice: Notice, settings: EmailSettings) -> EmailMessage: ...   # Subject = title; text/plain only
# hypothex.notify.channels
class ChannelError(HypothexError): permanent: bool; retry_after: float | None; error_class: str   # e.g. "http_429", "smtp_535", "timeout", "unset:HYPOTHEX_SLACK_WEBHOOK"
def send_slack(webhook: SecretStr, payload: dict[str, Any], *, timeout: float = 10) -> None: ...   # httpx POST; https only unless the host is loopback; 2xx ok; 429 (Retry-After) / 5xx / transport -> retryable; other 4xx permanent
def send_email(settings: EmailSettings, password: SecretStr | None, message: EmailMessage) -> None: ...   # smtplib; starttls|ssl|none; 4xx/connection -> retryable; 5xx and auth failure -> permanent
def redact(text: str, secrets: Iterable[SecretStr | str | None]) -> str: ...   # every secret value (and a webhook URL's path) -> "***"
# hypothex.notify.notifier
NOTIFY_DIR = "notify"                  # <home>/notify/{cursor.json, outbox/<id>.<channel>.json, sent.jsonl, digest.json}
RETRY_DELAYS = (30.0, 120.0, 600.0)    # seconds after attempts 1, 2, 3; then failed
TERMINAL_EVENTS = ("run.finished", "run.failed", "run.killed", "run.lost")
class OutboxEntry(BaseModel):
    id: str; channel: Channel; notice: Notice; status: Literal["pending", "sending", "sent", "failed", "skipped"]
    attempts: int = 0; next_at: datetime; last_error: str | None = None   # error_class only, redacted
    created_at: datetime; sent_at: datetime | None = None
class Notifier:
    def __init__(self, ctx: Context, settings: Settings, *, now: Callable[[], datetime] = utcnow, transport: httpx.BaseTransport | None = None) -> None: ...
    def scan(self) -> list[OutboxEntry]: ...      # events after cursor: TERMINAL_EVENTS and mirror.run_updated whose original_type is one; rule match; enqueue (idempotent by entry id)
    def deliver(self) -> list[OutboxEntry]: ...   # due entries: mark sending, send, mark sent/failed/pending(+next_at)
    def digests(self) -> list[str]: ...           # projects whose weekly digest was sent this tick (1.8)
    def tick(self) -> None: ...                   # scan, digests, deliver (a digest goes out on the tick that makes it)
    def recent(self, limit: int = 50) -> list[OutboxEntry]: ...
def run_notifier_loop(ctx: Context, stop: threading.Event, *, interval: float = 5.0) -> None: ...   # re-reads config.yaml each tick
```
The notifier runs only in the hub's `hx serve` (kind `local`), as a thread started in the lifespan like the scheduler. A run is folded into a sweep only when it carries this hub's member tag `sweep:<owner8>:<id>` (a mirrored run of another hub's sweep with the same id is notified as a run). A folded sweep notifies only when no member is queued or running, when it is not still issuing launches (fewer members than `len(sweep_combos(spec)) * len(spec.seeds)` while `sweeps.sweep_issuing(layout, project, sweep_id)` holds: a short first run never reads `1/1`), and when at least one of its runs ended with a status in `rule.events` (a failure-only rule hears only about sweeps with a failure; `events: []` hears nothing). `Notifier.enqueue` redacts every configured secret value from every notice (run, sweep, digest, test) before it is written. A digest that fails in `tick` is logged by type name and never stops delivery. First start sets the cursor to the current last sequence (no backlog flood). A run mirrored from a host notifies from its `mirror.run_updated` event; a host never notifies. Delivery is at least once: an entry left `sending` by a crash is retried after 60 s; one already recorded in `sent.jsonl` (a crash between the record and the outbox unlink) is dropped, never resent. Events `notify.sent`/`notify.failed` `{entry_id, channel, kind, run_id, attempts, error_class}` (no secret, no message body).

### 1.8 `hypothex.core.digest` — weekly summary

```python
class TaskChange(BaseModel): task: str; primary: str; before: float | None; after: float | None; best_label: str; best_group_id: str | None; new_best: bool; n_new_runs: int
class NoteItem(BaseModel): source: Literal["run", "notebook"]; run_id: str | None; day: date | None; author: str; at: datetime; text: str   # text cut to 200 chars
class SweepLine(BaseModel): id: str; n_runs: int; best: dict[str, Any] | None
class Digest(BaseModel):
    project: str; since: datetime; until: datetime; week: str            # ISO week "2026-W40" of `until`
    counts: dict[str, int]          # started, finished, failed, lost, killed, queued (runs created / ended in the window)
    by_owner: dict[str, int]        # runs created per created_by
    cost: CostTotals                # summed over runs ended in the window
    tasks: list[TaskChange]; notes: list[NoteItem]; sweeps: list[SweepLine]; headline: str
def build_digest(ctx: Context, project: str, *, since: datetime, until: datetime | None = None, top_notes: int = 5) -> Digest: ...
def render_digest_markdown(digest: Digest) -> str: ...
def digest_notice(digest: Digest, *, base_url: str | None) -> Notice: ...   # lines: one per task change, then one "✎ <MM-DD HH:MM> @who [[run:<id>]] <text>" per top note
def week_key(moment: datetime) -> str: ...
def digest_due(settings: DigestSettings, last_sent: str | None, now: datetime) -> str | None: ...   # the week key when now >= this week's weekday/hour in the timezone and last_sent != it
def send_digest(ctx: Context, settings: Settings, project: str, *, now: datetime, channels: list[Channel] | None = None) -> list[str]: ...   # enqueues one Notice per channel; appends the markdown to the notebook day of `until` when save_to_notebook
```
`before` is the leaderboard built from runs and scores created before `since` (same `build_leaderboard`, filtered inputs); `after` from everything up to `until`. Notes come from run `notes.md` sections and notebook entries whose `## <iso> — <author>` stamp falls in the window, newest first; the top `top_notes` travel in the Slack/email notice too, not only the notebook block. `render_digest_markdown` starts `**<week>** · <headline>` and lists task changes as `- <task> before→after ▲ · N runs` (no Markdown table). A hub that was off at the due time sends once at its next start in the same week; missed earlier weeks are not sent. A scheduled digest's window ends at the week's send time (not the tick), so a resend after a crash before `digest.json` is written has the same notice id and notebook stamp: it is queued once and saved once. A full notebook day (`NotebookTooLargeError`) skips only the notebook copy (logged); the digest is still sent and checkpointed. State `<home>/notify/digest.json` `{project: last_week_key}`. Event `digest.sent` `{project, week, channels}`.

### 1.9 `hypothex.core.storage` — report and cleanup

```python
StorageKind = Literal["run", "artifact", "pulled"]
class StorageItem(BaseModel):
    project: str; run_id: str; host: str; environment_id: str; kind: StorageKind; artifact_kind: str | None
    path: str; bytes: int; files: int; mtime: float | None; exists: bool
    archived: bool; starred: bool; status: RunStatus; ended_at: datetime | None
class StorageReport(BaseModel):
    items: list[StorageItem]; by_project: dict[str, int]; by_host: dict[str, int]; by_kind: dict[str, int]
    total_bytes: int; errors: list[dict[str, str]]; generated_at: datetime   # errors: [{host, error}]
class CleanPolicy(BaseModel, extra="forbid"):
    archived: Literal[True] = True                  # only archived runs, always (spec 9)
    older_than_days: int = Field(30, ge=0); kinds: list[str] = ["checkpoint"]   # ["*"] = every artifact kind
    projects: list[str] | None = None; hosts: list[str] | None = None; include_pulled: bool = True
class CleanItem(BaseModel): project: str; run_id: str; host: str; environment_id: str; kind: Literal["artifact", "pulled"]; artifact_kind: str | None; path: str; bytes: int; mtime: float | None; reason: str
class CleanPlan(BaseModel): plan_id: str; policy: CleanPolicy; items: list[CleanItem]; refused: list[dict[str, str]]; total_bytes: int; created_at: datetime; expires_at: datetime; created_by: str   # plan_id "cp-<8 hex>"; refused: [{path, run_id, reason}]
class CleanResult(BaseModel): plan_id: str; deleted: list[CleanItem]; skipped: list[dict[str, Any]]; freed_bytes: int; errors: list[dict[str, str]]
class CleanedArtifact(BaseModel): path: str; bytes: int; at: datetime; actor: str; plan_id: str
class CleanRefusedError(HypothexError): ...         # expired plan, confirm mismatch, unknown plan
class HostClients(Protocol):                        # api.app.HubManager satisfies it; core never imports api
    def names(self) -> list[str]: ...
    def client(self, name: str) -> EnvClient: ...   # HostUnavailableError when not connected
    def host_for_environment(self, environment_id: str) -> str | None: ...
def measure_path(path: Path) -> tuple[int, int, float | None]: ...   # (bytes, files, newest mtime); lstat walk, never follows symlinks; bytes = st_blocks*512 (st_size when absent)
def local_usage(ctx: Context, *, project: str | None = None) -> list[StorageItem]: ...   # runs whose environment_id is this env's
def storage_report(ctx: Context, hosts: HostClients | None, *, project: str | None = None, remote: bool = True) -> StorageReport: ...
def plan_clean(ctx: Context, hosts: HostClients | None, policy: CleanPolicy, *, created_by: str, settings: StorageSettings, now: datetime | None = None) -> CleanPlan: ...   # writes <home>/storage/plans/<plan_id>.json
def apply_clean(ctx: Context, hosts: HostClients | None, plan_id: str, *, confirm_bytes: int, actor: str, now: datetime | None = None) -> CleanResult: ...
def delete_artifacts(ctx: Context, items: list[CleanItem], *, actor: str, plan_id: str, older_than_days: int) -> CleanResult: ...   # env side and hub side; re-checks every item with the plan's age rule, under cleanup_lock
def cleanup_lock(layout: Layout) -> AbstractContextManager[None]: ...   # <home>/storage/.lock; held by delete_artifacts, and taken to create a run that reads an input, to star, and to (un)archive
def cleaned_artifacts(ctx: Context, record: RunRecord) -> list[CleanedArtifact]: ...   # <run_dir>/.hx/cleaned.json
```
Eligibility (all must hold, checked at plan and again at delete, both with the plan's `older_than_days`): run archived, not starred, status terminal, `ended_at <= now - older_than_days`; the path is a recorded `Artifact.path` of that run with a kind in `kinds` (or a file under the hub's `<run dir>/pulled/`); no run that fails these rules records the same path, or a path inside or above it, as an artifact (an archived run's folder artifact `/scratch/models` never takes a starred run's `/scratch/models/best.pt` with it), or reads it, or a path inside or above it, as an input (`vars["checkpoint"]`, which `control.reinfer` sets without recording an artifact: a queued or unarchived `reinfer` child keeps its parent's checkpoint, reason "used by <run_id>"); the path is not protected. Protected: `/`, the user's home, the Hypothex home, any registered repo root, any of their ancestors, inside a run folder everything except `artifacts/**` and `pulled/**`, and anything in the Hypothex home below a symlinked folder (a `pulled/` that links elsewhere is never entered or deleted through). Apply needs `confirm_bytes == plan.total_bytes` and an unexpired plan (`plan_ttl_minutes`); an item whose bytes or mtime changed is skipped ("changed since plan"). A symlink is removed, never its target. Remote items go to their host's env route `POST /api/v1/storage/delete`; an unreachable host lands in `errors` and other hosts proceed. Each deletion appends to `<run_dir>/.hx/cleaned.json` (on the host and, for mirrored runs, on the hub) and emits `run.artifacts_cleaned` `{paths, freed_bytes, plan_id}` (status unchanged). `run.yaml` is never rewritten by cleanup. `RunDetail` adds `cleaned: list[CleanedArtifact] = []`.

### 1.10 `hypothex.auth` — users, pairing, sessions, scopes

```python
# hypothex.auth.scopes
Scope = Literal["read", "launch", "admin"]          # ordered: admin ⊇ launch ⊇ read
ScopeOrPublic = Scope | Literal["public"]
def covers(held: Scope, wanted: Scope) -> bool: ...
def scopes_of(held: Scope) -> list[Scope]: ...       # "launch" -> ["read", "launch"]
# hypothex.auth.store
USER_NAME = r"^[a-z][a-z0-9_-]{0,31}$"
Client = Literal["browser", "cli", "agent", "host", "local"]
class User(BaseModel): name: str; role: Scope; created_at: datetime; created_by: str; disabled_at: datetime | None = None
class Session(BaseModel): id: str; user: str; scope: Scope; client: Client; device: str; created_at: datetime; last_seen_at: datetime; expires_at: datetime; revoked_at: datetime | None = None   # id "s_<12 hex>"
class PairingOffer(BaseModel): id: str; user: str; new_user: bool; scope: Scope; issued_by: str; created_at: datetime; expires_at: datetime; used_at: datetime | None = None; failures: int = 0   # id "p_<12 hex>"
class Principal(BaseModel): user: str; scope: Scope; session_id: str | None; client: Client; agent: str | None = None
LOCAL_OWNER = Principal(user="local", scope="admin", session_id=None, client="local")   # every request when auth is off
PAIRING_TTL_SECONDS = 300; PAIRING_MAX_FAILURES = 5; TICKET_TTL_SECONDS = 30
class AuthError(HypothexError): ...        # 401
class ScopeError(HypothexError): ...       # 403
class PairingError(HypothexError): ...     # 400, one message for unknown/expired/used/wrong secret: "pairing link invalid or expired; run hx pair again"
class AuthStore:
    def __init__(self, layout: Layout, *, now: Callable[[], datetime] = utcnow) -> None: ...   # <home>/auth/auth.db (SQLite; dir 0700, file 0600)
    def ensure_owner(self, name: str) -> User: ...                       # first admin; idempotent
    def users(self) -> list[User]: ...
    def get_user(self, name: str) -> User | None: ...
    def disable_user(self, name: str, *, by: Principal) -> User: ...     # admin; revokes every session of the user
    def create_offer(self, *, issuer: Principal, user: str, scope: Scope, ttl_seconds: int = PAIRING_TTL_SECONDS) -> tuple[PairingOffer, str]: ...   # ScopeError when scope or a new user's role exceeds issuer.scope; ttl <= 300
    def redeem(self, offer_id: str, secret: str, *, client: Client, device: str) -> tuple[Session, str]: ...   # one use; burns the offer after PAIRING_MAX_FAILURES; token "hxs_<session id>_<43-char secret>"; client "host" needs an admin offer (else PairingError, offer kept)
    def authenticate(self, token: str) -> Principal | None: ...           # sha256 of the secret, hmac.compare_digest; None if revoked/expired/user disabled; last_seen at most once per 60 s
    def sessions(self, user: str | None = None) -> list[Session]: ...
    def revoke(self, session_id: str, *, by: Principal) -> Session: ...   # own session or admin
    def mint_local(self, user: str) -> tuple[Session, str]: ...           # client "local", admin, for hx serve's own server.json (revoked at stop)
    def issue_ticket(self, principal: Principal) -> str: ...              # in memory, single use, TICKET_TTL_SECONDS
    def redeem_ticket(self, ticket: str) -> Principal | None: ...
# hypothex.auth.pairing
def pairing_url(base_url: str, offer_id: str, secret: str) -> str: ...    # f"{base_url}/pair#{offer_id}.{secret}"
def parse_pairing_url(url: str) -> tuple[str, str, str]: ...              # (base_url, offer_id, secret); ConfigError on a malformed link
def qr_text(url: str) -> str: ...                                         # segno, UTF-8 half blocks, no ANSI
# hypothex.api.auth — FastAPI glue
SESSION_COOKIE = "hx_session"; AGENT_HEADER = "X-Hypothex-Agent"; SCOPE_KEY = "x-hx-scope"
def requires(scope: ScopeOrPublic) -> Any: ...       # a Depends; stores the scope in route.openapi_extra[SCOPE_KEY]
def principal_of(request: Request | WebSocket) -> Principal: ...
class AuthGuard:                                     # ASGI; resolves cookie, Bearer, or ?ticket= (WebSocket only) to scope["hx.principal"]
    def __init__(self, app: ASGIApp, store: AuthStore, *, host_token: str | None = None) -> None: ...   # host_token = HYPOTHEX_SERVE_TOKEN -> Principal(user="hub", scope="admin", client="host")
def route_scopes(app: FastAPI) -> dict[str, ScopeOrPublic]: ...   # "METHOD path" -> declared scope for every APIRoute/WebSocketRoute; undeclared routes are absent (the unit test fails on them)
# hypothex.mcp.server
def scoped(scope: Scope) -> Callable[[F], F]: ...     # tool decorator; tool_scopes(server) -> dict[str, Scope]
def caller_token() -> str | None: ...                 # over HTTP: the caller's bearer token, else its hx_session cookie value
def tool_hub_token(fallback: Callable[[], str | None]) -> str | None: ...   # over HTTP caller_token() only (never hub_token or the local admin token); in-process/stdio fallback()
```
Auth is on when `server.auth: on` (or `hx serve --auth`). Then every HTTP route and the WebSocket need a principal except `public` routes (`/.well-known/hypothex/environment`, `POST /api/v1/auth/pair`, the UI's static files and `/pair`). Cookie: `HttpOnly; SameSite=Strict; Path=/`, plus `Secure` when `public_url` is https; lifetime `session_days` (sliding via `last_seen_at`). Bearer tokens for `cli`/`agent`/`host`. Browsers open `/api/v1/ws?ticket=<t>` after `POST /api/v1/auth/ws-ticket`; long-lived tokens never appear in a URL. An open WebSocket re-checks its session every 30 s and closes with code `4401` when it is revoked or expired. With auth off, every request runs as `LOCAL_OWNER` and phase 1–2 guards (`OriginGuard`, `TrustedHostMiddleware`, optional `TokenGuard`) are unchanged. `hx serve` with auth on: `ensure_owner($USER lowercased, else "owner")` on first start, `mint_local` writes the local token into `<home>/serve/server.json` (0600) so `resolve_hub_token` keeps working for the CLI on that machine. A non-loopback bind requires auth on or `HYPOTHEX_SERVE_TOKEN` (the existing refusal text names both).

### 1.11 Postgres server mode (`hypothex.core.index`, `hypothex.core.migrations`)

```python
class Index:
    def __init__(self, target: Path | str, *, password: SecretStr | None = None) -> None: ...   # Path -> SQLite (unchanged); "postgresql+psycopg://..." -> Postgres engine (pool_pre_ping)
    dialect: Literal["sqlite", "postgresql"]
def upsert(session: Session, model: type[Base], values: dict[str, Any], keys: list[str]) -> None: ...   # dialect insert ... on conflict; replaces every sqlite_insert call
def open_index(layout: Layout, settings: ServerSettings) -> Index: ...   # Context.open uses it; IndexUnavailableError when Postgres does not answer (URL printed without password)
class IndexUnavailableError(HypothexError): ...   # API 503
class IndexSchemaError(ConfigError): ...          # Postgres revision != head: "run hx db upgrade"
def repair_pending(index: Index, store: RunStore) -> list[str]: ...   # re-index, from files, the runs whose index write failed after their files were written (Index.pending, <home>/index-pending.txt); Context.open and the server's 30 s repair loop call it. Claim: the journal moves to index-pending.txt.<8 hex>.claim; every claim file (a crashed process's too) is read and removed only after its runs are indexed; each run is re-read and indexed under its run_lock (the one Context.update_run holds)
# hypothex.core.migrations (Alembic; shipped in the wheel)
def alembic_config(index_url: str, password: SecretStr | None) -> alembic.config.Config: ...
def upgrade(layout: Layout, settings: ServerSettings) -> str: ...   # returns the new head revision
def current(layout: Layout, settings: ServerSettings) -> str | None: ...
```
SQLite keeps the disposable schema-version rebuild (no migrations needed). Postgres uses Alembic: revision `0001_phase3` creates exactly `Base.metadata` at `SCHEMA_VERSION = 3`, and a unit test asserts autogenerate finds no diff between the head and `Base.metadata`. Only the index moves: the event log, command receipts, `auth.db`, and all files stay under the server's home. Dependencies: `alembic` (main), optional extra `server = ["psycopg[binary]>=3.2"]`; `Context.open` reads `config.yaml` for `index_url`, so an invalid `config.yaml` stops every `hx` command on that home (fail closed: never a silent fallback to SQLite or to auth off; `docs/team.rst` says so).

### 1.12 Collaborators: what a collaborator sees

A collaborator's principal reads every project, task, run, sweep, host, and notebook of the hub (one lab, a few people; no per-project ACLs). `launch` lets them launch on any configured host, rerun, tag, star, note, edit notebooks, and export; `OWNER_ACTIONS` follow 1.3; storage, notification settings, users, and other users' sessions need `admin`. The Overview, runs list, and run page show `owner` (`@name`). `GET /api/v1/runs?owner=me` filters to the caller (with auth off runs have no owner, and `me` filters nothing; `hx runs --owner me` does the same).

### 1.13 Tailscale and `route: url` hosts (`hypothex.remote.tailscale`, `hypothex.remote.config`, `hypothex.remote.hub`)

```python
# hypothex.remote.tailscale
class TailscaleError(HypothexError): ...
def tailscale_bin() -> str: ...                       # $HYPOTHEX_TAILSCALE or "tailscale"
def tailscale_dns_name(*, timeout: float = 10) -> str: ...   # `tailscale status --json` -> Self.DNSName without the trailing dot; TailscaleError naming `tailscale up` when logged out
def serve_https(port: int, *, https_port: int = 443) -> str: ...   # `tailscale serve --bg --https=<https_port> http://127.0.0.1:<port>`; returns "https://<dns>" (":<https_port>" when not 443)
def unserve(https_port: int = 443) -> None: ...       # `tailscale serve --https=<https_port> off`
# hypothex.remote.config
class HostSpec(...):   # add
    token_env: str | None = Field(None, pattern=ENV_NAME)    # route url: variable holding the env server's bearer token
HOST_TOKENS_FILE = "auth/host-tokens.json"             # <hub home>/auth/host-tokens.json, 0600: {host: {url, token}} from `hx hosts pair`
def host_token(layout: Layout, name: str, spec: HostSpec) -> SecretStr | None: ...   # host-tokens.json first (only while spec.url is the origin it was paired at), then resolve_secret(token_env)
```
`hx serve --tailscale` requires auth on (else `ConfigError` "tailscale needs server.auth: on"), binds `127.0.0.1`, calls `serve_https`, uses the returned URL as `public_url` for this process (allowed `Host`/`Origin`, `Secure` cookie, pairing links), and calls `unserve` at shutdown only for the mapping it set. A lab server is an env server started with `server.auth: on` (any reachable bind, e.g. behind `tailscale serve`); its owner runs `hx pair --client host --scope admin` there (`--client host` refuses any other scope) and the hub runs `hx hosts pair <name> <pairing-url>`, which refuses a link whose origin is not the host's `url` and stores the token bound to that origin. The hub supervisor sends `host_token(...)` for `route: url`; a 401/403 puts the host in `error` with message `auth failed: hx hosts pair <name> <pairing-url>` and stops retrying until `connect` (existing rule).

### 1.14 SDK (`hypothex.sdk`)

```python
class Run:     # add
    def log_cost(self, usd: float, tokens_in: int = 0, tokens_out: int = 0, example_id: str | None = None) -> None: ...   # = log_usage(usd=, tokens_in=, tokens_out=, example_id=); spec 9's "log_cost(usd=..., tokens=...)" with tokens split in/out like usage.jsonl
class NoopRun: # add the same no-op
```

## 2. Data files and schemas

| Path | Owner | Format | Mode | Notes |
|---|---|---|---|---|
| `<home>/config.yaml` | hub, env servers | YAML, `Settings` | 0600 | secrets only as env var names |
| `<home>/secrets.env` | user | `KEY=VALUE` lines | must be 0600, own uid | optional; `resolve_secret` fallback |
| `<home>/auth/auth.db` | `hx serve` | SQLite: `users`, `sessions`, `offers` | dir 0700, file 0600 | state, not index: `hx reindex` never touches it; secrets stored as sha256 |
| `<home>/auth/host-tokens.json` | hub | `{host: {url, token}}` | 0600 | from `hx hosts pair`; sent only to `url`'s origin |
| `<home>/auth/hub-tokens.json` | CLI client | `{hub_url: {token, user, scope, session_id}}` | 0600 | from `hx login`; read by `resolve_hub_token` after `$HYPOTHEX_HUB_TOKEN` |
| `<home>/serve/server.json` | `hx serve` | existing + `token` = local session token when auth on | 0600 | unchanged shape |
| `<home>/notify/cursor.json` | notifier | `{last_sequence}` | 0600 | |
| `<home>/notify/outbox/<id>.<channel>.json` | notifier | `OutboxEntry` | 0600 | atomic rewrite per state change |
| `<home>/notify/sent.jsonl` | notifier | `OutboxEntry` (final) lines | 0600 | `recent()` reads its tail; outbox file removed after append |
| `<home>/notify/digest.json` | notifier | `{project: "YYYY-Www"}` | 0600 | |
| `<home>/storage/plans/<plan_id>.json` | hub | `CleanPlan` | 0600 | expired plans pruned on the next plan |
| `<store>/<project>/notebook/YYYY-MM-DD.md` | hub | Markdown; entries `## <iso> — <author>` | 0644 | files of record |
| `<run_dir>/.hx/cleaned.json` | env server, hub | list of `CleanedArtifact` | 0644 | reserved `.hx/` (never mirrored) |
| `hypothex.yaml` `tasks.<t>.baselines` | project repo | list of `BaselineSpec` | | validated by `hx validate` |
| `run.yaml` | | adds `owner` | | additive; old files load (`owner: null`) |
| index | | `runs.owner` column, `SCHEMA_VERSION = 3` | | SQLite rebuilds; Postgres via Alembic |

New event types: `notebook.updated`, `run.artifacts_cleaned`, `storage.plan_created` `{plan_id, total_bytes, n_items}`, `storage.cleaned` `{plan_id, freed_bytes, n_deleted, n_skipped}`, `notify.sent`, `notify.failed`, `digest.sent`, `auth.session_created` / `auth.session_revoked` `{session_id, user, client}` (never a token or secret). The WebSocket sends `auth.*` and `notify.*` events only to `admin` principals.

## 3. HTTP API additions

Every route (old and new) declares a scope; the table gives it for new routes. Every `command_id` (old and new routes) is stored under `api.auth.command_key(conn, command_id)` = `<user>|<scope>|<METHOD> <path>|<command_id>`, never raw: `EventLog.run_once` returns a stored result without running the route's checks, so only the same caller retrying the same route and target gets it (a retry with an edited body still gets the first result, as in phase 1). A hub sends its key as the `command_id` it forwards, so a host's receipts are per hub caller too. Existing routes: `GET` → `read`; launch, rerun, reinfer, reeval, stop, tags, star, archive, notes, views PUT/DELETE, sweeps POST/cancel/extend, pull → `launch` (+ `require_act` for `OWNER_ACTIONS`); hosts reload/connect/disconnect, `POST /api/v1/hosts/{host}/runs` → `launch`; env-only routes (`files`, `entry`, `gpus`, `queue`, `slurm`) → `read`; `/api/v1/ws` → `read`; `/mcp` → `read` at the mount, then per-tool scopes.

| Method | Path | Scope | Body / query | Returns |
|---|---|---|---|---|
| POST | `/api/v1/auth/pair` | public | `{offer_id, secret, device, client: "browser"\|"cli"\|"agent"\|"host"}` | browser: `Set-Cookie` + `{user, scope, scopes, session_id}`; others: `{token, user, scope, scopes, session_id}`; 400 `PairingError`; 429 after 10 failed attempts/min per client address (successes are not counted; behind `tailscale serve` the address is `Tailscale-User-Login`, else the proxy's `X-Forwarded-For` hop) |
| GET | `/api/v1/auth/me` | read | | `{user, scope, scopes, session_id, client, auth: "on"\|"off", public_url}` (auth off: `local`, `admin`) |
| POST | `/api/v1/auth/logout` | read | | `{ok}`; revokes the calling session, clears the cookie |
| POST | `/api/v1/auth/ws-ticket` | read | | `{ticket, expires_in: 30}` |
| POST | `/api/v1/auth/pairings` | read (+ scope rule) | `{user?, new_user?: bool, scope, ttl_seconds?: <=300, client_hint?}` | `{offer_id, url, expires_at, qr}` (`qr` = `qr_text`); 403 when it would widen scope; 400 when auth is off |
| GET | `/api/v1/auth/sessions` | read | `?user=` (admin for others) | `list[Session]` (own; all for admin) |
| POST | `/api/v1/auth/sessions/{session_id}/revoke` | read (own) / admin | `{command_id?}` | `Session` |
| GET | `/api/v1/auth/users` | admin | | `list[User]` |
| POST | `/api/v1/auth/users/{name}/disable` | admin | `{command_id?}` | `User` |
| GET | `/api/v1/runs` | read | phase 2 filters + `owner?` (`me` = caller) | `list[RunRecord]` |
| GET | `/api/v1/projects/{project}/notebook` | read | | `[{day, bytes, entries}]` |
| GET | `/api/v1/projects/{project}/notebook/{day}` | read | `{day}` = `YYYY-MM-DD` or `today` (the hub's date, 1.4) | `NotebookDay` |
| POST | `/api/v1/projects/{project}/notebook/{day}` | launch | `{text, command_id?}` (author = principal) | `NotebookDay` (append) |
| PUT | `/api/v1/projects/{project}/notebook/{day}` | launch | `{text, base_hash, command_id?}` | `NotebookDay`; 409 `{error, type: "NotebookConflictError", current}`; 413 |
| GET | `/api/v1/tasks/{project}/{task}/export` | read | `format, metrics?, noise?, digits?, percent?, top?, groups?, baselines?, caption?, label?, standalone?` | `text/plain; charset=utf-8` (LaTeX, Markdown) or `text/csv`; `Content-Disposition: attachment; filename="<task>.<tex\|md\|csv>"` |
| GET | `/api/v1/compare/export` | read | `run_ids` (comma list, 2–20), same options | as above, filename `compare.<ext>` |
| GET | `/api/v1/projects/{project}/digest` | read | `since?` (ISO, default now−7 d), `until?` | `Digest` |
| POST | `/api/v1/projects/{project}/digest/send` | admin | `{since?, channels?, command_id?}` | `{channels: list[str], notebook_day: str \| null}` |
| GET | `/api/v1/notify` | admin | | `{channels: {slack: {configured, env, set}, email: {configured, env, set, host, to}}, projects: dict[str, ProjectRule], default: ProjectRule \| null, digest: DigestSettings, recent: list[OutboxEntry]}` (`set`: the variable has a value; the value is never returned) |
| POST | `/api/v1/notify/test` | admin | `{channel, command_id?}` | `{ok: bool, error_class: str \| null}` |
| GET | `/api/v1/storage` | admin | `project?, remote?: bool = true` | `StorageReport` |
| POST | `/api/v1/storage/plan` | admin | `CleanPolicy` + `{command_id?}` | `CleanPlan` |
| POST | `/api/v1/storage/plans/{plan_id}/apply` | admin | `{confirm_bytes, command_id?}` | `CleanResult`; 400 `CleanRefusedError` |
| GET | `/api/v1/storage/usage` *env* | admin | `project?` | `list[StorageItem]` (this environment's runs) |
| POST | `/api/v1/storage/delete` *env* | admin | `{items: list[CleanItem], plan_id, actor, older_than_days, command_id?}` (the plan's policy age, rechecked on the host) | `CleanResult` |
| GET | `/api/v1/runs/{id}` | read | | adds `cleaned: list[CleanedArtifact]`, `record.owner` |
| GET | `/api/v1/tasks/{project}/{task}/leaderboard` | read | | adds `baselines: list[BaselineRow]` |

Errors keep `{error, type}`: `AuthError` 401, `ScopeError` 403, `PairingError` 400, `NotebookConflictError` 409, `NotebookTooLargeError` 413, `CleanRefusedError` 400, `IndexUnavailableError` 503, `TailscaleError` and `ChannelError` never reach the API (logged, redacted). A 401 response carries `WWW-Authenticate: Bearer realm="hypothex"`.

## 4. CLI additions (`--json` everywhere)

| Command | Effect |
|---|---|
| `hx export <task> [-p P] [--format latex\|markdown\|csv] [--metrics a,b] [--noise both\|seed\|test\|none] [--digits 3] [--percent] [--top N] [--groups g1,g2] [--no-baselines] [--caption C] [--label L] [--standalone] [-o FILE]` | prints the table (or writes `FILE`); `--json` returns `{format, text, table: ExportTable}` |
| `hx export --runs a,b[,c…] [same options]` | compare table |
| `hx note <run_id> <text>` | unchanged |
| `hx note --project P <text> [--day YYYY-MM-DD]` | notebook entry (spec 9) |
| `hx notebook list -p P` / `hx notebook show -p P [--day D]` | days / one day with run chips as `run_id status primary` |
| `hx digest [-p P] [--since 7d] [--send] [--channels slack,email]` | prints the digest (all projects when no `-p`); `--send` enqueues and saves to the notebook |
| `hx notify status` / `hx notify test slack\|email` | channel status and recent sends; a test notice through the hub (or directly when no hub runs) |
| `hx storage report [-p P] [--local-only]` | bytes by project, host, kind, and the 20 largest items |
| `hx storage clean --archived [--older-than 30d] [--kind checkpoint …\|--all-kinds] [-p P] [--host H] [--no-pulled] [--dry-run]` | always a dry run: prints the plan id, items, total; refuses without `--archived` |
| `hx storage clean --apply <plan_id> [--yes]` | deletes; asks to type the total shown unless `--yes`; prints freed bytes |
| `hx pair [--user NAME] [--new-user] [--scope read\|launch\|admin] [--client browser\|cli\|host] [--ttl 300] [--url HUB]` | prints the pairing URL and a QR code; default user = a new collaborator only with `--new-user`, else the caller |
| `hx login <pairing-url> [--device NAME]` / `hx logout [--hub URL]` | redeems as `cli` (or `agent` when `HYPOTHEX_AGENT` is set), stores the token in `hub-tokens.json` / revokes and forgets it |
| `hx whoami` | `GET /api/v1/auth/me` |
| `hx sessions list [--all]` / `hx sessions revoke <id>` | |
| `hx users list` / `hx users disable <name>` | admin |
| `hx hosts add <name> --url URL [--token-env VAR \| --pair PAIRING_URL] [--slurm …]` | phase 2 command, new options for `route: url` |
| `hx hosts pair <name> <pairing-url>` | redeems as `host`, writes `host-tokens.json`, reconnects the host |
| `hx serve [--auth] [--tailscale] [--public-url URL]` | `--auth` = `server.auth: on` for this process |
| `hx db upgrade` / `hx db current` | Alembic on the Postgres index (`ConfigError` on SQLite: "the SQLite index needs no migrations") |
| `hx runs --owner me\|NAME` | filter |
| `hx demo --with-team` (hidden) | seeds the phase 3 fixtures for the UI (section 10) |

The CLI sends `X-Hypothex-Agent` when `HYPOTHEX_AGENT` is set. Duration flags accept `Nd`, `Nh`, `Nw`.

## 5. MCP additions

Tools (with scope): `export_table(task, format="markdown", project=None, metrics=None, noise="both", digits=3) -> {text}` (read); `export_compare(run_ids, format="markdown") -> {text}` (read); `get_baselines(task, project=None) -> {baselines}` (read); `get_notebook(project, day=None) -> NotebookDay` (read); `add_notebook_entry(project, text, agent="mcp") -> NotebookDay` (launch; author `agent:<agent>@<user>`); `get_digest(project, days=7) -> Digest` (read); `storage_report(project=None) -> StorageReport` (admin); `plan_storage_clean(older_than_days=30, kinds=None, project=None) -> CleanPlan` (admin; dry run only); `whoami() -> {user, scope}` (read). There is no MCP tool that applies a cleanup, sends notifications, or manages users or sessions (agents never delete; skill rule 6). Every tool, old and new, carries `@scoped(...)`: list/get tools `read`; launch/rerun/reinfer/reevaluate/stop/add_note/tag/add_view/sweep tools/pull `launch`. Over `/mcp` with auth on, the caller's principal (bearer or cookie) applies; stdio `hx mcp` runs as `LOCAL_OWNER`. Over HTTP a tool's own hub calls carry only the caller's credential (`tool_hub_token`), never `hub_token` or the local admin token; tools apply the HTTP ownership rules (1.3): `stop_run` on a local run and `cancel_sweep` on a local sweep call `require_act` first. `skills/hypothex/SKILL.md` gains: export a table for a paper, write findings to the notebook, never apply storage cleanup.

## 6. Config keys (full `config.yaml`)

```yaml
server:
  auth: off                      # off | on
  public_url: null               # https://hub.tail1234.ts.net (pairing links, Host/Origin allow-list, Secure cookie)
  session_days: 90
  index_url: null                # postgresql+psycopg://hx@db.lab:5432/hypothex  (password: $HYPOTHEX_INDEX_PASSWORD)
  index_password_env: HYPOTHEX_INDEX_PASSWORD
notify:
  slack: {webhook_env: HYPOTHEX_SLACK_WEBHOOK}
  email: {host: smtp.lab.org, port: 587, security: starttls, username: sv, password_env: HYPOTHEX_SMTP_PASSWORD,
          sender: hx@lab.org, to: [sv@lab.org], timeout: 20}
  projects:
    deepretro: {events: [finished, failed, lost], channels: [slack, email], min_seconds: 300, fold_sweeps: true}
  default: null                  # rule for unlisted projects; null = opt-in only
  max_age_hours: 24
digest: {enabled: true, weekday: mon, hour: 9, timezone: Europe/London, channels: [slack], projects: all,
         save_to_notebook: true, top_notes: 5}
storage: {older_than_days: 30, kinds: [checkpoint], plan_ttl_minutes: 60}
```
`environments.yaml` adds `token_env` per `route: url` host. `hypothex.yaml` adds `tasks.<t>.baselines`. Env vars: `HYPOTHEX_SLACK_WEBHOOK`, `HYPOTHEX_SMTP_PASSWORD`, `HYPOTHEX_INDEX_PASSWORD` (names configurable), `HYPOTHEX_TAILSCALE` (binary override, tests), existing `HYPOTHEX_SERVE_TOKEN`, `HYPOTHEX_HUB_TOKEN`, `HYPOTHEX_AGENT`.

## 7. Security model

- **Secrets** (Slack webhook URL, SMTP password, Postgres password, session and pairing secrets, host tokens) live only in environment variables, `secrets.env` (0600, own uid), `auth.db` (hashed), `host-tokens.json`/`hub-tokens.json`/`server.json` (0600). They never appear in `config.yaml`, run folders, `env/` captures, the event log, the index, API responses, CLI `--json` output, log lines, exception messages, notices, or the outbox. Mechanisms: `SecretStr` end to end; `redact()` on every error string that leaves `hypothex.notify` and on stderr lines quoted in notices; `ENV_ALLOWLIST` stays an allow-list and a test asserts no `*_WEBHOOK`, `*_PASSWORD`, `*_TOKEN`, `*_SECRET` name is ever on it; `hx serve` pops `HYPOTHEX_SERVE_TOKEN` (existing) and strips the configured secret variable names, `HYPOTHEX_SERVE_TOKEN`, `HYPOTHEX_HUB_TOKEN`, and every host's `token_env` from the environment it passes to run subprocesses.
- **Webhooks** must be `https://` unless the host is loopback (tests). SMTP uses STARTTLS or SSL by default; `security: none` with a `username` is refused (`ConfigError`) unless `host` is loopback, so a password never crosses the network in clear text.
- **Authentication**: sessions from one-time pairing only (no passwords). Pairing secret: 32 random bytes in the URL fragment (never sent in an HTTP request line or logged), 5 min, one use, burned after 5 wrong secrets; session secret: 32 random bytes, stored as sha256, compared in constant time. Cookies `HttpOnly; SameSite=Strict` (+`Secure` on https). Writes from browsers also pass `OriginGuard` with `public_url`'s host allowed. WebSocket: single-use 30 s tickets; re-check every 30 s.
- **Execution**: a run executes as the Unix user of the machine that runs it and can read everything that user can. So a run on the serving machine needs `admin` (1.3), and a shared host should run under its own account, not the hub owner's: everyone who launches there shares that account (and the host's own `server.json`), which the hub's ownership rules guard at the API, not the OS. `docs/team.rst` says so.
- **Authorization**: scopes `read ⊂ launch ⊂ admin`; every API route, the WebSocket, and every MCP tool declares one (unit tests fail on a missing declaration); a principal can issue pairings only up to its own scope; ownership rules in 1.3; body fields `created_by`/`owner`/`author` are overwritten from the principal when auth is on.
- **Machine-to-machine**: ssh-bootstrapped env servers keep phase 2's per-start `TokenGuard` token; `route: url` hosts use a paired `host` session or `token_env`. The hub's principal on a host is `admin` (it forwards for many users and enforces their scopes itself before forwarding).
- **Network**: hubs bind `127.0.0.1` unless auth is on or a serve token is set; Tailscale access via `tailscale serve` (HTTPS terminated by tailscaled), no custom relay; `TrustedHostMiddleware` accepts `public_url`'s host.
- **Destructive actions**: storage deletion is admin-only, plan-then-apply with exact byte confirmation, re-validated per item, never deletes a run folder's records, never follows symlinks, never a protected path, never through MCP.

## 8. Failure modes (each has a test in the plan that owns the code)

1. Slack answers 429 `Retry-After: 7` → next attempt after max(7 s, `RETRY_DELAYS[n]`); after 3 failed attempts the entry is `failed`; one notice per (run, status), never duplicated by retries.
2. Webhook revoked (404/410) or SMTP auth fails (535) → permanent failure at once, `error_class` visible in `hx notify status` and Settings; the URL and password appear nowhere (log, outbox, events, API).
3. Secret variable unset → entries `skipped` with `error_class` `unset:<VAR NAME>`; the channel shows `○ unset`.
4. Hub crashes after the send but before recording it → entry `sending` is retried after 60 s (at least once; documented). Crash before the send → sent once. Crash after `sent.jsonl` records it but before the outbox file is removed → dropped at the next delivery, never resent.
5. A remote run ends while the hub is off → replayed `mirror.run_updated` notifies late; older than `max_age_hours` → no notice.
6. A 200-run sweep finishes → one sweep notice (`fold_sweeps`), failures counted in it, also when its last run ends between two event batches of one scan; a short first run that ends while later launches are still being issued → nothing until the last run ends (never `1/1`); a mirrored run of another hub's sweep with the same id → its own run notice.
7. `secrets.env` group-readable → `hx serve` refuses at start naming `chmod 600 <path>`; `config.yaml` with a literal `webhook:` → `ConfigError` with the `_env` hint, value not echoed.
8. Export: missing scores → `—`; n=1 → no ±, `¹`; identical seeds → `◇×n`; no per-example data → no CI; labels with `_ & % $ #` → escaped; empty leaderboard → header-only table, exit 0.
9. Storage: artifact rewritten after the plan → skipped "changed since plan"; run unarchived or starred after the plan → skipped; plan older than `plan_ttl_minutes` or `confirm_bytes` wrong → 400, nothing deleted; host unreachable → its items in `errors`, others deleted; a checkpoint shared with an unarchived reinfer child → refused "used by <id>"; an artifact path equal to `/`, home, the repo, or the Hypothex home → refused "protected"; a symlink artifact → the link is removed, the target kept; a `pulled/` folder that is a symlink → never entered, its target never listed or deleted; a run that reads the path (a `reinfer` child) created, or a run starred or unarchived, during an apply → waits for the apply's lock, so it is never between a check and a deletion; a user of the path that ended inside the policy's age (an archived child that ended yesterday under 30 days) → skipped `used by <id>` at apply, as at plan; an archived run's folder artifact that holds a starred (or otherwise kept) run's file → refused, or skipped at apply, `used by <id>`.
10. Pairing link reused, expired, or with a wrong secret → the same 400 message; 5 wrong secrets burn the offer; 10 failed attempts/min per address → 429.
11. Session revoked or user disabled while the UI is open → next HTTP call 401 (UI shows the 401 gate), open WebSocket closed with `4401` within 30 s.
12. A collaborator posts `created_by: "human:sv"` or `owner: "sv"` → ignored; the run records their own identity. A collaborator stops the owner's run → 403; their own → ok. A `launch` collaborator starts a run on the hub's own machine (HTTP or MCP) → 403 `runs on this machine need admin; launch on a host`; on a host → ok. An agent acting through a remote MCP call → `agent:<agent>@<user>` (the tool sends `X-Hypothex-Agent`).
13. Postgres down at start → `IndexUnavailableError` naming the host (no password, in `user:pw@` or `?password=`), `hx serve` exits 1 and leaves no Tailscale mapping or local session behind; down mid-request → 503, run files still written (file first), and the run's id is noted so `repair_pending` re-indexes it (a stale archive, star, status, or score) once the index answers, while `repair_index_gaps` adds runs with no row; schema behind → `IndexSchemaError` "run hx db upgrade". `index_url` with `?password=` → refused like `user:pw@`.
14. `tailscale` missing or logged out → `TailscaleError` naming `tailscale up`; `hx serve --tailscale` with auth off → refused; a second `hx serve` on a home a live server owns → refused before it touches the running server's mapping or session.
15. Hub off at the digest hour → sent once at the next start that week; several missed weeks → only the current one; a crash after the digest is queued but before `digest.json` is written → the resend has the same notice id and notebook stamp: queued once, saved once.
16. Two people edit one notebook day → the second save gets 409 with the current text; appends never conflict (project lock); a day cleared by an empty save while it is read or listed → reads as empty, never a 500.
17. A host rejects the hub's token (re-installed lab server) → host state `error`, message `auth failed: hx hosts pair <name> <pairing-url>`, no retry loop.

## 9. Testing strategy (fakes only)

- `tests/fakes/smtp.py`: `FakeSmtp` on `127.0.0.1:0` built on `aiosmtpd` (`uv add --dev aiosmtpd trustme`): records `(mail_from, rcpt_tos, message)`, supports `AUTH PLAIN/LOGIN` with a configured password, STARTTLS and implicit SSL with a `trustme` CA (the client trusts it through an injected `ssl.SSLContext`), and scripted failures (`421` on connect, `535` auth, `451` on DATA, a stall for timeouts).
- `tests/fakes/webhook.py`: `FakeWebhook` (`ThreadingHTTPServer` on `127.0.0.1:0`, URL `http://127.0.0.1:<port>/services/T000/B000/<secret>`): records requests, plays a script of responses (`200`, `429` + `Retry-After`, `500`, `404`, a stall).
- `tests/fakes/tailscale`: a `sh` script used through `HYPOTHEX_TAILSCALE`, state in `HYPOTHEX_FAKE_TAILSCALE_STATE` (JSON: logged in, DNS name, serve mappings); records every call.
- Network guard: `pytest_configure` and an autouse fixture in `tests/conftest.py` patch `socket.socket.connect`/`connect_ex` and `socket.create_connection` to refuse non-loopback addresses (`tests/test_isolation.py` proves it for `httpx`, `smtplib`, and `psycopg`); `HYPOTHEX_SLACK_WEBHOOK`, `HYPOTHEX_SMTP_PASSWORD`, `HYPOTHEX_INDEX_PASSWORD`, `HYPOTHEX_HUB_TOKEN` are removed for every test; `HYPOTHEX_TAILSCALE` points at a refusing stub unless a test installs the fake.
- Fake clock: `AuthStore(now=)`, `Notifier(now=)`, `plan_clean(now=)`, `digest_due(now)`; no `sleep` in tests (retry delays checked through `next_at`).
- Secret-leak tests: after a successful send, each failure class, `hx notify status --json`, `GET /api/v1/notify`, and a failing `hx serve` start, scan every file under the home (bytes), all event payloads, the outbox, captured logs at DEBUG, CLI output, and raised messages for the webhook secret, the SMTP password, session tokens, and pairing secrets: zero hits.
- Scope tests: `route_scopes(create_app(...))` has an entry for every `APIRoute` and `WebSocketRoute`; `tool_scopes(build_server(...))` for every MCP tool; a table-driven test calls each route as `read`, `launch`, `admin` principals and checks 403/2xx against the declared scope.
- In-process hub + env servers (`route: url`, fake GPUs) for remote storage reports, remote deletes, ownership forwarding, and host pairing.
- Export golden files: `tests/core/golden/export/<case>.{tex,md,csv}` for the toy task, a training task with n=1 and identical seeds, a task with baselines and a version mismatch, and a compare table; regenerated only with `HX_UPDATE_GOLDEN=1`.
- Postgres: `tests/docker/test_postgres_index.py` (marker `docker`, `postgres:16-alpine` on a random port, throwaway password): `hx db upgrade`, reindex equivalence (index built live == rebuilt from files, same queries as SQLite), concurrent upserts. Unit test: Alembic head vs `Base.metadata` on a temp SQLite file shows no diff.
- UI: `bun test` with a fake `fetch` for every new component; Playwright smoke against `hx demo --with-team` in light and dark: pair through `/pair`, Settings, Storage dry-run → apply, Notebook edit + conflict, Task export menu, baseline rows, run owner and cleaned artifact, 401 gate.

## 10. Frontend

Additions in `ui/` (same stack and rules as phase 1b and 2; terse: numbers and glyphs, no prose; labels of one or two words; explanations only in tooltips):
- `ui/src/api/models.ts`: `Scope`, `Principal` (`/auth/me`), `SessionRow`, `UserRow`, `PairingOffer` (`{offer_id, url, expires_at, qr}`), `NotifyStatus`, `OutboxEntry`, `ProjectRule`, `Digest`, `TaskChange`, `NotebookDay`, `RunChip`, `BaselineRow`, `StorageReport`, `StorageItem`, `CleanPolicy`, `CleanPlan`, `CleanResult`, `CleanedArtifact`; `RunRecord.owner?`, `RunDetail.cleaned?`, `Leaderboard.baselines?` (optional: older hubs).
- `ui/src/api/client.ts`: every request `credentials: "same-origin"`; a 401 sets the app's auth state to `locked`; `eventsUrl()` becomes `async eventsUrl(): Promise<string>` that fetches a ticket when `/auth/me` says `auth: "on"`; close code `4401` → `locked`.
- Routes: `/pair` (`ui/src/pages/Pair.tsx`), `/settings` (`ui/src/pages/Settings.tsx`), `/storage` (`ui/src/pages/Storage.tsx`), `/n/:project` and `/n/:project/:day` (`ui/src/pages/Notebook.tsx`). `/pair` renders without the header and without `/auth/me`.
- Header: right side `notebook` (last project), `storage` (admin only), `⚙` settings, user chip `@user` with scope glyph (`r`/`l`/`a`); auth off: no chip.
- Task page: `export ▾` in the leaderboard panel title (LaTeX / Markdown / CSV; each Copy and ↓ download; options digits and noise in the menu); baseline rows in the leaderboard (dashed rule above, `◆ name`, value, `↗` source link, `≠v2` badge (our metric version; the tooltip says the paper used another) when `version_match` is false, never in the best band).
- Run page: `@owner` in the status line; cleaned artifacts in "where everything is" struck through with `✕ <date> <bytes>`.
- Overview: `@owner` on running and recent rows (`TimelineItem`, `IdeaRow`, `FailureRow` gain `owner: str | None = None`; `IdeaRow.owner` is its first run's, like `created_by`); a `mine` toggle filters by `owner=me` (hidden when auth off).
- `ui/src/pages/components/AuthGate.tsx`: on `locked`, one line `401 · pair this device: hx pair` plus a copy button for the command.
- Live updates: `notebook.updated` invalidates notebook queries; `run.artifacts_cleaned`/`storage.*` invalidate storage, runs, run detail; `notify.*` invalidates the notify status; `auth.*` invalidates sessions and users.

### 10.1 Mockup requirements (`docs/mockups/phase3/`: `index.html`, `data.js`, `shot-<screen>-{light,dark}.png`)

Made before the frontend plan, same design system as `ui-v4`/`phase2` (lettered panels, hairlines, no cards, numbers right-aligned, monospace only for paths, commands, tokens). Each screen shows real-looking numbers from `data.js`; no lorem ipsum, no help text.
1. **pair** — three states: ready (device field prefilled `MacBook`, `pair` button, the hub and the offer id `p_3f9a…`), done (`✓ alice · launch`), invalid (`✗ link invalid or expired`). Centred, no header. (User, scope and countdown are not shown before redeeming: the link carries only `<offer>.<secret>`, and no public route reads an offer; see "Changes after review round 1".)
2. **settings** (admin) — headline `3 users · 5 sessions · slack ● email ○`; a sessions (device, user, client, scope, last seen `2m`, `revoke ×`), b users (name, role, sessions, `disable`), c add device (scope picker, user picker / `+ new`, then QR + URL + countdown `4:59`), d notifications (channels `● set`/`○ unset` with variable name in tooltip, per-project rules table: project, events as glyphs `✓ ✗ ? ⊘`, channels, `min`, recent sends: time, run, channel, `✓/✗/…`, attempts, error class; `test` buttons). Collaborator view: only a (own sessions) and c limited to own scope.
3. **storage** — headline `1.84 TB · 412 GB cleanable (archived, >30d)`; a bytes by project (horizontal bars, local vs remote split), b bytes by host, c largest items table (run, host, kind, path, bytes, age, `★`/`archived` glyphs), d clean: `older than [30] d`, kinds chips, `dry run` button → plan table (run, host, path, bytes, reason) with refused rows greyed (reason `protected`, `used by 01J…`), total, `apply` disabled until a plan exists; confirm dialog `delete 412.3 GB · 37 paths · 3 hosts` (37 = the 6 listed plus `+31 more`; a `CleanItem` is a path, with no file count) with the number typed back; result `freed 409.8 GB · 2 skipped`.
4. **notebook** — left: day list (`2026-10-04 · 3`), right: rendered Markdown with run chips (`01J8…a1b2 ✓ 0.913`, unknown id as `? 01J…`), entry stamps `09:14 @alice`, `+ entry` box, `edit` → textarea, `save`/`discard`; conflict state: `409 · changed by @sv 1m` with a side-by-side diff and `use theirs`/`keep mine`. Weekly summary entry shown as one block with counts row `▲12 ✓9 ✗2 ?1 · 41.2 GPU-h $86.5` and task changes `uspto50k-topk 0.598→0.613 ▲`.
5. **task export + baselines** — the leaderboard with two baseline rows (one with `≠v2`), the `export ▾` menu open showing LaTeX preview (first 6 lines, monospace), Copy and ↓ buttons, digits `3`, noise `both`.
6. **run** — owner `@alice` in the status line, one cleaned checkpoint struck through `✕ 2026-10-04 4.2 GB`.
7. **401 gate** — single line and command chip, both modes.

## 11. Plans and done criteria

- `docs/superpowers/plans/2026-10-04-hypothex-phase3-backend.md` — sections 1–9: settings and secrets, ownership fields, notebook, baselines, export, notify (+ fakes), digest, storage (+ env routes), auth (store, pairing, guard, scopes on every route and tool, WS tickets), Postgres + Alembic (+ Docker test), Tailscale + `route: url` pairing, SDK `log_cost`, CLI, MCP, skill, `docs/` pages (`team.rst`, `notifications.rst`, `export.rst`, `storage.rst`), `hx demo --with-team`.
- `docs/superpowers/plans/2026-10-04-hypothex-phase3-frontend.md` — section 10, after the backend plan is merged and the mockups are approved.
- `hx demo --with-team` (backend plan) gives the UI: auth on with owner `sv` (admin) and `alice` (launch), a printed pairing URL for each, two projects with notebook days and one weekly summary, baselines on the toy task, 6 archived runs with artifacts (two cleanable, one protected, one shared with a child), outbox entries in every state (fake webhook and fake SMTP started by the demo on loopback), and one connected fake host.

Done when, all automated and green in CI (Docker job for marker `docker`):
1. Acceptance (spec 13): a test starts a hub with `server.auth: on` and `public_url`, plus an in-process env server as a shared `route: url` host with fake GPUs; the owner runs `hx pair --new-user --user alice --scope launch`; `alice` runs `hx login <url>` from a second home (her laptop); `alice` lists the same projects and tasks as the owner, launches on the shared host, and the run is mirrored with `owner: alice`, `created_by: human:alice`; the owner sees it; `alice` cannot stop the owner's run (403) and can stop her own; revoking `alice`'s session makes her next call 401.
2. A finished, a failed, and a lost run each produce exactly one Slack notice on `FakeWebhook` and one email on `FakeSmtp` for an opted-in project, none for a project not opted in; a 200-run sweep produces one; secret-leak scan has zero hits.
3. `hx export` golden files match for LaTeX, Markdown, and CSV, with seed noise, test-set CI, best bold, `†`, baselines, and `‡`.
4. `hx storage clean --archived --older-than 30d` dry run lists exactly the eligible artifacts (local and on a fake host), `--apply` frees exactly the planned bytes, and every refusal case of section 8.9 holds.
5. The weekly digest is built, sent once per week through both fakes, and saved to the notebook; `hx note --project` and the notebook API round-trip with run chips.
6. Every route, the WebSocket, and every MCP tool declares a scope; the scope matrix test passes.
7. Postgres (Docker): `hx db upgrade`, then reindex equivalence with SQLite.
8. Playwright smoke of every new screen in both modes against `hx demo --with-team`.
9. `uv run pytest`, `uv run ruff check`, `uv run ruff format --check`, `uv run ty check`, `bun test`, `bun run typecheck` clean. A first send to the user's real Slack/SMTP and a first Tailscale exposure are the user's manual steps.

## Changes after review round 1

Codex and Fable reviewed the three plans against this contract and the code on `main`. Every finding was fixed; where the fix differs from the reviewer's suggestion, or the contract changed, the ruling is one line here.

- **Host sessions (Codex 1, Fable 1).** `redeem(client="host")` needs an `admin` offer, and `identity()` honours body `created_by`/`owner` only for `client == "host"` with `admin` scope; `hx pair --client host` refuses any scope but `admin` (1.2, 1.10, 1.13).
- **MCP over HTTP (Codex 2, 3).** Tools carry the caller's own credential (bearer, else the `hx_session` cookie) and never fall back to the server's token; `stop_run`/`cancel_sweep` call `require_act` on local runs and sweeps (1.10, 5).
- **Host tokens are origin-bound (Codex 4).** `host-tokens.json` is `{host: {url, token}}`; `host_token` sends a paired token only to the origin it was redeemed at; `hx hosts pair` refuses a link for another origin (1.13, 2).
- **Run environments (Codex 5).** `HYPOTHEX_HUB_TOKEN` joins the default secret names and every host's `token_env` is scrubbed from runs (7).
- **Re-inference inputs (Codex 6).** Cleanup treats `vars["checkpoint"]` (what `control.reinfer` really writes) as a use of that path, at plan and at delete (1.9).
- **Compare export (Codex 9).** A shown metric with two versions or directions across the compared runs is refused, not merged (1.6).
- **Folded sweeps (Codex 10).** The sweep notice follows `rule.events` (1.7).
- **Digest notices (Codex 11).** The top notes are in the Slack/email notice; the notebook block lists task changes as lines, not a Markdown table, so the UI renders it (1.8). Fable 12 asked only to align the UI fixture; both sides now share one format.
- **Notebook "today" (Codex 14).** `hub_today` is the one date; the API accepts `today` for `{day}`, and the UI and `hx note` in client mode ask the hub instead of computing a date (1.4, 3).
- **Pairing limit (Codex 15, Fable 7).** The limit counts failed attempts only (a success spends a fresh one-use secret), keyed by `Tailscale-User-Login` or the proxy's `X-Forwarded-For` hop behind `tailscale serve`. Ruling: this fixes the e2e 429s at the source instead of isolating hubs per test, and still stops guessing (3, 8.10).
- **Overview owners (Codex 16).** `TimelineItem`, `IdeaRow`, `FailureRow` gain `owner` (10).
- **Revoke route (Fable 5).** The path parameter is `{session_id}` in the contract and both plans (3).
- **Pair page (Fable 13).** Ruling: the ready state shows the hub and offer id, not `user · scope · 4:12`; a public read of an offer by id would tell anyone holding a leaked offer id whom it pairs and at what scope, and the countdown adds nothing the 5-minute link does not already say (10.1).
- **Confirm dialog (Fable 14).** `3 paths`, not `37 files`: a `CleanItem` is a path with no file count (10.1).
- **Base commit (Fable 3, 4).** The backend plan's base is `main` at `e27a3a2` (it includes `6ace21d`); its anchors were re-checked there. Ruling: the frontend plan cannot name the phase 2 merge commit yet (phase 2 Task 28 is still on `phase-2`), so it gets a pre-flight script that checks every "as left by phase 2" anchor on `main` before Task 1.
- Plan-only fixes, no contract change: `NotifyTestBody` at module scope (Codex 8), `from None` on every `ChannelError` (Fable 2), frozen cleanup plan in the confirm dialog (Codex 12), Copy disabled on placeholder export text (Codex 13), the pairing label from the sent body (Codex 7), a concurrent apply of one plan refused instead of a 500 (Fable 6), `AuthGuard` skips the session lookup for static paths (Fable 8), a Postgres URL without `psycopg` is a `ConfigError` (Fable 9), the open-bind test never listens on `0.0.0.0` (Fable 10), and `docs/team.rst` says the home becomes 0700 (Fable 11).

## Changes after review round 2

Codex (17 findings) and Fable (3 Important, 7 Minor) reviewed the three plans again. Every finding was fixed in the plans; where the fix differs from the reviewer's suggestion, or a finding was not taken, the ruling is one line here.

- **Runs and the server's credentials (Codex 1).** A run on the serving machine needs `admin` (`require_local_exec`, 1.3, 7; HTTP and MCP; Tasks 5, 27, 32). Ruling: this separates collaborators' code from the hub's credentials by machine, not by a second Unix account on the hub; a `run_as` account needs privileged setup that tests cannot fake, and a lab runs its shared box as a host under its own account (`docs/team.rst`).
- **Cleanup (Codex 2, 3, 4).** A symlinked folder under the home is never entered or deleted through (`protected_reason`, `local_usage`); `delete_artifacts` takes the plan's `older_than_days` (also in the host's delete body) and checks and deletes under `cleanup_lock`, which run creation with an input path, `star_run`, and `archive_run` also take (1.9, 3, 8.9). Ruling: one lock per apply, not per item; deleting files takes seconds and the waiting actions are rare.
- **Second `hx serve` (Codex 5, Fable 6).** The home is claimed before any side effect, and a start that fails before serving undoes its session and Tailscale mapping (8.13, 8.14; Task 39).
- **`?password=` in `index_url` (Codex 6).** Refused like `user:pw@`, and `redact_url` hides it (1.1).
- **Stale index rows after a Postgres outage (Codex 7).** Failed run writes are journaled and re-indexed from files by `repair_pending` (8.13; Task 34).
- **Notifier (Codex 8, 9; Fable 2).** A recorded entry left in the outbox is dropped, not resent; a scheduled digest ends its window at the week's send time, so a resend has the same notice id, and the notebook append is skipped when its stamp exists; sweep summaries are cached per event batch (1.7, 1.8, 8.4, 8.6, 8.15).
- **Export directions (Codex 10).** Export uses the leaderboard's rule (`metric_higher_is_better`: a `system_bench` percentile ranks lower-first) for every column, in task and compare tables (1.6).
- **Agent provenance over remote MCP (Codex 11).** `hub_call(agent=)` sends `X-Hypothex-Agent` with the tool's own agent (Task 41).
- **Plan tests (Codex 12, 13; Fable 1, 4).** MCP error assertions match the message's end (the SDK prefixes `Error executing tool <name>: `); `LAUNCH_TOOLS` gains `add_notebook_entry` in Task 33; the docs test looks for `auth: on` and `hx serve --auth --tailscale`; Task 12 expects 26 tests.
- **Notebook reads (Codex 14).** One open per read; a day removed meanwhile reads as empty (8.16).
- **UI (Codex 15, 16, 17).** The notebook text areas are read-only while their request is in flight; export texts are keyed under `["leaderboard", project, …]`, so run events refresh them; the leaderboard panel draws baselines when no run is scored yet.
- **Frontend anchors (Fable 3).** The `RunActions.tsx` Cancel/Stop blocks are phase 2 Task 26's, on `phase-2` only; every "replace" block in a phase 2 file is now marked for the pre-flight (12 anchors). Ruling: Task 25's e2e anchors are re-synced at the pre-flight, not now, because phase 2 moved the e2e homes under a per-run `RUN_DIR` (`9341413`) and `phase-2` still has uncommitted e2e edits.
- **Demo shared host (Fable 5).** It runs with a bearer token (`token_env: HX_DEMO_SHARED_TOKEN` in the hub's `secrets.env`), so the hub forwards as the host principal and runs keep their owner (11).
- **Ruling, digest layering (Fable 7).** Not changed: `core.digest` uses `notify.messages` for the notice and imports the notifier lazily in `send_digest`; moving `Notice` into core would touch five tasks for no behaviour change.
- **Baseline badge (Fable 8).** The badge is `≠<our version>` with a tooltip; 10 and 10.1 now say `≠v2`, as the mockup and the UI do (no backend field added).
- **Ruling, notebook "today" query (Fable 9).** Kept on day pages: it gives the day list its "today" row when today has no file yet, so it is not an extra request.
- **Mockup (Fable 10).** `plan.files` is `plan.paths` (37 = 6 listed + 31 more); 10.1's dialog says `37 paths`, which corrects round 1's `3 paths` (that number came from the frontend test fixture, not the mockup).

## Changes after review round 3

Codex (11 findings above P3, 1 lint) and Fable (2 Important, 6 Minor) reviewed the plans against `origin/main` `8df4760`. Every finding was fixed in the plans; where the fix differs from the suggestion, or a finding was not taken, the ruling is one line here.

- **Folder artifacts (Codex 1).** `plan_clean` and `delete_artifacts` compare every other run's artifacts by `overlaps` (equal, inside, or above), not by equal path (1.9; Tasks 21, 22).
- **Command receipts (Codex 2).** `command_key` binds every receipt to caller (user and scope), method, and path (3; Tasks 23, 25, 27, 29–31). Ruling: the body is not in the key. Phase 1 makes a retry with an edited body return the first result (`test_put_view_is_idempotent_by_command_id`, `test_run_actions_are_forwarded_with_the_same_command_id`), and a same-caller, same-target replay crosses no authorization boundary.
- **Digest secrets (Codex 3).** Redaction moved into `Notifier.enqueue`, so no caller can skip it (1.7; Tasks 16, 19).
- **Full notebook day (Codex 4).** `send_digest` skips only the notebook copy; `tick` isolates `digests()` from `deliver()` (1.7, 1.8; Task 19).
- **Foreign sweeps (Codex 5).** Folding needs this hub's member tag on the run (1.7; Task 16).
- **Sweeps still launching (Codex 6).** Not folded while members < planned and `sweep_issuing` holds the sweep lock (1.7; Task 16). Ruling: a launch that failed midway (lock free) notifies with what exists; that is the sweep's final state unless a retry resumes it, which issues more runs whose endings notify again.
- **Repair journal (Codex 7, 8).** Recoverable claim files, journal appends under `flock` that follow a moved file, and re-index under `run_lock` (1.11; Task 34).
- **Demo checkpoints (Codex 9).** In each run's own `artifacts/` (`<run_dir>/artifacts/model.pt`), the only cleanable place in the home (11; Task 45).
- **Compare `--percent` (Codex 10).** Per column, only where `value_format` is `fraction` (1.6; Task 12).
- **Notebook free text (Codex 11).** `parseDay` keeps the text before the first stamped entry as an unstamped entry (frontend Task 18).
- **Lint (Codex 12).** Unused imports removed from the acceptance test; Task 34's test imports sorted.
- **Frontend anchors and `RUN_DIR` (Fable 1, 2).** The header records `8df4760`; Task 25's `serve-demo.ts` anchors are copied from it (pre-flight: `12 anchors anchors ok`); the team home and demo file are `<RUN_DIR>/home-team` and `<RUN_DIR>/demo-team.json`; no `.gitignore` step (`.runs/` is ignored).
- **Minor (Fable 3–6, 8).** Task 6 expects 24 scope tests; `hx storage clean` prints `paths`; `--owner me` with auth off filters nothing (1.12); the fail-closed `config.yaml` read is documented (1.11, `docs/team.rst`); the mockup's input label is `Confirm size`, as in the UI and e2e.
- **Ruling, pairing rate margin (Fable 7).** No change: the team specs make about 2 failed pairings per minute against a limit of 10.
