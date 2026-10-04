# Backend performance remeasurement, 2026-10-05

Code: `8e1a1ef` (audit fixes plus main through PR #14). Baseline: the saved
2026-10-04 audit at `738c711`; the baseline was not re-run on this date.
Same Apple Silicon 12-core, 16-GB machine and Python 3.11.14. The preserved original
synthetic fixture was cloned with APFS copy-on-write to a separate `/tmp` home.
No real host connections or source-fixture writes were made.

The fixture contains 19,993 runs, 30 projects, 54,642 scores and 1,000,000 events.
Each ordinary run has 200 series with 5 steps; 21 training runs have 500 steps.
Dates span January–April 2026, so the default seven-day overview is now a quiet
window. A separate all-history overview explicitly includes those dates.

For each HTTP endpoint, a fresh server process measures its first request and
then the median of three further requests. Server startup is excluded. Cold
means application caches, not OS/disk caches. Lazy metric hydration persists in
the cloned index across endpoint cases; first view reads are called out separately.
Timing includes response serialization and transfer over loopback, with httpx's
default compression negotiation. Byte counts distinguish decoded JSON from gzip
wire size. The original audit reported the median of three requests in one server
process, so its numbers are historical comparison points, not paired trials.

The server uses the actual application with lifecycle repair and remote hub
connections disabled, preserving the static synthetic fixture's queued/running
records. Every response must succeed; view panel errors fail the harness.
No fixed latency thresholds are imposed on this single-machine measurement.

## Results

| Operation | Historical baseline | Current result |
|---|---:|---:|
| Rebuild, 19,993 runs | 766 s; 393 MB max RSS | 30.28 s; 68 MB max RSS |
| Indexed metric rows immediately after rebuild | 22,072,000 | 0; 19,993 runs pending |
| SDK, 200 metric values per step | 12.4–15.5 ms/step | 0.5 ms/step; 437,421 values/s |
| WebSocket replay from sequence 0 | 18.9 s; 1,000,000 events | 14.970 s; 1,000,000 events |
| WebSocket subscribe from latest | Not available | 3.177 ms; no replay events |
| WebSocket replay cap 1,000 from sequence 0 | Not available | 1.490 ms; one reset frame |

The rebuild preserves all run, score, project, event and per-status counts. It
moves metric loading to first use. The original SQLite file still occupies
2.368 GB after rebuilding: 63.2 MB are live pages and 2.305 GB are reusable free
pages. Atomic table replacement does **not** compact the existing file. After
the HTTP/CLI measurements, 3,777,000 metric rows had been hydrated, 17,899 runs
were still pending, and live pages occupied 494.1 MB. No vacuum was performed.

All HTTP timings below are milliseconds. MB are decimal, rounded to three
places; sub-kilobyte responses can therefore display as 0.000 MB. The first
request and warm median refer to the current code only.

| Request | Baseline median | Current first | Current warm median | Decoded MB | Wire MB |
|---|---:|---:|---:|---:|---:|
| Runs, limit 200 | 8 | 37.0 | 9.9 | 0.375 | 0.019 |
| Runs, project/task/status filter | 22 | 118.9 | 37.2 | 0.377 | 0.019 |
| Runs, tag filter | 68 | 70.4 | 29.2 | 0.376 | 0.019 |
| Runs, limit 1,000 | 77 | 79.7 | 70.1 | 1.878 | 0.090 |
| Runs, limit 16,000 | 1,235 | 1,360.7 | 1,229.9 | 30.042 | 1.428 |
| Projects | 89 | 68.3 | 28.5 | 0.003 | 0.000 |
| Tasks | 2,436 | 3,283.4 | 33.8 | 0.014 | 0.001 |
| Task p00/agent | 251 | 201.5 | 2.0 | 0.001 | 0.001 |
| Leaderboard p00/train | 184 | 280.7 | 35.6 | 0.779 | 0.168 |
| Leaderboard p00/agent | 2,292 | 2,526.3 | 38.4 | 0.814 | 0.179 |
| Leaderboard p00/qa | 13,174 | 2,536.0 | 21.0 | 0.409 | 0.090 |
| Leaderboard p07/eval | 97 | 136.3 | 6.6 | 0.090 | 0.021 |
| Overview, default window | 24,221 | 2,663.2 | 478.6 | 1.414 | 0.077 |
| Run page, p00/agent | 238 | 43.2 | 2.4 | 0.005 | 0.002 |
| Run page, p07/train | 31 | 39.0 | 2.5 | 0.004 | 0.001 |
| Long-run metrics, all 200 names | 1,140 | 1,601.3 | 526.2 | 7.713 | 1.592 |
| Normal-run metrics | 10 | 33.7 | 5.6 | 0.075 | 0.015 |
| Traces | 5 | 7.6 | 3.6 | 0.001 | 0.001 |
| View definitions, p07/train | 7 | 5.7 | 4.7 | 0.000 | 0.000 |
| View p07/train | 2,816 | 3,013.2 | 235.3 | 1.560 | 0.184 |
| View p00/train | 45,670 | 37,693.2 | 2,918.5 | 15.934 | 1.736 |
| View p00/agent | 16,789 | 9,083.0 | 6,150.3 | 18.504 | 1.612 |
| View p00/qa | 26,364 | 2,634.7 | 78.3 | 0.410 | 0.090 |

The unfiltered metrics row uses the same request and preserves all 200 series
and the list response shape. A separate request for only `train/loss` and
`val/loss`, with `max_points=500`, took **40.5 ms first / 5.9 ms warm**, returning
0.081 MB decoded and 0.016 MB on the wire. That is a smaller query, not an
apples-to-apples speedup for the unfiltered endpoint. The table's first long-run
metrics request includes lazy hydration; the selected-name request runs after
that hydration. The frontend adoption of selected names is a separate follow-up.

The default overview still includes queued and running work, but this fixture
has no recent completed runs. An explicit `since=2026-01-01T00:00:00Z` query
includes the full historical workload and took **19,975.9 ms first / 8,403.4 ms
warm**, returning 8.939 MB decoded and 0.917 MB on the wire. It has no matching
historical baseline measurement and is not substituted into the default-window
comparison.

Every leaderboard row retains its statistics. These improvements do not come
from removing uncertainty estimates from rows outside a top-K cutoff. Board
and statistical caches reduce repeat work, but the generation key is still
index-wide. In a separate fresh process, the p00/qa board plus JSON serialization
took 2,582.4 ms cold and a median 15.4 ms warm. Writing an unchanged, unrelated
p05 record to the index bumped the generation; the next p00/qa read took
743.9 ms, then returned to a 15.3 ms warm median. This is a real invalidation
cost during active writes; a quiet warm result does not measure sustained traffic.

## CLI

Each current CLI value is the median of three fresh `uv run hx` processes,
including startup. The cloned home is explicit and the hub URL is a deliberately
closed loopback port, so these are local fallback reads. The baseline values
are the original audit's recorded wall times, not paired reruns.

| Command | Baseline ms | Current median ms |
|---|---:|---:|
| `hx runs` | 420 | 625.2 |
| `hx runs --limit 200 --json` | 390 | 615.1 |
| `hx runs --project p00 --task agent` | 350 | 623.5 |
| `hx projects` | 530 | 312.5 |
| `hx leaderboard p00/train` | 370 | 452.9 |
| `hx show <p00 agent run>` | 360 | 616.5 |

The CLI table includes regressions: several hub-aware read commands now take
about 0.62 s locally. The filtered runs endpoint is also slower in this sample
(37.2 ms warm versus 22 ms), and the 16,000-run endpoint remains about 1.23 s.
Compression reduces transfer size without removing full-record serialization.

## Limits and retained evidence

- First-use costs remain substantial: the large training view takes 37.7 s
  after metric indexing is deferred, and the agent view remains 6.15 s warm.
  Both requests still return large decoded payloads on this fixture.
- This is one static synthetic fixture on one workstation, with three warm
  samples per request. It is not a production workload, a concurrent-write
  stress test, or a confidence interval for latency. Broad test processes and
  Docker were stopped during the timing window (22:00–22:05 UTC on October 4;
  October 5 locally). The operating-system cache was not flushed.
- Historical baseline code `738c711` was not re-run. The current backend code
  was `8e1a1ef`; subsequent changes in this report commit are documentation only.
  The baseline used one long-lived server; current first requests use separate
  server processes and current warm medians follow each first request.
- Lifecycle repair and remote connections were disabled only in the benchmark
  harness. No real SSH/SLURM host was used. The synthetic store's records and
  dates were not rewritten to make the overview busier.
- Current server heap/RSS peaks, contention latency, and event append throughput
  were not re-profiled. Only rebuild max RSS is compared above. Full WebSocket
  replay remains available; latest/capped subscriptions are distinct modes.

The checked-in [measurement data](2026-10-05-backend-performance.json) preserve
all request paths, individual samples, response sizes, baseline source lines,
counts and invalidation measurements. The original baseline inputs/logs remain
under `/tmp/hx-audit-perf`; the isolated clone, runnable harnesses and complete
new logs remain under `/tmp/hx-af-perf-after`:

- `server.py`, `bench_http_after.py`, `bench_invalidation.py`, `bench_cli.py`,
  and `collect_counts.py` describe the exact current method.
- `http-after.log`, `http-after.json`, `rebuild-after.log`, `sdk-after.log`,
  `cli-after.json`, `invalidation-after.json`, and the count snapshots retain
  the measured evidence. The baseline's `time_rebuild.py` and `sdk_rate.py`
  were reused directly for those two operations.

## Validation of the branch

- Python: 1,727 passed, 3 skipped, 11 Docker tests deselected in the main run.
- Docker SSH/SLURM integration: all 11 passed separately.
- UI: 848 unit tests, TypeScript checks, production build, 44 Playwright tests,
  and all three demo shutdown scenarios passed against merged main.
- Ruff lint/format, ty, Sphinx with warnings as errors, and diff checks passed.
- Review regressions cover CLI task re-evaluation's timeout, competing launch
  worktree reservations, and concurrent rebuild update/create/delete retention
  when advisory locks are unavailable. The SLURM property model now also covers
  intentional array refusal. Failing-before evidence is retained in the handoff
  logs; no real host or user SSH configuration was accessed.
