# Primary refresh R5 — Claude primary review

**Verdict: LGTM** for the full Phase 3 plan at exact commit **`2ebfc28eeded41e236f5f93c05347a467328ef4b`** against main **`f6f130cfa2669bfcccbadcb36282dd5fea881d1f`**.

This LGTM covers this exact plan only. The next step is a NEW independent adversarial R2 on this same hash. This LGTM does **not** authorize implementation.

No P0, P1 or P2. One P3 nit (optional, nonblocking).

## Inputs (checked at start and end)

| File | SHA256 |
|---|---|
| contract | `47e4f718043a115a999e1d446e21a48ac9f39c44170307ac884e23ea72f090c7` |
| backend | `402c98af078692e9f465bf0e2668bc0c04dd0f1398e1d6117a4208c09896dd8a` |
| frontend | `5c71dfc0e12e2c6f9fbfd1c592ad73826419c7b09110631df841c51c96bba757` |
| package supplement | `0972c9439b864ba06c3f99a5f87c123a34deb7bf66be9f7fc1cd4a2596747027` |
| main-refresh | `b0278eb1dd1869153b7c8550d13d01439317e3473952c7c1209f8edd673bc01f` |
| tasks/phase3-execution.md | `afe961c91bc7d9a5c735d2163524836bfe2e27945e4b0c1dbab2d9ccd38d8bff` |
| tasks/lessons.md | `2bf004304304606935d2a23f17cd2f36f4a8d963e8c515607299e7c7578a9bca` |
| tasks/ui-selection-ci.md | `7cb35a33b450d3e641f139ea9fb4cb9377fb4b0ddbd3367a123f3dbb93c7bcdb` |

All 8 match `review-input.json` and `../final-review-input.json` (the two files are equal) at start and end. Both frozen trees are clean at start and end, at the HEADs above. The root checkout was not written: its only status is the pre-existing untracked `.superpowers/`. See [receipts/inputs-end.txt](receipts/inputs-end.txt).

Plan versus main outside `docs/superpowers/`: only `docs/mockups/phase3/*` and `tasks/*`. The runtime diff is empty. `tasks/ui-selection-ci.md` differs from main by one checkbox line (PR26 merged).

## What changed since R4 (`1a81663` → `2ebfc28`)

Commits: `b6cc9eb` (empty-PG guard fix), `86e0336` (merge of main `f6f130c`), `2ebfc28` (pin refresh). I read every changed token ([receipts/plan-delta-tokens.txt](receipts/plan-delta-tokens.txt), [receipts/plan-delta-1a81663-2ebfc28.worddiff](receipts/plan-delta-1a81663-2ebfc28.worddiff)).

Per-task hashes ([receipts/task-hashes.json](receipts/task-hashes.json)):

- **Backend:** preamble and Tasks 1, 4, 9, 12, 14, 22, 34, 39 changed. 41 of 49 tasks are byte-identical.
  - Task 1 has the real change: L408 guard, L501 contract text, L507 matrix.
  - Tasks 4, 9, 12, 14, 22, 34, 39 changed only the pin `e73b810` → `f6f130c` (snapshot oracle, `SweepSummary` note, `higher_is_better` note and similar). Main `e73b810..f6f130c` touches only 5 UI/doc/tracker files. So every backend oracle these pins name is byte-identical.
- **Frontend:** preamble and Tasks 24 and 26 changed. 24 of 26 are byte-identical.
  - Task 24 L335 adds the SelectedRun preservation sentence.
  - Task 26 changed only pins plus the SelectedRun blob `5b21ef0` → `0585836`.
- **Contract:** pins, §9 network-guard bullet (L565: "present … including empty values"), §10 task workspace (L584: preserve the selected-run reveal).
- **Package supplement:** L5 pins only. The schema-3 `a444125` and schema-4 `e73b810` fixture pins are unchanged on purpose. They are original fixture provenance, not source drift: main's backend and schema are the same at `e73b810` and `f6f130c`.

