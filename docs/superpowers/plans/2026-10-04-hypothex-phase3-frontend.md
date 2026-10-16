# Hypothex Phase 3 frontend implementation plan — UI v5 refresh

**Status: plan only; refreshed 2026-10-17.** This document supersedes the old frontend implementation blocks in full. Its 26 task numbers retain their feature responsibilities. No Phase 3 runtime is implemented by this refresh. Implementation requires renewed primary Claude LGTM followed by independent adversarial LGTM on the frozen complete plan set. Historical approval on `e10e6ff` is not approval of this refresh. Material changes after either gate require reconfirmation. The concurrent diagnostic is not an implementation gate.

**Source pin:** merged main `f6f130cfa2669bfcccbadcb36282dd5fea881d1f` (PR26 viewport fix atop UI v5), inspected read-only at `/tmp/hx-p3-main-current`. The refresh checkout `/tmp/hx-p3-plans` includes baseline merge `86e03367fd8fde5d4f28b115d2d3ca337083ee27`. Its runtime source equals pinned main. The parent owns the contract and execution tracker; backend and installed-package writers own their plans. This worker owns only this frontend plan. Do not edit or commit in the user's main checkout.

Binding references: [Phase 3 contract](2026-10-04-hypothex-phase3-contract.md), [backend Tasks 1–49](2026-10-04-hypothex-phase3-backend.md), [installed-package acceptance](2026-10-06-hypothex-phase3-package-acceptance.md), [design specification](../specs/2026-09-26-hypothex-design.md), and the current UI v5 specification `docs/superpowers/specs/2026-10-16-hypothex-ui-v5-design.md`. Current main SQLite is schema **4**; Phase 3 ownership advances it to **5**. Frontend neither owns migrations nor invents schema fixtures. Backend Task49 preserves distinct authentic schema-3 and schema-4 upgrade inputs.

## Scope, order, and ownership

| Contract scope | Frontend owner / acceptance | Backend owner |
|---|---|---|
| 1 Notebook and run chips | 18–20, 25 | 8, 29, 43 |
| 2 Paper baselines | 1, 22–23, 25 | 9, 29 |
| 3 Opt-in Slack/SMTP | 9, 12–13, 25 | 13–17, 30 |
| 4 Weekly digest | 1, 12, 18–20, 25 | 18–19, 29 |
| 5 LaTeX/Markdown/CSV export | 2–3, 21–23, 25 | 10–12, 29, 43 |
| 6 Guarded storage and cleanup | 14–17, 24–25 | 20–22, 31, 44 |
| 7 PostgreSQL/Alembic team hub | browser compatibility in 25; package gate | 34–36, 49 |
| 8 Pairing, sessions, scopes | 1–13, 25 | 4–7, 23–28, 39, 41 |
| 9 Tailscale and URL hosts | retain Hosts/launch behavior, 7–8, 25 | 37–39, 42 |
| 10 Stop auth retries until re-pair | 2, 4–5, 8, 25 | 26, 38 |
| 11 Scoped HTTP MCP | UI shares identity semantics; no MCP UI invented | 32–33, 48–49 |
| 12 SDK log_cost | preserve completeness in 1, 18, 23, 25 | 14, 18, 40 |
| 13 Collaborators and ownership | 1, 7–13, 25 | 4–6, 27, 48–49 |

Dependency order: backend contract/models/routes before type generation; frontend 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Then 9 → 10/11/12 → 13, 14 → 15/16 → 17, 18 → 19 → 20, 21/22 → 23, and 24. Tasks 25–26 verify the assembled result; backend Task49 follows all 26 and is mandatory for the installed-wheel handoff. Independent feature groups may proceed only with non-overlapping file ownership and the already-approved integration contract. The final assembler owns shared `models.ts`, `client.ts`, `queries.ts`, `router.tsx` and CSS imports; never overwrite another group's edits with historical full-file replacements.

During the refresh write only this document and external evidence. During later authorized implementation update the parent's tracker with observed checks, do not create a second competing tracker. Use Bun per `~/.claude/nodejs.md`, uv for Python, and the existing test harness. No real SSH, SLURM, Slack, SMTP, Tailscale, provider, external Postgres or `~/.ssh` access. Docker and loopback fakes only. Do not claim a mock or bounded probe proves the assembled application.

## Current architecture and preservation contract

- `ui/src/main.tsx` currently owns QueryClient → AuthGate → LiveUpdates → RouterProvider. `ui/src/router.tsx` imports `shell/AppShell.tsx`; it does not define the shell. Task5 moves routing-aware auth placement into that existing shell and keeps a session-reset subscription at QueryClient lifetime.
- `shell/AppShell.tsx` retains the 216px navigation, collapse preference/shortcut, `TopBar`, `NavTree`, `HubVersion`, `ThemeToggle`, `CommandPalette`, `TooltipHost`, `.app/.nav/.main/.app-page` structure. `TopBar.tsx` owns breadcrumbs, New run and its launched receipt/link. Add navigation there and in NavTree; do not recreate historical `Header.tsx` or a recents-based shell.
- `home/HomePage.tsx` owns status strip, Running now, Hosts, Tasks, Recent runs. `homeModel.ts` derives recent rows, names, failure folding and metric-direction-aware history. Ownership is additive. Preserve the fallback for older hubs without `recent`, and stderr links/retry labels.
- `task/TaskPage.tsx` owns the task header, Charts/Runs/Sweeps/Examples/saved-view tabs, URL-backed selection, task-run data, board and view list. `ChartsTab.tsx`, `ScoresSection.tsx`, `StepMetricsSection.tsx`, `ScoreKeySections.tsx`, `RunsTab.tsx`, `SweepDetail.tsx`, `ViewTab.tsx`, `ViewPanels.tsx` remain their owners. Preserve panel search, smoothing/x controls, hidden/suppressed/compared identities, names, direction and archived-run behavior.
- `run/RunPage.tsx` builds `RunContext`; `RunHeader.tsx` keeps `RunName` editing and `RunActions`, `PropsSidebar.tsx` keeps properties and owner-qualified sweep links, and Overview/Charts/Logs/Files/Examples tabs keep their current contexts. `FileList.tsx` and `files.ts` own the v5 file surfaces. Retained `pages/components/SelectedRun.tsx`, `WhereList.tsx`, and `TrainingDetails.tsx` also need cleanup annotations.
- Retain `/`, `/t/$project/$task`, `/t/$project/$task/edit/$view`, `/r/$runId`, `/x/$a/$b`, `/s/$project/$id` (redirect into task Sweeps), `/hosts`, `/queue`. Add `/pair`, `/settings`, `/storage`, `/n/$project`, `/n/$project/$day`. Keep current typed search validation and string-preserving parse/stringify for filter/group/sort/hide/sup/col, run tab/log/example, view and sweep IDs. No old page replacement under `pages/Task.tsx`, `pages/Run.tsx` or `pages/Overview.tsx`.
- Preserve exact per-run evaluation binding, `require_bound` comparisons, metric/key selection, lower-is-better ranking, `metric_versions`, key directions and typed `ViewQueryBody`. Paper references are never runs, seed groups, identity colours, Pareto points, best candidates or statistical comparisons.
- Preserve bounded metric reads (`max_points` 2–500, explicit names chunked at most 100), run-metric query keys, current paging/cancellation, durable sweep issuance states/events/polling and explicit resume. Do not replace launch/seed machinery or infer issuance completion from observed counts.
- Preserve existing cost fields and uncertainty. A sweep subtotal is a total only when `cost_complete === true`; old/false/null data remains unknown. Numeric zero does not prove completeness. Do not reprice old records.

Mockups under `docs/mockups/phase3` specify feature states, scientific meaning and information content. Their old serif header and lettered figures are not the UI v5 layout. Use current Geist tokens, chrome `Panel`, `PanelSection`, buttons/menus and focus behavior. Port the data and states into v5; do not reintroduce old global CSS. Existing mockup totals are illustrative, not arithmetic test oracles. The unavailable unknown-cost screenshot is nonblocking; its explicit textual acceptance remains required.

## Preflight and source compatibility

Before implementation, record the implementation HEAD and verify ancestry and the source inventory at the end of this document. Read any applicable AGENTS.md, relevant lessons and Bun guidance. The source inventory records real symbols, line anchors and blob IDs at the pin; lines are navigation aids, not patch offsets. New Phase 3 files are intentionally absent.

```sh
# From the isolated implementation checkout. These commands are read-only.
git rev-parse HEAD
git merge-base --is-ancestor f6f130cfa2669bfcccbadcb36282dd5fea881d1f HEAD
git status --short
git diff f6f130cfa2669bfcccbadcb36282dd5fea881d1f -- ui/src ui/test ui/e2e ui/package.json ui/bun.lock
rg -n 'AppShell|TaskPage|RunPage|SweepRedirect|parseSearch|stringifySearch' ui/src/router.tsx
rg -n 'taskRuns|renameRun|require_bound|max_points' ui/src/api/{client,queries,models}.ts
```

An ancestry pass alone is insufficient: inspect later changes and refresh material anchors before implementation/review. Baseline source comparison must happen before Phase 3 implementation edits; afterward expected Phase 3 diffs are not mistaken for baseline drift. Regenerate OpenAPI from the assembled backend, never hand-edit `types.ts` to suppress errors. For plan refresh the source probe and route/parser/fixture arithmetic checks are evidence only; do not run or report planned component tests as though components exist.

## Shared implementation and test rules

