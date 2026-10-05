# Bounded host panel backlog fixes

Scope: triaged rows 18 (terse nonconnected state cells) and 21 (accessible legend label), owning HostsPanel and its focused tests only. TaskInsights comparison/provenance review is read-only. No shared API/models/screens/global docs/git actions.

- [x] Reproduce verbose no-GPU states and missing legend role with failing tests: 5 failed, 9 passed (`red.log`).
- [x] Keep state explanations in existing tooltips, preserving bootstrap progress; give the legend a semantic group. Updated the corresponding host-group inventories in the panel and Overview tests.
- [x] Run focused host tests: 22 passed across 2 files (`green.log`); scoped diff check clean. Typecheck currently blocked only by concurrent `cost_complete` additions absent from LeaderboardRowJson (`types.log`). Parent owns assembled validation.
- [x] Independently inspect TaskInsights comparison provenance. Reported missing metric source hashes being accepted as equal; owner accepted a fail-closed correction. Also flagged first-prediction-only discovery as insufficient evidence for claiming no binary outcomes; owner is investigating. Review only, no edits to TaskInsights.

Evidence: `/tmp/hx-handoff-evidence/backlog-hosts/`.

Host implementation/tests frozen. No shared API/model/source edits, commits, staging, publication, full suite, or browser run.