## Adjudication 1 — empty-value PG correction (my R4 P3-1): RESOLVED

The current Task 1 fence (backend L408) is `ambient = sorted(name for name in os.environ if name.startswith("PG"))`. It is **byte-equal** to the parent's executed `parent-primary-r4-empty-pg-fix/final_network.py` (fence SHA `eb174c61…`). The R4-commit fence is equal to `original_network.py` (`69de516f…`). The only difference is that one line.

The parent's receipt hash `cf3c67ef…` is the same text without the trailing newline. I re-derived this; it is not a mismatch. The contract (C:565) and the mandatory matrix (L507) agree with the code.

**Fresh probe** ([probes/pg/tests/test_r5_guard.py](probes/pg/tests/test_r5_guard.py), **73 passed**, [receipts/pg-probe-pytest.log](receipts/pg-probe-pytest.log)). Before any guard loads or runs, each test installs an inert `Connection._connect_gen` recorder and socket/DNS tripwires. No database, socket or DNS I/O can happen. The guard source is pulled at runtime from the frozen plan.

- **82 rejected calls with zero boundary entries.** I made the list of variable names dynamically from libpq's own `PQconndefaults` envvar table, plus 5 non-option names. That gives 41 names: every libpq-documented `PG*` variable, plus a future sentinel. Each one is set to `""`, and both `psycopg.connect` and `Connection.connect` are called. The error text is exactly `tests block PG defaults: <NAME>`.
- **Red/green for the R4 scenario.** I used a disposable HOME with `.pg_service.conf` = `[]` + `hostaddr=203.0.113.77`.
  - With PGSERVICE absent, libpq defaults show no hostaddr. Absence is safe.
  - With `PGSERVICE=""`, libpq defaults show `hostaddr=203.0.113.77`. Empty is not the same as absent.
  - The R4 guard reaches the boundary with `{dbname:x, host:/tmp}`. The R5 guard rejects with zero entries. See [receipts/empty-service-old.json](receipts/empty-service-old.json) and [receipts/empty-service-new.json](receipts/empty-service-new.json).
  - The old-red case is evidence of the defect, not approval of it.
- **Service-file variants.** `PGSERVICEFILE=<file>` + `PGSERVICE=""` and `PGSYSCONFDIR=<dir>` + `PGSERVICE=""` are rejected. The paths do not appear in the error.
- **Names-only secrecy.** `PGPASSWORD=SECRETPG-…` and an explicit conninfo `password=` on a rejected external host never appear in the error. In the pytest child, the output does not contain the injected secret.
- **Safe behavior retained.** 10 accepted cases. Each multihost attempt is recorded, because the sentinel subclasses `OperationalError`. Each attempt is local:
  - numeric IPv4/IPv6 loopback
  - `localhost` → `127.0.0.1` and `ip6-localhost` → `::1`, with no DNS
  - hostless → `/tmp`, and an explicit Unix directory
  - an empty first host → `/tmp`
  - mixed `localhost,/tmp/s` + `hostaddr=,::1`
  - a kwargs-local host over a conninfo-external host
  - a `None` kwarg ignored
- **Forbidden cases.** 12 forbidden cases never reach the boundary:
  - external v4 and v6 hosts
  - an external hostaddr with a loopback host
  - a local hostaddr with a named host
  - a hostaddr path, and `0.0.0.0`
  - an unsafe second host, and an unsafe second hostaddr
  - `service=x`, and an empty `service` kwarg
  - kwargs-external host or hostaddr over conninfo-loopback
- **Production engine path.** SQLAlchemy 2.1.1 `postgresql+psycopg` (Task 34) with an empty PGSERVICE raises `NetworkBlockedError`. With it absent, the engine reaches only the boundary, at 127.0.0.1.
- Repeated `guard_network` installation forwards once, with no recursion.
- `scrub_pg_environment` and `pg_child_environment` drop all 41 empty names, keep `USER`/`HOME`, and leave the parent mapping unchanged.
- **Pytest child.** The launcher injects `PGSERVICE=""`, `PGHOST=""`, `PGHOSTADDR=<external>` and `PGPASSWORD`. The child conftest contains the **exact Step 5 snippets** pulled from the plan. A module fixture sees the session scrub. A test-added empty `PGSERVICE` is rejected at connect. The next test sees the per-test scrub and reaches only the boundary. Result: 2 passed ([receipts/pytest-child.log](receipts/pytest-child.log)).