1. Each task below specifies owned paths, dependencies, implementation steps and regression assertions. Add meaningful tests in the existing `ui/test` hierarchy; use existing happy-dom setup and `ui/test/pages/helpers.tsx` / render helpers. Never bake an old suite's test count into an expected result.
2. Baseline `api/auth.ts` is the only transport credential store. Do not add `locked: boolean` state beside it, persist credentials in localStorage, or put credentials in query keys, URLs, snapshots or browser artifacts. A pairing secret may be transiently held only until redemption; no analytics/console output.
3. Every user intent captures credential generation and immutable arguments when submitted. Retry retains that intent's command_id and credential. A superseded request, retry, mutation onSuccess, clipboard completion or navigation has no side effects. `AbortError` is non-retryable. Preserve this for existing `useAction`, `LaunchDialog`, seed/sweep flows, rename and view-save mutations, not only new actions.
4. Tests should await the affected request/render explicitly; do not pass an assertion on an empty page before fetch settles. Inspect structured request method/path/query/body, including selected primary and command_id. Restore fake fetch, clock, clipboard, URL and auth state after each test.
5. Scope hints disable controls and explain why; the server remains authoritative. Read-only visits issue no admin-only reads. Unknown principal stays pending/fails closed. Auth-off fallback preserves root token authentication. A scoped endpoint 404 does not mean unauthenticated API access is allowed.
6. Every new screen has loading, empty, partial, error and permission states where meaningful. Use semantic headings/regions and accessible names in the task table below. Dialogs trap focus, close on Escape when no destructive action is in progress, and restore focus. Both themes and narrow layouts retain usable controls and readable paths.

## Group 1: Models, transport, queries and events

### Task 1: Phase 3 models, fixtures and complete/unknown sweep cost

**Depends:** contract §§1.2–1.10; backend 4, 8–9, 18, 20–22, 25, 27. **Modify:** `ui/src/api/models.ts`, `ui/src/pages/components/SweepModel.ts`, `ui/src/task/SweepDetail.tsx`; relevant existing fixtures/tests. **Create:** `ui/test/phase3/fixtures.ts`, `ui/test/phase3/models.test.ts`.

- Add exact wire types: Scope, Principal (the `/auth/me` envelope, including auth, scopes, client, session_id and public_url), SessionRow, UserRow, PairingOffer (offer_id/url/expires_at/qr), PairResult (browser user/scope/scopes/session_id, no token), ExportOptions/ExportFormat/NoiseMode, RunChip, NotebookDay, notebook day list, BaselineRow, ProjectRule/NotifyStatus/OutboxEntry/Digest settings and Digest/TaskChange, StorageItem/Report, CleanPolicy/Item/Plan/Result/CleanedArtifact. Copy field meanings from the contract; do not confuse pairing store `id` with API `offer_id` or `User.role` with session `scope`.
- Add optional `owner?: string | null` to RunRecord, RecentRun, TaskRun and retained TimelineItem/IdeaRow/FailureRow; `RunsQuery.owner?: string`; `RunDetail.cleaned?: CleanedArtifact[]` with `CleanedArtifact.environment_id?: string | null` (absent/null legacy unknown, new backend entries always populated); `Leaderboard.baselines?: BaselineRow[]`; `SweepSummary.cost_complete?: boolean`. Existing `name`, derived_name/renamed, score/key direction, bound evaluation, issuance, `gpu_pricing_complete` and `LeaderboardRow.cost_complete` fields remain intact.
- Backend27 must populate RecentRun and TaskRun owners, not merely annotate TypeScript. Do not infer owner from created_by or invent an owner for a mixed group. The contract owner must incorporate these current-main serializers.
- Extend `sweepStats` input with `costComplete`; current `task/SweepDetail.tsx` must pass `summary.cost_complete` at its actual call site. For true show recorded total; otherwise `Cost unknown` plus a recorded-subtotal tooltip/text (including zero when the contract requires it). Preserve progress, counts, issuance and all other stat cells.
- Fixtures must be internally consistent. A cleanup plan with bytes `[96_400_000_000, 74_000_000_000, 241_900_000_000]` totals `412_300_000_000`; deleting first two frees `170_400_000_000`, with the third skipped. Do not reuse the old contradictory `409.8 GB` result for that list. Complete and incomplete costs are separately declared, never inferred from mockup labels.

**Verify:** compile-time exact shapes via `satisfies` and typecheck; old fixture compatibility; owner absent/null; both baseline keys; zero, complete, false/missing/null legacy, empty and mixed sweep cost cases through both helper and real SweepDetail component. Run existing `ui/test/pages/sweepStats.test.ts`, sweep model/fixtures and `ui/test/task/sweepDetail.test.tsx` with actual filenames checked by `rg --files`.

### Task 2: Typed API additions on the existing credential transport

**Depends:** 1; backend23–31 endpoints assembled. **Modify:** `api/client.ts`, `api/auth.ts` only as necessary, generated `api/types.ts`, `api/queries.ts` retry predicate if needed. **Tests:** extend `ui/test/api` client/auth contracts; add text/export/pair cases.

- Keep `ROUTES satisfies Record<string, keyof paths>`, encoded params and structured queries. Run `bun --cwd ui run gen:types` after the backend is available. Add routes and typed client methods for me, pair, pairings, sessions/revoke, users/disable, notebook list/day/append/replace, task export, notify/status/test, storage/report/plan/apply. Existing taskRuns, renameRun, host routes, stop_queued callers and launch/sweep transports survive.
- Every JSON **and text** request uses the same captured credential, combined AbortSignal, `credentials: "same-origin"`, bearer selection, no response logging, pre/post-await current-generation checks, structured ApiError handling and current-401 lock. Factor a private common response transport rather than duplicating security logic. Text mode returns raw response text only on success; failed text routes still parse structured errors. Preserve ApiError.body for notebook conflicts.
- Public browser pair sends `{offer_id, secret, device, client: "browser"}` without the old bearer. Give this call its own captured generation/abort checks and same-origin cookies; it must work while locked. On success the caller selects cookie mode via `auth.select(null)` and then validates it. Do not call `auth.accept` for the previous bearer generation. Never return or store a browser token.
- Retain `websocketTicket()` and `wsUrl()` behavior: ticket endpoint at one path, clean ws URL, fixed-plus-ticket subprotocols, strict ticket response validation, null only for intentional no-auth response. `/auth/me` 404 must not switch ticket auth off.
- Add `owner` to the current RunsQuery flow, retaining q/search, cursor pair, environment_id and archived filters. `exportTask(project, task, opts, signal)` includes primary and comma-joined `metrics`/`groups` parameters as backend29 parses them (the existing leaderboard endpoint separately retains repeated `metric` parameters); no bare protected download links.
- Check unused API additions (logout, compare/export, digest GET/send) exist in generated paths; they need no new screen. Do not extend scope with unsolicited Settings editors or a compare-export UI.

**Verify:** bearer and cookie JSON/text success; parsed 400/403/409/413/503; current 401 locks once; stale 401 does not lock new session; credential change aborts before/after body parsing; pairing omits Authorization even with a saved bearer; text export cannot issue navigation; `AbortError` never retries; special characters and comma-joined export metrics/groups encoded, while existing repeated leaderboard metrics remain unchanged; root-token + me404 still requires the token and a WS ticket. Run client/auth/type-generation tests and typecheck.

### Task 3: Query keys, hooks and mutation invalidation

**Depends:** 1–2. **Modify:** `api/queries.ts`; **tests:** existing query suite plus phase3 keys/hooks tests.

- Add `queryKeys.me() = ["auth", "me"]`, sessions/user filters below `["auth","sessions"]`, users below `["auth","users"]`; notebook `["notebook", project, "days"]` and `["notebook", project, "day", day]` (including literal `today`); notify `["notify"]`; storage `["storage", project ?? null, remote]`; export `["leaderboard", project, task, "export", normalizedOptions]`. Include primary, format, noise, digits and every effective option in export identity. Do not use tokens as keys.
- Keep current hierarchical families exactly, especially `["taskRuns", project, task, archived]`, `["views","query",project,task,body]`, run metric names/maxPoints and require_bound compare keys. Do not replace them with historical approximations.
- Add hooks `useMe`, `useSessions`, `useUsers`, `useNotebookDays`, `useNotebookDay`, `useNotify`, `useStorage`, `useExport`. Respect enabled/read options and signals. Me404 returns a distinct `legacy` scoped-feature-unavailable capability result after transport validation, permitting existing pre-Phase3 actions but disabling absent Phase3 reads/links; an actual me response with auth off is supported local-admin mode. In both cases keep transport auth; 401 propagates to the lock. No other failure masquerades as auth off. Storage staleTime 60s; export uses no placeholderData and can refetch on run invalidation.
- Keep `clearSessionQueries` cancel/clear plus last-known-host and lost-reason side caches; also clear notebook editor attribution (Task4). Mutations use current-intent guards before cache updates. Own-session revoke/logout/disable triggers lock/reset only for current intent, other revokes invalidate sessions/users. Notebook writes invalidate list, explicit day and today; apply invalidates storage plus run/runs/taskRuns and relevant derived families.
- Export stays under leaderboard so run/mirror invalidation reaches it. Known export text is not actionable during a refetch/error, even when its key has not changed.

**Verify:** unequal primary/options produce unequal keys; owner-filter requests do not collide; no admin fetch until enabled; me404 versus other errors; notebook invalidation includes today; cleaned-artifact invalidation reaches taskRuns; stale mutation callback does not refill a cleared cache. Preserve current shouldRetry and host-cache regressions, with AbortError suppression added if absent.

### Task 4: Phase 3 event invalidation, 4401 and notebook editors

**Depends:** 3. **Modify:** `api/events.ts`; **create:** `api/notebookEditors.ts`; **tests:** existing events/stream suite plus notebook editor tests.

- Extend `keysForEvent` before generic run handling: notebook.updated narrows project notebook and records last observed `{project, day, author, at}`; digest.sent refreshes that project's notebook; notify.* refreshes notify; auth.* refreshes auth me/sessions/users; storage.* refreshes storage and run/runs/taskRuns; run.artifacts_cleaned retains normal run invalidations **and** storage. Preserve sweep.issuance and mirror handling, project narrowing, deduplication and a single batch invalidation.
- Notebook editor attribution is a bounded in-memory per-project/day store with subscription and clear/reset; do not persist it as identity proof. Missing attribution displays time only. Validate payload strings before indexing. Clear on credential reset so a new user cannot see old attribution.
- Keep EventStream ticket acquisition for every connect, generation cancellation, head-first startup, validated replay cursor, 3/4/8/16s transient backoff, focus/stale invalidations, batched events and the one shared stream. A current 4401 locks and cancels retry/tickets; an old socket cannot lock the new credential. Malformed protocol/ticket errors stay safe. Revocation must not become a permanent auto-reconnect loop.

