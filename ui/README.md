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