**R4 suite replayed on the new plan** ([receipts/r4-replay-on-2ebfc28.log](receipts/r4-replay-on-2ebfc28.log)): my immutable R4 probe, copied with only the backend SHA constant updated. Result: **57 passed, 2 failed.** Both failures are expected and confirm the change:

1. `test_extracted_guard_equals_parent_final_copy` compares against the superseded A1 final copy. The diff is exactly at the `and value` line.
2. `test_empty_pgservice_passes_guard_…` asserted the old bypass. It now raises `NetworkBlockedError: tests block PG defaults: PGSERVICE`.

All other R4 checks still pass on the new text: 46 forbidden calls, 6 accepted, the SQLAlchemy path, the Task 36 `run_cmd` final-merge filter on main's real source, and the Task 39 AST check (5 of 5 launches filtered, filter after `full.update`).

**Cross-task effect check.** No planned test sets any `PG*` variable. The plan's only `PG*` literal is the `pg_child_environment` doctest. CI and the main tests define no `PG*`. The Docker image uses `POSTGRES_*`, which the rule does not affect. So "reject when present" adds no false failures. It also adds no production PostgreSQL restriction: the rule lives only in `tests/fakes/network.py`, and contract §9 says "Apply only in tests".

## Adjudication 2 — PR26 baseline and UI preservation seam: RESOLVED

- Main `e73b810..f6f130c` touches exactly 5 files: `SelectedRun.tsx`, `selectedRun.test.tsx`, the new `e2e/selectedRun.spec.ts`, `docs/ui.rst` and `tasks/ui-selection-ci.md`.
- The tree at `eb503ee` equals the tree at `f6f130c`: the reviewed and CI-green head is what merged ([merge.json](../ui-selection-ci/merge.json), with Codex `has_any_findings:false` in premerge.json).
- I read the code. It focuses the heading once. An ancestor `ResizeObserver` re-centers only while `revealing` is set and the heading is still active. Capture-phase wheel, touchstart, pointerdown, keydown and focusin release it. The cleanup calls `release()` before the pre-existing focus restore. Without `ResizeObserver`, the code falls back to the old behavior. There is no refocus loop and no polling.
- **Fresh run** (temp `git archive f6f130c`, `bun install --frozen-lockfile`, temp dir removed after): `bun test test/pages/selectedRun.test.tsx` gives **15 pass, 0 fail** ([receipts/ui-selectedRun-unit.log](receipts/ui-selectedRun-unit.log)).
- **Mutation checks** show that the retained tests the plan requires really guard the seam:
  - The e73b810 component gives **6 fail** (late-layout reveal plus all 5 user-takeover cases).
  - Removing only the `revealing` flag gives **5 fail** (all takeover cases).
  - Restoring the code gives 15 of 15 again.
- **Plan side.**
  - Frontend Task 24 (L335) now lists `SelectedRun.tsx` as a modify target. It must pass `RunDetail` to WhereList/CheckpointTable while keeping the observer, focus restore, user-input release and queued-callback guard. It must keep both regression files. Contract §10 (C:584) matches.
  - Cleaned markers are additive, and late layout from them is exactly what the observer handles.
  - No other frontend task moves focus without user input. Dialog focus traps (frontend L68) open only after a click or key, which already releases the reveal.
  - All 51 source anchors resolve, by blob and by line text, at current main ([receipts/anchor-check.json](receipts/anchor-check.json)). Only the SelectedRun blob changed.

## Finding

### P3-1 · nonblocking nit · Task 26 does not name the new selected-run docs paragraph