**Verify:** exact keys for each new event, project isolation and batch union; storage run update refreshes names/taskRuns; editor reset; no duplicate streams under StrictMode/remount; fresh ticket on retry; head timeout fallback; stale socket 4401 ignored, current 4401 stops every reconnect until re-pair/select; late head/ticket/success completion ignored after reset. Backend26 owns revocation tests and must use positive async timeout (not `wait_for(..., timeout=0)`).

## Group 2: Gate, pairing, navigation and ownership

### Task 5: Auth gate around the existing v5 shell

**Depends:** 2–4. **Modify:** `main.tsx`, `api/AuthGate.tsx`, `shell/AppShell.tsx`; **create:** `api/SessionReset.tsx` and scoped session context only if needed. **Tests:** shell/gate integration under the real router.

- Main becomes QueryClientProvider → SessionReset → RouterProvider. SessionReset registers the one QueryClient-lifetime auth.onReset callback; clear queries/side caches/cursor at reset even while `/pair` is mounted. Remove the now-duplicate reset subscription from AuthGate.
- Existing AppShell becomes a routing-aware outer component: pair route renders only Outlet; every other route renders AuthGate → LiveUpdates → the retained authenticated shell frame. Router imports this owner unchanged. Hooks that read projects/hosts/names, NavTree and TopBar must live inside the authenticated frame so pair issues no protected requests.
- Preserve the existing token form (password, no autocomplete, Unlock) for default root-token mode. Add the locked pairing hint `401 · pair this device: hx pair` with a Copy command control. Never replace root auth with a scoped-only gate. Validate via the protected projects read, then resolve me for scope-aware pages. Unknown/unavailable scopes cannot authorize writes before transport validation.
- Handle validating/transient errors without repeatedly mounting protected queries. Initial validation once per selected generation; StrictMode must not lock a successful credential due to an obsolete duplicate validation. Re-pair success makes a fresh generation and uses the same validation path.

**Verify:** direct /settings and /storage first render gate then frame after real validation; `/pair` has neither Navigation nor TopBar, me/projects/hosts fetch nor WS; pair reset still empties all caches; existing theme/collapse/command palette/tooltip behavior survives ordinary route changes. Rejected credential never flashes previous user's data.

### Task 6: Public pairing page `/pair`

**Depends:** 5. **Create:** `pages/Pair.tsx`, scoped `pages/pair.css`; **modify:** router route list; **tests:** `ui/test/phase3/Pair.test.tsx` and later auth browser coverage.

- Read `#<offer_id>.<secret>` once into transient state; validate expected p_ ID and secret syntax before POST. Immediately `history.replaceState` to the same path/search without fragment, including malformed links. StrictMode must retain the first captured value rather than re-reading the now-empty hash. Clear held secret on unmount, success or terminal invalid-link response; a transient network error may retain it only in component memory for an explicit retry while the page stays open.
- Render compact shared brand, hub origin and truncated offer ID; labelled `Device name` and `Pair`. No claimed user/scope/countdown before redemption: no public offer inspection exists. Device has a sensible editable default, bounded/trimmed according to backend validation.
- Submit once, freeze input/intent until settled, no retry storm. Success shows returned user and scope plus `Home` link after switching to cookie mode. Invalid/expired/used/wrong secret share the contract error; 429 is a bounded visible error, no guessed timer unless returned. No session secret/QR/old bearer appears in success DOM or logs.
- Home navigation re-enters the normal validation path; stale pair completion after a different credential/route cannot overwrite the selected session.

**Verify:** valid, empty/malformed, expired/used, double-click, rejection and retry; fragment stripped before fetch; no me/WS before redemption; old bearer absent; browser result omits token; cookie works on subsequent protected read; stale completion ignored. Test clipboard only for harmless command, never assert secret values in stored snapshots.

### Task 7: v5 navigation, principal chip, routes and scope helpers

**Depends:** 5–6. **Modify:** `shell/TopBar.tsx`, `shell/NavTree.tsx`, `pages/components/links.tsx`, `router.tsx`; **create:** `pages/components/ScopeHint.tsx` / `api/scopes.ts` as small shared helpers; **tests:** shell/nav/link/router tests.

- Add notebook under each project in NavTree, global Settings and admin-only Storage, and the current project's Notebook shortcut in TopBar when known. Current run route project comes from its cached run detail; do not create a duplicate run query or historical recents store. Keep New run and launched-run receipts, breadcrumbs, collapse and command palette.
- Auth-on chip `@user` with r/l/a glyph and accessible scope label; auth off no chip. `hasScope` explicitly orders read < launch < admin; pending/error principal yields false. Explicit validated legacy capability permits existing actions but has no Phase3 endpoints; hide Storage/device/notify reads in that case rather than issuing404s. ScopeHint explains disabled mutations in a tooltip/accessible description. Settings is available to every authenticated reader; Storage only admins/auth-off admin.
- Add typed href builders for settings/storage/pair/notebook(project, day?). Dayless notebook means hub today, not browser date. Add breadcrumb cases for new pages without disturbing task/view/run names.
- Replace broad isAppPath prefix regex with exact path-shape admission aligned with backend23's static classifier. Admit root; t/p/t with optional `/edit/view`; r/id; x/a/b; s/p/id; hosts; queue; settings; storage; n/project with optional single day. Accept the same optional trailing slash as backend. Reject extra segments, `/api`, `/mcp`, `/docs`, `/openapi.json`, unknown files and malformed encoded separators as backend specifies. Pair is a server-public SPA path but a **full-load navigation exception** in both `AppLink` and delegated plain-link interception, preserving fragment capture. Do not conflate public-path admission with all client interception.
- Keep normal modified clicks, download/target links, external origins and nested prevented clicks untouched. Keep current search parsing and sweep redirect.

**Verify:** route table with valid/invalid/trailing-slash cases shared conceptually with backend; direct links work behind token and scoped guards; pair links do not get swallowed by router interception; current `/hosts`, `/queue`, saved-view editor and /s redirect survive; repeated route changes do not duplicate command palette or stream. Generated hrefs encode project/day/run identifiers.

### Task 8: Run ownership and Mine on current Home/workspaces

**Depends:** 1, 3, 7; backend27. **Modify:** `home/HomePage.tsx`, `home/homeModel.ts`, `run/RunHeader.tsx`, `run/PropsSidebar.tsx`, `run/RunName.tsx`, `pages/components/RunActions.tsx`, `pages/components/useAction.ts`, current task/bulk/queue/launch mutation surfaces; add ownership helper/tests.

- Render `@owner` beside status/launcher without replacing created_by. Home recent/fallback rows carry real owner; failure folding must not falsely label mixed owners as one (include owner in group key or display distinct owners). Task run rows/selected details use TaskRun.owner; preserve display names and rename/reset-to-derived behavior.
- Add `Mine` aria-pressed in **Running now**. It enables the existing runs query `{owner:"me", status:"running"}`; unselected uses overview.running. Label/pending/error belongs to that section. Keep global status strip, Hosts, Tasks and Recent runs global. Preserve run labels/progress from summary when available and a valid name fallback. Hide toggle auth off; do not leave a previous user's query active after reset.
- Central permission helper: stop/archive/cancel_queued require launch plus same owner or admin; unknown/legacy null owner is admin-only. Rename/tags/notes/reevaluate/view writes need launch; rerun/reinfer/local launch additionally obey server local-execution admin rule. New-run dialog disables local target for launch-only user while keeping verified shared host targets. No forged owner/created_by from the UI.
- Apply to real current surfaces: RunActions queued Cancel, More actions Stop/Archive/Re-infer/Re-evaluate, RunName, task RunsTab bulk archive, QueuePage cancellation, SweepDetail cancel/extend/resume and launch/seed flows. Preserve stop double-click arm timeout, reachability/infer-stage conditions, all command IDs, per-intent generation and structured failures. Do not replace existing conditions with scope alone. Host auth-error UI shows re-pair instruction and does not blindly repeat reconnect.
- Audit `useAction` plus direct mutations (`useRenameRun`, `useSaveView`, LaunchDialog and seeds) for stale callbacks/retries; carry generation in immutable mutation variables/context, guard sends **and** side effects. For multi-run `renameEach`, pass the original credential/intent through every target and ordinary failure rollback; a superseded generation must not issue a rollback under the new user. Preserve normal partial-failure rollback accounting within the same credential. Unmount resets local editor state.

**Verify:** alice own versus sv/legacy run; admin all; read only; auth off baseline; grouped mixed owners; Mine exact request and one-section behavior; disabled controls send no request; server403 displays useful error without locking; current401 locks; switching credentials during delayed rename/launch/save prevents navigation/cache/refetch/receipt changes and prevents multi-run rename continuation/rollback POSTs under the replacement user. Existing v5 rename, queue, remote run, task selection, launch and durable sweep suites remain green.

## Group 3: Settings

### Task 9: Settings presentation model

**Depends:** 1, 7. **Create:** `pages/settings/model.ts`, `ui/test/phase3/settingsModel.test.ts`.

Implement pure typed helpers for scope order/glyphs, client labels, active/revoked/expired session state at an injected time, relative last-seen text, current-session identification, active-session counts by user, valid user names, allowed offer scopes, notification event/state glyphs and digest schedule. Keep API states distinct: sending/pending/sent/failed are not the same; revoked and expired sessions remain inspectable.

- Existing users' role constrains offer scope as well as issuer scope; new user role is the chosen offer scope within issuer ceiling. Disabled users cannot be re-created by choosing `+ new`; reserved names remain reserved. A collaborator can issue only for self and at or below held scope. Confirm exact server validation for an existing user's higher requested scope and mirror its rejection/ceiling; never assert that alice launch can receive admin.
- Unknown dates/invalid data render a neutral marker without a misleading zero-age count. Auth off hides scoped user/session/device sections but permits local-admin notification view. No principal or secret value is serialized by these helpers.

