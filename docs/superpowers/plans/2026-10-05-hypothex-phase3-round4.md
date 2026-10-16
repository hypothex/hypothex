# Phase 3 plan review round 4

Scope: document-only corrections to the contract and backend/frontend implementation plans. No phase-3 source implementation or external service operations. The direct review of plan commit `58f074a` was supplemental; it did not use the required CLI reviewer. Its four fixes were committed as `7f6d7a5`. The actual required round 4 subsequently reviewed that fixed state; the final main-baseline refresh remains a later queue step.

## Supplemental direct review

| Finding | Failure scenario | Resolution | Planned regression |
| --- | --- | --- | --- |
| P1: MCP caller can inherit server token | Middleware accepts a cookie after unusable bearer; the tool forwards no token and `hub_call` discovers the server credential | Preserve middleware-selected credential in private ASGI state; propagate explicit no-discovery through real `hub_call`, including Task 41 replacement | Registered stop/get/cancel/extend tools through `AuthGuard`, inspect actual outbound headers for bad/empty/NBSP bearer plus cookie and no-credential HTTP |
| P1: cleanup misses input aliases | Relative checkpoint or symlinked parent differs textually from the recorded artifact | Normalize against run cwd; resolve reader targets and artifact parent aliases only on owning environment; remote read-only preflight plus locked delete recheck | Local/remote planning and apply, reader added after plan, relative/parent-symlink/leaf-symlink inputs, leaf-only deletion retained |
| P2: task percent export mixes units | Fraction primary scales latency by 100, or number primary leaves accuracy unscaled | Per-column formats supplied by `task_table`, applied to groups, dispersion, intervals, and baselines | Both primary choices plus configured metric-unit integration |
| P2: partial sweep notice is lost | Last existing member ends while issuance lock is held; later launch fails without another terminal event | Atomically persist deferred trigger before cursor advances; retry every scan and across restart | Restart under issuance lock, release without new event, exactly one partial notice and empty pending state |

## Supplemental fix verification

- [x] Update all affected planned call paths and contract shapes.
- [x] Add targeted regression cases to the implementation tasks.
- [x] Validate changed executable snippets and run focused in-memory probes.
- [x] Check document diff; commit the plan changes as the final local step.

Validation used the existing local Python environment with `uv run --no-sync python /tmp/validate-p3-round4.py`; the probe extracts the revised document functions and applies the MCP forwarding edits to the reviewed baseline in memory. All changed Python blocks parse (indented replacement fragments are dedented for this check). Changed Python snippets were formatted with Ruff. The focused probes passed: both export primary choices with group/baseline dispersion, all three input alias forms, remote owner preflight plus unavailable-check refusal, 16 guarded registered-tool/header combinations plus four no-credential calls, and notifier replay after restart/nonterminal events with no new ending. `git diff --check` is the document whitespace check. These probes use temporary files, stubs, and in-process request transports; they do not connect to real hosts or services.

## Actual required CLI round 4

Pinned plan HEAD: `7f6d7a53d7128813bf77f62d91423d5df9b49079`. Pinned real main: `87a1db54f1f30564f569de36c6cfa93e1da43bee`. The prompt covered all three plans, the design spec, prior findings/resolutions, and the accepted but pending schema/default-token changes. The reviewer used read-only inspection, with no tests, builds, runtime probes, network calls, or further delegation.

Exact invocation, with the working directory `/tmp/hx-p3-plans`:

```sh
codex exec -s read-only -c 'approval_policy="never"' -C /tmp/hx-p3-plans --json --color never -o /tmp/hx-handoff-evidence/phase3-round4/final.md - < /tmp/hx-handoff-evidence/phase3-round4/prompt.md > /tmp/hx-handoff-evidence/phase3-round4/raw.stdout.jsonl 2> /tmp/hx-handoff-evidence/phase3-round4/raw.stderr.txt
```

The process exited **0**. Exact command, argv, prompt, raw stdout/stderr, final report, metadata, and exit code are retained in `/tmp/hx-handoff-evidence/phase3-round4/` (`command.sh`, `argv.json`, `prompt.md`, `raw.stdout.jsonl`, `raw.stderr.txt`, `final.md`, `metadata.json`, `exitcode.txt`). The original review output is unchanged by the subsequent fix.

Result: **one new P2**, no new P0/P1 established. Task 31's storage-route test snippet used `pytest.mark.parametrize` at reviewed lines 14525–14528 but omitted `import pytest` from lines 14431–14441, preventing collection. The sole finding is resolved by adding that import. The reviewer classified MCP, mixed-unit export, and partial-sweep notification fixes as FIXED; storage was PARTIAL solely because of this test import.

Narrow verification extracts the actual Task 31 decorator and its `pytest` import, substitutes an empty test body, and executes only that import/decorator pair. `pytest-import-probe.py` and its exact command are retained beside the review evidence. Before the fix it exited **1** with `NameError: name 'pytest' is not defined` (`pytest-import-before.txt`, `.exitcode`); after the import it exited **0**, confirming the parametrization retains both `after_plan` cases (`pytest-import-after.txt`, `.exitcode`). This is an isolated decorator probe, not collection or execution of the unimplemented phase-3 suite.

## Final-baseline integration checklist

- [x] Preserve pinned main's Header `confirmKeys` and successful-query gating when updating the whole-file replacement; the existing Header test imports `confirmKeys`.
- [x] Merge WebSocket ticket acquisition into pinned main's split EventStream `connect`/`open` flow, retaining the head lookup, boundary refresh, and cancellation behavior.
- [x] Advance phase 3 to `SCHEMA_VERSION = 4` over the pinned audit schema-3 baseline; update migration metadata and tests consistently. See the [baseline refresh checkpoint](2026-10-05-hypothex-phase3-baseline-refresh.md) for additional index, MCP, UI and supplemental PostgreSQL findings. These remain document-level resolutions, subject to final-main refresh.
- [x] Reconcile step 9's final auth interfaces: default per-start all-kind bearer, public static shell and explicit credential gate/`hx token`, single-use 30-second ticket via WebSocket subprotocol, private local SSH socket forwarding, unauthenticated verification of SSH-derived identity before bearer, `local_port = null`, and local-kind hubs. Phase-3 `AuthGuard` replaces that baseline while preserving the selected HTTP caller and disabling privileged fallback through every forwarding helper. Preserve new hub timeout parameters and error semantics.
- [x] Reconcile DF-48 against its merged interfaces: planned notifications defer for all durable active states (`preparing`, `queued`, `issuing`, `settling`) independently of member counts; legacy summaries without issuance retain the held-core-lock check. Terminal `issued`/`incomplete`/`interrupted` state and absent legacy locks allow terminal member evaluation. The plan and restart regressions retain no-new-terminal-event behavior; zero-member failures are not claimed as run-terminal notification coverage.
- [ ] Run actual review rounds 5–6 only after the final main/auth baseline refresh. The refresh is now pinned to actual merged main `54259b0fbfff70b20f612e3e508da37d65efeff5`; the token/issuance pending notes above are historical and superseded. No formal round is implied by the earlier supplemental adapter checks.

Assembled phase-3 pytest/ruff/type/API/UI suites remain implementation acceptance checks; this document does not claim they ran.