**Where:** frontend Task 26, L469 ("Preserve user-facing New run/rename/search/metric direction and explicit sweep resume descriptions") and L471 (Verify). Main `docs/ui.rst` L358–360 now says the selected heading stays visible during delayed chart loading and yields on scroll, touch, click, typing or focus. `tests/test_docs_ui.py` on main does not assert this paragraph.

**Scenario:** a Task 26 docs rewrite of the task-page section could drop those three lines, and no docs test would fail. The behavior and its tests stay protected by Task 24, so only the user doc text is at risk.

**Fix (optional):** add "selected-run reveal during delayed charts" to the L469 preserve list, or add one assertion to `tests/test_docs_ui.py`. This does not block. The parent may fold it in or defer it, without a renewed review if it is the only change.

## Dispositions

| Item | Disposition |
|---|---|
| **R4 P3-1** empty `PGSERVICE` | **Resolved** (above; red/green reproduced fresh). |
| PR26 baseline / SelectedRun seam | **Resolved** (above). |
| A1 PG test isolation (adversarial R1) | Resolved. Task 36 and the package L179 text are unchanged. Task 39 changed only a pin. R4's Task36/39 checks pass again on the current text. |
| F1 parent-symlink TOCTOU | Resolved. Task 22 changed only a pin (L11954/11956 snapshot oracle). The R2 4-env replay and the adversarial-R1 23 cases are reused. Full apply/remote tests are future acceptance. |
| F2 schema 4/5 | Resolved. Schema 5 is everywhere. The Task 49 schema3=`a444125` and schema4=`e73b810` fixtures are kept, correctly not repinned. Real PG/wheel restore is future acceptance. |
| F3 WS zero timeout | Resolved (unchanged). |
| F4 scopes / rename `forward` | Resolved. The contract C:426 change is a pin only. |
| F5 `/hosts`, `/queue` | Resolved (unchanged). |
| F6 `q` search | Resolved. The Task 34 L17294 pin is the only change. |
| F7 UI owners | Resolved. 24 of 26 frontend tasks are byte-identical. Task 24/26 deltas were read. 51 of 51 anchors were re-verified fresh. |
| F8 direction | Resolved. The Task 12 change is a pin only, and the R2 import fix is kept. |
| F9 PG cache identity | Resolved. The Task 34 changes are pins only. |
| R1 P2-1 O_PATH/O_SEARCH | Resolved (Task 22 body unchanged except the pin). |
| R2 P2-A Task 42 merge | Resolved (Task 42 byte-identical; the R3 replay is reused). |
| R3 P3 wording nits | Still fixed. |
| USER=alice elevation | Stays rejected. No contrary evidence. |
| Unknown-cost screenshot | Nonblocking, as documented. Its textual correctness acceptance is still required (Task 26 L469). |
| Historical R1/R2/R3 fixes (costs, alias protection, SPA routes, wheel Task 49, runner.temp, USER pin, source sync) | Kept. The texts are unchanged except for pins. |

## Testing limits

- Bounded probes of exact plan snippets with real psycopg 3.3.6 / libpq 18.6 (binary) / SQLAlchemy 2.1.1 parsing on macOS, Python 3.11.14. This is not an assembled Phase 3 app. No PostgreSQL server, Docker, `hx serve`, wheel, browser or CI was run for Phase 3. No Linux or Windows claim this round.
- `Conninfo.get_defaults()` parses defaults only. I did not open a libpq connection to prove the final libpq step. The parent and R4 showed the same thing the same way.
- UI: one fresh unit file plus 2 mutation runs. The 122 browser tests, the 12 focused e2e runs and the CI results are the parent's and PR26's evidence. I inspected them but did not rerun them.
- Unchanged tasks: the verdict relies on byte-identity (or pin-only deltas) to `1a81663`, plus the R2/R3/R4/adversarial-R1 full reads, as listed in [coverage.md](coverage.md). I re-checked cross-task links to the changed seams, not every unchanged task body.
- Future-feature acceptance (all 13 items) remains prospective, as planned.