**Verify:** every scope pair; read versus launch versus admin issuer; enabled/disabled user; existing role clamp; current session; expired boundary; invalid dates; each outbox state; optional channel/default/digest configuration. Use deterministic times.

### Task 10: Sessions and Users sections

**Depends:** 3, 8–9. **Create:** `pages/settings/Sessions.tsx`, `pages/settings/Users.tsx`, matching tests.

- Use v5 PanelSection headings `Sessions` / `Users`, semantic tables and stable action names such as `Revoke <device>` and `Disable <user>`. Session columns: device, user, client, scope, last seen, expiry/revoked state and action. Admin sees all; collaborator sees own only. Mark current session explicitly.
- Revoke with existing useAction command-intent behavior. On success refresh relevant auth families; revoking current session locks immediately and clears cached data. Do not let a stale completion lock a newer user. Disable user shows server safeguards/errors (including last-admin protection), updates users/sessions and invalidates me if relevant.
- Users mounts only for confirmed admin; session queries begin only when scoped auth is on. Do not issue forbidden requests and hide their errors as empty tables. Keep pending/error rows local to their section and prevent duplicate sends.

**Verify:** admin/all versus self-only, current revoke lock, other revoke refresh, disabled controls, role change response, conflict/403 error, no admin requests for launch/read, auth-off absence, delayed completion across credential reset. Read-only UI can revoke its own session per contract.

### Task 11: Add device with bounded offers

**Depends:** 2, 9–10. **Create:** `pages/settings/AddDevice.tsx`, matching tests.

- Section `Add device`: label Device scope and User with current/existing/new options as authorized; new user text follows USER_NAME. Offer POST snapshots user/new_user/scope/ttl and cannot widen scope. Existing user picker excludes disabled accounts but keeps their names reserved for validation.
- Show QR as escaped plain UTF-8 text in a pre, returned URL in a selectable field plus Copy, exact returned expiry countdown at most five minutes, and the **submitted** user/scope label even if controls have since changed. No guessed principal from URL. Expired offer disables copy/use and supports creating a fresh offer; keep previous offer from being shown with new labels during request.
- QR/URL necessarily contain the one-time secret while the offer is active; do not cache in QueryClient, storage, console, snapshots or traces. Clear on unmount/reset/expiry. Tests capture values transiently rather than saving them to artifacts. A new offer is a new intent, not a retry of an old command receipt.

**Verify:** requested user/scope frozen during delayed response; narrower scopes; disabled/reserved user; invalid username; 403; exact expiry with fake clock; clipboard failure; no intervals after unmount; credential replacement clears offer. Screen still keyboard-usable without QR scanning.

### Task 12: Read-only Notifications and test delivery

**Depends:** 3, 9. **Create:** `pages/settings/Notifications.tsx`, matching tests; backend30 and fake channels required for integration.

- Confirmed admin only. Section `Notifications` includes Slack/email configured/set indicators with environment **variable names**, not values; email host/to as allowed; per-project events/channels/min_seconds/fold_sweeps; default opt-in state; digest weekday/hour/timezone/save-to-notebook; Recent sends table with timestamp, run link, channel, status, attempts and redacted error_class.
- Show project opt-in accurately: missing project and missing default is off, empty events means no run event notices. Expose `Test Slack` / `Test email` only when configured appropriately; response `{ok:false,error_class}` is a failure even on HTTP200. Send only when explicitly clicked; mounting the screen never sends a message.
- Settings displays status/config; changing secrets/rules remains CLI/config-file workflow. Do not add unapproved UI configuration writes or real delivery acceptance. Render digest cost information only through the completeness-aware shared display when present.

**Verify:** unset/configured/available differences, project/default off and override, all outbox states, HTTP200 false, pending/double-click, real API error, no secrets in DOM/snapshot, notify event refetch, no notify request for non-admin.

### Task 13: Settings page and `/settings`

**Depends:** 10–12. **Create:** `pages/Settings.tsx`, scoped `pages/settings/settings.css`; **modify:** router; matching integration tests.

Use h1 `Settings`, compact facts and v5 sections, with no old letter prefixes. Admin: Sessions, Users, Add device, Notifications. Auth-on collaborator/read: own Sessions and Add device within scope. Supported auth off: Notifications plus concise scoped-auth-off status; legacy me404: unavailable status with no Phase3 queries; no fabricated `@local` identity chip. Capability loading/error comes before permission-dependent children. A me404 compatibility path continues only after root transport validation.

**Verify:** route refresh/direct link; exact section set for admin/launch/read/auth-off; no forbidden network calls; independent section errors; scope switch clears old sections/data; narrow and both-theme layout. Settings navigation and page h1 are distinct locators.

## Group 4: Storage

### Task 14: Storage presentation model and exact confirmation

**Depends:** 1; backend20–22. **Create:** `pages/storage/model.ts`, matching tests.

- Pure typed helpers: integer byte formatting, project/host/kind summaries, largest item sorting, age/state labels, local-vs-remote split using authoritative environment identity, plan expiry, policy parsing, exact confirmation and result summary. Decimal units may be used for display but never converted back to deletion bytes.
- `Confirm bytes` accepts only a decimal safe nonnegative integer equal to `plan.total_bytes`; no exponent, sign, decimal, NaN, Infinity, unsafe integer or rounded GB. Require valid safe integer plan total and valid future expiry. Use a strict digits regex before Number conversion. Display both human size and exact bytes next to the input; copyable exact text is harmless.
- `older_than_days` is a finite nonnegative safe integer; `archived:true` is fixed. Kinds is nonempty; `include_pulled` distinct from a recorded artifact kind; project and remote options carry through explicitly. UI never computes eligibility from archived/starred alone or substitutes report totals for an actual plan.
- Report summary maps are authoritative; if deriving splits from items, require a full internally consistent item fixture. Do not sum the truncated Largest display rows or double count physical bytes. Show report errors alongside partial totals.

**Verify:** bytes boundary/format and zero; invalid policy values; exact `412300000000` accepted but `412.3`, exponent and `412299999999` rejected; expiry boundary; unsorted items; same host label/different env; partial report; consistent plan/result arithmetic. Negative/unsafe wire values fail closed for Apply.

### Task 15: Bytes by project/host and Largest items

**Depends:** 3, 14. **Create:** `pages/storage/StorageBars.tsx`, `pages/storage/LargestItems.tsx`, matching tests.

- v5 sections `By project`, `By host`, `Largest`; totals right-aligned. Bars include local/remote distinction and accessible text values, with no division by zero. Legend identifies locality by environment identity; remote uncertainty/errors stay visible.
- Largest table shows run link, host, kind, path (wrapping/truncation with full title), bytes, age, archived/starred/exists markers. Stable sort by bytes then deterministic identity; bounded initially with explicit more/paging. Do not create one run-detail fetch per storage item or turn paths into unauthenticated file URLs.
- Rows identify actual environment/host; inaccessible host report does not become 0 bytes. Never label report subtotal as complete when errors exist.

**Verify:** totals and accessible bar values; zero/empty, many rows, partial host failure, same basename/different path, narrow layout, sorting/pagination, no N+1 requests. Display retains every refusal reason via the cleanup section separately.

### Task 16: Dry run, frozen plan, typed confirmation and Apply

**Depends:** 3, 14–15. **Create:** `pages/storage/Clean.tsx`, matching tests.

1. Fixed archived/unstarred/ended policy explanation; `Older than` days, kind toggles and include-pulled; `Dry run` POST uses a snapshot and command_id. Policy edit invalidates/discards the visible plan and result; it cannot silently retarget an open confirmation.
2. Display returned plan_id, policy, created/expires times, candidates (`Plan items` table) with run/host/path/bytes/reason, refused items with reasons, exact total and counts. Apply unavailable with no candidate, invalid/missing total, expired plan, policy mismatch, pending request or non-admin principal. Never synthesize a plan ID/client-side eligible list.
3. `Apply` opens labelled dialog `Apply cleanup` with a frozen plan snapshot, human size, **exact bytes**, path/host counts, refused count and `Confirm bytes`. Disable policy changes/new Dry run while dialog open (or close/discard dialog before accepting them). Timer rechecks expiry inside the dialog. Final handler rechecks identity, policy, expiry, exact bytes and generation, then sends that plan_id with its exact raw total.
4. In-flight Apply disables duplicate submission/close that would suggest cancellation of a server deletion. HTTP/network retry reuses the intent's command_id and plan identity; a new dry run creates a new intent. A refused/expired plan requires new dry run, no automatic destructive retry with a new plan.
5. Render actual freed_bytes plus deleted/skipped/errors individually. Partial failure is not green unconditional success; every skip/error explains path/host/reason. Invalidate report and run detail/runs/taskRuns after response; cleanup never changes run status or scores. A successful response for a stale credential must not show results or clear another user's form.

**Verify:** no apply before dry run; wrong/rounded/unsafe total; negative age; plan expires while dialog open; edit policy after plan; new plan cannot replace confirmation target; delayed response; double-click; stale generation; skipped changed item, protected item, unreachable host and partial success; re-use versus fresh command IDs. The concrete fixture in Task1 must produce 170.4GB freed and one skip. Backend22 independently proves symlink-race protection; the UI's dry-run gate is not deletion security.

### Task 17: Storage page and `/storage`

**Depends:** 15–16. **Create:** `pages/Storage.tsx`, scoped `pages/storage/storage.css`; **modify:** router; matching integration tests.

Use h1 `Storage`, project filter and remote toggle if exposed, summary total + partial-error badge, By project/By host/Largest/Clean sections. `useStorage` starts only for confirmed admin/auth-off admin. Include environment identity using the shared `useHubEnvironment`, not a duplicate descriptor fetch. Initial loading/error renders without stale action controls; stale report may remain visible with error but cannot supply a new cleanup plan.

