# Dogfood integration — 2026-10-05

Scope: queue step 6, areas A–G/M/N and packaging, in `/tmp/hx-df-fix`.
Dependencies: do not merge main, push, or open a PR until audit and security branches merge.

- [x] Read handover and dogfood findings; archive inherited staged and unstaged patches.
- [x] Preserve cancellation coverage, integrate a shared queue batch primitive, verify red/green.
- [x] Verify inherited warning deduplication, hint consolidation, and fixture repairs red/green.
- [x] Review DF-1 grouping, DF-3 seed collapse, and DF-7 p-values with independent calculations.
- [x] Run Python/UI checks and inspect the complete dogfood diff.
- [x] Commit locally and report exact counts and remaining integration dependencies.
- [x] Remove only proven-clean, merged, inactive area worktrees, preserving evidence first.

Decisions:
- Retain inherited removal of obsolete queue refresh calls: queue ranks are computed on read.
- Keep a shared cancellation primitive and move the deleted regression to its actual integrated path.
- Test snapshots and command outputs live in `/tmp/hx-handoff-evidence/dogfood-integration`.

Verification and review evidence:
- Cancellation: failing integration regression observed 3 scheduler locks instead of 1; 11 focused tests pass after consolidating batch cancellation.
- Diff capture: two failing real launch/roundtrip tests pass after persisting diff hashes. Removed the test-only GitInfo subclass.
- Dirty group collision: 20 fixed / 0 broken returned p=1.0 when two hashes shared their first four characters. Full recorded hash suffix now gives exact p=2/2**20.
- Independent statistics oracle: 100 randomized unequal-rerun cases match Python sample statistics and SciPy Welch; maximum p error 8.4e-14. 2601 sign tests match exact integer binomial sums with zero error.
- Warning integration: old execution implementation makes both local and fake-SLURM warnings appear twice; updated execution passes both once-only tests. Template hint consolidation also verified against old implementation.
- Read models: failing tests for queue rank, host-qualified mirrored paths, mixed source hashes, and dirty-vs-dirty comparison now pass. Combined query/leaderboard/seed suite: 57 passed.
- Deferred pin: failing test ran changed code after HEAD moved while queued; staging now preserves the explicitly pinned code.
- UI: Bun 676 passed, zero failed, 2878 assertions; TypeScript and build passed.
- Cleanup: eight df-area worktrees/branches removed by ordinary safe commands; manifests in /tmp/hx-handoff-evidence/df-area-archive. Only disposable caches/virtualenvs existed.
- Full Python: 1627 passed, 3 skipped, 9 Docker tests deselected in 486.43s. Sphinx HTML build passed without warnings. Ruff check/format (142 files), ty, and git diff --check passed.
- Cross-layer follow-up list: /tmp/hx-handoff-evidence/dogfood-integration/step7-cross-layer-remainder.md.

Further decisions:
- Keep complete eight-character recorded dirty hash in group IDs to prevent internal comparison-map collisions. Update the spec and plan contract; clean IDs remain unchanged.
- Infer board metric drift only from differing stored hashes at the selected metric version; never execute project code from leaderboard reads.
- Honor explicitly pinned deferred execution even when the repo matches at preparation: the working copy can change before queued execution.
- API queue ranks are derived globally before filtering/pagination; persisted tickets stay unchanged.

Packaging verification:
- Real uv build from the built UI: wheel 1,271,957 bytes; both referenced UI assets exist, skill and license included, internal docs excluded. Artifacts retained under /tmp/hx-handoff-evidence/dogfood-integration/dist.

Integration gate:
- No main merge, push, or PR yet. Wait for queue steps 2/4/5 to merge.
- Current branch predates audit wave 3 (merge-base with 52b25e4 is 70c369c), so later integration must retain both sides: audit LTTB/metric_names, reeval run_ids filtering, security local_repo gates and metric bounds, plus these dogfood semantics.
- Cross-layer step7 remainder is deliberately open; see the external evidence note.

Pre-merge composition checks (parent-authorized, no main merge yet):
- [x] Reproduce long Unicode atomic filenames plus umask: both permission cases fail
  with ENAMETOOLONG, then pass with byte-bounded prefixes and existing O_EXCL writes.
- [x] Reproduce delayed execution checkout ownership: an unowned worktree was reused,
  git received an unreserved destination, and a racing creator was not protected.
  Three failing tests now pass with exclusive reservation, recorded completion for
  SLURM reuse, and cleanup refusal for destinations this run never created.
- [x] Focused lifecycle suite: 28 passed, 219 deselected, including pinned local/queued
  and fake-SLURM execution/cleanup. Ruff check/format, scoped ty, Sphinx with warnings
  as errors, and diff whitespace checks passed. Red/green logs remain in the external
  evidence folder; commit only this worker's seven explicit files.
- Gate/staging cleanup and verified host-alias/path-cache composition still wait for
  the authorized main merge after security dependencies land.
