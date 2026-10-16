# Whole Phase 3 independent implementation review

**Verdict: LGTM. No unresolved actionable findings remain in the reviewed implementation.** Both findings from this review were fixed and independently verified. The final installed package also passes all five required acceptance cases and contains the reviewed API fix. This is implementation review approval; GitHub CI, publication and merge remain separate parent-owned steps.

Reviewed checkout: `/private/tmp/hx-phase3-implementation`, including uncommitted and untracked implementation against approved base `244d55f9c3be775b8c335bb258bbe9d5858ef83e`. This reviewer authored no product changes and made no checkout edits, staging, commits or pushes. Evidence root: `/Users/shreyasv/Desktop/code/hypothex-phase3-evidence/implementation/final-review/`.

## Scope

Reviewed all 13 Phase 3 contract items and their HTTP, CLI, MCP, SDK, filesystem, remote-host and browser boundaries: notebook/run links, paper baselines, opt-in Slack/SMTP, digest, exports, guarded storage cleanup, PostgreSQL/Alembic, pairing/scopes/revocation, Tailscale/URL hosts, paused auth retries, scoped HTTP MCP, SDK cost and shared-hub ownership. The accompanying `coverage.md` maps source inspection and evidence to each item and the retained current-main contracts: UI v5, names/search, bound metrics, selected primary, tri-state direction, cost completeness and durable sweep issuance.

## Resolved P1: completed pre-upgrade launch receipt could execute twice

Location: `src/hypothex/api/app.py`, `check_legacy_command` at line 2164 and the `once` wrapper used by POST `/api/v1/runs`.

A successful pre-upgrade launch stores its receipt under the raw command ID. The first compatibility implementation discarded that completed result, then claimed the new caller/route-bound key and executed the command again. Independent `test_legacy_launch.py` created the exact old raw `EventLog.run_once(command_id, launch_here)` receipt around a real trivial Python command, waited for completion, then retried the same HTTP body. Tokenless and root-token auth-off variants each returned 200 with a second finished run and two physical execution-counter lines. `legacy-launch-red.log` records both failures.

The owner changed the guard to return a generic 409 for every non-None raw receipt when no bound receipt exists, including `{}`. It never exposes the unbound payload. Current bound-result precedence, pending/interrupted handling and scoped/host exclusions remain intact. The exact independent probes now return 409 with one execution each. All four earlier cross-interface probes also pass: `legacy-launch-fixed.log`, **6 passed in 2.77s**. Owner regression coverage additionally checks empty results, bound precedence and the authorization boundaries.

Final reviewed app SHA256: `e1bc8ce69050055118f53bc62df5e78d9a7f75995bb48efdabde45acc6d8d958`. The installed wheel contains exactly these bytes. This finding and closure supersede the earlier bounded security report's expectation that a completed raw receipt permits a fresh mutation; its tags-only probe did not establish launch idempotency.

## Resolved P2: browser pairing accepted labels longer than the API permits

`ui/src/pages/Pair.tsx` allowed 80-character device labels while the API permits 64. The owner aligned input maxlength, submit guard and disabled state to 64 and added boundary tests. Source inspection and the independent API probe confirm 65 characters reject without consuming the offer, while 64 redeem exactly once. Final Pair SHA256: `d277db5f91baf4381961a0efe292b2ccbf81cf7565e9155a144b9c2a1783bef1`.

## Independent and inherited verification

- Reviewer cross-interface tests cover per-user notebook receipts, immutable retry and stale-hash conflict preservation; pairing limits/expiry/disabled targets; selected lower-is-better latency export, fraction-only percentage scaling and read-scope write refusal. The final six-test result includes the two physical launch regressions above.
- Reviewer verified all 23 + 39 frozen historical-fixture payload hashes, 4 + 4 pinned Git source objects, generator hashes and 11 + 19 protected pre-relocation byte identities. See `fixture-verification.json`.
- The prior bounded security and core reviews supplied additional independent auth/MCP/receipt and storage/channel/crash/index evidence. Their pairing-secret redaction, pulled-copy ownership and partial-SMTP fixes were inspected in the actual source. Their reports support this review but do not replace it.
- Parent backend suite: **3,675 passed, 3 skipped, 24 deselected** in 935.50s, including four assembled acceptance scenarios. The three skips require unavailable `flock` behavior on macOS. The final completed-raw guard landed after collection; its final bytes are covered by the owner's **138 affected tests**, the reviewer's six tests and the final installed package, not a claim that the earlier full suite covered the change. Parent Ruff check/format, ty and Sphinx warnings-as-errors checks passed.
- Parent Docker suite: **24 passed**, including actual PostgreSQL cases. Reviewer did not start containers or rerun that suite.
- UI evidence: **1,510 Bun tests passed**, TypeScript/build passed; **122 existing browser tests passed**, followed by **28 affected host/launch and complete light/dark team tests** after the final local-launch scope fix. These are separate runs, not a claimed final monolithic browser sweep.

## Final package acceptance and artifact identity

`../package/final-accepted.log`: **5 passed in 191.71s**. It exercises default-token and team startup/restart, both immutable schema-3/schema-4 homes through upgrade/restart/reindex, required default dependency closure/resources/migration metadata, HTTP/CLI/MCP behavior, fake notifications and **20 browser executions**. Installed imports come from an external Python 3.13 site-packages under `-I`, without checkout entries in `sys.path`.

The reviewer independently recomputed the wheel/sdist hashes, compared all **108 declared source/resource input hashes** with current checkout bytes, checked **105 wheel package members** and **108 matching sdist members**, inspected the schema/migration/import evidence and all ten two-theme browser reports. The wheel's force-included skill comes from `skills/hypothex/SKILL.md`, outside the harness's declared `src` input mapping; it was verified directly against checkout and is included in the review manifest. See `package-verification.json` and `verify_final_package.py`.

- Wheel SHA256: `419c184c02562ee6eccd20b624a55060642735f83e4d98d0df35be047f9b345a`.
- Sdist SHA256: `b6d7d17ae785b0f6f0625878fa68c0eb91a9c1acc90003a86350ec8cdbc8f896`.
- Cleanup evidence: **12 owned servers, 2 detached descendants checked, 0 remaining, 0 failures**. The retained scan passed for **26 text artifacts**.

An earlier final attempt exposed a harness race: exact accessible names `Runs`/`Sweeps` stopped matching after the UI appended counts. Diagnostics proved the correct task/sweep destination, HTTP 200 and no page errors. The final harness uses anchored count-aware names and still asserts the exact task destination, sweep query and selected navigation entry. This was a test matcher correction, not a product change or a relaxed redirect requirement. Its final source was inspected.

## Limits and hash handoff

No real external provider, SSH/SLURM deployment, Tailscale exposure, user home or credential was exercised. Probes used guarded disposable homes, local synthetic commands and fakes/loopback. Review approval is tied to `reviewed-filehashes.json`; `source-hash-changes.json` records changes since the initial snapshot. Inclusion in the input manifest is not a claim of dynamically exercising every line. `commands.md`, the probe/log files and `evidence-hashes.json` make the review reproducible. Material changes to runtime or acceptance paths require a focused refresh; copying this report into repository documentation does not change the reviewed runtime.