**Verify:** route before/after auth; non-admin gets permission state without storage fetch; filter/scope/reset changes discard old plan; storage events refresh; zero/partial/empty reports; exact confirmation integration; narrow and both-theme screenshots. No report request or destructive action is needed merely to expose a navigation link to unauthorized users.

## Group 5: Notebook

### Task 18: Notebook parsing, run chips, safe Markdown and bounded diff

**Depends:** 1, 7; backend8/18. **Create:** `pages/notebook/model.ts`, `pages/notebook/RunChips.tsx`; **modify:** retained `panels/Markdown.tsx` inline extension; matching model/Markdown tests.

- Parse stamped `## <ISO> — <author>` entries while retaining all free text before the first stamp and entirely unstamped documents. Display compact time and `human:alice` → `@alice`; never rewrite the stored text. Identify weekly-summary entries by their actual ISO-week marker; render the digest as one block with counts/task changes/top notes, including unknown-cost text verbatim.
- Match exactly `\[\[run:([A-Za-z0-9][A-Za-z0-9_.-]{0,79})\]\]`; split text into ordinary/run-link segments without a mutable global-regex lastIndex bug. Resolve **only** from NotebookDay.runs. Known chips use API label, run status and primary; unknown chip is disabled `? id`. No per-chip fetch or made-up status/metric/name.
- Add optional inline renderer to safe Markdown for paragraph/list/heading inline text. Existing links/formatting/code remain safe. Fenced and inline code must stay literal, no chip replacement inside code; no `dangerouslySetInnerHTML`, script URLs or interpretation of raw HTML. Use normal AppLink only for validated known run IDs.
- Implement side-by-side `lineDiff(theirs,mine)` with bounded work (e.g. LCS only while line product <=4,000,000, deterministic linear fallback above). Preserve unchanged/inserted/deleted/changed lines and empty text. `conflictOf` checks ApiError status/type plus required NotebookDay fields and same requested project/day before using current; a malformed409 stays an error, not a cast to valid state.
- `withToday(days, hubToday)` keeps hub date first even if no file exists; browser UTC/local date is never the write target. Editor attribution is only the observed event store, not a fabricated current author.

