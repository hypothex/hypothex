# Hypothex UI

React 19 + TypeScript + Vite, built and tested with Bun. `hx serve` serves the built files
from `src/hypothex/ui_dist/`.

```bash
bun install                 # once
bun run dev                 # http://localhost:5173, proxies /api to hx serve on :7777
bun test                    # unit and component tests (happy-dom)
bun run typecheck           # tsc --noEmit
bun run build               # typecheck, then write ../src/hypothex/ui_dist/
```

Set `HX_API=http://host:port` to point the dev proxy at another `hx serve`.

### API types

`src/api/types.ts` is generated from the running server's OpenAPI document and checked in.
Regenerate it after any backend route change (from the repo root):

```bash
export HYPOTHEX_HOME="$(mktemp -d)"          # types do not depend on data
uv run hx serve --port 7777 &
until curl -sf http://127.0.0.1:7777/api/openapi.json >/dev/null; do sleep 0.5; done
(cd ui && bun run gen:types)
pkill -f "hx serve --port 7777"
```

`src/api/client.ts` checks every route it calls against the generated `paths`, so a renamed
route fails `bun run typecheck`. Response bodies are typed by `src/api/models.ts`
(hand-written from the phase 1b contract, because most routes return plain dicts).

### End-to-end tests

`bun run e2e` builds the UI and runs Playwright against two demo hubs that it starts
itself (`e2e/serve-demo.ts`):

- `hx demo`, every task kind; projects `light`, `dark`, `light-edit`, `dark-edit`.
- `hx demo --with-hosts`, fake remote hosts with GPUs, a queue, a SLURM host and a sweep;
  projects `hosts-light`, `hosts-dark`, `hosts-light-edit`, `hosts-dark-edit`.

Each listens on a port the OS reports free for that run (never a fixed port, so a test can
never land on an `hx serve` you left running on your real `~/.hypothex`). Both run with
`HYPOTHEX_SSH=false` and `HYPOTHEX_SCP=false`, so no test can reach a real host, and
neither is ever reused from a server that already answers. Every test first checks that the
hub answers with the identity `serve-demo.ts` wrote into its fresh home (`environment.json`,
labels `hx-e2e-demo` and `hx-e2e-hosts`), so no host route, note or launch can reach
another server. If a demo server cannot start, the run stops at once. Run one group with
`--project`:

```bash
bun run build && bunx playwright test --project=hosts-light --project=hosts-dark
```

Each run keeps its homes and demo files in its own directory, `e2e/.runs/run-XXXXXX`, so two
suites can run at once in one checkout without wiping each other's homes. A server removes
its home when it stops.

On stop, `serve-demo.ts` sends SIGTERM to the hub alone and waits for it: the hub's
shutdown stops the demo runs on its fake hosts, then the fake hosts. After that, after 60 s
without an exit, or when the hub dies by itself, it kills every process still running from
the run's directory (fake hosts, supervisors and their run commands; they run in their own
sessions, so a crashed hub leaves them behind). `bun e2e/shutdown-check.ts` (also run in CI)
checks three ends, each on its own random port after it has verified the hub's identity: a
SIGTERM, a killed hub, and a hub that hangs. It fails if any demo process is left.

### Serving, launches, and sweep progress

Run actions use the server's `served` flag, separately from host connection state. A
configured disconnected host can reconnect; an unmapped environment cannot run actions.
Stop arms an inline confirmation for three seconds and disarms on blur, Escape, navigation,
or a run-state change. Queued Cancel remains a direct action and sends an atomic
queue-only precondition, so a run that starts before cancellation is not stopped.

A template launch retains its environment identity and GPU request, including zero. If no
configured host matches, the dialog asks for an explicit host choice. SLURM GPU defaults
initialize a newly selected host; ordinary polling does not overwrite edits. Command
previews fill original template slots once before displaying shell quoting; slot text
inside a carried value stays literal. Requests above a connected host's total GPU count
remain visible but block Launch, even with Queue enabled.

Sweep summaries expose admission/issuance progress independently of observed members.
The UI polls preparing, queued, issuing, and settling episodes every two seconds and stops
at terminal states, including cancelled episodes whose `cancel_requested` remains true.
The `sweep.issuance` event refreshes the summary and project list. Cancel can stop accepted
issuance before its first member arrives; Resume is explicit and sends the server's exact
resume seeds. Incomplete/interrupted episodes can also cancel retained remote members
before they appear locally. Resume and Add seeds are disabled while cancellation is
pending or settling. Scored `n` and `+M` uncounted members remain separate in tables and heat cells.
