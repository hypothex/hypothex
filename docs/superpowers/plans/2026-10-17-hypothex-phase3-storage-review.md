# PR 27 storage follow-up: independent final review

**LGTM for the scoped storage follow-up at runtime SHA-256 `c282d9969fb93667c7f43af42c3f0c27448cbd16cd1056154b33fb928adc1a0f`. No remaining demonstrated P1/P2 findings in this scope.**

This review follows PR 27 base `96ffd74932038e5ad0ce0789673436911026c0a9`. It covers overlapping artifact selection, shared-owner bookkeeping, physical byte confirmation, owner-side preflight/apply, grouped alias races, the associated API tests, UI wording/results, and storage documentation. It supplements the earlier Phase 3 review; it does not replace the assembler's fresh package, merged-main, or CI acceptance.

The reviewer made no product edits, commits, pushes, or provider calls. All destructive probes used synthetic files in disposable guarded contexts. The only checkout write is this review document, explicitly requested by the assembler.

## Resolved findings

1. **Excluded overlapping bindings could be deleted.** The committed baseline failed same-path, parent, and child cases, including excluded log bindings in the same eligible run. The final implementation preserves each environment/project/run/storage-kind/artifact-kind/raw-path association, refuses overlapping policy exclusions, and requires all current bindings to have been selected. New owners or kinds after planning, excluded projects, and mirrored runs' genuine local pulled copies remain protected. Direct owner requests cannot bypass this by sending only part of the selected ownership batch.
2. **Shared selected owners lost markers/events and bytes were duplicated.** Final plans retain all selected associations, while deletion groups physical roots on the owning filesystem. Successful roots are removed and counted once; every affected run/raw path receives its marker and event. Local parent aliases, nested paths, owner transport labels, and host-to-hub marker mirroring are covered. A failed or partially removed group does not acquire success markers; a disjoint successful group is still reported.
3. **The first grouped fix could mark a rebound non-root alias as cleaned.** The reviewer reproduced a parent alias change between group preflight and root removal. The final implementation captures group member identities, verifies them again after measurement, and checks surviving/rebound non-root paths after the syscall. Independent probes retarget aliases before removal, during measurement, and inside the actual unlink call. Pre-syscall changes refuse the group; syscall-boundary changes count the completed root removal but leave the unrelated surviving artifact unmarked. Missing safe-removal capabilities refuse the group before descriptor capture.
4. **Remote aliases could misstate exact confirmed bytes.** Reviewer probes demonstrated three directions: separate lexical aliases double-counted a shared physical file; one lexical parent/child group split physically and confirmed 0 bytes before freeing 16,384; and a reversed physical root confirmed 4,096 before freeing 20,480. The final owner preflight compares full-batch lexical and physical group membership **and root identity**. All incompatible groups are refused with `filesystem aliases require a local cleanup plan`. Final probes preserve every affected file and report zero freed bytes. Ordinary shared and nested remote paths still delete successfully with exact totals.

## Verification

- **27 independent artifact-level probes passed in 4.27 seconds** on the exact final source. `partition-final-run.json` records the command, environment, exit status, and identical source hashes before and after execution. `partition-final-green.log` contains the results. The probes verify actual files, marker content, events, selection boundaries, and byte totals.
- The expanded baseline suite demonstrated **17 failures and 2 passes** before correction (`baseline-expanded.log`). Separate red receipts preserve the first grouped alias race (`fix-first.log`), remote duplicate totals (`remote-alias-red.log`), inverse alias split (`inverse-alias.log`), and reversed root (`reversed-root.log`). These are historical failing receipts, not final failures.
- Inspected owner evidence: **273 affected tests passed in 64.79 seconds**, including all **7 real HTTP hub/owner overlap tests**, on the final runtime. The integrated command covers storage core/safety/overlap, storage API/overlap, queries, and execution. The final 34 owner overlap tests include file/directory alias races and all three inverse/reversed-root cases.
- Inspected scoped Ruff, formatting, ty, and Sphinx `-W --keep-going` success. The final docs accurately explain per-owner rows versus physical totals, excluded bindings, changed aliases, and remote alias refusal.
- Inspected parent UI evidence: **23 tests passed**, and TypeScript plus production build succeeded. The UI now calls association rows “items” and includes run IDs in deletion results; its shared-owner regression confirms the server's physical byte total rather than summing rows.

The independent suite uses a transport adapter that invokes actual owner-side storage functions on a separate Context. Real HTTP coverage is separately supplied by the integrated API suite; these are distinct evidence layers. This follow-up did not run real remote hosts or deployments.

## Reviewed source receipt

The following hashes were checked against the final checkout. `reviewed-file-hashes.json` is the machine-readable receipt.

| File | SHA-256 |
| --- | --- |
| `src/hypothex/core/storage.py` | `c282d9969fb93667c7f43af42c3f0c27448cbd16cd1056154b33fb928adc1a0f` |
| `docs/storage.rst` | `8da5928738bbbd581908b6881fd991a794ef0f490b48ca3ac0dc74d952d1f11d` |
| `tests/core/test_storage_overlap.py` | `a67498db397251353eae57667a703cf1d922f513d7bffec329dd98547cb5a348` |
| `tests/core/test_storage_safety.py` | `5f296a21ec7f79de64de0cbce6e7b353884863724959b76f1303f6af3b426d3e` |
| `tests/api/test_storage_overlap.py` | `2042100941e5de633ae28a633783a2ef49dd6ec4fe60dbdf7002f03e4aaacc8f` |
| `ui/src/pages/storage/Clean.tsx` | `060fe4bb5f0785ac4334fe88343ee9777941fc6ab520af0c8528b1f73f83107b` |
| `ui/test/phase3/storage.test.tsx` | `6c048e23f07ae7fd6d9925859025fb0f9721866f5b12ea49d59a57ca9004423b` |

## Evidence location and acceptance boundary

Independent evidence lives at `/Users/shreyasv/Desktop/code/hypothex-phase3-evidence/implementation/final-review/pr27-storage/`. Owner evidence is in `implementation/storage/pr27-review/`; UI evidence is in `implementation/pr27-storage-ui-green.log` and `implementation/pr27-storage-ui-build.log`. `evidence-hashes.json` covers the independent source/probes/red/green receipts, this report, and the inspected final owner/UI evidence.

Remote groups whose filesystem alias topology changes grouping or root choice intentionally require an owner-local cleanup plan. Reporting totals still describe report rows; only cleanup confirmation and successful deletion totals count physical removal roots once. These documented limits are accepted in this review. Final installed-package rebuild, clean merged-main validation, CI, and publishing remain assembler-owned acceptance steps.
