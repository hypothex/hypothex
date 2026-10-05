# Run and chart backlog

Scope: UI-F17 KindPanels, Curves, Grid, Distribution and focused unit tests. Parent owns adapters/routes and backend owns metadata. No commits, full suites, build, or browser from this worker.

- [x] Add failing tests for trajectory ordering and exact selected-example comparison, current config highlight.
- [x] Implement trajectory-first rendering and preserve trace navigation; selected grid uses actual ID only.
- [x] Add failing chart tests and implement authoritative best config accent/recorded params, terminal empty wording and contributing-run legend.
- [x] Apply explicit baseline semantics to distribution colors without altering generic series order.
- [x] Run focused unit checks and source/unit types; hand parent evidence and documentation notes.


## Handoff

Owned source: `ui/src/pages/components/KindPanels.tsx`, `ui/src/panels/{Curves,Grid,Distribution}.tsx`, corresponding four unit files. Parent owns PanelGrid adapters and Run context wiring; backend owns best config and recorded params metadata.

- Agent run view honors trajectory-first source ordering and uses the same explicit URL/default failed-trace example ID for the current-target grid. Pending/error/empty trace selection cannot fall back to all targets. Existing trace chooser and run URLs stay intact; trace-free views keep prior grid behavior.
- Grid selects only actual matching item IDs, marks the current config, displays exact solved fraction, and keeps absent config values unknown. Missing selected ID yields explicit unavailable text.
- Curves accents only `meta.best_group_id`; stable recorded `groups[].params` subtitles truncate visibly with full tooltip and reserved header space. No best ranking is inferred from chart order. Terminal run empty text says no metric history recorded. Single-contributor cells use a run legend; real multi-seed cells keep seed/mean labels.
- Distribution uses explicit `meta.baseline` for orange baseline/blue first alternative parity; generic or unmatched baseline metadata preserves existing ordinal colors.

Evidence: `/tmp/hx-handoff-evidence/backlog-charts/`. Red: 65 pass / 8 fail (`red.log`). Final focused: 78 pass / 0 fail (`focused-final.log`). `git diff --check` clean. Source/unit typecheck initially blocked only by parent-owned TaskInsights.tsx Loading what prop errors (`types-final.log`); parent notified. No build, browser, full suite, Python, commit, or push performed by worker. Parent should cover final combined types/build/browser and document these behaviors in the consolidated UI docs.
