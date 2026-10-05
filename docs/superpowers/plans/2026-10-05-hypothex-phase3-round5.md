# Phase 3: formal round 5 resolutions

Status: plan-only fixes, prepared for final formal round 6. Phase 3 remains unimplemented. The actual merged-main baseline is `54259b0fbfff70b20f612e3e508da37d65efeff5`.

The actual read-only `codex exec -s read-only` round 5 returned nine P2 findings. All nine are addressed in the plans:

1. Backend Task 27 now explicitly adapts the existing batch `stop_queued` route to three-argument `once(request, body, fn)`, launch scope and owner/admin checks for every existing member before any cancellation. Missing IDs retain baseline per-member error accounting; receipt retries retain the original result.
2. Task-wide re-evaluation retains main's local/host partition, down-host aggregation and merged reports. Only caller-bound receipts are added; the retained `_reeval_on` appends the run suffix.
3. `forward` retains unserved-mirror edit refusal and the imported-run exception.
4. The owner-filtered runs route retains keyset cursors, paired-cursor validation, queue rank enrichment and host state.
5. Local reinfer retains `vars` while adding trusted owner and creator fields.
6. Forwarded re-evaluation retains the 600-second timeout.
7. Task 41 normalizes an omitted tool agent through the configured server agent, including body attribution and the HTTP header; explicit overrides still win, and existing missing-run error mapping remains.
8. Task 32 transport tests patch the actual `_hub_request` seam used by main's pooled HTTP implementation.
9. Frontend Task 25 tests the authenticated Blob download button: await download, verify filename and compare saved CSV bytes with the paired API response.

The adjacent completeness audit also adds public `HEAD /api/v1/identity`, the retained read-scoped WebSocket ticket method, and read scopes for `get_logs` and `compare_examples`. The unmerged backlog's optional example-binding flag remains explicitly prospective.

Verification is bounded and does not claim an assembled Phase 3 implementation:

- An executable source/plan audit accounts for all 54 existing HTTP method/path pairs, all 29 MCP tools, and every one of 17 retained `once`/`forward` calls with the new arity.
- Five isolated probes execute exact planned helper bodies with in-memory fakes. The reviewed version fails all five and the revised version passes: unserved-mirror refusal, re-evaluation timeout/receipt, reinfer variables, batch preauthorization/receipt and configured agent forwarding.
- Eleven targeted plan assertions fail before and pass after. AST deltas for the restored adapters were compared with actual main.
- The new ownership regression module passes undefined-name checks; changed Python fences parse and added regression examples are Ruff-formatted. Frontend team-spec syntax is checked separately. Full planned API/MCP/browser regression examples are included, but have not been run as assembled product suites.
- Runtime, UI, tests, dependency and task trees remain identical to actual main. No server, real host, SSH access, database or Phase 3 implementation was used for these checks.

Raw formal round-5 evidence is retained under `/tmp/hx-handoff-evidence/phase3-round5/`; bounded fix evidence under `/tmp/hx-handoff-evidence/phase3-round5-fixes/`. Final round 6 must review the complete contract/backend/frontend against actual main, including these resolutions, before handoff.
