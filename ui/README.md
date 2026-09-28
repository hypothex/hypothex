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
