# Hypothex Phase 3 Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show phase 3 in the web UI: pairing a device (`/pair`), the 401 gate, the header's notebook, storage, settings and user chip, Settings (sessions, users, add device with QR, notifications), Storage (bytes by project and host, largest items, dry run, then apply with the number typed back), the lab notebook (`/n/:project/:day` with run chips, append, whole-day edit and the 409 conflict view), the Task page's `export ▾` menu and paper baselines, and run ownership (`@owner`, owner-only stop) plus cleaned artifacts on the Run page, all kept live by the phase 3 events.

**Architecture:** The phase 1b/2 API layer stays the only data layer. Tasks 1–4 add the contract shapes to `models.ts`, the merged token credential provider extended with scoped principal context, one `api.*` function per route the screens use, keys, hooks and invalidation lists, and the phase 3 event mapping; the event stream retains the token baseline's fresh-ticket subprotocol flow before every connect. Each screen keeps its arithmetic in small pure modules with unit tests on concrete numbers (`pairing.ts`, `owner.ts`, `settings/model.ts`, `storage/model.ts`, `notebook/model.ts`, `exportFormats.ts`) and draws with small prop-driven components that inject their own scoped CSS. One `GET /api/v1/auth/me` per app (in `AppShell`) feeds `PrincipalContext`; components read it with `usePrincipal()` instead of fetching. Playwright gets a third demo hub, `hx demo --with-team` (auth on, owner `sv`, collaborator `alice`), and pairs every browser through the real `/pair` page.

**Tech Stack:** Bun 1.3, Vite 8, React 19, TypeScript 5.9 (strict), TanStack Router and TanStack Query 5, d3-scale (through the phase 1b `charts/` primitives), happy-dom + Testing Library (`bun test`), Playwright 1.63, openapi-typescript 7; `uv` for every Python command (`uv run hx ...`, `uv run pytest`, `uv run sphinx-build`).

**Spec:** `docs/superpowers/specs/2026-09-26-hypothex-design.md` sections 9 (phase 3 design), 7.2 (`hx export`, `hx storage`), 7.3 (phase 3 auth), 13 (phase 3 row); sections 8 and 8.1 for the UI rules.

**Contract:** `docs/superpowers/plans/2026-10-04-hypothex-phase3-contract.md`. Section 10 is this plan's scope; sections 1.3–1.10 are the shapes, section 3 the routes, section 2 the events, section 11 the demo it consumes. Every name, field and route in it is exact.

**Mockups:** `docs/mockups/phase3/` (`index.html`, `data.js`, `shot-pair-{ready,done,invalid}-*`, `shot-settings-*`, `shot-settings-collab-*`, `shot-storage-*`, `shot-storage-confirm-*`, `shot-storage-result-*`, `shot-notebook-*`, `shot-notebook-conflict-*`, `shot-task-export-*`, `shot-run-*`, `shot-gate-*`).

**Depends on:**
- The phase 2 frontend and audit/UI improvements are merged. The integration snippets below were refreshed against actual merged-main baseline `54259b0fbfff70b20f612e3e508da37d65efeff5`, including the frozen DF-48 and token interfaces. PR21 is merged at this exact main commit; the final baseline refresh is complete and formal rounds 5–6 remain pending. Before implementation, run this check on the intended source checkout. The 12 historical snippet anchors alone are insufficient: whole-file Header replacement and procedural event-stream edits must also match the reviewed source blobs.

```bash
uv run python - <<'PY'
import pathlib
import re
import subprocess

plan = pathlib.Path("docs/superpowers/plans/2026-10-04-hypothex-phase3-frontend.md").read_text()
anchor = re.compile(r"`(ui/[^`]+)` \(as left by phase 2 Task \d+\), replace\n\n```[a-z]*\n(.*?)\n```", re.S)
found = anchor.findall(plan)
bad = [f for f, block in found if not pathlib.Path(f).is_file() or block not in pathlib.Path(f).read_text()]
reviewed = {
    'ui/src/api/events.ts': '7256185bf8aea3b9950f480611bb4bc527de9d1a',
    'ui/src/api/queries.ts': 'c05040ef695e234e7165056c87a3360fef1a435a',
    'ui/src/api/client.ts': 'a7c990fbbe099a016ff28045d2a271231798702c',
    'ui/src/shell/Header.tsx': 'b61fbb21380110a250fb21190ce17d81b289a1d8',
    'ui/src/pages/components/OverviewLists.tsx': 'b332763d7670b1192bc4d05e7d0ef2bbd56198a6',
    'ui/src/pages/Task.tsx': 'a9f4134b06601564edc191ed1162bca270f2da20',
    'ui/e2e/serve-demo.ts': 'a5148484442f9e2656c3757c98140c9b037a36d4',
    'ui/src/pages/components/RunActions.tsx': '0edaee2caf463d139749f539a1ce797a36193710',
    'ui/playwright.config.ts': '221aaa10fc64bd01c486a48ce0ab00f677277ab1',
    'ui/src/pages/Overview.tsx': 'f9fae51a56733ebc95ab3851aeb7e3a37f7bdb96',
    'ui/src/pages/Run.tsx': 'dc58c5266a557f0a2258c9fd196d95f62de2169d',
    'ui/src/shell/CommandPalette.tsx': 'd6f33215ed15652b23d9f50d3656e598d00088bd',
    'ui/src/pages/components/WhereList.tsx': '2f8b41b3d5289e13aac5763b18381d13f053fa3a',
    'ui/src/panels/Leaderboard.tsx': '50d1a4ffb5d5e06f02db3fe506908c230ea31bcb',
    'ui/src/pages/components/useAction.ts': 'cce82cbf60c2e148bbd60faabc217d4088ef64e8',
    'ui/src/launch/launchApi.ts': '7eb67cab7d6b6442cc74e1ac13becd850465e47d',
    'ui/src/launch/LaunchDialog.tsx': '6a5f6efb4f96330e78980b06ce4c65a7567dfcbc',
    'ui/src/pages/components/KindPanels.tsx': '9923dd29c2fa1ded68c95fbedaadd624bfd7d413',
    'ui/src/api/models.ts': '97e0f932194bfa945510fd3c4804c976b50f1fcf',
}
changed = [f for f, blob in reviewed.items()
           if subprocess.check_output(["git", "hash-object", f], text=True).strip() != blob]
print(f"{len(found)} snippet anchors", "ok" if not bad else f"MISSING in {bad}")
print("reviewed replacement sources", "ok" if not changed else f"REFRESH REQUIRED for {changed}")
assert not bad and not changed, "Re-read changed sources and refresh affected replacements before implementation"
PY
```

Expected on the pinned baseline: `12 snippet anchors ok` and `reviewed replacement sources ok`. A later merge deliberately fails the blob check: re-read changed files and update the snippets, tests and baseline hashes together; do not merely copy new hashes. In particular preserve confirmed recents, WebSocket head/cancellation/single-batch invalidation, `sweep.issuance` events and `issuancePoll`, credential resets including side caches, grouped failure retries, Task unscored counts/metric-drift indicator/templateEnvironment and loading/launch behavior, and per-run e2e homes. Task 25's whole-file `ui/playwright.config.ts` must remain the final baseline plus its team server/projects.
- The phase 3 backend plan (`docs/superpowers/plans/2026-10-04-hypothex-phase3-backend.md`) merged: the contract section 3 routes in `/api/openapi.json`, `RunRecord.owner`, `RunDetail.cleaned`, `Leaderboard.baselines`, the section 2 events, the `4401` close code, `hx serve --auth`, and `hx demo --with-team` (contract 11: owner `sv` admin and `alice` launch, two projects with notebook days and one weekly summary, baselines on `toy-classifier/toy-test`, 6 archived runs with artifacts, outbox entries in every state, one connected fake host, the local session token in `<home>/serve/server.json`).
- The mockups in `docs/mockups/phase3/` approved.
- The local pin includes the final credential-intent guards. Keep `Vars.generation` captured by `useAction.run`, checks before/after `send` and in `onSuccess`, and `shouldRetry` rejecting `AbortError`. Keep `launchSeeds`' captured generation around every `postLaunch` and `LaunchDialog`'s generation checks before progress and after awaiting the outcome, before invalidation/navigation/callbacks. Reusing an idempotency key never authorizes an old intent under a replacement principal. Preserve `ui/test/pages/authActions.test.tsx` and the replacement-credential regression in `ui/test/launch/launchApi.test.ts`. These interfaces need no Phase 3 replacement.

## Global Constraints

- Tooling: Bun only for JavaScript (`bun test`, `bun run typecheck`, `bun run build`, `bun run dev`, `bunx`); never npm, yarn or pnpm. `uv` only for Python (`uv run hx ...`, `uv run pytest`, `uv run sphinx-build`); never pip.
- Paths: commands run from `ui/` unless the step says "repo root" (`/Users/shreyasv/Desktop/code/research_dash`). Unit and component tests live in `ui/test/`, mirroring `ui/src/`; Playwright specs in `ui/e2e/`.
- Generated file: `ui/src/api/types.ts` comes from `bunx openapi-typescript` against a running hub, is checked in, and is never edited by hand. Response bodies are typed by `ui/src/api/models.ts`, the only hand-written copy of the contract shapes.
- Contract names (exact): `Scope` (`read | launch | admin`), `Principal` (the `/auth/me` body), `SessionRow`, `UserRow`, `PairingOffer` (`{offer_id, url, expires_at, qr}`), `NotifyStatus`, `OutboxEntry`, `ProjectRule`, `Digest`, `TaskChange`, `NotebookDay`, `RunChip`, `BaselineRow`, `StorageReport`, `StorageItem`, `CleanPolicy`, `CleanPlan`, `CleanResult`, `CleanedArtifact`; additive optional fields `RunRecord.owner?`, `RunDetail.cleaned?`, `Leaderboard.baselines?` (an older hub omits them). Event types `notebook.updated`, `run.artifacts_cleaned`, `storage.plan_created`, `storage.cleaned`, `notify.sent`, `notify.failed`, `digest.sent`, `auth.session_created`, `auth.session_revoked`.
- Routes (exact): UI routes `/pair`, `/settings`, `/storage`, `/n/$project`, `/n/$project/$day` (contract `/n/:project`, `/n/:project/:day`). API the UI calls: `GET /api/v1/auth/me`, `POST /api/v1/auth/ws-ticket`, `POST /api/v1/auth/pair`, `POST /api/v1/auth/pairings`, `GET /api/v1/auth/sessions`, `POST /api/v1/auth/sessions/{session_id}/revoke`, `GET /api/v1/auth/users`, `POST /api/v1/auth/users/{name}/disable`, `GET|POST|PUT /api/v1/projects/{project}/notebook[/{day}]`, `GET /api/v1/tasks/{project}/{task}/export`, `GET /api/v1/notify`, `POST /api/v1/notify/test`, `GET /api/v1/storage`, `POST /api/v1/storage/plan`, `POST /api/v1/storage/plans/{plan_id}/apply`, and `GET /api/v1/runs?owner=me`. `POST /api/v1/auth/logout`, `GET /api/v1/compare/export`, `GET /api/v1/projects/{project}/digest` and `POST .../digest/send` exist on the hub (Task 2's `types.ts` test checks them) but no screen uses them, so the client has no function for them.
- Auth (contract 1.10): every request sends `credentials: "same-origin"` (the `hx_session` cookie is `HttpOnly; SameSite=Strict`, so script never reads it). A current-generation `401` locks the credential provider and clears session queries/cursor; stale responses cannot affect a replacement credential. The root token-entry gate remains available, with pairing guidance in scoped mode. The event stream uses `websocketTicket` before every connect and sends its one-use result through `hx-ticket.<ticket>` alongside `hypothex.v1`; no credential appears in a URL. Current-generation `4401` locks and stops reconnecting. `/pair` renders without the header and never calls `/auth/me` or opens the event stream; it strips the `#<offer>.<secret>` fragment from the address bar (`history.replaceState`) before it sends anything, and sends the secret only in the `POST /api/v1/auth/pair` body.
- Scopes in the UI are hints, never the gate: the server decides (403 shows as an error line). Admin-only reads (`/auth/users`, `/notify`, `/storage`) are never requested for a non-admin principal, so a collaborator's console stays free of 403s; the header hides `storage` for them.
- Actions: every new write sends only `{command_id, ...its fields}`; `created_by`, `owner` and `author` are set by the server from the principal (contract 1.2, 7). Phase 1–2 actions keep `action()` (`command_id`, `created_by: "human"`). Writes go through the inherited `useAction` (`ui/src/pages/components/useAction.ts`) so retries reuse both the original `command_id` and credential-generation guard. Do not replace the hook, bypass it for retries, or strip its post-response/onSuccess checks. A new click after a credential change is a new user intent.
- One data layer: every request goes through `api.*` in `ui/src/api/client.ts`; no module builds its own `fetch` or route table. Downloads use a Blob made from authenticated `api.exportTask(...)` text; a remote anchor cannot carry the root bearer header.
- Live data: `notebook.updated` invalidates `["notebook", project]`; `run.artifacts_cleaned` invalidates the run families (narrowed) plus `["storage"]`; `storage.*` invalidates `STORAGE_EVENT_INVALIDATES` (`["storage"]`, `["runs"]`, `["run"]`); `notify.*` and `digest.sent` invalidate `["notify"]` (and `digest.sent` the project's notebook, where the summary is saved); `auth.*` invalidates `AUTH_EVENT_INVALIDATES` (`["auth", "sessions"]`, `["auth", "users"]`). Run events never invalidate `["storage"]` (a storage report walks every host; it refreshes on cleanup events and on demand). Export texts are keyed under `["leaderboard", project, task, "export", opts]`, so the run and mirror events that refresh a leaderboard refresh an open export menu with it (Copy never copies older numbers than the table shows).
- Copy (spec 8.1, terse UI): numbers and glyphs, labels of one or two words; explanations only in `title` tooltips; every state has its own glyph, never colour alone; monospace only for commands, paths, ids and tokens; times in UTC; a missing value is `—`; a not-yet-known cell is `·`. Glyphs: notify events `✓` finished, `✗` failed, `?` lost, `⊘` killed; outbox `✓` sent, `✗` failed, `…` pending/sending, `○` skipped; channel `●` set, `○` unset, `·` not configured; scope `r`/`l`/`a`; refused clean rows `⊘`; cleaned artifact `✕ <date> <bytes>`; baseline `◆`; digest counts `▲` started.
- CSS: each new component injects its own `<style data-hx="…">`; every selector is scoped (`.page …`, `.bar …`, `.pair …`); colours only through the theme tokens (`var(--ink)`, `var(--fail)`, …), so light and dark both work. `ui/src/pages/components/styles.ts` is not edited.
- HARD RULE, never touch real services or hosts: no test or step connects to a real Slack workspace, SMTP server, Tailscale tailnet, SSH or SLURM host, and nothing reads `~/.hypothex` or `~/.ssh`. Unit tests stub `fetch` (`mockApi`, `mockFetch`). Every `hx` a step starts uses a fresh temp home given on its own command line (`uv run hx --home "$H" ...`) and runs with `HYPOTHEX_SSH=false HYPOTHEX_SCP=false` set inline on that same command line, never by an earlier `export` (agent shells do not keep variables between calls). Waits are bounded (`for i in $(seq 60)`). Every port a step or check serves a hub on is asked from the OS for that run (`freePort()` in `ui/e2e/paths.ts`, or `uv run python -c` binding port 0), and the caller checks the hub's `GET /.well-known/hypothex/environment` identity before any other route. Playwright never reuses a server it did not start (`reuseExistingServer: false`); the team hub's local session token is read only from the fresh e2e home `serve-demo.ts` wrote.
- Build output: `bun run build` writes `src/hypothex/ui_dist/` (git-ignored); never commit it.
- Docs: Task 26 updates `docs/ui.rst` and its test (spec rule: every feature ships with docs).
- Commits: plain conventional commits (`feat(ui): …`, `test(ui): …`, `docs: …`). No `Co-Authored-By` lines and no AI mention in commits or PR text.

## Review Focus

Six failure modes the contract implies that no single screen's happy path covers; each test is in its owning task.

1. **A session is revoked while the UI is open.** The next HTTP call answers 401 and the open WebSocket closes with `4401` within 30 s (contract 8.11). The app must lock once, show the gate, and stop: no reconnect loop that hammers `POST /auth/ws-ticket` with 401s, no retry of the 401 (TanStack would otherwise retry three times). Tests: `a 401 locks the app; a 403 and a 404 do not` (Task 2; `useMe` never retries and `shouldRetry` never retries a 4xx), `close code 4401 locks and never reconnects` (Task 4), `a ticket request that answers 401 locks and stops the stream` (Task 4), `locked: the header keeps brand and theme only, the screen shows the gate` (Task 5).
2. **The pairing secret leaks into history or a request line.** The `/pair#p_….<secret>` fragment never reaches the server in a URL, but it stays in the address bar and the history entry unless the page removes it. The page must call `history.replaceState` before the first request, send the secret only in the POST body, and still work after a reload (the link is gone: `✗ link invalid or expired`). Test: `pair strips the fragment before posting and sends the secret only in the body` (Task 6).
3. **Two people edit one notebook day.** The second save gets 409 with the current day (contract 8.16). The page must keep the user's text, show both versions side by side, and `keep mine` must PUT with `base_hash = current.hash` (not the stale one, which would 409 forever). An append never conflicts. Tests: `a 409 keeps my text, shows theirs, and keep mine saves on their hash`, `use theirs drops my edit; without a seen editor the bar says only when` and `save replaces the day on the hash the edit started from, even after a live refresh` (Task 19).
4. **Apply on a stale or mistyped plan.** The plan expires after `plan_ttl_minutes`; a wrong number must never reach the server as a "close enough" confirm. `apply` stays disabled until a plan exists and is unexpired; the dialog's `delete` stays disabled until the typed text equals the plan's displayed number (`412.3`); the request carries `plan.total_bytes` exactly; a `400 CleanRefusedError` shows its message and the plan is kept for a new dry run. Tests: `delete stays disabled until the typed number matches; apply sends the exact bytes`, `an expired plan disables apply` and `a refused apply shows the error and keeps the plan` (Task 16).
5. **A collaborator opens Settings.** A `launch` principal must see only their own sessions and an add-device panel limited to `read`/`launch`, and the page must not request `/auth/users` or `/notify` (403s in the console, contract 1.12). Test: `a collaborator sees own sessions and add device only; admin routes are never requested` (Task 13).
6. **A hub without scoped auth routes.** `/auth/me` answers 404: hide the collaboration chip/storage UI and keep scoped owner checks permissive. Retain the root credential gate and ticket transport; 404 does not prove transport auth is off. Test the root gate and fresh-ticket socket path independently of scoped feature discovery, plus `a hub without /auth/me: no chip, no storage, settings link kept` (Task 7).

---

## File Structure

```
ui/
  src/
    api/models.ts                 phase 3 shapes: principal, sessions, users, pairing, notify, notebook, baselines, export, storage, digest (Task 1)
    api/types.ts                  GENERATED OpenAPI paths, regenerated with the phase 3 routes   (Task 2)
    api/auth.ts                   existing credential provider plus PrincipalContext, usePrincipal, authOn, isAdmin (Task 2)
    api/client.ts                 credential-aware requests, 401 → lock, requestText, ROUTES + api.* (Task 2)
    api/queries.ts                keys, useMe/useSessions/useUsers/useNotify/useNotebook*/useStorage/useExportText, lists (Task 3)
    api/events.ts                 phase 3 events, async ticket URL, 4401, enabled flag             (Task 4)
    api/notebookEditors.ts        last editor of a notebook day, from notebook.updated events      (Task 4)
    main.tsx                      no event stream on /pair                                         (Task 5)
    router.tsx                    AppShell (gate, bare /pair, PrincipalContext); /pair /settings /storage /n/… (Tasks 5, 6, 13, 17, 20)
    pages/components/AuthGate.tsx the 401 line                                                     (Task 5)
    pages/components/pairing.ts   fragment parse, device name, pair errors                         (Task 6)
    pages/Pair.tsx                the pair page                                                    (Task 6)
    shell/Header.tsx              notebook, storage, ⚙, @user chip; locked header                  (Task 7)
    pages/components/links.tsx    hrefs.notebook/settings/storage; isAppPath                       (Task 7)
    pages/components/owner.ts     ownerLabel, mayStop                                              (Task 8)
    pages/components/StatusLine.tsx  @owner                                                        (Task 8)
    pages/components/RunActions.tsx  owner-only Stop and Cancel                                    (Task 8)
    pages/components/OverviewLists.tsx pages/Overview.tsx  @owner on running rows; `mine` toggle   (Task 8)
    settings/model.ts             headline, glyphs, ages, countdown, scopes, rows                  (Task 9)
    settings/styles.ts SessionsPanel.tsx UsersPanel.tsx                                            (Task 10)
    settings/AddDevice.tsx        scope and user pickers, QR, URL, countdown                       (Task 11)
    settings/NotifyPanel.tsx      channels, test, rules, digest line, recent sends                 (Task 12)
    pages/Settings.tsx            the Settings page                                                (Task 13)
    storage/model.ts              bytes, bars, largest, cleanable estimate, confirm text, plan facts (Task 14)
    storage/styles.ts StorageBars.tsx LargestTable.tsx                                             (Task 15)
    storage/CleanPanel.tsx        policy, dry run, plan table, confirm dialog, result               (Task 16)
    pages/Storage.tsx             the Storage page                                                 (Task 17)
    notebook/model.ts             entries, run links, chips, digest entries, line diff, conflict   (Task 18)
    panels/Markdown.tsx           renderMarkdown(text, inline?) exported                           (Task 18)
    notebook/styles.ts DayView.tsx  entries with chips, + entry, edit, 409 view                    (Task 19)
    pages/Notebook.tsx            day list + day                                                   (Task 20)
    pages/components/exportFormats.ts ExportMenu.tsx  formats, file names, preview, menu             (Task 21)
    charts/Glyphs.tsx charts/charts.css panels/Leaderboard.tsx panels/panels.css  baseline rows    (Task 22)
    pages/components/PanelGrid.tsx pages/components/baselines.ts pages/Task.tsx  aside + baselines (Task 23)
    pages/components/WhereList.tsx cleaned artifacts struck through                                (Task 24)
  test/
    setup.ts                      unlock() after each test                                         (Task 2)
    api/phase3-fixtures.ts phase3-client.test.ts types.test.ts phase3-queries.test.tsx phase3-events.test.ts notebookEditors.test.ts (Tasks 1–4)
    shell/AppShell.test.tsx pages/authGate.test.tsx pages/pairing.test.ts pages/Pair.test.tsx router.test.tsx (Tasks 5, 6)
    shell/Header.test.tsx pages/links.test.tsx                                                     (Task 7)
    pages/owner.test.tsx                                                                           (Task 8)
    settings/model.test.ts panels.test.tsx addDevice.test.tsx notifyPanel.test.tsx pages/Settings.test.tsx (Tasks 9–13)
    storage/model.test.ts parts.test.tsx cleanPanel.test.tsx pages/Storage.test.tsx               (Tasks 14–17)
    notebook/model.test.ts dayView.test.tsx pages/Notebook.test.tsx panels/Markdown.test.tsx      (Tasks 18–20)
    pages/exportMenu.test.tsx panels/Leaderboard.test.tsx pages/Task.test.tsx panelGrid.test.tsx   (Tasks 21–23)
    pages/whereList.test.tsx                                                                       (Task 24)
  e2e/paths.ts serve-demo.ts fixtures.ts team-fixtures.ts team.spec.ts team-edit.spec.ts playwright.config.ts README.md (Task 25)
docs/ui.rst  tests/test_docs_ui.py                                                                 (Task 26)
```

Each file has one job: `api/` talks to the server, `settings/`, `storage/` and `notebook/` own their screens' parts (pure `model.ts` modules hold the arithmetic, `.tsx` files draw), `pages/` composes one screen, `router.tsx` maps URLs to screens.

---

## Group 1: Models, auth store, client, queries, live events (Tasks 1–4)

Gives the UI typed access to every phase 3 hub route the screens use and keeps them live. `models.ts` gets the contract shapes (the new routes return plain dicts or pydantic models; `types.ts` knows only their paths). `api/auth.ts` retains the token baseline credential state and adds principal context. `client.ts` retains bearer/cookie selection and credential-generation guards, and adds authenticated export text. Event tickets use the baseline WebSocket subprotocol flow. `queries.ts` adds keys, read hooks and four invalidation lists; `events.ts` maps the new events and handles `4401`. The backend plan must be merged before Task 2 Step 3 (the phase 3 routes must be in `/api/openapi.json`).

### Task 1: Phase 3 models and typed fixtures

All models are additive to the prerequisite. Retain `PanelData.max_points?: number | null` (curves, 2–500, absent/null default 500), `RunDetail.metric_names`, and the generated OpenAPI constraint; regenerating types must not remove them. The Run page keeps `runViewPanels(kindSpecs, traceCount, metricNames)`: explicit displayed metric lists exclude reserved sweep/step series, chunk at 100 references, send `metrics: []` when empty, and preserve each panel's `max_points ?? 500`. Terminal histories spanning more than 100 metrics are split rather than truncated. No Phase 3 task replaces that path.

**Files:**
- Modify: `ui/src/api/models.ts` (end of `RunRecord` after `gpus_requested`; end of `RunDetail` after `host_state`; end of `Leaderboard` after `value_format`; end of `RunsQuery` after `environment_id`; append at end of file)
- Create: `ui/test/api/phase3-fixtures.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces (in `ui/src/api/models.ts`, re-exported by `ui/src/api/client.ts` through `export type * from "./models"`):
  - `type Scope = "read" | "launch" | "admin"`; `type AuthClient = "browser" | "cli" | "agent" | "host" | "local"`
  - `interface Principal { user; scope: Scope; scopes: Scope[]; session_id: string | null; client: AuthClient; auth: "on" | "off"; public_url: string | null }` (the `/auth/me` body)
  - `interface SessionRow { id; user; scope: Scope; client: AuthClient; device; created_at; last_seen_at; expires_at; revoked_at: string | null }`
  - `interface UserRow { name; role: Scope; created_at; created_by; disabled_at: string | null }`
  - `interface PairingRequest { user?: string; new_user?: boolean; scope: Scope; ttl_seconds?: number; client_hint?: string }`; `interface PairingOffer { offer_id; url; expires_at; qr }`
  - `interface PairRequest { offer_id; secret; device; client: "browser" | "cli" | "agent" | "host" }`; `interface PairResult { user; scope: Scope; scopes: Scope[]; session_id: string; token?: string }`
  - `type NotifyEvent = "finished" | "failed" | "lost" | "killed"`; `type Channel = "slack" | "email"`; `type Weekday = "mon" | … | "sun"`
  - `interface ProjectRule { events: NotifyEvent[]; channels: Channel[]; min_seconds: number; fold_sweeps: boolean }`
  - `interface DigestSettings { enabled; weekday: Weekday; hour; timezone: string | null; channels: Channel[]; projects: string[] | "all"; save_to_notebook; top_notes }`
  - `interface ChannelStatus { configured: boolean; env: string | null; set: boolean; host?: string; to?: string[] }`
  - `interface NotifyStatus { channels: { slack: ChannelStatus; email: ChannelStatus }; projects: Record<string, ProjectRule>; default: ProjectRule | null; digest: DigestSettings; recent: OutboxEntry[] }`
  - `type NoticeKind = "run" | "sweep" | "digest" | "test"`; `interface Notice { id; kind; project: string | null; run_id?: string | null; sweep_id?: string | null; status?: string | null; title; lines: string[]; url: string | null; created_at }`
  - `type OutboxStatus = "pending" | "sending" | "sent" | "failed" | "skipped"`; `interface OutboxEntry { id; channel: Channel; notice: Notice; status: OutboxStatus; attempts; next_at; last_error: string | null; created_at; sent_at: string | null }`; `interface NotifyTestResult { ok: boolean; error_class: string | null }`
  - `interface RunChip { run_id; status: RunStatus | null; task: string | null; label; primary: number | null }`; `interface NotebookDayInfo { day; bytes; entries }`; `interface NotebookDay { project; day; text; hash; runs: RunChip[]; updated_at: string | null }`
  - `interface BaselineRow { name; values: Record<string, number>; std: Record<string, number>; source; source_url; version_match: Record<string, boolean>; primary: number | null; delta_vs_best: number | null }`
  - `type ExportFormat = "latex" | "markdown" | "csv"`; `type NoiseMode = "both" | "seed" | "test" | "none"`; `interface ExportOptions { format: ExportFormat; metrics?: string[]; noise?: NoiseMode; digits?: number; percent?: boolean; top?: number; groups?: string[]; baselines?: boolean; caption?: string; label?: string; standalone?: boolean }`
  - `type StorageKind = "run" | "artifact" | "pulled"`; `interface StorageItem`, `interface StorageReport`, `interface CleanPolicy`, `interface CleanItem`, `interface CleanPlan`, `interface CleanResult`, `interface CleanedArtifact` (contract 1.9, fields exact)
  - `interface TaskChange`, `interface NoteItem`, `interface SweepLine`, `interface Digest` (contract 1.8, fields exact)
  - Optional additions: `RunRecord.owner?: string | null`, `RunDetail.cleaned?: CleanedArtifact[]`, `Leaderboard.baselines?: BaselineRow[]`, `RunsQuery.owner?: string` (`"me"` = the caller).
  - Test fixtures in `ui/test/api/phase3-fixtures.ts`: `NOW` (`2026-10-04T14:32:00Z` in ms), `ME_ADMIN`, `ME_ALICE`, `ME_OFF`, `SESSIONS`, `USERS`, `OFFER`, `NOTIFY`, `OUTBOX`, `NOTEBOOK_DAYS`, `NOTEBOOK_DAY`, `BASELINES`, `STORAGE_REPORT`, `CLEAN_PLAN`, `CLEAN_RESULT`, `CLEANED`, `DIGEST`.

The test for this task is the type checker: the fixtures are typed against the models, so `bun run typecheck` fails while a model is missing or misshaped.

- [ ] **Step 1: Write the typed fixtures (the failing test)**

Create `ui/test/api/phase3-fixtures.ts`:

```ts
/**
 * Phase 3 API bodies for the unit tests (phase 3 contract sections 1.3-1.10 and 3).
 *
 * Typed against `src/api/models.ts`, so `bun run typecheck` fails when a model drifts from
 * the contract. Numbers match docs/mockups/phase3/data.js where both have them: owner `sv`
 * (admin) and collaborator `alice` (launch) share the hub `hub.tail1234.ts.net`; the storage
 * report is 1.84 TB over four hosts; the clean plan deletes 412.3 GB in 3 paths on 3 hosts.
 * `NOW` is the instant every age and countdown in the tests is measured from.
 */
import type {
  BaselineRow,
  CleanedArtifact,
  CleanPlan,
  CleanResult,
  Digest,
  NotebookDay,
  NotebookDayInfo,
  NotifyStatus,
  OutboxEntry,
  PairingOffer,
  Principal,
  SessionRow,
  StorageItem,
  StorageReport,
  UserRow,
} from "../../src/api/models";

/** 2026-10-04T14:32:00Z. */
export const NOW = Date.parse("2026-10-04T14:32:00Z");

const HUB = "https://hub.tail1234.ts.net";

export const ME_ADMIN: Principal = {
  user: "sv",
  scope: "admin",
  scopes: ["read", "launch", "admin"],
  session_id: "s_4b1e09c2d7a3",
  client: "browser",
  auth: "on",
  public_url: HUB,
};

export const ME_ALICE: Principal = {
  user: "alice",
  scope: "launch",
  scopes: ["read", "launch"],
  session_id: "s_91d0aa3f62c8",
  client: "browser",
  auth: "on",
  public_url: HUB,
};

/** Every request of a hub with auth off runs as the local owner (contract 1.10). */
export const ME_OFF: Principal = {
  user: "local",
  scope: "admin",
  scopes: ["read", "launch", "admin"],
  session_id: null,
  client: "local",
  auth: "off",
  public_url: null,
};

function session(
  id: string,
  user: string,
  scope: SessionRow["scope"],
  client: SessionRow["client"],
  device: string,
  lastSeen: string,
  revoked: string | null = null,
): SessionRow {
  return {
    id,
    user,
    scope,
    client,
    device,
    created_at: "2026-09-30T10:22:00Z",
    last_seen_at: lastSeen,
    expires_at: "2026-12-29T10:22:00Z",
    revoked_at: revoked,
  };
}

/** Five live sessions of three users, plus one revoked session that no table shows. */
export const SESSIONS: SessionRow[] = [
  session("s_4b1e09c2d7a3", "sv", "admin", "browser", "MacBook", "2026-10-04T14:30:00Z"),
  session("s_7f20c1b9e4d0", "sv", "admin", "cli", "lab-laptop", "2026-10-04T13:32:00Z"),
  session("s_91d0aa3f62c8", "alice", "launch", "browser", "MacBook Air", "2026-10-04T14:20:00Z"),
  session("s_c3e8f0172ab5", "alice", "launch", "agent", "claude", "2026-10-04T11:32:00Z"),
  session("s_0d5a7e91b2f4", "bo", "read", "browser", "iPad", "2026-10-02T14:32:00Z"),
  session("s_aa11bb22cc33", "bo", "read", "browser", "old phone", "2026-10-01T09:00:00Z", "2026-10-02T16:40:00Z"),
];

export const USERS: UserRow[] = [
  { name: "sv", role: "admin", created_at: "2026-09-12T08:01:00Z", created_by: "local", disabled_at: null },
  { name: "alice", role: "launch", created_at: "2026-09-30T10:22:00Z", created_by: "sv", disabled_at: null },
  { name: "bo", role: "read", created_at: "2026-10-02T16:40:00Z", created_by: "sv", disabled_at: null },
  { name: "dan", role: "launch", created_at: "2026-09-14T09:00:00Z", created_by: "sv", disabled_at: "2026-09-20T09:00:00Z" },
];

/** A pairing link made at NOW - 1 s: 299 s left. */
export const OFFER: PairingOffer = {
  offer_id: "p_3f9a2c71e0b4",
  url: `${HUB}/pair#p_3f9a2c71e0b4.kX2mQ9vR7tLw4pYc8zNf1aJ3sD6hG0eUiBqTnW5oVyM`,
  expires_at: "2026-10-04T14:36:59Z",
  qr: "█▀▀▀▀▀█ ▄ █▀▀▀▀▀█\n█ ███ █ ▀ █ ███ █\n▀▀▀▀▀▀▀ ▀ ▀▀▀▀▀▀▀",
};

function outbox(
  id: string,
  channel: OutboxEntry["channel"],
  kind: OutboxEntry["notice"]["kind"],
  target: { run_id?: string; sweep_id?: string },
  status: OutboxEntry["status"],
  attempts: number,
  lastError: string | null,
  createdAt: string,
): OutboxEntry {
  return {
    id,
    channel,
    notice: {
      id: id.slice(0, 16),
      kind,
      project: "deepretro",
      run_id: target.run_id ?? null,
      sweep_id: target.sweep_id ?? null,
      status: "finished",
      title: kind === "digest" ? "deepretro 2026-W40" : `✓ deepretro ${target.run_id ?? target.sweep_id ?? ""}`,
      lines: [],
      url: null,
      created_at: createdAt,
    },
    status,
    attempts,
    next_at: createdAt,
    last_error: lastError,
    created_at: createdAt,
    sent_at: status === "sent" ? createdAt : null,
  };
}

/** Newest first, as `recent()` returns them; one entry in every state. */
export const OUTBOX: OutboxEntry[] = [
  outbox("e1a2b3c4d5e6f701", "slack", "run", { run_id: "01J8Z3K7-clf-a1b2" }, "sent", 1, null, "2026-10-04T14:02:00Z"),
  outbox("e1a2b3c4d5e6f702", "slack", "sweep", { sweep_id: "s-7f3a" }, "sent", 1, null, "2026-10-04T13:40:00Z"),
  outbox(
    "e1a2b3c4d5e6f703",
    "email",
    "run",
    { run_id: "01J8Z2QF-clf-c2b9" },
    "skipped",
    0,
    "unset:HYPOTHEX_SMTP_PASSWORD",
    "2026-10-04T13:12:00Z",
  ),
  outbox("e1a2b3c4d5e6f704", "slack", "run", { run_id: "01J8YX0M-tr-77fe" }, "failed", 3, "http_404", "2026-10-04T12:55:00Z"),
  outbox("e1a2b3c4d5e6f705", "slack", "run", { run_id: "01J8YT4C-tr-9d0c" }, "pending", 2, "http_429", "2026-10-04T12:31:00Z"),
  outbox("e1a2b3c4d5e6f706", "slack", "digest", {}, "sent", 1, null, "2026-10-04T09:00:00Z"),
];

export const NOTIFY: NotifyStatus = {
  channels: {
    slack: { configured: true, env: "HYPOTHEX_SLACK_WEBHOOK", set: true },
    email: { configured: true, env: "HYPOTHEX_SMTP_PASSWORD", set: false, host: "smtp.lab.org", to: ["sv@lab.org"] },
  },
  projects: {
    deepretro: { events: ["finished", "failed", "lost"], channels: ["slack", "email"], min_seconds: 300, fold_sweeps: true },
    "rxn-forward": { events: ["failed", "lost", "killed"], channels: ["slack"], min_seconds: 0, fold_sweeps: true },
  },
  default: null,
  digest: {
    enabled: true,
    weekday: "sun",
    hour: 9,
    timezone: "Europe/London",
    channels: ["slack"],
    projects: "all",
    save_to_notebook: true,
    top_notes: 5,
  },
  recent: OUTBOX,
};

export const NOTEBOOK_DAYS: NotebookDayInfo[] = [
  { day: "2026-10-04", bytes: 512, entries: 3 },
  { day: "2026-10-03", bytes: 3021, entries: 5 },
  { day: "2026-09-29", bytes: 880, entries: 1 },
];

/**
 * The weekly summary the hub saved at 09:00 (exactly `render_digest_markdown`'s shape, backend
 * Task 18: `**<week>** · <headline>`, then `- <task> before→after ▲ · N runs`), then two entries;
 * one chip names an unknown run.
 */
export const NOTEBOOK_TEXT = [
  "## 2026-10-04T09:00:02Z — digest",
  "",
  "**2026-W40** · ▲12 ✓9 ✗2 ?1 · 41.2 GPU-h $86.5 · uspto50k-topk 0.598→0.613 ▲",
  "",
  "- uspto50k-topk 0.598→0.613 ▲ · 12 runs",
  "",
  "## 2026-10-04T09:14:31Z — human:alice",
  "Beam 10 holds at lr 3e-4: [[run:01J8Z3K7-clf-a1b2]] is inside the best band.",
  "",
  "## 2026-10-04T11:02:41Z — human:sv",
  "Tokenizer, not data: [[run:01J8YX0M-tr-77fe]] fails at load. Old [[run:01J7AAAA-old-0001]] is gone.",
  "",
].join("\n");

export const NOTEBOOK_DAY: NotebookDay = {
  project: "deepretro",
  day: "2026-10-04",
  text: NOTEBOOK_TEXT,
  hash: "sha256:9f2c41d07be3a5e8",
  runs: [
    { run_id: "01J8Z3K7-clf-a1b2", status: "finished", task: "uspto50k-topk", label: "lr 3e-4, beam 10", primary: 0.9131 },
    { run_id: "01J8YX0M-tr-77fe", status: "failed", task: "uspto50k-top1", label: "tokenizer v2", primary: null },
    { run_id: "01J7AAAA-old-0001", status: null, task: null, label: "01J7AAAA-old-0001", primary: null },
  ],
  updated_at: "2026-10-04T11:02:41Z",
};

/**
 * Two paper baselines on the toy task (`accuracy`, `macro_f1`, versions `v1`): one matches
 * our metric version, one was published under another and scores above our best (0.9222),
 * which must never make it "best".
 */
export const BASELINES: BaselineRow[] = [
  {
    name: "sklearn SVC",
    values: { "accuracy/value": 0.91, "macro_f1/value": 0.905 },
    std: {},
    source: "arXiv:2403.12345",
    source_url: "https://arxiv.org/abs/2403.12345",
    version_match: { accuracy: true, macro_f1: true },
    primary: 0.91,
    delta_vs_best: 0.012222,
  },
  {
    name: "TabPFN",
    values: { "accuracy/value": 0.93 },
    std: { "accuracy/value": 0.004 },
    source: "doi:10.48550/arXiv.2207.01848",
    source_url: "https://doi.org/10.48550/arXiv.2207.01848",
    version_match: { accuracy: false },
    primary: 0.93,
    delta_vs_best: -0.007778,
  },
];

const GB = 1e9;

function item(over: Partial<StorageItem> & Pick<StorageItem, "run_id" | "host" | "bytes">): StorageItem {
  return {
    project: "deepretro",
    environment_id: over.host === "local" ? "env-hub" : `env-${over.host}`,
    kind: "artifact",
    artifact_kind: "checkpoint",
    path: `/scratch/sv/hx/runs/${over.run_id}/artifacts/ckpt`,
    files: 6,
    mtime: Date.parse("2026-08-20T10:00:00Z") / 1000,
    exists: true,
    archived: true,
    starred: false,
    status: "finished",
    ended_at: "2026-08-20T10:00:00Z",
    ...over,
  };
}

/** Items of the report: archived and old, starred, recent, remote and local, one pulled copy, whole run folders. */
export const STORAGE_ITEMS: StorageItem[] = [
  item({ run_id: "01J7QK2D-tr-5e9a", host: "mccleary", bytes: 96.4 * GB }),
  item({ run_id: "01J8B0MZ-tr-a3c1", host: "gpu1", bytes: 88.1 * GB, archived: false, starred: true }),
  item({ run_id: "01J7MZ81-tr-0a6d", host: "gpu1", bytes: 74 * GB }),
  item({
    run_id: "01J8D7HC-tr-52c9",
    host: "local",
    bytes: 44.2 * GB,
    kind: "pulled",
    artifact_kind: null,
    path: "/Users/sv/.hypothex/store/deepretro/runs/01J8D7HC-tr-52c9/pulled/ckpt",
    archived: false,
    ended_at: "2026-09-28T10:00:00Z",
  }),
  item({
    run_id: "01J7R1C9-tr-4d2e",
    project: "rxn-forward",
    host: "local",
    bytes: 21.8 * GB,
    kind: "run",
    artifact_kind: null,
    path: "/Users/sv/.hypothex/store/rxn-forward/runs/01J7R1C9-tr-4d2e",
  }),
  item({ run_id: "01J7KD0P-tr-8b5f", host: "mccleary", bytes: 39.9 * GB, artifact_kind: "predictions" }),
  item({
    run_id: "01J7TOY0-clf-0001",
    project: "toy-classifier",
    host: "local",
    bytes: 186 * GB,
    kind: "run",
    artifact_kind: null,
    path: "/Users/sv/.hypothex/store/toy-classifier/runs/01J7TOY0-clf-0001",
    archived: false,
  }),
];

export const STORAGE_REPORT: StorageReport = {
  items: STORAGE_ITEMS,
  by_project: { deepretro: 1120 * GB, "rxn-forward": 534 * GB, "toy-classifier": 186 * GB },
  by_host: { gpu1: 812 * GB, local: 484 * GB, mccleary: 371 * GB, dgx: 173 * GB },
  by_kind: { artifact: 1520 * GB, run: 214 * GB, pulled: 106 * GB },
  total_bytes: 1840 * GB,
  errors: [{ host: "dgx", error: "HostUnavailableError: dgx is stale" }],
  generated_at: "2026-10-04T14:31:00Z",
};

export const CLEAN_PLAN: CleanPlan = {
  plan_id: "cp-8e41c0d2",
  policy: { archived: true, older_than_days: 30, kinds: ["checkpoint"], projects: null, hosts: null, include_pulled: true },
  items: [
    {
      project: "deepretro",
      run_id: "01J7QK2D-tr-5e9a",
      host: "mccleary",
      environment_id: "env-mccleary",
      kind: "artifact",
      artifact_kind: "checkpoint",
      path: "/gpfs/sv/hx/runs/01J7QK2D-tr-5e9a/artifacts/ckpt",
      bytes: 96.4 * GB,
      mtime: 1755684000,
      reason: "archived 41d, checkpoint",
    },
    {
      project: "deepretro",
      run_id: "01J7MZ81-tr-0a6d",
      host: "gpu1",
      environment_id: "env-gpu1",
      kind: "artifact",
      artifact_kind: "checkpoint",
      path: "/scratch/sv/hx/runs/01J7MZ81-tr-0a6d/artifacts/ckpt",
      bytes: 74 * GB,
      mtime: 1755684000,
      reason: "archived 52d, checkpoint",
    },
    {
      project: "rxn-forward",
      run_id: "01J7R1C9-tr-4d2e",
      host: "local",
      environment_id: "env-hub",
      kind: "pulled",
      artifact_kind: null,
      path: "/Users/sv/.hypothex/store/rxn-forward/runs/01J7R1C9-tr-4d2e/pulled/ckpt",
      bytes: 241.9 * GB,
      mtime: 1755684000,
      reason: "archived 44d, pulled",
    },
  ],
  refused: [
    { path: "/raid/sv/hx/runs/01J7T3VE-tr-d1f4/artifacts/ckpt", run_id: "01J7T3VE-tr-d1f4", reason: "used by 01J8E5WQ-tr-c7d4" },
    { path: "/Users/sv/code/deepretro", run_id: "01J6ZZ10-tr-e2d5", reason: "protected" },
  ],
  total_bytes: 412_300_000_000,
  created_at: "2026-10-04T14:32:00Z",
  expires_at: "2026-10-04T15:32:00Z",
  created_by: "human:sv",
};

export const CLEAN_RESULT: CleanResult = {
  plan_id: "cp-8e41c0d2",
  deleted: CLEAN_PLAN.items.slice(0, 2),
  skipped: [{ path: "/Users/sv/.hypothex/store/rxn-forward/runs/01J7R1C9-tr-4d2e/pulled/ckpt", reason: "changed since plan" }],
  freed_bytes: 409_800_000_000,
  errors: [],
};

export const CLEANED: CleanedArtifact[] = [
  {
    path: "/scratch/sv/hx/runs/01J7P2KD-tr-3a90/artifacts/ckpt/step-40000.pt",
    bytes: 4.2 * GB,
    at: "2026-10-04T14:33:10Z",
    actor: "human:sv",
    plan_id: "cp-8e41c0d2",
  },
];

export const DIGEST: Digest = {
  project: "deepretro",
  since: "2026-09-27T09:00:00Z",
  until: "2026-10-04T09:00:00Z",
  week: "2026-W40",
  counts: { started: 12, finished: 9, failed: 2, lost: 1, killed: 0, queued: 0 },
  by_owner: { "agent:claude@alice": 7, "human:sv": 3, "human:alice": 2 },
  cost: { gpu_hours: 41.2, gpu_usd: 45.3, api_usd: 41.2, total_usd: 86.5 },
  tasks: [
    {
      task: "uspto50k-topk",
      primary: "top10/value",
      before: 0.598,
      after: 0.613,
      best_label: "lr 3e-4, beam 10",
      best_group_id: "g-7e3f",
      new_best: true,
      n_new_runs: 9,
    },
  ],
  notes: [
    {
      source: "notebook",
      run_id: null,
      day: "2026-10-03",
      author: "human:alice",
      at: "2026-10-03T16:10:00Z",
      text: "beam 10 holds",
    },
  ],
  sweeps: [{ id: "s-7f3a", n_runs: 27, best: { params: { lr: "3e-4", beam: "10" }, mean: 0.613 } }],
  headline: "12 runs, uspto50k-topk 0.598 → 0.613",
};
```

- [ ] **Step 2: Run the type checker to verify it fails**

Run: `bun run typecheck`
Expected: FAIL, starting with
```
test/api/phase3-fixtures.ts(11,3): error TS2305: Module '"../../src/api/models"' has no exported member 'BaselineRow'.
test/api/phase3-fixtures.ts(12,3): error TS2305: Module '"../../src/api/models"' has no exported member 'CleanedArtifact'.
```

- [ ] **Step 3: Add the models**

In `ui/src/api/models.ts`, replace

```ts
  sweep_id?: string | null;
  gpus_requested?: number;
}
```

with

```ts
  sweep_id?: string | null;
  gpus_requested?: number;
  /**
   * Phase 3 (contract 1.2): the user name of the principal that created the run; null with
   * auth off or before phase 3 (such runs count as the hub owner's).
   */
  owner?: string | null;
}
```

Replace

```ts
  host_state?: ConnState | null;
}
```

with

```ts
  host_state?: ConnState | null;
  /** Phase 3 (contract 1.9): artifacts a storage cleanup deleted; absent before phase 3. */
  cleaned?: CleanedArtifact[];
}
```

Replace

```ts
  value_format?: string;
}
```

with

```ts
  value_format?: string;
  /** Phase 3 (contract 1.5): published results; never a seed group, never best. */
  baselines?: BaselineRow[];
}
```

Replace

```ts
  environment_id?: string;
}
```

with

```ts
  environment_id?: string;
  /** Phase 3: runs owned by one user; `"me"` is the caller (`GET /api/v1/runs?owner=me`). */
  owner?: string;
}
```

Append to the end of the file:

```ts

// phase 3: team and output (phase 3 contract 1.2-1.10, 3) ---------------------------------
/** Scopes, ordered: `admin` covers `launch` covers `read` (`hypothex.auth.scopes.Scope`). */
export type Scope = "read" | "launch" | "admin";

/** How a session was made (`hypothex.auth.store.Client`). */
export type AuthClient = "browser" | "cli" | "agent" | "host" | "local";

/**
 * `GET /api/v1/auth/me`: who the hub thinks is asking. With auth off every request runs as
 * the local owner: `{user: "local", scope: "admin", auth: "off"}`.
 */
export interface Principal {
  user: string;
  scope: Scope;
  /** Every scope `scope` covers, e.g. `["read", "launch"]`. */
  scopes: Scope[];
  session_id: string | null;
  client: AuthClient;
  auth: "on" | "off";
  /** The hub's public URL (pairing links, Secure cookie); null when unset. */
  public_url: string | null;
}

/** One revocable session (`hypothex.auth.store.Session`); its secret never leaves the hub. */
export interface SessionRow {
  /** `s_<12 hex>`. */
  id: string;
  user: string;
  scope: Scope;
  client: AuthClient;
  device: string;
  created_at: string;
  last_seen_at: string;
  expires_at: string;
  revoked_at: string | null;
}

/** `GET /api/v1/auth/users` (admin). */
export interface UserRow {
  name: string;
  role: Scope;
  created_at: string;
  created_by: string;
  disabled_at: string | null;
}

/** Body of `POST /api/v1/auth/pairings`; the hub refuses a scope above the caller's (403). */
export interface PairingRequest {
  user?: string;
  new_user?: boolean;
  scope: Scope;
  /** At most 300. */
  ttl_seconds?: number;
  client_hint?: string;
}

/** A one-time pairing link: secret after the `#`, valid until `expires_at`, one use. */
export interface PairingOffer {
  /** `p_<12 hex>`. */
  offer_id: string;
  url: string;
  expires_at: string;
  /** The link as a QR code in UTF-8 half blocks (`qr_text`), no ANSI. */
  qr: string;
}

/** Body of `POST /api/v1/auth/pair` (public). */
export interface PairRequest {
  offer_id: string;
  secret: string;
  device: string;
  client: "browser" | "cli" | "agent" | "host";
}

/** Answer of `POST /api/v1/auth/pair`; a browser gets the cookie and no `token`. */
export interface PairResult {
  user: string;
  scope: Scope;
  scopes: Scope[];
  session_id: string;
  token?: string;
}

export type NotifyEvent = "finished" | "failed" | "lost" | "killed";
export type Channel = "slack" | "email";
export type Weekday = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";

/** Which runs of one project notify, and where (`hypothex.core.settings.ProjectRule`). */
export interface ProjectRule {
  events: NotifyEvent[];
  channels: Channel[];
  /** Finished runs shorter than this are skipped; failed, lost and killed always notify. */
  min_seconds: number;
  /** One notice per sweep once it has no active run left. */
  fold_sweeps: boolean;
}

export interface DigestSettings {
  enabled: boolean;
  weekday: Weekday;
  hour: number;
  /** IANA name; null = the hub's local zone. */
  timezone: string | null;
  channels: Channel[];
  projects: string[] | "all";
  save_to_notebook: boolean;
  top_notes: number;
}

/** One channel in `GET /api/v1/notify`: `set` says the variable has a value; the value never comes. */
export interface ChannelStatus {
  configured: boolean;
  /** The environment variable NAME holding the secret. */
  env: string | null;
  set: boolean;
  host?: string;
  to?: string[];
}

/** `GET /api/v1/notify` (admin). */
export interface NotifyStatus {
  channels: { slack: ChannelStatus; email: ChannelStatus };
  projects: Record<string, ProjectRule>;
  /** Rule for unlisted projects; null = opt-in only. */
  default: ProjectRule | null;
  digest: DigestSettings;
  recent: OutboxEntry[];
}

export type NoticeKind = "run" | "sweep" | "digest" | "test";

export interface Notice {
  id: string;
  kind: NoticeKind;
  project: string | null;
  run_id?: string | null;
  sweep_id?: string | null;
  status?: string | null;
  title: string;
  lines: string[];
  url: string | null;
  created_at: string;
}

export type OutboxStatus = "pending" | "sending" | "sent" | "failed" | "skipped";

/** One notice for one channel in the hub's outbox; `last_error` is a redacted error class. */
export interface OutboxEntry {
  id: string;
  channel: Channel;
  notice: Notice;
  status: OutboxStatus;
  attempts: number;
  next_at: string;
  /** e.g. `http_429`, `smtp_535`, `timeout`, `unset:HYPOTHEX_SLACK_WEBHOOK`. */
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
}

/** `POST /api/v1/notify/test`. */
export interface NotifyTestResult {
  ok: boolean;
  error_class: string | null;
}

/** A `[[run:<id>]]` link resolved by the hub; `status: null` = no such run. */
export interface RunChip {
  run_id: string;
  status: RunStatus | null;
  task: string | null;
  label: string;
  primary: number | null;
}

/** One row of `GET /api/v1/projects/{project}/notebook`, newest first. */
export interface NotebookDayInfo {
  /** `YYYY-MM-DD`. */
  day: string;
  bytes: number;
  entries: number;
}

/** `GET .../notebook/{day}`; `hash` is `sha256:<hex>` of the file (`""` when it does not exist). */
export interface NotebookDay {
  project: string;
  day: string;
  text: string;
  hash: string;
  runs: RunChip[];
  updated_at: string | null;
}

/** A published result shown under the leaderboard (`hypothex.core.leaderboard.BaselineRow`). */
export interface BaselineRow {
  name: string;
  /** Metric ref (`accuracy/value`) to value. */
  values: Record<string, number>;
  std: Record<string, number>;
  source: string;
  source_url: string;
  /** Metric name to whether the paper's metric version equals ours (missing = false). */
  version_match: Record<string, boolean>;
  primary: number | null;
  /** Best group's primary mean minus this value, signed by the metric direction. */
  delta_vs_best: number | null;
}

export type ExportFormat = "latex" | "markdown" | "csv";
export type NoiseMode = "both" | "seed" | "test" | "none";

/** Query of `GET /api/v1/tasks/{project}/{task}/export` (`hypothex.core.export.ExportOptions`). */
export interface ExportOptions {
  format: ExportFormat;
  metrics?: string[];
  noise?: NoiseMode;
  digits?: number;
  percent?: boolean;
  top?: number;
  groups?: string[];
  baselines?: boolean;
  caption?: string;
  label?: string;
  standalone?: boolean;
}

export type StorageKind = "run" | "artifact" | "pulled";

/** One measured path (`hypothex.core.storage.StorageItem`). */
export interface StorageItem {
  project: string;
  run_id: string;
  host: string;
  environment_id: string;
  kind: StorageKind;
  artifact_kind: string | null;
  path: string;
  bytes: number;
  files: number;
  /** Seconds since the epoch. */
  mtime: number | null;
  exists: boolean;
  archived: boolean;
  starred: boolean;
  status: RunStatus;
  ended_at: string | null;
}

/** `GET /api/v1/storage` (admin). `errors` lists hosts that did not answer. */
export interface StorageReport {
  items: StorageItem[];
  by_project: Record<string, number>;
  by_host: Record<string, number>;
  by_kind: Record<string, number>;
  total_bytes: number;
  errors: { host: string; error: string }[];
  generated_at: string;
}

/** Body of `POST /api/v1/storage/plan`; `archived` is always true (spec 9). */
export interface CleanPolicy {
  archived: true;
  older_than_days: number;
  /** Artifact kinds; `["*"]` = every kind. */
  kinds: string[];
  projects: string[] | null;
  hosts: string[] | null;
  include_pulled: boolean;
}

export interface CleanItem {
  project: string;
  run_id: string;
  host: string;
  environment_id: string;
  kind: "artifact" | "pulled";
  artifact_kind: string | null;
  path: string;
  bytes: number;
  mtime: number | null;
  reason: string;
}

/** A dry run (`cp-<8 hex>`); apply needs `confirm_bytes == total_bytes` before `expires_at`. */
export interface CleanPlan {
  plan_id: string;
  policy: CleanPolicy;
  items: CleanItem[];
  refused: { path: string; run_id: string; reason: string }[];
  total_bytes: number;
  created_at: string;
  expires_at: string;
  created_by: string;
}

export interface CleanResult {
  plan_id: string;
  deleted: CleanItem[];
  skipped: Record<string, unknown>[];
  freed_bytes: number;
  errors: Record<string, string>[];
}

/** One deleted artifact in a run's `.hx/cleaned.json`. */
export interface CleanedArtifact {
  path: string;
  bytes: number;
  at: string;
  actor: string;
  plan_id: string;
}

/** One task's best primary before and after the digest window. */
export interface TaskChange {
  task: string;
  primary: string;
  before: number | null;
  after: number | null;
  best_label: string;
  best_group_id: string | null;
  new_best: boolean;
  n_new_runs: number;
}

export interface NoteItem {
  source: "run" | "notebook";
  run_id: string | null;
  day: string | null;
  author: string;
  at: string;
  /** Cut to 200 characters. */
  text: string;
}

export interface SweepLine {
  id: string;
  n_runs: number;
  best: Record<string, unknown> | null;
}

/** The weekly summary of one project (`hypothex.core.digest.Digest`). */
export interface Digest {
  project: string;
  since: string;
  until: string;
  /** ISO week of `until`, e.g. `2026-W40`. */
  week: string;
  counts: Record<string, number>;
  by_owner: Record<string, number>;
  cost: CostTotals;
  tasks: TaskChange[];
  notes: NoteItem[];
  sweeps: SweepLine[];
  headline: string;
}
```

- [ ] **Step 4: Run the type checker to verify it passes**

Run: `bun run typecheck`
Expected: PASS (`tsc --noEmit` prints nothing).

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/api/models.ts ui/test/api/phase3-fixtures.ts
git commit -m "feat(ui): phase 3 api models for auth, notebook, export, notify and storage"
```

---

### Task 2: Auth store, client routes, 401 lock and the event-stream ticket

**Files:**
- Modify: the token baseline credential provider (`ui/src/api/auth.ts` or its final merged location)
- Modify: `ui/src/api/types.ts` (regenerated)
- Modify: `ui/src/api/client.ts` (imports; `request` and a new `requestText`; after `wsUrl`; `ROUTES`; end of the `api` object)
- Modify: `ui/test/setup.ts` (reset the auth store after each test)
- Modify: `ui/test/api/types.test.ts`
- Create: `ui/test/api/phase3-client.test.ts`

**Interfaces:**
- Consumes: Task 1 models; `ApiError`, `buildUrl`, `get`, `post`, `request`, `newCommandId` in `client.ts`.
- Produces:
  - Preserve the merged token provider's credential state, transitions and public helpers; add `PrincipalContext`, `usePrincipal`, `authOn` (scoped feature mode), and `isAdmin`. Do not replace its generation guards with a separate boolean store. Adapt the test-only lock/reset helpers below to the final reviewed exports before Round 5.
  - Retain bearer selection, same-origin cookies, stale-response rejection, 401 lock/query/cursor cleanup, and 403/404 handling in all JSON and text requests. `requestText` must use that same transport; `exportQuery` joins list options. `/auth/me` 404 hides scoped features only. Reuse the baseline ticket endpoint and socket protocol helpers; do not add a second URL resolver.
  - `api.me(signal?)`, `api.wsTicket(signal?)`, `api.pair(body)`, `api.createPairing(body)`, `api.sessions(signal?)`, `api.revokeSession(id, opts?)`, `api.users(signal?)`, `api.disableUser(name, opts?)`, `api.notebookDays(project, signal?)`, `api.notebookDay(project, day, signal?)`, `api.appendNotebook(project, day, text, opts?)`, `api.saveNotebook(project, day, text, baseHash, opts?)` (PUT), `api.exportTask(project, task, opts, signal?) => Promise<string>`, `api.exportTaskUrl(project, task, opts) => string (URL construction only, never a remote download anchor)`, `api.notify(signal?)`, `api.testNotify(channel, opts?)`, `api.storage(query?, signal?)`, `api.planClean(policy, opts?)`, `api.applyClean(planId, confirmBytes, opts?)`. New writes send `{command_id, …fields}` and no `created_by`.

- [ ] **Step 1: Write the failing tests**

In `ui/test/api/types.test.ts`, replace

```ts
  "/api/v1/queue",
];
```

with

```ts
  "/api/v1/queue",
];

/** Hub routes added in phase 3 (phase 3 contract section 3), including the ones no screen calls. */
const PHASE_3_ROUTES = [
  "/api/v1/auth/pair",
  "/api/v1/auth/me",
  "/api/v1/auth/logout",
  "/api/v1/auth/ws-ticket",
  "/api/v1/auth/pairings",
  "/api/v1/auth/sessions",
  "/api/v1/auth/sessions/{session_id}/revoke",
  "/api/v1/auth/users",
  "/api/v1/auth/users/{name}/disable",
  "/api/v1/projects/{project}/notebook",
  "/api/v1/projects/{project}/notebook/{day}",
  "/api/v1/tasks/{project}/{task}/export",
  "/api/v1/compare/export",
  "/api/v1/projects/{project}/digest",
  "/api/v1/projects/{project}/digest/send",
  "/api/v1/notify",
  "/api/v1/notify/test",
  "/api/v1/storage",
  "/api/v1/storage/plan",
  "/api/v1/storage/plans/{plan_id}/apply",
];
```

and replace `[...PHASE_1B_ROUTES, ...PHASE_2_ROUTES, ...Object.values(ROUTES)]` with `[...PHASE_1B_ROUTES, ...PHASE_2_ROUTES, ...PHASE_3_ROUTES, ...Object.values(ROUTES)]`.

In `ui/test/setup.ts`, replace

```ts
const { afterEach } = await import("bun:test");
const { cleanup } = await import("@testing-library/react");

afterEach(() => {
  cleanup();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});
```

with

```ts
const { afterEach } = await import("bun:test");
const { cleanup } = await import("@testing-library/react");
const { unlock } = await import("../src/api/auth");

afterEach(() => {
  cleanup();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
  // a test that saw a 401 must not leave the next one behind the gate
  unlock();
});
```

Create `ui/test/api/phase3-client.test.ts`:

```ts
import { afterEach, describe, expect, mock, test } from "bun:test";
import { authState, lock, subscribeAuth, unlock } from "../../src/api/auth";
import { ApiError, api, exportQuery } from "../../src/api/client";
import { mockFetch } from "./fetch-mock";
import { CLEAN_PLAN, CLEAN_RESULT, ME_ADMIN, ME_OFF, NOTEBOOK_DAY, OFFER } from "./phase3-fixtures";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

interface Seen {
  url: string;
  method: string;
  credentials: RequestCredentials | undefined;
  accept: string | null;
  body: unknown;
}

/** A fetch stub that answers each URL from `routes` (status, body) and keeps the request init. */
function stub(routes: Record<string, [number, unknown]>): Seen[] {
  const seen: Seen[] = [];
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const headers = new Headers(init?.headers);
    seen.push({
      url,
      method: init?.method ?? "GET",
      credentials: init?.credentials,
      accept: headers.get("Accept"),
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    });
    const [status, body] = routes[url] ?? [404, { error: "no route", type: "StoreError" }];
    const text = typeof body === "string" ? body : JSON.stringify(body);
    return new Response(text, { status });
  }) as unknown as typeof fetch;
  return seen;
}

describe("auth store", () => {
  test("lock and unlock notify subscribers once per change", () => {
    const seen: string[] = [];
    const off = subscribeAuth(() => seen.push(authState()));
    lock();
    lock();
    unlock();
    off();
    lock();
    expect(seen).toEqual(["locked", "open"]);
    expect(authState()).toBe("locked");
  });
});

describe("requests", () => {
  test("every request sends the cookie (credentials same-origin)", async () => {
    const seen = stub({ "/api/v1/auth/me": [200, ME_ADMIN] });
    await api.me();
    expect(seen.map((s) => [s.url, s.credentials])).toEqual([["/api/v1/auth/me", "same-origin"]]);
  });

  test("a 401 locks the app; a 403 and a 404 do not", async () => {
    stub({
      "/api/v1/storage": [403, { error: "storage needs admin", type: "ScopeError" }],
      "/api/v1/notify": [401, { error: "no session", type: "AuthError" }],
    });
    await expect(api.storage()).rejects.toBeInstanceOf(ApiError);
    await expect(api.me()).rejects.toBeInstanceOf(ApiError);
    expect(authState()).toBe("open");
    const err = await api.notify().catch((e: unknown) => e);
    expect([(err as ApiError).status, (err as ApiError).type, authState()]).toEqual([401, "AuthError", "locked"]);
  });

  test("exportTask asks for text and returns it as is", async () => {
    const latex = "% requires \\usepackage{booktabs}\n\\begin{tabular}{lrr}\n";
    const seen = stub({
      "/api/v1/tasks/toy-classifier/toy-test/export?format=latex&metrics=accuracy%2Fvalue%2Cmacro_f1%2Fvalue&noise=both&digits=3":
        [200, latex],
    });
    const text = await api.exportTask("toy-classifier", "toy-test", {
      format: "latex",
      noise: "both",
      digits: 3,
      metrics: ["accuracy/value", "macro_f1/value"],
    });
    expect(text).toBe(latex);
    expect([seen[0]?.accept, seen[0]?.credentials]).toEqual(["text/plain, text/csv", "same-origin"]);
  });

  test("an export error keeps the API error shape and a 401 locks", async () => {
    stub({ "/api/v1/tasks/p/t/export?format=csv": [401, { error: "no session", type: "AuthError" }] });
    const err = await api.exportTask("p", "t", { format: "csv" }).catch((e: unknown) => e);
    expect([(err as ApiError).message, authState()]).toEqual(["no session", "locked"]);
  });
});

describe("phase 3 api", () => {
  test("pair posts the offer, secret and device in the body only", async () => {
    const calls = mockFetch({ user: "alice", scope: "launch", scopes: ["read", "launch"], session_id: "s_91d0aa3f62c8" });
    const made = await api.pair({ offer_id: "p_3f9a2c71e0b4", secret: "kX2mQ9vR7tLw", device: "MacBook", client: "browser" });
    expect([made.user, made.scope]).toEqual(["alice", "launch"]);
    expect(calls).toEqual([
      {
        url: "/api/v1/auth/pair",
        method: "POST",
        body: { offer_id: "p_3f9a2c71e0b4", secret: "kX2mQ9vR7tLw", device: "MacBook", client: "browser" },
      },
    ]);
  });

  test("createPairing posts user, new_user and scope", async () => {
    const calls = mockFetch(OFFER);
    const offer = await api.createPairing({ user: "cy", new_user: true, scope: "read" });
    expect(offer.offer_id).toBe("p_3f9a2c71e0b4");
    expect(calls[0]).toEqual({ url: "/api/v1/auth/pairings", method: "POST", body: { user: "cy", new_user: true, scope: "read" } });
  });

  test("revokeSession and disableUser send only a command id", async () => {
    const calls = mockFetch({});
    await api.revokeSession("s_0d5a7e91b2f4", { command_id: "c-1" });
    await api.disableUser("bo", { command_id: "c-2" });
    expect(calls).toEqual([
      { url: "/api/v1/auth/sessions/s_0d5a7e91b2f4/revoke", method: "POST", body: { command_id: "c-1" } },
      { url: "/api/v1/auth/users/bo/disable", method: "POST", body: { command_id: "c-2" } },
    ]);
  });

  test("notebook: list, read, append (POST) and save (PUT with the base hash)", async () => {
    const calls = mockFetch(NOTEBOOK_DAY);
    await api.notebookDays("deepretro");
    await api.notebookDay("deepretro", "2026-10-04");
    await api.appendNotebook("deepretro", "2026-10-04", "beam 10 holds", { command_id: "c-3" });
    await api.saveNotebook("deepretro", "2026-10-04", "all text", "sha256:9f2c41d07be3a5e8", { command_id: "c-4" });
    expect(calls.map((c) => [c.method, c.url, c.body])).toEqual([
      ["GET", "/api/v1/projects/deepretro/notebook", undefined],
      ["GET", "/api/v1/projects/deepretro/notebook/2026-10-04", undefined],
      ["POST", "/api/v1/projects/deepretro/notebook/2026-10-04", { command_id: "c-3", text: "beam 10 holds" }],
      [
        "PUT",
        "/api/v1/projects/deepretro/notebook/2026-10-04",
        { command_id: "c-4", text: "all text", base_hash: "sha256:9f2c41d07be3a5e8" },
      ],
    ]);
  });

  test("exportTaskUrl constructs the same-origin route with the same query", () => {
    expect(api.exportTaskUrl("toy-classifier", "toy-test", { format: "csv", digits: 2, baselines: false })).toBe(
      "/api/v1/tasks/toy-classifier/toy-test/export?format=csv&digits=2&baselines=false",
    );
    expect(exportQuery({ format: "markdown", groups: ["g1", "g2"], top: 5 })).toEqual({
      format: "markdown",
      metrics: undefined,
      noise: undefined,
      digits: undefined,
      percent: undefined,
      top: 5,
      groups: "g1,g2",
      baselines: undefined,
      caption: undefined,
      label: undefined,
      standalone: undefined,
    });
  });

  test("notify: status, and a test send of one channel", async () => {
    const calls = mockFetch({ ok: false, error_class: "http_404" });
    const res = await api.testNotify("slack", { command_id: "c-5" });
    expect(res).toEqual({ ok: false, error_class: "http_404" });
    expect(calls[0]).toEqual({ url: "/api/v1/notify/test", method: "POST", body: { command_id: "c-5", channel: "slack" } });
  });

  test("storage: report query, plan with the policy, apply with the exact bytes", async () => {
    const calls = mockFetch(CLEAN_PLAN);
    await api.storage({ project: "deepretro", remote: false });
    await api.planClean(CLEAN_PLAN.policy, { command_id: "c-6" });
    mockFetch(CLEAN_RESULT);
    const result = await api.applyClean("cp-8e41c0d2", 412_300_000_000, { command_id: "c-7" });
    expect(result.freed_bytes).toBe(409_800_000_000);
    expect(calls.map((c) => [c.method, c.url, c.body])).toEqual([
      ["GET", "/api/v1/storage?project=deepretro&remote=false", undefined],
      ["POST", "/api/v1/storage/plan", { ...CLEAN_PLAN.policy, command_id: "c-6" }],
    ]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/api/phase3-client.test.ts test/api/types.test.ts`
Expected: FAIL. The file does not load: `error: Cannot find module '../../src/api/auth'` (and `setup.ts` fails the same way for every test file until Step 4 creates `auth.ts`).

- [ ] **Step 3: Regenerate `types.ts` from a private authenticated hub with no hosts**

Run from the repo root after the Phase 3 routes are implemented. This uses the actual `hx token` selected-home command, retains default authentication and fetches OpenAPI with a header only after verifying the expected identity. It never prints the credential, connects a host, or disables OpenAPI protection; cleanup owns only its child process and temporary home. Save the following as a temporary Python script and execute with `uv run python <script>`:

```python
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

repo = Path.cwd()
with tempfile.TemporaryDirectory(prefix="hx-phase3-types-") as directory:
    home = Path(directory)
    env = {**os.environ, "HYPOTHEX_SSH": "false", "HYPOTHEX_SCP": "false"}
    env.pop("HYPOTHEX_SERVE_TOKEN", None)
    with (home / "server.log").open("wb") as log:
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "from hypothex.cli.main import cli; cli()",
                "--home",
                str(home),
                "serve",
                "--port",
                "0",
            ],
            env=env,
            stdout=log,
            stderr=log,
        )
        try:
            deadline = time.monotonic() + 30
            record = None
            while time.monotonic() < deadline and child.poll() is None:
                try:
                    candidate = json.loads((home / "serve/server.json").read_text())
                    identity = json.loads((home / "environment.json").read_text())
                    if candidate.get("pid") == child.pid and candidate.get(
                        "environment_id"
                    ) == identity.get("environment_id"):
                        record = candidate
                        break
                except (OSError, ValueError):
                    pass
                time.sleep(0.1)
            if record is None:
                raise RuntimeError("temporary hub did not publish its owned identity")
            base = f"http://127.0.0.1:{int(record['port'])}"
            # CLI verifies the selected home's exact live process birth locally.
            token = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    "from hypothex.cli.main import cli; cli()",
                    "--home",
                    str(home),
                    "token",
                ],
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=2) as client:
                while time.monotonic() < deadline:
                    if child.poll() is not None:
                        raise RuntimeError("temporary hub exited before readiness")
                    try:
                        identity_response = client.get(base + "/.well-known/hypothex/environment")
                        if identity_response.status_code == 200:
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("temporary hub readiness timed out")
                if identity_response.json().get("environment_id") != record["environment_id"]:
                    raise RuntimeError("temporary hub identity mismatch")
                response = client.get(
                    base + "/api/openapi.json", headers={"Authorization": f"Bearer {token}"}
                )
                if response.status_code != 200:
                    raise RuntimeError(
                        f"authenticated OpenAPI returned HTTP {response.status_code}"
                    )
                spec = home / "openapi.json"
                spec.write_text(response.text)
            subprocess.run(
                ["bunx", "openapi-typescript", str(spec), "-o", "src/api/types.ts"],
                cwd=repo / "ui",
                check=True,
                timeout=60,
            )
        finally:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
```

Expected: the header contains `This file was auto-generated by openapi-typescript.`, and the `grep` prints these lines

```
"/api/v1/auth/logout"
"/api/v1/auth/me"
"/api/v1/auth/pair"
"/api/v1/auth/pairings"
"/api/v1/auth/sessions"
"/api/v1/auth/sessions/{session_id}/revoke"
"/api/v1/auth/users"
"/api/v1/auth/users/{name}/disable"
"/api/v1/auth/ws-ticket"
"/api/v1/compare/export"
"/api/v1/notify"
"/api/v1/notify/test"
"/api/v1/projects/{project}/digest"
"/api/v1/projects/{project}/digest/send"
"/api/v1/projects/{project}/notebook"
"/api/v1/projects/{project}/notebook/{day}"
"/api/v1/storage"
"/api/v1/storage/plan"
"/api/v1/storage/plans/{plan_id}/apply"
"/api/v1/tasks/{project}/{task}/export"
```

(plus `/api/v1/storage/delete` and `/api/v1/storage/usage` if the hub also registers its env routes; the UI calls neither). If a path is missing, stop: the backend plan is not merged. If a path exists with another placeholder name (for example `{sid}` where this plan has `{session_id}`), the backend spelling wins: use it in `PHASE_3_ROUTES` (Step 1), in `ROUTES` and in the matching `params` keys (Step 5). `bun run typecheck` fails until they agree.

- [ ] **Step 4: Extend the merged credential provider with principal context**

Keep the complete baseline `AuthStore` and `auth` instance from `ui/src/api/auth.ts`. Add `createContext`, `useContext`, `useSyncExternalStore`, and the `Principal` type import. Append these feature-facing aliases; all state remains owned by the baseline store. Async callers must pass their captured generation to `lock`; zero-argument calls are synchronous UI/test actions only.

```ts
export type AuthState = "open" | "locked";
export function authState(): AuthState {
  return auth.snapshot().status === "locked" ? "locked" : "open";
}
export function lock(generation = auth.snapshot().generation): void {
  auth.lock(generation);
}
/** Test reset only; app credentials are validated by the transport AuthGate. */
export function unlock(): void {
  auth.accept(auth.select(null));
}
export const subscribeAuth = auth.subscribe;
export function useAuthState(): AuthState {
  return useSyncExternalStore(subscribeAuth, authState, authState);
}
```

Append the principal helpers:

```ts
/**
 * The principal from the app's one `GET /api/v1/auth/me` (`AppShell`). Null while it
 * loads, on a hub without auth routes (before phase 3), and outside the shell (unit tests
 * of a component), which all mean: no chip, no admin-only links, no owner checks.
 */
export const PrincipalContext = createContext<Principal | null>(null);

/** The principal from `PrincipalContext`. */
export function usePrincipal(): Principal | null {
  return useContext(PrincipalContext);
}

/** True when the hub runs with `server.auth: on`. */
export function authOn(principal: Principal | null): boolean {
  return principal?.auth === "on";
}

/** True for an admin, including the local owner of a hub with auth off. */
export function isAdmin(principal: Principal | null): boolean {
  return principal?.scope === "admin";
}
```

- [ ] **Step 5: Extend the authenticated transport, routes and functions**

Preserve the baseline request implementation and imports. Add text response support through its existing request path, including credential capture, bearer headers, cookie selection, stale-generation rejection, and current-generation 401 cleanup. Authentication errors must never return stale protected data. Keep 403/404 from locking a valid provider. Reuse the baseline ticket route/helper and `WsTicket` nullability; deduplicate the route and function if already present. Restore exact executable adapters against the merged files before formal Round 5.

Replace

```ts
  compareExamples: "/api/v1/compare/examples",
  hosts: "/api/v1/hosts",
```

with

```ts
  compareExamples: "/api/v1/compare/examples",
  authMe: "/api/v1/auth/me",
  authPair: "/api/v1/auth/pair",
  authPairings: "/api/v1/auth/pairings",
  authSessions: "/api/v1/auth/sessions",
  authSessionRevoke: "/api/v1/auth/sessions/{session_id}/revoke",
  authUsers: "/api/v1/auth/users",
  authUserDisable: "/api/v1/auth/users/{name}/disable",
  notebookDays: "/api/v1/projects/{project}/notebook",
  notebookDay: "/api/v1/projects/{project}/notebook/{day}",
  taskExport: "/api/v1/tasks/{project}/{task}/export",
  notify: "/api/v1/notify",
  notifyTest: "/api/v1/notify/test",
  storage: "/api/v1/storage",
  storagePlan: "/api/v1/storage/plan",
  storageApply: "/api/v1/storage/plans/{plan_id}/apply",
  hosts: "/api/v1/hosts",
```

Extend the actual baseline `request` in place. Rename its body to a private `requestBody` with a `responseType: "json" | "text"` parameter; leave credential capture, headers, combined abort signal, both `current()` checks, 401 handling and error conversion intact. Change only these lines in that body:

```ts
async function requestBody<T>(method: Method, route: Route, opts: RequestOptions, responseType: "json" | "text"): Promise<T> {
  // The remaining body is the baseline request implementation.
```

```ts
  const headers: Record<string, string> = { Accept: responseType === "text" ? "text/plain, text/csv" : "application/json" };
```

```ts
  const init: RequestInit = { method, headers, signal, credentials: "same-origin" };
```

After its existing `if (!res.ok) throw ApiError.from(res.status, data);`, replace `return data as T;` with:

```ts
  return (responseType === "text" ? text : data) as T;
```

Then add these public wrappers; `websocketTicket` continues using `request`, retaining nullable tickets and protocol validation:

```ts
export function request<T>(method: Method, route: Route, opts: RequestOptions = {}): Promise<T> {
  return requestBody<T>(method, route, opts, "json");
}
export function requestText(route: Route, opts: RequestOptions = {}): Promise<string> {
  return requestBody<string>("GET", route, opts, "text");
}
```

Add this pure export query mapper:

```ts
/** Export options as query values: lists become comma lists, unset options are dropped. */
export function exportQuery(opts: M.ExportOptions): Record<string, QueryValue> {
  return {
    format: opts.format,
    metrics: opts.metrics?.join(","),
    noise: opts.noise,
    digits: opts.digits,
    percent: opts.percent,
    top: opts.top,
    groups: opts.groups?.join(","),
    baselines: opts.baselines,
    caption: opts.caption,
    label: opts.label,
    standalone: opts.standalone,
  };
}
```

Directly after the `action` function, insert:

```ts

/** The body of a phase 3 write: only the idempotency key; the hub sets who did it. */
function command(opts: M.ActionOptions = {}): { command_id: string } {
  return { command_id: opts.command_id ?? newCommandId() };
}
```

At the end of the `api` object, replace

```ts
  pull: (runId: string, artifact: string, opts?: M.ActionOptions) =>
    post<M.PullResult>(ROUTES.runPull, { params: { run_id: runId }, body: { ...action(opts), artifact } }),
};
```

with

```ts
  pull: (runId: string, artifact: string, opts?: M.ActionOptions) =>
    post<M.PullResult>(ROUTES.runPull, { params: { run_id: runId }, body: { ...action(opts), artifact } }),
  // phase 3: auth, notebook, export, notify, storage ---------------------------------------
  me: (signal?: AbortSignal) => get<M.Principal>(ROUTES.authMe, { signal }),
  wsTicket: (signal?: AbortSignal) =>
    post<{ ticket: string | null; expires_in: number }>(ROUTES.wsTicket, { body: {}, signal }),
  /** Redeem a pairing link (public route); a browser gets the session cookie. */
  pair: (body: M.PairRequest) => post<M.PairResult>(ROUTES.authPair, { body }),
  createPairing: (body: M.PairingRequest) => post<M.PairingOffer>(ROUTES.authPairings, { body }),
  /** Own sessions; every session for an admin. */
  sessions: (signal?: AbortSignal) => get<M.SessionRow[]>(ROUTES.authSessions, { signal }),
  revokeSession: (id: string, opts?: M.ActionOptions) =>
    post<M.SessionRow>(ROUTES.authSessionRevoke, {
      params: { session_id: id },
      body: command(opts),
    }),
  users: (signal?: AbortSignal) => get<M.UserRow[]>(ROUTES.authUsers, { signal }),
  disableUser: (name: string, opts?: M.ActionOptions) =>
    post<M.UserRow>(ROUTES.authUserDisable, { params: { name }, body: command(opts) }),
  notebookDays: (project: string, signal?: AbortSignal) =>
    get<M.NotebookDayInfo[]>(ROUTES.notebookDays, { params: { project }, signal }),
  notebookDay: (project: string, day: string, signal?: AbortSignal) =>
    get<M.NotebookDay>(ROUTES.notebookDay, { params: { project, day }, signal }),
  /** Add one entry under the project lock (never a conflict); the hub stamps time and author. */
  appendNotebook: (project: string, day: string, text: string, opts?: M.ActionOptions) =>
    post<M.NotebookDay>(ROUTES.notebookDay, { params: { project, day }, body: { ...command(opts), text } }),
  /** Replace the day; 409 `NotebookConflictError` (with `current`) when the file changed since `baseHash`. */
  saveNotebook: (project: string, day: string, text: string, baseHash: string, opts?: M.ActionOptions) =>
    request<M.NotebookDay>("PUT", ROUTES.notebookDay, {
      params: { project, day },
      body: { ...command(opts), text, base_hash: baseHash },
    }),
  exportTask: (project: string, task: string, opts: M.ExportOptions, signal?: AbortSignal) =>
    requestText(ROUTES.taskExport, { params: { project, task }, query: exportQuery(opts), signal }),
  /** Export URL construction only; downloads use authenticated text and a Blob. */
  exportTaskUrl: (project: string, task: string, opts: M.ExportOptions) =>
    buildUrl(ROUTES.taskExport, { project, task }, exportQuery(opts)),
  notify: (signal?: AbortSignal) => get<M.NotifyStatus>(ROUTES.notify, { signal }),
  testNotify: (channel: M.Channel, opts?: M.ActionOptions) =>
    post<M.NotifyTestResult>(ROUTES.notifyTest, { body: { ...command(opts), channel } }),
  storage: (query: { project?: string; remote?: boolean } = {}, signal?: AbortSignal) =>
    get<M.StorageReport>(ROUTES.storage, { query: { ...query }, signal }),
  /** A dry run; nothing is deleted. */
  planClean: (policy: M.CleanPolicy, opts?: M.ActionOptions) =>
    post<M.CleanPlan>(ROUTES.storagePlan, { body: { ...policy, ...command(opts) } }),
  /** Delete a plan's items; `confirmBytes` must equal the plan's `total_bytes`. */
  applyClean: (planId: string, confirmBytes: number, opts?: M.ActionOptions) =>
    post<M.CleanResult>(ROUTES.storageApply, {
      params: { plan_id: planId },
      body: { ...command(opts), confirm_bytes: confirmBytes },
    }),
};
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `bun test test/api && bun run typecheck`
Expected: `phase3-client.test.ts` 16 pass; the phase 1b/2 api tests pass unchanged (the `ApiError` shapes, `buildUrl` and `wsUrl` did not change); `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 7: Commit (repo root)**

```bash
git add ui/src/api/auth.ts ui/src/api/client.ts ui/src/api/types.ts ui/test/setup.ts ui/test/api/types.test.ts ui/test/api/phase3-client.test.ts
git commit -m "feat(ui): api client for auth, notebook, export, notify and storage; 401 locks the app"
```

---

### Task 3: Query keys, read hooks and phase 3 invalidation lists

**Files:**
- Modify: `ui/src/api/queries.ts` (`queryKeys` end; after `HOST_EVENT_INVALIDATES`; before `// writes`)
- Create: `ui/test/api/phase3-queries.test.tsx`

**Interfaces:**
- Consumes: Task 2 `api.*`.
- Produces (in `ui/src/api/queries.ts`):
  - `queryKeys.me() = ["auth", "me"]`, `sessions() = ["auth", "sessions"]`, `users() = ["auth", "users"]`, `notify() = ["notify"]`, `notebookDays(project) = ["notebook", project, "days"]`, `notebookDay(project, day) = ["notebook", project, "day", day]`, `storage(project?, remote = true) = ["storage", project ?? null, remote]`, `exportText(project, task, opts) = ["leaderboard", project, task, "export", opts]` (inside the leaderboard family, so every run or mirror event that refreshes the project's leaderboard refreshes an open export menu too, and Copy never copies numbers older than the table beside it).
  - `NOTEBOOK_INVALIDATES = [["notebook"]]`, `STORAGE_EVENT_INVALIDATES = [["storage"], ["runs"], ["run"]]`, `NOTIFY_INVALIDATES = [["notify"]]`, `AUTH_EVENT_INVALIDATES = [["auth", "sessions"], ["auth", "users"]]`. `RUN_EVENT_INVALIDATES` is unchanged: run events refresh neither the storage report nor an export preview (the preview is read only while the menu is open, and reopening it after the 5 s stale time reads it again).
  - `useMe(enabled = true)` (60 s stale time; no retry, so a 401 or 404 answers at once), `useSessions(enabled = true)`, `useUsers(enabled = true)`, `useNotify(enabled = true)`, `useNotebookDays(project)`, `useNotebookDay(project, day)`, `useStorage(project?, remote = true, enabled = true)` (stale for 60 s: a report walks every host), `useExportText(project, task, opts, enabled)` (keeps the last text while the next format loads).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/api/phase3-queries.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import {
  AUTH_EVENT_INVALIDATES,
  NOTEBOOK_INVALIDATES,
  NOTIFY_INVALIDATES,
  RUN_EVENT_INVALIDATES,
  STORAGE_EVENT_INVALIDATES,
  queryKeys,
  useExportText,
  useMe,
  useNotebookDay,
  useStorage,
} from "../../src/api/queries";
import { mockApi, restoreFetch } from "../pages/helpers";
import { ME_ALICE, NOTEBOOK_DAY, STORAGE_REPORT } from "./phase3-fixtures";

afterEach(restoreFetch);

function wrapper(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => createElement(QueryClientProvider, { client }, children);
}
const fresh = () => new QueryClient({ defaultOptions: { queries: { retry: false } } });

describe("keys and lists", () => {
  test("keys are hierarchical by family and project", () => {
    expect([
      queryKeys.me(),
      queryKeys.sessions(),
      queryKeys.users(),
      queryKeys.notify(),
      queryKeys.notebookDays("deepretro"),
      queryKeys.notebookDay("deepretro", "2026-10-04"),
      queryKeys.storage(),
      queryKeys.storage("deepretro", false),
      queryKeys.exportText("p", "t", { format: "csv" }),
    ]).toEqual([
      ["auth", "me"],
      ["auth", "sessions"],
      ["auth", "users"],
      ["notify"],
      ["notebook", "deepretro", "days"],
      ["notebook", "deepretro", "day", "2026-10-04"],
      ["storage", null, true],
      ["storage", "deepretro", false],
      ["leaderboard", "p", "t", "export", { format: "csv" }],
    ]);
  });

  test("invalidation lists; run events never refresh storage, but do refresh exports", () => {
    expect(NOTEBOOK_INVALIDATES).toEqual([["notebook"]]);
    expect(STORAGE_EVENT_INVALIDATES).toEqual([["storage"], ["runs"], ["run"]]);
    expect(NOTIFY_INVALIDATES).toEqual([["notify"]]);
    expect(AUTH_EVENT_INVALIDATES).toEqual([
      ["auth", "sessions"],
      ["auth", "users"],
    ]);
    expect(RUN_EVENT_INVALIDATES).not.toContainEqual(["storage"]);
    // an export key sits under ["leaderboard", project], which run events invalidate
    const key = queryKeys.exportText("p", "t", { format: "csv" });
    expect(RUN_EVENT_INVALIDATES).toContainEqual(["leaderboard"]);
    expect(key.slice(0, 2)).toEqual(["leaderboard", "p"]);
  });
});

describe("hooks", () => {
  test("useMe reads /auth/me once and does not retry a 404", async () => {
    const calls = mockApi({ "GET /api/v1/auth/me": ME_ALICE });
    const { result } = renderHook(() => useMe(), { wrapper: wrapper(new QueryClient()) });
    await waitFor(() => expect(result.current.data?.user).toBe("alice"));
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/auth/me"]);
    mockApi({});
    const missing = renderHook(() => useMe(), { wrapper: wrapper(new QueryClient()) });
    await waitFor(() => expect(missing.result.current.isError).toBe(true));
  });

  test("useMe(false) stays idle", () => {
    const calls = mockApi({ "GET /api/v1/auth/me": ME_ALICE });
    const { result } = renderHook(() => useMe(false), { wrapper: wrapper(fresh()) });
    expect([result.current.fetchStatus, calls.length]).toEqual(["idle", 0]);
  });

  test("useNotebookDay reads one day", async () => {
    mockApi({ "GET /api/v1/projects/deepretro/notebook/2026-10-04": NOTEBOOK_DAY });
    const { result } = renderHook(() => useNotebookDay("deepretro", "2026-10-04"), { wrapper: wrapper(fresh()) });
    await waitFor(() => expect(result.current.data?.hash).toBe("sha256:9f2c41d07be3a5e8"));
  });

  test("useStorage reads the report and stays idle when disabled", async () => {
    const calls = mockApi({ "GET /api/v1/storage?remote=true": STORAGE_REPORT });
    const idle = renderHook(() => useStorage(undefined, true, false), { wrapper: wrapper(fresh()) });
    expect(idle.result.current.fetchStatus).toBe("idle");
    const { result } = renderHook(() => useStorage(), { wrapper: wrapper(fresh()) });
    await waitFor(() => expect(result.current.data?.total_bytes).toBe(1.84e12));
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/storage?remote=true"]);
  });

  test("useExportText fetches only while enabled", async () => {
    const calls = mockApi({ "GET /api/v1/tasks/p/t/export?format=markdown": "| a |\n" });
    const off = renderHook(() => useExportText("p", "t", { format: "markdown" }, false), { wrapper: wrapper(fresh()) });
    expect(off.result.current.fetchStatus).toBe("idle");
    const { result } = renderHook(() => useExportText("p", "t", { format: "markdown" }, true), {
      wrapper: wrapper(fresh()),
    });
    await waitFor(() => expect(result.current.data).toBe("| a |\n"));
    expect(calls).toHaveLength(1);
  });
});
```

`mockApi` answers a string handler as JSON (`"\"| a |\\n\""`); `requestText` returns the raw text, so the last test would see the quotes. Make `mockApi` send strings as text: in `ui/test/pages/helpers.tsx`, replace

```ts
    if (out instanceof HttpReply) return json(out.status, out.body);
    return json(200, out);
```

with

```ts
    if (out instanceof HttpReply) return json(out.status, out.body);
    // a string answer is a text body (export routes); everything else is JSON
    if (typeof out === "string") return new Response(out, { status: 200, headers: { "Content-Type": "text/plain" } });
    return json(200, out);
```

(No phase 1b/2 test answers a JSON route with a bare string, so they are unchanged.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/api/phase3-queries.test.tsx`
Expected: FAIL. `SyntaxError: Export named 'AUTH_EVENT_INVALIDATES' not found in module '.../src/api/queries.ts'` (bun names one of the missing exports).

- [ ] **Step 3: Add the keys, lists and hooks**

Keep `queryKeys.environment()` and `useHubEnvironment(opts)` unchanged. Overview, Run's owner-qualified sweep links, and the command palette share this query; Run retains `enabled: Boolean(record?.sweep_id)`. Do not restore page-local descriptor queries. Keep `clearSessionQueries` so the descriptor and side caches are cleared with credentials even though the descriptor's `staleTime` is infinite.

In `ui/src/api/queries.ts`, replace

```ts
  allRuns: (query: Omit<M.RunsQuery, "limit">) => ["runs", "all", query] as const,
};
```

with

```ts
  allRuns: (query: Omit<M.RunsQuery, "limit">) => ["runs", "all", query] as const,
  me: () => ["auth", "me"] as const,
  sessions: () => ["auth", "sessions"] as const,
  users: () => ["auth", "users"] as const,
  notify: () => ["notify"] as const,
  notebookDays: (project: string) => ["notebook", project, "days"] as const,
  notebookDay: (project: string, day: string) => ["notebook", project, "day", day] as const,
  storage: (project?: string, remote = true) => ["storage", project ?? null, remote] as const,
  /** Under the leaderboard family: run and mirror events refresh an open export menu with the board. */
  exportText: (project: string, task: string, opts: M.ExportOptions) =>
    ["leaderboard", project, task, "export", opts] as const,
};
```

Directly after `HOST_EVENT_INVALIDATES`, insert:

```ts

/** A notebook write or `notebook.updated`: every notebook query (events narrow it to the project). */
export const NOTEBOOK_INVALIDATES: readonly QueryKey[] = [["notebook"]];

/**
 * A cleanup (`storage.*` events, apply): the report, and the runs whose artifacts went
 * (`RunDetail.cleaned`). Run events never refresh the report: it walks every host.
 */
export const STORAGE_EVENT_INVALIDATES: readonly QueryKey[] = [["storage"], ["runs"], ["run"]];

/** `notify.*`, `digest.sent`, a test send: the channel status and recent sends. */
export const NOTIFY_INVALIDATES: readonly QueryKey[] = [["notify"]];

/** `auth.*` events, a revoke or a disable: session and user lists (never `/auth/me`). */
export const AUTH_EVENT_INVALIDATES: readonly QueryKey[] = [
  ["auth", "sessions"],
  ["auth", "users"],
];
```

Directly above `// writes ---`, insert:

```ts
/**
 * `GET /api/v1/auth/me`, once per app (`AppShell`); 60 s stale. Never retried: a 401
 * already locked the app and a 404 means a hub before phase 3.
 */
export const useMe = (enabled = true) =>
  useQuery({
    queryKey: queryKeys.me(),
    queryFn: ({ signal }) => api.me(signal),
    enabled,
    staleTime: 60_000,
    retry: false,
  });

export const useSessions = (enabled = true) =>
  useQuery({ queryKey: queryKeys.sessions(), queryFn: ({ signal }) => api.sessions(signal), enabled });

/** Admin only: never enable it for another principal (a 403 is console noise). */
export const useUsers = (enabled = true) =>
  useQuery({ queryKey: queryKeys.users(), queryFn: ({ signal }) => api.users(signal), enabled });

/** Admin only. */
export const useNotify = (enabled = true) =>
  useQuery({ queryKey: queryKeys.notify(), queryFn: ({ signal }) => api.notify(signal), enabled });

export const useNotebookDays = (project: string) =>
  useQuery({
    queryKey: queryKeys.notebookDays(project),
    queryFn: ({ signal }) => api.notebookDays(project, signal),
  });

export const useNotebookDay = (project: string, day: string) =>
  useQuery({
    queryKey: queryKeys.notebookDay(project, day),
    queryFn: ({ signal }) => api.notebookDay(project, day, signal),
  });

/** Admin only; 60 s stale (a report walks every host's run folders). */
export const useStorage = (project?: string, remote = true, enabled = true) =>
  useQuery({
    queryKey: queryKeys.storage(project, remote),
    queryFn: ({ signal }) => api.storage(project === undefined ? { remote } : { project, remote }, signal),
    enabled,
    staleTime: 60_000,
  });

/** Export text for the menu's preview; keeps the last text while another format loads. */
export const useExportText = (project: string, task: string, opts: M.ExportOptions, enabled: boolean) =>
  useQuery({
    queryKey: queryKeys.exportText(project, task, opts),
    queryFn: ({ signal }) => api.exportTask(project, task, opts, signal),
    enabled,
    placeholderData: keepPreviousData,
  });

```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/api && bun run typecheck`
Expected: `phase3-queries.test.tsx` 7 pass; `queries.test.tsx` (phase 1b/2) passes unchanged; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/api/queries.ts ui/test/api/phase3-queries.test.tsx ui/test/pages/helpers.tsx
git commit -m "feat(ui): queries for principal, sessions, notify, notebook, storage and export"
```

---

### Task 4: Live invalidation for phase 3 events; tickets, 4401, notebook editors

**Files:**
- Modify: `ui/src/api/events.ts` (imports; `EventStreamOptions`; `EventStreamHookOptions`; `BY_PROJECT`; `keysForEvent`; `EventStream.connect` and `handleClose`; `useEventStream`; `LiveUpdatesProps` and `LiveUpdates`)
- Create: `ui/src/api/notebookEditors.ts`
- Create: `ui/test/api/phase3-events.test.ts`, `ui/test/api/notebookEditors.test.ts`

**Interfaces:**
- Consumes: the merged token provider and event transport; Task 3 invalidation lists.
- Produces:
  - `BY_PROJECT` gains `notebook` (so `notebook.updated` narrows to its project).
  - Preserve the baseline socket options and ticket helper. Before every connection request a fresh one-use ticket and connect to the clean URL with `hypothex.v1` and `hx-ticket.<ticket>` subprotocols; intentional no-auth uses only `hypothex.v1`.
  - A socket closed with code `WS_AUTH_CLOSE = 4401` calls `lock()`, sets `offline` and never reconnects.
  - `keysForEvent`: `notebook.updated` → `["notebook", project]`; `run.artifacts_cleaned` → the narrowed run families plus `["storage"]`; `storage.*` → `STORAGE_EVENT_INVALIDATES`; `notify.*` → `["notify"]`; `digest.sent` → `["notify"]` and `["notebook", project]`; `auth.*` → `AUTH_EVENT_INVALIDATES`.
  - Preserve the baseline provider/stream gate; `/pair` opens no socket or protected queries. Adapt its existing enable mechanism rather than creating an independent gate.
  - `ui/src/api/notebookEditors.ts`: `notebookEditorOf(event): {project, day, author, at} | null`; `noteNotebookEditors(events)`; `notebookEditor(project, day)`; `useNotebookEditor(project, day)`; `clearNotebookEditors()` (tests).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/api/notebookEditors.test.ts`:

```ts
import { afterEach, describe, expect, test } from "bun:test";
import { act, renderHook } from "@testing-library/react";
import type { HxEvent } from "../../src/api/models";
import {
  clearNotebookEditors,
  notebookEditor,
  notebookEditorOf,
  noteNotebookEditors,
  useNotebookEditor,
} from "../../src/api/notebookEditors";

function ev(sequence: number, type: string, payload: Record<string, unknown>, project: string | null = "deepretro"): HxEvent {
  return { sequence, type, project, run_id: null, payload, created_at: `2026-10-04T11:0${sequence}:00Z` };
}

afterEach(() => act(() => clearNotebookEditors()));

describe("notebook editors", () => {
  test("notebookEditorOf reads notebook.updated only, with a day and an author", () => {
    expect(notebookEditorOf(ev(1, "notebook.updated", { project: "deepretro", day: "2026-10-04", author: "human:sv" }))).toEqual({
      project: "deepretro",
      day: "2026-10-04",
      author: "human:sv",
      at: "2026-10-04T11:01:00Z",
    });
    expect(notebookEditorOf(ev(2, "run.finished", { day: "2026-10-04", author: "human:sv" }))).toBeNull();
    expect(notebookEditorOf(ev(3, "notebook.updated", { day: "2026-10-04" }))).toBeNull();
    expect(notebookEditorOf(ev(4, "notebook.updated", { day: "2026-10-04", author: "human:sv" }, null))).toBeNull();
  });

  test("the newest editor per day wins and the hook follows it", () => {
    const { result } = renderHook(() => useNotebookEditor("deepretro", "2026-10-04"));
    expect(result.current).toBeNull();
    act(() =>
      noteNotebookEditors([
        ev(1, "notebook.updated", { day: "2026-10-04", author: "human:alice" }),
        ev(2, "notebook.updated", { day: "2026-10-04", author: "human:sv" }),
      ]),
    );
    expect(result.current?.author).toBe("human:sv");
    expect(notebookEditor("deepretro", "2026-10-03")).toBeNull();
  });
});
```

Create `ui/test/api/phase3-events.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { type HxEvent, keysForEvent } from "../../src/api/events";

function ev(type: string, project: string | null = "deepretro", run_id: string | null = null): HxEvent {
  return { sequence: 1, type, project, run_id, payload: {}, created_at: "2026-10-04T14:00:00Z" };
}

describe("phase 3 keys", () => {
  test("notebook.updated refreshes that project's notebook only", () => {
    expect(keysForEvent(ev("notebook.updated"))).toEqual([["notebook", "deepretro"]]);
  });

  test("run.artifacts_cleaned refreshes the run, its project and the storage report", () => {
    const keys = keysForEvent(ev("run.artifacts_cleaned", "deepretro", "r-3a90"));
    expect(keys).toContainEqual(["run", "r-3a90"]);
    expect(keys).toContainEqual(["leaderboard", "deepretro"]);
    expect(keys).toContainEqual(["storage"]);
  });

  test("storage, notify, digest and auth events map to their families", () => {
    expect(keysForEvent(ev("storage.cleaned", null))).toEqual([["storage"], ["runs"], ["run"]]);
    expect(keysForEvent(ev("storage.plan_created", null))).toEqual([["storage"], ["runs"], ["run"]]);
    expect(keysForEvent(ev("notify.failed"))).toEqual([["notify"]]);
    expect(keysForEvent(ev("digest.sent"))).toEqual([["notify"], ["notebook", "deepretro"]]);
    expect(keysForEvent(ev("auth.session_revoked", null))).toEqual([
      ["auth", "sessions"],
      ["auth", "users"],
    ]);
  });

  test("durable issuance refreshes only its sweep detail and project list", () => {
    expect(keysForEvent({ ...ev("sweep.issuance"), payload: { sweep_id: "s-1" } })).toEqual([
      ["sweeps", "deepretro", "detail", "s-1"], ["sweeps", "deepretro", "list"],
    ]);
    expect(keysForEvent(ev("sweep.issuance"))).toEqual([]);
  });

  test("a plain run event never refreshes the storage report", () => {
    expect(keysForEvent(ev("run.finished", "deepretro", "r1"))).not.toContainEqual(["storage"]);
  });
});

```

Add concrete transport regression tests against the final merged test fixtures before Round 5: head lookup completes before ticket mint; each reconnect uses a new ticket on a clean URL and fixed protocol; an old ticket result after stop/restart or credential replacement cannot open a socket; current 401/4401 clears queries and cursor then locks/stops; stale 401 cannot lock the replacement credential; 429/5xx/network ticket failures retry with bounded backoff and a fresh ticket; `/auth/me` 404 retains root protection; intentional no-auth uses the nullable-ticket contract. Keep the baseline event tests.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/api/phase3-events.test.ts test/api/notebookEditors.test.ts`
Expected: FAIL. `notebookEditors.test.ts`: `error: Cannot find module '../../src/api/notebookEditors'`; `phase3-events.test.ts`: new event families are not yet mapped.

- [ ] **Step 3: Write `notebookEditors.ts`**

Create `ui/src/api/notebookEditors.ts`:

```ts
/**
 * Who last wrote each notebook day, read from the event stream (phase 3 contract 1.4).
 *
 * Both notebook writes emit `notebook.updated` with `{project, day, author}`; the day file
 * itself does not say who changed it last. The notebook's 409 view names the other editor
 * from here (`409 · changed by @sv 1m`); a tab that did not see the event says only
 * `409 · changed 1m`.
 */
import { useSyncExternalStore } from "react";

import type { HxEvent } from "./models";

export interface NotebookEdit {
  project: string;
  day: string;
  author: string;
  at: string;
}

const edits = new Map<string, NotebookEdit>();
const listeners = new Set<() => void>();
const key = (project: string, day: string): string => `${project}\u0000${day}`;

function changed(): void {
  for (const listener of listeners) listener();
}

/** The edit a `notebook.updated` event describes; null for any other event or a partial one. */
export function notebookEditorOf(event: HxEvent): NotebookEdit | null {
  if (event.type !== "notebook.updated" || event.project === null) return null;
  const { day, author } = event.payload ?? {};
  if (typeof day !== "string" || typeof author !== "string" || author === "") return null;
  return { project: event.project, day, author, at: event.created_at };
}

/** Remember the newest editor of every day in `events`. */
export function noteNotebookEditors(events: readonly HxEvent[]): void {
  let any = false;
  for (const event of events) {
    const edit = notebookEditorOf(event);
    if (edit === null) continue;
    edits.set(key(edit.project, edit.day), edit);
    any = true;
  }
  if (any) changed();
}

/** The last edit seen for a day, or null. */
export function notebookEditor(project: string, day: string): NotebookEdit | null {
  return edits.get(key(project, day)) ?? null;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** `notebookEditor(project, day)`, re-rendering when any edit arrives. */
export function useNotebookEditor(project: string, day: string): NotebookEdit | null {
  return useSyncExternalStore(
    subscribe,
    () => notebookEditor(project, day),
    () => null,
  );
}

/** Forget every edit (tests). */
export function clearNotebookEditors(): void {
  edits.clear();
  changed();
}
```

- [ ] **Step 4: Add event mappings to the merged authenticated event stream**

Keep all baseline imports and transport/provider interfaces. Add `noteNotebookEditors` and the four new invalidation lists (`AUTH_EVENT_INVALIDATES`, `NOTEBOOK_INVALIDATES`, `NOTIFY_INVALIDATES`, `STORAGE_EVENT_INVALIDATES`) to the existing imports. Do not recreate the removed `resolveUrl`/query-ticket implementation. Exact transport adapters and regression tests are required against the merged token baseline before formal Round 5.

Replace

```ts
/** Run families whose next key segment is the project. */
const BY_PROJECT = new Set(["task", "leaderboard", "views/query", "sweeps"]);
```

with

```ts
/** Run families whose next key segment is the project. */
const BY_PROJECT = new Set(["task", "leaderboard", "views/query", "sweeps", "notebook"]);

/** WebSocket close code of a revoked or expired session (phase 3 contract 1.10). */
export const WS_AUTH_CLOSE = 4401;
```

Replace the whole `keysForEvent` function and its doc comment (as left by phase 2 Task 4)

```ts
/**
 * Query keys to invalidate for one event.
 *
 * - `run.*`: `RUN_EVENT_INVALIDATES`, narrowed to the event's run and project.
 * - `mirror.run_updated` (a remote run changed): `REMOTE_RUN_INVALIDATES`, narrowed the
 *   same way, so it also refreshes the hosts list.
 * - `host.*`: `HOST_EVENT_INVALIDATES` as is (a host change touches all its runs).
 * - anything else: nothing.
 */
export function keysForEvent(event: HxEvent): QueryKey[] {
  if (event.type === "sweep.issuance") {
    const project = event.project ?? event.payload?.project;
    const id = event.payload?.sweep_id;
    if (typeof project !== "string" || typeof id !== "string") return [];
    return [["sweeps", project, "detail", id], ["sweeps", project, "list"]];
  }
  if (event.type.startsWith("host.")) return HOST_EVENT_INVALIDATES.map((family) => [...family]);
  if (event.type === MIRROR_RUN_UPDATED) return narrow(REMOTE_RUN_INVALIDATES, event);
  if (event.type.startsWith("run.")) return narrow(RUN_EVENT_INVALIDATES, event);
  return [];
}
```

with

```ts
/**
 * Query keys to invalidate for one event.
 *
 * - `run.*`: `RUN_EVENT_INVALIDATES`, narrowed to the event's run and project.
 * - `run.artifacts_cleaned`: the run families as above, plus the storage report.
 * - `mirror.run_updated` (a remote run changed): `REMOTE_RUN_INVALIDATES`, narrowed the
 *   same way, so it also refreshes the hosts list.
 * - `host.*`: `HOST_EVENT_INVALIDATES` as is (a host change touches all its runs).
 * - `notebook.updated`: the project's notebook queries; `digest.sent` also the notify status.
 * - `storage.*`, `notify.*`, `auth.*`: `STORAGE_EVENT_INVALIDATES`, `NOTIFY_INVALIDATES`,
 *   `AUTH_EVENT_INVALIDATES` as they are.
 * - anything else: nothing.
 */
export function keysForEvent(event: HxEvent): QueryKey[] {
  if (event.type === "sweep.issuance") {
    const project = event.project ?? event.payload?.project;
    const id = event.payload?.sweep_id;
    if (typeof project !== "string" || typeof id !== "string") return [];
    return [["sweeps", project, "detail", id], ["sweeps", project, "list"]];
  }
  const all = (families: readonly QueryKey[]): QueryKey[] => families.map((family) => [...family]);
  if (event.type.startsWith("host.")) return all(HOST_EVENT_INVALIDATES);
  if (event.type === MIRROR_RUN_UPDATED) return narrow(REMOTE_RUN_INVALIDATES, event);
  if (event.type === "run.artifacts_cleaned") return [...narrow(RUN_EVENT_INVALIDATES, event), ["storage"]];
  if (event.type.startsWith("run.")) return narrow(RUN_EVENT_INVALIDATES, event);
  if (event.type === "notebook.updated") return narrow([["notebook"]], event);
  if (event.type === "digest.sent") return [...all(NOTIFY_INVALIDATES), ...narrow([["notebook"]], event)];
  if (event.type.startsWith("storage.")) return all(STORAGE_EVENT_INVALIDATES);
  if (event.type.startsWith("notify.")) return all(NOTIFY_INVALIDATES);
  if (event.type.startsWith("auth.")) return all(AUTH_EVENT_INVALIDATES);
  return [];
}
```

Preserve the baseline `EventStreamOptions.ticket?: ((signal: AbortSignal) => Promise<string | null>) | null`, `websocketTicket`, `connectionGeneration`, `ticketController`, and `openSocket(ticket)` protocol assembly. Preserve `connect`/`lookupHead` ordering, head cancellation, replay, backoff and secret-free socket URL. Add `auth` to the existing auth import. In `openSocket`, capture `const credentialGeneration = auth.snapshot().generation;` immediately before installing handlers; replace only its `socket.onclose` callback:

```ts
    socket.onclose = (event) => {
      if (socket !== this.socket) return;
      if (event.code === WS_AUTH_CLOSE) {
        auth.lock(credentialGeneration);
        this.stop();
        this.setStatus("offline");
        return;
      }
      this.handleClose();
    };
```

In `useEventStream`, add `noteNotebookEditors(events)` directly after `noteLostReasons(events)`. Keep the single predicate-based batch invalidation and `partialMatchKey`. Extend `onHead`'s existing `const keys` with the four new lists:

```ts
        const keys = [
          ...RUN_EVENT_INVALIDATES, ...HOST_EVENT_INVALIDATES,
          ...NOTEBOOK_INVALIDATES, ...STORAGE_EVENT_INVALIDATES,
          ...NOTIFY_INVALIDATES, ...AUTH_EVENT_INVALIDATES,
        ];
```

Keep `cancelQueries(filters).then(() => invalidateQueries(filters))`, the head test override and `ticket` option forwarding unchanged. Keep the prerequisite's existing class-level `unsubscribeAuth` subscription in `EventStream.start()` and its removal in `stop()`; it synchronously cancels work on credential reset. Do not add a second hook-level subscription. The transport `AuthGate` owns remounting after validation. Retain baseline tests and add captured-generation 4401 and reset-during-ticket tests using the real `ticket`/`createSocket(url, protocols)` options.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `bun test test/api && bun run typecheck`
Expected: all phase-3 event cases pass, including head-before-ticket and stopped-generation rejection; `notebookEditors.test.ts` 2 pass; the merged baseline event tests pass with their actual authenticated transport fixtures; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 6: Commit (repo root)**

```bash
git add ui/src/api/events.ts ui/src/api/notebookEditors.ts ui/test/api/phase3-events.test.ts ui/test/api/notebookEditors.test.ts
git commit -m "feat(ui): live updates for notebook, storage, notify and auth events; ws tickets and 4401"
```

---

## Group 2: The 401 gate, pairing, the header and run ownership (Tasks 5–8)

Puts auth into the shell. `AppShell` reads `/auth/me` once (never on `/pair`), hands the principal to every component through `PrincipalContext`, and swaps the routed screen for the 401 gate while the auth store is `locked`. `/pair` redeems a pairing link from the URL fragment without a header. The header gets the phase 3 links and the user chip. Runs show `@owner`, and Stop/Cancel follow contract 1.3 (owner or admin) as a hint; the server's 403 stays the rule.

### Task 5: The 401 gate and the shell

**Files:**
- Create: `ui/src/pages/components/AuthGate.tsx`
- Modify: `ui/src/router.tsx` (imports; `AppShell`)
- Modify: `ui/src/main.tsx` (no event stream on `/pair`)
- Create: `ui/test/pages/authGate.test.tsx`, `ui/test/shell/AppShell.test.tsx`

**Interfaces:**
- Consumes: Task 2 `useAuthState`, `PrincipalContext`; Task 3 `useMe`; `CopyButton` (exists).
- Produces: `PAIR_COMMAND = "hx pair"`; `AuthGate()` (one line `401 · pair this device: hx pair` with a copy button, `role="alert"`); `PAIR_PATH = "/pair"` (exported from `router.tsx`); `AppShell` renders `/pair` bare (no header, no `/auth/me`, no palette), the gate while `locked`, and wraps everything else in `PrincipalContext.Provider value={me.data ?? null}`; `Header` gets `locked` (Task 7 draws it; this task passes it).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/authGate.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { AuthGate, PAIR_COMMAND } from "../../src/pages/components/AuthGate";
import { mockClipboard } from "./helpers";

afterEach(() => {
  Reflect.deleteProperty(globalThis.navigator, "clipboard");
});

test("the gate is one line with the command and a copy button", async () => {
  const written = mockClipboard();
  render(<AuthGate />);
  expect(screen.getByRole("alert").textContent).toBe("401·pair this device:hx pair");
  expect(PAIR_COMMAND).toBe("hx pair");
  fireEvent.click(screen.getByRole("button", { name: "Copy hx pair" }));
  await waitFor(() => expect(written).toEqual(["hx pair"]));
});
```

Create `ui/test/shell/AppShell.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { screen, waitFor } from "@testing-library/react";
import { authState } from "../../src/api/auth";
import { ME_ADMIN } from "../api/phase3-fixtures";
import { HttpReply, mockApi, restoreFetch } from "../pages/helpers";
import { renderApp } from "../render-app";

afterEach(restoreFetch);

test("locked: the header keeps brand and theme only, the screen shows the gate", async () => {
  mockApi({ "GET /api/v1/auth/me": new HttpReply(401, { error: "no session", type: "AuthError" }) });
  renderApp("/");
  await screen.findByText("pair this device:");
  expect(screen.getByLabelText("Token")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Unlock" })).toBeTruthy();
  expect(authState()).toBe("locked");
  expect(screen.queryByRole("navigation", { name: "Screens" })).toBeNull();
  expect(screen.queryByRole("button", { name: /Find a run/ })).toBeNull();
  expect(screen.getByRole("link", { name: "Hypothex, overview" })).toBeTruthy();
  expect(screen.getByRole("button", { name: "Switch colour mode" })).toBeTruthy();
});

test("open: the screen renders under the header, /auth/me is read once", async () => {
  const calls = mockApi({ "GET /api/v1/auth/me": ME_ADMIN });
  const { router } = renderApp("/");
  await waitFor(() => expect(router.state.status).toBe("idle"));
  await waitFor(() => expect(calls.filter((c) => c.url === "/api/v1/auth/me")).toHaveLength(1));
  expect(screen.getByRole("navigation", { name: "Screens" })).toBeTruthy();
  expect(screen.queryByText("pair this device:")).toBeNull();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/authGate.test.tsx test/shell/AppShell.test.tsx`
Expected: FAIL. `authGate.test.tsx`: `error: Cannot find module '../../src/pages/components/AuthGate'`; `AppShell.test.tsx`: the first test times out in `findByText("pair this device:")` (the shell never shows a gate).

- [ ] **Step 3: Write `AuthGate.tsx`**

Create `ui/src/pages/components/AuthGate.tsx`:

```tsx
/**
 * The 401 gate (phase 3 contract 10): shown instead of every screen once the hub said 401
 * (no session, a revoked or expired one, or a disabled user). One line and the command
 * that makes a pairing link on the hub; the explanation is the tooltip.
 */
import { createElement } from "react";
import { CopyButton } from "./CopyButton";

export const PAIR_COMMAND = "hx pair";

export const GATE_CSS = `
.page.gate { min-height: calc(100vh - 220px); display: grid; place-items: center; }
.page.gate p { display: flex; gap: 14px; align-items: center; margin: 0; font-size: 17px; color: var(--ink-2); }
.page.gate b { font: 500 30px/1 var(--serif); color: var(--ink); letter-spacing: -.01em; }
.page.gate .chipc { display: inline-flex; align-items: center; gap: 8px; height: 34px; padding: 0 6px 0 12px; background: var(--paper-2); border-radius: 6px; }
.page.gate .chipc code { font-size: 13.5px; color: var(--ink); }
`;

export function AuthGate() {
  return (
    <div className="page gate">
      {createElement("style", { "data-hx": "gate" }, GATE_CSS)}
      <p role="alert" title="This browser has no session on this hub, or it was revoked. Run the command on the hub and open the link it prints.">
        <b>401</b>
        <span>·</span>
        <span>pair this device:</span>
        <span className="chipc">
          <code>{PAIR_COMMAND}</code>
          <CopyButton text={PAIR_COMMAND} label={PAIR_COMMAND} />
        </span>
      </p>
    </div>
  );
}
```

- [ ] **Step 4: Gate the shell and keep `/pair` bare**

In `ui/src/router.tsx`, retain existing imports and add `useRouterState`, `PrincipalContext`, `useMe`, `LiveUpdates`, the existing pairing component under `import { AuthGate as PairingHint } from "./pages/components/AuthGate"`, and the baseline gate under `import { AuthGate as TransportAuthGate } from "./api/AuthGate"`. Rename the old `AppShell` to `AuthenticatedShell`; keep its header, palette, existing lazy routes and reads, and wrap its returned frame in `<PrincipalContext.Provider value={me.data ?? null}>` after `const me = useMe();`. Add this outer shell:

```tsx
export const PAIR_PATH = "/pair";
export function AppShell() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  if (pathname === PAIR_PATH) return <main className="bare"><Outlet /></main>;
  return (
    <TransportAuthGate lockedHeader={<Header locked />} pairingHint={<PairingHint />}>
      <LiveUpdates><AuthenticatedShell /></LiveUpdates>
    </TransportAuthGate>
  );
}
```

Extend the existing `ui/src/api/AuthGate.tsx` component signature with two optional presentation slots:

```tsx
export function AuthGate({ children, lockedHeader, pairingHint }: {
  children: ReactNode;
  lockedHeader?: ReactNode;
  pairingHint?: ReactNode;
}) {
```

Keep validation, credential generation, all password-field options, submit behavior and the `unlocked` return unchanged. Move the existing query-reset subscription to the always-mounted `SessionReset` wrapper below so `/pair` also clears the previous principal's data. In the existing locked/validating return, wrap the current `<main>` in a fragment, render `{lockedHeader}` before it and `{pairingHint}` immediately after the existing form inside that main. This is the exact resulting outer structure; the original form body is retained verbatim:

```tsx
  return (
    <>
      {lockedHeader}
      <main style={{ maxWidth: 320, margin: "18vh auto", padding: 24 }}>
        {/* Existing token form and validation/error status, unchanged. */}
        {pairingHint}
      </main>
    </>
  );
```

Both supported credential-entry paths remain visible: the original token form and pairing guidance. The feature `pages/components/AuthGate.tsx` is the reusable hint, not a substitute for `api/AuthGate.tsx`. The header slot supplies only brand/theme while locked; no protected reads or palette mount. `/pair` returns bare before either gate and before any protected query/socket. Update the shell regression to assert Token/Unlock alongside the existing pairing line, brand and colour-mode button; `/auth/me` 404 never removes the token gate.

In `ui/src/shell/Header.tsx`, replace

```tsx
export interface HeaderProps {
  /** Opens the command palette. */
  onFind?: () => void;
}
```

with

```tsx
export interface HeaderProps {
  /** Opens the command palette. */
  onFind?: () => void;
  /** The hub answered 401: only the brand and the theme toggle (Task 7 draws it). */
  locked?: boolean;
}
```

and in `Header`, replace

```tsx
  return (
    <header className="bar">
      <div className="bar-in">
        <Link className="brand" to="/" aria-label="Hypothex, overview">
          <BrandMark />
          <span>Hypothex</span>
        </Link>
        <nav className="tabs" aria-label="Screens">
```

with

```tsx
  if (locked) {
    return (
      <header className="bar">
        <div className="bar-in">
          <Link className="brand" to="/" aria-label="Hypothex, overview">
            <BrandMark />
            <span>Hypothex</span>
          </Link>
          <div className="bar-r">
            <ThemeToggle />
          </div>
        </div>
      </header>
    );
  }
  return (
    <header className="bar">
      <div className="bar-in">
        <Link className="brand" to="/" aria-label="Hypothex, overview">
          <BrandMark />
          <span>Hypothex</span>
        </Link>
        <nav className="tabs" aria-label="Screens">
```

and change its signature to `export function Header({ onFind, locked = false }: HeaderProps) {`.

In `ui/src/api/AuthGate.tsx`, move its existing `const qc = useQueryClient()` and reset `useEffect` out of `AuthGate` into this exported wrapper (keep their imports). It must remain mounted on the public pairing page, where selecting the cookie credential also resets protected cache data:

```tsx
export function SessionReset({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  useEffect(() => auth.onReset(() => clearSessionQueries(qc)), [qc]);
  return <>{children}</>;
}
```

In `ui/src/main.tsx`, replace the `AuthGate` import with `SessionReset`, remove the `LiveUpdates` import, and replace the old `AuthGate`/`LiveUpdates` wrappers with `SessionReset`. The router-aware `AppShell` owns the gates/live stream; the reset listener owns the query client's entire lifetime, including `/pair`:

```tsx
    <QueryClientProvider client={queryClient}>
      <SessionReset><RouterProvider router={router} /></SessionReset>
    </QueryClientProvider>
```

Apply the same wrapper in the `renderApp` test helper. Keep other providers and defaults. Add a regression that starts with a populated protected query cache, renders `/pair` with no protected requests, completes pairing, and verifies `auth.select(null)` synchronously clears the old cache and stops any prior stream before the cookie-authenticated shell mounts. The listener is registered exactly once per query-client lifetime; the token form no longer installs a second copy.

At the Pair page's successful `api.pair` completion, call `auth.select(null)` before any navigation or page reload. This removes root bearer/session-storage selection; subsequent requests use the newly set HttpOnly cookie. Import the existing `auth` instance rather than creating a second provider. Tests must pair while a root bearer is selected and assert the next `/auth/me`/projects request has no Authorization header and resolves the cookie principal. Keep root-mode unlock, intentional no-auth, `/pair` with no requests, and `/auth/me` 404 gate tests.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `bun test test/pages/authGate.test.tsx test/shell test/router.test.tsx && bun run typecheck`
Expected: `authGate.test.tsx` 1 pass, `AppShell.test.tsx` 2 pass; `Header.test.tsx`, `CommandPalette.test.tsx`, `ThemeToggle.test.tsx` and `router.test.tsx` pass unchanged (their fixtures provide valid transport credentials or explicit no-auth; `/auth/me` 404 alone does not open the gate); `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 6: Commit (repo root)**

```bash
git add ui/src/pages/components/AuthGate.tsx ui/src/router.tsx ui/src/main.tsx ui/src/shell/Header.tsx ui/test/pages/authGate.test.tsx ui/test/shell/AppShell.test.tsx
git commit -m "feat(ui): 401 gate; one /auth/me per app; no event stream on /pair"
```

---

### Task 6: The pair page `/pair`

**Files:**
- Create: `ui/src/pages/components/pairing.ts`
- Create: `ui/src/pages/Pair.tsx`
- Modify: `ui/src/shell/Header.tsx` (export `BrandMark`)
- Modify: `ui/src/router.tsx` (doc comment, import, route, route tree)
- Create: `ui/test/pages/pairing.test.ts`, `ui/test/pages/Pair.test.tsx`
- Modify: `ui/test/router.test.tsx` (the route list; one new test)

**Interfaces:**
- Consumes: Task 2 `api.pair`, `ApiError`; `PAIR_PATH`, `PAIR_COMMAND` (Task 5); `CopyButton`.
- Produces:
  - `pairing.ts`: `interface PairLink { offerId: string; secret: string }`; `parseFragment(hash): PairLink | null` (`#p_<12 hex>.<secret>`; the secret is base64url, 16–128 characters); `deviceName(userAgent): string` (`MacBook`, `iPhone`, `iPad`, `Android`, `Windows PC`, `Chromebook`, `Linux`, else `browser`); `DEVICE_MAX = 64`; `cleanDevice(text, fallback): string`; `pairFailure(err): string` (400 → `link invalid or expired`, 429 → `429 · wait 1m`, network → `hub unreachable`, else `<status> · <message>`).
  - `PairPage({ hash?, userAgent?, host? })` (test seams; the app passes none). States: ready (device field, `pair`), done (`✓ <user> · <scope>`, plain `<a href="/">overview →</a>` for a full page load with the new cookie), failed (`✗ <reason>` and the `hx pair` command).
  - Router: `pairRoute` (path `/pair`).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/pairing.test.ts`:

```ts
import { expect, test } from "bun:test";
import { ApiError } from "../../src/api/client";
import { DEVICE_MAX, cleanDevice, deviceName, pairFailure, parseFragment } from "../../src/pages/components/pairing";

const SECRET = "kX2mQ9vR7tLw4pYc8zNf1aJ3sD6hG0eUiBqTnW5oVyM";

test("parseFragment accepts #p_<12 hex>.<base64url secret> only", () => {
  expect(parseFragment(`#p_3f9a2c71e0b4.${SECRET}`)).toEqual({ offerId: "p_3f9a2c71e0b4", secret: SECRET });
  expect(parseFragment(`p_3f9a2c71e0b4.${SECRET}`)).toEqual({ offerId: "p_3f9a2c71e0b4", secret: SECRET });
  for (const bad of [
    "",
    "#",
    `#p_3f9a2c71e0b4`,
    `#p_3F9A2C71E0B4.${SECRET}`,
    `#p_3f9a2c71e0.${SECRET}`,
    "#p_3f9a2c71e0b4.short",
    `#p_3f9a2c71e0b4.${SECRET}=`,
    `#s_3f9a2c71e0b4.${SECRET}`,
  ]) {
    expect([bad, parseFragment(bad)]).toEqual([bad, null]);
  }
});

test("deviceName and cleanDevice", () => {
  const ua = (s: string) => `Mozilla/5.0 (${s}) AppleWebKit/605.1.15`;
  expect(
    [
      ua("Macintosh; Intel Mac OS X 14_6"),
      ua("iPhone; CPU iPhone OS 18_0 like Mac OS X"),
      ua("iPad; CPU OS 18_0 like Mac OS X"),
      ua("Linux; Android 15; Pixel 9"),
      ua("Windows NT 10.0; Win64; x64"),
      ua("X11; CrOS x86_64 16002.44.0"),
      ua("X11; Linux x86_64"),
      "curl/8.7.1",
    ].map(deviceName),
  ).toEqual(["MacBook", "iPhone", "iPad", "Android", "Windows PC", "Chromebook", "Linux", "browser"]);
  expect(cleanDevice("  lab laptop  ", "MacBook")).toBe("lab laptop");
  expect(cleanDevice("   ", "MacBook")).toBe("MacBook");
  expect(cleanDevice("x".repeat(80), "MacBook")).toHaveLength(DEVICE_MAX);
});

test("pairFailure: one message for every bad link, then rate limit, network, others", () => {
  const err = (status: number, error: string, type: string) => ApiError.from(status, { error, type });
  expect(
    [
      err(400, "pairing link invalid or expired; run hx pair again", "PairingError"),
      err(429, "too many attempts", "HTTPError"),
      new ApiError(0, "Cannot reach hx serve", "NetworkError", [], null),
      err(500, "boom", "HTTPError"),
      new Error("odd"),
    ].map(pairFailure),
  ).toEqual(["link invalid or expired", "429 · wait 1m", "hub unreachable", "500 · boom", "odd"]);
});
```

Create `ui/test/pages/Pair.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { fireEvent, screen } from "@testing-library/react";
import { PairPage } from "../../src/pages/Pair";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";

const SECRET = "kX2mQ9vR7tLw4pYc8zNf1aJ3sD6hG0eUiBqTnW5oVyM";
const HASH = `#p_3f9a2c71e0b4.${SECRET}`;
const MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15";
const ALICE = { user: "alice", scope: "launch", scopes: ["read", "launch"], session_id: "s_91d0aa3f62c8" };

afterEach(() => {
  restoreFetch();
  window.history.replaceState(null, "", "/");
});

test("ready: the device comes from the user agent; hub and offer shown", () => {
  mockApi({});
  renderWithClient(<PairPage hash={HASH} userAgent={MAC} host="hub.tail1234.ts.net" />);
  expect((screen.getByLabelText("device") as HTMLInputElement).value).toBe("MacBook");
  expect(screen.getByText("hub.tail1234.ts.net · p_3f9a2c71…")).toBeTruthy();
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("pair");
});

test("pair strips the fragment before posting and sends the secret only in the body", async () => {
  window.history.replaceState(null, "", `/pair${HASH}`);
  const calls = mockApi({ "POST /api/v1/auth/pair": ALICE });
  renderWithClient(<PairPage userAgent={MAC} host="hub.tail1234.ts.net" />);
  expect(window.location.hash).toBe("");
  expect(window.location.pathname).toBe("/pair");
  fireEvent.change(screen.getByLabelText("device"), { target: { value: "MacBook Air" } });
  fireEvent.click(screen.getByRole("button", { name: "pair" }));
  expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("✓ alice · launch");
  expect(calls).toEqual([
    {
      method: "POST",
      url: "/api/v1/auth/pair",
      body: { offer_id: "p_3f9a2c71e0b4", secret: SECRET, device: "MacBook Air", client: "browser" },
    },
  ]);
  expect(calls.some((c) => c.url.includes(SECRET))).toBe(false);
  expect(screen.getByRole("link", { name: "overview →" }).getAttribute("href")).toBe("/");
});

test("a used or expired link: one message, and the command to get a new one", async () => {
  mockApi({
    "POST /api/v1/auth/pair": new HttpReply(400, {
      error: "pairing link invalid or expired; run hx pair again",
      type: "PairingError",
    }),
  });
  renderWithClient(<PairPage hash={HASH} userAgent={MAC} host="hub.tail1234.ts.net" />);
  fireEvent.click(screen.getByRole("button", { name: "pair" }));
  expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("✗ link invalid or expired");
  expect(screen.getByText("hx pair")).toBeTruthy();
});

test("no fragment (a reload after pairing): invalid at once, nothing sent", () => {
  const calls = mockApi({});
  renderWithClient(<PairPage hash="" userAgent={MAC} host="hub.tail1234.ts.net" />);
  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("✗ link invalid or expired");
  expect(screen.queryByRole("button", { name: "pair" })).toBeNull();
  expect(calls).toEqual([]);
});

test("429 asks to wait", async () => {
  mockApi({ "POST /api/v1/auth/pair": new HttpReply(429, { error: "too many attempts", type: "HTTPError" }) });
  renderWithClient(<PairPage hash={HASH} userAgent={MAC} host="hub.tail1234.ts.net" />);
  fireEvent.click(screen.getByRole("button", { name: "pair" }));
  expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("✗ 429 · wait 1m");
});
```

In `ui/test/router.test.tsx`, test `every route renders its own screen, not the placeholder`, replace (as left by phase 2 Task 21)

```tsx
  for (const path of ["/", "/t/toy/acc", "/t/toy/acc/edit/new", "/r/r1", "/x/r1/r2?metric=accuracy", "/s/rxn/s-7f3a"]) {
```

with

```tsx
  for (const path of [
    "/",
    "/t/toy/acc",
    "/t/toy/acc/edit/new",
    "/r/r1",
    "/x/r1/r2?metric=accuracy",
    "/s/rxn/s-7f3a",
    "/pair",
  ]) {
```

and add at the end of `describe("routes", ...)`:

```tsx
  test("/pair renders without the header and never asks /auth/me", async () => {
    const calls = mockRoutes({});
    const { router } = renderApp("/pair");
    await settled(router, "/pair");
    expect(document.querySelector("header.bar")).toBeNull();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("✗ link invalid or expired");
    expect(calls.map((c) => c.url)).toEqual([]);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/pairing.test.ts test/pages/Pair.test.tsx test/router.test.tsx`
Expected: FAIL. `error: Cannot find module '../../src/pages/components/pairing'` and `'../../src/pages/Pair'`; in the router file the new test fails (`/pair` renders Not found under the header) and `bun run typecheck` rejects `"/pair"` as a route id until the route exists.

- [ ] **Step 3: Write `pairing.ts`**

Create `ui/src/pages/components/pairing.ts`:

```ts
/**
 * The pair page's pure parts (phase 3 contract 1.10): the pairing link's fragment, a
 * default device name, and the short failure texts.
 *
 * A link is `<hub>/pair#<offer_id>.<secret>`: the browser never sends a fragment in a
 * request line, and the page sends the secret only in the `POST /api/v1/auth/pair` body.
 */
import { ApiError } from "../../api/client";

export interface PairLink {
  offerId: string;
  secret: string;
}

const OFFER = /^p_[0-9a-f]{12}$/;
/** 32 random bytes as base64url are 43 characters; allow 16-128, no padding. */
const SECRET = /^[A-Za-z0-9_-]{16,128}$/;

/** `#p_3f9a2c71e0b4.kX2m…` → `{offerId, secret}`; null for anything else. */
export function parseFragment(hash: string): PairLink | null {
  const raw = hash.startsWith("#") ? hash.slice(1) : hash;
  const dot = raw.indexOf(".");
  if (dot < 0) return null;
  const offerId = raw.slice(0, dot);
  const secret = raw.slice(dot + 1);
  return OFFER.test(offerId) && SECRET.test(secret) ? { offerId, secret } : null;
}

/** A short device name from the user agent, shown in the session list: `MacBook`, `iPhone`, … */
export function deviceName(userAgent: string): string {
  if (/iPhone/.test(userAgent)) return "iPhone";
  if (/iPad/.test(userAgent)) return "iPad";
  if (/Android/.test(userAgent)) return "Android";
  if (/Macintosh|Mac OS X/.test(userAgent)) return "MacBook";
  if (/Windows/.test(userAgent)) return "Windows PC";
  if (/CrOS/.test(userAgent)) return "Chromebook";
  if (/Linux/.test(userAgent)) return "Linux";
  return "browser";
}

/** Longest device name sent. */
export const DEVICE_MAX = 64;

/** The typed device name, trimmed and cut to `DEVICE_MAX`; `fallback` when blank. */
export function cleanDevice(text: string, fallback: string): string {
  const name = text.trim().slice(0, DEVICE_MAX);
  return name === "" ? fallback : name;
}

/**
 * Short text for a failed pairing. The hub gives one message for an unknown, expired, used
 * or wrong-secret link (400), so the page does too.
 */
export function pairFailure(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 400) return "link invalid or expired";
    if (err.status === 429) return "429 · wait 1m";
    if (err.status === 0) return "hub unreachable";
    return `${err.status} · ${err.message}`;
  }
  return err instanceof Error ? err.message : String(err);
}
```

- [ ] **Step 4: Write `Pair.tsx`, export `BrandMark`, add the route**

In `ui/src/shell/Header.tsx`, replace `function BrandMark() {` with `export function BrandMark() {`.

Create `ui/src/pages/Pair.tsx`:

```tsx
/**
 * `/pair` (phase 3 contract 1.10, mockup `shot-pair-*`): redeem a one-time pairing link in
 * this browser. Public: no header, no `/auth/me`, no event stream (Task 5).
 *
 * The secret is in the URL fragment. The page reads it once, removes it from the address
 * bar and the history entry at once (`history.replaceState`), and sends it only in the
 * POST body. On success the hub sets the `hx_session` cookie; `overview →` is a plain link,
 * so the app loads again with the cookie and opens its event stream.
 */
import { auth } from "../api/auth";
import { createElement, type FormEvent, useEffect, useState } from "react";
import { api } from "../api/client";
import type { PairResult } from "../api/models";
import { BrandMark } from "../shell/Header";
import { PAIR_COMMAND } from "./components/AuthGate";
import { CopyButton } from "./components/CopyButton";
import { cleanDevice, DEVICE_MAX, deviceName, pairFailure, parseFragment } from "./components/pairing";

export const PAIR_CSS = `
.pair { min-height: 100vh; display: grid; place-items: center; }
.pair .pair-in { width: 460px; padding: 40px 0; }
.pair .brand { display: flex; align-items: center; gap: 10px; font: 600 24px/1 var(--serif); margin-bottom: 40px; }
.pair h1 { margin: 0 0 6px; font: 500 34px/1.1 var(--serif); letter-spacing: -.012em; }
.pair h1 .ok { color: var(--best); }
.pair h1 .bad { color: var(--fail); }
.pair .hub { font: 400 13px var(--mono); color: var(--ink-3); }
.pair form, .pair .res { display: flex; gap: 10px; align-items: center; margin-top: 28px; padding-top: 22px; border-top: 1px solid var(--rule); }
.pair form label { font-weight: 550; font-size: 14px; width: 64px; }
.pair .in { flex: 1; height: 32px; border: 1px solid var(--rule); border-radius: 6px; background: transparent; padding: 0 10px; font-size: 14px; color: var(--ink); }
.pair .chipc { display: inline-flex; align-items: center; gap: 8px; height: 34px; padding: 0 6px 0 12px; background: var(--paper-2); border-radius: 6px; }
.pair .chipc code { font-size: 13.5px; color: var(--ink); }
`;

export interface PairPageProps {
  /** The fragment; default `window.location.hash` (tests pass it). */
  hash?: string;
  /** Default `navigator.userAgent`. */
  userAgent?: string;
  /** The hub's host shown on the page; default `window.location.host`. */
  host?: string;
}

type PairState =
  | { phase: "ready" }
  | { phase: "sending" }
  | { phase: "done"; result: PairResult; device: string }
  | { phase: "failed"; text: string };

export function PairPage({ hash, userAgent, host }: PairPageProps = {}) {
  const [link] = useState(() => parseFragment(hash ?? window.location.hash));
  const fallback = deviceName(userAgent ?? navigator.userAgent);
  const [device, setDevice] = useState(fallback);
  const [state, setState] = useState<PairState>(() =>
    link ? { phase: "ready" } : { phase: "failed", text: "link invalid or expired" },
  );
  const hub = host ?? window.location.host;

  useEffect(() => {
    // the secret leaves the address bar and the history entry before anything is sent
    if (window.location.hash !== "") {
      window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}`);
    }
  }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (link === null || state.phase === "sending") return;
    const name = cleanDevice(device, fallback);
    setState({ phase: "sending" });
    try {
      const result = await api.pair({ offer_id: link.offerId, secret: link.secret, device: name, client: "browser" });
      auth.select(null); // the new HttpOnly session replaces any selected root bearer
      setState({ phase: "done", result, device: name });
    } catch (err) {
      setState({ phase: "failed", text: pairFailure(err) });
    }
  };

  let body;
  if (state.phase === "done") {
    body = (
      <>
        <h1>
          <span className="ok">✓</span> {`${state.result.user} · ${state.result.scope}`}
        </h1>
        <p className="hub" title={state.result.session_id}>{`${hub} · ${state.device}`}</p>
        <div className="res">
          {/* a full page load: the app starts again with the new cookie */}
          <a className="btn primary" href="/">
            overview →
          </a>
        </div>
      </>
    );
  } else if (state.phase === "failed") {
    body = (
      <>
        <h1>
          <span className="bad">✗</span> {state.text}
        </h1>
        <p className="hub">{hub}</p>
        <div className="res" title="Run this on the hub for a new link">
          <span className="chipc">
            <code>{PAIR_COMMAND}</code>
            <CopyButton text={PAIR_COMMAND} label={PAIR_COMMAND} />
          </span>
        </div>
      </>
    );
  } else {
    const offer = link?.offerId ?? "";
    body = (
      <>
        <h1>pair</h1>
        <p className="hub" title={`offer ${offer}, one use`}>{`${hub} · ${offer.slice(0, 10)}…`}</p>
        <form onSubmit={submit}>
          <label htmlFor="pair-device">device</label>
          <input
            id="pair-device"
            className="in"
            value={device}
            maxLength={DEVICE_MAX}
            onChange={(e) => setDevice(e.target.value)}
            title="Shown in the session list"
          />
          <button className="btn primary" type="submit" disabled={state.phase === "sending"}>
            pair
          </button>
        </form>
      </>
    );
  }

  return (
    <div className="pair">
      {createElement("style", { "data-hx": "pair" }, PAIR_CSS)}
      <div className="pair-in">
        <span className="brand">
          <BrandMark />
          <span>Hypothex</span>
        </span>
        {body}
      </div>
    </div>
  );
}
```

In `ui/src/router.tsx`: add `` `/pair` Pair (no header) `` to the doc comment's route list; add `import { PairPage } from "./pages/Pair";` after the `OverviewPage` import; after `examplesRoute`, add

```tsx
export const pairRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: PAIR_PATH,
  component: PairPage,
});
```

and add `pairRoute,` as the last entry of `rootRoute.addChildren([...])`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `bun test test/pages/pairing.test.ts test/pages/Pair.test.tsx test/router.test.tsx && bun run typecheck`
Expected: `pairing.test.ts` 3 pass, `Pair.test.tsx` 5 pass, `router.test.tsx` passes with its new test; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 6: Commit (repo root)**

```bash
git add ui/src/pages/components/pairing.ts ui/src/pages/Pair.tsx ui/src/shell/Header.tsx ui/src/router.tsx ui/test/pages/pairing.test.ts ui/test/pages/Pair.test.tsx ui/test/router.test.tsx
git commit -m "feat(ui): /pair redeems a pairing link from the fragment without a header"
```

---

### Task 7: Header links, the user chip, and the new paths

**Files:**
- Create: `ui/src/pages/components/scopes.ts`
- Modify: `ui/src/shell/Header.tsx` (whole file below)
- Modify: `ui/src/pages/components/links.tsx` (`hrefs`; `isAppPath`)
- Modify: `ui/test/shell/Header.test.tsx` (`updateRecent` expectation)
- Modify: `ui/test/pages/links.test.tsx` (the `isAppPath` list)
- Create: `ui/test/shell/headerPhase3.test.tsx`

**Interfaces:**
- Consumes: Task 2 `usePrincipal`, `authOn`, `isAdmin`; `AppLink` (exists).
- Produces:
  - `scopes.ts`: `SCOPES: readonly Scope[]` (`read, launch, admin`); `SCOPE_GLYPH: Record<Scope, string>` (`r`, `l`, `a`); `covers(held, wanted): boolean`; `scopesUpTo(held): Scope[]`.
  - `links.tsx`: `hrefs.notebook(project, day?)` (`/n/<project>[/<day>]`), `hrefs.settings()`, `hrefs.storage()`; `isAppPath` accepts `/n/…`, `/settings`, `/storage` (never `/pair`, which must load in full).
  - `Header.tsx`: `Screen` adds `notebook | settings | storage`; `screenOf` maps them; `projectOf(pathname)` (task, sweep and notebook paths); `RecentTargets.project?: { name }` kept by `updateRecent`/`parseRecent`; the right side shows `notebook` (last project; hidden until there is one), `storage` (admins), `⚙` (`aria-label="Settings"`), the chip `@user` plus scope glyph (auth on only); `locked` keeps brand and theme only.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/shell/headerPhase3.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { screen, waitFor } from "@testing-library/react";
import { covers, SCOPE_GLYPH, scopesUpTo } from "../../src/pages/components/scopes";
import { RECENT_KEY, confirmKeys, parseRecent, projectOf, screenOf, updateRecent } from "../../src/shell/Header";
import { ME_ADMIN, ME_ALICE, ME_OFF } from "../api/phase3-fixtures";
import { mockApi, restoreFetch } from "../pages/helpers";
import { renderApp } from "../render-app";

afterEach(restoreFetch);

describe("paths", () => {
  test("screenOf maps the phase 3 screens; projectOf reads task, sweep and notebook paths", () => {
    expect(["/n/deepretro", "/n/deepretro/2026-10-04", "/settings", "/storage", "/pair"].map(screenOf)).toEqual([
      "notebook",
      "notebook",
      "settings",
      "storage",
      null,
    ]);
    expect(["/t/deep%20retro/topk", "/s/rxn/s-7f3a", "/n/deepretro/2026-10-04", "/r/r1", "/"].map(projectOf)).toEqual([
      "deep retro",
      "rxn",
      "deepretro",
      null,
      null,
    ]);
  });

  test("updateRecent keeps the last project; parseRecent keeps a well-formed one", () => {
    let r = updateRecent({}, "/t/toy/acc", {});
    r = updateRecent(r, "/n/deepretro", {});
    r = updateRecent(r, "/r/r1", {});
    expect(r.project).toEqual({ name: "deepretro" });
    expect(parseRecent({ project: { name: "deepretro" } })).toEqual({ project: { name: "deepretro" } });
    expect(parseRecent({ project: { name: "" } })).toEqual({});
  });
});

test("new project recents require the page's successful read", () => {
  expect(confirmKeys("/s/toy/s-0001")).toEqual([["sweeps", "toy", "detail", "s-0001"]]);
  expect(confirmKeys("/n/toy")).toEqual([["notebook", "toy", "day", "today"]]);
  expect(confirmKeys("/n/toy/2026-10-04")).toEqual([["notebook", "toy", "day", "2026-10-04"]]);
});

test("scopes: order, glyphs, what a scope covers", () => {
  expect(SCOPE_GLYPH).toEqual({ read: "r", launch: "l", admin: "a" });
  expect([covers("admin", "launch"), covers("launch", "launch"), covers("read", "launch")]).toEqual([true, true, false]);
  expect([scopesUpTo("read"), scopesUpTo("launch"), scopesUpTo("admin")]).toEqual([
    ["read"],
    ["read", "launch"],
    ["read", "launch", "admin"],
  ]);
});

describe("right side of the header", () => {
  const links = () => ({
    notebook: screen.queryByRole("link", { name: "notebook" })?.getAttribute("href") ?? null,
    storage: screen.queryByRole("link", { name: "storage" })?.getAttribute("href") ?? null,
    settings: screen.queryByRole("link", { name: "Settings" })?.getAttribute("href") ?? null,
  });

  test("admin with auth on: notebook of the last project, storage, settings, and @sv a", async () => {
    localStorage.setItem(RECENT_KEY, JSON.stringify({ project: { name: "deepretro" } }));
    mockApi({ "GET /api/v1/auth/me": ME_ADMIN });
    renderApp("/");
    const chip = await screen.findByTitle("sv, scope admin, session s_4b1e09c2d7a3");
    expect(chip.textContent).toBe("@sva");
    expect(links()).toEqual({ notebook: "/n/deepretro", storage: "/storage", settings: "/settings" });
  });

  test("a collaborator: no storage link; @alice l", async () => {
    mockApi({ "GET /api/v1/auth/me": ME_ALICE });
    renderApp("/");
    expect((await screen.findByTitle("alice, scope launch, session s_91d0aa3f62c8")).textContent).toBe("@alicel");
    expect(links()).toEqual({ notebook: null, storage: null, settings: "/settings" });
  });

  test("auth off: no chip; the local owner keeps storage and settings", async () => {
    mockApi({ "GET /api/v1/auth/me": ME_OFF });
    renderApp("/");
    await waitFor(() => expect(links().storage).toBe("/storage"));
    expect(document.querySelector(".bar .me")).toBeNull();
  });

  test("a hub without /auth/me: no chip, no storage, settings link kept", async () => {
    const calls = mockApi({});
    renderApp("/");
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/auth/me")).toBe(true));
    expect(links()).toEqual({ notebook: null, storage: null, settings: "/settings" });
    expect(document.querySelector(".bar .me")).toBeNull();
  });
});
```

In `ui/test/shell/Header.test.tsx`, test `records the task, run and example pair, decoding segments`, replace

```tsx
    expect(r).toEqual({
      task: { project: "my proj", task: "acc" },
      run: { runId: "r-9" },
      examples: { a: "r1", b: "r2", metric: "accuracy" },
    });
```

with

```tsx
    expect(r).toEqual({
      task: { project: "my proj", task: "acc" },
      run: { runId: "r-9" },
      examples: { a: "r1", b: "r2", metric: "accuracy" },
      project: { name: "my proj" },
    });
```

and in test `remembers the last task and run as tabs`, replace

```tsx
    expect(JSON.parse(localStorage.getItem(RECENT_KEY) ?? "{}")).toEqual({
      task: { project: "toy", task: "acc" },
      run: { runId: "r-7" },
    });
```

with

```tsx
    expect(JSON.parse(localStorage.getItem(RECENT_KEY) ?? "{}")).toEqual({
      task: { project: "toy", task: "acc" },
      run: { runId: "r-7" },
      project: { name: "toy" },
    });
```

In `ui/test/pages/links.test.tsx`, replace (as left by phase 2 Task 21)

```tsx
    expect(["/", "/t/p/t", "/r/r1", "/x/a/b", "/s/p/s-1", "/api/v1/runs", "/mcp", "/rx"].map(isAppPath)).toEqual([
      true,
      true,
      true,
      true,
      true,
      false,
      false,
      false,
    ]);
```

with

```tsx
    expect(
      [
        "/",
        "/t/p/t",
        "/r/r1",
        "/x/a/b",
        "/s/p/s-1",
        "/n/p",
        "/n/p/2026-10-04",
        "/settings",
        "/storage",
        "/pair",
        "/settingsx",
        "/api/v1/runs",
        "/mcp",
        "/rx",
      ].map(isAppPath),
    ).toEqual([true, true, true, true, true, true, true, true, true, false, false, false, false, false]);
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/shell test/pages/links.test.tsx`
Expected: FAIL. `headerPhase3.test.tsx`: `error: Cannot find module '../../src/pages/components/scopes'`; `Header.test.tsx`: the `updateRecent` and `remembers the last task and run as tabs` tests fail (no `project` key yet); `links.test.tsx`: `isAppPath("/n/p")` is `false`.

- [ ] **Step 3: Write `scopes.ts` and the hrefs**

Create `ui/src/pages/components/scopes.ts`:

```ts
/** Scopes in the UI (phase 3 contract 1.10): `read ⊂ launch ⊂ admin`, and their one-letter glyphs. */
import type { Scope } from "../../api/models";

export const SCOPES: readonly Scope[] = ["read", "launch", "admin"];

export const SCOPE_GLYPH: Record<Scope, string> = { read: "r", launch: "l", admin: "a" };

/** True when `held` covers `wanted` (`admin` covers everything). */
export function covers(held: Scope, wanted: Scope): boolean {
  return SCOPES.indexOf(held) >= SCOPES.indexOf(wanted);
}

/** Every scope `held` may hand out: pairing never widens scope. */
export function scopesUpTo(held: Scope): Scope[] {
  return SCOPES.filter((s) => covers(held, s));
}
```

In `ui/src/pages/components/links.tsx`, replace

```tsx
  examples: (a: string, b: string, metric?: string): string =>
    withSearch(`/x/${enc(a)}/${enc(b)}`, { metric }),
};
```

with

```tsx
  examples: (a: string, b: string, metric?: string): string =>
    withSearch(`/x/${enc(a)}/${enc(b)}`, { metric }),
  notebook: (project: string, day?: string): string =>
    day ? `/n/${enc(project)}/${enc(day)}` : `/n/${enc(project)}`,
  settings: (): string => "/settings",
  storage: (): string => "/storage",
};
```

Replace the whole `isAppPath` function (as left by phase 2 Task 21)

```tsx
/** True for a path the SPA routes (Overview, Task, Run, Examples, Sweep); `/api/…` is left to the browser. */
export function isAppPath(pathname: string): boolean {
  return /^\/($|[trsx]\/)/.test(pathname);
}
```

with

```tsx
/**
 * True for a path the SPA routes (Overview, Task, Run, Examples, Sweep, Notebook, Settings,
 * Storage); `/api/…` is left to the browser, and so is `/pair` (it must load in full).
 */
export function isAppPath(pathname: string): boolean {
  return /^\/($|[trsxn]\/|settings$|storage$)/.test(pathname);
}
```

Keep all merged `Header.test.tsx` not-found and pending-read regressions. Extend those cases to a failed/pending notebook day and sweep read: the previous project recent must remain until the requested page query succeeds; a 404 must never replace it. The helper reads only cache state and must not launch duplicate queries. Keep `OverviewLists` grouped failure/retry tests while adding an owner to both a retry-ok and retry-failed row.

- [ ] **Step 4: Replace `Header.tsx`**

Replace the whole of `ui/src/shell/Header.tsx` with:

```tsx
/**
 * Sticky top bar from the ui-v4 mockup and docs/mockups/phase3: brand, screen tabs, and on
 * the right the live status, `notebook` (the last project's notebook), `storage` (admins),
 * `⚙` settings, the user chip `@sv a` (auth on only), find, and the theme toggle.
 *
 * Tabs: Overview always; Task, Run and Examples point at the last task, run and example
 * pair the user opened (kept in localStorage) and are hidden until there is one. While the
 * app is locked (the hub said 401), only the brand and the theme toggle stay.
 */
import { type QueryKey, useQueryClient } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { createElement, useCallback, useEffect, useState, useSyncExternalStore } from "react";

import { authOn, isAdmin, usePrincipal } from "../api/auth";
import { useStreamStatus } from "../api/events";
import type { Principal } from "../api/models";
import { queryKeys } from "../api/queries";
import { AppLink, hrefs } from "../pages/components/links";
import { SCOPE_GLYPH } from "../pages/components/scopes";
import { ThemeToggle } from "./ThemeToggle";

export type Screen = "overview" | "task" | "run" | "examples" | "notebook" | "settings" | "storage";

export interface RecentTargets {
  task?: { project: string; task: string };
  run?: { runId: string };
  examples?: { a: string; b: string; metric?: string };
  /** The last project opened on a task, sweep or notebook page (the `notebook` link). */
  project?: { name: string };
}

export const RECENT_KEY = "hx-recent";

const seg = (s: string): string => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

/** Which screen a pathname belongs to (the view editor counts as the task screen). */
export function screenOf(pathname: string): Screen | null {
  if (pathname === "/" || pathname === "") return "overview";
  if (/^\/t\/[^/]+\/[^/]+(\/edit\/[^/]+)?\/?$/.test(pathname)) return "task";
  if (/^\/r\/[^/]+\/?$/.test(pathname)) return "run";
  if (/^\/x\/[^/]+\/[^/]+\/?$/.test(pathname)) return "examples";
  if (/^\/n\/[^/]+(\/[^/]+)?\/?$/.test(pathname)) return "notebook";
  if (/^\/settings\/?$/.test(pathname)) return "settings";
  if (/^\/storage\/?$/.test(pathname)) return "storage";
  return null;
}

/** The project in a task, sweep or notebook path; null elsewhere. */
export function projectOf(pathname: string): string | null {
  const m = /^\/[tsn]\/([^/]+)/.exec(pathname);
  return m?.[1] ? seg(m[1]) : null;
}

/** Remember the task, run, example pair or project in `pathname` (other screens leave `prev` as is). */
export function updateRecent(prev: RecentTargets, pathname: string, search: Record<string, unknown>): RecentTargets {
  const parts = pathname.split("/").filter(Boolean).map(seg);
  const project = projectOf(pathname);
  const next = project ? { ...prev, project: { name: project } } : prev;
  switch (screenOf(pathname)) {
    case "task":
      return { ...next, task: { project: parts[1] ?? "", task: parts[2] ?? "" } };
    case "run":
      return { ...next, run: { runId: parts[1] ?? "" } };
    case "examples": {
      const metric = typeof search.metric === "string" ? search.metric : undefined;
      return { ...next, examples: { a: parts[1] ?? "", b: parts[2] ?? "", metric } };
    }
    default:
      return next;
  }
}

type Json = Record<string, unknown>;

const isObject = (v: unknown): v is Json => typeof v === "object" && v !== null && !Array.isArray(v);
const isName = (v: unknown): v is string => typeof v === "string" && v !== "";

/** The well-formed entries of a stored value; anything else (old or corrupt) is dropped. */
export function parseRecent(value: unknown): RecentTargets {
  if (!isObject(value)) return {};
  const out: RecentTargets = {};
  const { task, run, examples, project } = value;
  if (isObject(task) && isName(task.project) && isName(task.task)) {
    out.task = { project: task.project, task: task.task };
  }
  if (isObject(run) && isName(run.runId)) out.run = { runId: run.runId };
  if (isObject(examples) && isName(examples.a) && isName(examples.b)) {
    out.examples = { a: examples.a, b: examples.b };
    if (isName(examples.metric)) out.examples.metric = examples.metric;
  }
  if (isObject(project) && isName(project.name)) out.project = { name: project.name };
  return out;
}

function loadRecent(): RecentTargets {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? parseRecent(JSON.parse(raw)) : {};
  } catch {
    return {};
  }
}

/**
 * The reads whose success shows the target in `pathname` exists: the ones its page makes
 * (Task and the view editor read the leaderboard; Run and Examples read their runs).
 */
export function confirmKeys(pathname: string): QueryKey[] {
  const { task, run, examples } = updateRecent({}, pathname, {});
  if (task) return [queryKeys.leaderboard(task.project, task.task)];
  if (run) return [queryKeys.run(run.runId)];
  if (examples) return [queryKeys.run(examples.a), queryKeys.run(examples.b)];
  const parts = pathname.split("/").filter(Boolean).map(seg);
  if (parts[0] === "s" && parts[1] && parts[2]) return [queryKeys.sweep(parts[1], parts[2])];
  if (parts[0] === "n" && parts[1]) {
    return [queryKeys.notebookDay(parts[1], parts[2] ?? "today")];
  }
  return [];
}

/**
 * True once every read in `keys` has succeeded. It only watches the cache (an observer
 * here would fetch, or pass its options on to the page's query).
 */
function useReadsOk(keys: QueryKey[]): boolean {
  const client = useQueryClient();
  const cache = client.getQueryCache();
  const subscribe = useCallback((onChange: () => void) => cache.subscribe(onChange), [cache]);
  const ok = () => keys.every((key) => client.getQueryState(key)?.status === "success");
  return useSyncExternalStore(subscribe, ok, ok);
}

function useRecentTargets(pathname: string, search: Record<string, unknown>): RecentTargets {
  const [recent, setRecent] = useState<RecentTargets>(loadRecent);
  const confirmed = useReadsOk(confirmKeys(pathname));
  useEffect(() => {
    if (!confirmed) return;
    setRecent((prev) => {
      const next = updateRecent(prev, pathname, search);
      try {
        localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      } catch {
        // storage disabled: tabs still work for this page
      }
      return next;
    });
  }, [confirmed, pathname, search]);
  return recent;
}

/** The brand mark: the best idea's band, a diamond on it, a dot for the baseline. */
export function BrandMark() {
  return (
    <svg width="22" height="18" viewBox="0 0 22 18" aria-hidden="true">
      <rect x="9" y="1" width="8" height="16" style={{ fill: "var(--best-wash)" }} />
      <line x1="9" y1="1" x2="9" y2="17" style={{ stroke: "var(--best-edge)" }} />
      <line x1="17" y1="1" x2="17" y2="17" style={{ stroke: "var(--best-edge)" }} />
      <line x1="1" y1="9" x2="21" y2="9" style={{ stroke: "var(--ink)", strokeWidth: 1.4 }} />
      <rect x="10" y="5" width="5.6" height="5.6" transform="rotate(45 12.8 7.8)" style={{ fill: "var(--best)" }} />
      <circle cx="4" cy="9" r="2.6" style={{ fill: "var(--ink)" }} />
    </svg>
  );
}

/** "⌘K" on Apple platforms, "Ctrl K" elsewhere. */
export function paletteShortcut(platform: string = navigator.platform): string {
  return /Mac|iPhone|iPad/.test(platform) ? "⌘K" : "Ctrl K";
}

/** A dot and word while live updates are down; nothing while they are live. */
function LiveStatus() {
  const status = useStreamStatus();
  if (status === "ready") return null;
  const offline = status === "offline";
  return (
    <span
      className={offline ? "live off" : "live"}
      role="status"
      aria-label={`Live updates ${offline ? "off" : "reconnecting"}`}
      title={
        offline
          ? "Live updates are off: data is not live, reload to reconnect"
          : "Reconnecting live updates: data is not live yet"
      }
    >
      {offline ? "● offline" : "● connecting"}
    </span>
  );
}

const HEADER_CSS = `
.bar .hl { font-size: 13.5px; color: var(--ink-3); text-decoration: none; padding: 0 4px; white-space: nowrap; }
.bar .hl:hover, .bar .hl[aria-current="page"] { color: var(--ink); }
.bar .hl.ic { font-size: 16px; line-height: 1; }
.bar .me { display: inline-flex; align-items: center; gap: 6px; height: 28px; padding: 0 4px 0 9px; border: 1px solid var(--rule); border-radius: 99px; font-size: 13px; color: var(--ink); cursor: help; white-space: nowrap; }
.bar .me i { font: 600 11px/16px var(--mono); font-style: normal; width: 18px; text-align: center; border-radius: 99px; background: var(--paper-2); color: var(--ink-2); }
`;

/** `@sv` and the scope glyph; the tooltip names the scope and the session. */
function UserChip({ principal }: { principal: Principal }) {
  const session = principal.session_id ? `, session ${principal.session_id}` : "";
  return (
    <span className="me" title={`${principal.user}, scope ${principal.scope}${session}`}>
      @{principal.user}
      <i aria-label={`scope ${principal.scope}`}>{SCOPE_GLYPH[principal.scope]}</i>
    </span>
  );
}

export interface HeaderProps {
  /** Opens the command palette. */
  onFind?: () => void;
  /** The hub answered 401: only the brand and the theme toggle. */
  locked?: boolean;
}

export function Header({ onFind, locked = false }: HeaderProps) {
  const location = useRouterState({ select: (s) => s.location });
  const search = location.search as Record<string, unknown>;
  const recent = useRecentTargets(location.pathname, search);
  const principal = usePrincipal();
  const here = screenOf(location.pathname);
  const current = (s: Screen) => (here === s ? ("page" as const) : undefined);
  const brand = (
    <Link className="brand" to="/" aria-label="Hypothex, overview">
      <BrandMark />
      <span>Hypothex</span>
    </Link>
  );

  if (locked) {
    return (
      <header className="bar">
        <div className="bar-in">
          {brand}
          <div className="bar-r">
            <ThemeToggle />
          </div>
        </div>
      </header>
    );
  }

  return (
    <header className="bar">
      {createElement("style", { "data-hx": "header" }, HEADER_CSS)}
      <div className="bar-in">
        {brand}
        <nav className="tabs" aria-label="Screens">
          <Link to="/" aria-current={current("overview")}>
            Overview
          </Link>
          {recent.task && (
            <Link
              to="/t/$project/$task"
              params={recent.task}
              aria-current={current("task")}
              title={`${recent.task.project} / ${recent.task.task}`}
            >
              Task
            </Link>
          )}
          {recent.run && (
            <Link to="/r/$runId" params={recent.run} aria-current={current("run")} title={recent.run.runId}>
              Run
            </Link>
          )}
          {recent.examples && (
            <Link
              to="/x/$a/$b"
              params={{ a: recent.examples.a, b: recent.examples.b }}
              search={{ metric: recent.examples.metric }}
              aria-current={current("examples")}
              title={`${recent.examples.a} vs ${recent.examples.b}`}
            >
              Examples
            </Link>
          )}
        </nav>
        <div className="bar-r">
          <LiveStatus />
          {recent.project ? (
            <AppLink
              className="hl"
              href={hrefs.notebook(recent.project.name)}
              aria-current={current("notebook")}
              title={`Notebook, ${recent.project.name}`}
            >
              notebook
            </AppLink>
          ) : null}
          {isAdmin(principal) ? (
            <AppLink className="hl" href={hrefs.storage()} aria-current={current("storage")} title="Storage">
              storage
            </AppLink>
          ) : null}
          <AppLink
            className="hl ic"
            href={hrefs.settings()}
            aria-current={current("settings")}
            aria-label="Settings"
            title="Settings"
          >
            ⚙
          </AppLink>
          {authOn(principal) && principal ? <UserChip principal={principal} /> : null}
          <button className="find" id="findBtn" type="button" aria-haspopup="dialog" onClick={onFind}>
            <span>Find a run, task or path</span>
            <kbd>{paletteShortcut()}</kbd>
          </button>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `bun test test/shell test/pages/links.test.tsx test/router.test.tsx && bun run typecheck`
Expected: `headerPhase3.test.tsx` 7 pass; `Header.test.tsx` passes with the two updated expectations; `AppShell.test.tsx`, `links.test.tsx` and `router.test.tsx` pass; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 6: Commit (repo root)**

```bash
git add ui/src/pages/components/scopes.ts ui/src/shell/Header.tsx ui/src/pages/components/links.tsx ui/test/shell/headerPhase3.test.tsx ui/test/shell/Header.test.tsx ui/test/pages/links.test.tsx
git commit -m "feat(ui): header notebook, storage and settings links and the user chip"
```

---

### Task 8: Run ownership: `@owner`, owner-only stop, and `mine` on the Overview

**Files:**
- Create: `ui/src/pages/components/owner.ts`
- Modify: `ui/src/pages/components/StatusLine.tsx` (after the launcher span)
- Modify: `ui/src/pages/components/RunActions.tsx` (imports; the `Cancel` button; the `Stop` button of the other phases)
- Modify: `ui/src/pages/components/OverviewLists.tsx` (`RunningList` small line; `FailureList` small line)
- Modify: `ui/src/pages/components/IdeaList.tsx` (`IdeaLine` meta line)
- Modify: `ui/src/api/models.ts` (`owner?` at the end of `TimelineItem`, `IdeaRow`, `FailureRow`)
- Modify: `ui/src/pages/Overview.tsx` (imports; the `d Running` figure)
- Create: `ui/test/pages/owner.test.tsx`

**Interfaces:**
- Consumes: Task 2 `usePrincipal`, `authOn`, `PrincipalContext`; Task 7 `covers`; `queryKeys.runs`, `api.runs` (exist; `RunsQuery.owner` from Task 1).
- Produces:
  - `owner.ts`: `ownerLabel(owner): string | null` (`@alice`); `interface Permit { ok: boolean; why: string | null }`; `mayStop(principal, owner): Permit` (contract 1.3: no principal or auth off → ok, the server decides; below `launch` → no; admin → ok; `owner === user` → ok; otherwise `owned by @sv; stop needs owner or admin`, and an owner-less run is the hub owner's: `owned by the hub owner; …`).
  - `StatusLine` shows `@owner` (title `owner`) after the launcher when the record has one.
  - `RunActions` disables `Cancel` (queued/pending) and `Stop` for a principal that `mayStop` refuses, with the reason as the tooltip.
  - Overview: `@owner` at the end of each running row's small line, each recent idea's meta line and each failure's small line (backend Task 27 adds `owner` to `TimelineItem`, `IdeaRow`, `FailureRow`; models gain `owner?: string | null` on the three); with auth on, a `mine` toggle (`aria-pressed`) in the Running figure that lists `GET /api/v1/runs?owner=me&status=running` instead.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/owner.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { PrincipalContext } from "../../src/api/auth";
import type { Principal } from "../../src/api/models";
import { OverviewPage } from "../../src/pages/Overview";
import { mayStop, ownerLabel } from "../../src/pages/components/owner";
import { RunActions } from "../../src/pages/components/RunActions";
import { StatusLine } from "../../src/pages/components/StatusLine";
import { ME_ADMIN, ME_ALICE, ME_OFF } from "../api/phase3-fixtures";
import { makeOverview, makeRecord } from "./fixtures";
import { mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(restoreFetch);

const READER: Principal = { ...ME_ALICE, user: "bo", scope: "read", scopes: ["read"] };
const as = (p: Principal | null, ui: ReactElement) => (
  <PrincipalContext.Provider value={p}>{ui}</PrincipalContext.Provider>
);

describe("rules", () => {
  test("mayStop follows contract 1.3", () => {
    expect(
      [
        mayStop(null, "sv"),
        mayStop(ME_OFF, "sv"),
        mayStop(ME_ADMIN, "alice"),
        mayStop(ME_ALICE, "alice"),
        mayStop(ME_ALICE, "sv"),
        mayStop(ME_ALICE, null),
        mayStop(READER, "bo"),
      ].map((p) => [p.ok, p.why]),
    ).toEqual([
      [true, null],
      [true, null],
      [true, null],
      [true, null],
      [false, "owned by @sv; stop needs owner or admin"],
      [false, "owned by the hub owner; stop needs owner or admin"],
      [false, "stop needs scope launch"],
    ]);
    expect([ownerLabel("alice"), ownerLabel(null), ownerLabel(undefined), ownerLabel("")]).toEqual([
      "@alice",
      null,
      null,
      null,
    ]);
  });
});

describe("run page", () => {
  test("the status line names the owner after the launcher", () => {
    render(<StatusLine record={makeRecord({ owner: "alice", created_by: "human:alice" })} />);
    expect(screen.getByTitle("owner").textContent).toBe("@alice");
    render(<StatusLine record={makeRecord({ run_id: "r-x", owner: null })} />);
    expect(screen.getAllByTitle("owner")).toHaveLength(1);
  });

  test("a collaborator cannot stop the owner's run; the reason is the tooltip", () => {
    mockApi({});
    renderWithClient(as(ME_ALICE, <RunActions served hostsLoaded record={makeRecord({ status: "running", owner: "sv" })} />));
    const stop = screen.getByRole("button", { name: "Stop" }) as HTMLButtonElement;
    expect([stop.disabled, stop.title]).toEqual([true, "owned by @sv; stop needs owner or admin"]);
  });

  test("the owner and an admin can stop it", () => {
    mockApi({});
    const view = renderWithClient(as(ME_ALICE, <RunActions served hostsLoaded record={makeRecord({ status: "running", owner: "alice" })} />));
    expect((within(view.container).getByRole("button", { name: "Stop" }) as HTMLButtonElement).disabled).toBe(false);
    const admin = renderWithClient(as(ME_ADMIN, <RunActions served hostsLoaded record={makeRecord({ status: "running", owner: "alice" })} />));
    expect((within(admin.container).getByRole("button", { name: "Stop" }) as HTMLButtonElement).disabled).toBe(false);
  });

  test("a queued run of someone else: Cancel is disabled for a collaborator", () => {
    mockApi({});
    renderWithClient(
      as(ME_ALICE, <RunActions served hostsLoaded record={makeRecord({ status: "queued", owner: "sv" })} phase="queued" hostName="gpu1" />),
    );
    const cancel = screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement;
    expect([cancel.disabled, cancel.title]).toEqual([true, "owned by @sv; stop needs owner or admin"]);
  });
});

describe("overview", () => {
  const overview = () => {
    const base = makeOverview();
    const runs = [
      makeRecord({ run_id: "r-sv", hypothesis: "beam 5 baseline", status: "running", owner: "sv" }),
      makeRecord({ run_id: "r-al", hypothesis: "beam 10 holds", status: "running", owner: "alice" }),
    ];
    return { ...base, running: runs };
  };

  test("running rows end with @owner; mine lists the caller's running runs", async () => {
    const mine = [makeRecord({ run_id: "r-al", hypothesis: "beam 10 holds", status: "running", owner: "alice" })];
    const calls = mockApi({
      "GET /api/v1/overview": overview(),
      "GET /api/v1/hosts": [],
      "GET /api/v1/runs?owner=me&status=running": mine,
    });
    renderWithClient(as(ME_ALICE, <OverviewPage />));
    const panel = await screen.findByRole("region", { name: "d Running" });
    await waitFor(() => expect(within(panel).getAllByRole("listitem")).toHaveLength(2));
    expect(within(panel).getAllByText(/@sv$|@alice$/).map((n) => n.textContent?.split(", ").at(-1))).toEqual([
      "@sv",
      "@alice",
    ]);
    fireEvent.click(within(panel).getByRole("button", { name: "mine" }));
    await waitFor(() => expect(within(panel).getAllByRole("listitem")).toHaveLength(1));
    expect(within(panel).getByRole("button", { name: "mine" }).getAttribute("aria-pressed")).toBe("true");
    expect(calls.some((c) => c.url === "/api/v1/runs?owner=me&status=running")).toBe(true);
  });

  test("recent ideas and failures end with @owner", async () => {
    const base = makeOverview();
    const summary = {
      ...base,
      ideas: base.ideas.map((idea, i) => (i === 0 ? { ...idea, owner: "alice" } : idea)),
      failures: base.failures.map((f, i) => (i === 0 ? { ...f, owner: "sv" } : f)),
    };
    mockApi({ "GET /api/v1/overview": summary, "GET /api/v1/hosts": [] });
    renderWithClient(as(ME_ADMIN, <OverviewPage />));
    await waitFor(() => expect(screen.getAllByText(/, @alice$/)).toHaveLength(1));
    expect(screen.getAllByText(/, @sv$/)).toHaveLength(1);
  });

  test("auth off: no mine toggle", async () => {
    mockApi({ "GET /api/v1/overview": overview(), "GET /api/v1/hosts": [] });
    renderWithClient(as(ME_OFF, <OverviewPage />));
    const panel = await screen.findByRole("region", { name: "d Running" });
    expect(within(panel).queryByRole("button", { name: "mine" })).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/owner.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/pages/components/owner'`.

- [ ] **Step 3: Write `owner.ts`**

Create `ui/src/pages/components/owner.ts`:

```ts
/**
 * Run ownership in the UI (phase 3 contract 1.3, 1.12). The hub enforces it; the UI only
 * names the owner and disables what the server would refuse, with the reason as a tooltip.
 */
import type { Principal } from "../../api/models";
import { covers } from "./scopes";

/** `@alice`; null for a run without an owner (auth off, or before phase 3). */
export function ownerLabel(owner: string | null | undefined): string | null {
  return owner ? `@${owner}` : null;
}

export interface Permit {
  ok: boolean;
  /** Why not, for the tooltip; null when allowed. */
  why: string | null;
}

const OK: Permit = { ok: true, why: null };

/**
 * May `principal` stop, archive or cancel the queued run of `owner`? Every action needs
 * `launch`; these also need the owner or an admin. A run without an owner counts as the
 * hub owner's, so only an admin may stop it. Without a principal (auth off, a hub before
 * phase 3, a component outside the shell) the UI allows it and the server decides.
 */
export function mayStop(principal: Principal | null, owner: string | null | undefined): Permit {
  if (principal === null || principal.auth === "off") return OK;
  if (!covers(principal.scope, "launch")) return { ok: false, why: "stop needs scope launch" };
  if (principal.scope === "admin") return OK;
  if (owner && owner === principal.user) return OK;
  return { ok: false, why: `owned by ${owner ? `@${owner}` : "the hub owner"}; stop needs owner or admin` };
}
```

- [ ] **Step 4: Show the owner and gate Stop and Cancel**

In `ui/src/pages/components/StatusLine.tsx` (as left by phase 2 Task 25), replace

```tsx
      <span className={`who ${isAgent(record.created_by) ? "agent" : "human"}`}>
        <i />
        {record.created_by}
      </span>
```

with

```tsx
      <span className={`who ${isAgent(record.created_by) ? "agent" : "human"}`}>
        <i />
        {record.created_by}
      </span>
      {record.owner ? (
        <span title="owner" style={{ color: "var(--ink)", fontWeight: 500 }}>
          {`@${record.owner}`}
        </span>
      ) : null}
```

In `ui/src/pages/components/RunActions.tsx` (as left by phase 2 Task 26), replace

```tsx
import { api } from "../../api/client";
```

with

```tsx
import { usePrincipal } from "../../api/auth";
import { api } from "../../api/client";
import { mayStop } from "./owner";
```

Replace

```tsx
  const active = ACTIVE_STATUSES.has(record.status);
```

with

```tsx
  const active = ACTIVE_STATUSES.has(record.status);
  // contract 1.3: stop and cancel need the owner or an admin (a hint; the hub decides)
  const permit = mayStop(usePrincipal(), record.owner);
```

In `ui/src/pages/components/RunActions.tsx` (as left by phase 2 Task 26), replace

```tsx
            disabled={!served || stop.pending}
            onClick={() => stop.run(true)}
            title={
              !served ? unavailable : phase === "pending" && record.executor.slurm_job_id
                ? `Cancel SLURM job ${record.executor.slurm_job_id}`
                : `Remove from the ${label} queue`
            }
```

with

```tsx
            disabled={!served || stop.pending || !permit.ok}
            onClick={() => stop.run(true)}
            title={
              !served ? unavailable : !permit.ok
                ? (permit.why ?? "")
                : phase === "pending" && record.executor.slurm_job_id
                  ? `Cancel SLURM job ${record.executor.slurm_job_id}`
                  : `Remove from the ${label} queue`
            }
```

In `ui/src/pages/components/RunActions.tsx` (as left by phase 2 Task 26), replace

```tsx
              disabled={!served || !active || stop.pending}
              onClick={() => {
                if (!served || !active || stop.pending) return;
                if (armed) {
                  setArmed(false);
                  stop.run(false);
                } else {
                  setArmed(true);
                }
              }}
              onBlur={() => setArmed(false)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setArmed(false);
              }}
              title={!served ? unavailable : active ? (armed ? "Click again to stop this run" : "Stop this run") : "The run is not active"}
```

with

```tsx
              disabled={!served || !active || stop.pending || !permit.ok}
              onClick={() => {
                if (!served || !active || stop.pending || !permit.ok) return;
                if (armed) {
                  setArmed(false);
                  stop.run(false);
                } else {
                  setArmed(true);
                }
              }}
              onBlur={() => setArmed(false)}
              onKeyDown={(event) => {
                if (event.key === "Escape") setArmed(false);
              }}
              title={!served ? unavailable : !permit.ok ? (permit.why ?? "") : active ? (armed ? "Click again to stop this run" : "Stop this run") : "The run is not active"}
```

Preserve the current `inferStage` gate (only a successfully loaded infer stage enables Re-infer), run-ID-qualified re-evaluation reports through `ReevalSummary`, `served`, `hostsLoaded`, routing-unavailable tooltips, `stop.run(true)` for queued cancellation, and the armed running-stop confirmation with its three-second timeout, blur/Escape reset and status/identity reset. Add `permit.ok` to the reset effect's dependencies so a permission change disarms it. Phase 3 ownership is an additional condition; it never enables an unserved run. Extend the existing action tests with unserved owner/admin, conditional queued cancellation, and two-click running stop cases under `PrincipalContext`.

In `ui/src/pages/components/OverviewLists.tsx`, replace

```tsx
            {`${run.created_by}, ${fmtClock(run.started_at ?? run.created_at)}${run.task ? `, ${run.task}` : ""}`}
```

with

```tsx
            {`${run.created_by}, ${fmtClock(run.started_at ?? run.created_at)}${run.task ? `, ${run.task}` : ""}${
              run.owner ? `, @${run.owner}` : ""
            }`}
```

and replace

```tsx
          <span className="small">{`${fmtTime(f.created_at)}${retry}`}</span>
```

with

```tsx
          <span className="small">{`${fmtTime(f.created_at)}${retry}${
            f.owner ? `, @${f.owner}` : ""
          }`}</span>
```

In `ui/src/pages/components/IdeaList.tsx`, replace

```tsx
        <div className="meta">{`${idea.created_by}, ${fmtClock(idea.created_at)}`}</div>
```

with

```tsx
        <div className="meta">{`${idea.created_by}, ${fmtClock(idea.created_at)}${idea.owner ? `, @${idea.owner}` : ""}`}</div>
```

In `ui/src/api/models.ts`, replace

```ts
  is_best: boolean;
  label: string;
}
```

with

```ts
  is_best: boolean;
  label: string;
  /** Phase 3: the run's owner; absent from an older hub, null with auth off. */
  owner?: string | null;
}
```

replace

```ts
  /** Display unit of the task's primary metric (`""`, `ms`, `$`, `tokens`, `s`). */
  unit: string;
}

export interface FailureRow {
```

with

```ts
  /** Display unit of the task's primary metric (`""`, `ms`, `$`, `tokens`, `s`). */
  unit: string;
  /** Phase 3: the owner of the group's first run (as `created_by`). */
  owner?: string | null;
}

export interface FailureRow {
```

and replace

```ts
  stderr_path: string;
  retried_ok: boolean;
}
```

with

```ts
  stderr_path: string;
  retried_ok: boolean;
  /** Phase 3: the run's owner. */
  owner?: string | null;
}
```

In `ui/src/pages/Overview.tsx`, replace

```tsx
import { Fragment } from "react";
import { useHosts, useHubEnvironment, useOverview } from "../api/queries";
```

with

```tsx
import { useQuery } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { authOn, usePrincipal } from "../api/auth";
import { api } from "../api/client";
import type { RunsQuery } from "../api/models";
import { queryKeys, useHosts, useHubEnvironment, useOverview } from "../api/queries";
```

and add, directly above `function OverviewBody`,

```tsx
/** The caller's running runs (`GET /api/v1/runs?owner=me&status=running`) for `mine`. */
const MINE: RunsQuery = { owner: "me", status: "running" };

/** Panel d: running runs, or only the caller's with `mine` (auth on). */
function RunningPanel({ runs }: { runs: OverviewSummary["running"] }) {
  const principal = usePrincipal();
  const [mine, setMine] = useState(false);
  const own = useQuery({
    queryKey: queryKeys.runs(MINE),
    queryFn: ({ signal }) => api.runs(MINE, signal),
    enabled: mine,
  });
  const toggle = authOn(principal) ? (
    <button
      type="button"
      className="btn"
      aria-pressed={mine}
      onClick={() => setMine(!mine)}
      title="Only runs you own"
      style={{ height: 24, padding: "0 8px", fontSize: 12.5, background: mine ? "var(--paper-2)" : undefined }}
    >
      mine
    </button>
  ) : undefined;
  return (
    <Figure letter="d" title="Running" aside={toggle}>
      {mine && own.error ? <ErrorBox error={own.error} /> : null}
      {mine && own.data === undefined && !own.error ? <Loading /> : null}
      {!mine || own.data ? <RunningList runs={mine ? (own.data ?? []) : runs} /> : null}
    </Figure>
  );
}
```

and replace

```tsx
          <Figure letter="d" title="Running">
            <RunningList runs={summary.running} />
          </Figure>
```

with

```tsx
          <RunningPanel runs={summary.running} />
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `bun test test/pages && bun run typecheck`
Expected: `owner.test.tsx` 8 pass; the phase 1b/2 page tests (`runActions.test.tsx`, `remoteActions.test.tsx`, `remoteParts.test.tsx`, `Overview.test.tsx`, `overviewLists.test.tsx`) pass unchanged (no principal in their trees, and their records have no owner); `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 6: Commit (repo root)**

```bash
git add ui/src/api/models.ts ui/src/pages/components/owner.ts ui/src/pages/components/StatusLine.tsx ui/src/pages/components/RunActions.tsx ui/src/pages/components/OverviewLists.tsx ui/src/pages/components/IdeaList.tsx ui/src/pages/Overview.tsx ui/test/pages/owner.test.tsx
git commit -m "feat(ui): run owner on the run page and overview; owner-only stop; mine toggle"
```

---

## Group 3: Settings `/settings` (Tasks 9–13)

The Settings page (mockup `shot-settings-*`, `shot-settings-collab-*`): a headline (`3 users · 5 sessions · slack ● email ○`), a Sessions (device, user, client, scope, last seen, `revoke ×`), b Users (name, role, sessions, `disable`), c Add device (scope picker, user picker or `+ new`, then QR, URL and countdown `4:59`), d Notifications (channels `● set`/`○ unset` with `test`, per-project rules with event glyphs, the digest line, recent sends). A collaborator sees only their own sessions and an add-device panel limited to their scope; with auth off only Notifications. All arithmetic sits in `settings/model.ts`.

### Task 9: Settings model

**Files:**
- Create: `ui/src/settings/model.ts`
- Create: `ui/test/settings/model.test.ts`

**Interfaces:**
- Consumes: Task 1 models; `parseTime`, `fmtClock`, `shortId` (`pages/components/format`), `fmtAgeMs` (`pages/components/HostsPanel`).
- Produces: `EVENT_GLYPHS: readonly [NotifyEvent, string][]` (`✓ ✗ ? ⊘`); `OUTBOX_GLYPH: Record<OutboxStatus, string>`; `channelGlyph(c)` (`●`, `○`, `·`); `channelWord(c)` (`set`, `unset`, `off`); `channelTitle(c)`; `liveSessions(rows, now)` (not revoked, not expired, newest `last_seen_at` first); `activeUsers(users)`; `settingsHeadline({principal, sessions, users, notify})`; `ageText(iso, now)` (`2m`, `3h`, `2d`); `dayText(iso)` (`09-30`); `secondsLeft(expiresAt, now)`; `countdown(expiresAt, now)` (`4:59`, `0:00`); `minText(seconds)` (`·`, `45s`, `5m`); `digestLine(d)`; `recentWhat(entry)` (`a1b2`, `sweep s-7f3a`, `digest deepretro`, `test`); `USER_NAME`; `userNameError(name, users)`.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/settings/model.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import {
  activeUsers,
  ageText,
  channelGlyph,
  channelTitle,
  channelWord,
  countdown,
  dayText,
  digestLine,
  liveSessions,
  minText,
  recentWhat,
  secondsLeft,
  settingsHeadline,
  userNameError,
} from "../../src/settings/model";
import { ME_ADMIN, ME_ALICE, ME_OFF, NOTIFY, NOW, OFFER, OUTBOX, SESSIONS, USERS } from "../api/phase3-fixtures";

describe("channels", () => {
  test("glyph, word and tooltip of set, unset and unconfigured channels", () => {
    const off = { configured: false, env: null, set: false };
    expect([NOTIFY.channels.slack, NOTIFY.channels.email, off].map((c) => [channelGlyph(c), channelWord(c), channelTitle(c)])).toEqual([
      ["●", "set", "HYPOTHEX_SLACK_WEBHOOK has a value"],
      ["○", "unset", "set HYPOTHEX_SMTP_PASSWORD on the hub"],
      ["·", "off", "not in config.yaml"],
    ]);
  });
});

describe("sessions and users", () => {
  test("liveSessions drops revoked and expired sessions, newest first", () => {
    expect(liveSessions(SESSIONS, NOW).map((s) => [s.device, ageText(s.last_seen_at, NOW)])).toEqual([
      ["MacBook", "2m"],
      ["MacBook Air", "12m"],
      ["lab-laptop", "1h"],
      ["claude", "3h"],
      ["iPad", "2d"],
    ]);
    expect(liveSessions(SESSIONS, Date.parse("2026-12-30T00:00:00Z"))).toEqual([]);
    expect(activeUsers(USERS).map((u) => u.name)).toEqual(["sv", "alice", "bo"]);
    expect(dayText("2026-09-30T10:22:00Z")).toBe("09-30");
  });

  test("the headline for an admin, a collaborator, auth off, and an admin still loading", () => {
    const live = liveSessions(SESSIONS, NOW);
    expect(settingsHeadline({ principal: ME_ADMIN, sessions: live, users: USERS, notify: NOTIFY })).toBe(
      "3 users · 5 sessions · slack ● email ○",
    );
    const own = live.filter((s) => s.user === "alice");
    expect(settingsHeadline({ principal: ME_ALICE, sessions: own, users: null, notify: null })).toBe(
      "@alice · launch · 2 sessions",
    );
    expect(settingsHeadline({ principal: ME_OFF, sessions: null, users: null, notify: NOTIFY })).toBe(
      "auth off · slack ● email ○",
    );
    expect(settingsHeadline({ principal: ME_ADMIN, sessions: null, users: null, notify: null })).toBe("@sv · admin");
  });
});

describe("pairing, rules and sends", () => {
  test("countdown of a pairing link", () => {
    expect([secondsLeft(OFFER.expires_at, NOW), countdown(OFFER.expires_at, NOW)]).toEqual([299, "4:59"]);
    expect(countdown(OFFER.expires_at, NOW + 290_500)).toBe("0:08");
    expect([secondsLeft(OFFER.expires_at, NOW + 400_000), countdown(OFFER.expires_at, NOW + 400_000)]).toEqual([0, "0:00"]);
  });

  test("min, digest line and what each send was about", () => {
    expect([0, 45, 300, 5400].map(minText)).toEqual(["·", "45s", "5m", "90m"]);
    expect(digestLine(NOTIFY.digest)).toBe("digest · sun 09:00 Europe/London · slack · all");
    expect(digestLine({ ...NOTIFY.digest, timezone: null, projects: ["deepretro", "toy"], channels: ["slack", "email"] })).toBe(
      "digest · sun 09:00 · slack, email · deepretro, toy",
    );
    expect(digestLine({ ...NOTIFY.digest, enabled: false })).toBe("digest off");
    expect(OUTBOX.map(recentWhat)).toEqual(["a1b2", "sweep s-7f3a", "c2b9", "77fe", "9d0c", "digest deepretro"]);
  });

  test("new user names", () => {
    expect(["cy", "Cy", "1cy", "", "alice", "a".repeat(33), "dan"].map((n) => userNameError(n, USERS))).toEqual([
      null,
      "a-z 0-9 _ -, letter first",
      "a-z 0-9 _ -, letter first",
      "a-z 0-9 _ -, letter first",
      "taken",
      "a-z 0-9 _ -, letter first",
      "taken",
    ]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/settings/model.test.ts`
Expected: FAIL: `error: Cannot find module '../../src/settings/model'`.

- [ ] **Step 3: Write `model.ts`**

Create `ui/src/settings/model.ts`:

```ts
/**
 * Settings page arithmetic (phase 3 contract 1.7, 1.10, 3; mockup `shot-settings-*`):
 * channel glyphs, live sessions, the headline, ages, the pairing countdown, rule and send
 * texts. Pure functions of the API bodies and `now` (ms), so tests pin exact strings.
 */
import type {
  ChannelStatus,
  DigestSettings,
  NotifyEvent,
  NotifyStatus,
  OutboxEntry,
  OutboxStatus,
  Principal,
  SessionRow,
  UserRow,
} from "../api/models";
import { parseTime, shortId } from "../pages/components/format";
import { fmtAgeMs } from "../pages/components/HostsPanel";

/** Notify events in rule tables: finished ✓, failed ✗, lost ?, killed ⊘. */
export const EVENT_GLYPHS: readonly [NotifyEvent, string][] = [
  ["finished", "✓"],
  ["failed", "✗"],
  ["lost", "?"],
  ["killed", "⊘"],
];

/** Outbox states: sent ✓, failed ✗, waiting …, skipped ○ (secret unset). */
export const OUTBOX_GLYPH: Record<OutboxStatus, string> = {
  sent: "✓",
  failed: "✗",
  pending: "…",
  sending: "…",
  skipped: "○",
};

/** `●` configured with its secret set, `○` configured but the variable is empty, `·` not configured. */
export function channelGlyph(c: ChannelStatus | null | undefined): "●" | "○" | "·" {
  if (!c || !c.configured) return "·";
  return c.set ? "●" : "○";
}

export function channelWord(c: ChannelStatus | null | undefined): "set" | "unset" | "off" {
  if (!c || !c.configured) return "off";
  return c.set ? "set" : "unset";
}

/** The tooltip: names the variable, never its value (the hub never sends it). */
export function channelTitle(c: ChannelStatus | null | undefined): string {
  if (!c || !c.configured) return "not in config.yaml";
  return c.set ? `${c.env} has a value` : `set ${c.env} on the hub`;
}

/** Sessions that still work at `now`: not revoked, not expired; newest `last_seen_at` first. */
export function liveSessions(rows: readonly SessionRow[], now: number): SessionRow[] {
  return rows
    .filter((s) => s.revoked_at === null && parseTime(s.expires_at) > now)
    .sort((a, b) => parseTime(b.last_seen_at) - parseTime(a.last_seen_at));
}

/** Users not disabled. */
export function activeUsers(users: readonly UserRow[]): UserRow[] {
  return users.filter((u) => u.disabled_at === null);
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

export interface HeadlineInput {
  principal: Principal;
  /** Live sessions (`liveSessions`); null while loading or not read. */
  sessions: SessionRow[] | null;
  users: UserRow[] | null;
  notify: NotifyStatus | null;
}

/**
 * Admin: `3 users · 5 sessions · slack ● email ○` (parts appear as they load; `@sv · admin`
 * before any). Collaborator: `@alice · launch · 2 sessions`. Auth off: `auth off · slack ● email ○`.
 */
export function settingsHeadline({ principal, sessions, users, notify }: HeadlineInput): string {
  const channels = notify
    ? `slack ${channelGlyph(notify.channels.slack)} email ${channelGlyph(notify.channels.email)}`
    : null;
  if (principal.auth === "off") return ["auth off", channels].filter((p) => p !== null).join(" · ");
  if (principal.scope === "admin") {
    const parts: string[] = [];
    if (users) parts.push(plural(activeUsers(users).length, "user", "users"));
    if (sessions) parts.push(plural(sessions.length, "session", "sessions"));
    if (channels) parts.push(channels);
    return parts.length > 0 ? parts.join(" · ") : `@${principal.user} · admin`;
  }
  const own = sessions ? plural(sessions.length, "session", "sessions") : null;
  return [`@${principal.user}`, principal.scope, own].filter((p) => p !== null).join(" · ");
}

/** `2m`, `3h`, `2d` since `iso`. */
export function ageText(iso: string, now: number): string {
  return fmtAgeMs(now - parseTime(iso));
}

const pad = (n: number): string => String(n).padStart(2, "0");

/** `09-30` (UTC month and day). */
export function dayText(iso: string): string {
  const d = new Date(parseTime(iso));
  return Number.isNaN(d.getTime()) ? "—" : `${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
}

/** Whole seconds until `expiresAt`, never below 0. */
export function secondsLeft(expiresAt: string, now: number): number {
  return Math.max(0, Math.floor((parseTime(expiresAt) - now) / 1000));
}

/** `4:59`; `0:00` once expired. */
export function countdown(expiresAt: string, now: number): string {
  const s = secondsLeft(expiresAt, now);
  return `${Math.floor(s / 60)}:${pad(s % 60)}`;
}

/** A rule's `min_seconds`: `·` for none, `45s`, `5m`. */
export function minText(seconds: number): string {
  if (seconds <= 0) return "·";
  if (seconds < 60) return `${seconds}s`;
  return `${Math.round(seconds / 60)}m`;
}

/** `digest · sun 09:00 Europe/London · slack · all`, or `digest off`. */
export function digestLine(d: DigestSettings): string {
  if (!d.enabled) return "digest off";
  const when = `${d.weekday} ${pad(d.hour)}:00${d.timezone ? ` ${d.timezone}` : ""}`;
  const projects = d.projects === "all" ? "all" : d.projects.join(", ");
  return `digest · ${when} · ${d.channels.join(", ")} · ${projects}`;
}

/** What a send was about: the run's short id, `sweep <id>`, `digest <project>`, `test`. */
export function recentWhat(entry: OutboxEntry): string {
  const n = entry.notice;
  if (n.kind === "run") return n.run_id ? shortId(n.run_id) : "run";
  if (n.kind === "sweep") return `sweep ${n.sweep_id ?? ""}`.trim();
  if (n.kind === "digest") return `digest ${n.project ?? ""}`.trim();
  return "test";
}

/** `hypothex.auth.store.USER_NAME`. */
export const USER_NAME = /^[a-z][a-z0-9_-]{0,31}$/;

/** Why a new user name cannot be used, or null. Disabled users keep their names. */
export function userNameError(name: string, users: readonly UserRow[]): string | null {
  if (!USER_NAME.test(name)) return "a-z 0-9 _ -, letter first";
  if (users.some((u) => u.name === name)) return "taken";
  return null;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/settings/model.test.ts && bun run typecheck`
Expected: 6 pass, `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/settings/model.ts ui/test/settings/model.test.ts
git commit -m "feat(ui): settings model for sessions, channels, headline, countdown and sends"
```

---

### Task 10: Sessions and Users panels

**Files:**
- Create: `ui/src/settings/styles.ts`
- Create: `ui/src/settings/SessionsPanel.tsx`
- Create: `ui/src/settings/UsersPanel.tsx`
- Create: `ui/test/settings/panels.test.tsx`

**Interfaces:**
- Consumes: Task 9 helpers; `api.revokeSession`, `api.disableUser`, `AUTH_EVENT_INVALIDATES`; `useAction`, `ErrorBox`; `SCOPE_GLYPH`.
- Produces: `SETTINGS_CSS` and `SettingsStyles()` (selectors under `.page.settings`); `SessionsPanel({ sessions, principal, now, showUser })` (live sessions; the caller's own row marked `this`; `revoke ×` per row, `aria-label="Revoke <device>"`); `UsersPanel({ users, sessions, principal, now })` (`@name`, role, live session count, since, `disable` except for yourself; a disabled user reads `disabled`).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/settings/panels.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { SessionsPanel } from "../../src/settings/SessionsPanel";
import { UsersPanel } from "../../src/settings/UsersPanel";
import { ME_ADMIN, NOW, SESSIONS, USERS } from "../api/phase3-fixtures";
import { mockApi, renderWithClient, restoreFetch } from "../pages/helpers";

afterEach(restoreFetch);

const cells = (row: HTMLElement) => within(row).getAllByRole("cell").map((c) => c.textContent);

describe("SessionsPanel", () => {
  test("live sessions newest first; your own row says this", () => {
    mockApi({});
    renderWithClient(<SessionsPanel sessions={SESSIONS} principal={ME_ADMIN} now={NOW} showUser />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map(cells)).toEqual([
      ["MacBook this", "@sv", "browser", "a", "2m", "09-30", "revoke ×"],
      ["MacBook Air", "@alice", "browser", "l", "12m", "09-30", "revoke ×"],
      ["lab-laptop", "@sv", "cli", "a", "1h", "09-30", "revoke ×"],
      ["claude", "@alice", "agent", "l", "3h", "09-30", "revoke ×"],
      ["iPad", "@bo", "browser", "r", "2d", "09-30", "revoke ×"],
    ]);
    expect(rows[0]?.className).toBe("self");
  });

  test("revoke posts the session id with a command id; no user column for a collaborator", async () => {
    const calls = mockApi({ "POST /api/v1/auth/sessions/s_0d5a7e91b2f4/revoke": SESSIONS[4] });
    renderWithClient(<SessionsPanel sessions={SESSIONS} principal={ME_ADMIN} now={NOW} showUser={false} />);
    expect(screen.getAllByRole("columnheader").map((h) => h.textContent)).toEqual([
      "device",
      "client",
      "scope",
      "last seen",
      "since",
      "",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Revoke iPad" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]?.url).toBe("/api/v1/auth/sessions/s_0d5a7e91b2f4/revoke");
    expect(Object.keys(calls[0]?.body as object)).toEqual(["command_id"]);
  });

  test("no live session: none", () => {
    mockApi({});
    renderWithClient(<SessionsPanel sessions={[SESSIONS[5]!]} principal={ME_ADMIN} now={NOW} showUser />);
    expect(screen.getByText("none")).toBeTruthy();
  });
});

describe("UsersPanel", () => {
  test("users with live session counts; no disable for yourself; a disabled user says so", () => {
    mockApi({});
    renderWithClient(<UsersPanel users={USERS} sessions={SESSIONS} principal={ME_ADMIN} now={NOW} />);
    expect(screen.getAllByRole("row").slice(1).map(cells)).toEqual([
      ["@sv", "admin", "2", "09-12", ""],
      ["@alice", "launch", "2", "09-30", "disable"],
      ["@bo", "read", "1", "10-02", "disable"],
      ["@dan", "launch", "0", "09-14", "disabled"],
    ]);
  });

  test("disable posts the user name with a command id", async () => {
    const calls = mockApi({ "POST /api/v1/auth/users/bo/disable": { ...USERS[2], disabled_at: "2026-10-04T14:33:00Z" } });
    renderWithClient(<UsersPanel users={USERS} sessions={SESSIONS} principal={ME_ADMIN} now={NOW} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable bo" }));
    await waitFor(() => expect(calls.map((c) => c.url)).toEqual(["/api/v1/auth/users/bo/disable"]));
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/settings/panels.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/settings/SessionsPanel'`.

- [ ] **Step 3: Write the styles and the two panels**

Create `ui/src/settings/styles.ts`:

```ts
/**
 * Settings CSS, from docs/mockups/phase3 (`shot-settings-*`). Every selector starts with
 * `.page.settings`; colours come from the theme tokens.
 */
import { createElement } from "react";

export const SETTINGS_CSS = `
.page.settings .set-grid { display: grid; grid-template-columns: minmax(0, 1fr) 400px; gap: 72px; margin-top: 64px; align-items: start; }
.page.settings .set-grid .fig { margin-top: 0; }
.page.settings .tbl { font-variant-numeric: tabular-nums; }
.page.settings .tbl td { vertical-align: baseline; white-space: nowrap; }
.page.settings .tbl tr.self td { background: var(--paper-2); }
.page.settings .tbl tr.self td:first-child { box-shadow: inset 2px 0 0 var(--ink); padding-left: 8px; }
.page.settings .dim { color: var(--ink-3); }
.page.settings .mono { font-family: var(--mono); font-size: 13px; }
.page.settings .btn.x { height: 26px; padding: 0 9px; font-size: 12.5px; border-color: transparent; color: var(--ink-3); }
.page.settings .btn.x:hover:not(:disabled) { color: var(--fail); border-color: var(--rule); }
.page.settings .btn.s { height: 26px; padding: 0 9px; font-size: 12.5px; }
.page.settings .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 6px; overflow: hidden; }
.page.settings .seg button { height: 30px; padding: 0 11px; border: 0; background: transparent; color: var(--ink-2); cursor: pointer; font-size: 13.5px; }
.page.settings .seg button + button { border-left: 1px solid var(--rule); }
.page.settings .seg button[aria-pressed="true"] { background: var(--ink); color: var(--paper); }
.page.settings .seg button:disabled { color: var(--rule); cursor: not-allowed; }
.page.settings .in { height: 32px; border: 1px solid var(--rule); border-radius: 6px; background: transparent; padding: 0 10px; font-size: 14px; color: var(--ink); }
.page.settings .in[aria-invalid="true"] { border-color: var(--fail); }
.page.settings .frow2 { display: flex; gap: 14px; align-items: center; flex-wrap: wrap; margin-bottom: 20px; font-size: 14px; }
.page.settings .frow2 .lb { font-weight: 550; width: 44px; }
.page.settings .bad { color: var(--fail); }
.page.settings .ok { color: var(--best); }
.page.settings .dev { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 0 24px; align-items: start; }
.page.settings pre.qr { margin: 0; padding: 8px; background: #fff; color: #15181e; font: 400 9px/1 var(--mono); letter-spacing: 0; white-space: pre; }
.page.settings .url { display: block; word-break: break-all; font: 400 12.5px/1.55 var(--mono); color: var(--ink-2); }
.page.settings .cd { font: 400 30px/1 var(--sans); letter-spacing: -.01em; font-variant-numeric: tabular-nums; margin-top: 14px; }
.page.settings .cd small { font-size: 12.5px; color: var(--ink-3); margin-left: 6px; letter-spacing: 0; }
.page.settings .chan { display: grid; grid-template-columns: 110px 120px minmax(0, 1fr) auto auto; gap: 0 16px; align-items: baseline; padding: 11px 0; border-top: 1px solid var(--rule-2); font-size: 14px; }
.page.settings .chan:first-child { border-top: 0; padding-top: 0; }
.page.settings .chan b { font-weight: 600; }
.page.settings .ev { display: inline-flex; gap: 6px; font-weight: 500; }
.page.settings .ev span { width: 16px; text-align: center; }
.page.settings .ev span.off { color: var(--rule); }
.page.settings .subh { font: 600 13px var(--sans); color: var(--ink-2); margin: 28px 0 10px; }
@media (max-width: 1100px) { .page.settings .set-grid { grid-template-columns: 1fr; gap: 48px; } }
`;

/** Inject the settings CSS. */
export function SettingsStyles() {
  return createElement("style", { "data-hx": "settings" }, SETTINGS_CSS);
}
```

Create `ui/src/settings/SessionsPanel.tsx`:

```tsx
/** Settings panel a: live sessions with `revoke ×` (own sessions; all of them for an admin). */
import { api } from "../api/client";
import type { Principal, SessionRow } from "../api/models";
import { AUTH_EVENT_INVALIDATES } from "../api/queries";
import { ErrorBox } from "../pages/components/QueryState";
import { SCOPE_GLYPH } from "../pages/components/scopes";
import { useAction } from "../pages/components/useAction";
import { ageText, dayText, liveSessions } from "./model";

export interface SessionsPanelProps {
  sessions: SessionRow[];
  principal: Principal;
  now: number;
  /** The user column (admins see everyone's sessions). */
  showUser: boolean;
}

export function SessionsPanel({ sessions, principal, now, showUser }: SessionsPanelProps) {
  const revoke = useAction<SessionRow, string>({
    send: (id, opts) => api.revokeSession(id, opts),
    invalidate: AUTH_EVENT_INVALIDATES,
  });
  const rows = liveSessions(sessions, now);
  if (rows.length === 0) return <p className="small">none</p>;
  return (
    <>
      <table className="tbl" aria-label="Sessions">
        <thead>
          <tr>
            <th>device</th>
            {showUser ? <th>user</th> : null}
            <th>client</th>
            <th>scope</th>
            <th className="r">last seen</th>
            <th className="r">since</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const self = s.id === principal.session_id;
            return (
              <tr key={s.id} className={self ? "self" : undefined}>
                <td>
                  {s.device}
                  {self ? (
                    <span className="small" title="This browser">
                      {" this"}
                    </span>
                  ) : null}
                </td>
                {showUser ? <td>{`@${s.user}`}</td> : null}
                <td>{s.client}</td>
                <td title={s.scope}>{SCOPE_GLYPH[s.scope]}</td>
                <td className="r" title={s.last_seen_at}>
                  {ageText(s.last_seen_at, now)}
                </td>
                <td className="r dim" title={s.created_at}>
                  {dayText(s.created_at)}
                </td>
                <td className="r">
                  <button
                    type="button"
                    className="btn x"
                    aria-label={`Revoke ${s.device}`}
                    title={self ? `Revoke ${s.id}: this browser needs a new pairing link` : `Revoke ${s.id}`}
                    disabled={revoke.pending}
                    onClick={() => revoke.run(s.id)}
                  >
                    revoke ×
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {revoke.error ? <ErrorBox error={revoke.error} /> : null}
    </>
  );
}
```

Create `ui/src/settings/UsersPanel.tsx`:

```tsx
/** Settings panel b (admin): users, their live sessions, and `disable` (revokes every session). */
import { api } from "../api/client";
import type { Principal, SessionRow, UserRow } from "../api/models";
import { AUTH_EVENT_INVALIDATES } from "../api/queries";
import { ErrorBox } from "../pages/components/QueryState";
import { useAction } from "../pages/components/useAction";
import { dayText, liveSessions } from "./model";

export interface UsersPanelProps {
  users: UserRow[];
  sessions: SessionRow[];
  principal: Principal;
  now: number;
}

export function UsersPanel({ users, sessions, principal, now }: UsersPanelProps) {
  const disable = useAction<UserRow, string>({
    send: (name, opts) => api.disableUser(name, opts),
    invalidate: AUTH_EVENT_INVALIDATES,
  });
  const live = liveSessions(sessions, now);
  const rows = [...users.filter((u) => u.disabled_at === null), ...users.filter((u) => u.disabled_at !== null)];
  return (
    <>
      <table className="tbl" aria-label="Users">
        <thead>
          <tr>
            <th>name</th>
            <th>role</th>
            <th className="r">sessions</th>
            <th className="r">since</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {rows.map((u) => (
            <tr key={u.name}>
              <td>{`@${u.name}`}</td>
              <td>{u.role}</td>
              <td className="r">{live.filter((s) => s.user === u.name).length}</td>
              <td className="r dim" title={`by ${u.created_by}`}>
                {dayText(u.created_at)}
              </td>
              <td className="r">
                {u.disabled_at !== null ? (
                  <span className="dim" title={u.disabled_at}>
                    disabled
                  </span>
                ) : u.name === principal.user ? null : (
                  <button
                    type="button"
                    className="btn x"
                    aria-label={`Disable ${u.name}`}
                    title={`Disable ${u.name} and revoke every session`}
                    disabled={disable.pending}
                    onClick={() => disable.run(u.name)}
                  >
                    disable
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {disable.error ? <ErrorBox error={disable.error} /> : null}
    </>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/settings && bun run typecheck`
Expected: `panels.test.tsx` 5 pass, `model.test.ts` 6 pass; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/settings/styles.ts ui/src/settings/SessionsPanel.tsx ui/src/settings/UsersPanel.tsx ui/test/settings/panels.test.tsx
git commit -m "feat(ui): settings sessions and users panels with revoke and disable"
```

---

### Task 11: Add device (scope, user, QR, link, countdown)

**Files:**
- Create: `ui/src/settings/AddDevice.tsx`
- Create: `ui/test/settings/addDevice.test.tsx`

**Interfaces:**
- Consumes: Task 9 `countdown`, `secondsLeft`, `activeUsers`, `userNameError`; Task 7 `SCOPES`, `covers`; `api.createPairing`; `useAction`, `CopyButton`, `ErrorBox`, `useNow` (`pages/components/HostsPanel`).
- Produces: `AddDevice({ principal, users, now? })`. `users` is the admin's user list (null for a collaborator: no picker, the link is for the caller). Scopes above the caller's are disabled (`title="above your scope"`; pairing never widens scope). `link` posts `{scope}` (collaborator), `{user, scope}` (admin, existing user) or `{user, new_user: true, scope}` (admin, `+ new`). The offer shows the QR (`aria-label="QR code"`), the URL with a copy button, `alice · launch · one use`, and `4:59 left`, ticking each second; at 0 it reads `expired`. The `user · scope` label is taken from the request body that was sent (the action returns `{offer, user, scope}`), so changing the pickers while the request is in flight never relabels the link.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/settings/addDevice.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { AddDevice } from "../../src/settings/AddDevice";
import { ME_ADMIN, ME_ALICE, NOW, OFFER, USERS } from "../api/phase3-fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";

afterEach(restoreFetch);

const scopeButton = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

test("a collaborator: read and launch only, no user picker; the link shows QR, URL and countdown", async () => {
  const calls = mockApi({ "POST /api/v1/auth/pairings": OFFER });
  renderWithClient(<AddDevice principal={ME_ALICE} users={null} now={NOW} />);
  expect(["read", "launch", "admin"].map((s) => [scopeButton(s).disabled, scopeButton(s).getAttribute("aria-pressed")])).toEqual([
    [false, "false"],
    [false, "true"],
    [true, "false"],
  ]);
  expect(scopeButton("admin").title).toBe("above your scope");
  expect(screen.queryByLabelText("User")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "link" }));
  expect((await screen.findByLabelText("QR code")).textContent).toBe(OFFER.qr);
  expect(calls[0]?.body).toEqual({ scope: "launch" });
  expect(screen.getByText(OFFER.url)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Copy pairing link" })).toBeTruthy();
  expect(screen.getByText("alice · launch · one use")).toBeTruthy();
  expect(screen.getByTitle("The link works once, until it expires").textContent).toBe("4:59 left");
});

test("an admin pairs an existing user at a chosen scope", async () => {
  const calls = mockApi({ "POST /api/v1/auth/pairings": OFFER });
  renderWithClient(<AddDevice principal={ME_ADMIN} users={USERS} now={NOW} />);
  const select = screen.getByLabelText("User") as HTMLSelectElement;
  expect([...select.options].map((o) => o.value)).toEqual(["sv", "alice", "bo"]);
  fireEvent.change(select, { target: { value: "alice" } });
  fireEvent.click(scopeButton("read"));
  fireEvent.click(screen.getByRole("button", { name: "link" }));
  await screen.findByLabelText("QR code");
  expect(calls[0]?.body).toEqual({ user: "alice", scope: "read" });
  expect(screen.getByText("alice · read · one use")).toBeTruthy();
});

test("the link keeps the user and scope it was made for, even if the form changes in flight", async () => {
  mockApi({ "POST /api/v1/auth/pairings": OFFER });
  renderWithClient(<AddDevice principal={ME_ADMIN} users={USERS} now={NOW} />);
  const select = screen.getByLabelText("User") as HTMLSelectElement;
  fireEvent.change(select, { target: { value: "alice" } });
  fireEvent.click(scopeButton("admin"));
  fireEvent.click(screen.getByRole("button", { name: "link" }));
  fireEvent.change(select, { target: { value: "bo" } }); // before the answer lands
  fireEvent.click(scopeButton("read"));
  await screen.findByLabelText("QR code");
  expect(screen.getByText("alice · admin · one use")).toBeTruthy();
  expect(screen.queryByText("bo · read · one use")).toBeNull();
});

test("+ new: a valid unused name, sent with new_user", async () => {
  const calls = mockApi({ "POST /api/v1/auth/pairings": OFFER });
  renderWithClient(<AddDevice principal={ME_ADMIN} users={USERS} now={NOW} />);
  fireEvent.click(screen.getByRole("button", { name: "+ new" }));
  const input = screen.getByLabelText("New user") as HTMLInputElement;
  const link = () => screen.getByRole("button", { name: "link" }) as HTMLButtonElement;
  fireEvent.change(input, { target: { value: "Cy" } });
  expect([screen.getByText("a-z 0-9 _ -, letter first") !== null, link().disabled]).toEqual([true, true]);
  fireEvent.change(input, { target: { value: "alice" } });
  expect([screen.getByText("taken") !== null, link().disabled]).toEqual([true, true]);
  fireEvent.change(input, { target: { value: "cy" } });
  expect(link().disabled).toBe(false);
  fireEvent.click(link());
  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0]?.body).toEqual({ user: "cy", new_user: true, scope: "launch" });
});

test("an expired link says expired", async () => {
  mockApi({ "POST /api/v1/auth/pairings": OFFER });
  renderWithClient(<AddDevice principal={ME_ALICE} users={null} now={NOW + 300_000} />);
  fireEvent.click(screen.getByRole("button", { name: "link" }));
  expect((await screen.findByTitle("The link works once, until it expires")).textContent).toBe("expired");
});

test("a refused scope shows the hub's message", async () => {
  mockApi({
    "POST /api/v1/auth/pairings": new HttpReply(403, { error: "a launch session cannot pair admin", type: "ScopeError" }),
  });
  renderWithClient(<AddDevice principal={ME_ALICE} users={null} now={NOW} />);
  fireEvent.click(screen.getByRole("button", { name: "link" }));
  expect((await screen.findByRole("alert")).textContent).toBe("a launch session cannot pair admin");
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/settings/addDevice.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/settings/AddDevice'`.

- [ ] **Step 3: Write `AddDevice.tsx`**

Create `ui/src/settings/AddDevice.tsx`:

```tsx
/**
 * Settings panel c (phase 3 contract 1.10, 3): make a one-time pairing link for a device.
 * Scope picker (never above the caller's), user picker or `+ new` for an admin, then the
 * QR code, the URL and a countdown. The link goes to the device out of band (scan or paste).
 */
import { useState } from "react";
import { api } from "../api/client";
import type { PairingOffer, PairingRequest, Principal, Scope, UserRow } from "../api/models";
import { CopyButton } from "../pages/components/CopyButton";
import { useNow } from "../pages/components/HostsPanel";
import { ErrorBox } from "../pages/components/QueryState";
import { SCOPES, covers } from "../pages/components/scopes";
import { useAction } from "../pages/components/useAction";
import { activeUsers, countdown, secondsLeft, userNameError } from "./model";

export interface AddDeviceProps {
  principal: Principal;
  /** The admin's user list; null for a collaborator (the link is for the caller). */
  users: UserRow[] | null;
  /** Fixed clock (tests); default the current time, ticking each second. */
  now?: number;
}

interface Made {
  offer: PairingOffer;
  user: string;
  scope: Scope;
}

export function AddDevice({ principal, users, now }: AddDeviceProps) {
  const ticking = useNow(1_000);
  const at = now ?? ticking;
  const [scope, setScope] = useState<Scope>(covers(principal.scope, "launch") ? "launch" : "read");
  const [user, setUser] = useState(principal.user);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [made, setMade] = useState<Made | null>(null);
  const admin = users !== null;
  const nameError = adding ? userNameError(name, users ?? []) : null;

  // The label comes from the body that was sent, never from the form after the click:
  // a user or scope changed while the request is in flight must not relabel the link.
  const create = useAction<Made, PairingRequest>({
    send: async (sent) => ({
      offer: await api.createPairing(sent),
      user: sent.user ?? principal.user,
      scope: sent.scope,
    }),
    onSuccess: setMade,
  });
  const body = (): PairingRequest => {
    if (!admin) return { scope };
    return adding ? { user: name, new_user: true, scope } : { user, scope };
  };
  const left = made ? secondsLeft(made.offer.expires_at, at) : 0;

  return (
    <div>
      <div className="frow2">
        <span className="lb">scope</span>
        <div className="seg" role="group" aria-label="Scope">
          {SCOPES.map((s) => (
            <button
              key={s}
              type="button"
              aria-pressed={scope === s}
              disabled={!covers(principal.scope, s)}
              title={covers(principal.scope, s) ? undefined : "above your scope"}
              onClick={() => setScope(s)}
            >
              {s}
            </button>
          ))}
        </div>
      </div>
      <div className="frow2">
        <span className="lb">user</span>
        {admin && !adding ? (
          <>
            <select className="in" aria-label="User" value={user} onChange={(e) => setUser(e.target.value)}>
              {activeUsers(users ?? []).map((u) => (
                <option key={u.name} value={u.name}>
                  {u.name}
                </option>
              ))}
            </select>
            <button type="button" className="btn s" title="A new collaborator" onClick={() => setAdding(true)}>
              + new
            </button>
          </>
        ) : admin ? (
          <>
            <input
              className="in"
              aria-label="New user"
              value={name}
              aria-invalid={nameError !== null}
              onChange={(e) => setName(e.target.value)}
              placeholder="name"
            />
            {nameError ? <span className="small bad">{nameError}</span> : null}
            <button type="button" className="btn s" onClick={() => setAdding(false)}>
              ×
            </button>
          </>
        ) : (
          <span>{`@${principal.user}`}</span>
        )}
        <button
          type="button"
          className="btn primary"
          disabled={create.pending || (adding && nameError !== null)}
          onClick={() => create.run(body())}
          title="A one-time link, valid 5 min"
        >
          link
        </button>
      </div>
      {create.error ? <ErrorBox error={create.error} /> : null}
      {made ? (
        <div className="dev">
          <pre className="qr" aria-label="QR code">
            {made.offer.qr}
          </pre>
          <div>
            <code className="url">{made.offer.url}</code>
            <div className="row" style={{ marginTop: 8 }}>
              <CopyButton text={made.offer.url} label="pairing link" />
              <span className="small">{`${made.user} · ${made.scope} · one use`}</span>
            </div>
            <div className="cd" title="The link works once, until it expires">
              {left > 0 ? (
                <>
                  {countdown(made.offer.expires_at, at)} <small>left</small>
                </>
              ) : (
                "expired"
              )}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/settings && bun run typecheck`
Expected: `addDevice.test.tsx` 6 pass; the other settings files pass; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/settings/AddDevice.tsx ui/test/settings/addDevice.test.tsx
git commit -m "feat(ui): add device panel with scope and user pickers, QR, link and countdown"
```

---

### Task 12: Notifications panel

**Files:**
- Create: `ui/src/settings/NotifyPanel.tsx`
- Create: `ui/test/settings/notifyPanel.test.tsx`

**Interfaces:**
- Consumes: Task 9 `EVENT_GLYPHS`, `OUTBOX_GLYPH`, `channelGlyph`, `channelWord`, `channelTitle`, `minText`, `digestLine`, `recentWhat`; `api.testNotify`, `NOTIFY_INVALIDATES`; `fmtClock`; `useAction`.
- Produces: `NotifyPanel({ notify })`: one row per channel (`slack`, `email`: glyph and word, the variable name as tooltip, the detail `webhook` or `<host> → <to>`, `test` enabled only when set, then `✓` or `✗ <error_class>` after a test); a rules table (`aria-label="Rules"`; events as glyphs, the off ones greyed with class `off`; channels; `min`; `◇` when sweeps fold; an `others` row for the default rule or `·`); the digest line; a recent-sends table (`aria-label="Recent sends"`: time, what, channel, glyph and status, tries, error class or `·`).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/settings/notifyPanel.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { fireEvent, screen, within } from "@testing-library/react";
import { NotifyPanel } from "../../src/settings/NotifyPanel";
import { NOTIFY } from "../api/phase3-fixtures";
import { mockApi, renderWithClient, restoreFetch } from "../pages/helpers";

afterEach(restoreFetch);

const rowsOf = (label: string) =>
  within(screen.getByRole("table", { name: label }))
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("cell").map((c) => c.textContent));

test("channels: set, unset; test sends only through a set channel and shows the result", async () => {
  const calls = mockApi({ "POST /api/v1/notify/test": { ok: false, error_class: "http_404" } });
  renderWithClient(<NotifyPanel notify={NOTIFY} />);
  const slack = screen.getByTitle("HYPOTHEX_SLACK_WEBHOOK has a value");
  const email = screen.getByTitle("set HYPOTHEX_SMTP_PASSWORD on the hub");
  expect([slack.textContent, email.textContent]).toEqual(["● set", "○ unset"]);
  expect(screen.getByText("smtp.lab.org → sv@lab.org")).toBeTruthy();
  const tests = screen.getAllByRole("button", { name: /^Test / }) as HTMLButtonElement[];
  expect(tests.map((b) => [b.getAttribute("aria-label"), b.disabled])).toEqual([
    ["Test slack", false],
    ["Test email", true],
  ]);
  fireEvent.click(tests[0] as HTMLButtonElement);
  expect((await screen.findByText("✗ http_404")).textContent).toBe("✗ http_404");
  expect(calls[0]?.body).toMatchObject({ channel: "slack" });
});

test("rules: event glyphs on and off, channels, min, sweeps, others", () => {
  mockApi({});
  renderWithClient(<NotifyPanel notify={NOTIFY} />);
  expect(rowsOf("Rules")).toEqual([
    ["deepretro", "✓✗?⊘", "slack, email", "5m", "◇"],
    ["rxn-forward", "✓✗?⊘", "slack", "·", "◇"],
    ["others", "·", "", "", ""],
  ]);
  const deep = screen.getByRole("row", { name: "deepretro" });
  expect([...deep.querySelectorAll(".ev span.off")].map((s) => s.getAttribute("title"))).toEqual(["killed"]);
  const rxn = screen.getByRole("row", { name: "rxn-forward" });
  expect([...rxn.querySelectorAll(".ev span.off")].map((s) => s.getAttribute("title"))).toEqual(["finished"]);
  expect(screen.getByText("digest · sun 09:00 Europe/London · slack · all")).toBeTruthy();
});

test("recent sends: time, what, channel, status, tries, error class", () => {
  mockApi({});
  renderWithClient(<NotifyPanel notify={NOTIFY} />);
  expect(rowsOf("Recent sends")).toEqual([
    ["14:02", "a1b2", "slack", "✓ sent", "1", "·"],
    ["13:40", "sweep s-7f3a", "slack", "✓ sent", "1", "·"],
    ["13:12", "c2b9", "email", "○ skipped", "0", "unset:HYPOTHEX_SMTP_PASSWORD"],
    ["12:55", "77fe", "slack", "✗ failed", "3", "http_404"],
    ["12:31", "9d0c", "slack", "… pending", "2", "http_429"],
    ["09:00", "digest deepretro", "slack", "✓ sent", "1", "·"],
  ]);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/settings/notifyPanel.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/settings/NotifyPanel'`.

- [ ] **Step 3: Write `NotifyPanel.tsx`**

Create `ui/src/settings/NotifyPanel.tsx`:

```tsx
/**
 * Settings panel d (admin; phase 3 contract 1.7, 3): channels with a test send, per-project
 * rules, the weekly digest, and recent sends. Secrets never reach the browser: a channel
 * shows only whether its variable has a value, and the variable's name as the tooltip.
 */
import { useState } from "react";
import { api } from "../api/client";
import type { Channel, ChannelStatus, NotifyStatus, NotifyTestResult, ProjectRule } from "../api/models";
import { NOTIFY_INVALIDATES } from "../api/queries";
import { fmtClock } from "../pages/components/format";
import { ErrorBox } from "../pages/components/QueryState";
import { useAction } from "../pages/components/useAction";
import {
  EVENT_GLYPHS,
  OUTBOX_GLYPH,
  channelGlyph,
  channelTitle,
  channelWord,
  digestLine,
  minText,
  recentWhat,
} from "./model";

function ChannelRow({ name, status }: { name: Channel; status: ChannelStatus }) {
  const [result, setResult] = useState<NotifyTestResult | null>(null);
  const test = useAction<NotifyTestResult>({
    send: (_: void, opts) => api.testNotify(name, opts),
    invalidate: NOTIFY_INVALIDATES,
    onSuccess: setResult,
  });
  const ready = status.configured && status.set;
  const detail =
    name === "email" ? `${status.host ?? "?"} → ${(status.to ?? []).join(", ")}` : status.configured ? "webhook" : "";
  return (
    <div className="chan">
      <b>{name}</b>
      <span title={channelTitle(status)}>{`${channelGlyph(status)} ${channelWord(status)}`}</span>
      <span className="small">{detail}</span>
      <span className="small">
        {result ? (result.ok ? <span className="ok">✓</span> : <span className="bad">{`✗ ${result.error_class ?? "error"}`}</span>) : null}
      </span>
      <button
        type="button"
        className="btn s"
        aria-label={`Test ${name}`}
        disabled={!ready || test.pending}
        title={ready ? "Send a test notice" : `${name} not ready`}
        onClick={() => test.run()}
      >
        test
      </button>
      {test.error ? <ErrorBox error={test.error} /> : null}
    </div>
  );
}

function RuleCells({ rule }: { rule: ProjectRule }) {
  return (
    <>
      <td>
        <span className="ev">
          {EVENT_GLYPHS.map(([event, glyph]) => (
            <span key={event} title={event} className={rule.events.includes(event) ? undefined : "off"}>
              {glyph}
            </span>
          ))}
        </span>
      </td>
      <td>{rule.channels.join(", ")}</td>
      <td className="r">{minText(rule.min_seconds)}</td>
      <td className="r" title={rule.fold_sweeps ? "One notice per sweep" : "One notice per run"}>
        {rule.fold_sweeps ? "◇" : "·"}
      </td>
    </>
  );
}

export function NotifyPanel({ notify }: { notify: NotifyStatus }) {
  const projects = Object.keys(notify.projects).sort();
  return (
    <div>
      <ChannelRow name="slack" status={notify.channels.slack} />
      <ChannelRow name="email" status={notify.channels.email} />
      <div className="subh">rules</div>
      <table className="tbl" aria-label="Rules">
        <thead>
          <tr>
            <th>project</th>
            <th title="finished ✓ · failed ✗ · lost ? · killed ⊘">events</th>
            <th>channels</th>
            <th className="r" title="Finished runs shorter than this are skipped">
              min
            </th>
            <th className="r">sweep</th>
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => (
            <tr key={project} aria-label={project}>
              <td>{project}</td>
              <RuleCells rule={notify.projects[project] as ProjectRule} />
            </tr>
          ))}
          <tr aria-label="others">
            <td className="dim">others</td>
            {notify.default ? (
              <RuleCells rule={notify.default} />
            ) : (
              <>
                <td className="dim" title="Unlisted projects get nothing (opt-in)">
                  ·
                </td>
                <td />
                <td />
                <td />
              </>
            )}
          </tr>
        </tbody>
      </table>
      <p className="small" style={{ marginTop: 12 }}>
        {digestLine(notify.digest)}
      </p>
      <div className="subh">recent</div>
      {notify.recent.length === 0 ? (
        <p className="small">none</p>
      ) : (
        <table className="tbl" aria-label="Recent sends">
          <thead>
            <tr>
              <th>time</th>
              <th>what</th>
              <th>channel</th>
              <th />
              <th className="r">tries</th>
              <th>error</th>
            </tr>
          </thead>
          <tbody>
            {notify.recent.map((e) => (
              <tr key={`${e.id}.${e.channel}`}>
                <td title={e.created_at}>{fmtClock(e.created_at)}</td>
                <td className="mono" title={e.notice.title}>
                  {recentWhat(e)}
                </td>
                <td>{e.channel}</td>
                <td className={e.status === "failed" ? "bad" : e.status === "sent" ? "ok" : undefined}>
                  {`${OUTBOX_GLYPH[e.status]} ${e.status}`}
                </td>
                <td className="r">{e.attempts}</td>
                <td className="mono dim">{e.last_error ?? "·"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/settings && bun run typecheck`
Expected: `notifyPanel.test.tsx` 3 pass; the other settings files pass; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/settings/NotifyPanel.tsx ui/test/settings/notifyPanel.test.tsx
git commit -m "feat(ui): notifications panel with channels, test send, rules, digest and recent sends"
```

---

### Task 13: The Settings page and route `/settings`

**Files:**
- Create: `ui/src/pages/Settings.tsx`
- Modify: `ui/src/router.tsx` (doc comment, import, route, route tree)
- Create: `ui/test/pages/Settings.test.tsx`
- Modify: `ui/test/router.test.tsx` (the route list)

**Interfaces:**
- Consumes: Tasks 9–12; Task 3 `useMe`, `useSessions`, `useUsers`, `useNotify`; Task 2 `authOn`, `isAdmin`; `Figure`, `panelLetter`, `PageStyles`, `ErrorBox`, `Loading`, `useNow`.
- Produces: `SettingsPage({ now? })` (`now` fixes the clock in tests). Admin with auth on: a Sessions (everyone's), b Users, c Add device, d Notifications. Collaborator: a Sessions (own), b Add device; never requests `/auth/users` or `/notify`. Auth off: a Notifications only; no `/auth/sessions`. Letters follow the panels shown. Router `settingsRoute` (path `/settings`).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/Settings.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { screen, waitFor } from "@testing-library/react";
import { SettingsPage } from "../../src/pages/Settings";
import { ME_ADMIN, ME_ALICE, ME_OFF, NOTIFY, NOW, SESSIONS, USERS } from "../api/phase3-fixtures";
import { mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(restoreFetch);

const regions = () => screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));

test("an admin: headline and panels a-d", async () => {
  mockApi({
    "GET /api/v1/auth/me": ME_ADMIN,
    "GET /api/v1/auth/sessions": SESSIONS,
    "GET /api/v1/auth/users": USERS,
    "GET /api/v1/notify": NOTIFY,
  });
  renderWithClient(<SettingsPage now={NOW} />);
  await waitFor(() =>
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("3 users · 5 sessions · slack ● email ○"),
  );
  expect(regions()).toEqual(["a Sessions", "b Users", "c Add device", "d Notifications"]);
  expect(screen.getByText("hub.tail1234.ts.net")).toBeTruthy();
});

test("a collaborator sees own sessions and add device only; admin routes are never requested", async () => {
  const own = SESSIONS.filter((s) => s.user === "alice");
  const calls = mockApi({ "GET /api/v1/auth/me": ME_ALICE, "GET /api/v1/auth/sessions": own });
  renderWithClient(<SettingsPage now={NOW} />);
  await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("@alice · launch · 2 sessions"));
  expect(regions()).toEqual(["a Sessions", "b Add device"]);
  expect(calls.map((c) => c.url).sort()).toEqual(["/api/v1/auth/me", "/api/v1/auth/sessions"]);
});

test("auth off: notifications only, no session list", async () => {
  const calls = mockApi({ "GET /api/v1/auth/me": ME_OFF, "GET /api/v1/notify": NOTIFY });
  renderWithClient(<SettingsPage now={NOW} />);
  await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("auth off · slack ● email ○"));
  expect(regions()).toEqual(["a Notifications"]);
  expect(calls.some((c) => c.url === "/api/v1/auth/sessions")).toBe(false);
});
```

In `ui/test/router.test.tsx`, add `"/settings",` after `"/pair",` in the route list of `every route renders its own screen, not the placeholder`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/Settings.test.tsx test/router.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/pages/Settings'`; the router test renders Not found for `/settings` (still not the placeholder, so that test passes; `bun run typecheck` is clean until Step 3 adds the route).

- [ ] **Step 3: Write `Settings.tsx` and the route**

Create `ui/src/pages/Settings.tsx`:

```tsx
/**
 * `/settings` (phase 3 contract 10, mockups `shot-settings-*`, `shot-settings-collab-*`):
 * sessions, users, add device, notifications. What a principal sees follows its scope; the
 * page never requests an admin-only route for a non-admin.
 */
import { authOn, isAdmin } from "../api/auth";
import { useMe, useNotify, useSessions, useUsers } from "../api/queries";
import { AddDevice } from "../settings/AddDevice";
import { liveSessions, settingsHeadline } from "../settings/model";
import { NotifyPanel } from "../settings/NotifyPanel";
import { SessionsPanel } from "../settings/SessionsPanel";
import { SettingsStyles } from "../settings/styles";
import { UsersPanel } from "../settings/UsersPanel";
import { Figure, panelLetter } from "./components/Figure";
import { Unbroken } from "./components/Headline";
import { useNow } from "./components/HostsPanel";
import { ErrorBox, Loading } from "./components/QueryState";
import { PageStyles } from "./components/styles";

/** The hub's name for the crumb: its public URL's host, else this page's host. */
function hubName(publicUrl: string | null): string {
  if (publicUrl) {
    try {
      return new URL(publicUrl).host;
    } catch {
      // fall through to the page's host
    }
  }
  return window.location.host;
}

export interface SettingsPageProps {
  /** Fixed clock (tests). */
  now?: number;
}

export function SettingsPage({ now }: SettingsPageProps = {}) {
  const me = useMe();
  const principal = me.data ?? null;
  const on = authOn(principal);
  const admin = isAdmin(principal);
  const sessions = useSessions(on);
  const users = useUsers(on && admin);
  const notify = useNotify(admin);
  const ticking = useNow(30_000);
  const at = now ?? ticking;

  if (me.error || principal === null) {
    return (
      <div className="page settings">
        <PageStyles />
        {me.error ? <ErrorBox error={me.error} /> : <Loading />}
      </div>
    );
  }

  const live = sessions.data ? liveSessions(sessions.data, at) : null;
  const headline = settingsHeadline({
    principal,
    sessions: live,
    users: users.data ?? null,
    notify: notify.data ?? null,
  });
  let next = 0;
  const letter = () => panelLetter(next++);
  const sessionsLetter = on ? letter() : "";
  const usersLetter = on && admin ? letter() : "";
  const deviceLetter = on ? letter() : "";
  const notifyLetter = admin ? letter() : "";

  return (
    <div className="page settings">
      <PageStyles />
      <SettingsStyles />
      <p className="crumb">
        <span>{hubName(principal.public_url)}</span>
        <span className="sep">/</span>
        settings
      </p>
      <h1 className="headline">
        <Unbroken text={headline} />
      </h1>
      <p className="metaline">
        <span>{on ? "auth on" : "auth off"}</span>
        {principal.public_url ? <span className="mono">{principal.public_url}</span> : null}
        {on ? <span>{`@${principal.user} ${principal.scope}`}</span> : null}
      </p>
      {on ? (
        <Figure letter={sessionsLetter} title="Sessions" aside={live ? String(live.length) : undefined}>
          {sessions.error ? (
            <ErrorBox error={sessions.error} />
          ) : sessions.data ? (
            <SessionsPanel sessions={sessions.data} principal={principal} now={at} showUser={admin} />
          ) : (
            <Loading />
          )}
        </Figure>
      ) : null}
      {on ? (
        <div className="set-grid">
          {admin ? (
            <Figure letter={usersLetter} title="Users">
              {users.error ? (
                <ErrorBox error={users.error} />
              ) : users.data && sessions.data ? (
                <UsersPanel users={users.data} sessions={sessions.data} principal={principal} now={at} />
              ) : (
                <Loading />
              )}
            </Figure>
          ) : null}
          <Figure letter={deviceLetter} title="Add device" aside={`≤ ${principal.scope} · 5 min · one use`}>
            <AddDevice principal={principal} users={admin ? (users.data ?? []) : null} now={now} />
          </Figure>
        </div>
      ) : null}
      {admin ? (
        <Figure letter={notifyLetter} title="Notifications">
          {notify.error ? <ErrorBox error={notify.error} /> : notify.data ? <NotifyPanel notify={notify.data} /> : <Loading />}
        </Figure>
      ) : null}
    </div>
  );
}
```

In `ui/src/router.tsx`: add `` `/settings` Settings `` to the doc comment; add `import { SettingsPage } from "./pages/Settings";`; after `pairRoute`, add

```tsx
export const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  component: SettingsPage,
});
```

and add `settingsRoute,` to `rootRoute.addChildren([...])`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/pages/Settings.test.tsx test/settings test/router.test.tsx && bun run typecheck`
Expected: `Settings.test.tsx` 3 pass; the settings files and the router test pass; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/pages/Settings.tsx ui/src/router.tsx ui/test/pages/Settings.test.tsx ui/test/router.test.tsx
git commit -m "feat(ui): settings page at /settings, scoped to the signed-in principal"
```

---

## Group 4: Storage `/storage` (Tasks 14–17)

The Storage page (admin; mockups `shot-storage-*`, `shot-storage-confirm-*`, `shot-storage-result-*`): headline `1.84 TB · 412 GB cleanable` with `archived, >30d`, a bytes by project (local solid, remote hatched), b bytes by host, c largest items (run, host, kind, path, bytes, age, `★`/`archived`), d clean: `older than [30] d`, kind chips, `dry run` → plan table with refused rows greyed (`⊘ protected`, `⊘ used by 01J…`), `apply` (disabled until there is an unexpired plan) → a dialog `delete 412.3 GB · 3 paths · 3 hosts` that needs the number typed back → `✓ freed 409.8 GB · 2 deleted · 1 skipped`. The UI never deletes without a plan, never sends a confirm the user did not type, and never offers apply to an agent (MCP has no such tool; the UI is for humans).

### Task 14: Storage model

**Files:**
- Create: `ui/src/storage/model.ts`
- Create: `ui/test/storage/model.test.ts`

**Interfaces:**
- Consumes: Task 1 models; `fmtBytes`, `parseTime`, `fmtClock`, `shortId` (`pages/components/format`); `LOCAL_HOST` (`pages/components/HostsPanel`).
- Produces: `TERMINAL: ReadonlySet<RunStatus>`; `fmtBytes3(n)` (three significant digits: `1.84 TB`, `412 GB`, `96.4 GB`, `2.10 GB`); `confirmText(total)` (the number of `fmtBytes(total)`: `412.3`) and `confirmUnit(total)` (`GB`); `confirmMatches(typed, total)`; `interface ProjectBar { project; local; remote; total }` and `projectBars(report)`; `interface HostBar { host; bytes }` and `hostBars(report)`; `largest(items, n = 20)`; `ageDays(item, now)`; `defaultPolicy(): CleanPolicy`; `isCleanable(item, policy, now)` and `cleanableBytes(items, policy, now)` (the client's estimate for the headline; the plan decides); `artifactKinds(items)` (`checkpoint` first); `storageHeadline(report, cleanable)`; `kindLine(report)`; `planFacts(plan)` (`{total, paths, hosts}`); `planExpired(plan, now)`; `resultLine(result)`.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/storage/model.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import {
  ageDays,
  artifactKinds,
  cleanableBytes,
  confirmMatches,
  confirmText,
  confirmUnit,
  defaultPolicy,
  fmtBytes3,
  hostBars,
  isCleanable,
  kindLine,
  largest,
  planExpired,
  planFacts,
  projectBars,
  resultLine,
  storageHeadline,
} from "../../src/storage/model";
import { CLEAN_PLAN, CLEAN_RESULT, NOW, STORAGE_ITEMS, STORAGE_REPORT } from "../api/phase3-fixtures";

const GB = 1e9;

describe("bytes", () => {
  test("fmtBytes3 keeps three significant digits", () => {
    expect([1.84e12, 412 * GB, 96.4 * GB, 2.1 * GB, 18.5e6, 4.2e3, 512, 0].map(fmtBytes3)).toEqual([
      "1.84 TB",
      "412 GB",
      "96.4 GB",
      "2.10 GB",
      "18.5 MB",
      "4.20 KB",
      "512 B",
      "0 B",
    ]);
  });

  test("the confirm number is the plan total as shown, typed back exactly", () => {
    expect([confirmText(412_300_000_000), confirmUnit(412_300_000_000)]).toEqual(["412.3", "GB"]);
    expect([confirmText(512), confirmUnit(512)]).toEqual(["512", "B"]);
    expect(["412.3", " 412.3 ", "412", "412.30", "412.3 GB", ""].map((t) => confirmMatches(t, 412_300_000_000))).toEqual([
      true,
      true,
      false,
      false,
      false,
      false,
    ]);
  });
});

describe("report", () => {
  test("bars by project split local and remote; hosts sorted by bytes", () => {
    expect(projectBars(STORAGE_REPORT).map((b) => [b.project, b.local / GB, Math.round(b.remote / GB), b.total / GB])).toEqual([
      ["deepretro", 44.2, 1076, 1120],
      ["rxn-forward", 21.8, 512, 534],
      ["toy-classifier", 186, 0, 186],
    ]);
    expect(hostBars(STORAGE_REPORT).map((b) => [b.host, b.bytes / GB])).toEqual([
      ["gpu1", 812],
      ["local", 484],
      ["mccleary", 371],
      ["dgx", 173],
    ]);
    expect(kindLine(STORAGE_REPORT)).toEqual(["artifact 1.52 TB", "run 214 GB", "pulled 106 GB"]);
  });

  test("largest items and their age in days", () => {
    expect(largest(STORAGE_ITEMS, 3).map((i) => i.run_id)).toEqual([
      "01J7TOY0-clf-0001",
      "01J7QK2D-tr-5e9a",
      "01J8B0MZ-tr-a3c1",
    ]);
    expect(STORAGE_ITEMS.slice(0, 4).map((i) => ageDays(i, NOW))).toEqual([45, 45, 45, 6]);
  });

  test("cleanable: archived, unstarred, ended long enough ago, a chosen kind or a pulled copy", () => {
    const policy = defaultPolicy();
    expect(policy).toEqual({
      archived: true,
      older_than_days: 30,
      kinds: ["checkpoint"],
      projects: null,
      hosts: null,
      include_pulled: true,
    });
    expect(STORAGE_ITEMS.filter((i) => isCleanable(i, policy, NOW)).map((i) => i.run_id)).toEqual([
      "01J7QK2D-tr-5e9a",
      "01J7MZ81-tr-0a6d",
    ]);
    expect(cleanableBytes(STORAGE_ITEMS, policy, NOW) / GB).toBeCloseTo(170.4, 6);
    expect(cleanableBytes(STORAGE_ITEMS, { ...policy, kinds: ["*"] }, NOW) / GB).toBeCloseTo(210.3, 6);
    expect(cleanableBytes(STORAGE_ITEMS, { ...policy, older_than_days: 60 }, NOW)).toBe(0);
    expect(artifactKinds(STORAGE_ITEMS)).toEqual(["checkpoint", "predictions"]);
    expect(storageHeadline(STORAGE_REPORT, 170.4 * GB)).toBe("1.84 TB · 170 GB cleanable");
  });
});

describe("plan and result", () => {
  test("plan facts, expiry and the result line", () => {
    expect(planFacts(CLEAN_PLAN)).toEqual({ total: "412.3 GB", paths: 3, hosts: 3 });
    expect([planExpired(CLEAN_PLAN, NOW), planExpired(CLEAN_PLAN, NOW + 3_600_001)]).toEqual([false, true]);
    expect(resultLine(CLEAN_RESULT)).toBe("freed 409.8 GB · 2 deleted · 1 skipped");
    expect(resultLine({ ...CLEAN_RESULT, errors: [{ host: "dgx", error: "unreachable" }] })).toBe(
      "freed 409.8 GB · 2 deleted · 1 skipped · 1 error",
    );
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/storage/model.test.ts`
Expected: FAIL: `error: Cannot find module '../../src/storage/model'`.

- [ ] **Step 3: Write `model.ts`**

Create `ui/src/storage/model.ts`:

```ts
/**
 * Storage page arithmetic (phase 3 contract 1.9; mockups `shot-storage-*`): byte texts,
 * bars, largest items, the client's cleanable estimate for the headline, the confirm text
 * of a plan, plan facts and the result line. The hub's plan is the only list of what will
 * be deleted; the estimate only fills the headline before a dry run.
 */
import type { CleanPlan, CleanPolicy, CleanResult, RunStatus, StorageItem, StorageReport } from "../api/models";
import { fmtBytes, parseTime } from "../pages/components/format";
import { LOCAL_HOST } from "../pages/components/HostsPanel";

/** Statuses after which a run can be cleaned. */
export const TERMINAL: ReadonlySet<RunStatus> = new Set<RunStatus>(["finished", "failed", "killed", "lost"]);

const UNITS: readonly [string, number][] = [
  ["TB", 1e12],
  ["GB", 1e9],
  ["MB", 1e6],
  ["KB", 1e3],
];

/** Three significant digits: `1.84 TB`, `412 GB`, `96.4 GB`, `2.10 GB`, `512 B`. */
export function fmtBytes3(n: number): string {
  for (const [unit, factor] of UNITS) {
    if (n >= factor) {
      const v = n / factor;
      return `${v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2)} ${unit}`;
    }
  }
  return `${Math.round(n)} B`;
}

/** The number the user types back to apply a plan: the plan total as `fmtBytes` shows it. */
export function confirmText(totalBytes: number): string {
  return fmtBytes(totalBytes).split(" ")[0] ?? "";
}

/** The unit next to the confirm field (`GB`). */
export function confirmUnit(totalBytes: number): string {
  return fmtBytes(totalBytes).split(" ")[1] ?? "";
}

/** True when `typed` (trimmed) is exactly `confirmText(total)`; the request then sends `total`. */
export function confirmMatches(typed: string, totalBytes: number): boolean {
  return typed.trim() === confirmText(totalBytes);
}

export interface ProjectBar {
  project: string;
  local: number;
  remote: number;
  total: number;
}

/** Bytes per project: `local` on the hub's own disk (host `local`), the rest remote; largest first. */
export function projectBars(report: StorageReport): ProjectBar[] {
  const local = new Map<string, number>();
  for (const item of report.items) {
    if (item.host === LOCAL_HOST) local.set(item.project, (local.get(item.project) ?? 0) + item.bytes);
  }
  return Object.entries(report.by_project)
    .map(([project, total]) => {
      const here = Math.min(total, local.get(project) ?? 0);
      return { project, local: here, remote: total - here, total };
    })
    .sort((a, b) => b.total - a.total || a.project.localeCompare(b.project));
}

export interface HostBar {
  host: string;
  bytes: number;
}

/** Bytes per host, largest first. */
export function hostBars(report: StorageReport): HostBar[] {
  return Object.entries(report.by_host)
    .map(([host, bytes]) => ({ host, bytes }))
    .sort((a, b) => b.bytes - a.bytes || a.host.localeCompare(b.host));
}

/** The `n` largest items. */
export function largest(items: readonly StorageItem[], n = 20): StorageItem[] {
  return [...items].sort((a, b) => b.bytes - a.bytes).slice(0, n);
}

/** Whole days since the run ended (else since the newest file changed); null when unknown. */
export function ageDays(item: StorageItem, now: number): number | null {
  const at = item.ended_at ? parseTime(item.ended_at) : item.mtime !== null ? item.mtime * 1000 : Number.NaN;
  return Number.isNaN(at) ? null : Math.max(0, Math.floor((now - at) / 86_400_000));
}

/** The hub's default policy (`StorageSettings`: 30 days, checkpoints, pulled copies too). */
export function defaultPolicy(): CleanPolicy {
  return { archived: true, older_than_days: 30, kinds: ["checkpoint"], projects: null, hosts: null, include_pulled: true };
}

/** Contract 1.9 eligibility, as far as the report shows it (the hub also checks paths and children). */
export function isCleanable(item: StorageItem, policy: CleanPolicy, now: number): boolean {
  if (!item.archived || item.starred || !TERMINAL.has(item.status) || !item.ended_at) return false;
  if (parseTime(item.ended_at) > now - policy.older_than_days * 86_400_000) return false;
  if (item.kind === "pulled") return policy.include_pulled;
  if (item.kind !== "artifact") return false;
  return policy.kinds.includes("*") || (item.artifact_kind !== null && policy.kinds.includes(item.artifact_kind));
}

/** Sum of `isCleanable` items. */
export function cleanableBytes(items: readonly StorageItem[], policy: CleanPolicy, now: number): number {
  return items.reduce((sum, item) => (isCleanable(item, policy, now) ? sum + item.bytes : sum), 0);
}

/** Artifact kinds in the report, `checkpoint` first, then by name. */
export function artifactKinds(items: readonly StorageItem[]): string[] {
  const kinds = new Set(items.map((i) => i.artifact_kind).filter((k): k is string => k !== null));
  kinds.add("checkpoint");
  return [...kinds].sort((a, b) => (a === "checkpoint" ? -1 : b === "checkpoint" ? 1 : a.localeCompare(b)));
}

/** `1.84 TB · 412 GB cleanable`. */
export function storageHeadline(report: StorageReport, cleanable: number): string {
  return `${fmtBytes3(report.total_bytes)} · ${fmtBytes3(cleanable)} cleanable`;
}

/** `artifact 1.52 TB`, `run 214 GB`, … largest first. */
export function kindLine(report: StorageReport): string[] {
  return Object.entries(report.by_kind)
    .sort((a, b) => b[1] - a[1])
    .map(([kind, bytes]) => `${kind} ${fmtBytes3(bytes)}`);
}

/** What a plan deletes: `412.3 GB`, paths, hosts. */
export function planFacts(plan: CleanPlan): { total: string; paths: number; hosts: number } {
  return {
    total: fmtBytes(plan.total_bytes),
    paths: plan.items.length,
    hosts: new Set(plan.items.map((i) => i.host)).size,
  };
}

/** True once the hub would refuse the plan (`plan_ttl_minutes`). */
export function planExpired(plan: CleanPlan, now: number): boolean {
  return parseTime(plan.expires_at) <= now;
}

const count = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** `freed 409.8 GB · 2 deleted · 1 skipped` (and `· 1 error` when a host failed). */
export function resultLine(result: CleanResult): string {
  const parts = [
    `freed ${fmtBytes(result.freed_bytes)}`,
    `${result.deleted.length} deleted`,
    `${result.skipped.length} skipped`,
  ];
  if (result.errors.length > 0) parts.push(count(result.errors.length, "error", "errors"));
  return parts.join(" · ");
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/storage/model.test.ts && bun run typecheck`
Expected: 6 pass, `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/storage/model.ts ui/test/storage/model.test.ts
git commit -m "feat(ui): storage model for bytes, bars, cleanable estimate, confirm text and results"
```

---

### Task 15: Storage bars and the largest-items table

**Files:**
- Create: `ui/src/storage/styles.ts`
- Create: `ui/src/storage/StorageBars.tsx`
- Create: `ui/src/storage/LargestTable.tsx`
- Create: `ui/test/storage/parts.test.tsx`

**Interfaces:**
- Consumes: Task 14; `AppLink`, `hrefs`, `shortId`, `tailPath`.
- Produces: `STORAGE_CSS`, `StorageStyles()` (selectors under `.page.storage`); `ProjectBars({ bars })` (rows `aria-label="<project>"`, a track with `i.l` (local) and `i.m` (remote) widths as percentages of the largest total, the total; a key `local`/`remote`); `HostBars({ bars })` (`i.l` for `local`, `i.m` for remote hosts); `LargestTable({ items, now, total })` (`aria-label="Largest"`: run link, host, kind, path tail with the full path as title, bytes, `<n>d`, `★` and an `archived` tag).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/storage/parts.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { render, screen, within } from "@testing-library/react";
import { hostBars, projectBars } from "../../src/storage/model";
import { HostBars, ProjectBars } from "../../src/storage/StorageBars";
import { LargestTable } from "../../src/storage/LargestTable";
import { NOW, STORAGE_ITEMS, STORAGE_REPORT } from "../api/phase3-fixtures";
import { restoreFetch } from "../pages/helpers";

afterEach(restoreFetch);

const widths = (row: HTMLElement) =>
  [...row.querySelectorAll<HTMLElement>(".tr i")].map((i) => `${i.className} ${i.style.width}`);

test("project bars: local and remote shares of the largest project", () => {
  render(<ProjectBars bars={projectBars(STORAGE_REPORT)} />);
  const deep = screen.getByLabelText("deepretro");
  expect(widths(deep)).toEqual(["l 3.95%", "m 96.05%"]);
  expect(within(deep).getByText("1.12 TB")).toBeTruthy();
  expect(within(deep).getByTitle("local 44.2 GB · remote 1.08 TB")).toBeTruthy();
  expect(widths(screen.getByLabelText("toy-classifier"))).toEqual(["l 16.61%", "m 0%"]);
  expect(screen.getByLabelText("Key").textContent).toBe("localremote");
});

test("host bars: the hub's disk solid, remote hosts hatched", () => {
  render(<HostBars bars={hostBars(STORAGE_REPORT)} />);
  expect(widths(screen.getByLabelText("gpu1"))).toEqual(["m 100%"]);
  expect(widths(screen.getByLabelText("local"))).toEqual(["l 59.61%"]);
  expect(within(screen.getByLabelText("dgx")).getByText("173 GB")).toBeTruthy();
});

test("largest: run, host, kind, path tail, bytes, age and flags", () => {
  render(<LargestTable items={STORAGE_ITEMS} now={NOW} total={1204} />);
  const rows = within(screen.getByRole("table", { name: "Largest" })).getAllByRole("row").slice(1);
  expect(rows.slice(0, 3).map((r) => within(r).getAllByRole("cell").map((c) => c.textContent))).toEqual([
    ["0001", "local", "run", "…/toy-classifier/runs/01J7TOY0-clf-0001", "186 GB", "45d", ""],
    ["5e9a", "mccleary", "checkpoint", "…/01J7QK2D-tr-5e9a/artifacts/ckpt", "96.4 GB", "45d", "archived"],
    ["a3c1", "gpu1", "checkpoint", "…/01J8B0MZ-tr-a3c1/artifacts/ckpt", "88.1 GB", "45d", "★"],
  ]);
  expect(within(rows[1] as HTMLElement).getByRole("link", { name: "5e9a" }).getAttribute("href")).toBe("/r/01J7QK2D-tr-5e9a");
  expect(within(rows[1] as HTMLElement).getByTitle("/scratch/sv/hx/runs/01J7QK2D-tr-5e9a/artifacts/ckpt")).toBeTruthy();
});
```

(Widths: deepretro local 44.2 / 1120 = 3.95%, remote 1075.8 / 1120 = 96.05%; toy-classifier 186 / 1120 = 16.61%; host `local` 484 / 812 = 59.61%.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/storage/parts.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/storage/StorageBars'`.

- [ ] **Step 3: Write the styles, bars and table**

Create `ui/src/storage/styles.ts`:

```ts
/** Storage CSS, from docs/mockups/phase3 (`shot-storage-*`). Every selector starts with `.page.storage`. */
import { createElement } from "react";

export const STORAGE_CSS = `
.page.storage h1.headline .then { color: var(--ink-3); font-weight: 400; font-size: 27px; letter-spacing: 0; }
.page.storage .two-x .fig { margin-top: 0; }
.page.storage .bars { font-variant-numeric: tabular-nums; }
.page.storage .brow { display: grid; grid-template-columns: 128px minmax(0, 1fr) 76px; gap: 0 16px; align-items: center; padding: 9px 0; border-top: 1px solid var(--rule-2); font-size: 14px; }
.page.storage .brow:first-child { border-top: 0; }
.page.storage .brow .nm { font-weight: 550; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.page.storage .brow .r { text-align: right; }
.page.storage .tr { display: flex; height: 14px; }
.page.storage .tr i { display: block; height: 100%; }
.page.storage .tr i.l { background: var(--ink-2); }
.page.storage .tr i.m { background: repeating-linear-gradient(135deg, var(--ink-3) 0 1.5px, transparent 1.5px 5px); box-shadow: inset 0 0 0 1px var(--ink-3); }
.page.storage .gk { display: inline-block; width: 18px; height: 11px; }
.page.storage .gk.l { background: var(--ink-2); }
.page.storage .gk.m { background: repeating-linear-gradient(135deg, var(--ink-3) 0 1.5px, transparent 1.5px 5px); box-shadow: inset 0 0 0 1px var(--ink-3); }
.page.storage .tbl { font-variant-numeric: tabular-nums; }
.page.storage .tbl td { vertical-align: baseline; white-space: nowrap; }
.page.storage .tbl td.path { white-space: normal; max-width: 420px; }
.page.storage .p { font-family: var(--mono); font-size: 13px; color: var(--ink); }
.page.storage .tbl tr.refused td, .page.storage .tbl tr.refused .p { color: var(--ink-3); }
.page.storage .tbl tr.more td { color: var(--ink-3); font-size: 13px; }
.page.storage .dim { color: var(--ink-3); }
.page.storage .ok { color: var(--best); }
.page.storage .cleanbar { display: flex; gap: 18px; align-items: center; flex-wrap: wrap; padding: 12px 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); font-size: 14px; color: var(--ink-2); }
.page.storage .cleanbar .r { margin-left: auto; display: flex; gap: 8px; }
.page.storage .in { height: 32px; width: 64px; text-align: center; border: 1px solid var(--rule); border-radius: 6px; background: transparent; padding: 0 10px; font-size: 14px; color: var(--ink); font-variant-numeric: tabular-nums; }
.page.storage .in[aria-invalid="true"] { border-color: var(--fail); }
.page.storage .kc { height: 28px; padding: 0 11px; border-radius: 99px; border: 1px solid var(--rule); background: transparent; font-size: 13px; color: var(--ink-3); cursor: pointer; }
.page.storage .kc[aria-pressed="true"] { border-color: var(--ink); color: var(--ink); background: var(--paper-2); }
.page.storage .planline { display: flex; gap: 18px; align-items: baseline; flex-wrap: wrap; margin: 22px 0 12px; font-size: 14px; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.page.storage .planline b { font: 400 25px/1 var(--sans); color: var(--ink); letter-spacing: -.01em; }
.page.storage .resline { margin-top: 18px; padding: 12px 0; border-top: 1px solid var(--rule); font-size: 14px; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.page.storage .hx-confirm { position: fixed; inset: 0; z-index: 30; display: flex; justify-content: center; align-items: flex-start; padding-top: 160px; background: color-mix(in srgb, var(--ink) 24%, transparent); }
[data-theme="dark"] .page.storage .hx-confirm { background: rgba(0, 0, 0, .55); }
.page.storage .dlg { width: 520px; max-width: calc(100vw - 24px); background: var(--paper); border: 1px solid var(--rule); border-radius: 10px; box-shadow: 0 24px 60px -20px rgba(10, 14, 20, .35); }
.page.storage .dlg-h { padding: 18px 24px 14px; border-bottom: 1px solid var(--rule); }
.page.storage .dlg-h h2 { margin: 0; font: 500 26px/1.1 var(--serif); letter-spacing: -.01em; }
.page.storage .dlg-b { padding: 18px 24px; font-size: 14px; color: var(--ink-2); font-variant-numeric: tabular-nums; }
.page.storage .dlg-b .row { margin-top: 16px; }
.page.storage .dlg-b .in { width: 132px; text-align: left; }
.page.storage .dlg-f { display: flex; gap: 8px; align-items: center; padding: 14px 24px; border-top: 1px solid var(--rule); }
.page.storage .dlg-f .sp { margin-left: auto; }
.page.storage .btn.danger { background: var(--fail); color: #fff; border-color: var(--fail); }
.page.storage .btn.danger:disabled { background: transparent; color: var(--ink-3); border-color: var(--rule-2); }
`;

/** Inject the storage CSS. */
export function StorageStyles() {
  return createElement("style", { "data-hx": "storage" }, STORAGE_CSS);
}
```

Create `ui/src/storage/StorageBars.tsx`:

```tsx
/** Storage panels a and b: bytes per project (local solid, remote hatched) and per host. */
import { LOCAL_HOST } from "../pages/components/HostsPanel";
import { fmtBytes3, type HostBar, type ProjectBar } from "./model";

/** `12.3456` → `"12.35%"`; widths are shares of the largest row. */
const pct = (part: number, whole: number): string => `${whole > 0 ? Math.round((part / whole) * 10_000) / 100 : 0}%`;

export function ProjectBars({ bars }: { bars: ProjectBar[] }) {
  if (bars.length === 0) return <p className="small">none</p>;
  const max = Math.max(...bars.map((b) => b.total));
  return (
    <>
      <div className="bars">
        {bars.map((b) => (
          <div key={b.project} className="brow" aria-label={b.project}>
            <span className="nm">{b.project}</span>
            <span className="tr" title={`local ${fmtBytes3(b.local)} · remote ${fmtBytes3(b.remote)}`}>
              <i className="l" style={{ width: pct(b.local, max) }} />
              <i className="m" style={{ width: pct(b.remote, max) }} />
            </span>
            <span className="r">{fmtBytes3(b.total)}</span>
          </div>
        ))}
      </div>
      <div className="key" aria-label="Key">
        <span title="On the hub's own disk">
          <span className="gk l" />
          local
        </span>
        <span title="On the hosts">
          <span className="gk m" />
          remote
        </span>
      </div>
    </>
  );
}

export function HostBars({ bars }: { bars: HostBar[] }) {
  if (bars.length === 0) return <p className="small">none</p>;
  const max = Math.max(...bars.map((b) => b.bytes));
  return (
    <div className="bars">
      {bars.map((b) => (
        <div key={b.host} className="brow" aria-label={b.host}>
          <span className="nm">{b.host}</span>
          <span className="tr">
            <i className={b.host === LOCAL_HOST ? "l" : "m"} style={{ width: pct(b.bytes, max) }} />
          </span>
          <span className="r">{fmtBytes3(b.bytes)}</span>
        </div>
      ))}
    </div>
  );
}
```

Create `ui/src/storage/LargestTable.tsx`:

```tsx
/** Storage panel c: the largest items, with where they are and why they stay or could go. */
import type { StorageItem } from "../api/models";
import { shortId, tailPath } from "../pages/components/format";
import { AppLink, hrefs } from "../pages/components/links";
import { ageDays, fmtBytes3, largest } from "./model";

export interface LargestTableProps {
  items: StorageItem[];
  now: number;
  /** Items in the whole report (the aside's `20 of 1,204`); shown by the page. */
  total: number;
}

export function LargestTable({ items, now }: LargestTableProps) {
  const rows = largest(items);
  if (rows.length === 0) return <p className="small">none</p>;
  return (
    <table className="tbl" aria-label="Largest">
      <thead>
        <tr>
          <th>run</th>
          <th>host</th>
          <th>kind</th>
          <th>path</th>
          <th className="r">bytes</th>
          <th className="r">age</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((item) => {
          const age = ageDays(item, now);
          return (
            <tr key={`${item.host}:${item.path}`}>
              <td>
                <AppLink className="p" href={hrefs.run(item.run_id)} title={item.run_id}>
                  {shortId(item.run_id)}
                </AppLink>
              </td>
              <td>{item.host}</td>
              <td>{item.artifact_kind ?? item.kind}</td>
              <td className="path">
                <span className="p" title={item.path}>
                  {tailPath(item.path)}
                </span>
              </td>
              <td className="r">{fmtBytes3(item.bytes)}</td>
              <td className="r">{age === null ? "—" : `${age}d`}</td>
              <td>
                {item.starred ? <span title="starred: never cleaned">★</span> : null}
                {item.archived ? <span className="tag">archived</span> : null}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/storage && bun run typecheck`
Expected: `parts.test.tsx` 3 pass, `model.test.ts` 6 pass; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/storage/styles.ts ui/src/storage/StorageBars.tsx ui/src/storage/LargestTable.tsx ui/test/storage/parts.test.tsx
git commit -m "feat(ui): storage bars by project and host and the largest-items table"
```

---

### Task 16: Clean: dry run, plan, typed confirm, apply

**Files:**
- Create: `ui/src/storage/CleanPanel.tsx`
- Create: `ui/test/storage/cleanPanel.test.tsx`

**Interfaces:**
- Consumes: Task 14 (`artifactKinds`, `defaultPolicy`, `planFacts`, `planExpired`, `confirmText`, `confirmUnit`, `confirmMatches`, `resultLine`, `fmtBytes3`); `api.planClean`, `api.applyClean`, `STORAGE_EVENT_INVALIDATES`; `useAction`, `ErrorBox`, `fmtClock`, `shortId`, `tailPath`.
- Produces: `CleanPanel({ items, now })`. The policy bar: `older than [30] d` (`aria-label="Days"`, whole numbers ≥ 0, else `aria-invalid` and `dry run` disabled), one chip per artifact kind plus `pulled` (`aria-pressed`), `dry run`, `apply`. `dry run` posts the policy and shows the plan line (`412.3 GB`, `3 paths`, `3 hosts`, plan id, `until 15:32` or `expired`), the items (the first 50, then `+ N more`) and the refused rows (`⊘ <reason>`). `apply` is disabled without a plan and for an expired one (`title="plan expired: dry run again"`). It opens `role="dialog"` `delete 412.3 GB`, `3 paths · 3 hosts · cp-8e41c0d2`, `type 412.3 [   ] GB`; `delete` is enabled only on an exact match and posts `confirm_bytes = plan.total_bytes`. Success shows `✓ freed …` and clears the plan; a refusal shows the hub's message in the dialog and keeps the plan. The dialog confirms the plan as it was when `apply` was clicked (a frozen copy): `dry run` is disabled while the dialog is open, and `apply` is disabled while a dry run is in flight (`title="dry run in flight"`), so a new plan can never slip under a typed confirmation.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/storage/cleanPanel.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { CleanPanel } from "../../src/storage/CleanPanel";
import { CLEAN_PLAN, CLEAN_RESULT, NOW, STORAGE_ITEMS } from "../api/phase3-fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";

afterEach(restoreFetch);

const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;
const PLAN = "POST /api/v1/storage/plan";
const APPLY = "POST /api/v1/storage/plans/cp-8e41c0d2/apply";

async function dryRun() {
  fireEvent.click(button("dry run"));
  await screen.findByText("cp-8e41c0d2");
}

describe("dry run", () => {
  test("apply is disabled until a plan exists", () => {
    mockApi({});
    renderWithClient(<CleanPanel items={STORAGE_ITEMS} now={NOW} />);
    expect([button("apply").disabled, button("apply").title]).toEqual([true, "dry run first"]);
  });

  test("dry run posts the policy; the plan lists items and refused rows", async () => {
    const calls = mockApi({ [PLAN]: CLEAN_PLAN });
    renderWithClient(<CleanPanel items={STORAGE_ITEMS} now={NOW} />);
    await dryRun();
    const { command_id, ...policy } = calls[0]?.body as Record<string, unknown>;
    expect(typeof command_id).toBe("string");
    expect(policy).toEqual({ archived: true, older_than_days: 30, kinds: ["checkpoint"], projects: null, hosts: null, include_pulled: true });
    expect(screen.getByLabelText("Plan").textContent).toBe("412.3 GB3 paths3 hostscp-8e41c0d2until 15:32");
    const rows = within(screen.getByRole("table", { name: "Plan items" })).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell").map((c) => c.textContent))).toEqual([
      ["5e9a", "mccleary", "…/01J7QK2D-tr-5e9a/artifacts/ckpt", "96.4 GB", "archived 41d, checkpoint"],
      ["0a6d", "gpu1", "…/01J7MZ81-tr-0a6d/artifacts/ckpt", "74.0 GB", "archived 52d, checkpoint"],
      ["4d2e", "local", "…/01J7R1C9-tr-4d2e/pulled/ckpt", "242 GB", "archived 44d, pulled"],
      ["d1f4", "·", "…/01J7T3VE-tr-d1f4/artifacts/ckpt", "·", "⊘ used by 01J8E5WQ-tr-c7d4"],
      ["e2d5", "·", "…/sv/code/deepretro", "·", "⊘ protected"],
    ]);
    expect(rows.slice(3).map((r) => r.className)).toEqual(["refused", "refused"]);
  });

  test("owner preflight refusals remain outside the confirmation total", async () => {
    const plan = {
      ...CLEAN_PLAN,
      items: CLEAN_PLAN.items.slice(0, 1),
      total_bytes: 96_400_000_000,
      refused: [
        { path: "/host/alias/parent.pt", run_id: "parent", reason: "used by reader" },
        { path: "/host/unavailable.pt", run_id: "other", reason: "host check failed: unavailable" },
      ],
    };
    mockApi({ [PLAN]: plan });
    renderWithClient(<CleanPanel items={STORAGE_ITEMS} now={NOW} />);
    await dryRun();
    expect(screen.getByText("⊘ used by reader")).toBeTruthy();
    expect(screen.getByText("⊘ host check failed: unavailable")).toBeTruthy();
    fireEvent.click(button("apply"));
    const dialog = screen.getByRole("dialog", { name: "delete 96.4 GB" });
    expect(within(dialog).getByText("1 paths · 1 hosts · cp-8e41c0d2")).toBeTruthy();
  });

  test("kinds: a chip per artifact kind; pulled toggles include_pulled; days must be whole", async () => {
    const calls = mockApi({ [PLAN]: CLEAN_PLAN });
    renderWithClient(<CleanPanel items={STORAGE_ITEMS} now={NOW} />);
    expect(screen.getAllByRole("button", { pressed: true }).map((b) => b.textContent)).toEqual(["checkpoint", "pulled"]);
    fireEvent.click(button("predictions"));
    fireEvent.click(button("pulled"));
    const days = screen.getByLabelText("Days") as HTMLInputElement;
    fireEvent.change(days, { target: { value: "abc" } });
    expect([days.getAttribute("aria-invalid"), button("dry run").disabled]).toEqual(["true", true]);
    fireEvent.change(days, { target: { value: "7" } });
    await dryRun();
    expect(calls[0]?.body).toMatchObject({ older_than_days: 7, kinds: ["checkpoint", "predictions"], include_pulled: false });
  });
});

describe("apply", () => {
  test("delete stays disabled until the typed number matches; apply sends the exact bytes", async () => {
    const calls = mockApi({ [PLAN]: CLEAN_PLAN, [APPLY]: CLEAN_RESULT });
    renderWithClient(<CleanPanel items={STORAGE_ITEMS} now={NOW} />);
    await dryRun();
    fireEvent.click(button("apply"));
    const dialog = screen.getByRole("dialog", { name: "delete 412.3 GB" });
    expect(within(dialog).getByText("3 paths · 3 hosts · cp-8e41c0d2")).toBeTruthy();
    const input = within(dialog).getByLabelText("Confirm size") as HTMLInputElement;
    const del = within(dialog).getByRole("button", { name: "delete" }) as HTMLButtonElement;
    for (const wrong of ["412", "412.30", "412.3 GB"]) {
      fireEvent.change(input, { target: { value: wrong } });
      expect([wrong, del.disabled]).toEqual([wrong, true]);
    }
    fireEvent.change(input, { target: { value: "412.3" } });
    expect(del.disabled).toBe(false);
    fireEvent.click(del);
    expect((await screen.findByRole("status")).textContent).toBe("✓ freed 409.8 GB · 2 deleted · 1 skipped");
    const applied = calls.find((c) => c.url === "/api/v1/storage/plans/cp-8e41c0d2/apply");
    expect(applied?.body).toMatchObject({ confirm_bytes: 412_300_000_000 });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByText("cp-8e41c0d2")).toBeNull();
  });

  test("the dialog's plan is frozen: no dry run while it is open, no apply while one is in flight", async () => {
    let release: () => void = () => {};
    let second = false;
    mockApi({
      [PLAN]: async () => {
        if (second) await new Promise<void>((done) => (release = done));
        second = true;
        return CLEAN_PLAN;
      },
    });
    renderWithClient(<CleanPanel items={STORAGE_ITEMS} now={NOW} />);
    await dryRun();
    fireEvent.click(button("apply"));
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(button("dry run").disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    fireEvent.click(button("dry run")); // the second dry run hangs until release()
    await waitFor(() => expect(button("apply").disabled).toBe(true));
    expect(button("apply").title).toBe("dry run in flight");
    release();
    await waitFor(() => expect(button("apply").disabled).toBe(false));
  });

  test("an expired plan disables apply", async () => {
    mockApi({ [PLAN]: CLEAN_PLAN });
    renderWithClient(<CleanPanel items={STORAGE_ITEMS} now={NOW + 7_200_000} />);
    await dryRun();
    expect([button("apply").disabled, button("apply").title]).toEqual([true, "plan expired: dry run again"]);
    expect(screen.getByLabelText("Plan").textContent).toContain("expired");
  });

  test("a refused apply shows the error and keeps the plan", async () => {
    mockApi({
      [PLAN]: CLEAN_PLAN,
      [APPLY]: new HttpReply(400, { error: "plan cp-8e41c0d2 expired; dry run again", type: "CleanRefusedError" }),
    });
    renderWithClient(<CleanPanel items={STORAGE_ITEMS} now={NOW} />);
    await dryRun();
    fireEvent.click(button("apply"));
    fireEvent.change(screen.getByLabelText("Confirm size"), { target: { value: "412.3" } });
    fireEvent.click(screen.getByRole("button", { name: "delete" }));
    expect((await screen.findByRole("alert")).textContent).toBe("plan cp-8e41c0d2 expired; dry run again");
    fireEvent.click(screen.getByRole("button", { name: "cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.getByText("cp-8e41c0d2")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/storage/cleanPanel.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/storage/CleanPanel'`.

- [ ] **Step 3: Write `CleanPanel.tsx`**

Create `ui/src/storage/CleanPanel.tsx`:

```tsx
/**
 * Storage panel d (phase 3 contract 1.9, spec 9): always plan first, then apply with the
 * exact byte total typed back. Only artifacts of archived, unstarred runs are ever in a
 * plan; the hub re-checks every item at delete time and skips what changed.
 */
import { type KeyboardEvent, useState } from "react";
import { api } from "../api/client";
import type { CleanPlan, CleanPolicy, CleanResult, StorageItem } from "../api/models";
import { STORAGE_EVENT_INVALIDATES } from "../api/queries";
import { fmtClock, shortId, tailPath } from "../pages/components/format";
import { ErrorBox } from "../pages/components/QueryState";
import { useAction } from "../pages/components/useAction";
import {
  artifactKinds,
  confirmMatches,
  confirmText,
  confirmUnit,
  defaultPolicy,
  fmtBytes3,
  planExpired,
  planFacts,
  resultLine,
} from "./model";

/** Plan rows shown before `+ N more`. */
export const PLAN_ROWS = 50;

export interface CleanPanelProps {
  items: StorageItem[];
  now: number;
}

function ConfirmDialog({
  plan,
  onCancel,
  onApplied,
}: {
  plan: CleanPlan;
  onCancel: () => void;
  onApplied: (result: CleanResult) => void;
}) {
  const [typed, setTyped] = useState("");
  const apply = useAction<CleanResult>({
    send: (_: void, opts) => api.applyClean(plan.plan_id, plan.total_bytes, opts),
    invalidate: STORAGE_EVENT_INVALIDATES,
    onSuccess: onApplied,
  });
  const facts = planFacts(plan);
  const ok = confirmMatches(typed, plan.total_bytes);
  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape" && !apply.pending) onCancel();
  };
  return (
    <div className="hx-confirm" onKeyDown={onKeyDown}>
      <div className="dlg" role="dialog" aria-modal="true" aria-labelledby="hx-confirm-h">
        <div className="dlg-h">
          <h2 id="hx-confirm-h">{`delete ${facts.total}`}</h2>
        </div>
        <div className="dlg-b">
          <div>{`${facts.paths} paths · ${facts.hosts} hosts · ${plan.plan_id}`}</div>
          <div className="row" title="Type the number shown to confirm">
            <span>type</span>
            <b className="p">{confirmText(plan.total_bytes)}</b>
            <input
              className="in"
              aria-label="Confirm size"
              value={typed}
              autoFocus
              onChange={(e) => setTyped(e.target.value)}
            />
            <span>{confirmUnit(plan.total_bytes)}</span>
          </div>
          {apply.error ? <ErrorBox error={apply.error} /> : null}
        </div>
        <div className="dlg-f">
          <span className="small">{plan.refused.length > 0 ? `${plan.refused.length} refused · kept` : ""}</span>
          <span className="sp" />
          <button type="button" className="btn" disabled={apply.pending} onClick={onCancel}>
            cancel
          </button>
          <button type="button" className="btn danger" disabled={!ok || apply.pending} onClick={() => apply.run()}>
            delete
          </button>
        </div>
      </div>
    </div>
  );
}

export function CleanPanel({ items, now }: CleanPanelProps) {
  const base = defaultPolicy();
  const [days, setDays] = useState(String(base.older_than_days));
  const [kinds, setKinds] = useState<string[]>(base.kinds);
  const [pulled, setPulled] = useState(base.include_pulled);
  const [plan, setPlan] = useState<CleanPlan | null>(null);
  // The plan the open dialog confirms, frozen when `apply` was clicked: no dry run may
  // replace it under a typed confirmation (the same total could hide other items).
  const [confirming, setConfirming] = useState<CleanPlan | null>(null);
  const [result, setResult] = useState<CleanResult | null>(null);
  const daysOk = /^\d+$/.test(days.trim());
  const choices = artifactKinds(items);

  const dry = useAction<CleanPlan, CleanPolicy>({
    send: (policy, opts) => api.planClean(policy, opts),
    onSuccess: (made) => {
      setPlan(made);
      setResult(null);
    },
  });
  const policy = (): CleanPolicy => ({
    ...base,
    older_than_days: Number(days.trim()),
    kinds: choices.filter((k) => kinds.includes(k)),
    include_pulled: pulled,
  });
  const toggle = (kind: string) => setKinds(kinds.includes(kind) ? kinds.filter((k) => k !== kind) : [...kinds, kind]);
  const expired = plan !== null && planExpired(plan, now);
  const facts = plan ? planFacts(plan) : null;
  const applyTitle =
    plan === null
      ? "dry run first"
      : expired
        ? "plan expired: dry run again"
        : dry.pending
          ? "dry run in flight"
          : "Delete the plan's items";

  return (
    <div>
      <div className="cleanbar">
        <span>older than</span>
        <input
          className="in"
          aria-label="Days"
          value={days}
          aria-invalid={!daysOk}
          onChange={(e) => setDays(e.target.value)}
        />
        <span>d</span>
        {choices.map((kind) => (
          <button key={kind} type="button" className="kc" aria-pressed={kinds.includes(kind)} onClick={() => toggle(kind)}>
            {kind}
          </button>
        ))}
        <button
          type="button"
          className="kc"
          aria-pressed={pulled}
          title="Copies under the hub's pulled/ folders"
          onClick={() => setPulled(!pulled)}
        >
          pulled
        </button>
        <span className="r">
          <button
            type="button"
            className="btn"
            disabled={!daysOk || dry.pending || confirming !== null}
            onClick={() => dry.run(policy())}
          >
            dry run
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={plan === null || expired || dry.pending}
            title={applyTitle}
            onClick={() => setConfirming(plan)}
          >
            apply
          </button>
        </span>
      </div>
      {dry.error ? <ErrorBox error={dry.error} /> : null}
      {plan && facts ? (
        <>
          <div className="planline" aria-label="Plan">
            <b>{facts.total}</b>
            <span>{`${facts.paths} paths`}</span>
            <span>{`${facts.hosts} hosts`}</span>
            <span className="p">{plan.plan_id}</span>
            <span className="small" title={plan.expires_at}>
              {expired ? "expired" : `until ${fmtClock(plan.expires_at)}`}
            </span>
          </div>
          <table className="tbl" aria-label="Plan items">
            <thead>
              <tr>
                <th>run</th>
                <th>host</th>
                <th>path</th>
                <th className="r">bytes</th>
                <th>reason</th>
              </tr>
            </thead>
            <tbody>
              {plan.items.slice(0, PLAN_ROWS).map((item) => (
                <tr key={`${item.host}:${item.path}`}>
                  <td className="p">{shortId(item.run_id)}</td>
                  <td>{item.host}</td>
                  <td className="path">
                    <span className="p" title={item.path}>
                      {tailPath(item.path)}
                    </span>
                  </td>
                  <td className="r">{fmtBytes3(item.bytes)}</td>
                  <td className="dim">{item.reason}</td>
                </tr>
              ))}
              {plan.items.length > PLAN_ROWS ? (
                <tr className="more">
                  <td colSpan={5}>{`+ ${plan.items.length - PLAN_ROWS} more`}</td>
                </tr>
              ) : null}
              {plan.refused.map((r) => (
                <tr key={`refused:${r.path}`} className="refused">
                  <td className="p">{shortId(r.run_id)}</td>
                  <td>·</td>
                  <td className="path">
                    <span className="p" title={r.path}>
                      {tailPath(r.path)}
                    </span>
                  </td>
                  <td className="r">·</td>
                  <td>{`⊘ ${r.reason}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      ) : result === null ? (
        <p className="small" style={{ marginTop: 18 }}>
          no plan
        </p>
      ) : null}
      {result ? (
        <p className="resline" role="status" title={result.skipped.map((s) => JSON.stringify(s)).join("\n") || undefined}>
          <span className="ok">✓</span> {resultLine(result)}
        </p>
      ) : null}
      {confirming ? (
        <ConfirmDialog
          plan={confirming}
          onCancel={() => setConfirming(null)}
          onApplied={(done) => {
            setConfirming(null);
            setPlan(null);
            setResult(done);
          }}
        />
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/storage && bun run typecheck`
Expected: `cleanPanel.test.tsx` 7 pass; the other storage files pass; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/storage/CleanPanel.tsx ui/test/storage/cleanPanel.test.tsx
git commit -m "feat(ui): storage clean with dry run, plan table, typed confirm and apply"
```

---

### Task 17: The Storage page and route `/storage`

**Files:**
- Create: `ui/src/pages/Storage.tsx`
- Modify: `ui/src/router.tsx` (doc comment, import, route, route tree)
- Create: `ui/test/pages/Storage.test.tsx`
- Modify: `ui/test/router.test.tsx` (the route list)

**Interfaces:**
- Consumes: Tasks 14–16; Task 3 `useMe`, `useStorage`; Task 2 `isAdmin`; `Figure`, `PageStyles`, `ErrorBox`, `Loading`, `Unbroken`, `useNow`, `fmtClock`.
- Produces: `StoragePage({ now? })`. A non-admin gets one line `403 · admin` and no `/storage` request. An admin gets the headline (`fmtBytes3(total) · fmtBytes3(estimate) cleanable` plus `archived, >30d`), a metaline (`N hosts`, the bytes per kind, unreachable hosts as `dgx ✗` with the error as tooltip, the report time), and panels a By project, b By host, c Largest (`20 of N`), d Clean. Router `storageRoute` (path `/storage`).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/Storage.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { screen, waitFor } from "@testing-library/react";
import { StoragePage } from "../../src/pages/Storage";
import { ME_ADMIN, ME_ALICE, NOW, STORAGE_REPORT } from "../api/phase3-fixtures";
import { mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(restoreFetch);

test("an admin: headline, metaline, and panels a-d", async () => {
  mockApi({ "GET /api/v1/auth/me": ME_ADMIN, "GET /api/v1/storage?remote=true": STORAGE_REPORT });
  renderWithClient(<StoragePage now={NOW} />);
  await waitFor(() =>
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("1.84 TB · 170 GB cleanable archived, >30d"),
  );
  expect([...document.querySelectorAll(".metaline > span")].map((s) => s.textContent)).toEqual([
    "4 hosts",
    "artifact 1.52 TB",
    "run 214 GB",
    "pulled 106 GB",
    "dgx ✗",
    "14:31",
  ]);
  expect(screen.getByText("dgx ✗").getAttribute("title")).toBe("HostUnavailableError: dgx is stale");
  expect(screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"))).toEqual([
    "a By project",
    "b By host",
    "c Largest",
    "d Clean",
  ]);
  expect(screen.getByText("7 of 7")).toBeTruthy();
});

test("a collaborator: 403 · admin, and no storage request", async () => {
  const calls = mockApi({ "GET /api/v1/auth/me": ME_ALICE });
  renderWithClient(<StoragePage now={NOW} />);
  expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("403 · admin");
  expect(calls.map((c) => c.url)).toEqual(["/api/v1/auth/me"]);
});
```

In `ui/test/router.test.tsx`, add `"/storage",` after `"/settings",` in the route list.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/Storage.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/pages/Storage'`.

- [ ] **Step 3: Write `Storage.tsx` and the route**

Create `ui/src/pages/Storage.tsx`:

```tsx
/**
 * `/storage` (admin; phase 3 contract 1.9, 10; mockups `shot-storage-*`): bytes by project
 * and host, local and remote, the largest items, and plan-first cleanup.
 */
import type { ReactNode } from "react";
import { isAdmin } from "../api/auth";
import { useMe, useStorage } from "../api/queries";
import { CleanPanel } from "../storage/CleanPanel";
import { LargestTable } from "../storage/LargestTable";
import { cleanableBytes, defaultPolicy, hostBars, kindLine, largest, projectBars, storageHeadline } from "../storage/model";
import { HostBars, ProjectBars } from "../storage/StorageBars";
import { StorageStyles } from "../storage/styles";
import { Figure } from "./components/Figure";
import { fmtClock } from "./components/format";
import { Unbroken } from "./components/Headline";
import { useNow } from "./components/HostsPanel";
import { AppLink, hrefs } from "./components/links";
import { ErrorBox, Loading } from "./components/QueryState";
import { PageStyles } from "./components/styles";

export interface StoragePageProps {
  /** Fixed clock (tests). */
  now?: number;
}

export function StoragePage({ now }: StoragePageProps = {}) {
  const me = useMe();
  const admin = isAdmin(me.data ?? null);
  const report = useStorage(undefined, true, admin);
  const ticking = useNow(60_000);
  const at = now ?? ticking;

  const frame = (body: ReactNode) => (
    <div className="page storage">
      <PageStyles />
      <StorageStyles />
      <p className="crumb">
        <AppLink href={hrefs.overview()}>All projects</AppLink>
        <span className="sep">/</span>
        storage
      </p>
      {body}
    </div>
  );

  if (me.error) return frame(<ErrorBox error={me.error} />);
  if (me.data === undefined) return frame(<Loading />);
  if (!admin) {
    return frame(
      <h1 className="headline" title="Storage needs the admin scope">
        403 · admin
      </h1>,
    );
  }
  if (report.error) return frame(<ErrorBox error={report.error} />);
  if (report.data === undefined) return frame(<Loading />);

  const data = report.data;
  const policy = defaultPolicy();
  const shown = largest(data.items);
  return frame(
    <>
      <h1 className="headline">
        <Unbroken text={storageHeadline(data, cleanableBytes(data.items, policy, at))} />{" "}
        <span className="then" title="Archived, unstarred runs that ended more than 30 days ago; the dry run decides">
          {`archived, >${policy.older_than_days}d`}
        </span>
      </h1>
      <p className="metaline">
        <span>{`${Object.keys(data.by_host).length} hosts`}</span>
        {kindLine(data).map((text) => (
          <span key={text}>{text}</span>
        ))}
        {data.errors.map((e) => (
          <span key={e.host} title={e.error}>{`${e.host} ✗`}</span>
        ))}
        <span title={data.generated_at}>{fmtClock(data.generated_at)}</span>
      </p>
      <div className="two-x">
        <Figure letter="a" title="By project" aside={String(Object.keys(data.by_project).length)}>
          <ProjectBars bars={projectBars(data)} />
        </Figure>
        <Figure letter="b" title="By host" aside={String(Object.keys(data.by_host).length)}>
          <HostBars bars={hostBars(data)} />
        </Figure>
      </div>
      <Figure letter="c" title="Largest" aside={`${shown.length} of ${data.items.length}`}>
        <LargestTable items={data.items} now={at} total={data.items.length} />
      </Figure>
      <Figure letter="d" title="Clean" aside="archived · unstarred · ended">
        <CleanPanel items={data.items} now={at} />
      </Figure>
    </>,
  );
}
```

(The page uses the `.two-x` grid already in `PageStyles`.)

In `ui/src/router.tsx`: add `` `/storage` Storage `` to the doc comment; add `import { StoragePage } from "./pages/Storage";`; after `settingsRoute`, add

```tsx
export const storageRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/storage",
  component: StoragePage,
});
```

and add `storageRoute,` to `rootRoute.addChildren([...])`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/pages/Storage.test.tsx test/storage test/router.test.tsx && bun run typecheck`
Expected: `Storage.test.tsx` 2 pass; the storage files and the router test pass; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/pages/Storage.tsx ui/src/router.tsx ui/test/pages/Storage.test.tsx ui/test/router.test.tsx
git commit -m "feat(ui): storage page at /storage for admins"
```

---

## Group 5: Lab notebook `/n/:project/:day` (Tasks 18–20)

The notebook (mockups `shot-notebook-*`, `shot-notebook-conflict-*`): left the days (`2026-10-04 · 3`, today on top even before its file exists), right the day's entries with `09:14 @alice` stamps, Markdown with run chips (`01J8…a1b2 ✓ 0.913`; an unknown id is `? 01J7…`), the weekly summary as one block, `+ entry` (append: never a conflict), and `edit` (whole-day replace on the hash the edit started from). A 409 shows `409 · changed by @sv 1m` with theirs and mine side by side, `use theirs` / `keep mine`. Chips come from `NotebookDay.runs` (the hub resolves them); the page never fetches runs itself.

### Task 18: Notebook model and Markdown with an inline renderer

**Files:**
- Create: `ui/src/notebook/model.ts`
- Modify: `ui/src/panels/Markdown.tsx` (`renderBlock` takes the inline renderer; export `renderMarkdown`)
- Create: `ui/test/notebook/model.test.ts`, `ui/test/panels/markdownInline.test.tsx`

**Interfaces:**
- Consumes: `parseNotes`, `NoteEntry` (`pages/components/Notes`, the `## <iso> — <author>` format of `fsutil.append_note_file`); `ApiError`; `shortId`, `fmtClock`, `isAgent`, `parseTime`; Task 1 `RunChip`, `NotebookDay`, `NotebookDayInfo`.
- Produces:
  - `notebook/model.ts`: `RUN_LINK` (contract regex, global); `type Segment`; `splitRunLinks(text)`; `parseDay(text)` (`parseNotes`, plus the free text before the first stamped entry as an entry without a stamp: a day saved as free text and then appended to keeps its text); `isDigest(entry)` (its first line names an ISO week, `2026-W40`); `interface ChipView { id; short; glyph; cls; primary; known; title }` and `chipView(id, chips)`; `authorLabel(author)` (`human:alice` → `@alice`); `stamp(at)` (`09:14`, `""` without a stamp); `runCount(text)`; `interface DiffRow { left; right; kind: "same" | "change" | "del" | "add" }` and `lineDiff(theirs, mine)`; `conflictOf(err)` (the `current` day of a 409 `NotebookConflictError`, else null); `withToday(days, today)` (`today` is the hub's date from `GET .../notebook/today`, contract 1.4, never the browser's).
  - `panels/Markdown.tsx`: `type InlineRenderer = (text: string, key: string) => ReactNode[]`; `renderMarkdown(src, inline = renderInline): ReactNode[]` (the panel uses it with the default).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/notebook/model.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import { ApiError } from "../../src/api/client";
import {
  authorLabel,
  chipView,
  conflictOf,
  isDigest,
  lineDiff,
  parseDay,
  runCount,
  splitRunLinks,
  stamp,
  withToday,
} from "../../src/notebook/model";
import { NOTEBOOK_DAY, NOTEBOOK_DAYS, NOTEBOOK_TEXT } from "../api/phase3-fixtures";

describe("text", () => {
  test("splitRunLinks cuts text around [[run:<id>]]; a malformed link stays text", () => {
    expect(splitRunLinks("see [[run:01J8-a1b2]] and [[run:r.2_x]]; not [[run:]] or [[run:-x]]")).toEqual([
      { kind: "text", text: "see " },
      { kind: "run", id: "01J8-a1b2" },
      { kind: "text", text: " and " },
      { kind: "run", id: "r.2_x" },
      { kind: "text", text: "; not [[run:]] or [[run:-x]]" },
    ]);
    expect(splitRunLinks("")).toEqual([]);
    expect(runCount(NOTEBOOK_TEXT)).toBe(3);
    expect(runCount("[[run:a]] [[run:a]] [[run:b]]")).toBe(2);
  });

  test("parseDay splits entries; the weekly summary is the entry whose first line names a week", () => {
    const entries = parseDay(NOTEBOOK_TEXT);
    expect(entries.map((e) => [stamp(e.at), authorLabel(e.author), isDigest(e)])).toEqual([
      ["09:00", "digest", true],
      ["09:14", "@alice", false],
      ["11:02", "@sv", false],
    ]);
    expect([authorLabel("agent:claude@alice"), authorLabel("human"), authorLabel("")]).toEqual(["agent:claude@alice", "human", ""]);
    expect(stamp("")).toBe("");
  });

  test("parseDay keeps free text written before the first stamped entry", () => {
    const day = "plan for today\n\n## 2026-10-04T09:14:00+00:00 — human:alice\n\nlater\n";
    expect(parseDay(day).map((e) => [e.at, e.author, e.text])).toEqual([
      ["", "", "plan for today"],
      ["2026-10-04T09:14:00+00:00", "human:alice", "later"],
    ]);
    expect(parseDay("only free text\n")).toEqual([{ at: "", author: "", text: "only free text" }]);
  });
});

describe("chips", () => {
  test("known runs show status glyph and primary; unknown ids a question mark", () => {
    expect(["01J8Z3K7-clf-a1b2", "01J8YX0M-tr-77fe", "01J7AAAA-old-0001", "nope-0000"].map((id) => chipView(id, NOTEBOOK_DAY.runs))).toEqual([
      {
        id: "01J8Z3K7-clf-a1b2",
        short: "01J8…a1b2",
        glyph: "✓",
        cls: "f",
        primary: "0.913",
        known: true,
        title: "01J8Z3K7-clf-a1b2 · finished · uspto50k-topk",
      },
      {
        id: "01J8YX0M-tr-77fe",
        short: "01J8…77fe",
        glyph: "✗",
        cls: "x",
        primary: null,
        known: true,
        title: "01J8YX0M-tr-77fe · failed · uspto50k-top1",
      },
      { id: "01J7AAAA-old-0001", short: "01J7…", glyph: "?", cls: "", primary: null, known: false, title: "unknown run 01J7AAAA-old-0001" },
      { id: "nope-0000", short: "nope…", glyph: "?", cls: "", primary: null, known: false, title: "unknown run nope-0000" },
    ]);
  });
});

describe("conflicts and days", () => {
  test("lineDiff pairs changed lines and keeps added and removed ones apart", () => {
    expect(lineDiff("a\nb\nc", "a\nx\nc")).toEqual([
      { left: "a", right: "a", kind: "same" },
      { left: "b", right: "x", kind: "change" },
      { left: "c", right: "c", kind: "same" },
    ]);
    expect(lineDiff("a\nb", "a\nb\nc")).toEqual([
      { left: "a", right: "a", kind: "same" },
      { left: "b", right: "b", kind: "same" },
      { left: null, right: "c", kind: "add" },
    ]);
    expect(lineDiff("a\nb\nc", "a")).toEqual([
      { left: "a", right: "a", kind: "same" },
      { left: "b", right: null, kind: "del" },
      { left: "c", right: null, kind: "del" },
    ]);
  });

  test("conflictOf reads the current day of a 409 only", () => {
    const body = { error: "changed since you opened it", type: "NotebookConflictError", current: NOTEBOOK_DAY };
    expect(conflictOf(ApiError.from(409, body))?.hash).toBe("sha256:9f2c41d07be3a5e8");
    expect(conflictOf(ApiError.from(400, body))).toBeNull();
    expect(conflictOf(ApiError.from(409, { error: "x", type: "NotebookConflictError" }))).toBeNull();
    expect(conflictOf(new Error("x"))).toBeNull();
  });

  test("today (the hub's date) is listed first when its file does not exist yet", () => {
    expect(withToday(NOTEBOOK_DAYS, "2026-10-04")).toEqual(NOTEBOOK_DAYS);
    expect(withToday(NOTEBOOK_DAYS, "2026-10-05").map((d) => [d.day, d.entries])).toEqual([
      ["2026-10-05", 0],
      ["2026-10-04", 3],
      ["2026-10-03", 5],
      ["2026-09-29", 1],
    ]);
  });
});
```

Create `ui/test/panels/markdownInline.test.tsx`:

```tsx
import { expect, test } from "bun:test";
import { render } from "@testing-library/react";
import { renderMarkdown } from "../../src/panels/Markdown";

test("renderMarkdown keeps blocks and hands every inline run of text to the given renderer", () => {
  const seen: string[] = [];
  const { container } = render(
    <div>
      {renderMarkdown("# Week\nline one\nline two\n\n- item", (text, key) => {
        seen.push(text);
        return [<b key={key}>{text.toUpperCase()}</b>];
      })}
    </div>,
  );
  expect(seen).toEqual(["Week", "line one", "line two", "item"]);
  expect([...container.querySelectorAll("b")].map((b) => b.textContent)).toEqual(["WEEK", "LINE ONE", "LINE TWO", "ITEM"]);
  expect(container.querySelector("br")).not.toBeNull();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/notebook/model.test.ts test/panels/markdownInline.test.tsx`
Expected: FAIL. `error: Cannot find module '../../src/notebook/model'`; `SyntaxError: Export named 'renderMarkdown' not found in module '.../src/panels/Markdown.tsx'`.

- [ ] **Step 3: Export `renderMarkdown`**

In `ui/src/panels/Markdown.tsx`, replace

```tsx
function renderBlock(b: Block, i: number): ReactNode {
  const k = String(i);
  switch (b.kind) {
    case "p":
      return (
        <p key={k} style={S.p}>
          {b.lines.flatMap((line, j) => {
            const inline = renderInline(line, `${k}.${j}`);
            return j === 0 ? inline : [<br key={`${k}.br${j}`} />, ...inline];
          })}
        </p>
      );
    case "h": {
      const Tag = (["h3", "h4", "h5"] as const)[b.level - 1];
      return (
        <Tag key={k} style={S.h}>
          {renderInline(b.text, k)}
        </Tag>
      );
    }
    case "ul":
    case "ol": {
      const Tag = b.kind;
      return (
        <Tag key={k} style={S.list}>
          {b.items.map((item, j) => (
            <li key={j}>{renderInline(item, `${k}.${j}`)}</li>
          ))}
        </Tag>
      );
    }
```

with

```tsx
/** Renders one run of inline text (bold, code, links…); the notebook adds run chips. */
export type InlineRenderer = (text: string, key: string) => ReactNode[];

function renderBlock(b: Block, i: number, inline: InlineRenderer): ReactNode {
  const k = String(i);
  switch (b.kind) {
    case "p":
      return (
        <p key={k} style={S.p}>
          {b.lines.flatMap((line, j) => {
            const nodes = inline(line, `${k}.${j}`);
            return j === 0 ? nodes : [<br key={`${k}.br${j}`} />, ...nodes];
          })}
        </p>
      );
    case "h": {
      const Tag = (["h3", "h4", "h5"] as const)[b.level - 1];
      return (
        <Tag key={k} style={S.h}>
          {inline(b.text, k)}
        </Tag>
      );
    }
    case "ul":
    case "ol": {
      const Tag = b.kind;
      return (
        <Tag key={k} style={S.list}>
          {b.items.map((item, j) => (
            <li key={j}>{inline(item, `${k}.${j}`)}</li>
          ))}
        </Tag>
      );
    }
```

Directly after the `renderBlock` function, insert:

```tsx

/** Markdown source as React blocks; `inline` renders each run of inline text. */
export function renderMarkdown(src: string, inline: InlineRenderer = renderInline): ReactNode[] {
  return parseBlocks(src).map((b, i) => renderBlock(b, i, inline));
}
```

In `MarkdownPanel`, replace `{parseBlocks(text).map(renderBlock)}` with `{renderMarkdown(text)}`.

- [ ] **Step 4: Write `notebook/model.ts`**

Create `ui/src/notebook/model.ts`:

```ts
/**
 * Notebook arithmetic (phase 3 contract 1.4): entries, `[[run:<id>]]` links and their
 * chips, the weekly-summary entry, a line diff for the 409 view, and the day list.
 */
import { ApiError } from "../api/client";
import type { NotebookDay, NotebookDayInfo, RunChip, RunStatus } from "../api/models";
import { fmtClock, isAgent, shortId } from "../pages/components/format";
import { type NoteEntry, parseNotes } from "../pages/components/Notes";

/** `hypothex.core.notebook.RUN_LINK`, global. */
export const RUN_LINK = /\[\[run:([A-Za-z0-9][A-Za-z0-9_.-]{0,79})\]\]/g;

export type Segment = { kind: "text"; text: string } | { kind: "run"; id: string };

/** Text and run links in order; a malformed link stays text. */
export function splitRunLinks(text: string): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(RUN_LINK)) {
    const at = m.index ?? 0;
    if (at > last) out.push({ kind: "text", text: text.slice(last, at) });
    out.push({ kind: "run", id: m[1] ?? "" });
    last = at + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}

/** Unique run ids linked in `text`. */
export function runCount(text: string): number {
  return new Set([...text.matchAll(RUN_LINK)].map((m) => m[1])).size;
}

const ENTRY_HEAD = /^## \S+ — .+$/m;

/**
 * The day's entries (`## <iso> — <author>` headers, as `fsutil.append_note_file` writes them).
 * Text before the first header (a day saved as free text, then appended to) comes first, as an
 * entry without a stamp: `parseNotes` alone drops it.
 */
export function parseDay(text: string): NoteEntry[] {
  const entries = parseNotes(text);
  const first = text.search(ENTRY_HEAD);
  const head = first > 0 ? text.slice(0, first).trim() : "";
  return head ? [{ at: "", author: "", text: head }, ...entries] : entries;
}

const WEEK = /\b\d{4}-W\d{2}\b/;

/** The weekly summary the hub saves: its first line names the ISO week (`**2026-W40** · ▲12 ✓9 …`). */
export function isDigest(entry: NoteEntry): boolean {
  const first = entry.text.split("\n").find((line) => line.trim() !== "") ?? "";
  return WEEK.test(first);
}

/** `human:alice` → `@alice`; agents and bare names as they are. */
export function authorLabel(author: string): string {
  return author.startsWith("human:") ? `@${author.slice("human:".length)}` : author;
}

/** `agent` or `human`, for the launcher dot. */
export function authorKind(author: string): "agent" | "human" {
  return isAgent(author) ? "agent" : "human";
}

/** `09:14` (UTC); `""` for an entry without a stamp. */
export function stamp(at: string): string {
  return at ? fmtClock(at) : "";
}

export interface ChipView {
  id: string;
  /** `01J8…a1b2`; an unknown run `01J7…`. */
  short: string;
  glyph: string;
  /** Glyph colour class: `f` finished, `x` failed/killed/lost, `r` running, `q` queued. */
  cls: "" | "f" | "x" | "r" | "q";
  /** The primary metric, 3 decimals; null when unscored. */
  primary: string | null;
  known: boolean;
  title: string;
}

const STATUS_GLYPH: Record<RunStatus, [string, ChipView["cls"]]> = {
  finished: ["✓", "f"],
  failed: ["✗", "x"],
  killed: ["⊘", "x"],
  lost: ["?", "x"],
  running: ["◉", "r"],
  queued: ["○", "q"],
};

/** How a `[[run:<id>]]` chip looks, from the hub's resolved chips. */
export function chipView(id: string, chips: readonly RunChip[]): ChipView {
  const chip = chips.find((c) => c.run_id === id);
  if (!chip || chip.status === null) {
    return { id, short: `${id.slice(0, 4)}…`, glyph: "?", cls: "", primary: null, known: false, title: `unknown run ${id}` };
  }
  const [glyph, cls] = STATUS_GLYPH[chip.status];
  return {
    id,
    short: `${id.slice(0, 4)}…${shortId(id)}`,
    glyph,
    cls,
    primary: chip.primary === null ? null : chip.primary.toFixed(3),
    known: true,
    title: `${id} · ${chip.status}${chip.task ? ` · ${chip.task}` : ""}`,
  };
}

export interface DiffRow {
  left: string | null;
  right: string | null;
  kind: "same" | "change" | "del" | "add";
}

/** Above this many line pairs the diff is not computed; every line shows as changed. */
const DIFF_CELLS = 4_000_000;

/** Side-by-side rows of `theirs` against `mine` (LCS over lines; a removed run next to an added run pairs up). */
export function lineDiff(theirs: string, mine: string): DiffRow[] {
  const a = theirs.split("\n");
  const b = mine.split("\n");
  if (a.length * b.length > DIFF_CELLS) {
    const n = Math.max(a.length, b.length);
    return Array.from({ length: n }, (_, i) => ({ left: a[i] ?? null, right: b[i] ?? null, kind: "change" as const }));
  }
  // lcs[i][j]: common lines of a[i..] and b[j..]
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      const row = lcs[i] as number[];
      row[j] = a[i] === b[j] ? (lcs[i + 1]?.[j + 1] ?? 0) + 1 : Math.max(lcs[i + 1]?.[j] ?? 0, row[j + 1] ?? 0);
    }
  }
  const ops: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length || j < b.length) {
    if (i < a.length && j < b.length && a[i] === b[j]) {
      ops.push({ left: a[i] ?? "", right: b[j] ?? "", kind: "same" });
      i++;
      j++;
    } else if (j < b.length && (i >= a.length || (lcs[i]?.[j + 1] ?? 0) >= (lcs[i + 1]?.[j] ?? 0))) {
      ops.push({ left: null, right: b[j] ?? "", kind: "add" });
      j++;
    } else {
      ops.push({ left: a[i] ?? "", right: null, kind: "del" });
      i++;
    }
  }
  // pair each run of removed lines with the run of added lines next to it
  const out: DiffRow[] = [];
  for (let k = 0; k < ops.length; ) {
    if ((ops[k] as DiffRow).kind === "same") {
      out.push(ops[k] as DiffRow);
      k++;
      continue;
    }
    const dels: string[] = [];
    const adds: string[] = [];
    while (k < ops.length && (ops[k] as DiffRow).kind !== "same") {
      const op = ops[k] as DiffRow;
      if (op.kind === "del") dels.push(op.left ?? "");
      else adds.push(op.right ?? "");
      k++;
    }
    const n = Math.max(dels.length, adds.length);
    for (let m = 0; m < n; m++) {
      const left = dels[m] ?? null;
      const right = adds[m] ?? null;
      out.push({ left, right, kind: left !== null && right !== null ? "change" : left !== null ? "del" : "add" });
    }
  }
  return out;
}

/** The day as it is now, from a 409 `NotebookConflictError`; null for any other error. */
export function conflictOf(err: unknown): NotebookDay | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null;
  const body = err.body as { current?: unknown } | null;
  const current = body?.current as Partial<NotebookDay> | undefined;
  if (!current || typeof current.text !== "string" || typeof current.hash !== "string") return null;
  return current as NotebookDay;
}

/**
 * The days, newest first, with `today` first (0 entries) when its file does not exist yet.
 * `today` is the hub's date (`GET .../notebook/today`), so the UI, `hx note` and the digest
 * agree on the day near midnight.
 */
export function withToday(days: readonly NotebookDayInfo[], today: string): NotebookDayInfo[] {
  if (days.some((d) => d.day === today)) return [...days];
  return [{ day: today, bytes: 0, entries: 0 }, ...days];
}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `bun test test/notebook/model.test.ts test/panels && bun run typecheck`
Expected: `model.test.ts` 7 pass, `markdownInline.test.tsx` 1 pass; `Markdown.test.tsx` (phase 1b) passes unchanged; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 6: Commit (repo root)**

```bash
git add ui/src/notebook/model.ts ui/src/panels/Markdown.tsx ui/test/notebook/model.test.ts ui/test/panels/markdownInline.test.tsx
git commit -m "feat(ui): notebook model for entries, run chips, digest blocks and line diffs"
```

---

### Task 19: One notebook day: entries, `+ entry`, edit, and the 409 view

**Files:**
- Create: `ui/src/notebook/styles.ts`
- Create: `ui/src/notebook/DayView.tsx`
- Create: `ui/test/notebook/dayView.test.tsx`

**Interfaces:**
- Consumes: Task 18; Task 4 `useNotebookEditor`; `api.appendNotebook`, `api.saveNotebook`, `NOTEBOOK_INVALIDATES`; `renderMarkdown`, `renderInline`; `AppLink`, `hrefs`; `useAction`, `ErrorBox`; `ageText` (Task 9).
- Produces: `NOTEBOOK_CSS`, `NotebookStyles()`; `DayView({ project, day, data, now })`. View: a header (`<day>`, `N entries · M runs`, `edit`), the entries (`.ent`, `.ent.dg` for the weekly summary) with `stamp` and author, Markdown with chips (known: a link to the run; unknown: a dashed `? 01J7…`), then `+ entry` (`aria-label="New entry"`, read-only while the entry is sent, so text typed then is never cleared away). Edit: a textarea (`aria-label="Day text"`, read-only while the save is in flight), `save`, `discard`; `save` sends the hash the edit started from (a live refresh during the edit does not move it). 409: `role="alert"` `409 · changed by @sv 1m` (or `changed 1m` without a seen editor), theirs and mine side by side, `use theirs` (drops my edit and reloads the day), `keep mine` (PUT my text on their hash).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/notebook/dayView.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { clearNotebookEditors, noteNotebookEditors } from "../../src/api/notebookEditors";
import type { NotebookDay } from "../../src/api/models";
import { DayView } from "../../src/notebook/DayView";
import { NOTEBOOK_DAY, NOW } from "../api/phase3-fixtures";
import { type Call, HttpReply, mockApi, renderWithClient, restoreFetch } from "../pages/helpers";

afterEach(() => {
  restoreFetch();
  act(() => clearNotebookEditors());
});

const DAY_URL = "/api/v1/projects/deepretro/notebook/2026-10-04";
const THEIRS: NotebookDay = {
  ...NOTEBOOK_DAY,
  text: `${NOTEBOOK_DAY.text}## 2026-10-04T14:31:00Z — human:sv\nFixed in 8f4cac4.\n`,
  hash: "sha256:0c1d2e3f4a5b6c7d",
  updated_at: "2026-10-04T14:31:00Z",
};
const view = (data: NotebookDay = NOTEBOOK_DAY) => (
  <DayView project="deepretro" day="2026-10-04" data={data} now={NOW} />
);

describe("view", () => {
  test("entries with stamps, authors and run chips; the weekly summary is one block", () => {
    mockApi({});
    const { container } = renderWithClient(view());
    expect(screen.getByText("3 entries · 3 runs")).toBeTruthy();
    const entries = [...container.querySelectorAll<HTMLElement>(".ent")];
    expect(entries.map((e) => [e.className, e.querySelector(".by")?.textContent])).toEqual([
      ["ent dg", "09:00digest"],
      ["ent", "09:14@alice"],
      ["ent", "11:02@sv"],
    ]);
    const chip = screen.getByRole("link", { name: "01J8…a1b2 ✓ 0.913" });
    expect([chip.getAttribute("href"), chip.getAttribute("title")]).toEqual([
      "/r/01J8Z3K7-clf-a1b2",
      "01J8Z3K7-clf-a1b2 · finished · uspto50k-topk",
    ]);
    expect(screen.getByRole("link", { name: "01J8…77fe ✗" })).toBeTruthy();
    expect(screen.getByTitle("unknown run 01J7AAAA-old-0001").textContent).toBe("?01J7…");
    expect(within(entries[0] as HTMLElement).getByText(/· ▲12 ✓9 ✗2 \?1 · 41\.2 GPU-h \$86\.5 ·/)).toBeTruthy();
    expect(within(entries[0] as HTMLElement).getByText("2026-W40").tagName).toBe("B");
  });

  test("+ entry appends and clears", async () => {
    const calls = mockApi({ [`POST ${DAY_URL}`]: NOTEBOOK_DAY });
    renderWithClient(view());
    const box = screen.getByLabelText("New entry") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "beam 10 holds on seed 4 [[run:01J8Z3K7-clf-a1b2]]" } });
    fireEvent.click(screen.getByRole("button", { name: "+ entry" }));
    await waitFor(() => expect(box.value).toBe(""));
    expect(calls[0]?.body).toMatchObject({ text: "beam 10 holds on seed 4 [[run:01J8Z3K7-clf-a1b2]]" });
    expect(Object.keys(calls[0]?.body as object).sort()).toEqual(["command_id", "text"]);
  });

  test("the box is read-only while the entry is sent, so nothing typed then is lost", async () => {
    let release = () => {};
    const held = new Promise<void>((r) => {
      release = r;
    });
    mockApi({
      [`POST ${DAY_URL}`]: async () => {
        await held;
        return NOTEBOOK_DAY;
      },
    });
    renderWithClient(view());
    const box = screen.getByLabelText("New entry") as HTMLTextAreaElement;
    fireEvent.change(box, { target: { value: "A" } });
    fireEvent.click(screen.getByRole("button", { name: "+ entry" }));
    await waitFor(() => expect(box.readOnly).toBe(true));
    fireEvent.change(box, { target: { value: "AB" } });
    expect(box.value).toBe("A");
    act(() => release());
    await waitFor(() => expect(box.value).toBe(""));
    expect(box.readOnly).toBe(false);
  });
});

describe("edit", () => {
  function Harness() {
    const [data, setData] = useState(NOTEBOOK_DAY);
    return (
      <>
        <button type="button" onClick={() => setData({ ...data, hash: "sha256:moved" })}>
          refresh
        </button>
        {view(data)}
      </>
    );
  }

  test("save replaces the day on the hash the edit started from, even after a live refresh", async () => {
    const calls = mockApi({ [`PUT ${DAY_URL}`]: { ...NOTEBOOK_DAY, text: "all new", hash: "sha256:new" } });
    renderWithClient(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "edit" }));
    const area = screen.getByLabelText("Day text") as HTMLTextAreaElement;
    expect(area.value).toBe(NOTEBOOK_DAY.text);
    fireEvent.change(area, { target: { value: "all new" } });
    fireEvent.click(screen.getByRole("button", { name: "refresh" }));
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() => expect(screen.queryByLabelText("Day text")).toBeNull());
    expect(calls[0]?.body).toMatchObject({ text: "all new", base_hash: "sha256:9f2c41d07be3a5e8" });
  });

  test("a 409 keeps my text, shows theirs, and keep mine saves on their hash", async () => {
    let n = 0;
    const calls = mockApi({
      [`PUT ${DAY_URL}`]: (_call: Call) =>
        ++n === 1
          ? new HttpReply(409, { error: "changed since you opened it", type: "NotebookConflictError", current: THEIRS })
          : { ...THEIRS, text: "mine", hash: "sha256:final" },
    });
    act(() =>
      noteNotebookEditors([
        {
          sequence: 9,
          type: "notebook.updated",
          project: "deepretro",
          run_id: null,
          payload: { project: "deepretro", day: "2026-10-04", author: "human:sv" },
          created_at: "2026-10-04T14:31:00Z",
        },
      ]),
    );
    renderWithClient(view());
    fireEvent.click(screen.getByRole("button", { name: "edit" }));
    fireEvent.change(screen.getByLabelText("Day text"), { target: { value: "mine" } });
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    const bar = await screen.findByRole("alert");
    expect(within(bar).getByText("changed by @sv 1m")).toBeTruthy();
    expect(within(screen.getByLabelText("theirs")).getByText("Fixed in 8f4cac4.")).toBeTruthy();
    expect(screen.getByLabelText("mine").textContent).toContain("mine");
    fireEvent.click(screen.getByRole("button", { name: "keep mine" }));
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]?.body).toMatchObject({ text: "mine", base_hash: "sha256:0c1d2e3f4a5b6c7d" });
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  test("use theirs drops my edit; without a seen editor the bar says only when", async () => {
    const calls = mockApi({
      [`PUT ${DAY_URL}`]: new HttpReply(409, { error: "changed", type: "NotebookConflictError", current: THEIRS }),
    });
    renderWithClient(view());
    fireEvent.click(screen.getByRole("button", { name: "edit" }));
    fireEvent.change(screen.getByLabelText("Day text"), { target: { value: "mine" } });
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    expect(within(await screen.findByRole("alert")).getByText("changed 1m")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "use theirs" }));
    await waitFor(() => expect(screen.queryByLabelText("Day text")).toBeNull());
    expect(screen.queryByRole("alert")).toBeNull();
    expect(calls).toHaveLength(1);
  });

  test("a day over 1 MB shows the hub's message", async () => {
    mockApi({ [`PUT ${DAY_URL}`]: new HttpReply(413, { error: "notebook day over 1 MB", type: "NotebookTooLargeError" }) });
    renderWithClient(view());
    fireEvent.click(screen.getByRole("button", { name: "edit" }));
    fireEvent.click(screen.getByRole("button", { name: "save" }));
    expect((await screen.findByText("notebook day over 1 MB")).getAttribute("role")).toBe("alert");
    expect(screen.getByLabelText("Day text")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/notebook/dayView.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/notebook/DayView'`.

- [ ] **Step 3: Write the styles and `DayView.tsx`**

Create `ui/src/notebook/styles.ts`:

```ts
/** Notebook CSS, from docs/mockups/phase3 (`shot-notebook-*`). Every selector starts with `.page.notebook`. */
import { createElement } from "react";

export const NOTEBOOK_CSS = `
.page.notebook .nb { display: grid; grid-template-columns: 210px minmax(0, 1fr); gap: 64px; margin-top: 48px; align-items: start; }
.page.notebook .days { list-style: none; margin: 0; padding: 0; font-size: 14px; font-variant-numeric: tabular-nums; }
.page.notebook .days a { display: flex; justify-content: space-between; padding: 7px 10px; text-decoration: none; color: var(--ink-2); border-left: 2px solid transparent; }
.page.notebook .days a[aria-current="page"] { color: var(--ink); font-weight: 600; border-left-color: var(--ink); background: var(--paper-2); }
.page.notebook .days a small { color: var(--ink-3); font-weight: 400; }
.page.notebook .nbh { display: flex; align-items: center; gap: 10px; padding-bottom: 12px; border-bottom: 1px solid var(--rule); }
.page.notebook .nbh .r { margin-left: auto; display: flex; gap: 8px; }
.page.notebook .ent { padding: 18px 0; border-bottom: 1px solid var(--rule-2); }
.page.notebook .ent .by { display: flex; gap: 12px; align-items: center; font-size: 12.5px; color: var(--ink-3); margin-bottom: 6px; font-variant-numeric: tabular-nums; }
.page.notebook .ent .tx { font: 400 17px/1.6 var(--serif); color: var(--ink-2); max-width: 46em; }
.page.notebook .ent.dg .tx { margin-top: 6px; padding: 4px 0 4px 18px; border-left: 2px solid var(--ink); font-family: var(--sans); font-size: 15px; font-variant-numeric: tabular-nums; }
.page.notebook .chip { display: inline-flex; align-items: center; gap: 5px; height: 22px; padding: 0 7px; border: 1px solid var(--rule); border-radius: 4px; font: 400 12.5px var(--sans); color: var(--ink); text-decoration: none; vertical-align: 2px; font-variant-numeric: tabular-nums; }
.page.notebook .chip .id { font-family: var(--mono); font-size: 12px; }
.page.notebook .chip .g { font-weight: 600; }
.page.notebook .chip .g.f { color: var(--best); }
.page.notebook .chip .g.x { color: var(--fail); }
.page.notebook .chip .g.r { color: var(--agent); }
.page.notebook .chip.unk { color: var(--ink-3); border-style: dashed; }
.page.notebook textarea { width: 100%; border: 1px solid var(--rule); border-radius: 6px; background: transparent; padding: 8px 10px; font: 400 14px/1.5 var(--sans); color: var(--ink); resize: vertical; }
.page.notebook .addbox { margin-top: 22px; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; align-items: end; }
.page.notebook .addbox textarea { min-height: 64px; }
.page.notebook .ed textarea { min-height: 420px; font-family: var(--mono); font-size: 13px; margin-top: 16px; }
.page.notebook .ed .row { margin-top: 10px; }
.page.notebook .cfl { display: flex; gap: 16px; align-items: center; padding: 12px 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); font-size: 14px; color: var(--ink-2); margin-top: 18px; }
.page.notebook .cfl b { color: var(--fail); font-weight: 650; }
.page.notebook .cfl .r { margin-left: auto; display: flex; gap: 8px; }
.page.notebook .diff { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-top: 18px; }
.page.notebook .diff h4 { margin: 0 0 8px; font: 500 12.5px var(--sans); color: var(--ink-3); }
.page.notebook .diff pre { margin: 0; padding: 10px 0; background: var(--paper-2); border-radius: 6px; font: 400 12.5px/1.65 var(--mono); color: var(--ink-2); white-space: pre-wrap; word-break: break-word; }
.page.notebook .diff pre span { display: block; padding: 0 12px; min-height: 1.65em; }
.page.notebook .diff pre span.ch { background: color-mix(in srgb, var(--human) 16%, transparent); color: var(--ink); box-shadow: inset 2px 0 0 var(--human); }
.page.notebook .diff pre span.ad { background: var(--best-wash); color: var(--ink); box-shadow: inset 2px 0 0 var(--best); }
@media (max-width: 1100px) { .page.notebook .nb { grid-template-columns: 1fr; gap: 32px; } }
`;

/** Inject the notebook CSS. */
export function NotebookStyles() {
  return createElement("style", { "data-hx": "notebook" }, NOTEBOOK_CSS);
}
```

Create `ui/src/notebook/DayView.tsx`:

```tsx
/**
 * One notebook day (phase 3 contract 1.4, 3; mockups `shot-notebook-*`): entries with run
 * chips, `+ entry` (append, never a conflict), and whole-day edit with the 409 view.
 *
 * An edit saves on the hash the day had when the edit started, so a live refresh during
 * the edit cannot turn someone else's change into a silent overwrite.
 */
import { useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { api } from "../api/client";
import type { NotebookDay, RunChip } from "../api/models";
import { useNotebookEditor } from "../api/notebookEditors";
import { NOTEBOOK_INVALIDATES } from "../api/queries";
import { renderInline, renderMarkdown } from "../panels/Markdown";
import { AppLink, hrefs } from "../pages/components/links";
import { ErrorBox } from "../pages/components/QueryState";
import { useAction } from "../pages/components/useAction";
import { ageText } from "../settings/model";
import {
  authorKind,
  authorLabel,
  chipView,
  conflictOf,
  isDigest,
  lineDiff,
  parseDay,
  runCount,
  splitRunLinks,
  stamp,
} from "./model";

function Chip({ id, chips }: { id: string; chips: readonly RunChip[] }) {
  const v = chipView(id, chips);
  if (!v.known) {
    return (
      <span className="chip unk" title={v.title}>
        <span className="g">?</span>
        <span className="id">{v.short}</span>
      </span>
    );
  }
  return (
    <AppLink className="chip" href={hrefs.run(v.id)} title={v.title}>
      <span className="id">{v.short}</span>
      <span className={`g ${v.cls}`}>{v.glyph}</span>
      {v.primary !== null ? <span>{v.primary}</span> : null}
    </AppLink>
  );
}

/** Inline Markdown with `[[run:<id>]]` turned into chips. */
function withChips(chips: readonly RunChip[]) {
  return (text: string, key: string): ReactNode[] =>
    splitRunLinks(text).flatMap((seg, i) =>
      seg.kind === "run" ? [<Chip key={`${key}.c${i}`} id={seg.id} chips={chips} />] : renderInline(seg.text, `${key}.t${i}`),
    );
}

export interface DayViewProps {
  project: string;
  day: string;
  data: NotebookDay;
  now: number;
}

interface Editing {
  text: string;
  /** The day's hash when the edit started. */
  base: string;
}

export function DayView({ project, day, data, now }: DayViewProps) {
  const qc = useQueryClient();
  const editor = useNotebookEditor(project, day);
  const [entry, setEntry] = useState("");
  const [editing, setEditing] = useState<Editing | null>(null);
  const [dropped, setDropped] = useState<string | null>(null);

  const append = useAction<NotebookDay, string>({
    send: (text, opts) => api.appendNotebook(project, day, text, opts),
    invalidate: NOTEBOOK_INVALIDATES,
    onSuccess: () => setEntry(""),
  });
  const save = useAction<NotebookDay, Editing>({
    send: (e, opts) => api.saveNotebook(project, day, e.text, e.base, opts),
    invalidate: NOTEBOOK_INVALIDATES,
    onSuccess: () => setEditing(null),
  });

  const current = conflictOf(save.error);
  const conflict = editing !== null && current !== null && current.hash !== dropped ? current : null;
  const entries = parseDay(data.text);
  const inline = withChips(data.runs);

  if (editing !== null) {
    const rows = conflict ? lineDiff(conflict.text, editing.text) : [];
    const who = editor && editor.day === day ? `changed by ${authorLabel(editor.author)}` : "changed";
    const age = conflict?.updated_at ? ` ${ageText(conflict.updated_at, now)}` : "";
    return (
      <div className="ed">
        <div className="nbh">
          <b>{day}</b>
          <span className="small">editing</span>
        </div>
        {conflict ? (
          <>
            <div className="cfl" role="alert">
              <b>409</b>
              <span>{`${who}${age}`}</span>
              <span className="small">your text is kept</span>
              <span className="r">
                <button
                  type="button"
                  className="btn"
                  onClick={() => {
                    setDropped(conflict.hash);
                    setEditing(null);
                    for (const queryKey of NOTEBOOK_INVALIDATES) void qc.invalidateQueries({ queryKey });
                  }}
                >
                  use theirs
                </button>
                <button
                  type="button"
                  className="btn primary"
                  disabled={save.pending}
                  onClick={() => save.run({ text: editing.text, base: conflict.hash })}
                >
                  keep mine
                </button>
              </span>
            </div>
            <div className="diff">
              <div>
                <h4>theirs</h4>
                <pre aria-label="theirs">
                  {rows.map((r, i) => (
                    <span key={i} className={r.kind === "change" || r.kind === "del" ? "ch" : undefined}>
                      {r.left ?? ""}
                    </span>
                  ))}
                </pre>
              </div>
              <div>
                <h4>mine</h4>
                <pre aria-label="mine">
                  {rows.map((r, i) => (
                    <span key={i} className={r.kind === "change" || r.kind === "add" ? "ad" : undefined}>
                      {r.right ?? ""}
                    </span>
                  ))}
                </pre>
              </div>
            </div>
          </>
        ) : null}
        <textarea
          aria-label="Day text"
          value={editing.text}
          readOnly={save.pending}
          onChange={(e) => {
            // read-only while the save is in flight: success closes the editor, so text
            // typed meanwhile would be lost
            if (!save.pending) setEditing({ ...editing, text: e.target.value });
          }}
        />
        <div className="row">
          {conflict ? null : (
            <button type="button" className="btn primary" disabled={save.pending} onClick={() => save.run(editing)}>
              save
            </button>
          )}
          <button type="button" className="btn" disabled={save.pending} onClick={() => setEditing(null)}>
            discard
          </button>
        </div>
        {save.error && !conflict ? <ErrorBox error={save.error} /> : null}
      </div>
    );
  }

  return (
    <div>
      <div className="nbh">
        <b>{day}</b>
        <span className="small">{`${entries.length} entries · ${runCount(data.text)} runs`}</span>
        <span className="r">
          <button
            type="button"
            className="btn"
            title="Edit the whole day"
            onClick={() => {
              setDropped(null);
              setEditing({ text: data.text, base: data.hash });
            }}
          >
            edit
          </button>
        </span>
      </div>
      {entries.length === 0 ? <p className="small">none</p> : null}
      {entries.map((e, i) => (
        <div key={`${e.at}-${i}`} className={isDigest(e) ? "ent dg" : "ent"}>
          <div className="by">
            {e.at ? <span title={e.at}>{stamp(e.at)}</span> : null}
            {e.author ? (
              <span className={`who ${authorKind(e.author)}`}>
                <i />
                {authorLabel(e.author)}
              </span>
            ) : null}
          </div>
          <div className="tx">{renderMarkdown(e.text, inline)}</div>
        </div>
      ))}
      <form
        className="addbox"
        onSubmit={(ev) => {
          ev.preventDefault();
          if (entry.trim() !== "") append.run(entry.trim());
        }}
      >
        <textarea
          aria-label="New entry"
          value={entry}
          placeholder="[[run:<id>]] links a run"
          readOnly={append.pending}
          onChange={(ev) => {
            // read-only while the entry is sent: success clears the box
            if (!append.pending) setEntry(ev.target.value);
          }}
        />
        <button type="submit" className="btn primary" disabled={append.pending || entry.trim() === ""}>
          + entry
        </button>
      </form>
      {append.error ? <ErrorBox error={append.error} /> : null}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/notebook && bun run typecheck`
Expected: `dayView.test.tsx` 7 pass, `model.test.ts` 7 pass; `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/notebook/styles.ts ui/src/notebook/DayView.tsx ui/test/notebook/dayView.test.tsx
git commit -m "feat(ui): notebook day with run chips, append, whole-day edit and the 409 view"
```

---

### Task 20: The Notebook page and routes `/n/$project`, `/n/$project/$day`

**Files:**
- Create: `ui/src/pages/Notebook.tsx`
- Modify: `ui/src/router.tsx` (doc comment, imports, two screens, two routes, route tree)
- Create: `ui/test/pages/Notebook.test.tsx`
- Modify: `ui/test/router.test.tsx` (the route list; one new test)

**Interfaces:**
- Consumes: Tasks 18–19; Task 3 `useNotebookDays`, `useNotebookDay`; `AppLink`, `hrefs`; `PageStyles`, `ErrorBox`, `Loading`, `Unbroken`, `useNow`, `fmtClock`.
- Produces: `NotebookPage({ project, day?, now? })`: crumb `<project> / notebook`, headline `<project> · <day>`, metaline (`N days`, `M entries`, `edited HH:MM @x` from the open day), the day list (`aria-label="Days"`, newest first, today first with `0` when it has no file, the open day `aria-current="page"`), and `DayView` keyed by day. "Today" is the hub's date: the page reads `GET .../notebook/today` (backend Task 29: the hub answers the `NotebookDay` of `hub_today`, contract 1.4) and uses its `day`; it never computes a date in the browser. Without `day` it opens that day, and `DayView` writes to it by its explicit date. Router: `notebookRoute` (`/n/$project`) and `notebookDayRoute` (`/n/$project/$day`).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/Notebook.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { screen, waitFor, within } from "@testing-library/react";
import { NotebookPage } from "../../src/pages/Notebook";
import { NOTEBOOK_DAY, NOTEBOOK_DAYS, NOW } from "../api/phase3-fixtures";
import { mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(restoreFetch);

const BASE = "/api/v1/projects/deepretro/notebook";
const days = () =>
  within(screen.getByRole("list", { name: "Days" }))
    .getAllByRole("link")
    .map((a) => [a.textContent, a.getAttribute("href"), a.getAttribute("aria-current")]);

test("without a day: today opens; the list is newest first; the metaline sums it up", async () => {
  const calls = mockApi({ [`GET ${BASE}`]: NOTEBOOK_DAYS, [`GET ${BASE}/today`]: NOTEBOOK_DAY });
  renderWithClient(<NotebookPage project="deepretro" now={NOW} />);
  await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("deepretro · 2026-10-04"));
  expect(calls.some((c) => c.url === `${BASE}/2026-10-04`)).toBe(false); // the hub named the day
  expect(days()).toEqual([
    ["2026-10-043", "/n/deepretro/2026-10-04", "page"],
    ["2026-10-035", "/n/deepretro/2026-10-03", null],
    ["2026-09-291", "/n/deepretro/2026-09-29", null],
  ]);
  await waitFor(() =>
    expect([...document.querySelectorAll(".metaline span")].map((s) => s.textContent)).toEqual([
      "3 days",
      "9 entries",
      "edited 11:02 @sv",
    ]),
  );
});

test("today is the hub's date, not the browser's; without a file it is listed with 0 and opens empty", async () => {
  // the browser clock still says 2026-10-04 (UTC); the hub's zone has reached the 5th
  mockApi({
    [`GET ${BASE}`]: NOTEBOOK_DAYS,
    [`GET ${BASE}/today`]: { project: "deepretro", day: "2026-10-05", text: "", hash: "", runs: [], updated_at: null },
  });
  renderWithClient(<NotebookPage project="deepretro" now={NOW} />);
  await screen.findByText("none");
  expect(days()[0]).toEqual(["2026-10-050", "/n/deepretro/2026-10-05", "page"]);
  expect(screen.getByLabelText("New entry")).toBeTruthy();
});

test("a day from the URL opens that day", async () => {
  mockApi({
    [`GET ${BASE}`]: NOTEBOOK_DAYS,
    [`GET ${BASE}/today`]: NOTEBOOK_DAY,
    [`GET ${BASE}/2026-10-03`]: { ...NOTEBOOK_DAY, day: "2026-10-03" },
  });
  renderWithClient(<NotebookPage project="deepretro" day="2026-10-03" now={NOW} />);
  await waitFor(() => expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("deepretro · 2026-10-03"));
  expect(days()[1]?.[2]).toBe("page");
});
```

In `ui/test/router.test.tsx`, add `"/n/deepretro",` and `"/n/deepretro/2026-10-04",` after `"/storage",` in the route list, and add at the end of `describe("routes", ...)`:

```tsx
  test("/n/:project/:day reads both params", async () => {
    const { router } = renderApp("/n/deep%20retro/2026-10-04");
    await settled(router, "/n/$project/$day");
    expect(leaf(router)?.params).toEqual({ project: "deep retro", day: "2026-10-04" });
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/Notebook.test.tsx test/router.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/pages/Notebook'`; the router test fails (`/n/…` renders Not found) and `bun run typecheck` rejects `"/n/$project/$day"` as a route id until the route exists.

- [ ] **Step 3: Write `Notebook.tsx` and the routes**

Create `ui/src/pages/Notebook.tsx`:

```tsx
/**
 * `/n/:project` and `/n/:project/:day` (phase 3 contract 1.4, 10; mockups `shot-notebook-*`):
 * the project's lab notebook, one Markdown file per day on the hub.
 */
import type { ReactNode } from "react";
import { useNotebookDay, useNotebookDays } from "../api/queries";
import { DayView } from "../notebook/DayView";
import { authorLabel, parseDay, withToday } from "../notebook/model";
import { NotebookStyles } from "../notebook/styles";
import { fmtClock } from "./components/format";
import { Unbroken } from "./components/Headline";
import { useNow } from "./components/HostsPanel";
import { AppLink, hrefs } from "./components/links";
import { ErrorBox, Loading } from "./components/QueryState";
import { PageStyles } from "./components/styles";

export interface NotebookPageProps {
  project: string;
  /** `YYYY-MM-DD`; default the hub's today. */
  day?: string;
  /** Fixed clock (tests). */
  now?: number;
}

export function NotebookPage({ project, day, now }: NotebookPageProps) {
  const ticking = useNow(60_000);
  const at = now ?? ticking;
  // "today" is the hub's date (contract 1.4: DigestSettings.timezone, else the hub's zone);
  // the hub resolves it, so the UI, `hx note` and the digest write the same file
  const hubToday = useNotebookDay(project, "today");
  const today = hubToday.data?.day ?? null;
  const days = useNotebookDays(project);
  const page = useNotebookDay(project, day ?? "today"); // one query with hubToday when no day
  const active = day ?? today;
  const list = days.data ? (today ? withToday(days.data, today) : days.data) : null;
  const last = page.data ? parseDay(page.data.text).at(-1) : undefined;

  let body: ReactNode;
  if (page.error) body = <ErrorBox error={page.error} />;
  else if (page.data === undefined) body = <Loading />;
  else
    body = (
      <DayView key={`${project}/${page.data.day}`} project={project} day={page.data.day} data={page.data} now={at} />
    );

  return (
    <div className="page notebook">
      <PageStyles />
      <NotebookStyles />
      <p className="crumb">
        {project}
        <span className="sep">/</span>
        notebook
      </p>
      <h1 className="headline">
        <Unbroken text={`${project} · ${active ?? "·"}`} />
      </h1>
      <p className="metaline">
        {days.data ? <span>{`${days.data.length} days`}</span> : null}
        {days.data ? <span>{`${days.data.reduce((n, d) => n + d.entries, 0)} entries`}</span> : null}
        {page.data?.updated_at ? (
          <span title={page.data.updated_at}>
            {`edited ${fmtClock(page.data.updated_at)}${last?.author ? ` ${authorLabel(last.author)}` : ""}`}
          </span>
        ) : null}
      </p>
      {days.error ? <ErrorBox error={days.error} /> : null}
      <div className="nb">
        <ul className="days" aria-label="Days">
          {(list ?? []).map((d) => (
            <li key={d.day}>
              <AppLink href={hrefs.notebook(project, d.day)} aria-current={d.day === active ? "page" : undefined}>
                <span>{d.day}</span>
                <small>{d.entries}</small>
              </AppLink>
            </li>
          ))}
        </ul>
        <div>{body}</div>
      </div>
    </div>
  );
}
```

In `ui/src/router.tsx`: add `` `/n/$project[/$day]` Notebook `` to the doc comment; add `import { NotebookPage } from "./pages/Notebook";`; after `RunScreen`, add

```tsx
/** `/n/$project`: the notebook, today. */
function NotebookScreen(): ReactElement {
  const { project } = notebookRoute.useParams();
  return <NotebookPage project={project} />;
}

/** `/n/$project/$day`: one notebook day. */
function NotebookDayScreen(): ReactElement {
  const { project, day } = notebookDayRoute.useParams();
  return <NotebookPage project={project} day={day} />;
}
```

after `storageRoute`, add

```tsx
export const notebookRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/n/$project",
  component: NotebookScreen,
});

export const notebookDayRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/n/$project/$day",
  component: NotebookDayScreen,
});
```

and add `notebookRoute,` and `notebookDayRoute,` to `rootRoute.addChildren([...])`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/pages/Notebook.test.tsx test/notebook test/router.test.tsx test/shell && bun run typecheck`
Expected: `Notebook.test.tsx` 3 pass; the notebook, router and shell tests pass (the header now links to a real route); `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/pages/Notebook.tsx ui/src/router.tsx ui/test/pages/Notebook.test.tsx ui/test/router.test.tsx
git commit -m "feat(ui): notebook page at /n/:project and /n/:project/:day"
```

---

## Group 6: Task export, paper baselines, cleaned artifacts (Tasks 21–24)

The Task page gets `export ▾` in the leaderboard panel's title (mockup `shot-task-export-*`): LaTeX, Markdown or CSV, digits and noise, a six-line preview, Copy, and a `↓` Blob-download button, all from `GET /api/v1/tasks/{project}/{task}/export`. The leaderboard draws the board's paper baselines after a dashed rule (`◆ name`, value, `↗` source link, `≠v1` when the paper used another metric version, a hollow dashed diamond on the plot), never in the best band and never as best. The Run page strikes through cleaned artifacts (`✕ 2026-10-04 4.2 GB`, mockup `shot-run-*`).

### Task 21: The export menu

**Files:**
- Create: `ui/src/pages/components/exportFormats.ts`
- Create: `ui/src/pages/components/ExportMenu.tsx`
- Create: `ui/test/pages/exportMenu.test.tsx`

**Interfaces:**
- Consumes: Task 3 `useExportText` through authenticated `api.exportTask`; `ErrorBox`, `Loading`.
- Produces: `EXPORT_FORMATS` (`latex` LaTeX `tex`, `markdown` Markdown `md`, `csv` CSV `csv`); `NOISE_MODES`; `DIGITS` (0–6); `exportFilename(task, format)`; `previewLines(text, n = 6)`; `lineCount(text)`. `ExportMenu({ project, task })`: a button `export ▾` (`aria-expanded`); open, a `role="dialog"` `aria-label="Export"` popover with the format buttons (`aria-pressed`), `Digits` and `Noise` selects, a `Preview` of the first six lines, `N lines`, `Copy` (`Copied` after a write, `blocked` when the clipboard refuses; disabled while the preview still shows the previous options' text, `isPlaceholderData`) and the download button `↓ .tex` (a Blob of the authenticated current text, saved as `<task>.tex`; disabled on missing/placeholder/error data). Escape and a click outside close it; nothing is fetched while it is closed.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/exportMenu.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { ExportMenu } from "../../src/pages/components/ExportMenu";
import { exportFilename, lineCount, previewLines } from "../../src/pages/components/exportFormats";
import { mockApi, mockClipboard, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  restoreFetch();
  Reflect.deleteProperty(globalThis.navigator, "clipboard");
});

const BASE = "/api/v1/tasks/toy-classifier/toy-test/export";
const LATEX = [
  "% requires \\usepackage{booktabs}",
  "\\begin{tabular}{lrll}",
  "\\toprule",
  "Method & $n$ & accuracy $\\uparrow$ & macro\\_f1 $\\uparrow$ \\\\",
  "\\midrule",
  "\\textbf{RBF-kernel SVM} & 3 & \\textbf{0.922 ($\\diamond{\\times}3$)} [0.874, 0.953] & \\textbf{0.922} \\\\",
  "Baseline rf & 3 & 0.885 $\\pm$ 0.006 [0.830, 0.924] & 0.886 $\\pm$ 0.006 \\\\",
  "\\bottomrule",
  "\\end{tabular}",
  "",
].join("\n");
const MD = "| Method | n | accuracy ↑ |\n|---|--:|--:|\n| **RBF-kernel SVM** | 3 | **0.92 (◇×3)** |\n";

describe("helpers", () => {
  test("file names, preview lines and line counts", () => {
    expect(["latex", "markdown", "csv"].map((f) => exportFilename("toy-test", f as "latex"))).toEqual([
      "toy-test.tex",
      "toy-test.md",
      "toy-test.csv",
    ]);
    expect(previewLines(LATEX)).toHaveLength(6);
    expect(previewLines(LATEX)[0]).toBe("% requires \\usepackage{booktabs}");
    expect([lineCount(LATEX), lineCount(MD), lineCount("")]).toEqual([9, 3, 0]);
  });
});

describe("ExportMenu", () => {
  test("closed: nothing fetched; open: a LaTeX preview with digits 3 and noise both", async () => {
    const calls = mockApi({ [`GET ${BASE}?format=latex&noise=both&digits=3`]: LATEX });
    renderWithClient(<ExportMenu project="toy-classifier" task="toy-test" />);
    expect(calls).toEqual([]);
    fireEvent.click(screen.getByRole("button", { name: "export ▾" }));
    const menu = screen.getByRole("dialog", { name: "Export" });
    await waitFor(() => expect(within(menu).getByLabelText("Preview").textContent).toBe(LATEX.split("\n").slice(0, 6).join("\n")));
    expect(within(menu).getByText("9 lines")).toBeTruthy();
    expect(within(menu).getAllByRole("button", { pressed: true }).map((b) => b.textContent)).toEqual(["LaTeX"]);
    expect(screen.getByRole("button", { name: "export ▾" }).getAttribute("aria-expanded")).toBe("true");
  });

  test("format and digits refetch; download uses the authenticated text and file name", async () => {
    const calls = mockApi({
      [`GET ${BASE}?format=latex&noise=both&digits=3`]: LATEX,
      [`GET ${BASE}?format=markdown&noise=both&digits=3`]: MD,
      [`GET ${BASE}?format=markdown&noise=both&digits=2`]: MD,
      [`GET ${BASE}?format=markdown&noise=seed&digits=2`]: MD,
    });
    renderWithClient(<ExportMenu project="toy-classifier" task="toy-test" />);
    fireEvent.click(screen.getByRole("button", { name: "export ▾" }));
    fireEvent.click(screen.getByRole("button", { name: "Markdown" }));
    fireEvent.change(screen.getByLabelText("Digits"), { target: { value: "2" } });
    fireEvent.change(screen.getByLabelText("Noise"), { target: { value: "seed" } });
    await waitFor(() => expect(calls.at(-1)?.url).toBe(`${BASE}?format=markdown&noise=seed&digits=2`));
    await waitFor(() => expect((screen.getByRole("button", { name: "↓ .md" }) as HTMLButtonElement).disabled).toBe(false));
    const blobs: Blob[] = [];
    const downloads: string[][] = [];
    const revoked: string[] = [];
    const create = Object.getOwnPropertyDescriptor(URL, "createObjectURL");
    const revoke = Object.getOwnPropertyDescriptor(URL, "revokeObjectURL");
    const click = Object.getOwnPropertyDescriptor(HTMLAnchorElement.prototype, "click");
    Object.defineProperty(URL, "createObjectURL", { configurable: true, value: (blob: Blob) => { blobs.push(blob); return "blob:hx-export"; } });
    Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: (url: string) => revoked.push(url) });
    Object.defineProperty(HTMLAnchorElement.prototype, "click", { configurable: true, value: function (this: HTMLAnchorElement) { downloads.push([this.href, this.download]); } });
    try {
      const before = calls.length;
      fireEvent.click(screen.getByRole("button", { name: "↓ .md" }));
      expect(await blobs[0].text()).toBe(MD);
      expect(downloads).toEqual([["blob:hx-export", "toy-test.md"]]);
      expect(calls.length).toBe(before); // the click never navigates to a protected HTTP URL
      await waitFor(() => expect(revoked).toEqual(["blob:hx-export"]));
    } finally {
      for (const [target, key, descriptor] of [[URL, "createObjectURL", create], [URL, "revokeObjectURL", revoke], [HTMLAnchorElement.prototype, "click", click]] as const) {
        if (descriptor) Object.defineProperty(target, key, descriptor);
        else Reflect.deleteProperty(target, key);
      }
    }
  });

  test("Copy puts the whole text on the clipboard", async () => {
    mockApi({ [`GET ${BASE}?format=latex&noise=both&digits=3`]: LATEX });
    const written = mockClipboard();
    renderWithClient(<ExportMenu project="toy-classifier" task="toy-test" />);
    fireEvent.click(screen.getByRole("button", { name: "export ▾" }));
    await screen.findByLabelText("Preview");
    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => expect(written).toEqual([LATEX]));
    expect(screen.getByRole("button", { name: "Copied" })).toBeTruthy();
  });

  test("Copy waits for the new format: the previous text is never copied", async () => {
    let release: () => void = () => {};
    mockApi({
      [`GET ${BASE}?format=latex&noise=both&digits=3`]: LATEX,
      [`GET ${BASE}?format=csv&noise=both&digits=3`]: async () => {
        await new Promise<void>((done) => (release = done));
        return "method,n\n";
      },
    });
    const written = mockClipboard();
    renderWithClient(<ExportMenu project="toy-classifier" task="toy-test" />);
    fireEvent.click(screen.getByRole("button", { name: "export ▾" }));
    await screen.findByLabelText("Preview");
    fireEvent.click(screen.getByRole("button", { name: "CSV" }));
    const copyButton = () => screen.getByRole("button", { name: "Copy" }) as HTMLButtonElement;
    await waitFor(() => expect(copyButton().disabled).toBe(true)); // LaTeX still shown, CSV not here
    expect((screen.getByRole("button", { name: "↓ .csv" }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(copyButton());
    expect(written).toEqual([]);
    release();
    await waitFor(() => expect(copyButton().disabled).toBe(false));
    expect((screen.getByRole("button", { name: "↓ .csv" }) as HTMLButtonElement).disabled).toBe(false);
  });

  test("Escape and a click outside close the menu", () => {
    mockApi({ [`GET ${BASE}?format=latex&noise=both&digits=3`]: LATEX });
    renderWithClient(
      <>
        <p>outside</p>
        <ExportMenu project="toy-classifier" task="toy-test" />
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: "export ▾" }));
    fireEvent.keyDown(screen.getByRole("dialog", { name: "Export" }), { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "export ▾" }));
    fireEvent.mouseDown(screen.getByText("outside"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/exportMenu.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/pages/components/ExportMenu'`.

- [ ] **Step 3: Write `exportFormats.ts` and `ExportMenu.tsx`**

(The pure module is `exportFormats.ts`: a lower-case `exportMenu.ts` next to `ExportMenu.tsx` would clash on a case-insensitive file system, macOS by default, where `./ExportMenu` resolves to the `.ts` file.)

Create `ui/src/pages/components/exportFormats.ts`:

```ts
/** The export menu's pure parts (phase 3 contract 1.6): formats, file names, preview lines. */
import type { ExportFormat, NoiseMode } from "../../api/models";

export const EXPORT_FORMATS: readonly { format: ExportFormat; label: string; ext: string }[] = [
  { format: "latex", label: "LaTeX", ext: "tex" },
  { format: "markdown", label: "Markdown", ext: "md" },
  { format: "csv", label: "CSV", ext: "csv" },
];

/** `both`: `mean ± std` and the test-set CI; `seed`, `test`: one of them; `none`: means only. */
export const NOISE_MODES: readonly NoiseMode[] = ["both", "seed", "test", "none"];

export const DIGITS: readonly number[] = [0, 1, 2, 3, 4, 5, 6];

/** `toy-test.tex`, the name the hub's `Content-Disposition` uses too. */
export function exportFilename(task: string, format: ExportFormat): string {
  const ext = EXPORT_FORMATS.find((f) => f.format === format)?.ext ?? "txt";
  return `${task}.${ext}`;
}

/** The first `n` lines of an export. */
export function previewLines(text: string, n = 6): string[] {
  return text.split("\n").slice(0, n);
}

/** Lines in an export, not counting the newline at its end. */
export function lineCount(text: string): number {
  if (text === "") return 0;
  return text.replace(/\n$/, "").split("\n").length;
}
```

Create `ui/src/pages/components/ExportMenu.tsx`:

```tsx
/**
 * `export ▾` in the leaderboard panel's title (phase 3 contract 1.6, 10; mockup
 * `shot-task-export-*`): the task's leaderboard as LaTeX (booktabs), Markdown or CSV, with
 * `mean ± std`, the test-set CI, best in bold and the noise marks the hub adds. Copy takes
 * the whole text; `↓` downloads a Blob of the same authenticated current export.
 */
import { createElement, type KeyboardEvent, useEffect, useRef, useState } from "react";
import type { ExportFormat, ExportOptions, NoiseMode } from "../../api/models";
import { useExportText } from "../../api/queries";
import { DIGITS, EXPORT_FORMATS, NOISE_MODES, exportFilename, lineCount, previewLines } from "./exportFormats";
import { ErrorBox, Loading } from "./QueryState";

export const EXPORT_CSS = `
.hx-export { position: relative; display: inline-block; }
.hx-export .btn.s { height: 26px; padding: 0 9px; font-size: 12.5px; }
.hx-export .btn[aria-expanded="true"] { border-color: var(--ink); }
.hx-export .pop { position: absolute; right: 0; top: 32px; z-index: 10; width: 560px; max-width: calc(100vw - 48px); background: var(--paper); border: 1px solid var(--rule); border-radius: 9px; box-shadow: 0 18px 48px -20px rgba(10, 14, 20, .35); padding: 14px 16px; text-align: left; }
.hx-export .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; font-size: 13.5px; color: var(--ink-2); }
.hx-export .row + .row, .hx-export pre + .row { margin-top: 12px; }
.hx-export .row .sp { margin-left: auto; }
.hx-export .seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 6px; overflow: hidden; }
.hx-export .seg button { height: 30px; padding: 0 11px; border: 0; background: transparent; color: var(--ink-2); cursor: pointer; font-size: 13.5px; }
.hx-export .seg button + button { border-left: 1px solid var(--rule); }
.hx-export .seg button[aria-pressed="true"] { background: var(--ink); color: var(--paper); }
.hx-export select { height: 30px; border: 1px solid var(--rule); border-radius: 6px; background: transparent; color: var(--ink); font-size: 13.5px; }
.hx-export pre { margin: 12px 0 0; padding: 10px 12px; background: var(--paper-2); border-radius: 6px; font: 400 12px/1.6 var(--mono); color: var(--ink); white-space: pre; overflow: hidden; }
`;

type CopyState = "idle" | "copied" | "failed";

export interface ExportMenuProps {
  project: string;
  task: string;
}

export function ExportMenu({ project, task }: ExportMenuProps) {
  const [open, setOpen] = useState(false);
  const [format, setFormat] = useState<ExportFormat>("latex");
  const [digits, setDigits] = useState(3);
  const [noise, setNoise] = useState<NoiseMode>("both");
  const [copy, setCopy] = useState<CopyState>("idle");
  const box = useRef<HTMLSpanElement>(null);
  const opts: ExportOptions = { format, noise, digits };
  const text = useExportText(project, task, opts, open);
  // keepPreviousData shows the last format while the new one loads; that text must
  // never be copied as if it were the format now selected
  const stale = text.data === undefined || text.isPlaceholderData || text.isError;

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  useEffect(() => {
    if (copy === "idle") return;
    const timer = setTimeout(() => setCopy("idle"), 1500);
    return () => clearTimeout(timer);
  }, [copy]);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
    }
  };
  const doCopy = async () => {
    try {
      await navigator.clipboard.writeText(text.data ?? "");
      setCopy("copied");
    } catch {
      setCopy("failed");
    }
  };
  const doDownload = () => {
    if (stale || text.data === undefined) return;
    const mime = format === "csv" ? "text/csv;charset=utf-8" : "text/plain;charset=utf-8";
    const url = URL.createObjectURL(new Blob([text.data], { type: mime }));
    const link = document.createElement("a");
    link.href = url;
    link.download = exportFilename(task, format);
    document.body.append(link);
    try {
      link.click();
    } finally {
      link.remove();
      // Give the browser the current task to start the download before releasing it.
      setTimeout(() => URL.revokeObjectURL(url), 0);
    }
  };
  const ext = EXPORT_FORMATS.find((f) => f.format === format)?.ext ?? "txt";

  return (
    <span className="hx-export" ref={box}>
      {createElement("style", { "data-hx": "export" }, EXPORT_CSS)}
      <button
        type="button"
        className="btn s"
        aria-expanded={open}
        aria-haspopup="dialog"
        title="The leaderboard as LaTeX, Markdown or CSV"
        onClick={() => setOpen(!open)}
      >
        export ▾
      </button>
      {open ? (
        <div className="pop" role="dialog" aria-label="Export" onKeyDown={onKeyDown}>
          <div className="row">
            <div className="seg" role="group" aria-label="Format">
              {EXPORT_FORMATS.map((f) => (
                <button key={f.format} type="button" aria-pressed={format === f.format} onClick={() => setFormat(f.format)}>
                  {f.label}
                </button>
              ))}
            </div>
            <span>digits</span>
            <select aria-label="Digits" value={digits} onChange={(e) => setDigits(Number(e.target.value))}>
              {DIGITS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
            <span title="both: mean ± std and the test-set CI">noise</span>
            <select aria-label="Noise" value={noise} onChange={(e) => setNoise(e.target.value as NoiseMode)}>
              {NOISE_MODES.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
          {text.error ? (
            <ErrorBox error={text.error} />
          ) : text.data === undefined ? (
            <Loading />
          ) : (
            <pre aria-label="Preview">{previewLines(text.data).join("\n")}</pre>
          )}
          <div className="row">
            <span className="small">{text.data === undefined ? "" : `${lineCount(text.data)} lines`}</span>
            <span className="sp" />
            <button type="button" className="btn s" disabled={stale} onClick={doCopy}>
              {copy === "copied" ? "Copied" : copy === "failed" ? "blocked" : "Copy"}
            </button>
            <button type="button" className="btn s" disabled={stale} onClick={doDownload} title={exportFilename(task, format)}>
              {`↓ .${ext}`}
            </button>
          </div>
        </div>
      ) : null}
    </span>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/pages/exportMenu.test.tsx && bun run typecheck`
Expected: 6 pass, `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/pages/components/exportFormats.ts ui/src/pages/components/ExportMenu.tsx ui/test/pages/exportMenu.test.tsx
git commit -m "feat(ui): export menu with LaTeX, Markdown and CSV preview, copy and download"
```

---

### Task 22: Paper baselines in the leaderboard panel

**Files:**
- Modify: `ui/src/charts/Glyphs.tsx` (`BaselineMark`; `KeyGlyphKind` and `KeyGlyph` gain `baseline`)
- Modify: `ui/src/charts/charts.css` (the `.bdia` mark)
- Modify: `ui/src/panels/Leaderboard.tsx` (models import; helpers; x-domain values; baseline rows; key)
- Modify: `ui/src/panels/panels.css` (baseline rows)
- Create: `ui/test/panels/leaderboardBaselines.test.tsx`

**Interfaces:**
- Consumes: Task 1 `BaselineRow`; the leaderboard panel `meta` (`primary`, `metric_versions`; `baselines` is added by the Task page, Task 23).
- Produces: `BaselineMark({ cx, cy, r? })` (a hollow dashed diamond, class `bdia`); key glyph `baseline`; in `Leaderboard.tsx`: `baselineRows(meta): BaselineRow[]`, `baselineValue(b, key): number | null` (the value for a metric ref, else `primary` for the primary key), `baselineKey(baselines, meta): string | null` (the primary key from the papers' values when no run is scored; the panel then draws the baselines instead of `No scored runs yet`), `versionBadge(b, key, meta): string | null` (`≠v1` when `version_match[<metric>]` is not true). The panel draws baseline rows (`.frow.bl`, `data-baseline=<name>`, the first with class `first` for the dashed rule) after the groups: `◆ <name>`, the badge, `↗ <source>` linking `source_url` in a new tab, the value (`fmt.num`) with `paper` or `± std`, the mark on the shared x scale (baseline values widen the domain), the second metric, and `fmt.delta(value, best)` in the verdict column. A baseline is never the best row, never draws a band, and never gets a verdict glyph.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/panels/leaderboardBaselines.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, within } from "@testing-library/react";
import { MINUS } from "../../src/charts/Scale";
import type { PanelResult } from "../../src/panels/index";
import {
  Leaderboard,
  baselineKey,
  baselineRows,
  baselineValue,
  versionBadge,
  type LeaderboardRowJson,
} from "../../src/panels/Leaderboard";
import { BASELINES } from "../api/phase3-fixtures";

afterEach(cleanup);

const stat = (mean: number, std = 0, n = 3) => ({ mean, std, n, ci_low: null, ci_high: null });
const base = {
  run_ids: ["r1", "r2", "r3"],
  latest_run_id: "r3",
  hypothesis: "h",
  commit: "2bbf5a3",
  n: 3,
  single_seed: false,
  identical_seeds: false,
  vs_best: null,
  created_by: ["human"],
  usage: null,
};
const SVM: LeaderboardRowJson = {
  ...base,
  group_id: "6f71aa00@8f4cac4",
  label: "RBF-kernel SVM",
  scores: { "accuracy/value": stat(0.922222), "macro_f1/value": stat(0.9225) },
  primary: stat(0.922222),
  seed_values: { "accuracy/value": [0.922222, 0.922222, 0.922222] },
  identical_seeds: true,
  test_interval: { lo: 0.874, hi: 0.953, method: "wilson", n: 180 },
};
const RF: LeaderboardRowJson = {
  ...base,
  group_id: "ef4f0000@2bbf5a3",
  label: "Baseline rf",
  scores: { "accuracy/value": stat(0.885185, 0.006415), "macro_f1/value": stat(0.8855, 0.006) },
  primary: stat(0.885185, 0.006415),
  seed_values: { "accuracy/value": [0.877778, 0.888889, 0.888889] },
  test_interval: { lo: 0.83, hi: 0.924, method: "wilson", n: 180 },
  vs_best: { delta: -0.037037, p: 0.146, fixed: 9, broken: 3, test: "sign", examples_needed: 250 },
};
const META = { primary: "accuracy", metric_versions: { accuracy: "v1", macro_f1: "v1" } };
const board = (meta: Record<string, unknown>): PanelResult => ({
  type: "leaderboard",
  title: "All ideas",
  rows: [SVM, RF] as unknown as Record<string, unknown>[],
  meta,
});

describe("helpers", () => {
  test("baselineRows reads meta.baselines; baselineValue and versionBadge per metric", () => {
    expect(baselineRows({ ...META, baselines: BASELINES }).map((b) => b.name)).toEqual(["sklearn SVC", "TabPFN"]);
    expect([baselineRows({}), baselineRows({ baselines: "x" })]).toEqual([[], []]);
    const [svc, pfn] = BASELINES as [(typeof BASELINES)[0], (typeof BASELINES)[0]];
    expect([baselineValue(svc, "accuracy/value"), baselineValue(svc, "macro_f1/value"), baselineValue(pfn, "macro_f1/value")]).toEqual([
      0.91, 0.905, null,
    ]);
    expect([versionBadge(svc, "accuracy/value", META), versionBadge(pfn, "accuracy/value", META)]).toEqual([null, "≠v1"]);
    expect(versionBadge(pfn, "accuracy/value", {})).toBe("≠");
    expect([baselineKey(BASELINES, META), baselineKey([], META)]).toEqual(["accuracy/value", null]);
  });
});

describe("panel", () => {
  test("baseline rows after a dashed rule: name, badge, source, value, second metric, delta", () => {
    const { container } = render(<Leaderboard result={board({ ...META, baselines: BASELINES })} />);
    const rows = [...container.querySelectorAll<HTMLElement>(".frow.bl")];
    expect(rows.map((r) => r.className)).toEqual(["frow bl first", "frow bl"]);
    expect(rows.map((r) => r.querySelector(".nm")?.textContent)).toEqual(["◆ sklearn SVC", "◆ TabPFN≠v1"]);
    expect(rows.map((r) => [r.querySelector(".big")?.textContent, r.querySelector(".sd")?.textContent])).toEqual([
      ["0.9100", "paper"],
      ["0.9300", "± 0.0040"],
    ]);
    expect(rows.map((r) => r.querySelector(".f1")?.textContent)).toEqual(["0.9050", ""]);
    expect(rows.map((r) => r.querySelector(".vd")?.textContent)).toEqual([`${MINUS}0.012`, "+0.008"]);
    const link = within(rows[0] as HTMLElement).getByRole("link", { name: "↗ arXiv:2403.12345" });
    expect([link.getAttribute("href"), link.getAttribute("target"), link.getAttribute("rel")]).toEqual([
      "https://arxiv.org/abs/2403.12345",
      "_blank",
      "noreferrer noopener",
    ]);
    expect(within(rows[1] as HTMLElement).getByTitle("Published under another accuracy version than v1").textContent).toBe("≠v1");
  });

  test("a baseline above every group is never best and draws no band or verdict glyph", () => {
    const { container } = render(<Leaderboard result={board({ ...META, baselines: BASELINES })} />);
    const groups = [...container.querySelectorAll<HTMLElement>(".frow[data-row]")];
    expect(groups.map((r) => r.querySelector(".vd")?.textContent)).toEqual(["best", `${MINUS}0.037p 0.15`]);
    const pfn = container.querySelector<HTMLElement>('.frow.bl[data-baseline="TabPFN"]') as HTMLElement;
    expect([pfn.querySelectorAll("path.bdia").length, pfn.querySelectorAll(".vg").length]).toEqual([1, 0]);
    // the band behind the baseline row is the best group's, not a band of its own
    expect(pfn.querySelectorAll("rect.band").length).toBeLessThanOrEqual(1);
    expect(container.querySelector('[aria-label="Key"] [data-glyph="baseline"]')).not.toBeNull();
  });

  test("baseline values widen the shared x scale", () => {
    const { container } = render(<Leaderboard result={board({ ...META, baselines: BASELINES })} />);
    const mark = container.querySelector<SVGPathElement>('.frow.bl[data-baseline="TabPFN"] path.bdia');
    const width = Number(container.querySelector('.frow.bl[data-baseline="TabPFN"] svg')?.getAttribute("width"));
    const x = Number(/^M([\d.]+)/.exec(mark?.getAttribute("d") ?? "")?.[1]);
    expect(x).toBeGreaterThan(0);
    expect(x).toBeLessThan(width);
  });

  test("no baselines: no baseline rows and no key entry", () => {
    const { container } = render(<Leaderboard result={board(META)} />);
    expect(container.querySelectorAll(".frow.bl")).toHaveLength(0);
    expect(container.querySelector('[data-glyph="baseline"]')).toBeNull();
  });

  test("papers but no scored run yet: the baselines still show", () => {
    const { container } = render(<Leaderboard result={{ ...board({ ...META, baselines: BASELINES }), rows: [] }} />);
    expect(container.querySelector(".panel-empty")).toBeNull();
    const rows = [...container.querySelectorAll<HTMLElement>(".frow.bl")];
    expect(rows.map((r) => r.dataset.baseline)).toEqual(["sklearn SVC", "TabPFN"]);
    expect(rows.map((r) => r.querySelector(".big")?.textContent?.slice(0, 4))).toEqual(["0.91", "0.93"]);
    expect(rows.map((r) => r.querySelector(".vd")?.textContent)).toEqual(["—", "—"]);
    cleanup();
    const none = render(<Leaderboard result={{ ...board(META), rows: [] }} />);
    expect(none.container.querySelector(".panel-empty")?.textContent).toBe("No scored runs yet");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/panels/leaderboardBaselines.test.tsx`
Expected: FAIL: `SyntaxError: Export named 'baselineRows' not found in module '.../src/panels/Leaderboard.tsx'` (bun names one of the missing exports).

- [ ] **Step 3: Add the glyph**

In `ui/src/charts/Glyphs.tsx`, directly after the `Diamond` function, insert:

```tsx

/** A published (paper) result: a hollow diamond with a dashed edge, never filled, never best. */
export function BaselineMark({ cx, cy, r = 5.5 }: { cx: number; cy: number; r?: number }): ReactElement {
  return <path className="bdia" d={diamondPath(cx, cy, r)} />;
}
```

Replace

```tsx
  | "spike"
  | "killed";
```

with

```tsx
  | "spike"
  | "killed"
  | "baseline";
```

and in `KeyGlyph`, replace

```tsx
    case "killed":
      return box(12, <KillMark x={6} y={6} r={4} />);
```

with

```tsx
    case "killed":
      return box(12, <KillMark x={6} y={6} r={4} />);
    case "baseline":
      return box(12, <BaselineMark cx={6} cy={6} r={4.5} />);
```

Append to `ui/src/charts/charts.css`:

```css
/* paper baselines (phase 3): hollow, dashed, never the best colour */
.hx-chart .bdia { fill: var(--paper); stroke: var(--ink-2); stroke-width: 1.5; stroke-dasharray: 2 1.5; }
```

- [ ] **Step 4: Draw baseline rows**

In `ui/src/panels/Leaderboard.tsx` (as left by phase 2 Task 24), replace

```tsx
import {
  BestBand,
  IdenticalSeeds,
```

with

```tsx
import {
  BaselineMark,
  BestBand,
  IdenticalSeeds,
```

and replace

```tsx
import type { CostTotals, LeaderboardRow, NoiseInterval, Stats, UsageTotals, VersusBest } from "../api/models";
```

with

```tsx
import type {
  BaselineRow,
  CostTotals,
  LeaderboardRow,
  NoiseInterval,
  Stats,
  UsageTotals,
  VersusBest,
} from "../api/models";
```

Directly above `/** Draw a \`leaderboard\` panel result. */`, insert:

```tsx
/** Height of a baseline row's plot (a baseline has one mark, no seeds or whisker). */
export const BL_H = 56;

/** `meta.baselines` (the Task page adds the board's), or none. */
export function baselineRows(meta: Record<string, unknown> | undefined): BaselineRow[] {
  const raw = meta?.baselines;
  return Array.isArray(raw) ? (raw as BaselineRow[]) : [];
}

/** A baseline's value for a score key (`accuracy/value`); null when the paper did not report it. */
export function baselineValue(b: BaselineRow, key: string): number | null {
  const v = b.values[key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** With no scored run yet, the primary score key from the papers' values (`meta.primary` first). */
export function baselineKey(baselines: readonly BaselineRow[], meta: Record<string, unknown> | undefined): string | null {
  const keys = new Set(baselines.flatMap((b) => Object.keys(b.values)));
  const hinted = meta?.primary;
  if (typeof hinted === "string") {
    if (keys.has(hinted)) return hinted;
    if (keys.has(`${hinted}/value`)) return `${hinted}/value`;
  }
  return [...keys].sort()[0] ?? null;
}

/**
 * `≠v1` when the paper's metric version is not ours for this key's metric (or unknown);
 * null when it matches. The board's version comes from `meta.metric_versions`.
 */
export function versionBadge(b: BaselineRow, key: string, meta: Record<string, unknown> | undefined): string | null {
  const metric = key.split("/")[0] ?? key;
  if (b.version_match[metric] === true) return null;
  const versions = meta?.metric_versions as Record<string, string> | undefined;
  return `≠${versions?.[metric] ?? ""}`;
}

function BaselinePlot({
  value,
  x,
  width,
  band,
  best,
}: {
  value: number | null;
  x: LinearScale;
  width: number;
  band: Band | null;
  best: LeaderboardRowJson | null;
}): ReactElement {
  return (
    <svg className="hx-chart" width={width} height={BL_H} aria-hidden="true">
      <GridX x={x.at} ticks={x.ticks} y0={0} y1={BL_H} />
      {band ? <BestBand x1={x.at(band.lo)} x2={x.at(band.hi)} y0={0} y1={BL_H} /> : null}
      {best?.primary ? (
        <line className="bestline" x1={x.at(best.primary.mean)} x2={x.at(best.primary.mean)} y1={0} y2={BL_H} />
      ) : null}
      {value !== null ? <BaselineMark cx={x.at(value)} cy={BL_H / 2} /> : null}
    </svg>
  );
}

```

In `Leaderboard`, let a task with paper results and no scored run show the papers (they are the targets): replace

```tsx
  if (rows.length === 0) return <p className="panel-empty">No scored runs yet</p>;

  const meta = result.meta;
```

with

```tsx
  const meta = result.meta;
  const baselines = baselineRows(meta);
  // paper results are the targets: with baselines and no scored run yet, still draw them
  if (rows.length === 0 && baselines.length === 0) {
    return <p className="panel-empty">No scored runs yet</p>;
  }
```

replace

```tsx
  const pkey = primaryKey(rows, meta) ?? "";
  const secondKey = [...new Set(rows.flatMap((r) => Object.keys(r.scores)))]
```

with

```tsx
  const pkey = primaryKey(rows, meta) ?? baselineKey(baselines, meta) ?? "";
  // no scored run yet: the keys the papers report stand in for the score columns
  const scoreKeys =
    rows.length > 0 ? rows.flatMap((r) => Object.keys(r.scores)) : baselines.flatMap((b) => Object.keys(b.values));
  const secondKey = [...new Set(scoreKeys)]
```

replace

```tsx
  const fmt = valueFormatter(meta, rows.flatMap((r) => (r.primary ? [r.primary.mean] : [])), pkey);
```

with

```tsx
  const primaries = rows.flatMap((r) => (r.primary ? [r.primary.mean] : []));
  const fmt = valueFormatter(
    meta,
    primaries.length > 0 ? primaries : baselines.flatMap((b) => baselineValue(b, pkey) ?? []),
    pkey,
  );
```

replace

```tsx
  if (band) values.push(band.lo, band.hi);
  // This is the plot column's measured width, not the full leaderboard card.
  const tickCount = Math.max(2, Math.floor((width - 2 * PAD) / 70));
  const x = linear(niceDomain(values), PAD, width - PAD, tickCount);
```

with

```tsx
  if (band) values.push(band.lo, band.hi);
  for (const b of baselines) {
    const v = baselineValue(b, pkey);
    if (v !== null) values.push(v);
  }
  // This is the plot column's measured width, not the full leaderboard card.
  const tickCount = Math.max(2, Math.floor((width - 2 * PAD) / 70));
  const x = linear(niceDomain(values), PAD, width - PAD, tickCount);
```

Replace

```tsx
  if (band) keyItems.push({ glyph: "band", label: "best's CI", title: band.how });
```

with

```tsx
  if (band) keyItems.push({ glyph: "band", label: "best's CI", title: band.how });
  if (baselines.length > 0) {
    keyItems.push({ glyph: "baseline", label: "paper", title: "Published result; never a seed group, never best" });
  }
```

Replace the start of the axis row

```tsx
        <div className="frow axisrow">
```

with

```tsx
        {baselines.map((b, i) => {
          const v = baselineValue(b, pkey);
          const std = b.std[pkey];
          const badge = versionBadge(b, pkey, meta);
          const metric = pkey.split("/")[0] ?? pkey;
          const second = secondKey ? baselineValue(b, secondKey) : null;
          const versions = meta?.metric_versions as Record<string, string> | undefined;
          return (
            <div className={i === 0 ? "frow bl first" : "frow bl"} data-baseline={b.name} key={`bl-${b.name}`}>
              <div>
                <div className="nm" title={b.name}>
                  {`◆ ${b.name}`}
                  {badge ? (
                    <span
                      className="vbad"
                      title={`Published under another ${metric} version than ${versions?.[metric] ?? "ours"}`}
                    >
                      {badge}
                    </span>
                  ) : null}
                </div>
                <div className="meta">
                  <a href={b.source_url} target="_blank" rel="noreferrer noopener" title={b.source_url}>
                    {`↗ ${b.source}`}
                  </a>
                </div>
              </div>
              <div className="acc">
                <div className="big">{v !== null ? fmt.num(v) : "—"}</div>
                <div className="sd">
                  {typeof std === "number" ? (
                    <span title="published std">{`± ${fmt.spread(std)}`}</span>
                  ) : (
                    <span title="published result">paper</span>
                  )}
                </div>
              </div>
              <div className="fplot">
                <BaselinePlot value={v} x={x} width={width} band={band} best={best} />
              </div>
              <div className="f1">{second !== null ? fmt2.value(second) : ""}</div>
              <div className="vd" title="This paper result minus the best group's mean">
                <span>{v !== null && best?.primary ? fmt.delta(v, best.primary.mean) : "—"}</span>
              </div>
            </div>
          );
        })}
        <div className="frow axisrow">
```

Keep the baseline measured-width tick density and endpoint text-anchor rules. Paper baseline values extend the domain without reverting chart layout fixes or CSS.

Append to `ui/src/panels/panels.css`:

```css
/* paper baselines (phase 3): after a dashed rule, shorter rows, greyed names, never best */
.frow.bl { height: 57px; padding: 10px 0 8px; }
.frow.bl.first { border-top: 1px dashed var(--ink-3); }
.frow.bl .fplot { margin: -10px 0 -8px; }
.frow.bl .nm { font-weight: 450; color: var(--ink-2); font-size: 15px; }
.frow.bl .meta { flex-direction: row; gap: 10px; margin-top: 3px; }
.frow.bl .big { color: var(--ink-2); font-size: 20px; }
.frow.bl .vbad { margin-left: 8px; font: 500 11.5px var(--sans); color: var(--human); border: 1px solid color-mix(in srgb, var(--human) 45%, transparent); border-radius: 4px; padding: 0 5px; cursor: help; }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `bun test test/panels test/charts && bun run typecheck`
Expected: `leaderboardBaselines.test.tsx` 6 pass; `Leaderboard.test.tsx` and `Glyphs.test.tsx` pass unchanged (no `meta.baselines`, so no baseline rows or key entry); `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 6: Commit (repo root)**

```bash
git add ui/src/charts/Glyphs.tsx ui/src/charts/charts.css ui/src/panels/Leaderboard.tsx ui/src/panels/panels.css ui/test/panels/leaderboardBaselines.test.tsx
git commit -m "feat(ui): paper baselines in the leaderboard panel, never best, with version badges"
```

---

### Task 23: Wire export and baselines into the Task page

**Files:**
- Create: `ui/src/pages/components/baselines.ts`
- Modify: `ui/src/pages/components/PanelGrid.tsx` (`PanelGridProps.aside`; the `Figure` aside)
- Modify: `ui/src/pages/Task.tsx` (imports; the `PanelGrid` call)
- Create: `ui/test/pages/taskExport.test.tsx`

**Interfaces:**
- Consumes: Task 21 `ExportMenu`; Task 22 (the panel reads `meta.baselines`); `useLeaderboard` (the Task page already reads the board).
- Produces: `withBaselines(results, board): PanelResult[]` (every `leaderboard` result gets `meta.baselines = board.baselines ?? []`; other results and an unloaded board pass through); `PanelGridProps.aside?: (result, index) => ReactNode` (shown after the warnings count in each panel's title); the Task page passes `ExportMenu` for leaderboard panels.

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/taskExport.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { withBaselines } from "../../src/pages/components/baselines";
import { PanelGrid } from "../../src/pages/components/PanelGrid";
import type { PanelResult, QueryResponse, ViewDetail, ViewInfo } from "../../src/pages/components/types";
import { TaskPage } from "../../src/pages/Task";
import { BASELINES } from "../api/phase3-fixtures";
import { makeBoard } from "./fixtures";
import { fakeRegistry, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(restoreFetch);

const BASE = "/api/v1/tasks/toy-classifier/toy-test";
const LB: PanelResult = { type: "leaderboard", title: "All ideas", rows: [{}, {}], meta: { primary: "accuracy" } };
const STRIP: PanelResult = { type: "stat_strip", title: "Best", rows: [], meta: {} };

describe("withBaselines", () => {
  test("adds the board's baselines to leaderboard results only", () => {
    const out = withBaselines([STRIP, LB], { ...makeBoard(), baselines: BASELINES });
    expect(out[0]).toBe(STRIP);
    expect(out[1]?.meta).toEqual({ primary: "accuracy", baselines: BASELINES });
    expect(withBaselines([LB], { ...makeBoard(), baselines: undefined })[0]?.meta.baselines).toEqual([]);
    expect(withBaselines([LB], undefined)[0]).toBe(LB);
  });
});

test("PanelGrid shows a panel's aside after its warnings", () => {
  renderWithClient(
    <PanelGrid
      results={[STRIP, { ...LB, meta: { warnings: ["seed 3 missing"] } }]}
      aside={(r) => (r.type === "leaderboard" ? <button type="button">export ▾</button> : null)}
    />,
    { registry: fakeRegistry(["stat_strip", "leaderboard"]) },
  );
  expect(within(screen.getByRole("region", { name: "a Best" })).queryByRole("button")).toBeNull();
  const lb = screen.getByRole("region", { name: "b All ideas" });
  expect(lb.querySelector(".aside")?.textContent).toBe("⚠ 1export ▾");
});

test("the Task page: export in the leaderboard's title, baselines in its meta", async () => {
  const info: ViewInfo = { name: "overview", title: "Overview", origin: "preset", path: null, kind: "generic" };
  const doc: ViewDetail = {
    info,
    text: "title: Overview\n",
    view: {
      title: "Overview",
      panels: [
        { type: "stat_strip", title: "Best", data: {}, layout: { span: 4, row: null } },
        { type: "leaderboard", title: "All ideas", data: {}, layout: { span: 8, row: null } },
      ],
    },
  };
  const panels: QueryResponse = { panels: [STRIP, LB] };
  mockApi({
    [`GET ${BASE}/leaderboard`]: { ...makeBoard(), baselines: BASELINES },
    [`GET ${BASE}/views`]: [info],
    [`GET ${BASE}/views/overview`]: doc,
    [`POST ${BASE}/views/query`]: panels,
    "GET /api/v1/projects/toy-classifier/sweeps": [],
    [`GET ${BASE}/export?format=latex&noise=both&digits=3`]: "% requires \\usepackage{booktabs}\n",
  });
  const registry = {
    ...fakeRegistry(["stat_strip"]),
    leaderboard: ({ result }: { result: PanelResult }) => (
      <p>{`baselines:${(result.meta.baselines as unknown[] | undefined)?.length ?? "none"}`}</p>
    ),
  };
  renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
  await screen.findByText("baselines:2");
  const lb = screen.getByRole("region", { name: "b All ideas" });
  fireEvent.click(within(lb).getByRole("button", { name: "export ▾" }));
  await waitFor(() =>
    expect(within(lb).getByLabelText("Preview").textContent).toBe("% requires \\usepackage{booktabs}\n"),
  );
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/taskExport.test.tsx`
Expected: FAIL: `error: Cannot find module '../../src/pages/components/baselines'`.

- [ ] **Step 3: Write `baselines.ts`, extend `PanelGrid`, wire the Task page**

Create `ui/src/pages/components/baselines.ts`:

```ts
/**
 * Paper baselines reach the leaderboard panel through its `meta` (phase 3 contract 1.5):
 * `GET .../leaderboard` carries `baselines`; the view query's leaderboard panel does not,
 * so the Task page adds the board's to each leaderboard result before drawing it.
 */
import type { Leaderboard, PanelResult } from "./types";

export function withBaselines(results: PanelResult[], board: Leaderboard | undefined): PanelResult[] {
  if (board === undefined) return results;
  const baselines = board.baselines ?? [];
  return results.map((r) => (r.type === "leaderboard" ? { ...r, meta: { ...r.meta, baselines } } : r));
}
```

In `ui/src/pages/components/PanelGrid.tsx`, replace

```tsx
import { type ComponentType, createContext, useContext } from "react";
```

with

```tsx
import { type ComponentType, type ReactNode, createContext, useContext } from "react";
```

replace

```tsx
export interface PanelGridProps {
  results: PanelResult[];
  specs?: PanelSpec[];
  startIndex?: number;
}

export function PanelGrid({ results, specs, startIndex = 0 }: PanelGridProps) {
```

with

```tsx
export interface PanelGridProps {
  results: PanelResult[];
  specs?: PanelSpec[];
  startIndex?: number;
  /** Extra controls in a panel's title (the Task page's `export ▾` on leaderboards). */
  aside?: (result: PanelResult, index: number) => ReactNode;
}

export function PanelGrid({ results, specs, startIndex = 0, aside }: PanelGridProps) {
```

and replace

```tsx
        const warn = warnings(result);
        return (
          <Figure
            key={`${i}-${result.type}`}
            letter={panelLetter(startIndex + i)}
            title={result.title || spec?.title || result.type}
            aside={warn.length ? <span title={warn.join("\n")}>⚠ {warn.length}</span> : undefined}
```

with

```tsx
        const warn = warnings(result);
        const extra = aside?.(result, i) ?? null;
        return (
          <Figure
            key={`${i}-${result.type}`}
            letter={panelLetter(startIndex + i)}
            title={result.title || spec?.title || result.type}
            aside={
              warn.length || extra ? (
                <>
                  {warn.length ? <span title={warn.join("\n")}>⚠ {warn.length}</span> : null}
                  {extra}
                </>
              ) : undefined
            }
```

In `ui/src/pages/Task.tsx` (as left by phase 2 Task 21), replace

```tsx
import { PanelGrid } from "./components/PanelGrid";
```

with

```tsx
import { withBaselines } from "./components/baselines";
import { ExportMenu } from "./components/ExportMenu";
import { PanelGrid } from "./components/PanelGrid";
```

and replace

```tsx
        <PanelGrid results={panels.data.panels} specs={detail.data?.view.panels} />
```

with

```tsx
        <PanelGrid
          results={withBaselines(panels.data.panels, board.data)}
          specs={detail.data?.view.panels}
          aside={(result) => (result.type === "leaderboard" ? <ExportMenu project={project} task={task} /> : null)}
        />
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/pages && bun run typecheck`
Expected: `taskExport.test.tsx` 3 pass; `Task.test.tsx` and `panelGrid.test.tsx` pass unchanged (their leaderboard panels get `baselines: []`, which the fake registry ignores; a panel without warnings and without an aside still has no aside); `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/pages/components/baselines.ts ui/src/pages/components/PanelGrid.tsx ui/src/pages/Task.tsx ui/test/pages/taskExport.test.tsx
git commit -m "feat(ui): task page export menu and baselines on the leaderboard panel"
```

---

### Task 24: Cleaned artifacts on the Run page

**Files:**
- Modify: `ui/src/pages/components/WhereList.tsx` (imports; `WhereRow.cleaned`; `buildWhere`; `WhereList` rows; a scoped style)
- Create: `ui/test/pages/whereCleaned.test.tsx`

**Interfaces:**
- Consumes: Task 1 `RunDetail.cleaned`, `CleanedArtifact`; `fmtBytes`, `fmtDate`.
- Produces: `WhereRow.cleaned?: CleanedArtifact`; `cleanedText(c): string` (`✕ 2026-10-04 4.2 GB`); `buildWhere` marks an artifact row whose path a cleanup deleted and appends a struck-through row for each cleaned path that is not a recorded artifact (a pulled copy); `WhereList` draws such rows `li.cleaned` (path struck through, `✕ <date> <bytes>` with `cleaned by <actor>, plan <id>` as the tooltip, no copy button: the file is gone).

- [ ] **Step 1: Write the failing tests**

Create `ui/test/pages/whereCleaned.test.tsx`:

```tsx
import { expect, test } from "bun:test";
import { render, within } from "@testing-library/react";
import { buildWhere, cleanedText, WhereList } from "../../src/pages/components/WhereList";
import { RUN_SVM, STORE, makeDetail } from "./fixtures";

const DIR = `${STORE}/${RUN_SVM}`;
const CLEANED = [
  { path: `${DIR}/model.pkl`, bytes: 4.2e9, at: "2026-10-04T14:33:10Z", actor: "human:sv", plan_id: "cp-8e41c0d2" },
  { path: `${DIR}/pulled/ckpt`, bytes: 44.2e9, at: "2026-10-04T14:33:12Z", actor: "human:sv", plan_id: "cp-8e41c0d2" },
];

test("cleanedText is the date and the bytes", () => {
  expect(cleanedText(CLEANED[0]!)).toBe("✕ 2026-10-04 4.2 GB");
});

test("buildWhere marks a cleaned artifact and adds cleaned paths that were not artifacts", () => {
  const run = buildWhere(makeDetail({}, { cleaned: CLEANED })).find((g) => g.title === "Run");
  const cleaned = run?.rows.filter((r) => r.cleaned) ?? [];
  expect(cleaned.map((r) => [r.display, r.cleaned?.plan_id])).toEqual([
    ["model.pkl", "cp-8e41c0d2"],
    ["pulled/ckpt", "cp-8e41c0d2"],
  ]);
  expect(buildWhere(makeDetail()).find((g) => g.title === "Run")?.rows.some((r) => r.cleaned)).toBe(false);
});

test("a cleaned row is struck through, says when and how much, and has no copy button", () => {
  const { container } = render(<WhereList detail={makeDetail({}, { cleaned: CLEANED })} />);
  const rows = [...container.querySelectorAll<HTMLElement>("li.cleaned")];
  expect(rows.map((r) => [r.querySelector(".p")?.textContent, r.querySelector(".what")?.textContent])).toEqual([
    ["model.pkl", "✕ 2026-10-04 4.2 GB"],
    ["pulled/ckpt", "✕ 2026-10-04 44.2 GB"],
  ]);
  expect(within(rows[0] as HTMLElement).getByTitle("cleaned by human:sv, plan cp-8e41c0d2")).toBeTruthy();
  expect(rows.map((r) => r.querySelectorAll("button.copy").length)).toEqual([0, 0]);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `bun test test/pages/whereCleaned.test.tsx`
Expected: FAIL: `SyntaxError: Export named 'cleanedText' not found in module '.../src/pages/components/WhereList.tsx'`.

- [ ] **Step 3: Mark cleaned rows**

Preserve the shared `SlashPath` component for roots and child paths, its slash-only wrapping, and linked paths' accessible labels. Cleaned paths retain that renderer while dropping the link and copy action; do not reintroduce plain unbroken path text.

In `ui/src/pages/components/WhereList.tsx`, replace

```tsx
import { CopyButton } from "./CopyButton";
import { SlashPath } from "./SlashPath";
import { displayPath, fmtBytes, isNum, relativeTo, shellJoin, splitHostPath, tailPath } from "./format";
import { AppLink, hrefs } from "./links";
import type { GitInfo, RunDetail } from "./types";
```

with

```tsx
import { createElement } from "react";
import { CopyButton } from "./CopyButton";
import { SlashPath } from "./SlashPath";
import { displayPath, fmtBytes, fmtDate, isNum, relativeTo, shellJoin, splitHostPath, tailPath } from "./format";
import { AppLink, hrefs } from "./links";
import type { CleanedArtifact, GitInfo, RunDetail } from "./types";

/** Cleaned rows: the path struck through, the date and bytes after it (phase 3 contract 1.9). */
const CLEANED_CSS = `
.page .tree .kids li.cleaned .p { color: var(--ink-3); text-decoration: line-through; text-decoration-color: var(--ink-3); }
.page .tree .kids li.cleaned .what { color: var(--ink-2); cursor: help; }
`;

/** `✕ 2026-10-04 4.2 GB`. */
export function cleanedText(c: CleanedArtifact): string {
  return `✕ ${fmtDate(c.at).slice(0, 10)} ${fmtBytes(c.bytes)}`;
}
```

In `WhereRow`, replace

```tsx
  /** The full path, when `display` is shortened. */
  title?: string;
}
```

with

```tsx
  /** The full path, when `display` is shortened. */
  title?: string;
  /** A storage cleanup deleted this path. */
  cleaned?: CleanedArtifact;
}
```

In `buildWhere`, replace

```tsx
    for (const art of record.artifacts) {
      const note = joinNote([
        art.kind,
        isNum(art.step) ? `step ${art.step}` : null,
        isNum(art.size) ? fmtBytes(art.size) : null,
      ]);
      const row = whereRow({ host: art.host, path: art.path }, dir, { note });
      if (!row.indent && row.display.length > LONG_PATH) {
        row.display = displayPath(art.host, tailPath(art.path, 2));
        row.title = row.copy;
      }
      run.rows.push(row);
    }
    groups.push(run);
```

with

```tsx
    const cleaned = new Map((detail.cleaned ?? []).map((c) => [c.path, c]));
    for (const art of record.artifacts) {
      const note = joinNote([
        art.kind,
        isNum(art.step) ? `step ${art.step}` : null,
        isNum(art.size) ? fmtBytes(art.size) : null,
      ]);
      const gone = cleaned.get(art.path);
      const row = whereRow({ host: art.host, path: art.path }, dir, gone ? { note, cleaned: gone } : { note });
      if (!row.indent && row.display.length > LONG_PATH) {
        row.display = displayPath(art.host, tailPath(art.path, 2));
        row.title = row.copy;
      }
      cleaned.delete(art.path);
      run.rows.push(row);
    }
    // cleaned paths that were not recorded artifacts (pulled copies)
    for (const gone of cleaned.values()) {
      run.rows.push(whereRow({ host: dir.host, path: gone.path }, dir, { cleaned: gone }));
    }
    groups.push(run);
```

In `WhereList`, replace

```tsx
  return (
    <div className="tree">
      <div className="cmdrow">
```

with

```tsx
  return (
    <div className="tree">
      {createElement("style", { "data-hx": "where" }, CLEANED_CSS)}
      <div className="cmdrow">
```

and replace

```tsx
                {kids.map((row, i) => (
                  <li key={`${row.copy}-${i}`}>
                    <span className="br">{row.indent ? (i === kids.length - 1 ? "└" : "├") : "·"}</span>
                    <span className="p" title={row.title}>
                      {row.href ? (
                        <AppLink href={row.href} title="Open" aria-label={row.display}>
                          <SlashPath path={row.display} />
                        </AppLink>
                      ) : (
                        <SlashPath path={row.display} />
                      )}
                    </span>
                    <span className="what">{row.note ?? ""}</span>
                    <CopyButton text={row.copy} label={row.display} />
                  </li>
                ))}
```

with

```tsx
                {kids.map((row, i) => (
                  <li key={`${row.copy}-${i}`} className={row.cleaned ? "cleaned" : undefined}>
                    <span className="br">{row.indent ? (i === kids.length - 1 ? "└" : "├") : "·"}</span>
                    <span className="p" title={row.title}>
                      {row.href && !row.cleaned ? (
                        <AppLink href={row.href} title="Open" aria-label={row.display}>
                          <SlashPath path={row.display} />
                        </AppLink>
                      ) : (
                        <SlashPath path={row.display} />
                      )}
                    </span>
                    {row.cleaned ? (
                      <span className="what" title={`cleaned by ${row.cleaned.actor}, plan ${row.cleaned.plan_id}`}>
                        {cleanedText(row.cleaned)}
                      </span>
                    ) : (
                      <span className="what">{row.note ?? ""}</span>
                    )}
                    {row.cleaned ? <span /> : <CopyButton text={row.copy} label={row.display} />}
                  </li>
                ))}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `bun test test/pages && bun run typecheck`
Expected: `whereCleaned.test.tsx` 3 pass; `whereList.test.tsx`, `Run.test.tsx` and `RunRemote.test.tsx` pass unchanged (no `cleaned` in their details); `0 fail`; `tsc --noEmit` prints nothing.

- [ ] **Step 5: Commit (repo root)**

```bash
git add ui/src/pages/components/WhereList.tsx ui/test/pages/whereCleaned.test.tsx
git commit -m "feat(ui): run page strikes through artifacts a storage cleanup deleted"
```

---

## Group 7: Playwright against `hx demo --with-team`, and docs (Tasks 25–26)

A third demo hub, `hx demo --with-team` with auth on, served by `serve-demo.ts --with-team` on its own random port and fresh home, checked by identity before every test like the other two. Every browser signs in through the real `/pair` page with a link the spec makes from that home's own local session token (`<home>/serve/server.json`, written by `hx serve` with auth on), so the specs exercise pairing, cookies, tickets and scopes end to end. All browsers reach the hub from `127.0.0.1`, so the hub's pairing limit (10 per minute per address) would trip if it counted successes; it counts only failed pairings (backend Task 25, contract 3), and only `a used pairing link reads invalid` fails one (once per theme project), so parallel workers never get a 429. Read-only specs run in `team-light`/`team-dark`; the writes (notebook, cleanup) run serially in `team-light-edit` then `team-dark-edit`, and the cleanup itself runs once.

Demo requirements this group reads (backend plan, contract 11): users `sv` (admin) and `alice` (launch); at least one run with `owner: "alice"`; two projects with notebook days; baselines on `toy-classifier/toy-test`, whose preset view has a leaderboard panel; archived runs whose dry run (default policy) has items, one `protected` refusal and one `used by <id>` refusal; outbox entries that include `sent`, `failed` and `skipped`; the local token in `serve/server.json`.

### Task 25: Team demo hub, pairing helpers, and the team specs

**Files:**
- Modify: `ui/e2e/paths.ts` (append)
- Modify: `ui/e2e/serve-demo.ts` (doc comment; imports; mode selection; demo and serve arguments)
- Modify: `ui/e2e/fixtures.ts` (imports; `OWN_HUBS`)
- Modify: `ui/playwright.config.ts` (whole file)
- Create: `ui/e2e/team-fixtures.ts`
- Create: `ui/e2e/team.spec.ts`
- Create: `ui/e2e/team-edit.spec.ts`
- Modify: `ui/README.md` (append a section)

**Interfaces:**
- Consumes: `freePort`-based `runPort`, `readIdentity`, `expectIsolatedHub`, `expectTheme`, the `consoleErrors` fixture (phase 1b/2); the accessible names of Tasks 5–24 (`pair this device:`, `device`, `pair`, `overview →`, `@sva` chip title, regions `a Sessions` … `d Notifications`, tables `Recent sends`, `Plan items`, `Confirm size`, `export ▾`, dialog `Export`, `Preview`, `New entry`, `Day text`, `theirs`, `keep mine`, `li.cleaned`, `.frow.bl`).
- Produces: `TEAM_PORT` (`HX_E2E_TEAM_PORT`), `TEAM_HOME_DIR` (`<RUN_DIR>/home-team`), `TEAM_DEMO_FILE` (`<RUN_DIR>/demo-team.json`), `TEAM_DEMO_LABEL = "hx-e2e-team"`, `SERVER_JSON`, `readLocalToken(home)` (paths.ts); `serve-demo.ts --with-team` (`hx demo --with-team --json`, then `hx serve --auth`); `ownerHeaders()`, `ownerGet(request, path)`, `ownerPost(request, path, data)`, `pairBrowser(page, request, user, scope)` → `{ user, scope, sessionId, fragment }`, `allowStatus(errors, ...statuses)` (team-fixtures.ts); Playwright projects `team-light`, `team-dark`, `team-light-edit`, `team-dark-edit`.

- [ ] **Step 1: Team paths and the local token reader**

Append to `ui/e2e/paths.ts`:

```ts

/** Port of the `hx demo --with-team` hub (auth on; projects team-*). Random per run, like the others. */
export const TEAM_PORT = runPort("HX_E2E_TEAM_PORT");
/**
 * Hub home of the `hx demo --with-team` server (auth on), wiped on every start. In the run's
 * own directory like the other two, so `serve-demo.ts` wipes and `procs.ts` kills only there.
 */
export const TEAM_HOME_DIR = join(RUN_DIR, "home-team");
/** `hx demo --with-team --json` output. */
export const TEAM_DEMO_FILE = join(RUN_DIR, "demo-team.json");
export const TEAM_DEMO_LABEL = "hx-e2e-team";
/** Where `hx serve` with auth on keeps its own local admin session token (contract section 2). */
export const SERVER_JSON = join("serve", "server.json");

/**
 * The local admin token `hx serve` wrote into `home` (the fresh team home only), or null
 * before the hub wrote it. Specs use it to make pairing links and to arrange state; the
 * browsers themselves only ever hold sessions made through `/pair`.
 */
export function readLocalToken(home: string): string | null {
  const file = join(home, SERVER_JSON);
  if (!existsSync(file)) return null;
  try {
    const raw = JSON.parse(readFileSync(file, "utf8")) as { token?: unknown };
    return typeof raw.token === "string" && raw.token !== "" ? raw.token : null;
  } catch {
    return null;
  }
}
```

- [ ] **Step 2: Let `serve-demo.ts` seed and serve the team demo**

In `ui/e2e/serve-demo.ts` (as left by phase 2 Task 28), replace

```ts
 * connection. `PORT` and `HOSTS_PORT` are the run's random ports.
```

with

```ts
 * connection. `PORT` and `HOSTS_PORT` are the run's random ports.
 *
 * With `--with-team`: `hx demo --with-team --json` into `TEAM_HOME_DIR` (`home-team` in the
 * run's directory), label `TEAM_DEMO_LABEL`, output in `TEAM_DEMO_FILE`, served with
 * `hx serve --auth` on `TEAM_PORT`. Auth is on: the identity route stays public, everything
 * else needs a session.
```

In `ui/e2e/serve-demo.ts` (as left by phase 2 Task 28), replace

```ts
  HOSTS_PORT,
  IDENTITY_FILE,
  PORT,
  REPO_ROOT,
  RUN_DIR,
  SHUTDOWN_WAIT_MS,
  UI_DIST_INDEX,
} from "./paths";
import { demoOwner, killOwned, listProcs, type Owner } from "./procs";

const withHosts = process.argv.includes("--with-hosts");
const home = withHosts ? HOSTS_HOME_DIR : HOME_DIR;
const demoFile = withHosts ? HOSTS_DEMO_FILE : DEMO_FILE;
const port = withHosts ? HOSTS_PORT : PORT;
const label = withHosts ? HOSTS_DEMO_LABEL : DEMO_LABEL;
```

with

```ts
  HOSTS_PORT,
  IDENTITY_FILE,
  PORT,
  REPO_ROOT,
  RUN_DIR,
  SHUTDOWN_WAIT_MS,
  TEAM_DEMO_FILE,
  TEAM_DEMO_LABEL,
  TEAM_HOME_DIR,
  TEAM_PORT,
  UI_DIST_INDEX,
} from "./paths";
import { demoOwner, killOwned, listProcs, type Owner } from "./procs";

const withHosts = process.argv.includes("--with-hosts");
const withTeam = process.argv.includes("--with-team");
const home = withTeam ? TEAM_HOME_DIR : withHosts ? HOSTS_HOME_DIR : HOME_DIR;
const demoFile = withTeam ? TEAM_DEMO_FILE : withHosts ? HOSTS_DEMO_FILE : DEMO_FILE;
const port = withTeam ? TEAM_PORT : withHosts ? HOSTS_PORT : PORT;
const label = withTeam ? TEAM_DEMO_LABEL : withHosts ? HOSTS_DEMO_LABEL : DEMO_LABEL;
```

In `ui/e2e/serve-demo.ts` (as left by phase 2 Task 28), replace

```ts
const demoArgs = withHosts ? ["demo", "--with-hosts", "--json"] : ["demo", "--json"];
```

with

```ts
const demoArgs = withTeam
  ? ["demo", "--with-team", "--json"]
  : withHosts
    ? ["demo", "--with-hosts", "--json"]
    : ["demo", "--json"];
```

In `ui/e2e/serve-demo.ts` (as left by phase 2 Task 28), replace

```ts
const server: ChildProcess = spawn(hx, ["--home", home, "serve", "--port", String(port)], {
```

with

```ts
const serveArgs = ["--home", home, "serve", "--port", String(port), ...(withTeam ? ["--auth"] : [])];
const server: ChildProcess = spawn(hx, serveArgs, {
```

Keep the final baseline's `env` construction and deletion of `HYPOTHEX_SERVE_TOKEN`/`HYPOTHEX_HUB_TOKEN`; team mode must mint its own scoped owner session. Preserve process ownership, bounded shutdown, and isolated homes.

- [ ] **Step 3: Check the team hub's identity too**

In `ui/e2e/fixtures.ts` (as left by phase 2 Task 28), replace

```ts
  readIdentity,
} from "./paths";
```

with

```ts
  readIdentity,
  TEAM_DEMO_LABEL,
  TEAM_HOME_DIR,
  TEAM_PORT,
} from "./paths";
```

In `ui/e2e/fixtures.ts` (as left by phase 2 Task 28), replace

```ts
  [`http://127.0.0.1:${HOSTS_PORT}`]: { home: HOSTS_HOME_DIR, label: HOSTS_DEMO_LABEL },
};
```

with

```ts
  [`http://127.0.0.1:${HOSTS_PORT}`]: { home: HOSTS_HOME_DIR, label: HOSTS_DEMO_LABEL },
  [`http://127.0.0.1:${TEAM_PORT}`]: { home: TEAM_HOME_DIR, label: TEAM_DEMO_LABEL },
};
```

- [ ] **Step 4: Add the team server and projects to `playwright.config.ts`**

Replace the whole of `ui/playwright.config.ts` with:

```ts
import { defineConfig, devices } from "@playwright/test";
import type { ThemeOptions } from "./e2e/fixtures";
// Loading paths.ts picks this run's free ports and puts them in process.env, which the
// workers and every web server inherit (never a fixed port, ruling S1).
import { HOSTS_PORT, IDENTITY_ROUTE, PORT, TEAM_PORT, VITE_PORT } from "./e2e/paths";

const WRITES = /(editor|live)\.spec\.ts$/;
/** Specs against the `hx demo --with-hosts` hub; `launch` starts runs, so it runs last. */
const HOSTS_READS = /hosts\.spec\.ts$/;
const HOSTS_WRITES = /launch\.spec\.ts$/;
/** Specs against the `hx demo --with-team` hub (auth on); the edits write notes and delete artifacts. */
const TEAM_READS = /team\.spec\.ts$/;
const TEAM_WRITES = /team-edit\.spec\.ts$/;
const HOSTS_URL = `http://127.0.0.1:${HOSTS_PORT}`;
const TEAM_URL = `http://127.0.0.1:${TEAM_PORT}`;
const OTHER_HUBS = [HOSTS_READS, HOSTS_WRITES, TEAM_READS, TEAM_WRITES];
/**
 * SIGTERM, then SIGKILL after 90 s: `serve-demo.ts` forwards the SIGTERM to `hx serve`,
 * whose lifespan shutdown stops the demo runs and fake hosts (its own wait is 60 s).
 * Without this Playwright SIGKILLs the group at once.
 */
const GRACEFUL = { signal: "SIGTERM", timeout: 90_000 } as const;
const desktop = (theme: "light" | "dark", baseURL?: string) => ({
  ...devices["Desktop Chrome"],
  ...(baseURL ? { baseURL } : {}),
  colorScheme: theme,
  theme,
});

export default defineConfig<ThemeOptions>({
  testDir: "./e2e",
  outputDir: "./e2e/.results",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [["list"], ["html", { outputFolder: "./e2e/.report", open: "never" }]]
    : [["list"]],
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "off",
    screenshot: "off",
  },
  projects: [
    {
      name: "vite-auth",
      testMatch: /auth\.spec\.ts$/,
      use: desktop("light", `http://127.0.0.1:${VITE_PORT}`),
    },
    { name: "light", testIgnore: [WRITES, ...OTHER_HUBS], use: desktop("light") },
    { name: "dark", testIgnore: [WRITES, ...OTHER_HUBS], use: desktop("dark") },
    { name: "light-edit", testMatch: WRITES, dependencies: ["light", "dark"], use: desktop("light") },
    {
      // Runs after light-edit (not just light/dark): live.spec.ts posts a note to the
      // same shared demo run from both edit projects, and the Notes panel shows only the
      // newest one, so the two projects must not write to it at the same time.
      name: "dark-edit",
      testMatch: WRITES,
      dependencies: ["light", "dark", "light-edit"],
      use: desktop("dark"),
    },
    { name: "hosts-light", testMatch: HOSTS_READS, use: desktop("light", HOSTS_URL) },
    { name: "hosts-dark", testMatch: HOSTS_READS, use: desktop("dark", HOSTS_URL) },
    {
      // Launches add queued runs to a fake host, so they wait for the read-only specs.
      name: "hosts-light-edit",
      testMatch: HOSTS_WRITES,
      dependencies: ["hosts-light", "hosts-dark"],
      use: desktop("light", HOSTS_URL),
    },
    {
      name: "hosts-dark-edit",
      testMatch: HOSTS_WRITES,
      dependencies: ["hosts-light", "hosts-dark", "hosts-light-edit"],
      use: desktop("dark", HOSTS_URL),
    },
    { name: "team-light", testMatch: TEAM_READS, use: { ...desktop("light", TEAM_URL), unlock: false } },
    { name: "team-dark", testMatch: TEAM_READS, use: { ...desktop("dark", TEAM_URL), unlock: false } },
    {
      // The edits delete artifacts and revoke nothing the read specs need, but they run
      // after them so the reads see the seeded state.
      name: "team-light-edit",
      testMatch: TEAM_WRITES,
      dependencies: ["team-light", "team-dark"],
      use: { ...desktop("light", TEAM_URL), unlock: false },
    },
    {
      // After team-light-edit: it applies the cleanup this project checks.
      name: "team-dark-edit",
      testMatch: TEAM_WRITES,
      dependencies: ["team-light", "team-dark", "team-light-edit"],
      use: { ...desktop("dark", TEAM_URL), unlock: false },
    },
  ],
  // Every port is random per run. Never reuse a server that answers on one anyway: an
  // `hx serve` there may run on the real ~/.hypothex. Playwright fails at start instead, a
  // web server whose command exits stops the run at once, and every test checks the hub's
  // identity first (`isolatedHub` in e2e/fixtures.ts).
  webServer: [
    {
      command: `bun run dev --host 127.0.0.1 --port ${VITE_PORT}`,
      env: { HX_API: `http://127.0.0.1:${PORT}` },
      url: `http://127.0.0.1:${VITE_PORT}/`,
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "bun e2e/serve-demo.ts",
      url: `http://127.0.0.1:${PORT}${IDENTITY_ROUTE}`,
      reuseExistingServer: false,
      gracefulShutdown: GRACEFUL,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "bun e2e/serve-demo.ts --with-hosts",
      url: `${HOSTS_URL}${IDENTITY_ROUTE}`,
      reuseExistingServer: false,
      gracefulShutdown: GRACEFUL,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "bun e2e/serve-demo.ts --with-team",
      url: `${TEAM_URL}${IDENTITY_ROUTE}`,
      reuseExistingServer: false,
      gracefulShutdown: GRACEFUL,
      timeout: 180_000,
      stdout: "pipe",
      stderr: "pipe",
    },
  ],
});
```

The existing fixture now unlocks root-auth browsers by default and sends the isolated home's bearer for API requests. Team projects set `unlock: false` above so their pages reach `/pair` without selecting the owner token; retain the fixture's identity verification and `authToken`/`localToken` safeguards. `pairBrowser` then selects cookie mode through the real Pair page. Keep the Vite proxy authentication project, `VITE_PORT` ownership mapping, and `trace: "off"`/`screenshot: "off"` so credentials are not recorded in artifacts.

- [ ] **Step 5: Write the team helpers**

Create `ui/e2e/team-fixtures.ts`:

```ts
/**
 * Helpers for the specs against the `hx demo --with-team` hub (auth on; owner `sv`,
 * collaborator `alice`). The owner's local token comes only from the fresh e2e home
 * `serve-demo.ts` wrote; every browser signs in through the real `/pair` page.
 */
import type { APIRequestContext, Page } from "@playwright/test";
import { expect } from "./fixtures";
import { TEAM_HOME_DIR, readLocalToken } from "./paths";

/** Bearer headers with the team hub's local admin token. */
export function ownerHeaders(): Record<string, string> {
  const token = readLocalToken(TEAM_HOME_DIR);
  if (token === null) throw new Error(`no local token in ${TEAM_HOME_DIR}/serve/server.json`);
  return { Authorization: `Bearer ${token}` };
}

/** GET a JSON route as the owner. */
export async function ownerGet<T>(request: APIRequestContext, path: string): Promise<T> {
  const response = await request.get(path, { headers: ownerHeaders() });
  expect(response.status(), `GET ${path}`).toBe(200);
  return (await response.json()) as T;
}

/** POST a JSON body as the owner. */
export async function ownerPost<T>(request: APIRequestContext, path: string, data: unknown): Promise<T> {
  const response = await request.post(path, { headers: ownerHeaders(), data });
  expect(response.status(), `POST ${path}`).toBe(200);
  return (await response.json()) as T;
}

export interface Paired {
  user: string;
  scope: string;
  sessionId: string;
  /** `#p_<12 hex>.<secret>`, already used. */
  fragment: string;
}

/**
 * Make a pairing link as the owner and redeem it in this page through `/pair`. Afterwards
 * the browser context holds a session cookie for `user` at `scope`.
 */
export async function pairBrowser(
  page: Page,
  request: APIRequestContext,
  user: "sv" | "alice",
  scope: "admin" | "launch",
): Promise<Paired> {
  const offer = await ownerPost<{ url: string }>(request, "/api/v1/auth/pairings", { user, scope });
  const fragment = new URL(offer.url).hash;
  expect(fragment).toMatch(/^#p_[0-9a-f]{12}\./);
  await page.goto(`/pair${fragment}`);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("pair");
  // the page removed the secret from the address bar before anything was sent
  await expect.poll(() => new URL(page.url()).hash).toBe("");
  await page.getByLabel("device").fill(`e2e ${user}`);
  await page.getByRole("button", { name: "pair" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(`✓ ${user} · ${scope}`);
  const me = await page.request.get("/api/v1/auth/me");
  expect(me.status()).toBe(200);
  const body = (await me.json()) as { user: string; scope: string; session_id: string };
  return { user: body.user, scope: body.scope, sessionId: body.session_id, fragment };
}

/** Drop console errors the browser logs for HTTP answers a spec expects (`status of 401`). */
export function allowStatus(errors: string[], ...statuses: number[]): void {
  const keep = errors.filter((e) => !statuses.some((s) => e.includes(`status of ${s}`)));
  errors.splice(0, errors.length, ...keep);
}
```

- [ ] **Step 6: Write the read-only team specs**

Create `ui/e2e/team.spec.ts`:

```ts
import { readFile } from "node:fs/promises";
import { expect, expectTheme, test } from "./fixtures";
import { allowStatus, ownerGet, ownerHeaders, pairBrowser } from "./team-fixtures";

test("pairing through /pair signs the browser in; the header shows @sv a", async ({ page, request, theme }) => {
  await pairBrowser(page, request, "sv", "admin");
  await page.getByRole("link", { name: "overview →" }).click();
  await expect(page.getByRole("navigation", { name: "Screens" })).toBeVisible();
  await expectTheme(page, theme);
  await expect(page.getByTitle(/^sv, scope admin, session s_/)).toHaveText("@sva");
  await expect(page.getByRole("link", { name: "storage" })).toBeVisible();
});

test("a used pairing link reads invalid", async ({ page, request, consoleErrors }) => {
  const paired = await pairBrowser(page, request, "alice", "launch");
  await page.goto(`/pair${paired.fragment}`);
  await page.getByRole("button", { name: "pair" }).click();
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("✗ link invalid or expired");
  allowStatus(consoleErrors, 400);
});

test("settings: the owner sees sessions, users, add device and notifications", async ({ page, request, theme }) => {
  await pairBrowser(page, request, "sv", "admin");
  await page.goto("/settings");
  await expectTheme(page, theme);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("users");
  for (const name of ["a Sessions", "b Users", "c Add device", "d Notifications"]) {
    await expect(page.getByRole("region", { name })).toBeVisible();
  }
  const recent = page.getByRole("table", { name: "Recent sends" });
  for (const status of ["✓ sent", "✗ failed", "○ skipped"]) {
    await expect(recent.getByText(status).first()).toBeVisible();
  }
});

test("settings: a collaborator sees own sessions and add device only", async ({ page, request }) => {
  await pairBrowser(page, request, "alice", "launch");
  await page.goto("/settings");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(/^@alice · launch · \d+ sessions?$/);
  await expect(page.getByRole("region", { name: "a Sessions" })).toBeVisible();
  await expect(page.getByRole("region", { name: "b Add device" })).toBeVisible();
  await expect(page.getByRole("region", { name: /Notifications|Users/ })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "storage" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "admin" })).toBeDisabled();
});

test("task: baseline rows, and the export menu as LaTeX and CSV", async ({ page, request, theme }) => {
  await pairBrowser(page, request, "sv", "admin");
  await page.goto("/t/toy-classifier/toy-test");
  await expectTheme(page, theme);
  const board = page.getByRole("region").filter({ has: page.getByRole("button", { name: "export ▾" }) }).first();
  await expect(board.locator(".frow.bl").first()).toContainText("◆");
  await board.getByRole("button", { name: "export ▾" }).click();
  const menu = page.getByRole("dialog", { name: "Export" });
  await expect(menu.getByLabel("Preview")).toContainText("% requires \\usepackage{booktabs}");
  await menu.getByRole("button", { name: "CSV" }).click();
  await expect(menu.getByLabel("Preview")).toContainText("kind,label,key,n,metric,mean,std");
  const expected = await page.request.get("/api/v1/tasks/toy-classifier/toy-test/export?format=csv&digits=3&noise=both");
  expect(expected.status()).toBe(200);
  const pendingDownload = page.waitForEvent("download");
  await menu.getByRole("button", { name: "↓ .csv" }).click();
  const download = await pendingDownload;
  expect(download.suggestedFilename()).toBe("toy-test.csv");
  const saved = await download.path();
  expect(saved).not.toBeNull();
  expect(await readFile(saved!, "utf8")).toBe(await expected.text());
});

test("run: the status line names the owner", async ({ page, request }) => {
  await pairBrowser(page, request, "sv", "admin");
  const runs = await ownerGet<{ run_id: string }[]>(request, "/api/v1/runs?owner=alice&limit=5");
  expect(runs.length, "hx demo --with-team seeded no run owned by alice").toBeGreaterThan(0);
  await page.goto(`/r/${encodeURIComponent(runs[0]?.run_id ?? "")}`);
  await expect(page.locator(".status")).toContainText("@alice");
});

test("a revoked session shows the 401 gate", async ({ page, request, consoleErrors }) => {
  const paired = await pairBrowser(page, request, "sv", "admin");
  await page.goto("/");
  await expect(page.getByTitle(/^sv, scope admin/)).toBeVisible();
  const revoked = await request.post(`/api/v1/auth/sessions/${paired.sessionId}/revoke`, {
    headers: ownerHeaders(),
    data: { command_id: `e2e-revoke-${paired.sessionId}` },
  });
  expect(revoked.status()).toBe(200);
  await page.reload();
  await expect(page.getByText("pair this device:")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Screens" })).toHaveCount(0);
  allowStatus(consoleErrors, 401);
});
```

- [ ] **Step 7: Write the team edit specs**

Create `ui/e2e/team-edit.spec.ts`:

```ts
import { expect, expectTheme, test } from "./fixtures";
import { allowStatus, ownerGet, ownerHeaders, pairBrowser } from "./team-fixtures";

// one at a time: the cleanup test must finish before the cleaned-artifact test reads it
test.describe.configure({ mode: "serial" });

test("notebook: an entry, then a conflicting save: 409, keep mine wins", async ({ page, request, theme, consoleErrors }) => {
  await pairBrowser(page, request, "sv", "admin");
  let project = "";
  let day = "";
  for (const p of await ownerGet<{ project: string }[]>(request, "/api/v1/projects")) {
    const days = await ownerGet<{ day: string }[]>(request, `/api/v1/projects/${encodeURIComponent(p.project)}/notebook`);
    if (days[0]) {
      project = p.project;
      day = days[0].day;
      break;
    }
  }
  expect(project, "hx demo --with-team seeded no notebook day").not.toBe("");
  const route = `/api/v1/projects/${encodeURIComponent(project)}/notebook/${day}`;
  await page.goto(`/n/${encodeURIComponent(project)}/${day}`);
  await expectTheme(page, theme);
  const marker = `e2e ${theme} ${Date.now()}`;
  await page.getByLabel("New entry").fill(marker);
  await page.getByRole("button", { name: "+ entry" }).click();
  await expect(page.locator(".ent").filter({ hasText: marker })).toBeVisible();

  await page.getByRole("button", { name: "edit" }).click();
  const area = page.getByLabel("Day text");
  await area.fill(`${await area.inputValue()}\nmine ${marker}\n`);
  // someone else saves the day first
  const current = await ownerGet<{ text: string; hash: string }>(request, route);
  const theirs = await request.put(route, {
    headers: ownerHeaders(),
    data: { text: `${current.text}\ntheirs ${marker}\n`, base_hash: current.hash, command_id: `e2e-theirs-${marker}` },
  });
  expect(theirs.status()).toBe(200);
  await page.getByRole("button", { name: "save" }).click();
  await expect(page.getByRole("alert")).toContainText("409");
  await expect(page.getByLabel("theirs")).toContainText(`theirs ${marker}`);
  await page.getByRole("button", { name: "keep mine" }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  expect((await ownerGet<{ text: string }>(request, route)).text).toContain(`mine ${marker}`);
  allowStatus(consoleErrors, 409);
});

test("storage: the dry run lists refusals; the typed size applies the plan", async ({ page, request }, testInfo) => {
  test.skip(testInfo.project.name !== "team-light-edit", "deletes artifacts once; team-dark-edit checks the result");
  await pairBrowser(page, request, "sv", "admin");
  await page.goto("/storage");
  await expect(page.getByRole("heading", { level: 1 })).toContainText("cleanable");
  await expect(page.getByRole("button", { name: "apply" })).toBeDisabled();
  await page.getByRole("button", { name: "dry run" }).click();
  const plan = page.getByRole("table", { name: "Plan items" });
  await expect(plan).toContainText("⊘ protected");
  await expect(plan).toContainText("⊘ used by");
  await page.getByRole("button", { name: "apply" }).click();
  const dialog = page.getByRole("dialog");
  const size = (await dialog.locator("b.p").textContent()) ?? "";
  await expect(dialog.getByRole("button", { name: "delete" })).toBeDisabled();
  await dialog.getByLabel("Confirm size").fill(size);
  await dialog.getByRole("button", { name: "delete" }).click();
  await expect(page.getByRole("status").filter({ hasText: "freed" })).toBeVisible();
});

test("run: a cleaned artifact is struck through", async ({ page, request, theme }) => {
  await pairBrowser(page, request, "sv", "admin");
  let cleaned = "";
  for (const r of await ownerGet<{ run_id: string }[]>(request, "/api/v1/runs?archived=true&limit=50")) {
    const detail = await ownerGet<{ cleaned?: unknown[] }>(request, `/api/v1/runs/${encodeURIComponent(r.run_id)}`);
    if ((detail.cleaned ?? []).length > 0) {
      cleaned = r.run_id;
      break;
    }
  }
  expect(cleaned, "no run with a cleaned artifact: team-light-edit applies a plan first").not.toBe("");
  await page.goto(`/r/${encodeURIComponent(cleaned)}`);
  await expectTheme(page, theme);
  await expect(page.locator("li.cleaned").first()).toContainText("✕");
});
```

- [ ] **Step 8: Document the team demo for UI developers**

Append to `ui/README.md`:

```markdown

## The team demo (phase 3)

`bunx playwright test` also starts `bun e2e/serve-demo.ts --with-team`: `hx demo --with-team`
seeds a fresh home, `home-team` in the run's own directory (`e2e/.runs/run-XXXXXX`; auth on,
owner `sv`, collaborator `alice`, notebook days, paper baselines, cleanable archived runs,
outbox entries), and `hx serve --auth` serves it on a random port (`HX_E2E_TEAM_PORT`). The
specs read that home's local token from its `serve/server.json` to make pairing links and
sign every browser in through `/pair`. Like the other two, the server removes its home when
it stops and kills only processes under it. Projects: `team-light`, `team-dark` (read-only), then `team-light-edit` and
`team-dark-edit` (notebook writes; the cleanup runs once, in `team-light-edit`).
```

- [ ] **Step 9: Run the team projects, then the whole suite**

Run (from `ui/`; Playwright starts and stops its own three hubs on random ports and fresh homes):

```bash
bun run build && bunx playwright test --project team-light --project team-dark --project team-light-edit --project team-dark-edit
```

Expected: `19 passed, 1 skipped` (team.spec.ts 7 tests in each of `team-light` and `team-dark`; team-edit.spec.ts 3 tests in `team-light-edit` and 2 plus 1 skipped in `team-dark-edit`), `0 failed`. Then run `bunx playwright test`: every phase 1b and phase 2 project passes as before, plus the team lines; `0 failed`.

- [ ] **Step 10: Look at the new screens in both themes (no real services)**

Run (repo root, in a second terminal; one shell command: the fresh home and the SSH variables are on each `hx` command line, the port comes from the OS):

```bash
H=/tmp/hx-p3-visual; rm -rf "$H" && mkdir -p "$H" && ID="$(uuidgen | tr -d '-' | tr 'A-Z' 'a-z')" && \
printf '{"environment_id": "%s", "label": "hx-visual-team"}\n' "$ID" > "$H/environment.json" && \
HYPOTHEX_SSH=false HYPOTHEX_SCP=false uv run hx --home "$H" demo --with-team --json > /dev/null && (cd ui && bun run build) && \
P="$(uv run python -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')" && echo "hub port $P, id $ID" && \
HYPOTHEX_SSH=false HYPOTHEX_SCP=false uv run hx --home "$H" serve --auth --port "$P"
```

In a third terminal, from the repo root, check the identity, then make a pairing link for the owner:

```bash
P=<the port the second terminal printed>; ID="$(sed -n 's/.*"environment_id": *"\([^"]*\)".*/\1/p' /tmp/hx-p3-visual/environment.json)"; \
if [ -n "$ID" ] && curl -sf "http://127.0.0.1:$P/.well-known/hypothex/environment" | grep -Fq "\"$ID\""; then \
HYPOTHEX_SSH=false HYPOTHEX_SCP=false uv run hx --home /tmp/hx-p3-visual pair --user sv --scope admin --client browser --url "http://127.0.0.1:$P"; \
else echo "port $P is not the /tmp/hx-p3-visual hub: stop"; fi
```

Open the printed link (only after the identity check passed), press `pair`, then visit `/settings`, `/storage` (dry run only; do not apply here), `/n/<project>`, the toy task's `export ▾`, a run owned by `alice`, and toggle the theme on each. Compare with `docs/mockups/phase3/shot-*`. Expected: every screen readable in both themes; no prose beyond one or two words per label. Stop the server with Ctrl-C.

- [ ] **Step 11: Commit (repo root)**

```bash
git add ui/e2e/paths.ts ui/e2e/serve-demo.ts ui/e2e/fixtures.ts ui/playwright.config.ts ui/e2e/team-fixtures.ts ui/e2e/team.spec.ts ui/e2e/team-edit.spec.ts ui/README.md
git commit -m "test(ui): playwright against hx demo --with-team: pairing, settings, storage, notebook, export, 401"
```

---

### Task 26: Docs: the phase 3 screens in `docs/ui.rst`

**Files:**
- Modify: `docs/ui.rst` (Screens: new bullets before the `⌘K` paragraph; Test: one paragraph at the end)
- Modify: `tests/test_docs_ui.py` (one new test at the end)

**Interfaces:**
- Consumes: the screens of Tasks 5–24 and the e2e setup of Task 25.
- Produces: user docs for `/pair`, `/settings`, `/storage`, `/n/<project>/<day>`, the Task page export and baselines, the Run page owner and cleaned artifacts, `mine`, and the 401 gate; a docs test that names them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_docs_ui.py`:

```python


def test_ui_page_covers_phase_3_screens() -> None:
    page = (DOCS / "ui.rst").read_text()
    for screen in ("Pair", "Settings", "Storage", "Notebook"):
        assert f"**{screen}**" in page, screen
    for text in (
        "/settings",
        "/storage",
        "/n/<project>/<day>",
        "hx pair",
        "export ▾",
        "[[run:<id>]]",
        "dry run",
        "401 · pair this device",
        "HX_E2E_TEAM_PORT",
    ):
        assert text in page, text
```

- [ ] **Step 2: Run the test to verify it fails**

Run (repo root): `uv run pytest tests/test_docs_ui.py -q`
Expected: FAIL: `test_ui_page_covers_phase_3_screens` with `AssertionError: Pair`.

- [ ] **Step 3: Document the screens**

In `docs/ui.rst`, replace

```rst
Press ``⌘K`` (``Ctrl K`` on Linux and Windows) to find a run, task or path.
```

with

```rst
- **Pair** (``/pair#<link>``): opens from the link (or QR code) that ``hx pair`` prints on
  the hub. Name the device and press ``pair``; the browser gets a session you can revoke in
  Settings. The secret is the part after ``#``, which a browser never sends in a URL; the
  page removes it from the address bar at once. A used or expired link reads
  ``✗ link invalid or expired``.
- **Settings** (``/settings``): sessions (``revoke ×``), users (``disable``), add device (a
  one-time link and QR code, valid 5 minutes, never above your own scope), and
  notifications (channels with ``test``, per-project rules, the weekly digest, recent
  sends). A collaborator sees only their own sessions and add device; with auth off, only
  notifications.
- **Storage** (``/storage``, admins only): bytes by project and host, local and remote, the
  largest items, and cleanup. ``dry run`` lists what would go and what is refused
  (``protected``, ``used by <run>``); ``apply`` asks you to type the size back. Only
  artifacts of archived, unstarred runs are ever deleted.
- **Notebook** (``/n/<project>/<day>``): one Markdown page per day, newest first.
  ``[[run:<id>]]`` becomes a chip with the run's status and score. ``+ entry`` adds an
  entry; ``edit`` replaces the whole day, and if someone saved first you see both versions
  and choose ``use theirs`` or ``keep mine``.
- On the **Task** page, ``export ▾`` in the leaderboard's title gives the table as LaTeX
  (booktabs), Markdown or CSV, to copy or download. Paper baselines from
  ``hypothex.yaml`` show under the groups (``◆``), never as best; ``≠v1`` means the paper
  used another metric version. The **Run** page names the run's owner (``@alice``) and
  strikes through artifacts a cleanup deleted. With auth on, the Overview's ``mine`` lists
  only your running runs.
- When the hub answers 401 (no session, or it was revoked), every screen shows
  ``401 · pair this device: hx pair``.

Press ``⌘K`` (``Ctrl K`` on Linux and Windows) to find a run, task or path.
```

Append to the end of `docs/ui.rst`:

```rst

The suite also starts ``hx demo --with-team`` (auth on) in ``home-team`` in the same run
directory, on a random port (``HX_E2E_TEAM_PORT``). Each browser signs in through ``/pair`` with a link the
specs make from that fresh home's own local token; nothing reads ``~/.hypothex`` or talks to
a real Slack, SMTP or Tailscale service.
```

- [ ] **Step 4: Run the tests and build the docs**

Run (repo root): `uv run pytest tests/test_docs_ui.py -q && uv run sphinx-build -W -b html docs /tmp/hx-docs-p3`
Expected: every test in the file passes, including `test_ui_page_covers_phase_3_screens`; Sphinx ends with `build succeeded.` (no warnings, `-W`).

- [ ] **Step 5: Commit (repo root)**

```bash
git add docs/ui.rst tests/test_docs_ui.py
git commit -m "docs: pair, settings, storage, notebook, export and baselines in the web UI page"
```

---

## Done criteria (contract 11, frontend part)

All automated:
1. `bun test` and `bun run typecheck` clean (contract 11.9). Every new component has a test with a fake `fetch`.
2. Playwright smoke of every new screen in both themes against `hx demo --with-team` (contract 11.8): `/pair` (ready, done, invalid), Settings (owner and collaborator), Storage dry run → apply, Notebook edit + 409, Task export menu, baseline rows, run owner and cleaned artifact, 401 gate.
3. `uv run pytest tests/test_docs_ui.py` and `uv run sphinx-build -W` clean.

## Assembly notes

1. **What `/pair` shows before redeeming.** The link carries only `<offer_id>.<secret>` (contract 1.10 `pairing_url`) and no route reads an offer, so the ready state shows the hub and the offer id; user and scope appear after `pair` (`✓ alice · launch`). Contract 10.1 was amended to say so in review round 1 (a public read of an offer would tell anyone with a leaked offer id whom it pairs). The mockup `shot-pair-ready-*` follows this.
2. **The baseline version badge.** The badge is `≠<our version>` (`≠v1` in the tests, `≠v2` in the mockup), and the tooltip says the paper used another version. Contract 10 and 10.1 say `≠v2` since review round 2, so contract, mockup and UI agree; the paper's own version is not on `BaselineRow` and is not needed at a glance.
3. **Paths, not files.** `CleanItem` has no file count, so the confirm dialog counts paths: `412.3 GB · 3 paths · 3 hosts` with this plan's 3-item fixture, `37 paths` in the mockup (6 listed + 31 more; contract 10.1 since review round 2).
4. **Baselines reach the panel through the Task page.** The view query's leaderboard panel `meta` has no `baselines`; the Task page copies `GET .../leaderboard`'s into every leaderboard result (`withBaselines`, Task 23). A leaderboard panel drawn elsewhere shows none. Moving `baselines` into the panel `meta` on the backend would make this step unnecessary.
5. **`@owner` on the Overview.** Running rows carry `owner` (`RunRecord`); backend Task 27 adds `owner` to `TimelineItem`, `IdeaRow` and `FailureRow`, so recent ideas and failures end with `@owner` too (contract 1.12, review round 1). `mine` swaps the Running panel to `GET /api/v1/runs?owner=me&status=running`.
6. **Encodings the backend must accept.** Export `metrics` and `groups` go as comma lists (`metrics=accuracy/value,macro_f1/value`), like the CLI's `--metrics a,b`; the contract names the parameters but not their encoding. The weekly summary is found by its first line naming the ISO week; `render_digest_markdown` (backend Task 18) starts `**2026-W40** · <headline>` and lists task changes as `- <task> before→after ▲ · N runs` (no Markdown table: the UI's renderer has none), and `NOTEBOOK_TEXT` is that exact shape. Any other format still renders, only without the summary block style.
7. **Event-stream transport.** Retain the token baseline fresh-ticket subprotocol flow and clean URL. `/auth/me` 404 never disables transport authentication. Current-generation 401/4401 locks and stops; stale results cannot affect replacement credentials; transient ticket errors use bounded backoff.
8. **Scopes are hints.** The UI hides `storage`, disables Stop/Cancel for non-owners and limits pairing scopes, but every decision is the server's; a 403 shows as an error line. Since review round 2 a run on the hub's own machine needs admin (contract 1.3): a `launch` collaborator who picks `local` in the phase 2 Launch dialog gets the hub's 403 (`runs on this machine need admin; launch on a host`) as an error line, and a host placement works as before. Admin-only reads are never requested for a non-admin, so the browser console stays clean (Playwright's console guard enforces it).
9. **Kept out of scope.** No client function for `POST /api/v1/auth/logout` (no screen has a logout button yet; revoking the session in Settings does it), `GET /api/v1/compare/export` (no compare screen exports yet), or the digest routes (the digest shows up as a notebook entry). Their routes are checked in `types.test.ts`.
10. **Dry run of this plan.** Every task's code was applied, in order, to a copy of the `phase-2` branch as of `1b5de39` (phase 2 Tasks 1–22), with phase 2's final `RunActions.tsx` and Task 28 e2e files taken from the phase 2 plan, and with the phase 3 paths added to a copy of `types.ts` (Task 2 Step 3 needs the backend). Result: `bun test` 858 of 859 pass (the one failure, `tokens.css`, only needs `docs/mockups/ui-v4/` next to the copy), `tsc --noEmit` and `tsc -p e2e` print nothing, and `playwright test --list` shows the 20 team tests (19 run, 1 skipped) and no team spec in the other projects. The dry run found and fixed three plan bugs before this version: `exportMenu.ts` next to `ExportMenu.tsx` clashed on macOS's case-insensitive file system (now `exportFormats.ts`); adding `["export"]` to `RUN_EVENT_INVALIDATES` broke the phase 2 event tests (dropped; since review round 2 the export key lives under `["leaderboard", project]` instead, so run events refresh it with no list change); and testing-library joins a chip's spans with spaces in its accessible name (`01J8…a1b2 ✓ 0.913`).


## Review round 4 integration notes

- Storage continues to display the server's `CleanPlan.refused` and `CleanResult.skipped` reasons. The hub now preflights remote candidates through the owning environment's read-only `/api/v1/storage/check`; the browser does not call that env endpoint. Relative or aliased checkpoint readers therefore appear as `used by <run_id>`, and an unavailable preflight appears as a refusal before confirmation. Task 16 adds a storage regression with both refusal reasons and checks that the confirmation total contains only accepted items.
- The export endpoint returns text. `ExportMenu` previews/copies/downloads that text without interpreting metric values; no `ExportTable` browser schema is introduced. Backend Tasks 10 and 12 add mixed-unit/primary-swap regressions and name scaled columns in the footnote. Existing frontend exact-text copy/download tests remain applicable.
- MCP cookie fallback is resolved in server middleware; private authenticated-credential state is never a frontend model or response field. Deferred sweep triggers likewise remain server-private; existing notification status/events continue to drive the UI after issuance ends.

This historical round-4 handoff is superseded by the final baseline refresh against merged main `54259b0fbfff70b20f612e3e508da37d65efeff5`, including step 9 and the authenticated bootstrap/event interfaces above. During authorized Phase 3 implementation, regenerate OpenAPI types from the assembled backend so the admin-only env preflight appears in the schema. Recheck source anchors if main changes after this review pin; no assembled Phase 3 backend or generated types are claimed here.