**Verify:** preamble/stamped/free text; duplicate/run-link bounds; unknown/missing chips; XSS/unsafe URLs/code literals; chip label comes verbatim from NotebookDay.runs (the contract's hypothesis-clause/id label, not a browser-generated name); large diff bounded, add/delete/empty; malformed conflict object; timezone around midnight; weekly complete `$86.50` versus `Cost unknown · $0.25 recorded` with no synthesized known total.

### Task 19: Day view, append, edit and 409 recovery

**Depends:** 3–4, 18. **Create:** `pages/notebook/DayView.tsx`, scoped styles, matching tests.

- Day header shows explicit day, entry/run counts and `Edit day`. View has stamps, Markdown/chips, weekly block, labelled `New entry`, `Add entry`. Append uses explicit resolved hub day and launch permission, freezes submitted text/readOnly while pending, retains text on failure, clears only the submitted text on current success. Append is serialized by server and has no whole-file conflict.
- On Edit capture `{project, day, text, base_hash, generation}` once. Day text textarea, `Save` and `Cancel`. Live query invalidation can refresh view data but must not silently move this edit's base_hash or erase its draft. Route/day change ends the editor; if preserving drafts is desired, use explicit local-per-day state, never send one day's text to another.
- Save PUT uses captured hash/text/day and immutable command intent. 413 keeps draft and explains limit. A valid409 opens region/alert `Notebook conflict` with labelled `Theirs` / `Mine` panes, bounded diff and `Use theirs`, `Keep mine`, `Copy mine`. Show last seen editor only if matching project/day event evidence exists; otherwise time only.
- Use theirs is explicit discard/reload of returned current. Keep mine is explicit overwrite attempt using **current.hash** and a **new** command_id, still optimistic (another writer can cause another409); it is not a silent retry of the first intent. Copy mine never saves. Keep draft on second conflict or fetch error. The `Reload` synonym must not silently discard edits; use the single `Use theirs` action for that behavior.
- Read-only viewers see content/chips with disabled write controls + ScopeHint, no unexpected write. Current-generation checks cover append/save/retry/copy completion and post-response focus/clearing.

**Verify:** append request/day/author server ownership; pending typing retained or input readOnly; edit base pinned through WS refresh; valid conflict preserves mine, displays theirs, keep mine uses new hash/id; second conflict; Use theirs; 413; malformed409; cross-day navigation and credential switch; no status invented from unknown chip. Assert real request bodies, not only success banners.

### Task 20: Notebook route and day navigation

**Depends:** 19. **Create:** `pages/Notebook.tsx`, scoped `pages/notebook/notebook.css`; **modify:** router; integration tests.

Use `/n/$project` to query literal `today` from backend and display its returned day; `/n/$project/$day` queries that day after format validation. Sidebar day list with entry counts and active state, h1 containing project and Notebook, DayView keyed by project/explicit day and credential generation. Read days + today where needed without two independent definitions of today's date. Server404 unknown project/day error remains visible; missing valid day with empty hash renders editable empty day.

**Verify:** encoded project names; valid/invalid dates; deep link and browser refresh; empty hub-today file; timezone boundary; list updates after append/digest; switching days cancels/isolates old reads; sidebar keyboard/scroll at narrow widths; chips navigate to current RunPage and preserve names. NavTree notebook link is usable without a last-visited task.

## Group 6: Exports, baselines and cleaned artifacts

### Task 21: Authenticated export menu

**Depends:** 2–3, 7; backend10–12/29. **Create:** `pages/components/ExportMenu.tsx`, matching tests; scoped CSS.

- Trigger `Export`; labelled dialog/popover `Export`. Formats `LaTeX`, `Markdown`, `CSV`; noise `both/seed/test/none`; digits integer 0–6. Selected format/options are local; server text is fetched by typed query using resolved selected board.primary. Preview first six lines plus exact remaining line count, selectable monospaced text. Do not render LaTeX/CSV as HTML or recompute server statistics in the browser.
- Prop contract includes project/task/resolved primary and a parent `ready` capability; query is disabled until the displayed board is current. Copy/Download disabled when pending, fetching (including same-key invalidation), error, placeholder, stale credential, or parent selection mismatch. Do not use cached old text as export of a new metric. Error on refetch blocks old successful text even if it remains visible.
- Clipboard receives full text, guarded before/after asynchronous completion; clipboard errors are local. Download uses a Blob and temporary object URL, an inert temporary download anchor with sanitized filename `<task>.<tex|md|csv>`, then revokes/removes it. No bearer-bearing URL, no navigation to the protected export endpoint, no tokens in filenames.
- Reset menu text/actionability on primary/route/auth changes. Closing aborts unnecessary requests where appropriate. Esc/focus return and keyboard selection use existing menu helpers.

**Verify:** exact query primary/format/noise/digits; both/seed/test/none; validation; six-line preview and full clipboard/blob; unsafe task filename; revoke URL; clipboard failure; changed-primary delayed response; invalidated same-key fetch pending/error cannot copy/download; stale auth completion cannot show Copied. Keep request/error security tests shared with Task2.

### Task 22: Paper baselines as references in plots and tables

**Depends:** 1, 18 (safe links helper only if reused). **Modify:** `panels/Leaderboard.tsx`, `charts/Glyphs.tsx`, `charts/DotCIChart.tsx`; **create:** `pages/components/BaselineRows.tsx` / pure baseline helper and tests. Preserve existing regular-run chart behavior.

- Keep raw BaselineRow values/std/version_match/source/source_url. Resolve a panel's **full metric/key** from actual result meta or task data, never baseline.primary from a different board selection. A missing value for that key is absent/neutral, not a fallback to another metric. Version mismatch checks metric name against the current matching version and displays `≠<ourVersion>` with a precise tooltip. Source links allow only http/https and use safe external-link attributes.
- Retained Leaderboard appends reference rows below a dashed divider and includes their finite displayed values in the shared plot domain. Reference row: neutral hollow diamond, name, value ± published std when present, second metric value when present, source link, mismatch badge and a plain numeric value-minus-best difference for the same key (label its sign; no statistical verdict). Compute that arithmetic only from the matching current panel run mean/key, not a stale default-board delta_vs_best; with no scored best leave it blank. No best band behind paper rows, no seed dots/seed count/test-set CI/p-value/vs_best verdict or run link. Published std is not a 95% interval. Its presence must not change best selection, best band, row ranking, counts or repeat checks of actual groups.
- For current v5 Scores plot add a **separate references prop** to DotCIChart (not fake DotCIRow seeds). Domain includes run rows + reference values. Render references after separator; exclude them from row best/identity/highlight/click calculations. Tooltip says published value/std/source; ordinary rows retain existing tooltips and per-seed marks. Extend chart height for references and keep best band restricted to run-row height. A compact Paper baselines table below provides links/badges/text equivalents.
- Both panels must render a baseline-only state when no scored runs exist. Do not return `No scored runs yet` before checking references. With no values for selected key, show appropriate no-reference state; do not draw NaN coordinates. No reference enters TaskRuns.groups, colorOf, hidden identity storage, selected groups, comparisons or Pareto.

**Verify:** two keys with deliberately different numbers, one mismatch, missing key, second metric and signed arithmetic difference, unsafe source link, published std, baseline-only, no baselines, finite domain; original rank/best/count/seed/CI/repeat output unchanged; reference is hollow and not clickable as a run; axis includes outlying paper value; no best band behind reference rows. Test both retained Leaderboard and actual DotCIChart path.

### Task 23: Integrate export and baselines into the v5 task workspace

**Depends:** 21–22; all current TaskPage/ViewTab regression contracts. **Modify:** `task/TaskPage.tsx`, `task/ChartsTab.tsx`, `task/ScoresSection.tsx`, `task/ViewTab.tsx`, `task/ViewPanels.tsx`; only necessary shared adapter changes. **Tests:** current task/workspace/view suites plus integration cases.

- TaskPage default board and TaskRuns remain separate typed reads. Non-saved-view tabs may expose task-level Export using **resolved** current default board.primary, gated on board pending/error/fetching and route identity. ChartsTab passes board baselines + exact TaskRuns.primary/version into ScoresSection and the Paper baselines table. Place reference content outside `items.length > 0` early-return/conditional so baseline-only tasks work; selected run identities stay untouched.
- ViewTab already owns `primary`, `seeds`, effective view and selectedRun. Add `useLeaderboard(project, task, [], {primary: primary ?? board?.primary, enabled: ...})` for its selected board, keyed correctly; the default board prop supplies available metric choices, **not selected export text**. Put the ViewTab Export control next to Metric/Seeds/Edit; gate on the selected board and panel query being current, not placeholder/fetching/error. Avoid two confusing Export buttons on a saved-view tab.
- Per-view panels may author different primary keys. `withBaselines(result, baselines)` decorates only leaderboard results using each result.meta.primary and raw values/version metadata; it must not replace result rows/meta/noise, substitute a global primary, or overwrite authored plot axes. `ViewPanels` pairs effective specs/results exactly as today, preserving `selectedItemId`, `currentGroupId`, `runStatus`, kind and run-link interception through PanelGrid. If no valid key is known, withhold references for that panel rather than guess.
- Preserve Metric and Seeds/Repeats controls, authored/overridden view behavior, stale-panel suppression, SelectedRun, edit links and typed bodies `{name}` versus `{view: effective}`. If necessary rename a local prop to distinguish defaultBoard/selectedBoard without changing the wire shape. Keep run names and metric direction/ranking from server, not UI reverse sorting.

**Verify:** select alternative lower-is-better metric and inspect export primary plus actual reversed ranking; change back; seed override remains correct; authored second-metric baseline shows its own value; slow/errors on new selected board or view disable export and suppress mismatched old results; same-key live refetch disables copy; baseline-only current Charts; selected-run drawer; all tab URL state, panel contexts, bounded metrics, compare binding and v5 naming suites. No wholesale replacement of TaskPage or router.

### Task 24: Cleaned artifact state on every current run/checkpoint surface

**Depends:** 1, 3–4, 16; backend22/31 location contract. **Modify:** `run/files.ts`, `run/FileList.tsx`, `run/OverviewTab.tsx`, `run/FilesTab.tsx`, `pages/components/WhereList.tsx`, `pages/components/TrainingDetails.tsx`, `pages/components/SelectedRun.tsx`; **create:** shared pure `pages/components/cleaned.ts` if useful; tests on all owners.

- Add cleaned metadata to FileRow while preserving raw full location before relative display. Match exact path or true slash-boundary descendant of a deleted directory, trim trailing separators safely; `/artifacts/a` must not match `/artifacts/ab`. Only eligible artifact/pulled rows can be struck through: never run folder, code, dataset, metadata, logs, env/config, or scores by broad prefix.
- Render struck-through path plus `✕ <date> <bytes>` and actor tooltip; remove/disable file-open and copy-as-existing controls for deleted artifact while keeping run navigation/status/history/scores. In FilesTab pass cleaned explicitly to CheckpointTable; OverviewTab file generation receives detail.cleaned; SelectedRun already has RunDetail and must pass it to retained WhereList/CheckpointTable. Preserve its ancestor ResizeObserver, focus restoration, user-input release and queued-callback guard: delayed chart growth must reveal the focused heading until the user takes over. Retain `ui/test/pages/selectedRun.test.tsx` and both-theme `ui/e2e/selectedRun.spec.ts` delayed-chart/manual-scroll regressions when adding cleaned markers.
- The reconciled contract adds `CleanedArtifact.environment_id: str | None = None`: new entries copy CleanItem.environment_id (actual deletion target), and hub merges preserve that value. Match environment plus unmodified raw path before display formatting. Source artifacts use record.environment_id; hub pulled copies use the shared hub descriptor environment_id. If row location is unknown, leave deletion state unknown. Legacy absent/null marker location is not guessed, even if a raw path happens to match. Do not infer identity from display host aliases or resolve remote paths on the hub. This is additive file/DTO metadata, not another SQL schema change.
- Task TrainingDetails currently holds RunRecord/artifacts, not RunDetail. Fetch details only for its visible checkpoint page (max20 run IDs), dedupe via existing queryKeys.run and reuse cached details. Do not fetch every run/one per artifact or send sentinel IDs. Preserve paging, selected-run context, error/loading and known deletion evidence during refetch. A failed cleanup-detail fetch is unknown, not proof the artifact still exists.
- Live run.artifacts_cleaned reaches both RunDetail and taskRuns/query owners. Historical checkpoint metric values remain visible but cannot trigger reinfer from a known deleted checkpoint.

Concrete DTO and matching seam (add to the existing model and shared cleanup helper; this is planned implementation, not a new source file written by the refresh):

```ts
export interface CleanedArtifact {
  path: string;
  bytes: number;
  at: string;
  actor: string;
  plan_id: string;
  /** Actual deletion filesystem; omitted/null only in legacy entries. */
  environment_id?: string | null;
}

type CleanedLocation = Pick<CleanedArtifact, "path" | "environment_id">;

/** Compare raw locations; never normalize a host path against the browser/hub. */
export function cleanedMatches(
  rawPath: string,
  environmentId: string | null | undefined,
  marker: CleanedLocation,
): boolean {
  if (!environmentId || marker.environment_id !== environmentId) return false;
  const cleanedPath = marker.path.replace(/\/+$/, "");
  // Root is protected and cannot be a legitimate cleaned artifact.
  if (!cleanedPath.startsWith("/")) return false;
  return rawPath === cleanedPath || rawPath.startsWith(`${cleanedPath}/`);
}
```

Use this helper only after a row is classified as a deletable artifact/pulled location. Pass raw `Artifact.path`, never relative display text, `host:path`, or a resolved alias. Before adding location to FileRow, preserve its raw path and environment separately. The shared hub environment lookup remains a single existing query; a pending/failed lookup cannot label a hub pulled row with the remote run's environment. Backend tests prove each new record and merged host response retains its deletion target environment.

Concrete regressions in `ui/test/pages/cleaned.test.ts` (import the helper in that test):

```ts
const hostMarker = { path: "/same/ckpt", environment_id: "env-host" };
const hubMarker = { ...hostMarker, environment_id: "env-hub" };
expect(cleanedMatches("/same/ckpt", "env-host", hostMarker)).toBe(true);
expect(cleanedMatches("/same/ckpt", "env-host", hubMarker)).toBe(false);
expect(cleanedMatches("/same/ckpt", "env-hub", hostMarker)).toBe(false);
expect(cleanedMatches("/same/ckpt/weights.bin", "env-host", hostMarker)).toBe(true);
expect(cleanedMatches("/same/ckpt2", "env-host", hostMarker)).toBe(false);
expect(cleanedMatches("/same/ckpt", "env-host", { path: "/same/ckpt" })).toBe(false);
expect(cleanedMatches("/same/ckpt", "env-host", { ...hostMarker, environment_id: null })).toBe(false);
expect(cleanedMatches("/same/ckpt", undefined, hostMarker)).toBe(false);
expect(cleanedMatches("/alias/ckpt", "env-host", hostMarker)).toBe(false);
expect(cleanedMatches("/same/ckpt", "env-host", { ...hostMarker, path: "/same/ckpt/" })).toBe(true);
expect(cleanedMatches("/same/ckpt/weights.bin", "env-host", { ...hostMarker, path: "/same/ckpt//" })).toBe(true);
expect(cleanedMatches("/same/ckpt", "env-host", { ...hostMarker, path: "///" })).toBe(false);
```

Component regressions must additionally render two same-path rows for source/pulled locations, apply only the corresponding environment marker, and assert exactly the deleted row loses copy/open actions. Additive JSON fixtures allow environment_id without modifying any SQL-version expectation.

**Verify:** exact/descendant/non-boundary paths, same basename/different environment, local pulled versus remote source, old hubs no cleaned, all v5 Overview/Files plus retained drawer/TrainingDetails; directory cleanup, event refresh, no copy/open/reinfer of known-deleted path; names/step-metric/history remain unchanged; <=20 requests per page, cache reuse, no sentinel fetch, error keeps known state. Backend tests own actual filesystem deletion and race safety.

## Group 7: Browser acceptance and documentation

### Task 25: Isolated team browser suite and v5 regression acceptance

**Depends:** frontend1–24, backend45/48, assembled backend/source environment. **Modify:** `ui/e2e/paths.ts`, `ui/e2e/serve-demo.ts`, `ui/e2e/fixtures.ts`, `ui/playwright.config.ts`, `ui/test/e2e/paths.test.ts`, relevant teardown tests. **Create:** `ui/e2e/team-fixtures.ts`, `ui/e2e/team.spec.ts` (or split read/write specs with disjoint matching). Backend49 owns `ui/package-e2e/installed.spec.ts` and its separate config; coordinate this matrix with that owner, do not duplicate package orchestration.

**Harness implementation:**

- Add TEAM_HOME/TEAM_DEMO_FILE below the current per-invocation RUN_DIR, TEAM_PORT through existing `runPort`, a unique team identity and strict home allowlist. Never restore fixed ports/shared `/tmp` homes, never reuse an existing server. `reuseExistingServer:false`, explicit identity equality before every browser/API mutation, child PID/start ownership and bounded shutdown remain mandatory. Extend localToken's allowlist and continue `uv run ... hx --home <isolated> token`; do not read a token from an assumed server.json layout or the user's home.
- Extend `serve-demo.ts --with-team` without replacing non-team/with-hosts branches. Team children alone set `USER=sv` for deterministic synthetic owner, plus disposable home and fake-only transports; strip inherited HYPOTHEX_SERVE_TOKEN/HUB_TOKEN. The parent test process need not change USER. Backend45 seeds the collaborator, notebooks/digest, baselines, cleanup fixtures, fake notices and connected URL host. Do not print raw pairing URLs/credentials to logs or shared reports; store only private harness data with restricted access and remove it at teardown.
- Keep base light/dark, editor, host launch and Vite-auth projects. Add team-light/team-dark with matching/exclusion so team specs never run against non-team homes and non-team specs never accidentally execute destructive steps against team. Serialize shared-home mutations across themes/specs or give each writer its own seeded home. Cleanup is destructive within the disposable fixture: a second theme needs independently eligible items or a fresh home, not an already-deleted plan.
- Team fixture verifies identity before obtaining the isolated owner token. Use a separate **unpaired** browser context with no token storage/Authorization to test real `/pair` redemption; derive a fresh offer via authenticated API. Per-principal API contexts do not silently inherit owner bearer. After pair, cookie-only protected reads establish identity. Keep traces/video/screenshots off while URL/QR contains secrets; capture only sanitized post-redemption states. Secret scan all retained artifacts, including errors and HTTP headers.
- Discover project/task/run IDs from current demo JSON/API. Current kinds are generic, training, agent_eval, agent_iteration, system_bench plus `eval_matrix` extra; do not replace them with old hardcoded names. Backend's explicitly seeded team toy task can be used only after checking its actual demo mapping. TaskRuns API supplies name/derived_name/renamed/seed; current runTitle uses the renamed name as-is, else derived_name plus ` · seed N` when seed is present. Fail clearly when required data is absent; never skip a selected acceptance test because a feature or fixture is missing.

**Acceptance matrix (all rows automated, both themes unless a pure protocol case):**

| Scenario | Actions and observations |
|---|---|
| Pair/public route | Fresh context opens offer URL; fragment removed before POST; no Navigation/me/WS pre-pair; Device name → Pair → success user/scope → Home; API cookie confirms alice; reused offer fails. |
| Existing shell | Navigation landmark, breadcrumbs, collapse/expand and theme; Home headings match `/^Running now/`, `/^Tasks/`, `/^Recent runs/` because count spans are part of accessible names. New run and command palette remain functional. |
| Settings/admin | h1 Settings; regions Sessions/Users/Add device/Notifications; own session marker and all session rows; generate bounded offer (no artifact leaks); configured/unset channels, project opt-in and recent states visible. Test delivery reaches only loopback fakes. |
| Settings/collaborator | h1 Settings; own Sessions and Add device; no Users/Notifications request; scopes cannot widen; protected admin route returns403, session remains valid. |
| Storage/read | h1 Storage, totals reconciled with API, partial-host error visible where seeded; By project/By host/Largest; non-admin no report request. |
| Storage/apply | Dry run → exact API plan_id/items/total → Apply cleanup → wrong Confirm bytes disabled → exact bytes enabled → Apply; response freed_bytes/deleted/skipped/errors reflected. Assert actual eligible file disappearance via disposable harness, protected/metadata/shared input unchanged; no fake success-only check. |
| Notebook | Open /n/project using hub today; Add entry with known and unknown chips; known opens RunPage named from API; unknown stays disabled; free text preserved; weekly complete/incomplete-cost block correct. |
| Notebook/conflict | Start Edit day; independent same-principal API writes another version; Save gets409; Mine text retained, Theirs current visible; Keep mine submits latest hash/new command_id; verify persisted bytes. Also Use theirs and413 retention in component suite. |
| Export | Task non-view Export with all three formats; options change request; clipboard/full download bytes agree with API; baseline values/footnotes preserved. In saved view choose alternative primary and confirm export query/ranking match it; delayed/refetch failure disables actions. |
| Baselines | Paper baselines visible with source/mismatch, hollow mark and no rank/seed/best badge; empty actual run list still shows references. Compare actual groups/best/count before and after reference injection in deterministic component test. |
| Run/cleanup | h1 contains the expected runTitle display (renamed name, else derived name plus seed suffix; never assume raw ID); Run tablist includes Overview/Charts/Logs/Files/Examples; Properties, editable name/reset; after cleanup eligible checkpoint struck through in Overview and Files/Checkpoint metrics, historical scores intact. |
| Ownership | Alice owner label; own stop/cancel allowed, sv/legacy denied; read-only controls disabled; launch-only uses fake shared host and cannot run on hub; run appears mirrored with correct owner/created_by. Mine affects Running now only. |
| Auth failure | Revoke currently paired browser from owner context; current HTTP401 or WS4401 leads to locked gate; count tickets/WS attempts over multiple backoff windows stays fixed; fresh pair resumes. Old delayed response never leaks/refills prior cache. |
| Hosts/queue/sweep | /hosts and /queue direct navigation; /s/p/id redirects to task Sweeps; preserve explicit issuance resume, queued cancellation and partial issuance display. Host auth-error re-pair instructions do not loop reconnect. |
| v5 task/workspace | All five kind tabs and eval_matrix; Runs sidebar selection/filter/group/sort/hide/suppress/columns survive URL reload; training step metrics bounded; key direction and selected metric correct; seeds and named-view editing preserved. |
| Evaluation/naming | Rename/reset reflected across run/task/Home/command palette; exact `require_bound` comparisons retain evaluator binding, legacy unbound remains unbound; no paper row in examples comparisons. |
| Teardown | Normal, error and interrupted run terminate only owned hub/fake children; no leftover test process/home writer; credential/URL artifact scan clean. |

Accessible controls to implement and use: `Device name`, `Pair`, `Home`; `Settings`, `Sessions`, `Users`, `Add device`, `Notifications`; `Storage`, `Dry run`, `Apply cleanup`, `Confirm bytes`, `Apply`; `New entry`, `Add entry`, `Edit day`, `Day text`, `Save`, `Cancel`, `Notebook conflict`, `Theirs`, `Mine`, `Use theirs`, `Keep mine`, `Copy mine`; `Export`, `LaTeX`, `Markdown`, `CSV`, `Preview`, `Copy`, `Download`, `Paper baselines`; Home `Mine`. Scope duplicate action names to their dialog/section. Do not assert historical `a Sessions`, `d Notifications`, `export ▾`, `Confirm size`, `.frow.bl` or `li.cleaned` as the only behavior oracle.

Concrete locator pattern for existing v5 behavior (example inside a properly authenticated, identity-checked Playwright test):

```ts
await page.goto(`/t/${encodeURIComponent(project)}/${encodeURIComponent(task)}`);
await expect(page.getByRole("heading", { level: 1, name: task, exact: true })).toBeVisible();
await expect(page.getByRole("tablist", { name: "Task", exact: true })).toBeVisible();
await expect(page.getByRole("complementary", { name: "Runs", exact: true })).toBeVisible();
await page.goto(`/r/${encodeURIComponent(run.run_id)}`);
const display = run.renamed ? run.name : `${run.derived_name}${run.seed == null ? "" : ` · seed ${run.seed}`}`;
await expect(page.getByRole("heading", { level: 1 })).toContainText(display);
await expect(page.getByRole("tablist", { name: "Run", exact: true })).toBeVisible();
await page.getByRole("tab", { name: "Files", exact: true }).click();
await expect(page.getByRole("table", { name: "Checkpoint metrics", exact: true })).toBeVisible();
```

Here `run` is a seeded training TaskRun with checkpoints; do not use that last assertion for every task kind. Derive project/task mapping and run.name through typed fixtures before navigation. New-screen assertions await both HTTP outcome and the visible state they verify.

**Commands after assembly (not during plan refresh):**

```sh
uv sync --locked --all-groups
bun --cwd ui install --frozen-lockfile
bun --cwd ui run gen:types
bun --cwd ui run typecheck
bun --cwd ui test
bun --cwd ui run build
bun --cwd ui run e2e
```

The full e2e script already builds, so a completed build need not be repeated merely for reporting; use the repository's explicit Playwright invocation after a known current build when appropriate. Record exact commands/results and any missing browser prerequisite. Run required affected Python/API suites plus full repository checks through backend assembly owner; no claim of backend or installed-wheel acceptance from UI mocks.

### Task 26: Document the Phase 3 screens and testing handoff

**Depends:** 25; coordinate backend46/49. **Modify:** existing `docs/ui.rst` and `tests/test_docs_ui.py`; update links/index only if needed and assigned. Tests/documentation stay in the Sphinx/RTD system; do not add a competing docs framework.

Document pairing via fragment and cookie, fallback token gate, sessions/revoke/scopes, own-versus-admin run actions and local-execution restriction, Settings status/test delivery, project Notebook append/edit/409/413, run chips and weekly summary, selected-primary export formats/noise, paper references/version mismatch, storage Dry run/exact-byte Apply/partial result, deleted checkpoint history, and v5 paths/task/run tabs. Examples use disposable homes and fake channels; no actual personal secrets/hostnames. Include screenshots only from sanitized completed UI states in both themes.

Link backend docs for notifications/config/env variable names, Tailscale/url hosts, scoped MCP/SDK cost, Postgres, and the backend49 installed-package testing path. Distinguish schema3→5 and schema4→5 SQLite rebuild from PostgreSQL Alembic. Preserve user-facing New run/rename/search/metric direction and explicit sweep resume descriptions. Explain an unknown recorded cost as a subtotal without implying a total.

**Verify:** extend existing docs tests for new sections/routes while retaining all current v5 tab/filter/selection/rename/keyboard/screenshot assertions; run `uv run pytest tests/test_docs_ui.py`. Sphinx build with repository command (`uv run sphinx-build -b html docs <isolated-output>` with warnings treated as configured); all internal links and referenced labels/routes exist; browser screenshots inspected at final scale; manual instructions reproduced in backend49 from installed wheel, outside checkout, with restart and upgrade evidence. Document actual limitations instead of saying stable/user-test-ready before those checks pass.

## Done criteria and review handoff

Frontend done means all 26 tasks implemented with their meaningful regressions, full Bun unit/type/build/browser checks current, current-main v5 regression matrix preserved, no secret artifacts, docs built, and backend49 installed browser assertions passing with authentic schema3/schema4 upgrade/restart receipts. A screenshot, source build or plan probe alone satisfies none of that. Real Slack/SMTP/Tailscale exposure remains a separate user action.

The plan-refresh worker's done means this file is internally coherent, all26 coverage preserved, source anchors checked against f6f130c, old replacements removed, cross-owner dependencies reported, and an exact frozen hash/change receipt saved. It is **ready for primary review**, not LGTM, implementation authorization, or runtime validation.

Cross-owner reconciliation before the plan set can receive final approval:

1. Contract §10 must name current v5 owners (shell/HomePage/TaskPage/RunPage, `api/AuthGate.tsx`), current v5 layout/labels and exact-byte confirmation. Add RecentRun/TaskRun.owner serialization in backend27 and contract. Preserve Mine's Running-now-only scope.
2. Contract §1.9 now resolves cleaned artifact identity with environment_id copied from actual CleanItem target and preserved in host-response merges. Backend22/31 and frontend24 must implement the concrete same-path/different-env, merge and legacy-null tests. Deletion must independently resist parent-symlink replacement after eligibility checks; the UI lock/confirm does not solve it.
3. Backend23 public SPA classifier and frontend Task7 exact routes agree, including hosts/queue/notebook/settings/storage and trailing slashes; pair remains a full-load client exception. Backend26 timeout tests must actually start receive and recheck at a positive bounded interval.
4. Backend45/49 demo mapping, deterministic USER only in team children, scope/owner assertions, current UI-v5 selectors, exact-byte cleanup and real package identity guards agree with Task25. No old `Run <id>` h1 or lettered-figure locator; packaged assertions use actual run names.
5. Parent owns schema5, source pins and renewed review gates across all documents. Historical references remain historical; no active text may still prescribe Phase3 schema4 or claim old LGTM approves current-main assembly.

## Source inventory at f6f130c

The following generated inventory records actual paths/symbols/line anchors and Git blob IDs, not future implementation files. Re-run the external compatibility probe before relying on these anchors after main changes. It also compares this refresh checkout's source bytes with pinned main and records absent historical replacement paths. The probe is read-only; passing it establishes source compatibility only.
| Existing path and source anchor | Git blob at pin |
|---|---|
| `ui/src/main.tsx:5` — `QueryClientProvider` | `c62bc2ebd55330949f485ddc4c6cb59602191a3a` |
| `ui/src/router.tsx:134` — `export const rootRoute` | `09360f2c7c3929f3f2792a37fd5d01d8cec8575d` |
| `ui/src/shell/AppShell.tsx:55` — `export function AppShell` | `52a45834d369cba437a392cbe3478b7429362daa` |
| `ui/src/shell/TopBar.tsx:119` — `export function TopBar` | `7159ebcea39103c4a1e42ad2883ffd02077aed68` |
| `ui/src/shell/NavTree.tsx:62` — `export function NavTree` | `7b5deeefb5540a99c98d0cdcf803f97720425851` |
| `ui/src/api/auth.ts:23` — `export class AuthStore` | `cee7616e37fd884a1b8120852eadd3d9f49d28cf` |
| `ui/src/api/AuthGate.tsx:10` — `export function AuthGate` | `d8f8091fcc2fa3437f42b4705812cb6cacc7f448` |
| `ui/src/api/client.ts:15` — `export const ROUTES` | `8807af1dd1a243a1658154ab51c0140ab87f1b5f` |
| `ui/src/api/models.ts:914` — `export interface TaskRun` | `09c061502658a4713ef50f40ff3b4768f2dc3a53` |
| `ui/src/api/queries.ts:25` — `export const queryKeys` | `102c5aa4ad01bc5c623a1634abca7b6bfcef6980` |
| `ui/src/api/events.ts:169` — `export function keysForEvent` | `d648bc3216927fd805de534ca416f084d9ea1c30` |
| `ui/src/home/HomePage.tsx:214` — `export function HomePage` | `91f59f9a24be1ea7ccbc824afd4c5860a0e0e86e` |
| `ui/src/home/homeModel.ts:184` — `export function recentRows` | `92be415bed31e1d2ae7235c326a5a3b46e5eaea1` |
| `ui/src/task/TaskPage.tsx:34` — `export function TaskPage` | `fc4cb81972a04f95ffc7e34d3e7672a3148e951e` |
| `ui/src/task/ChartsTab.tsx:51` — `export function ChartsTab` | `a0259ee7a6a4ca67e4262cdb0deb9418c8a3ded1` |
| `ui/src/task/ScoresSection.tsx:69` — `export function ScoresSection` | `aa050b5a6af478bdc4d6f151ffed2de8af5d0af2` |
| `ui/src/task/ViewTab.tsx:24` — `export function ViewTab` | `71ad81f6fd7c5db9df90d9501cfa14f0e2144f60` |
| `ui/src/task/ViewPanels.tsx:41` — `export function ViewPanels` | `b67a1e6fe10c411faefe1f94a48b9518b2445ab8` |
| `ui/src/task/SweepDetail.tsx:188` — `sweepStats(` | `9c7cb285c783aed803c60861029ed4d8eb17bf8c` |
| `ui/src/task/useRunSelection.ts:227` — `export function useRunSelection` | `9e5f8c0e263940db90edf39e43a41dc4dbcafcbe` |
| `ui/src/task/RunsTab.tsx:55` — `export function RunsTab` | `0914eaa6aeac8f309970bcc983c6ef473d92c932` |
| `ui/src/hosts/QueuePage.tsx:61` — `export function QueuePage` | `d4a07796f75cd42164af8cbcd70ac8ef07bb153c` |
| `ui/src/run/RunPage.tsx:36` — `export function RunPage` | `09846bec84576ab86f71decb199cdd99b3de58ed` |
| `ui/src/run/RunHeader.tsx:17` — `export function RunHeader` | `3e20a4cba8899355d2fc44fac52eabb922a6d49d` |
| `ui/src/run/RunName.tsx:125` — `export function RunName` | `ca93d0f08957ad1aa7582f52b048d5dc217302ea` |
| `ui/src/run/PropsSidebar.tsx:90` — `export function PropsSidebar` | `14d37abcb99b2853d4c19361f335cf0cba2d7966` |
| `ui/src/run/OverviewTab.tsx:200` — `overviewFiles(detail)` | `c36e8c1fe45f6462d84fcfef4a57263589bf9101` |
| `ui/src/run/FilesTab.tsx:3` — `CheckpointTable` | `372ed5ffbcbcff6a4991e0ab1717999a03fc240c` |
| `ui/src/run/files.ts:70` — `export function overviewFiles` | `e992ad338788224a046659a70447ea647c1e4a60` |
| `ui/src/run/FileList.tsx:21` — `export function FileList` | `3131da02fbca9af0ede897d992a5798d02619fcc` |
| `ui/src/pages/components/links.tsx:82` — `export function isAppPath` | `d35842bb6ac5495e1c8413d6ae2087226f304c0e` |
| `ui/src/pages/components/useAction.ts:37` — `export function useAction` | `12ecff8de35690bfa73f69e34992710c0f8158f9` |
| `ui/src/pages/components/RunActions.tsx:57` — `export function RunActions` | `c81bfe7424ac18f51cf0e3793675d65f3c760fb4` |
| `ui/src/pages/components/SweepModel.ts:526` — `export function sweepStats` | `b5735bb5bcc53007d2d219ca5fc0c93a26122b14` |
| `ui/src/pages/components/TrainingDetails.tsx:74` — `export function TrainingCheckpoints` | `e8315332380a17bc2b72456f012656bcd19e2806` |
| `ui/src/pages/components/SelectedRun.tsx:18` — `export function SelectedRun` | `058583660ed8dc961315c16e0fcfbc2ed87a97b2` |
| `ui/src/pages/components/WhereList.tsx:132` — `export function WhereList` | `2f8b41b3d5289e13aac5763b18381d13f053fa3a` |
| `ui/src/pages/components/PanelGrid.tsx:62` — `export function PanelGrid` | `2a70abb7b9e6f5adbb22236bcf1ca4893345e1c0` |
| `ui/src/charts/DotCIChart.tsx:66` — `export function DotCIChart` | `7c777da2dbee4cebb0916a879bad73fb6ea22569` |
| `ui/src/panels/Leaderboard.tsx:370` — `export function Leaderboard` | `e0efc8d5032b01af933b1551370992a38f4f4705` |
| `ui/src/panels/Markdown.tsx:36` — `export function` | `eaabcb9e9d37a128ae90f44132d7682b85a85dfb` |
| `ui/src/launch/LaunchDialog.tsx:410` — `export function LaunchDialog` | `082fdbfd2c6cde46b9676f5d25d21a1baa5512ab` |
| `ui/e2e/paths.ts:150` — `export function localToken` | `299a06b062757333c91da9ad77f8478ebc8228bd` |
| `ui/e2e/serve-demo.ts:53` — `const withHosts` | `a5148484442f9e2656c3757c98140c9b037a36d4` |
| `ui/e2e/fixtures.ts:70` — `export interface TaskRunsLite` | `f6e8475f11e30f7f5e9a3520d12a84b044cf8fe0` |
| `ui/playwright.config.ts:19` — `export default defineConfig` | `221aaa10fc64bd01c486a48ce0ab00f677277ab1` |
| `ui/package.json:12` — `"gen:types"` | `182499fbc8300133391653e2b11d663aff4919fc` |
| `src/hypothex/core/overview.py:117` — `class RecentRun` | `1db0c8ad91640f4dee099478d3ff5cb6f9a3a1ef` |
| `src/hypothex/core/taskruns.py:36` — `class TaskRun` | `7a65beb6bb92a1fc2172e228e29bc695e986efdf` |
| `src/hypothex/core/index.py:58` — `SCHEMA_VERSION = 4` | `0c18175ad0be8521f75850945661eeb1dc171509` |
| `docs/superpowers/specs/2026-10-16-hypothex-ui-v5-design.md:1` — `#` | `761e817378a44195bdf008f69256719f1f1f5af2` |
