# Hypothex Phase 1b Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Hypothex web UI in `ui/` (Overview, Task with view tabs, Run, Examples, View editor, ⌘K palette, live updates) over the phase 1b API, shipped as `src/hypothex/ui_dist/` and served by `hx serve`.

**Architecture:** One typed client (`ui/src/api/`: generated OpenAPI paths, hand-written contract models, TanStack Query keys and hooks) is the only data layer; every screen and panel reads through it, so the WebSocket event stream refreshes every page by invalidating one set of key families. Panels are React SVG components keyed by `PanelType` in one registry; pages lay them out as lettered figures on a 12-column grid, and the view editor previews unsaved YAML through the same registry. Code-defined TanStack routes render thin screen wrappers around prop-driven pages.

**Tech Stack:** Bun, Vite 8, React 19, TypeScript 5.9 (strict), TanStack Router and Query, d3-scale/d3-shape/d3-array/d3-format (math only), vega-embed, CodeMirror 6 (`@codemirror/lang-yaml`, lint gutter), happy-dom + Testing Library (`bun test`), Playwright; `uv` for every Python command (`uv run hx ...`).

**Spec:** `docs/superpowers/specs/2026-09-26-hypothex-design.md` section 8 (UI, task kinds, views).

**Contract:** `docs/superpowers/plans/2026-09-27-hypothex-phase1b-contract.md` (section 4 is this plan's scope; sections 1–2 are the shapes and routes it consumes). Every name, field and route in it is exact.

**Depends on:** `docs/superpowers/plans/2026-09-27-hypothex-phase1b-backend.md` merged: the section 2 routes, `hx demo`, `hx serve` serving `src/hypothex/ui_dist/` with SPA fallback, and the wheel's hatch `artifacts` entry for `ui_dist`.

## Global Constraints

- Stack (contract 4): Bun + Vite + React 19 + TypeScript (strict). TanStack Router (file-free, code routes) + TanStack Query. CodeMirror 6 (`@codemirror/lang-yaml`, lint gutter) for the view editor. `vega-embed` for `vega_lite`. `d3-scale`, `d3-shape`, `d3-array`, `d3-format` for chart math only. No Tailwind, no component kit.
- Tooling: Bun only for JavaScript (`bun install`, `bun add`, `bun test`, `bunx`); never npm, yarn or pnpm. `uv` only for Python (`uv run hx ...`, `uv sync`, `uv build`); never pip.
- Tests (contract 4): `bun test` with `happy-dom` + `@testing-library/react`; unit and component tests live in `ui/test/`, mirroring `ui/src/` (`ui/bunfig.toml` has `root = "./test"`). Playwright (`bunx playwright test`) smoke tests live in `ui/e2e/` and run against `hx serve` on a `hx demo` home, in light and dark.
- Build (contract 4): `bun run build` writes `src/hypothex/ui_dist/` (git-ignored; built in CI and before packaging). This plan does not touch `pyproject.toml`.
- Types (contract 4): `ui/src/api/types.ts` is generated from `/api/openapi.json` with `bunx openapi-typescript`, checked in, never edited by hand; `bun run gen:types` regenerates it. Response bodies are typed by `ui/src/api/models.ts`, the only hand-written copy of the contract shapes.
- Routes (contract 4, exact): `/` Overview, `/t/:project/:task` Task (view tabs, `?view=<name>`), `/t/:project/:task/edit/:view` View editor (`new` for a new view), `/r/:runId` Run, `/x/:a/:b` Examples (query `metric`).
- Design tokens (contract 4): copied verbatim from `docs/mockups/ui-v4/index.html` into `ui/src/styles/tokens.css` (light on `:root` + `[data-theme="dark"]`). Plain CSS over the tokens; dark and light mode are equal citizens (spec 8.1).
- Panels (contract 4): one component per `PanelType` in `ui/src/panels/<Type>.tsx`, each taking `{result: PanelResult}`; registry `ui/src/panels/index.ts` maps type → component; an unknown type renders a small error box.
- Live updates (contract 4): `useEventStream()` subscribes to `/api/v1/ws` with `after_sequence` replay and invalidates TanStack Query keys by event (`run.*` → runs, leaderboard, overview, views/query).
- Copy (contract 4, spec 8.1): terse; explanations only in `title` tooltips. Each page's headline is one line with the finding and its number (for example `SVM +0.037 over rf, p = 0.15`). Panels are lettered (a, b, c …) with a few-word title; no identical bordered cards. Monospace only for paths, commands, and YAML.
- Noise (spec 8.1): seed noise as per-seed dots, identical seeds collapse to `◇×3` (never a fake `± 0`); test-set noise as a 95% interval; the best group's interval is a band the other rows are compared against.
- Numbers: negative numbers use U+2212 (`−`); p-values print `p = 0.15` (two decimals), three decimals below 0.01, `p < 0.001` when tiny, matching the server's headline formatter (contract 1.8); a missing value is `—`.
- Where everything is (spec 8.1): run pages list code, data, run folder, logs, predictions, checkpoints as `host:path`; the run folder is shown once and its children relative to it.
- Views (contract 1.4): view names match `^[a-z0-9][a-z0-9_-]*$`; `overview` is reserved for the kind preset. Invalid views are never saved (spec 8.6).
- Actions: every POST carries a client-made `command_id` (UUID) and `created_by: "human"`; a retry after a dropped connection reuses the same `command_id`.
- Commits: conventional commit messages (`feat(ui): ...`, `test(ui): ...`, `ci: ...`); no `Co-Authored-By` lines and no AI attribution in commits or PR text.

## Review Focus

1. **A run event must refresh the page the user is looking at.** A note, score or status change arriving on the WebSocket must invalidate the exact query keys the Overview, Task, Run and Examples pages and the editor preview use (and must not reload an open view document). Test: `a run event refreshes every page query of that run and project, and no view text` in Task 42.
2. **Every panel type a preset uses must draw.** An `agent_eval` or `system_bench` preset that shows `Unknown panel type: scatter` boxes is broken for the user even though each panel file passes its own tests. Test: `every contract panel type has a registered component` in Task 20.
3. **Every route must show its screen and keep its search values.** A route left on its placeholder, or a run route that drops `?log=stderr` (the Overview's `Open stderr` link) or `?example=`, silently loses the user's click. Tests: `/r/:runId keeps ?log and ?example for the run page` in Task 35 and `every route renders its own screen, not the placeholder` in Task 41.
4. **The Examples page on a task whose binary field is not `correct`.** Agent tasks score `solved`. Phase 1a `GET /compare/examples` and `GET /runs/{id}/predictions` default to `field="correct"` (the backend plan does not change them; its `pick_field` is used only inside the leaderboard), and `compare_examples` keeps only examples that have `field`. So a request without `field` on an agent task answers 200 with `fixed = []`, `broken = []`, `both_pass = both_fail = 0`: the page shows `fixes 0, breaks 0, p = 1.00` and an empty errors table, with no error. The page must read the field from one row of B's per-example scores (`correct`, then `solved`, then the first boolean field) and send it to both routes. Test: `sends the solved field to compare and to the errors query` in Task 37.
5. **A panel that throws on a page.** Malformed rows in one panel of a Task or Run page must show `Panel failed: <message>` in that panel while the other panels still draw. Test: `a panel that throws shows its error and the other panels still draw` in Task 25.

---

## File Structure

```
.gitignore                          + ui/node_modules/, src/hypothex/ui_dist/            (Task 1)
.github/workflows/ci.yml            + `ui` job: bun test, build, Playwright              (Task 47)
docs/ui.rst                         Web UI page: screens, build, dev server, tests       (Task 48)
docs/index.rst                      + `ui` toctree entry after `views`                   (Task 48)
tests/test_docs_ui.py               the page is in the toctree and names the commands    (Task 48)
ui/
  package.json bun.lock tsconfig.json vite.config.ts bunfig.toml index.html README.md  (Task 1)
  playwright.config.ts              light/dark read-only and edit projects               (Task 43)
  src/
    main.tsx                        QueryClientProvider, LiveUpdates, RouterProvider     (Tasks 1, 2, 6, 42)
    router.tsx                      code routes, AppShell, NotFound, screen wrappers     (Tasks 6, 7; wired in Tasks 29, 30, 35, 37, 41)
    styles/tokens.css               verbatim mockup tokens                               (Task 2)
    styles/base.css                 fonts, chrome, type, stats, figures, buttons, palette (Task 2)
    api/types.ts                    GENERATED OpenAPI paths                              (Task 3)
    api/models.ts                   contract response and body shapes (the only copy)    (Task 3)
    api/client.ts                   ROUTES, ApiError, api.*, wsUrl, newCommandId         (Task 3)
    api/queries.ts                  queryKeys, RUN_EVENT_INVALIDATES, hooks, mutations   (Task 4)
    api/events.ts                   EventStream, useEventStream, LiveUpdates             (Task 42)
    shell/ThemeToggle.tsx           useTheme, setTheme, toggleTheme, ThemeToggle         (Task 5)
    shell/Header.tsx                brand, screen tabs from recent targets, find button  (Task 6)
    shell/CommandPalette.tsx        ⌘K palette and toast                                 (Task 7)
    charts/Scale.tsx                scales, number formats, MINUS, fmtP, width hook      (Task 8)
    charts/Axis.tsx Tooltip.tsx     axes, grids, hover tooltips                          (Task 9)
    charts/Glyphs.tsx charts.css    seed dots, diamonds, whiskers, band, event marks, key (Task 10)
    panels/index.ts panels.css      PANELS registry, Panel, PanelBoundary, PanelError    (Tasks 11–13, 20)
    panels/StatStrip.tsx            stat_strip                                           (Task 11)
    panels/Leaderboard.tsx          leaderboard forest plot                              (Task 12)
    panels/Curves.tsx               curves small multiples                               (Task 13)
    panels/Table.tsx Markdown.tsx Trace.tsx Distribution.tsx Scatter.tsx Grid.tsx VegaLite.tsx (Tasks 14–20)
    pages/components/types.ts       page names over the models, status sets              (Task 21)
    pages/components/format.ts      page number, time and path formats                  (Task 22)
    pages/components/links.tsx      hrefs, AppLink, NavigateContext                      (Task 23)
    pages/components/styles.ts Figure.tsx StatStrip.tsx CopyButton.tsx QueryState.tsx   (Task 24)
    pages/components/PanelGrid.tsx  lettered 12-column grid, PanelBody                   (Task 25)
    pages/components/useAction.ts   idempotent actions over api.*                        (Task 26)
    pages/components/RunTimeline.tsx IdeaList.tsx OverviewLists.tsx                      (Tasks 27, 28)
    pages/components/WhereList.tsx ScoresList.tsx runStats.ts StatusLine.tsx           (Tasks 31, 32)
    pages/components/Notes.tsx RunActions.tsx KindPanels.tsx LogView.tsx               (Tasks 33, 34)
    pages/components/examples.ts ExampleCharts.tsx                                      (Task 36)
    pages/Overview.tsx Task.tsx Run.tsx Examples.tsx                                    (Tasks 29, 30, 35, 37)
    editor/YamlEditor.tsx PanelPalette.tsx Preview.tsx editor.css                       (Tasks 38–41)
    pages/ViewEditor.tsx            the view editor page                                 (Task 41)
  test/                             mirrors src/: setup.ts, render-app.tsx, api/fetch-mock.ts, pages/fixtures.ts, pages/helpers.tsx, *.test.ts(x)
  e2e/                              paths.ts serve-demo.ts fixtures.ts tsconfig.json .gitignore pages.spec.ts editor.spec.ts live.spec.ts (Tasks 43–46)
```

Each file has one job: `api/` talks to the server, `charts/` draws marks, `panels/` turns one `PanelResult` into a figure body, `pages/components/` builds page sections, `pages/` composes one screen from props, `router.tsx` maps URLs to screens.

## Part 1: Scaffold, tokens, API client, shell (Tasks 1–7)

Builds `ui/`: the Bun + Vite + React 19 + TypeScript (strict) app, the verbatim design tokens and shared base CSS, the generated OpenAPI types plus the hand-written contract models and typed client (the only fetch layer in the UI), the TanStack Query keys and hooks every screen uses, the theme toggle, code-defined routes with the header, and the ⌘K palette. Each screen task later replaces its route's `ScreenPending` placeholder with the real screen.

### Task 1: `ui/` scaffold (Bun, Vite, React 19, TS strict, happy-dom tests, build to `ui_dist`)

**Files:**
- Create: `ui/package.json`, `ui/tsconfig.json`, `ui/vite.config.ts`, `ui/bunfig.toml`, `ui/index.html`, `ui/src/main.tsx`, `ui/README.md`, `ui/test/setup.ts`
- Create (generated): `ui/bun.lock`
- Modify: `.gitignore` (append two lines)
- Test: `ui/test/setup.test.ts`

**Interfaces:**
- Consumes: the backend plan merged: `hx serve` serves `src/hypothex/ui_dist` with SPA fallback, and `pyproject.toml` already lists `artifacts = ["src/hypothex/ui_dist/**"]` under `[tool.hatch.build.targets.wheel]`.
- Produces: `bun test` (root `ui/test`, preload `ui/test/setup.ts`), `bun run dev|build|typecheck|gen:types`; `bun run build` writes `src/hypothex/ui_dist/index.html` + `assets/`; dev server on `:5173` proxies `/api` (HTTP + WebSocket) and `/.well-known` to `HX_API` (default `http://127.0.0.1:7777`).

Versions below were resolved on 2026-09-27 (`vite` 8 uses Rolldown; `typescript` is pinned to 5.9 because `openapi-typescript` 7 has peer `typescript ^5.x`; TypeScript 7 is the native port).

- [ ] **Step 1: Write the failing test**

Run `mkdir -p ui/test`, then write:

`ui/test/setup.test.ts`:

```ts
import { expect, test } from "bun:test";

test("happy-dom provides a document", () => {
  const el = document.createElement("p");
  el.textContent = "hi";
  document.body.append(el);
  expect(document.body.querySelector("p")?.textContent).toBe("hi");
  expect(location.origin).toBe("http://127.0.0.1:7777");
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ui && bun test test/setup.test.ts`
Expected: FAIL with `ReferenceError: document is not defined` (no happy-dom preload yet).

- [ ] **Step 3: Write the scaffold**

`ui/package.json`:

```json
{
  "name": "hypothex-ui",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "typecheck": "tsc --noEmit",
    "test": "bun test",
    "gen:types": "openapi-typescript http://127.0.0.1:7777/api/openapi.json -o src/api/types.ts"
  },
  "dependencies": {
    "@fontsource-variable/geist": "^5.3.0",
    "@fontsource-variable/geist-mono": "^5.3.0",
    "@fontsource-variable/newsreader": "^5.3.0",
    "@tanstack/react-query": "^5.104.0",
    "@tanstack/react-router": "^1.170.39",
    "react": "^19.3.0",
    "react-dom": "^19.3.0"
  },
  "devDependencies": {
    "@happy-dom/global-registrator": "^20.14.5",
    "@testing-library/dom": "^10.4.2",
    "@testing-library/react": "^16.3.3",
    "@testing-library/user-event": "^14.6.7",
    "@types/bun": "^1.4.2",
    "@types/react": "^19.3.0",
    "@types/react-dom": "^19.3.0",
    "@vitejs/plugin-react": "^6.1.1",
    "openapi-typescript": "^7.13.0",
    "typescript": "~5.9.3",
    "vite": "^8.3.1"
  }
}
```

`ui/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2023", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noFallthroughCasesInSwitch": true,
    "isolatedModules": true,
    "resolveJsonModule": true,
    "skipLibCheck": true,
    "noEmit": true,
    "types": ["bun", "vite/client"]
  },
  "include": ["src", "test", "vite.config.ts"]
}
```

`ui/vite.config.ts`:

```ts
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/** The `hx serve` the dev server forwards `/api` to. */
const API = process.env.HX_API ?? "http://127.0.0.1:7777";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: fileURLToPath(new URL("../src/hypothex/ui_dist", import.meta.url)),
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: API, ws: true },
      "/.well-known": { target: API },
    },
  },
});
```

`ui/bunfig.toml`:

```toml
[test]
root = "./test"
preload = ["./test/setup.ts"]
```

`ui/test/setup.ts`:

```ts
import { GlobalRegistrator } from "@happy-dom/global-registrator";

GlobalRegistrator.register({ url: "http://127.0.0.1:7777/" });

const { afterEach } = await import("bun:test");
const { cleanup } = await import("@testing-library/react");

afterEach(() => {
  cleanup();
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});
```

`ui/index.html` (the inline script sets the theme before first paint, as in the mockup: `?theme=`, then `localStorage["hx-theme"]`, then the OS preference):

```html
<!doctype html>
<html lang="en" data-theme="light">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Hypothex</title>
    <script>
      (function () {
        var q = new URLSearchParams(location.search).get("theme");
        var s = null;
        try { s = localStorage.getItem("hx-theme"); } catch (e) {}
        var t = q === "dark" || q === "light" ? q : s === "dark" || s === "light" ? s
          : matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
        document.documentElement.dataset.theme = t;
      })();
    </script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

`ui/src/main.tsx` (temporary; Task 2 adds the stylesheets and Task 6 the router):

```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

function App() {
  return <p>Hypothex</p>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

`ui/README.md`:

````markdown
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
````

Append to `.gitignore`:

```
ui/node_modules/
src/hypothex/ui_dist/
```

Do not edit `pyproject.toml`: the backend plan already ships `ui_dist` in the wheel through hatch `artifacts` (a no-op when the folder is absent). Step 4 checks that the built UI lands in the wheel.

Install (writes `ui/bun.lock` and `ui/node_modules/`):

Run: `cd ui && bun install`
Expected: ends with `95 packages installed` (the count may differ by a few with newer patch releases).

- [ ] **Step 4: Run the test and the build**

Run: `cd ui && bun test`
Expected: `1 pass`, `0 fail`.

Run: `cd ui && bun run build`
Expected: `tsc --noEmit` prints nothing, then Vite prints `../src/hypothex/ui_dist/index.html` and one `assets/index-*.js` line and `✓ built in ...`.

Run: `ls src/hypothex/ui_dist && git status --short src/hypothex/ui_dist ui/node_modules`
Expected: `assets  index.html`, and `git status` prints nothing for those paths (ignored).

Run: `uv build --wheel -o /tmp/hx-wheel && unzip -l /tmp/hx-wheel/hypothex-*.whl | grep ui_dist/index.html; rm -rf /tmp/hx-wheel`
Expected: one line ending in `hypothex/ui_dist/index.html`.

- [ ] **Step 5: Check the dev proxy against a live `hx serve`**

Run (from the repo root):

```bash
export HYPOTHEX_HOME="$(mktemp -d)"
uv run hx serve --port 7777 > /tmp/hx-serve.log 2>&1 &
(cd ui && bunx vite --port 5173 > /tmp/hx-vite.log 2>&1 &)
until curl -sf http://127.0.0.1:7777/api/v1/projects >/dev/null; do sleep 0.5; done
until curl -sf http://localhost:5173/ >/dev/null; do sleep 0.5; done
curl -s http://localhost:5173/api/v1/projects; echo
curl -s -X POST -H 'Origin: http://localhost:5173' -H 'Content-Type: application/json' -d '{}' \
  http://localhost:5173/api/v1/runs/nope/star; echo
pkill -f "hx serve --port 7777"; pkill -f "vite --port 5173"
```

Expected: `[]` then `{"error":"no run 'nope'","type":"RunNotFoundError"}` (the POST passes `OriginGuard` because `localhost` is a loopback origin).

- [ ] **Step 6: Commit**

```bash
git add .gitignore ui/package.json ui/bun.lock ui/tsconfig.json ui/vite.config.ts ui/bunfig.toml ui/index.html ui/README.md ui/src/main.tsx ui/test/setup.ts ui/test/setup.test.ts
git commit -m "feat(ui): scaffold bun + vite + react app building into ui_dist"
```

### Task 2: Design tokens and shared base CSS

**Files:**
- Create: `ui/src/styles/tokens.css`, `ui/src/styles/base.css`
- Modify: `ui/src/main.tsx` (import both stylesheets)
- Test: `ui/test/styles/styles.test.ts`

**Interfaces:**
- Consumes: Task 1 scaffold; `docs/mockups/ui-v4/index.html` (lines 19-53 are the tokens).
- Produces: CSS custom properties `--paper --paper-2 --ink --ink-2 --ink-3 --rule --rule-2 --best --best-wash --best-edge --fail --agent --human --serif --sans --mono` (light on `:root`, dark on `[data-theme="dark"]`); shared classes from the mockup: `.bar .bar-in .brand .tabs .bar-r .find .theme main .crumb h1.finding .lede .metaline .hint .stats .fig .fig-h .caption .small svg .tk/.lbl/.axis/.grid/.band/... .who .btn(.primary/.link) .cmd .key .tbl .tag .p .host .copy .pal* .toast .tip .num .path`; fonts `"Geist"`, `"Geist Mono"`, `"Newsreader"` served from the bundle (no Google Fonts request).

- [ ] **Step 1: Write the failing test**

`ui/test/styles/styles.test.ts`:

```ts
import { describe, expect, test } from "bun:test";

const read = (rel: string): Promise<string> => Bun.file(new URL(rel, import.meta.url)).text();

/** The `:root { ... }` and `[data-theme="dark"] { ... }` blocks of the approved mockup. */
async function mockupTokens(): Promise<string> {
  const html = await read("../../../docs/mockups/ui-v4/index.html");
  const start = html.indexOf(":root {");
  const darkStart = html.indexOf('[data-theme="dark"] {');
  const end = html.indexOf("}", darkStart) + 1;
  if (start < 0 || darkStart < start) throw new Error("token blocks not found in mockup");
  return html.slice(start, end);
}

describe("tokens.css", () => {
  test("is a verbatim copy of the mockup tokens (light and dark)", async () => {
    const tokens = await read("../../src/styles/tokens.css");
    const expected = await mockupTokens();
    expect(tokens).toContain(expected);
    expect(tokens).toContain("--paper: #F6F7F3;");
    expect(tokens).toContain("--best: #1FA282;");
  });
});

describe("base.css", () => {
  test("self-hosts the three mockup fonts under their token names", async () => {
    const css = await read("../../src/styles/base.css");
    for (const family of ['"Geist"', '"Geist Mono"', '"Newsreader"']) {
      expect(css).toContain(`font-family: ${family};`);
    }
    expect(css).not.toContain("fonts.googleapis.com");
  });

  test("carries the shared chrome, palette and figure rules", async () => {
    const css = await read("../../src/styles/base.css");
    for (const sel of [".bar {", ".bar-in {", ".brand {", ".tabs a[aria-current=\"page\"]", ".find {",
      ".theme {", "main {", "h1.finding {", ".stats {", ".fig-h {", ".btn {", ".tbl {", ".pal {",
      ".pal-list li.it[aria-selected=\"true\"]", ".toast {", ".tip {"]) {
      expect(css).toContain(sel);
    }
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ui && bun test test/styles`
Expected: FAIL with `ENOENT` / `No such file or directory` for `src/styles/tokens.css`.

- [ ] **Step 3: Write the stylesheets**

`ui/src/styles/tokens.css` is the mockup's token blocks, byte for byte. Generate it instead of retyping (from the repo root):

```bash
mkdir -p ui/src/styles
{ echo '/* Design tokens, copied verbatim from docs/mockups/ui-v4/index.html. Do not edit by hand. */'
  sed -n 19,53p docs/mockups/ui-v4/index.html; } > ui/src/styles/tokens.css
```

The result must be exactly:

```css
/* Design tokens, copied verbatim from docs/mockups/ui-v4/index.html. Do not edit by hand. */
:root {
  --paper: #F6F7F3;
  --paper-2: #ECEEE8;
  --ink: #15181E;
  --ink-2: #464C57;
  --ink-3: #767C87;
  --rule: #D5D8D0;
  --rule-2: #E4E6E0;
  --best: #00846A;
  --best-wash: rgba(0, 132, 106, .12);
  --best-edge: rgba(0, 132, 106, .50);
  --fail: #C8412B;
  --agent: #5B48C2;
  --human: #A66A12;
  --serif: "Newsreader", "Iowan Old Style", Georgia, serif;
  --sans: "Geist", ui-sans-serif, system-ui, sans-serif;
  --mono: "Geist Mono", ui-monospace, "SF Mono", Menlo, monospace;
  color-scheme: light;
}
[data-theme="dark"] {
  --paper: #12161C;
  --paper-2: #1A1F27;
  --ink: #E9ECEF;
  --ink-2: #AEB5BF;
  --ink-3: #7C8490;
  --rule: #2C333D;
  --rule-2: #222830;
  --best: #1FA282;
  --best-wash: rgba(31, 162, 130, .17);
  --best-edge: rgba(31, 162, 130, .60);
  --fail: #DE5F49;
  --agent: #8C7BEA;
  --human: #C08629;
  color-scheme: dark;
}
```

`ui/src/styles/base.css` (the `@font-face` rules point at the `@fontsource-variable/*` files; Vite resolves the bare `url()` specifiers and bundles the `.woff2` files, so the token font names `"Geist"`, `"Geist Mono"`, `"Newsreader"` work offline; the rest is copied from mockup lines 55-188, 194-196, 224-228, 267, 277-279, 284-285, 333-353 and the chrome parts of the two media queries):

```css
/* Shared styles from docs/mockups/ui-v4/index.html: reset, chrome, type, figures, buttons,
   palette, toast, tooltip. Screen-specific rules live next to each screen. */

/* ------------------------------------------------------------------ fonts (self-hosted) */
@font-face {
  font-family: "Geist"; font-style: normal; font-display: swap; font-weight: 100 900;
  src: url("@fontsource-variable/geist/files/geist-latin-wght-normal.woff2") format("woff2-variations");
}
@font-face {
  font-family: "Geist Mono"; font-style: normal; font-display: swap; font-weight: 100 900;
  src: url("@fontsource-variable/geist-mono/files/geist-mono-latin-wght-normal.woff2") format("woff2-variations");
}
@font-face {
  font-family: "Newsreader"; font-style: normal; font-display: swap; font-weight: 200 800;
  src: url("@fontsource-variable/newsreader/files/newsreader-latin-standard-normal.woff2") format("woff2-variations");
}
@font-face {
  font-family: "Newsreader"; font-style: italic; font-display: swap; font-weight: 200 800;
  src: url("@fontsource-variable/newsreader/files/newsreader-latin-standard-italic.woff2") format("woff2-variations");
}

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0; background: var(--paper); color: var(--ink);
  font: 400 15px/1.5 var(--sans);
  font-feature-settings: "ss01" 0;
  -webkit-font-smoothing: antialiased;
}
a { color: inherit; text-decoration: underline; text-decoration-color: var(--rule); text-underline-offset: 3px; text-decoration-thickness: 1px; }
a:hover { text-decoration-color: currentColor; }
:focus-visible { outline: 2px solid var(--agent); outline-offset: 2px; border-radius: 3px; }
button { font: inherit; color: inherit; }
.num { font-variant-numeric: tabular-nums; }
.path, code, kbd { font-family: var(--mono); font-size: .86em; }

/* ------------------------------------------------------------------ chrome */
.bar {
  position: sticky; top: 0; z-index: 20;
  background: color-mix(in srgb, var(--paper) 92%, transparent);
  backdrop-filter: blur(8px);
  border-bottom: 1px solid var(--rule);
}
.bar-in { max-width: 1280px; margin: 0 auto; padding: 0 40px; height: 60px; display: flex; align-items: stretch; gap: 40px; }
.brand { display: flex; align-items: center; gap: 10px; text-decoration: none; font: 600 21px/1 var(--serif); letter-spacing: -.01em; }
.brand svg { display: block; }
.tabs { display: flex; gap: 4px; }
.tabs a {
  display: flex; align-items: center; padding: 0 12px; text-decoration: none; color: var(--ink-3);
  font-size: 14.5px; border-bottom: 2px solid transparent; margin-bottom: -1px;
}
.tabs a:hover { color: var(--ink); }
.tabs a[aria-current="page"] { color: var(--ink); border-bottom-color: var(--ink); font-weight: 500; }
.bar-r { margin-left: auto; display: flex; align-items: center; gap: 10px; }
.find {
  display: flex; align-items: center; gap: 28px; height: 34px; padding: 0 8px 0 12px; min-width: 250px;
  border: 1px solid var(--rule); border-radius: 7px; background: transparent; color: var(--ink-3); cursor: pointer; font-size: 13.5px;
}
.find:hover { border-color: var(--ink-3); }
.find kbd { margin-left: auto; font-family: var(--sans); font-size: 12px; color: var(--ink-2); border: 1px solid var(--rule); border-radius: 4px; padding: 1px 5px; }
.theme { height: 34px; padding: 0 12px; border: 1px solid var(--rule); border-radius: 7px; background: transparent; cursor: pointer; font-size: 13.5px; color: var(--ink-2); display: flex; gap: 8px; align-items: center; }
.theme:hover { border-color: var(--ink-3); color: var(--ink); }

main { max-width: 1280px; margin: 0 auto; padding: 44px 40px 120px; }

/* ------------------------------------------------------------------ type */
.crumb { margin: 0 0 18px; font-size: 13.5px; color: var(--ink-3); }
.crumb a { color: var(--ink-2); text-decoration: none; }
.crumb a:hover { text-decoration: underline; }
.crumb .sep { margin: 0 6px; color: var(--rule); }
h1.finding {
  margin: 0; max-width: 21em;
  font: 500 46px/1.06 var(--serif); font-variation-settings: "opsz" 72;
  letter-spacing: -.018em; text-wrap: balance;
}
h1.finding .then { color: var(--ink-2); font-weight: 400; }
.lede { margin: 18px 0 0; max-width: 64ch; font: 400 19.5px/1.5 var(--serif); font-variation-settings: "opsz" 16; color: var(--ink-2); text-wrap: pretty; }
.metaline { margin: 14px 0 0; display: flex; flex-wrap: wrap; gap: 4px 22px; font-size: 14px; color: var(--ink-3); font-variant-numeric: tabular-nums; align-items: center; }
.metaline b { color: var(--ink-2); font-weight: 500; }
.hint { text-decoration: underline dotted var(--rule); text-underline-offset: 3px; cursor: help; }

/* stat strip: numbers with short labels; explanations live in the title tooltips */
.stats { display: flex; flex-wrap: wrap; gap: 14px 0; margin: 0; padding: 0; }
.stats > div { padding: 0 32px; border-left: 1px solid var(--rule-2); cursor: help; }
.stats > div:first-child { padding-left: 0; border-left: 0; }
.stats dt { font-size: 12.5px; color: var(--ink-3); }
.stats dd { margin: 0 0 3px; font: 400 25px/1.1 var(--sans); letter-spacing: -.012em; font-variant-numeric: tabular-nums; color: var(--ink); }
.stats dd small { font-size: 15px; color: var(--ink-3); letter-spacing: 0; }
.stats > div { display: flex; flex-direction: column-reverse; }

/* figure panels: space, letters, captions. No boxes. */
.fig { margin-top: 64px; }
.fig + .fig { margin-top: 64px; }
.fig-h { display: flex; align-items: baseline; gap: 12px; margin: 0 0 18px; }
.fig-h .pl { font: 700 19px/1 var(--sans); }
.fig-h .t { font: 600 16px/1.3 var(--sans); }
.fig-h .aside { margin-left: auto; font-size: 13px; color: var(--ink-3); }
.caption { margin: 16px 0 0; max-width: 78ch; font: 400 15.5px/1.52 var(--serif); font-variation-settings: "opsz" 12; color: var(--ink-2); text-wrap: pretty; }
.caption b { font-weight: 650; color: var(--ink); }
.small { font-size: 13px; color: var(--ink-3); }

/* svg figure text */
svg text { font-family: var(--sans); fill: var(--ink-2); }
svg .tk { font-size: 11.5px; fill: var(--ink-3); font-variant-numeric: tabular-nums; }
svg .lbl { font-size: 12.5px; fill: var(--ink-2); }
svg .lbl-s { font-size: 11.5px; fill: var(--ink-3); }
svg .lbl-b { font-size: 12.5px; fill: var(--ink); font-weight: 600; }
svg .axis { stroke: var(--ink-3); stroke-width: 1; }
svg .grid { stroke: var(--rule-2); stroke-width: 1; }
svg .hair { stroke: var(--rule); stroke-width: 1; }
svg .band { fill: var(--best-wash); }
svg .band-edge { stroke: var(--best-edge); stroke-width: 1; }
svg .bestline { stroke: var(--best); stroke-width: 1.25; }
svg .whisk { stroke: var(--ink-3); stroke-width: 1.5; stroke-linecap: round; fill: none; }
svg .whisk.best { stroke: var(--best); }
svg .mean { fill: var(--ink); stroke: var(--paper); stroke-width: 2; }
svg .mean.best { fill: var(--best); }
svg .seed { fill: var(--ink-2); stroke: var(--paper); stroke-width: 2; }
svg .dia { fill: var(--paper); stroke: var(--ink); stroke-width: 1.6; }
svg .dia.best { stroke: var(--best); fill: var(--best-wash); }
svg .lead { stroke: var(--ink-3); stroke-width: 1; fill: none; }
svg .gap { stroke: var(--ink); stroke-width: 1.25; fill: none; }
svg .m-agent { fill: var(--agent); }
svg .m-human { fill: var(--human); }
svg .m-best { fill: var(--best); }
svg .m-ring { fill: var(--paper); stroke-width: 1.6; }
svg .m-ring.agent { stroke: var(--agent); }
svg .m-ring.human { stroke: var(--human); }
svg .m-fail { stroke: var(--fail); stroke-width: 2; stroke-linecap: round; }
svg .ringed { stroke: var(--paper); stroke-width: 2; }
svg .hit { fill: transparent; cursor: default; }

/* who glyph */
.who { display: inline-flex; align-items: center; gap: 6px; }
.who i { width: 8px; height: 8px; border-radius: 50%; display: inline-block; flex: none; }
.who.agent i { background: var(--agent); }
.who.human i { background: var(--human); border-radius: 1px; }

/* buttons */
.btn {
  height: 32px; padding: 0 13px; border-radius: 6px; border: 1px solid var(--rule); background: transparent;
  font-size: 13.5px; color: var(--ink); cursor: pointer; white-space: nowrap;
}
.btn:hover { border-color: var(--ink-3); }
.btn.primary { background: var(--ink); color: var(--paper); border-color: var(--ink); }
.btn.primary:hover { opacity: .88; }
.btn:disabled { color: var(--ink-3); cursor: not-allowed; border-color: var(--rule-2); }
.btn.link { border: 0; padding: 0; height: auto; color: var(--ink-2); text-decoration: underline; text-decoration-color: var(--rule); text-underline-offset: 3px; }
.btn.link:hover { color: var(--ink); text-decoration-color: currentColor; }

.cmd {
  display: block; padding: 12px 14px; background: var(--paper-2); border-radius: 6px;
  font: 400 13px/1.6 var(--mono); color: var(--ink); white-space: pre-wrap; word-break: break-word;
}

.key { display: flex; flex-wrap: wrap; gap: 6px 22px; margin-top: 14px; font-size: 13px; color: var(--ink-2); }
.key span { display: inline-flex; align-items: center; gap: 7px; }
.key svg { display: block; overflow: visible; }
.tbl { width: 100%; border-collapse: collapse; font-size: 14px; }
.tbl th { text-align: left; font-weight: 500; color: var(--ink-3); font-size: 12.5px; padding: 0 0 8px; border-bottom: 1px solid var(--rule); }
.tbl td { padding: 10px 0; border-bottom: 1px solid var(--rule-2); vertical-align: top; }
.tbl .r { text-align: right; font-variant-numeric: tabular-nums; }
.tbl tr:last-child td { border-bottom: 0; }
.tag { font-size: 12.5px; color: var(--ink-2); border: 1px solid var(--rule); border-radius: 99px; padding: 1px 9px; }
.p { font-family: var(--mono); font-size: 13px; word-break: break-all; color: var(--ink); }
.p .pre { color: var(--ink-3); }
.host { font-family: var(--sans); font-size: 11.5px; color: var(--ink-2); border: 1px solid var(--rule); border-radius: 4px; padding: 0 5px; margin-right: 8px; vertical-align: 1px; }
.copy { border: 0; background: transparent; color: var(--ink-3); font-size: 12.5px; cursor: pointer; padding: 4px; border-radius: 4px; align-self: center; }
.copy:hover { color: var(--ink); background: var(--paper-2); }

/* ------------------------------------------------------------------ palette, toast, tooltip */
.pal { position: fixed; inset: 0; z-index: 50; display: none; background: color-mix(in srgb, var(--ink) 22%, transparent); }
.pal.on { display: block; }
.pal-box {
  width: 600px; margin: 110px auto 0; background: var(--paper); border: 1px solid var(--rule); border-radius: 10px;
  box-shadow: 0 24px 60px -20px rgba(10, 14, 20, .35); overflow: hidden;
}
.pal-in { width: 100%; border: 0; border-bottom: 1px solid var(--rule); background: transparent; color: var(--ink); font: 400 20px/1 var(--serif); padding: 20px 20px; outline: none; }
.pal-list { list-style: none; margin: 0; padding: 8px; max-height: 420px; overflow: auto; }
.pal-list .grp { font-size: 12px; color: var(--ink-3); padding: 10px 12px 4px; }
.pal-list li.it { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; padding: 9px 12px; border-radius: 6px; cursor: pointer; font-size: 14.5px; align-items: baseline; }
.pal-list li.it small { color: var(--ink-3); font-size: 12.5px; }
.pal-list li.it[aria-selected="true"] { background: var(--paper-2); }
.pal-foot { border-top: 1px solid var(--rule); padding: 10px 20px; font-size: 12.5px; color: var(--ink-3); display: flex; gap: 18px; }
.pal-foot kbd { font-family: var(--sans); font-size: 11.5px; border: 1px solid var(--rule); border-radius: 4px; padding: 0 5px; color: var(--ink-2); }
.toast { position: fixed; left: 50%; bottom: 28px; transform: translate(-50%, 16px); opacity: 0; background: var(--ink); color: var(--paper); padding: 10px 16px; border-radius: 7px; font-size: 13.5px; transition: all .18s ease; pointer-events: none; z-index: 60; }
.toast.on { opacity: 1; transform: translate(-50%, 0); }
.tip { position: fixed; z-index: 40; pointer-events: none; background: var(--ink); color: var(--paper); font-size: 12.5px; line-height: 1.4; padding: 7px 10px; border-radius: 6px; max-width: 300px; opacity: 0; transition: opacity .08s; }
.tip.on { opacity: 1; }

@media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
@media (max-width: 1100px) {
  .find { min-width: 0; } .find span { display: none; }
}
@media (max-width: 720px) {
  .bar-in { padding: 0 16px; gap: 16px; } main { padding: 28px 16px 80px; }
  .tabs a { padding: 0 6px; font-size: 13.5px; }
  h1.finding { font-size: 32px; }
  .brand span { display: none; }
}
```

`ui/src/main.tsx`:

```tsx
import "./styles/tokens.css";
import "./styles/base.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

function App() {
  return <p>Hypothex</p>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```

- [ ] **Step 4: Run the tests and the build**

Run: `cd ui && bun test`
Expected: `4 pass`, `0 fail`.

Run: `cd ui && bun run build`
Expected: the Vite output lists four `.woff2` assets (`geist-latin-wght-normal-*.woff2`, `geist-mono-latin-wght-normal-*.woff2`, `newsreader-latin-standard-normal-*.woff2`, `newsreader-latin-standard-italic-*.woff2`) and one `index-*.css`.

- [ ] **Step 5: Commit**

```bash
git add ui/src/styles ui/src/main.tsx ui/test/styles
git commit -m "feat(ui): design tokens from the ui-v4 mockup and shared base styles"
```

### Task 3: Generated API types, contract models, and the typed client

**Files:**
- Create (generated): `ui/src/api/types.ts`
- Create: `ui/src/api/models.ts`, `ui/src/api/client.ts`
- Create: `ui/test/api/fetch-mock.ts`
- Test: `ui/test/api/client.test.ts`, `ui/test/api/types.test.ts`

**Interfaces:**
- Consumes: the backend plan's routes (contract section 2) on a running `hx serve`; phase 1a routes and pydantic models (`RunRecord`, `RunDetail`, `TaskSummary`, `PredictionPage`, `ExampleDiff`, `LogChunk`, `EvalReport`, `Stats`); contract 1.2-1.9 shapes.
- Produces:
  - `ui/src/api/types.ts`: `export interface paths` (openapi-typescript output; never edited by hand).
  - `ui/src/api/models.ts`: every response and body shape of contract sections 1–2 (records, leaderboard, overview, views and panels, panel row shapes `CurvesRow`, `ScatterRow`, `DistributionRow` (with `DeltaCI`), `GridRow`, `TraceRow`, `StatItem`, events `HxEvent`, `WsMessage`, enums `RunStatus`, `TaskKind`, `PanelType`, `Source`, `LogStream`).
  - `ui/src/api/client.ts`: `ROUTES` (as const, `satisfies Record<string, keyof paths>`); `class ApiError extends Error { status: number; type: string; issues: ValidationIssue[]; body: unknown; static from(status, body): ApiError }`; `buildUrl(route, params?, query?): string`; `request<T>(method, route, opts?): Promise<T>`; `wsUrl(): string`; `newCommandId(): string`; `api` with: `environment, overview(since?), projects, tasks(project?), task(p, t), leaderboard(p, t, metrics?), taskKind(p, t), views(p, t), view(p, t, name), saveView(p, t, name, text, opts?), deleteView(p, t, name), validateView(p, t, text), queryView(p, t, body), runs(query?), run(id), runMetrics(id), runLogs(id, stream?, offset?), runPredictions(id, query?), runTraces(id), runTrace(id, exampleId), compareExamples(a, b, metric, field?) (no field query parameter unless given; the server then uses `correct`, so callers that can meet other fields pass one, see Task 37), rerun(id, opts?), reinfer(id, checkpoint?, opts?), reevalRun(id, args?, opts?), reevalTask(p, t, args?, opts?), stop(id, opts?), tag(id, add, remove?, opts?), star(id, on, opts?), archive(id, on, opts?), note(id, text, opts?)`. Every read takes an optional trailing `signal?: AbortSignal`. Actions send `{command_id: <uuid>, created_by: "human"}` unless `opts` overrides.
  - `ui/test/api/fetch-mock.ts`: `mockFetch`, `mockRoutes` (longest prefix wins; a `null` body answers 404), `Call`.

- [ ] **Step 1: Write the failing tests**

`ui/test/api/fetch-mock.ts`:

```ts
import { mock } from "bun:test";

export interface Call {
  url: string;
  method: string;
  body: unknown;
}

/**
 * Replace `fetch` with a stub that answers every request with `status` and `body`
 * (objects are sent as JSON, strings as text) and records each call.
 */
export function mockFetch(body: unknown, status = 200): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({
      url: String(input),
      method: init?.method ?? "GET",
      body: typeof init?.body === "string" ? JSON.parse(init.body) : undefined,
    });
    const text = typeof body === "string" ? body : JSON.stringify(body);
    return new Response(text, { status, headers: { "Content-Type": "application/json" } });
  }) as unknown as typeof fetch;
  return calls;
}

/**
 * Route-aware variant: `routes` maps a URL path prefix to the JSON body to return; the
 * longest prefix wins. A `null` body, or no matching prefix, answers 404.
 */
export function mockRoutes(routes: Record<string, unknown>): Call[] {
  const calls: Call[] = [];
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, method: init?.method ?? "GET", body: undefined });
    const key = Object.keys(routes)
      .sort((a, b) => b.length - a.length)
      .find((prefix) => url.startsWith(prefix));
    if (key === undefined || routes[key] === null) {
      return new Response(JSON.stringify({ error: "no route", type: "StoreError" }), { status: 404 });
    }
    return new Response(JSON.stringify(routes[key]), { status: 200 });
  }) as unknown as typeof fetch;
  return calls;
}
```

`ui/test/api/client.test.ts`:

```ts
import { afterEach, describe, expect, test } from "bun:test";

import { ApiError, api, buildUrl, wsUrl } from "../../src/api/client";
import { mockFetch } from "./fetch-mock";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

describe("buildUrl", () => {
  test("encodes path parameters, repeats array query keys, drops undefined", () => {
    const url = buildUrl(
      "/api/v1/tasks/{project}/{task}/leaderboard",
      { project: "toy", task: "a b/c" },
      { metric: ["accuracy@v1", "f1@v2"], since: undefined, limit: 5, archived: false },
    );
    expect(url).toBe(
      "/api/v1/tasks/toy/a%20b%2Fc/leaderboard?metric=accuracy%40v1&metric=f1%40v2&limit=5&archived=false",
    );
  });

  test("returns the bare path when there is no query", () => {
    expect(buildUrl("/api/v1/projects")).toBe("/api/v1/projects");
  });

  test("throws on a missing path parameter", () => {
    expect(() => buildUrl("/api/v1/runs/{run_id}", {})).toThrow('missing path parameter "run_id"');
  });
});

describe("api", () => {
  test("leaderboard GETs the task route with repeated metric params", async () => {
    const calls = mockFetch({ project: "toy", task: "acc", rows: [] });
    const board = await api.leaderboard("toy", "acc", ["accuracy@v2"]);
    expect(board.task).toBe("acc");
    expect(calls).toEqual([
      { url: "/api/v1/tasks/toy/acc/leaderboard?metric=accuracy%40v2", method: "GET", body: undefined },
    ]);
  });

  test("overview passes since only when given", async () => {
    const calls = mockFetch({ headline: "Idle." });
    await api.overview();
    await api.overview("2026-09-27T00:00:00Z");
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/overview",
      "/api/v1/overview?since=2026-09-27T00%3A00%3A00Z",
    ]);
  });

  test("saveView PUTs the YAML text with a command id", async () => {
    const calls = mockFetch({ info: { name: "route" }, view: { title: "route quality" } });
    const saved = await api.saveView("toy", "acc", "route", "title: route quality\n", { command_id: "c-1" });
    expect(saved.view.title).toBe("route quality");
    expect(calls[0]).toEqual({
      url: "/api/v1/tasks/toy/acc/views/route",
      method: "PUT",
      body: { text: "title: route quality\n", command_id: "c-1" },
    });
  });

  test("queryView POSTs the body as JSON", async () => {
    const calls = mockFetch({ panels: [{ type: "markdown", title: "", rows: [], meta: { text: "hi" } }] });
    const out = await api.queryView("toy", "acc", { name: "overview" });
    expect(out.panels[0]?.meta.text).toBe("hi");
    expect(calls[0]).toEqual({ url: "/api/v1/tasks/toy/acc/views/query", method: "POST", body: { name: "overview" } });
  });

  test("runTrace encodes the example id", async () => {
    const calls = mockFetch({ type: "trace", title: "", rows: [], meta: {} });
    await api.runTrace("r1", "ex/1 a");
    expect(calls[0]?.url).toBe("/api/v1/runs/r1/traces/ex%2F1%20a");
  });

  test("compareExamples sends field only when given", async () => {
    const calls = mockFetch({ fixed: [], broken: [] });
    await api.compareExamples("r1", "r2", "solved@v2");
    await api.compareExamples("r1", "r2", "accuracy", "correct");
    expect(calls.map((c) => c.url)).toEqual([
      "/api/v1/compare/examples?a=r1&b=r2&metric=solved%40v2",
      "/api/v1/compare/examples?a=r1&b=r2&metric=accuracy&field=correct",
    ]);
  });

  test("actions send a fresh command id and created_by human", async () => {
    const calls = mockFetch({ run_id: "r2" });
    await api.rerun("r1");
    await api.rerun("r1");
    const [a, b] = calls.map((c) => c.body as { command_id: string; created_by: string });
    expect(a?.created_by).toBe("human");
    expect(a?.command_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(a?.command_id).not.toBe(b?.command_id);
  });

  test("star and note carry their own fields", async () => {
    const calls = mockFetch({ ok: true });
    await api.star("r1", false, { command_id: "s" });
    await api.note("r1", "looks good", { command_id: "n" });
    expect(calls[0]?.body).toEqual({ command_id: "s", created_by: "human", on: false });
    expect(calls[1]?.body).toEqual({ command_id: "n", created_by: "human", text: "looks good", author: "human" });
  });
});

describe("errors", () => {
  test("400 with issues keeps message, type and issues", async () => {
    const issue = { line: 3, path: "panels[0].data.metrics[0]", message: "unknown metric accuracyy", suggestion: "accuracy" };
    mockFetch({ error: "invalid view", issues: [issue] }, 400);
    const err = (await api.saveView("toy", "acc", "v", "x").catch((e: unknown) => e)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(400);
    expect(err.message).toBe("invalid view");
    expect(err.issues).toEqual([issue]);
  });

  test("404 keeps the server error type", async () => {
    mockFetch({ error: "run nope not found", type: "RunNotFoundError" }, 404);
    const err = (await api.run("nope").catch((e: unknown) => e)) as ApiError;
    expect([err.status, err.type, err.message]).toEqual([404, "RunNotFoundError", "run nope not found"]);
  });

  test("422 from FastAPI names the first bad field", async () => {
    mockFetch({ detail: [{ loc: ["body", "text"], msg: "Field required", type: "missing" }] }, 422);
    const err = (await api.validateView("toy", "acc", "").catch((e: unknown) => e)) as ApiError;
    expect(err.message).toBe("body.text: Field required");
    expect(err.type).toBe("RequestValidationError");
  });

  test("a non-JSON error body becomes HTTP <status>: <text>", async () => {
    mockFetch("Bad Gateway", 502);
    const err = (await api.projects().catch((e: unknown) => e)) as ApiError;
    expect(err.message).toBe("HTTP 502: Bad Gateway");
  });

  test("an unreachable server is status 0 NetworkError", async () => {
    globalThis.fetch = (async () => {
      throw new TypeError("fetch failed");
    }) as unknown as typeof fetch;
    const err = (await api.projects().catch((e: unknown) => e)) as ApiError;
    expect([err.status, err.type, err.message]).toEqual([0, "NetworkError", "Cannot reach hx serve"]);
  });
});

test("wsUrl points at the event stream on the page origin", () => {
  expect(wsUrl()).toBe("ws://127.0.0.1:7777/api/v1/ws");
});
```

`ui/test/api/types.test.ts`:

```ts
import { expect, test } from "bun:test";

import { ROUTES } from "../../src/api/client";

/** Routes added in phase 1b (contract section 2); types.ts must be regenerated after them. */
const PHASE_1B_ROUTES = [
  "/api/v1/overview",
  "/api/v1/tasks/{project}/{task}/views",
  "/api/v1/tasks/{project}/{task}/views/{name}",
  "/api/v1/tasks/{project}/{task}/views/validate",
  "/api/v1/tasks/{project}/{task}/views/query",
  "/api/v1/runs/{run_id}/traces",
  "/api/v1/runs/{run_id}/traces/{example_id}",
  "/api/v1/tasks/{project}/{task}/kind",
];

test("types.ts is generated by openapi-typescript and includes every client route", async () => {
  const text = await Bun.file(new URL("../../src/api/types.ts", import.meta.url)).text();
  expect(text).toContain("This file was auto-generated by openapi-typescript.");
  for (const route of [...PHASE_1B_ROUTES, ...Object.values(ROUTES)]) {
    expect(text).toContain(`"${route}": {`);
  }
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd ui && bun test test/api`
Expected: FAIL with `Cannot find module '../../src/api/client'`.

- [ ] **Step 3: Generate `types.ts` from a running `hx serve`**

The backend plan must be merged first; the generated file must contain the section 2 routes. From the repo root:

```bash
export HYPOTHEX_HOME="$(mktemp -d)"          # types do not depend on data
uv run hx serve --port 7777 > /tmp/hx-serve.log 2>&1 &
until curl -sf http://127.0.0.1:7777/api/openapi.json >/dev/null; do sleep 0.5; done
(cd ui && bun run gen:types)
pkill -f "hx serve --port 7777"
grep -c '"/api/v1/' ui/src/api/types.ts
head -4 ui/src/api/types.ts
```

Expected: openapi-typescript prints `http://127.0.0.1:7777/api/openapi.json → src/api/types.ts`; the `grep -c` count is at least 29 (21 phase 1a `/api/v1` paths + 8 phase 1b paths); the header reads `This file was auto-generated by openapi-typescript.` If a phase 1b path is missing, stop: the backend plan is not merged.

- [ ] **Step 4: Write the models and the client**

`ui/src/api/models.ts`:

```ts
/**
 * Response and body shapes of the Hypothex HTTP API.
 *
 * Hand-written from the phase 1b interface contract
 * (docs/superpowers/plans/2026-09-27-hypothex-phase1b-contract.md, sections 1-2) and the
 * phase 1a pydantic models. Most routes return `dict[str, Any]`, so the generated
 * `types.ts` knows their paths but not their bodies; these types fill that gap.
 */

export type RunStatus = "queued" | "running" | "finished" | "failed" | "killed" | "lost";
export type TaskKind = "generic" | "training" | "agent_eval" | "agent_iteration" | "system_bench";
export type PanelType =
  | "stat_strip"
  | "leaderboard"
  | "curves"
  | "scatter"
  | "distribution"
  | "grid"
  | "table"
  | "trace"
  | "markdown"
  | "vega_lite";
export type Source = "runs" | "scores" | "metrics" | "predictions" | "samples" | "usage" | "traces";
/** Log streams `GET /runs/{id}/logs` serves. */
export type LogStream = "stdout" | "stderr" | "supervisor";

// records ------------------------------------------------------------------------------
export interface GitInfo {
  repo: string | null;
  commit: string | null;
  branch: string | null;
  dirty: boolean;
  untracked_count: number;
  untracked: string[];
}

export interface DatasetRef {
  name: string;
  version: string;
  split: string | null;
  host: string;
  path: string;
  hash: string | null;
  hash_mode: string | null;
  size: number | null;
  checked_at: string | null;
}

export interface Artifact {
  kind: string;
  path: string;
  host: string;
  size: number | null;
  step: number | null;
  metrics: Record<string, number>;
}

export interface ExecutorInfo {
  type: string;
  pid: number | null;
  pid_create_time: number | null;
  child_pid: number | null;
}

export interface UsageTotals {
  tokens_in: number;
  tokens_out: number;
  usd: number;
  seconds: number;
  calls: number;
}

export interface RunRecord {
  run_id: string;
  project: string;
  task: string | null;
  hypothesis: string;
  kind: "full" | "infer";
  parent: string | null;
  stage: string | null;
  command: string[];
  command_template: string[];
  vars: Record<string, string>;
  params: Record<string, string>;
  cwd: string;
  environment_id: string;
  host: string;
  executor: ExecutorInfo;
  git: GitInfo;
  datasets: DatasetRef[];
  seed: number | null;
  config_hash: string;
  status: RunStatus;
  created_at: string;
  started_at: string | null;
  ended_at: string | null;
  exit_code: number | null;
  artifacts: Artifact[];
  tags: string[];
  starred: boolean;
  archived: boolean;
  created_by: string;
  usage: UsageTotals | null;
}

export interface ScoreRecord {
  metric: string;
  version: string;
  key: string;
  value: number | null;
  error: string | null;
  source_hash: string | null;
  created_at: string;
}

export interface MetricPoint {
  name: string;
  step: number;
  value: number;
  t: number | null;
}

export interface Stats {
  mean: number;
  std: number;
  n: number;
  ci_low: number | null;
  ci_high: number | null;
}

// projects, tasks, runs ------------------------------------------------------------------
export interface ProjectInfo {
  project: string;
  repo: string;
  description: string;
  tasks: string[];
}

export interface TaskSummary {
  project: string;
  name: string;
  description: string;
  dataset: string;
  dataset_version: string;
  split: string | null;
  metrics: Record<string, string>;
  primary: string;
  higher_is_better: boolean;
  n_runs: number;
  best: number | null;
}

export interface TaskDetail {
  summary: TaskSummary;
  repo: string;
  dataset: { name: string } & Record<string, unknown>;
  metrics: Record<string, Record<string, unknown>>;
  stages: Record<string, unknown>;
}

export interface RunDetail {
  record: RunRecord;
  scores: ScoreRecord[];
  paths: Record<string, string>;
  notes: string;
  has_diff: boolean;
  metric_names: string[];
  children: string[];
}

export interface PredictionRow {
  id: string;
  prediction: unknown;
  reference: unknown;
  scores: Record<string, Record<string, unknown>>;
}

export interface PredictionPage {
  run_id: string;
  total: number;
  offset: number;
  limit: number;
  rows: PredictionRow[];
}

export interface ExampleDiff {
  a: string;
  b: string;
  metric: string;
  field: string;
  fixed: string[];
  broken: string[];
  both_pass: number;
  both_fail: number;
}

export interface LogChunk {
  stream: string;
  text: string;
  offset: number;
  size: number;
}

export interface RunsQuery {
  project?: string;
  task?: string;
  status?: RunStatus;
  tag?: string;
  archived?: boolean;
  limit?: number;
}

export interface PredictionsQuery {
  offset?: number;
  limit?: number;
  metric?: string;
  failures_only?: boolean;
  field?: string;
}

// leaderboard (contract 1.7) -------------------------------------------------------------
export interface NoiseInterval {
  lo: number;
  hi: number;
  method: "wilson" | "bootstrap";
  n: number;
}

export interface VersusBest {
  delta: number;
  p: number | null;
  fixed: number | null;
  broken: number | null;
  test: "sign" | "paired_bootstrap" | "welch" | null;
  examples_needed: number | null;
}

/** One stat in a stat strip: a number with a short label; the explanation is the tooltip. */
export interface StatItem {
  label: string;
  value: number | string | null;
  unit?: string | null;
  tooltip?: string | null;
}

export interface LeaderboardRow {
  group_id: string;
  run_ids: string[];
  latest_run_id: string;
  hypothesis: string;
  commit: string | null;
  config_hash: string;
  n: number;
  scores: Record<string, Stats>;
  primary: Stats | null;
  single_seed: boolean;
  within_noise_of_best: boolean | null;
  label: string;
  seed_values: Record<string, number[]>;
  identical_seeds: boolean;
  test_interval: NoiseInterval | null;
  vs_best: VersusBest | null;
  created_by: string[];
  usage: UsageTotals | null;
}

export interface Leaderboard {
  project: string;
  task: string;
  primary: string;
  higher_is_better: boolean;
  metric_versions: Record<string, string>;
  rows: LeaderboardRow[];
  needs_reeval: string[];
  unscored: string[];
  headline: string;
  kind: TaskKind;
  stat_strip: StatItem[];
}

// overview (contract 1.9) ----------------------------------------------------------------
export interface TimelineItem {
  run_id: string;
  project: string;
  task: string | null;
  created_at: string;
  created_by: string;
  status: RunStatus;
  archived: boolean;
  group_id: string | null;
  is_best: boolean;
  label: string;
}

export interface IdeaRow {
  project: string;
  task: string | null;
  group_id: string;
  label: string;
  created_by: string;
  created_at: string;
  statuses: RunStatus[];
  primary: Stats | null;
  test_interval: NoiseInterval | null;
  identical_seeds: boolean;
  best_band: NoiseInterval | null;
}

export interface FailureRow {
  run_id: string;
  label: string;
  exit_code: number | null;
  created_at: string;
  stderr_path: string;
  retried_ok: boolean;
}

export interface ProjectRow {
  project: string;
  task: string;
  runs: number;
  best: number | null;
  kind: TaskKind;
}

export interface OverviewSummary {
  headline: string;
  counts: Record<string, number>;
  timeline: TimelineItem[];
  ideas: IdeaRow[];
  running: RunRecord[];
  failures: FailureRow[];
  projects: ProjectRow[];
}

// views and panels (contract 1.4, 1.6) --------------------------------------------------
export interface RunFilter {
  status?: string[] | null;
  tags?: string[] | null;
  created_by?: string | null;
  since?: string | null;
}

export interface PanelLayout {
  span?: number;
  row?: number | null;
}

export interface PanelData {
  metrics?: string[] | null;
  x?: string | null;
  y?: string | null;
  group_by?: "group" | "config" | "run" | "seed" | null;
  filter?: Record<string, unknown> | null;
  pick?: "best" | "latest" | "all" | null;
  source?: Source | null;
  fields?: string[] | null;
  run_id?: string | null;
  example_id?: string | null;
  step_metric?: string | null;
}

export interface PanelSpec {
  type: PanelType;
  title?: string;
  data?: PanelData;
  layout?: PanelLayout;
  noise?: ("seed" | "test_set")[];
  pareto?: Record<string, "min" | "max"> | null;
  spec?: Record<string, unknown> | null;
  text?: string | null;
  scale?: "linear" | "log";
  render?: "chart" | "table";
}

export interface ViewSpec {
  title: string;
  from?: TaskKind | null;
  runs?: RunFilter;
  panels?: PanelSpec[];
}

export interface ValidationIssue {
  line: number | null;
  path: string;
  message: string;
  suggestion: string | null;
}

export interface ViewInfo {
  name: string;
  title: string;
  origin: "preset" | "inline" | "file";
  path: string | null;
  kind: TaskKind | null;
}

/** `GET .../views/{name}`: the stored YAML text and the resolved view. */
export interface ViewDocument {
  info: ViewInfo;
  text: string;
  view: ViewSpec;
}

export interface SavedView {
  info: ViewInfo;
  view: ViewSpec;
}

export interface ViewValidation {
  ok: boolean;
  issues: ValidationIssue[];
  view?: ViewSpec | null;
}

export interface ViewQueryBody {
  view?: ViewSpec;
  name?: string;
  panel?: PanelSpec;
}

export interface PanelResult {
  type: PanelType;
  title: string;
  rows: Record<string, unknown>[];
  meta: Record<string, unknown>;
}

export interface ViewQueryResult {
  panels: PanelResult[];
}

// panel row shapes (contract 1.6; keys exact) --------------------------------------------
export interface CurvesRow {
  run_id: string;
  group_id: string;
  seed: number | null;
  name: string;
  step: number;
  value: number;
}

/** `x` is text on an ordinal axis (`meta.x_type = "ordinal"`, e.g. versions), else a number. */
export interface ScatterRow {
  group_id: string;
  label: string;
  x: number | string;
  x_lo: number | null;
  x_hi: number | null;
  y: number;
  y_lo: number | null;
  y_hi: number | null;
  seeds: { x: number | string; y: number }[];
  pareto: boolean;
  /** Ordinal x only: worse than the best earlier row by more than its 95% CI. */
  regression: boolean;
}

/** `[delta_rel, lo, hi]`: relative change vs the baseline and its 95% bootstrap CI. */
export type DeltaCI = [number, number | null, number | null];

export interface DistributionRow {
  group_id: string;
  label: string;
  n: number;
  p50: number;
  p95: number;
  p99: number;
  ecdf: [number, number][];
  seeds: { run_id: string; p50: number; p95: number; p99: number }[];
  /** Change vs the task's baseline group; null on the baseline row or with no baseline. */
  vs_baseline: { p50: DeltaCI; p95: DeltaCI; p99: DeltaCI } | null;
}

export interface GridRow {
  item_id: string;
  group_id: string;
  value: number;
}

export interface TraceRow {
  turn: number;
  tool: string | null;
  args: unknown;
  result: unknown;
  tokens_in: number | null;
  tokens_out: number | null;
  seconds: number | null;
  error: string | null;
}

// traces and kinds ------------------------------------------------------------------------
export interface TraceSummary {
  example_id: string;
  turns: number;
  failed: boolean;
}

export interface TaskKindInfo {
  kind: TaskKind;
  run_view: PanelSpec[];
}

// actions and events ----------------------------------------------------------------------
export interface ActionOptions {
  /** Idempotency key; a fresh UUID is used when omitted. */
  command_id?: string;
  created_by?: string;
}

export interface HxEvent {
  sequence: number;
  type: string;
  project: string | null;
  run_id: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

/** Messages the server sends on `/api/v1/ws`. */
export type WsMessage =
  | { type: "event"; event: HxEvent }
  | { type: "ready"; last_sequence: number }
  | { type: "error"; error: string };

export interface EvalReport {
  evaluated: string[];
  skipped: Record<string, string>;
  warnings: string[];
}
```

`ui/src/api/client.ts`:

```ts
/**
 * Typed client for the Hypothex HTTP API (`/api/v1`).
 *
 * Every route string is checked against the generated OpenAPI `paths` (types.ts), so a
 * renamed or removed backend route fails `bun run typecheck` after `bun run gen:types`.
 * Response bodies use the hand-written contract shapes in models.ts.
 */
import type * as M from "./models";
import type { paths } from "./types";

export type * from "./models";

/** Every HTTP route the UI calls. Keys are client names; values must exist in `paths`. */
export const ROUTES = {
  environment: "/.well-known/hypothex/environment",
  overview: "/api/v1/overview",
  projects: "/api/v1/projects",
  tasks: "/api/v1/tasks",
  task: "/api/v1/tasks/{project}/{task}",
  leaderboard: "/api/v1/tasks/{project}/{task}/leaderboard",
  taskReeval: "/api/v1/tasks/{project}/{task}/reeval",
  taskKind: "/api/v1/tasks/{project}/{task}/kind",
  views: "/api/v1/tasks/{project}/{task}/views",
  view: "/api/v1/tasks/{project}/{task}/views/{name}",
  viewValidate: "/api/v1/tasks/{project}/{task}/views/validate",
  viewQuery: "/api/v1/tasks/{project}/{task}/views/query",
  runs: "/api/v1/runs",
  run: "/api/v1/runs/{run_id}",
  runMetrics: "/api/v1/runs/{run_id}/metrics",
  runLogs: "/api/v1/runs/{run_id}/logs",
  runPredictions: "/api/v1/runs/{run_id}/predictions",
  runTraces: "/api/v1/runs/{run_id}/traces",
  runTrace: "/api/v1/runs/{run_id}/traces/{example_id}",
  runRerun: "/api/v1/runs/{run_id}/rerun",
  runReinfer: "/api/v1/runs/{run_id}/reinfer",
  runReeval: "/api/v1/runs/{run_id}/reeval",
  runStop: "/api/v1/runs/{run_id}/stop",
  runTags: "/api/v1/runs/{run_id}/tags",
  runStar: "/api/v1/runs/{run_id}/star",
  runArchive: "/api/v1/runs/{run_id}/archive",
  runNotes: "/api/v1/runs/{run_id}/notes",
  compareExamples: "/api/v1/compare/examples",
} as const satisfies Record<string, keyof paths>;

export type Route = (typeof ROUTES)[keyof typeof ROUTES];
export type QueryValue = string | number | boolean | readonly string[] | null | undefined;
export type Method = "GET" | "POST" | "PUT" | "DELETE";

export interface RequestOptions {
  params?: Record<string, string>;
  query?: Record<string, QueryValue>;
  body?: unknown;
  signal?: AbortSignal;
}

/** An API failure. `status` 0 means the server could not be reached. */
export class ApiError extends Error {
  readonly status: number;
  readonly type: string;
  readonly issues: M.ValidationIssue[];
  readonly body: unknown;

  constructor(status: number, message: string, type: string, issues: M.ValidationIssue[], body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.type = type;
    this.issues = issues;
    this.body = body;
  }

  /** Build from a response status and its parsed body (`{error, type}`, `{error, issues}`, or FastAPI `{detail}`). */
  static from(status: number, body: unknown): ApiError {
    if (body !== null && typeof body === "object") {
      const b = body as Record<string, unknown>;
      const issues = Array.isArray(b.issues) ? (b.issues as M.ValidationIssue[]) : [];
      if (typeof b.error === "string") {
        return new ApiError(status, b.error, typeof b.type === "string" ? b.type : "HTTPError", issues, body);
      }
      if (Array.isArray(b.detail) && b.detail.length > 0) {
        const first = b.detail[0] as { msg?: unknown; loc?: unknown };
        const loc = Array.isArray(first.loc) ? first.loc.join(".") : "";
        const msg = typeof first.msg === "string" ? first.msg : "invalid request";
        return new ApiError(status, loc ? `${loc}: ${msg}` : msg, "RequestValidationError", issues, body);
      }
      if (typeof b.detail === "string") return new ApiError(status, b.detail, "HTTPError", issues, body);
    }
    const text = typeof body === "string" && body ? `: ${body.slice(0, 200)}` : "";
    return new ApiError(status, `HTTP ${status}${text}`, "HTTPError", [], body);
  }
}

/**
 * Fill `{name}` placeholders (URL-encoded) and append query parameters.
 *
 * `undefined` and `null` query values are dropped; arrays repeat the key.
 */
export function buildUrl(route: string, params: Record<string, string> = {}, query: Record<string, QueryValue> = {}): string {
  const path = route.replace(/\{(\w+)\}/g, (_match, key: string) => {
    const value = params[key];
    if (value === undefined) throw new Error(`missing path parameter "${key}" for ${route}`);
    return encodeURIComponent(value);
  });
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) continue;
    if (Array.isArray(value)) for (const item of value) qs.append(key, item);
    else qs.append(key, String(value));
  }
  const s = qs.toString();
  return s ? `${path}?${s}` : path;
}

/** Send one request and return the parsed JSON body, or throw `ApiError`. */
export async function request<T>(method: Method, route: Route, opts: RequestOptions = {}): Promise<T> {
  const url = buildUrl(route, opts.params, opts.query);
  const headers: Record<string, string> = { Accept: "application/json" };
  const init: RequestInit = { method, headers, signal: opts.signal };
  if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "Cannot reach hx serve", "NetworkError", [], null);
  }
  const text = await res.text();
  let data: unknown = null;
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = text;
    }
  }
  if (!res.ok) throw ApiError.from(res.status, data);
  return data as T;
}

/** WebSocket URL of the live event stream, on the page's own origin. */
export function wsUrl(): string {
  const url = new URL("/api/v1/ws", window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.toString();
}

/** A fresh idempotency key for a POST/PUT action. */
export function newCommandId(): string {
  return crypto.randomUUID();
}

function action(opts: M.ActionOptions = {}): { command_id: string; created_by: string } {
  return { command_id: opts.command_id ?? newCommandId(), created_by: opts.created_by ?? "human" };
}

const get = <T>(route: Route, opts: RequestOptions = {}): Promise<T> => request<T>("GET", route, opts);
const post = <T>(route: Route, opts: RequestOptions = {}): Promise<T> => request<T>("POST", route, opts);

export const api = {
  environment: (signal?: AbortSignal) => get<Record<string, unknown>>(ROUTES.environment, { signal }),
  overview: (since?: string, signal?: AbortSignal) =>
    get<M.OverviewSummary>(ROUTES.overview, { query: { since }, signal }),
  projects: (signal?: AbortSignal) => get<M.ProjectInfo[]>(ROUTES.projects, { signal }),
  tasks: (project?: string, signal?: AbortSignal) =>
    get<M.TaskSummary[]>(ROUTES.tasks, { query: { project }, signal }),
  task: (project: string, task: string, signal?: AbortSignal) =>
    get<M.TaskDetail>(ROUTES.task, { params: { project, task }, signal }),
  leaderboard: (project: string, task: string, metrics?: readonly string[], signal?: AbortSignal) =>
    get<M.Leaderboard>(ROUTES.leaderboard, { params: { project, task }, query: { metric: metrics }, signal }),
  taskKind: (project: string, task: string, signal?: AbortSignal) =>
    get<M.TaskKindInfo>(ROUTES.taskKind, { params: { project, task }, signal }),
  views: (project: string, task: string, signal?: AbortSignal) =>
    get<M.ViewInfo[]>(ROUTES.views, { params: { project, task }, signal }),
  view: (project: string, task: string, name: string, signal?: AbortSignal) =>
    get<M.ViewDocument>(ROUTES.view, { params: { project, task, name }, signal }),
  saveView: (project: string, task: string, name: string, text: string, opts: M.ActionOptions = {}) =>
    request<M.SavedView>("PUT", ROUTES.view, {
      params: { project, task, name },
      body: { text, command_id: action(opts).command_id },
    }),
  deleteView: (project: string, task: string, name: string) =>
    request<{ ok: true }>("DELETE", ROUTES.view, { params: { project, task, name } }),
  validateView: (project: string, task: string, text: string, signal?: AbortSignal) =>
    post<M.ViewValidation>(ROUTES.viewValidate, { params: { project, task }, body: { text }, signal }),
  queryView: (project: string, task: string, body: M.ViewQueryBody, signal?: AbortSignal) =>
    post<M.ViewQueryResult>(ROUTES.viewQuery, { params: { project, task }, body, signal }),
  runs: (query: M.RunsQuery = {}, signal?: AbortSignal) =>
    get<M.RunRecord[]>(ROUTES.runs, { query: { ...query }, signal }),
  run: (runId: string, signal?: AbortSignal) =>
    get<M.RunDetail>(ROUTES.run, { params: { run_id: runId }, signal }),
  runMetrics: (runId: string, signal?: AbortSignal) =>
    get<M.MetricPoint[]>(ROUTES.runMetrics, { params: { run_id: runId }, signal }),
  runLogs: (runId: string, stream: M.LogStream = "stdout", offset?: number, signal?: AbortSignal) =>
    get<M.LogChunk>(ROUTES.runLogs, { params: { run_id: runId }, query: { stream, offset }, signal }),
  runPredictions: (runId: string, query: M.PredictionsQuery = {}, signal?: AbortSignal) =>
    get<M.PredictionPage>(ROUTES.runPredictions, { params: { run_id: runId }, query: { ...query }, signal }),
  runTraces: (runId: string, signal?: AbortSignal) =>
    get<M.TraceSummary[]>(ROUTES.runTraces, { params: { run_id: runId }, signal }),
  runTrace: (runId: string, exampleId: string, signal?: AbortSignal) =>
    get<M.PanelResult>(ROUTES.runTrace, { params: { run_id: runId, example_id: exampleId }, signal }),
  compareExamples: (a: string, b: string, metric: string, field?: string, signal?: AbortSignal) =>
    get<M.ExampleDiff>(ROUTES.compareExamples, { query: { a, b, metric, field }, signal }),
  rerun: (runId: string, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runRerun, { params: { run_id: runId }, body: action(opts) }),
  reinfer: (runId: string, checkpoint?: string, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runReinfer, { params: { run_id: runId }, body: { ...action(opts), checkpoint } }),
  reevalRun: (runId: string, args: { metric?: string; force?: boolean } = {}, opts?: M.ActionOptions) =>
    post<M.EvalReport>(ROUTES.runReeval, { params: { run_id: runId }, body: { ...action(opts), ...args } }),
  reevalTask: (project: string, task: string, args: { metric?: string; force?: boolean } = {}, opts?: M.ActionOptions) =>
    post<M.EvalReport>(ROUTES.taskReeval, { params: { project, task }, body: { ...action(opts), ...args } }),
  stop: (runId: string, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runStop, { params: { run_id: runId }, body: action(opts) }),
  tag: (runId: string, add: string[], remove: string[] = [], opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runTags, { params: { run_id: runId }, body: { ...action(opts), add, remove } }),
  star: (runId: string, on: boolean, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runStar, { params: { run_id: runId }, body: { ...action(opts), on } }),
  archive: (runId: string, on: boolean, opts?: M.ActionOptions) =>
    post<M.RunRecord>(ROUTES.runArchive, { params: { run_id: runId }, body: { ...action(opts), on } }),
  note: (runId: string, text: string, opts?: M.ActionOptions) =>
    post<{ ok: true }>(ROUTES.runNotes, {
      params: { run_id: runId },
      body: { ...action(opts), text, author: opts?.created_by ?? "human" },
    }),
};
```

- [ ] **Step 5: Run the tests and the typecheck**

Run: `cd ui && bun test`
Expected: `22 pass`, `0 fail`.

Run: `cd ui && bun run typecheck`
Expected: no output, exit 0. If `tsc` reports `Type '"/api/v1/..."' is not assignable to type 'keyof paths'`, the backend named that route differently from the contract (for example `{id}` instead of `{run_id}`); the contract's backend route string is binding, so fix the backend route, regenerate `types.ts`, and rerun. Do not edit `types.ts` by hand.

- [ ] **Step 6: Commit**

```bash
git add ui/src/api/types.ts ui/src/api/models.ts ui/src/api/client.ts ui/test/api/fetch-mock.ts ui/test/api/client.test.ts ui/test/api/types.test.ts
git commit -m "feat(ui): typed api client over generated openapi paths"
```

### Task 4: TanStack Query keys, hooks and mutations

**Files:**
- Create: `ui/src/api/queries.ts`
- Test: `ui/test/api/queries.test.tsx`

**Interfaces:**
- Consumes: Task 3 `api`, `ApiError`, models; `ui/test/api/fetch-mock.ts` `mockRoutes`.
- Produces: `createQueryClient(): QueryClient` (staleTime 5 s, no refetch on focus, `retry: shouldRetry`, mutations never retry); `shouldRetry(failureCount, error): boolean`; `queryKeys` (keys below); `RUN_EVENT_INVALIDATES: readonly QueryKey[]` (the families a `run.*` event or a run action can change: overview, tasks, task, runs, run, leaderboard, views/query, compareExamples); hooks `useOverview, useProjects, useTasks, useTask, useLeaderboard, useTaskKind, useRuns, useRun, useRunMetrics, useRunLogs(runId, stream: LogStream), useRunPredictions, useRunTraces, useRunTrace(runId, exampleId | null), useCompareExamples(a, b, metric, field?), useViews, useView(project, task, name | null), useViewQuery(project, task, body | null)`; mutations `useSaveView(project, task)` (`mutate({name, text})`), `useDeleteView(project, task)`. Screens use these keys and hooks only; no screen builds its own key or fetch.
  - Keys: `["overview", since|null]`, `["projects"]`, `["tasks", project|null]`, `["task", p, t]`, `["leaderboard", p, t, metrics[]]`, `["taskKind", p, t]`, `["runs", query]`, `["run", id]`, `["run", id, "metrics"]`, `["run", id, "logs", stream]`, `["run", id, "predictions", query]`, `["run", id, "traces"]`, `["run", id, "traces", exampleId]`, `["compareExamples", a, b, metric, field|null]`, `["views", "list", p, t]`, `["views", "doc", p, t, name]`, `["views", "query", p, t, body]`.

- [ ] **Step 1: Write the failing test**

`ui/test/api/queries.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";

import { ApiError } from "../../src/api/client";
import {
  RUN_EVENT_INVALIDATES,
  createQueryClient,
  queryKeys,
  shouldRetry,
  useLeaderboard,
  useSaveView,
  useView,
} from "../../src/api/queries";
import { mockRoutes } from "./fetch-mock";

const realFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = realFetch;
});

function setup(): { qc: QueryClient; wrapper: (p: { children: ReactNode }) => ReactNode } {
  const qc = createQueryClient();
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  return { qc, wrapper };
}

const invalidated = (qc: QueryClient, key: readonly unknown[]): boolean | undefined =>
  qc.getQueryState(key)?.isInvalidated;

describe("queryKeys", () => {
  test("families share a prefix", () => {
    expect(queryKeys.leaderboard("toy", "acc", ["accuracy@v2"])).toEqual(["leaderboard", "toy", "acc", ["accuracy@v2"]]);
    expect(queryKeys.runTrace("r1", "ex-3")).toEqual(["run", "r1", "traces", "ex-3"]);
    expect(queryKeys.viewQuery("toy", "acc", { name: "overview" }).slice(0, 2)).toEqual(["views", "query"]);
    expect(queryKeys.views("toy", "acc")).toEqual(["views", "list", "toy", "acc"]);
  });

  test("RUN_EVENT_INVALIDATES hits run data and panel queries but not view documents", async () => {
    const { qc } = setup();
    const hit = [
      queryKeys.runs({ project: "toy" }),
      queryKeys.run("r1"),
      queryKeys.runMetrics("r1"),
      queryKeys.tasks(),
      queryKeys.task("toy", "acc"),
      queryKeys.leaderboard("toy", "acc"),
      queryKeys.overview(),
      queryKeys.viewQuery("toy", "acc", { name: "overview" }),
      queryKeys.compareExamples("r1", "r2", "accuracy"),
    ];
    const miss = [queryKeys.views("toy", "acc"), queryKeys.view("toy", "acc", "route"), queryKeys.projects()];
    for (const key of [...hit, ...miss]) qc.setQueryData(key, { seeded: true });
    await Promise.all(RUN_EVENT_INVALIDATES.map((queryKey) => qc.invalidateQueries({ queryKey })));
    expect(hit.map((k) => invalidated(qc, k))).toEqual(hit.map(() => true));
    expect(miss.map((k) => invalidated(qc, k))).toEqual(miss.map(() => false));
  });
});

describe("shouldRetry", () => {
  test("never retries a 4xx, retries other failures twice", () => {
    const notFound = new ApiError(404, "run x not found", "RunNotFoundError", [], null);
    const offline = new ApiError(0, "Cannot reach hx serve", "NetworkError", [], null);
    expect(shouldRetry(0, notFound)).toBe(false);
    expect([shouldRetry(0, offline), shouldRetry(1, offline), shouldRetry(2, offline)]).toEqual([true, true, false]);
  });
});

describe("hooks", () => {
  test("useLeaderboard loads the board", async () => {
    mockRoutes({ "/api/v1/tasks/toy/acc/leaderboard": { task: "acc", headline: "SVM +0.037 over rf, p = 0.15" } });
    const { wrapper } = setup();
    const { result } = renderHook(() => useLeaderboard("toy", "acc"), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.headline).toBe("SVM +0.037 over rf, p = 0.15");
  });

  test("useView stays idle while name is null", async () => {
    const calls = mockRoutes({});
    const { wrapper } = setup();
    const { result } = renderHook(() => useView("toy", "acc", null), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(result.current.fetchStatus).toBe("idle");
    expect(calls).toEqual([]);
  });

  test("useSaveView invalidates the view list, the document and panel queries of that task", async () => {
    mockRoutes({ "/api/v1/tasks/toy/acc/views/route": { info: { name: "route" }, view: { title: "r" } } });
    const { qc, wrapper } = setup();
    const list = queryKeys.views("toy", "acc");
    const doc = queryKeys.view("toy", "acc", "route");
    const panels = queryKeys.viewQuery("toy", "acc", { name: "route" });
    const other = queryKeys.views("toy", "other");
    for (const key of [list, doc, panels, other]) qc.setQueryData(key, []);
    const { result } = renderHook(() => useSaveView("toy", "acc"), { wrapper });
    act(() => result.current.mutate({ name: "route", text: "title: r\n" }));
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect([list, doc, panels, other].map((k) => invalidated(qc, k))).toEqual([true, true, true, false]);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ui && bun test test/api/queries.test.tsx`
Expected: FAIL with `Cannot find module '../../src/api/queries'`.

- [ ] **Step 3: Write the queries module**

`ui/src/api/queries.ts`:

```ts
/**
 * TanStack Query keys, hooks and mutations over the API client.
 *
 * Keys are hierarchical so one prefix invalidates a family: `["run"]` covers every
 * per-run query, `["views", "query"]` every panel query. `RUN_EVENT_INVALIDATES` is the
 * list the live event stream invalidates on any `run.*` event.
 */
import {
  QueryClient,
  type QueryKey,
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import { ApiError, api } from "./client";
import type * as M from "./models";

export const queryKeys = {
  overview: (since?: string) => ["overview", since ?? null] as const,
  projects: () => ["projects"] as const,
  tasks: (project?: string) => ["tasks", project ?? null] as const,
  task: (project: string, task: string) => ["task", project, task] as const,
  leaderboard: (project: string, task: string, metrics: readonly string[] = []) =>
    ["leaderboard", project, task, [...metrics]] as const,
  taskKind: (project: string, task: string) => ["taskKind", project, task] as const,
  runs: (query: M.RunsQuery = {}) => ["runs", query] as const,
  run: (runId: string) => ["run", runId] as const,
  runMetrics: (runId: string) => ["run", runId, "metrics"] as const,
  runLogs: (runId: string, stream: M.LogStream) => ["run", runId, "logs", stream] as const,
  runPredictions: (runId: string, query: M.PredictionsQuery = {}) =>
    ["run", runId, "predictions", query] as const,
  runTraces: (runId: string) => ["run", runId, "traces"] as const,
  runTrace: (runId: string, exampleId: string) => ["run", runId, "traces", exampleId] as const,
  compareExamples: (a: string, b: string, metric: string, field?: string) =>
    ["compareExamples", a, b, metric, field ?? null] as const,
  views: (project: string, task: string) => ["views", "list", project, task] as const,
  view: (project: string, task: string, name: string) => ["views", "doc", project, task, name] as const,
  viewQuery: (project: string, task: string, body: M.ViewQueryBody) =>
    ["views", "query", project, task, body] as const,
};

/**
 * Key families a `run.*` event or a run action can change (contract section 4: runs,
 * leaderboard, overview, views/query; plus the task summary, run detail and example
 * comparisons that read the same runs). View lists, view documents and `/kind` are never
 * in this list, so an open editor is not reloaded under the user.
 */
export const RUN_EVENT_INVALIDATES: readonly QueryKey[] = [
  ["overview"],
  ["tasks"],
  ["task"],
  ["runs"],
  ["run"],
  ["leaderboard"],
  ["views", "query"],
  ["compareExamples"],
];

/** Retry transient failures twice; never retry a 4xx (the answer will not change). */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

/** The app's QueryClient: 5 s stale time, no refetch on focus (the event stream keeps data fresh). */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { staleTime: 5_000, refetchOnWindowFocus: false, retry: shouldRetry },
      mutations: { retry: false },
    },
  });
}

// reads ------------------------------------------------------------------------------------
export const useOverview = (since?: string) =>
  useQuery({ queryKey: queryKeys.overview(since), queryFn: ({ signal }) => api.overview(since, signal) });

export const useProjects = () =>
  useQuery({ queryKey: queryKeys.projects(), queryFn: ({ signal }) => api.projects(signal) });

export const useTasks = (project?: string) =>
  useQuery({ queryKey: queryKeys.tasks(project), queryFn: ({ signal }) => api.tasks(project, signal) });

export const useTask = (project: string, task: string) =>
  useQuery({ queryKey: queryKeys.task(project, task), queryFn: ({ signal }) => api.task(project, task, signal) });

export const useLeaderboard = (project: string, task: string, metrics: readonly string[] = []) =>
  useQuery({
    queryKey: queryKeys.leaderboard(project, task, metrics),
    queryFn: ({ signal }) => api.leaderboard(project, task, metrics, signal),
  });

export const useTaskKind = (project: string, task: string) =>
  useQuery({
    queryKey: queryKeys.taskKind(project, task),
    queryFn: ({ signal }) => api.taskKind(project, task, signal),
  });

export const useRuns = (query: M.RunsQuery = {}) =>
  useQuery({ queryKey: queryKeys.runs(query), queryFn: ({ signal }) => api.runs(query, signal) });

export const useRun = (runId: string) =>
  useQuery({ queryKey: queryKeys.run(runId), queryFn: ({ signal }) => api.run(runId, signal) });

export const useRunMetrics = (runId: string) =>
  useQuery({ queryKey: queryKeys.runMetrics(runId), queryFn: ({ signal }) => api.runMetrics(runId, signal) });

export const useRunLogs = (runId: string, stream: M.LogStream = "stdout") =>
  useQuery({
    queryKey: queryKeys.runLogs(runId, stream),
    queryFn: ({ signal }) => api.runLogs(runId, stream, undefined, signal),
  });

export const useRunPredictions = (runId: string, query: M.PredictionsQuery = {}) =>
  useQuery({
    queryKey: queryKeys.runPredictions(runId, query),
    queryFn: ({ signal }) => api.runPredictions(runId, query, signal),
    placeholderData: keepPreviousData,
  });

export const useRunTraces = (runId: string) =>
  useQuery({ queryKey: queryKeys.runTraces(runId), queryFn: ({ signal }) => api.runTraces(runId, signal) });

/** One trace; idle until `exampleId` is set. */
export const useRunTrace = (runId: string, exampleId: string | null) =>
  useQuery({
    queryKey: queryKeys.runTrace(runId, exampleId ?? ""),
    queryFn: ({ signal }) => api.runTrace(runId, exampleId ?? "", signal),
    enabled: exampleId !== null,
  });

export const useCompareExamples = (a: string, b: string, metric: string, field?: string) =>
  useQuery({
    queryKey: queryKeys.compareExamples(a, b, metric, field),
    queryFn: ({ signal }) => api.compareExamples(a, b, metric, field, signal),
  });

export const useViews = (project: string, task: string) =>
  useQuery({ queryKey: queryKeys.views(project, task), queryFn: ({ signal }) => api.views(project, task, signal) });

/** One view document; idle while `name` is null (the editor's "new" view). */
export const useView = (project: string, task: string, name: string | null) =>
  useQuery({
    queryKey: queryKeys.view(project, task, name ?? ""),
    queryFn: ({ signal }) => api.view(project, task, name ?? "", signal),
    enabled: name !== null,
  });

/** Panel data for a view, a named view, or one panel; keeps the last result while refetching. */
export const useViewQuery = (project: string, task: string, body: M.ViewQueryBody | null) =>
  useQuery({
    queryKey: queryKeys.viewQuery(project, task, body ?? {}),
    queryFn: ({ signal }) => api.queryView(project, task, body ?? {}, signal),
    enabled: body !== null,
    placeholderData: keepPreviousData,
  });

// writes -----------------------------------------------------------------------------------
export function useSaveView(project: string, task: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, text }: { name: string; text: string }) => api.saveView(project, task, name, text),
    onSuccess: async (_data, { name }) => {
      await Promise.all([
        qc.invalidateQueries({ queryKey: queryKeys.views(project, task) }),
        qc.invalidateQueries({ queryKey: queryKeys.view(project, task, name) }),
        qc.invalidateQueries({ queryKey: ["views", "query", project, task] }),
      ]);
    },
  });
}

export function useDeleteView(project: string, task: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.deleteView(project, task, name),
    onSuccess: async (_data, name) => {
      qc.removeQueries({ queryKey: queryKeys.view(project, task, name) });
      await qc.invalidateQueries({ queryKey: queryKeys.views(project, task) });
    },
  });
}
```

- [ ] **Step 4: Run the tests and the typecheck**

Run: `cd ui && bun test`
Expected: `28 pass`, `0 fail`, and no "not wrapped in act(...)" warnings.

Run: `cd ui && bun run typecheck`
Expected: no output, exit 0.

- [ ] **Step 5: Commit**

```bash
git add ui/src/api/queries.ts ui/test/api/queries.test.tsx
git commit -m "feat(ui): query keys, hooks and mutations with event invalidation prefixes"
```

### Task 5: Theme toggle

**Files:**
- Create: `ui/src/shell/ThemeToggle.tsx`
- Test: `ui/test/shell/ThemeToggle.test.tsx`

**Interfaces:**
- Consumes: Task 2 `.theme` class; `index.html` bootstrap script (Task 1) sets `data-theme` before paint.
- Produces: `type Theme = "light" | "dark"`, `THEME_KEY = "hx-theme"`, `currentTheme(): Theme`, `setTheme(theme): void`, `toggleTheme(): Theme`, `useTheme(): Theme`, `<ThemeToggle />` (button labelled "Switch colour mode"; visible text is the mode it switches to: "Dark" in light mode, "Light" in dark mode, as in the mockup).

- [ ] **Step 1: Write the failing test**

`ui/test/shell/ThemeToggle.test.tsx`:

```tsx
import { describe, expect, test } from "bun:test";
import { act, fireEvent, render, screen } from "@testing-library/react";

import { THEME_KEY, ThemeToggle, currentTheme, toggleTheme } from "../../src/shell/ThemeToggle";

describe("ThemeToggle", () => {
  test("starts light and offers Dark", () => {
    render(<ThemeToggle />);
    expect(currentTheme()).toBe("light");
    expect(screen.getByRole("button", { name: "Switch colour mode" }).textContent).toBe("Dark");
  });

  test("click switches to dark, stores it, and relabels", () => {
    render(<ThemeToggle />);
    fireEvent.click(screen.getByRole("button", { name: "Switch colour mode" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch colour mode" }).textContent).toBe("Light");
  });

  test("a toggle from elsewhere (the palette) updates the label", () => {
    document.documentElement.dataset.theme = "dark";
    render(<ThemeToggle />);
    expect(screen.getByRole("button").textContent).toBe("Light");
    act(() => {
      expect(toggleTheme()).toBe("light");
    });
    expect(screen.getByRole("button").textContent).toBe("Dark");
    expect(localStorage.getItem(THEME_KEY)).toBe("light");
  });

  test("still switches when storage is unavailable", () => {
    const real = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
    const attempts: string[] = [];
    const blocked = {
      getItem: () => null,
      setItem: (key: string) => {
        attempts.push(key);
        throw new Error("SecurityError");
      },
    };
    Object.defineProperty(globalThis, "localStorage", { value: blocked, configurable: true });
    try {
      render(<ThemeToggle />);
      fireEvent.click(screen.getByRole("button", { name: "Switch colour mode" }));
      expect(document.documentElement.dataset.theme).toBe("dark");
      expect(screen.getByRole("button").textContent).toBe("Light");
      expect(attempts).toEqual(["hx-theme"]);
    } finally {
      if (real) Object.defineProperty(globalThis, "localStorage", real);
    }
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ui && bun test test/shell/ThemeToggle.test.tsx`
Expected: FAIL with `Cannot find module '../../src/shell/ThemeToggle'`.

- [ ] **Step 3: Write the component**

`ui/src/shell/ThemeToggle.tsx`:

```tsx
/**
 * Light/dark switch. The theme lives on `<html data-theme>` (set before first paint by the
 * script in index.html) and in `localStorage["hx-theme"]`.
 */
import { useSyncExternalStore } from "react";

export type Theme = "light" | "dark";
export const THEME_KEY = "hx-theme";
const THEME_EVENT = "hx:theme";

/** The theme currently on `<html>`; anything but "dark" is light. */
export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

/** Apply a theme, remember it, and notify `useTheme` subscribers. */
export function setTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    // storage can be disabled; the theme still applies for this page
  }
  window.dispatchEvent(new Event(THEME_EVENT));
}

/** Switch to the other theme and return it. */
export function toggleTheme(): Theme {
  const next: Theme = currentTheme() === "dark" ? "light" : "dark";
  setTheme(next);
  return next;
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(THEME_EVENT, onChange);
  return () => window.removeEventListener(THEME_EVENT, onChange);
}

/** The current theme; re-renders when it changes (charts use this for canvas colours). */
export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, currentTheme, () => "light");
}

/** Header button; its label names the mode it switches to, as in the mockup. */
export function ThemeToggle() {
  const theme = useTheme();
  return (
    <button className="theme" type="button" aria-label="Switch colour mode" onClick={toggleTheme}>
      <svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true">
        <circle cx="7" cy="7" r="6" fill="none" stroke="currentColor" strokeWidth="1.3" />
        <path d="M7 1a6 6 0 0 1 0 12z" fill="currentColor" />
      </svg>
      <span>{theme === "dark" ? "Light" : "Dark"}</span>
    </button>
  );
}
```

- [ ] **Step 4: Run the tests**

Run: `cd ui && bun test`
Expected: `32 pass`, `0 fail`.

- [ ] **Step 5: Commit**

```bash
git add ui/src/shell/ThemeToggle.tsx ui/test/shell/ThemeToggle.test.tsx
git commit -m "feat(ui): light and dark theme toggle"
```

### Task 6: Router, app shell and header

**Files:**
- Create: `ui/src/router.tsx`, `ui/src/shell/Header.tsx`, `ui/test/render-app.tsx`
- Modify: `ui/src/main.tsx` (full replacement below)
- Test: `ui/test/router.test.tsx`, `ui/test/shell/Header.test.tsx`

**Interfaces:**
- Consumes: Task 4 `createQueryClient`; Task 5 `ThemeToggle`; Task 2 classes `.bar .bar-in .brand .tabs .bar-r .find h1.finding .metaline`.
- Produces:
  - `ui/src/router.tsx`: `rootRoute`, `overviewRoute`, `taskRoute`, `viewEditorRoute`, `runRoute`, `examplesRoute`, `routeTree`, `createAppRouter(history?: RouterHistory)`, `AppShell`, `ScreenPending({name})`, `NotFound`, `interface TaskSearch {view?: string}`, `interface ExamplesSearch {metric?: string}`; `parseSearch(searchStr: string): Record<string, string>` and `stringifySearch(search: Record<string, unknown>): string` (plain `URLSearchParams`; the router uses them instead of TanStack's JSON search parser, which turns `?example=42` or `?view=2024` into numbers that `str()` would drop, while `hrefs` build every link with `URLSearchParams`); the `Register` declaration that types `Link`/`useNavigate`/`getRouteApi` app-wide.
  - `ui/src/shell/Header.tsx`: `Header({onFind?})`, `type Screen`, `interface RecentTargets`, `RECENT_KEY = "hx-recent"`, `screenOf(pathname)`, `updateRecent(prev, pathname, search)`, `paletteShortcut(platform?)`. The find button has `id="findBtn"` (the palette returns focus to it).
  - `ui/test/render-app.tsx`: `renderApp(path)`.

- [ ] **Step 1: Write the failing tests**

`ui/test/render-app.tsx`:

```tsx
import { type QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider, createMemoryHistory } from "@tanstack/react-router";
import { render } from "@testing-library/react";

import { createQueryClient } from "../src/api/queries";
import { createAppRouter } from "../src/router";

/**
 * Render the whole app (shell + routes) at `path` with an in-memory history.
 * Mock `fetch` first (see test/api/fetch-mock.ts) if the page loads data.
 */
export function renderApp(path: string): {
  router: ReturnType<typeof createAppRouter>;
  queryClient: QueryClient;
} {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  const queryClient = createQueryClient();
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
  return { router, queryClient };
}
```

`ui/test/router.test.tsx` (tests wait on the matched route, not on screen text, so they keep passing after each screen replaces its placeholder):

```tsx
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { screen, waitFor } from "@testing-library/react";

import { parseSearch, stringifySearch } from "../src/router";
import { mockRoutes } from "./api/fetch-mock";
import { renderApp } from "./render-app";

const realFetch = globalThis.fetch;
beforeEach(() => {
  mockRoutes({});
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

type AppRouter = ReturnType<typeof renderApp>["router"];
const leaf = (router: AppRouter) => router.state.matches.at(-1);
const settled = (router: AppRouter, routeId: string) =>
  waitFor(() => expect(leaf(router)?.routeId).toBe(routeId));

describe("routes", () => {
  test("/ is the overview", async () => {
    const { router } = renderApp("/");
    await settled(router, "/");
  });

  test("/t/:project/:task reads ?view", async () => {
    const { router } = renderApp("/t/toy/acc?view=route");
    await settled(router, "/t/$project/$task");
    expect(leaf(router)?.params).toEqual({ project: "toy", task: "acc" });
    expect(leaf(router)?.search).toEqual({ view: "route" });
  });

  test("/t/:project/:task/edit/new is the view editor", async () => {
    const { router } = renderApp("/t/toy/acc/edit/new");
    await settled(router, "/t/$project/$task/edit/$view");
    expect(leaf(router)?.params).toMatchObject({ view: "new" });
  });

  test("/r/:runId decodes the id", async () => {
    const { router } = renderApp("/r/20260927-a%2Fb");
    await settled(router, "/r/$runId");
    expect(leaf(router)?.params).toEqual({ runId: "20260927-a/b" });
  });

  test("/x/:a/:b reads ?metric", async () => {
    const { router } = renderApp("/x/r1/r2?metric=accuracy%40v1");
    await settled(router, "/x/$a/$b");
    expect(leaf(router)?.params).toEqual({ a: "r1", b: "r2" });
    expect(leaf(router)?.search).toEqual({ metric: "accuracy@v1" });
  });

  test("a numeric-looking ?view stays a string (no JSON parsing)", async () => {
    const { router } = renderApp("/t/toy/acc?view=2024");
    await settled(router, "/t/$project/$task");
    expect(leaf(router)?.search).toEqual({ view: "2024" });
  });

  test("an unknown path shows Not found with a way home", async () => {
    renderApp("/nope/at/all");
    expect((await screen.findByRole("heading", { level: 1 })).textContent).toBe("Not found");
    expect(screen.getAllByRole("link", { name: "Overview" }).length).toBeGreaterThan(0);
  });
});

describe("search serialization", () => {
  test("parseSearch keeps every value a string; stringifySearch matches URLSearchParams", () => {
    expect(parseSearch("?example=42&view=2024&metric=accuracy%40v1&flag=true")).toEqual({
      example: "42",
      view: "2024",
      metric: "accuracy@v1",
      flag: "true",
    });
    expect(parseSearch("")).toEqual({});
    expect(stringifySearch({ example: "42", log: undefined, metric: "solved@v2" })).toBe(
      "?example=42&metric=solved%40v2",
    );
    expect(stringifySearch({ view: undefined })).toBe("");
    expect(stringifySearch({ n: 3 })).toBe("?n=3");
  });
});
```
`ui/test/shell/Header.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, test } from "bun:test";
import { act, screen, waitFor, within } from "@testing-library/react";

import { RECENT_KEY, paletteShortcut, screenOf, updateRecent } from "../../src/shell/Header";
import { mockRoutes } from "../api/fetch-mock";
import { renderApp } from "../render-app";

const realFetch = globalThis.fetch;
beforeEach(() => {
  mockRoutes({});
});
afterEach(() => {
  globalThis.fetch = realFetch;
});

const tabs = () => within(screen.getByRole("navigation", { name: "Screens" })).getAllByRole("link");

describe("screenOf", () => {
  test("maps paths to screens", () => {
    expect(["/", "/t/toy/acc", "/t/toy/acc/edit/new", "/r/r1", "/x/r1/r2", "/nope"].map(screenOf)).toEqual([
      "overview",
      "task",
      "task",
      "run",
      "examples",
      null,
    ]);
  });
});

describe("updateRecent", () => {
  test("records the task, run and example pair, decoding segments", () => {
    let r = updateRecent({}, "/t/my%20proj/acc", {});
    r = updateRecent(r, "/r/r-9", {});
    r = updateRecent(r, "/x/r1/r2", { metric: "accuracy" });
    r = updateRecent(r, "/", {});
    expect(r).toEqual({
      task: { project: "my proj", task: "acc" },
      run: { runId: "r-9" },
      examples: { a: "r1", b: "r2", metric: "accuracy" },
    });
  });
});

test("paletteShortcut shows the platform's modifier", () => {
  expect([paletteShortcut("MacIntel"), paletteShortcut("Win32")]).toEqual(["⌘K", "Ctrl K"]);
});

describe("Header", () => {
  test("on first visit only Overview is a tab, and it is current", async () => {
    renderApp("/");
    await screen.findByRole("navigation", { name: "Screens" });
    await waitFor(() => expect(tabs().map((a) => a.getAttribute("aria-current"))).toEqual(["page"]));
    expect(tabs().map((a) => a.textContent)).toEqual(["Overview"]);
    expect(screen.getByRole("link", { name: "Hypothex, overview" }).getAttribute("href")).toBe("/");
    expect(screen.getByRole("button", { name: /Find a run, task or path/ })).toBeTruthy();
  });

  test("a corrupt stored value is ignored", async () => {
    localStorage.setItem(RECENT_KEY, "{not json");
    renderApp("/r/r-1");
    await screen.findByRole("navigation", { name: "Screens" });
    await waitFor(() => expect(tabs().map((a) => a.textContent)).toEqual(["Overview", "Run"]));
  });

  test("remembers the last task and run as tabs", async () => {
    const { router } = renderApp("/t/toy/acc");
    await waitFor(() => expect(router.state.location.pathname).toBe("/t/toy/acc"));
    await act(() => router.navigate({ to: "/r/$runId", params: { runId: "r-7" } }));
    await waitFor(() =>
      expect(tabs().map((a) => [a.textContent, a.getAttribute("href"), a.getAttribute("aria-current")])).toEqual([
        ["Overview", "/", null],
        ["Task", "/t/toy/acc", null],
        ["Run", "/r/r-7", "page"],
      ]),
    );
    expect(JSON.parse(localStorage.getItem(RECENT_KEY) ?? "{}")).toEqual({
      task: { project: "toy", task: "acc" },
      run: { runId: "r-7" },
    });
  });
});
```

- [ ] **Step 2: Run them to verify they fail**

Run: `cd ui && bun test test/router.test.tsx test/shell/Header.test.tsx`
Expected: FAIL with `Cannot find module '../src/router'` and `Cannot find module '../../src/shell/Header'`.

- [ ] **Step 3: Write the header, router and entry point**

`ui/src/shell/Header.tsx`:

```tsx
/**
 * Sticky top bar from the ui-v4 mockup: brand, screen tabs, find button, theme toggle.
 *
 * Tabs: Overview always; Task, Run and Examples point at the last task, run and example
 * pair the user opened (kept in localStorage) and are hidden until there is one.
 */
import { Link, useRouterState } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { ThemeToggle } from "./ThemeToggle";

export type Screen = "overview" | "task" | "run" | "examples";

export interface RecentTargets {
  task?: { project: string; task: string };
  run?: { runId: string };
  examples?: { a: string; b: string; metric?: string };
}

export const RECENT_KEY = "hx-recent";

const seg = (s: string): string => {
  try {
    return decodeURIComponent(s);
  } catch {
    return s;
  }
};

/** Which screen a pathname belongs to (the view editor counts as the task screen). */
export function screenOf(pathname: string): Screen | null {
  if (pathname === "/" || pathname === "") return "overview";
  if (/^\/t\/[^/]+\/[^/]+(\/edit\/[^/]+)?\/?$/.test(pathname)) return "task";
  if (/^\/r\/[^/]+\/?$/.test(pathname)) return "run";
  if (/^\/x\/[^/]+\/[^/]+\/?$/.test(pathname)) return "examples";
  return null;
}

/** Remember the task, run or example pair in `pathname` (other screens leave `prev` as is). */
export function updateRecent(prev: RecentTargets, pathname: string, search: Record<string, unknown>): RecentTargets {
  const parts = pathname.split("/").filter(Boolean).map(seg);
  switch (screenOf(pathname)) {
    case "task":
      return { ...prev, task: { project: parts[1] ?? "", task: parts[2] ?? "" } };
    case "run":
      return { ...prev, run: { runId: parts[1] ?? "" } };
    case "examples": {
      const metric = typeof search.metric === "string" ? search.metric : undefined;
      return { ...prev, examples: { a: parts[1] ?? "", b: parts[2] ?? "", metric } };
    }
    default:
      return prev;
  }
}

function loadRecent(): RecentTargets {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? (JSON.parse(raw) as RecentTargets) : {};
  } catch {
    return {};
  }
}

function useRecentTargets(pathname: string, search: Record<string, unknown>): RecentTargets {
  const [recent, setRecent] = useState<RecentTargets>(() => updateRecent(loadRecent(), pathname, search));
  useEffect(() => {
    setRecent((prev) => {
      const next = updateRecent(prev, pathname, search);
      try {
        localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      } catch {
        // storage disabled: tabs still work for this page
      }
      return next;
    });
  }, [pathname, search]);
  return recent;
}

/** The brand mark: the best idea's band, a diamond on it, a dot for the baseline. */
function BrandMark() {
  return (
    <svg width="22" height="18" viewBox="0 0 22 18" aria-hidden="true">
      <rect x="9" y="1" width="8" height="16" style={{ fill: "var(--best-wash)" }} />
      <line x1="9" y1="1" x2="9" y2="17" style={{ stroke: "var(--best-edge)" }} />
      <line x1="17" y1="1" x2="17" y2="17" style={{ stroke: "var(--best-edge)" }} />
      <line x1="1" y1="9" x2="21" y2="9" style={{ stroke: "var(--ink)", strokeWidth: 1.4 }} />
      <rect x="10" y="5" width="5.6" height="5.6" transform="rotate(45 12.8 7.8)" style={{ fill: "var(--best)" }} />
      <circle cx="4" cy="9" r="2.6" style={{ fill: "var(--ink)" }} />
    </svg>
  );
}

/** "⌘K" on Apple platforms, "Ctrl K" elsewhere. */
export function paletteShortcut(platform: string = navigator.platform): string {
  return /Mac|iPhone|iPad/.test(platform) ? "⌘K" : "Ctrl K";
}

export interface HeaderProps {
  /** Opens the command palette. */
  onFind?: () => void;
}

export function Header({ onFind }: HeaderProps) {
  const location = useRouterState({ select: (s) => s.location });
  const search = location.search as Record<string, unknown>;
  const recent = useRecentTargets(location.pathname, search);
  const here = screenOf(location.pathname);
  const current = (s: Screen) => (here === s ? ("page" as const) : undefined);

  return (
    <header className="bar">
      <div className="bar-in">
        <Link className="brand" to="/" aria-label="Hypothex, overview">
          <BrandMark />
          <span>Hypothex</span>
        </Link>
        <nav className="tabs" aria-label="Screens">
          <Link to="/" aria-current={current("overview")}>
            Overview
          </Link>
          {recent.task && (
            <Link
              to="/t/$project/$task"
              params={recent.task}
              aria-current={current("task")}
              title={`${recent.task.project} / ${recent.task.task}`}
            >
              Task
            </Link>
          )}
          {recent.run && (
            <Link to="/r/$runId" params={recent.run} aria-current={current("run")} title={recent.run.runId}>
              Run
            </Link>
          )}
          {recent.examples && (
            <Link
              to="/x/$a/$b"
              params={{ a: recent.examples.a, b: recent.examples.b }}
              search={{ metric: recent.examples.metric }}
              aria-current={current("examples")}
              title={`${recent.examples.a} vs ${recent.examples.b}`}
            >
              Examples
            </Link>
          )}
        </nav>
        <div className="bar-r">
          <button className="find" id="findBtn" type="button" aria-haspopup="dialog" onClick={onFind}>
            <span>Find a run, task or path</span>
            <kbd>{paletteShortcut()}</kbd>
          </button>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
```

`ui/src/router.tsx` (Task 7 adds the palette to `AppShell`):

```tsx
/**
 * Code-defined routes (contract section 4):
 * `/` Overview, `/t/$project/$task?view=` Task, `/t/$project/$task/edit/$view` View editor
 * (`new` for a new view), `/r/$runId` Run, `/x/$a/$b?metric=` Examples.
 *
 * Each screen replaces its `ScreenPending` component below with the real screen. Screens
 * read params with `getRouteApi("<route id>")` to avoid importing this module.
 */
import {
  Link,
  Outlet,
  type RouterHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { Header } from "./shell/Header";

export interface TaskSearch {
  view?: string;
}

export interface ExamplesSearch {
  metric?: string;
}

const str = (v: unknown): string | undefined => (typeof v === "string" && v !== "" ? v : undefined);

/**
 * Search parser for the router: plain `URLSearchParams`, every value a string.
 * TanStack's default JSON-parses values (`?example=42` becomes the number 42), which
 * `str()` would then drop; `hrefs` build every in-app link with `URLSearchParams`, so the
 * router reads search strings the same way. A repeated key keeps its last value.
 */
export function parseSearch(searchStr: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of new URLSearchParams(searchStr)) out[key] = value;
  return out;
}

/** The inverse of `parseSearch`: drops `undefined`/`null`, `String()`s the rest, adds `?`. */
export function stringifySearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const out = params.toString();
  return out ? `?${out}` : "";
}

/** Stand-in until the screen's own component is wired in; shows the screen name. */
export function ScreenPending({ name }: { name: string }) {
  return (
    <h1 className="finding" data-testid="screen-pending">
      {name}
    </h1>
  );
}

export function NotFound() {
  return (
    <>
      <h1 className="finding">Not found</h1>
      <p className="metaline">
        <Link to="/">Overview</Link>
      </p>
    </>
  );
}

/** Page frame: header, the routed screen in `<main>`. */
export function AppShell() {
  return (
    <>
      <Header />
      <main>
        <Outlet />
      </main>
    </>
  );
}

export const rootRoute = createRootRoute({ component: AppShell, notFoundComponent: NotFound });

export const overviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: () => <ScreenPending name="Overview" />,
});

export const taskRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/t/$project/$task",
  validateSearch: (search: Record<string, unknown>): TaskSearch => ({ view: str(search.view) }),
  component: () => <ScreenPending name="Task" />,
});

export const viewEditorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/t/$project/$task/edit/$view",
  component: () => <ScreenPending name="View editor" />,
});

export const runRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/r/$runId",
  component: () => <ScreenPending name="Run" />,
});

export const examplesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/x/$a/$b",
  validateSearch: (search: Record<string, unknown>): ExamplesSearch => ({ metric: str(search.metric) }),
  component: () => <ScreenPending name="Examples" />,
});

export const routeTree = rootRoute.addChildren([
  overviewRoute,
  taskRoute,
  viewEditorRoute,
  runRoute,
  examplesRoute,
]);

/** Build the router; tests pass a memory history. */
export function createAppRouter(history?: RouterHistory) {
  return createRouter({
    routeTree,
    history,
    parseSearch,
    stringifySearch,
    defaultPreload: "intent",
    scrollRestoration: true,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
```

`ui/src/main.tsx`:

```tsx
import "./styles/tokens.css";
import "./styles/base.css";

import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { createQueryClient } from "./api/queries";
import { createAppRouter } from "./router";

const queryClient = createQueryClient();
const router = createAppRouter();

const root = document.getElementById("root");
if (!root) throw new Error("index.html has no #root element");

createRoot(root).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
);
```

- [ ] **Step 4: Run the tests, typecheck and build**

Run: `cd ui && bun test`
Expected: `46 pass`, `0 fail`.

Run: `cd ui && bun run build`
Expected: `tsc` silent, Vite `✓ built`.

- [ ] **Step 5: Commit**

```bash
git add ui/src/router.tsx ui/src/shell/Header.tsx ui/src/main.tsx ui/test/render-app.tsx ui/test/router.test.tsx ui/test/shell/Header.test.tsx
git commit -m "feat(ui): code routes, app shell and header with screen tabs"
```

### Task 7: Command palette (⌘K) and end-to-end shell check

**Files:**
- Create: `ui/src/shell/CommandPalette.tsx`
- Modify: `ui/src/router.tsx` (imports and `AppShell`; full file below)
- Test: `ui/test/shell/CommandPalette.test.tsx`

**Interfaces:**
- Consumes: Task 4 `useProjects`, `useTasks`, `useRuns`; Task 5 `toggleTheme`; Task 6 router (`useNavigate` typed by `Register`), `#findBtn`, `renderApp`; Task 3 `mockRoutes`.
- Produces: `CommandPalette({open, onOpenChange})` (global ⌘K / Ctrl+K toggle; `.toast` "Copied …" status); pure `buildCommands(data: CommandData, h: CommandHandlers): CommandItem[]`, `filterCommands(items, query): CommandItem[]`, `MAX_RUNS = 50`, types `NavTarget`, `CommandItem`, `CommandHandlers`, `CommandData`. Groups, in order: "Go to", "Tasks", "Runs", "Paths", "Commands". Runs are searchable by hypothesis, project, task, launcher, tags and working directory; paths are `host:path` unless the host is `local`.

- [ ] **Step 1: Write the failing test**

`ui/test/shell/CommandPalette.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";

import type { ProjectInfo, RunRecord, TaskSummary } from "../../src/api/models";
import { type CommandHandlers, MAX_RUNS, buildCommands, filterCommands } from "../../src/shell/CommandPalette";
import { mockRoutes } from "../api/fetch-mock";
import { renderApp } from "../render-app";

function makeRun(over: Partial<RunRecord> & { run_id: string }): RunRecord {
  return {
    project: "toy",
    task: "acc",
    hypothesis: "",
    kind: "full",
    parent: null,
    stage: null,
    command: ["python", "train.py"],
    command_template: ["python", "train.py"],
    vars: {},
    params: {},
    cwd: "/Users/me/toy",
    environment_id: "env1",
    host: "mac",
    executor: { type: "local", pid: null, pid_create_time: null, child_pid: null },
    git: { repo: null, commit: null, branch: null, dirty: false, untracked_count: 0, untracked: [] },
    datasets: [],
    seed: null,
    config_hash: "sha256:abc",
    status: "finished",
    created_at: "2026-09-27T10:00:00Z",
    started_at: null,
    ended_at: null,
    exit_code: null,
    artifacts: [],
    tags: [],
    starred: false,
    archived: false,
    created_by: "human",
    usage: null,
    ...over,
  };
}

const dataset = (name: string, path: string, host = "local") => ({
  name, version: "v1", split: "test", host, path, hash: null, hash_mode: null, size: null, checked_at: null,
});

const PROJECTS: ProjectInfo[] = [{ project: "toy", repo: "/Users/me/toy", description: "", tasks: ["acc", "f1"] }];
const TASKS: TaskSummary[] = [
  { project: "toy", name: "acc", description: "accuracy on the toy set", dataset: "toy", dataset_version: "v1",
    split: "test", metrics: { accuracy: "v1" }, primary: "accuracy", higher_is_better: true, n_runs: 6, best: 0.9 },
  { project: "toy", name: "f1", description: "", dataset: "toy", dataset_version: "v1",
    split: "test", metrics: { f1: "v1" }, primary: "f1", higher_is_better: true, n_runs: 1, best: null },
];
const RUNS: RunRecord[] = [
  makeRun({ run_id: "r-svm", hypothesis: "RBF-kernel SVM beats rf", seed: 1, tags: ["baseline"],
    datasets: [dataset("toy", "/data/test.jsonl")] }),
  makeRun({ run_id: "r-old", hypothesis: "debug test", archived: true }),
  makeRun({ run_id: "r-gpu", hypothesis: "", status: "running", cwd: "/scratch/wt",
    datasets: [dataset("big", "/scratch/train.jsonl", "gpu1"), dataset("toy", "/data/test.jsonl")] }),
];

function handlers(): CommandHandlers & { calls: unknown[] } {
  const calls: unknown[] = [];
  return {
    calls,
    go: (t) => calls.push(["go", t]),
    copy: (p) => calls.push(["copy", p]),
    toggleTheme: () => calls.push(["theme"]),
  };
}

describe("buildCommands", () => {
  test("lists go-to, tasks, unarchived runs, paths and commands in order", () => {
    const items = buildCommands({ projects: PROJECTS, tasks: TASKS, runs: RUNS }, handlers());
    expect(items.map((c) => [c.group, c.title, c.subtitle])).toEqual([
      ["Go to", "Overview", "all projects"],
      ["Tasks", "toy / acc", "6 runs"],
      ["Tasks", "toy / f1", "1 run"],
      ["Runs", "r-svm", "RBF-kernel SVM beats rf, seed 1, finished"],
      ["Runs", "r-gpu", "acc, running"],
      ["Paths", "Copy toy repo", "/Users/me/toy"],
      ["Paths", "Copy toy data", "/data/test.jsonl"],
      ["Paths", "Copy big data", "gpu1:/scratch/train.jsonl"],
      ["Commands", "Switch colour mode", "light or dark"],
    ]);
  });

  test("items call the matching handler", () => {
    const h = handlers();
    const items = buildCommands({ projects: PROJECTS, tasks: TASKS, runs: RUNS }, h);
    for (const title of ["toy / acc", "r-gpu", "Copy big data", "Switch colour mode"]) {
      items.find((c) => c.title === title)?.run();
    }
    expect(h.calls).toEqual([
      ["go", { to: "/t/$project/$task", params: { project: "toy", task: "acc" } }],
      ["go", { to: "/r/$runId", params: { runId: "r-gpu" } }],
      ["copy", "gpu1:/scratch/train.jsonl"],
      ["theme"],
    ]);
  });
});

describe("buildCommands edge cases", () => {
  test("an empty store still offers Overview and the colour switch", () => {
    const items = buildCommands({ projects: [], tasks: [], runs: [] }, handlers());
    expect(items.map((c) => c.title)).toEqual(["Overview", "Switch colour mode"]);
  });

  test(`lists at most ${MAX_RUNS} runs`, () => {
    const many = Array.from({ length: 60 }, (_, i) => makeRun({ run_id: `r-${i}` }));
    const items = buildCommands({ projects: [], tasks: [], runs: many }, handlers());
    expect(items.filter((c) => c.group === "Runs")).toHaveLength(MAX_RUNS);
  });
});

describe("filterCommands", () => {
  const items = buildCommands({ projects: PROJECTS, tasks: TASKS, runs: RUNS }, handlers());
  const titles = (q: string) => filterCommands(items, q).map((c) => c.title);

  test("an empty query keeps everything", () => {
    expect(titles("  ")).toHaveLength(items.length);
  });

  test("matches hypothesis and tags case-insensitively", () => {
    expect(titles("SVM")).toEqual(["r-svm"]);
    expect(titles("baseline")).toEqual(["r-svm"]);
  });

  test("every word must match; paths are searchable", () => {
    expect(titles("gpu1 train")).toEqual(["Copy big data"]);
    expect(titles("/users/me/toy")).toEqual(["r-svm", "Copy toy repo"]);
    expect(titles("svm running")).toEqual([]);
  });
});

describe("CommandPalette", () => {
  const realFetch = globalThis.fetch;
  let writeText: ReturnType<typeof mock>;

  beforeEach(() => {
    // "/api/v1/tasks/" answers 404 so the Task page opened by Enter shows its error box
    // instead of reading the task list as a leaderboard.
    mockRoutes({ "/api/v1/projects": PROJECTS, "/api/v1/tasks": TASKS, "/api/v1/tasks/": null, "/api/v1/runs": RUNS });
    writeText = mock(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  });
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  const openWithShortcut = async () => {
    fireEvent.keyDown(document, { key: "k", ctrlKey: true });
    return screen.findByRole("dialog", { name: "Find and run commands" });
  };

  test("Ctrl+K opens it with the input focused; Escape closes and refocuses Find", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    const dialog = await openWithShortcut();
    const input = screen.getByPlaceholderText("Find a run, task, path or command");
    expect(document.activeElement).toBe(input);
    fireEvent.keyDown(dialog, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement?.id).toBe("findBtn");
  });

  test("typing filters, Enter opens the selected task", async () => {
    const { router } = renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    fireEvent.click(screen.getByRole("button", { name: /Find a run, task or path/ }));
    await screen.findByRole("option", { name: /toy \/ acc/ });
    const input = screen.getByPlaceholderText("Find a run, task, path or command");
    fireEvent.change(input, { target: { value: "acc" } });
    const options = screen.getAllByRole("option");
    expect(options.map((o) => o.querySelector("span")?.textContent)).toEqual(["toy / acc", "r-svm", "r-gpu"]);
    expect(options[0]?.getAttribute("aria-selected")).toBe("true");
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(router.state.location.pathname).toBe("/t/toy/acc"));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  test("arrow keys move the selection and stop at the ends", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    const dialog = await openWithShortcut();
    await screen.findByRole("option", { name: /r-gpu/ });
    fireEvent.change(screen.getByPlaceholderText(/Find a run/), { target: { value: "copy" } });
    const selected = () => screen.getAllByRole("option").findIndex((o) => o.getAttribute("aria-selected") === "true");
    fireEvent.keyDown(dialog, { key: "ArrowUp" });
    expect(selected()).toBe(0);
    for (let i = 0; i < 5; i++) fireEvent.keyDown(dialog, { key: "ArrowDown" });
    expect(selected()).toBe(2);
  });

  test("a path item copies and shows a toast", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    await openWithShortcut();
    fireEvent.click(await screen.findByRole("option", { name: /Copy toy repo/ }));
    expect(writeText).toHaveBeenCalledWith("/Users/me/toy");
    expect(screen.getByRole("status").textContent).toBe("Copied /Users/me/toy");
  });

  test("the colour mode command toggles the theme", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    await openWithShortcut();
    await act(async () => {
      fireEvent.click(screen.getByRole("option", { name: /Switch colour mode/ }));
    });
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch colour mode" }).textContent).toBe("Light");
  });

  test("with the API failing it still offers Overview and the colour switch", async () => {
    mockRoutes({});
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    await openWithShortcut();
    await waitFor(() => expect(screen.queryByText("Loading…")).toBeNull());
    expect(screen.getAllByRole("option").map((o) => o.querySelector("span")?.textContent)).toEqual([
      "Overview",
      "Switch colour mode",
    ]);
  });

  test("shows Nothing matches for a query with no hits", async () => {
    renderApp("/");
    await screen.findByRole("button", { name: /Find a run, task or path/ });
    await openWithShortcut();
    await screen.findByRole("option", { name: /r-svm/ });
    fireEvent.change(screen.getByPlaceholderText(/Find a run/), { target: { value: "zzzz" } });
    expect(screen.queryAllByRole("option")).toHaveLength(0);
    expect(screen.getByText("Nothing matches")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ui && bun test test/shell/CommandPalette.test.tsx`
Expected: FAIL with `Cannot find module '../../src/shell/CommandPalette'`.

- [ ] **Step 3: Write the palette and mount it in the shell**

`ui/src/shell/CommandPalette.tsx`:

```tsx
/**
 * ⌘K / Ctrl+K palette (ui-v4 mockup): go to a task or run, copy a repo or dataset path,
 * switch colour mode. Items are filtered by every typed word (case-insensitive) over the
 * group, title, subtitle and hidden keywords (hypothesis, tags, paths).
 */
import { useNavigate } from "@tanstack/react-router";
import { type KeyboardEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";

import type { ProjectInfo, RunRecord, TaskSummary } from "../api/models";
import { useProjects, useRuns, useTasks } from "../api/queries";
import { toggleTheme } from "./ThemeToggle";

export type NavTarget =
  | { to: "/" }
  | { to: "/t/$project/$task"; params: { project: string; task: string } }
  | { to: "/r/$runId"; params: { runId: string } };

export interface CommandItem {
  group: "Go to" | "Tasks" | "Runs" | "Paths" | "Commands";
  title: string;
  subtitle: string;
  keywords?: string;
  run: () => void;
}

export interface CommandHandlers {
  go: (target: NavTarget) => void;
  copy: (text: string) => void;
  toggleTheme: () => void;
}

export interface CommandData {
  projects: ProjectInfo[];
  tasks: TaskSummary[];
  runs: RunRecord[];
}

/** Most runs listed in the palette (newest first, archived runs left out). */
export const MAX_RUNS = 50;

const clip = (s: string, n = 60): string => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
const plural = (n: number, word: string): string => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Build the palette items, grouped in display order. */
export function buildCommands(data: CommandData, h: CommandHandlers): CommandItem[] {
  const items: CommandItem[] = [{ group: "Go to", title: "Overview", subtitle: "all projects", run: () => h.go({ to: "/" }) }];
  for (const t of data.tasks) {
    items.push({
      group: "Tasks",
      title: `${t.project} / ${t.name}`,
      subtitle: plural(t.n_runs, "run"),
      keywords: t.description,
      run: () => h.go({ to: "/t/$project/$task", params: { project: t.project, task: t.name } }),
    });
  }
  const runs = data.runs.filter((r) => !r.archived).slice(0, MAX_RUNS);
  for (const r of runs) {
    const who = r.seed === null ? r.status : `seed ${r.seed}, ${r.status}`;
    items.push({
      group: "Runs",
      title: r.run_id,
      subtitle: `${clip(r.hypothesis || r.task || r.project)}, ${who}`,
      keywords: [r.hypothesis, r.project, r.task ?? "", r.created_by, ...r.tags, r.cwd].join(" "),
      run: () => h.go({ to: "/r/$runId", params: { runId: r.run_id } }),
    });
  }
  for (const p of data.projects) {
    items.push({ group: "Paths", title: `Copy ${p.project} repo`, subtitle: p.repo, run: () => h.copy(p.repo) });
  }
  const seen = new Set<string>();
  for (const r of runs) {
    for (const d of r.datasets) {
      const where = d.host === "local" ? d.path : `${d.host}:${d.path}`;
      if (seen.has(where)) continue;
      seen.add(where);
      items.push({ group: "Paths", title: `Copy ${d.name} data`, subtitle: where, run: () => h.copy(where) });
    }
  }
  items.push({ group: "Commands", title: "Switch colour mode", subtitle: "light or dark", run: h.toggleTheme });
  return items;
}

/** Keep items whose text contains every whitespace-separated word of `query`. */
export function filterCommands(items: CommandItem[], query: string): CommandItem[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return items;
  return items.filter((c) => {
    const hay = `${c.group} ${c.title} ${c.subtitle} ${c.keywords ?? ""}`.toLowerCase();
    return words.every((w) => hay.includes(w));
  });
}

function PaletteDialog({ onClose, onToast }: { onClose: () => void; onToast: (msg: string) => void }) {
  const navigate = useNavigate();
  const projects = useProjects();
  const tasks = useTasks();
  const runs = useRuns({ limit: 200 });
  const [query, setQuery] = useState("");
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => input.current?.focus(), []);

  const all = useMemo(
    () =>
      buildCommands(
        { projects: projects.data ?? [], tasks: tasks.data ?? [], runs: runs.data ?? [] },
        {
          go: (target) => void navigate(target),
          copy: (text) => {
            void navigator.clipboard?.writeText(text).catch(() => undefined);
            onToast(`Copied ${text}`);
          },
          toggleTheme: () => void toggleTheme(),
        },
      ),
    [projects.data, tasks.data, runs.data, navigate, onToast],
  );
  const items = useMemo(() => filterCommands(all, query), [all, query]);
  const loading = projects.isPending || tasks.isPending || runs.isPending;

  useEffect(() => {
    document.getElementById(`po${sel}`)?.scrollIntoView?.({ block: "nearest" });
  }, [sel]);

  const runItem = (i: number) => {
    const item = items[i];
    if (!item) return;
    onClose();
    item.run();
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setSel((s) => Math.min(items.length - 1, s + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSel((s) => Math.max(0, s - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      runItem(sel);
    }
  };

  const rows: ReactNode[] = [];
  let lastGroup = "";
  items.forEach((c, i) => {
    if (c.group !== lastGroup) {
      rows.push(
        <li className="grp" role="presentation" key={`g-${c.group}`}>
          {c.group}
        </li>,
      );
      lastGroup = c.group;
    }
    rows.push(
      <li
        className="it"
        role="option"
        id={`po${i}`}
        key={`${c.group}-${c.title}-${c.subtitle}`}
        aria-selected={i === sel}
        onMouseMove={() => setSel(i)}
        onClick={() => runItem(i)}
      >
        <span>{c.title}</span>
        <small>{c.subtitle}</small>
      </li>,
    );
  });

  return (
    <div
      className="pal on"
      role="dialog"
      aria-modal="true"
      aria-label="Find and run commands"
      onKeyDown={onKeyDown}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="pal-box">
        <input
          ref={input}
          className="pal-in"
          placeholder="Find a run, task, path or command"
          autoComplete="off"
          aria-controls="palList"
          aria-activedescendant={items.length ? `po${sel}` : undefined}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSel(0);
          }}
        />
        <ul className="pal-list" id="palList" role="listbox">
          {rows.length ? rows : <li className="grp">{loading ? "Loading…" : "Nothing matches"}</li>}
          {rows.length > 0 && loading && <li className="grp">Loading…</li>}
        </ul>
        <div className="pal-foot">
          <span>
            <kbd>↑</kbd> <kbd>↓</kbd> move
          </span>
          <span>
            <kbd>Enter</kbd> open
          </span>
          <span>
            <kbd>Esc</kbd> close
          </span>
        </div>
      </div>
    </div>
  );
}

export interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/** Palette plus its ⌘K / Ctrl+K shortcut and the "Copied …" toast. Mounted once, in the shell. */
export function CommandPalette({ open, onOpenChange }: CommandPaletteProps) {
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        onOpenChange(!open);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onOpenChange]);

  useEffect(() => {
    if (toast === null) return;
    const t = setTimeout(() => setToast(null), 2200);
    return () => clearTimeout(t);
  }, [toast]);

  const close = () => {
    onOpenChange(false);
    document.getElementById("findBtn")?.focus();
  };

  return (
    <>
      {open && <PaletteDialog onClose={close} onToast={setToast} />}
      <div className={toast ? "toast on" : "toast"} role="status" aria-live="polite">
        {toast}
      </div>
    </>
  );
}
```

`ui/src/router.tsx` (full file; only the imports and `AppShell` change):

```tsx
/**
 * Code-defined routes (contract section 4):
 * `/` Overview, `/t/$project/$task?view=` Task, `/t/$project/$task/edit/$view` View editor
 * (`new` for a new view), `/r/$runId` Run, `/x/$a/$b?metric=` Examples.
 *
 * Each screen replaces its `ScreenPending` component below with the real screen. Screens
 * read params with `getRouteApi("<route id>")` to avoid importing this module.
 */
import {
  Link,
  Outlet,
  type RouterHistory,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";
import { useState } from "react";

import { CommandPalette } from "./shell/CommandPalette";
import { Header } from "./shell/Header";

export interface TaskSearch {
  view?: string;
}

export interface ExamplesSearch {
  metric?: string;
}

const str = (v: unknown): string | undefined => (typeof v === "string" && v !== "" ? v : undefined);

/**
 * Search parser for the router: plain `URLSearchParams`, every value a string.
 * TanStack's default JSON-parses values (`?example=42` becomes the number 42), which
 * `str()` would then drop; `hrefs` build every in-app link with `URLSearchParams`, so the
 * router reads search strings the same way. A repeated key keeps its last value.
 */
export function parseSearch(searchStr: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of new URLSearchParams(searchStr)) out[key] = value;
  return out;
}

/** The inverse of `parseSearch`: drops `undefined`/`null`, `String()`s the rest, adds `?`. */
export function stringifySearch(search: Record<string, unknown>): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (value !== undefined && value !== null) params.set(key, String(value));
  }
  const out = params.toString();
  return out ? `?${out}` : "";
}

/** Stand-in until the screen's own component is wired in; shows the screen name. */
export function ScreenPending({ name }: { name: string }) {
  return (
    <h1 className="finding" data-testid="screen-pending">
      {name}
    </h1>
  );
}

export function NotFound() {
  return (
    <>
      <h1 className="finding">Not found</h1>
      <p className="metaline">
        <Link to="/">Overview</Link>
      </p>
    </>
  );
}

/** Page frame: header, the routed screen in `<main>`, the command palette. */
export function AppShell() {
  const [paletteOpen, setPaletteOpen] = useState(false);
  return (
    <>
      <Header onFind={() => setPaletteOpen(true)} />
      <main>
        <Outlet />
      </main>
      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </>
  );
}

export const rootRoute = createRootRoute({ component: AppShell, notFoundComponent: NotFound });

export const overviewRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: () => <ScreenPending name="Overview" />,
});

export const taskRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/t/$project/$task",
  validateSearch: (search: Record<string, unknown>): TaskSearch => ({ view: str(search.view) }),
  component: () => <ScreenPending name="Task" />,
});

export const viewEditorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/t/$project/$task/edit/$view",
  component: () => <ScreenPending name="View editor" />,
});

export const runRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/r/$runId",
  component: () => <ScreenPending name="Run" />,
});

export const examplesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/x/$a/$b",
  validateSearch: (search: Record<string, unknown>): ExamplesSearch => ({ metric: str(search.metric) }),
  component: () => <ScreenPending name="Examples" />,
});

export const routeTree = rootRoute.addChildren([
  overviewRoute,
  taskRoute,
  viewEditorRoute,
  runRoute,
  examplesRoute,
]);

/** Build the router; tests pass a memory history. */
export function createAppRouter(history?: RouterHistory) {
  return createRouter({
    routeTree,
    history,
    parseSearch,
    stringifySearch,
    defaultPreload: "intent",
    scrollRestoration: true,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
```

- [ ] **Step 4: Run the whole suite, typecheck and build**

Run: `cd ui && bun test`
Expected: `60 pass`, `0 fail`, `Ran 60 tests across 9 files`.

Run: `cd ui && bun run build`
Expected: `tsc` silent, Vite `✓ built`, `src/hypothex/ui_dist/index.html` present.

- [ ] **Step 5: Check the built shell under `hx serve`**

Run (from the repo root):

```bash
export HYPOTHEX_HOME="$(mktemp -d)"
uv run hx serve --port 7777 > /tmp/hx-serve.log 2>&1 &
until curl -sf http://127.0.0.1:7777/api/v1/projects >/dev/null; do sleep 0.5; done
curl -s http://127.0.0.1:7777/ | grep -o '<div id="root"></div>'
curl -s http://127.0.0.1:7777/ | grep -o '/assets/index-[A-Za-z0-9_-]*\.js' | head -1
pkill -f "hx serve --port 7777"
```

Expected: `<div id="root"></div>` and one `/assets/index-….js` path. Then open `http://127.0.0.1:7777/` in a browser once: the header matches `docs/mockups/ui-v4/shot-overview-light.png` (brand, Overview tab, find button with `⌘K`, "Dark" toggle); ⌘K opens the palette as in `shot-palette-light.png`; the toggle switches to the dark tokens and survives a reload.

- [ ] **Step 6: Commit**

```bash
git add ui/src/shell/CommandPalette.tsx ui/src/router.tsx ui/test/shell/CommandPalette.test.tsx
git commit -m "feat(ui): command palette for tasks, runs, paths and theme"
```

## Part 2: Chart primitives, panel registry, StatStrip, Leaderboard, Curves (Tasks 8–13)

Builds the shared SVG chart layer (`ui/src/charts/`), the panel registry (`ui/src/panels/index.ts`), and the first three panels. Visual reference: `docs/mockups/ui-v4/index.html` (leaderboard forest plot, glyph key) and `docs/mockups/kinds/training/index.html` (curves small multiples). Panel components render only their body; the lettered title (`a  Configs`) is drawn by whoever lays out the panels (Task 25 and the editor preview). Row types come from `ui/src/api/models.ts` (Task 3); this part adds no second copy of them.

### Task 8: Chart scales, number formats, width hook

**Files:**
- Create: `ui/src/charts/Scale.tsx`
- Test: `ui/test/charts/Scale.test.tsx`
- Modify: `ui/package.json`, `ui/bun.lock` (add the chart math dependencies)

**Interfaces:**
- Consumes: Task 1 scaffold.
- Produces (`ui/src/charts/Scale.tsx`):
  - `type Pos = (v: number) => number`; `const MINUS = "\u2212"`.
  - `f2(v)`, `f3(v)`, `f4(v): string` fixed decimals with U+2212, never `-0`.
  - `signed(v: number, digits = 3): string` (`+0.037`, `−0.037`, `0.000`).
  - `fmtP(p: number): string` (`0.15`, `0.004`, `< 0.001`; the same rule as the server's `fmt_p`, so a p-value never shows as `0.00`).
  - `fmtValue(v: number): string` (integers `40,000`; |v| ≥ 100 rounded `1,235`; else 3
    significant digits `0.0064`).
  - `kStep(s: number): string` (`0`, `999`, `1.5k`, `20k`, `1.2M`).
  - `tickDecimals(ticks: number[]): number`; `tickFormat(ticks: number[]): (v: number) => string`.
  - `niceDomain(values: number[]): [number, number]`.
  - `interface LinearScale { at: Pos; ticks: number[]; domain: [number, number]; invert: Pos }`.
  - `linear(domain, r0, r1, count = 8): LinearScale`; `logScale(domain, r0, r1): LinearScale`
    (ticks at 1-2-4 per decade).
  - `useElementWidth<T extends HTMLElement>(fallback: number): [RefObject<T | null>, number]`.

- [ ] **Step 1: Make sure the chart math packages are installed**

Run: `(cd ui && bun add d3-scale d3-shape d3-array d3-format && bun add -d @types/d3-scale @types/d3-shape @types/d3-array @types/d3-format)`
Expected: `installed` lines for `d3-scale`, `d3-shape`, `d3-array`, `d3-format` and their `@types/*` packages.

- [ ] **Step 2: Write the failing test**

`ui/test/charts/Scale.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import {
  MINUS,
  f2,
  f3,
  f4,
  fmtP,
  fmtValue,
  kStep,
  linear,
  logScale,
  niceDomain,
  signed,
  tickDecimals,
  tickFormat,
  useElementWidth,
} from "../../src/charts/Scale";

afterEach(cleanup);

describe("number formats", () => {
  test("fixed decimals use a real minus and never print -0", () => {
    expect(f2(0.1534)).toBe("0.15");
    expect(f3(0.87412)).toBe("0.874");
    expect(f4(0.92216)).toBe("0.9222");
    expect(f3(-0.0374)).toBe(`${MINUS}0.037`);
    expect(f3(-0.0001)).toBe("0.000");
  });
  test("signed adds a plus for gains", () => {
    expect(signed(0.0371)).toBe("+0.037");
    expect(signed(-0.0561)).toBe(`${MINUS}0.056`);
    expect(signed(0)).toBe("0.000");
    expect(signed(0.26312, 3)).toBe("+0.263");
  });
  test("p-values: two decimals, three below 0.01, or < 0.001", () => {
    expect(fmtP(0.1459)).toBe("0.15");
    expect(fmtP(0.0289)).toBe("0.03");
    expect(fmtP(0.0042)).toBe("0.004");
    expect(fmtP(0.0004)).toBe("< 0.001");
  });
  test("free numbers: separators for integers, 3 significant digits for small", () => {
    expect(fmtValue(40000)).toBe("40,000");
    expect(fmtValue(250)).toBe("250");
    expect(fmtValue(1234.56)).toBe("1,235");
    expect(fmtValue(0.037)).toBe("0.037");
    expect(fmtValue(0.0064)).toBe("0.0064");
    expect(fmtValue(0.92216)).toBe("0.922");
    expect(fmtValue(-0.0561)).toBe(`${MINUS}0.0561`);
    expect(fmtValue(Number.NaN)).toBe("NaN");
  });
  test("steps compact to k and M", () => {
    expect(kStep(0)).toBe("0");
    expect(kStep(999)).toBe("999");
    expect(kStep(1500)).toBe("1.5k");
    expect(kStep(20000)).toBe("20k");
    expect(kStep(1_200_000)).toBe("1.2M");
  });
});

describe("scales", () => {
  test("tickDecimals follows the tick step", () => {
    expect(tickDecimals([0.78, 0.8, 0.82])).toBe(2);
    expect(tickDecimals([0.875, 0.88, 0.885])).toBe(3);
    expect(tickDecimals([0, 5000, 10000])).toBe(0);
    expect(tickDecimals([1])).toBe(2);
  });
  test("tickFormat labels ticks with the tick step's decimals", () => {
    const fmt = tickFormat([0.875, 0.88, 0.885]);
    expect(fmt(0.88)).toBe("0.880");
    expect(tickFormat([0, 5000])(5000)).toBe("5000");
    expect(tickFormat([-0.02, 0])(-0.02)).toBe(`${MINUS}0.02`);
  });
  test("niceDomain covers the data and survives degenerate input", () => {
    expect(niceDomain([0.8278, 0.953])).toEqual([0.82, 0.96]);
    expect(niceDomain([])).toEqual([0, 1]);
    const [lo, hi] = niceDomain([0.5, 0.5]);
    expect(lo).toBeLessThan(0.5);
    expect(hi).toBeGreaterThan(0.5);
    expect(niceDomain([Number.NaN, 2, 4])).toEqual([2, 4]);
  });
  test("linear maps the domain onto the range and inverts", () => {
    const s = linear([0, 10], 100, 200);
    expect(s.at(0)).toBe(100);
    expect(s.at(5)).toBe(150);
    expect(s.invert(175)).toBe(7.5);
    expect(s.ticks[0]).toBe(0);
    expect(s.ticks.at(-1)).toBe(10);
  });
  test("logScale puts decades evenly and ticks at 1-2-4", () => {
    const s = logScale([0.1, 10], 0, 200);
    expect(s.at(0.1)).toBeCloseTo(0, 6);
    expect(s.at(1)).toBeCloseTo(100, 6);
    expect(s.at(10)).toBeCloseTo(200, 6);
    expect(s.ticks).toEqual([0.1, 0.2, 0.4, 1, 2, 4, 10]);
    expect(Number.isFinite(s.at(0))).toBe(true);
  });
});

function Probe({ fallback }: { fallback: number }) {
  const [ref, width] = useElementWidth<HTMLDivElement>(fallback);
  return <div ref={ref}>w={width}</div>;
}

describe("useElementWidth", () => {
  test("uses the fallback when layout reports 0", () => {
    render(<Probe fallback={640} />);
    expect(screen.getByText("w=640")).toBeTruthy();
  });
  test("uses the measured width when layout reports one", () => {
    const orig = HTMLElement.prototype.getBoundingClientRect;
    HTMLElement.prototype.getBoundingClientRect = function () {
      return { width: 512.4, height: 10, top: 0, left: 0, right: 512.4, bottom: 10, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;
    };
    try {
      render(<Probe fallback={640} />);
      expect(screen.getByText("w=512")).toBeTruthy();
    } finally {
      HTMLElement.prototype.getBoundingClientRect = orig;
    }
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `(cd ui && bun test test/charts/Scale.test.tsx)`
Expected: FAIL with `Cannot find module '../../src/charts/Scale' from '.../test/charts/Scale.test.tsx'`.

- [ ] **Step 4: Write the implementation**

`ui/src/charts/Scale.tsx`:

```tsx
/**
 * Scales, number formats, and width measurement shared by every chart.
 *
 * All chart math goes through these helpers so that the leaderboard, curves, and
 * later panels format numbers the same way (U+2212 minus, tabular decimals).
 */
import { scaleLinear, scaleLog } from "d3-scale";
import { format } from "d3-format";
import { useLayoutEffect, useRef, useState, type RefObject } from "react";

/** A numeric position function, value to pixel. */
export type Pos = (v: number) => number;

/** Typographic minus sign used for every negative number on screen. */
export const MINUS = "−";

function fixed(v: number, digits: number): string {
  const s = Math.abs(v).toFixed(digits);
  return v < 0 && Number(s) !== 0 ? MINUS + s : s;
}

/** Format with 2 decimals, e.g. `0.15`. */
export const f2 = (v: number): string => fixed(v, 2);
/** Format with 3 decimals, e.g. `0.874`. */
export const f3 = (v: number): string => fixed(v, 3);
/** Format with 4 decimals, e.g. `0.9222`. */
export const f4 = (v: number): string => fixed(v, 4);

/** Format a difference with an explicit sign, e.g. `+0.037` or `−0.037`. */
export function signed(v: number, digits = 3): string {
  const s = fixed(v, digits);
  return v > 0 && Number(s) !== 0 ? `+${s}` : s;
}

/**
 * Format a p-value: two decimals, three below 0.01 (never `0.00`), `< 0.001` when tiny.
 *
 * Same rule as the server's `hypothex.core.headlines.fmt_p`, so headlines and panels agree.
 */
export function fmtP(p: number): string {
  if (p < 0.001) return "< 0.001";
  return p < 0.01 ? p.toFixed(3) : p.toFixed(2);
}

const sig3 = format(".3~r");
const grouped = format(",");
const rounded = format(",.0f");

/**
 * Format a free-standing number for a stat strip or tooltip.
 *
 * Integers get thousands separators, large numbers are rounded, and small numbers
 * keep three significant digits.
 */
export function fmtValue(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  if (Number.isInteger(v)) return grouped(v).replace("-", MINUS);
  if (Math.abs(v) >= 100) return rounded(v).replace("-", MINUS);
  return sig3(v).replace("-", MINUS);
}

/** Format a training step compactly: `0`, `999`, `1.5k`, `20k`, `1.2M`. */
export function kStep(s: number): string {
  if (Math.abs(s) >= 1e6) return `${+(s / 1e6).toFixed(1)}M`;
  if (Math.abs(s) >= 1e3) return `${+(s / 1e3).toFixed(1)}k`;
  return String(s);
}

/** Number of decimals needed to tell adjacent ticks apart. */
export function tickDecimals(ticks: number[]): number {
  if (ticks.length < 2) return 2;
  const step = Math.abs((ticks[1] ?? 0) - (ticks[0] ?? 0));
  if (step === 0) return 2;
  return Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
}

/** A tick label formatter with just enough decimals for `ticks`, e.g. `0.78`, `0.885`. */
export function tickFormat(ticks: number[]): (v: number) => string {
  const d = tickDecimals(ticks);
  return (v) => fixed(v, d);
}

/**
 * Return a padded, nice domain covering all finite values.
 *
 * Empty input gives `[0, 1]`; a single distinct value is widened by 1% of its
 * magnitude (or 0.01 at zero) so the scale never divides by zero.
 */
export function niceDomain(values: number[]): [number, number] {
  const xs = values.filter(Number.isFinite);
  if (xs.length === 0) return [0, 1];
  let lo = Math.min(...xs);
  let hi = Math.max(...xs);
  if (lo === hi) {
    const pad = lo === 0 ? 0.01 : Math.abs(lo) * 0.01;
    lo -= pad;
    hi += pad;
  }
  const d = scaleLinear().domain([lo, hi]).nice(8).domain();
  return [d[0] ?? lo, d[1] ?? hi];
}

/** A linear scale with its ticks. */
export interface LinearScale {
  at: Pos;
  ticks: number[];
  domain: [number, number];
  invert: Pos;
}

/** Build a linear scale over `domain` mapped to `[r0, r1]`, with about `count` ticks. */
export function linear(domain: [number, number], r0: number, r1: number, count = 8): LinearScale {
  const s = scaleLinear().domain(domain).range([r0, r1]);
  return { at: (v) => s(v), ticks: s.ticks(count), domain, invert: (px) => s.invert(px) };
}

/**
 * Build a log scale over positive values mapped to `[r0, r1]`.
 *
 * Ticks are the 1-2-4 steps of each decade inside the domain, as in the mockups.
 */
export function logScale(domain: [number, number], r0: number, r1: number): LinearScale {
  const lo = Math.max(domain[0], 1e-12);
  const hi = Math.max(domain[1], lo * 1.0001);
  const s = scaleLog().domain([lo, hi]).range([r0, r1]).clamp(false);
  const ticks: number[] = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.ceil(Math.log10(hi)); e++) {
    for (const m of [1, 2, 4]) {
      const t = +(m * 10 ** e).toPrecision(6);
      if (t >= lo && t <= hi) ticks.push(t);
    }
  }
  return {
    at: (v) => s(Math.max(v, 1e-12)),
    ticks,
    domain: [lo, hi],
    invert: (px) => s.invert(px),
  };
}

/**
 * Measure an element's width, falling back to `fallback` when layout is unknown.
 *
 * Charts render at `fallback` first (and in test DOMs, where width is 0), then
 * re-render at the measured width and on every resize.
 */
export function useElementWidth<T extends HTMLElement>(
  fallback: number,
): [RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const read = (): void => {
      const w = el.getBoundingClientRect().width;
      if (w > 0) setWidth(Math.round(w));
    };
    read();
    if (typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(read);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}
```

- [ ] **Step 5: Run the test and the type check**

Run: `(cd ui && bun test test/charts/Scale.test.tsx && bunx tsc --noEmit -p .)`
Expected: `12 pass`, `0 fail`; `tsc` prints nothing.

- [ ] **Step 6: Commit**

```bash
git add ui/package.json ui/bun.lock ui/src/charts/Scale.tsx ui/test/charts/Scale.test.tsx
git commit -m "feat(ui): add chart scales, number formats, and width hook"
```

### Task 9: Axes and tooltips

**Files:**
- Create: `ui/src/charts/Axis.tsx`, `ui/src/charts/Tooltip.tsx`
- Test: `ui/test/charts/Axis.test.tsx`, `ui/test/charts/Tooltip.test.tsx`

**Interfaces:**
- Consumes: Task 8 (`Pos`).
- Produces:
  - `ui/src/charts/Axis.tsx`: `AxisBottom({x, ticks, y, x0, x1, format, label?, every = 1})`
    (baseline, 4 px ticks, labels at `y + 17`, caption right-aligned at `y + 36`),
    `GridX({x, ticks, y0, y1})`, `GridY({y, ticks, x0, x1})`,
    `AxisLeftLabels({y, ticks, x, format})` (right-aligned at `x`, baseline `y(t) + 4`).
  - `ui/src/charts/Tooltip.tsx`: `useTooltip(): Tooltip` with
    `bind(text) => {onMouseEnter, onMouseMove, onMouseLeave, onFocus, onBlur}`,
    `show(text, x, y)`, `hide()`, `state: TipState | null`, `node: ReactNode`
    (a `div.hx-tip[role=tooltip]`, `position: fixed` at pointer + `TIP_OFFSET` = 12 px,
    newlines kept). Render `node` once per chart.

- [ ] **Step 1: Write the failing tests**

`ui/test/charts/Axis.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { cleanup, render } from "@testing-library/react";
import { AxisBottom, AxisLeftLabels, GridX, GridY } from "../../src/charts/Axis";

afterEach(cleanup);

const x = (v: number) => 100 + v * 10;

test("AxisBottom draws a baseline, one tick per value, labels and caption", () => {
  const { container } = render(
    <svg>
      <AxisBottom x={x} ticks={[0, 5, 10]} y={50} x0={0} x1={300} format={(v) => `${v}%`} label="accuracy" />
    </svg>,
  );
  const lines = container.querySelectorAll("line.axis");
  expect(lines.length).toBe(4);
  const tick = lines[2] as SVGLineElement;
  expect(tick.getAttribute("x1")).toBe("150");
  expect(tick.getAttribute("y2")).toBe("54");
  const labels = [...container.querySelectorAll("text.tk")].map((t) => t.textContent);
  expect(labels).toEqual(["0%", "5%", "10%"]);
  const caption = container.querySelector("text.lbl-s");
  expect(caption?.textContent).toBe("accuracy");
  expect(caption?.getAttribute("x")).toBe("300");
  expect(caption?.getAttribute("text-anchor")).toBe("end");
});

test("AxisBottom labels every n-th tick only", () => {
  const { container } = render(
    <svg>
      <AxisBottom x={x} ticks={[0, 1, 2, 3, 4]} y={0} x0={0} x1={10} format={String} every={2} />
    </svg>,
  );
  const labels = [...container.querySelectorAll("text.tk")].map((t) => t.textContent);
  expect(labels).toEqual(["0", "2", "4"]);
  expect(container.querySelector("text.lbl-s")).toBeNull();
});

test("grids and left labels sit at the scaled positions", () => {
  const { container } = render(
    <svg>
      <GridX x={x} ticks={[1, 2]} y0={0} y1={80} />
      <GridY y={x} ticks={[3]} x0={5} x1={95} />
      <AxisLeftLabels y={x} ticks={[3]} x={40} format={(v) => v.toFixed(1)} />
    </svg>,
  );
  const grid = [...container.querySelectorAll("line.grid")];
  expect(grid.map((l) => l.getAttribute("x1"))).toEqual(["110", "120", "5"]);
  expect(grid[2]?.getAttribute("y1")).toBe("130");
  const lbl = container.querySelector(".axis-l text");
  expect(lbl?.textContent).toBe("3.0");
  expect(lbl?.getAttribute("y")).toBe("134");
});
```

`ui/test/charts/Tooltip.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { TIP_OFFSET, useTooltip } from "../../src/charts/Tooltip";

afterEach(cleanup);

function Chart() {
  const tip = useTooltip();
  return (
    <div>
      <svg>
        <rect data-testid="mark" tabIndex={0} {...tip.bind("mean 0.9222\nseeds 3")} />
      </svg>
      {tip.node}
    </div>
  );
}

test("hover shows the text next to the pointer and leave hides it", () => {
  render(<Chart />);
  expect(screen.queryByRole("tooltip")).toBeNull();
  fireEvent.mouseEnter(screen.getByTestId("mark"), { clientX: 10, clientY: 20 });
  const tip = screen.getByRole("tooltip");
  expect(tip.textContent).toBe("mean 0.9222\nseeds 3");
  expect(tip.style.left).toBe(`${10 + TIP_OFFSET}px`);
  expect(tip.style.top).toBe(`${20 + TIP_OFFSET}px`);
  fireEvent.mouseMove(screen.getByTestId("mark"), { clientX: 30, clientY: 40 });
  expect(screen.getByRole("tooltip").style.left).toBe(`${30 + TIP_OFFSET}px`);
  fireEvent.mouseLeave(screen.getByTestId("mark"));
  expect(screen.queryByRole("tooltip")).toBeNull();
});

test("keyboard focus shows the tooltip and blur hides it", () => {
  render(<Chart />);
  fireEvent.focus(screen.getByTestId("mark"));
  expect(screen.getByRole("tooltip").textContent).toBe("mean 0.9222\nseeds 3");
  fireEvent.blur(screen.getByTestId("mark"));
  expect(screen.queryByRole("tooltip")).toBeNull();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `(cd ui && bun test test/charts/Axis.test.tsx test/charts/Tooltip.test.tsx)`
Expected: FAIL with `Cannot find module '../../src/charts/Axis'` and `Cannot find module '../../src/charts/Tooltip'`.

- [ ] **Step 3: Write the implementation**

`ui/src/charts/Axis.tsx`:

```tsx
/**
 * Axis and grid primitives for SVG charts (journal style: hairline grid, small ticks).
 */
import type { ReactElement } from "react";
import type { Pos } from "./Scale";

/** Props for {@link AxisBottom}. */
export interface AxisBottomProps {
  /** Value to x pixel. */
  x: Pos;
  /** Tick values. */
  ticks: number[];
  /** Baseline y. */
  y: number;
  /** Left end of the axis line. */
  x0: number;
  /** Right end of the axis line. */
  x1: number;
  /** Tick label format. */
  format: (v: number) => string;
  /** Axis caption, drawn right-aligned under the tick labels. */
  label?: string;
  /** Label every n-th tick (1 = all). */
  every?: number;
}

/** Horizontal axis: baseline, 4 px ticks, labels, optional right-aligned caption. */
export function AxisBottom({
  x,
  ticks,
  y,
  x0,
  x1,
  format,
  label,
  every = 1,
}: AxisBottomProps): ReactElement {
  return (
    <g className="axis-b">
      <line className="axis" x1={x0} x2={x1} y1={y} y2={y} />
      {ticks.map((t, i) => (
        <g key={t}>
          <line className="axis" x1={x(t)} x2={x(t)} y1={y} y2={y + 4} />
          {i % every === 0 ? (
            <text className="tk" x={x(t)} y={y + 17} textAnchor="middle">
              {format(t)}
            </text>
          ) : null}
        </g>
      ))}
      {label ? (
        <text className="lbl-s" x={x1} y={y + 36} textAnchor="end">
          {label}
        </text>
      ) : null}
    </g>
  );
}

/** Vertical grid lines at `ticks`, from `y0` to `y1`. */
export function GridX({
  x,
  ticks,
  y0,
  y1,
}: {
  x: Pos;
  ticks: number[];
  y0: number;
  y1: number;
}): ReactElement {
  return (
    <g className="grid-x">
      {ticks.map((t) => (
        <line key={t} className="grid" x1={x(t)} x2={x(t)} y1={y0} y2={y1} />
      ))}
    </g>
  );
}

/** Horizontal grid lines at `ticks`, from `x0` to `x1`. */
export function GridY({
  y,
  ticks,
  x0,
  x1,
}: {
  y: Pos;
  ticks: number[];
  x0: number;
  x1: number;
}): ReactElement {
  return (
    <g className="grid-y">
      {ticks.map((t) => (
        <line key={t} className="grid" x1={x0} x2={x1} y1={y(t)} y2={y(t)} />
      ))}
    </g>
  );
}

/** Right-aligned y tick labels ending at `x`. */
export function AxisLeftLabels({
  y,
  ticks,
  x,
  format,
}: {
  y: Pos;
  ticks: number[];
  x: number;
  format: (v: number) => string;
}): ReactElement {
  return (
    <g className="axis-l">
      {ticks.map((t) => (
        <text key={t} className="tk" x={x} y={y(t) + 4} textAnchor="end">
          {format(t)}
        </text>
      ))}
    </g>
  );
}
```

`ui/src/charts/Tooltip.tsx`:

```tsx
/**
 * Hover tooltips for SVG marks.
 *
 * Page copy stays terse; explanations and exact numbers live in these tooltips.
 * Text may contain newlines, which render as line breaks.
 */
import { useCallback, useMemo, useState, type FocusEvent, type MouseEvent, type ReactNode } from "react";

/** Where and what the tooltip shows. */
export interface TipState {
  text: string;
  x: number;
  y: number;
}

/** Event handlers that show a tooltip for one mark. */
export interface TipHandlers {
  onMouseEnter: (e: MouseEvent<Element>) => void;
  onMouseMove: (e: MouseEvent<Element>) => void;
  onMouseLeave: () => void;
  onFocus: (e: FocusEvent<Element>) => void;
  onBlur: () => void;
}

/** What {@link useTooltip} returns. */
export interface Tooltip {
  /** Handlers to spread on a mark: `<rect {...tip.bind("mean 0.92")} />`. */
  bind: (text: string) => TipHandlers;
  /** Show `text` at viewport position (`x`, `y`). */
  show: (text: string, x: number, y: number) => void;
  /** Hide the tooltip. */
  hide: () => void;
  /** Current state, `null` when hidden. */
  state: TipState | null;
  /** The tooltip element; render it once inside the chart. */
  node: ReactNode;
}

/** Pixel offset from the pointer. */
export const TIP_OFFSET = 12;

/**
 * Tooltip state for one chart.
 *
 * Returns
 * -------
 * Tooltip
 *     `bind(text)` handlers for marks and the `node` to render.
 */
export function useTooltip(): Tooltip {
  const [state, setState] = useState<TipState | null>(null);
  const show = useCallback((text: string, x: number, y: number) => setState({ text, x, y }), []);
  const hide = useCallback(() => setState(null), []);
  const bind = useCallback(
    (text: string): TipHandlers => ({
      onMouseEnter: (e) => show(text, e.clientX, e.clientY),
      onMouseMove: (e) => show(text, e.clientX, e.clientY),
      onMouseLeave: hide,
      onFocus: (e) => {
        const r = e.currentTarget.getBoundingClientRect();
        show(text, r.left + r.width / 2, r.top);
      },
      onBlur: hide,
    }),
    [show, hide],
  );
  const node = useMemo(
    () =>
      state ? (
        <div
          role="tooltip"
          className="hx-tip"
          style={{ left: state.x + TIP_OFFSET, top: state.y + TIP_OFFSET }}
        >
          {state.text}
        </div>
      ) : null,
    [state],
  );
  return { bind, show, hide, state, node };
}
```

- [ ] **Step 4: Run the tests and the type check**

Run: `(cd ui && bun test test/charts/Axis.test.tsx test/charts/Tooltip.test.tsx && bunx tsc --noEmit -p .)`
Expected: `5 pass`, `0 fail`; `tsc` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add ui/src/charts/Axis.tsx ui/test/charts/Axis.test.tsx ui/src/charts/Tooltip.tsx ui/test/charts/Tooltip.test.tsx
git commit -m "feat(ui): add chart axes, grids, and hover tooltips"
```

### Task 10: Glyph language and chart styles

**Files:**
- Create: `ui/src/charts/Glyphs.tsx`, `ui/src/charts/charts.css`
- Test: `ui/test/charts/Glyphs.test.tsx`

**Interfaces:**
- Consumes: Task 8 (`Pos`); Task 2 `tokens.css` variables and the `.key` rules in `base.css`.
- Produces (`ui/src/charts/Glyphs.tsx`, which imports `charts.css` so any chart that uses a glyph
  gets the styles):
  - `SEED_GAP = 8`; `stackSeeds(xs: number[], gap = SEED_GAP): {x, level}[]`.
  - `SeedDots({x, values, y, r = 3.8})` (`circle.seed`, `cy = y − 8·level`).
  - `diamondPath(cx, cy, r)`, `Diamond({cx, cy, r = 6.5, best})` (`path.dia[.best]`).
  - `IdenticalSeeds({cx, cy, n, best, r = 6.5})` (diamond + bold `×n`, right of the mark, left
    for the best row).
  - `MeanMark({cx, cy, r = 4.5, best})` (`rect.mean[.best]`), `Whisker({x1, x2, y, best})`
    (`path.whisk[.best]`), `BestBand({x1, x2, y0, y1})` (`rect.band` + 2 `line.band-edge`).
  - `SpikeMark({x, y, s = 1})` (`path.evg`), `KillMark({x, y, r = 3.5})` (`path.m-fail`),
    `CheckpointMark({cx, cy, best})` (`circle.m-best.ringed` r 4.5, or `circle.ck` r 3.2).
  - `type KeyGlyphKind = "seed" | "identical" | "whisker" | "band" | "seedLine" | "meanLine" |
    "bestCkpt" | "ckpt" | "spike" | "killed"`; `KeyGlyph({kind})` (inline
    `svg.hx-chart.glyph[data-glyph]`); `interface KeyItem {glyph; label; title?}`;
    `Key({items})` (`div.key[aria-label=Key]`).
  - CSS classes (scoped under `.hx-chart`): `tk lbl lbl-s lbl-b ttl axis grid hair band band-edge
    bestline whisk mean seed dia m-best ringed m-fail hit sl ml lrl lra ev evg clipm ck xh`;
    plus `.hx-tip` (`.key` comes from `base.css`, Task 2). Every chart root `<svg>` carries `className="hx-chart"`.

- [ ] **Step 1: Write the failing test**

`ui/test/charts/Glyphs.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import {
  BestBand,
  CheckpointMark,
  IdenticalSeeds,
  Key,
  KillMark,
  MeanMark,
  SeedDots,
  SpikeMark,
  Whisker,
  diamondPath,
  stackSeeds,
} from "../../src/charts/Glyphs";

afterEach(cleanup);

describe("stackSeeds", () => {
  test("close dots stack, far dots reset to level 0", () => {
    expect(stackSeeds([50, 10, 13, 16, 30])).toEqual([
      { x: 10, level: 0 },
      { x: 13, level: 1 },
      { x: 16, level: 2 },
      { x: 30, level: 0 },
      { x: 50, level: 0 },
    ]);
  });
  test("identical positions stack upward", () => {
    expect(stackSeeds([5, 5]).map((d) => d.level)).toEqual([0, 1]);
    expect(stackSeeds([])).toEqual([]);
  });
});

test("SeedDots draws one dot per finite seed, 8 px per stack level", () => {
  const { container } = render(
    <svg>
      <SeedDots x={(v) => v * 100} values={[0.1, 0.12, 0.5, Number.NaN]} y={30} />
    </svg>,
  );
  const dots = [...container.querySelectorAll("circle.seed")];
  expect(dots.length).toBe(3);
  expect(dots.map((d) => d.getAttribute("cy"))).toEqual(["30", "22", "30"]);
});

test("diamondPath is a closed rhombus", () => {
  expect(diamondPath(10, 20, 5)).toBe("M10 15L15 20L10 25L5 20Z");
});

test("IdenticalSeeds shows ×n right of the diamond, left for the best row", () => {
  const { container, rerender } = render(
    <svg>
      <IdenticalSeeds cx={100} cy={30} n={3} />
    </svg>,
  );
  let label = container.querySelector("text");
  expect(label?.textContent).toBe("×3");
  expect(label?.getAttribute("x")).toBe("111");
  expect(container.querySelector("path.dia")?.getAttribute("class")).toBe("dia");
  rerender(
    <svg>
      <IdenticalSeeds cx={100} cy={30} n={3} best />
    </svg>,
  );
  label = container.querySelector("text");
  expect(label?.getAttribute("x")).toBe("89");
  expect(label?.getAttribute("text-anchor")).toBe("end");
  expect(container.querySelector("path.dia")?.getAttribute("class")).toBe("dia best");
});

test("MeanMark, Whisker and BestBand geometry", () => {
  const { container } = render(
    <svg>
      <MeanMark cx={50} cy={58} best />
      <Whisker x1={20} x2={80} y={58} />
      <BestBand x1={90} x2={60} y0={0} y1={104} />
    </svg>,
  );
  const sq = container.querySelector("rect.mean");
  expect(sq?.getAttribute("x")).toBe("45.5");
  expect(sq?.getAttribute("width")).toBe("9");
  expect(sq?.getAttribute("class")).toBe("mean best");
  expect(container.querySelector("path.whisk")?.getAttribute("d")).toBe("M20 58H80M20 54V62M80 54V62");
  const band = container.querySelector("rect.band");
  expect(band?.getAttribute("x")).toBe("60");
  expect(band?.getAttribute("width")).toBe("30");
  expect(container.querySelectorAll("line.band-edge").length).toBe(2);
});

test("event and checkpoint marks use their classes", () => {
  const { container } = render(
    <svg>
      <SpikeMark x={10} y={10} />
      <KillMark x={20} y={20} r={4} />
      <CheckpointMark cx={30} cy={30} />
      <CheckpointMark cx={40} cy={40} best />
    </svg>,
  );
  expect(container.querySelector("path.evg")?.getAttribute("d")).toBe("M4 14H7.5L10 5L12.5 14H16");
  expect(container.querySelector("path.m-fail")?.getAttribute("d")).toBe("M16 16L24 24M24 16L16 24");
  expect(container.querySelector("circle.ck")?.getAttribute("r")).toBe("3.2");
  expect(container.querySelector("circle.m-best")?.getAttribute("r")).toBe("4.5");
});

test("Key renders one labelled glyph per item with its tooltip", () => {
  render(
    <Key
      items={[
        { glyph: "seed", label: "seed" },
        { glyph: "identical", label: "×3 identical seeds", title: "All seeds gave one score" },
      ]}
    />,
  );
  const key = screen.getByLabelText("Key");
  expect(key.querySelectorAll("svg").length).toBe(2);
  expect(key.querySelector("[data-glyph=identical]")).not.toBeNull();
  expect(screen.getByTitle("All seeds gave one score").textContent).toBe("×3 identical seeds");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `(cd ui && bun test test/charts/Glyphs.test.tsx)`
Expected: FAIL with `Cannot find module '../../src/charts/Glyphs'`.

- [ ] **Step 3: Write the styles**

`ui/src/charts/charts.css`:

```css
/* Chart marks. Values copied from docs/mockups/ui-v4 and docs/mockups/kinds/training. */
.hx-chart { display: block; overflow: visible; }
.hx-chart.glyph { display: inline-block; vertical-align: middle; }
.hx-chart text { font-family: var(--sans); fill: var(--ink-2); }
.hx-chart .tk { font-size: 11.5px; fill: var(--ink-3); font-variant-numeric: tabular-nums; }
.hx-chart .lbl { font-size: 12.5px; fill: var(--ink-2); }
.hx-chart .lbl-s { font-size: 11.5px; fill: var(--ink-3); }
.hx-chart .lbl-b { font-size: 12.5px; fill: var(--ink); font-weight: 600; }
.hx-chart .ttl { font-size: 14px; font-weight: 600; fill: var(--ink); }
.hx-chart .axis { stroke: var(--ink-3); stroke-width: 1; }
.hx-chart .grid { stroke: var(--rule-2); stroke-width: 1; }
.hx-chart .hair { stroke: var(--rule); stroke-width: 1; }
.hx-chart .band { fill: var(--best-wash); }
.hx-chart .band-edge { stroke: var(--best-edge); stroke-width: 1; }
.hx-chart .bestline { stroke: var(--best); stroke-width: 1.25; }
.hx-chart .whisk { stroke: var(--ink-3); stroke-width: 1.5; stroke-linecap: round; fill: none; }
.hx-chart .whisk.best { stroke: var(--best); }
.hx-chart .mean { fill: var(--ink); stroke: var(--paper); stroke-width: 2; }
.hx-chart .mean.best { fill: var(--best); }
.hx-chart .seed { fill: var(--ink-2); stroke: var(--paper); stroke-width: 2; }
.hx-chart .dia { fill: var(--paper); stroke: var(--ink); stroke-width: 1.6; }
.hx-chart .dia.best { stroke: var(--best); fill: var(--best-wash); }
.hx-chart .m-best { fill: var(--best); }
.hx-chart .ringed { stroke: var(--paper); stroke-width: 2; }
.hx-chart .m-fail { stroke: var(--fail); stroke-width: 2; stroke-linecap: round; fill: none; }
.hx-chart .hit { fill: transparent; cursor: default; }
.hx-chart .hit:focus-visible { outline: none; stroke: var(--agent); stroke-width: 1; }
.hx-chart .sl { stroke: var(--ink-3); stroke-width: 1; fill: none; opacity: .6; }
.hx-chart .ml { stroke: var(--ink); stroke-width: 2; fill: none; stroke-linejoin: round; }
.hx-chart .lrl { stroke: var(--ink-2); stroke-width: 1.5; fill: none; }
.hx-chart .lra { fill: var(--paper-2); }
.hx-chart .ev { stroke: var(--fail); stroke-width: 1.25; stroke-dasharray: 3 3; }
.hx-chart .evg { stroke: var(--fail); stroke-width: 1.6; fill: none; stroke-linejoin: round; stroke-linecap: round; }
.hx-chart .clipm { fill: var(--fail); }
.hx-chart .ck { fill: var(--paper); stroke: var(--ink-2); stroke-width: 1.4; }
.hx-chart .xh { stroke: var(--ink-2); stroke-width: 1; stroke-dasharray: 2 2; pointer-events: none; }

.hx-tip {
  position: fixed; z-index: 50; pointer-events: none; max-width: 320px;
  padding: 7px 10px; border-radius: 6px; background: var(--ink); color: var(--paper);
  font: 400 12.5px/1.45 var(--sans); font-variant-numeric: tabular-nums; white-space: pre-line;
}
```

- [ ] **Step 4: Write the implementation**

`ui/src/charts/Glyphs.tsx`:

```tsx
/**
 * The glyph language shared by every chart.
 *
 * - seed dots: one dot per seed, stacked when they would overlap;
 * - diamond with `×n`: n seeds that all gave one score (never a fake `± 0`);
 * - mean square plus whisker: the test-set 95% interval;
 * - best band: the best group's interval, drawn behind all rows;
 * - spike, kill, and checkpoint marks for training curves.
 */
import type { ReactElement } from "react";
import type { Pos } from "./Scale";
import "./charts.css";

/** Minimum horizontal gap in px before seed dots stack. */
export const SEED_GAP = 8;

/** A seed dot position after stacking. */
export interface StackedDot {
  x: number;
  level: number;
}

/**
 * Stack dots that would overlap into a tiny beeswarm.
 *
 * Positions are sorted; a dot closer than `gap` to the previous one sits one level
 * higher, otherwise it goes back to level 0.
 *
 * Parameters
 * ----------
 * xs : number[]
 *     Pixel positions.
 * gap : number
 *     Minimum distance before stacking.
 *
 * Returns
 * -------
 * StackedDot[]
 *     Sorted positions with their stack level.
 */
export function stackSeeds(xs: number[], gap = SEED_GAP): StackedDot[] {
  const out: StackedDot[] = [];
  let prev = Number.NEGATIVE_INFINITY;
  let level = 0;
  for (const x of [...xs].sort((a, b) => a - b)) {
    level = x - prev < gap ? level + 1 : 0;
    out.push({ x, level });
    prev = x;
  }
  return out;
}

/** One dot per seed value, stacked upward from `y`. */
export function SeedDots({
  x,
  values,
  y,
  r = 3.8,
}: {
  x: Pos;
  values: number[];
  y: number;
  r?: number;
}): ReactElement {
  return (
    <g className="seeds">
      {stackSeeds(values.filter(Number.isFinite).map(x)).map((d, i) => (
        <circle key={i} className="seed" cx={d.x} cy={y - d.level * SEED_GAP} r={r} />
      ))}
    </g>
  );
}

/** SVG path of a diamond centred on (`cx`, `cy`) with half-diagonal `r`. */
export function diamondPath(cx: number, cy: number, r: number): string {
  return `M${cx} ${cy - r}L${cx + r} ${cy}L${cx} ${cy + r}L${cx - r} ${cy}Z`;
}

/** A hollow diamond; green-washed when `best`. */
export function Diamond({
  cx,
  cy,
  r = 6.5,
  best = false,
}: {
  cx: number;
  cy: number;
  r?: number;
  best?: boolean;
}): ReactElement {
  return <path className={best ? "dia best" : "dia"} d={diamondPath(cx, cy, r)} />;
}

/** `n` identical seeds: a diamond plus a bold `×n` (left of the mark for the best row). */
export function IdenticalSeeds({
  cx,
  cy,
  n,
  best = false,
  r = 6.5,
}: {
  cx: number;
  cy: number;
  n: number;
  best?: boolean;
  r?: number;
}): ReactElement {
  const dx = r + 4.5;
  return (
    <g className="identical">
      <Diamond cx={cx} cy={cy} r={r} best={best} />
      <text
        className="lbl-b"
        x={best ? cx - dx : cx + dx}
        y={cy + 4}
        textAnchor={best ? "end" : "start"}
      >
        {`×${n}`}
      </text>
    </g>
  );
}

/** The group mean: a small rounded square. */
export function MeanMark({
  cx,
  cy,
  r = 4.5,
  best = false,
}: {
  cx: number;
  cy: number;
  r?: number;
  best?: boolean;
}): ReactElement {
  return (
    <rect
      className={best ? "mean best" : "mean"}
      x={cx - r}
      y={cy - r}
      width={2 * r}
      height={2 * r}
      rx={1.5}
    />
  );
}

/** A 95% interval: horizontal line with 8 px end caps. */
export function Whisker({
  x1,
  x2,
  y,
  best = false,
}: {
  x1: number;
  x2: number;
  y: number;
  best?: boolean;
}): ReactElement {
  return (
    <path
      className={best ? "whisk best" : "whisk"}
      d={`M${x1} ${y}H${x2}M${x1} ${y - 4}V${y + 4}M${x2} ${y - 4}V${y + 4}`}
    />
  );
}

/** The best group's interval as a washed band with edge lines. */
export function BestBand({
  x1,
  x2,
  y0,
  y1,
}: {
  x1: number;
  x2: number;
  y0: number;
  y1: number;
}): ReactElement {
  const a = Math.min(x1, x2);
  const b = Math.max(x1, x2);
  return (
    <g className="best-band">
      <rect className="band" x={a} y={y0} width={b - a} height={Math.max(0, y1 - y0)} />
      <line className="band-edge" x1={a} x2={a} y1={y0} y2={y1} />
      <line className="band-edge" x1={b} x2={b} y1={y0} y2={y1} />
    </g>
  );
}

/** A loss-spike glyph (a red peak), centred on (`x`, `y`), scaled by `s`. */
export function SpikeMark({ x, y, s = 1 }: { x: number; y: number; s?: number }): ReactElement {
  return (
    <path
      className="evg"
      d={`M${x - 6 * s} ${y + 4 * s}H${x - 2.5 * s}L${x} ${y - 5 * s}L${x + 2.5 * s} ${y + 4 * s}H${x + 6 * s}`}
    />
  );
}

/** A killed or failed run: a red cross. */
export function KillMark({ x, y, r = 3.5 }: { x: number; y: number; r?: number }): ReactElement {
  return (
    <path
      className="m-fail"
      d={`M${x - r} ${y - r}L${x + r} ${y + r}M${x + r} ${y - r}L${x - r} ${y + r}`}
    />
  );
}

/** A checkpoint: hollow ring, or a filled green dot for the best checkpoint. */
export function CheckpointMark({
  cx,
  cy,
  best = false,
}: {
  cx: number;
  cy: number;
  best?: boolean;
}): ReactElement {
  return best ? (
    <circle className="m-best ringed" cx={cx} cy={cy} r={4.5} />
  ) : (
    <circle className="ck" cx={cx} cy={cy} r={3.2} />
  );
}

/** Glyphs available in chart keys. */
export type KeyGlyphKind =
  | "seed"
  | "identical"
  | "whisker"
  | "band"
  | "seedLine"
  | "meanLine"
  | "bestCkpt"
  | "ckpt"
  | "spike"
  | "killed";

/** A small inline SVG of one glyph, for keys and table cells. */
export function KeyGlyph({ kind }: { kind: KeyGlyphKind }): ReactElement {
  const box = (w: number, body: ReactElement): ReactElement => (
    <svg className="hx-chart glyph" width={w} height={12} aria-hidden="true" data-glyph={kind}>
      {body}
    </svg>
  );
  switch (kind) {
    case "seed":
      return box(
        18,
        <>
          <circle className="seed" cx={5} cy={6} r={3.6} />
          <circle className="seed" cx={13} cy={6} r={3.6} />
        </>,
      );
    case "identical":
      return box(12, <Diamond cx={6} cy={6} r={5} />);
    case "whisker":
      return box(22, <path className="whisk" d="M2 6H20M2 2V10M20 2V10" />);
    case "band":
      return box(18, <BestBand x1={3} x2={15} y0={0} y1={12} />);
    case "seedLine":
      return box(22, <path className="sl" style={{ opacity: 1 }} d="M1 8L8 5L14 7L21 3" />);
    case "meanLine":
      return box(22, <path className="ml" d="M1 8L8 5L14 7L21 3" />);
    case "bestCkpt":
      return box(12, <circle className="m-best ringed" cx={6} cy={6} r={4} />);
    case "ckpt":
      return box(12, <circle className="ck" cx={6} cy={6} r={3.2} />);
    case "spike":
      return box(16, <SpikeMark x={8} y={6} s={0.9} />);
    case "killed":
      return box(12, <KillMark x={6} y={6} r={4} />);
  }
}

/** One entry of a chart key. */
export interface KeyItem {
  glyph: KeyGlyphKind;
  label: string;
  title?: string;
}

/** A chart key: glyph plus short label per item; explanations in `title`. */
export function Key({ items }: { items: KeyItem[] }): ReactElement {
  return (
    <div className="key" aria-label="Key">
      {items.map((it) => (
        <span key={it.glyph} title={it.title}>
          <KeyGlyph kind={it.glyph} />
          {it.label}
        </span>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Run the chart tests and the type check**

Run: `(cd ui && bun test test/charts && bunx tsc --noEmit -p .)`
Expected: `25 pass`, `0 fail` (Scale 12, Axis 3, Tooltip 2, Glyphs 8); `tsc` prints nothing.

- [ ] **Step 6: Commit**

```bash
git add ui/src/charts/Glyphs.tsx ui/test/charts/Glyphs.test.tsx ui/src/charts/charts.css
git commit -m "feat(ui): add seed, diamond, whisker, band, and event glyphs"
```

### Task 11: Panel registry and StatStrip

**Files:**
- Create: `ui/src/panels/index.ts`, `ui/src/panels/StatStrip.tsx`, `ui/src/panels/panels.css`
- Test: `ui/test/panels/index.test.tsx`, `ui/test/panels/StatStrip.test.tsx`

**Interfaces:**
- Consumes: Task 8 (`fmtValue`).
- Produces:
  - `ui/src/panels/index.ts`: `type PanelType` (re-exported from `ui/src/api/models.ts`);
    `interface PanelResult { type: PanelType; title: string; rows: Array<Record<string, unknown>>;
    meta?: Record<string, unknown> }` (the API model with `meta` optional, so API results pass
    straight in and hand-built results in tests need no `meta`);
    `interface PanelProps { result: PanelResult }`;
    `PANELS: Partial<Record<PanelType, ComponentType<PanelProps>>>`;
    `panelFor(type: string): ComponentType<PanelProps> | null`;
    `PanelError({message})` (`div.panel-error[role=alert]`); `PanelBoundary`;
    `Panel({result})`.
  - `ui/src/panels/StatStrip.tsx`: `interface StatRow {label; value; unit?; tooltip?}`,
    `fmtStat(value: unknown): string`, `StatStrip({result})` (`dl.stats`, one `div[title]` per
    row with `dt` label and `dd` value + `<small> unit</small>`; empty state
    `p.panel-empty` "No stats yet"). `meta.headline` is not drawn here; the page heading owns it.

- [ ] **Step 1: Write the failing tests**

`ui/test/panels/StatStrip.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import { StatStrip, fmtStat } from "../../src/panels/StatStrip";
import type { PanelResult } from "../../src/panels/index";

afterEach(cleanup);

const result: PanelResult = {
  type: "stat_strip",
  title: "SVM vs rf",
  rows: [
    { label: "Δ accuracy", value: 0.037, unit: null, tooltip: "0.0370 = 6.7 of 180 examples" },
    { label: "paired p", value: "0.15", unit: null, tooltip: "Exact two-sided sign test" },
    { label: "fixed / broken", value: "9 / 3", unit: null, tooltip: null },
    { label: "seed σ", value: 0.0064, unit: null, tooltip: null },
    { label: "n for p < 0.05", value: 250, unit: "examples", tooltip: null },
    { label: "cost", value: null, unit: "$", tooltip: null },
  ],
  meta: { headline: "SVM +0.037 over rf, p = 0.15" },
};

test("fmtStat formats numbers, keeps strings, dashes missing values", () => {
  expect(fmtStat(0.037)).toBe("0.037");
  expect(fmtStat(40000)).toBe("40,000");
  expect(fmtStat("9 / 3")).toBe("9 / 3");
  expect(fmtStat(null)).toBe("—");
  expect(fmtStat("")).toBe("—");
});

test("renders one labelled number per row with tooltip and unit", () => {
  const { container } = render(<StatStrip result={result} />);
  const items = [...container.querySelectorAll("dl.stats > div")];
  expect(items.length).toBe(6);
  expect(items.map((d) => d.querySelector("dt")?.textContent)).toEqual([
    "Δ accuracy",
    "paired p",
    "fixed / broken",
    "seed σ",
    "n for p < 0.05",
    "cost",
  ]);
  expect(items.map((d) => d.querySelector("dd")?.textContent)).toEqual([
    "0.037",
    "0.15",
    "9 / 3",
    "0.0064",
    "250 examples",
    "— $",
  ]);
  expect(items[0]?.getAttribute("title")).toBe("0.0370 = 6.7 of 180 examples");
  expect(items[2]?.hasAttribute("title")).toBe(false);
  expect(screen.queryByText("SVM +0.037 over rf, p = 0.15")).toBeNull();
});

test("skips malformed rows and shows an empty state when nothing is left", () => {
  const { container } = render(
    <StatStrip result={{ type: "stat_strip", title: "", rows: [{ value: 1 }, { label: 3 }] }} />,
  );
  expect(container.querySelector("dl")).toBeNull();
  expect(screen.getByText("No stats yet")).toBeTruthy();
});
```

`ui/test/panels/index.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import { PANELS, Panel, panelFor, type PanelProps } from "../../src/panels/index";
import { StatStrip } from "../../src/panels/StatStrip";

afterEach(cleanup);

test("the registry maps stat_strip to StatStrip and rejects unknown types", () => {
  expect(panelFor("stat_strip")).toBe(StatStrip);
  expect(panelFor("pie")).toBeNull();
  expect(panelFor("constructor")).toBeNull();
});

test("Panel renders the registered component", () => {
  render(
    <Panel result={{ type: "stat_strip", title: "", rows: [{ label: "runs", value: 12 }] }} />,
  );
  expect(screen.getByText("runs")).toBeTruthy();
  expect(screen.getByText("12")).toBeTruthy();
});

test("Panel shows an error box for an unknown type", () => {
  render(<Panel result={{ type: "pie" as never, title: "", rows: [] }} />);
  expect(screen.getByRole("alert").textContent).toBe("Unknown panel type: pie");
});

test("Panel contains a panel that throws", () => {
  const Broken = (_: PanelProps) => {
    throw new Error("bad rows");
  };
  const before = PANELS.table;
  PANELS.table = Broken;
  const err = console.error;
  console.error = () => {};
  try {
    render(<Panel result={{ type: "table", title: "", rows: [] }} />);
    expect(screen.getByRole("alert").textContent).toBe("Panel failed: bad rows");
  } finally {
    console.error = err;
    if (before) PANELS.table = before;
    else delete PANELS.table;
  }
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `(cd ui && bun test test/panels)`
Expected: FAIL with `Cannot find module '../../src/panels/StatStrip'` and `Cannot find module '../../src/panels/index'`.

- [ ] **Step 3: Write the styles**

`ui/src/panels/panels.css`:

```css
/* Panel layouts. Values copied from docs/mockups/ui-v4 and docs/mockups/kinds/training.
   The stat strip uses the shared `.stats` rules in styles/base.css. */
.panel-error {
  padding: 10px 12px; border: 1px solid var(--fail); border-radius: 6px;
  color: var(--fail); font-size: 13px;
}
.panel-empty { margin: 0; font-size: 13px; color: var(--ink-3); }
```

- [ ] **Step 4: Write the StatStrip component**

`ui/src/panels/StatStrip.tsx`:

```tsx
/**
 * `stat_strip` panel: a row of big numbers with short labels.
 *
 * Rows are `{label, value, unit, tooltip}`; the tooltip is the only place for
 * explanation.
 */
import type { ReactElement } from "react";
import { fmtValue } from "../charts/Scale";
import type { PanelProps } from "./index";

/** One stat, as sent by the server. */
export interface StatRow {
  label: string;
  value: string | number | null;
  unit?: string | null;
  tooltip?: string | null;
}

/** Format a stat value: numbers via `fmtValue`, strings as sent, missing as a dash. */
export function fmtStat(value: unknown): string {
  if (typeof value === "number") return fmtValue(value);
  if (typeof value === "string" && value !== "") return value;
  return "—";
}

function asStat(row: Record<string, unknown>): StatRow | null {
  if (typeof row.label !== "string") return null;
  return {
    label: row.label,
    value: typeof row.value === "number" || typeof row.value === "string" ? row.value : null,
    unit: typeof row.unit === "string" ? row.unit : null,
    tooltip: typeof row.tooltip === "string" ? row.tooltip : null,
  };
}

/** Draw a `stat_strip` panel result. */
export function StatStrip({ result }: PanelProps): ReactElement {
  const rows = result.rows.map(asStat).filter((r): r is StatRow => r !== null);
  if (rows.length === 0) return <p className="panel-empty">No stats yet</p>;
  return (
    <dl className="stats">
      {rows.map((r, i) => (
        <div key={`${r.label}-${i}`} title={r.tooltip ?? undefined}>
          <dt>{r.label}</dt>
          <dd>
            {fmtStat(r.value)}
            {r.unit ? <small> {r.unit}</small> : null}
          </dd>
        </div>
      ))}
    </dl>
  );
}
```

- [ ] **Step 5: Write the registry**

`ui/src/panels/index.ts`:

```ts
/**
 * Panel registry: maps a `PanelType` to the component that draws its `PanelResult`.
 *
 * Every panel component takes `{ result }`. Unknown types and panels that throw while
 * rendering show a small error box instead of breaking the page.
 */
import { Component, createElement, type ComponentType, type ReactElement, type ReactNode } from "react";
import type { PanelType } from "../api/models";
import { StatStrip } from "./StatStrip";
import "./panels.css";

/** Panel types (contract 1.4), from the API models. */
export type { PanelType };

/** Server-computed panel data, same as `hypothex.core.panels.PanelResult`. */
export interface PanelResult {
  type: PanelType;
  title: string;
  rows: Array<Record<string, unknown>>;
  meta?: Record<string, unknown>;
}

/** Props every panel component takes. */
export interface PanelProps {
  result: PanelResult;
}

/** Registered panel components. Later panel groups add their entries here. */
export const PANELS: Partial<Record<PanelType, ComponentType<PanelProps>>> = {
  stat_strip: StatStrip,
};

/** Return the component for `type`, or `null` if none is registered. */
export function panelFor(type: string): ComponentType<PanelProps> | null {
  return Object.hasOwn(PANELS, type) ? (PANELS[type as PanelType] ?? null) : null;
}

/** A small error box. */
export function PanelError({ message }: { message: string }): ReactElement {
  return createElement("div", { className: "panel-error", role: "alert" }, message);
}

interface BoundaryState {
  error: Error | null;
}

/** Catch render errors in one panel so the rest of the view still draws. */
export class PanelBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  override state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  override render(): ReactNode {
    return this.state.error
      ? createElement(PanelError, { message: `Panel failed: ${this.state.error.message}` })
      : this.props.children;
  }
}

/** Render `result` with its registered component, inside an error boundary. */
export function Panel({ result }: PanelProps): ReactElement {
  const C = panelFor(result.type);
  if (!C) return createElement(PanelError, { message: `Unknown panel type: ${result.type}` });
  return createElement(PanelBoundary, null, createElement(C, { result }));
}
```

- [ ] **Step 6: Run the tests and the type check**

Run: `(cd ui && bun test test/panels && bunx tsc --noEmit -p .)`
Expected: `7 pass`, `0 fail` (StatStrip 3, index 4); `tsc` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add ui/src/panels/index.ts ui/test/panels/index.test.tsx ui/src/panels/StatStrip.tsx ui/test/panels/StatStrip.test.tsx ui/src/panels/panels.css
git commit -m "feat(ui): add panel registry and stat strip panel"
```

### Task 12: Leaderboard forest plot

**Files:**
- Create: `ui/src/panels/Leaderboard.tsx`
- Modify: `ui/src/panels/index.ts` (register), `ui/test/panels/index.test.tsx` (append a test),
  `ui/src/panels/panels.css` (append leaderboard styles)
- Test: `ui/test/panels/Leaderboard.test.tsx`

**Interfaces:**
- Consumes: Task 8 (`f3 f4 fmtP linear niceDomain signed tickFormat useElementWidth
  LinearScale`), Task 9 (`AxisBottom GridX useTooltip Tooltip`), Task 10 (`BestBand
  IdenticalSeeds Key KeyGlyph MeanMark SeedDots Whisker KeyItem`), Task 11 (`PanelProps`).
  Rows are contract 1.7 `LeaderboardRow` JSON. Optional meta read: `meta.primary` (score key or
  bare metric name) and `meta.noise` (`["seed","test_set"]` subset, from `PanelSpec.noise`); both
  default sensibly when absent.
- Produces (`ui/src/panels/Leaderboard.tsx`): `StatsJson`, `NoiseIntervalJson`,
  `VersusBestJson`, `UsageJson`, `LeaderboardRowJson` (aliases of the Task 3 models), `Band {lo, hi, how}`,
  `Verdict {kind: "best"|"band"|"behind"|"none", text, p, tip}`; constants `ROW_H = 104`,
  `SEED_Y = 30`, `CI_Y = 58`, `PLOT_FALLBACK_W = 600`; helpers
  `primaryKey(rows, meta): string | null`, `metricLabel(key)`, `fmtDuration(seconds)`,
  `bestBand(best): Band | null` (test interval, else seed t-interval), `verdictOf(row, best,
  band): Verdict`, `examplesHref(a, b, metric): string` (`/x/<a>/<b>?metric=<metric>`, the
  same URL as Task 23 `hrefs.examples`); component `Leaderboard({result})`; registry entry
  `leaderboard`.
- Examples entry point (spec 8.3 item 4): the vs-best text of each scored non-best row is a
  link to `/x/<row.latest_run_id>/<best.latest_run_id>?metric=<primary metric name>` (the
  metric name is the primary key before `/`, for example `accuracy`), so the Examples screen
  opens from the leaderboard as the mockup's `fixed / broken` does. It is a plain `<a href>`,
  like the run links in panels; on pages, Task 25's `PanelBody` routes plain clicks on these
  links in-app (Task 23 `useInAppLinks`), so they do not reload the page.
- Behaviour: best row = first row with a primary score and `vs_best == null`. The vs-best text is
  computed from the means (`row.mean − best.mean`, signed, 3 decimals) so it does not depend on the
  sign convention of `VersusBest.delta`; `p`, test, fixed/broken, and examples needed come from
  `vs_best` and go into the `title` tooltip.

- [ ] **Step 1: Write the failing test**

`ui/test/panels/Leaderboard.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MINUS } from "../../src/charts/Scale";
import type { PanelResult } from "../../src/panels/index";
import {
  Leaderboard,
  bestBand,
  examplesHref,
  fmtDuration,
  metricLabel,
  primaryKey,
  verdictOf,
  type LeaderboardRowJson,
} from "../../src/panels/Leaderboard";

afterEach(cleanup);

/*
 * Fixture mirrors docs/mockups/ui-v4 (toy-test, n = 180 test examples).
 * Seed scores are k/180: SVM 166/180 on all three seeds; rf 158, 160, 160;
 * knn 156 on all seeds; logreg 149 on all seeds.
 * rf mean = (0.877778 + 0.888889 + 0.888889) / 3 = 0.885185,
 * rf sample std = sqrt(((-0.007407)^2 + 2 * 0.003704^2) / 2) = 0.006415.
 * Wilson 95% intervals (z = 1.959964) as drawn in the mockup.
 */
function row(over: Partial<LeaderboardRowJson> & Pick<LeaderboardRowJson, "group_id">): LeaderboardRowJson {
  return {
    run_ids: ["r1", "r2", "r3"],
    latest_run_id: "r3",
    hypothesis: "h",
    commit: "2bbf5a3",
    n: 3,
    scores: {},
    primary: null,
    single_seed: false,
    label: over.group_id,
    seed_values: {},
    identical_seeds: false,
    test_interval: null,
    vs_best: null,
    created_by: ["human"],
    usage: null,
    ...over,
  };
}
const stat = (mean: number, std = 0, n = 3) => ({ mean, std, n, ci_low: null, ci_high: null });
const SVM = row({
  group_id: "6f71aa00@8f4cac4",
  latest_run_id: "20260926-6f71",
  hypothesis: "RBF-kernel SVM beats the tree baselines",
  label: "RBF-kernel SVM",
  scores: { "accuracy/value": stat(0.922222), "macro_f1/value": stat(0.9225) },
  primary: stat(0.922222),
  seed_values: { "accuracy/value": [0.922222, 0.922222, 0.922222] },
  identical_seeds: true,
  test_interval: { lo: 0.874, hi: 0.953, method: "wilson", n: 180 },
  created_by: ["agent:acceptance"],
});
const RF = row({
  group_id: "ef4f0000@2bbf5a3",
  label: "Baseline rf",
  scores: { "accuracy/value": stat(0.885185, 0.006415), "macro_f1/value": stat(0.8855, 0.006) },
  primary: stat(0.885185, 0.006415),
  seed_values: { "accuracy/value": [0.877778, 0.888889, 0.888889] },
  test_interval: { lo: 0.83, hi: 0.924, method: "wilson", n: 180 },
  vs_best: { delta: -0.037037, p: 0.146, fixed: 9, broken: 3, test: "sign", examples_needed: 250 },
});
const KNN = row({
  group_id: "3f7e0000@2bbf5a3",
  label: "Baseline knn",
  scores: { "accuracy/value": stat(0.866667), "macro_f1/value": stat(0.8664) },
  primary: stat(0.866667),
  seed_values: { "accuracy/value": [0.866667, 0.866667, 0.866667] },
  identical_seeds: true,
  test_interval: { lo: 0.809, hi: 0.909, method: "wilson", n: 180 },
  vs_best: { delta: -0.055556, p: null, fixed: null, broken: null, test: null, examples_needed: null },
});
const LOGREG = row({
  group_id: "a50e0000@2bbf5a3",
  label: "Baseline logreg",
  scores: { "accuracy/value": stat(0.827778), "macro_f1/value": stat(0.8291) },
  primary: stat(0.827778),
  seed_values: { "accuracy/value": [0.827778, 0.827778, 0.827778] },
  identical_seeds: true,
  test_interval: { lo: 0.766, hi: 0.876, method: "wilson", n: 180 },
  vs_best: { delta: -0.094444, p: null, fixed: null, broken: null, test: null, examples_needed: null },
});
const ROWS = [SVM, RF, KNN, LOGREG];
const board = (meta: Record<string, unknown> = {}, rows = ROWS): PanelResult => ({
  type: "leaderboard",
  title: "All ideas",
  rows: rows as unknown as Array<Record<string, unknown>>,
  meta,
});

describe("helpers", () => {
  test("primaryKey: meta hint, bare metric name, or matching stats", () => {
    expect(primaryKey(ROWS, {})).toBe("accuracy/value");
    expect(primaryKey(ROWS, { primary: "macro_f1/value" })).toBe("macro_f1/value");
    expect(primaryKey(ROWS, { primary: "accuracy" })).toBe("accuracy/value");
    expect(primaryKey([], {})).toBeNull();
  });
  test("metricLabel and fmtDuration", () => {
    expect(metricLabel("accuracy/value")).toBe("accuracy");
    expect(metricLabel("latency/p95")).toBe("latency p95");
    expect(fmtDuration(42.4)).toBe("42s");
    expect(fmtDuration(250)).toBe("4m 10s");
    expect(fmtDuration(3900)).toBe("1h 5m");
  });
  test("bestBand prefers the test interval, then the seed t-interval", () => {
    expect(bestBand(SVM)).toEqual({ lo: 0.874, hi: 0.953, how: "Wilson, n = 180" });
    const seedOnly = { ...SVM, test_interval: null, primary: { mean: 0.9, std: 0.01, n: 3, ci_low: 0.875, ci_high: 0.925 } };
    expect(bestBand(seedOnly)).toEqual({ lo: 0.875, hi: 0.925, how: "t-interval over 3 seeds" });
    expect(bestBand({ ...SVM, test_interval: null })).toBeNull();
    expect(bestBand(null)).toBeNull();
  });
  test("verdictOf: best, inside the band, behind, unscored", () => {
    const band = bestBand(SVM);
    expect(verdictOf(SVM, SVM, band).kind).toBe("best");
    const rf = verdictOf(RF, SVM, band);
    expect(rf.kind).toBe("band");
    expect(rf.text).toBe(`${MINUS}0.037`);
    expect(rf.p).toBe("p 0.15");
    expect(rf.tip).toBe(
      "Mean inside the best's 95% CI: not proven worse. Exact sign test on 12 changed examples (9 fixed / 3 broken), p = 0.15. ≈250 examples for p < 0.05.",
    );
    const knn = verdictOf(KNN, SVM, band);
    expect(knn.kind).toBe("behind");
    expect(knn.text).toBe(`${MINUS}0.056`);
    expect(knn.p).toBe("");
    expect(verdictOf({ ...KNN, primary: null }, SVM, band).kind).toBe("none");
    const welch = verdictOf(
      { ...RF, vs_best: { delta: -0.02, p: 0.0004, fixed: null, broken: null, test: "welch", examples_needed: null } },
      SVM,
      null,
    );
    expect(welch.kind).toBe("behind");
    expect(welch.p).toBe("p < 0.001");
    expect(welch.tip).toBe("No 95% CI for the best group. Welch t-test over seeds, p < 0.001.");
  });
});

describe("Leaderboard panel", () => {
  test("one row per seed group with label, mean, spread, CI, second metric and verdict", () => {
    const { container } = render(<Leaderboard result={board()} />);
    const rows = [...container.querySelectorAll<HTMLElement>(".frow[data-row]")];
    expect(rows.map((r) => r.querySelector(".nm")?.textContent)).toEqual([
      "RBF-kernel SVM",
      "Baseline rf",
      "Baseline knn",
      "Baseline logreg",
    ]);
    expect(rows.map((r) => r.querySelector(".big")?.textContent)).toEqual(["0.9222", "0.8852", "0.8667", "0.8278"]);
    expect(rows.map((r) => r.querySelector(".f1")?.textContent)).toEqual(["0.9225", "0.8855", "0.8664", "0.8291"]);
    expect(rows.map((r) => r.querySelector(".vd")?.textContent)).toEqual([
      "best",
      `${MINUS}0.037p 0.15`,
      `${MINUS}0.056`,
      `${MINUS}0.094`,
    ]);
    expect(rows.map((r) => r.querySelector(".vg")?.getAttribute("class"))).toEqual([
      "vg best",
      "vg band",
      "vg behind",
      "vg behind",
    ]);
    const svm = within(rows[0] as HTMLElement);
    expect(svm.getByTitle("3 seeds, one score: the model ignores the seed").textContent).toBe("×3");
    expect(svm.getByTitle("test-set 95% CI (Wilson, n = 180)").textContent).toBe("0.874–0.953");
    expect(svm.getByTitle("RBF-kernel SVM beats the tree baselines")).toBeTruthy();
    expect(svm.getByText("agent:acceptance").className).toBe("who agent");
    expect(svm.getByText("6f71aa00@8f4cac4").getAttribute("href")).toBe("/r/20260926-6f71");
    expect(within(rows[1] as HTMLElement).getByTitle("std over 3 seeds").textContent).toBe("± 0.0064");
    const head = container.querySelector(".frow.head");
    expect([...(head?.children ?? [])].map((c) => c.textContent)).toEqual([
      "Idea",
      "accuracy",
      "seeds, 95% CI",
      "macro_f1",
      "vs best",
    ]);
  });

  test("plots seeds, diamonds, whiskers and the best band on one shared scale", () => {
    const { container } = render(<Leaderboard result={board()} />);
    const plots = [...container.querySelectorAll(".frow[data-row] .fplot svg")];
    expect(plots.length).toBe(4);
    // SVM: diamond (best) with ×3; rf: three seed dots, two of them stacked.
    expect(plots[0]?.querySelector("path.dia")?.getAttribute("class")).toBe("dia best");
    expect(plots[0]?.querySelector(".identical text")?.textContent).toBe("×3");
    expect([...(plots[1]?.querySelectorAll("circle.seed") ?? [])].map((c) => c.getAttribute("cy"))).toEqual([
      "30",
      "30",
      "22",
    ]);
    for (const p of plots) {
      expect(p.querySelectorAll("path.whisk").length).toBe(1);
      expect(p.querySelectorAll("rect.band").length).toBe(1);
    }
    // Domain: values span 0.766..0.953 -> nice [0.76, 0.96]; range [8, 592] at the 600 px fallback.
    // X(0.874) = 8 + (0.114 / 0.2) * 584 = 340.88; X(0.922222) = 8 + (0.162222 / 0.2) * 584 = 481.689.
    const band = plots[2]?.querySelector("rect.band");
    expect(Number(band?.getAttribute("x"))).toBeCloseTo(340.88, 2);
    expect(Number(plots[2]?.querySelector("line.bestline")?.getAttribute("x1"))).toBeCloseTo(481.689, 2);
    const ticks = [...container.querySelectorAll(".axisrow text.tk")].map((t) => t.textContent);
    expect(ticks.length).toBe(11);
    expect(ticks[0]).toBe("0.76");
    expect(ticks.at(-1)).toBe("0.96");
    expect(container.querySelector(".axisrow text.lbl-s")?.textContent).toBe("accuracy");
    expect([...container.querySelectorAll(".key span")].map((s) => s.textContent)).toEqual([
      "seed",
      "identical seeds",
      "test-set 95% CI",
      "best's CI",
    ]);
  });

  test("hovering an interval shows its exact numbers", () => {
    const { container } = render(<Leaderboard result={board()} />);
    const rfPlot = container.querySelectorAll(".frow[data-row] .fplot svg")[1] as SVGElement;
    const hit = rfPlot.querySelector("path.whisk")?.parentElement as Element;
    fireEvent.mouseEnter(hit, { clientX: 5, clientY: 5 });
    expect(screen.getByRole("tooltip").textContent).toBe(
      "Baseline rf\nmean 0.8852\ntest-set 95% CI 0.8300–0.9240\n(Wilson, n = 180)",
    );
  });

  test("noise: [test_set] hides seed marks; [seed] hides whiskers and CI text", () => {
    const { container, unmount } = render(<Leaderboard result={board({ noise: ["test_set"] })} />);
    expect(container.querySelectorAll(".fplot circle.seed, .fplot path.dia").length).toBe(0);
    expect(container.querySelectorAll(".fplot path.whisk").length).toBe(4);
    expect(container.querySelector(".frow.head")?.children[2]?.textContent).toBe("95% CI");
    unmount();
    const seedsOnly = render(<Leaderboard result={board({ noise: ["seed"] })} />).container;
    expect(seedsOnly.querySelectorAll(".fplot path.whisk").length).toBe(0);
    expect(seedsOnly.querySelectorAll(".fplot circle.seed").length).toBe(3);
    expect(seedsOnly.querySelector(".frow.head")?.children[2]?.textContent).toBe("seeds");
    expect(screen.queryByText("0.874–0.953")).toBeNull();
  });

  test("each scored non-best verdict links to the Examples page against the best run", () => {
    const rf = { ...RF, latest_run_id: "20260926-ef4f" };
    const knn = { ...KNN, latest_run_id: "20260926-3f7e" };
    const unscored = row({ group_id: "b2@c2", label: "unscored", vs_best: null });
    const hrefs = (meta: Record<string, unknown>) => {
      const { container, unmount } = render(<Leaderboard result={board(meta, [SVM, rf, knn, unscored])} />);
      const out = [...container.querySelectorAll(".frow[data-row]")].map(
        (r) => r.querySelector(".vd a")?.getAttribute("href") ?? null,
      );
      unmount();
      return out;
    };
    expect(hrefs({})).toEqual([
      null,
      "/x/20260926-ef4f/20260926-6f71?metric=accuracy",
      "/x/20260926-3f7e/20260926-6f71?metric=accuracy",
      null,
    ]);
    expect(hrefs({ primary: "macro_f1/value" })[1]).toBe("/x/20260926-ef4f/20260926-6f71?metric=macro_f1");
    expect(examplesHref("a b", "c", "solved@v2")).toBe("/x/a%20b/c?metric=solved%40v2");
  });

  test("single seed, missing primary, usage, and the empty state", () => {
    const one = row({
      group_id: "b1@c1",
      label: "one seed",
      run_ids: ["r9"],
      n: 1,
      single_seed: true,
      scores: { "accuracy/value": stat(0.95, 0, 1) },
      primary: stat(0.95, 0, 1),
      seed_values: { "accuracy/value": [0.95] },
      created_by: ["agent:tuner"],
      usage: { tokens_in: 1000, tokens_out: 200, usd: 1.234, seconds: 250, calls: 7 },
    });
    const none = row({ group_id: "b2@c2", label: "unscored", vs_best: null });
    const { container } = render(<Leaderboard result={board({}, [one, none])} />);
    const rows = [...container.querySelectorAll<HTMLElement>(".frow[data-row]")];
    expect(within(rows[0] as HTMLElement).getByTitle("One run: no seed noise estimate").textContent).toBe("single seed");
    expect(within(rows[0] as HTMLElement).getByTitle("7 calls, 1000 tokens in, 200 out").textContent).toBe("$1.23 · 4m 10s");
    expect(rows[1]?.querySelector(".big")?.textContent).toBe("—");
    expect(rows[1]?.querySelector(".vd")?.textContent).toBe("—");
    expect(rows[1]?.querySelectorAll(".fplot rect.mean").length).toBe(0);
    cleanup();
    render(<Leaderboard result={board({}, [])} />);
    expect(screen.getByText("No scored runs yet")).toBeTruthy();
  });
});
```

Append to `ui/test/panels/index.test.tsx`:

```tsx
test("the registry maps leaderboard to Leaderboard", async () => {
  const { Leaderboard } = await import("../../src/panels/Leaderboard");
  expect(panelFor("leaderboard")).toBe(Leaderboard);
  render(<Panel result={{ type: "leaderboard", title: "", rows: [] }} />);
  expect(screen.getByText("No scored runs yet")).toBeTruthy();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `(cd ui && bun test test/panels/Leaderboard.test.tsx test/panels/index.test.tsx)`
Expected: FAIL with `Cannot find module '../../src/panels/Leaderboard'`.

- [ ] **Step 3: Append the leaderboard styles**

Append to `ui/src/panels/panels.css`:

```css
/* leaderboard: one grid row per seed group; the plot column is an SVG per row */
.forest { position: relative; }
.frow {
  display: grid; grid-template-columns: minmax(0, 1fr) 118px minmax(240px, 600px) 64px 128px;
  gap: 0 24px; align-items: start; border-bottom: 1px solid var(--rule-2);
  box-sizing: border-box; height: 105px; padding: 16px 0 14px; /* plot SVG = 105 - 1 border = 104 */
}
.frow.head { height: auto; padding: 0 0 10px; border-bottom: 1px solid var(--rule); font-size: 12.5px; color: var(--ink-3); align-items: end; }
.frow.axisrow { border-bottom: 0; height: 48px; padding: 0; }
.frow .fplot { align-self: stretch; margin: -16px 0 -14px; min-width: 0; }
.frow.axisrow .fplot { margin: 0; }
.frow .nm { font-weight: 600; font-size: 16px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.frow .meta { font-size: 12.5px; color: var(--ink-3); margin-top: 5px; display: flex; flex-direction: column; gap: 2px; }
.frow .acc { text-align: right; }
.frow .big { font: 400 24px/1.05 var(--sans); letter-spacing: -.01em; font-variant-numeric: tabular-nums; }
.frow .sd { font-size: 13px; color: var(--ink-3); margin-top: 5px; font-variant-numeric: tabular-nums; display: flex; justify-content: flex-end; align-items: center; gap: 5px; }
.frow .sd .hint { display: inline-flex; align-items: center; gap: 2px; }
.frow .f1 { text-align: right; font-size: 14.5px; font-variant-numeric: tabular-nums; padding-top: 4px; }
.frow .vd { font-size: 14px; padding-top: 4px; font-variant-numeric: tabular-nums; display: flex; align-items: center; gap: 8px; cursor: help; }
.frow .vd small { color: var(--ink-3); font-size: 12.5px; }
.frow .vd a.vx { color: inherit; text-decoration: none; cursor: pointer; }
.frow .vd a.vx:hover { text-decoration: underline; }
/* .hint and .who come from styles/base.css */
.vg { width: 10px; height: 10px; display: inline-block; flex: none; }
.vg.best { background: var(--best); transform: rotate(45deg) scale(.8); }
.vg.band { background: var(--best-wash); outline: 1px solid var(--best-edge); }
.vg.behind { border: 1.5px solid var(--ink-3); border-radius: 50%; }
```

- [ ] **Step 4: Write the component**

`ui/src/panels/Leaderboard.tsx`:

```tsx
/**
 * `leaderboard` panel: a forest plot with one row per seed group.
 *
 * Shows both kinds of noise: per-seed dots (identical seeds collapse to a diamond
 * with `×n`) and the test-set 95% interval as a whisker. The best group's interval
 * is a band behind every row; the last column says how each row compares to it.
 */
import type { ReactElement } from "react";
import { AxisBottom, GridX } from "../charts/Axis";
import {
  BestBand,
  IdenticalSeeds,
  Key,
  KeyGlyph,
  MeanMark,
  SeedDots,
  Whisker,
  type KeyItem,
} from "../charts/Glyphs";
import {
  f3,
  f4,
  fmtP,
  linear,
  niceDomain,
  signed,
  tickFormat,
  useElementWidth,
  type LinearScale,
} from "../charts/Scale";
import { useTooltip, type Tooltip } from "../charts/Tooltip";
import type { LeaderboardRow, NoiseInterval, Stats, UsageTotals, VersusBest } from "../api/models";
import type { PanelProps } from "./index";

/** `hypothex.core.seeds.Stats` as JSON. */
export type StatsJson = Stats;
/** `hypothex.core.leaderboard.NoiseInterval` as JSON. */
export type NoiseIntervalJson = NoiseInterval;
/** `hypothex.core.leaderboard.VersusBest` as JSON. */
export type VersusBestJson = VersusBest;
/** `hypothex.core.records.UsageTotals` as JSON. */
export type UsageJson = UsageTotals;
/** `hypothex.core.leaderboard.LeaderboardRow` as JSON (the fields this panel reads). */
export type LeaderboardRowJson = Omit<LeaderboardRow, "config_hash" | "within_noise_of_best">;

/** An interval drawn as the best band. */
export interface Band {
  lo: number;
  hi: number;
  /** Tooltip wording of the method, e.g. `Wilson, n = 180`. */
  how: string;
}

/** The vs-best verdict of one row. */
export interface Verdict {
  kind: "best" | "band" | "behind" | "none";
  text: string;
  p: string;
  tip: string;
}

/** Row height in px; the plot SVG of each row is exactly this tall. */
export const ROW_H = 104;
/** y of the seed marks inside a row. */
export const SEED_Y = 30;
/** y of the interval whisker inside a row. */
export const CI_Y = 58;
/** Plot width used before layout is known. */
export const PLOT_FALLBACK_W = 600;
const PAD = 8;

/**
 * Find the score key of the primary metric.
 *
 * Uses `meta.primary` when it names a score key (`accuracy` also matches
 * `accuracy/value`); otherwise the key whose stats equal a row's `primary`.
 */
export function primaryKey(
  rows: LeaderboardRowJson[],
  meta: Record<string, unknown> | undefined,
): string | null {
  const keys = new Set(rows.flatMap((r) => Object.keys(r.scores)));
  const hinted = meta?.primary;
  if (typeof hinted === "string") {
    if (keys.has(hinted)) return hinted;
    if (keys.has(`${hinted}/value`)) return `${hinted}/value`;
  }
  for (const r of rows) {
    const p = r.primary;
    if (!p) continue;
    const hit = Object.entries(r.scores).find(
      ([, s]) => s.mean === p.mean && s.std === p.std && s.n === p.n,
    );
    if (hit) return hit[0];
  }
  return [...keys].sort()[0] ?? null;
}

/**
 * The Examples page comparing run `a` with run `b` on `metric` (`name` or `name@version`);
 * the same URL as `hrefs.examples` (Task 23), built here because panels use plain links.
 */
export function examplesHref(a: string, b: string, metric: string): string {
  return `/x/${encodeURIComponent(a)}/${encodeURIComponent(b)}?metric=${encodeURIComponent(metric)}`;
}

/** Short column label for a score key: `accuracy/value` → `accuracy`, `lat/p95` → `lat p95`. */
export function metricLabel(key: string): string {
  return key.replace(/\/value$/, "").replace("/", " ");
}

/** Compact duration: `42s`, `4m 10s`, `1h 5m`. */
export function fmtDuration(seconds: number): string {
  const s = Math.round(seconds);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

/** The best group's band: its test-set interval, else its seed t-interval. */
export function bestBand(best: LeaderboardRowJson | null): Band | null {
  if (!best) return null;
  const t = best.test_interval;
  if (t) return { lo: t.lo, hi: t.hi, how: `${t.method === "wilson" ? "Wilson" : "bootstrap"}, n = ${t.n}` };
  const p = best.primary;
  if (p && p.ci_low != null && p.ci_high != null) {
    return { lo: p.ci_low, hi: p.ci_high, how: `t-interval over ${p.n} seeds` };
  }
  return null;
}

function testTip(v: VersusBestJson | null): string {
  if (!v || v.p == null) return "";
  const p = v.p < 0.001 ? "p < 0.001" : `p = ${fmtP(v.p)}`;
  let line = `${p}.`;
  if (v.test === "sign") {
    line = `Exact sign test on ${(v.fixed ?? 0) + (v.broken ?? 0)} changed examples (${v.fixed ?? 0} fixed / ${v.broken ?? 0} broken), ${p}.`;
  } else if (v.test === "paired_bootstrap") {
    line = `Paired bootstrap over examples, ${p}.`;
  } else if (v.test === "welch") {
    line = `Welch t-test over seeds, ${p}.`;
  }
  const need = v.examples_needed != null ? ` ≈${v.examples_needed} examples for p < 0.05.` : "";
  return ` ${line}${need}`;
}

/** How a row compares with the best row and its band. */
export function verdictOf(
  row: LeaderboardRowJson,
  best: LeaderboardRowJson | null,
  band: Band | null,
): Verdict {
  if (row === best) {
    return { kind: "best", text: "best", p: "", tip: "Best mean. Its 95% CI is the green band." };
  }
  if (!row.primary || !best?.primary) {
    return { kind: "none", text: "—", p: "", tip: "No score for the primary metric." };
  }
  const m = row.primary.mean;
  const inBand = band !== null && m >= Math.min(band.lo, band.hi) && m <= Math.max(band.lo, band.hi);
  const p = row.vs_best?.p != null ? `p ${fmtP(row.vs_best.p)}` : "";
  const base = band
    ? inBand
      ? "Mean inside the best's 95% CI: not proven worse."
      : "Mean outside the best's 95% CI."
    : "No 95% CI for the best group.";
  return {
    kind: inBand ? "band" : "behind",
    text: signed(m - best.primary.mean, 3),
    p,
    tip: base + testTip(row.vs_best),
  };
}

function Who({ by }: { by: string[] }): ReactElement {
  const first = by[0] ?? "unknown";
  const kind = first.startsWith("agent") ? "agent" : "human";
  return (
    <span className={`who ${kind}`}>
      <i />
      {by.length ? by.join(", ") : "unknown"}
    </span>
  );
}

function SeedSpread({ row }: { row: LeaderboardRowJson }): ReactElement | null {
  const s = row.primary;
  if (!s) return null;
  if (row.identical_seeds) {
    return (
      <span className="hint" title={`${s.n} seeds, one score: the model ignores the seed`}>
        <KeyGlyph kind="identical" />×{s.n}
      </span>
    );
  }
  if (s.n <= 1) {
    return (
      <span className="hint" title="One run: no seed noise estimate">
        single seed
      </span>
    );
  }
  return <span title={`std over ${s.n} seeds`}>± {f4(s.std)}</span>;
}

interface PlotProps {
  row: LeaderboardRowJson;
  pkey: string;
  x: LinearScale;
  width: number;
  band: Band | null;
  best: LeaderboardRowJson | null;
  showSeeds: boolean;
  showTest: boolean;
  tip: Tooltip;
}

function RowPlot({ row, pkey, x, width, band, best, showSeeds, showTest, tip }: PlotProps): ReactElement {
  const s = row.primary;
  const isBest = row === best;
  const seeds = row.seed_values[pkey] ?? [];
  const t = row.test_interval;
  return (
    <svg
      className="hx-chart"
      width={width}
      height={ROW_H}
      role="img"
      aria-label={`${row.label}: ${s ? f4(s.mean) : "no score"}`}
    >
      <GridX x={x.at} ticks={x.ticks} y0={0} y1={ROW_H} />
      {band ? <BestBand x1={x.at(band.lo)} x2={x.at(band.hi)} y0={0} y1={ROW_H} /> : null}
      {best?.primary ? (
        <line
          className="bestline"
          x1={x.at(best.primary.mean)}
          x2={x.at(best.primary.mean)}
          y1={0}
          y2={ROW_H}
        />
      ) : null}
      {s && showSeeds ? (
        <g
          {...tip.bind(
            row.identical_seeds
              ? `${row.label}\n×${s.n}: all seeds gave ${f4(s.mean)}`
              : `${row.label}\nseeds: ${seeds.map(f4).join(", ")}`,
          )}
        >
          {row.identical_seeds ? (
            <IdenticalSeeds cx={x.at(s.mean)} cy={SEED_Y} n={s.n} best={isBest} />
          ) : (
            <SeedDots x={x.at} values={seeds} y={SEED_Y} />
          )}
          <rect className="hit" x={x.at(s.mean) - 40} y={SEED_Y - 14} width={80} height={24} />
        </g>
      ) : null}
      {s && showTest && t ? (
        <g
          {...tip.bind(
            `${row.label}\nmean ${f4(s.mean)}\ntest-set 95% CI ${f4(t.lo)}–${f4(t.hi)}\n(${t.method === "wilson" ? "Wilson" : "bootstrap"}, n = ${t.n})`,
          )}
        >
          <Whisker x1={x.at(t.lo)} x2={x.at(t.hi)} y={CI_Y} best={isBest} />
          <rect
            className="hit"
            x={x.at(t.lo)}
            y={CI_Y - 10}
            width={Math.max(8, x.at(t.hi) - x.at(t.lo))}
            height={20}
          />
        </g>
      ) : null}
      {s ? <MeanMark cx={x.at(s.mean)} cy={CI_Y} best={isBest} /> : null}
    </svg>
  );
}

/** Draw a `leaderboard` panel result. */
export function Leaderboard({ result }: PanelProps): ReactElement {
  const rows = result.rows as unknown as LeaderboardRowJson[];
  const [plotRef, width] = useElementWidth<HTMLDivElement>(PLOT_FALLBACK_W);
  const tip = useTooltip();
  if (rows.length === 0) return <p className="panel-empty">No scored runs yet</p>;

  const meta = result.meta;
  const noise = Array.isArray(meta?.noise) ? (meta.noise as string[]) : ["seed", "test_set"];
  const showSeeds = noise.includes("seed");
  const showTest = noise.includes("test_set");
  const pkey = primaryKey(rows, meta) ?? "";
  const secondKey = [...new Set(rows.flatMap((r) => Object.keys(r.scores)))]
    .sort()
    .find((k) => k !== pkey);
  const best = rows.find((r) => r.primary && r.vs_best == null) ?? null;
  const band = bestBand(best);

  const values: number[] = [];
  for (const r of rows) {
    if (!r.primary) continue;
    values.push(r.primary.mean);
    if (showSeeds) values.push(...(r.seed_values[pkey] ?? []));
    if (showTest && r.test_interval) values.push(r.test_interval.lo, r.test_interval.hi);
  }
  if (band) values.push(band.lo, band.hi);
  const x = linear(niceDomain(values), PAD, width - PAD);
  const plotHead = showSeeds && showTest ? "seeds, 95% CI" : showSeeds ? "seeds" : "95% CI";
  const keyItems: KeyItem[] = [];
  if (showSeeds) {
    keyItems.push({ glyph: "seed", label: "seed" });
    if (rows.some((r) => r.identical_seeds)) {
      keyItems.push({ glyph: "identical", label: "identical seeds", title: "All seeds gave one score" });
    }
  }
  if (showTest && rows.some((r) => r.test_interval)) {
    keyItems.push({ glyph: "whisker", label: "test-set 95% CI" });
  }
  if (band) keyItems.push({ glyph: "band", label: "best's CI", title: band.how });

  return (
    <div className="lb">
      <div className="forest">
        <div className="frow head">
          <div>Idea</div>
          <div className="acc">{metricLabel(pkey)}</div>
          <div ref={plotRef}>{plotHead}</div>
          <div className="f1">{secondKey ? metricLabel(secondKey) : ""}</div>
          <div>vs best</div>
        </div>
        {rows.map((row, i) => {
          const v = verdictOf(row, best, band);
          const s = row.primary;
          const second = secondKey ? row.scores[secondKey] : undefined;
          const u = row.usage;
          return (
            <div className="frow" data-row={i} key={row.group_id}>
              <div>
                <div className="nm" title={row.hypothesis}>
                  {row.label}
                </div>
                <div className="meta">
                  <Who by={row.created_by} />
                  <span>
                    <a href={`/r/${encodeURIComponent(row.latest_run_id)}`}>{row.group_id}</a>
                  </span>
                  {u && (u.usd > 0 || u.seconds > 0) ? (
                    <span title={`${u.calls} calls, ${u.tokens_in} tokens in, ${u.tokens_out} out`}>
                      ${u.usd.toFixed(2)} · {fmtDuration(u.seconds)}
                    </span>
                  ) : null}
                </div>
              </div>
              <div className="acc">
                <div className="big">{s ? f4(s.mean) : "—"}</div>
                <div className="sd">
                  <SeedSpread row={row} />
                </div>
                {showTest && row.test_interval ? (
                  <div className="sd">
                    <span
                      title={`test-set 95% CI (${row.test_interval.method === "wilson" ? "Wilson" : "bootstrap"}, n = ${row.test_interval.n})`}
                    >
                      {f3(row.test_interval.lo)}–{f3(row.test_interval.hi)}
                    </span>
                  </div>
                ) : null}
              </div>
              <div className="fplot">
                <RowPlot
                  row={row}
                  pkey={pkey}
                  x={x}
                  width={width}
                  band={band}
                  best={best}
                  showSeeds={showSeeds}
                  showTest={showTest}
                  tip={tip}
                />
              </div>
              <div className="f1">{second ? f4(second.mean) : ""}</div>
              <div className="vd" title={v.tip}>
                {v.kind === "none" ? null : <span className={`vg ${v.kind}`} />}
                {best && row !== best && s && pkey ? (
                  <a className="vx" href={examplesHref(row.latest_run_id, best.latest_run_id, pkey.split("/")[0] ?? pkey)}>
                    {v.text}
                  </a>
                ) : (
                  <span>{v.text}</span>
                )}
                {v.p ? <small>{v.p}</small> : null}
              </div>
            </div>
          );
        })}
        <div className="frow axisrow">
          <div />
          <div />
          <div className="fplot">
            <svg className="hx-chart" width={width} height={48} aria-hidden="true">
              {band ? <BestBand x1={x.at(band.lo)} x2={x.at(band.hi)} y0={0} y1={8} /> : null}
              <AxisBottom
                x={x.at}
                ticks={x.ticks}
                y={8}
                x0={0}
                x1={width}
                format={tickFormat(x.ticks)}
                label={metricLabel(pkey)}
              />
            </svg>
          </div>
          <div />
          <div />
        </div>
      </div>
      {keyItems.length ? <Key items={keyItems} /> : null}
      {tip.node}
    </div>
  );
}
```

- [ ] **Step 5: Register the panel**

In `ui/src/panels/index.ts` replace

```ts
import { StatStrip } from "./StatStrip";
```

with

```ts
import { Leaderboard } from "./Leaderboard";
import { StatStrip } from "./StatStrip";
```

and replace

```ts
  stat_strip: StatStrip,
};
```

with

```ts
  stat_strip: StatStrip,
  leaderboard: Leaderboard,
};
```

- [ ] **Step 6: Run the tests and the type check**

Run: `(cd ui && bun test test/panels && bunx tsc --noEmit -p .)`
Expected: `18 pass`, `0 fail` (StatStrip 3, index 5, Leaderboard 10); `tsc` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add ui/src/panels/Leaderboard.tsx ui/test/panels/Leaderboard.test.tsx ui/src/panels/index.ts ui/test/panels/index.test.tsx ui/src/panels/panels.css
git commit -m "feat(ui): add leaderboard forest plot with seed and test-set noise"
```

### Task 13: Curves small multiples

**Files:**
- Create: `ui/src/panels/Curves.tsx`
- Modify: `ui/src/panels/index.ts` (register), `ui/test/panels/index.test.tsx` (append a test),
  `ui/src/panels/panels.css` (append curves styles)
- Test: `ui/test/panels/Curves.test.tsx`

**Interfaces:**
- Consumes: Task 8 (`fmtValue kStep linear logScale useElementWidth LinearScale`), Task 9
  (`AxisBottom AxisLeftLabels GridY useTooltip`), Task 10 (`CheckpointMark Key KillMark
  SpikeMark KeyItem`), Task 11 (`PanelProps`), `d3-shape` (`line`, `area`), `d3-array`
  (`bisectCenter`). Rows and meta exactly as contract 1.6 `curves`: rows
  `{run_id, group_id, seed, name, step, value}`, `meta.checkpoints[{run_id, step, value, best}]`,
  `meta.events[{run_id, step, kind}]`, `meta.groups[{group_id, label}]`.
- Produces (`ui/src/panels/Curves.tsx`): `CurvePoint` (alias of `CurvesRow`), `CheckpointJson`, `EventJson`,
  `GroupJson`, `RunSeries`, `Cell`, `RowScale {kind: "log"|"linear"|"lr", domain}`,
  `PlacedCheckpoint`, `CurvesModel`; constants `MAX_COLS = 3`, `LABEL_W = 104`, `COL_GAP = 36`,
  `TITLE_H = 34`, `ROW_H = 116`, `LR_ROW_H = 40`, `ROW_GAP = 16`, `SPIKE_WINDOW = 0.1`; helpers
  `isLr(name)`, `isLoss(name)`, `cellKey(group, name)`, `meanSeries(runs)`,
  `valueAt(points, step)`, `buildCurves(rows, meta): CurvesModel`; component `Curves({result})`;
  registry entry `curves`.
- Behaviour: columns = groups (meta order, unknown groups appended), at most 3 per band, more
  bands below. Rows = metric names in first-seen order, learning-rate names last (drawn as an
  area with `peak <value>`). Losses with positive values use a log scale. Only `best: true`
  checkpoints are drawn, on the row whose series has that exact `(step, value)`, else on the last
  non-loss, non-lr row. `spike` events: dashed red line in every row, spike glyph + step label
  above the first row, red caret with the value when the spiked run leaves the panel. `killed`
  and `failed` events: red cross at the run's last point on every non-lr row.

- [ ] **Step 1: Write the failing test**

`ui/test/panels/Curves.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import {
  Curves,
  buildCurves,
  cellKey,
  isLoss,
  isLr,
  meanSeries,
  valueAt,
  type CheckpointJson,
  type CurvePoint,
} from "../../src/panels/Curves";

afterEach(cleanup);

/*
 * Two groups x two seeds, steps 0..1000 every 100 (mirrors docs/mockups/kinds/training):
 *   train_loss = 0.8 exp(-step / 400) + 0.1 + 0.01 seed
 *   val_top1   = 0.9 - 0.4 exp(-step / 300) + 0.002 seed
 *   lr         = 3e-4 (1 - 0.9 step / 1000)
 * base seed 2 spikes at step 500 (train_loss 3.0, val_top1 0.44);
 * aug seed 2 is killed at step 600 (no points after it).
 */
const loss = (s: number, seed: number) => 0.8 * Math.exp(-s / 400) + 0.1 + 0.01 * seed;
const top1 = (s: number, seed: number) => 0.9 - 0.4 * Math.exp(-s / 300) + 0.002 * seed;
const lr = (s: number) => 3e-4 * (1 - (0.9 * s) / 1000);
const RUNS = [
  { run_id: "b1", group_id: "base", seed: 1, last: 1000 },
  { run_id: "b2", group_id: "base", seed: 2, last: 1000 },
  { run_id: "a1", group_id: "aug", seed: 1, last: 1000 },
  { run_id: "a2", group_id: "aug", seed: 2, last: 600 },
];
function points(): CurvePoint[] {
  const out: CurvePoint[] = [];
  for (const r of RUNS) {
    for (let s = 0; s <= r.last; s += 100) {
      const base = { run_id: r.run_id, group_id: r.group_id, seed: r.seed, step: s };
      out.push({ ...base, name: "lr", value: lr(s) });
      out.push({ ...base, name: "train_loss", value: r.run_id === "b2" && s === 500 ? 3.0 : loss(s, r.seed) });
      out.push({ ...base, name: "val_top1", value: r.run_id === "b2" && s === 500 ? 0.44 : top1(s, r.seed) });
    }
  }
  return out;
}
const CKPTS: CheckpointJson[] = [
  { run_id: "b1", step: 900, value: top1(900, 1), best: true },
  { run_id: "b2", step: 400, value: top1(400, 2), best: true },
  { run_id: "a1", step: 1000, value: top1(1000, 1), best: true },
  { run_id: "a2", step: 600, value: top1(600, 2), best: true },
  { run_id: "a1", step: 500, value: top1(500, 1), best: false },
];
const META = {
  groups: [
    { group_id: "base", label: "base" },
    { group_id: "aug", label: "+aug" },
  ],
  checkpoints: CKPTS,
  events: [
    { run_id: "b2", step: 500, kind: "spike" },
    { run_id: "a2", step: 600, kind: "killed" },
  ],
};
const result = (rows = points(), meta: Record<string, unknown> = META): PanelResult => ({
  type: "curves",
  title: "Curves",
  rows: rows as unknown as Array<Record<string, unknown>>,
  meta,
});

describe("model", () => {
  test("name helpers", () => {
    expect(isLr("lr")).toBe(true);
    expect(isLr("train/lr")).toBe(true);
    expect(isLr("learning_rate")).toBe(true);
    expect(isLr("clr_score")).toBe(false);
    expect(isLoss("val_loss")).toBe(true);
    expect(isLoss("val_top1")).toBe(false);
  });

  test("meanSeries averages runs per step; valueAt holds the last value", () => {
    const m = meanSeries([
      { run_id: "x", seed: 1, points: [[0, 1], [10, 3]] },
      { run_id: "y", seed: 2, points: [[0, 3]] },
    ]);
    expect(m).toEqual([[0, 2], [10, 3]]);
    expect(valueAt(m, 5)).toBe(2);
    expect(valueAt(m, -1)).toBeNull();
  });

  test("groups keep meta order, lr rows go last, cells hold seeds and mean", () => {
    const m = buildCurves(points(), META);
    expect(m.groups.map((g) => g.label)).toEqual(["base", "+aug"]);
    expect(m.names).toEqual(["train_loss", "val_top1", "lr"]);
    expect(m.maxStep).toBe(1000);
    const cell = m.cells.get(cellKey("base", "val_top1"));
    expect(cell?.runs.map((r) => r.run_id)).toEqual(["b1", "b2"]);
    // mean at step 100 = (0.615387 + 0.617387) / 2, with 0.9 - 0.4 exp(-1/3) = 0.613387.
    expect(valueAt(cell?.mean ?? [], 100)).toBeCloseTo(0.616387, 5);
    expect(m.cells.get(cellKey("aug", "train_loss"))?.runs[1]?.points.length).toBe(7);
  });

  test("scales: log for losses, lr from zero, spike window left out", () => {
    const m = buildCurves(points(), META);
    expect(m.scales.train_loss?.kind).toBe("log");
    // Max outside the spike window is step 0, seed 2: 0.8 + 0.1 + 0.02 = 0.92; x 1.1 = 1.012.
    expect(m.scales.train_loss?.domain[1]).toBeCloseTo(1.012, 6);
    expect(m.scales.val_top1?.kind).toBe("linear");
    // Min outside the window is step 0, seed 1: 0.502; span 0.502..0.9007 (a1 at 1000), pad 5%.
    expect(m.scales.val_top1?.domain[0]).toBeGreaterThan(0.44);
    expect(m.scales.lr).toEqual({ kind: "lr", domain: [0, 3e-4] });
  });

  test("best checkpoints land on the matching metric row; events get their group", () => {
    const m = buildCurves(points(), META);
    expect(m.checkpoints.map((c) => [c.run_id, c.name, c.group_id])).toEqual([
      ["b1", "val_top1", "base"],
      ["b2", "val_top1", "base"],
      ["a1", "val_top1", "aug"],
      ["a2", "val_top1", "aug"],
    ]);
    const odd = buildCurves(points(), { ...META, checkpoints: [{ run_id: "b1", step: 950, value: 0.5, best: true }] });
    expect(odd.checkpoints[0]?.name).toBe("val_top1");
    expect(m.events.map((e) => [e.kind, e.group_id])).toEqual([
      ["spike", "base"],
      ["killed", "aug"],
    ]);
  });

  test("groups missing from meta are appended; bad points are skipped", () => {
    const rows = [
      ...points().filter((p) => p.group_id === "base"),
      { run_id: "z1", group_id: "zeta", seed: 1, name: "train_loss", step: 0, value: Number.NaN },
      { run_id: "z1", group_id: "zeta", seed: 1, name: "train_loss", step: 100, value: 0.5 },
    ];
    const m = buildCurves(rows, { groups: [{ group_id: "base", label: "base" }] });
    expect(m.groups.map((g) => g.group_id)).toEqual(["base", "zeta"]);
    expect(m.cells.get(cellKey("zeta", "train_loss"))?.runs[0]?.points).toEqual([[100, 0.5]]);
  });
});

describe("Curves panel", () => {
  test("one column per group; faint seeds, bold mean, lr area", () => {
    const { container } = render(<Curves result={result()} />);
    const cols = [...container.querySelectorAll(".curve-col")];
    expect(cols.map((c) => c.querySelector("text.ttl")?.textContent)).toEqual(["base", "+aug"]);
    expect(container.querySelectorAll(".curves svg.hx-chart[role=img]").length).toBe(1);
    // 4 runs x 2 non-lr metrics; 2 groups x 2 means; one lr area per group.
    expect(container.querySelectorAll("svg[role=img] path.sl").length).toBe(8);
    expect(container.querySelectorAll("svg[role=img] path.ml").length).toBe(4);
    expect(container.querySelectorAll("path.lra").length).toBe(2);
    expect([...container.querySelectorAll("svg[role=img] text.lbl")].map((t) => t.textContent)).toEqual([
      "train_loss",
      "val_top1",
      "lr",
    ]);
    expect(container.querySelector(".curve-cell[data-name=lr] text.lbl-s")?.textContent).toBe("peak 0.0003");
  });

  test("spike, kill, clip carets and best checkpoints are marked", () => {
    const { container } = render(<Curves result={result()} />);
    const chart = container.querySelector("svg[role=img]") as SVGElement;
    const base = chart.querySelector('.curve-col[data-group="base"]') as Element;
    const aug = chart.querySelector('.curve-col[data-group="aug"]') as Element;
    expect(base.querySelectorAll("line.ev").length).toBe(3);
    expect(base.querySelectorAll("path.evg").length).toBe(1);
    expect(base.querySelector(".event.spike text.lbl-s")?.textContent).toBe("500");
    const carets = [...base.querySelectorAll(".clip-caret text")].map((t) => t.textContent);
    expect(carets).toEqual(["3", "0.44"]);
    expect(aug.querySelectorAll("path.m-fail").length).toBe(2);
    expect(aug.querySelectorAll("line.ev").length).toBe(0);
    expect(chart.querySelectorAll("circle.m-best").length).toBe(4);
    expect([...container.querySelectorAll(".key span")].map((s) => s.textContent)).toEqual([
      "seed",
      "mean",
      "best ckpt",
      "spike",
      "killed",
    ]);
  });

  test("hover shows every seed and the mean at the nearest step", () => {
    const { container } = render(<Curves result={result()} />);
    // Fallback width 960: colW = (960 - 104 - 36) / 2 = 410; step 300 sits at 104 + 0.3 * 410 = 227.
    const hit = container.querySelector('rect.hit[data-hit="base"]') as Element;
    fireEvent.mouseMove(hit, { clientX: 229, clientY: 50 });
    const lines = screen.getByRole("tooltip").textContent?.split("\n") ?? [];
    // train_loss at 300: 0.8 exp(-0.75) + 0.11 = 0.487893, + 0.01 = 0.497893, mean 0.492893.
    expect(lines[0]).toBe("base, step 300");
    expect(lines[1]).toBe("train_loss  s1 0.488  s2 0.498  mean 0.493");
    expect(container.querySelector("line.xh")).not.toBeNull();
    fireEvent.mouseLeave(hit);
    expect(screen.queryByRole("tooltip")).toBeNull();
    expect(container.querySelector("line.xh")).toBeNull();
  });

  test("more than three groups wrap into a second band; empty rows show a note", () => {
    const rows = [1, 2, 3, 4].map((i) => ({
      run_id: `r${i}`,
      group_id: `g${i}`,
      seed: 1,
      name: "loss",
      step: 0,
      value: 1,
    }));
    const { container } = render(<Curves result={result(rows, {})} />);
    expect(container.querySelectorAll("svg[role=img]").length).toBe(2);
    cleanup();
    render(<Curves result={result([], {})} />);
    expect(screen.getByText("No metric history yet")).toBeTruthy();
  });
});
```

Append to `ui/test/panels/index.test.tsx`:

```tsx
test("the registry maps curves to Curves", async () => {
  const { Curves } = await import("../../src/panels/Curves");
  expect(panelFor("curves")).toBe(Curves);
  render(<Panel result={{ type: "curves", title: "", rows: [], meta: {} }} />);
  expect(screen.getByText("No metric history yet")).toBeTruthy();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `(cd ui && bun test test/panels/Curves.test.tsx test/panels/index.test.tsx)`
Expected: FAIL with `Cannot find module '../../src/panels/Curves'`.

- [ ] **Step 3: Append the curves styles**

Append to `ui/src/panels/panels.css`:

```css
/* curves: small multiples, one column per group */
.curves { display: flex; flex-direction: column; gap: 28px; }
```

- [ ] **Step 4: Write the component**

`ui/src/panels/Curves.tsx`:

```tsx
/**
 * `curves` panel: small multiples of metric histories.
 *
 * One column per seed group, one row per metric, all on one step axis. Seeds are
 * faint lines, the seed mean is bold. The best checkpoint of each run is a green
 * dot; loss spikes are dashed red lines with a spike glyph, killed or failed runs
 * end in a red cross. Values pushed off the panel by a spike get a red caret with
 * their number.
 */
import { bisectCenter } from "d3-array";
import { area, line } from "d3-shape";
import { useId, useMemo, useState, type MouseEvent, type ReactElement } from "react";
import { AxisBottom, AxisLeftLabels, GridY } from "../charts/Axis";
import { CheckpointMark, Key, KillMark, SpikeMark, type KeyItem } from "../charts/Glyphs";
import {
  fmtValue,
  kStep,
  linear,
  logScale,
  useElementWidth,
  type LinearScale,
} from "../charts/Scale";
import { useTooltip } from "../charts/Tooltip";
import type { CurvesRow } from "../api/models";
import type { PanelProps } from "./index";

/** One `curves` row as sent by the server (contract 1.6). */
export type CurvePoint = CurvesRow;

/** `meta.checkpoints[]`. */
export interface CheckpointJson {
  run_id: string;
  step: number;
  value: number;
  best: boolean;
}

/** `meta.events[]`. */
export interface EventJson {
  run_id: string;
  step: number;
  kind: "spike" | "killed" | "failed";
}

/** `meta.groups[]`. */
export interface GroupJson {
  group_id: string;
  label: string;
}

/** One run's points for one metric, sorted by step. */
export interface RunSeries {
  run_id: string;
  seed: number | null;
  points: Array<[number, number]>;
}

/** One small multiple: a group's runs for one metric plus their mean. */
export interface Cell {
  runs: RunSeries[];
  mean: Array<[number, number]>;
}

/** How a metric row is scaled. */
export interface RowScale {
  kind: "log" | "linear" | "lr";
  domain: [number, number];
}

/** A best checkpoint placed on a metric row. */
export interface PlacedCheckpoint extends CheckpointJson {
  name: string;
  group_id: string;
}

/** Everything the panel draws, computed from the rows and meta. */
export interface CurvesModel {
  groups: GroupJson[];
  names: string[];
  cells: Map<string, Cell>;
  maxStep: number;
  scales: Record<string, RowScale>;
  checkpoints: PlacedCheckpoint[];
  events: Array<EventJson & { group_id: string }>;
}

/** Most columns per band of small multiples. */
export const MAX_COLS = 3;
/** Width of the row-label gutter. */
export const LABEL_W = 104;
/** Gap between columns. */
export const COL_GAP = 36;
/** Height of the column-title strip. */
export const TITLE_H = 34;
/** Height of a metric row, and of the learning-rate row. */
export const ROW_H = 116;
export const LR_ROW_H = 40;
/** Gap between metric rows. */
export const ROW_GAP = 16;
/** Share of the step axis after a spike that is left out of the y-domain. */
export const SPIKE_WINDOW = 0.1;

/** True for learning-rate metric names (`lr`, `learning_rate`, `train/lr`). */
export function isLr(name: string): boolean {
  return /(^|[/_.])lr$|learning_rate$/.test(name);
}

/** True for loss metric names. */
export function isLoss(name: string): boolean {
  return /loss/i.test(name);
}

/** Key of a cell in {@link CurvesModel.cells}. */
export const cellKey = (group: string, name: string): string => `${group}\u0000${name}`;

/** Average the runs at every step where at least one run has a value. */
export function meanSeries(runs: RunSeries[]): Array<[number, number]> {
  const by = new Map<number, number[]>();
  for (const r of runs) {
    for (const [s, v] of r.points) {
      const list = by.get(s);
      if (list) list.push(v);
      else by.set(s, [v]);
    }
  }
  return [...by.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([s, vs]) => [s, vs.reduce((a, b) => a + b, 0) / vs.length]);
}

/** The value in effect at `step`: the last point at or before it, or `null`. */
export function valueAt(points: Array<[number, number]>, step: number): number | null {
  let out: number | null = null;
  for (const [s, v] of points) {
    if (s > step) break;
    out = v;
  }
  return out;
}

function assignName(
  ck: CheckpointJson,
  names: string[],
  byRun: Map<string, Map<string, RunSeries>>,
): string | null {
  const series = byRun.get(ck.run_id);
  for (const name of names) {
    const pts = series?.get(name)?.points ?? [];
    const hit = pts.find(([s, v]) => s === ck.step && Math.abs(v - ck.value) <= 1e-9 * Math.max(1, Math.abs(v)));
    if (hit) return name;
  }
  const plain = names.filter((n) => !isLr(n) && !isLoss(n));
  return plain.at(-1) ?? names.filter((n) => !isLr(n)).at(-1) ?? null;
}

/**
 * Turn `curves` rows and meta into drawable cells, scales, checkpoints, and events.
 *
 * Parameters
 * ----------
 * rows : CurvePoint[]
 *     Metric points, any order.
 * meta : object
 *     `groups`, `checkpoints`, `events` as in the contract; all optional.
 *
 * Returns
 * -------
 * CurvesModel
 *     Groups in `meta.groups` order (unknown groups appended), metric names in
 *     first-seen order with learning-rate rows last, and per-row scales. Points of a
 *     spiked run within {@link SPIKE_WINDOW} of the axis after the spike are left
 *     out of the y-domain so one spike does not flatten every other line.
 */
export function buildCurves(rows: CurvePoint[], meta: Record<string, unknown> | undefined): CurvesModel {
  const metaGroups = Array.isArray(meta?.groups) ? (meta.groups as GroupJson[]) : [];
  const events = Array.isArray(meta?.events) ? (meta.events as EventJson[]) : [];
  const cks = Array.isArray(meta?.checkpoints) ? (meta.checkpoints as CheckpointJson[]) : [];

  const groups: GroupJson[] = [...metaGroups];
  const known = new Set(groups.map((g) => g.group_id));
  const names: string[] = [];
  const runGroup = new Map<string, string>();
  const byRun = new Map<string, Map<string, RunSeries>>();
  let maxStep = 0;
  for (const p of rows) {
    if (!Number.isFinite(p.value) || !Number.isFinite(p.step)) continue;
    if (!known.has(p.group_id)) {
      known.add(p.group_id);
      groups.push({ group_id: p.group_id, label: p.group_id });
    }
    if (!names.includes(p.name)) names.push(p.name);
    runGroup.set(p.run_id, p.group_id);
    let series = byRun.get(p.run_id);
    if (!series) byRun.set(p.run_id, (series = new Map()));
    let rs = series.get(p.name);
    if (!rs) series.set(p.name, (rs = { run_id: p.run_id, seed: p.seed, points: [] }));
    rs.points.push([p.step, p.value]);
    maxStep = Math.max(maxStep, p.step);
  }
  names.sort((a, b) => Number(isLr(a)) - Number(isLr(b)));

  const cells = new Map<string, Cell>();
  for (const series of byRun.values()) {
    for (const [name, rs] of series) {
      rs.points.sort((a, b) => a[0] - b[0]);
      const key = cellKey(runGroup.get(rs.run_id) ?? "", name);
      const cell = cells.get(key);
      if (cell) cell.runs.push(rs);
      else cells.set(key, { runs: [rs], mean: [] });
    }
  }
  for (const cell of cells.values()) {
    cell.runs.sort((a, b) => (a.seed ?? 0) - (b.seed ?? 0) || a.run_id.localeCompare(b.run_id));
    cell.mean = meanSeries(cell.runs);
  }

  const spikes = events.filter((e) => e.kind === "spike");
  const window = SPIKE_WINDOW * maxStep;
  const scales: Record<string, RowScale> = {};
  for (const name of names) {
    const vals: number[] = [];
    for (const [runId, series] of byRun) {
      const own = spikes.filter((e) => e.run_id === runId);
      for (const [s, v] of series.get(name)?.points ?? []) {
        if (own.some((e) => s >= e.step && s <= e.step + window)) continue;
        vals.push(v);
      }
    }
    const lo = vals.length ? Math.min(...vals) : 0;
    const hi = vals.length ? Math.max(...vals) : 1;
    if (isLr(name)) {
      scales[name] = { kind: "lr", domain: [0, hi > 0 ? hi : 1] };
    } else if (isLoss(name) && lo > 0) {
      scales[name] = { kind: "log", domain: [lo * 0.9, hi * 1.1] };
    } else {
      const pad = (hi - lo || Math.abs(hi) || 1) * 0.05;
      scales[name] = { kind: "linear", domain: [lo - pad, hi + pad] };
    }
  }

  const checkpoints: PlacedCheckpoint[] = [];
  for (const ck of cks) {
    if (!ck.best) continue;
    const name = assignName(ck, names, byRun);
    const group = runGroup.get(ck.run_id);
    if (name && group) checkpoints.push({ ...ck, name, group_id: group });
  }
  return {
    groups,
    names,
    cells,
    maxStep,
    scales,
    checkpoints,
    events: events
      .filter((e) => runGroup.has(e.run_id))
      .map((e) => ({ ...e, group_id: runGroup.get(e.run_id) ?? "" })),
  };
}

function yScaleFor(scale: RowScale, top: number, h: number): LinearScale {
  if (scale.kind === "log") return logScale(scale.domain, top + h, top);
  return linear(scale.domain, top + h, top, 3);
}

interface RowGeom {
  name: string;
  top: number;
  h: number;
}

function rowGeometry(names: string[]): { rows: RowGeom[]; bottom: number } {
  let y = TITLE_H;
  const rows = names.map((name) => {
    const h = isLr(name) ? LR_ROW_H : ROW_H;
    const r = { name, top: y, h };
    y += h + ROW_GAP;
    return r;
  });
  return { rows, bottom: y - ROW_GAP };
}

function Caret({ x, y, up, v }: { x: number; y: number; up: boolean; v: number }): ReactElement {
  const d = up
    ? `M${x - 4} ${y + 5}L${x} ${y - 1}L${x + 4} ${y + 5}Z`
    : `M${x - 4} ${y - 5}L${x} ${y + 1}L${x + 4} ${y - 5}Z`;
  return (
    <g className="clip-caret">
      <path className="clipm" d={d} />
      <text className="lbl-s" x={up ? x + 8 : x - 8} y={up ? y + 6 : y - 1} textAnchor={up ? "start" : "end"}>
        {fmtValue(v)}
      </text>
    </g>
  );
}

interface StackProps {
  model: CurvesModel;
  groups: GroupJson[];
  width: number;
  cols: number;
  onHover: (text: string | null, x: number, y: number) => void;
}

function CurveStack({ model, groups, width, cols, onHover }: StackProps): ReactElement {
  const uid = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const [hover, setHover] = useState<{ col: number; step: number } | null>(null);
  const colW = Math.max(40, (width - LABEL_W - COL_GAP * (cols - 1)) / cols);
  const { rows, bottom } = rowGeometry(model.names);
  const H = bottom + 30;
  const xTicks = linear([0, model.maxStep || 1], 0, 1, 4).ticks;

  const columns = groups.map((g, ci) => {
    const x0 = LABEL_W + ci * (colW + COL_GAP);
    const x = linear([0, model.maxStep || 1], x0, x0 + colW, 4);
    const runIds = new Set(
      model.names.flatMap((n) => model.cells.get(cellKey(g.group_id, n))?.runs.map((r) => r.run_id) ?? []),
    );
    const steps = [
      ...new Set(
        model.names.flatMap((n) => model.cells.get(cellKey(g.group_id, n))?.mean.map((p) => p[0]) ?? []),
      ),
    ].sort((a, b) => a - b);
    return { g, ci, x0, x, runIds, steps };
  });

  const tipText = (col: (typeof columns)[number], step: number): string => {
    const lines = [`${col.g.label}, step ${step.toLocaleString("en-US")}`];
    for (const name of model.names) {
      const cell = model.cells.get(cellKey(col.g.group_id, name));
      if (!cell) continue;
      const parts = cell.runs.map((r) => {
        const last = r.points.at(-1);
        const v = last && step <= last[0] ? valueAt(r.points, step) : null;
        return `${r.seed != null ? `s${r.seed}` : r.run_id.slice(-4)} ${v == null ? "—" : fmtValue(v)}`;
      });
      const m = valueAt(cell.mean, step);
      lines.push(`${name}  ${parts.join("  ")}  mean ${m == null ? "—" : fmtValue(m)}`);
    }
    return lines.join("\n");
  };

  const move = (col: (typeof columns)[number], e: MouseEvent<SVGRectElement>): void => {
    const svg = e.currentTarget.closest("svg");
    const left = svg ? svg.getBoundingClientRect().left : 0;
    const raw = col.x.invert(e.clientX - left);
    const step = col.steps[bisectCenter(col.steps, raw)];
    if (step == null) return;
    setHover({ col: col.ci, step });
    onHover(tipText(col, step), e.clientX, e.clientY);
  };

  return (
    <svg
      className="hx-chart"
      width={width}
      height={H}
      role="img"
      aria-label={`${model.names.join(", ")} by step, one column per group`}
    >
      {rows.map((r) => (
        <text key={r.name} className="lbl" x={0} y={r.top + r.h / 2 + 4}>
          {r.name}
        </text>
      ))}
      {columns.map((col) => (
        <g key={col.g.group_id} className="curve-col" data-group={col.g.group_id}>
          <text className="ttl" x={col.x0} y={15}>
            {col.g.label}
          </text>
          {rows.map((r, ri) => {
            const scale = model.scales[r.name] ?? { kind: "linear", domain: [0, 1] };
            const y = yScaleFor(scale, r.top, r.h);
            const cell = model.cells.get(cellKey(col.g.group_id, r.name));
            const clipId = `${uid}-c${col.ci}r${ri}`;
            const path = line<[number, number]>()
              .x((p) => col.x.at(p[0]))
              .y((p) => y.at(p[1]));
            const lrRun = cell?.runs.reduce((a, b) => (b.points.length > a.points.length ? b : a));
            const lrPeak = lrRun ? Math.max(...lrRun.points.map((p) => p[1])) : 0;
            return (
              <g key={r.name} className="curve-cell" data-name={r.name}>
                {scale.kind === "lr" ? null : <GridY y={y.at} ticks={y.ticks} x0={col.x0} x1={col.x0 + colW} />}
                {col.ci === 0 && scale.kind !== "lr" ? (
                  <AxisLeftLabels y={y.at} ticks={y.ticks} x={LABEL_W - 10} format={fmtValue} />
                ) : null}
                <line
                  className={ri === rows.length - 1 ? "axis" : "hair"}
                  x1={col.x0}
                  x2={col.x0 + colW}
                  y1={r.top + r.h}
                  y2={r.top + r.h}
                />
                <clipPath id={clipId}>
                  <rect x={col.x0 - 2} y={r.top - 3} width={colW + 4} height={r.h + 6} />
                </clipPath>
                <g clipPath={`url(#${clipId})`}>
                  {scale.kind === "lr" && lrRun ? (
                    <>
                      <path
                        className="lra"
                        d={
                          area<[number, number]>()
                            .x((p) => col.x.at(p[0]))
                            .y0(y.at(0))
                            .y1((p) => y.at(p[1]))(lrRun.points) ?? ""
                        }
                      />
                      <path className="lrl" d={path(lrRun.points) ?? ""} />
                    </>
                  ) : (
                    <>
                      {cell?.runs.map((rs) => (
                        <path key={rs.run_id} className="sl" data-run={rs.run_id} d={path(rs.points) ?? ""} />
                      ))}
                      {cell ? <path className="ml" d={path(cell.mean) ?? ""} /> : null}
                    </>
                  )}
                </g>
                {scale.kind === "lr" && lrRun ? (
                  <text className="lbl-s" x={col.x0 + colW} y={r.top + 10} textAnchor="end">
                    peak {fmtValue(lrPeak)}
                  </text>
                ) : null}
                {model.events
                  .filter((e) => col.runIds.has(e.run_id))
                  .map((e) => {
                    const rs = cell?.runs.find((x) => x.run_id === e.run_id);
                    if (e.kind === "spike") {
                      const ex = col.x.at(e.step);
                      const after = rs?.points.find((p) => p[0] >= e.step);
                      const vy = after ? y.at(after[1]) : null;
                      return (
                        <g key={`${e.run_id}-${e.step}-${e.kind}`} className="event spike">
                          <line className="ev" x1={ex} x2={ex} y1={r.top} y2={r.top + r.h} />
                          {ri === 0 ? (
                            <>
                              <SpikeMark x={ex - 16} y={r.top - 8} s={0.8} />
                              <text className="lbl-s" x={ex - 26} y={r.top - 4} textAnchor="end">
                                {kStep(e.step)}
                              </text>
                            </>
                          ) : null}
                          {scale.kind !== "lr" && after && vy != null && vy < r.top ? (
                            <Caret x={ex} y={r.top} up v={after[1]} />
                          ) : null}
                          {scale.kind !== "lr" && after && vy != null && vy > r.top + r.h ? (
                            <Caret x={ex} y={r.top + r.h} up={false} v={after[1]} />
                          ) : null}
                        </g>
                      );
                    }
                    const last = rs?.points.at(-1);
                    if (scale.kind === "lr" || !last) return null;
                    const ky = Math.max(r.top, Math.min(r.top + r.h, y.at(last[1])));
                    return <KillMark key={`${e.run_id}-${e.kind}`} x={col.x.at(last[0])} y={ky} />;
                  })}
                {model.checkpoints
                  .filter((c) => c.name === r.name && c.group_id === col.g.group_id)
                  .map((c) => (
                    <CheckpointMark key={`${c.run_id}-${c.step}`} cx={col.x.at(c.step)} cy={y.at(c.value)} best />
                  ))}
              </g>
            );
          })}
          <AxisBottom x={col.x.at} ticks={xTicks} y={bottom} x0={col.x0} x1={col.x0 + colW} format={kStep} />
          {hover?.col === col.ci ? (
            <line className="xh" x1={col.x.at(hover.step)} x2={col.x.at(hover.step)} y1={TITLE_H - 4} y2={bottom} />
          ) : null}
          <rect
            className="hit"
            data-hit={col.g.group_id}
            x={col.x0}
            y={TITLE_H - 4}
            width={colW}
            height={bottom - TITLE_H + 4}
            style={{ cursor: "crosshair" }}
            onMouseMove={(e) => move(col, e)}
            onMouseLeave={() => {
              setHover(null);
              onHover(null, 0, 0);
            }}
          />
        </g>
      ))}
    </svg>
  );
}

/** Draw a `curves` panel result. */
export function Curves({ result }: PanelProps): ReactElement {
  const [ref, width] = useElementWidth<HTMLDivElement>(960);
  const tip = useTooltip();
  const model = useMemo(
    () => buildCurves(result.rows as unknown as CurvePoint[], result.meta),
    [result.rows, result.meta],
  );
  if (model.names.length === 0) {
    return (
      <div ref={ref}>
        <p className="panel-empty">No metric history yet</p>
      </div>
    );
  }
  const cols = Math.min(MAX_COLS, model.groups.length);
  const bands: GroupJson[][] = [];
  for (let i = 0; i < model.groups.length; i += MAX_COLS) bands.push(model.groups.slice(i, i + MAX_COLS));
  const onHover = (text: string | null, x: number, y: number): void => {
    if (text) tip.show(text, x, y);
    else tip.hide();
  };
  const keyItems: KeyItem[] = [
    { glyph: "seedLine", label: "seed" },
    { glyph: "meanLine", label: "mean" },
  ];
  if (model.checkpoints.length) keyItems.push({ glyph: "bestCkpt", label: "best ckpt" });
  if (model.events.some((e) => e.kind === "spike")) {
    keyItems.push({ glyph: "spike", label: "spike", title: "Loss above 5× the median of the previous 20 points" });
  }
  if (model.events.some((e) => e.kind !== "spike")) keyItems.push({ glyph: "killed", label: "killed" });
  return (
    <div className="curves" ref={ref}>
      {bands.map((groups) => (
        <CurveStack
          key={groups.map((g) => g.group_id).join("|")}
          model={model}
          groups={groups}
          width={width}
          cols={cols}
          onHover={onHover}
        />
      ))}
      <Key items={keyItems} />
      {tip.node}
    </div>
  );
}
```

- [ ] **Step 5: Register the panel**

In `ui/src/panels/index.ts` replace

```ts
import { Leaderboard } from "./Leaderboard";
```

with

```ts
import { Curves } from "./Curves";
import { Leaderboard } from "./Leaderboard";
```

and replace

```ts
  leaderboard: Leaderboard,
};
```

with

```ts
  leaderboard: Leaderboard,
  curves: Curves,
};
```

- [ ] **Step 6: Run the whole UI unit suite and the type check**

Run: `(cd ui && bun test test/charts test/panels && bunx tsc --noEmit -p .)`
Expected: `54 pass`, `0 fail` (charts 25; StatStrip 3, index 6, Leaderboard 10, Curves 10);
`tsc` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add ui/src/panels/Curves.tsx ui/test/panels/Curves.test.tsx ui/src/panels/index.ts ui/test/panels/index.test.tsx ui/src/panels/panels.css
git commit -m "feat(ui): add training curves small multiples with checkpoints and events"
```

## Part 3: Data panels (Tasks 14–20)

Scatter, Distribution, Grid, Table, Trace, Markdown and VegaLite panels (contract 4; row shapes in contract 1.6). Each file exports its component by name (`ScatterPanel`, `DistributionPanel`, `GridPanel`, `TablePanel`, `TracePanel`, `MarkdownPanel`, `VegaLitePanel`) and as the default export, and takes `{ result: PanelResult }` from `ui/src/panels/index.ts`. Task 20 registers all seven in `PANELS`.

Conventions in this part:
- A panel renders the figure body only; the page or preview draws the lettered header from `result.title`.
- No CSS files. Styles are inline objects over the design tokens (`var(--ink)` and so on), so light and dark mode need no JavaScript. Only Vega needs concrete colours; it reads the tokens and re-embeds when the colour mode changes (`useTheme`, Task 5).
- SVG charts use a fixed `viewBox` and `width="100%"`, so they need no layout measurement and render the same in happy-dom and the browser.
- Hover text is a native `<title>`. Tests read `<title>` elements directly, because Testing Library's `getByTitle` only finds `svg > title`.
- Row types are aliases of the Task 3 models. `fmtNum` (Table.tsx) formats numbers in these panels; `xAxis`, `xScale`, `logTicks`, `niceLogDomain`, `fmtTick`, `SERIES_LIGHT`, `SERIES_DARK` and `seriesColor` (Distribution.tsx) serve Scatter and VegaLite. The task order respects these imports.
- `meta` keys read beyond contract 1.6 are optional with fallbacks: `scale`, `unit`, `x_label`, `y_label`, `pareto` (`{x, y}` directions), `best_group`. The backend (backend plan Tasks 22–23) sends none of `unit`, `x_label`, `y_label`: scatter gets `meta = {x, y, x_type, scale, pareto}` with the metric or field refs, and distribution gets `{name, scale, render, baseline}`. Contract 1.6 row flags drawn here: scatter `regression` (ordinal x only, Task 18) and distribution `vs_baseline` (the `render: table` percentile table, Task 17). So axis captions fall back to those refs (`meta.x`, `meta.y`, `meta.name`) before the generic `x` and `y`, and each panel has a test with meta in the backend shape.
- The series palette (5 fixed slots, never cycled; the 6th and later series use `--ink-3`) was checked with the dataviz palette validator. Light passes, but its yellow slot is below 3:1 contrast, so every Distribution series is also labelled directly. Dark passes.

### Task 14: Table panel and the shared number formatter

**Files:**
- Create: `ui/src/panels/Table.tsx`
- Test: `ui/test/panels/Table.test.tsx`

**Interfaces:**
- Consumes: `PanelResult` from `ui/src/panels/index.ts` (Task 11; fields `type`, `title`, `rows`, optional `meta`).
- Produces: `TablePanel({ result }): JSX.Element` (default export too); `fmtNum(v: number): string` (grouped integers, 3 decimals in [-1, 1], 3 significant digits below 1000, true minus sign); `fmtCell(v: unknown): string`; `tableColumns(rows): string[]`; `sortRows(rows, key, dir: "asc" | "desc"): Row[]` (missing values last); `MINUS` (re-exported from `charts/Scale`, Task 8), `ROW_CAP = 500`. Rows are any `iter_rows` dicts (contract 1.5/1.6); columns are the union of row keys in first-seen order; a `run_id` cell links to `/r/<run_id>`.

- [ ] **Step 1: Confirm the chart and test dependencies are installed**

Run: `cd ui && bun pm ls | grep -E "d3-scale|d3-shape|@testing-library/react|happy-dom"`
Expected: at least 4 lines, one per package (Task 1 and Task 8 installed them). If one is missing, stop: an earlier task is not merged.

- [ ] **Step 2: Write the failing test**

`ui/test/panels/Table.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import { fmtCell, fmtNum, ROW_CAP, sortRows, TablePanel, tableColumns } from "../../src/panels/Table";

afterEach(cleanup);

const table = (rows: Record<string, unknown>[]): PanelResult => ({
  type: "table",
  title: "Runs",
  rows,
  meta: {},
});

const bodyCells = (container: HTMLElement, col: number): string[] =>
  [...container.querySelectorAll("tbody tr")].map(
    (tr) => tr.querySelectorAll("td")[col]?.textContent ?? "",
  );

describe("fmtNum", () => {
  test("metric values in [0, 1] get three decimals", () => {
    expect(fmtNum(0.6634)).toBe("0.663");
    expect(fmtNum(0.5)).toBe("0.500");
  });

  test("integers are grouped; other values get three significant digits", () => {
    expect(fmtNum(200)).toBe("200");
    expect(fmtNum(12000)).toBe("12,000");
    expect(fmtNum(12.345)).toBe("12.3");
    expect(fmtNum(1234.5)).toBe("1,235");
  });

  test("negatives use a true minus; tiny values keep two significant digits", () => {
    expect(fmtNum(-0.25)).toBe("−0.250");
    expect(fmtNum(0.00012345)).toBe("0.00012");
    expect(fmtNum(Number.NaN)).toBe("NaN");
  });
});

describe("fmtCell", () => {
  test("formats each JSON type", () => {
    expect(fmtCell(null)).toBe("—");
    expect(fmtCell(undefined)).toBe("—");
    expect(fmtCell(true)).toBe("✓");
    expect(fmtCell(false)).toBe("✗");
    expect(fmtCell("finished")).toBe("finished");
    expect(fmtCell({ a: 1 })).toBe('{"a":1}');
    expect(fmtCell(0.9)).toBe("0.900");
  });
});

describe("tableColumns and sortRows", () => {
  test("columns are the union of keys in first-seen order", () => {
    expect(
      tableColumns([
        { run_id: "r1", acc: 0.9 },
        { run_id: "r2", loss: 1.5 },
      ]),
    ).toEqual(["run_id", "acc", "loss"]);
  });

  test("missing values sort last in both directions", () => {
    const rows = [{ acc: 0.9 }, { acc: null }, { acc: 0.7 }, { acc: 0.8 }];
    expect(sortRows(rows, "acc", "asc").map((r) => r.acc)).toEqual([0.7, 0.8, 0.9, null]);
    expect(sortRows(rows, "acc", "desc").map((r) => r.acc)).toEqual([0.9, 0.8, 0.7, null]);
  });

  test("strings sort with numeric awareness", () => {
    const rows = [{ id: "r10" }, { id: "r2" }, { id: "r1" }];
    expect(sortRows(rows, "id", "asc").map((r) => r.id)).toEqual(["r1", "r2", "r10"]);
  });
});

describe("TablePanel", () => {
  const rows = [
    { run_id: "r1", status: "finished", acc: 0.9 },
    { run_id: "r2", status: "failed", acc: null },
    { run_id: "r3", status: "finished", acc: 0.7 },
  ];

  test("renders headers, formatted cells and run links", () => {
    const { container } = render(<TablePanel result={table(rows)} />);
    expect(screen.getByRole("button", { name: "acc" })).toBeTruthy();
    expect(bodyCells(container, 2)).toEqual(["0.900", "—", "0.700"]);
    expect(screen.getByRole("link", { name: "r1" }).getAttribute("href")).toBe("/r/r1");
  });

  test("header clicks cycle ascending, descending, original order", () => {
    const { container } = render(<TablePanel result={table(rows)} />);
    const btn = screen.getByRole("button", { name: "acc" });
    fireEvent.click(btn);
    expect(bodyCells(container, 2)).toEqual(["0.700", "0.900", "—"]);
    expect(btn.closest("th")?.getAttribute("aria-sort")).toBe("ascending");
    fireEvent.click(btn);
    expect(bodyCells(container, 2)).toEqual(["0.900", "0.700", "—"]);
    expect(btn.closest("th")?.getAttribute("aria-sort")).toBe("descending");
    fireEvent.click(btn);
    expect(bodyCells(container, 0)).toEqual(["r1", "r2", "r3"]);
    expect(btn.closest("th")?.getAttribute("aria-sort")).toBe("none");
  });

  test("caps rendered rows and says how many exist", () => {
    const many = Array.from({ length: ROW_CAP + 1 }, (_, i) => ({ i }));
    const { container } = render(<TablePanel result={table(many)} />);
    expect(container.querySelectorAll("tbody tr").length).toBe(ROW_CAP);
    expect(screen.getByText("500 of 501 rows")).toBeTruthy();
  });

  test("empty result says so", () => {
    render(<TablePanel result={table([])} />);
    expect(screen.getByText("No rows")).toBeTruthy();
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd ui && bun test test/panels/Table.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/panels/Table' from '.../ui/test/panels/Table.test.tsx'`.

- [ ] **Step 4: Write the implementation**

`ui/src/panels/Table.tsx`:

```tsx
/**
 * Table panel: one row per source row, one column per field, sortable headers.
 */
import { type CSSProperties, useMemo, useState } from "react";
import { MINUS } from "../charts/Scale";
import type { PanelResult } from "./index";

type Row = Record<string, unknown>;
type SortDir = "asc" | "desc";

/** True minus sign, used for negative numbers (shared with the charts). */
export { MINUS };
/** Rows rendered before the table stops and shows a count. */
export const ROW_CAP = 500;

/**
 * Format a number tersely.
 *
 * Integers are grouped (`12,000`), values in [-1, 1] get three decimals (`0.663`), values
 * below 1000 get three significant digits (`12.3`), larger values are rounded and grouped.
 */
export function fmtNum(v: number): string {
  if (!Number.isFinite(v)) return String(v);
  const a = Math.abs(v);
  let s: string;
  if (Number.isInteger(a)) s = a.toLocaleString("en-US");
  else if (a < 0.001) s = String(Number(a.toPrecision(2)));
  else if (a <= 1) s = a.toFixed(3);
  else if (a < 1000) s = String(Number(a.toPrecision(3)));
  else s = Math.round(a).toLocaleString("en-US");
  return v < 0 ? MINUS + s : s;
}

/** Render any JSON cell value as short text. Missing values become an em dash. */
export function fmtCell(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (typeof v === "number") return fmtNum(v);
  if (typeof v === "boolean") return v ? "✓" : "✗";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

/** Column names: the union of row keys, in order of first appearance. */
export function tableColumns(rows: Row[]): string[] {
  const seen = new Set<string>();
  for (const row of rows) for (const key of Object.keys(row)) seen.add(key);
  return [...seen];
}

function isMissing(v: unknown): boolean {
  return v === null || v === undefined;
}

function compareCells(a: unknown, b: unknown): number {
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), "en", { numeric: true });
}

/** Sort rows by one column. Missing values always sort last. Returns a new array. */
export function sortRows(rows: Row[], key: string, dir: SortDir): Row[] {
  const present = rows.filter((r) => !isMissing(r[key]));
  const missing = rows.filter((r) => isMissing(r[key]));
  const sign = dir === "asc" ? 1 : -1;
  present.sort((a, b) => sign * compareCells(a[key], b[key]));
  return [...present, ...missing];
}

const S = {
  wrap: { overflowX: "auto" },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: 13.5,
    fontVariantNumeric: "tabular-nums",
  },
  th: {
    textAlign: "left",
    fontWeight: 500,
    color: "var(--ink-3)",
    fontSize: 12.5,
    padding: "0 12px 8px 0",
    borderBottom: "1px solid var(--rule)",
    whiteSpace: "nowrap",
  },
  sortBtn: {
    font: "inherit",
    color: "inherit",
    background: "none",
    border: 0,
    padding: 0,
    cursor: "pointer",
  },
  td: {
    padding: "7px 12px 7px 0",
    borderBottom: "1px solid var(--rule-2)",
    maxWidth: "28ch",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  foot: { fontSize: 12.5, color: "var(--ink-3)", margin: "8px 0 0" },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
} satisfies Record<string, CSSProperties>;

/** Table panel. Click a header to sort ascending, again for descending, again to reset. */
export function TablePanel({ result }: { result: PanelResult }) {
  const rows = result.rows as Row[];
  const cols = useMemo(() => tableColumns(rows), [rows]);
  const [sort, setSort] = useState<{ key: string; dir: SortDir } | null>(null);
  const sorted = useMemo(() => (sort ? sortRows(rows, sort.key, sort.dir) : rows), [rows, sort]);
  if (rows.length === 0) return <p style={S.empty}>No rows</p>;

  const numeric = new Set(cols.filter((c) => rows.some((r) => typeof r[c] === "number")));
  const toggle = (key: string) =>
    setSort((s) => {
      if (s?.key !== key) return { key, dir: "asc" };
      return s.dir === "asc" ? { key, dir: "desc" } : null;
    });
  const ariaSort = (key: string) =>
    sort?.key === key ? (sort.dir === "asc" ? "ascending" : "descending") : "none";

  return (
    <div style={S.wrap}>
      <table style={S.table}>
        <thead>
          <tr>
            {cols.map((c) => (
              <th
                key={c}
                aria-sort={ariaSort(c)}
                style={{ ...S.th, textAlign: numeric.has(c) ? "right" : "left" }}
              >
                <button type="button" style={S.sortBtn} onClick={() => toggle(c)}>
                  {c}
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.slice(0, ROW_CAP).map((row, i) => (
            <tr key={i}>
              {cols.map((c) => {
                const v = row[c];
                const text = fmtCell(v);
                const align = typeof v === "number" ? "right" : "left";
                return (
                  <td key={c} title={text} style={{ ...S.td, textAlign: align }}>
                    {c === "run_id" && typeof v === "string" ? (
                      <a href={`/r/${encodeURIComponent(v)}`}>{v}</a>
                    ) : (
                      text
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > ROW_CAP && (
        <p style={S.foot}>
          {fmtNum(ROW_CAP)} of {fmtNum(rows.length)} rows
        </p>
      )}
    </div>
  );
}

export default TablePanel;
```

- [ ] **Step 5: Run the tests and the type check**

Run: `cd ui && bun test test/panels/Table.test.tsx && bunx tsc --noEmit -p .`
Expected: PASS, `11 pass`, `0 fail`; `tsc` prints nothing and exits 0.

- [ ] **Step 6: Commit**

```bash
git add ui/src/panels/Table.tsx ui/test/panels/Table.test.tsx
git commit -m "feat(ui): table panel with sortable columns"
```

### Task 15: Markdown panel (safe subset, no raw HTML)

**Files:**
- Create: `ui/src/panels/Markdown.tsx`
- Test: `ui/test/panels/Markdown.test.tsx`

**Interfaces:**
- Consumes: `PanelResult` from `ui/src/panels/index.ts` (Task 11; fields `type`, `title`, `rows`, optional `meta`). `meta.text: string` (contract 1.6 `markdown`).
- Produces: `MarkdownPanel({ result })` (default export too); `parseBlocks(src: string): Block[]` where `Block = {kind: "p", lines} | {kind: "h", level: 1|2|3, text} | {kind: "ul"|"ol", items} | {kind: "code", text} | {kind: "hr"}`; `safeHref(url: string): string | null`; `renderInline(text: string, key?: string): ReactNode[]`. The panel never uses `dangerouslySetInnerHTML`. React escapes raw HTML, so it shows as text.

- [ ] **Step 1: Write the failing test**

`ui/test/panels/Markdown.test.tsx`:

````tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import { MarkdownPanel, parseBlocks, safeHref } from "../../src/panels/Markdown";

afterEach(cleanup);

const md = (text: string): PanelResult => ({
  type: "markdown",
  title: "Note",
  rows: [],
  meta: { text },
});

describe("parseBlocks", () => {
  test("splits paragraphs, headings, lists, code and rules", () => {
    const src = "# Title\nline one\nline two\n\n- a\n- b\n\n1. x\n2. y\n\n```\ncode\n```\n---";
    expect(parseBlocks(src)).toEqual([
      { kind: "h", level: 1, text: "Title" },
      { kind: "p", lines: ["line one", "line two"] },
      { kind: "ul", items: ["a", "b"] },
      { kind: "ol", items: ["x", "y"] },
      { kind: "code", text: "code" },
      { kind: "hr" },
    ]);
  });

  test("an unclosed fence runs to the end", () => {
    expect(parseBlocks("```\na\nb")).toEqual([{ kind: "code", text: "a\nb" }]);
  });
});

describe("safeHref", () => {
  test("keeps web, mail, relative and anchor links", () => {
    expect(safeHref("https://example.com/x")).toBe("https://example.com/x");
    expect(safeHref("mailto:a@b.c")).toBe("mailto:a@b.c");
    expect(safeHref("/r/abc")).toBe("/r/abc");
    expect(safeHref("#sec")).toBe("#sec");
  });

  test("drops script, data and protocol-relative links", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("JavaScript:alert(1)")).toBeNull();
    expect(safeHref("data:text/html,<b>x</b>")).toBeNull();
    expect(safeHref("//evil.example")).toBeNull();
  });
});

describe("MarkdownPanel", () => {
  test("renders the mockup note: bold value and two lines", () => {
    const text =
      "Critic gain is largest on 5+ step targets: **+0.05**.\nNext: mcts-256+critic, 3 seeds.";
    const { container } = render(<MarkdownPanel result={md(text)} />);
    expect(container.querySelector("b")?.textContent).toBe("+0.05");
    const p = container.querySelector("p");
    expect(p?.querySelectorAll("br").length).toBe(1);
    expect(p?.textContent).toBe(
      "Critic gain is largest on 5+ step targets: +0.05.Next: mcts-256+critic, 3 seeds.",
    );
  });

  test("inline code, italic and lists render as elements", () => {
    const { container } = render(<MarkdownPanel result={md("use `hx view` *now*\n\n- a\n- b")} />);
    expect(container.querySelector("code")?.textContent).toBe("hx view");
    expect(container.querySelector("i")?.textContent).toBe("now");
    expect(container.querySelectorAll("ul li").length).toBe(2);
  });

  test("raw HTML shows as text and never becomes elements", () => {
    const text = '<script>alert(1)</script>\n<img src=x onerror="alert(1)">';
    const { container } = render(<MarkdownPanel result={md(text)} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<script>alert(1)</script>");
  });

  test("code fences keep HTML as literal text", () => {
    const { container } = render(<MarkdownPanel result={md("```\n<b>x</b>\n```")} />);
    expect(container.querySelector("pre code")?.textContent).toBe("<b>x</b>");
    expect(container.querySelector("b")).toBeNull();
  });

  test("links: external opens a new tab, relative stays, unsafe loses its anchor", () => {
    const text = "[docs](https://example.com) [run](/r/abc) [bad](javascript:alert)";
    const { container } = render(<MarkdownPanel result={md(text)} />);
    const docs = screen.getByRole("link", { name: "docs" });
    expect(docs.getAttribute("href")).toBe("https://example.com");
    expect(docs.getAttribute("target")).toBe("_blank");
    expect(docs.getAttribute("rel")).toBe("noreferrer noopener");
    expect(screen.getByRole("link", { name: "run" }).getAttribute("target")).toBeNull();
    expect(screen.queryByRole("link", { name: "bad" })).toBeNull();
    expect(container.textContent).toContain("bad");
    for (const a of container.querySelectorAll("a")) {
      expect(a.getAttribute("href") ?? "").not.toContain("javascript");
    }
  });

  test("missing text says so", () => {
    render(<MarkdownPanel result={{ type: "markdown", title: "Note", rows: [], meta: {} }} />);
    expect(screen.getByText("No text")).toBeTruthy();
  });
});
````

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/panels/Markdown.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/panels/Markdown' from '.../ui/test/panels/Markdown.test.tsx'`.

- [ ] **Step 3: Write the implementation**

`ui/src/panels/Markdown.tsx`:

````tsx
/**
 * Markdown panel: a small, safe Markdown subset rendered as React elements.
 *
 * Supported: paragraphs (single newlines become line breaks), `#`-`###` headings, `-`/`*`
 * and `1.` lists, fenced code, `---` rules, `**bold**`, `*italic*`, `` `code` `` and
 * `[text](url)` links. Raw HTML is never interpreted: React escapes it, so it shows as text.
 * Links keep only http(s), mailto, relative and `#` targets.
 */
import type { CSSProperties, ReactNode } from "react";
import type { PanelResult } from "./index";

/** One parsed block of Markdown. */
export type Block =
  | { kind: "p"; lines: string[] }
  | { kind: "h"; level: 1 | 2 | 3; text: string }
  | { kind: "ul" | "ol"; items: string[] }
  | { kind: "code"; text: string }
  | { kind: "hr" };

const FENCE = /^\s*```/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const RULE = /^\s*(-{3,}|\*{3,})\s*$/;
const LIST = { ul: /^\s*[-*+]\s+(.*)$/, ol: /^\s*\d+[.)]\s+(.*)$/ } as const;

function isBlockStart(line: string): boolean {
  return (
    FENCE.test(line) ||
    HEADING.test(line) ||
    RULE.test(line) ||
    LIST.ul.test(line) ||
    LIST.ol.test(line)
  );
}

/** Split Markdown source into blocks. */
export function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, "\n").split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (line.trim() === "") {
      i++;
      continue;
    }
    if (FENCE.test(line)) {
      const body: string[] = [];
      i++;
      while (i < lines.length && !FENCE.test(lines[i])) body.push(lines[i++]);
      i++;
      out.push({ kind: "code", text: body.join("\n") });
      continue;
    }
    const h = HEADING.exec(line);
    if (h) {
      out.push({ kind: "h", level: Math.min(h[1].length, 3) as 1 | 2 | 3, text: h[2].trim() });
      i++;
      continue;
    }
    if (RULE.test(line)) {
      out.push({ kind: "hr" });
      i++;
      continue;
    }
    const kind = LIST.ul.test(line) ? "ul" : LIST.ol.test(line) ? "ol" : null;
    if (kind) {
      const items: string[] = [];
      while (i < lines.length) {
        const m = LIST[kind].exec(lines[i]);
        if (!m) break;
        items.push(m[1]);
        i++;
      }
      out.push({ kind, items });
      continue;
    }
    const para: string[] = [];
    while (i < lines.length && lines[i].trim() !== "" && !isBlockStart(lines[i])) {
      para.push(lines[i].trim());
      i++;
    }
    out.push({ kind: "p", lines: para });
  }
  return out;
}

/** Return a link target if it is safe to render, else `null`. */
export function safeHref(url: string): string | null {
  const u = url.trim();
  if (/^(https?:|mailto:)/i.test(u)) return u;
  if (/^[a-z][a-z0-9+.-]*:/i.test(u)) return null;
  if (u.startsWith("//")) return null;
  return u;
}

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\[[^\]\n]+\]\([^)\s]+\))|(\*[^*\s][^*\n]*\*)/;
const LINK = /^\[([^\]]+)\]\(([^)\s]+)\)$/;

const S = {
  notes: {
    font: "400 17px/1.6 var(--serif)",
    color: "var(--ink-2)",
    textWrap: "pretty",
  },
  p: { margin: "0 0 8px" },
  h: { font: "600 16px/1.3 var(--sans)", color: "var(--ink)", margin: "12px 0 6px" },
  b: { color: "var(--ink)", fontWeight: 650 },
  code: {
    fontFamily: "var(--mono)",
    fontSize: ".86em",
    background: "var(--paper-2)",
    borderRadius: 3,
    padding: "1px 4px",
  },
  pre: {
    font: "400 13px/1.6 var(--mono)",
    color: "var(--ink)",
    background: "var(--paper-2)",
    borderRadius: 6,
    padding: "10px 12px",
    margin: "0 0 8px",
    whiteSpace: "pre-wrap",
  },
  list: { margin: "0 0 8px", paddingLeft: 22 },
  hr: { border: 0, borderTop: "1px solid var(--rule)", margin: "12px 0" },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
} satisfies Record<string, CSSProperties>;

/** Render inline Markdown (code, bold, italic, links) as React nodes. */
export function renderInline(text: string, key = "i"): ReactNode[] {
  const out: ReactNode[] = [];
  let rest = text;
  let n = 0;
  while (rest) {
    const m = INLINE.exec(rest);
    if (!m) {
      out.push(rest);
      break;
    }
    if (m.index > 0) out.push(rest.slice(0, m.index));
    const tok = m[0];
    const k = `${key}.${n++}`;
    if (m[1]) {
      out.push(
        <code key={k} style={S.code}>
          {tok.slice(1, -1)}
        </code>,
      );
    } else if (m[2]) {
      out.push(
        <b key={k} style={S.b}>
          {renderInline(tok.slice(2, -2), k)}
        </b>,
      );
    } else if (m[3]) {
      const lm = LINK.exec(tok);
      const href = lm ? safeHref(lm[2]) : null;
      const inner = renderInline(lm ? lm[1] : tok, k);
      if (href === null) out.push(<span key={k}>{inner}</span>);
      else if (/^https?:/i.test(href)) {
        out.push(
          <a key={k} href={href} target="_blank" rel="noreferrer noopener">
            {inner}
          </a>,
        );
      } else
        out.push(
          <a key={k} href={href}>
            {inner}
          </a>,
        );
    } else {
      out.push(<i key={k}>{renderInline(tok.slice(1, -1), k)}</i>);
    }
    rest = rest.slice(m.index + tok.length);
  }
  return out;
}

function renderBlock(b: Block, i: number): ReactNode {
  const k = String(i);
  switch (b.kind) {
    case "p":
      return (
        <p key={k} style={S.p}>
          {b.lines.flatMap((line, j) => {
            const inline = renderInline(line, `${k}.${j}`);
            return j === 0 ? inline : [<br key={`${k}.br${j}`} />, ...inline];
          })}
        </p>
      );
    case "h": {
      const Tag = (["h3", "h4", "h5"] as const)[b.level - 1];
      return (
        <Tag key={k} style={S.h}>
          {renderInline(b.text, k)}
        </Tag>
      );
    }
    case "ul":
    case "ol": {
      const Tag = b.kind;
      return (
        <Tag key={k} style={S.list}>
          {b.items.map((item, j) => (
            <li key={j}>{renderInline(item, `${k}.${j}`)}</li>
          ))}
        </Tag>
      );
    }
    case "code":
      return (
        <pre key={k} style={S.pre}>
          <code>{b.text}</code>
        </pre>
      );
    case "hr":
      return <hr key={k} style={S.hr} />;
  }
}

/** Markdown panel. Reads `result.meta.text`. */
export function MarkdownPanel({ result }: { result: PanelResult }) {
  const meta = (result.meta ?? {}) as Record<string, unknown>;
  const text = typeof meta.text === "string" ? meta.text : "";
  if (!text.trim()) return <p style={S.empty}>No text</p>;
  return (
    <div className="notes" style={S.notes}>
      {parseBlocks(text).map(renderBlock)}
    </div>
  );
}

export default MarkdownPanel;
````

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && bun test test/panels/Markdown.test.tsx && bunx tsc --noEmit -p .`
Expected: PASS, `10 pass`, `0 fail`; `tsc` prints nothing and exits 0.

- [ ] **Step 5: Commit**

```bash
git add ui/src/panels/Markdown.tsx ui/test/panels/Markdown.test.tsx
git commit -m "feat(ui): markdown panel rendering a safe subset"
```

### Task 16: Trace panel (step list, failing turn marked)

**Files:**
- Create: `ui/src/panels/Trace.tsx`
- Test: `ui/test/panels/Trace.test.tsx`

**Interfaces:**
- Consumes: `PanelResult` from `ui/src/panels/index.ts` (Task 11; fields `type`, `title`, `rows`, optional `meta`). Rows `{turn, tool, args, result, tokens_in, tokens_out, seconds, error}`; `meta.run_id`, `meta.example_id`, `meta.failed_turn` (contract 1.6 `trace`).
- Produces: `TracePanel({ result })` (default export too); `TraceStep` (alias of `TraceRow`); `kTok(v: number): string` (`250`, `1.2k`, `15k`, `2.50M`); `shortText(v: unknown, max = 120): string`; `BAR_MAX = 56`. Rows carry `data-turn`, `data-failed`, `data-warn`. The failing turn has a fail-wash background, a 3px fail rule and fail-coloured result. Earlier errors get a `!` warning mark. The footer sums turns, tokens and seconds.

- [ ] **Step 1: Write the failing test**

`ui/test/panels/Trace.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import { kTok, shortText, TracePanel } from "../../src/panels/Trace";

afterEach(cleanup);

const STEPS = [
  {
    turn: 1,
    tool: "search",
    args: { smiles: "CCO" },
    result: "12 hits",
    tokens_in: 1200,
    tokens_out: 50,
    seconds: 1.2,
    error: null,
  },
  {
    turn: 2,
    tool: "expand",
    args: { node: 3 },
    result: null,
    tokens_in: 3400,
    tokens_out: 80,
    seconds: 2.5,
    error: "tool timeout",
  },
  {
    turn: 3,
    tool: "expand",
    args: { node: 3 },
    result: null,
    tokens_in: 15000,
    tokens_out: 120,
    seconds: 4.0,
    error: "loop detector: 3rd identical call",
  },
];

const trace = (rows: Record<string, unknown>[], meta: Record<string, unknown>): PanelResult => ({
  type: "trace",
  title: "Attempt",
  rows,
  meta,
});

const row = (c: HTMLElement, turn: number) =>
  c.querySelector(`tbody tr[data-turn="${turn}"]`) as HTMLElement;

describe("kTok and shortText", () => {
  test("token counts are short", () => {
    expect(kTok(250)).toBe("250");
    expect(kTok(1200)).toBe("1.2k");
    expect(kTok(15000)).toBe("15k");
    expect(kTok(19600)).toBe("20k");
    expect(kTok(2_500_000)).toBe("2.50M");
  });

  test("JSON values are one line and cut with an ellipsis", () => {
    expect(shortText({ smiles: "CCO" })).toBe('{"smiles":"CCO"}');
    expect(shortText("x".repeat(200), 10)).toBe(`${"x".repeat(9)}…`);
    expect(shortText(null)).toBe("");
  });
});

describe("TracePanel", () => {
  const meta = { run_id: "r-abc", example_id: "t042", failed_turn: 3 };

  test("marks the failing turn and flags earlier errors as warnings", () => {
    const { container } = render(<TracePanel result={trace(STEPS, meta)} />);
    expect(container.querySelectorAll("tbody tr").length).toBe(3);
    expect(row(container, 3).dataset.failed).toBe("true");
    expect(row(container, 1).dataset.failed).toBe("false");
    expect(row(container, 2).dataset.warn).toBe("true");
    expect(row(container, 3).dataset.warn).toBe("false");
    expect(row(container, 3).textContent).toContain("loop detector: 3rd identical call");
    expect(row(container, 2).textContent).toContain("tool timeout");
    expect(row(container, 1).textContent).toContain('{"smiles":"CCO"}');
    expect(row(container, 1).textContent).toContain("12 hits");
  });

  test("footer sums turns, tokens and seconds", () => {
    render(<TracePanel result={trace(STEPS, meta)} />);
    expect(screen.getByTestId("turns").textContent).toBe("3");
    expect(screen.getByTestId("sum-in").textContent).toBe("20k");
    expect(screen.getByTestId("sum-out").textContent).toBe("250");
    expect(screen.getByTestId("sum-s").textContent).toBe("7.7");
  });

  test("seconds bars scale to the slowest turn", () => {
    render(<TracePanel result={trace(STEPS, meta)} />);
    const widths = screen.getAllByTestId("sbar").map((el) => el.style.width);
    expect(widths).toEqual(["17px", "35px", "56px"]);
  });

  test("caption links the run and names the failing turn", () => {
    render(<TracePanel result={trace(STEPS, meta)} />);
    expect(screen.getByRole("link", { name: "r-abc" }).getAttribute("href")).toBe("/r/r-abc");
    expect(screen.getByText(/failed at turn 3/)).toBeTruthy();
  });

  test("without failed_turn no row is marked failed", () => {
    const { container } = render(<TracePanel result={trace(STEPS, { run_id: "r-abc" })} />);
    expect(container.querySelectorAll('tr[data-failed="true"]').length).toBe(0);
  });

  test("empty trace says so", () => {
    render(<TracePanel result={trace([], {})} />);
    expect(screen.getByText("No trace")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/panels/Trace.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/panels/Trace' from '.../ui/test/panels/Trace.test.tsx'`.

- [ ] **Step 3: Write the implementation**

`ui/src/panels/Trace.tsx`:

```tsx
/**
 * Trace panel: the step list of one agent attempt, with the failing turn marked.
 */
import type { CSSProperties } from "react";
import type { TraceRow } from "../api/models";
import type { PanelResult } from "./index";

/** One trace step, as returned by the query engine (contract 1.6). */
export type TraceStep = TraceRow;

/** Width in px of the longest seconds bar. */
export const BAR_MAX = 56;

/** Format a token count: `250`, `1.2k`, `15k`, `2.50M`. */
export function kTok(v: number): string {
  if (v < 1000) return String(Math.round(v));
  if (v < 1e4) return `${(v / 1000).toFixed(1)}k`;
  if (v < 1e6) return `${Math.round(v / 1000)}k`;
  return `${(v / 1e6).toFixed(2)}M`;
}

/** Render a JSON value as one line, cut to `max` characters with an ellipsis. */
export function shortText(v: unknown, max = 120): string {
  if (v === null || v === undefined) return "";
  const s = typeof v === "string" ? v : JSON.stringify(v);
  return s.length > max ? `${s.slice(0, max - 1)}…` : s;
}

function fullText(v: unknown): string {
  if (v === null || v === undefined) return "";
  return typeof v === "string" ? v : JSON.stringify(v, null, 2);
}

const FAIL_WASH = "color-mix(in srgb, var(--fail) 8%, transparent)";

const S = {
  cap: { fontSize: 12.5, color: "var(--ink-3)", margin: "0 0 10px" },
  capFail: { color: "var(--fail)" },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontSize: 13.5,
    fontVariantNumeric: "tabular-nums",
  },
  th: {
    textAlign: "left",
    fontWeight: 500,
    color: "var(--ink-3)",
    fontSize: 12.5,
    padding: "0 10px 8px 0",
    borderBottom: "1px solid var(--rule)",
    whiteSpace: "nowrap",
  },
  td: {
    padding: "7px 10px 7px 0",
    borderBottom: "1px solid var(--rule-2)",
    verticalAlign: "middle",
    whiteSpace: "nowrap",
  },
  n: { color: "var(--ink-3)", width: 34, paddingLeft: 8 },
  tool: { fontFamily: "var(--mono)", fontSize: 12.5, color: "var(--ink)" },
  args: {
    fontFamily: "var(--mono)",
    fontSize: 12,
    color: "var(--ink-2)",
    maxWidth: 0,
    width: "36%",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  res: {
    color: "var(--ink-2)",
    maxWidth: 0,
    width: "30%",
    overflow: "hidden",
    textOverflow: "ellipsis",
  },
  r: { textAlign: "right" },
  msb: { display: "flex", alignItems: "center", gap: 8, justifyContent: "flex-end" },
  bar: { display: "block", height: 6, borderRadius: "0 3px 3px 0" },
  warn: { color: "var(--human)", fontWeight: 700, marginLeft: 4 },
  foot: { color: "var(--ink-3)", fontSize: 12.5, paddingTop: 10 },
  b: { color: "var(--ink)", fontWeight: 500 },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
} satisfies Record<string, CSSProperties>;

/** Trace panel. Reads `meta.run_id`, `meta.example_id` and `meta.failed_turn`. */
export function TracePanel({ result }: { result: PanelResult }) {
  const steps = result.rows as unknown as TraceStep[];
  const meta = (result.meta ?? {}) as Record<string, unknown>;
  const failedTurn = typeof meta.failed_turn === "number" ? meta.failed_turn : null;
  const runId = typeof meta.run_id === "string" ? meta.run_id : null;
  const exampleId = typeof meta.example_id === "string" ? meta.example_id : null;
  if (steps.length === 0) return <p style={S.empty}>No trace</p>;

  const maxS = Math.max(0, ...steps.map((s) => s.seconds ?? 0));
  const sum = (key: "tokens_in" | "tokens_out" | "seconds") =>
    steps.reduce((acc, s) => acc + (s[key] ?? 0), 0);

  return (
    <div>
      <p style={S.cap}>
        {runId && <a href={`/r/${encodeURIComponent(runId)}`}>{runId}</a>}
        {exampleId && <span> · {exampleId}</span>}
        {failedTurn !== null && <span style={S.capFail}> · failed at turn {failedTurn}</span>}
      </p>
      <table style={S.table} aria-label="Trajectory">
        <thead>
          <tr>
            <th style={{ ...S.th, ...S.n }}>#</th>
            <th style={S.th}>tool</th>
            <th style={S.th}>args</th>
            <th style={S.th}>result</th>
            <th style={{ ...S.th, ...S.r }} title="tokens in">
              in
            </th>
            <th style={{ ...S.th, ...S.r }} title="tokens out">
              out
            </th>
            <th style={{ ...S.th, ...S.r }} title="seconds">
              s
            </th>
          </tr>
        </thead>
        <tbody>
          {steps.map((s) => {
            const failed = s.turn === failedTurn;
            const warn = !failed && Boolean(s.error);
            const shown = s.error ?? s.result;
            const td: CSSProperties = failed ? { ...S.td, background: FAIL_WASH } : S.td;
            const bar = maxS > 0 ? Math.round(((s.seconds ?? 0) / maxS) * BAR_MAX) : 0;
            return (
              <tr
                key={s.turn}
                data-turn={s.turn}
                data-failed={failed ? "true" : "false"}
                data-warn={warn ? "true" : "false"}
                title={s.error ?? undefined}
              >
                <td
                  style={{
                    ...td,
                    ...S.n,
                    ...(failed
                      ? {
                          color: "var(--fail)",
                          fontWeight: 600,
                          boxShadow: "inset 3px 0 0 var(--fail)",
                        }
                      : {}),
                  }}
                >
                  {s.turn}
                  {warn && <span style={S.warn}>!</span>}
                </td>
                <td style={{ ...td, ...S.tool }}>{s.tool}</td>
                <td style={{ ...td, ...S.args }} title={fullText(s.args)}>
                  {shortText(s.args)}
                </td>
                <td
                  style={{
                    ...td,
                    ...S.res,
                    ...(failed ? { color: "var(--fail)", fontWeight: 600 } : {}),
                    ...(warn ? { color: "var(--ink)" } : {}),
                  }}
                  title={fullText(shown)}
                >
                  {shortText(shown)}
                </td>
                <td style={{ ...td, ...S.r }}>{s.tokens_in === null ? "" : kTok(s.tokens_in)}</td>
                <td style={{ ...td, ...S.r }}>{s.tokens_out === null ? "" : kTok(s.tokens_out)}</td>
                <td style={{ ...td, width: 132 }}>
                  <span style={S.msb}>
                    <i
                      data-testid="sbar"
                      style={{
                        ...S.bar,
                        width: bar,
                        background: failed ? "var(--fail)" : "var(--ink-3)",
                        opacity: failed ? 1 : 0.55,
                      }}
                    />
                    {s.seconds === null ? "" : s.seconds.toFixed(1)}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr>
            <td style={S.foot} />
            <td style={S.foot}>
              <b style={S.b} data-testid="turns">
                {steps.length}
              </b>{" "}
              turns
            </td>
            <td style={S.foot} />
            <td style={S.foot} />
            <td style={{ ...S.foot, ...S.r }}>
              <b style={S.b} data-testid="sum-in">
                {kTok(sum("tokens_in"))}
              </b>
            </td>
            <td style={{ ...S.foot, ...S.r }}>
              <b style={S.b} data-testid="sum-out">
                {kTok(sum("tokens_out"))}
              </b>
            </td>
            <td style={{ ...S.foot, ...S.r }}>
              <b style={S.b} data-testid="sum-s">
                {sum("seconds").toFixed(1)}
              </b>{" "}
              s
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export default TracePanel;
```

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && bun test test/panels/Trace.test.tsx && bunx tsc --noEmit -p .`
Expected: PASS, `8 pass`, `0 fail`; `tsc` prints nothing and exits 0.

- [ ] **Step 5: Commit**

```bash
git add ui/src/panels/Trace.tsx ui/test/panels/Trace.test.tsx
git commit -m "feat(ui): trace panel with failing turn highlighted"
```

### Task 17: Distribution panel (ECDF, p50/p95/p99 ticks, log scale, percentile table)

**Files:**
- Create: `ui/src/panels/Distribution.tsx`
- Test: `ui/test/panels/Distribution.test.tsx`

**Interfaces:**
- Consumes: `PanelResult` from `ui/src/panels/index.ts` (Task 11; fields `type`, `title`, `rows`, optional `meta`); `fmtNum` from `./Table` (Task 14). Rows `{group_id, label, n, p50, p95, p99, ecdf: [[x, y], ...], seeds: [{run_id, p50, p95, p99}], vs_baseline: {p50: [delta_rel, lo, hi], p95, p99} | null}` (contract 1.6 `distribution`); optional `meta.scale` (default `"log"`), `meta.unit`, `meta.x_label`, `meta.name`, `meta.render` (`"table"` draws the percentile table), `meta.baseline` (the baseline row's `group_id`) (the backend's meta is `{name, scale, render, baseline}`; the axis caption is `x_label`, else `name`, `unit` and `log` joined by commas).
- Produces: `DistributionPanel({ result })` (default export too); axis helpers for Scatter: `niceLogDomain(lo, hi): [number, number]`, `logTicks(lo, hi): number[]`, `xAxis(kind: "linear" | "log", values: number[]): {domain: [number, number], ticks: number[]}` (log drops values <= 0 and keeps only powers of ten above 8 ticks; linear starts at 0, `nice(6)`), `xScale(kind, domain, range): (v: number) => number` (log clamps), `fmtTick(v): string`; palette `SERIES_LIGHT`, `SERIES_DARK` (5 validated hexes each), `seriesColor(i): string` (`light-dark(<light>, <dark>)`, `var(--ink-3)` past slot 5); `signedPctNum(v, digits = 0)` (`−30`, `+4.1`; U+2212 minus) and `signedPct(v, digits = 0)` (`−30%`). Geometry: viewBox 720 wide, plot x range [132, 704]. With `meta.render = "table"` the panel is a `<table data-testid="ptable">` instead of the SVG (spec 8.4 system_bench "percentile table with Δ and CI vs baseline"): one row per group (`tr[data-group]`), one cell per percentile (`td[data-q]`) holding the value (`fmtNum`) and a `<small>` line: `ref` on the baseline row, `−30% [−34, −24]` when `vs_baseline` has an interval, `−30%` when it has none (a side with one repeat), nothing when `vs_baseline` is null. Cell tooltip: `<label> <q>: repeats <per-seed values>` plus `\nbaseline` or `\nvs baseline −30.0%, 95% CI −34.0 to −24.0%` (`, one repeat: no CI` without an interval).

- [ ] **Step 1: Write the failing test**

`ui/test/panels/Distribution.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import {
  DistributionPanel,
  fmtTick,
  logTicks,
  niceLogDomain,
  seriesColor,
  signedPct,
  signedPctNum,
  xAxis,
  xScale,
} from "../../src/panels/Distribution";

afterEach(cleanup);

const ROWS = [
  {
    group_id: "g1",
    label: "baseline",
    n: 4,
    p50: 20,
    p95: 80,
    p99: 200,
    ecdf: [
      [10, 0.25],
      [20, 0.5],
      [80, 0.75],
      [200, 1],
    ],
    seeds: [
      { run_id: "r1", p50: 19, p95: 78, p99: 190 },
      { run_id: "r2", p50: 21, p95: 82, p99: 210 },
    ],
  },
  {
    group_id: "g2",
    label: "cache",
    n: 4,
    p50: 12,
    p95: 40,
    p99: 90,
    ecdf: [
      [8, 0.25],
      [12, 0.5],
      [40, 0.75],
      [90, 1],
    ],
    seeds: [{ run_id: "r3", p50: 12, p95: 41, p99: 88 }],
  },
];

const dist = (meta: Record<string, unknown>, rows: unknown[] = ROWS): PanelResult => ({
  type: "distribution",
  title: "Latency",
  rows: rows as Record<string, unknown>[],
  meta,
});

const tickLabels = (c: HTMLElement) =>
  [...c.querySelectorAll("text[data-tick]")].map((t) => t.getAttribute("data-tick"));

describe("log axis helpers", () => {
  test("niceLogDomain widens to 1-2-5 values", () => {
    expect(niceLogDomain(7.3, 812)).toEqual([5, 1000]);
    expect(niceLogDomain(5, 1000)).toEqual([5, 1000]);
    expect(niceLogDomain(0.008, 2.2)).toEqual([0.005, 5]);
    expect(niceLogDomain(100, 100)).toEqual([100, 1000]);
  });

  test("logTicks lists 1-2-5 values inside the domain", () => {
    expect(logTicks(5, 1000)).toEqual([5, 10, 20, 50, 100, 200, 500, 1000]);
    expect(logTicks(0.005, 5)).toEqual([0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5]);
  });

  test("xAxis keeps only powers of ten when there are more than 8 ticks", () => {
    expect(xAxis("log", [0.008, 2.2]).ticks).toEqual([0.01, 0.1, 1]);
    expect(xAxis("log", [-1, 0, 7.3, 812])).toEqual({
      domain: [5, 1000],
      ticks: [5, 10, 20, 50, 100, 200, 500, 1000],
    });
  });

  test("xAxis linear starts at zero and uses nice ticks", () => {
    // d3-scale: [0, 210].nice(6) -> [0, 250]; ticks(6) step 50
    expect(xAxis("linear", [8, 210])).toEqual({
      domain: [0, 250],
      ticks: [0, 50, 100, 150, 200, 250],
    });
  });

  test("xScale log puts the geometric midpoint in the middle and clamps", () => {
    const x = xScale("log", [10, 1000], [0, 200]);
    expect(x(100)).toBeCloseTo(100, 6);
    expect(x(1)).toBeCloseTo(0, 6);
    expect(xScale("linear", [0, 100], [0, 200])(50)).toBe(100);
  });

  test("fmtTick is short", () => {
    expect(fmtTick(0.05)).toBe("0.05");
    expect(fmtTick(20)).toBe("20");
    expect(fmtTick(1000)).toBe("1,000");
  });
});

describe("signed percents", () => {
  test("U+2212 minus, explicit plus, fixed decimals", () => {
    expect(signedPct(-0.3)).toBe("\u221230%");
    expect(signedPct(0)).toBe("+0%");
    expect(signedPctNum(0.041, 1)).toBe("+4.1");
    expect(signedPctNum(-0.452)).toBe("\u221245");
  });
});

describe("seriesColor", () => {
  test("fixed order with light and dark steps, then muted ink", () => {
    expect(seriesColor(0)).toBe("light-dark(#2a78d6, #4a90e8)");
    expect(seriesColor(1)).toBe("light-dark(#e0602e, #e06a35)");
    expect(seriesColor(5)).toBe("var(--ink-3)");
  });
});

describe("DistributionPanel", () => {
  test("draws one ECDF per group with labels, ticks and seed dots", () => {
    const { container } = render(<DistributionPanel result={dist({ unit: "ms" })} />);
    expect(container.querySelectorAll('[data-testid="ecdf"]').length).toBe(2);
    expect(screen.getByText("baseline")).toBeTruthy();
    expect(screen.getByText("cache")).toBeTruthy();
    expect(container.querySelectorAll("[data-q]").length).toBe(6);
    expect(container.querySelectorAll("[data-seed]").length).toBe(3);
    expect(screen.getByText("ms, log")).toBeTruthy();
  });

  test("log axis: domain [5, 500], ticks at 1-2-5, positions on a log scale", () => {
    const { container } = render(<DistributionPanel result={dist({ unit: "ms" })} />);
    expect(tickLabels(container)).toEqual(["5", "10", "20", "50", "100", "200", "500"]);
    // x range [132, 704]; 50 is the geometric middle of [5, 500]
    const t50 = container.querySelector('text[data-tick="50"]');
    expect(Number(t50?.getAttribute("x"))).toBeCloseTo(418, 3);
    const g1 = container.querySelector('[data-group="g1"]') as Element;
    const x = (q: string) => Number(g1.querySelector(`[data-q="${q}"]`)?.getAttribute("x1"));
    // 132 + log10(80 / 5) / log10(100) * 572
    expect(x("p95")).toBeCloseTo(476.378, 2);
    expect(x("p50")).toBeLessThan(x("p95"));
    expect(x("p95")).toBeLessThan(x("p99"));
  });

  test("tick and seed tooltips carry the value and unit", () => {
    const { container } = render(<DistributionPanel result={dist({ unit: "ms" })} />);
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles).toContain("baseline p95 80 ms\nn = 4, 2 seeds");
    expect(titles).toContain("r2\np50 21 ms, p95 82 ms, p99 210 ms");
  });

  test("linear scale when asked", () => {
    const { container } = render(
      <DistributionPanel result={dist({ scale: "linear", unit: "ms" })} />,
    );
    expect(tickLabels(container)).toEqual(["0", "50", "100", "150", "200", "250"]);
    const t100 = container.querySelector('text[data-tick="100"]');
    expect(Number(t100?.getAttribute("x"))).toBeCloseTo(360.8, 3);
    expect(screen.getByText("ms")).toBeTruthy();
  });

  test("one sample and a zero latency still draw finite geometry", () => {
    const one = [
      {
        group_id: "g1",
        label: "tiny",
        n: 2,
        p50: 0,
        p95: 100,
        p99: 100,
        ecdf: [
          [0, 0.5],
          [100, 1],
        ],
        seeds: [],
      },
    ];
    const { container } = render(<DistributionPanel result={dist({ unit: "ms" }, one)} />);
    expect(container.innerHTML).not.toContain("NaN");
    expect(container.querySelectorAll('[data-testid="ecdf"]').length).toBe(1);
    // zero is dropped from the log domain and its tick clamps to the left edge
    const p50 = container.querySelector('[data-q="p50"]');
    expect(Number(p50?.getAttribute("x1"))).toBe(132);
  });

  test("the backend's meta names the axis with the sample name", () => {
    render(<DistributionPanel result={dist({ name: "latency_ms", scale: "log" })} />);
    expect(screen.getByText("latency_ms, log")).toBeTruthy();
  });

  test("empty result says so", () => {
    render(<DistributionPanel result={dist({}, [])} />);
    expect(screen.getByText("No samples")).toBeTruthy();
  });
});

describe("DistributionPanel as a percentile table", () => {
  // g1 is the baseline; g2 has one repeat on p95's comparison, so no interval there
  const DELTA_ROWS = [
    { ...ROWS[0], vs_baseline: null },
    {
      ...ROWS[1],
      vs_baseline: {
        p50: [-0.4, -0.452, -0.348],
        p95: [-0.5, null, null],
        p99: [-0.55, -0.6, -0.5],
      },
    },
  ];
  const cell = (c: HTMLElement, g: string, q: string) =>
    c.querySelector(`tr[data-group="${g}"] td[data-q="${q}"]`) as HTMLElement;

  test("values, Δ% with its CI, and ref on the baseline row", () => {
    const { container } = render(
      <DistributionPanel
        result={dist({ render: "table", unit: "ms", baseline: "g1" }, DELTA_ROWS)}
      />,
    );
    expect(container.querySelector("svg")).toBeNull();
    expect(container.querySelectorAll('[data-testid="ptable"] tbody tr').length).toBe(2);
    expect(screen.getByText("p95 ms")).toBeTruthy();
    expect(cell(container, "g1", "p50").textContent).toBe("20ref");
    expect(cell(container, "g2", "p50").textContent).toBe("12\u221240% [\u221245, \u221235]");
    expect(cell(container, "g2", "p95").textContent).toBe("40\u221250%");
    expect(cell(container, "g2", "p99").textContent).toBe("90\u221255% [\u221260, \u221250]");
    expect(cell(container, "g2", "p50").getAttribute("title")).toBe(
      "cache p50: repeats 12\nvs baseline \u221240.0%, 95% CI \u221245.2 to \u221234.8%",
    );
    expect(cell(container, "g2", "p95").getAttribute("title")).toBe(
      "cache p95: repeats 41\nvs baseline \u221250.0%, one repeat: no CI",
    );
    expect(cell(container, "g1", "p95").getAttribute("title")).toBe(
      "baseline p95: repeats 78, 82\nbaseline",
    );
  });

  test("without a baseline the table shows values only", () => {
    const { container } = render(<DistributionPanel result={dist({ render: "table" })} />);
    expect(container.querySelectorAll("[data-delta]").length).toBe(0);
    expect(cell(container, "g1", "p99").textContent).toBe("200");
    expect(cell(container, "g2", "p50").getAttribute("title")).toBe("cache p50: repeats 12");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/panels/Distribution.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/panels/Distribution' from '.../ui/test/panels/Distribution.test.tsx'`.

- [ ] **Step 3: Write the implementation**

`ui/src/panels/Distribution.tsx`:

```tsx
/**
 * Distribution panel: ECDF per group plus p50/p95/p99 ticks and per-seed p95 dots.
 *
 * The x axis is log by default (latency); `meta.scale = "linear"` switches it.
 * `meta.render = "table"` draws the percentile table with the change vs the baseline instead.
 */
import { scaleLinear, scaleLog } from "d3-scale";
import { curveStepAfter, line } from "d3-shape";
import type { CSSProperties } from "react";
import type { DistributionRow } from "../api/models";
import type { PanelResult } from "./index";
import { fmtNum } from "./Table";

/** One group's distribution row (contract 1.6). */
export type DistRow = DistributionRow;
/** One seed's percentiles. */
export type DistSeed = DistRow["seeds"][number];
type Quantile = "p50" | "p95" | "p99";
type Scale = "linear" | "log";

/**
 * Categorical series colours, fixed order, light and dark steps.
 *
 * Checked with the dataviz palette validator: light passes with adjacent CVD dE >= 15.7
 * (the yellow slot is below 3:1 contrast, so every series is also direct-labelled); dark
 * passes with adjacent CVD dE >= 16.7.
 */
export const SERIES_LIGHT = ["#2a78d6", "#e0602e", "#b8447e", "#eda100", "#4a3aa7"] as const;
export const SERIES_DARK = ["#4a90e8", "#e06a35", "#c95aa8", "#c98500", "#9085e9"] as const;

/** Colour for series `i`; follows `color-scheme`. Series past the fifth share muted ink. */
export function seriesColor(i: number): string {
  if (i < 0 || i >= SERIES_LIGHT.length) return "var(--ink-3)";
  return `light-dark(${SERIES_LIGHT[i]}, ${SERIES_DARK[i]})`;
}

const MANTISSAS = [1, 2, 5] as const;
const r12 = (v: number): number => Number(v.toPrecision(12));

/** Widen `[lo, hi]` (both > 0) to the enclosing 1-2-5 values. */
export function niceLogDomain(lo: number, hi: number): [number, number] {
  const e0 = Math.floor(Math.log10(lo));
  let dLo = r12(10 ** e0);
  for (const m of MANTISSAS) if (r12(m * 10 ** e0) <= lo) dLo = r12(m * 10 ** e0);
  const e1 = Math.floor(Math.log10(hi));
  let dHi = r12(10 ** (e1 + 1));
  for (const m of [5, 2, 1]) if (r12(m * 10 ** e1) >= hi) dHi = r12(m * 10 ** e1);
  if (dHi <= dLo) dHi = r12(dLo * 10);
  return [dLo, dHi];
}

/** All 1-2-5 values inside `[lo, hi]`. */
export function logTicks(lo: number, hi: number): number[] {
  const out: number[] = [];
  for (let e = Math.floor(Math.log10(lo)); e <= Math.floor(Math.log10(hi)); e++) {
    for (const m of MANTISSAS) {
      const v = r12(m * 10 ** e);
      if (v >= lo * (1 - 1e-9) && v <= hi * (1 + 1e-9)) out.push(v);
    }
  }
  return out;
}

/** Signed percent number: `−30`, `+4.1` (U+2212 minus), `digits` decimals. */
export function signedPctNum(v: number, digits = 0): string {
  return `${v < 0 ? "\u2212" : "+"}${Math.abs(v * 100).toFixed(digits)}`;
}

/** Signed percent: `−30%`, `+4%`. */
export function signedPct(v: number, digits = 0): string {
  return `${signedPctNum(v, digits)}%`;
}

/** Axis tick text: `0.05`, `20`, `1,000`. */
export function fmtTick(v: number): string {
  return Math.abs(v) >= 1000 ? v.toLocaleString("en-US") : String(Number(v.toPrecision(3)));
}

/** A linear or log (clamped) position function over `domain` mapped to `range`. */
export function xScale(
  kind: Scale,
  domain: [number, number],
  range: [number, number],
): (v: number) => number {
  const s =
    kind === "log"
      ? scaleLog().domain(domain).range(range).clamp(true)
      : scaleLinear().domain(domain).range(range);
  return (v: number) => s(v);
}

/** Domain and ticks for an x axis over `values`. Log drops values <= 0. */
export function xAxis(
  kind: Scale,
  values: number[],
): { domain: [number, number]; ticks: number[] } {
  const vs = values.filter((v) => Number.isFinite(v) && (kind === "linear" || v > 0));
  if (vs.length === 0) {
    return kind === "log"
      ? { domain: [1, 10], ticks: [1, 2, 5, 10] }
      : { domain: [0, 1], ticks: [0, 0.5, 1] };
  }
  const lo = Math.min(...vs);
  const hi = Math.max(...vs);
  if (kind === "log") {
    const domain = niceLogDomain(lo, hi);
    const all = logTicks(domain[0], domain[1]);
    const pow10 = (t: number) => r12(10 ** Math.round(Math.log10(t))) === t;
    return { domain, ticks: all.length > 8 ? all.filter(pow10) : all };
  }
  const s = scaleLinear()
    .domain([Math.min(0, lo), hi === lo ? lo + 1 : hi])
    .nice(6);
  const [d0, d1] = s.domain();
  return { domain: [d0, d1], ticks: s.ticks(6) };
}

// viewBox geometry
const W = 720;
const PL = 132;
const PR = 16;
const TOP = 12;
const EH = 180;
const GAP = 34;
const RH = 36;
const TICK_HALF = { p50: 7, p95: 10, p99: 13 } as const;
const TICK_WIDTH = { p50: 1.25, p95: 2, p99: 1.25 } as const;
const QS = ["p50", "p95", "p99"] as const;

const T = {
  tk: { fontSize: 11.5, fill: "var(--ink-3)", fontVariantNumeric: "tabular-nums" },
  lbl: { fontSize: 12.5, fill: "var(--ink-2)" },
  lblB: { fontSize: 12.5, fill: "var(--ink)", fontWeight: 600 },
  lblS: { fontSize: 11.5, fill: "var(--ink-3)" },
  axis: { stroke: "var(--ink-3)", strokeWidth: 1 },
  grid: { stroke: "var(--rule-2)", strokeWidth: 1 },
  hair: { stroke: "var(--rule)", strokeWidth: 1 },
  seed: { fill: "var(--ink-3)", stroke: "var(--paper)", strokeWidth: 1.5 },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
  table: {
    borderCollapse: "collapse",
    width: "100%",
    fontSize: 13,
    fontVariantNumeric: "tabular-nums",
  },
  th: {
    fontSize: 11.5,
    fontWeight: 400,
    color: "var(--ink-3)",
    textAlign: "right",
    padding: "0 0 6px 12px",
    borderBottom: "1px solid var(--rule)",
  },
  td: {
    textAlign: "right",
    padding: "6px 0 6px 12px",
    borderBottom: "1px solid var(--rule-2)",
    color: "var(--ink)",
    verticalAlign: "top",
  },
  tdLabel: {
    textAlign: "left",
    padding: "6px 12px 6px 0",
    borderBottom: "1px solid var(--rule-2)",
    color: "var(--ink)",
    fontWeight: 600,
    verticalAlign: "top",
  },
  delta: { display: "block", fontSize: 11.5, color: "var(--ink-2)" },
  ref: { display: "block", fontSize: 11.5, color: "var(--ink-3)" },
} satisfies Record<string, CSSProperties>;

/** One percentile cell's tooltip: per-seed values, then the change vs the baseline. */
function cellTip(r: DistRow, q: Quantile, isBase: boolean): string {
  const repeats = r.seeds.map((s) => fmtNum(s[q])).join(", ");
  const head = `${r.label} ${q}: repeats ${repeats || "\u2014"}`;
  if (isBase) return `${head}\nbaseline`;
  const d = r.vs_baseline?.[q];
  if (!d) return head;
  const [rel, lo, hi] = d;
  const ci =
    lo !== null && hi !== null
      ? `, 95% CI ${signedPctNum(lo, 1)} to ${signedPct(hi, 1)}`
      : ", one repeat: no CI";
  return `${head}\nvs baseline ${signedPct(rel, 1)}${ci}`;
}

/**
 * Percentile table: a row per group, p50/p95/p99 columns. Each cell shows the pooled value
 * and, below it, `ref` on the baseline row or the change vs the baseline with its 95% CI.
 */
function PercentileTable({
  rows,
  unit,
  baseline,
}: {
  rows: DistRow[];
  unit: string;
  baseline: string | null;
}) {
  const u = unit ? ` ${unit}` : "";
  return (
    <table data-testid="ptable" style={T.table}>
      <thead>
        <tr>
          <th style={{ ...T.th, textAlign: "left", padding: "0 12px 6px 0" }} />
          {QS.map((q) => (
            <th key={q} style={T.th}>{`${q}${u}`}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const isBase = r.group_id === baseline;
          return (
            <tr key={r.group_id} data-group={r.group_id}>
              <td style={T.tdLabel}>{r.label}</td>
              {QS.map((q) => {
                const d = isBase ? null : (r.vs_baseline?.[q] ?? null);
                return (
                  <td key={q} data-q={q} title={cellTip(r, q, isBase)} style={T.td}>
                    {fmtNum(r[q])}
                    {isBase && (
                      <small data-delta="ref" style={T.ref}>
                        ref
                      </small>
                    )}
                    {d && (
                      <small data-delta={q} style={T.delta}>
                        {signedPct(d[0])}
                        {d[1] !== null && d[2] !== null
                          ? ` [${signedPctNum(d[1])}, ${signedPctNum(d[2])}]`
                          : ""}
                      </small>
                    )}
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

/**
 * Distribution panel. Reads `meta.scale`, `meta.unit`, `meta.x_label`, `meta.name` (the
 * sample name), `meta.render` and `meta.baseline` (the backend sends
 * `{name, scale, render, baseline}`).
 */
export function DistributionPanel({ result }: { result: PanelResult }) {
  const rows = result.rows as unknown as DistRow[];
  const meta = (result.meta ?? {}) as Record<string, unknown>;
  if (rows.length === 0) return <p style={T.empty}>No samples</p>;
  const unit = typeof meta.unit === "string" ? meta.unit : "";
  if (meta.render === "table") {
    const baseline = typeof meta.baseline === "string" ? meta.baseline : null;
    return <PercentileTable rows={rows} unit={unit} baseline={baseline} />;
  }
  const kind: Scale = meta.scale === "linear" ? "linear" : "log";
  const name = typeof meta.name === "string" ? meta.name : "";
  const xLabel =
    typeof meta.x_label === "string"
      ? meta.x_label
      : [name, unit, kind === "log" ? "log" : ""].filter(Boolean).join(", ");

  const values = rows.flatMap((r) => [
    r.p50,
    r.p95,
    r.p99,
    ...r.ecdf.map((p) => p[0]),
    ...r.seeds.flatMap((s) => [s.p50, s.p95, s.p99]),
  ]);
  const { domain, ticks } = xAxis(kind, values);
  const X = xScale(kind, domain, [PL, W - PR]);
  const yE = TOP + EH;
  const Y = (p: number) => yE - p * EH;
  const rowsTop = yE + GAP;
  const yA = rowsTop + RH * rows.length + 4;
  const H = yA + 40;
  const path = line<[number, number]>()
    .x((d) => X(d[0]))
    .y((d) => Y(d[1]))
    .curve(curveStepAfter);
  const u = unit ? ` ${unit}` : "";

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label={`Distributions of ${rows.length} groups, ${kind} scale, with p50, p95 and p99 ticks`}
      style={{ display: "block", overflow: "visible", fontFamily: "var(--sans)" }}
    >
      {ticks.map((t) => (
        <line key={`g${t}`} x1={X(t)} x2={X(t)} y1={TOP} y2={yA} style={T.grid} />
      ))}
      {[0, 0.5, 1].map((p) => (
        <g key={`y${p}`}>
          <line x1={PL} x2={W - PR} y1={Y(p)} y2={Y(p)} style={p === 0 ? T.axis : T.grid} />
          <text x={PL - 8} y={Y(p) + 4} textAnchor="end" style={T.tk}>
            {p}
          </text>
        </g>
      ))}
      <text x={PL - 8} y={TOP - 2} textAnchor="end" style={T.lblS}>
        share
      </text>
      {rows.map((r, i) => {
        const pts = r.ecdf.filter((p) => kind === "linear" || p[0] > 0);
        if (pts.length === 0) return null;
        const d = path([[pts[0][0], 0], ...pts]) ?? "";
        return (
          <path
            key={`e${r.group_id}`}
            data-testid="ecdf"
            d={d}
            style={{
              fill: "none",
              stroke: seriesColor(i),
              strokeWidth: 2,
              strokeLinejoin: "round",
            }}
          >
            <title>{`${r.label}\nn = ${fmtNum(r.n)}`}</title>
          </path>
        );
      })}
      {QS.map((q) => (
        <text key={`h${q}`} x={X(rows[0][q])} y={rowsTop - 10} textAnchor="middle" style={T.lblS}>
          {q}
        </text>
      ))}
      {rows.map((r, i) => {
        const cy = rowsTop + RH * i + RH / 2;
        return (
          <g key={`r${r.group_id}`} data-group={r.group_id}>
            <line
              x1={0}
              x2={14}
              y1={cy}
              y2={cy}
              style={{ stroke: seriesColor(i), strokeWidth: 2.5 }}
            />
            <text x={20} y={cy + 4} style={T.lblB}>
              {r.label}
            </text>
            <line x1={PL} x2={W - PR} y1={cy} y2={cy} style={T.grid} />
            {r.seeds.map((s) => (
              <circle
                key={s.run_id}
                data-seed={s.run_id}
                cx={X(s.p95)}
                cy={cy}
                r={3.2}
                style={T.seed}
              >
                <title>{`${s.run_id}\np50 ${fmtNum(s.p50)}${u}, p95 ${fmtNum(s.p95)}${u}, p99 ${fmtNum(s.p99)}${u}`}</title>
              </circle>
            ))}
            {QS.map((q) => (
              <line
                key={q}
                data-q={q}
                x1={X(r[q])}
                x2={X(r[q])}
                y1={cy - TICK_HALF[q]}
                y2={cy + TICK_HALF[q]}
                style={{ stroke: "var(--ink)", strokeWidth: TICK_WIDTH[q] }}
              >
                <title>{`${r.label} ${q} ${fmtNum(r[q])}${u}\nn = ${fmtNum(r.n)}, ${r.seeds.length} seeds`}</title>
              </line>
            ))}
          </g>
        );
      })}
      <line x1={PL} x2={W - PR} y1={yA} y2={yA} style={T.axis} />
      {ticks.map((t) => (
        <g key={`t${t}`}>
          <line x1={X(t)} x2={X(t)} y1={yA} y2={yA + 4} style={T.axis} />
          <text data-tick={fmtTick(t)} x={X(t)} y={yA + 17} textAnchor="middle" style={T.tk}>
            {fmtTick(t)}
          </text>
        </g>
      ))}
      <text x={W - PR} y={yA + 34} textAnchor="end" style={T.lblS}>
        {xLabel}
      </text>
    </svg>
  );
}

export default DistributionPanel;
```

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && bun test test/panels/Distribution.test.tsx && bunx tsc --noEmit -p .`
Expected: PASS, `17 pass`, `0 fail`; `tsc` prints nothing and exits 0.

- [ ] **Step 5: Commit**

```bash
git add ui/src/panels/Distribution.tsx ui/test/panels/Distribution.test.tsx
git commit -m "feat(ui): distribution panel with ECDF, percentile ticks, and percentile table"
```

### Task 18: Scatter panel (seeds, 95% whiskers, Pareto staircase, ordinal x with regressions)

**Files:**
- Create: `ui/src/panels/Scatter.tsx`
- Test: `ui/test/panels/Scatter.test.tsx`

**Interfaces:**
- Consumes: `PanelResult` from `ui/src/panels/index.ts` (Task 11; fields `type`, `title`, `rows`, optional `meta`); `fmtNum` (`./Table`, Task 14); `xAxis`, `xScale`, `fmtTick` (`./Distribution`, Task 17). Rows `{group_id, label, x, x_lo, x_hi, y, y_lo, y_hi, seeds: [{x, y}], pareto: bool, regression: bool}` (contract 1.6 `scatter`; the server decides front membership and regressions); `meta.x_type` (`"ordinal"`: x is text such as `v9`, rows arrive in axis order); optional `meta.pareto` (`{x: "min"|"max", y: "min"|"max"}`, default `{x: "min", y: "max"}`), `meta.scale`, `meta.x_label`, `meta.y_label`, `meta.x`, `meta.y`, `meta.best_group` (the backend's meta is `{x, y, scale, pareto}` with the metric or field refs; captions are `x_label`, else `x`, else `"x"`, and the same for y).
- Produces: `ScatterPanel({ result })` (default export too); `paretoPath(front: {x, y}[], xDir: "min" | "max", tailTo?: number): [number, number][]` (data-space staircase vertices); `bestIndex(rows, yDir, bestGroup?): number`; types `Dir`, `ScatterRow` (re-exported from the Task 3 models). Geometry: viewBox 640x360, x range [52, 624], y range [316, 26]. Ordinal x (`meta.x_type = "ordinal"`): one equal band per row in row order, the point at the band centre (`52 + (i + 0.5) * 572 / rows`), tick labels are the x texts, no x whiskers, no Pareto line, no hollow "dominated" style. A row with `regression: true` on an ordinal axis (spec 8.4 "regressions marked") has its mean filled with `var(--fail)`, a `▼` glyph below it (`[data-testid="regression"]`, `var(--fail)`) with the tooltip `regression vs best earlier version`, and its point tooltip ends with `, regression vs best earlier version`; the key gains a `regression` item when any row regresses.

- [ ] **Step 1: Write the failing test**

`ui/test/panels/Scatter.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import { bestIndex, paretoPath, type ScatterRow, ScatterPanel } from "../../src/panels/Scatter";

afterEach(cleanup);

const ROWS: ScatterRow[] = [
  {
    group_id: "g1",
    label: "mcts-64",
    x: 0.3,
    x_lo: 0.28,
    x_hi: 0.32,
    y: 0.6,
    y_lo: 0.53,
    y_hi: 0.67,
    seeds: [
      { x: 0.29, y: 0.59 },
      { x: 0.31, y: 0.61 },
    ],
    pareto: true,
    regression: false,
  },
  {
    group_id: "g2",
    label: "greedy",
    x: 0.05,
    x_lo: null,
    x_hi: null,
    y: 0.4,
    y_lo: 0.33,
    y_hi: 0.47,
    seeds: [{ x: 0.05, y: 0.4 }],
    pareto: true,
    regression: false,
  },
  {
    group_id: "g3",
    label: "beam",
    x: 0.5,
    x_lo: 0.45,
    x_hi: 0.55,
    y: 0.5,
    y_lo: 0.43,
    y_hi: 0.57,
    seeds: [],
    pareto: false,
    regression: false,
  },
];

const scatter = (meta: Record<string, unknown>, rows: ScatterRow[] = ROWS): PanelResult => ({
  type: "scatter",
  title: "Cost vs solved",
  rows: rows as unknown as Record<string, unknown>[],
  meta,
});

const META = { x_label: "$ / attempt", y_label: "solved@v2", pareto: { x: "min", y: "max" } };

const mean = (c: HTMLElement, g: string) =>
  c.querySelector(`[data-group="${g}"] [data-testid="mean"]`) as SVGElement;

describe("paretoPath", () => {
  test("lower x better: across, then up, then tail to the right edge", () => {
    const front = [
      { x: 0.3, y: 0.6 },
      { x: 0.05, y: 0.4 },
      { x: 1.2, y: 0.66 },
    ];
    expect(paretoPath(front, "min", 2)).toEqual([
      [0.05, 0.4],
      [0.3, 0.4],
      [0.3, 0.6],
      [1.2, 0.6],
      [1.2, 0.66],
      [2, 0.66],
    ]);
  });

  test("higher x better: down first, tail to the left edge", () => {
    expect(
      paretoPath(
        [
          { x: 1, y: 5 },
          { x: 3, y: 2 },
        ],
        "max",
        0,
      ),
    ).toEqual([
      [0, 5],
      [1, 5],
      [1, 2],
      [3, 2],
    ]);
  });

  test("empty front gives no path", () => {
    expect(paretoPath([], "min", 1)).toEqual([]);
  });
});

describe("bestIndex", () => {
  test("highest y, lowest y, or the named group", () => {
    expect(bestIndex(ROWS, "max")).toBe(0);
    expect(bestIndex(ROWS, "min")).toBe(1);
    expect(bestIndex(ROWS, "max", "g3")).toBe(2);
    expect(bestIndex([], "max")).toBe(-1);
  });
});

describe("ScatterPanel", () => {
  test("one mean per group; best, front and dominated styles differ", () => {
    const { container } = render(<ScatterPanel result={scatter(META)} />);
    expect(container.querySelectorAll('[data-testid="mean"]').length).toBe(3);
    expect(mean(container, "g1").dataset.best).toBe("true");
    expect(mean(container, "g1").style.fill).toBe("var(--best)");
    expect(mean(container, "g2").style.fill).toBe("var(--ink)");
    expect(mean(container, "g3").dataset.pareto).toBe("false");
    expect(mean(container, "g3").style.fill).toBe("var(--paper)");
    expect(container.querySelectorAll('[data-testid="regression"]').length).toBe(0);
  });

  test("seed dots, whiskers only where intervals exist, labels", () => {
    const { container } = render(<ScatterPanel result={scatter(META)} />);
    expect(container.querySelectorAll("[data-seed]").length).toBe(3);
    expect(container.querySelectorAll('[data-testid="ywhisk"]').length).toBe(3);
    expect(container.querySelectorAll('[data-testid="xwhisk"]').length).toBe(2);
    for (const l of ["mcts-64", "greedy", "beam", "$ / attempt", "solved@v2"]) {
      expect(screen.getByText(l)).toBeTruthy();
    }
  });

  test("Pareto staircase runs through front groups only, plus a tail", () => {
    const { container } = render(<ScatterPanel result={scatter(META)} />);
    const d = container.querySelector('[data-testid="pareto"]')?.getAttribute("d") ?? "";
    // vertices: greedy, across to x=0.3, up to mcts-64, tail to the right edge
    // x domain [0, 0.6] -> [52, 624]; y domain [0.3, 0.7] -> [316, 26]
    // greedy (0.05, 0.4) -> (52 + 0.05 / 0.6 * 572, 316 - 0.1 / 0.4 * 290) = (99.7, 243.5)
    // across to mcts-64 x = 0.3 -> 338, up to y = 0.6 -> 98.5, tail to the right edge 624
    expect(d).toBe("M99.7 243.5L338.0 243.5L338.0 98.5L624.0 98.5");
  });

  test("tooltip names values, intervals and front membership", () => {
    const { container } = render(<ScatterPanel result={scatter(META)} />);
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles).toContain(
      "beam\nsolved@v2 0.500 [0.430, 0.570]\n$ / attempt 0.500 [0.450, 0.550]\n0 seeds, dominated",
    );
  });

  test("log x axis uses 1-2-5 ticks", () => {
    const { container } = render(<ScatterPanel result={scatter({ ...META, scale: "log" })} />);
    const ticks = [...container.querySelectorAll("text[data-tick]")].map((t) =>
      t.getAttribute("data-tick"),
    );
    // values span 0.05..0.55 -> domain [0.05, 1]
    expect(ticks).toEqual(["0.05", "0.1", "0.2", "0.5", "1"]);
    expect(screen.getByText("$ / attempt, log")).toBeTruthy();
  });

  test("a single group with no intervals still draws finite geometry", () => {
    const one: ScatterRow = {
      group_id: "g1",
      label: "only",
      x: 0,
      x_lo: null,
      x_hi: null,
      y: 0.5,
      y_lo: null,
      y_hi: null,
      seeds: [],
      pareto: true,
      regression: false,
    };
    for (const scale of ["linear", "log"]) {
      const { container, unmount } = render(<ScatterPanel result={scatter({ scale }, [one])} />);
      expect(container.innerHTML).not.toContain("NaN");
      expect(container.querySelectorAll('[data-testid="mean"]').length).toBe(1);
      unmount();
    }
  });

  test("the backend's meta names the axes and tooltips with the metric refs", () => {
    const backend = { x: "usage.usd", y: "solved@v2/value", scale: "linear", pareto: { x: "min", y: "max" } };
    const { container } = render(<ScatterPanel result={scatter(backend)} />);
    expect(screen.getByText("usage.usd")).toBeTruthy();
    expect(screen.getByText("solved@v2/value")).toBeTruthy();
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles).toContain(
      "beam\nsolved@v2/value 0.500 [0.430, 0.570]\nusage.usd 0.500 [0.450, 0.550]\n0 seeds, dominated",
    );
  });

  test("ordinal x: versions in order; a regression is drawn in the failure colour with ▼", () => {
    const version = (v: string, y: number, regression: boolean): ScatterRow => ({
      group_id: v,
      label: v,
      x: v,
      x_lo: null,
      x_hi: null,
      y,
      y_lo: y - 0.025,
      y_hi: y + 0.025,
      seeds: [
        { x: v, y: y - 0.01 },
        { x: v, y: y + 0.01 },
      ],
      pareto: false,
      regression,
    });
    // the backend's meta for the agent_iteration "Solved by version" panel
    const meta = {
      x: "params.version",
      y: "solved/value",
      x_type: "ordinal",
      scale: "linear",
      pareto: null,
    };
    const rows = [version("v1", 0.5, false), version("v2", 0.7, false), version("v3", 0.6, true)];
    const { container } = render(<ScatterPanel result={scatter(meta, rows)} />);
    expect(container.innerHTML).not.toContain("NaN");
    const ticks = [...container.querySelectorAll("text[data-tick]")].map((t) =>
      t.getAttribute("data-tick"),
    );
    expect(ticks).toEqual(["v1", "v2", "v3"]);
    // three bands over [52, 624]: v2's centre is 52 + 1.5 * 572 / 3 = 338; its square starts at 333
    expect(Number(mean(container, "v2").getAttribute("x"))).toBeCloseTo(333, 6);
    expect(mean(container, "v2").style.fill).toBe("var(--best)");
    expect(mean(container, "v1").style.fill).toBe("var(--ink)"); // no hollow "dominated" style
    expect(mean(container, "v3").dataset.regression).toBe("true");
    expect(mean(container, "v3").style.fill).toBe("var(--fail)");
    const glyphs = container.querySelectorAll('[data-testid="regression"]');
    expect(glyphs.length).toBe(1);
    expect(glyphs[0].closest("[data-group]")?.getAttribute("data-group")).toBe("v3");
    expect(glyphs[0].querySelector("text")?.textContent).toBe("▼");
    expect(glyphs[0].querySelector("title")?.textContent).toBe(
      "regression vs best earlier version",
    );
    expect(container.querySelector('[data-testid="pareto"]')).toBeNull();
    expect(container.querySelectorAll('[data-testid="xwhisk"]').length).toBe(0);
    expect(container.querySelectorAll("[data-seed]").length).toBe(6);
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles).toContain(
      "v3\nsolved/value 0.600 [0.575, 0.625]\nparams.version v3\n2 seeds, regression vs best earlier version",
    );
    expect(screen.getByText("regression")).toBeTruthy(); // key item
    expect(screen.queryByText("Pareto")).toBeNull();
  });

  test("empty result says so", () => {
    render(<ScatterPanel result={scatter({}, [])} />);
    expect(screen.getByText("No data")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/panels/Scatter.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/panels/Scatter' from '.../ui/test/panels/Scatter.test.tsx'`.

- [ ] **Step 3: Write the implementation**

`ui/src/panels/Scatter.tsx`:

```tsx
/**
 * Scatter panel: one point per group with 95% whiskers on both axes, faint seed dots, and
 * a dashed Pareto staircase through the groups the query engine marked `pareto: true`.
 * On an ordinal x (`meta.x_type = "ordinal"`, e.g. versions) rows sit in equal bands in
 * row order, and rows the engine marked `regression: true` are drawn in the failure colour.
 */
import { scaleLinear } from "d3-scale";
import type { CSSProperties } from "react";
import type { ScatterRow } from "../api/models";
import { fmtTick, xAxis, xScale } from "./Distribution";
import type { PanelResult } from "./index";
import { fmtNum } from "./Table";

/** Optimisation direction of one axis. */
export type Dir = "min" | "max";
/** One group's scatter row (contract 1.6). */
export type { ScatterRow };

/**
 * Vertices of the Pareto staircase in data space.
 *
 * Points are sorted by x. When lower x is better (`xDir = "min"`) each step goes across then
 * up/down; when higher x is better it goes up/down then across. `tailTo` extends the line to
 * the far edge of the x domain on the dominated side.
 */
export function paretoPath(
  front: { x: number; y: number }[],
  xDir: Dir,
  tailTo?: number,
): [number, number][] {
  if (front.length === 0) return [];
  const pts = [...front].sort((a, b) => a.x - b.x);
  const out: [number, number][] = [[pts[0].x, pts[0].y]];
  for (const p of pts.slice(1)) {
    const prev = out[out.length - 1];
    if (xDir === "min") out.push([p.x, prev[1]], [p.x, p.y]);
    else out.push([prev[0], p.y], [p.x, p.y]);
  }
  if (tailTo !== undefined) {
    if (xDir === "min") out.push([tailTo, out[out.length - 1][1]]);
    else out.unshift([tailTo, out[0][1]]);
  }
  return out;
}

/** Index of the best row: `bestGroup` if given, else best y for `yDir`; -1 if empty. */
export function bestIndex(rows: ScatterRow[], yDir: Dir, bestGroup?: string): number {
  if (bestGroup !== undefined) return rows.findIndex((r) => r.group_id === bestGroup);
  let best = -1;
  rows.forEach((r, i) => {
    if (best < 0 || (yDir === "max" ? r.y > rows[best].y : r.y < rows[best].y)) best = i;
  });
  return best;
}

function dirOf(v: unknown, fallback: Dir): Dir {
  return v === "min" || v === "max" ? v : fallback;
}

const W = 640;
const H = 360;
const PL = 52;
const PR = 16;
const PT = 26;
const PB = 44;

const T = {
  tk: { fontSize: 11.5, fill: "var(--ink-3)", fontVariantNumeric: "tabular-nums" },
  lbl: { fontSize: 12.5, fill: "var(--ink-2)" },
  lblB: { fontSize: 12.5, fill: "var(--ink)", fontWeight: 600 },
  lblBest: { fontSize: 12.5, fill: "var(--best)", fontWeight: 600 },
  lblS: { fontSize: 11.5, fill: "var(--ink-3)" },
  axis: { stroke: "var(--ink-3)", strokeWidth: 1 },
  grid: { stroke: "var(--rule-2)", strokeWidth: 1 },
  whisk: { stroke: "var(--ink-3)", strokeWidth: 1.5, strokeLinecap: "round", fill: "none" },
  pareto: { stroke: "var(--ink)", strokeWidth: 1.4, fill: "none", strokeDasharray: "5 4" },
  seed: { fill: "var(--ink-3)", stroke: "var(--paper)", strokeWidth: 1.5 },
  reg: { fontSize: 10, fill: "var(--fail)" },
  key: {
    display: "flex",
    flexWrap: "wrap",
    gap: "6px 20px",
    marginTop: 14,
    fontSize: 13,
    color: "var(--ink-2)",
  },
  keyItem: { display: "inline-flex", alignItems: "center", gap: 7 },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
} satisfies Record<string, CSSProperties>;

function meanStyle(best: boolean, dominated: boolean, regressed = false): CSSProperties {
  if (regressed) return { fill: "var(--fail)", stroke: "var(--paper)", strokeWidth: 2 };
  if (best) return { fill: "var(--best)", stroke: "var(--paper)", strokeWidth: 2 };
  if (dominated) return { fill: "var(--paper)", stroke: "var(--ink-3)", strokeWidth: 1.6 };
  return { fill: "var(--ink)", stroke: "var(--paper)", strokeWidth: 2 };
}

const range = (lo: number | null, hi: number | null) =>
  lo !== null && hi !== null ? ` [${fmtNum(lo)}, ${fmtNum(hi)}]` : "";

const REGRESSION_TIP = "regression vs best earlier version";

/** A number, or null for ordinal (text) values. */
const numeric = (v: number | string | null): number | null => (typeof v === "number" ? v : null);

/**
 * Scatter panel. Reads `meta.x_label`, `meta.y_label` (else the backend's refs `meta.x`,
 * `meta.y`), `meta.scale` (x axis), `meta.x_type` (`"ordinal"`: text x in row order),
 * `meta.pareto` (`{x, y}` directions, default `{x: "min", y: "max"}`) and `meta.best_group`.
 */
export function ScatterPanel({ result }: { result: PanelResult }) {
  const rows = result.rows as unknown as ScatterRow[];
  const meta = (result.meta ?? {}) as Record<string, unknown>;
  if (rows.length === 0) return <p style={T.empty}>No data</p>;
  const dirs = (meta.pareto ?? {}) as Record<string, unknown>;
  const xDir = dirOf(dirs.x, "min");
  const yDir = dirOf(dirs.y, "max");
  const kind = meta.scale === "log" ? "log" : "linear";
  const label = (...keys: string[]) => {
    const hit = keys.map((k) => meta[k]).find((v) => typeof v === "string" && v !== "");
    return typeof hit === "string" ? hit : null;
  };
  const xLabel = label("x_label", "x") ?? "x";
  const yLabel = label("y_label", "y") ?? "y";
  const best = bestIndex(
    rows,
    yDir,
    typeof meta.best_group === "string" ? meta.best_group : undefined,
  );

  const ordinal = meta.x_type === "ordinal";
  const nums = (vs: (number | null)[]) => vs.filter((v): v is number => v !== null);
  const xs = ordinal
    ? []
    : rows.flatMap((r) =>
        nums([numeric(r.x), r.x_lo, r.x_hi, ...r.seeds.map((s) => numeric(s.x))]),
      );
  const ys = rows.flatMap((r) => nums([r.y, r.y_lo, r.y_hi, ...r.seeds.map((s) => s.y)]));
  const { domain: xDom, ticks: xTicks } = xAxis(kind, xs);
  const X = xScale(kind, xDom, [PL, W - PR]);
  // ordinal: one equal band per row, in row order (the engine sorts versions naturally)
  const band = (W - PR - PL) / rows.length;
  const bandX = (i: number) => PL + (i + 0.5) * band;
  const yLo = Math.min(...ys);
  const yHi = Math.max(...ys);
  const ys0 = scaleLinear()
    .domain([yLo, yHi === yLo ? yLo + 1 : yHi])
    .nice(5);
  const Y = scaleLinear()
    .domain(ys0.domain())
    .range([H - PB, PT]);
  const yTicks = ys0.ticks(5);

  const front = ordinal
    ? []
    : rows.flatMap((r) => (r.pareto && typeof r.x === "number" ? [{ x: r.x, y: r.y }] : []));
  const regressions = ordinal ? rows.filter((r) => r.regression).length : 0;
  const stairs = paretoPath(front, xDir, xDir === "min" ? xDom[1] : xDom[0]);
  const stairsD = stairs
    .map(([x, y], i) => `${i ? "L" : "M"}${X(x).toFixed(1)} ${Y(y).toFixed(1)}`)
    .join("");

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        aria-label={`${xLabel} against ${yLabel}; ${front.length} of ${rows.length} on the Pareto front`}
        style={{ display: "block", overflow: "visible", fontFamily: "var(--sans)" }}
      >
        <text x={PL} y={PT - 12} style={T.lblS}>
          {yLabel}
        </text>
        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line x1={PL} x2={W - PR} y1={Y(t)} y2={Y(t)} style={T.grid} />
            <text x={PL - 8} y={Y(t) + 4} textAnchor="end" style={T.tk}>
              {fmtTick(t)}
            </text>
          </g>
        ))}
        <line x1={PL} x2={W - PR} y1={H - PB} y2={H - PB} style={T.axis} />
        {ordinal
          ? rows.map((r, i) => (
              <g key={`x${r.group_id}`}>
                <line x1={bandX(i)} x2={bandX(i)} y1={H - PB} y2={H - PB + 4} style={T.axis} />
                <text
                  data-tick={String(r.x)}
                  x={bandX(i)}
                  y={H - PB + 17}
                  textAnchor="middle"
                  style={T.tk}
                >
                  {String(r.x)}
                </text>
              </g>
            ))
          : xTicks.map((t) => (
              <g key={`x${t}`}>
                <line x1={X(t)} x2={X(t)} y1={H - PB} y2={H - PB + 4} style={T.axis} />
                <text
                  data-tick={fmtTick(t)}
                  x={X(t)}
                  y={H - PB + 17}
                  textAnchor="middle"
                  style={T.tk}
                >
                  {fmtTick(t)}
                </text>
              </g>
            ))}
        <text x={W - PR} y={H - PB + 36} textAnchor="end" style={T.lblS}>
          {kind === "log" && !ordinal ? `${xLabel}, log` : xLabel}
        </text>
        {stairsD && <path data-testid="pareto" d={stairsD} style={T.pareto} />}
        {rows.map((r, i) => {
          const x = ordinal ? bandX(i) : X(Number(r.x));
          const y = Y(r.y);
          const isBest = i === best;
          const dominated = !ordinal && !r.pareto;
          const regressed = ordinal && r.regression;
          const right = x + 12 + r.label.length * 7 <= W - PR;
          const xLine = ordinal
            ? `${xLabel} ${r.x}`
            : `${xLabel} ${fmtNum(Number(r.x))}${range(r.x_lo, r.x_hi)}`;
          const status = ordinal
            ? regressed
              ? `, ${REGRESSION_TIP}`
              : ""
            : `, ${r.pareto ? "on the Pareto front" : "dominated"}`;
          return (
            <g key={r.group_id} data-group={r.group_id}>
              {r.seeds.map((s, k) => (
                <circle
                  key={k}
                  data-seed=""
                  cx={ordinal ? x : X(Number(s.x))}
                  cy={Y(s.y)}
                  r={3.2}
                  style={T.seed}
                />
              ))}
              {r.y_lo !== null && r.y_hi !== null && (
                <path
                  data-testid="ywhisk"
                  d={`M${x} ${Y(r.y_lo)}V${Y(r.y_hi)}M${x - 4} ${Y(r.y_lo)}H${x + 4}M${x - 4} ${Y(r.y_hi)}H${x + 4}`}
                  style={{ ...T.whisk, ...(isBest ? { stroke: "var(--best)" } : {}) }}
                />
              )}
              {r.x_lo !== null && r.x_hi !== null && (
                <path
                  data-testid="xwhisk"
                  d={`M${X(r.x_lo)} ${y}H${X(r.x_hi)}M${X(r.x_lo)} ${y - 4}V${y + 4}M${X(r.x_hi)} ${y - 4}V${y + 4}`}
                  style={{ ...T.whisk, ...(isBest ? { stroke: "var(--best)" } : {}) }}
                />
              )}
              <rect
                data-testid="mean"
                data-pareto={r.pareto ? "true" : "false"}
                data-best={isBest ? "true" : "false"}
                data-regression={regressed ? "true" : "false"}
                x={x - 5}
                y={y - 5}
                width={10}
                height={10}
                rx={1.5}
                style={meanStyle(isBest, dominated, regressed)}
              />
              {regressed && (
                <g data-testid="regression">
                  <text x={x} y={y + 19} textAnchor="middle" style={T.reg}>
                    ▼
                  </text>
                  <title>{REGRESSION_TIP}</title>
                </g>
              )}
              <text
                x={right ? x + 12 : x - 12}
                y={y - 8}
                textAnchor={right ? "start" : "end"}
                style={isBest ? T.lblBest : dominated ? T.lbl : T.lblB}
              >
                {r.label}
              </text>
              <rect x={x - 14} y={y - 14} width={28} height={28} style={{ fill: "transparent" }}>
                <title>
                  {`${r.label}\n${yLabel} ${fmtNum(r.y)}${range(r.y_lo, r.y_hi)}\n` +
                    `${xLine}\n${r.seeds.length} seeds${status}`}
                </title>
              </rect>
            </g>
          );
        })}
      </svg>
      <div style={T.key} aria-label="Key">
        <span style={T.keyItem}>
          <svg width="12" height="16" aria-hidden="true">
            <path d="M6 1V15M2 1H10M2 15H10" style={T.whisk} />
            <rect x="2" y="4" width="8" height="8" rx="1.5" style={meanStyle(false, false)} />
          </svg>
          mean, 95% CI
        </span>
        <span style={T.keyItem}>
          <svg width="12" height="12" aria-hidden="true">
            <circle cx="6" cy="6" r="3.2" style={T.seed} />
          </svg>
          seed
        </span>
        {!ordinal && (
          <span style={T.keyItem} title="No other group is better on both axes">
            <svg width="22" height="12" aria-hidden="true">
              <path d="M1 10H11V2H21" style={T.pareto} />
            </svg>
            Pareto
          </span>
        )}
        {!ordinal && (
          <span style={T.keyItem} title="Another group is at least as good on both axes">
            <svg width="12" height="12" aria-hidden="true">
              <rect x="2" y="2" width="8" height="8" rx="1.5" style={meanStyle(false, true)} />
            </svg>
            dominated
          </span>
        )}
        {regressions > 0 && (
          <span
            style={T.keyItem}
            title="Worse than the best earlier version by more than that version's 95% CI"
          >
            <svg width="12" height="12" aria-hidden="true">
              <path d="M1 2H11L6 10Z" style={{ fill: "var(--fail)" }} />
            </svg>
            regression
          </span>
        )}
      </div>
    </div>
  );
}

export default ScatterPanel;
```

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && bun test test/panels/Scatter.test.tsx && bunx tsc --noEmit -p .`
Expected: PASS, `13 pass`, `0 fail`; `tsc` prints nothing and exits 0.

- [ ] **Step 5: Commit**

```bash
git add ui/src/panels/Scatter.tsx ui/test/panels/Scatter.test.tsx
git commit -m "feat(ui): scatter panel with seed dots, pareto front, and ordinal regressions"
```

### Task 19: Grid panel (items x groups)

**Files:**
- Create: `ui/src/panels/Grid.tsx`
- Test: `ui/test/panels/Grid.test.tsx`

**Interfaces:**
- Consumes: `PanelResult` from `ui/src/panels/index.ts` (Task 11; fields `type`, `title`, `rows`, optional `meta`); `fmtNum` (`./Table`, Task 14). Rows `{item_id, group_id, value}` (value = share of seeds solved, 0..1); `meta.items` ordered by mean value ascending (hardest first), `meta.groups: [{group_id, label}]` (contract 1.6 `grid`).
- Produces: `GridPanel({ result })` (default export too); `gridLayout(rows, meta): {items, groups, cells}` (meta order wins; unknown items are appended by difficulty, unknown groups by id); `cellFill(v): string` (`var(--paper-2)` at 0, `var(--ink)` at 1, `color-mix(in srgb, var(--ink) round(87v)%, var(--paper))` in between); `cellKey(groupId, itemId)`; types `GridRow` (re-exported from the Task 3 models), `GridGroup`, `GridLayout`. Geometry: viewBox 720 wide, label column 150.

- [ ] **Step 1: Write the failing test**

`ui/test/panels/Grid.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import type { PanelResult } from "../../src/panels/index";
import { cellFill, cellKey, GridPanel, type GridRow, gridLayout } from "../../src/panels/Grid";

afterEach(cleanup);

const ROWS: GridRow[] = [
  { item_id: "t1", group_id: "gA", value: 1 },
  { item_id: "t2", group_id: "gA", value: 2 / 3 },
  { item_id: "t3", group_id: "gA", value: 1 / 3 },
  { item_id: "t1", group_id: "gB", value: 1 },
  { item_id: "t2", group_id: "gB", value: 0 },
  { item_id: "t3", group_id: "gB", value: 0 },
];
// mean per item: t3 = 1/6, t2 = 1/3, t1 = 1 -> hardest first: t3, t2, t1
const META = {
  items: ["t3", "t2", "t1"],
  groups: [
    { group_id: "gA", label: "mcts" },
    { group_id: "gB", label: "greedy" },
  ],
};

const grid = (meta: Record<string, unknown>, rows: GridRow[] = ROWS): PanelResult => ({
  type: "grid",
  title: "Per target",
  rows: rows as unknown as Record<string, unknown>[],
  meta,
});

describe("cellFill", () => {
  test("paper at 0, ink at 1, mixed in between", () => {
    expect(cellFill(0)).toBe("var(--paper-2)");
    expect(cellFill(1)).toBe("var(--ink)");
    expect(cellFill(1 / 3)).toBe("color-mix(in srgb, var(--ink) 29%, var(--paper))");
    expect(cellFill(2 / 3)).toBe("color-mix(in srgb, var(--ink) 58%, var(--paper))");
    expect(cellFill(0.5)).toBe("color-mix(in srgb, var(--ink) 44%, var(--paper))");
  });
});

describe("gridLayout", () => {
  test("uses meta order when given", () => {
    const g = gridLayout(ROWS, META);
    expect(g.items).toEqual(["t3", "t2", "t1"]);
    expect(g.groups.map((x) => x.label)).toEqual(["mcts", "greedy"]);
    expect(g.cells.get(cellKey("gA", "t2"))).toBeCloseTo(2 / 3, 12);
  });

  test("derives difficulty order and group ids without meta", () => {
    const g = gridLayout(ROWS, {});
    expect(g.items).toEqual(["t3", "t2", "t1"]);
    expect(g.groups).toEqual([
      { group_id: "gA", label: "gA" },
      { group_id: "gB", label: "gB" },
    ]);
  });

  test("appends items and groups missing from meta", () => {
    const g = gridLayout([...ROWS, { item_id: "t4", group_id: "gC", value: 0.5 }], META);
    expect(g.items).toEqual(["t3", "t2", "t1", "t4"]);
    expect(g.groups.map((x) => x.group_id)).toEqual(["gA", "gB", "gC"]);
  });
});

describe("GridPanel", () => {
  test("one cell per row, columns in meta order, fills by value", () => {
    const { container } = render(<GridPanel result={grid(META)} />);
    expect(container.querySelectorAll("rect[data-item]").length).toBe(6);
    const gA = container.querySelector('[data-group="gA"]') as Element;
    const cells = [...gA.querySelectorAll("rect[data-item]")] as SVGElement[];
    expect(cells.map((c) => c.getAttribute("data-item"))).toEqual(["t3", "t2", "t1"]);
    expect(cells.map((c) => c.style.fill)).toEqual([
      "color-mix(in srgb, var(--ink) 29%, var(--paper))",
      "color-mix(in srgb, var(--ink) 58%, var(--paper))",
      "var(--ink)",
    ]);
    // x = 150 + j * (720 - 150) / 3
    expect(cells.map((c) => Number(c.getAttribute("x")))).toEqual([150, 340, 530]);
  });

  test("group labels in order with solved counts", () => {
    const { container } = render(<GridPanel result={grid(META)} />);
    const labels = [...container.querySelectorAll("[data-group]")].map(
      (g) => g.querySelector("text")?.textContent,
    );
    expect(labels).toEqual(["mcts", "greedy"]);
    const solved = [...container.querySelectorAll("[data-solved]")].map((t) =>
      t.getAttribute("data-solved"),
    );
    expect(solved).toEqual(["2", "1"]);
  });

  test("cell tooltips and axis ends", () => {
    const { container } = render(<GridPanel result={grid(META)} />);
    const titles = [...container.querySelectorAll("title")].map((t) => t.textContent);
    expect(titles).toContain("t2\nmcts: 0.667 of seeds solved");
    expect(screen.getByText("hard")).toBeTruthy();
    expect(screen.getByText("easy")).toBeTruthy();
  });

  test("empty result says so", () => {
    render(<GridPanel result={grid({}, [])} />);
    expect(screen.getByText("No items")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/panels/Grid.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/panels/Grid' from '.../ui/test/panels/Grid.test.tsx'`.

- [ ] **Step 3: Write the implementation**

`ui/src/panels/Grid.tsx`:

```tsx
/**
 * Grid panel: items x groups outcome matrix. Each cell is the fraction of seeds that solved
 * the item; darker is more. Columns run hardest (left) to easiest (right).
 */
import type { CSSProperties } from "react";
import type { GridRow } from "../api/models";
import type { PanelResult } from "./index";
import { fmtNum } from "./Table";

/** One grid cell (contract 1.6). */
export type { GridRow };
/** A group with its display label. */
export type GridGroup = { group_id: string; label: string };
/** Everything needed to draw the grid. */
export type GridLayout = { items: string[]; groups: GridGroup[]; cells: Map<string, number> };

/** Map key of one cell. */
export const cellKey = (groupId: string, itemId: string): string => `${groupId}\u0000${itemId}`;

/** Cell colour: paper for 0, ink for 1, ink mixed into paper in between (1/3 -> 29%). */
export function cellFill(v: number): string {
  if (v <= 0) return "var(--paper-2)";
  if (v >= 1) return "var(--ink)";
  return `color-mix(in srgb, var(--ink) ${Math.round(v * 87)}%, var(--paper))`;
}

function byDifficulty(rows: GridRow[]): string[] {
  const acc = new Map<string, { sum: number; n: number }>();
  for (const r of rows) {
    const a = acc.get(r.item_id) ?? { sum: 0, n: 0 };
    a.sum += r.value;
    a.n += 1;
    acc.set(r.item_id, a);
  }
  const mean = (id: string) => {
    const a = acc.get(id);
    return a ? a.sum / a.n : 0;
  };
  return [...acc.keys()].sort(
    (a, b) => mean(a) - mean(b) || a.localeCompare(b, "en", { numeric: true }),
  );
}

/**
 * Resolve item order, group order and cell values.
 *
 * `meta.items` and `meta.groups` win when present; items or groups seen only in rows are
 * appended (items by difficulty, groups labelled by id).
 */
export function gridLayout(rows: GridRow[], meta: Record<string, unknown>): GridLayout {
  const metaItems = Array.isArray(meta.items)
    ? meta.items.filter((v): v is string => typeof v === "string")
    : [];
  const items = [...metaItems];
  const seenItems = new Set(items);
  for (const id of byDifficulty(rows)) if (!seenItems.has(id)) items.push(id);

  const groups: GridGroup[] = [];
  const seenGroups = new Set<string>();
  if (Array.isArray(meta.groups)) {
    for (const g of meta.groups as Partial<GridGroup>[]) {
      if (typeof g?.group_id === "string" && !seenGroups.has(g.group_id)) {
        groups.push({
          group_id: g.group_id,
          label: typeof g.label === "string" ? g.label : g.group_id,
        });
        seenGroups.add(g.group_id);
      }
    }
  }
  for (const r of rows) {
    if (!seenGroups.has(r.group_id)) {
      groups.push({ group_id: r.group_id, label: r.group_id });
      seenGroups.add(r.group_id);
    }
  }
  const cells = new Map<string, number>();
  for (const r of rows) cells.set(cellKey(r.group_id, r.item_id), r.value);
  return { items, groups, cells };
}

const W = 720;
const LW = 150;
const TOP = 24;
const RH = 24;
const CH = 18;

const T = {
  tk: { fontSize: 11.5, fill: "var(--ink-3)", fontVariantNumeric: "tabular-nums" },
  lbl: { fontSize: 12.5, fill: "var(--ink-2)" },
  lblS: { fontSize: 11.5, fill: "var(--ink-3)" },
  key: {
    display: "flex",
    flexWrap: "wrap",
    gap: "6px 20px",
    marginTop: 14,
    fontSize: 13,
    color: "var(--ink-2)",
    alignItems: "center",
  },
  keyItem: { display: "inline-flex", alignItems: "center", gap: 7 },
  sw: { width: 10, height: 10, borderRadius: 2, display: "inline-block" },
  empty: { fontSize: 13, color: "var(--ink-3)", margin: 0 },
} satisfies Record<string, CSSProperties>;

/** Grid panel. Reads `meta.items` (hardest first) and `meta.groups`. */
export function GridPanel({ result }: { result: PanelResult }) {
  const rows = result.rows as unknown as GridRow[];
  const meta = (result.meta ?? {}) as Record<string, unknown>;
  if (rows.length === 0) return <p style={T.empty}>No items</p>;
  const { items, groups, cells } = gridLayout(rows, meta);
  const cw = (W - LW) / items.length;
  const gap = cw > 4 ? 1 : 0;
  const yb = TOP + groups.length * RH + 14;

  return (
    <div>
      <svg
        viewBox={`0 0 ${W} ${yb + 6}`}
        width="100%"
        role="img"
        aria-label={`Share of seeds solved for ${items.length} items by ${groups.length} groups`}
        style={{ display: "block", overflow: "visible", fontFamily: "var(--sans)" }}
      >
        <text x={LW - 12} y={TOP - 10} textAnchor="end" style={T.lblS}>
          solved
        </text>
        {groups.map((g, r) => {
          const y = TOP + r * RH;
          const solved = items.reduce(
            (acc, id) => acc + (cells.get(cellKey(g.group_id, id)) ?? 0),
            0,
          );
          return (
            <g key={g.group_id} data-group={g.group_id}>
              <text x={0} y={y + CH / 2 + 4} style={T.lbl}>
                {g.label}
              </text>
              <text
                data-solved={Math.round(solved)}
                x={LW - 12}
                y={y + CH / 2 + 4}
                textAnchor="end"
                style={T.tk}
              >
                <title>{`${fmtNum(solved)} items solved on average over seeds`}</title>
                {Math.round(solved)}
              </text>
              {items.map((id, j) => {
                const v = cells.get(cellKey(g.group_id, id));
                if (v === undefined) return null;
                return (
                  <rect
                    key={id}
                    data-item={id}
                    x={LW + j * cw}
                    y={y}
                    width={Math.max(1, cw - gap)}
                    height={CH}
                    style={{ fill: cellFill(v) }}
                  >
                    <title>{`${id}\n${g.label}: ${fmtNum(v)} of seeds solved`}</title>
                  </rect>
                );
              })}
            </g>
          );
        })}
        <text x={LW} y={yb} style={T.lblS}>
          hard
        </text>
        <text x={W} y={yb} textAnchor="end" style={T.lblS}>
          easy
        </text>
      </svg>
      <div style={T.key} aria-label="Key">
        {[0, 0.5, 1].map((v) => (
          <span key={v} style={T.keyItem}>
            <i
              style={{
                ...T.sw,
                background: cellFill(v),
                ...(v === 0 ? { outline: "1px solid var(--rule)", outlineOffset: -1 } : {}),
              }}
            />
            {v}
          </span>
        ))}
        <span style={{ color: "var(--ink-3)" }}>share of seeds solved</span>
      </div>
    </div>
  );
}

export default GridPanel;
```

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && bun test test/panels/Grid.test.tsx && bunx tsc --noEmit -p .`
Expected: PASS, `8 pass`, `0 fail`; `tsc` prints nothing and exits 0.

- [ ] **Step 5: Commit**

```bash
git add ui/src/panels/Grid.tsx ui/test/panels/Grid.test.tsx
git commit -m "feat(ui): items by groups grid panel"
```

### Task 20: Vega-Lite panel (injected rows, theme-aware config)

**Files:**
- Create: `ui/src/panels/VegaLite.tsx`
- Modify: `ui/src/panels/index.ts` (register the seven Part 3 panels), `ui/test/panels/index.test.tsx` (append a test), `ui/package.json`, `ui/bun.lock` (Vega packages)
- Test: `ui/test/panels/VegaLite.test.tsx`

**Interfaces:**
- Consumes: `PanelResult` from `ui/src/panels/index.ts` (Task 11; fields `type`, `title`, `rows`, optional `meta`); `SERIES_LIGHT`, `SERIES_DARK` (`./Distribution`, Task 17); `vega-embed` default export `embed(el, spec, opts): Promise<Result>`. `meta.spec` is the view's Vega-Lite spec with `data.values` empty (contract 1.6 `vega_lite`); `rows` are the `iter_rows` dicts restricted to `fields`.
- Produces: `VegaLitePanel({ result })` (default export too); `buildSpec(spec, rows, config): object` (row copies go into `data.values`, `url`/`name` are dropped, the theme is merged under the spec's own `config`, a single view gets `width: "container"`, the input is not changed); `themeConfig(tokens, theme)`; `readTokens(theme, getVar?)`; `TOKEN_FALLBACK`; `deepMerge(base, over)`; `cssVar(name)`. The colour mode comes from `useTheme` (Task 5), so the header toggle and the ⌘K command both re-theme the chart. Task 20 also registers every Part 3 panel in `PANELS`. Embed options: `{actions: false, renderer: "svg"}`. The previous view is finalized on re-render and on unmount. Errors show in a `role="alert"` box.

- [ ] **Step 1: Install Vega and write the failing test**

Run: `cd ui && bun add vega vega-lite vega-embed`
Expected: `installed` lines for the three packages.

`ui/test/panels/VegaLite.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { setTheme } from "../../src/shell/ThemeToggle";
import type { PanelResult } from "../../src/panels/index";

type Obj = Record<string, unknown>;

const finalize = mock(() => {});
const embedMock = mock(async (_el: HTMLElement, spec: unknown, _opts: unknown) => ({
  finalize,
  spec,
  view: {},
}));
mock.module("vega-embed", () => ({ default: embedMock }));

const { buildSpec, deepMerge, readTokens, themeConfig, TOKEN_FALLBACK, VegaLitePanel } =
  await import("../../src/panels/VegaLite");

beforeEach(() => {
  embedMock.mockClear();
  finalize.mockClear();
  delete document.documentElement.dataset.theme;
});
afterEach(cleanup);

const SPEC = {
  mark: "point",
  encoding: { x: { field: "a", type: "quantitative" } },
  data: { values: [] },
};
const ROWS = [{ a: 1 }, { a: 2 }];
const vega = (meta: Obj, rows: Obj[] = ROWS): PanelResult => ({
  type: "vega_lite",
  title: "Solved by depth",
  rows,
  meta,
});
const lastSpec = () => embedMock.mock.calls.at(-1)?.[1] as Obj;
const axisOf = (spec: Obj) => (spec.config as Obj).axis as Obj;

describe("deepMerge", () => {
  test("merges nested objects; arrays and scalars replace", () => {
    expect(
      deepMerge(
        { axis: { labelColor: "a", labelFontSize: 11 }, range: { category: ["x"] } },
        { axis: { labelFontSize: 20 }, range: { category: ["y", "z"] } },
      ),
    ).toEqual({ axis: { labelColor: "a", labelFontSize: 20 }, range: { category: ["y", "z"] } });
  });
});

describe("buildSpec", () => {
  const theme = themeConfig(TOKEN_FALLBACK.light, "light");

  test("injects copies of rows, keeps user config on top, fills container width", () => {
    const spec = { ...SPEC, config: { axis: { labelFontSize: 20 } } };
    const out = buildSpec(spec, ROWS, theme);
    const values = (out.data as Obj).values as Obj[];
    expect(values).toEqual(ROWS);
    expect(values[0]).not.toBe(ROWS[0]);
    expect(axisOf(out).labelFontSize).toBe(20);
    expect(axisOf(out).labelColor).toBe("#767C87");
    expect(out.width).toBe("container");
    expect(out.$schema).toBe("https://vega.github.io/schema/vega-lite/v5.json");
    expect((spec.data as Obj).values).toEqual([]);
  });

  test("multi-view specs keep their own width; url and name are dropped", () => {
    const out = buildSpec({ hconcat: [], data: { url: "x.csv", name: "d" } }, ROWS, theme);
    expect("width" in out).toBe(false);
    expect(out.data).toEqual({ values: ROWS });
  });
});

describe("tokens and theme", () => {
  test("readTokens falls back per theme and trims values it can read", () => {
    expect(readTokens("dark", () => "")).toEqual(TOKEN_FALLBACK.dark);
    const t = readTokens("light", (n) => (n === "--ink" ? " #101010 " : ""));
    expect(t.ink).toBe("#101010");
    expect(t.ink3).toBe("#767C87");
  });

  test("themeConfig uses the mode's colours and series order", () => {
    const dark = themeConfig(TOKEN_FALLBACK.dark, "dark");
    expect((dark.axis as Obj).labelColor).toBe("#7C8490");
    expect(((dark.range as Obj).category as string[])[0]).toBe("#4a90e8");
    expect((dark.range as Obj).ramp).toEqual(["#1A1F27", "#1FA282"]);
  });
});

describe("VegaLitePanel", () => {
  test("embeds the spec with rows and the light theme", async () => {
    render(<VegaLitePanel result={vega({ spec: SPEC })} />);
    await waitFor(() => expect(embedMock).toHaveBeenCalledTimes(1));
    const [el, spec, opts] = embedMock.mock.calls[0];
    expect(el).toBe(screen.getByTestId("vega"));
    expect((spec as Obj).data).toEqual({ values: ROWS });
    expect(opts).toEqual({ actions: false, renderer: "svg" });
    expect(axisOf(spec as Obj).labelColor).toBe("#767C87");
  });

  test("re-embeds with dark colours when the theme flips, and cleans up", async () => {
    const { unmount } = render(<VegaLitePanel result={vega({ spec: SPEC })} />);
    await waitFor(() => expect(embedMock).toHaveBeenCalledTimes(1));
    act(() => {
      setTheme("dark");
    });
    await waitFor(() => expect(embedMock).toHaveBeenCalledTimes(2));
    expect(axisOf(lastSpec()).labelColor).toBe("#7C8490");
    expect(finalize).toHaveBeenCalledTimes(1);
    unmount();
    expect(finalize).toHaveBeenCalledTimes(2);
  });

  test("shows the embed error", async () => {
    embedMock.mockImplementationOnce(async () => {
      throw new Error("bad spec");
    });
    render(<VegaLitePanel result={vega({ spec: SPEC })} />);
    expect((await screen.findByRole("alert")).textContent).toBe("Vega-Lite: bad spec");
  });

  test("missing spec says so and never embeds", () => {
    render(<VegaLitePanel result={vega({})} />);
    expect(screen.getByRole("alert").textContent).toBe("No Vega-Lite spec");
    expect(embedMock).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/panels/VegaLite.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/panels/VegaLite' from '.../ui/test/panels/VegaLite.test.tsx'`.

- [ ] **Step 3: Write the implementation**

`ui/src/panels/VegaLite.tsx`:

```tsx
/**
 * Vega-Lite panel: renders `meta.spec` with vega-embed, injecting the panel rows as
 * `data.values` and a Hypothex theme built from the current design tokens. Re-embeds when
 * the colour mode changes (`useTheme` from the shell).
 */
import embed, { type Result, type VisualizationSpec } from "vega-embed";
import { type CSSProperties, useEffect, useRef, useState } from "react";
import { type Theme, useTheme } from "../shell/ThemeToggle";
import { SERIES_DARK, SERIES_LIGHT } from "./Distribution";
import type { PanelResult } from "./index";

type Obj = Record<string, unknown>;

/** Design tokens the theme needs. */
export type Tokens = {
  paper: string;
  paper2: string;
  ink: string;
  ink2: string;
  ink3: string;
  rule: string;
  rule2: string;
  best: string;
  sans: string;
};

const SANS = '"Geist", ui-sans-serif, system-ui, sans-serif';

/** Token values from `tokens.css`, used when a CSS variable cannot be read. */
export const TOKEN_FALLBACK: Record<Theme, Tokens> = {
  light: {
    paper: "#F6F7F3",
    paper2: "#ECEEE8",
    ink: "#15181E",
    ink2: "#464C57",
    ink3: "#767C87",
    rule: "#D5D8D0",
    rule2: "#E4E6E0",
    best: "#00846A",
    sans: SANS,
  },
  dark: {
    paper: "#12161C",
    paper2: "#1A1F27",
    ink: "#E9ECEF",
    ink2: "#AEB5BF",
    ink3: "#7C8490",
    rule: "#2C333D",
    rule2: "#222830",
    best: "#1FA282",
    sans: SANS,
  },
};

const TOKEN_VARS: Record<keyof Tokens, string> = {
  paper: "--paper",
  paper2: "--paper-2",
  ink: "--ink",
  ink2: "--ink-2",
  ink3: "--ink-3",
  rule: "--rule",
  rule2: "--rule-2",
  best: "--best",
  sans: "--sans",
};

const MULTI_VIEW = ["facet", "hconcat", "vconcat", "concat", "repeat"];

function isPlain(v: unknown): v is Obj {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

/** Read a CSS custom property from `<html>`. */
export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name);
}

/** Resolve tokens to concrete colours (Vega cannot use `var(...)`). */
export function readTokens(theme: Theme, getVar: (name: string) => string = cssVar): Tokens {
  const out = { ...TOKEN_FALLBACK[theme] };
  for (const key of Object.keys(TOKEN_VARS) as (keyof Tokens)[]) {
    const v = getVar(TOKEN_VARS[key]).trim();
    if (v) out[key] = v;
  }
  return out;
}

/** Vega-Lite `config` matching the Hypothex figure style. */
export function themeConfig(t: Tokens, theme: Theme): Obj {
  return {
    background: "transparent",
    font: t.sans,
    view: { stroke: null },
    axis: {
      domainColor: t.ink3,
      tickColor: t.ink3,
      gridColor: t.rule2,
      labelColor: t.ink3,
      titleColor: t.ink2,
      labelFontSize: 11.5,
      titleFontSize: 12.5,
      titleFontWeight: 400,
    },
    legend: {
      labelColor: t.ink2,
      titleColor: t.ink3,
      labelFontSize: 12.5,
      titleFontSize: 12.5,
      titleFontWeight: 400,
    },
    header: { labelColor: t.ink2, titleColor: t.ink2 },
    title: { color: t.ink, fontSize: 14, fontWeight: 600 },
    mark: { color: t.ink },
    text: { color: t.ink },
    range: {
      category: [...(theme === "dark" ? SERIES_DARK : SERIES_LIGHT)],
      ramp: [t.paper2, t.best],
      heatmap: [t.paper2, t.best],
    },
  };
}

/** Recursively merge plain objects; arrays and scalars from `over` replace. */
export function deepMerge(base: Obj, over: Obj): Obj {
  const out: Obj = { ...base };
  for (const [k, v] of Object.entries(over)) {
    const cur = out[k];
    out[k] = isPlain(v) && isPlain(cur) ? deepMerge(cur, v) : v;
  }
  return out;
}

/**
 * Build the spec to embed: copies of `rows` become `data.values` (`url`/`name` are dropped),
 * the theme is merged under the spec's own `config`, and single views fill the container
 * width. The input spec is not modified.
 */
export function buildSpec(spec: Obj, rows: Obj[], config: Obj): Obj {
  const data = isPlain(spec.data) ? spec.data : {};
  const keep = Object.fromEntries(
    Object.entries(data).filter(([k]) => k !== "url" && k !== "name" && k !== "values"),
  );
  const out: Obj = {
    $schema: "https://vega.github.io/schema/vega-lite/v5.json",
    ...spec,
    data: { ...keep, values: rows.map((r) => ({ ...r })) },
    config: deepMerge(config, isPlain(spec.config) ? spec.config : {}),
  };
  if (!("width" in spec) && !MULTI_VIEW.some((k) => k in spec)) out.width = "container";
  return out;
}

const S = {
  err: {
    fontSize: 13,
    color: "var(--fail)",
    border: "1px solid var(--rule)",
    borderRadius: 6,
    padding: "8px 10px",
    margin: "0 0 8px",
  },
} satisfies Record<string, CSSProperties>;

/** Vega-Lite panel. Reads `meta.spec`. */
export function VegaLitePanel({ result }: { result: PanelResult }) {
  const ref = useRef<HTMLDivElement>(null);
  const theme = useTheme();
  const [error, setError] = useState<string | null>(null);
  const meta = (result.meta ?? {}) as Obj;
  const spec = isPlain(meta.spec) ? meta.spec : null;
  const rows = result.rows as Obj[];

  useEffect(() => {
    const el = ref.current;
    if (!el || !spec) return;
    let cancelled = false;
    let view: Result | null = null;
    setError(null);
    const full = buildSpec(spec, rows, themeConfig(readTokens(theme), theme));
    embed(el, full as VisualizationSpec, { actions: false, renderer: "svg" })
      .then((r) => {
        if (cancelled) r.finalize();
        else view = r;
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
      view?.finalize();
    };
  }, [spec, rows, theme]);

  if (!spec)
    return (
      <p role="alert" style={S.err}>
        No Vega-Lite spec
      </p>
    );
  return (
    <div>
      {error && (
        <p role="alert" style={S.err}>
          Vega-Lite: {error}
        </p>
      )}
      <div ref={ref} data-testid="vega" style={{ width: "100%" }} />
    </div>
  );
}

export default VegaLitePanel;
```

- [ ] **Step 4: Run the tests and the type check**

Run: `cd ui && bun test test/panels/VegaLite.test.tsx && bunx tsc --noEmit -p .`
Expected: PASS, `9 pass`, `0 fail`; `tsc` prints nothing and exits 0.

- [ ] **Step 5: Register the seven data panels**

Append to `ui/test/panels/index.test.tsx`:

```tsx
test("every contract panel type has a registered component", () => {
  const types = [
    "stat_strip",
    "leaderboard",
    "curves",
    "scatter",
    "distribution",
    "grid",
    "table",
    "trace",
    "markdown",
    "vega_lite",
  ];
  expect(types.filter((type) => panelFor(type) === null)).toEqual([]);
});
```

Run: `cd ui && bun test test/panels/index.test.tsx`
Expected: FAIL: `every contract panel type has a registered component` reports `["scatter", "distribution", "grid", "table", "trace", "markdown", "vega_lite"]`.

In `ui/src/panels/index.ts` replace

```ts
import { Curves } from "./Curves";
import { Leaderboard } from "./Leaderboard";
import { StatStrip } from "./StatStrip";
```

with

```ts
import { Curves } from "./Curves";
import { DistributionPanel } from "./Distribution";
import { GridPanel } from "./Grid";
import { Leaderboard } from "./Leaderboard";
import { MarkdownPanel } from "./Markdown";
import { ScatterPanel } from "./Scatter";
import { StatStrip } from "./StatStrip";
import { TablePanel } from "./Table";
import { TracePanel } from "./Trace";
import { VegaLitePanel } from "./VegaLite";
```

and replace

```ts
  curves: Curves,
};
```

with

```ts
  curves: Curves,
  scatter: ScatterPanel,
  distribution: DistributionPanel,
  grid: GridPanel,
  table: TablePanel,
  trace: TracePanel,
  markdown: MarkdownPanel,
  vega_lite: VegaLitePanel,
};
```

The Part 3 panels import only the `PanelResult` type from `./index`, so the registry and the panels have no runtime import cycle.

- [ ] **Step 6: Run the panel suite and the type check**

Run: `cd ui && bun test test/panels && bunx tsc --noEmit -p .`
Expected: every panel test passes, `0 fail`; `tsc` prints nothing. The existing `Panel contains a panel that throws` test still passes: it swaps `PANELS.table` and puts the registered `TablePanel` back.

- [ ] **Step 7: Commit**

```bash
git add ui/package.json ui/bun.lock ui/src/panels/VegaLite.tsx ui/test/panels/VegaLite.test.tsx ui/src/panels/index.ts ui/test/panels/index.test.tsx
git commit -m "feat(ui): vega-lite panel and registry entries for every data panel"
```

## Part 4: Pages: Overview, Task, Run, Examples (Tasks 21–37)

The four read-and-act screens of spec 8.3 on top of the shell (Part 1) and the panels (Parts 2 and 3): the Overview status page, the Task page with view tabs (`?view=<name>`), the Run page (common parts plus the kind's `run_view` panels from `GET /tasks/{p}/{t}/kind`), and the two-run Examples page. Every page has a one-line headline, lettered panels (a, b, c ...), terse labels with explanations only in `title` tooltips, and actions that send a client-made `command_id`. Mockups: `docs/mockups/ui-v4/` (overview, leaderboard, run, examples) and `docs/mockups/kinds/*/` (kind run screens, view tabs).

Pages take plain props and never import `router.tsx`:
- `ui/src/pages/Overview.tsx`: `OverviewPage()`
- `ui/src/pages/Task.tsx`: `TaskPage({ project, task, view? })`
- `ui/src/pages/Run.tsx`: `RunPage({ runId, log?, example? })`
- `ui/src/pages/Examples.tsx`: `ExamplesPage({ a, b, metric? })`

Each page task ends by wiring its page into `ui/src/router.tsx` (a small screen component that reads params and search and renders the page). Pages read data only through `api`, `queryKeys` and the hooks of Tasks 3–4, so the live event stream (Task 42) refreshes them. Building blocks live in `ui/src/pages/components/`; tests live in `ui/test/pages/` and share `fixtures.ts` and `helpers.tsx`. All commands in this part run from `ui/`.

### Task 21: Page shapes, run-status sets, and test fixtures

**Files:**
- Create: `ui/src/pages/components/types.ts`
- Create: `ui/test/pages/fixtures.ts` (shared fixtures from `docs/mockups/ui-v4/data.js`)
- Test: `ui/test/pages/types.test.ts`

**Interfaces:**
- Consumes: Task 3 `ui/src/api/models.ts` (every response shape; the one hand-written copy of the contract).
- Produces:
  - `types.ts`: re-exports every type in `models.ts`; adds `ViewDetail` (= `ViewDocument`), `QueryResponse` (= `ViewQueryResult`), `KindInfo` (= `TaskKindInfo`), `RunRef { run_id }`, and the sets `ACTIVE_STATUSES` (`queued`, `running`) and `FAILED_STATUSES` (`failed`, `killed`, `lost`). Page components import shapes from `./types` and fetch only through `api`, `queryKeys` and the hooks of Tasks 3–4.
  - `test/pages/fixtures.ts`: `RUN_SVM`, `RUN_RF`, `RUN_FAILED`, `STORE`, `REPO`, `SVM_HYPOTHESIS`, `makeRecord(over?)`, `makeDetail(over?, rest?)`, `makeBoard()`, `makeOverview()`, `makeDiff()`; every value type-checks against the models.

- [ ] **Step 1: Write the failing test**

`ui/test/pages/types.test.ts`:

```ts
import { expect, test } from "bun:test";
import { ACTIVE_STATUSES, FAILED_STATUSES, type RunStatus } from "../../src/pages/components/types";
import { makeBoard, makeDetail, makeOverview } from "./fixtures";

const ALL: RunStatus[] = ["queued", "running", "finished", "failed", "killed", "lost"];

test("every status is active, failed, or finished", () => {
  expect(ALL.filter((s) => ACTIVE_STATUSES.has(s))).toEqual(["queued", "running"]);
  expect(ALL.filter((s) => FAILED_STATUSES.has(s))).toEqual(["failed", "killed", "lost"]);
  expect(ALL.filter((s) => !ACTIVE_STATUSES.has(s) && !FAILED_STATUSES.has(s))).toEqual(["finished"]);
});

test("fixtures mirror the ui-v4 mockup numbers", () => {
  expect(makeDetail().record.run_id).toBe("20260926-210306-toy-test-6f71");
  expect(makeBoard().rows.map((r) => r.label)).toEqual(["RBF-kernel SVM", "Baseline rf"]);
  expect(makeOverview().headline).toBe("Idle. SVM leads toy-test by 0.037, p = 0.15");
});

test("the rf row's vs_best counts match the backend's _versus meaning", () => {
  // fixed = the best passes where this row fails; the SVM fixes 9 of rf's examples, breaks 3
  const rf = makeBoard().rows[1];
  expect(rf?.vs_best).toEqual({ delta: -0.037, p: 0.146, fixed: 9, broken: 3, test: "sign", examples_needed: 250 });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ui && bun test test/pages/types.test.ts`
Expected: FAIL with `Cannot find module './fixtures'`.

- [ ] **Step 3: Write the shapes and the fixtures**

`ui/src/pages/components/types.ts`:

```ts
/**
 * API shapes the pages read, and the run-status sets they share.
 *
 * Every shape comes from `ui/src/api/models.ts`, the single hand-written copy of the
 * phase 1b contract; this module only adds page names for three of them and the sets.
 */
import type { RunStatus, TaskKindInfo, ViewDocument, ViewQueryResult } from "../../api/models";

export type * from "../../api/models";

/** `GET .../views/{name}`: the stored YAML and the resolved view. */
export type ViewDetail = ViewDocument;
/** `POST .../views/query`. */
export type QueryResponse = ViewQueryResult;
/** `GET .../kind`: the task kind and its run-detail panels. */
export type KindInfo = TaskKindInfo;

/** The part of a `RunRecord` that rerun and re-infer answers are read for. */
export interface RunRef {
  run_id: string;
}

/** Statuses of a run that can still be stopped. */
export const ACTIVE_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>(["queued", "running"]);
/** Statuses drawn as a failure mark. */
export const FAILED_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "failed",
  "killed",
  "lost",
]);
```

`ui/test/pages/fixtures.ts` (numbers from `docs/mockups/ui-v4/data.js`):

```ts
import type {
  ExampleDiff,
  Leaderboard,
  OverviewSummary,
  RunDetail,
  RunRecord,
} from "../../src/pages/components/types";

export const RUN_SVM = "20260926-210306-toy-test-6f71";
export const RUN_RF = "20260926-210032-toy-test-ef4f";
export const RUN_FAILED = "20260926-210158-toy-test-58c5";
export const STORE = "/private/tmp/hx-accept/home/store/toy-classifier/runs";
export const REPO = "/private/tmp/hx-accept/toy";
export const SVM_HYPOTHESIS =
  "RBF-kernel SVM should beat RF/KNN/logreg because the class clusters are round";

export function makeRecord(over: Partial<RunRecord> = {}): RunRecord {
  const runId = over.run_id ?? RUN_SVM;
  return {
    run_id: runId,
    project: "toy-classifier",
    task: "toy-test",
    hypothesis: SVM_HYPOTHESIS,
    kind: "full",
    parent: null,
    stage: null,
    command: ["python", "train_eval.py", "--model", "svm", "--seed=3"],
    command_template: ["python", "train_eval.py", "--model", "svm", "--seed={seed}"],
    params: {},
    vars: {},
    cwd: REPO,
    environment_id: "env-5c1e",
    host: "mbp.local",
    executor: { type: "local", pid: null, pid_create_time: null, child_pid: null },
    git: {
      repo: null,
      commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
      branch: "main",
      dirty: false,
      untracked_count: 2,
      untracked: ["scratch.py", "notes.txt"],
    },
    datasets: [
      {
        name: "toyset",
        version: "v1",
        split: "test",
        host: "local",
        path: `${REPO}/data/test.jsonl`,
        hash: "xxh3:a6ff57960a911828",
        hash_mode: null,
        size: 26123,
        checked_at: null,
      },
    ],
    seed: 3,
    config_hash: "sha256:63c2ec5fb24db57e",
    status: "finished",
    created_at: "2026-09-26T21:03:06.685638Z",
    started_at: "2026-09-26T21:03:06.756813Z",
    ended_at: "2026-09-26T21:03:07.578937Z",
    exit_code: 0,
    artifacts: [
      {
        kind: "checkpoint",
        path: `${STORE}/${runId}/model.pkl`,
        host: "local",
        size: 18494,
        step: null,
        metrics: {},
      },
    ],
    tags: ["best", "svm"],
    starred: false,
    archived: false,
    created_by: "agent:acceptance",
    usage: null,
    ...over,
  };
}

export function makeDetail(over: Partial<RunRecord> = {}, rest: Partial<RunDetail> = {}): RunDetail {
  const record = makeRecord(over);
  const dir = `${STORE}/${record.run_id}`;
  return {
    record,
    scores: [
      {
        metric: "accuracy",
        version: "v1",
        key: "value",
        value: 0.9222222222222223,
        error: null,
        source_hash: "sha256:e662a37bb8a556fd",
        created_at: "2026-09-26T21:03:08.286629Z",
      },
      {
        metric: "macro_f1",
        version: "v1",
        key: "value",
        value: 0.9224758529636579,
        error: null,
        source_hash: "sha256:28127f3db7be711f",
        created_at: "2026-09-26T21:03:08.286629Z",
      },
    ],
    paths: {
      run_dir: dir,
      cwd: REPO,
      stdout: `${dir}/logs/stdout.log`,
      stderr: `${dir}/logs/stderr.log`,
      predictions: `${dir}/predictions`,
      env: `${dir}/env`,
      repo: REPO,
    },
    notes: "\n## 2026-09-26T21:03:56.036288+00:00 — agent:acceptance\n\nRBF SVM beats prior best (rf).\n",
    has_diff: false,
    metric_names: ["train_accuracy"],
    children: [],
    ...rest,
  };
}

export function makeBoard(): Leaderboard {
  return {
    project: "toy-classifier",
    task: "toy-test",
    primary: "accuracy/value",
    higher_is_better: true,
    metric_versions: { accuracy: "v1", macro_f1: "v1" },
    rows: [
      {
        group_id: "63c2ec5f@8f4cac4",
        run_ids: ["20260926-210302-toy-test-e294", "20260926-210304-toy-test-03bb", RUN_SVM],
        latest_run_id: RUN_SVM,
        hypothesis: SVM_HYPOTHESIS,
        label: "RBF-kernel SVM",
        commit: "8f4cac43877b75953f18ff1daf7e6fc54a5d8f37",
        config_hash: "sha256:63c2ec5fb24db57e",
        n: 3,
        scores: {},
        primary: {
          mean: 0.9222222222222222,
          std: 0,
          n: 3,
          ci_low: 0.9222222222222222,
          ci_high: 0.9222222222222222,
        },
        single_seed: false,
        within_noise_of_best: null,
        seed_values: { "accuracy/value": [0.9222222222222222, 0.9222222222222222, 0.9222222222222222] },
        identical_seeds: true,
        test_interval: { lo: 0.874, hi: 0.953, method: "wilson", n: 180 },
        vs_best: null,
        created_by: ["agent:acceptance"],
        usage: null,
      },
      {
        group_id: "5a810ddb@2bbf5a3",
        run_ids: ["20260926-210028-toy-test-b5c4", "20260926-210030-toy-test-2e66", RUN_RF],
        latest_run_id: RUN_RF,
        hypothesis: "baseline rf",
        label: "Baseline rf",
        commit: "2bbf5a3c81bfc657dea6d28bf0b3f057409602ad",
        config_hash: "sha256:5a810ddb4e0c2f19",
        n: 3,
        scores: {},
        primary: {
          mean: 0.8851851851851852,
          std: 0.006415002990995819,
          n: 3,
          ci_low: 0.8692481481481482,
          ci_high: 0.9011222222222222,
        },
        single_seed: false,
        within_noise_of_best: true,
        seed_values: { "accuracy/value": [0.8833333333333333, 0.8777777777777778, 0.8944444444444445] },
        identical_seeds: false,
        test_interval: { lo: 0.83, hi: 0.924, method: "wilson", n: 180 },
        // backend `_versus`: fixed = best passes and this row fails (the Task 12 fixture agrees)
        vs_best: { delta: -0.037, p: 0.146, fixed: 9, broken: 3, test: "sign", examples_needed: 250 },
        created_by: ["human"],
        usage: null,
      },
    ],
    needs_reeval: [],
    unscored: [],
    headline: "SVM +0.037 over rf, p = 0.15",
    kind: "generic",
    stat_strip: [],
  };
}

export function makeOverview(): OverviewSummary {
  const band = { lo: 0.874, hi: 0.953, method: "wilson" as const, n: 180 };
  return {
    headline: "Idle. SVM leads toy-test by 0.037, p = 0.15",
    counts: { "runs today": 19, failed: 3, task: 1 },
    timeline: [
      {
        run_id: RUN_SVM,
        project: "toy-classifier",
        task: "toy-test",
        created_at: "2026-09-26T21:03:06Z",
        created_by: "agent:acceptance",
        status: "finished",
        archived: false,
        group_id: "63c2ec5f@8f4cac4",
        is_best: true,
        label: "RBF-kernel SVM",
      },
      {
        run_id: RUN_FAILED,
        project: "toy-classifier",
        task: "toy-test",
        created_at: "2026-09-26T21:01:58Z",
        created_by: "agent:acceptance",
        status: "failed",
        archived: true,
        group_id: null,
        is_best: false,
        label: "RBF-kernel SVM",
      },
      {
        run_id: RUN_RF,
        project: "toy-classifier",
        task: "toy-test",
        created_at: "2026-09-26T21:00:32Z",
        created_by: "human",
        status: "finished",
        archived: false,
        group_id: "5a810ddb@2bbf5a3",
        is_best: false,
        label: "Baseline rf",
      },
    ],
    ideas: [
      {
        project: "toy-classifier",
        task: "toy-test",
        group_id: "63c2ec5f@8f4cac4",
        label: "RBF-kernel SVM",
        created_by: "agent:acceptance",
        created_at: "2026-09-26T21:03:06Z",
        statuses: ["finished", "finished", "finished"],
        primary: { mean: 0.9222222222222222, std: 0, n: 3, ci_low: null, ci_high: null },
        test_interval: band,
        identical_seeds: true,
        best_band: band,
      },
      {
        project: "toy-classifier",
        task: "toy-test",
        group_id: "63c2ec5f@0000000",
        label: "RBF-kernel SVM",
        created_by: "agent:acceptance",
        created_at: "2026-09-26T21:01:58Z",
        statuses: ["failed", "failed", "failed"],
        primary: null,
        test_interval: null,
        identical_seeds: false,
        best_band: band,
      },
      {
        project: "toy-classifier",
        task: "toy-test",
        group_id: "5a810ddb@2bbf5a3",
        label: "Baseline rf",
        created_by: "human",
        created_at: "2026-09-26T21:00:32Z",
        statuses: ["finished", "finished", "finished"],
        primary: { mean: 0.8851851851851852, std: 0.006415002990995819, n: 3, ci_low: null, ci_high: null },
        test_interval: { lo: 0.83, hi: 0.924, method: "wilson", n: 180 },
        identical_seeds: false,
        best_band: band,
      },
    ],
    running: [],
    failures: [
      {
        run_id: RUN_FAILED,
        label: "SVM",
        exit_code: 2,
        created_at: "2026-09-26T21:01:58Z",
        stderr_path: `${STORE}/${RUN_FAILED}/logs/stderr.log`,
        retried_ok: true,
      },
    ],
    projects: [
      { project: "toy-classifier", task: "toy-test", runs: 12, best: 0.9222222222222222, kind: "generic" },
    ],
  };
}

export function makeDiff(): ExampleDiff {
  return {
    a: RUN_RF,
    b: RUN_SVM,
    metric: "accuracy@v1",
    field: "correct",
    fixed: ["test-0", "test-110", "test-116", "test-12", "test-156", "test-177", "test-21", "test-63", "test-83"],
    broken: ["test-137", "test-167", "test-30"],
    both_pass: 157,
    both_fail: 11,
  };
}
```

- [ ] **Step 4: Run the test and the type check**

Run: `cd ui && bun test test/pages/types.test.ts && bun run typecheck`
Expected: `3 pass`, `0 fail`; `tsc` prints nothing.

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/types.ts ui/test/pages/fixtures.ts ui/test/pages/types.test.ts
git commit -m "feat(ui): page shapes from the api models, status sets, and fixtures"
```

### Task 22: Formatting helpers

**Files:**
- Create: `ui/src/pages/components/format.ts`
- Test: `ui/test/pages/format.test.ts`

**Interfaces:**
- Consumes: `d3-format` `format`; `MINUS`, `fmtP` (Task 8); `RunRecord` (Task 21).
- Produces (all pure): `DASH = "—"` (the missing-value glyph the panels use), `MINUS` (re-exported from `charts/Scale`), `isNum(v): v is number`,
  `parseTime(iso: string): number`, `fmtScore(v)`, `fmtDelta(v)`, `fmtSigned(n)`,
  `fmtInterval(lo, hi)`, `fmtP(p)`, `fmtDuration(seconds)`,
  `runSeconds(record, now?) -> number | null`, `fmtClock(iso)`, `fmtTime(iso)`,
  `fmtDate(iso)`, `fmtBytes(n)`, `fmtUsd(v)`, `fmtCount(n)`, `shortId(runId)`,
  `shortHash(hash)`, `firstClause(text, fallback, max?)`, `splitHostPath(value) -> {host, path}`,
  `displayPath(host, path)`, `relativeTo(path, base) -> string | null`, `tailPath(path, keep?)`,
  `shellJoin(argv)`, `fmtValue(v)`, `primaryMetricName(primary)`, `isAgent(createdBy)`.
  Every function returns `string` unless noted.

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/format.test.ts`:

```ts
import { describe, expect, test } from "bun:test";
import {
  displayPath,
  firstClause,
  fmtBytes,
  fmtClock,
  fmtCount,
  fmtDate,
  fmtDelta,
  fmtDuration,
  fmtInterval,
  fmtP,
  fmtScore,
  fmtSigned,
  fmtTime,
  fmtUsd,
  fmtValue,
  isAgent,
  primaryMetricName,
  relativeTo,
  runSeconds,
  shellJoin,
  shortHash,
  shortId,
  splitHostPath,
  tailPath,
} from "../../src/pages/components/format";
import { makeRecord } from "./fixtures";

describe("numbers", () => {
  test("fmtScore uses 4 decimals in [-1, 1], 3 significant digits above, SI above 1000", () => {
    expect(fmtScore(0.9222222222222222)).toBe("0.9222");
    expect(fmtScore(1)).toBe("1.0000");
    expect(fmtScore(-0.25)).toBe("−0.2500");
    expect(fmtScore(68.4)).toBe("68.4");
    expect(fmtScore(166.4)).toBe("166");
    expect(fmtScore(153000)).toBe("153k");
    expect(fmtScore(null)).toBe("—");
    expect(fmtScore(Number.NaN)).toBe("—");
  });

  test("fmtDelta and fmtSigned always carry a sign", () => {
    expect(fmtDelta(6 / 180)).toBe("+0.0333");
    expect(fmtDelta(-0.037)).toBe("−0.0370");
    expect(fmtDelta(0)).toBe("0.0000");
    expect(fmtSigned(6)).toBe("+6");
    expect(fmtSigned(-2)).toBe("−2");
    expect(fmtSigned(0)).toBe("0");
  });

  test("fmtInterval uses 3 decimals for fractions", () => {
    expect(fmtInterval(0.874, 0.953)).toBe("0.874–0.953");
    expect(fmtInterval(164.2, 168.1)).toBe("164–168");
  });

  test("fmtP: two decimals, three below 0.01, floor at 0.001", () => {
    // 598/4096 is the exact two-sided sign-test p for 9 fixed vs 3 broken
    expect(fmtP(598 / 4096)).toBe("p = 0.15");
    expect(fmtP(2 / 1024)).toBe("p = 0.002");
    expect(fmtP(0.0004)).toBe("p < 0.001");
    expect(fmtP(null)).toBe("—");
  });

  test("fmtBytes, fmtUsd, fmtCount", () => {
    expect(fmtBytes(512)).toBe("512 B");
    expect(fmtBytes(18494)).toBe("18.5 KB");
    expect(fmtBytes(26123)).toBe("26.1 KB");
    expect(fmtBytes(1_200_000)).toBe("1.2 MB");
    expect(fmtBytes(5.4e9)).toBe("5.4 GB");
    expect(fmtUsd(0.097)).toBe("$0.097");
    expect(fmtUsd(0.25)).toBe("$0.25");
    expect(fmtUsd(12.4)).toBe("$12.40");
    expect(fmtCount(13)).toBe("13");
    expect(fmtCount(4500)).toBe("4.5k");
    expect(fmtCount(153000)).toBe("153k");
  });
});

describe("time", () => {
  test("durations", () => {
    expect(fmtDuration(0.822124)).toBe("0.8 s");
    expect(fmtDuration(125)).toBe("2m 5s");
    expect(fmtDuration(20400)).toBe("5h 40m");
    expect(fmtDuration(null)).toBe("—");
  });

  test("runSeconds uses ended_at, or now while running", () => {
    // parseTime keeps milliseconds: 07.578 - 06.756 = 0.822 s
    expect(runSeconds(makeRecord())).toBeCloseTo(0.822, 6);
    const running = makeRecord({ ended_at: null, started_at: "2026-09-26T21:00:00Z" });
    expect(runSeconds(running, Date.parse("2026-09-26T21:00:30Z"))).toBe(30);
    expect(runSeconds(makeRecord({ started_at: null }))).toBeNull();
  });

  test("clock formats are UTC and accept microseconds and offsets", () => {
    expect(fmtClock("2026-09-26T21:03:06.685638Z")).toBe("21:03");
    expect(fmtTime("2026-09-26T21:03:06.685638Z")).toBe("21:03:06 UTC");
    expect(fmtDate("2026-09-26T21:03:56.036288+00:00")).toBe("2026-09-26 21:03");
    expect(fmtClock("not a time")).toBe("—");
  });
});

describe("text and paths", () => {
  test("shortId and shortHash", () => {
    expect(shortId("20260926-210306-toy-test-6f71")).toBe("6f71");
    expect(shortHash("sha256:e662a37bb8a556fd")).toBe("e662a37b");
  });

  test("firstClause cuts at the first clause break", () => {
    expect(firstClause("RBF-kernel SVM should beat RF because clusters are round", "x")).toBe(
      "RBF-kernel SVM",
    );
    expect(firstClause("baseline rf", "x")).toBe("baseline rf");
    expect(firstClause("lr 0.5 warmup, then decay", "x")).toBe("lr 0.5 warmup");
    expect(firstClause("  ", "run 6f71")).toBe("run 6f71");
    expect(firstClause("a".repeat(50), "x")).toBe(`${"a".repeat(39)}…`);
  });

  test("splitHostPath and displayPath", () => {
    expect(splitHostPath("local:/x/y")).toEqual({ host: "local", path: "/x/y" });
    expect(splitHostPath("/x/y")).toEqual({ host: "local", path: "/x/y" });
    expect(splitHostPath("gpu-a03:/scratch/run")).toEqual({ host: "gpu-a03", path: "/scratch/run" });
    expect(displayPath("local", "/x")).toBe("/x");
    expect(displayPath("gpu-a03", "/x")).toBe("gpu-a03:/x");
  });

  test("relativeTo and tailPath", () => {
    expect(relativeTo("/r/run1/logs/stdout.log", "/r/run1")).toBe("logs/stdout.log");
    expect(relativeTo("/r/run1/logs", "/r/run1/")).toBe("logs");
    expect(relativeTo("/r/run1", "/r/run1")).toBe(".");
    expect(relativeTo("/r/run10/x", "/r/run1")).toBeNull();
    expect(tailPath("/a/b/c/d/e")).toBe("…/c/d/e");
    expect(tailPath("/a/b")).toBe("/a/b");
  });

  test("shellJoin quotes only when needed", () => {
    expect(shellJoin(["python", "train.py", "--seed={seed}", "--name", "a b"])).toBe(
      "python train.py --seed={seed} --name 'a b'",
    );
    expect(shellJoin(["echo", "it's", ""])).toBe(`echo 'it'"'"'s' ''`);
  });

  test("fmtValue, primaryMetricName, isAgent", () => {
    expect(fmtValue("x")).toBe("x");
    expect(fmtValue(2)).toBe("2");
    expect(fmtValue(false)).toBe("false");
    expect(fmtValue(null)).toBe("—");
    expect(fmtValue({ a: 1 })).toBe('{"a":1}');
    expect(fmtValue("y".repeat(100))).toBe(`${"y".repeat(79)}…`);
    expect(primaryMetricName("accuracy/value")).toBe("accuracy");
    expect(isAgent("agent:acceptance")).toBe(true);
    expect(isAgent("human")).toBe(false);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/format.test.ts`
Expected: FAIL with `Cannot find module '../../src/pages/components/format'`.

- [ ] **Step 3: Implement the helpers**

`ui/src/pages/components/format.ts`:

```ts
/** Pure formatting helpers shared by the pages. Times are shown in UTC. */
import { format } from "d3-format";
import { MINUS, fmtP as pDigits } from "../../charts/Scale";
import type { RunRecord } from "./types";

/** Shown for a missing value (the same glyph as the panels). */
export const DASH = "—";
export { MINUS };

const sig3 = format(".3~g");
const si3 = format(".3~s");

/** True for finite numbers. */
export function isNum(v: unknown): v is number {
  return typeof v === "number" && Number.isFinite(v);
}

/** Parse an ISO time; trims sub-millisecond digits first (Python writes microseconds). */
export function parseTime(iso: string): number {
  return Date.parse(iso.replace(/(\.\d{3})\d+/, "$1"));
}

function minus(text: string): string {
  return text.replace("-", MINUS);
}

/** A metric value: 4 decimals in [-1, 1], 3 significant digits below 1000, else SI. */
export function fmtScore(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  const a = Math.abs(v);
  if (a <= 1) return minus(v.toFixed(4));
  if (a < 1000) return minus(sig3(v));
  return minus(si3(v));
}

/** A signed metric difference, e.g. `+0.0333`. */
export function fmtDelta(v: number | null | undefined): string {
  if (!isNum(v)) return DASH;
  const sign = v > 0 ? "+" : v < 0 ? MINUS : "";
  return `${sign}${fmtScore(Math.abs(v))}`;
}

/** A signed integer, e.g. `+6`. */
export function fmtSigned(n: number): string {
  return n > 0 ? `+${n}` : n < 0 ? `${MINUS}${Math.abs(n)}` : "0";
}

/** An interval `lo–hi`; 3 decimals when both ends are fractions. */
export function fmtInterval(lo: number, hi: number): string {
  if (Math.abs(lo) <= 1 && Math.abs(hi) <= 1) {
    return `${minus(lo.toFixed(3))}–${minus(hi.toFixed(3))}`;
  }
  return `${fmtScore(lo)}–${fmtScore(hi)}`;
}

/** A p-value with its name: `p = 0.15`, `p = 0.002`, or `p < 0.001` (digits from `charts/Scale`). */
export function fmtP(p: number | null | undefined): string {
  if (!isNum(p)) return DASH;
  const digits = pDigits(p);
  return digits.startsWith("<") ? `p ${digits}` : `p = ${digits}`;
}

/** A wall-clock duration: `0.8 s`, `2m 5s`, `5h 40m`. */
export function fmtDuration(seconds: number | null | undefined): string {
  if (!isNum(seconds)) return DASH;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
}

/** Seconds a run has taken (so far, while it runs); null before it starts. */
export function runSeconds(record: RunRecord, now: number = Date.now()): number | null {
  if (!record.started_at) return null;
  const start = parseTime(record.started_at);
  const end = record.ended_at ? parseTime(record.ended_at) : now;
  if (!isNum(start) || !isNum(end)) return null;
  return Math.max(0, (end - start) / 1000);
}

function utcParts(iso: string): Date | null {
  const t = parseTime(iso);
  return Number.isNaN(t) ? null : new Date(t);
}

const pad = (n: number): string => String(n).padStart(2, "0");

/** `21:03` (UTC). */
export function fmtClock(iso: string): string {
  const d = utcParts(iso);
  return d ? `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}` : DASH;
}

/** `21:03:06 UTC`. */
export function fmtTime(iso: string): string {
  const d = utcParts(iso);
  return d
    ? `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())} UTC`
    : DASH;
}

/** `2026-09-26 21:03` (UTC). */
export function fmtDate(iso: string): string {
  const d = utcParts(iso);
  if (!d) return DASH;
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${fmtClock(iso)}`;
}

/** A byte size with SI units: `18.5 KB`. */
export function fmtBytes(n: number): string {
  if (n < 1e3) return `${n} B`;
  if (n < 1e6) return `${(n / 1e3).toFixed(1)} KB`;
  if (n < 1e9) return `${(n / 1e6).toFixed(1)} MB`;
  return `${(n / 1e9).toFixed(1)} GB`;
}

/** Dollars: 3 decimals below $0.10, else 2. */
export function fmtUsd(v: number): string {
  return v < 0.1 ? `$${v.toFixed(3)}` : `$${v.toFixed(2)}`;
}

/** A count: exact below 1000, else SI (`4.5k`). */
export function fmtCount(n: number): string {
  return n < 1000 ? String(Math.round(n)) : si3(n);
}

/** The random tail of a run id: `…-6f71` → `6f71`. */
export function shortId(runId: string): string {
  return runId.split("-").pop() || runId;
}

/** The first 8 hex digits of a `sha256:`/`xxh3:` hash. */
export function shortHash(hash: string): string {
  return hash.replace(/^[a-z0-9]+:/, "").slice(0, 8);
}

const CLAUSE = /[,;(]|[.:](?:\s|$)|\s(?:should|because|so that|will)\s/i;

/** A short label from a hypothesis: text before the first clause break. */
export function firstClause(text: string, fallback: string, max = 40): string {
  const t = text.trim();
  if (!t) return fallback;
  const m = CLAUSE.exec(t);
  const head = (m ? t.slice(0, m.index) : t).trim() || t;
  return head.length > max ? `${head.slice(0, max - 1).trimEnd()}…` : head;
}

/** Split `host:/abs/path`; a bare path is on `local`. */
export function splitHostPath(value: string): { host: string; path: string } {
  const m = /^([A-Za-z0-9_.-]+):(\/.*)$/.exec(value);
  return m ? { host: m[1] ?? "local", path: m[2] ?? value } : { host: "local", path: value };
}

/** `path` for local files, `host:path` elsewhere. */
export function displayPath(host: string, path: string): string {
  return host === "local" ? path : `${host}:${path}`;
}

/** `path` relative to `base`, `"."` for `base` itself, or null when outside it. */
export function relativeTo(path: string, base: string): string | null {
  const b = base.replace(/\/+$/, "");
  if (path === b) return ".";
  return path.startsWith(`${b}/`) ? path.slice(b.length + 1) : null;
}

/** The last `keep` segments of a long path, prefixed with `…/`. */
export function tailPath(path: string, keep = 3): string {
  const parts = path.split("/").filter(Boolean);
  return parts.length <= keep ? path : `…/${parts.slice(-keep).join("/")}`;
}

const SAFE = /^[A-Za-z0-9_\-+=/.,:@%{}]+$/;

/** Join argv for display, single-quoting arguments a shell would split or expand. */
export function shellJoin(argv: string[]): string {
  return argv
    .map((a) => (a === "" ? "''" : SAFE.test(a) ? a : `'${a.replace(/'/g, `'"'"'`)}'`))
    .join(" ");
}

/** Any JSON value as short text (80 characters at most). */
export function fmtValue(v: unknown): string {
  if (v === null || v === undefined) return DASH;
  const text = typeof v === "string" ? v : typeof v === "object" ? JSON.stringify(v) : String(v);
  return text.length > 80 ? `${text.slice(0, 79)}…` : text;
}

/** `accuracy/value` → `accuracy`. */
export function primaryMetricName(primary: string): string {
  return primary.split("/")[0] ?? primary;
}

/** Launchers named `agent…` are agents; everyone else is a human. */
export function isAgent(createdBy: string): boolean {
  return createdBy.startsWith("agent");
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/format.test.ts`
Expected: PASS (14 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/format.ts ui/test/pages/format.test.ts
git commit -m "feat(ui): number, time, and path formatting for pages"
```

### Task 23: Links and in-app navigation

**Files:**
- Create: `ui/src/pages/components/links.tsx`
- Test: `ui/test/pages/links.test.tsx`

**Interfaces:**
- Consumes: `@tanstack/react-router` `useRouter`.
- Produces:
  - `hrefs.overview(): string`, `hrefs.task(project, task, view?)`, `hrefs.edit(project, task, view)`,
    `hrefs.run(runId, search?: { log?: string; example?: string })`, `hrefs.examples(a, b, metric?)`.
  - `type Navigate = (href: string) => void`; `NavigateContext` (React context, default
    `null`; tests provide a spy); `useNavigateHref(): Navigate` (context override, else
    the router's `history.push`, else `window.location.assign`).
  - `isPlainClick(e: { button: number; metaKey: boolean; ctrlKey: boolean; shiftKey: boolean; altKey: boolean }): boolean`.
  - `AppLink(props: AnchorHTMLAttributes & { href: string })`: a real `<a href>` that
    navigates in-app on a plain left click.
  - `isAppPath(pathname: string): boolean` (`/`, `/t/…`, `/r/…`, `/x/…`; not `/api/…`).
  - `useInAppLinks(): (e: MouseEvent<HTMLElement>) => void`: a click handler for a container
    whose children render plain `<a href>` (the panels of Parts 2–3, which do not import
    the router). A plain left click on a same-origin link to an app path, with no `target`
    or `download` and not already handled, navigates in-app instead of reloading the page
    (a reload also refetches every query and reconnects the live event stream, Task 42).

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/links.test.tsx`:

```tsx
import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  AppLink,
  NavigateContext,
  hrefs,
  isAppPath,
  isPlainClick,
  useInAppLinks,
} from "../../src/pages/components/links";

afterEach(cleanup);

describe("hrefs", () => {
  test("builds the contract routes", () => {
    expect(hrefs.overview()).toBe("/");
    expect(hrefs.task("toy-classifier", "toy-test")).toBe("/t/toy-classifier/toy-test");
    expect(hrefs.task("toy-classifier", "toy-test", "overview")).toBe("/t/toy-classifier/toy-test");
    expect(hrefs.task("p", "t", "route-quality")).toBe("/t/p/t?view=route-quality");
    expect(hrefs.edit("p", "t", "new")).toBe("/t/p/t/edit/new");
    expect(hrefs.run("r1", { log: "stderr" })).toBe("/r/r1?log=stderr");
    expect(hrefs.run("r1", { example: "T-014" })).toBe("/r/r1?example=T-014");
    expect(hrefs.examples("A", "B")).toBe("/x/A/B");
    expect(hrefs.examples("A", "B", "accuracy@v1")).toBe("/x/A/B?metric=accuracy%40v1");
  });

  test("encodes every path segment", () => {
    expect(hrefs.run("r 1/2")).toBe("/r/r%201%2F2");
    expect(hrefs.task("my proj", "a/b", "my view")).toBe("/t/my%20proj/a%2Fb?view=my+view");
  });
});

test("isPlainClick rejects modified and non-left clicks", () => {
  const base = { button: 0, metaKey: false, ctrlKey: false, shiftKey: false, altKey: false };
  expect(isPlainClick(base)).toBe(true);
  expect(isPlainClick({ ...base, metaKey: true })).toBe(false);
  expect(isPlainClick({ ...base, button: 1 })).toBe(false);
});

describe("AppLink", () => {
  test("navigates in-app on a plain click", () => {
    const navigate = mock((_href: string) => {});
    render(
      <NavigateContext.Provider value={navigate}>
        <AppLink href="/r/r1">run</AppLink>
      </NavigateContext.Provider>,
    );
    const link = screen.getByRole("link", { name: "run" });
    expect(link.getAttribute("href")).toBe("/r/r1");
    const notPrevented = fireEvent.click(link);
    expect(notPrevented).toBe(false);
    expect(navigate).toHaveBeenCalledWith("/r/r1");
  });

  test("leaves the click alone when a handler already prevented it", () => {
    const navigate = mock((_href: string) => {});
    render(
      <NavigateContext.Provider value={navigate}>
        <AppLink href="/r/r1" onClick={(e) => e.preventDefault()}>
          run
        </AppLink>
      </NavigateContext.Provider>,
    );
    fireEvent.click(screen.getByRole("link", { name: "run" }));
    expect(navigate).not.toHaveBeenCalled();
  });
});

describe("useInAppLinks", () => {
  test("routes plain clicks on app links in-app and leaves the rest to the browser", () => {
    expect(["/", "/t/p/t", "/r/r1", "/x/a/b", "/api/v1/runs", "/mcp", "/rx"].map(isAppPath)).toEqual([
      true,
      true,
      true,
      true,
      false,
      false,
      false,
    ]);
    const navigate = mock((_href: string) => {});
    const handled: [string, boolean][] = [];
    function Panel() {
      const onLinks = useInAppLinks();
      return (
        // The outer handler records whether the link click was taken over, then stops the
        // test DOM from following the link.
        <div
          onClick={(e) => {
            handled.push([(e.target as HTMLElement).textContent ?? "", e.defaultPrevented]);
            e.preventDefault();
          }}
        >
          <div onClick={onLinks}>
            <a href="/r/r1?example=42">run</a>
            <a href="/api/v1/runs/r1/logs?stream=stderr">raw</a>
            <a href="https://example.com/r/r1">out</a>
            <a href="/r/r2" target="_blank" rel="noreferrer">tab</a>
          </div>
        </div>
      );
    }
    render(
      <NavigateContext.Provider value={navigate}>
        <Panel />
      </NavigateContext.Provider>,
    );
    fireEvent.click(screen.getByRole("link", { name: "run" }));
    fireEvent.click(screen.getByRole("link", { name: "run" }), { metaKey: true });
    for (const name of ["raw", "out", "tab"]) fireEvent.click(screen.getByRole("link", { name }));
    expect(handled).toEqual([
      ["run", true],
      ["run", false],
      ["raw", false],
      ["out", false],
      ["tab", false],
    ]);
    expect(navigate.mock.calls).toEqual([["/r/r1?example=42"]]);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/links.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/links'`.

- [ ] **Step 3: Implement the links**

`ui/src/pages/components/links.tsx`:

```tsx
/** Route hrefs (contract section 4) and an in-app link that works with or without a router. */
import { useRouter } from "@tanstack/react-router";
import {
  type AnchorHTMLAttributes,
  type MouseEvent,
  createContext,
  useCallback,
  useContext,
} from "react";

export type Navigate = (href: string) => void;

/** Overrides navigation (tests, embedding). `null` means "use the router". */
export const NavigateContext = createContext<Navigate | null>(null);

const enc = encodeURIComponent;

function withSearch(path: string, search: Record<string, string | undefined>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(search)) {
    if (value !== undefined && value !== "") qs.set(key, value);
  }
  const query = qs.toString();
  return query ? `${path}?${query}` : path;
}

export const hrefs = {
  overview: (): string => "/",
  task: (project: string, task: string, view?: string): string =>
    withSearch(`/t/${enc(project)}/${enc(task)}`, {
      view: view === "overview" ? undefined : view,
    }),
  edit: (project: string, task: string, view: string): string =>
    `/t/${enc(project)}/${enc(task)}/edit/${enc(view)}`,
  run: (runId: string, search: { log?: string; example?: string } = {}): string =>
    withSearch(`/r/${enc(runId)}`, search),
  examples: (a: string, b: string, metric?: string): string =>
    withSearch(`/x/${enc(a)}/${enc(b)}`, { metric }),
};

interface HistoryLike {
  history: { push: (href: string) => void };
}

/** Navigate to an href: context override, else the router, else a full page load. */
export function useNavigateHref(): Navigate {
  const override = useContext(NavigateContext);
  const router = useRouter({ warn: false }) as unknown as HistoryLike | null | undefined;
  return useCallback(
    (href: string) => {
      if (override) override(href);
      else if (router) router.history.push(href);
      else window.location.assign(href);
    },
    [override, router],
  );
}

/** A left click with no modifier keys (a modified click opens a new tab instead). */
export function isPlainClick(e: {
  button: number;
  metaKey: boolean;
  ctrlKey: boolean;
  shiftKey: boolean;
  altKey: boolean;
}): boolean {
  return e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey && !e.altKey;
}

export type AppLinkProps = Omit<AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string;
};

/** True for a path the SPA routes (Overview, Task, Run, Examples); `/api/…` is left to the browser. */
export function isAppPath(pathname: string): boolean {
  return /^\/($|[trx]\/)/.test(pathname);
}

/**
 * Click handler for a container of plain `<a href>` links (panel bodies).
 *
 * Panels (Parts 2–3) render plain links so they work without a router; this turns a
 * plain left click on a same-origin app link into in-app navigation. Modified clicks,
 * `target`/`download` links, other origins, `/api/…` paths and clicks a link already
 * handled (for example an `AppLink`) keep the browser's behaviour.
 */
export function useInAppLinks(): (e: MouseEvent<HTMLElement>) => void {
  const navigate = useNavigateHref();
  return useCallback(
    (e: MouseEvent<HTMLElement>) => {
      if (e.defaultPrevented || !isPlainClick(e)) return;
      const link = (e.target as Element | null)?.closest?.("a[href]");
      if (!(link instanceof HTMLAnchorElement) || !e.currentTarget.contains(link)) return;
      if (link.target || link.hasAttribute("download")) return;
      const url = new URL(link.href, window.location.href);
      if (url.origin !== window.location.origin || !isAppPath(url.pathname)) return;
      e.preventDefault();
      navigate(`${url.pathname}${url.search}${url.hash}`);
    },
    [navigate],
  );
}

/** An `<a href>` that navigates in-app on a plain click and keeps browser behaviour otherwise. */
export function AppLink({ href, onClick, target, children, ...rest }: AppLinkProps) {
  const navigate = useNavigateHref();
  const handle = (e: MouseEvent<HTMLAnchorElement>) => {
    onClick?.(e);
    if (e.defaultPrevented || target || !isPlainClick(e)) return;
    e.preventDefault();
    navigate(href);
  };
  return (
    <a {...rest} href={href} target={target} onClick={handle}>
      {children}
    </a>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/links.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/links.tsx ui/test/pages/links.test.tsx
git commit -m "feat(ui): route hrefs and in-app links for pages"
```

### Task 24: Page primitives (styles, lettered figure, stat strip, copy button, states)

**Files:**
- Create: `ui/src/pages/components/styles.ts`
- Create: `ui/src/pages/components/Figure.tsx`
- Create: `ui/src/pages/components/StatStrip.tsx`
- Create: `ui/src/pages/components/CopyButton.tsx`
- Create: `ui/src/pages/components/QueryState.tsx`
- Create: `ui/test/pages/helpers.tsx` (shared test helpers)
- Test: `ui/test/pages/primitives.test.tsx`

**Interfaces:**
- Consumes: design-token CSS variables and the shared rules in `base.css` (Task 2); the `stat_strip` panel (Task 11).
- Produces:
  - `PAGES_CSS: string`; `PageStyles()` renders `<style data-hx="pages">` once per page.
    Every rule is scoped under `.page`, so it cannot clash with the app shell's styles.
  - `panelLetter(index: number): string` (0 → `a`, 25 → `z`, 26 → `aa`).
  - `Figure({ letter, title, aside?, children?, className?, style? })`: a `<section>` with
    `aria-label="<letter> <title>"` (role `region`) and the lettered header.
  - `StatItem` (the Task 3 model); `StatStrip({ items })` draws through the `stat_strip`
    panel of Task 11 and renders nothing for no items.
  - `CopyButton({ text, label? })`: `aria-label="Copy <label ?? text>"`, `data-state`
    `idle | copied | failed`.
  - `ErrorBox({ error })` (`role="alert"`, the error's message); `Loading()`.
  - `test/pages/helpers.tsx`: `interface Call`, `HttpReply`, `mockApi(routes): Call[]`,
    `restoreFetch()`, `mockClipboard(fail?): string[]`,
    `renderWithClient(ui, { navigate? }) -> RenderResult & { client }`.

- [ ] **Step 1: Write the shared test helpers and the failing tests**

`ui/test/pages/helpers.tsx` (shared by every later test in this part; Task 25
adds panel-registry support):

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { NavigateContext } from "../../src/pages/components/links";

/** One request the mocked `fetch` saw. */
export interface Call {
  method: string;
  url: string;
  body: unknown;
}

/** A non-200 answer for `mockApi`. */
export class HttpReply {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {}
}

type Handler = unknown | ((call: Call) => unknown);

const realFetch = globalThis.fetch;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

/**
 * Replace `fetch` with a table of canned answers keyed by `"METHOD /path?query"`.
 *
 * A handler may be a value (sent as JSON 200), an `HttpReply`, or a function of the
 * call; a function that throws makes `fetch` reject, like a dropped connection.
 * Unknown keys answer 404. Returns the list of calls, in order.
 */
export function mockApi(routes: Record<string, Handler>): Call[] {
  const calls: Call[] = [];
  const fake = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url =
      typeof input === "string" ? input : input instanceof URL ? `${input.pathname}${input.search}` : input.url;
    const method = (init?.method ?? "GET").toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    const call = { method, url, body };
    calls.push(call);
    const key = `${method} ${url}`;
    if (!(key in routes)) return json(404, { error: `unmocked ${key}`, type: "StoreError" });
    const handler = routes[key];
    const out = typeof handler === "function" ? await (handler as (c: Call) => unknown)(call) : handler;
    if (out instanceof HttpReply) return json(out.status, out.body);
    return json(200, out);
  };
  globalThis.fetch = fake as unknown as typeof fetch;
  return calls;
}

/** Put the real `fetch` back (call in `afterEach`). */
export function restoreFetch(): void {
  globalThis.fetch = realFetch;
}

/** Replace `navigator.clipboard`; returns the texts written. */
export function mockClipboard(fail = false): string[] {
  const written: string[] = [];
  Object.defineProperty(globalThis.navigator, "clipboard", {
    configurable: true,
    value: {
      writeText: async (text: string) => {
        if (fail) throw new Error("denied");
        written.push(text);
      },
    },
  });
  return written;
}

export interface RenderOpts {
  navigate?: (href: string) => void;
}

/** Render inside a fresh QueryClient (no query retries), with an optional navigate spy. */
export function renderWithClient(ui: ReactElement, opts: RenderOpts = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let tree = <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
  if (opts.navigate) {
    tree = <NavigateContext.Provider value={opts.navigate}>{tree}</NavigateContext.Provider>;
  }
  return { ...render(tree), client };
}
```

`ui/test/pages/primitives.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { CopyButton } from "../../src/pages/components/CopyButton";
import { Figure, panelLetter } from "../../src/pages/components/Figure";
import { ErrorBox } from "../../src/pages/components/QueryState";
import { StatStrip } from "../../src/pages/components/StatStrip";
import { PAGES_CSS, PageStyles } from "../../src/pages/components/styles";
import { mockClipboard } from "./helpers";

afterEach(cleanup);

test("panelLetter runs a..z then aa, ab", () => {
  expect([0, 1, 25, 26, 27, 51, 52].map(panelLetter)).toEqual(["a", "b", "z", "aa", "ab", "az", "ba"]);
});

test("Figure is a named region with its letter and title", () => {
  render(
    <Figure letter="b" title="Scores" aside="2 metrics">
      <p>body</p>
    </Figure>,
  );
  const region = screen.getByRole("region", { name: "b Scores" });
  expect(region.querySelector(".pl")?.textContent).toBe("b");
  expect(region.querySelector("h2")?.textContent).toBe("Scores");
  expect(region.querySelector(".aside")?.textContent).toBe("2 metrics");
});

test("StatStrip shows value, unit, label, and tooltip", () => {
  render(<StatStrip items={[{ label: "wall", value: "68.4", unit: "s", tooltip: "wall-clock time" }]} />);
  const cell = screen.getByText("wall").parentElement as HTMLElement;
  expect(cell.getAttribute("title")).toBe("wall-clock time");
  expect(cell.querySelector("dd")?.textContent).toBe("68.4 s");
});

test("StatStrip renders nothing for no items", () => {
  const { container } = render(<StatStrip items={[]} />);
  expect(container.innerHTML).toBe("");
});

describe("CopyButton", () => {
  test("writes the text and marks itself copied", async () => {
    const written = mockClipboard();
    render(<CopyButton text="/runs/r1/logs/stderr.log" label="stderr path" />);
    const button = screen.getByRole("button", { name: "Copy stderr path" });
    fireEvent.click(button);
    await waitFor(() => expect(button.getAttribute("data-state")).toBe("copied"));
    expect(written).toEqual(["/runs/r1/logs/stderr.log"]);
  });

  test("shows a failure mark when the clipboard is blocked", async () => {
    mockClipboard(true);
    render(<CopyButton text="/x" />);
    const button = screen.getByRole("button", { name: "Copy /x" });
    fireEvent.click(button);
    await waitFor(() => expect(button.getAttribute("data-state")).toBe("failed"));
    expect(button.getAttribute("title")).toBe("Clipboard blocked");
  });
});

test("ErrorBox shows the message as an alert", () => {
  render(<ErrorBox error={new Error("no run abc")} />);
  expect(screen.getByRole("alert").textContent).toBe("no run abc");
});

test("PageStyles scopes every rule under .page", () => {
  const { container } = render(<PageStyles />);
  expect(container.querySelector("style[data-hx='pages']")?.textContent).toBe(PAGES_CSS);
  const selectors = PAGES_CSS.split("}")
    .map((block) => block.split("{")[0]?.trim() ?? "")
    .filter((sel) => sel && !sel.startsWith("/*"));
  for (const sel of selectors) {
    for (const part of sel.split(",")) expect(part.trim().startsWith(".page")).toBe(true);
  }
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/primitives.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/CopyButton'`.

- [ ] **Step 3: Implement the primitives**

`ui/src/pages/components/styles.ts` (rules adapted from `docs/mockups/ui-v4/index.html`
and `docs/mockups/kinds/*/index.html`; the shared chrome, type, stat strip, figure, button,
table, tag and `who` rules already live in `base.css` (Task 2), so this string holds only
page layouts and the few overrides pages need; no comments inside the string so the scoping
test stays simple):

```ts
/** Page-level CSS. Every selector starts with `.page` so it cannot leak into the shell. */
import { createElement } from "react";

export const PAGES_CSS = `
.page { max-width: 1280px; margin: 0 auto; }
.page .crumb .tag { margin-left: 10px; }
.page h1.headline { margin: 0; max-width: 21em; font: 500 46px/1.06 var(--serif); letter-spacing: -.018em; text-wrap: balance; }
.page h1.headline.long { font-size: 27px; line-height: 1.25; font-weight: 450; max-width: 40em; text-wrap: pretty; }
.page .err { color: var(--fail); font-size: 14px; margin: 12px 0; }
.page .stats { margin: 36px 0 0; }
.page .stats > div:not([title]) { cursor: default; }
.page .fig { min-width: 0; }
.page .fig-h .t { margin: 0; }
.page .panel-grid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 56px 48px; margin-top: 64px; }
.page .panel-grid > .fig { margin-top: 0; }
.page .btn { display: inline-flex; align-items: center; text-decoration: none; }
.page .btn:disabled { background: transparent; }
.page .btn.link { text-decoration: underline; }
.page .copy { line-height: 0; }
.page .copy[data-state="failed"] { color: var(--fail); }
.page .row { display: flex; gap: 8px; align-items: center; }
.page .plain { list-style: none; margin: 0; padding: 0; }
.page .plain li { padding: 6px 0; }
.page .ov-grid { display: grid; grid-template-columns: minmax(0, 1fr) 300px; gap: 72px; margin-top: 64px; }
.page .ov-grid .fig { margin-top: 0; }
.page .side .fig + .fig { margin-top: 48px; }
.page .timeline svg { width: 100%; height: auto; overflow: visible; }
.page .timeline .ln { font: 600 13px var(--sans); fill: var(--ink); }
.page .timeline .lc { font: 400 12px var(--sans); fill: var(--ink-3); }
.page .timeline .grid { stroke: var(--rule-2); }
.page .timeline .lane, .page .timeline .axis { stroke: var(--rule); }
.page .timeline .tick, .page .timeline .cl { font: 400 12px var(--sans); fill: var(--ink-3); }
.page .timeline .cl.best { fill: var(--ink); font-weight: 600; }
.page .timeline .mark { cursor: pointer; }
.page .ideas { list-style: none; margin: 0; padding: 0; }
.page .idea { display: grid; grid-template-columns: 56px minmax(0, 1fr) minmax(0, 420px) 84px; gap: 0 20px; align-items: center; padding: 14px 0; border-top: 1px solid var(--rule-2); }
.page .idea:first-child { border-top: 0; }
.page .idea .mks { display: flex; gap: 4px; align-items: center; }
.page .idea .nm { font-weight: 550; font-size: 15px; }
.page .idea .meta { font-size: 13px; color: var(--ink-3); margin-top: 1px; }
.page .idea .sc { text-align: right; font-size: 15px; font-variant-numeric: tabular-nums; }
.page .idea .sc small { display: block; font-size: 12.5px; color: var(--ink-3); }
.page .idea.dim .nm, .page .idea.dim .sc { color: var(--ink-3); font-weight: 400; }
.page .idea svg.iv { width: 100%; height: 30px; overflow: visible; }
.page .idea-axis svg { width: 100%; height: 24px; overflow: visible; }
.page .idea-axis text { font: 400 11.5px var(--sans); fill: var(--ink-3); }
.page .fail-b { font: 400 15.5px/1.5 var(--serif); color: var(--ink-2); margin: 0 0 16px; }
.page .fail-b b { color: var(--ink); font-weight: 650; }
.page .fail-b .x { color: var(--fail); font-family: var(--sans); font-weight: 600; margin-right: 6px; }
.page .fail-b .row { margin-top: 8px; }
.page .view-tabs { display: flex; align-items: center; gap: 4px; margin-top: 36px; border-bottom: 1px solid var(--rule); font-size: 14px; }
.page .view-tabs > a { padding: 10px 12px; text-decoration: none; color: var(--ink-3); border-bottom: 2px solid transparent; margin-bottom: -1px; }
.page .view-tabs > a small { margin-left: 6px; font-size: 12px; color: var(--ink-3); }
.page .view-tabs > a[aria-current="page"] { color: var(--ink); border-bottom-color: var(--ink); font-weight: 500; }
.page .view-tabs .r { margin-left: auto; display: flex; gap: 8px; align-items: center; padding-bottom: 6px; }
.page .run-top { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 40px; align-items: start; }
.page .actions { display: flex; gap: 8px; padding-top: 10px; }
.page .status { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 18px; font-size: 14px; color: var(--ink-2); align-items: center; }
.page .st { display: inline-flex; align-items: center; gap: 6px; font-weight: 500; color: var(--ink); }
.page .st i { width: 7px; height: 7px; border-radius: 50%; background: var(--ink-3); }
.page .st.finished i { background: var(--best); }
.page .st.failed i, .page .st.killed i, .page .st.lost i { background: var(--fail); }
.page .st.running i { background: var(--agent); }
.page .run-grid { display: grid; grid-template-columns: minmax(0, 1fr) 400px; gap: 72px; margin-top: 64px; }
.page .run-grid .fig { margin-top: 0; }
.page .run-grid .side .fig + .fig { margin-top: 56px; }
.page .tree { font-size: 14px; }
.page .tree .cmdrow { display: grid; grid-template-columns: 116px minmax(0, 1fr); gap: 0 16px; align-items: start; padding: 0 0 18px; }
.page .tree .root { display: grid; grid-template-columns: 116px minmax(0, 1fr) auto auto; gap: 0 16px; align-items: baseline; padding: 14px 0 10px; border-top: 1px solid var(--rule); }
.page .tree .k { color: var(--ink); font-weight: 550; }
.page .tree .what { font-size: 12.5px; color: var(--ink-3); text-align: right; }
.page .tree .kids { list-style: none; margin: 0 0 6px 132px; padding: 0; }
.page .tree .kids li { display: grid; grid-template-columns: 18px minmax(0, 1fr) auto auto; gap: 0 10px; align-items: baseline; padding: 5px 0; }
.page .tree .br { color: var(--ink-3); font-family: var(--mono); font-size: 13px; }
.page .gitline { margin: 4px 0 8px 132px; font-size: 13px; color: var(--ink-3); }
.page .gitline b { color: var(--ink); font-weight: 650; font-family: var(--mono); }
.page .gitline .dirty { color: var(--fail); }
.page .tmpl { margin: 6px 0 0; font-size: 12.5px; color: var(--ink-3); }
.page .scores { width: 100%; border-collapse: collapse; }
.page .scores td { padding: 12px 0; border-top: 1px solid var(--rule-2); vertical-align: top; font-size: 14px; }
.page .scores tr:first-child td { border-top: 0; }
.page .scores .v { font: 400 30px/1 var(--sans); letter-spacing: -.015em; text-align: right; }
.page .scores small { display: block; color: var(--ink-3); font-size: 12.5px; margin-top: 4px; letter-spacing: 0; }
.page .notes { font: 400 15.5px/1.55 var(--serif); color: var(--ink-2); margin: 0 0 12px; }
.page .notes .by { font: 400 12.5px/1.4 var(--sans); color: var(--ink-3); margin-bottom: 6px; display: flex; gap: 10px; }
.page .notes p { margin: 0; white-space: pre-wrap; }
.page .notes p.clip { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
.page .note-edit textarea { width: 100%; min-height: 90px; font: 400 14px/1.5 var(--sans); color: var(--ink); background: transparent; border: 1px solid var(--rule); border-radius: 6px; padding: 8px; margin-bottom: 8px; }
.page pre.log { max-height: 480px; overflow: auto; padding: 12px 14px; background: var(--paper-2); border-radius: 6px; font: 400 12.5px/1.5 var(--mono); white-space: pre-wrap; word-break: break-word; margin: 0 0 8px; }
.page .trace-pick { display: flex; flex-wrap: wrap; gap: 4px 12px; margin: 0 0 14px; font: 400 13px var(--mono); }
.page .trace-pick a { color: var(--ink-3); text-decoration: none; }
.page .trace-pick a.failed { color: var(--fail); }
.page .trace-pick a[aria-current="true"] { color: var(--ink); text-decoration: underline; }
.page .ab { display: grid; grid-template-columns: 1fr 1fr; gap: 56px; margin-top: 36px; padding: 18px 0; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); }
.page .ab .lbl { font-size: 12.5px; color: var(--ink-3); }
.page .ab .nm { font-weight: 600; font-size: 16px; margin-top: 2px; }
.page .ab .meta { font-size: 13px; color: var(--ink-3); margin-top: 3px; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.page .ab .row { justify-content: space-between; align-items: end; gap: 20px; }
.page .ab .acc { font: 300 38px/1 var(--sans); letter-spacing: -.02em; text-align: right; }
.page .ab .acc small { display: block; font-size: 12.5px; color: var(--ink-3); font-weight: 400; letter-spacing: 0; margin-top: 4px; }
.page .two-x { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 64px; align-items: start; margin-top: 64px; }
.page .two-x .fig { margin-top: 0; }
.page .ot { border-collapse: collapse; width: 100%; }
.page .ot th { font: 500 13px/1.3 var(--sans); color: var(--ink-3); padding: 0 12px 10px; text-align: center; }
.page .ot th.rh { text-align: right; padding: 0 16px 0 0; width: 96px; vertical-align: middle; white-space: nowrap; }
.page .ot td { width: 44%; height: 124px; text-align: center; vertical-align: middle; border: 1px solid var(--rule); }
.page .ot .n { font: 300 50px/1 var(--sans); letter-spacing: -.02em; display: block; }
.page .ot .w { font-size: 13px; color: var(--ink-2); display: inline-flex; gap: 7px; align-items: center; margin-top: 6px; }
.page .ot td.fx { background: var(--best-wash); }
.page .ot td.bk { background: color-mix(in srgb, var(--fail) 10%, transparent); }
.page .ot td.same .n { color: var(--ink-2); }
.page .sw { width: 9px; height: 9px; display: inline-block; border-radius: 2px; }
.page .sw.fixed { background: var(--best); }
.page .sw.broken { background: var(--fail); }
.page .sw.both_fail { background: var(--ink-2); }
.page .sw.both_pass { background: var(--rule); }
.page .strip svg, .page .signtest svg { width: 100%; height: auto; overflow: visible; }
.page .strip rect.fixed { fill: var(--best); }
.page .strip rect.broken { fill: var(--fail); }
.page .strip rect.both_fail { fill: var(--ink-2); }
.page .strip rect.both_pass { fill: var(--rule); }
.page .strip-key { list-style: none; display: flex; gap: 22px; margin: 10px 0 0; padding: 0; font-size: 13px; color: var(--ink-2); }
.page .strip-key li { display: inline-flex; gap: 7px; align-items: center; }
.page .signtest rect { fill: var(--rule); }
.page .signtest rect[data-tail="true"] { fill: var(--ink); }
.page .signtest text { font: 400 11.5px var(--sans); fill: var(--ink-3); }
.page .signtest .obs { stroke: var(--ink-3); }
.page .signtest text.obs-l { fill: var(--ink); font-weight: 600; }
`;

/** Inject the page CSS (React dedupes nothing here; one `<style>` per mounted page). */
export function PageStyles() {
  return createElement("style", { "data-hx": "pages" }, PAGES_CSS);
}
```

`ui/src/pages/components/Figure.tsx`:

```tsx
/** Journal-style lettered panel (spec 8.1): letter, a few-word title, optional aside. */
import type { CSSProperties, ReactNode } from "react";

/** 0 → "a", 25 → "z", 26 → "aa", 27 → "ab" (spreadsheet-style). */
export function panelLetter(index: number): string {
  let n = index;
  let out = "";
  do {
    out = String.fromCharCode(97 + (n % 26)) + out;
    n = Math.floor(n / 26) - 1;
  } while (n >= 0);
  return out;
}

export interface FigureProps {
  letter: string;
  title: string;
  aside?: ReactNode;
  children?: ReactNode;
  className?: string;
  style?: CSSProperties;
}

export function Figure({ letter, title, aside, children, className, style }: FigureProps) {
  return (
    <section
      className={className ? `fig ${className}` : "fig"}
      style={style}
      aria-label={`${letter} ${title}`}
    >
      <header className="fig-h">
        <span className="pl">{letter}</span>
        <h2 className="t">{title}</h2>
        {aside !== undefined && aside !== null ? <span className="aside">{aside}</span> : null}
      </header>
      {children}
    </section>
  );
}
```

`ui/src/pages/components/StatStrip.tsx`:

```tsx
/** A row of big numbers with short labels; explanations go in the tooltip. Drawn by the `stat_strip` panel. */
import type { StatItem } from "../../api/models";
import { StatStrip as StatStripPanel } from "../../panels/StatStrip";

export type { StatItem };

export function StatStrip({ items }: { items: StatItem[] }) {
  if (items.length === 0) return null;
  const rows: Record<string, unknown>[] = items.map((item) => ({
    label: item.label,
    value: item.value,
    unit: item.unit ?? null,
    tooltip: item.tooltip ?? null,
  }));
  return <StatStripPanel result={{ type: "stat_strip", title: "", rows, meta: {} }} />;
}
```

`ui/src/pages/components/CopyButton.tsx`:

```tsx
/** Copy a path or command to the clipboard, with a visible result. */
import { useEffect, useState } from "react";

type CopyState = "idle" | "copied" | "failed";

const TITLES: Record<CopyState, string> = {
  idle: "Copy",
  copied: "Copied",
  failed: "Clipboard blocked",
};

function CopyIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 13 13" aria-hidden="true">
      <rect x="3.5" y="3.5" width="8" height="8" rx="1.5" fill="none" stroke="currentColor" />
      <path d="M9 1.5H2.5a1 1 0 0 0-1 1V9" fill="none" stroke="currentColor" />
    </svg>
  );
}

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const [state, setState] = useState<CopyState>("idle");
  useEffect(() => {
    if (state === "idle") return;
    const timer = setTimeout(() => setState("idle"), 1500);
    return () => clearTimeout(timer);
  }, [state]);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
  };
  return (
    <button
      type="button"
      className="copy"
      data-state={state}
      title={TITLES[state]}
      aria-label={`Copy ${label ?? text}`}
      onClick={copy}
    >
      {state === "copied" ? "✓" : state === "failed" ? "!" : <CopyIcon />}
    </button>
  );
}
```

`ui/src/pages/components/QueryState.tsx`:

```tsx
/** Loading and error placeholders for page queries. */
export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <p role="alert" className="err">
      {message}
    </p>
  );
}

export function Loading() {
  return (
    <p className="small" aria-busy="true">
      loading…
    </p>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/primitives.test.tsx`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/styles.ts ui/src/pages/components/Figure.tsx \
  ui/src/pages/components/StatStrip.tsx ui/src/pages/components/CopyButton.tsx \
  ui/src/pages/components/QueryState.tsx ui/test/pages/helpers.tsx \
  ui/test/pages/primitives.test.tsx
git commit -m "feat(ui): lettered figures, stat strip, copy button, page styles"
```

### Task 25: Panel grid over the panel registry

**Files:**
- Create: `ui/src/pages/components/PanelGrid.tsx`
- Modify: `ui/test/pages/helpers.tsx` (registry option for `renderWithClient`, `fakeRegistry`)
- Test: `ui/test/pages/panelGrid.test.tsx`

**Interfaces:**
- Consumes: `PANELS`, `PanelBoundary`, `PanelError` from `ui/src/panels/index.ts` (Task 11);
  `Figure`, `panelLetter` (Task 24); `PanelResult`, `PanelSpec` (Task 21).
- Produces:
  - `type PanelComponent = ComponentType<{ result: PanelResult }>`;
    `type PanelRegistry = Partial<Record<string, PanelComponent>>`.
  - `PanelRegistryContext` (default: `PANELS`).
  - `PanelBody({ result })`: the server's reason when the panel query failed
    (`meta.error` is a string: backend `query_view` answers `{rows: [], meta: {error}}`,
    for example `scatter panel needs data.x and data.y`), else the registered component
    inside the registry's error boundary, or the registry's alert
    `Unknown panel type: <type>`. The view editor preview (Task 41) draws panels through it too.
    The component sits in a `display: contents` wrapper with Task 23 `useInAppLinks`, so
    the panels' plain run links (Tasks 12, 14, 16) navigate in-app instead of reloading.
  - `clampSpan(span?: number): number` (1..12, default 12).
  - `PanelGrid({ results, specs?, startIndex? })`: a 12-column grid of lettered figures;
    `specs[i].layout` gives `span`/`row`; `result.meta.warnings` (strings) show as
    `⚠ <n>` with the text in the tooltip.
  - `test/pages/helpers.tsx`: `renderWithClient(ui, { navigate?, registry? })`;
    `fakeRegistry(types: string[]): PanelRegistry` (each panel prints `"<title>:<row count>"`
    in a `data-testid="panel-<type>"` element).

- [ ] **Step 1: Extend the test helpers and write the failing tests**

In `ui/test/pages/helpers.tsx`, add these imports below the `NavigateContext` import:

```tsx
import {
  type PanelRegistry,
  PanelRegistryContext,
} from "../../src/pages/components/PanelGrid";
import type { PanelResult } from "../../src/pages/components/types";
```

Replace the `RenderOpts` interface and `renderWithClient` with:

```tsx
export interface RenderOpts {
  navigate?: (href: string) => void;
  registry?: PanelRegistry;
}

/** Render inside a fresh QueryClient (no query retries), with optional fakes. */
export function renderWithClient(ui: ReactElement, opts: RenderOpts = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let tree = <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
  if (opts.registry) {
    tree = <PanelRegistryContext.Provider value={opts.registry}>{tree}</PanelRegistryContext.Provider>;
  }
  if (opts.navigate) {
    tree = <NavigateContext.Provider value={opts.navigate}>{tree}</NavigateContext.Provider>;
  }
  return { ...render(tree), client };
}
```

Append at the end of the file:

```tsx
function FakePanel({ result }: { result: PanelResult }) {
  return <div data-testid={`panel-${result.type}`}>{`${result.title}:${result.rows.length}`}</div>;
}

/** A panel registry whose panels print `"<title>:<row count>"`. */
export function fakeRegistry(types: string[]): PanelRegistry {
  return Object.fromEntries(types.map((t) => [t, FakePanel]));
}
```

`ui/test/pages/panelGrid.test.tsx`:

```tsx
import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { NavigateContext } from "../../src/pages/components/links";
import { PanelGrid, PanelRegistryContext, clampSpan } from "../../src/pages/components/PanelGrid";
import type { PanelResult } from "../../src/pages/components/types";
import { fakeRegistry } from "./helpers";

afterEach(cleanup);

const results: PanelResult[] = [
  { type: "markdown", title: "Note", rows: [], meta: { text: "hi" } },
  { type: "curves", title: "", rows: [{}, {}], meta: { warnings: ["metric lr not logged"] } },
  { type: "vega_lite", title: "Depth", rows: [], meta: {} },
];

test("clampSpan keeps spans in 1..12", () => {
  expect([undefined, 0, 4, 12, 13, 5.6].map(clampSpan)).toEqual([12, 1, 4, 12, 12, 6]);
});

test("letters panels in order, applies layout, shows warnings and unknown types", () => {
  render(
    <PanelRegistryContext.Provider value={fakeRegistry(["markdown", "curves"])}>
      <PanelGrid
        results={results}
        startIndex={2}
        specs={[
          { type: "markdown", layout: { span: 4, row: 2 } },
          { type: "curves", title: "Loss", layout: { span: 8, row: null } },
          { type: "vega_lite" },
        ]}
      />
    </PanelRegistryContext.Provider>,
  );
  const note = screen.getByRole("region", { name: "c Note" });
  expect(note.style.gridColumn).toBe("span 4");
  expect(note.style.gridRow).toBe("2");
  expect(within(note).getByTestId("panel-markdown").textContent).toBe("Note:0");

  const loss = screen.getByRole("region", { name: "d Loss" });
  expect(loss.style.gridColumn).toBe("span 8");
  const warn = loss.querySelector(".aside span") as HTMLElement;
  expect(warn.textContent).toBe("⚠ 1");
  expect(warn.getAttribute("title")).toBe("metric lr not logged");

  const depth = screen.getByRole("region", { name: "e Depth" });
  expect(depth.style.gridColumn).toBe("span 12");
  expect(within(depth).getByRole("alert").textContent).toBe("Unknown panel type: vega_lite");
});

test("a panel whose query failed shows the server's reason, not its empty state", () => {
  const failed: PanelResult[] = [
    { type: "scatter", title: "Cost vs quality", rows: [], meta: { error: "scatter panel needs data.x and data.y" } },
    { type: "markdown", title: "Note", rows: [], meta: { text: "hi" } },
  ];
  render(
    <PanelRegistryContext.Provider value={fakeRegistry(["scatter", "markdown"])}>
      <PanelGrid results={failed} />
    </PanelRegistryContext.Provider>,
  );
  const bad = screen.getByRole("region", { name: "a Cost vs quality" });
  expect(within(bad).getByRole("alert").textContent).toBe("scatter panel needs data.x and data.y");
  expect(within(bad).queryByTestId("panel-scatter")).toBeNull();
  const note = screen.getByRole("region", { name: "b Note" });
  expect(within(note).getByTestId("panel-markdown").textContent).toBe("Note:0");
});

test("a panel that throws shows its error and the other panels still draw", () => {
  const Broken = () => {
    throw new Error("bad rows");
  };
  const quiet = console.error;
  console.error = () => {};
  try {
    render(
      <PanelRegistryContext.Provider value={{ ...fakeRegistry(["markdown"]), curves: Broken }}>
        <PanelGrid results={results.slice(0, 2)} />
      </PanelRegistryContext.Provider>,
    );
  } finally {
    console.error = quiet;
  }
  const broken = screen.getByRole("region", { name: "b curves" });
  expect(within(broken).getByRole("alert").textContent).toBe("Panel failed: bad rows");
  const note = screen.getByRole("region", { name: "a Note" });
  expect(within(note).getByTestId("panel-markdown").textContent).toBe("Note:0");
});

test("a plain run link inside a panel navigates in-app", () => {
  const navigate = mock((_href: string) => {});
  const RunLink = ({ result }: { result: PanelResult }) => <a href="/r/r9">{result.title}</a>;
  render(
    <NavigateContext.Provider value={navigate}>
      <PanelRegistryContext.Provider value={{ table: RunLink }}>
        <PanelGrid results={[{ type: "table", title: "open r9", rows: [], meta: {} }]} />
      </PanelRegistryContext.Provider>
    </NavigateContext.Provider>,
  );
  const link = screen.getByRole("link", { name: "open r9" });
  expect(fireEvent.click(link)).toBe(false);
  expect(navigate.mock.calls).toEqual([["/r/r9"]]);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/panelGrid.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/PanelGrid'`.

- [ ] **Step 3: Implement the grid**

`ui/src/pages/components/PanelGrid.tsx`:

```tsx
/** Lay out panel results on the 12-column grid, lettered, via the panel registry. */
import { type ComponentType, createContext, useContext } from "react";
import { PANELS, PanelBoundary, PanelError } from "../../panels";
import { Figure, panelLetter } from "./Figure";
import { useInAppLinks } from "./links";
import type { PanelResult, PanelSpec } from "./types";

export type PanelComponent = ComponentType<{ result: PanelResult }>;
export type PanelRegistry = Partial<Record<string, PanelComponent>>;

// The registry's props allow a missing `meta`; API results always carry one, so widen
// the registry's type once here.
export const PanelRegistryContext = createContext<PanelRegistry>(PANELS as unknown as PanelRegistry);

/**
 * Render one panel result with its registered component.
 *
 * A panel whose query failed on the server (`meta.error`, with `rows: []`) shows that
 * reason instead of the panel's empty state. Unknown types and panels that throw show
 * the registry's error box, so one bad panel never blanks the page.
 */
export function PanelBody({ result }: { result: PanelResult }) {
  const registry = useContext(PanelRegistryContext);
  const onLinks = useInAppLinks();
  const failed = result.meta.error;
  if (typeof failed === "string") return <PanelError message={failed} />;
  const Component = registry[result.type];
  if (!Component) return <PanelError message={`Unknown panel type: ${result.type}`} />;
  // Panels render plain <a href> run links; route plain clicks on them in-app.
  return (
    <div className="panel-links" style={{ display: "contents" }} onClick={onLinks}>
      <PanelBoundary>
        <Component result={result} />
      </PanelBoundary>
    </div>
  );
}

/** A grid span in 1..12; missing means full width. */
export function clampSpan(span?: number): number {
  if (span === undefined || !Number.isFinite(span)) return 12;
  return Math.min(12, Math.max(1, Math.round(span)));
}

function warnings(result: PanelResult): string[] {
  const raw = result.meta.warnings;
  return Array.isArray(raw) ? raw.filter((w): w is string => typeof w === "string") : [];
}

export interface PanelGridProps {
  results: PanelResult[];
  specs?: PanelSpec[];
  startIndex?: number;
}

export function PanelGrid({ results, specs, startIndex = 0 }: PanelGridProps) {
  return (
    <div className="panel-grid">
      {results.map((result, i) => {
        const spec = specs?.[i];
        const row = spec?.layout?.row ?? undefined;
        const warn = warnings(result);
        return (
          <Figure
            key={`${i}-${result.type}`}
            letter={panelLetter(startIndex + i)}
            title={result.title || spec?.title || result.type}
            aside={warn.length ? <span title={warn.join("\n")}>⚠ {warn.length}</span> : undefined}
            style={{
              gridColumn: `span ${clampSpan(spec?.layout?.span)}`,
              gridRow: row ? String(row) : undefined,
            }}
          >
            <PanelBody result={result} />
          </Figure>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/panelGrid.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/PanelGrid.tsx ui/test/pages/helpers.tsx \
  ui/test/pages/panelGrid.test.tsx
git commit -m "feat(ui): lettered 12-column panel grid over the panel registry"
```

### Task 26: Idempotent actions (`useAction`)

**Files:**
- Create: `ui/src/pages/components/useAction.ts`
- Test: `ui/test/pages/useAction.test.tsx`

**Interfaces:**
- Consumes: `api`, `ApiError`, `newCommandId` and the `ActionOptions` model (Task 3); TanStack Query `useMutation`.
- Produces:
  - `ACTION_RETRY_DELAY_MS = 250`; `shouldRetry(failureCount: number, error: Error): boolean`
    (retry only requests with no HTTP answer, that is `ApiError` status 0 or a raw network
    error, at most twice).
  - `useAction<T, A = void>({ send, invalidate?, onSuccess? }): { run(arg: A): void; pending: boolean; error: Error | null }`
    where `send: (arg: A, opts: ActionOptions) => Promise<T>` calls an `api.*` action with
    `opts`. Each `run()` makes one new `command_id`; a retry after a dropped connection
    resends the same `command_id` (the server's `run_once` returns the first result).
    `opts.created_by` is `"human"`.

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/useAction.test.tsx`:

```tsx
import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { ApiError, api } from "../../src/api/client";
import { shouldRetry, useAction } from "../../src/pages/components/useAction";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

function Probe({ onDone }: { onDone: (d: { run_id: string }) => void }) {
  const action = useAction<{ run_id: string }>({ send: (_arg, opts) => api.rerun("R", opts), onSuccess: onDone });
  return (
    <div>
      <button type="button" onClick={() => action.run()} disabled={action.pending}>
        go
      </button>
      {action.error ? <p role="alert">{action.error.message}</p> : null}
    </div>
  );
}

test("shouldRetry retries unanswered requests twice and never HTTP errors", () => {
  const net = new TypeError("fetch failed");
  const offline = new ApiError(0, "Cannot reach hx serve", "NetworkError", [], null);
  expect(shouldRetry(0, net)).toBe(true);
  expect(shouldRetry(1, offline)).toBe(true);
  expect(shouldRetry(2, offline)).toBe(false);
  expect(shouldRetry(0, new ApiError(400, "bad", "RunError", [], null))).toBe(false);
});

test("retries a network failure with the same command_id", async () => {
  let attempts = 0;
  const calls = mockApi({
    "POST /api/v1/runs/R/rerun": () => {
      attempts += 1;
      if (attempts === 1) throw new TypeError("connection reset");
      return { run_id: "NEW" };
    },
  });
  const onDone = mock((_d: { run_id: string }) => {});
  renderWithClient(<Probe onDone={onDone} />);
  const button = screen.getByRole("button", { name: "go" });
  fireEvent.click(button);
  await waitFor(() => expect(button.hasAttribute("disabled")).toBe(true));
  await waitFor(() => expect(onDone).toHaveBeenCalledWith({ run_id: "NEW" }));
  expect(calls).toHaveLength(2);
  const [first, second] = calls.map((c) => c.body as Record<string, unknown>);
  expect(typeof first?.command_id).toBe("string");
  expect(second?.command_id).toBe(first?.command_id);
  expect(first?.created_by).toBe("human");
});

test("shows the server error and does not retry it", async () => {
  const calls = mockApi({
    "POST /api/v1/runs/R/rerun": new HttpReply(400, { error: "run is not active", type: "RunError" }),
  });
  renderWithClient(<Probe onDone={() => {}} />);
  fireEvent.click(screen.getByRole("button", { name: "go" }));
  expect((await screen.findByRole("alert")).textContent).toBe("run is not active");
  expect(calls).toHaveLength(1);
});

test("two clicks send two different command_ids", async () => {
  const calls = mockApi({ "POST /api/v1/runs/R/rerun": { run_id: "NEW" } });
  const onDone = mock((_d: { run_id: string }) => {});
  renderWithClient(<Probe onDone={onDone} />);
  const button = screen.getByRole("button", { name: "go" });
  fireEvent.click(button);
  await waitFor(() => expect(onDone).toHaveBeenCalledTimes(1));
  fireEvent.click(button);
  await waitFor(() => expect(onDone).toHaveBeenCalledTimes(2));
  const ids = calls.map((c) => (c.body as { command_id: string }).command_id);
  expect(new Set(ids).size).toBe(2);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/useAction.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/useAction'`.

- [ ] **Step 3: Implement the hook**

`ui/src/pages/components/useAction.ts`:

```ts
/** A POST action with a per-click `command_id`, safe to retry after a dropped connection. */
import { type QueryKey, useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, newCommandId } from "../../api/client";
import type { ActionOptions } from "../../api/models";

export const ACTION_RETRY_DELAY_MS = 250;

/** Retry only requests with no HTTP answer (the server may not have seen them), twice. */
export function shouldRetry(failureCount: number, error: Error): boolean {
  const unanswered = !(error instanceof ApiError) || error.status === 0;
  return failureCount < 2 && unanswered;
}

export interface UseActionOptions<T, A> {
  /** Call one `api.*` action; pass `opts` through so every attempt has the same `command_id`. */
  send: (arg: A, opts: ActionOptions) => Promise<T>;
  invalidate?: readonly QueryKey[];
  onSuccess?: (data: T) => void;
}

export interface Action<A> {
  run: (arg: A) => void;
  pending: boolean;
  error: Error | null;
}

interface Vars<A> {
  commandId: string;
  arg: A;
}

export function useAction<T = unknown, A = void>({
  send,
  invalidate = [],
  onSuccess,
}: UseActionOptions<T, A>): Action<A> {
  const client = useQueryClient();
  const mutation = useMutation<T, Error, Vars<A>>({
    mutationFn: ({ commandId, arg }) => send(arg, { command_id: commandId, created_by: "human" }),
    retry: shouldRetry,
    retryDelay: ACTION_RETRY_DELAY_MS,
    onSuccess: async (data) => {
      await Promise.all(invalidate.map((queryKey) => client.invalidateQueries({ queryKey })));
      onSuccess?.(data);
    },
  });
  return {
    run: (arg: A) => mutation.mutate({ commandId: newCommandId(), arg }),
    pending: mutation.isPending,
    error: mutation.error,
  };
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/useAction.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/useAction.ts ui/test/pages/useAction.test.tsx
git commit -m "feat(ui): idempotent page actions with command_id reuse on retry"
```

### Task 27: Runs-by-launcher timeline

**Files:**
- Create: `ui/src/pages/components/RunTimeline.tsx`
- Test: `ui/test/pages/runTimeline.test.tsx`

**Interfaces:**
- Consumes: `TimelineItem`, `FAILED_STATUSES` (Task 21); `fmtClock`, `fmtTime`, `isAgent`,
  `parseTime` (Task 22); `hrefs`, `useNavigateHref` (Task 23); `d3-scale` `scaleLinear`.
- Produces:
  - `interface TimelineRow { launcher: string; agent: boolean; items: TimelineItem[]; failed: number }`;
    `timelineRows(items): TimelineRow[]` (agents first, then by name; items by time).
  - `type MarkKind = "failed" | "archived" | "best" | "running" | "agent" | "human"`;
    `markKind(item): MarkKind` (in that precedence order).
  - `interface Cluster { label: string; items: TimelineItem[]; best: boolean }`;
    `clusters(items): Cluster[]` (neighbours with the same label); `clusterText(c): string`.
  - `timeTicks(lo: number, hi: number, maxTicks?: number): number[]` (ms; whole
    1/2/5/10/15/30-minute or 1/2/3/6/12/24-hour steps).
  - `RunTimeline({ items })`: SVG with one lane per launcher; each mark is a
    `role="link"` group named `"<label>, <status>[, best], <HH:MM>"` that opens the run.

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/runTimeline.test.tsx`:

```tsx
import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { NavigateContext } from "../../src/pages/components/links";
import {
  RunTimeline,
  clusterText,
  clusters,
  markKind,
  timeTicks,
  timelineRows,
} from "../../src/pages/components/RunTimeline";
import type { TimelineItem } from "../../src/pages/components/types";
import { RUN_FAILED, RUN_SVM, makeOverview } from "./fixtures";

afterEach(cleanup);

function item(over: Partial<TimelineItem>): TimelineItem {
  return {
    run_id: "r",
    project: "p",
    task: "t",
    created_at: "2026-09-26T21:00:00Z",
    created_by: "human",
    status: "finished",
    archived: false,
    group_id: null,
    is_best: false,
    label: "A",
    ...over,
  };
}

describe("timelineRows", () => {
  test("one lane per launcher, agents first, items by time, failures counted", () => {
    const rows = timelineRows(makeOverview().timeline);
    expect(rows.map((r) => [r.launcher, r.agent, r.items.length, r.failed])).toEqual([
      ["agent:acceptance", true, 2, 1],
      ["human", false, 1, 0],
    ]);
    expect(rows[0]?.items.map((i) => i.run_id)).toEqual([RUN_FAILED, RUN_SVM]);
  });
});

test("markKind precedence: failed, archived, best, running, launcher", () => {
  expect(markKind(item({ status: "failed", archived: true }))).toBe("failed");
  expect(markKind(item({ status: "lost" }))).toBe("failed");
  expect(markKind(item({ archived: true, is_best: true }))).toBe("archived");
  expect(markKind(item({ is_best: true }))).toBe("best");
  expect(markKind(item({ status: "running" }))).toBe("running");
  expect(markKind(item({ created_by: "agent:tuner" }))).toBe("agent");
  expect(markKind(item({}))).toBe("human");
});

test("clusters merge neighbours with the same label", () => {
  const got = clusters([
    item({ run_id: "1", label: "A" }),
    item({ run_id: "2", label: "A", is_best: true }),
    item({ run_id: "3", label: "B" }),
    item({ run_id: "4", label: "A" }),
  ]);
  expect(got.map((c) => [c.label, c.items.length, c.best])).toEqual([
    ["A", 2, true],
    ["B", 1, false],
    ["A", 1, false],
  ]);
  expect(got.map(clusterText)).toEqual(["A, best", "B", "A"]);
});

test("timeTicks picks whole minutes for minutes and 6 h steps for a day", () => {
  const t = (iso: string) => Date.parse(iso);
  expect(timeTicks(t("2026-09-26T21:00:32Z"), t("2026-09-26T21:03:06Z"))).toEqual([
    t("2026-09-26T21:01:00Z"),
    t("2026-09-26T21:02:00Z"),
    t("2026-09-26T21:03:00Z"),
  ]);
  // 1420 min / 6 ticks = 237 min, so the first step with at most 6 ticks is 360 min
  expect(timeTicks(t("2026-09-26T00:10:00Z"), t("2026-09-26T23:50:00Z"))).toEqual([
    t("2026-09-26T06:00:00Z"),
    t("2026-09-26T12:00:00Z"),
    t("2026-09-26T18:00:00Z"),
  ]);
});

test("renders lanes, marks, cluster labels, and ticks; a mark opens its run", () => {
  const navigate = mock((_href: string) => {});
  const { container } = render(
    <NavigateContext.Provider value={navigate}>
      <RunTimeline items={makeOverview().timeline} />
    </NavigateContext.Provider>,
  );
  // the legend below the chart repeats "human"/"agent", so look inside the chart only
  const svg = container.querySelector("svg[aria-label='Runs by launcher over time']") as HTMLElement;
  const texts = ["agent:acceptance", "2 runs, 1 failed", "human", "1 run", "RBF-kernel SVM, best", "Baseline rf", "21:01", "21:02", "21:03"];
  for (const text of texts) expect(within(svg).getByText(text)).toBeTruthy();
  const kinds = [...container.querySelectorAll("[data-mark]")].map((m) => m.getAttribute("data-mark"));
  expect(kinds).toEqual(["failed", "best", "human"]);
  fireEvent.click(screen.getByRole("link", { name: "RBF-kernel SVM, finished, best, 21:03" }));
  expect(navigate).toHaveBeenCalledWith(`/r/${RUN_SVM}`);
});

test("an empty window says so", () => {
  render(<RunTimeline items={[]} />);
  expect(screen.getByText("no runs in this window")).toBeTruthy();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/runTimeline.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/RunTimeline'`.

- [ ] **Step 3: Implement the timeline**

`ui/src/pages/components/RunTimeline.tsx`:

```tsx
/** Overview panel: runs over time, one lane per launcher (agent vs human, spec 8.3.1). */
import { scaleLinear } from "d3-scale";
import { fmtClock, fmtTime, isAgent, parseTime } from "./format";
import { hrefs, useNavigateHref } from "./links";
import { FAILED_STATUSES, type TimelineItem } from "./types";

const W = 1000;
const LEFT = 190;
const PAD = 14;
const TOP = 26;
const ROW_H = 64;
const AXIS_H = 30;
const STEPS_MIN = [1, 2, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1440];

export interface TimelineRow {
  launcher: string;
  agent: boolean;
  items: TimelineItem[];
  failed: number;
}

const at = (item: TimelineItem): number => parseTime(item.created_at);

/** Group items by launcher; agent lanes first, then by name; items oldest first. */
export function timelineRows(items: TimelineItem[]): TimelineRow[] {
  const byLauncher = new Map<string, TimelineItem[]>();
  for (const item of items) {
    const list = byLauncher.get(item.created_by) ?? [];
    list.push(item);
    byLauncher.set(item.created_by, list);
  }
  return [...byLauncher.entries()]
    .map(([launcher, list]) => ({
      launcher,
      agent: isAgent(launcher),
      items: [...list].sort((a, b) => at(a) - at(b)),
      failed: list.filter((i) => FAILED_STATUSES.has(i.status)).length,
    }))
    .sort((a, b) => Number(b.agent) - Number(a.agent) || a.launcher.localeCompare(b.launcher));
}

export type MarkKind = "failed" | "archived" | "best" | "running" | "agent" | "human";

/** How to draw one run: failure beats archived beats best beats running. */
export function markKind(item: TimelineItem): MarkKind {
  if (FAILED_STATUSES.has(item.status)) return "failed";
  if (item.archived) return "archived";
  if (item.is_best) return "best";
  if (item.status === "running" || item.status === "queued") return "running";
  return isAgent(item.created_by) ? "agent" : "human";
}

export interface Cluster {
  label: string;
  items: TimelineItem[];
  best: boolean;
}

/** Merge neighbouring runs with the same label so each idea is labelled once. */
export function clusters(items: TimelineItem[]): Cluster[] {
  const out: Cluster[] = [];
  for (const item of items) {
    const last = out[out.length - 1];
    if (last && last.label === item.label) {
      last.items.push(item);
      last.best = last.best || item.is_best;
    } else {
      out.push({ label: item.label, items: [item], best: item.is_best });
    }
  }
  return out;
}

export function clusterText(c: Cluster): string {
  return c.best ? `${c.label}, best` : c.label;
}

/** Tick times (ms) on whole minutes or hours, at most `maxTicks` of them. */
export function timeTicks(lo: number, hi: number, maxTicks = 6): number[] {
  const spanMin = (hi - lo) / 60_000;
  const step = (STEPS_MIN.find((s) => spanMin / s <= maxTicks) ?? 1440) * 60_000;
  const out: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= hi; t += step) out.push(t);
  return out;
}

function Mark({ kind, agent }: { kind: MarkKind; agent: boolean }) {
  const color = agent ? "var(--agent)" : "var(--human)";
  switch (kind) {
    case "failed":
      return <path d="M-4,-4L4,4M4,-4L-4,4" stroke="var(--fail)" strokeWidth={1.8} />;
    case "archived":
      return <circle r={4.2} fill="none" stroke={color} strokeWidth={1.4} />;
    case "best":
      return <circle r={4.6} fill="var(--best)" />;
    case "running":
      return <circle r={4.2} fill="none" stroke="var(--ink)" strokeWidth={1.4} strokeDasharray="2 2" />;
    case "agent":
      return <circle r={4.6} fill={color} />;
    case "human":
      return <rect x={-4.2} y={-4.2} width={8.4} height={8.4} fill={color} />;
  }
}

function markName(item: TimelineItem): string {
  return `${item.label}, ${item.status}${item.is_best ? ", best" : ""}, ${fmtClock(item.created_at)}`;
}

function Key() {
  const entries: [MarkKind, boolean, string][] = [
    ["agent", true, "agent"],
    ["human", false, "human"],
    ["best", true, "current best"],
    ["failed", true, "failed"],
    ["archived", true, "archived"],
  ];
  return (
    <div className="key">
      {entries.map(([kind, agent, text]) => (
        <span key={text}>
          <svg width="12" height="12" viewBox="-6 -6 12 12" aria-hidden="true">
            <Mark kind={kind} agent={agent} />
          </svg>
          {text}
        </span>
      ))}
    </div>
  );
}

export function RunTimeline({ items }: { items: TimelineItem[] }) {
  const navigate = useNavigateHref();
  if (items.length === 0) return <p className="small">no runs in this window</p>;
  const rows = timelineRows(items);
  const times = items.map(at);
  let lo = Math.min(...times);
  let hi = Math.max(...times);
  if (hi - lo < 60_000) {
    lo -= 30_000;
    hi += 30_000;
  }
  const x = scaleLinear().domain([lo, hi]).range([LEFT + PAD, W - PAD]);
  const height = TOP + rows.length * ROW_H + AXIS_H;
  const axisY = height - AXIS_H;
  return (
    <div className="timeline">
      <svg viewBox={`0 0 ${W} ${height}`} aria-label="Runs by launcher over time">
        {timeTicks(lo, hi).map((t) => (
          <g key={t} transform={`translate(${x(t)},0)`}>
            <line className="grid" y1={TOP - 16} y2={axisY} />
            <text className="tick" y={axisY + 18} textAnchor="middle">
              {fmtClock(new Date(t).toISOString())}
            </text>
          </g>
        ))}
        <line className="axis" x1={LEFT + PAD} x2={W - PAD} y1={axisY} y2={axisY} />
        {rows.map((row, ri) => {
          const y = TOP + ri * ROW_H + ROW_H / 2;
          return (
            <g key={row.launcher} data-row={row.launcher}>
              <text className="ln" x={14} y={y - 2}>
                {row.launcher}
              </text>
              <g transform={`translate(4,${y - 6})`}>
                <Mark kind={row.agent ? "agent" : "human"} agent={row.agent} />
              </g>
              <text className="lc" x={14} y={y + 14}>
                {`${row.items.length} ${row.items.length === 1 ? "run" : "runs"}${row.failed ? `, ${row.failed} failed` : ""}`}
              </text>
              <line className="lane" x1={LEFT + PAD} x2={W - PAD} y1={y} y2={y} />
              {clusters(row.items).map((c) => {
                const cx = c.items.reduce((sum, i) => sum + x(at(i)), 0) / c.items.length;
                return (
                  <text
                    key={`${c.label}-${c.items[0]?.run_id ?? ""}`}
                    className={c.best ? "cl best" : "cl"}
                    x={cx}
                    y={y - 12}
                    textAnchor="middle"
                  >
                    {clusterText(c)}
                  </text>
                );
              })}
              {row.items.map((item) => {
                const kind = markKind(item);
                const href = hrefs.run(item.run_id);
                return (
                  <g
                    key={item.run_id}
                    className="mark"
                    data-mark={kind}
                    role="link"
                    tabIndex={0}
                    aria-label={markName(item)}
                    transform={`translate(${x(at(item))},${y})`}
                    onClick={() => navigate(href)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") navigate(href);
                    }}
                  >
                    <title>{`${item.label} · ${item.status} · ${fmtTime(item.created_at)} · ${item.run_id}`}</title>
                    <Mark kind={kind} agent={row.agent} />
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>
      <Key />
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/runTimeline.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/RunTimeline.tsx ui/test/pages/runTimeline.test.tsx
git commit -m "feat(ui): runs-by-launcher timeline for the overview"
```

### Task 28: Overview lists (ideas, running, failures, projects)

**Files:**
- Create: `ui/src/pages/components/IdeaList.tsx`
- Create: `ui/src/pages/components/OverviewLists.tsx`
- Test: `ui/test/pages/overviewLists.test.tsx`

**Interfaces:**
- Consumes: `IdeaRow`, `RunRecord`, `FailureRow`, `ProjectRow`, `ACTIVE_STATUSES`,
  `FAILED_STATUSES` (Task 21); `fmtScore`, `fmtInterval`, `fmtClock`, `fmtTime`, `firstClause`,
  `shortId`, `tailPath`, `isAgent`, `isNum` (Task 22); `AppLink`, `hrefs` (Task 23);
  `CopyButton` (Task 24); `d3-scale` `scaleLinear`.
- Produces:
  - `ideaDomain(ideas: IdeaRow[]): [number, number] | null` (all interval ends and
    means, padded 5%); `ideaScore(idea): string`; `ideaSub(idea): string`
    (`◇×n` for identical seeds, `± std` for n > 1, `1 seed`, or `""`).
  - `IdeaList({ ideas })`: one row per seed group: one mark per seed, name (link to the
    task), launcher and time, test-set interval against the best band, score.
  - `RunningList({ runs })`, `FailureList({ failures })`, `ProjectsTable({ projects })`.

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/overviewLists.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { IdeaList, ideaDomain, ideaScore, ideaSub } from "../../src/pages/components/IdeaList";
import { FailureList, ProjectsTable, RunningList } from "../../src/pages/components/OverviewLists";
import type { IdeaRow } from "../../src/pages/components/types";
import { RUN_FAILED, RUN_SVM, STORE, makeOverview, makeRecord } from "./fixtures";
import { mockClipboard } from "./helpers";

afterEach(cleanup);

const ideas = makeOverview().ideas;

describe("idea helpers", () => {
  test("ideaDomain spans every interval end and mean, padded by 5%", () => {
    // lo = 0.83 (rf interval), hi = 0.953 (best band); pad = 0.123 * 0.05 = 0.00615
    const [lo, hi] = ideaDomain(ideas) ?? [0, 0];
    expect(lo).toBeCloseTo(0.82385, 6);
    expect(hi).toBeCloseTo(0.95915, 6);
    expect(ideaDomain([])).toBeNull();
  });

  test("ideaScore and ideaSub", () => {
    const [svm, failed, rf] = ideas as [IdeaRow, IdeaRow, IdeaRow];
    expect([ideaScore(svm), ideaSub(svm)]).toEqual(["0.9222", "◇×3"]);
    expect([ideaScore(failed), ideaSub(failed)]).toEqual(["failed", ""]);
    expect([ideaScore(rf), ideaSub(rf)]).toEqual(["0.8852", "± 0.0064"]);
    const running: IdeaRow = { ...failed, statuses: ["running", "finished"] };
    expect(ideaScore(running)).toBe("running");
    const one: IdeaRow = { ...rf, primary: { mean: 0.5, std: 0, n: 1, ci_low: null, ci_high: null } };
    expect(ideaSub(one)).toBe("1 seed");
  });
});

test("IdeaList draws one mark per seed and dims failed groups", () => {
  const { container } = render(<IdeaList ideas={ideas} />);
  expect(container.querySelectorAll("[data-seed]")).toHaveLength(9);
  expect(container.querySelectorAll("[data-seed='failed']")).toHaveLength(3);
  const rows = container.querySelectorAll("li.idea");
  expect(rows).toHaveLength(3);
  expect(rows[1]?.classList.contains("dim")).toBe(true);
  expect(rows[0]?.querySelector("svg.iv title")?.textContent).toBe("95% CI 0.874–0.953");
  const name = within(rows[0] as HTMLElement).getByRole("link", { name: "RBF-kernel SVM" });
  expect(name.getAttribute("href")).toBe("/t/toy-classifier/toy-test");
  expect(within(rows[2] as HTMLElement).getByText("human, 21:00")).toBeTruthy();
});

test("RunningList shows none, or one link per run", () => {
  const { rerender } = render(<RunningList runs={[]} />);
  expect(screen.getByText("none")).toBeTruthy();
  rerender(<RunningList runs={[makeRecord({ status: "running", ended_at: null })]} />);
  expect(screen.getByRole("link", { name: "RBF-kernel SVM" }).getAttribute("href")).toBe(`/r/${RUN_SVM}`);
});

test("FailureList links to stderr and copies its path", async () => {
  const written = mockClipboard();
  render(<FailureList failures={makeOverview().failures} />);
  expect(screen.getByText("SVM, exit 2")).toBeTruthy();
  expect(screen.getByText("21:01:58 UTC, retry ok")).toBeTruthy();
  expect(screen.getByText("…/20260926-210158-toy-test-58c5/logs/stderr.log")).toBeTruthy();
  const open = screen.getByRole("link", { name: "Open stderr" });
  expect(open.getAttribute("href")).toBe(`/r/${RUN_FAILED}?log=stderr`);
  fireEvent.click(screen.getByRole("button", { name: "Copy stderr path" }));
  await waitFor(() => expect(written).toEqual([`${STORE}/${RUN_FAILED}/logs/stderr.log`]));
});

test("ProjectsTable links each task and shows runs and best", () => {
  render(<ProjectsTable projects={makeOverview().projects} />);
  const link = screen.getByRole("link", { name: "toy-classifier / toy-test" });
  expect(link.getAttribute("href")).toBe("/t/toy-classifier/toy-test");
  const cells = screen.getAllByRole("cell").map((c) => c.textContent);
  expect(cells).toEqual(["toy-classifier / toy-test", "12", "0.9222"]);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/overviewLists.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/IdeaList'`.

- [ ] **Step 3: Implement the lists**

`ui/src/pages/components/IdeaList.tsx`:

```tsx
/** Overview panel: recent ideas, one row per seed group with seed marks and intervals. */
import { scaleLinear } from "d3-scale";
import { DASH, fmtClock, fmtInterval, fmtScore, isAgent, isNum } from "./format";
import { AppLink, hrefs } from "./links";
import { ACTIVE_STATUSES, FAILED_STATUSES, type IdeaRow, type RunStatus } from "./types";

const STRIP_W = 420;
const STRIP_H = 30;

/** The shared x domain of every row's interval, best band, and mean, padded 5%. */
export function ideaDomain(ideas: IdeaRow[]): [number, number] | null {
  const values: number[] = [];
  for (const idea of ideas) {
    const candidates = [
      idea.test_interval?.lo,
      idea.test_interval?.hi,
      idea.best_band?.lo,
      idea.best_band?.hi,
      idea.primary?.mean,
    ];
    for (const v of candidates) if (isNum(v)) values.push(v);
  }
  if (values.length === 0) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const pad = (hi - lo) * 0.05 || 0.01;
  return [lo - pad, hi + pad];
}

/** The big number of a row, or what happened instead. */
export function ideaScore(idea: IdeaRow): string {
  if (idea.primary) return fmtScore(idea.primary.mean);
  if (idea.statuses.some((s) => ACTIVE_STATUSES.has(s))) return "running";
  if (idea.statuses.length > 0 && idea.statuses.every((s) => FAILED_STATUSES.has(s))) {
    return "failed";
  }
  return DASH;
}

/** Seed noise under the score: identical seeds collapse to `◇×n`, never `± 0`. */
export function ideaSub(idea: IdeaRow): string {
  const p = idea.primary;
  if (!p) return "";
  if (idea.identical_seeds) return `◇×${p.n}`;
  if (p.n > 1) return `± ${fmtScore(p.std)}`;
  return "1 seed";
}

function SeedMark({ status, agent }: { status: RunStatus; agent: boolean }) {
  if (FAILED_STATUSES.has(status)) {
    return (
      <svg width="12" height="12" viewBox="-6 -6 12 12" data-seed="failed" aria-hidden="true">
        <path d="M-4,-4L4,4M4,-4L-4,4" stroke="var(--fail)" strokeWidth={1.8} />
      </svg>
    );
  }
  if (ACTIVE_STATUSES.has(status)) {
    return (
      <svg width="12" height="12" viewBox="-6 -6 12 12" data-seed="running" aria-hidden="true">
        <circle r={4.2} fill="none" stroke="var(--ink)" strokeWidth={1.4} strokeDasharray="2 2" />
      </svg>
    );
  }
  return (
    <svg width="12" height="12" viewBox="-6 -6 12 12" data-seed="ok" aria-hidden="true">
      <circle r={4.6} fill={agent ? "var(--agent)" : "var(--human)"} />
    </svg>
  );
}

function IntervalStrip({ idea, domain }: { idea: IdeaRow; domain: [number, number] }) {
  const x = scaleLinear().domain(domain).range([4, STRIP_W - 4]);
  const mid = STRIP_H / 2;
  const band = idea.best_band;
  const iv = idea.test_interval;
  return (
    <svg className="iv" viewBox={`0 0 ${STRIP_W} ${STRIP_H}`} preserveAspectRatio="none">
      {iv ? <title>{`95% CI ${fmtInterval(iv.lo, iv.hi)}`}</title> : null}
      {band ? (
        <rect
          x={x(band.lo)}
          y={0}
          width={Math.max(0, x(band.hi) - x(band.lo))}
          height={STRIP_H}
          fill="var(--best-wash)"
          stroke="var(--best-edge)"
        />
      ) : null}
      {iv ? (
        <g stroke="var(--ink-2)">
          <line x1={x(iv.lo)} x2={x(iv.hi)} y1={mid} y2={mid} />
          <line x1={x(iv.lo)} x2={x(iv.lo)} y1={mid - 5} y2={mid + 5} />
          <line x1={x(iv.hi)} x2={x(iv.hi)} y1={mid - 5} y2={mid + 5} />
        </g>
      ) : null}
      {idea.primary ? (
        <rect x={x(idea.primary.mean) - 3.5} y={mid - 3.5} width={7} height={7} fill="var(--ink)" />
      ) : null}
    </svg>
  );
}

function Axis({ domain }: { domain: [number, number] }) {
  const x = scaleLinear().domain(domain).range([4, STRIP_W - 4]);
  return (
    <div className="idea idea-axis">
      <span />
      <span />
      <svg viewBox={`0 0 ${STRIP_W} 24`}>
        {x.ticks(4).map((t) => (
          <text key={t} x={x(t)} y={16} textAnchor="middle">
            {t.toFixed(2)}
          </text>
        ))}
      </svg>
      <span />
    </div>
  );
}

export function IdeaList({ ideas }: { ideas: IdeaRow[] }) {
  if (ideas.length === 0) return <p className="small">no ideas in this window</p>;
  const domain = ideaDomain(ideas);
  return (
    <div>
      <ul className="ideas">
        {ideas.map((idea) => {
          const agent = isAgent(idea.created_by);
          return (
            <li key={idea.group_id} className={idea.primary ? "idea" : "idea dim"}>
              <span className="mks">
                {idea.statuses.map((status, i) => (
                  <SeedMark key={`${i}-${status}`} status={status} agent={agent} />
                ))}
              </span>
              <div>
                <div className="nm">
                  {idea.task ? (
                    <AppLink href={hrefs.task(idea.project, idea.task)}>{idea.label}</AppLink>
                  ) : (
                    idea.label
                  )}
                </div>
                <div className="meta">{`${idea.created_by}, ${fmtClock(idea.created_at)}`}</div>
              </div>
              {domain ? <IntervalStrip idea={idea} domain={domain} /> : <span />}
              <div className="sc">
                {ideaScore(idea)}
                <small title={idea.identical_seeds ? "all seeds gave the same score" : undefined}>
                  {ideaSub(idea)}
                </small>
              </div>
            </li>
          );
        })}
      </ul>
      {domain ? <Axis domain={domain} /> : null}
    </div>
  );
}
```

`ui/src/pages/components/OverviewLists.tsx`:

```tsx
/** Overview side panels: running runs, failures, projects. */
import { CopyButton } from "./CopyButton";
import { firstClause, fmtClock, fmtScore, fmtTime, shortId, tailPath } from "./format";
import { AppLink, hrefs } from "./links";
import type { FailureRow, ProjectRow, RunRecord } from "./types";

export function RunningList({ runs }: { runs: RunRecord[] }) {
  if (runs.length === 0) return <p className="small">none</p>;
  return (
    <ul className="plain">
      {runs.map((run) => (
        <li key={run.run_id}>
          <AppLink href={hrefs.run(run.run_id)}>
            {firstClause(run.hypothesis, `run ${shortId(run.run_id)}`)}
          </AppLink>
          <div className="small">
            {`${run.created_by}, ${fmtClock(run.started_at ?? run.created_at)}${run.task ? `, ${run.task}` : ""}`}
          </div>
        </li>
      ))}
    </ul>
  );
}

export function FailureList({ failures }: { failures: FailureRow[] }) {
  if (failures.length === 0) return <p className="small">none</p>;
  return (
    <div>
      {failures.map((f) => (
        <div key={f.run_id} className="fail-b">
          <span className="x">×</span>
          <b>{f.exit_code !== null ? `${f.label}, exit ${f.exit_code}` : f.label}</b>{" "}
          <span className="small">{`${fmtTime(f.created_at)}${f.retried_ok ? ", retry ok" : ""}`}</span>
          <div className="p" title={f.stderr_path}>
            {tailPath(f.stderr_path)}
          </div>
          <div className="row">
            <AppLink className="btn" href={hrefs.run(f.run_id, { log: "stderr" })}>
              Open stderr
            </AppLink>
            <CopyButton text={f.stderr_path} label="stderr path" />
          </div>
        </div>
      ))}
    </div>
  );
}

export function ProjectsTable({ projects }: { projects: ProjectRow[] }) {
  if (projects.length === 0) return <p className="small">none</p>;
  return (
    <table className="tbl">
      <thead>
        <tr>
          <th>Task</th>
          <th className="r">Runs</th>
          <th className="r">Best</th>
        </tr>
      </thead>
      <tbody>
        {projects.map((p) => (
          <tr key={`${p.project}/${p.task}`} title={p.kind}>
            <td>
              <AppLink href={hrefs.task(p.project, p.task)}>{`${p.project} / ${p.task}`}</AppLink>
            </td>
            <td className="r">{p.runs}</td>
            <td className="r">{fmtScore(p.best)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/overviewLists.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/IdeaList.tsx ui/src/pages/components/OverviewLists.tsx \
  ui/test/pages/overviewLists.test.tsx
git commit -m "feat(ui): overview ideas, running, failures, and projects lists"
```

### Task 29: Overview page

**Files:**
- Create: `ui/src/pages/Overview.tsx`
- Modify: `ui/src/router.tsx` (the `/` route renders `OverviewPage`)
- Test: `ui/test/pages/Overview.test.tsx`

**Interfaces:**
- Consumes: `GET /api/v1/overview` → `OverviewSummary` (contract 1.9, 2) through `useOverview`
  (Task 4); `Figure`, `PageStyles`, `ErrorBox`, `Loading` (Task 24); `RunTimeline` (Task 27);
  `IdeaList`, `RunningList`, `FailureList`, `ProjectsTable` (Task 28).
- Produces: `OverviewPage()` for route `/`: crumb `All projects`, headline
  (`summary.headline`), counts line, panels a Runs by launcher, b Ideas, c Running,
  d Failures, e Projects.

- [ ] **Step 1: Write the failing test**

`ui/test/pages/Overview.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { cleanup, screen, within } from "@testing-library/react";
import { OverviewPage } from "../../src/pages/Overview";
import { makeOverview } from "./fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

test("renders the headline, counts, and lettered panels", async () => {
  mockApi({ "GET /api/v1/overview": makeOverview() });
  renderWithClient(<OverviewPage />);
  const h1 = await screen.findByRole("heading", { level: 1 });
  expect(h1.textContent).toBe("Idle. SVM leads toy-test by 0.037, p = 0.15");
  for (const text of ["19 runs today", "3 failed", "1 task"]) expect(screen.getByText(text)).toBeTruthy();
  const names = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
  expect(names).toEqual(["a Runs by launcher", "b Ideas", "c Running", "d Failures", "e Projects"]);
  expect(within(screen.getByRole("region", { name: "c Running" })).getByText("none")).toBeTruthy();
  const projects = screen.getByRole("region", { name: "e Projects" });
  expect(within(projects).getByText("0.9222")).toBeTruthy();
});

test("shows the server error", async () => {
  mockApi({ "GET /api/v1/overview": new HttpReply(500, { error: "index locked", type: "StoreError" }) });
  renderWithClient(<OverviewPage />);
  expect((await screen.findByRole("alert")).textContent).toBe("index locked");
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/pages/Overview.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/Overview'`.

- [ ] **Step 3: Implement the page**

`ui/src/pages/Overview.tsx`:

```tsx
/**
 * Overview screen (spec 8.3.1): status headline; runs by launcher; recent ideas;
 * running; failures with a link to stderr; projects table.
 */
import { useOverview } from "../api/queries";
import { Figure } from "./components/Figure";
import { IdeaList } from "./components/IdeaList";
import { FailureList, ProjectsTable, RunningList } from "./components/OverviewLists";
import { ErrorBox, Loading } from "./components/QueryState";
import { RunTimeline } from "./components/RunTimeline";
import { PageStyles } from "./components/styles";
import type { OverviewSummary } from "./components/types";

function OverviewBody({ summary }: { summary: OverviewSummary }) {
  return (
    <>
      <h1 className="headline">{summary.headline}</h1>
      <p className="metaline">
        {Object.entries(summary.counts).map(([key, value]) => (
          <span key={key}>{`${value} ${key}`}</span>
        ))}
      </p>
      <Figure letter="a" title="Runs by launcher">
        <RunTimeline items={summary.timeline} />
      </Figure>
      <div className="ov-grid">
        <div>
          <Figure letter="b" title="Ideas">
            <IdeaList ideas={summary.ideas} />
          </Figure>
        </div>
        <div className="side">
          <Figure letter="c" title="Running">
            <RunningList runs={summary.running} />
          </Figure>
          <Figure letter="d" title="Failures">
            <FailureList failures={summary.failures} />
          </Figure>
          <Figure letter="e" title="Projects">
            <ProjectsTable projects={summary.projects} />
          </Figure>
        </div>
      </div>
    </>
  );
}

export function OverviewPage() {
  const overview = useOverview();
  return (
    <div className="page">
      <PageStyles />
      <p className="crumb">All projects</p>
      {overview.error ? <ErrorBox error={overview.error} /> : null}
      {overview.data ? (
        <OverviewBody summary={overview.data} />
      ) : overview.error ? null : (
        <Loading />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ui && bun test test/pages/Overview.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 5: Show the page on `/`**

In `ui/src/router.tsx` replace

```tsx
import { CommandPalette } from "./shell/CommandPalette";
```

with

```tsx
import { OverviewPage } from "./pages/Overview";
import { CommandPalette } from "./shell/CommandPalette";
```

and replace

```tsx
  path: "/",
  component: () => <ScreenPending name="Overview" />,
```

with

```tsx
  path: "/",
  component: OverviewPage,
```

Run: `cd ui && bun test test/router.test.tsx test/shell && bun run typecheck`
Expected: `0 fail` (the shell tests wait on routes and the header, not on page text); `tsc` prints nothing.

- [ ] **Step 6: Commit**

```bash
git add ui/src/pages/Overview.tsx ui/test/pages/Overview.test.tsx ui/src/router.tsx
git commit -m "feat(ui): overview page"
```

### Task 30: Task page with view tabs

**Files:**
- Create: `ui/src/pages/Task.tsx`
- Modify: `ui/src/router.tsx` (the task route renders `TaskPage`)
- Test: `ui/test/pages/Task.test.tsx`

**Interfaces:**
- Consumes: `GET /tasks/{p}/{t}/leaderboard` → `Leaderboard` (with `headline`, `kind`);
  `GET /tasks/{p}/{t}/views` → `ViewInfo[]`; `GET /tasks/{p}/{t}/views/{name}` →
  `ViewDetail` (panel layouts); `POST /tasks/{p}/{t}/views/query` `{name}` →
  `QueryResponse`; `POST /tasks/{p}/{t}/reeval` `{command_id, created_by}` (phase 1a).
  Task 3 `api`; Task 4 `useLeaderboard`, `useViews`, `useView`, `useViewQuery`,
  `RUN_EVENT_INVALIDATES`; Task 23 `AppLink`, `hrefs`; Task 24 `PageStyles`, `ErrorBox`,
  `Loading`; Task 25 `PanelGrid`; Task 26 `useAction`.
- Produces: `TaskPage({ project, task, view? })` for `/t/:project/:task?view=<name>`
  (default view `overview`, the kind preset); `boardMeta(board: Leaderboard): string[]`.

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/Task.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import type { QueryResponse, ViewDetail, ViewInfo } from "../../src/pages/components/types";
import { TaskPage, boardMeta } from "../../src/pages/Task";
import { makeBoard } from "./fixtures";
import { type Call, HttpReply, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const BASE = "/api/v1/tasks/toy-classifier/toy-test";

const VIEWS: ViewInfo[] = [
  { name: "overview", title: "Overview", origin: "preset", path: null, kind: "generic" },
  {
    name: "route-quality",
    title: "route quality",
    origin: "file",
    path: "/repo/.hypothex/views/toy-test/route-quality.yaml",
    kind: null,
  },
];

function detail(info: ViewInfo): ViewDetail {
  return {
    info,
    text: `title: ${info.title}\n`,
    view: {
      title: info.title,
      panels: [
        { type: "stat_strip", title: "Best", data: {}, layout: { span: 4, row: null } },
        { type: "leaderboard", title: "All ideas", data: {}, layout: { span: 8, row: null } },
      ],
    },
  };
}

const PANELS: QueryResponse = {
  panels: [
    { type: "stat_strip", title: "Best", rows: [{ label: "solved v2", value: "0.733" }], meta: {} },
    { type: "leaderboard", title: "All ideas", rows: [{}, {}], meta: {} },
  ],
};

function routes(view: string): Record<string, unknown> {
  const info = VIEWS.find((v) => v.name === view) as ViewInfo;
  return {
    [`GET ${BASE}/leaderboard`]: makeBoard(),
    [`GET ${BASE}/views`]: VIEWS,
    [`GET ${BASE}/views/${view}`]: detail(info),
    [`POST ${BASE}/views/query`]: PANELS,
    [`POST ${BASE}/reeval`]: { evaluated: 12 },
  };
}

const registry = fakeRegistry(["stat_strip", "leaderboard"]);

test("boardMeta counts configs and runs and lists metric versions", () => {
  expect(boardMeta(makeBoard())).toEqual(["2 configs, 6 runs", "accuracy v1", "macro_f1 v1"]);
  expect(boardMeta({ ...makeBoard(), needs_reeval: ["r1"] }).at(-1)).toBe("1 need re-eval");
});

describe("TaskPage", () => {
  test("renders headline, tabs, and the active view's lettered panels", async () => {
    const calls = mockApi(routes("route-quality"));
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" view="route-quality" />, {
      registry,
    });
    const h1 = await screen.findByRole("heading", { level: 1, name: "SVM +0.037 over rf, p = 0.15" });
    expect(h1).toBeTruthy();
    expect(screen.getByText("generic")).toBeTruthy();
    expect(screen.getByText("2 configs, 6 runs")).toBeTruthy();

    const tabs = screen.getByRole("navigation", { name: "Views" });
    const overview = within(tabs).getByRole("link", { name: "Overview preset" });
    expect(overview.getAttribute("href")).toBe("/t/toy-classifier/toy-test");
    expect(overview.getAttribute("aria-current")).toBeNull();
    const active = within(tabs).getByRole("link", { name: "route quality" });
    expect(active.getAttribute("href")).toBe("/t/toy-classifier/toy-test?view=route-quality");
    expect(active.getAttribute("aria-current")).toBe("page");
    expect(within(tabs).getByRole("link", { name: "+ view" }).getAttribute("href")).toBe(
      "/t/toy-classifier/toy-test/edit/new",
    );
    expect(within(tabs).getByRole("link", { name: "Edit" }).getAttribute("href")).toBe(
      "/t/toy-classifier/toy-test/edit/route-quality",
    );

    const best = await screen.findByRole("region", { name: "a Best" });
    expect(best.style.gridColumn).toBe("span 4");
    const ideas = screen.getByRole("region", { name: "b All ideas" });
    expect(ideas.style.gridColumn).toBe("span 8");
    expect(within(ideas).getByTestId("panel-leaderboard").textContent).toBe("All ideas:2");
    expect(within(tabs).getByText("2 panels")).toBeTruthy();

    const query = calls.find((c: Call) => c.url === `${BASE}/views/query`);
    expect(query?.body).toEqual({ name: "route-quality" });
  });

  test("defaults to the overview preset, which has no Edit button", async () => {
    const calls = mockApi(routes("overview"));
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    const tabs = screen.getByRole("navigation", { name: "Views" });
    expect(within(tabs).getByRole("link", { name: "Overview preset" }).getAttribute("aria-current")).toBe(
      "page",
    );
    expect(within(tabs).queryByRole("link", { name: "Edit" })).toBeNull();
    expect(calls.find((c) => c.url === `${BASE}/views/query`)?.body).toEqual({ name: "overview" });
  });

  test("Re-evaluate all posts to the task reeval route with a command_id", async () => {
    const calls = mockApi(routes("overview"));
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" />, { registry });
    await screen.findByRole("region", { name: "a Best" });
    fireEvent.click(screen.getByRole("button", { name: "Re-evaluate all" }));
    await waitFor(() => expect(calls.some((c) => c.url === `${BASE}/reeval`)).toBe(true));
    const body = calls.find((c) => c.url === `${BASE}/reeval`)?.body as Record<string, unknown>;
    expect(typeof body.command_id).toBe("string");
    expect(body.created_by).toBe("human");
  });

  test("shows the error for an unknown view", async () => {
    mockApi({
      ...routes("overview"),
      [`GET ${BASE}/views/nope`]: new HttpReply(404, { error: "no view 'nope' for toy-test", type: "StoreError" }),
      [`POST ${BASE}/views/query`]: new HttpReply(404, { error: "no view 'nope' for toy-test", type: "StoreError" }),
    });
    renderWithClient(<TaskPage project="toy-classifier" task="toy-test" view="nope" />, { registry });
    expect((await screen.findByRole("alert")).textContent).toBe("no view 'nope' for toy-test");
    expect(screen.queryByRole("region")).toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/Task.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/Task'`.

- [ ] **Step 3: Implement the page**

`ui/src/pages/Task.tsx`:

```tsx
/**
 * Task screen (spec 8.3.2): the leaderboard's one-line headline, view tabs (the kind's
 * preset, custom views, `+ view`), and the active view's panels on a 12-column grid.
 */
import { api } from "../api/client";
import { RUN_EVENT_INVALIDATES, useLeaderboard, useView, useViewQuery, useViews } from "../api/queries";
import { AppLink, hrefs } from "./components/links";
import { PanelGrid } from "./components/PanelGrid";
import { ErrorBox, Loading } from "./components/QueryState";
import { PageStyles } from "./components/styles";
import type { Leaderboard } from "./components/types";
import { useAction } from "./components/useAction";

export interface TaskPageProps {
  project: string;
  task: string;
  view?: string;
}

const plural = (n: number, one: string, many: string): string => `${n} ${n === 1 ? one : many}`;

/** The line under the headline: configs and runs, metric versions, re-eval backlog. */
export function boardMeta(board: Leaderboard): string[] {
  const runs = board.rows.reduce((n, row) => n + row.run_ids.length, 0);
  const out = [
    `${plural(board.rows.length, "config", "configs")}, ${plural(runs, "run", "runs")}`,
    ...Object.entries(board.metric_versions).map(([metric, version]) => `${metric} ${version}`),
  ];
  if (board.needs_reeval.length > 0) out.push(`${board.needs_reeval.length} need re-eval`);
  return out;
}

export function TaskPage({ project, task, view }: TaskPageProps) {
  const active = view ? String(view) : "overview";
  const board = useLeaderboard(project, task);
  const views = useViews(project, task);
  const detail = useView(project, task, active);
  const panels = useViewQuery(project, task, { name: active });
  const reeval = useAction({
    send: (_: void, opts) => api.reevalTask(project, task, {}, opts),
    invalidate: RUN_EVENT_INVALIDATES,
  });

  const info = views.data?.find((v) => v.name === active) ?? detail.data?.info;
  const editable = info !== undefined && info.origin !== "preset";
  const viewError = detail.error ?? panels.error;
  const ready = panels.data !== undefined && !detail.isPending;

  return (
    <div className="page">
      <PageStyles />
      <p className="crumb">
        <AppLink href={hrefs.overview()}>All projects</AppLink>
        <span className="sep">/</span>
        {project}
        <span className="sep">/</span>
        {task}
        {board.data ? (
          <span className="tag" title="task kind">
            {board.data.kind}
          </span>
        ) : null}
      </p>
      <h1 className="headline">{board.data?.headline ?? task}</h1>
      {board.error ? <ErrorBox error={board.error} /> : null}
      {board.data ? (
        <p className="metaline">
          {boardMeta(board.data).map((text) => (
            <span key={text}>{text}</span>
          ))}
        </p>
      ) : null}

      <nav className="view-tabs" aria-label="Views">
        {(views.data ?? []).map((v) => (
          <AppLink
            key={v.name}
            href={hrefs.task(project, task, v.name)}
            aria-current={v.name === active ? "page" : undefined}
            title={v.path ?? `${v.origin} view`}
          >
            {v.title || v.name}
            {v.origin === "preset" ? (
              <>
                {" "}
                <small>preset</small>
              </>
            ) : null}
          </AppLink>
        ))}
        <AppLink href={hrefs.edit(project, task, "new")} title="New view">
          + view
        </AppLink>
        <span className="r">
          {detail.data ? (
            <span className="small">{plural((detail.data.view.panels ?? []).length, "panel", "panels")}</span>
          ) : null}
          {editable ? (
            <AppLink className="btn" href={hrefs.edit(project, task, active)}>
              Edit
            </AppLink>
          ) : null}
          <button
            type="button"
            className="btn primary"
            onClick={() => reeval.run()}
            disabled={reeval.pending}
            title="Re-score every run's saved predictions with the current metric versions"
          >
            Re-evaluate all
          </button>
        </span>
      </nav>
      {views.error ? <ErrorBox error={views.error} /> : null}
      {reeval.error ? <ErrorBox error={reeval.error} /> : null}

      {viewError ? (
        <ErrorBox error={viewError} />
      ) : ready && panels.data ? (
        <PanelGrid results={panels.data.panels} specs={detail.data?.view.panels} />
      ) : (
        <Loading />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/Task.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Show the page on `/t/$project/$task`**

In `ui/src/router.tsx` replace

```tsx
import { useState } from "react";
```

with

```tsx
import { type ReactElement, useState } from "react";
```

replace

```tsx
import { OverviewPage } from "./pages/Overview";
```

with

```tsx
import { OverviewPage } from "./pages/Overview";
import { TaskPage } from "./pages/Task";
```

replace

```tsx
export const rootRoute = createRootRoute({ component: AppShell, notFoundComponent: NotFound });
```

with

```tsx
/** `/t/$project/$task?view=`: the Task page. Screens declare their return type, which keeps the route types free of cycles. */
function TaskScreen(): ReactElement {
  const { project, task } = taskRoute.useParams();
  const { view } = taskRoute.useSearch();
  return <TaskPage project={project} task={task} view={view} />;
}

export const rootRoute = createRootRoute({ component: AppShell, notFoundComponent: NotFound });
```

and replace

```tsx
  validateSearch: (search: Record<string, unknown>): TaskSearch => ({ view: str(search.view) }),
  component: () => <ScreenPending name="Task" />,
```

with

```tsx
  validateSearch: (search: Record<string, unknown>): TaskSearch => ({ view: str(search.view) }),
  component: TaskScreen,
```

Run: `cd ui && bun test test/router.test.tsx test/shell && bun run typecheck`
Expected: `0 fail`; `tsc` prints nothing.

- [ ] **Step 6: Commit**

```bash
git add ui/src/pages/Task.tsx ui/test/pages/Task.test.tsx ui/src/router.tsx
git commit -m "feat(ui): task page with view tabs and lettered panels"
```

### Task 31: Where-everything-is list

**Files:**
- Create: `ui/src/pages/components/WhereList.tsx`
- Test: `ui/test/pages/whereList.test.tsx`

**Interfaces:**
- Consumes: `RunDetail`, `GitInfo` (Task 21); `displayPath`, `fmtBytes`, `isNum`, `relativeTo`,
  `shellJoin`, `splitHostPath` (Task 22); `AppLink`, `hrefs` (Task 23); `CopyButton` (Task 24).
- Produces:
  - `interface WhereRow { display: string; copy: string; indent: boolean; note?: string; href?: string }`;
    `interface WhereGroup { title: string; host: string; rows: WhereRow[] }`;
    `buildWhere(detail: RunDetail): WhereGroup[]`: groups `Project` (repo, then cwd and
    datasets inside it, relative), `Data` (datasets outside the repo, as `host:path`),
    `Run` (run folder once, then logs, predictions, env, config, `git.diff`, artifacts
    relative to it). `copy` is the full path (`host:path` off `local`).
  - `interface GitLine { ref: string; state: "clean" | "dirty" | "untracked"; text: string; untracked: string[] }`;
    `type GitState`; `gitLine(git: GitState): GitLine | null` (spec 8.8: `untracked files only` when there
    is no tracked diff).
  - `WhereList({ detail })`: command (and template when different), then the groups;
    log rows link to `?log=<stream>`.

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/whereList.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WhereList, buildWhere, gitLine } from "../../src/pages/components/WhereList";
import { REPO, RUN_SVM, STORE, makeDetail } from "./fixtures";
import { mockClipboard } from "./helpers";

afterEach(cleanup);

const DIR = `${STORE}/${RUN_SVM}`;

describe("buildWhere", () => {
  test("local run: repo with its dataset, run folder with relative children", () => {
    const [project, run, ...rest] = buildWhere(makeDetail());
    expect(rest).toEqual([]);
    expect(project).toEqual({
      title: "Project",
      host: "local",
      rows: [
        { display: REPO, copy: REPO, indent: false },
        {
          display: "data/test.jsonl",
          copy: `${REPO}/data/test.jsonl`,
          indent: true,
          note: "toyset v1 test, 26.1 KB",
        },
      ],
    });
    expect(run?.title).toBe("Run");
    expect(run?.rows.map((r) => r.display)).toEqual([
      DIR,
      "logs/stdout.log",
      "logs/stderr.log",
      "predictions",
      "env",
      "model.pkl",
    ]);
    expect(run?.rows[2]).toEqual({
      display: "logs/stderr.log",
      copy: `${DIR}/logs/stderr.log`,
      indent: true,
      href: `/r/${RUN_SVM}?log=stderr`,
    });
    expect(run?.rows[5]?.note).toBe("checkpoint, 18.5 KB");
  });

  test("remote data gets its own group; a tracked diff is listed", () => {
    const detail = makeDetail(
      {
        datasets: [
          {
            name: "uspto",
            version: "v2",
            split: null,
            host: "nfs-01",
            path: "/data/uspto/v2",
            hash: null,
            hash_mode: null,
            size: null,
            checked_at: null,
          },
        ],
        artifacts: [
          { kind: "checkpoint", path: "/scratch/ckpt/step_18000.pt", host: "gpu-a03", size: null, step: 18000, metrics: {} },
        ],
      },
      { has_diff: true },
    );
    const groups = buildWhere(detail);
    expect(groups.map((g) => g.title)).toEqual(["Project", "Data", "Run"]);
    expect(groups[1]).toEqual({
      title: "Data",
      host: "nfs-01",
      rows: [{ display: "nfs-01:/data/uspto/v2", copy: "nfs-01:/data/uspto/v2", indent: false, note: "uspto v2" }],
    });
    const run = groups[2]?.rows ?? [];
    expect(run.find((r) => r.display === "git.diff")?.note).toBe("tracked diff");
    expect(run.at(-1)).toEqual({
      display: "gpu-a03:/scratch/ckpt/step_18000.pt",
      copy: "gpu-a03:/scratch/ckpt/step_18000.pt",
      indent: false,
      note: "checkpoint, step 18000",
    });
  });
});

test("gitLine separates tracked changes from untracked files", () => {
  const base = { repo: null, commit: "8f4cac43877b", branch: "main" };
  expect(gitLine({ ...base, dirty: false, untracked_count: 0 })).toEqual({
    ref: "main @ 8f4cac4",
    state: "clean",
    text: "tracked clean",
    untracked: [],
  });
  expect(gitLine({ ...base, dirty: false, untracked_count: 2, untracked: ["a.py", "b.txt"] })).toEqual({
    ref: "main @ 8f4cac4",
    state: "untracked",
    text: "untracked files only",
    untracked: ["a.py", "b.txt"],
  });
  expect(gitLine({ ...base, dirty: true, untracked_count: 1, untracked: ["a.py"] })?.text).toBe(
    "tracked changes, 1 untracked",
  );
  expect(gitLine({ ...base, branch: null, dirty: false })?.ref).toBe("detached @ 8f4cac4");
  expect(gitLine({ ...base, commit: null, dirty: false })).toBeNull();
});

test("WhereList shows command, git state, links, and copies full paths", async () => {
  const written = mockClipboard();
  render(<WhereList detail={makeDetail()} />);
  expect(screen.getByText("python train_eval.py --model svm --seed=3")).toBeTruthy();
  expect(screen.getByText("python train_eval.py --model svm --seed={seed}")).toBeTruthy();
  const untracked = screen.getByText("untracked files only");
  expect(untracked.parentElement?.getAttribute("title")).toBe("scratch.py\nnotes.txt");
  expect(screen.getByRole("link", { name: "logs/stderr.log" }).getAttribute("href")).toBe(
    `/r/${RUN_SVM}?log=stderr`,
  );
  fireEvent.click(screen.getByRole("button", { name: "Copy data/test.jsonl" }));
  await waitFor(() => expect(written).toEqual([`${REPO}/data/test.jsonl`]));
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/whereList.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/WhereList'`.

- [ ] **Step 3: Implement the list**

`ui/src/pages/components/WhereList.tsx`:

```tsx
/**
 * Run panel "where everything is" (spec 8.1): code, data, run folder, logs,
 * predictions, checkpoints as host:path. The run folder is shown once and its
 * children relative to it; copy buttons copy the full path.
 */
import { CopyButton } from "./CopyButton";
import { displayPath, fmtBytes, isNum, relativeTo, shellJoin, splitHostPath } from "./format";
import { AppLink, hrefs } from "./links";
import type { GitInfo, RunDetail } from "./types";

export interface WhereRow {
  display: string;
  copy: string;
  indent: boolean;
  note?: string;
  href?: string;
}

export interface WhereGroup {
  title: string;
  host: string;
  rows: WhereRow[];
}

export interface GitLine {
  ref: string;
  state: "clean" | "dirty" | "untracked";
  text: string;
  untracked: string[];
}

interface Loc {
  host: string;
  path: string;
}

function whereRow(loc: Loc, base: Loc | null, extra: Partial<WhereRow> = {}): WhereRow {
  const rel = base && base.host === loc.host ? relativeTo(loc.path, base.path) : null;
  const full = displayPath(loc.host, loc.path);
  return { display: rel ?? full, copy: full, indent: rel !== null, ...extra };
}

function joinNote(parts: (string | null)[]): string {
  return parts.filter((p): p is string => p !== null && p !== "").join(", ");
}

/** The git fields `gitLine` reads; the untracked fields may be missing on runs recorded before phase 1b. */
export type GitState = Pick<GitInfo, "commit" | "branch" | "dirty"> &
  Partial<Pick<GitInfo, "untracked_count" | "untracked">>;

/** Branch, short commit, and working-copy state; tracked changes and untracked files apart. */
export function gitLine(git: GitState): GitLine | null {
  if (!git.commit) return null;
  const ref = `${git.branch ?? "detached"} @ ${git.commit.slice(0, 7)}`;
  const count = git.untracked_count ?? 0;
  const untracked = git.untracked ?? [];
  if (git.dirty) {
    const text = count > 0 ? `tracked changes, ${count} untracked` : "tracked changes";
    return { ref, state: "dirty", text, untracked };
  }
  if (count > 0) return { ref, state: "untracked", text: "untracked files only", untracked };
  return { ref, state: "clean", text: "tracked clean", untracked: [] };
}

export function buildWhere(detail: RunDetail): WhereGroup[] {
  const { record, paths } = detail;
  const repo = splitHostPath(paths.repo ?? paths.cwd ?? record.cwd);
  const project: WhereGroup = { title: "Project", host: repo.host, rows: [whereRow(repo, null)] };
  const cwd = splitHostPath(paths.cwd ?? record.cwd);
  if (cwd.path !== repo.path) project.rows.push(whereRow(cwd, repo, { note: "cwd" }));

  const data: WhereGroup = { title: "Data", host: "", rows: [] };
  for (const ds of record.datasets) {
    const note = joinNote([
      `${ds.name} ${ds.version}${ds.split ? ` ${ds.split}` : ""}`,
      ds.size !== null ? fmtBytes(ds.size) : null,
    ]);
    const row = whereRow({ host: ds.host, path: ds.path }, repo, { note });
    if (row.indent) {
      project.rows.push(row);
    } else {
      data.rows.push(row);
      data.host = data.host || ds.host;
    }
  }

  const groups = [project];
  if (data.rows.length > 0) groups.push(data);

  const runDir = paths.run_dir;
  if (runDir) {
    const dir = splitHostPath(runDir);
    const run: WhereGroup = { title: "Run", host: dir.host, rows: [whereRow(dir, null)] };
    for (const stream of ["stdout", "stderr"] as const) {
      const p = paths[stream];
      if (p) {
        run.rows.push(whereRow(splitHostPath(p), dir, { href: hrefs.run(record.run_id, { log: stream }) }));
      }
    }
    for (const key of ["predictions", "env", "config"]) {
      const p = paths[key];
      if (p) run.rows.push(whereRow(splitHostPath(p), dir));
    }
    if (detail.has_diff) {
      run.rows.push(whereRow({ host: dir.host, path: `${dir.path}/git.diff` }, dir, { note: "tracked diff" }));
    }
    for (const art of record.artifacts) {
      const note = joinNote([
        art.kind,
        isNum(art.step) ? `step ${art.step}` : null,
        isNum(art.size) ? fmtBytes(art.size) : null,
      ]);
      run.rows.push(whereRow({ host: art.host, path: art.path }, dir, { note }));
    }
    groups.push(run);
  }
  return groups;
}

export function WhereList({ detail }: { detail: RunDetail }) {
  const { record } = detail;
  const git = gitLine(record.git);
  const cmd = shellJoin(record.command);
  const tmpl = shellJoin(record.command_template);
  return (
    <div className="tree">
      <div className="cmdrow">
        <span className="k">Command</span>
        <div>
          <code className="cmd">{cmd}</code>
          {tmpl !== cmd ? (
            <p className="tmpl">
              template <code>{tmpl}</code>
            </p>
          ) : null}
        </div>
      </div>
      {buildWhere(detail).map((group) => {
        const [root, ...kids] = group.rows;
        if (!root) return null;
        return (
          <div key={group.title}>
            <div className="root">
              <span className="k">{group.title}</span>
              <span className="p">{root.display}</span>
              <span className="what">{root.note ?? ""}</span>
              <CopyButton text={root.copy} label={root.display} />
            </div>
            {group.title === "Project" && git ? (
              <p className="gitline" title={git.untracked.length ? git.untracked.join("\n") : undefined}>
                <b>{git.ref}</b> <span className={git.state}>{git.text}</span>
              </p>
            ) : null}
            {kids.length > 0 ? (
              <ul className="kids">
                {kids.map((row, i) => (
                  <li key={`${row.copy}-${i}`}>
                    <span className="br">{row.indent ? (i === kids.length - 1 ? "└" : "├") : "·"}</span>
                    <span className="p">
                      {row.href ? (
                        <AppLink href={row.href} title="Open">
                          {row.display}
                        </AppLink>
                      ) : (
                        row.display
                      )}
                    </span>
                    <span className="what">{row.note ?? ""}</span>
                    <CopyButton text={row.copy} label={row.display} />
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/whereList.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/WhereList.tsx ui/test/pages/whereList.test.tsx
git commit -m "feat(ui): where-everything-is list with relative paths and copy buttons"
```

### Task 32: Run scores, stat strip, and status line

**Files:**
- Create: `ui/src/pages/components/ScoresList.tsx`
- Create: `ui/src/pages/components/runStats.ts`
- Create: `ui/src/pages/components/StatusLine.tsx`
- Test: `ui/test/pages/runSummary.test.tsx`

**Interfaces:**
- Consumes: `ScoreRecord`, `RunDetail`, `RunRecord`, `Leaderboard`, `LeaderboardRow`,
  `NoiseInterval` (Task 21); format helpers (Task 22); `AppLink`, `hrefs` (Task 23); `StatItem` (Task 24).
- Produces:
  - `latestScores(scores): ScoreRecord[]` (newest per metric/version/key, sorted);
    `scoreLabel(s): string` (`accuracy v1`, or `accuracy v1/<key>`);
    `scoreFor(scores, ref: string): number | null` (`name`, `name@version`, or
    `name@version/key`; errors and nulls skipped).
  - `interface PrimaryRef { metric: string; version: string; key: string; interval: NoiseInterval | null }`;
    `primaryRef(board: Leaderboard | null, row: LeaderboardRow | null): PrimaryRef | null`.
  - `ScoresList({ scores, metricNames, primary })`.
  - `runStats(detail, primary, row, now?): StatItem[]` (primary score, 95% CI, seeds, wall,
    tokens in/out, cost, exit code when non-zero).
  - `StatusLine({ record })`: status, wall time, seed, time, launcher, host, infer tag,
    parent link, tags.

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/runSummary.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import { runStats } from "../../src/pages/components/runStats";
import {
  ScoresList,
  latestScores,
  primaryRef,
  scoreFor,
  scoreLabel,
} from "../../src/pages/components/ScoresList";
import { StatusLine } from "../../src/pages/components/StatusLine";
import type { ScoreRecord } from "../../src/pages/components/types";
import { RUN_RF, makeBoard, makeDetail, makeRecord } from "./fixtures";

afterEach(cleanup);

function score(over: Partial<ScoreRecord>): ScoreRecord {
  return {
    metric: "accuracy",
    version: "v1",
    key: "value",
    value: 0.5,
    error: null,
    source_hash: null,
    created_at: "2026-09-26T21:00:00Z",
    ...over,
  };
}

describe("scores", () => {
  const scores = [
    score({ value: 0.9, created_at: "2026-09-26T21:00:00Z" }),
    score({ value: 0.92, created_at: "2026-09-26T22:00:00Z" }),
    score({ metric: "macro_f1", value: 0.91 }),
    score({ version: "v0", value: 0.7 }),
    score({ key: "top5", value: 0.99 }),
    score({ metric: "bleu", value: null, error: "division by zero" }),
  ];

  test("latestScores keeps the newest per metric, version, key (sorted by key: top5 < value)", () => {
    expect(latestScores(scores).map((s) => [scoreLabel(s), s.value])).toEqual([
      ["accuracy v0", 0.7],
      ["accuracy v1/top5", 0.99],
      ["accuracy v1", 0.92],
      ["bleu v1", null],
      ["macro_f1 v1", 0.91],
    ]);
  });

  test("scoreFor resolves name, name@version, and name@version/key", () => {
    expect(scoreFor(scores, "accuracy@v1")).toBe(0.92);
    expect(scoreFor(scores, "accuracy@v1/top5")).toBe(0.99);
    expect(scoreFor(scores, "accuracy@v0/value")).toBe(0.7);
    expect(scoreFor(scores, "macro_f1")).toBe(0.91);
    expect(scoreFor(scores, "bleu@v1")).toBeNull();
    expect(scoreFor(scores, "missing")).toBeNull();
  });

  test("ScoresList shows values, the primary interval, errors, and logged metrics", () => {
    const board = makeBoard();
    render(
      <ScoresList
        scores={[...makeDetail().scores, score({ metric: "bleu", error: "division by zero", value: null })]}
        metricNames={["train_accuracy"]}
        primary={primaryRef(board, board.rows[0] ?? null)}
      />,
    );
    expect(screen.getByText("0.9222")).toBeTruthy();
    expect(screen.getByText("0.9225")).toBeTruthy();
    expect(screen.getByText("0.874–0.953")).toBeTruthy();
    expect(screen.getByText("21:03 · e662a37b")).toBeTruthy();
    expect(screen.getByText("error").getAttribute("title")).toBe("division by zero");
    expect(screen.getByText("logged: train_accuracy")).toBeTruthy();
  });
});

describe("runStats", () => {
  test("primary score, interval, seeds, wall time", () => {
    const board = makeBoard();
    const row = board.rows[0] ?? null;
    const stats = runStats(makeDetail(), primaryRef(board, row), row);
    expect(stats.map((s) => [s.label, s.value])).toEqual([
      ["accuracy v1", "0.9222"],
      ["95% CI", "0.874–0.953"],
      ["seeds", "◇×3"],
      ["wall", "0.8 s"],
    ]);
  });

  test("usage and a failing exit code; no board means no score stats", () => {
    const detail = makeDetail({
      status: "failed",
      exit_code: 2,
      usage: { tokens_in: 153000, tokens_out: 4500, usd: 0.25, seconds: 68.4, calls: 13 },
    });
    expect(runStats(detail, null, null).map((s) => [s.label, s.value])).toEqual([
      ["wall", "0.8 s"],
      ["tokens in", "153k"],
      ["tokens out", "4.5k"],
      ["cost", "$0.25"],
      ["exit", "2"],
    ]);
  });
});

test("StatusLine lists status, time, launcher, host, tags, and parent", () => {
  render(<StatusLine record={makeRecord({ kind: "infer", parent: RUN_RF })} />);
  for (const text of ["finished", "0.8 s", "seed 3", "21:03:06 UTC", "agent:acceptance", "mbp.local", "infer", "best", "svm"]) {
    expect(screen.getByText(text)).toBeTruthy();
  }
  expect(screen.getByRole("link", { name: "parent ef4f" }).getAttribute("href")).toBe(`/r/${RUN_RF}`);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/runSummary.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/runStats'`.

- [ ] **Step 3: Implement scores, stats, and status line**

`ui/src/pages/components/ScoresList.tsx`:

```tsx
/** Run panel: scores by metric version (spec 8.3.3). */
import { fmtClock, fmtInterval, fmtScore, shortHash } from "./format";
import type { Leaderboard, LeaderboardRow, NoiseInterval, ScoreRecord } from "./types";

/** The newest score per (metric, version, key), sorted by metric, version, key. */
export function latestScores(scores: ScoreRecord[]): ScoreRecord[] {
  const newest = new Map<string, ScoreRecord>();
  for (const s of scores) {
    const key = `${s.metric}\u0000${s.version}\u0000${s.key}`;
    const current = newest.get(key);
    if (!current || s.created_at > current.created_at) newest.set(key, s);
  }
  return [...newest.values()].sort(
    (a, b) =>
      a.metric.localeCompare(b.metric) ||
      a.version.localeCompare(b.version) ||
      a.key.localeCompare(b.key),
  );
}

/** `accuracy v1`, or `accuracy v1/top5` for a non-`value` key. */
export function scoreLabel(s: ScoreRecord): string {
  return `${s.metric} ${s.version}${s.key === "value" ? "" : `/${s.key}`}`;
}

/** The newest valid score for `name`, `name@version`, or `name@version/key`. */
export function scoreFor(scores: ScoreRecord[], ref: string): number | null {
  const [head = "", key] = ref.split("/");
  const [name = "", version] = head.split("@");
  const candidates = latestScores(scores).filter(
    (s) =>
      s.metric === name &&
      (version === undefined || s.version === version) &&
      s.error === null &&
      s.value !== null,
  );
  const pick = candidates.find((s) => s.key === (key ?? "value")) ?? (key ? undefined : candidates[0]);
  return pick?.value ?? null;
}

export interface PrimaryRef {
  metric: string;
  version: string;
  key: string;
  interval: NoiseInterval | null;
}

/** The task's primary metric at its current version, with the run group's test interval. */
export function primaryRef(board: Leaderboard | null, row: LeaderboardRow | null): PrimaryRef | null {
  if (!board) return null;
  const [metric = board.primary, key = "value"] = board.primary.split("/");
  const version = board.metric_versions[metric];
  if (!version) return null;
  return { metric, version, key, interval: row?.test_interval ?? null };
}

export interface ScoresListProps {
  scores: ScoreRecord[];
  metricNames: string[];
  primary: PrimaryRef | null;
}

export function ScoresList({ scores, metricNames, primary }: ScoresListProps) {
  const rows = latestScores(scores);
  return (
    <div>
      {rows.length === 0 ? (
        <p className="small">no scores</p>
      ) : (
        <table className="scores">
          <tbody>
            {rows.map((s) => {
              const isPrimary =
                primary !== null &&
                s.metric === primary.metric &&
                s.version === primary.version &&
                s.key === primary.key;
              const iv = isPrimary ? primary.interval : null;
              return (
                <tr key={`${s.metric}@${s.version}/${s.key}`}>
                  <td>
                    {scoreLabel(s)}
                    <small>
                      {s.source_hash
                        ? `${fmtClock(s.created_at)} · ${shortHash(s.source_hash)}`
                        : fmtClock(s.created_at)}
                    </small>
                  </td>
                  <td className="v">
                    {s.error ? (
                      <span className="err" title={s.error}>
                        error
                      </span>
                    ) : (
                      <span>{fmtScore(s.value)}</span>
                    )}
                    {iv ? (
                      <small title={`test-set 95% interval (${iv.method}, n = ${iv.n})`}>
                        {fmtInterval(iv.lo, iv.hi)}
                      </small>
                    ) : null}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {metricNames.length > 0 ? <p className="small">{`logged: ${metricNames.join(", ")}`}</p> : null}
    </div>
  );
}
```

`ui/src/pages/components/runStats.ts`:

```ts
/** The run page's stat strip: the few numbers that matter, tooltips for the rest. */
import { fmtCount, fmtDuration, fmtInterval, fmtScore, fmtUsd, runSeconds } from "./format";
import { type PrimaryRef, scoreFor } from "./ScoresList";
import type { StatItem } from "./StatStrip";
import type { LeaderboardRow, RunDetail } from "./types";

export function runStats(
  detail: RunDetail,
  primary: PrimaryRef | null,
  row: LeaderboardRow | null,
  now: number = Date.now(),
): StatItem[] {
  const out: StatItem[] = [];
  const record = detail.record;
  if (primary) {
    const value = scoreFor(detail.scores, `${primary.metric}@${primary.version}/${primary.key}`);
    if (value !== null) {
      const label = `${primary.metric} ${primary.version}${primary.key === "value" ? "" : `/${primary.key}`}`;
      out.push({ label, value: fmtScore(value), tooltip: "this run's primary score" });
    }
    if (primary.interval) {
      const iv = primary.interval;
      out.push({
        label: "95% CI",
        value: fmtInterval(iv.lo, iv.hi),
        tooltip: `test-set interval of the seed group (${iv.method}, n = ${iv.n})`,
      });
    }
  }
  if (row) {
    out.push({
      label: "seeds",
      value: row.identical_seeds ? `◇×${row.n}` : String(row.n),
      tooltip: row.identical_seeds ? "every seed gave the same score" : "runs in this seed group",
    });
  }
  const seconds = runSeconds(record, now);
  if (seconds !== null) out.push({ label: "wall", value: fmtDuration(seconds) });
  const usage = record.usage;
  if (usage) {
    out.push({ label: "tokens in", value: fmtCount(usage.tokens_in) });
    out.push({ label: "tokens out", value: fmtCount(usage.tokens_out) });
    out.push({ label: "cost", value: fmtUsd(usage.usd), tooltip: `${usage.calls} calls` });
  }
  if (record.exit_code !== null && record.exit_code !== 0) {
    out.push({ label: "exit", value: String(record.exit_code) });
  }
  return out;
}
```

`ui/src/pages/components/StatusLine.tsx`:

```tsx
/** The line under a run's title: status, time, seed, launcher, host, tags. */
import { fmtDuration, fmtTime, isAgent, runSeconds, shortId } from "./format";
import { AppLink, hrefs } from "./links";
import type { RunRecord } from "./types";

export function StatusLine({ record }: { record: RunRecord }) {
  const seconds = runSeconds(record);
  return (
    <p className="status">
      <span className={`st ${record.status}`}>
        <i />
        {record.status}
      </span>
      {seconds !== null ? <span>{fmtDuration(seconds)}</span> : null}
      {record.seed !== null ? <span>{`seed ${record.seed}`}</span> : null}
      <span title={record.created_at}>{fmtTime(record.created_at)}</span>
      <span className={`who ${isAgent(record.created_by) ? "agent" : "human"}`}>
        <i />
        {record.created_by}
      </span>
      <span>{record.host}</span>
      {record.kind === "infer" ? (
        <span className="tag" title="inference-only run">
          infer
        </span>
      ) : null}
      {record.parent ? (
        <AppLink href={hrefs.run(record.parent)}>{`parent ${shortId(record.parent)}`}</AppLink>
      ) : null}
      {record.tags.map((tag) => (
        <span key={tag} className="tag">
          {tag}
        </span>
      ))}
    </p>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/runSummary.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/ScoresList.tsx ui/src/pages/components/runStats.ts \
  ui/src/pages/components/StatusLine.tsx ui/test/pages/runSummary.test.tsx
git commit -m "feat(ui): run scores, stat strip, and status line"
```

### Task 33: Run notes and actions

**Files:**
- Create: `ui/src/pages/components/Notes.tsx`
- Create: `ui/src/pages/components/RunActions.tsx`
- Test: `ui/test/pages/runActions.test.tsx`

**Interfaces:**
- Consumes: `POST /runs/{id}/notes {text, author, command_id, created_by}`;
  `POST /runs/{id}/{rerun|reinfer|reeval|stop} {command_id, created_by}` (phase 1a;
  rerun and re-infer answer the new `RunRecord`), sent through `api.note`, `api.rerun`,
  `api.reinfer`, `api.reevalRun`, `api.stop` (Task 3); `queryKeys`, `RUN_EVENT_INVALIDATES`
  (Task 4); Task 21 `RunRecord`, `RunRef`, `ACTIVE_STATUSES`; Task 22 `fmtDate`,
  `isAgent`; Task 23 `hrefs`, `useNavigateHref`; Task 24 `ErrorBox`; Task 26 `useAction`.
- Produces:
  - `interface NoteEntry { at: string; author: string; text: string }`;
    `parseNotes(raw: string): NoteEntry[]` (reads the `## <iso> — <author>` blocks
    written by `fsutil.append_note`; text without headers is one entry).
  - `Notes({ runId, notes })`: the latest note (clipped), `More`/`Less`, `Add note`.
  - `RunActions({ record })`: Rerun, Re-infer (both open the new run), Re-evaluate,
    Stop (enabled only while queued or running); errors as an alert.

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/runActions.test.tsx`:

```tsx
import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { Notes, parseNotes } from "../../src/pages/components/Notes";
import { RunActions } from "../../src/pages/components/RunActions";
import { RUN_SVM, makeRecord } from "./fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const TWO_NOTES =
  "\n## 2026-09-26T21:03:56.036288+00:00 — agent:acceptance\n\nSVM beats rf.\n" +
  "\n## 2026-09-26T22:10:00+00:00 — human\n\nTry C=100.\nAnd gamma=0.1.\n";

describe("parseNotes", () => {
  test("splits header blocks", () => {
    expect(parseNotes(TWO_NOTES)).toEqual([
      { at: "2026-09-26T21:03:56.036288+00:00", author: "agent:acceptance", text: "SVM beats rf." },
      { at: "2026-09-26T22:10:00+00:00", author: "human", text: "Try C=100.\nAnd gamma=0.1." },
    ]);
  });

  test("hand-written text without headers is one entry; blank is none", () => {
    expect(parseNotes("just a thought\n")).toEqual([{ at: "", author: "", text: "just a thought" }]);
    expect(parseNotes("  \n")).toEqual([]);
  });
});

describe("Notes", () => {
  test("shows the latest note and More reveals the rest", () => {
    mockApi({});
    renderWithClient(<Notes runId={RUN_SVM} notes={TWO_NOTES} />);
    expect(screen.getByText(/Try C=100/)).toBeTruthy();
    expect(screen.queryByText("SVM beats rf.")).toBeNull();
    expect(screen.getByText("2026-09-26 22:10")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "More" }));
    expect(screen.getByText("SVM beats rf.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Less" })).toBeTruthy();
  });

  test("Add note posts the text as the human and closes the editor", async () => {
    const calls = mockApi({ [`POST /api/v1/runs/${RUN_SVM}/notes`]: { ok: true } });
    renderWithClient(<Notes runId={RUN_SVM} notes="" />);
    expect(screen.getByText("none")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Add note" }));
    const save = screen.getByRole("button", { name: "Save" });
    expect(save.hasAttribute("disabled")).toBe(true);
    fireEvent.change(screen.getByRole("textbox", { name: "Note" }), { target: { value: "  tried C=100  " } });
    fireEvent.click(save);
    await waitFor(() => expect(screen.queryByRole("textbox", { name: "Note" })).toBeNull());
    const body = calls.find((c) => c.method === "POST")?.body as Record<string, unknown>;
    expect(body.text).toBe("tried C=100");
    expect(body.author).toBe("human");
    expect(body.created_by).toBe("human");
    expect(typeof body.command_id).toBe("string");
  });
});

describe("RunActions", () => {
  test("Rerun posts a command_id and opens the new run", async () => {
    const calls = mockApi({ [`POST /api/v1/runs/${RUN_SVM}/rerun`]: { run_id: "NEW" } });
    const navigate = mock((_href: string) => {});
    renderWithClient(<RunActions record={makeRecord()} />, { navigate });
    fireEvent.click(screen.getByRole("button", { name: "Rerun" }));
    await waitFor(() => expect(navigate).toHaveBeenCalledWith("/r/NEW"));
    const body = calls[0]?.body as Record<string, unknown>;
    expect(typeof body.command_id).toBe("string");
    expect(body.created_by).toBe("human");
  });

  test("Stop is enabled only while the run is active", async () => {
    const calls = mockApi({ [`POST /api/v1/runs/${RUN_SVM}/stop`]: { run_id: RUN_SVM, status: "killed" } });
    renderWithClient(<RunActions record={makeRecord()} />);
    expect(screen.getByRole("button", { name: "Stop" }).hasAttribute("disabled")).toBe(true);
    cleanup();
    renderWithClient(<RunActions record={makeRecord({ status: "running", ended_at: null })} />);
    const stop = screen.getByRole("button", { name: "Stop" });
    expect(stop.hasAttribute("disabled")).toBe(false);
    fireEvent.click(stop);
    await waitFor(() => expect(calls.map((c) => c.url)).toEqual([`/api/v1/runs/${RUN_SVM}/stop`]));
  });

  test("shows the server error of a failed action", async () => {
    mockApi({
      [`POST /api/v1/runs/${RUN_SVM}/reeval`]: new HttpReply(400, {
        error: "run has no predictions to score",
        type: "EvalError",
      }),
    });
    renderWithClient(<RunActions record={makeRecord()} />);
    fireEvent.click(screen.getByRole("button", { name: "Re-evaluate" }));
    expect((await screen.findByRole("alert")).textContent).toBe("run has no predictions to score");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/runActions.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/Notes'`.

- [ ] **Step 3: Implement notes and actions**

`ui/src/pages/components/Notes.tsx`:

```tsx
/** Run panel: notes (`notes.md`), newest first shown, with Add note. */
import { useState } from "react";
import { api } from "../../api/client";
import { queryKeys } from "../../api/queries";
import { fmtDate, isAgent } from "./format";
import { ErrorBox } from "./QueryState";
import { useAction } from "./useAction";

export interface NoteEntry {
  at: string;
  author: string;
  text: string;
}

const HEADER = /^## (\S+) — (.+)$/gm;

/** Split `notes.md` into entries (header format from `hypothex.core.fsutil`). */
export function parseNotes(raw: string): NoteEntry[] {
  const heads = [...raw.matchAll(HEADER)];
  if (heads.length === 0) {
    const text = raw.trim();
    return text ? [{ at: "", author: "", text }] : [];
  }
  return heads.map((m, i) => {
    const start = (m.index ?? 0) + m[0].length;
    const end = heads[i + 1]?.index ?? raw.length;
    return { at: m[1] ?? "", author: (m[2] ?? "").trim(), text: raw.slice(start, end).trim() };
  });
}

const LONG_NOTE = 280;

export function Notes({ runId, notes }: { runId: string; notes: string }) {
  const entries = parseNotes(notes);
  const [all, setAll] = useState(false);
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const add = useAction<unknown, string>({
    send: (note, opts) => api.note(runId, note, opts),
    invalidate: [queryKeys.run(runId)],
    onSuccess: () => {
      setText("");
      setEditing(false);
    },
  });
  const shown = all ? entries : entries.slice(-1);
  const canExpand = entries.length > 1 || entries.some((e) => e.text.length > LONG_NOTE);
  return (
    <div>
      {entries.length === 0 && !editing ? <p className="small">none</p> : null}
      {shown.map((entry, i) => (
        <div key={`${entry.at}-${i}`} className="notes">
          {entry.author || entry.at ? (
            <div className="by">
              {entry.author ? (
                <span className={`who ${isAgent(entry.author) ? "agent" : "human"}`}>
                  <i />
                  {entry.author}
                </span>
              ) : null}
              {entry.at ? <span>{fmtDate(entry.at)}</span> : null}
            </div>
          ) : null}
          <p className={all ? undefined : "clip"}>{entry.text}</p>
        </div>
      ))}
      {editing ? (
        <div className="note-edit">
          <textarea aria-label="Note" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row">
            <button
              type="button"
              className="btn primary"
              disabled={add.pending || text.trim() === ""}
              onClick={() => add.run(text.trim())}
            >
              Save
            </button>
            <button type="button" className="btn" onClick={() => setEditing(false)}>
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <div className="row">
          {canExpand ? (
            <button type="button" className="btn" onClick={() => setAll(!all)}>
              {all ? "Less" : "More"}
            </button>
          ) : null}
          <button type="button" className="btn" onClick={() => setEditing(true)}>
            Add note
          </button>
        </div>
      )}
      {add.error ? <ErrorBox error={add.error} /> : null}
    </div>
  );
}
```

`ui/src/pages/components/RunActions.tsx`:

```tsx
/** Run actions (spec 8.3.3): rerun, re-infer, re-evaluate, stop; each with a command_id. */
import { api } from "../../api/client";
import { RUN_EVENT_INVALIDATES } from "../../api/queries";
import { hrefs, useNavigateHref } from "./links";
import { ErrorBox } from "./QueryState";
import { ACTIVE_STATUSES, type RunRecord, type RunRef } from "./types";
import { useAction } from "./useAction";

export function RunActions({ record }: { record: RunRecord }) {
  const navigate = useNavigateHref();
  const id = record.run_id;
  const refresh = RUN_EVENT_INVALIDATES;
  const openNew = (made: RunRef) => navigate(hrefs.run(made.run_id));
  const rerun = useAction<RunRef>({
    send: (_: void, opts) => api.rerun(id, opts),
    invalidate: refresh,
    onSuccess: openNew,
  });
  const reinfer = useAction<RunRef>({
    send: (_: void, opts) => api.reinfer(id, undefined, opts),
    invalidate: refresh,
    onSuccess: openNew,
  });
  const reeval = useAction({ send: (_: void, opts) => api.reevalRun(id, {}, opts), invalidate: refresh });
  const stop = useAction({ send: (_: void, opts) => api.stop(id, opts), invalidate: refresh });
  const active = ACTIVE_STATUSES.has(record.status);
  const error = rerun.error ?? reinfer.error ?? reeval.error ?? stop.error;
  return (
    <div>
      <div className="actions">
        <button
          type="button"
          className="btn"
          disabled={rerun.pending}
          onClick={() => rerun.run()}
          title="Run again with the same command, code, and seed"
        >
          Rerun
        </button>
        <button
          type="button"
          className="btn"
          disabled={reinfer.pending}
          onClick={() => reinfer.run()}
          title="Run the infer stage again on this run's checkpoint"
        >
          Re-infer
        </button>
        <button
          type="button"
          className="btn primary"
          disabled={reeval.pending}
          onClick={() => reeval.run()}
          title="Re-score saved predictions with the current metric versions"
        >
          Re-evaluate
        </button>
        <button
          type="button"
          className="btn"
          disabled={!active || stop.pending}
          onClick={() => stop.run()}
          title={active ? "Stop this run" : "The run is not active"}
        >
          Stop
        </button>
      </div>
      {error ? <ErrorBox error={error} /> : null}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/runActions.test.tsx`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/Notes.tsx ui/src/pages/components/RunActions.tsx \
  ui/test/pages/runActions.test.tsx
git commit -m "feat(ui): run notes and rerun/re-infer/re-evaluate/stop actions"
```

### Task 34: Kind run panels, traces, and log view

**Files:**
- Create: `ui/src/pages/components/KindPanels.tsx`
- Create: `ui/src/pages/components/LogView.tsx`
- Test: `ui/test/pages/kindPanels.test.tsx`

**Interfaces:**
- Consumes: `POST /tasks/{p}/{t}/views/query {view: {title, panels}}` → `QueryResponse`;
  `GET /runs/{id}/traces` → `TraceSummary[]`; `GET /runs/{id}/traces/{example_id}` →
  `PanelResult` (type `trace`); `GET /runs/{id}/logs?stream=` → `LogChunk` (phase 1a).
  Task 4 `useViewQuery`, `useRunTraces`, `useRunTrace`, `useRunLogs`; Task 22 `fmtBytes`;
  Task 23 `AppLink`, `hrefs`; Task 24 `Figure`, `panelLetter`, `ErrorBox`, `Loading`;
  Task 25 `PanelGrid`, `PanelBody`.
- Produces:
  - `scopeToRun(panel: PanelSpec, runId: string): PanelSpec` (adds
    `data.filter.run_id`; every source row carries `run_id`, contract 1.5). Panel types in
    `CROSS_RUN_TYPES` (`grid`) come back unchanged: the agent kinds' `grid "same item across
    configs"` (spec 8.4) compares this run's items with the other configs of the task, so a
    run filter would leave only this run's column.
  - `splitRunView(specs): { regular: PanelSpec[]; trace: PanelSpec | null }`;
    `kindPanelCount(specs): number` (regular panels plus one trace section).
  - `pickExample(traces: TraceSummary[]): string | null` (first failed, else first).
  - `KindPanels({ project, task, runId, specs, example?, startIndex })`: the kind's
    run-view panels (one query), then a trace section when the kind has a `trace` panel.
  - `TraceSection({ runId, example?, letter, title })`: traced-example picker
    (`?example=`), the chosen trace via the registry's `trace` panel.
  - `LogView({ runId, stream: LogStream, letter })`: a log tail with its size and a close link.

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/kindPanels.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, screen, within } from "@testing-library/react";
import {
  KindPanels,
  kindPanelCount,
  pickExample,
  scopeToRun,
} from "../../src/pages/components/KindPanels";
import { LogView } from "../../src/pages/components/LogView";
import type { PanelSpec } from "../../src/pages/components/types";
import { fakeRegistry, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const TRACES = [
  { example_id: "T-001", turns: 3, failed: false },
  { example_id: "T-014", turns: 13, failed: true },
];

const SPECS: PanelSpec[] = [
  { type: "curves", title: "Curves", data: { metrics: ["loss"] }, layout: { span: 12, row: null } },
  { type: "trace", title: "Trajectory", data: {}, layout: { span: 12, row: null } },
];

function traceRoutes(example: string): Record<string, unknown> {
  return {
    "POST /api/v1/tasks/p/t/views/query": {
      panels: [{ type: "curves", title: "Curves", rows: [{}, {}, {}], meta: {} }],
    },
    "GET /api/v1/runs/R/traces": TRACES,
    [`GET /api/v1/runs/R/traces/${example}`]: {
      type: "trace",
      title: "",
      rows: Array.from({ length: example === "T-014" ? 13 : 3 }, (_, i) => ({ turn: i + 1 })),
      meta: { run_id: "R", example_id: example },
    },
  };
}

describe("helpers", () => {
  test("scopeToRun adds the run filter and keeps the rest", () => {
    expect(
      scopeToRun({ type: "curves", title: "Loss", data: { metrics: ["loss"], filter: { status: ["finished"] } } }, "R"),
    ).toEqual({
      type: "curves",
      title: "Loss",
      data: { metrics: ["loss"], filter: { status: ["finished"], run_id: "R" } },
    });
    expect(scopeToRun({ type: "table" }, "R")).toEqual({ type: "table", data: { filter: { run_id: "R" } } });
  });

  test("scopeToRun leaves the cross-config grid unscoped", () => {
    const grid: PanelSpec = { type: "grid", title: "same item across configs" };
    expect(scopeToRun(grid, "R")).toEqual({ type: "grid", title: "same item across configs" });
    expect(scopeToRun(grid, "R")).toBe(grid);
  });

  test("pickExample prefers a failed trace; kindPanelCount counts one trace section", () => {
    expect(pickExample(TRACES)).toBe("T-014");
    expect(pickExample([{ example_id: "a", turns: 1, failed: false }])).toBe("a");
    expect(pickExample([])).toBeNull();
    expect(kindPanelCount([...SPECS, { type: "trace", title: "again" }])).toBe(2);
  });
});

test("KindPanels queries scoped panels and shows the failed trace first", async () => {
  const calls = mockApi(traceRoutes("T-014"));
  renderWithClient(
    <KindPanels project="p" task="t" runId="R" specs={SPECS} startIndex={1} />,
    { registry: fakeRegistry(["curves", "trace"]) },
  );
  const curves = await screen.findByRole("region", { name: "b Curves" });
  expect(within(curves).getByTestId("panel-curves").textContent).toBe("Curves:3");
  const trace = await screen.findByRole("region", { name: "c Trajectory · T-014" });
  expect((await within(trace).findByTestId("panel-trace")).textContent).toBe(":13");
  const picker = within(trace).getByRole("navigation", { name: "Traced examples" });
  expect(within(picker).getByRole("link", { name: "T-001" }).getAttribute("href")).toBe("/r/R?example=T-001");
  const failed = within(picker).getByRole("link", { name: "T-014" });
  expect(failed.getAttribute("aria-current")).toBe("true");
  expect(failed.className).toBe("failed");
  const body = calls.find((c) => c.method === "POST")?.body as {
    view: { title: string; panels: PanelSpec[] };
  };
  expect(body.view.title).toBe("run");
  expect(body.view.panels).toHaveLength(1);
  expect(body.view.panels[0]?.data?.filter).toEqual({ run_id: "R" });
});

test("KindPanels scopes the table to the run but not the grid", async () => {
  const calls = mockApi({
    "POST /api/v1/tasks/p/t/views/query": {
      panels: [
        { type: "grid", title: "same item across configs", rows: [{}, {}, {}, {}], meta: {} },
        { type: "table", title: "tokens per turn", rows: [{}], meta: {} },
      ],
    },
  });
  const agentSpecs: PanelSpec[] = [
    { type: "grid", title: "same item across configs" },
    { type: "table", title: "tokens per turn", data: { source: "traces" } },
  ];
  renderWithClient(
    <KindPanels project="p" task="t" runId="R" specs={agentSpecs} startIndex={0} />,
    { registry: fakeRegistry(["grid", "table"]) },
  );
  const grid = await screen.findByRole("region", { name: "a same item across configs" });
  expect(within(grid).getByTestId("panel-grid").textContent).toBe("same item across configs:4");
  const body = calls.find((c) => c.method === "POST")?.body as {
    view: { title: string; panels: PanelSpec[] };
  };
  expect(body.view.panels[0]).toEqual({ type: "grid", title: "same item across configs" });
  expect(body.view.panels[1]?.data).toEqual({ source: "traces", filter: { run_id: "R" } });
});

test("an explicit ?example= wins over the failed one", async () => {
  const calls = mockApi(traceRoutes("T-001"));
  renderWithClient(
    <KindPanels project="p" task="t" runId="R" specs={SPECS} example="T-001" startIndex={0} />,
    { registry: fakeRegistry(["curves", "trace"]) },
  );
  await screen.findByRole("region", { name: "b Trajectory · T-001" });
  expect(calls.some((c) => c.url === "/api/v1/runs/R/traces/T-001")).toBe(true);
  expect(calls.some((c) => c.url === "/api/v1/runs/R/traces/T-014")).toBe(false);
});

test("LogView shows the tail, its size, and a close link", async () => {
  mockApi({
    "GET /api/v1/runs/R/logs?stream=stderr": { stream: "stderr", text: "Traceback: boom\n", offset: 1500, size: 1500 },
  });
  renderWithClient(<LogView runId="R" stream="stderr" letter="a" />);
  const region = screen.getByRole("region", { name: "a stderr" });
  expect((await within(region).findByText("Traceback: boom")).tagName).toBe("PRE");
  expect(region.querySelector(".aside")?.textContent).toBe("1.5 KB");
  expect(within(region).getByRole("link", { name: "close" }).getAttribute("href")).toBe("/r/R");
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/kindPanels.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/KindPanels'`.

- [ ] **Step 3: Implement the kind panels and log view**

`ui/src/pages/components/KindPanels.tsx`:

```tsx
/**
 * Kind-specific run detail (spec 8.4): the task kind's `run_view` panels from
 * `GET /tasks/{p}/{t}/kind`, scoped to one run, plus a trace section for agent kinds.
 */
import { useRunTrace, useRunTraces, useViewQuery } from "../../api/queries";
import { Figure, panelLetter } from "./Figure";
import { AppLink, hrefs } from "./links";
import { PanelBody, PanelGrid } from "./PanelGrid";
import { ErrorBox, Loading } from "./QueryState";
import type { PanelSpec, TraceSummary } from "./types";

/**
 * Panel types that compare runs, so they stay unscoped on the run page: the agent kinds'
 * `grid "same item across configs"` (spec 8.4) shows this run's items next to the other
 * configs of the task.
 */
export const CROSS_RUN_TYPES: ReadonlySet<string> = new Set(["grid"]);

/**
 * Restrict a panel to one run: every source row carries `run_id` (contract 1.5).
 * Panels in `CROSS_RUN_TYPES` come back unchanged.
 */
export function scopeToRun(panel: PanelSpec, runId: string): PanelSpec {
  if (CROSS_RUN_TYPES.has(panel.type)) return panel;
  const data = { ...(panel.data ?? {}) };
  const filter = { ...((data.filter as Record<string, unknown> | undefined) ?? {}), run_id: runId };
  return { ...panel, data: { ...data, filter } };
}

/** Trace panels are drawn by the trace section; everything else goes through the query. */
export function splitRunView(specs: PanelSpec[]): { regular: PanelSpec[]; trace: PanelSpec | null } {
  return {
    regular: specs.filter((p) => p.type !== "trace"),
    trace: specs.find((p) => p.type === "trace") ?? null,
  };
}

/** How many lettered panels `KindPanels` draws for these specs. */
export function kindPanelCount(specs: PanelSpec[]): number {
  const { regular, trace } = splitRunView(specs);
  return regular.length + (trace ? 1 : 0);
}

/** The example to show first: the first failed trace, else the first trace. */
export function pickExample(traces: TraceSummary[]): string | null {
  return (traces.find((t) => t.failed) ?? traces[0])?.example_id ?? null;
}

export interface TraceSectionProps {
  runId: string;
  example?: string;
  letter: string;
  title: string;
}

export function TraceSection({ runId, example, letter, title }: TraceSectionProps) {
  const list = useRunTraces(runId);
  const traces = list.data ?? [];
  const chosen = example ? String(example) : pickExample(traces);
  const trace = useRunTrace(runId, chosen);
  return (
    <Figure
      letter={letter}
      title={chosen ? `${title} · ${chosen}` : title}
      aside={list.data ? `${traces.length} traced` : undefined}
    >
      {list.error ? <ErrorBox error={list.error} /> : null}
      {traces.length > 0 ? (
        <nav className="trace-pick" aria-label="Traced examples">
          {traces.map((t) => (
            <AppLink
              key={t.example_id}
              href={hrefs.run(runId, { example: t.example_id })}
              aria-current={t.example_id === chosen ? "true" : undefined}
              className={t.failed ? "failed" : undefined}
              title={`${t.turns} turns${t.failed ? ", failed" : ""}`}
            >
              {t.example_id}
            </AppLink>
          ))}
        </nav>
      ) : list.data ? (
        <p className="small">no traces</p>
      ) : null}
      {trace.error ? (
        <ErrorBox error={trace.error} />
      ) : trace.data ? (
        <PanelBody result={trace.data} />
      ) : chosen ? (
        <Loading />
      ) : null}
    </Figure>
  );
}

export interface KindPanelsProps {
  project: string;
  task: string;
  runId: string;
  specs: PanelSpec[];
  example?: string;
  startIndex: number;
}

export function KindPanels({ project, task, runId, specs, example, startIndex }: KindPanelsProps) {
  const { regular, trace } = splitRunView(specs);
  const panels = useViewQuery(
    project,
    task,
    regular.length > 0 ? { view: { title: "run", panels: regular.map((p) => scopeToRun(p, runId)) } } : null,
  );
  if (specs.length === 0) return null;
  return (
    <>
      {panels.error ? <ErrorBox error={panels.error} /> : null}
      {regular.length > 0 && panels.data ? (
        <PanelGrid results={panels.data.panels} specs={regular} startIndex={startIndex} />
      ) : regular.length > 0 && !panels.error ? (
        <Loading />
      ) : null}
      {trace ? (
        <TraceSection
          runId={runId}
          example={example}
          letter={panelLetter(startIndex + regular.length)}
          title={trace.title || "Trajectory"}
        />
      ) : null}
    </>
  );
}
```

`ui/src/pages/components/LogView.tsx`:

```tsx
/** A run log tail (opened from failures and the Where list via `?log=<stream>`). */
import { useRunLogs } from "../../api/queries";
import { Figure } from "./Figure";
import { fmtBytes } from "./format";
import { AppLink, hrefs } from "./links";
import { ErrorBox, Loading } from "./QueryState";
import type { LogStream } from "./types";

export function LogView({ runId, stream, letter }: { runId: string; stream: LogStream; letter: string }) {
  const log = useRunLogs(runId, stream);
  return (
    <Figure letter={letter} title={stream} aside={log.data ? fmtBytes(log.data.size) : undefined}>
      {log.error ? (
        <ErrorBox error={log.error} />
      ) : log.data ? (
        <pre className="log">{log.data.text.trimEnd() || "empty"}</pre>
      ) : (
        <Loading />
      )}
      <AppLink className="btn link" href={hrefs.run(runId)}>
        close
      </AppLink>
    </Figure>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/kindPanels.test.tsx`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/KindPanels.tsx ui/src/pages/components/LogView.tsx \
  ui/test/pages/kindPanels.test.tsx
git commit -m "feat(ui): kind run panels, trace picker, and log view"
```

### Task 35: Run page

**Files:**
- Create: `ui/src/pages/Run.tsx`
- Modify: `ui/src/router.tsx` (the run route keeps `?log` and `?example` and renders `RunPage`), `ui/test/router.test.tsx` (append two tests)
- Test: `ui/test/pages/Run.test.tsx`

**Interfaces:**
- Consumes: `GET /runs/{id}` → `RunDetail`; `GET /tasks/{p}/{t}/kind` → `KindInfo`;
  `GET /tasks/{p}/{t}/leaderboard` → `Leaderboard` (for the run's seed-group row and the
  primary metric), through Task 3 `api` and Task 4 `useRun`, `queryKeys`; Task 22 `firstClause`, `shortId`;
  Task 23 `AppLink`, `hrefs`; Task 24 `Figure`, `panelLetter`, `StatStrip`, `PageStyles`,
  `ErrorBox`, `Loading`; Task 31 `WhereList`; Task 32 `ScoresList`, `primaryRef`, `runStats`,
  `StatusLine`; Task 33 `Notes`, `RunActions`; Task 34 `KindPanels`, `kindPanelCount`, `LogView`.
- Produces: `RunPage({ runId, log?, example? })` for `/r/:runId`;
  `asLogStream(value: unknown): "stdout" | "stderr" | "supervisor" | null`.
  Panel order: log (when `?log=`), kind panels, Where, Scores, Notes; lettered in that order.

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/Run.test.tsx`:

```tsx
import { afterEach, describe, expect, test } from "bun:test";
import { cleanup, screen, waitFor } from "@testing-library/react";
import { RunPage, asLogStream } from "../../src/pages/Run";
import { RUN_SVM, SVM_HYPOTHESIS, makeBoard, makeDetail } from "./fixtures";
import { HttpReply, fakeRegistry, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const TASK = "/api/v1/tasks/toy-classifier/toy-test";

function routes(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail(),
    [`GET ${TASK}/kind`]: {
      kind: "generic",
      run_view: [{ type: "curves", title: "Metrics", data: {}, layout: { span: 12, row: null } }],
    },
    [`GET ${TASK}/leaderboard`]: makeBoard(),
    [`POST ${TASK}/views/query`]: { panels: [{ type: "curves", title: "Metrics", rows: [{}, {}], meta: {} }] },
    ...extra,
  };
}

const registry = fakeRegistry(["curves"]);

function regionNames(): (string | null)[] {
  return screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
}

function statValues(): (string | null)[] {
  return [...document.querySelectorAll(".stats dd")].map((d) => d.textContent);
}

test("asLogStream accepts only known streams", () => {
  expect(asLogStream("stderr")).toBe("stderr");
  expect(asLogStream("../etc/passwd")).toBeNull();
  expect(asLogStream(undefined)).toBeNull();
});

describe("RunPage", () => {
  test("renders title, crumb, stats, kind panels, then Where, Scores, Notes", async () => {
    const calls = mockApi(routes());
    renderWithClient(<RunPage runId={RUN_SVM} />, { registry });
    const h1 = await screen.findByRole("heading", { level: 1 });
    expect(h1.textContent).toBe(SVM_HYPOTHESIS);
    expect(h1.className).toBe("headline long");
    await screen.findByRole("region", { name: "a Metrics" });
    await waitFor(() =>
      expect(document.querySelector(".crumb")?.textContent).toBe(
        `toy-classifier/toy-test/RBF-kernel SVM/${RUN_SVM}generic`,
      ),
    );
    expect(regionNames()).toEqual(["a Metrics", "b Where", "c Scores", "d Notes"]);
    // the leaderboard loads in parallel; the strip fills in once it arrives
    await waitFor(() => expect(statValues()).toEqual(["0.9222", "0.874–0.953", "◇×3", "0.8 s"]));
    expect(screen.getByRole("link", { name: "toy-test" }).getAttribute("href")).toBe("/t/toy-classifier/toy-test");
    const query = calls.find((c) => c.method === "POST")?.body as {
      view: { title: string; panels: { data: { filter: Record<string, string> } }[] };
    };
    expect(query.view.panels[0]?.data.filter).toEqual({ run_id: RUN_SVM });
  });

  test("opens the requested log above the kind panels", async () => {
    mockApi(
      routes({
        [`GET /api/v1/runs/${RUN_SVM}/logs?stream=stderr`]: {
          stream: "stderr",
          text: "Traceback: boom",
          offset: 15,
          size: 15,
        },
      }),
    );
    renderWithClient(<RunPage runId={RUN_SVM} log="stderr" />, { registry });
    await screen.findByRole("region", { name: "b Metrics" });
    expect(regionNames()).toEqual(["a stderr", "b Metrics", "c Where", "d Scores", "e Notes"]);
    expect(await screen.findByText("Traceback: boom")).toBeTruthy();
  });

  test("renders a run that has no task", async () => {
    const calls = mockApi({ [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail({ task: null }) });
    renderWithClient(<RunPage runId={RUN_SVM} />, { registry });
    await screen.findByRole("region", { name: "a Where" });
    expect(regionNames()).toEqual(["a Where", "b Scores", "c Notes"]);
    expect(calls.map((c) => c.url)).toEqual([`/api/v1/runs/${RUN_SVM}`]);
    expect(document.querySelector(".crumb")?.textContent).toBe(
      `toy-classifier/RBF-kernel SVM/${RUN_SVM}`,
    );
    expect(statValues()).toEqual(["0.8 s"]);
  });

  test("shows the error for an unknown run", async () => {
    mockApi({ "GET /api/v1/runs/nope": new HttpReply(404, { error: "no run with id nope", type: "StoreError" }) });
    renderWithClient(<RunPage runId="nope" />, { registry });
    expect((await screen.findByRole("alert")).textContent).toBe("no run with id nope");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/Run.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/Run'`.

- [ ] **Step 3: Implement the page**

`ui/src/pages/Run.tsx`:

```tsx
/**
 * Run screen (spec 8.3.3): hypothesis as title, status, stat strip, the task kind's run
 * panels (spec 8.4), where everything is, scores by metric version, notes, and actions.
 */
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import { queryKeys, useRun } from "../api/queries";
import { Figure, panelLetter } from "./components/Figure";
import { firstClause, shortId } from "./components/format";
import { KindPanels, kindPanelCount } from "./components/KindPanels";
import { AppLink, hrefs } from "./components/links";
import { LogView } from "./components/LogView";
import { Notes } from "./components/Notes";
import { ErrorBox, Loading } from "./components/QueryState";
import { RunActions } from "./components/RunActions";
import { runStats } from "./components/runStats";
import { ScoresList, primaryRef } from "./components/ScoresList";
import { StatStrip } from "./components/StatStrip";
import { StatusLine } from "./components/StatusLine";
import { PageStyles } from "./components/styles";
import { WhereList } from "./components/WhereList";

const LOG_STREAMS = ["stdout", "stderr", "supervisor"] as const;
type LogStream = (typeof LOG_STREAMS)[number];

/** Accept only the log streams the API serves (the value comes from the URL). */
export function asLogStream(value: unknown): LogStream | null {
  return LOG_STREAMS.find((s) => s === value) ?? null;
}

export interface RunPageProps {
  runId: string;
  log?: string;
  example?: string;
}

const LONG_TITLE = 60;

export function RunPage({ runId, log, example }: RunPageProps) {
  const run = useRun(runId);
  const record = run.data?.record;
  const project = record?.project ?? "";
  const task = record?.task ?? "";
  const hasTask = task !== "";
  // The same keys as useTaskKind and useLeaderboard, but idle for a run without a task.
  const kind = useQuery({
    queryKey: queryKeys.taskKind(project, task),
    enabled: hasTask,
    queryFn: ({ signal }) => api.taskKind(project, task, signal),
  });
  const board = useQuery({
    queryKey: queryKeys.leaderboard(project, task),
    enabled: hasTask,
    queryFn: ({ signal }) => api.leaderboard(project, task, [], signal),
  });

  if (run.error) {
    return (
      <div className="page">
        <PageStyles />
        <ErrorBox error={run.error} />
      </div>
    );
  }
  if (!run.data || !record) {
    return (
      <div className="page">
        <PageStyles />
        <Loading />
      </div>
    );
  }

  const detail = run.data;
  const row = board.data?.rows.find((r) => r.run_ids.includes(runId)) ?? null;
  const primary = primaryRef(board.data ?? null, row);
  const specs = kind.data?.run_view ?? [];
  const stream = asLogStream(log);
  const label = row?.label ?? firstClause(record.hypothesis, `run ${shortId(runId)}`);
  const title = record.hypothesis || label;

  let next = 0;
  const logLetter = stream ? panelLetter(next++) : "";
  const kindStart = next;
  next += kindPanelCount(specs);
  const whereLetter = panelLetter(next++);
  const scoresLetter = panelLetter(next++);
  const notesLetter = panelLetter(next++);

  return (
    <div className="page">
      <PageStyles />
      <p className="crumb">
        {project}
        <span className="sep">/</span>
        {hasTask ? (
          <>
            <AppLink href={hrefs.task(project, task)}>{task}</AppLink>
            <span className="sep">/</span>
          </>
        ) : null}
        {label}
        <span className="sep">/</span>
        {runId}
        {kind.data ? (
          <span className="tag" title="task kind">
            {kind.data.kind}
          </span>
        ) : null}
      </p>
      <div className="run-top">
        <h1 className={title.length > LONG_TITLE ? "headline long" : "headline"}>{title}</h1>
        <RunActions record={record} />
      </div>
      <StatusLine record={record} />
      <StatStrip items={runStats(detail, primary, row)} />
      {kind.error ? <ErrorBox error={kind.error} /> : null}
      {stream ? <LogView runId={runId} stream={stream} letter={logLetter} /> : null}
      {hasTask ? (
        <KindPanels
          project={project}
          task={task}
          runId={runId}
          specs={specs}
          example={example}
          startIndex={kindStart}
        />
      ) : null}
      <div className="run-grid">
        <div>
          <Figure letter={whereLetter} title="Where" aside={<span title="host the run executed on">{record.host}</span>}>
            <WhereList detail={detail} />
          </Figure>
        </div>
        <div className="side">
          <Figure letter={scoresLetter} title="Scores">
            <ScoresList scores={detail.scores} metricNames={detail.metric_names} primary={primary} />
          </Figure>
          <Figure letter={notesLetter} title="Notes">
            <Notes runId={runId} notes={detail.notes} />
          </Figure>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/Run.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 5: Write the failing route test**

`Open stderr` on the Overview and the log rows of the Where list link to `/r/<id>?log=stderr`, and the trace picker links to `?example=`. The run route must keep both search values. Append to `ui/test/router.test.tsx`:

```tsx
test("/r/:runId keeps ?log and ?example for the run page", async () => {
  const { router } = renderApp("/r/r1?log=stderr&example=T-014");
  await settled(router, "/r/$runId");
  expect(leaf(router)?.search).toEqual({ log: "stderr", example: "T-014" });
});

test("/r/:runId keeps a numeric ?example id as a string", async () => {
  const { router } = renderApp("/r/r1?example=42");
  await settled(router, "/r/$runId");
  expect(leaf(router)?.search).toEqual({ log: undefined, example: "42" });
});
```

Run: `cd ui && bun test test/router.test.tsx`
Expected: FAIL: the run route has no `validateSearch` yet, so `search` is not `{ log: "stderr", example: "T-014" }`. The `?example=42` test pins that the id reaches the page as the string `"42"` (Task 6's `parseSearch` does no JSON parsing, and `str()` in Step 6 keeps strings); it must pass after Step 6.

- [ ] **Step 6: Show the page on `/r/$runId`**

In `ui/src/router.tsx` replace

```tsx
import { TaskPage } from "./pages/Task";
```

with

```tsx
import { RunPage } from "./pages/Run";
import { TaskPage } from "./pages/Task";
```

replace

```tsx
export interface ExamplesSearch {
  metric?: string;
}
```

with

```tsx
export interface ExamplesSearch {
  metric?: string;
}

export interface RunSearch {
  log?: string;
  example?: string;
}
```

replace

```tsx
  return <TaskPage project={project} task={task} view={view} />;
}
```

with

```tsx
  return <TaskPage project={project} task={task} view={view} />;
}

/** `/r/$runId?log=&example=`: the Run page. */
function RunScreen(): ReactElement {
  const { runId } = runRoute.useParams();
  const { log, example } = runRoute.useSearch();
  return <RunPage runId={runId} log={log} example={example} />;
}
```

and replace

```tsx
  path: "/r/$runId",
  component: () => <ScreenPending name="Run" />,
});
```

with

```tsx
  path: "/r/$runId",
  validateSearch: (search: Record<string, unknown>): RunSearch => ({
    log: str(search.log),
    example: str(search.example),
  }),
  component: RunScreen,
});
```

Run: `cd ui && bun test test/router.test.tsx test/shell && bun run typecheck`
Expected: `0 fail`; `tsc` prints nothing.

- [ ] **Step 7: Commit**

```bash
git add ui/src/pages/Run.tsx ui/test/pages/Run.test.tsx ui/src/router.tsx ui/test/router.test.tsx
git commit -m "feat(ui): run page with kind panels, where list, scores, notes, actions"
```

### Task 36: Examples math and charts

**Files:**
- Create: `ui/src/pages/components/examples.ts`
- Create: `ui/src/pages/components/ExampleCharts.tsx`
- Test: `ui/test/pages/exampleCharts.test.tsx`

**Interfaces:**
- Consumes: `ExampleDiff`, `RunRecord`, `PredictionRow` (Task 21); `firstClause`, `fmtDelta`,
  `fmtP`, `fmtSigned`, `fmtValue`, `shortId` (Task 22); `d3-scale` `scaleBand`, `scaleLinear`;
  `d3-array` `range`, `max`.
- Produces:
  - `binomPmf(n: number): number[]` (Binomial(n, ½) for k = 0..n, log space);
    `signTestP(fixed: number, broken: number): number` (exact two-sided; 1 when both 0).
    The UI computes this itself because `GET /compare/examples` returns only the counts.
  - `type Outcome = "fixed" | "broken" | "both_fail" | "both_pass"`;
    `interface Segment { outcome: Outcome; count: number; ids: string[]; label: string }`;
    `stripSegments(diff): Segment[]`; `exampleTotal(diff): number`.
  - `pairLabels(a: RunRecord, b: RunRecord): [string, string]` (short hypothesis labels;
    the run's short id is appended when both labels are equal).
  - `examplesHeadline(labelA, labelB, diff): string` (`B fixes 9, breaks 3 vs A, p = 0.15`);
    `examplesMeta(diff): string[]` (`n = 180`, `net +6`, `Δ +0.0333`).
  - `OutcomeTable({ labelA, labelB, diff })`, `ExampleStrip({ diff })`,
    `SignTestChart({ fixed, broken })`,
    `ErrorsTable({ rows, total, labelA, labelB, brokenIds, onMore })`.

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/exampleCharts.test.tsx`:

```tsx
import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  ErrorsTable,
  ExampleStrip,
  OutcomeTable,
  SignTestChart,
} from "../../src/pages/components/ExampleCharts";
import {
  binomPmf,
  examplesHeadline,
  examplesMeta,
  exampleTotal,
  pairLabels,
  signTestP,
  stripSegments,
} from "../../src/pages/components/examples";
import { RUN_RF, RUN_SVM, makeDiff, makeRecord } from "./fixtures";

afterEach(cleanup);

describe("sign test", () => {
  test("binomPmf is Binomial(n, 1/2)", () => {
    const pmf = binomPmf(4);
    [1, 4, 6, 4, 1].forEach((c, k) => expect(pmf[k]).toBeCloseTo(c / 16, 12));
    expect(binomPmf(1000).reduce((s, v) => s + v, 0)).toBeCloseTo(1, 9);
    expect(() => binomPmf(-1)).toThrow(RangeError);
  });

  test("signTestP matches exact binomial tails", () => {
    // 2 * P(X <= 3 | n = 12, p = 1/2) = 2 * (1 + 12 + 66 + 220) / 4096 = 598/4096;
    // same as scipy.stats.binomtest(9, 12, 0.5).pvalue = 0.14599609375
    expect(signTestP(9, 3)).toBeCloseTo(598 / 4096, 12);
    expect(signTestP(3, 9)).toBeCloseTo(598 / 4096, 12);
    // 2 * P(X = 0 | n = 10) = 2/1024
    expect(signTestP(10, 0)).toBeCloseTo(2 / 1024, 14);
    // 2 * P(X <= 5 | n = 10) = 2 * 638/1024 > 1, capped
    expect(signTestP(5, 5)).toBe(1);
    expect(signTestP(0, 0)).toBe(1);
    // 400 of 1000: z = (400.5 - 500) / 15.81 = -6.29, normal tail ~3e-10
    const p = signTestP(600, 400);
    expect(p).toBeGreaterThan(1e-11);
    expect(p).toBeLessThan(1e-8);
  });
});

describe("labels and summaries", () => {
  test("stripSegments orders fixed, broken, both wrong, both right", () => {
    const segs = stripSegments(makeDiff());
    expect(segs.map((s) => [s.outcome, s.count, s.label])).toEqual([
      ["fixed", 9, "9 fixed"],
      ["broken", 3, "3 broken"],
      ["both_fail", 11, "11 both wrong"],
      ["both_pass", 157, "157 both right"],
    ]);
    expect(segs[1]?.ids).toEqual(["test-137", "test-167", "test-30"]);
    expect(exampleTotal(makeDiff())).toBe(180);
  });

  test("pairLabels shortens hypotheses and separates equal labels", () => {
    const rf = makeRecord({ run_id: RUN_RF, hypothesis: "baseline rf" });
    expect(pairLabels(rf, makeRecord())).toEqual(["baseline rf", "RBF-kernel SVM"]);
    const rf2 = makeRecord({ run_id: RUN_SVM, hypothesis: "baseline rf" });
    expect(pairLabels(rf, rf2)).toEqual(["baseline rf ef4f", "baseline rf 6f71"]);
  });

  test("headline and meta line", () => {
    expect(examplesHeadline("baseline rf", "RBF-kernel SVM", makeDiff())).toBe(
      "RBF-kernel SVM fixes 9, breaks 3 vs baseline rf, p = 0.15",
    );
    expect(examplesMeta(makeDiff())).toEqual(["n = 180", "net +6", "Δ +0.0333"]);
    const none = { ...makeDiff(), fixed: [], broken: [], both_pass: 0, both_fail: 0 };
    expect(examplesHeadline("A", "B", none)).toBe("B fixes 0, breaks 0 vs A, p = 1.00");
    expect(examplesMeta(none)).toEqual(["n = 0"]);
  });
});

describe("charts", () => {
  test("OutcomeTable is the 2x2 of A and B outcomes", () => {
    const { container } = render(<OutcomeTable labelA="rf" labelB="SVM" diff={makeDiff()} />);
    expect([...container.querySelectorAll("td .n")].map((n) => n.textContent)).toEqual(["157", "3", "9", "11"]);
    expect(screen.getByText("SVM right")).toBeTruthy();
    expect(screen.getByText("rf wrong")).toBeTruthy();
  });

  test("ExampleStrip draws one mark per example with ids as titles", () => {
    const { container } = render(<ExampleStrip diff={makeDiff()} />);
    const count = (cls: string) => container.querySelectorAll(`rect.${cls}`).length;
    expect([count("fixed"), count("broken"), count("both_fail"), count("both_pass")]).toEqual([9, 3, 11, 157]);
    expect(container.querySelector("rect.fixed title")?.textContent).toBe("test-0");
    expect(screen.getByText("157 both right")).toBeTruthy();
  });

  test("ExampleStrip draws one block per outcome above 2000 examples", () => {
    const big = { ...makeDiff(), both_pass: 5000 };
    const { container } = render(<ExampleStrip diff={big} />);
    expect([...container.querySelectorAll("rect")].map((r) => r.getAttribute("class"))).toEqual([
      "fixed",
      "broken",
      "both_fail",
      "both_pass",
    ]);
  });

  test("SignTestChart marks both tails and the observed split", () => {
    const { container } = render(<SignTestChart fixed={9} broken={3} />);
    expect(container.querySelectorAll("rect")).toHaveLength(13);
    // tails as extreme as 9:3 are k <= 3 and k >= 9: 0,1,2,3,9,10,11,12
    expect(container.querySelectorAll("rect[data-tail='true']")).toHaveLength(8);
    expect(screen.getByText("9:3")).toBeTruthy();
    expect(screen.getByText("p = 0.15")).toBeTruthy();
  });

  test("SignTestChart with nothing changed says so", () => {
    render(<SignTestChart fixed={0} broken={0} />);
    expect(screen.getByText("no changed examples")).toBeTruthy();
  });

  test("ErrorsTable marks what A did on B's errors and pages on", () => {
    const onMore = mock(() => {});
    render(
      <ErrorsTable
        rows={[
          { id: "test-7", prediction: 2, reference: 1, scores: {} },
          { id: "test-30", prediction: 2, reference: 0, scores: {} },
        ]}
        total={14}
        labelA="rf"
        labelB="SVM"
        brokenIds={new Set(["test-30"])}
        onMore={onMore}
      />,
    );
    const cells = screen.getAllByRole("cell").map((c) => c.textContent);
    expect(cells).toEqual(["test-7", "2", "1", "wrong", "test-30", "2", "0", "right"]);
    fireEvent.click(screen.getByRole("button", { name: "+12 more" }));
    expect(onMore).toHaveBeenCalledTimes(1);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/exampleCharts.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/components/ExampleCharts'`.

- [ ] **Step 3: Implement the math and charts**

`ui/src/pages/components/examples.ts`:

```ts
/** Pure helpers for the two-run Examples page (spec 8.3.4 and 8.5). */
import { firstClause, fmtDelta, fmtP, fmtSigned, shortId } from "./format";
import type { ExampleDiff, RunRecord } from "./types";

function logFactorials(n: number): number[] {
  const out = [0];
  for (let k = 1; k <= n; k++) out.push((out[k - 1] ?? 0) + Math.log(k));
  return out;
}

/** Binomial(n, 1/2) probabilities for k = 0..n, computed in log space. */
export function binomPmf(n: number): number[] {
  if (!Number.isInteger(n) || n < 0) {
    throw new RangeError(`n must be a non-negative integer, got ${n}`);
  }
  const lf = logFactorials(n);
  const top = lf[n] ?? 0;
  return Array.from({ length: n + 1 }, (_, k) =>
    Math.exp(top - (lf[k] ?? 0) - (lf[n - k] ?? 0) - n * Math.LN2),
  );
}

/** Exact two-sided sign test on the discordant examples; 1 when none changed. */
export function signTestP(fixed: number, broken: number): number {
  const n = fixed + broken;
  if (n === 0) return 1;
  const pmf = binomPmf(n);
  const lo = Math.min(fixed, broken);
  let tail = 0;
  for (let k = 0; k <= lo; k++) tail += pmf[k] ?? 0;
  return Math.min(1, 2 * tail);
}

export type Outcome = "fixed" | "broken" | "both_fail" | "both_pass";

export interface Segment {
  outcome: Outcome;
  count: number;
  ids: string[];
  label: string;
}

/** Outcome groups in strip order; only fixed and broken ids are known. */
export function stripSegments(diff: ExampleDiff): Segment[] {
  return [
    { outcome: "fixed", count: diff.fixed.length, ids: diff.fixed, label: `${diff.fixed.length} fixed` },
    { outcome: "broken", count: diff.broken.length, ids: diff.broken, label: `${diff.broken.length} broken` },
    { outcome: "both_fail", count: diff.both_fail, ids: [], label: `${diff.both_fail} both wrong` },
    { outcome: "both_pass", count: diff.both_pass, ids: [], label: `${diff.both_pass} both right` },
  ];
}

/** Examples scored in both runs. */
export function exampleTotal(diff: ExampleDiff): number {
  return diff.fixed.length + diff.broken.length + diff.both_fail + diff.both_pass;
}

/** Short labels for runs A and B; equal labels get the run's short id. */
export function pairLabels(a: RunRecord, b: RunRecord): [string, string] {
  const la = firstClause(a.hypothesis, `run ${shortId(a.run_id)}`);
  const lb = firstClause(b.hypothesis, `run ${shortId(b.run_id)}`);
  if (la !== lb) return [la, lb];
  return [`${la} ${shortId(a.run_id)}`, `${lb} ${shortId(b.run_id)}`];
}

/** `B fixes 9, breaks 3 vs A, p = 0.15`. */
export function examplesHeadline(labelA: string, labelB: string, diff: ExampleDiff): string {
  const p = signTestP(diff.fixed.length, diff.broken.length);
  return `${labelB} fixes ${diff.fixed.length}, breaks ${diff.broken.length} vs ${labelA}, ${fmtP(p)}`;
}

/** `n = 180`, `net +6`, `Δ +0.0333` (the change in pass rate). */
export function examplesMeta(diff: ExampleDiff): string[] {
  const n = exampleTotal(diff);
  if (n === 0) return ["n = 0"];
  const net = diff.fixed.length - diff.broken.length;
  return [`n = ${n}`, `net ${fmtSigned(net)}`, `Δ ${fmtDelta(net / n)}`];
}
```

`ui/src/pages/components/ExampleCharts.tsx`:

```tsx
/** Examples page figures: outcome table, per-example strip, sign test, B's errors. */
import { max, range } from "d3-array";
import { scaleBand, scaleLinear } from "d3-scale";
import type { ReactElement } from "react";
import { type Segment, binomPmf, exampleTotal, signTestP, stripSegments } from "./examples";
import { fmtP, fmtValue } from "./format";
import type { ExampleDiff, PredictionRow } from "./types";

export function OutcomeTable({ labelA, labelB, diff }: { labelA: string; labelB: string; diff: ExampleDiff }) {
  return (
    <table className="ot">
      <thead>
        <tr>
          <th />
          <th>{`${labelB} right`}</th>
          <th>{`${labelB} wrong`}</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <th className="rh">{`${labelA} right`}</th>
          <td className="same">
            <span className="n">{diff.both_pass}</span>
          </td>
          <td className="bk">
            <span className="n">{diff.broken.length}</span>
            <span className="w">
              <i className="sw broken" />
              broken
            </span>
          </td>
        </tr>
        <tr>
          <th className="rh">{`${labelA} wrong`}</th>
          <td className="fx">
            <span className="n">{diff.fixed.length}</span>
            <span className="w">
              <i className="sw fixed" />
              fixed
            </span>
          </td>
          <td className="same">
            <span className="n">{diff.both_fail}</span>
          </td>
        </tr>
      </tbody>
    </table>
  );
}

const STRIP_W = 1000;
const STRIP_H = 44;
const MAX_MARKS = 2000;

function marks(segments: Segment[], n: number): ReactElement[] {
  const out: ReactElement[] = [];
  if (n > MAX_MARKS) {
    let x = 0;
    for (const seg of segments) {
      if (seg.count === 0) continue;
      const w = (STRIP_W * seg.count) / n;
      out.push(
        <rect key={seg.outcome} className={seg.outcome} x={x} y={0} width={w} height={STRIP_H}>
          <title>{seg.label}</title>
        </rect>,
      );
      x += w;
    }
    return out;
  }
  const w = STRIP_W / n;
  const gap = w > 3 ? w * 0.25 : 0;
  let i = 0;
  for (const seg of segments) {
    for (let k = 0; k < seg.count; k++) {
      const id = seg.ids[k];
      out.push(
        <rect key={i} className={seg.outcome} x={i * w} y={0} width={w - gap} height={STRIP_H}>
          {id ? <title>{id}</title> : null}
        </rect>,
      );
      i += 1;
    }
  }
  return out;
}

export function ExampleStrip({ diff }: { diff: ExampleDiff }) {
  const n = exampleTotal(diff);
  if (n === 0) return <p className="small">no shared examples</p>;
  const segments = stripSegments(diff);
  return (
    <div className="strip">
      <svg viewBox={`0 0 ${STRIP_W} ${STRIP_H}`} preserveAspectRatio="none" aria-label="One mark per example">
        {marks(segments, n)}
      </svg>
      <ul className="strip-key">
        {segments.map((seg) => (
          <li key={seg.outcome}>
            <i className={`sw ${seg.outcome}`} />
            {seg.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

const ST_W = 640;
const ST_H = 220;
const ST_BOTTOM = 24;
const ST_TOP = 40;

export function SignTestChart({ fixed, broken }: { fixed: number; broken: number }) {
  const n = fixed + broken;
  if (n === 0) return <p className="small">no changed examples</p>;
  const pmf = binomPmf(n);
  const p = signTestP(fixed, broken);
  const lo = Math.min(fixed, broken);
  const hi = n - lo;
  const x = scaleBand<number>().domain(range(n + 1)).range([0, ST_W]).padding(0.25);
  const y = scaleLinear()
    .domain([0, max(pmf) ?? 1])
    .range([ST_H - ST_BOTTOM, ST_TOP]);
  const bw = x.bandwidth();
  const every = n <= 24 ? 1 : Math.ceil(n / 12);
  const ox = (x(fixed) ?? 0) + bw / 2;
  return (
    <div className="signtest" title="Exact two-sided binomial test on the examples that changed">
      <svg viewBox={`0 0 ${ST_W} ${ST_H}`} aria-label="Sign test null distribution">
        {pmf.map((v, k) => (
          <rect
            key={`b${k}`}
            data-tail={k <= lo || k >= hi ? "true" : "false"}
            x={x(k) ?? 0}
            y={y(v)}
            width={bw}
            height={ST_H - ST_BOTTOM - y(v)}
          >
            <title>{`${k} fixed: ${(v * 100).toFixed(1)}%`}</title>
          </rect>
        ))}
        {pmf.map((_, k) =>
          k % every === 0 ? (
            <text key={`t${k}`} x={(x(k) ?? 0) + bw / 2} y={ST_H - 6} textAnchor="middle">
              {k}
            </text>
          ) : null,
        )}
        <line className="obs" x1={ox} x2={ox} y1={ST_TOP - 4} y2={y(pmf[fixed] ?? 0)} />
        <text className="obs-l" x={ox} y={ST_TOP - 24} textAnchor="middle">
          {`${fixed}:${broken}`}
        </text>
        <text className="obs-l" x={ox} y={ST_TOP - 10} textAnchor="middle">
          {fmtP(p)}
        </text>
      </svg>
    </div>
  );
}

export interface ErrorsTableProps {
  rows: PredictionRow[];
  total: number;
  labelA: string;
  labelB: string;
  brokenIds: ReadonlySet<string>;
  onMore: () => void;
}

/** B's failing examples with B's answer, the label, and whether A got them right. */
export function ErrorsTable({ rows, total, labelA, labelB, brokenIds, onMore }: ErrorsTableProps) {
  if (total === 0) return <p className="small">none</p>;
  return (
    <div>
      <table className="tbl">
        <thead>
          <tr>
            <th>Example</th>
            <th className="r">{labelB}</th>
            <th className="r">label</th>
            <th>{labelA}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const aRight = brokenIds.has(row.id);
            return (
              <tr key={row.id}>
                <td>{row.id}</td>
                <td className="r">{fmtValue(row.prediction)}</td>
                <td className="r">{fmtValue(row.reference)}</td>
                <td>
                  <i className={aRight ? "sw broken" : "sw both_fail"} />
                  {aRight ? "right" : "wrong"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      {total > rows.length ? (
        <button type="button" className="btn link" onClick={onMore}>
          {`+${total - rows.length} more`}
        </button>
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/exampleCharts.test.tsx`
Expected: PASS (11 tests).

- [ ] **Step 5: Commit**

```bash
git add ui/src/pages/components/examples.ts ui/src/pages/components/ExampleCharts.tsx \
  ui/test/pages/exampleCharts.test.tsx
git commit -m "feat(ui): sign test, outcome table, and per-example strip"
```

### Task 37: Examples page and full unit-suite check

**Files:**
- Create: `ui/src/pages/Examples.tsx`
- Modify: `ui/src/router.tsx` (the examples route renders `ExamplesPage`)
- Test: `ui/test/pages/Examples.test.tsx`

**Interfaces:**
- Consumes: `GET /runs/{a}`, `GET /runs/{b}` → `RunDetail`; `GET /tasks/{p}/{t}` →
  `TaskDetail` (primary metric when `?metric=` is absent); `GET /runs/{b}/predictions?metric&limit=1`
  → `PredictionPage` (one row, to read the binary field); `GET /compare/examples?a&b&metric&field`
  → `ExampleDiff`; `GET /runs/{b}/predictions?metric&failures_only=true&field&limit` → `PredictionPage`
  (phase 1a). Both phase 1a routes default to `field="correct"` and silently drop examples
  without that field, so the page always sends the field it read (an agent task's `solved`
  would otherwise give `fixes 0, breaks 0, p = 1.00`). Task 3 `api`; Task 4 `useRun`, `queryKeys`; Task 22 `fmtScore`, `isAgent`,
  `primaryMetricName`; Task 23 `AppLink`, `hrefs`; Task 24 `Figure`, `PageStyles`, `ErrorBox`,
  `Loading`; Task 32 `scoreFor`; Task 36 everything.
- Produces: `pickExampleField(page: PredictionPage, metric: string): string | undefined`
  (`correct`, then `solved` when binary, then the first boolean field by name, in the scores
  of `metric` or `name@version`; `undefined` when the row has no per-example scores for it);
  `ExamplesPage({ a, b, metric? })` for `/x/:a/:b?metric=`: headline
  `B fixes f, breaks k vs A, p = …`, meta line, A/B header with scores, panels
  a Outcomes, b Sign test, c Per example, d `<B> errors` (8 rows, `+N more` adds 50).

- [ ] **Step 1: Write the failing tests**

`ui/test/pages/Examples.test.tsx`:

```tsx
import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import type { PredictionPage, TaskDetail } from "../../src/pages/components/types";
import { ExamplesPage, pickExampleField } from "../../src/pages/Examples";
import { RUN_RF, RUN_SVM, makeDetail, makeDiff } from "./fixtures";
import { HttpReply, mockApi, renderWithClient, restoreFetch } from "./helpers";

afterEach(() => {
  cleanup();
  restoreFetch();
});

const PRED = `/api/v1/runs/${RUN_SVM}/predictions?metric=accuracy%40v1&failures_only=true&field=correct`;
const PROBE = `/api/v1/runs/${RUN_SVM}/predictions?metric=accuracy&limit=1`;
const COMPARE = `/api/v1/compare/examples?a=${RUN_RF}&b=${RUN_SVM}&metric=accuracy&field=correct`;

/** One predictions row whose per-example scores are `scores`. */
function probe(scores: Record<string, Record<string, unknown>>): PredictionPage {
  return { run_id: RUN_SVM, total: 180, offset: 0, limit: 1, rows: [{ id: "test-0", prediction: 1, reference: 1, scores }] };
}

function page(ids: [string, number, number][]): PredictionPage {
  return {
    run_id: RUN_SVM,
    total: 14,
    offset: 0,
    limit: ids.length,
    rows: ids.map(([id, prediction, reference]) => ({ id, prediction, reference, scores: {} })),
  };
}

function routes(extra: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    [`GET /api/v1/runs/${RUN_RF}`]: makeDetail(
      { run_id: RUN_RF, hypothesis: "baseline rf", created_by: "human" },
      {
        scores: [
          {
            metric: "accuracy",
            version: "v1",
            key: "value",
            value: 0.8888888888888888,
            error: null,
            source_hash: null,
            created_at: "2026-09-26T21:00:33Z",
          },
        ],
      },
    ),
    [`GET /api/v1/runs/${RUN_SVM}`]: makeDetail(),
    [`GET ${PROBE}`]: probe({ "accuracy@v1": { correct: true } }),
    [`GET ${COMPARE}`]: makeDiff(),
    [`GET ${PRED}&limit=8`]: page([
      ["test-7", 2, 1],
      ["test-30", 2, 0],
    ]),
    [`GET ${PRED}&limit=58`]: page([
      ["test-7", 2, 1],
      ["test-30", 2, 0],
      ["test-54", 0, 2],
    ]),
    ...extra,
  };
}

test("compares two runs example by example", async () => {
  mockApi(routes());
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} metric="accuracy" />);
  await screen.findByRole("heading", {
    level: 1,
    name: "RBF-kernel SVM fixes 9, breaks 3 vs baseline rf, p = 0.15",
  });
  for (const text of ["n = 180", "net +6", "Δ +0.0333", "baseline rf, seed 3", "RBF-kernel SVM, seed 3", "0.8889", "0.9222"]) {
    expect(screen.getByText(text)).toBeTruthy();
  }
  const names = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
  expect(names).toEqual(["a Outcomes", "b Sign test", "c Per example", "d RBF-kernel SVM errors"]);

  const errors = screen.getByRole("region", { name: "d RBF-kernel SVM errors" });
  const rows = await within(errors).findAllByRole("row");
  expect(rows.map((r) => [...r.querySelectorAll("td")].map((c) => c.textContent))).toEqual([
    [],
    ["test-7", "2", "1", "wrong"],
    ["test-30", "2", "0", "right"],
  ]);
  expect(errors.querySelector(".aside")?.textContent).toBe("2 of 14");
  fireEvent.click(within(errors).getByRole("button", { name: "+12 more" }));
  expect(await within(errors).findByText("test-54")).toBeTruthy();
  expect(errors.querySelector(".aside")?.textContent).toBe("3 of 14");
});

test("uses the task's primary metric when ?metric= is absent", async () => {
  const task: TaskDetail = {
    summary: {
      project: "toy-classifier",
      name: "toy-test",
      description: "",
      dataset: "toyset",
      dataset_version: "v1",
      split: "test",
      metrics: { accuracy: "v1", macro_f1: "v1" },
      primary: "accuracy/value",
      higher_is_better: true,
      n_runs: 12,
      best: 0.9222222222222222,
    },
    repo: "/private/tmp/hx-accept/toy",
    dataset: { name: "toyset" },
    metrics: {},
    stages: {},
  };
  const calls = mockApi(routes({ "GET /api/v1/tasks/toy-classifier/toy-test": task }));
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} />);
  await screen.findByRole("heading", { level: 1, name: /fixes 9, breaks 3/ });
  expect(calls.some((c) => c.url === COMPARE)).toBe(true);
});

test("shows the server error when a run has no per-example scores", async () => {
  mockApi(
    routes({
      [`GET ${COMPARE}`]: new HttpReply(400, {
        error: `run ${RUN_RF} has no per-example scores for accuracy@v1`,
        type: "EvalError",
      }),
    }),
  );
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} metric="accuracy" />);
  expect((await screen.findByRole("alert")).textContent).toBe(
    `run ${RUN_RF} has no per-example scores for accuracy@v1`,
  );
});

test("asks for ?metric= when run A has no task", async () => {
  mockApi(routes({ [`GET /api/v1/runs/${RUN_RF}`]: makeDetail({ run_id: RUN_RF, task: null }) }));
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} />);
  expect((await screen.findByRole("alert")).textContent).toBe("no task: add ?metric=<name> to the URL");
});

test("pickExampleField reads correct, then solved, then the first boolean field", () => {
  expect(pickExampleField(probe({ "accuracy@v1": { correct: false, loss: 0.2 } }), "accuracy")).toBe("correct");
  expect(pickExampleField(probe({ "solved@v2": { solved: 1, turns: 7 } }), "solved@v2")).toBe("solved");
  expect(pickExampleField(probe({ "rubric@v1": { score: 0.5, valid: true, exact: false } }), "rubric")).toBe("exact");
  expect(pickExampleField(probe({ "bleu@v1": { value: 31.2 } }), "bleu")).toBeUndefined();
  expect(pickExampleField(probe({}), "accuracy")).toBeUndefined();
  expect(pickExampleField(probe({ "other@v1": { correct: true } }), "accuracy")).toBeUndefined();
});

test("sends the solved field to compare and to the errors query", async () => {
  const solvedProbe = `/api/v1/runs/${RUN_SVM}/predictions?metric=solved&limit=1`;
  const solvedCompare = `/api/v1/compare/examples?a=${RUN_RF}&b=${RUN_SVM}&metric=solved&field=solved`;
  const solvedErrors = `/api/v1/runs/${RUN_SVM}/predictions?metric=solved%40v2&failures_only=true&field=solved&limit=8`;
  const calls = mockApi(
    routes({
      [`GET ${solvedProbe}`]: probe({ "solved@v2": { solved: false, turns: 12 } }),
      [`GET ${solvedCompare}`]: { ...makeDiff(), metric: "solved@v2", field: "solved" },
      [`GET ${solvedErrors}`]: page([["task-17", 0, 1]]),
    }),
  );
  renderWithClient(<ExamplesPage a={RUN_RF} b={RUN_SVM} metric="solved" />);
  await screen.findByRole("heading", { level: 1, name: /fixes 9, breaks 3/ });
  const errors = screen.getByRole("region", { name: "d RBF-kernel SVM errors" });
  expect(await within(errors).findByText("task-17")).toBeTruthy();
  const urls = calls.map((c) => c.url);
  expect(urls).toContain(solvedCompare);
  expect(urls).toContain(solvedErrors);
  expect(urls.some((u) => u.startsWith("/api/v1/compare/examples") && !u.includes("field="))).toBe(false);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/pages/Examples.test.tsx`
Expected: FAIL with `Cannot find module '../../src/pages/Examples'`.

- [ ] **Step 3: Implement the page**

`ui/src/pages/Examples.tsx`:

```tsx
/**
 * Examples screen (spec 8.3.4): two runs compared example by example: 2×2 outcome
 * table, sign-test p, one mark per example, and B's failing examples.
 */
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { queryKeys, useRun } from "../api/queries";
import { ErrorsTable, ExampleStrip, OutcomeTable, SignTestChart } from "./components/ExampleCharts";
import { examplesHeadline, examplesMeta, exampleTotal, pairLabels } from "./components/examples";
import { Figure } from "./components/Figure";
import { fmtScore, isAgent, primaryMetricName } from "./components/format";
import { AppLink, hrefs } from "./components/links";
import { ErrorBox, Loading } from "./components/QueryState";
import { scoreFor } from "./components/ScoresList";
import { PageStyles } from "./components/styles";
import type { PredictionPage, RunDetail } from "./components/types";

export interface ExamplesPageProps {
  a: string;
  b: string;
  metric?: string;
}

const FIRST_PAGE = 8;
const MORE = 50;

/** 0/1 or a bool, as the server's `pick_field` treats `correct` and `solved`. */
function isBinary(v: unknown): boolean {
  return typeof v === "boolean" || v === 0 || v === 1;
}

/**
 * The per-example field that marks success for `metric` (`name` or `name@version`), read from
 * the first row of a predictions page: `correct`, then `solved` (bool or 0/1), then the first
 * boolean field by name, the order of the server's `pick_field`. Phase 1a `compare/examples`
 * and `predictions` default to `correct` and drop examples without it, so an agent task
 * (`solved`) must send its field. `undefined` when the row has no scores for `metric`.
 */
export function pickExampleField(page: PredictionPage, metric: string): string | undefined {
  const scores = page.rows[0]?.scores ?? {};
  const fields =
    scores[metric] ?? Object.entries(scores).find(([ref]) => ref.split("@")[0] === metric)?.[1];
  if (!fields) return undefined;
  for (const name of ["correct", "solved"]) if (isBinary(fields[name])) return name;
  return Object.keys(fields)
    .sort()
    .find((name) => typeof fields[name] === "boolean");
}

interface SideProps {
  tag: "A" | "B";
  detail: RunDetail;
  label: string;
  metric: string | null;
}

function Side({ tag, detail, label, metric }: SideProps) {
  const record = detail.record;
  const value = metric ? scoreFor(detail.scores, metric) : null;
  return (
    <div>
      <div className="lbl">{tag}</div>
      <div className="row">
        <div>
          <div className="nm">{record.seed !== null ? `${label}, seed ${record.seed}` : label}</div>
          <div className="meta">
            <span className={`who ${isAgent(record.created_by) ? "agent" : "human"}`}>
              <i />
              {record.created_by}
            </span>
            <AppLink href={hrefs.run(record.run_id)}>{record.run_id}</AppLink>
          </div>
        </div>
        {value !== null && metric ? (
          <div className="acc">
            <span>{fmtScore(value)}</span>
            <small>{metric.replace("@", " ")}</small>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function ExamplesPage({ a, b, metric }: ExamplesPageProps) {
  const runA = useRun(a);
  const runB = useRun(b);
  const recA = runA.data?.record;
  const recB = runB.data?.record;
  const project = recA?.project ?? "";
  const task = recA?.task ?? "";
  const explicit = metric ? String(metric) : null;

  const taskQ = useQuery({
    queryKey: queryKeys.task(project, task),
    enabled: explicit === null && task !== "",
    queryFn: ({ signal }) => api.task(project, task, signal),
  });
  const metricRef = explicit ?? (taskQ.data ? primaryMetricName(taskQ.data.summary.primary) : null);
  // One row of B's per-example scores names the binary field (`correct`, `solved`, ...).
  // If this read fails, compare still runs without a field and shows the server's own error.
  const probe = { metric: metricRef ?? "", limit: 1 };
  const fieldQ = useQuery({
    queryKey: queryKeys.runPredictions(b, probe),
    enabled: metricRef !== null,
    queryFn: ({ signal }) => api.runPredictions(b, probe, signal),
  });
  const field = fieldQ.data && metricRef ? pickExampleField(fieldQ.data, metricRef) : undefined;
  const diffQ = useQuery({
    queryKey: queryKeys.compareExamples(a, b, metricRef ?? "", field),
    enabled: metricRef !== null && !fieldQ.isPending,
    queryFn: ({ signal }) => api.compareExamples(a, b, metricRef ?? "", field, signal),
  });
  const diff = diffQ.data;
  const [limit, setLimit] = useState(FIRST_PAGE);
  const failing = { metric: diff?.metric, failures_only: true, field: diff?.field, limit };
  const errors = useQuery({
    queryKey: queryKeys.runPredictions(b, failing),
    enabled: diff !== undefined,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) => api.runPredictions(b, failing, signal),
  });

  const labels = recA && recB ? pairLabels(recA, recB) : null;
  const [labelA, labelB] = labels ?? ["A", "B"];
  const noMetric = explicit === null && recA !== undefined && task === "";
  const error = runA.error ?? runB.error ?? taskQ.error ?? diffQ.error;
  const changed = diff ? diff.fixed.length + diff.broken.length : 0;

  return (
    <div className="page">
      <PageStyles />
      <p className="crumb">
        {project || "…"}
        <span className="sep">/</span>
        {task ? (
          <>
            <AppLink href={hrefs.task(project, task)}>{task}</AppLink>
            <span className="sep">/</span>
          </>
        ) : null}
        examples
      </p>
      <h1 className="headline">{diff && labels ? examplesHeadline(labelA, labelB, diff) : "Examples"}</h1>
      {diff ? (
        <p className="metaline">
          {examplesMeta(diff).map((text) => (
            <span key={text}>{text}</span>
          ))}
        </p>
      ) : null}
      {runA.data && runB.data ? (
        <div className="ab">
          <Side tag="A" detail={runA.data} label={labelA} metric={diff?.metric ?? null} />
          <Side tag="B" detail={runB.data} label={labelB} metric={diff?.metric ?? null} />
        </div>
      ) : null}
      {error ? <ErrorBox error={error} /> : null}
      {noMetric ? <ErrorBox error={new Error("no task: add ?metric=<name> to the URL")} /> : null}
      {diff ? (
        <>
          <div className="two-x">
            <Figure letter="a" title="Outcomes">
              <OutcomeTable labelA={labelA} labelB={labelB} diff={diff} />
            </Figure>
            <Figure letter="b" title="Sign test" aside={`${changed} changed`}>
              <SignTestChart fixed={diff.fixed.length} broken={diff.broken.length} />
            </Figure>
          </div>
          <Figure letter="c" title="Per example" aside={String(exampleTotal(diff))}>
            <ExampleStrip diff={diff} />
          </Figure>
          <Figure
            letter="d"
            title={`${labelB} errors`}
            aside={errors.data ? `${errors.data.rows.length} of ${errors.data.total}` : undefined}
          >
            {errors.error ? (
              <ErrorBox error={errors.error} />
            ) : errors.data ? (
              <ErrorsTable
                rows={errors.data.rows}
                total={errors.data.total}
                labelA={labelA}
                labelB={labelB}
                brokenIds={new Set(diff.broken)}
                onMore={() => setLimit(limit + MORE)}
              />
            ) : (
              <Loading />
            )}
          </Figure>
        </>
      ) : !error && !noMetric ? (
        <Loading />
      ) : null}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/pages/Examples.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Show the page on `/x/$a/$b`**

In `ui/src/router.tsx` replace

```tsx
import { OverviewPage } from "./pages/Overview";
```

with

```tsx
import { ExamplesPage } from "./pages/Examples";
import { OverviewPage } from "./pages/Overview";
```

replace

```tsx
  return <RunPage runId={runId} log={log} example={example} />;
}
```

with

```tsx
  return <RunPage runId={runId} log={log} example={example} />;
}

/** `/x/$a/$b?metric=`: the Examples page. */
function ExamplesScreen(): ReactElement {
  const { a, b } = examplesRoute.useParams();
  const { metric } = examplesRoute.useSearch();
  return <ExamplesPage a={a} b={b} metric={metric} />;
}
```

and replace

```tsx
  validateSearch: (search: Record<string, unknown>): ExamplesSearch => ({ metric: str(search.metric) }),
  component: () => <ScreenPending name="Examples" />,
```

with

```tsx
  validateSearch: (search: Record<string, unknown>): ExamplesSearch => ({ metric: str(search.metric) }),
  component: ExamplesScreen,
```

Run: `cd ui && bun test && bun run typecheck`
Expected: every test passes, `0 fail` (the Part 4 files under `test/pages` included); `tsc` prints nothing.

- [ ] **Step 6: Look at the pages in the real app**

Run (from the repo root, one shell):

```bash
export HYPOTHEX_HOME="$(mktemp -d)"
uv run hx demo
(cd ui && bun run build)
uv run hx serve --port 7777
```

Open `http://127.0.0.1:7777/` and check, in light and dark mode:
- `/` shows a one-line headline, panels a–e, a failure with `Open stderr`; that link opens
  the run page with the stderr tail as panel a.
- A training task (`/t/<project>/<task>` from the projects table) shows view tabs with
  `overview preset` active and `+ view`; a run from it shows its kind panels before
  Where, Scores, Notes.
- An `agent_eval` run shows the traced-example picker with the failed example selected.
- On the generic demo task's leaderboard, the vs-best value of a non-best row opens
  `/x/<that row's run>/<best run>?metric=<primary>`; the page shows the 2×2 table, the sign
  test bars, and the per-example strip. On an `agent_eval` task the same link shows nonzero
  fixed/broken counts (the page sends `field=solved`).
- Rerun on a finished run opens the new run; Stop is disabled on finished runs.
- On the training task, against `docs/mockups/kinds/training/shot-task-light.png` and
  `-dark.png`: the leaderboard band is one continuous wash across rows, `×n` sits on one
  line next to the diamond, seeds are faint and the mean bold, the spike column shows the
  dashed line, glyph, and caret, the killed seed ends in a cross.

Expected: every item above holds; the browser console has no errors.

- [ ] **Step 7: Commit**

```bash
git add ui/src/pages/Examples.tsx ui/test/pages/Examples.test.tsx ui/src/router.tsx
git commit -m "feat(ui): examples page comparing two runs example by example"
```

## Part 5: View editor (Tasks 38–41)

The `/t/:project/:task/edit/:view` screen (spec 8.3 item 5): YAML on the left with inline validation (red marker, message, suggested fix), live preview on the right on a 12-column grid with a layout ruler, an insert-panel palette, Save (disabled while invalid), Discard, Copy as CLI. Visual reference: `docs/mockups/kinds/custom_view/index.html` (`#edit`) and `shot-edit-light.png` / `shot-edit-dark.png`. The mockup edits `hypothex.yaml`; spec 8.6 wins: the editor edits the view file form (`.hypothex/views/<task>/<name>.yaml`, the `text` of `GET views/{name}`).

The editor talks to the server only through Task 3 `api` and the Task 4 hooks (`useView`, `useLeaderboard`, `useViewQuery`, `useSaveView`); validation is a text-keyed query so an answer for old text never lands on new text. Preview panels draw through `PanelBody` (Task 25). Files: `ui/src/editor/` (`YamlEditor.tsx`, `PanelPalette.tsx`, `Preview.tsx`, `editor.css`, `hx-ed-` prefix) and `ui/src/pages/ViewEditor.tsx`.

### Task 38: YAML editor with validation markers

**Files:**
- Create: `ui/src/editor/YamlEditor.tsx`
- Test: `ui/test/editor/YamlEditor.test.tsx`
- Modify: `ui/package.json`, `ui/bun.lock` (CodeMirror packages)

**Interfaces:**
- Consumes: CodeMirror 6 packages (`@codemirror/state`, `@codemirror/view`, `@codemirror/commands`, `@codemirror/lang-yaml`, `@codemirror/lint`).
- Produces:
  - `type ValidationIssue` (the Task 3 model with `suggestion` optional: `{ line: number | null; path: string; message: string; suggestion?: string | null }`)
  - `interface Insertion { from: number; to: number; insert: string; line: number }`
  - `interface PanelOutline { index: number; title: string; startLine: number; endLine: number }`
  - `interface ViewOutline { panelsLine: number | null; emptyList: boolean; itemIndent: string; endLine: number; panels: PanelOutline[] }`
  - `outlineView(text: string): ViewOutline`, `panelAtLine(outline: ViewOutline, line: number): PanelOutline | null`
  - `issuesToDiagnostics(doc: Text, issues: ValidationIssue[]): Diagnostic[]`
  - `interface YamlEditorHandle { applyInsertion(plan: (text: string, cursorLine: number) => Insertion): void; goToLine(line: number): void; view(): EditorView | null }`
  - `YamlEditor(props: { value: string; onChange: (text: string) => void; issues: ValidationIssue[]; onCursorLine?: (line: number) => void; ref?: Ref<YamlEditorHandle> })`

Lines are 1-based everywhere, matching `ValidationIssue.line` from PyYAML marks (contract 1.4). The backend's issue messages have no quotes: `unknown metric route_length`, `unknown key metrcs`, `unknown type leaderbord`, `unknown field stauts in runs`, `unknown scale zzz; expected one of linear, log` (backend plan Task 16). The name after `unknown <word> ` is found in the line as a whole token and the mark is widened over the rest of the reference (`[\w@./-]*`, so `route_length@v1/median`, not only `route_length`). A metric `suggestion` is the whole corrected reference (`route_len@v1/median`), so the CodeMirror lint action named `use <suggestion>` replaces the whole marked reference, never only the name (which would give `route_len@v1/median@v1/median`). This is the mockup's "use route_len" (spec 8.3 item 5).

- [ ] **Step 1: Make sure the CodeMirror packages are installed**

Run: `cd ui && bun add @codemirror/state @codemirror/view @codemirror/commands @codemirror/language @codemirror/lang-yaml @codemirror/lint`
Expected: `installed @codemirror/...` lines; `git status --short` shows `ui/package.json` and `ui/bun.lock` changed.

- [ ] **Step 2: Write the failing test**

Create `ui/test/editor/YamlEditor.test.tsx`:

```tsx
import { afterEach, describe, expect, mock, test } from "bun:test";
import { diagnosticCount } from "@codemirror/lint";
import { EditorState, Text } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { act, cleanup, render } from "@testing-library/react";
import { createRef } from "react";
import {
  issuesToDiagnostics,
  outlineView,
  panelAtLine,
  type ValidationIssue,
  YamlEditor,
  type YamlEditorHandle,
} from "../../src/editor/YamlEditor";

afterEach(cleanup);

// Lines: 1 title, 2 runs, 3 panels:, 4-7 panel a, 8 blank, 9-15 panel b, 16 "" (final newline).
const SAMPLE = [
  "title: route quality",
  "runs: {status: finished}",
  "panels:",
  "  - type: stat_strip",
  "    title: Best config",
  "    data: {metrics: [solved], pick: best}",
  "    layout: {span: 12, row: 1}",
  "",
  "  - type: scatter",
  '    title: "Length vs time"  # c',
  "    data:",
  "      x: solve_time",
  "      y: route_length@v1/median",
  "      title: not the panel title",
  "    layout: {span: 5, row: 2}",
  "",
].join("\n");

// The exact message and suggestion the backend sends (backend plan Task 16): no quotes, and
// a metric suggestion is the whole corrected reference.
const BAD_METRIC: ValidationIssue = {
  line: 13,
  path: "panels[1].data.y",
  message: "unknown metric route_length",
  suggestion: "route_len@v1/median",
};

describe("outlineView", () => {
  test("finds the list, its indent, and each panel's lines and title", () => {
    expect(outlineView(SAMPLE)).toEqual({
      panelsLine: 3,
      emptyList: false,
      itemIndent: "  ",
      endLine: 17,
      panels: [
        { index: 0, title: "Best config", startLine: 4, endLine: 8 },
        { index: 1, title: "Length vs time", startLine: 9, endLine: 16 },
      ],
    });
  });

  test("stops the list at the next top-level key", () => {
    const text = "panels:\n  - type: markdown\n    text: hi\nruns: {status: finished}\n";
    const outline = outlineView(text);
    expect(outline.endLine).toBe(4);
    expect(outline.panels).toEqual([{ index: 0, title: "", startLine: 2, endLine: 3 }]);
  });

  test("handles zero-indent items, the empty flow list, and no list", () => {
    const flat = outlineView("title: t\npanels:\n- type: markdown\n  title: n\n");
    expect(flat.itemIndent).toBe("");
    expect(flat.panels).toEqual([{ index: 0, title: "n", startLine: 3, endLine: 5 }]);
    const empty = outlineView("title: t\nfrom: training\npanels: []\n");
    expect([empty.panelsLine, empty.emptyList, empty.panels]).toEqual([3, true, []]);
    expect(outlineView("title: t").panelsLine).toBeNull();
  });

  test("panelAtLine maps a cursor line to its panel", () => {
    const outline = outlineView(SAMPLE);
    expect(panelAtLine(outline, 2)).toBeNull();
    expect(panelAtLine(outline, 6)?.title).toBe("Best config");
    expect(panelAtLine(outline, 13)?.index).toBe(1);
  });
});

describe("issuesToDiagnostics", () => {
  const doc = Text.of(SAMPLE.split("\n"));

  test("marks the whole metric reference and the fix replaces all of it", () => {
    const [d] = issuesToDiagnostics(doc, [BAD_METRIC]);
    // "      y: route_length@v1/median": the reference starts at column 9, 22 characters long.
    expect(d.from - doc.line(13).from).toBe(9);
    expect(d.to - d.from).toBe(22);
    expect(d.severity).toBe("error");
    expect(d.message).toBe("unknown metric route_length (panels[1].data.y)");
    expect(d.actions?.map((a) => a.name)).toEqual(["use route_len@v1/median"]);
    const view = new EditorView({ state: EditorState.create({ doc: SAMPLE }) });
    d.actions?.[0]?.apply(view, d.from, d.to);
    expect(view.state.doc.line(13).text).toBe("      y: route_len@v1/median");
    view.destroy();
  });

  test("narrows the backend's unquoted key, type and scale names to their token", () => {
    const text = Text.of([
      "title: t",
      "runs: {stauts: finished}",
      "panels:",
      "  - type: leaderbord",
      "    scale: zzz",
      "    data: {source: runs, fields: [stauts]}",
    ]);
    const [key, type, scale, field] = issuesToDiagnostics(text, [
      { line: 2, path: "runs.stauts", message: "unknown key stauts", suggestion: "status" },
      { line: 4, path: "panels[0].type", message: "unknown type leaderbord", suggestion: "leaderboard" },
      { line: 5, path: "panels[0].scale", message: "unknown scale zzz; expected one of linear, log", suggestion: null },
      { line: 6, path: "panels[0].data.fields[0]", message: "unknown field stauts in runs", suggestion: "status" },
    ]);
    const marked = (d: typeof key) => text.sliceString(d.from, d.to);
    expect([marked(key), marked(type), marked(scale), marked(field)]).toEqual(["stauts", "leaderbord", "zzz", "stauts"]);
    expect(key.actions?.map((a) => a.name)).toEqual(["use status"]);
    expect(type.actions?.map((a) => a.name)).toEqual(["use leaderboard"]);
    expect(scale.actions).toBeUndefined();
  });

  test("marks the whole line without a token, line 1 without a line, the last line past the end", () => {
    const issues: ValidationIssue[] = [
      { line: 7, path: "panels[0].layout.span", message: "span must be 1..12" },
      { line: null, path: "", message: "title: field required" },
      { line: 99, path: "panels", message: "bad" },
    ];
    const [span, noLine, past] = issuesToDiagnostics(doc, issues);
    // "    layout: {span: 12, row: 1}": marked from the first non-space character.
    expect([span.from, span.to]).toEqual([doc.line(7).from + 4, doc.line(7).to]);
    expect(span.actions).toBeUndefined();
    expect([noLine.from, noLine.to, noLine.message]).toEqual([0, 20, "title: field required"]);
    expect([past.from, past.to]).toEqual([doc.length, doc.length]);
  });
});

describe("YamlEditor", () => {
  test("shows the text, marks issues, applies insertions, and follows value changes", () => {
    const ref = createRef<YamlEditorHandle>();
    const onChange = mock((_text: string) => {});
    const onCursorLine = mock((_line: number) => {});
    const { rerender } = render(
      <YamlEditor
        ref={ref}
        value={SAMPLE}
        onChange={onChange}
        issues={[BAD_METRIC]}
        onCursorLine={onCursorLine}
      />,
    );
    const view = ref.current?.view();
    expect(view?.state.doc.toString()).toBe(SAMPLE);
    expect(diagnosticCount(view!.state)).toBe(1);

    act(() => ref.current?.applyInsertion(() => ({ from: 0, to: 0, insert: "# hi\n", line: 1 })));
    expect(onChange).toHaveBeenLastCalledWith(`# hi\n${SAMPLE}`);
    expect(view?.state.selection.main.head).toBe(4);

    act(() => ref.current?.goToLine(10));
    expect(onCursorLine).toHaveBeenLastCalledWith(10);

    rerender(
      <YamlEditor ref={ref} value={"title: x\n"} onChange={onChange} issues={[]} onCursorLine={onCursorLine} />,
    );
    expect(view?.state.doc.toString()).toBe("title: x\n");
    expect(diagnosticCount(view!.state)).toBe(0);
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd ui && bun test test/editor/YamlEditor.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/editor/YamlEditor' from '.../ui/test/editor/YamlEditor.test.tsx'`.

- [ ] **Step 4: Write the implementation**

Create `ui/src/editor/YamlEditor.tsx`:

```tsx
import { defaultKeymap, history, historyKeymap, indentWithTab } from "@codemirror/commands";
import { yaml } from "@codemirror/lang-yaml";
import { type Diagnostic, lintGutter, setDiagnostics } from "@codemirror/lint";
import { EditorState, type Text } from "@codemirror/state";
import { EditorView, keymap, lineNumbers } from "@codemirror/view";
import { type Ref, useEffect, useImperativeHandle, useRef } from "react";
import type { ValidationIssue as ApiValidationIssue } from "../api/models";

/** One problem reported by `POST views/validate` (contract 1.4); `suggestion` may be left out. */
export type ValidationIssue = Omit<ApiValidationIssue, "suggestion"> & { suggestion?: string | null };

/** A text change planned against the editor text (character offsets, 1-based `line`). */
export interface Insertion {
  from: number;
  to: number;
  insert: string;
  /** Line (1-based, in the new text) to put the cursor on after the change. */
  line: number;
}

/** One `- type: ...` item of the view's `panels:` list. Lines are 1-based, inclusive. */
export interface PanelOutline {
  index: number;
  title: string;
  startLine: number;
  endLine: number;
}

/** Where the `panels:` list sits in a view's YAML text. */
export interface ViewOutline {
  /** Line of the top-level `panels:` key, or null when there is none. */
  panelsLine: number | null;
  /** True when the key is written as the flow form `panels: []`. */
  emptyList: boolean;
  /** Indent of the list's `- ` markers ("  " when the list has no items yet). */
  itemIndent: string;
  /** First line after the list (lines.length + 1 when the list runs to the end). */
  endLine: number;
  panels: PanelOutline[];
}

const PANELS_KEY = /^panels:\s*(\[\s*\])?\s*(#.*)?$/;

function indentOf(line: string): number {
  return line.length - line.trimStart().length;
}

function isContent(line: string): boolean {
  const t = line.trim();
  return t !== "" && !t.startsWith("#");
}

function cleanScalar(raw: string): string {
  const noComment = raw.replace(/\s+#.*$/, "").trim();
  const quoted = /^(["'])(.*)\1$/.exec(noComment);
  return quoted ? quoted[2] : noComment;
}

/**
 * Find the `panels:` list and its items in view YAML by indentation.
 *
 * The scan is textual, so it also works while the YAML is invalid. It only
 * understands the block form written by the editor and by `hx view init`.
 */
export function outlineView(text: string): ViewOutline {
  const lines = text.split("\n");
  const keyIdx = lines.findIndex((l) => PANELS_KEY.test(l));
  if (keyIdx === -1) {
    return { panelsLine: null, emptyList: false, itemIndent: "  ", endLine: lines.length + 1, panels: [] };
  }
  const emptyList = /\[\s*\]/.test(lines[keyIdx].replace(/#.*$/, ""));
  const first = lines.slice(keyIdx + 1).find(isContent);
  const firstItem = first !== undefined && /^\s*- /.test(first) ? first : undefined;
  const itemIndent = firstItem === undefined ? "  " : " ".repeat(indentOf(firstItem));
  let end = lines.length;
  for (let i = keyIdx + 1; i < lines.length; i++) {
    const l = lines[i];
    if (!isContent(l) || indentOf(l) > 0) continue;
    if (itemIndent === "" && l.startsWith("-")) continue;
    end = i;
    break;
  }
  const starts: number[] = [];
  if (!emptyList) {
    for (let i = keyIdx + 1; i < end; i++) {
      if (lines[i].startsWith(`${itemIndent}- `) || lines[i] === `${itemIndent}-`) starts.push(i);
    }
  }
  const keyIndent = itemIndent.length + 2;
  const panels = starts.map((s, index) => {
    const stop = index + 1 < starts.length ? starts[index + 1] : end;
    let title = "";
    for (let i = s; i < stop; i++) {
      const m = /^(\s*(?:-\s+)?)title:(.*)$/.exec(lines[i]);
      if (m && m[1].length === keyIndent) {
        title = cleanScalar(m[2]);
        break;
      }
    }
    return { index, title, startLine: s + 1, endLine: stop };
  });
  return { panelsLine: keyIdx + 1, emptyList, itemIndent, endLine: end + 1, panels };
}

/** Return the panel whose lines contain `line` (1-based), or null. */
export function panelAtLine(outline: ViewOutline, line: number): PanelOutline | null {
  return outline.panels.find((p) => line >= p.startLine && line <= p.endLine) ?? null;
}

/** The name in a backend message: `unknown metric route_length`, `unknown scale zzz; ...`. */
const UNKNOWN_NAME = /^unknown (?:metric|key|field|\w+) ([^\s;,]+)/;
/** Characters of a reference: `route_len@v1/median`, `usage.usd`, `macro-f1`. */
const REF_CHAR = /[\w@./-]/;
/** Characters that continue a name, so `x` is not found inside `xy`. */
const NAME_CHAR = /[\w-]/;

/**
 * Find `name` in `text` as a whole token and widen it over the rest of its reference
 * (`route_length` in `y: route_length@v1/median` covers `route_length@v1/median`).
 */
function findRef(text: string, name: string): { at: number; end: number } | null {
  for (let at = text.indexOf(name); at >= 0; at = text.indexOf(name, at + 1)) {
    if (at > 0 && REF_CHAR.test(text.charAt(at - 1))) continue;
    let end = at + name.length;
    if (end < text.length && NAME_CHAR.test(text.charAt(end))) continue;
    while (end < text.length && REF_CHAR.test(text.charAt(end))) end++;
    return { at, end };
  }
  return null;
}

/**
 * Turn validation issues into CodeMirror diagnostics.
 *
 * The name after `unknown <word> ` in the message (the backend sends it unquoted:
 * `unknown metric route_length`) narrows the mark to that reference in the line, widened
 * over its `@version/key` suffix, and a suggestion (for a metric, the whole corrected
 * reference) becomes a one-click "use X" fix that replaces the marked reference. Issues
 * without a line mark line 1; lines past the end mark the last line.
 */
export function issuesToDiagnostics(doc: Text, issues: ValidationIssue[]): Diagnostic[] {
  return issues.map((issue) => {
    const n = Math.min(Math.max(issue.line ?? 1, 1), doc.lines);
    const line = doc.line(n);
    const name = UNKNOWN_NAME.exec(issue.message)?.[1];
    const ref = name ? findRef(line.text, name) : null;
    const at = ref ? ref.at : -1;
    const lead = indentOf(line.text);
    const from = ref ? line.from + ref.at : line.from + lead;
    const to = ref ? line.from + ref.end : line.to;
    const suggestion = issue.suggestion ?? null;
    const diagnostic: Diagnostic = {
      from,
      to,
      severity: "error",
      message: issue.path ? `${issue.message} (${issue.path})` : issue.message,
    };
    if (suggestion && at >= 0) {
      diagnostic.actions = [
        {
          name: `use ${suggestion}`,
          apply: (view, a, b) => view.dispatch({ changes: { from: a, to: b, insert: suggestion } }),
        },
      ];
    }
    return diagnostic;
  });
}

/** Imperative handle: the palette and status bar drive the editor through it. */
export interface YamlEditorHandle {
  /** Apply a change planned from the current text and cursor line, then focus. */
  applyInsertion(plan: (text: string, cursorLine: number) => Insertion): void;
  /** Move the cursor to a 1-based line and scroll it into view. */
  goToLine(line: number): void;
  /** The live CodeMirror view (null before mount). */
  view(): EditorView | null;
}

export interface YamlEditorProps {
  value: string;
  onChange: (text: string) => void;
  issues: ValidationIssue[];
  onCursorLine?: (line: number) => void;
  ref?: Ref<YamlEditorHandle>;
}

const theme = EditorView.theme({
  "&": { backgroundColor: "var(--paper-2)", color: "var(--ink)", fontSize: "12px" },
  ".cm-content": { fontFamily: "var(--mono)", lineHeight: "20px" },
  ".cm-gutters": { backgroundColor: "var(--paper-2)", color: "var(--ink-3)", border: "none" },
  ".cm-lintRange-error": { textDecoration: "underline wavy var(--fail)" },
  "&.cm-focused": { outline: "none" },
});

/** CodeMirror 6 YAML editor with validation markers in the gutter and inline. */
export function YamlEditor({ value, onChange, issues, onCursorLine, ref }: YamlEditorProps) {
  const host = useRef<HTMLDivElement>(null);
  const viewRef = useRef<EditorView | null>(null);
  const onChangeRef = useRef(onChange);
  const onCursorRef = useRef(onCursorLine);
  onChangeRef.current = onChange;
  onCursorRef.current = onCursorLine;

  // Mount once; later `value` changes sync through the next effect.
  useEffect(() => {
    const view = new EditorView({
      parent: host.current as HTMLDivElement,
      state: EditorState.create({
        doc: value,
        extensions: [
          lineNumbers(),
          lintGutter(),
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
          yaml(),
          theme,
          EditorView.updateListener.of((u) => {
            if (u.docChanged) onChangeRef.current(u.state.doc.toString());
            if (u.docChanged || u.selectionSet) {
              const head = u.state.selection.main.head;
              onCursorRef.current?.(u.state.doc.lineAt(head).number);
            }
          }),
        ],
      }),
    });
    viewRef.current = view;
    return () => {
      view.destroy();
      viewRef.current = null;
    };
  }, []);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current !== value) {
      view.dispatch({ changes: { from: 0, to: current.length, insert: value } });
    }
  }, [value]);

  useEffect(() => {
    const view = viewRef.current;
    if (!view) return;
    view.dispatch(setDiagnostics(view.state, issuesToDiagnostics(view.state.doc, issues)));
  }, [issues]);

  useImperativeHandle(ref, () => ({
    applyInsertion(plan) {
      const view = viewRef.current;
      if (!view) return;
      const { state } = view;
      const cursorLine = state.doc.lineAt(state.selection.main.head).number;
      const change = plan(state.doc.toString(), cursorLine);
      view.dispatch({ changes: { from: change.from, to: change.to, insert: change.insert } });
      const target = view.state.doc.line(Math.min(change.line, view.state.doc.lines));
      view.dispatch({ selection: { anchor: target.to }, scrollIntoView: true });
      view.focus();
    },
    goToLine(line) {
      const view = viewRef.current;
      if (!view) return;
      const target = view.state.doc.line(Math.min(Math.max(line, 1), view.state.doc.lines));
      view.dispatch({ selection: { anchor: target.from }, scrollIntoView: true });
      view.focus();
    },
    view: () => viewRef.current,
  }));

  return <div className="hx-ed-cm" ref={host} data-testid="yaml-editor" />;
}
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd ui && bun test test/editor/YamlEditor.test.tsx`
Expected: `8 pass`, `0 fail`.

- [ ] **Step 6: Type-check**

Run: `cd ui && bunx tsc --noEmit -p .`
Expected: no output, exit 0.

- [ ] **Step 7: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add ui/src/editor/YamlEditor.tsx ui/test/editor/YamlEditor.test.tsx ui/package.json ui/bun.lock
git commit -m "feat(ui): CodeMirror YAML editor with validation markers"
```

### Task 39: Insert-panel palette

**Files:**
- Create: `ui/src/editor/PanelPalette.tsx`
- Test: `ui/test/editor/PanelPalette.test.tsx`

**Interfaces:**
- Consumes: `Insertion`, `outlineView`, `panelAtLine` from `ui/src/editor/YamlEditor.tsx` (Task 38).
- Produces:
  - `PanelType` (re-exported from the Task 3 models)
  - `PALETTE: readonly { type: PanelType; label: string; hint: string }[]` (10 entries, mockup order)
  - `panelSnippet(type: PanelType, metric: string): string[]` (lines relative to the list indent)
  - `planInsert(text: string, cursorLine: number, snippet: string[]): Insertion`
  - `PanelPalette(props: { onInsert: (type: PanelType) => void })`

Placement rule for "insert at the cursor": the snippet goes right after the panel that contains the cursor, so it never splits a panel's keys. With the cursor outside every panel it goes at the end of the `panels:` list (before the next top-level key). `panels: []` becomes a block list; a view with no `panels:` key gets one appended. The list's own indent is kept (two spaces or zero). Snippets use only contract `PanelSpec` fields, with the task's primary metric in the metric slots.

- [ ] **Step 1: Write the failing test**

Create `ui/test/editor/PanelPalette.test.tsx`:

```tsx
import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { PALETTE, PanelPalette, type PanelType, panelSnippet, planInsert } from "../../src/editor/PanelPalette";

afterEach(cleanup);

function apply(text: string, cursorLine: number, type: PanelType, metric = "acc") {
  const plan = planInsert(text, cursorLine, panelSnippet(type, metric));
  return { text: text.slice(0, plan.from) + plan.insert + text.slice(plan.to), line: plan.line };
}

const TWO = [
  "title: t",
  "panels:",
  "  - type: stat_strip",
  "    title: a",
  "  - type: markdown",
  "    title: b",
  "    text: hi",
  "",
].join("\n");

describe("panelSnippet", () => {
  test("fills metric slots and ends with a full-width layout", () => {
    expect(panelSnippet("scatter", "solved")).toEqual([
      "- type: scatter",
      "  title: New scatter",
      "  data: {x: solved, y: solved}",
      "  pareto: {x: min, y: max}",
      "  layout: {span: 12}",
    ]);
    expect(panelSnippet("markdown", "x")).toEqual([
      "- type: markdown",
      "  title: New markdown",
      "  text: |",
      "    Note.",
      "  layout: {span: 12}",
    ]);
  });

  test("has a snippet for every palette entry", () => {
    for (const p of PALETTE) expect(panelSnippet(p.type, "m")[0]).toBe(`- type: ${p.type}`);
  });
});

describe("planInsert", () => {
  test("goes after the panel under the cursor", () => {
    const out = apply(TWO, 4, "markdown");
    expect(out.text).toBe(
      [
        "title: t",
        "panels:",
        "  - type: stat_strip",
        "    title: a",
        "  - type: markdown",
        "    title: New markdown",
        "    text: |",
        "      Note.",
        "    layout: {span: 12}",
        "  - type: markdown",
        "    title: b",
        "    text: hi",
        "",
      ].join("\n"),
    );
    expect(out.line).toBe(5);
  });

  test("goes to the end of the list when the cursor is outside every panel", () => {
    const out = apply(TWO, 1, "grid");
    expect(out.text).toBe(
      `${TWO}  - type: grid\n    title: New grid\n    data: {metrics: [acc]}\n    layout: {span: 12}\n`,
    );
    expect(out.line).toBe(8);
  });

  test("stops before the next top-level key", () => {
    const text = "panels:\n  - type: markdown\n    text: hi\nruns: {status: finished}\n";
    const out = apply(text, 1, "trace");
    expect(out.text).toBe(
      "panels:\n  - type: markdown\n    text: hi\n" +
        "  - type: trace\n    title: New trace\n    data: {source: traces}\n    layout: {span: 12}\n" +
        "runs: {status: finished}\n",
    );
    expect(out.line).toBe(4);
  });

  test("turns `panels: []` into a block list", () => {
    const text = "title: t\nfrom: training\npanels: []\n";
    const plan = planInsert(text, 1, panelSnippet("leaderboard", "loss"));
    // "title: t\n" is 9 characters and "from: training\n" is 15, so the key starts at 24.
    expect([plan.from, plan.to, plan.line]).toEqual([24, 34, 4]);
    expect(apply(text, 1, "leaderboard", "loss").text).toBe(
      "title: t\nfrom: training\npanels:\n  - type: leaderboard\n    title: New leaderboard\n" +
        "    data: {metrics: [loss]}\n    noise: [seed, test_set]\n    layout: {span: 12}\n",
    );
  });

  test("adds a `panels:` key when there is none, fixing a missing final newline", () => {
    const out = apply("title: t", 1, "stat_strip");
    expect(out.text).toBe(
      "title: t\npanels:\n  - type: stat_strip\n    title: New stat strip\n" +
        "    data: {metrics: [acc], pick: best}\n    layout: {span: 12}\n",
    );
    expect(out.line).toBe(3);
  });

  test("keeps a zero-indent list at zero indent", () => {
    const out = apply("panels:\n- type: markdown\n  text: hi\n", 2, "trace");
    expect(out.text).toBe(
      "panels:\n- type: markdown\n  text: hi\n- type: trace\n  title: New trace\n" +
        "  data: {source: traces}\n  layout: {span: 12}\n",
    );
    expect(out.line).toBe(4);
  });
});

describe("PanelPalette", () => {
  test("shows one button per type and reports the clicked type", () => {
    const onInsert = mock((_t: PanelType) => {});
    render(<PanelPalette onInsert={onInsert} />);
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((b) => b.textContent)).toEqual([
      "stat strip",
      "leaderboard",
      "curves",
      "scatter",
      "distribution",
      "grid",
      "table",
      "trace",
      "markdown",
      "vega-lite",
    ]);
    const vega = screen.getByRole("button", { name: "vega-lite" });
    expect(vega.getAttribute("title")).toBe("vega-lite: any Vega-Lite spec over a source");
    fireEvent.click(vega);
    expect(onInsert).toHaveBeenCalledWith("vega_lite");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/editor/PanelPalette.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/editor/PanelPalette' from '.../ui/test/editor/PanelPalette.test.tsx'`.

- [ ] **Step 3: Write the implementation**

Create `ui/src/editor/PanelPalette.tsx`:

```tsx
import type { PanelType } from "../api/models";
import { type Insertion, outlineView, panelAtLine } from "./YamlEditor";

/** Panel types a view may use (contract 1.4 `PanelType`, from the API models). */
export type { PanelType };

export interface PaletteEntry {
  type: PanelType;
  label: string;
  hint: string;
}

/** Palette buttons, in the mockup's order. `hint` is the button tooltip. */
export const PALETTE: readonly PaletteEntry[] = [
  { type: "stat_strip", label: "stat strip", hint: "a row of headline numbers" },
  { type: "leaderboard", label: "leaderboard", hint: "seed groups ranked, seed and test-set noise" },
  { type: "curves", label: "curves", hint: "metric by step, one line per run" },
  { type: "scatter", label: "scatter", hint: "two metrics per group, optional Pareto front" },
  { type: "distribution", label: "distribution", hint: "ECDF with p50, p95, p99" },
  { type: "grid", label: "grid", hint: "items by groups, fraction of seeds solved" },
  { type: "table", label: "table", hint: "rows from a source, chosen fields" },
  { type: "trace", label: "trace", hint: "one agent attempt, turn by turn" },
  { type: "markdown", label: "markdown", hint: "a note" },
  { type: "vega_lite", label: "vega-lite", hint: "any Vega-Lite spec over a source" },
];

/**
 * YAML lines for a new panel, relative to the list indent.
 *
 * `metric` fills metric slots (the task's primary metric name); the user edits
 * the rest. Every field is a contract `PanelSpec` field, so the snippet
 * validates whenever `metric` is known.
 */
export function panelSnippet(type: PanelType, metric: string): string[] {
  const label = PALETTE.find((p) => p.type === type)?.label ?? type;
  const body: Record<PanelType, string[]> = {
    stat_strip: [`  data: {metrics: [${metric}], pick: best}`],
    leaderboard: [`  data: {metrics: [${metric}]}`, "  noise: [seed, test_set]"],
    curves: [`  data: {metrics: [${metric}]}`],
    scatter: [`  data: {x: ${metric}, y: ${metric}}`, "  pareto: {x: min, y: max}"],
    distribution: [`  data: {metrics: [${metric}]}`, "  scale: linear"],
    grid: [`  data: {metrics: [${metric}]}`],
    table: ["  data: {source: runs, fields: [run_id, status, created_by]}"],
    trace: ["  data: {source: traces}"],
    markdown: ["  text: |", "    Note."],
    vega_lite: [
      "  data: {source: runs, fields: [status]}",
      "  spec:",
      "    mark: bar",
      "    encoding:",
      "      x: {field: status, type: nominal}",
      "      y: {aggregate: count, type: quantitative}",
    ],
  };
  return [`- type: ${type}`, `  title: New ${label}`, ...body[type], "  layout: {span: 12}"];
}

/**
 * Plan where a snippet goes: after the panel under the cursor.
 *
 * With the cursor outside every panel the snippet goes at the end of the
 * `panels:` list. `panels: []` becomes a block list; a view with no `panels:`
 * key gets one at the end.
 */
export function planInsert(text: string, cursorLine: number, snippet: string[]): Insertion {
  const outline = outlineView(text);
  const lines = text.split("\n");
  const startOf = (line: number) => lines.slice(0, line - 1).reduce((n, l) => n + l.length + 1, 0);
  const indent = outline.itemIndent;
  const block = snippet.map((l) => indent + l).join("\n");
  const tail = text === "" || text.endsWith("\n") ? "" : "\n";
  let from: number;
  let to: number;
  let insert: string;
  if (outline.panelsLine === null) {
    from = to = text.length;
    insert = `${tail}panels:\n${block}\n`;
  } else if (outline.emptyList) {
    from = startOf(outline.panelsLine);
    to = from + lines[outline.panelsLine - 1].length;
    insert = `panels:\n${block}`;
  } else {
    const inside = panelAtLine(outline, cursorLine);
    const target = inside ? inside.endLine + 1 : outline.endLine;
    if (target > lines.length) {
      from = to = text.length;
      insert = `${tail}${block}\n`;
    } else {
      from = to = startOf(target);
      insert = `${block}\n`;
    }
  }
  const next = text.slice(0, from) + insert + text.slice(to);
  const itemAt = from + insert.indexOf(`${indent}- type:`);
  return { from, to, insert, line: next.slice(0, itemAt).split("\n").length };
}

export interface PanelPaletteProps {
  onInsert: (type: PanelType) => void;
}

/** "Insert" row: one button per panel type. */
export function PanelPalette({ onInsert }: PanelPaletteProps) {
  return (
    <div className="hx-ed-ins">
      <span>Insert</span>
      <div className="hx-ed-lib">
        {PALETTE.map((p) => (
          <button key={p.type} type="button" title={`${p.label}: ${p.hint}`} onClick={() => onInsert(p.type)}>
            {p.label}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ui && bun test test/editor/PanelPalette.test.tsx`
Expected: `9 pass`, `0 fail`.

- [ ] **Step 5: Type-check**

Run: `cd ui && bunx tsc --noEmit -p .`
Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add ui/src/editor/PanelPalette.tsx ui/test/editor/PanelPalette.test.tsx
git commit -m "feat(ui): insert-panel palette with per-type snippets"
```

### Task 40: Preview grid and 12-column ruler

**Files:**
- Create: `ui/src/editor/Preview.tsx`
- Test: `ui/test/editor/Preview.test.tsx`

**Interfaces:**
- Consumes: `PanelResult` (Task 3); `panelLetter` (Task 24); `clampSpan` (Task 25). Panel bodies come through the `renderPanel` prop.
- Produces:
  - `PanelResult` (re-exported from the Task 3 models)
  - `interface LayoutHint { span?: number; row?: number | null }`
  - `interface Placement { col: number; span: number; row: number; overflow: boolean }`
  - `placePanels(layouts: LayoutHint[]): Placement[]`
  - `panelLetter` (re-exported from Task 24)
  - `LayoutRuler(props: { placement: Placement | null; label: string })`
  - `Preview(props: { results: PanelResult[]; layouts: LayoutHint[]; selected: number | null; problems: Record<number, string>; stale: boolean; renderPanel: (r: PanelResult) => ReactNode; onSelect?: (index: number) => void })`

`placePanels` follows CSS grid's sparse auto-placement (rows first for panels with `row`, then a forward-only cursor for the rest), and the preview sets `grid-column: <col> / span <span>` and `grid-row` from it, so the ruler and the drawn grid can never disagree. The ruler label is the mockup's `c: span 5, row 2`.

- [ ] **Step 1: Write the failing test**

Create `ui/test/editor/Preview.test.tsx`:

```tsx
import { afterEach, describe, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { LayoutRuler, type PanelResult, Preview, panelLetter, placePanels } from "../../src/editor/Preview";

afterEach(cleanup);

describe("placePanels", () => {
  test("places explicit rows left to right (the custom_view mockup layout)", () => {
    const got = placePanels([
      { span: 12, row: 1 },
      { span: 7, row: 2 },
      { span: 5, row: 2 },
      { span: 8, row: 3 },
      { span: 4, row: 3 },
    ]);
    expect(got).toEqual([
      { col: 1, span: 12, row: 1, overflow: false },
      { col: 1, span: 7, row: 2, overflow: false },
      { col: 8, span: 5, row: 2, overflow: false },
      { col: 1, span: 8, row: 3, overflow: false },
      { col: 9, span: 4, row: 3, overflow: false },
    ]);
  });

  test("flows panels without a row and wraps when a row is full", () => {
    expect(placePanels([{ span: 6 }, { span: 6 }, {}, { span: 4 }])).toEqual([
      { col: 1, span: 6, row: 1, overflow: false },
      { col: 7, span: 6, row: 1, overflow: false },
      { col: 1, span: 12, row: 2, overflow: false },
      { col: 1, span: 4, row: 3, overflow: false },
    ]);
  });

  test("flows around explicit rows and never moves back (CSS sparse placement)", () => {
    expect(placePanels([{ span: 6, row: 1 }, { span: 6 }])[1]).toEqual({
      col: 7,
      span: 6,
      row: 1,
      overflow: false,
    });
    // The 8-wide panel cannot fit beside row 1's 6; the next 6-wide one cannot fit in
    // row 2's 4 free columns and does not go back to row 1.
    expect(placePanels([{ span: 6, row: 1 }, { span: 8 }, { span: 6 }]).slice(1)).toEqual([
      { col: 1, span: 8, row: 2, overflow: false },
      { col: 1, span: 6, row: 3, overflow: false },
    ]);
  });

  test("flags a row wider than 12 columns and clamps spans to 1..12", () => {
    expect(placePanels([{ span: 7, row: 2 }, { span: 7, row: 2 }])[1]).toEqual({
      col: 6,
      span: 7,
      row: 2,
      overflow: true,
    });
    expect(placePanels([{ span: 20 }, { span: 0, row: 3 }]).map((p) => p.span)).toEqual([12, 1]);
  });
});

test("panelLetter counts a, b, c", () => {
  expect([0, 1, 2, 25].map(panelLetter)).toEqual(["a", "b", "c", "z"]);
});

describe("LayoutRuler", () => {
  test("lights the selected panel's columns", () => {
    const { container } = render(
      <LayoutRuler placement={{ col: 8, span: 5, row: 2, overflow: false }} label="c: span 5, row 2" />,
    );
    const lit = [...container.querySelectorAll(".hx-ed-ruler span.on")].map((s) => s.textContent);
    expect(lit).toEqual(["8", "9", "10", "11", "12"]);
    expect(screen.getByTestId("ruler-label").textContent).toBe("c: span 5, row 2");
  });

  test("lights nothing without a selection", () => {
    const { container } = render(<LayoutRuler placement={null} label="" />);
    expect(container.querySelectorAll(".hx-ed-ruler span").length).toBe(12);
    expect(container.querySelectorAll(".hx-ed-ruler span.on").length).toBe(0);
  });
});

const RESULTS: PanelResult[] = [
  { type: "stat_strip", title: "Best config", rows: [], meta: {} },
  { type: "scatter", title: "Length vs time", rows: [], meta: {} },
  { type: "markdown", title: "Note", rows: [], meta: { text: "hi" } },
];
const LAYOUTS = [{ span: 12, row: 1 }, { span: 5, row: 2 }, { span: 7, row: 2 }];

describe("Preview", () => {
  test("draws lettered panels at their grid cells through renderPanel", () => {
    const onSelect = mock((_i: number) => {});
    render(
      <Preview
        results={RESULTS}
        layouts={LAYOUTS}
        selected={2}
        problems={{}}
        stale={false}
        renderPanel={(r) => <p>{`${r.type} body`}</p>}
        onSelect={onSelect}
      />,
    );
    const note = screen.getByRole("region", { name: "Note" });
    expect(note.className).toBe("hx-ed-pp sel");
    expect(note.style.gridColumn).toBe("6 / span 7");
    expect(note.style.gridRow).toBe("2");
    expect(note.textContent).toBe("cNote7/12markdown body");
    expect(screen.getByTestId("ruler-label").textContent).toBe("c: span 7, row 2");
    fireEvent.click(screen.getByRole("region", { name: "Best config" }));
    expect(onSelect).toHaveBeenCalledWith(0);
  });

  test("replaces a panel with its validation problem and marks a stale preview", () => {
    const { container } = render(
      <Preview
        results={RESULTS}
        layouts={LAYOUTS}
        selected={null}
        problems={{ 1: "unknown metric route_length, ln 13" }}
        stale
        renderPanel={(r) => <p>{`${r.type} body`}</p>}
      />,
    );
    const bad = screen.getByRole("region", { name: "Length vs time" });
    expect(bad.className).toBe("hx-ed-pp bad");
    expect(bad.textContent).toContain("✕ unknown metric route_length, ln 13");
    expect(bad.textContent).not.toContain("scatter body");
    expect((container.firstChild as HTMLElement).className).toBe("hx-ed-pv stale");
    expect(screen.getByTestId("ruler-label").textContent).toBe("");
  });

  test("says so when the view has no panels", () => {
    render(<Preview results={[]} layouts={[]} selected={null} problems={{}} stale={false} renderPanel={() => null} />);
    expect(screen.getByText("No panels")).toBeDefined();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/editor/Preview.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/editor/Preview' from '.../ui/test/editor/Preview.test.tsx'`.

- [ ] **Step 3: Write the implementation**

Create `ui/src/editor/Preview.tsx`:

```tsx
import type { ReactNode } from "react";
import type { PanelResult } from "../api/models";
import { panelLetter } from "../pages/components/Figure";
import { clampSpan } from "../pages/components/PanelGrid";

/** One computed panel from `POST views/query` (contract 1.6), and the journal-style letter. */
export type { PanelResult };
export { panelLetter };

/** A panel's `layout:` block; missing values take the contract defaults. */
export interface LayoutHint {
  span?: number;
  row?: number | null;
}

/** Where a panel lands on the 12-column grid. `col` and `row` are 1-based. */
export interface Placement {
  col: number;
  span: number;
  row: number;
  /** True when an explicit row has no room left; the panel is drawn over its neighbours. */
  overflow: boolean;
}

const COLUMNS = 12;

/**
 * Place panels on the 12-column grid the way CSS grid's sparse auto-placement does.
 *
 * Panels with a `row` go first, left to right in that row. Panels without one then
 * flow from row 1 column 1, never moving back. The preview draws panels at these
 * exact cells, so the ruler and the preview always agree.
 */
export function placePanels(layouts: LayoutHint[]): Placement[] {
  const used = new Map<number, boolean[]>();
  const cells = (row: number): boolean[] => {
    let r = used.get(row);
    if (!r) {
      r = new Array<boolean>(COLUMNS).fill(false);
      used.set(row, r);
    }
    return r;
  };
  const fits = (row: number, col: number, span: number) =>
    col + span <= COLUMNS && cells(row).slice(col, col + span).every((c) => !c);
  const take = (row: number, col: number, span: number) => {
    const r = cells(row);
    for (let c = col; c < col + span; c++) r[c] = true;
  };
  const out = new Array<Placement>(layouts.length);
  const rowCursor = new Map<number, number>();
  layouts.forEach((l, i) => {
    if (l.row == null) return;
    const span = clampSpan(l.span);
    const row = Math.max(1, Math.floor(l.row));
    let col = rowCursor.get(row) ?? 0;
    while (col + span <= COLUMNS && !fits(row, col, span)) col++;
    const overflow = col + span > COLUMNS;
    if (overflow) col = COLUMNS - span;
    else take(row, col, span);
    rowCursor.set(row, col + span);
    out[i] = { col: col + 1, span, row, overflow };
  });
  let row = 1;
  let col = 0;
  layouts.forEach((l, i) => {
    if (l.row != null) return;
    const span = clampSpan(l.span);
    while (!fits(row, col, span)) {
      col++;
      if (col + span > COLUMNS) {
        row++;
        col = 0;
      }
    }
    take(row, col, span);
    out[i] = { col: col + 1, span, row, overflow: false };
    col += span;
  });
  return out;
}

export interface LayoutRulerProps {
  placement: Placement | null;
  label: string;
}

/** Twelve column ticks; the selected panel's columns are lit. */
export function LayoutRuler({ placement, label }: LayoutRulerProps) {
  const on = (c: number) => placement !== null && c >= placement.col && c < placement.col + placement.span;
  return (
    <div className="hx-ed-ruler-wrap">
      <div className="hx-ed-pv-h">
        <span className="t">Preview</span>
        <span className="aside" data-testid="ruler-label">
          {label}
        </span>
      </div>
      <div className="hx-ed-ruler" aria-hidden="true">
        {Array.from({ length: COLUMNS }, (_, i) => i + 1).map((c) => (
          <span key={c} className={on(c) ? "on" : undefined}>
            <b>{c}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

export interface PreviewProps {
  results: PanelResult[];
  layouts: LayoutHint[];
  selected: number | null;
  /** Result index -> validation message shown in place of that panel. */
  problems: Record<number, string>;
  /** True while the YAML is invalid and the preview shows the last valid view. */
  stale: boolean;
  renderPanel: (result: PanelResult) => ReactNode;
  onSelect?: (index: number) => void;
}

/** Live preview of the unsaved view on the 12-column grid. */
export function Preview({ results, layouts, selected, problems, stale, renderPanel, onSelect }: PreviewProps) {
  const places = placePanels(results.map((_, i) => layouts[i] ?? {}));
  const sel = selected !== null && selected < results.length ? selected : null;
  const label = sel === null ? "" : `${panelLetter(sel)}: span ${places[sel].span}, row ${places[sel].row}`;
  return (
    <div className={stale ? "hx-ed-pv stale" : "hx-ed-pv"} title={stale ? "Last valid view" : undefined}>
      <LayoutRuler placement={sel === null ? null : places[sel]} label={label} />
      {results.length === 0 ? (
        <p className="hx-ed-empty">No panels</p>
      ) : (
        <div className="hx-ed-pgrid">
          {results.map((r, i) => {
            const p = places[i];
            const problem = problems[i];
            const cls = ["hx-ed-pp", problem ? "bad" : i === sel ? "sel" : "", p.overflow ? "over" : ""];
            return (
              <section
                key={i}
                aria-label={r.title}
                className={cls.filter(Boolean).join(" ")}
                style={{ gridColumn: `${p.col} / span ${p.span}`, gridRow: `${p.row}` }}
                onClick={() => onSelect?.(i)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") onSelect?.(i);
                }}
                tabIndex={0}
              >
                <div className="hx-ed-fig-h">
                  <span className="pl">{panelLetter(i)}</span>
                  <span className="t">{r.title}</span>
                  <span className="aside" title={`span ${p.span} of 12, row ${p.row}`}>
                    {p.overflow ? "over 12 columns" : `${p.span}/12`}
                  </span>
                </div>
                {problem ? <div className="hx-ed-perr">✕ {problem}</div> : renderPanel(r)}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd ui && bun test test/editor/Preview.test.tsx`
Expected: `10 pass`, `0 fail`.

- [ ] **Step 5: Type-check**

Run: `cd ui && bunx tsc --noEmit -p .`
Expected: no output, exit 0.

- [ ] **Step 6: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add ui/src/editor/Preview.tsx ui/test/editor/Preview.test.tsx
git commit -m "feat(ui): view preview grid with 12-column layout ruler"
```

### Task 41: View editor page (validate, preview, Save, Discard, Copy as CLI)

**Files:**
- Create: `ui/src/pages/ViewEditor.tsx`
- Create: `ui/src/editor/editor.css`
- Modify: `ui/src/router.tsx` (the editor route renders `ViewEditor`), `ui/test/router.test.tsx` (append a test)
- Test: `ui/test/pages/ViewEditor.test.tsx`

**Interfaces:**
- Consumes: Task 38 `YamlEditor`, `YamlEditorHandle`, `ValidationIssue`, `outlineView`, `panelAtLine`; Task 39 `PanelPalette`, `PanelType`, `panelSnippet`, `planInsert`; Task 40 `Preview`, `PanelResult`, `LayoutHint`; Task 3 `api`, `ApiError`, `ViewSpec`; Task 4 `useView`, `useLeaderboard`, `useViewQuery`, `useSaveView`; Task 25 `PanelBody`. HTTP: `GET .../views/{name}` → `{info, text, view}`; `POST .../views/validate` `{text}` → `{ok, issues, view?}`; `POST .../views/query` `{view}` → `{panels}`; `PUT .../views/{name}` `{text, command_id}` → `{info, view}` or 400 `{error, type, issues}`; `GET .../leaderboard` → `Leaderboard` with `primary`.
- Produces:
  - `ViewEditor(props: { project: string; task: string; view: string; onSaved?: (name: string) => void; renderPanel?: (result: PanelResult) => ReactNode })` (named and default export). `view` is the `:view` route param (`new` for a new view); `renderPanel` defaults to `PanelBody`.
  - In `ui/src/router.tsx`: `ViewEditorScreen`, which passes `onSaved={(name) => navigate({ to: "/t/$project/$task", params: { project, task }, search: { view: name } })}`.
  - `NEW_VIEW_TEXT = "title: new view\npanels: []\n"`
  - `isViewName(name: string): boolean` (`^[a-z0-9][a-z0-9_-]*$`, not `overview`)
  - `metricOf(primary: string): string` (`"accuracy/value"` → `"accuracy"`)
  - `cliCommand(project: string, task: string, name: string, text: string): string`
  - `resolvePanels(view: ViewSpec, preset: ViewSpec | null): PanelSpec[]` (the panels of `view` after `from:`, the same merge as the server's `resolve_view`: preset panels first, a view panel whose non-empty title equals a preset panel's replaces it in place, every other view panel is appended; `view.panels` unchanged when there is no `from` or no preset)

Behaviour:
- Validation: the text is debounced 300 ms, then `POST views/validate`. The TanStack Query key includes the text, so an answer for old text never lands on new text, and undo back to a checked text needs no request.
- Preview: whenever validation returns `ok` with a `view`, `POST views/query {view}` runs with that unsaved view; the last good preview stays on screen (dimmed, `stale`) while the YAML is invalid. Validation issues inside a panel replace that panel's body with the message (matched by the panel's title, which is also how `resolve_view` matches panels).
- `from:` views: `POST views/validate` returns the view as written (not resolved), while `POST views/query` resolves `from:`, so inherited preset panels have no layout in `good.panels`. The editor loads the preset with `useView(project, task, "overview")` (the task kind's preset, resolved, with layouts) when `good.from` is set, and `resolvePanels(good, preset)` gives the full panel list. Preview layouts and the `✓ valid · N panels` count come from that list. The preset is used only when its `info.kind` equals `good.from`; for a `from:` of another kind (no route serves that preset) the count falls back to the preview's result count and inherited panels use the default full-width layout.
- Cursor → selection: the panel under the cursor is lit in the preview and its columns on the ruler; clicking a preview panel moves the cursor to its `- type:` line.
- Save: `useSaveView` sends `PUT views/{name}` with `{text, command_id}` (a fresh UUID per click). Disabled while checking, while invalid (tooltip `Fix N error(s) to save`), when nothing changed, or when the name is bad. For `new` and `overview` a Name box appears (`overview` is reserved). On success: the text becomes the new baseline, the task's view list, view document and panel queries refresh (so the new tab shows), `onSaved(name)` runs. On 400 the server's `issues` replace the markers and the error shows in an alert.
- Discard: back to the loaded text (or `NEW_VIEW_TEXT`).
- Copy as CLI: `hx view add` reads `--file` (it does not read stdin), so the copied text writes the YAML with a quoted heredoc, then adds it:
  ```
  cat > /tmp/hx-view-<name>.yaml <<'YAML'
  <text>
  YAML
  hx view add <task> --file /tmp/hx-view-<name>.yaml --name <name> -p <project>
  ```
  The heredoc tag grows (`YAML_`, `YAML__`) if a line of the text is exactly `YAML`.

- [ ] **Step 1: Write the failing test**

Create `ui/test/pages/ViewEditor.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, mock, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { outlineView } from "../../src/editor/YamlEditor";
import type { ViewSpec } from "../../src/api/models";
import {
  cliCommand,
  isViewName,
  metricOf,
  NEW_VIEW_TEXT,
  resolvePanels,
  ViewEditor,
} from "../../src/pages/ViewEditor";

const VIEWS = "/api/v1/tasks/toy/toy-acc/views";
const GOOD = "title: acc only\npanels:\n  - type: leaderboard\n    title: board\n    data: {metrics: [accuracy]}\n";
// Same view with the metric one letter off, on line 5, as in the backend API tests; the
// message is the backend's exact, unquoted text.
const BAD = GOOD.replace("[accuracy]", "[acuracy]");
const BAD_ISSUE = {
  line: 5,
  path: "panels[0].data.metrics[0]",
  message: "unknown metric acuracy",
  suggestion: "accuracy",
};
// A view that inherits the generic preset and adds one narrow panel.
const FROM_TEXT = "title: with preset\nfrom: generic\npanels:\n  - type: markdown\n    title: Note\n    text: hi\n    layout: {span: 4}\n";
// What `GET views/overview` serves for a generic task: the preset, resolved, with layouts.
const PRESET: ViewSpec = {
  title: "Overview",
  panels: [
    { type: "stat_strip", title: "Summary", layout: { span: 12, row: null } },
    { type: "leaderboard", title: "Leaderboard", layout: { span: 8, row: null } },
  ],
};

interface Call {
  method: string;
  url: string;
  body: Record<string, unknown> | null;
}

let calls: Call[] = [];
let docText = GOOD;
let putStatus = 200;
const realFetch = globalThis.fetch;

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

/** A fake view server: validation fails on "acuracy"; panels come from the YAML outline. */
function fakeServer(url: string, method: string, body: Record<string, unknown> | null): Response {
  if (url.endsWith("/leaderboard")) return json(200, { primary: "accuracy/value" });
  if (url === `${VIEWS}/validate`) {
    const text = String(body?.text);
    if (text.includes("acuracy")) return json(200, { ok: false, issues: [BAD_ISSUE] });
    if (text === FROM_TEXT) {
      // validate returns the view as written: `from` kept, preset panels not expanded
      return json(200, {
        ok: true,
        issues: [],
        view: {
          title: "with preset",
          from: "generic",
          panels: [{ type: "markdown", title: "Note", text: "hi", layout: { span: 4, row: null } }],
        },
      });
    }
    const panels = outlineView(text).panels.map((p) => ({
      type: "leaderboard",
      title: p.title,
      layout: { span: 12, row: null },
    }));
    return json(200, { ok: true, issues: [], view: { title: text.split("\n")[0].slice(7), panels } });
  }
  if (url === `${VIEWS}/query`) {
    // like the server, query resolves `from:` (the preset panels come first)
    const view = body?.view as { from?: string; panels: { type: string; title: string }[] };
    const panels = view.from === "generic" ? [...(PRESET.panels ?? []), ...view.panels] : view.panels;
    return json(200, {
      panels: panels.map((p) => ({ type: p.type, title: p.title ?? "", rows: [], meta: {} })),
    });
  }
  if (method === "GET" && url === `${VIEWS}/overview` && docText === FROM_TEXT) {
    return json(200, {
      info: { name: "overview", title: "Overview", origin: "preset", path: null, kind: "generic" },
      text: "title: Overview\n",
      view: PRESET,
    });
  }
  if (method === "GET" && (url === `${VIEWS}/acc` || url === `${VIEWS}/overview`)) {
    return json(200, {
      info: { name: "acc", title: "acc only", origin: "file", path: "/r/acc.yaml", kind: "generic" },
      text: docText,
      view: {},
    });
  }
  if (method === "PUT") {
    if (putStatus !== 200) {
      return json(putStatus, { error: "view 'acc' is invalid", type: "ViewValidationError", issues: [BAD_ISSUE] });
    }
    return json(200, { info: {}, view: {} });
  }
  return json(404, { error: "not found", type: "StoreError" });
}

beforeEach(() => {
  calls = [];
  docText = GOOD;
  putStatus = 200;
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : null;
    calls.push({ method, url, body });
    return fakeServer(url, method, body);
  }) as unknown as typeof fetch;
});

afterEach(() => {
  cleanup();
  globalThis.fetch = realFetch;
});

function renderEditor(view: string, onSaved = mock((_name: string) => {})) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ViewEditor
        project="toy"
        task="toy-acc"
        view={view}
        onSaved={onSaved}
        renderPanel={(r) => <p>{`${r.type} body`}</p>}
      />
    </QueryClientProvider>,
  );
  return onSaved;
}

const validateCalls = () => calls.filter((c) => c.url === `${VIEWS}/validate`);
const status = () => screen.getByTestId("ed-status").textContent ?? "";
const button = (name: string) => screen.getByRole("button", { name }) as HTMLButtonElement;

describe("helpers", () => {
  test("cliCommand writes a heredoc file and adds it", () => {
    expect(cliCommand("toy", "toy-acc", "acc", "title: a\npanels: []")).toBe(
      "cat > /tmp/hx-view-acc.yaml <<'YAML'\ntitle: a\npanels: []\nYAML\n" +
        "hx view add toy-acc --file /tmp/hx-view-acc.yaml --name acc -p toy",
    );
  });

  test("cliCommand picks a heredoc tag that is not a line of the text", () => {
    const out = cliCommand("p", "t", "v", "text: |\n  YAML\nYAML\n");
    expect(out.split("\n")[0]).toBe("cat > /tmp/hx-view-v.yaml <<'YAML_'");
    expect(out.split("\n")[4]).toBe("YAML_");
  });

  test("isViewName and metricOf", () => {
    expect(["acc", "route_quality", "a-1"].map(isViewName)).toEqual([true, true, true]);
    expect(["", "overview", "Bad", "-x", "a b"].map(isViewName)).toEqual([false, false, false, false, false]);
    expect([metricOf("accuracy/value"), metricOf("solved@v2/value"), metricOf("")]).toEqual([
      "accuracy",
      "solved@v2",
      "metric",
    ]);
  });

  test("resolvePanels applies from: like the server's resolve_view", () => {
    const view: ViewSpec = {
      title: "v",
      from: "generic",
      panels: [
        { type: "leaderboard", title: "Leaderboard", layout: { span: 6 } },
        { type: "markdown", title: "Note" },
      ],
    };
    expect(resolvePanels(view, PRESET).map((p) => [p.type, p.title, p.layout?.span])).toEqual([
      ["stat_strip", "Summary", 12],
      ["leaderboard", "Leaderboard", 6],
      ["markdown", "Note", undefined],
    ]);
    expect(resolvePanels(view, null)).toBe(view.panels ?? []);
    const plain: ViewSpec = { title: "p", panels: [{ type: "markdown", title: "Note" }] };
    expect(resolvePanels(plain, PRESET)).toEqual([{ type: "markdown", title: "Note" }]);
    expect(resolvePanels({ title: "empty" }, null)).toEqual([]);
  });
});

describe("ViewEditor", () => {
  test("loads the view, validates it once, previews it, and selects panels", async () => {
    renderEditor("acc");
    await waitFor(() => expect(status()).toContain("✓ valid · 1 panel"));
    expect(validateCalls().map((c) => c.body?.text)).toEqual([GOOD]);
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Edit acc only");
    const board = await screen.findByRole("region", { name: "board" });
    expect(board.textContent).toContain("leaderboard body");
    expect(button("Save").disabled).toBe(true);
    expect(button("Discard").disabled).toBe(true);
    fireEvent.click(board);
    await waitFor(() => expect(screen.getByTestId("ruler-label").textContent).toBe("a: span 12, row 1"));
  });

  test("palette inserts at the cursor, validation is debounced, Save PUTs the text", async () => {
    const onSaved = renderEditor("acc");
    await waitFor(() => expect(status()).toContain("✓ valid"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/leaderboard"))).toBe(true));
    fireEvent.click(button("stat strip"));
    fireEvent.click(button("table"));
    const expected =
      GOOD +
      "  - type: stat_strip\n    title: New stat strip\n    data: {metrics: [accuracy], pick: best}\n" +
      "    layout: {span: 12}\n" +
      "  - type: table\n    title: New table\n    data: {source: runs, fields: [run_id, status, created_by]}\n" +
      "    layout: {span: 12}\n";
    expect(screen.getByText("● unsaved")).toBeDefined();
    await waitFor(() => expect(status()).toContain("✓ valid · 3 panels"));
    // Two edits inside one 300 ms window: one validate call for the final text.
    expect(validateCalls().map((c) => c.body?.text)).toEqual([GOOD, expected]);
    await waitFor(() => expect(button("Save").disabled).toBe(false));
    fireEvent.click(button("Save"));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("acc"));
    const put = calls.find((c) => c.method === "PUT");
    expect(put?.url).toBe(`${VIEWS}/acc`);
    expect(put?.body?.text).toBe(expected);
    expect(typeof put?.body?.command_id).toBe("string");
    expect(screen.queryByText("● unsaved")).toBeNull();
    expect(button("Save").disabled).toBe(true);
  });

  test("an invalid view marks the line, blocks Save, and Discard restores the text", async () => {
    docText = BAD;
    const container = document.body;
    renderEditor("acc");
    await waitFor(() => expect(status()).toContain("✕ 1 error"));
    expect(button("ln 5")).toBeDefined();
    await waitFor(() => expect(container.querySelector(".cm-lintRange-error")?.textContent).toBe("acuracy"));
    fireEvent.click(button("markdown"));
    expect(screen.getByText("● unsaved")).toBeDefined();
    await waitFor(() => expect(validateCalls().length).toBe(2));
    await waitFor(() => expect(status()).toContain("✕ 1 error"));
    expect(button("Save").disabled).toBe(true);
    expect(button("Save").title).toBe("Fix 1 error to save");
    fireEvent.click(button("Discard"));
    expect(screen.queryByText("● unsaved")).toBeNull();
    expect(button("Discard").disabled).toBe(true);
  });

  test("a new view needs a valid name; Copy as CLI copies the command", async () => {
    const writeText = mock(async (_s: string) => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const onSaved = renderEditor("new");
    await waitFor(() => expect(status()).toContain("✓ valid · 0 panels"));
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("New view");
    expect(calls.some((c) => c.method === "GET" && c.url.includes("/views/"))).toBe(false);
    const nameBox = screen.getByLabelText("Name");
    expect(button("Save").disabled).toBe(true);
    expect(button("Copy as CLI").disabled).toBe(true);
    fireEvent.change(nameBox, { target: { value: "overview" } });
    expect(button("Save").disabled).toBe(true);
    fireEvent.change(nameBox, { target: { value: "acc2" } });
    expect(button("Save").disabled).toBe(false);
    await act(async () => fireEvent.click(button("Copy as CLI")));
    expect(writeText).toHaveBeenCalledWith(cliCommand("toy", "toy-acc", "acc2", NEW_VIEW_TEXT));
    expect(screen.getByRole("button", { name: "Copied" })).toBeDefined();
    fireEvent.click(button("Save"));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("acc2"));
    expect(calls.find((c) => c.method === "PUT")?.url).toBe(`${VIEWS}/acc2`);
  });

  test("the overview preset saves only under a new name, even unchanged", async () => {
    const onSaved = renderEditor("overview");
    await waitFor(() => expect(status()).toContain("✓ valid · 1 panel"));
    expect(screen.queryByText("● unsaved")).toBeNull();
    expect(button("Save").disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "acc_copy" } });
    expect(button("Save").disabled).toBe(false);
    fireEvent.click(button("Save"));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("acc_copy"));
    const put = calls.find((c) => c.method === "PUT");
    expect([put?.url, put?.body?.text]).toEqual([`${VIEWS}/acc_copy`, GOOD]);
  });

  test("a from: view previews inherited panels with the preset's layouts and counts them", async () => {
    docText = FROM_TEXT;
    renderEditor("acc");
    await waitFor(() => expect(status()).toContain("✓ valid · 3 panels"));
    expect(calls.some((c) => c.method === "GET" && c.url === `${VIEWS}/overview`)).toBe(true);
    const asides = async (title: string) =>
      (await screen.findByRole("region", { name: title })).querySelector(".aside")?.textContent;
    expect(await asides("Summary")).toBe("12/12");
    expect(await asides("Leaderboard")).toBe("8/12");
    expect(await asides("Note")).toBe("4/12");
    const query = calls.find((c) => c.url === `${VIEWS}/query`);
    expect((query?.body?.view as ViewSpec).from).toBe("generic");
  });

  test("a 400 from Save shows the error and the server's issues", async () => {
    putStatus = 400;
    const onSaved = renderEditor("acc");
    await waitFor(() => expect(status()).toContain("✓ valid"));
    fireEvent.click(button("markdown"));
    await waitFor(() => expect(button("Save").disabled).toBe(false));
    fireEvent.click(button("Save"));
    expect((await screen.findByRole("alert")).textContent).toBe("view 'acc' is invalid");
    expect(onSaved).not.toHaveBeenCalled();
    expect(screen.getByText("● unsaved")).toBeDefined();
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && bun test test/pages/ViewEditor.test.tsx`
Expected: FAIL with `error: Cannot find module '../../src/pages/ViewEditor' from '.../ui/test/pages/ViewEditor.test.tsx'`.

- [ ] **Step 3: Write the styles**

Create `ui/src/editor/editor.css`:

```css
/* View editor (docs/mockups/kinds/custom_view, #edit). Tokens come from styles/tokens.css;
   .crumb and .btn come from styles/base.css. */
.hx-ed-top { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 24px; align-items: end; }
.hx-ed-top h1 { font: 500 34px/1.1 var(--serif); letter-spacing: -.014em; margin: 0; display: flex; align-items: baseline; gap: 16px; }
.hx-ed-top h1 small { font: 400 13.5px/1 var(--sans); color: var(--ink-3); letter-spacing: 0; }
.hx-ed-act { display: flex; gap: 8px; align-items: center; }
.hx-ed-act label { font-size: 12.5px; color: var(--ink-3); display: inline-flex; gap: 8px; align-items: center; }
.hx-ed-act input { height: 32px; width: 160px; padding: 0 10px; border: 1px solid var(--rule); border-radius: 6px; background: transparent; color: var(--ink); font: 400 13px var(--mono); }
.hx-ed .btn:disabled { background: transparent; }
.hx-ed-alert { color: var(--fail); font-size: 13px; margin: 12px 0 0; }
.hx-ed-split { display: grid; grid-template-columns: minmax(0, 640px) minmax(0, 1fr); gap: 40px; margin-top: 28px; align-items: start; }

.hx-ed-ins { display: flex; align-items: flex-start; gap: 14px; margin-bottom: 14px; }
.hx-ed-ins > span { font-size: 12.5px; color: var(--ink-3); padding-top: 7px; width: 42px; flex: none; }
.hx-ed-lib { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 6px; flex: 1; }
.hx-ed-lib button { height: 30px; padding: 0 9px; border: 1px solid var(--rule); border-radius: 6px; background: transparent; cursor: pointer; font-size: 12.5px; color: var(--ink-2); white-space: nowrap; }
.hx-ed-lib button:hover { border-color: var(--ink-3); color: var(--ink); }

.hx-ed-editor { background: var(--paper-2); border-radius: 8px; overflow: hidden; }
.hx-ed-bar { display: flex; align-items: center; gap: 14px; height: 38px; padding: 0 14px; border-bottom: 1px solid var(--rule); font-size: 12.5px; color: var(--ink-3); }
.hx-ed-bar .file { font-family: var(--mono); color: var(--ink-2); }
.hx-ed-bar .vs { margin-left: auto; font-size: 13px; font-weight: 500; display: inline-flex; gap: 7px; align-items: center; }
.hx-ed-bar .vs.ok { color: var(--best); }
.hx-ed-bar .vs.err { color: var(--fail); }
.hx-ed-bar .vs button { border: 0; background: none; padding: 0; color: var(--ink-2); text-decoration: underline; cursor: pointer; font: inherit; font-weight: 400; }
.hx-ed-cm .cm-editor { min-height: 480px; }

.hx-ed-pv { position: sticky; top: 84px; }
.hx-ed-pv.stale .hx-ed-pgrid { opacity: .55; }
.hx-ed-pv-h { display: flex; align-items: baseline; gap: 12px; margin-bottom: 10px; height: 30px; }
.hx-ed-pv-h .t { font: 600 14px/1 var(--sans); }
.hx-ed-pv-h .aside { margin-left: auto; font-size: 12.5px; color: var(--ink-3); }
.hx-ed-ruler { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); column-gap: 16px; margin-bottom: 14px; }
.hx-ed-ruler span { height: 5px; border-radius: 1px; background: var(--rule-2); position: relative; }
.hx-ed-ruler span.on { background: var(--ink-3); }
.hx-ed-ruler span b { position: absolute; top: 8px; left: 0; right: 0; text-align: center; font: 400 10.5px/1 var(--sans); color: var(--ink-3); }
.hx-ed-pgrid { display: grid; grid-template-columns: repeat(12, minmax(0, 1fr)); gap: 16px; margin-top: 26px; }
.hx-ed-pp { min-width: 0; border: 1px solid var(--rule); border-radius: 7px; padding: 12px 14px 14px; cursor: pointer; }
.hx-ed-pp.sel { border-color: var(--ink-3); }
.hx-ed-pp.bad, .hx-ed-pp.over { border-color: var(--fail); }
.hx-ed-fig-h { display: flex; align-items: baseline; gap: 8px; margin-bottom: 10px; font-size: 14px; }
.hx-ed-fig-h .pl { font-weight: 700; }
.hx-ed-fig-h .t { font-weight: 600; }
.hx-ed-fig-h .aside { margin-left: auto; font-size: 12px; color: var(--ink-3); }
.hx-ed-perr { color: var(--fail); font-size: 13px; padding: 24px 0; text-align: center; }
.hx-ed-empty { color: var(--ink-3); font-size: 13px; }
```

- [ ] **Step 4: Write the page**

Create `ui/src/pages/ViewEditor.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import "../editor/editor.css";
import { ApiError, api } from "../api/client";
import type { PanelSpec, ViewSpec } from "../api/models";
import { useLeaderboard, useSaveView, useView, useViewQuery } from "../api/queries";
import { PanelPalette, type PanelType, panelSnippet, planInsert } from "../editor/PanelPalette";
import { type LayoutHint, type PanelResult, Preview } from "../editor/Preview";
import {
  outlineView,
  panelAtLine,
  type ValidationIssue,
  YamlEditor,
  type YamlEditorHandle,
} from "../editor/YamlEditor";
import { PanelBody } from "./components/PanelGrid";

/** Starting text for `/t/:project/:task/edit/new`. */
export const NEW_VIEW_TEXT = "title: new view\npanels: []\n";

const VIEW_NAME = /^[a-z0-9][a-z0-9_-]*$/;

/** True for a name `PUT views/{name}` accepts (contract 1.4; `overview` is reserved). */
export function isViewName(name: string): boolean {
  return VIEW_NAME.test(name) && name !== "overview";
}

/** Metric name from a task primary such as `accuracy/value` (the snippet default). */
export function metricOf(primary: string): string {
  return primary.split("/")[0] || "metric";
}

/**
 * Shell text that saves `text` as view `name` with the CLI.
 *
 * `hx view add` reads a file, so the command writes one with a quoted heredoc
 * (no shell expansion inside) and then adds it.
 */
export function cliCommand(project: string, task: string, name: string, text: string): string {
  const body = text.endsWith("\n") ? text : `${text}\n`;
  const lines = new Set(body.split("\n"));
  let tag = "YAML";
  while (lines.has(tag)) tag = `${tag}_`;
  const file = `/tmp/hx-view-${name}.yaml`;
  return `cat > ${file} <<'${tag}'\n${body}${tag}\nhx view add ${task} --file ${file} --name ${name} -p ${project}`;
}

/**
 * The panels of `view` after `from:`, merged the way the server's `resolve_view` does.
 *
 * Preset panels come first; a view panel whose non-empty title equals a preset panel's
 * title replaces it in place; every other view panel is appended. With no `from` or no
 * `preset`, the view's own panels come back unchanged. `POST views/validate` returns the
 * view as written, so the editor needs this to lay out and count inherited panels.
 */
export function resolvePanels(view: ViewSpec, preset: ViewSpec | null): PanelSpec[] {
  const own = view.panels ?? [];
  if (!view.from || !preset) return own;
  const panels = [...(preset.panels ?? [])];
  const position = new Map<string, number>();
  panels.forEach((p, i) => {
    if (p.title) position.set(p.title, i);
  });
  for (const panel of own) {
    const at = panel.title ? position.get(panel.title) : undefined;
    if (at === undefined) panels.push(panel);
    else panels[at] = panel;
  }
  return panels;
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}

function registryPanel(result: PanelResult): ReactNode {
  return <PanelBody result={result} />;
}

export interface ViewEditorProps {
  project: string;
  task: string;
  /** View name from the route; `new` starts a blank view. */
  view: string;
  /** Called with the saved name after every successful Save. */
  onSaved?: (name: string) => void;
  /** Renders one preview panel; defaults to the `ui/src/panels` registry. */
  renderPanel?: (result: PanelResult) => ReactNode;
}

/** `/t/:project/:task/edit/:view`: YAML on the left, live preview on the right. */
export function ViewEditor({ project, task, view, onSaved, renderPanel = registryPanel }: ViewEditorProps) {
  const isNew = view === "new";
  const nameEditable = isNew || view === "overview";
  const editor = useRef<YamlEditorHandle>(null);

  const [loaded, setLoaded] = useState(isNew);
  const [baseline, setBaseline] = useState(isNew ? NEW_VIEW_TEXT : "");
  const [text, setText] = useState(baseline);
  const [name, setName] = useState(nameEditable ? "" : view);
  const [cursorLine, setCursorLine] = useState(1);
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [good, setGood] = useState<ViewSpec | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const doc = useView(project, task, isNew ? null : view);
  useEffect(() => {
    if (loaded || !doc.data) return;
    setBaseline(doc.data.text);
    setText(doc.data.text);
    setLoaded(true);
  }, [doc.data, loaded]);

  const board = useLeaderboard(project, task);
  const metric = board.data ? metricOf(board.data.primary) : "metric";

  const debounced = useDebounced(text, 300);
  const validation = useQuery({
    queryKey: ["views", "validate", project, task, debounced],
    queryFn: ({ signal }) => api.validateView(project, task, debounced, signal),
    enabled: loaded && debounced === text,
    staleTime: Number.POSITIVE_INFINITY,
  });
  useEffect(() => {
    if (!validation.data) return;
    setIssues(validation.data.issues);
    if (validation.data.ok && validation.data.view) setGood(validation.data.view);
  }, [validation.data]);

  const preview = useViewQuery(project, task, good ? { view: good } : null);
  // `from:` views: the task kind's preset (resolved, with layouts) fills in inherited panels.
  const presetDoc = useView(project, task, good?.from ? "overview" : null);
  const presetData = presetDoc.data;
  const preset: ViewSpec | null =
    good?.from && presetData && presetData.info.kind === good.from ? presetData.view : null;
  const resolved = good ? resolvePanels(good, preset) : [];
  const resolvedComplete = !good?.from || preset !== null;

  const checking = !loaded || debounced !== text || validation.isFetching || !validation.data;
  const valid = !checking && validation.data?.ok === true;
  const invalid = !checking && validation.data?.ok === false;
  const dirty = text !== baseline;

  const save = useSaveView(project, task);
  const onSave = () => {
    const sent = text;
    save.mutate(
      { name, text: sent },
      {
        onSuccess: () => {
          setBaseline(sent);
          setSaveError(null);
          onSaved?.(name);
        },
        onError: (err) => {
          setSaveError(err.message);
          if (err instanceof ApiError && err.issues.length > 0) setIssues(err.issues);
        },
      },
    );
  };

  const outline = useMemo(() => outlineView(text), [text]);
  const results = preview.data?.panels ?? [];
  const indexOfTitle = (title: string) => results.findIndex((r) => r.title === title);
  const layouts: LayoutHint[] = results.map(
    (r) => resolved.find((p) => (p.title ?? "") === r.title)?.layout ?? {},
  );
  const cursorPanel = panelAtLine(outline, cursorLine);
  const selected = cursorPanel ? indexOfTitle(cursorPanel.title) : -1;
  const problems: Record<number, string> = {};
  for (const issue of issues) {
    const panel = issue.line === null ? null : panelAtLine(outline, issue.line);
    const i = panel ? indexOfTitle(panel.title) : -1;
    if (i >= 0 && problems[i] === undefined) problems[i] = `${issue.message}, ln ${issue.line}`;
  }

  const nameOk = isViewName(name);
  const canSave = valid && nameOk && (dirty || nameEditable) && !save.isPending;
  const saveTitle = invalid
    ? `Fix ${issues.length} error${issues.length === 1 ? "" : "s"} to save`
    : !nameOk
      ? "Name: a-z, 0-9, _ or -, not overview"
      : `Validate, then write .hypothex/views/${task}/${name}.yaml`;
  const cli = nameOk ? cliCommand(project, task, name, text) : "";

  const onInsert = (type: PanelType) => {
    editor.current?.applyInsertion((current, line) => planInsert(current, line, panelSnippet(type, metric)));
  };
  const onEdit = (next: string) => {
    setText(next);
    setSaveError(null);
  };
  const onDiscard = () => {
    setText(baseline);
    setSaveError(null);
  };
  const onCopy = async () => {
    await navigator.clipboard.writeText(cli);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  const onSelectPanel = (index: number) => {
    const panel = outline.panels.find((p) => p.title === results[index]?.title);
    if (panel) editor.current?.goToLine(panel.startLine);
  };

  const firstIssueLine = issues.find((i) => i.line !== null)?.line ?? null;
  // The resolved count; for a `from:` of another kind, the server-resolved preview's count.
  const nPanels = resolvedComplete ? resolved.length : results.length;
  let status: ReactNode;
  if (validation.error) status = <span className="vs err">✕ {validation.error.message}</span>;
  else if (checking) status = <span className="vs">checking</span>;
  else if (invalid)
    status = (
      <span className="vs err">
        ✕ {issues.length} error{issues.length === 1 ? "" : "s"}
        {firstIssueLine !== null && (
          <button type="button" onClick={() => editor.current?.goToLine(firstIssueLine)}>
            ln {firstIssueLine}
          </button>
        )}
      </span>
    );
  else status = <span className="vs ok">{`✓ valid · ${nPanels} panel${nPanels === 1 ? "" : "s"}`}</span>;

  const heading = isNew ? "New view" : `Edit ${good?.title ?? view}`;
  return (
    <div className="hx-ed">
      <p className="crumb">
        {project}
        <span className="sep">/</span>
        {task}
        <span className="sep">/</span>
        {isNew ? "new" : view}
      </p>
      <div className="hx-ed-top">
        <h1>
          {heading}
          {dirty && <small title="Not saved yet">● unsaved</small>}
        </h1>
        <div className="hx-ed-act">
          {nameEditable && (
            <label>
              Name
              <input value={name} onChange={(e) => setName(e.target.value.trim())} placeholder="route_quality" />
            </label>
          )}
          <button type="button" className="btn" disabled={!dirty} onClick={onDiscard}>
            Discard
          </button>
          <button
            type="button"
            className="btn"
            disabled={!nameOk}
            title={nameOk ? cli.split("\n").at(-1) : "Name the view first"}
            onClick={() => void onCopy()}
          >
            {copied ? "Copied" : "Copy as CLI"}
          </button>
          <button
            type="button"
            className="btn primary"
            disabled={!canSave}
            title={saveTitle}
            onClick={onSave}
          >
            Save
          </button>
        </div>
      </div>
      {doc.error && <p className="hx-ed-alert" role="alert">{doc.error.message}</p>}
      {saveError && <p className="hx-ed-alert" role="alert">{saveError}</p>}
      <div className="hx-ed-split">
        <div>
          <PanelPalette onInsert={onInsert} />
          <div className="hx-ed-editor">
            <div className="hx-ed-bar" data-testid="ed-status">
              <span className="file">{`.hypothex/views/${task}/${name || "<name>"}.yaml`}</span>
              {status}
            </div>
            <YamlEditor ref={editor} value={text} onChange={onEdit} issues={issues} onCursorLine={setCursorLine} />
          </div>
        </div>
        <Preview
          results={results}
          layouts={layouts}
          selected={selected >= 0 ? selected : null}
          problems={problems}
          stale={invalid}
          renderPanel={renderPanel}
          onSelect={onSelectPanel}
        />
      </div>
    </div>
  );
}

export default ViewEditor;
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd ui && bun test test/pages/ViewEditor.test.tsx`
Expected: `11 pass`, `0 fail` (the tests wait on the real 300 ms debounce; the file takes about 3 s).

- [ ] **Step 6: Run the whole group and type-check**

Run: `cd ui && bun test test/editor test/pages/ViewEditor.test.tsx && bunx tsc --noEmit -p .`
Expected: `38 pass`, `0 fail` across 4 files; `tsc` prints nothing and exits 0.

- [ ] **Step 7: Write the failing route test**

Append to `ui/test/router.test.tsx`:

```tsx
test("every route renders its own screen, not the placeholder", async () => {
  const { cleanup } = await import("@testing-library/react");
  for (const path of ["/", "/t/toy/acc", "/t/toy/acc/edit/new", "/r/r1", "/x/r1/r2?metric=accuracy"]) {
    const { router } = renderApp(path);
    await waitFor(() => expect(router.state.status).toBe("idle"));
    expect([path, screen.queryByTestId("screen-pending")]).toEqual([path, null]);
    cleanup();
  }
});
```

Run: `cd ui && bun test test/router.test.tsx`
Expected: FAIL for `/t/toy/acc/edit/new`: the editor route still renders the `View editor` placeholder.

- [ ] **Step 8: Show the editor on `/t/$project/$task/edit/$view`**

In `ui/src/router.tsx` replace

```tsx
  createRouter,
} from "@tanstack/react-router";
```

with

```tsx
  createRouter,
  useNavigate,
} from "@tanstack/react-router";
```

replace

```tsx
import { TaskPage } from "./pages/Task";
```

with

```tsx
import { TaskPage } from "./pages/Task";
import { ViewEditor } from "./pages/ViewEditor";
```

replace

```tsx
  return <ExamplesPage a={a} b={b} metric={metric} />;
}
```

with

```tsx
  return <ExamplesPage a={a} b={b} metric={metric} />;
}

/** `/t/$project/$task/edit/$view`: the view editor; Save opens the saved view's tab. */
function ViewEditorScreen(): ReactElement {
  const { project, task, view } = viewEditorRoute.useParams();
  const navigate = useNavigate();
  return (
    <ViewEditor
      key={`${project}/${task}/${view}`}
      project={project}
      task={task}
      view={view}
      onSaved={(name) => void navigate({ to: "/t/$project/$task", params: { project, task }, search: { view: name } })}
    />
  );
}
```

and replace

```tsx
  path: "/t/$project/$task/edit/$view",
  component: () => <ScreenPending name="View editor" />,
```

with

```tsx
  path: "/t/$project/$task/edit/$view",
  component: ViewEditorScreen,
```

The `key` remounts the editor when the route moves to another view, so its text and baseline never carry over.

Run: `cd ui && bun test && bun run typecheck`
Expected: every unit test passes, `0 fail`; `tsc` prints nothing.

- [ ] **Step 9: Check it in the real app**

Run (three shells, each from the repo root; every `hx` command names the demo home with `--home`, so no shell touches your real `~/.hypothex`):
```bash
# shell 1: make the demo home and fill it
mktemp -d > /tmp/hx-editor-home
H=$(cat /tmp/hx-editor-home)
uv run hx --home "$H" demo --json      # prints {kind: "project/task"}

# shell 2: serve that home
H=$(cat /tmp/hx-editor-home)
uv run hx --home "$H" serve            # API on 127.0.0.1:7777

# shell 3: the Vite dev server
cd ui && bun run dev                   # proxies /api to 127.0.0.1:7777
```
Open `http://localhost:5173/t/<project>/<task>/edit/new` using the `agent_eval` entry from the demo output. Expected:
- Status bar `✓ valid · 0 panels`; Save and Copy as CLI are disabled until a Name is typed.
- Click `leaderboard`: a snippet with the task's primary metric appears under `panels:`, `● unsaved` shows, and about 300 ms later the preview shows panel `a New leaderboard` with real rows; the ruler lights columns 1–12 with label `a: span 12, row 1`.
- Change the metric to a misspelling: a red wavy mark on the name, gutter marker, status `✕ 1 error ln N`, Save disabled with tooltip `Fix 1 error to save`, the panel shows the message; the lint tooltip action `use <metric>` fixes it.
- Type name `smoke`, Save: `$H/demo-repos/.../.hypothex/views/<task>/smoke.yaml` exists and `uv run hx --home "$H" view list <task> -p <project> --json` (shell 1) lists `smoke`.
- Copy as CLI, paste in shell 1 after `export HYPOTHEX_HOME="$H"` (the copied `hx view add` has no `--home`), with a new name in the `--name` flag: the command succeeds and prints `wrote .../<name>.yaml`.
- Toggle dark mode: editor, ruler and preview use the dark tokens.

- [ ] **Step 10: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add ui/src/pages/ViewEditor.tsx ui/test/pages/ViewEditor.test.tsx ui/src/editor/editor.css ui/src/router.tsx ui/test/router.test.tsx
git commit -m "feat(ui): view editor page with live preview, save, discard, copy as CLI"
```

## Part 6: Live updates, Playwright smoke tests, CI, docs (Tasks 42–48)

Adds the WebSocket live-update stream (contract section 4), the Playwright smoke suite against a real `hx serve` on a `hx demo` home (every kind's preset renders, a custom view round-trips through the editor, green in light and dark), a `ui` CI job, and the Sphinx `Web UI` docs page.

Backend WebSocket protocol (phase 1a, `src/hypothex/api/app.py` `events_ws`): the client sends `{"type":"subscribe","after_sequence":N}` first; the server sends `{"type":"event","event":Event}` for every event with `sequence > N` in order, then one `{"type":"ready","last_sequence":M}`, then live events. A bad first message gets `{"type":"error","error":...}` and a close. Event types in use: `run.created`, `run.launched`, `run.started`, `run.finished`, `run.failed`, `run.killed`, `run.lost`, `run.score_added`, `run.tagged`, `run.starred`, `run.archived`, `run.note_added`, `run.warning`, `run.eval_skipped`.

The e2e specs use the page DOM of Parts 4 and 5: view tabs are links in `nav[aria-label="Views"]` (the current one has `aria-current="page"`) plus a `+ view` link to `/t/:project/:task/edit/new`; panel titles are `h2` headings; the editor is CodeMirror 6 (`.cm-editor`, `.cm-content`, lint markers `.cm-lint-marker-error`) with a `Name` input on `/edit/new` and a `Save` button that is disabled while the YAML is invalid; the Run page shows the hypothesis and its notes.

### Task 42: `useEventStream` — replay, reconnect backoff, and query invalidation

**Files:**
- Create: `ui/src/api/events.ts`
- Modify: `ui/src/main.tsx` (mount `LiveUpdates`)
- Test: `ui/test/api/events.test.ts`

**Interfaces:**
- Consumes: Task 3 `wsUrl()`, `HxEvent`, `WsMessage`; Task 4 `RUN_EVENT_INVALIDATES`, `queryKeys` (the only query keys in the app); `@tanstack/react-query`, React 19, `@testing-library/react` (`renderHook`, `act`), `bun:test`.
- Produces (module `ui/src/api/events.ts`):
  - `HxEvent` (re-exported from the models), `type ServerMessage = WsMessage`
  - `type StreamStatus = "connecting" | "connected" | "ready" | "offline"`
  - `interface SocketLike`, `interface Clock`, `interface EventStreamOptions`, `interface EventStreamHookOptions`
  - `const BACKOFF_MS = [3000, 4000, 8000, 16000]`, `const STABLE_RESET_MS = 30000`, `const FLUSH_MS = 250`
  - `const SEQUENCE_KEY = "hx-ws-sequence"`; `readSequence(storage: Pick<Storage, "getItem"> | null): number` (0 when missing, bad, or storage throws); `writeSequence(storage: Pick<Storage, "setItem"> | null, sequence: number): void` (ignores storage errors)
  - `backoffDelay(attempt: number): number`, `keysForEvent(event: HxEvent): QueryKey[]` (the `RUN_EVENT_INVALIDATES` families, narrowed to the event's project for `task`, `leaderboard` and `views/query`, and to its run id for `run`), `keysForEvents(events: readonly HxEvent[]): QueryKey[]`, `invalidateForEvents(client: QueryClient, events: readonly HxEvent[]): void`
  - `class EventStream { constructor(options: EventStreamOptions); start(): void; stop(): void; get sequence(): number }`
  - `useEventStream(options?: EventStreamHookOptions): StreamStatus`; `LiveUpdates()` (a component that calls it once; mounted in `main.tsx`, outside the router, so route tests open no socket).

Resume across page loads: without it, every page load subscribes with `after_sequence: 0`, so the server replays the whole event log (in batches of 500) before `ready`, and the cost grows with the store's age. The hook saves the last delivered sequence in `sessionStorage` (`SEQUENCE_KEY`, per tab and origin) after `ready` and after each batch, and passes it to the stream as `resumeSequence`. A fresh page fetches all its data, so only events after that point matter. The stored value may come from another store (a different `--home` served on the same port) or a reset one, so the stream checks it: it subscribes with `after_sequence: resumeSequence - 1` and expects event `resumeSequence` back before `ready`. That event was already seen, so it is not delivered. If `ready` comes first, the server has no such event: the stream drops the stored value and reconnects at once from 0. If the first event has a higher sequence, the stream continues from there (every later event still arrives).

- [ ] **Step 1: Write the failing tests**

`ui/test/api/events.test.ts`:

```ts
import { describe, expect, spyOn, test } from "bun:test";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { queryKeys } from "../../src/api/queries";
import {
  backoffDelay,
  type Clock,
  EventStream,
  FLUSH_MS,
  type HxEvent,
  invalidateForEvents,
  keysForEvent,
  keysForEvents,
  readSequence,
  SEQUENCE_KEY,
  type SocketLike,
  type StreamStatus,
  useEventStream,
  writeSequence,
} from "../../src/api/events";

class FakeSocket implements SocketLike {
  readonly url: string;
  readyState = 0;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  readonly sent: string[] = [];
  closed = false;

  constructor(url: string) {
    this.url = url;
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    if (this.closed) return;
    this.closed = true;
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close"));
  }

  open(): void {
    this.readyState = 1;
    this.onopen?.(new Event("open"));
  }

  receive(message: unknown): void {
    this.receiveRaw(JSON.stringify(message));
  }

  receiveRaw(data: string): void {
    this.onmessage?.(new MessageEvent("message", { data }));
  }

  /** The network drops the connection (the server did not ask to close). */
  drop(): void {
    this.readyState = 3;
    this.onclose?.(new CloseEvent("close"));
  }
}

class FakeClock implements Clock {
  now = 0;
  private nextId = 1;
  private readonly timers = new Map<number, { at: number; fn: () => void }>();

  setTimeout(fn: () => void, ms: number): number {
    const id = this.nextId++;
    this.timers.set(id, { at: this.now + ms, fn });
    return id;
  }

  clearTimeout(handle: unknown): void {
    this.timers.delete(handle as number);
  }

  /** Move time forward, firing due timers in time order (ties in creation order). */
  advance(ms: number): void {
    const end = this.now + ms;
    for (;;) {
      let nextId = -1;
      let nextAt = Number.POSITIVE_INFINITY;
      for (const [id, timer] of this.timers) {
        if (timer.at <= end && timer.at < nextAt) {
          nextId = id;
          nextAt = timer.at;
        }
      }
      const timer = this.timers.get(nextId);
      if (!timer) break;
      this.timers.delete(nextId);
      this.now = nextAt;
      timer.fn();
    }
    this.now = end;
  }
}

function ev(
  sequence: number,
  type = "run.finished",
  project: string | null = "toy",
  run_id: string | null = "r1",
): HxEvent {
  return { sequence, type, project, run_id, payload: {}, created_at: "2026-09-27T10:00:00Z" };
}

function harness(afterSequence?: number, resumeSequence?: number) {
  const clock = new FakeClock();
  const sockets: FakeSocket[] = [];
  const delivered: number[][] = [];
  const statuses: StreamStatus[] = [];
  const saved: number[] = [];
  const stream = new EventStream({
    url: "ws://127.0.0.1:7777/api/v1/ws",
    clock,
    afterSequence,
    resumeSequence,
    createSocket: (url) => {
      const socket = new FakeSocket(url);
      sockets.push(socket);
      return socket;
    },
    onEvents: (events) => delivered.push(events.map((e) => e.sequence)),
    onStatus: (status) => statuses.push(status),
    onSequence: (sequence) => saved.push(sequence),
  });
  const last = (): FakeSocket => {
    const socket = sockets.at(-1);
    if (!socket) throw new Error("no socket was created");
    return socket;
  };
  return { stream, clock, sockets, delivered, statuses, saved, last };
}

/** An in-memory `Storage` stand-in. */
function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    data,
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => {
      data.set(key, value);
    },
  };
}

describe("backoffDelay", () => {
  test("follows 3/4/8/16 s and stays at 16 s", () => {
    expect([0, 1, 2, 3, 4, 9].map(backoffDelay)).toEqual([3000, 4000, 8000, 16000, 16000, 16000]);
  });
});

describe("keysForEvent", () => {
  test("a run event invalidates run lists, the run, and its project's boards and views", () => {
    expect(keysForEvent(ev(1, "run.finished", "toy", "r1"))).toEqual([
      ["overview"],
      ["tasks"],
      ["task", "toy"],
      ["runs"],
      ["run", "r1"],
      ["leaderboard", "toy"],
      ["views", "query", "toy"],
      ["compareExamples"],
    ]);
  });

  test("a run event without project or run id invalidates the families", () => {
    expect(keysForEvent(ev(1, "run.lost", null, null))).toEqual([
      ["overview"],
      ["tasks"],
      ["task"],
      ["runs"],
      ["leaderboard"],
      ["views", "query"],
      ["compareExamples"],
    ]);
  });

  test("a non-run event invalidates nothing", () => {
    expect(keysForEvent(ev(1, "test.event", null, null))).toEqual([]);
  });

  test("keysForEvents drops duplicate keys and keeps first-seen order", () => {
    const keys = keysForEvents([
      ev(1, "run.finished", "toy", "r1"),
      ev(2, "run.score_added", "toy", "r1"),
      ev(3, "run.started", "toy", "r2"),
    ]);
    expect(keys).toEqual([
      ["overview"],
      ["tasks"],
      ["task", "toy"],
      ["runs"],
      ["run", "r1"],
      ["leaderboard", "toy"],
      ["views", "query", "toy"],
      ["compareExamples"],
      ["run", "r2"],
    ]);
  });

  test("a run event refreshes every page query of that run and project, and no view text", async () => {
    const client = new QueryClient();
    const hit = [
      queryKeys.overview(),
      queryKeys.tasks(),
      queryKeys.task("toy", "acc"),
      queryKeys.runs({ project: "toy" }),
      queryKeys.run("r1"),
      queryKeys.runLogs("r1", "stderr"),
      queryKeys.runTrace("r1", "ex-1"),
      queryKeys.leaderboard("toy", "acc"),
      queryKeys.viewQuery("toy", "acc", { name: "overview" }),
      queryKeys.compareExamples("r0", "r1", "accuracy"),
    ];
    const miss = [
      queryKeys.run("r2"),
      queryKeys.leaderboard("other", "acc"),
      queryKeys.views("toy", "acc"),
      queryKeys.view("toy", "acc", "route"),
      queryKeys.taskKind("toy", "acc"),
      queryKeys.projects(),
    ];
    for (const key of [...hit, ...miss]) client.setQueryData(key, { seeded: true });
    invalidateForEvents(client, [ev(1, "run.note_added", "toy", "r1")]);
    await new Promise((resolve) => setTimeout(resolve, 0));
    const invalidated = (key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated;
    expect(hit.map(invalidated)).toEqual(hit.map(() => true));
    expect(miss.map(invalidated)).toEqual(miss.map(() => false));
  });
});

describe("stored sequence", () => {
  test("readSequence accepts only positive integers; writeSequence ignores storage errors", () => {
    expect(readSequence(memoryStorage({ [SEQUENCE_KEY]: "41" }))).toBe(41);
    for (const bad of ["", "abc", "-3", "1.5", "0"]) {
      expect(readSequence(memoryStorage({ [SEQUENCE_KEY]: bad }))).toBe(0);
    }
    expect(readSequence(memoryStorage())).toBe(0);
    expect(readSequence(null)).toBe(0);
    const broken = {
      getItem: (): string | null => {
        throw new Error("SecurityError");
      },
      setItem: (): void => {
        throw new Error("QuotaExceededError");
      },
    };
    expect(readSequence(broken)).toBe(0);
    expect(() => writeSequence(broken, 5)).not.toThrow();
    const store = memoryStorage();
    writeSequence(store, 42);
    expect(store.data.get(SEQUENCE_KEY)).toBe("42");
  });
});

describe("EventStream", () => {
  test("resumes from a stored sequence without replaying or redelivering it", () => {
    const h = harness(undefined, 41);
    h.stream.start();
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":40}']);
    h.last().receive({ type: "event", event: ev(41) });
    h.last().receive({ type: "event", event: ev(42) });
    h.last().receive({ type: "ready", last_sequence: 42 });
    expect(h.delivered).toEqual([[42]]);
    expect(h.stream.sequence).toBe(42);
    expect(h.saved).toEqual([42]);
    expect(h.sockets.length).toBe(1);
  });

  test("a stored sequence the server does not have restarts from 0 at once", () => {
    const h = harness(undefined, 41);
    h.stream.start();
    const first = h.last();
    first.open();
    first.receive({ type: "ready", last_sequence: 40 });
    expect(first.closed).toBe(true);
    expect(h.sockets.length).toBe(2);
    expect(h.delivered).toEqual([]);
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":0}']);
    h.last().receive({ type: "event", event: ev(1) });
    h.last().receive({ type: "ready", last_sequence: 1 });
    expect(h.delivered).toEqual([[1]]);
    expect(h.saved).toEqual([1]);
    expect(h.statuses).toEqual(["connecting", "connected", "connecting", "connected", "ready"]);
  });

  test("subscribes after the given sequence once the socket opens", () => {
    const fresh = harness();
    fresh.stream.start();
    expect(fresh.last().sent).toEqual([]);
    fresh.last().open();
    expect(fresh.last().sent).toEqual(['{"type":"subscribe","after_sequence":0}']);

    const resumed = harness(41);
    resumed.stream.start();
    resumed.last().open();
    expect(resumed.last().sent).toEqual(['{"type":"subscribe","after_sequence":41}']);
    expect(resumed.last().url).toBe("ws://127.0.0.1:7777/api/v1/ws");
  });

  test("buffers replayed events until ready, then delivers them once", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "event", event: ev(1) });
    h.last().receive({ type: "event", event: ev(2) });
    expect(h.delivered).toEqual([]);
    h.last().receive({ type: "ready", last_sequence: 2 });
    expect(h.delivered).toEqual([[1, 2]]);
    expect(h.statuses).toEqual(["connecting", "connected", "ready"]);
    expect(h.stream.sequence).toBe(2);
  });

  test("batches live events that arrive within FLUSH_MS", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "ready", last_sequence: 2 });
    h.last().receive({ type: "event", event: ev(3) });
    h.last().receive({ type: "event", event: ev(4) });
    h.clock.advance(FLUSH_MS - 1);
    expect(h.delivered).toEqual([]);
    h.clock.advance(1);
    expect(h.delivered).toEqual([[3, 4]]);
  });

  test("drops duplicate and old sequences", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "ready", last_sequence: 4 });
    for (const sequence of [3, 4, 5, 5]) h.last().receive({ type: "event", event: ev(sequence) });
    h.clock.advance(FLUSH_MS);
    expect(h.delivered).toEqual([[5]]);
  });

  test("reconnects after 3, 4, 8, 16, 16 s while the connection keeps failing", () => {
    const h = harness();
    h.stream.start();
    expect(h.sockets.length).toBe(1);
    let expected = 1;
    for (const delay of [3000, 4000, 8000, 16000, 16000]) {
      h.last().drop();
      expect(h.statuses.at(-1)).toBe("offline");
      h.clock.advance(delay - 1);
      expect(h.sockets.length).toBe(expected);
      h.clock.advance(1);
      expected += 1;
      expect(h.sockets.length).toBe(expected);
      expect(h.statuses.at(-1)).toBe("connecting");
    }
  });

  test("resubscribes after the last seen sequence", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "event", event: ev(1) });
    h.last().receive({ type: "event", event: ev(2) });
    h.last().receive({ type: "ready", last_sequence: 2 });
    h.last().receive({ type: "event", event: ev(3) });
    h.last().drop();
    h.clock.advance(3000);
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":3}']);
  });

  test("keeps replayed events across a drop before ready", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "event", event: ev(1) });
    h.last().drop();
    h.clock.advance(3000);
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":1}']);
    expect(h.delivered).toEqual([]);
    h.last().receive({ type: "ready", last_sequence: 1 });
    expect(h.delivered).toEqual([[1]]);
  });

  test("resets the backoff after 30 s of stable connection, and not before", () => {
    const h = harness();
    h.stream.start();
    h.last().drop();
    h.clock.advance(3000); // socket 2
    h.last().drop();
    h.clock.advance(4000); // socket 3, next delay would be 8 s
    h.last().open();
    h.clock.advance(29_999);
    h.last().drop();
    h.clock.advance(7_999);
    expect(h.sockets.length).toBe(3);
    h.clock.advance(1);
    expect(h.sockets.length).toBe(4); // not reset: 8 s
    h.last().open();
    h.clock.advance(30_000);
    h.last().drop();
    h.clock.advance(2_999);
    expect(h.sockets.length).toBe(4);
    h.clock.advance(1);
    expect(h.sockets.length).toBe(5); // reset: 3 s
  });

  test("ignores messages from a replaced socket", () => {
    const h = harness();
    h.stream.start();
    const first = h.last();
    first.open();
    first.receive({ type: "ready", last_sequence: 0 });
    first.drop();
    h.clock.advance(3000);
    first.receive({ type: "event", event: ev(9) });
    h.clock.advance(FLUSH_MS);
    expect(h.delivered).toEqual([]);
    h.last().open();
    expect(h.last().sent).toEqual(['{"type":"subscribe","after_sequence":0}']);
  });

  test("stops retrying after a server error message", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receive({ type: "error", error: "first message must be {type: subscribe}" });
    expect(h.last().closed).toBe(true);
    expect(h.statuses.at(-1)).toBe("offline");
    h.clock.advance(60_000);
    expect(h.sockets.length).toBe(1);
  });

  test("stop() closes an open socket and never reconnects", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.stream.stop();
    expect(h.last().closed).toBe(true);
    h.clock.advance(60_000);
    expect(h.sockets.length).toBe(1);
    expect(h.statuses).toEqual(["connecting", "connected"]);
  });

  test("stop() while connecting closes only after open", () => {
    const h = harness();
    h.stream.start();
    h.stream.stop();
    expect(h.last().closed).toBe(false);
    h.last().open();
    expect(h.last().closed).toBe(true);
    expect(h.last().sent).toEqual([]);
    h.clock.advance(60_000);
    expect(h.sockets.length).toBe(1);
  });

  test("ignores malformed messages", () => {
    const h = harness();
    h.stream.start();
    h.last().open();
    h.last().receiveRaw("not json");
    h.last().receiveRaw("null");
    h.last().receiveRaw('{"type":"event","event":{"sequence":"7","type":"run.finished"}}');
    h.last().receiveRaw('{"type":"event"}');
    h.last().receive({ type: "event", event: ev(1) });
    h.last().receive({ type: "ready", last_sequence: 1 });
    expect(h.delivered).toEqual([[1]]);
  });
});

describe("useEventStream", () => {
  test("invalidates the mapped keys, reports status, and closes on unmount", () => {
    const client = new QueryClient();
    const spy = spyOn(client, "invalidateQueries");
    const clock = new FakeClock();
    const sockets: FakeSocket[] = [];
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children);
    const { result, unmount } = renderHook(
      () =>
        useEventStream({
          url: "ws://127.0.0.1:7777/api/v1/ws",
          clock,
          storage: null,
          createSocket: (url) => {
            const socket = new FakeSocket(url);
            sockets.push(socket);
            return socket;
          },
        }),
      { wrapper },
    );
    const socket = sockets[0];
    if (!socket) throw new Error("hook did not open a socket");
    expect(result.current).toBe("connecting");

    act(() => {
      socket.open();
      socket.receive({ type: "ready", last_sequence: 7 });
    });
    expect(result.current).toBe("ready");
    expect(spy).not.toHaveBeenCalled();

    act(() => {
      socket.receive({ type: "event", event: ev(8, "run.score_added", "toy", "r1") });
      socket.receive({ type: "event", event: ev(9, "run.finished", "toy", "r1") });
      clock.advance(FLUSH_MS);
    });
    expect(spy.mock.calls.map((call) => call[0])).toEqual([
      { queryKey: ["overview"] },
      { queryKey: ["tasks"] },
      { queryKey: ["task", "toy"] },
      { queryKey: ["runs"] },
      { queryKey: ["run", "r1"] },
      { queryKey: ["leaderboard", "toy"] },
      { queryKey: ["views", "query", "toy"] },
      { queryKey: ["compareExamples"] },
    ]);

    unmount();
    expect(socket.closed).toBe(true);
    expect(sockets.length).toBe(1);
  });

  test("resumes from sessionStorage and saves the last delivered sequence", () => {
    const client = new QueryClient();
    const storage = memoryStorage({ [SEQUENCE_KEY]: "7" });
    const sockets: FakeSocket[] = [];
    const clock = new FakeClock();
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client }, children);
    const { unmount } = renderHook(
      () =>
        useEventStream({
          url: "ws://127.0.0.1:7777/api/v1/ws",
          clock,
          storage,
          createSocket: (url) => {
            const socket = new FakeSocket(url);
            sockets.push(socket);
            return socket;
          },
        }),
      { wrapper },
    );
    const socket = sockets[0];
    if (!socket) throw new Error("hook did not open a socket");
    act(() => socket.open());
    expect(socket.sent).toEqual(['{"type":"subscribe","after_sequence":6}']);
    act(() => {
      socket.receive({ type: "event", event: ev(7) });
      socket.receive({ type: "ready", last_sequence: 7 });
      socket.receive({ type: "event", event: ev(8) });
      socket.receive({ type: "event", event: ev(9) });
      clock.advance(FLUSH_MS);
    });
    expect(storage.data.get(SEQUENCE_KEY)).toBe("9");
    unmount();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd ui && bun test test/api/events.test.ts`
Expected: FAIL with `error: Cannot find module '../../src/api/events'`.

- [ ] **Step 3: Write the implementation**

`ui/src/api/events.ts` (whole file):

```ts
/**
 * Live updates over `/api/v1/ws`.
 *
 * One stream per app: subscribe with `after_sequence`, receive the replay, then live
 * events. Reconnects with 3/4/8/16 s backoff (reset after 30 s stable), drops duplicate
 * sequences, and turns events into TanStack Query invalidations (spec 5.3, 8.2). The last
 * delivered sequence is kept in `sessionStorage`, so a page load resumes there instead of
 * replaying the whole event log.
 */
import { type QueryClient, type QueryKey, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { wsUrl } from "./client";
import type { HxEvent, WsMessage } from "./models";
import { RUN_EVENT_INVALIDATES } from "./queries";

/** One entry of the server's event log (`hypothex.core.events.Event`). */
export type { HxEvent };

/** Messages the server sends on `/api/v1/ws`. */
export type ServerMessage = WsMessage;

/** `connected`: open and subscribed. `ready`: replay done, live from here on. */
export type StreamStatus = "connecting" | "connected" | "ready" | "offline";

/** The part of the browser `WebSocket` the stream uses (tests pass a fake). */
export interface SocketLike {
  readyState: number;
  onopen: ((ev: Event) => void) | null;
  onmessage: ((ev: MessageEvent) => void) | null;
  onclose: ((ev: CloseEvent) => void) | null;
  onerror: ((ev: Event) => void) | null;
  send(data: string): void;
  close(): void;
}

/** Timer functions (tests pass a fake clock). */
export interface Clock {
  setTimeout(fn: () => void, ms: number): unknown;
  clearTimeout(handle: unknown): void;
}

export interface EventStreamOptions {
  /** WebSocket URL, e.g. `ws://127.0.0.1:7777/api/v1/ws`. */
  url: string;
  /** Called with new events, deduplicated by sequence, in order, batched. */
  onEvents: (events: HxEvent[]) => void;
  onStatus?: (status: StreamStatus) => void;
  createSocket?: (url: string) => SocketLike;
  clock?: Clock;
  /** Last sequence already seen and trusted; the first subscribe replays after it. Default 0. */
  afterSequence?: number;
  /**
   * Sequence saved by an earlier page load (not trusted: the server may serve another
   * store now). The first subscribe asks for the events after `resumeSequence - 1`; event
   * `resumeSequence` must come back before `ready` (it is not delivered again), else the
   * stream reconnects from 0. Ignored when `afterSequence` is given.
   */
  resumeSequence?: number;
  /** Called with the last delivered sequence after `ready` and after each batch. */
  onSequence?: (sequence: number) => void;
}

export interface EventStreamHookOptions {
  url?: string;
  createSocket?: (url: string) => SocketLike;
  clock?: Clock;
  /** Where the last sequence is kept; default `sessionStorage`, `null` keeps nothing. */
  storage?: Pick<Storage, "getItem" | "setItem"> | null;
}

/** Reconnect delays in ms: 3, 4, 8, then 16 s for every later attempt. */
export const BACKOFF_MS: readonly number[] = [3_000, 4_000, 8_000, 16_000];
/** A connection open this long resets the backoff to its first step. */
export const STABLE_RESET_MS = 30_000;
/** Live events that arrive within this window are delivered as one batch. */
export const FLUSH_MS = 250;

/** `sessionStorage` key for the last delivered event sequence (per tab and origin). */
export const SEQUENCE_KEY = "hx-ws-sequence";

/** The stored sequence, or 0 when it is missing, not a positive integer, or unreadable. */
export function readSequence(storage: Pick<Storage, "getItem"> | null): number {
  try {
    const raw = storage?.getItem(SEQUENCE_KEY) ?? "";
    const value = /^[0-9]+$/.test(raw) ? Number(raw) : 0;
    return Number.isSafeInteger(value) ? value : 0;
  } catch {
    return 0;
  }
}

/** Save the sequence; a full or disabled storage only means the next load replays more. */
export function writeSequence(storage: Pick<Storage, "setItem"> | null, sequence: number): void {
  try {
    storage?.setItem(SEQUENCE_KEY, String(sequence));
  } catch {
    // ignore: the next page load replays from an older sequence
  }
}

function defaultStorage(): Pick<Storage, "getItem" | "setItem"> | null {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
}

/** `RUN_EVENT_INVALIDATES` families whose next key segment is the project. */
const BY_PROJECT = new Set(["task", "leaderboard", "views/query"]);

const CONNECTING = 0;

const realClock: Clock = {
  setTimeout: (fn, ms) => globalThis.setTimeout(fn, ms),
  clearTimeout: (handle) => globalThis.clearTimeout(handle as ReturnType<typeof setTimeout>),
};

/** Delay before reconnect attempt `attempt` (0-based). */
export function backoffDelay(attempt: number): number {
  const index = Math.min(Math.max(attempt, 0), BACKOFF_MS.length - 1);
  return BACKOFF_MS[index] ?? 16_000;
}

/**
 * Query keys to invalidate for one event. Only `run.*` events change query data.
 *
 * The families are `RUN_EVENT_INVALIDATES` (Task 4), narrowed where the key allows:
 * `["task" | "leaderboard", project]`, `["views", "query", project]`, `["run", runId]`
 * (prefix match, so `["run", id]` covers its metrics, logs, predictions and traces).
 */
export function keysForEvent(event: HxEvent): QueryKey[] {
  if (!event.type.startsWith("run.")) return [];
  const keys: QueryKey[] = [];
  for (const family of RUN_EVENT_INVALIDATES) {
    const id = family.join("/");
    if (id === "run") {
      if (event.run_id) keys.push([...family, event.run_id]);
    } else if (event.project && BY_PROJECT.has(id)) {
      keys.push([...family, event.project]);
    } else {
      keys.push([...family]);
    }
  }
  return keys;
}

/** Union of `keysForEvent` over a batch, without duplicates, in first-seen order. */
export function keysForEvents(events: readonly HxEvent[]): QueryKey[] {
  const seen = new Set<string>();
  const keys: QueryKey[] = [];
  for (const event of events) {
    for (const key of keysForEvent(event)) {
      const id = JSON.stringify(key);
      if (seen.has(id)) continue;
      seen.add(id);
      keys.push(key);
    }
  }
  return keys;
}

/** Invalidate every query a batch of events may have changed (active ones refetch). */
export function invalidateForEvents(client: QueryClient, events: readonly HxEvent[]): void {
  for (const queryKey of keysForEvents(events)) void client.invalidateQueries({ queryKey });
}

/** Connection supervisor for `/api/v1/ws` (one per app). */
export class EventStream {
  private readonly options: EventStreamOptions;
  private readonly clock: Clock;
  private readonly createSocket: (url: string) => SocketLike;
  private socket: SocketLike | null = null;
  private lastSequence: number;
  /** A stored sequence still to be confirmed by the server (see `resumeSequence`). */
  private anchor: number | null = null;
  private attempt = 0;
  private ready = false;
  private running = false;
  private pending: HxEvent[] = [];
  private reconnectTimer: unknown = null;
  private stableTimer: unknown = null;
  private flushTimer: unknown = null;

  constructor(options: EventStreamOptions) {
    this.options = options;
    this.clock = options.clock ?? realClock;
    this.createSocket = options.createSocket ?? ((url) => new WebSocket(url));
    const resume = options.resumeSequence ?? 0;
    if (options.afterSequence === undefined && resume > 0) {
      this.lastSequence = resume - 1;
      this.anchor = resume;
    } else {
      this.lastSequence = options.afterSequence ?? 0;
    }
  }

  /** Highest event sequence seen so far. */
  get sequence(): number {
    return this.lastSequence;
  }

  start(): void {
    if (this.running) return;
    this.running = true;
    this.connect();
  }

  stop(): void {
    this.running = false;
    this.cancel(this.reconnectTimer);
    this.cancel(this.stableTimer);
    this.cancel(this.flushTimer);
    this.reconnectTimer = null;
    this.stableTimer = null;
    this.flushTimer = null;
    this.pending = [];
    const socket = this.socket;
    this.socket = null;
    if (!socket) return;
    socket.onmessage = null;
    socket.onclose = null;
    socket.onerror = null;
    if (socket.readyState === CONNECTING) {
      // close() on a CONNECTING socket makes browsers log an error; close once it opens.
      socket.onopen = () => socket.close();
    } else {
      socket.onopen = null;
      socket.close();
    }
  }

  private cancel(handle: unknown): void {
    if (handle !== null) this.clock.clearTimeout(handle);
  }

  private setStatus(status: StreamStatus): void {
    this.options.onStatus?.(status);
  }

  private connect(): void {
    this.ready = false;
    this.setStatus("connecting");
    let socket: SocketLike;
    try {
      socket = this.createSocket(this.options.url);
    } catch {
      this.setStatus("offline");
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;
    socket.onopen = () => {
      if (socket !== this.socket) return;
      this.setStatus("connected");
      socket.send(JSON.stringify({ type: "subscribe", after_sequence: this.lastSequence }));
      this.stableTimer = this.clock.setTimeout(() => {
        this.stableTimer = null;
        this.attempt = 0;
      }, STABLE_RESET_MS);
    };
    socket.onmessage = (ev) => {
      if (socket === this.socket) this.handle(ev.data);
    };
    socket.onerror = () => {
      // A close event always follows an error; reconnecting happens there.
    };
    socket.onclose = () => {
      if (socket === this.socket) this.handleClose();
    };
  }

  private handleClose(): void {
    this.socket = null;
    this.ready = false;
    this.cancel(this.stableTimer);
    this.stableTimer = null;
    if (!this.running) return;
    this.setStatus("offline");
    this.scheduleReconnect();
  }

  /** The server lacks the stored sequence (another or a reset store): start over from 0. */
  private restartFromZero(): void {
    this.anchor = null;
    this.lastSequence = 0;
    this.pending = [];
    this.cancel(this.stableTimer);
    this.stableTimer = null;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onopen = null;
      socket.onmessage = null;
      socket.onclose = null;
      socket.onerror = null;
      socket.close();
    }
    this.connect();
  }

  private scheduleReconnect(): void {
    const delay = backoffDelay(this.attempt);
    this.attempt += 1;
    this.reconnectTimer = this.clock.setTimeout(() => {
      this.reconnectTimer = null;
      if (this.running) this.connect();
    }, delay);
  }

  private handle(data: unknown): void {
    let message: unknown;
    try {
      message = JSON.parse(String(data));
    } catch {
      return;
    }
    if (typeof message !== "object" || message === null) return;
    const msg = message as { type?: unknown; event?: Partial<HxEvent>; last_sequence?: unknown };
    if (msg.type === "event") {
      this.receive(msg.event);
    } else if (msg.type === "ready") {
      if (this.anchor !== null) {
        this.restartFromZero();
        return;
      }
      const last = typeof msg.last_sequence === "number" ? msg.last_sequence : this.lastSequence;
      this.markReady(last);
    } else if (msg.type === "error") {
      // The subscribe itself was rejected; retrying would repeat the same error.
      this.stop();
      this.setStatus("offline");
    }
  }

  private receive(event: Partial<HxEvent> | undefined): void {
    if (!event || typeof event.sequence !== "number" || typeof event.type !== "string") return;
    if (this.anchor !== null && event.sequence > this.lastSequence) {
      // First event after a resume: the stored one (seen on an earlier page) confirms it;
      // a higher one means it is gone, but every later event still arrives.
      const anchor = this.anchor;
      this.anchor = null;
      if (event.sequence === anchor) {
        this.lastSequence = anchor;
        return;
      }
    }
    if (event.sequence <= this.lastSequence) return;
    this.lastSequence = event.sequence;
    this.pending.push(event as HxEvent);
    if (this.ready && this.flushTimer === null) {
      this.flushTimer = this.clock.setTimeout(() => {
        this.flushTimer = null;
        this.flush();
        this.options.onSequence?.(this.lastSequence);
      }, FLUSH_MS);
    }
  }

  private markReady(lastSequence: number): void {
    this.ready = true;
    this.lastSequence = Math.max(this.lastSequence, lastSequence);
    this.setStatus("ready");
    this.flush();
    this.options.onSequence?.(this.lastSequence);
  }

  private flush(): void {
    if (this.pending.length === 0) return;
    const batch = this.pending;
    this.pending = [];
    this.options.onEvents(batch);
  }
}

/**
 * Subscribe to live events for the app's lifetime and invalidate affected queries.
 *
 * Call once (through `LiveUpdates`). Options are read on mount only (tests pass fakes).
 */
export function useEventStream(options: EventStreamHookOptions = {}): StreamStatus {
  const client = useQueryClient();
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const initial = useRef(options);
  useEffect(() => {
    const { url, createSocket, clock } = initial.current;
    const storage = initial.current.storage === undefined ? defaultStorage() : initial.current.storage;
    const stream = new EventStream({
      url: url ?? wsUrl(),
      onEvents: (events) => invalidateForEvents(client, events),
      onStatus: setStatus,
      onSequence: (sequence) => writeSequence(storage, sequence),
      resumeSequence: readSequence(storage),
      createSocket,
      clock,
    });
    stream.start();
    return () => stream.stop();
  }, [client]);
  return status;
}

/** Keeps the app's queries live; render once inside the `QueryClientProvider`. */
export function LiveUpdates(): null {
  useEventStream();
  return null;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd ui && bun test test/api/events.test.ts`
Expected: PASS, `24 pass`, `0 fail`.

- [ ] **Step 5: Mount the stream once, in the app entry**

`LiveUpdates` goes in `main.tsx`, next to the router rather than inside `AppShell`, so the route and shell tests (which render `AppShell` through `renderApp`) never open a socket.

In `ui/src/main.tsx` replace

```tsx
import { createQueryClient } from "./api/queries";
```

with

```tsx
import { LiveUpdates } from "./api/events";
import { createQueryClient } from "./api/queries";
```

and replace

```tsx
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
```

with

```tsx
    <QueryClientProvider client={queryClient}>
      <LiveUpdates />
      <RouterProvider router={router} />
    </QueryClientProvider>
```

Run: `cd ui && grep -rn "useEventStream()\|<LiveUpdates" src`
Expected: two hits: the `useEventStream();` line inside `LiveUpdates` in `src/api/events.ts`, and `<LiveUpdates />` in `src/main.tsx`.

- [ ] **Step 6: Type-check, run all unit tests, and build**

Run: `cd ui && bun test && bun run build`
Expected: all tests pass (the 24 new ones included), `0 fail`; the build prints Vite's
`✓ built in` line with no TypeScript errors.

- [ ] **Step 7: Commit**

```bash
git add ui/src/api/events.ts ui/test/api/events.test.ts ui/src/main.tsx
git commit -m "feat(ui): live updates over the event stream with replay and backoff"
```

### Task 43: Playwright harness on a demo home, with the Overview smoke test

**Files:**
- Create: `ui/playwright.config.ts`, `ui/e2e/paths.ts`, `ui/e2e/serve-demo.ts`,
  `ui/e2e/fixtures.ts`, `ui/e2e/tsconfig.json`, `ui/e2e/.gitignore`
- Test: `ui/e2e/pages.spec.ts`
- Modify: `ui/package.json` (dev dependencies, `e2e` script)

**Interfaces:**
- Consumes (backend plan): hidden CLI `hx --home <dir> demo --json` → `{kind: "project/task"}`
  for all five kinds; `hx --home <dir> serve --port <p>` serving `src/hypothex/ui_dist` with
  SPA fallback; `GET /.well-known/hypothex/environment` (readiness); `GET /api/v1/overview` →
  `OverviewSummary` with `headline` and `projects: [{project, task, ...}]`.
- Produces (used by Task 44–Task 46):
  - `ui/e2e/paths.ts`: `E2E_DIR`, `HOME_DIR`, `DEMO_FILE`, `REPO_ROOT`, `UI_DIST_INDEX`,
    `PORT` (default 7788, env `HX_E2E_PORT`), `KINDS` (the five kinds), `type Kind`.
  - `ui/e2e/fixtures.ts`: `test` (Playwright `test` with option fixture
    `theme: "light" | "dark"`, an auto fixture that fails the test on any console error
    or page error, and a `page` that starts with `localStorage["hx-theme"] = theme`),
    `expect`, `type Theme`, `type ThemeOptions`, `PAPER`, `expectTheme(page, theme)`,
    `demoTask(kind): {project, task}`, `getJson<T>(request, url)`,
    `postJson<T>(request, url, body)`, and response types `RunLite`, `ViewInfoLite`,
    `PanelLite`, `BoardLite`, `ExampleDiffLite`, `ProjectLite`, `OverviewLite`.
  - Playwright projects `light`, `dark` (read-only specs) and `light-edit`, `dark-edit`
    (`editor.spec.ts`, `live.spec.ts`; run after the read-only projects so saved views
    and notes never race the page checks).
  - `bun run e2e` = build, then Playwright.

- [ ] **Step 1: Write the failing test**

`ui/e2e/pages.spec.ts`:

```ts
import { expect, expectTheme, getJson, type OverviewLite, test } from "./fixtures";

test("overview shows the headline and every demo project", async ({ page, request, theme }) => {
  const summary = await getJson<OverviewLite>(request, "/api/v1/overview");
  expect(summary.projects.length).toBeGreaterThanOrEqual(5);
  await page.goto("/");
  await expectTheme(page, theme);
  await expect(page.getByText(summary.headline).first()).toBeVisible();
  for (const row of summary.projects) {
    await expect(page.getByText(row.project).first()).toBeVisible();
  }
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd ui && bunx playwright test`
Expected: FAIL while loading `e2e/pages.spec.ts`: `Cannot find module '@playwright/test'`
(not installed yet) or `Cannot find module './fixtures'` (installed, harness not written).

- [ ] **Step 3: Install Playwright and write the harness**

Run: `cd ui && bun add -d @playwright/test @types/node && bunx playwright install chromium`
Expected: `bun add` lists `@playwright/test` and `@types/node` under devDependencies;
the install ends with `Chromium ... downloaded` (or nothing if already present).

In `ui/package.json`, add to `"scripts"` (keep the existing entries):

```json
    "e2e": "bun run build && playwright test"
```

`ui/e2e/paths.ts`:

```ts
/** Paths and constants shared by the Playwright config, the demo server, and the specs. */
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const E2E_DIR = fileURLToPath(new URL(".", import.meta.url));
/** Fresh Hypothex home, wiped and re-seeded on every server start. */
export const HOME_DIR = join(E2E_DIR, ".home");
/** `hx demo --json` output: `{kind: "project/task"}`. */
export const DEMO_FILE = join(E2E_DIR, ".demo.json");
export const REPO_ROOT = resolve(E2E_DIR, "..", "..");
export const UI_DIST_INDEX = join(REPO_ROOT, "src", "hypothex", "ui_dist", "index.html");
export const PORT = Number(process.env.HX_E2E_PORT ?? "7788");
export const KINDS = [
  "generic",
  "training",
  "agent_eval",
  "agent_iteration",
  "system_bench",
] as const;
export type Kind = (typeof KINDS)[number];
```

`ui/e2e/serve-demo.ts`:

```ts
/**
 * Playwright `webServer` command: seed a fresh demo home, then serve it.
 *
 * Wipes `e2e/.home`, runs `hx demo --json` into it, writes the kind → "project/task" map
 * to `e2e/.demo.json`, then runs `hx serve` in the foreground until Playwright stops it.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { DEMO_FILE, HOME_DIR, PORT, REPO_ROOT, UI_DIST_INDEX } from "./paths";

if (!existsSync(UI_DIST_INDEX)) {
  console.error(`missing ${UI_DIST_INDEX}: run "bun run build" in ui/ first`);
  process.exit(1);
}
rmSync(HOME_DIR, { recursive: true, force: true });
mkdirSync(HOME_DIR, { recursive: true });

const hx = ["run", "--project", REPO_ROOT, "hx", "--home", HOME_DIR];
const seeded = spawnSync("uv", [...hx, "demo", "--json"], {
  cwd: REPO_ROOT,
  encoding: "utf8",
  stdio: ["ignore", "pipe", "inherit"],
});
if (seeded.status !== 0) {
  console.error(`hx demo failed with exit code ${seeded.status}`);
  process.exit(1);
}
writeFileSync(DEMO_FILE, seeded.stdout);

const server = spawn("uv", [...hx, "serve", "--port", String(PORT)], {
  cwd: REPO_ROOT,
  stdio: "inherit",
});
const stop = (): void => {
  server.kill("SIGTERM");
};
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
server.on("exit", (code) => process.exit(code ?? 0));
```

`ui/e2e/fixtures.ts`:

```ts
/** Shared Playwright fixtures: theme per project, console-error guard, API helpers. */
import { readFileSync } from "node:fs";
import { type APIRequestContext, test as base, expect, type Page } from "@playwright/test";
import { DEMO_FILE, type Kind } from "./paths";

export { expect };

export type Theme = "light" | "dark";
export interface ThemeOptions {
  theme: Theme;
}

/** `--paper` from docs/mockups/ui-v4/index.html: #F6F7F3 (light), #12161C (dark). */
export const PAPER: Record<Theme, string> = {
  light: "rgb(246, 247, 243)",
  dark: "rgb(18, 22, 28)",
};

export interface RunLite {
  run_id: string;
  hypothesis: string;
  status: string;
}
export interface ViewInfoLite {
  name: string;
  title: string;
  origin: "preset" | "inline" | "file";
  path: string | null;
}
export interface PanelLite {
  type: string;
  title: string;
}
export interface BoardLite {
  headline: string;
  kind: string;
  primary: string;
  rows: { group_id: string; latest_run_id: string }[];
}
export interface ExampleDiffLite {
  fixed: string[];
  broken: string[];
  both_pass: number;
  both_fail: number;
}
export interface ProjectLite {
  project: string;
  repo: string;
}
export interface OverviewLite {
  headline: string;
  projects: { project: string; task: string }[];
}

interface Fixtures {
  consoleErrors: string[];
}

export const test = base.extend<ThemeOptions & Fixtures>({
  theme: ["light", { option: true }],
  page: async ({ page, theme }, use) => {
    await page.addInitScript((value) => {
      window.localStorage.setItem("hx-theme", value);
    }, theme);
    await use(page);
  },
  consoleErrors: [
    async ({ page }, use) => {
      const errors: string[] = [];
      page.on("console", (message) => {
        if (message.type() === "error") errors.push(message.text());
      });
      page.on("pageerror", (error) => {
        errors.push(`pageerror: ${error.message}`);
      });
      await use(errors);
      expect(errors, "browser console errors").toEqual([]);
    },
    { auto: true },
  ],
});

/** The page is in `theme`: attribute set and the paper colour applied. */
export async function expectTheme(page: Page, theme: Theme): Promise<void> {
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator("body")).toHaveCSS("background-color", PAPER[theme]);
}

/** Project and task that `hx demo` seeded for `kind` (read after the server started). */
export function demoTask(kind: Kind): { project: string; task: string } {
  const seeded = JSON.parse(readFileSync(DEMO_FILE, "utf8")) as Record<string, string>;
  const ref = seeded[kind];
  if (!ref || !ref.includes("/")) throw new Error(`hx demo did not seed kind ${kind}`);
  const slash = ref.indexOf("/");
  return { project: ref.slice(0, slash), task: ref.slice(slash + 1) };
}

export async function getJson<T>(request: APIRequestContext, url: string): Promise<T> {
  const response = await request.get(url);
  expect(response.status(), `GET ${url}`).toBe(200);
  return (await response.json()) as T;
}

export async function postJson<T>(
  request: APIRequestContext,
  url: string,
  body: unknown,
): Promise<T> {
  const response = await request.post(url, { data: body });
  expect(response.status(), `POST ${url}`).toBe(200);
  return (await response.json()) as T;
}
```

`ui/playwright.config.ts`:

```ts
import { defineConfig, devices } from "@playwright/test";
import type { ThemeOptions } from "./e2e/fixtures";
import { PORT } from "./e2e/paths";

const WRITES = /(editor|live)\.spec\.ts$/;

export default defineConfig<ThemeOptions>({
  testDir: "./e2e",
  outputDir: "./e2e/.results",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI
    ? [["list"], ["html", { outputFolder: "./e2e/.report", open: "never" }]]
    : [["list"]],
  expect: { timeout: 10_000 },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    {
      name: "light",
      testIgnore: WRITES,
      use: { ...devices["Desktop Chrome"], colorScheme: "light", theme: "light" },
    },
    {
      name: "dark",
      testIgnore: WRITES,
      use: { ...devices["Desktop Chrome"], colorScheme: "dark", theme: "dark" },
    },
    {
      name: "light-edit",
      testMatch: WRITES,
      dependencies: ["light", "dark"],
      use: { ...devices["Desktop Chrome"], colorScheme: "light", theme: "light" },
    },
    {
      name: "dark-edit",
      testMatch: WRITES,
      dependencies: ["light", "dark"],
      use: { ...devices["Desktop Chrome"], colorScheme: "dark", theme: "dark" },
    },
  ],
  webServer: {
    command: "bun e2e/serve-demo.ts",
    url: `http://127.0.0.1:${PORT}/.well-known/hypothex/environment`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: "pipe",
    stderr: "pipe",
  },
});
```

`ui/e2e/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "lib": ["ES2022", "DOM"],
    "types": ["node"],
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true
  },
  "include": ["./*.ts", "../playwright.config.ts"]
}
```

`ui/e2e/.gitignore`:

```
.home/
.demo.json
.results/
.report/
```

Leave `ui/bunfig.toml` as Task 1 wrote it: `root = "./test"` already keeps `bun test` out of `e2e/`, where Bun would otherwise pick up `*.spec.ts` and run Playwright files under Bun.

- [ ] **Step 4: Check that `bun test` still finds every unit test and no e2e spec**

Run: `cd ui && find . -path ./node_modules -prune -o \( -name '*.test.ts' -o -name '*.test.tsx' \) -print | grep -v '^./test/'`
Expected: no output (every unit test lives under `test/`, so `root = "./test"` loses none).

Run: `cd ui && bun test 2>&1 | grep -c 'e2e/'`
Expected: `0`.

- [ ] **Step 5: Type-check the harness, build, and run the test**

Run: `cd ui && bunx tsc -p e2e/tsconfig.json && bun run e2e`
Expected: `tsc` prints nothing; the build prints `✓ built in`; Playwright prints
`2 passed` (`[light] › pages.spec.ts › overview ...` and `[dark] › ...`).

- [ ] **Step 6: Commit**

```bash
git add ui/playwright.config.ts ui/e2e ui/package.json ui/bun.lock
git commit -m "test(ui): playwright harness on a seeded demo home with overview smoke test"
```

### Task 44: Smoke tests for every page and every kind preset, light and dark

**Files:**
- Modify: `ui/e2e/pages.spec.ts`

**Interfaces:**
- Consumes: Task 43 fixtures (`test`, `expect`, `expectTheme`, `demoTask`, `getJson`,
  `postJson`, `RunLite`, `ViewInfoLite`, `PanelLite`, `BoardLite`, `ExampleDiffLite`),
  `KINDS` from `ui/e2e/paths.ts`; API: `GET /api/v1/tasks/{p}/{t}/leaderboard`
  (`headline`, `kind`, `primary`, `rows[].latest_run_id`), `GET .../views`
  (`list[ViewInfo]`, `overview` first), `POST .../views/query` with `{name: "overview"}`
  → `{panels: [PanelResult]}`, `GET .../kind` → `{kind, run_view: [PanelSpec]}`,
  `GET /api/v1/runs?project=&task=&status=finished&limit=1`,
  `GET /api/v1/compare/examples?a=&b=&metric=` → `ExampleDiff`. Routes `/t/:project/:task`,
  `/t/:project/:task/edit/:view`, `/r/:runId`, `/x/:a/:b?metric=`.
- Produces: 13 tests per theme project (Overview, 5 Task, 5 Run, Examples, Editor).

- [ ] **Step 1: Write the tests**

Replace `ui/e2e/pages.spec.ts` with:

```ts
import {
  type BoardLite,
  demoTask,
  type ExampleDiffLite,
  expect,
  expectTheme,
  getJson,
  type OverviewLite,
  type PanelLite,
  postJson,
  type RunLite,
  test,
  type ViewInfoLite,
} from "./fixtures";
import { KINDS } from "./paths";

test("overview shows the headline and every demo project", async ({ page, request, theme }) => {
  const summary = await getJson<OverviewLite>(request, "/api/v1/overview");
  expect(summary.projects.length).toBeGreaterThanOrEqual(5);
  await page.goto("/");
  await expectTheme(page, theme);
  await expect(page.getByText(summary.headline).first()).toBeVisible();
  for (const row of summary.projects) {
    await expect(page.getByText(row.project).first()).toBeVisible();
  }
});

for (const kind of KINDS) {
  test(`task page renders the ${kind} preset`, async ({ page, request, theme }) => {
    const { project, task } = demoTask(kind);
    const api = `/api/v1/tasks/${project}/${task}`;
    const board = await getJson<BoardLite>(request, `${api}/leaderboard`);
    expect(board.kind).toBe(kind);
    const views = await getJson<ViewInfoLite[]>(request, `${api}/views`);
    expect(views[0]?.name).toBe("overview");
    const query = await postJson<{ panels: PanelLite[] }>(request, `${api}/views/query`, {
      name: "overview",
    });
    expect(query.panels.length).toBeGreaterThan(0);

    await page.goto(`/t/${project}/${task}`);
    await expectTheme(page, theme);
    await expect(page.getByText(board.headline).first()).toBeVisible();
    const tabs = page.getByRole("navigation", { name: "Views" });
    await expect(tabs).toBeVisible();
    for (const view of views) {
      await expect(tabs.getByRole("link", { name: view.title }).first()).toBeVisible();
    }
    await expect(tabs.locator('a[aria-current="page"]')).toContainText(views[0]?.title ?? "");
    for (const panel of query.panels) {
      if (!panel.title) continue;
      await expect(page.getByRole("heading", { name: panel.title }).first()).toBeVisible();
    }
    await expect(page.getByRole("link", { name: "+ view" })).toHaveAttribute(
      "href",
      `/t/${project}/${task}/edit/new`,
    );
  });

  test(`run page renders the ${kind} run detail`, async ({ page, request, theme }) => {
    const { project, task } = demoTask(kind);
    const runs = await getJson<RunLite[]>(
      request,
      `/api/v1/runs?project=${project}&task=${task}&status=finished&limit=1`,
    );
    const run = runs[0];
    if (!run) throw new Error(`demo ${kind} has no finished run`);
    const layout = await getJson<{ kind: string; run_view: PanelLite[] }>(
      request,
      `/api/v1/tasks/${project}/${task}/kind`,
    );
    expect(layout.kind).toBe(kind);

    await page.goto(`/r/${run.run_id}`);
    await expectTheme(page, theme);
    await expect(page.getByText(run.hypothesis || run.run_id).first()).toBeVisible();
    for (const panel of layout.run_view) {
      if (!panel.title) continue;
      await expect(page.getByRole("heading", { name: panel.title }).first()).toBeVisible();
    }
  });
}

test("examples page compares the two best generic groups", async ({ page, request, theme }) => {
  const { project, task } = demoTask("generic");
  const board = await getJson<BoardLite>(request, `/api/v1/tasks/${project}/${task}/leaderboard`);
  const best = board.rows[0]?.latest_run_id;
  const second = board.rows[1]?.latest_run_id;
  if (!best || !second) throw new Error("generic demo needs at least two seed groups");
  const metric = board.primary.split("/")[0] ?? board.primary;
  const diff = await getJson<ExampleDiffLite>(
    request,
    `/api/v1/compare/examples?a=${second}&b=${best}&metric=${encodeURIComponent(metric)}`,
  );
  expect(diff.broken.length).toBeGreaterThan(0);

  await page.goto(`/x/${second}/${best}?metric=${encodeURIComponent(metric)}`);
  await expectTheme(page, theme);
  await expect(page.getByText(/\bp [=<] /).first()).toBeVisible();
  // The broken ids themselves are not all visible: the errors table shows only the first 8
  // of B's failures in predictions-file order, and the strip keeps ids in SVG <title>s.
  // The headline and the 2×2 outcome table show the counts, so check those.
  await expect(page.getByRole("heading", { level: 1 })).toContainText(
    `fixes ${diff.fixed.length}, breaks ${diff.broken.length}`,
  );
  const outcomes = page.locator("table.ot");
  await expect(outcomes.locator("td.fx .n")).toHaveText(String(diff.fixed.length));
  await expect(outcomes.locator("td.bk .n")).toHaveText(String(diff.broken.length));
  await expect(outcomes.locator("td.same .n")).toHaveText([String(diff.both_pass), String(diff.both_fail)]);
});

test("view editor opens with a YAML editor and preview", async ({ page, theme }) => {
  const { project, task } = demoTask("generic");
  await page.goto(`/t/${project}/${task}/edit/new`);
  await expectTheme(page, theme);
  await expect(page.locator(".cm-editor")).toBeVisible();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeVisible();
});
```

- [ ] **Step 2: Run the tests**

Run: `cd ui && bun run build && bunx playwright test e2e/pages.spec.ts`
Expected: `26 passed` (13 in `[light]`, 13 in `[dark]`). These pages exist from Tasks 1–41, so
this suite is a regression net, not red-first. A failure here is a real defect: read the
trace (`bunx playwright show-trace e2e/.results/<test>/trace.zip`), fix it in the
owning page or panel file with superpowers:systematic-debugging, and rerun. Do not
loosen an assertion to make it pass.

- [ ] **Step 3: Commit**

```bash
git add ui/e2e/pages.spec.ts
git commit -m "test(ui): smoke every page and every kind preset in light and dark"
```

### Task 45: Editor round trip — a saved view is a file and a tab

**Files:**
- Create: `ui/e2e/editor.spec.ts`

**Interfaces:**
- Consumes: Task 43 fixtures (`test`, `expect`, `expectTheme`, `demoTask`, `getJson`,
  `ViewInfoLite`, `ProjectLite`); the editor DOM listed in the Part 6 intro; API
  `PUT /api/v1/tasks/{p}/{t}/views/{name}` (sent by the editor), `GET .../views/{name}` →
  `{info: ViewInfo, text, view}`, `GET .../views`, `DELETE .../views/{name}`,
  `GET /api/v1/projects` → `[{project, repo, ...}]`. Contract 1.4: file views live at
  `<repo>/.hypothex/views/<task>/<name>.yaml`.
- Produces: 2 tests per edit project (`light-edit`, `dark-edit`).

- [ ] **Step 1: Write the tests**

`ui/e2e/editor.spec.ts`:

```ts
import { readFileSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import type { Page } from "@playwright/test";
import {
  demoTask,
  expect,
  expectTheme,
  getJson,
  type ProjectLite,
  test,
  type ViewInfoLite,
} from "./fixtures";

function viewYaml(title: string): string {
  return [
    `title: ${title}`,
    "panels:",
    "  - type: markdown",
    "    title: note",
    `    text: round trip ${title}`,
    "  - type: leaderboard",
    "    title: board",
    "",
  ].join("\n");
}

/** Replace the whole CodeMirror document in one input event (no auto-indent per key). */
async function replaceEditorText(page: Page, text: string): Promise<void> {
  await page.locator(".cm-content").click();
  await page.keyboard.press("ControlOrMeta+a");
  await page.keyboard.insertText(text);
}

test("a view saved in the editor is written to disk and shows as a tab", async ({
  page,
  request,
  theme,
}) => {
  const { project, task } = demoTask("generic");
  const name = `e2e-${theme}`;
  const title = `e2e ${theme}`;
  const text = viewYaml(title);
  const api = `/api/v1/tasks/${project}/${task}/views/${name}`;
  try {
    await page.goto(`/t/${project}/${task}/edit/new`);
    await expectTheme(page, theme);
    await page.getByLabel(/^name$/i).fill(name);
    await replaceEditorText(page, text);
    const save = page.getByRole("button", { name: "Save", exact: true });
    await expect(save).toBeEnabled();
    const [put] = await Promise.all([
      page.waitForResponse(
        (response) => response.request().method() === "PUT" && response.url().endsWith(api),
      ),
      save.click(),
    ]);
    expect(put.status()).toBe(200);

    const stored = await getJson<{ info: ViewInfoLite; text: string }>(request, api);
    expect(stored.info).toMatchObject({ name, title, origin: "file" });
    expect(stored.text).toBe(text);
    const projects = await getJson<ProjectLite[]>(request, "/api/v1/projects");
    const repo = projects.find((p) => p.project === project)?.repo;
    if (!repo) throw new Error(`project ${project} not registered`);
    const file = join(repo, ".hypothex", "views", task, `${name}.yaml`);
    const reported = stored.info.path ?? "";
    expect(isAbsolute(reported) ? reported : join(repo, reported)).toBe(file);
    expect(readFileSync(file, "utf8")).toBe(text);

    await page.goto(`/t/${project}/${task}`);
    const tab = page.getByRole("navigation", { name: "Views" }).getByRole("link", { name: title });
    await expect(tab).toBeVisible();
    await tab.click();
    await expect(tab).toHaveAttribute("aria-current", "page");
    await expect(page).toHaveURL(new RegExp(`[?&]view=${name}(&|$)`));
    await expect(page.getByText(`round trip ${title}`)).toBeVisible();
  } finally {
    await request.delete(api);
  }
});

test("an invalid view blocks Save and is never written", async ({ page, request, theme }) => {
  const { project, task } = demoTask("generic");
  const name = `e2e-bad-${theme}`;
  await page.goto(`/t/${project}/${task}/edit/new`);
  await expectTheme(page, theme);
  await page.getByLabel(/^name$/i).fill(name);
  await replaceEditorText(page, ["title: bad", "panels:", "  - type: leaderbord", ""].join("\n"));
  await expect(page.locator(".cm-lint-marker-error").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Save", exact: true })).toBeDisabled();
  const views = await getJson<ViewInfoLite[]>(request, `/api/v1/tasks/${project}/${task}/views`);
  expect(views.map((v) => v.name)).not.toContain(name);
});
```

- [ ] **Step 2: Run the tests**

Run: `cd ui && bun run build && bunx playwright test e2e/editor.spec.ts`
Expected: `4 passed` (2 in `[light-edit]`, 2 in `[dark-edit]`; Playwright runs the
`light` and `dark` projects first as dependencies, so the full line reads `30 passed`).
A failure is a defect in the editor (Tasks 38–41) or the views API (backend plan): fix it there with
superpowers:systematic-debugging; do not weaken the test.

- [ ] **Step 3: Commit**

```bash
git add ui/e2e/editor.spec.ts
git commit -m "test(ui): editor round trip saves a view file that shows as a tab"
```

### Task 46: Live update end to end — a note appears without a reload

**Files:**
- Create: `ui/e2e/live.spec.ts`

**Interfaces:**
- Consumes: Task 42 `LiveUpdates` mounted in `main.tsx`; Task 43 fixtures; API
  `POST /api/v1/runs/{id}/notes` with `{text, author}` (emits `run.note_added`), run
  notes shown on `/r/:runId` under a `["run", runId, ...]` query.
- Produces: 1 test per edit project.

- [ ] **Step 1: Write the test**

`ui/e2e/live.spec.ts`:

```ts
import { demoTask, expect, expectTheme, getJson, type RunLite, test } from "./fixtures";

test("a note added through the API appears on the open run page without a reload", async ({
  page,
  request,
  theme,
}) => {
  const sent: string[] = [];
  const received: string[] = [];
  page.on("websocket", (socket) => {
    if (!socket.url().endsWith("/api/v1/ws")) return;
    socket.on("framesent", (frame) => sent.push(String(frame.payload)));
    socket.on("framereceived", (frame) => received.push(String(frame.payload)));
  });

  const { project, task } = demoTask("generic");
  const runs = await getJson<RunLite[]>(
    request,
    `/api/v1/runs?project=${project}&task=${task}&status=finished&limit=1`,
  );
  const run = runs[0];
  if (!run) throw new Error("generic demo has no finished run");

  await page.goto(`/r/${run.run_id}`);
  await expectTheme(page, theme);
  await expect(page.getByText(run.hypothesis || run.run_id).first()).toBeVisible();
  await expect.poll(() => received.some((m) => m.includes('"type":"ready"'))).toBe(true);
  expect(sent[0]).toBe('{"type":"subscribe","after_sequence":0}');
  await page.evaluate(() => {
    (window as unknown as { hxNoReload?: boolean }).hxNoReload = true;
  });

  const text = `live note ${theme} ${Date.now()}`;
  const response = await request.post(`/api/v1/runs/${run.run_id}/notes`, {
    data: { text, author: "e2e" },
  });
  expect(response.status()).toBe(200);

  await expect(page.getByText(text)).toBeVisible();
  expect(received.some((m) => m.includes('"type":"run.note_added"'))).toBe(true);
  const stillSamePage = await page.evaluate(
    () => (window as unknown as { hxNoReload?: boolean }).hxNoReload === true,
  );
  expect(stillSamePage).toBe(true);
});
```

- [ ] **Step 2: Run the test**

Run: `cd ui && bun run build && bunx playwright test e2e/live.spec.ts`
Expected: `2 passed` for `[light-edit]` and `[dark-edit]` (the full line reads
`28 passed` with the dependency projects). If the note never shows, check that
`<LiveUpdates />` is mounted (Task 42 Step 5) and that the Run page reads the run through
`useRun` (key `["run", runId]`).

- [ ] **Step 3: Commit**

```bash
git add ui/e2e/live.spec.ts
git commit -m "test(ui): live event stream refreshes an open run page"
```

### Task 47: CI job for the UI

**Files:**
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `ui/bun.lock`, `bun test` (Tasks 1–42), `bun run build` (Task 1),
  `bunx tsc -p e2e/tsconfig.json` and `bunx playwright test` (Task 43–Task 46),
  `uv sync` for `hx demo` / `hx serve`.
- Produces: job `ui` next to the existing `test` job.

- [ ] **Step 1: Write the failing check**

Run:

```bash
uv run python -c "
import yaml
wf = yaml.safe_load(open('.github/workflows/ci.yml'))
steps = wf['jobs']['ui']['steps']
print([s.get('name') or s.get('uses') for s in steps])
"
```

Expected: FAIL with `KeyError: 'ui'`.

- [ ] **Step 2: Add the job**

Replace `.github/workflows/ci.yml` with:

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, macos-latest]
        python: ["3.11", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: ${{ matrix.python }}
      - run: uv sync --all-groups
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run ty check src
      - run: uv run pytest -q
      - run: uv run sphinx-build -b html docs docs/_build/html

  ui:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: ui
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
        with:
          python-version: "3.13"
      - uses: oven-sh/setup-bun@v2
        with:
          bun-version: "1.3.10"
      - name: Install Python package
        working-directory: .
        run: uv sync
      - name: Install UI dependencies
        run: bun install --frozen-lockfile
      - name: Unit tests
        run: bun test
      - name: Build
        run: bun run build
      - name: Type-check e2e
        run: bunx tsc -p e2e/tsconfig.json
      - name: Install Chromium
        run: bunx playwright install --with-deps chromium
      - name: Playwright smoke tests
        run: bunx playwright test
      - name: Upload Playwright report
        if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-report
          path: |
            ui/e2e/.report
            ui/e2e/.results
          retention-days: 7
```

- [ ] **Step 3: Run the check to verify it passes**

Run the Step 1 command again.
Expected output:

```
['actions/checkout@v4', 'astral-sh/setup-uv@v6', 'oven-sh/setup-bun@v2', 'Install Python package', 'Install UI dependencies', 'Unit tests', 'Build', 'Type-check e2e', 'Install Chromium', 'Playwright smoke tests', 'Upload Playwright report']
```

- [ ] **Step 4: Run the job's commands locally, in order, from a clean state**

Run: `uv sync && cd ui && rm -rf node_modules e2e/.home e2e/.demo.json && bun install --frozen-lockfile && bun test && bun run build && bunx tsc -p e2e/tsconfig.json && CI=1 bunx playwright test`
Expected: `bun install` succeeds with no lockfile change; `bun test` ends `0 fail`;
build prints `✓ built in`; `tsc` prints nothing; Playwright prints `32 passed`
(26 read-only + 4 editor + 2 live) and no `failed` or `flaky` line. `CI=1` makes
Playwright start its own server (no reuse) and forbid `test.only`.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add ui job with bun tests, build, and playwright smoke tests"
```

### Task 48: Sphinx docs page for the UI

**Files:**
- Create: `docs/ui.rst`
- Modify: `docs/index.rst` (toctree entry `ui`, after the backend plan's `views`)
- Test: `tests/test_docs_ui.py`

**Interfaces:**
- Consumes: the screens and routes of Tasks 6–41, `bun run dev|build` and `HX_API` (Task 1),
  `bunx playwright test` and `HX_E2E_PORT` (Task 43), the live stream (Task 42), the backend
  plan's `docs/index.rst` toctree (with `views`) and `hx serve` (serves `src/hypothex/ui_dist/`
  when it exists, else the API only).
- Produces: a `Web UI` docs page in the toctree: the screens and their URLs, how to build
  the UI before packaging, the dev server and its proxy, and the unit and e2e tests.

- [ ] **Step 1: Write the failing test**

`tests/test_docs_ui.py`:

```python
"""The Web UI docs page is in the toctree and names what a user needs."""

from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"


def test_ui_page_is_in_toctree_after_views() -> None:
    index = (DOCS / "index.rst").read_text()
    assert "   views\n   ui\n" in index


def test_ui_page_covers_screens_build_dev_and_e2e() -> None:
    page = (DOCS / "ui.rst").read_text()
    for screen in ("Overview", "Task", "Run", "Examples", "View editor"):
        assert f"**{screen}**" in page, screen
    for route in ("/t/<project>/<task>?view=<name>", "/r/<run_id>", "/x/<a>/<b>?metric=<name>"):
        assert route in page, route
    for command in (
        "hx serve",
        "bun run build",
        "uv build",
        "bun run dev",
        "HX_API",
        "bun test",
        "bunx playwright test",
        "HX_E2E_PORT",
    ):
        assert command in page, command
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_docs_ui.py -v`
Expected: FAIL: `test_ui_page_is_in_toctree_after_views` with `AssertionError` (no `ui` entry yet) and `test_ui_page_covers_screens_build_dev_and_e2e` with `FileNotFoundError: ... docs/ui.rst`.

- [ ] **Step 3: Write the page**

Create `docs/ui.rst`:

```rst
Web UI
======

``hx serve`` serves the web UI and the API on the same port (default
``http://127.0.0.1:7777``). The UI reads everything through ``/api/v1`` and stays live
over the ``/api/v1/ws`` event stream: a new run, score, note or status change refreshes
the page you are looking at, without a reload.

.. code-block:: bash

   uv run hx serve

Screens
-------

- **Overview** (``/``): one-line status, runs by launcher, ideas, running runs, recent
  failures (with ``Open stderr``), and projects.
- **Task** (``/t/<project>/<task>?view=<name>``): the task's views as tabs. ``overview``
  is the preset for the task kind; every other tab is a saved view (see :doc:`views`).
  ``+ view`` opens the view editor.
- **Run** (``/r/<run_id>``): the hypothesis as title, status, stat strip, the task kind's
  run panels, where everything is (code, data, run folder, logs, predictions,
  checkpoints), scores by metric version, notes, and actions. ``?log=stderr`` opens a log
  tail; ``?example=<id>`` picks a traced example on agent tasks.
- **Examples** (``/x/<a>/<b>?metric=<name>``): what run B fixes and breaks against run A,
  with the paired sign test.
- **View editor** (``/t/<project>/<task>/edit/<view>``, ``new`` for a new view): YAML on
  the left with inline validation, a live preview on the right, then Save (writes
  ``.hypothex/views/<task>/<name>.yaml``) or Copy as CLI.

Press ``⌘K`` (``Ctrl K`` on Linux and Windows) to find a run, task or path. The
colour-mode button in the header switches light and dark mode.

Build before packaging
----------------------

The built UI lives in ``src/hypothex/ui_dist/``, which git ignores. Build it before you
build the wheel, so the wheel ships it:

.. code-block:: bash

   cd ui && bun install && bun run build && cd ..
   uv build

Without ``ui_dist``, ``hx serve`` serves the API only, and the wheel has no UI.

Develop
-------

.. code-block:: bash

   uv run hx serve                 # API on 127.0.0.1:7777
   cd ui && bun run dev            # http://localhost:5173

The Vite dev server reloads on save and proxies ``/api`` (HTTP and WebSocket) to
``hx serve``. Set ``HX_API=http://host:port`` to proxy to another server.

Test
----

.. code-block:: bash

   cd ui
   bun test                        # unit and component tests
   bun run build                   # the smoke tests use the built UI
   bunx playwright install chromium    # once
   bunx playwright test            # smoke tests, light and dark

``bunx playwright test`` seeds a fresh demo home in ``ui/e2e/.home`` with ``hx demo``
and serves it with ``hx serve`` on port 7788 (``HX_E2E_PORT`` changes it), so it never
touches your own ``~/.hypothex``.
```

In `docs/index.rst`, change the toctree (the backend plan left `views` after `cli`) to:

```rst
.. toctree::
   :maxdepth: 2

   quickstart
   project_file
   cli
   views
   ui
   sdk
   agents
   architecture
```

- [ ] **Step 4: Run the test and build the docs**

Run: `uv run pytest tests/test_docs_ui.py -v`
Expected: PASS (2 tests).

Run: `uv run sphinx-build -b html docs docs/_build/html 2>&1 | grep -E "(ui|index)\.rst.*(WARNING|ERROR)" | wc -l`
Expected: `0`.

Run: `test -f docs/_build/html/ui.html && grep -c "Build before packaging" docs/_build/html/ui.html`
Expected: `1` or more (the page was built with its sections).

- [ ] **Step 5: Commit**

```bash
git add docs/ui.rst docs/index.rst tests/test_docs_ui.py
git commit -m "docs: add web UI page (screens, build, dev server, tests)"
```

## Assembly notes

This plan was assembled from six part drafts (Parts 1–6 above). Where parts disagreed, the contract decided; where the contract is silent, the owner of the shared piece (usually Part 1, the scaffold) decided.

1. **Test location.** Part 1 put tests in `ui/test/` (`bunfig.toml` `root = "./test"`), Parts 2, 3, 5 and 6 put them next to the source, Part 4 used `ui/tests/`, and Part 6 changed the root to `src`. With Part 1's root, colocated tests would never run. The contract is silent, so Part 1's layout wins: every unit test lives in `ui/test/` mirroring `ui/src/`, imports point at `../../src/...`, and Part 6 no longer edits `bunfig.toml` (`./test` already keeps `e2e/*.spec.ts` out of `bun test`).
2. **One data layer.** Part 4 had its own client, shapes and query keys (`["runs", id]`, `["views/query", ...]`), Part 5 its own fetch helper and `ApiError`, and Part 6 its own key roots (`view-query`, `compare`), `wsUrl` and `HxEvent`. Contract 4 requires the event stream to invalidate the pages' query keys; with three key schemes a `run.*` event would refresh none of the pages. Tasks 3–4 are now the only client, models and keys; Task 21 was rewritten to re-export the models; pages and the editor call `api.*` and the hooks; Task 42 derives its keys from `RUN_EVENT_INVALIDATES`, which gained the `task` and `compareExamples` families.
3. **Panel registry.** Part 4 imported `panelRegistry`, Part 5 `PANELS`; Part 2 exports `PANELS` at the contract's path, so `PANELS` wins. No part registered the Part 3 panels; Task 20 now does, with a completeness test. Part 4's `PanelBody` uses Part 2's `PanelBoundary` and `PanelError`, so its unknown-type message is `Unknown panel type: <type>`, and the editor preview draws through `PanelBody`.
4. **Row and panel types.** Part 3 typed panels with `components["schemas"]["PanelResult"]` from the generated file, but the routes return plain dicts (Part 1), so that schema may not exist. Part 3 now imports `PanelResult` from `panels/index.ts`. Row types in Parts 2, 3 and 5 are aliases of the Task 3 models. Part 4's fixtures gained the fields the models require (`environment_id`, `executor`, `hash_mode`, `checked_at`, `config_hash`, `within_noise_of_best`, and `TaskDetail.dataset/metrics/stages`); `gitLine` takes a `GitState` whose untracked fields may be missing on older runs.
5. **Theme.** Part 3 had a second `useTheme` (a `MutationObserver` on `data-theme`). It now uses Task 5's hook, and its test flips the mode with `setTheme`, the function the header toggle and the palette call.
6. **p-values.** Part 2 printed two decimals always (so `0.004` became `0.00`); Part 4 printed three decimals below 0.01. Contract 1.8 says "`p = 0.15` two decimals (`p < 0.001` when tiny)" and does not cover 0.001–0.01; the backend plan's `fmt_p` prints three decimals there. The UI follows the backend so headlines and panels agree: Part 2's `fmtP` gained the three-decimal branch and Part 4's `fmtP` is built on it.
7. **Missing values.** Part 4 used `–`, Parts 2 and 3 used `—`. All now use `—`; `–` stays the interval separator (`0.874–0.953`).
8. **Packaging.** Part 1 edited `pyproject.toml`. Hatch's `force-include` fails when the folder is absent, so the backend plan (merged first) adds `artifacts = ["src/hypothex/ui_dist/**"]` under `[tool.hatch.build.targets.wheel]`, and contract section 4 now names that entry. Task 1 keeps the `.gitignore` lines and the wheel check and no longer edits `pyproject.toml`.
9. **Example comparisons.** Part 1 always sent `field=correct`; Part 4 sent no field. Neither works for an agent task: phase 1a `GET /compare/examples` and `GET /runs/{id}/predictions` default to `field="correct"` (the backend plan does not change them; `pick_field` runs only inside the leaderboard) and drop examples without that field, so `solved` tasks get an empty 200 (`fixes 0, breaks 0, p = 1.00`). Spec 8.5 allows any boolean field (`correct`, `solved`, ...), so `api.compareExamples` sends `field` only when given, and the Examples page (Task 37) reads the field from one row of B's per-example scores with `pickExampleField` and passes it to both routes.
10. **Log streams.** Part 1 typed logs as `stdout | stderr`; the run page also opens `supervisor`, which phase 1a `read_log` serves. `LogStream` in the models covers all three.
11. **Actions.** Part 1's `useRunAction` made a new `command_id` per attempt and never retried; Part 4's `useAction` reuses the `command_id` on a network retry. `useAction` stays, now built on `api.*` with `ActionOptions`, and treats `ApiError` status 0 as unanswered. `useRunAction`, `runAction` and the unused `useValidateView` (the editor validates with a text-keyed query) were removed from Task 4.
12. **Route wiring.** Part 1 said each screen group wires its route; Parts 4 and 5 assumed a separate router group that no part contained. Each page task now ends with a router step; screen wrappers declare a `ReactElement` return type so route types have no cycle; the run route gained `validateSearch` for `log` and `example`. Part 1's route, header and palette tests wait on the matched route or the header instead of placeholder text, and mock `fetch`, so they keep passing after wiring.
13. **Live updates mount.** Part 6 edited "the root layout" only if nothing called the hook. `LiveUpdates` is mounted in `main.tsx`, outside `AppShell`, so tests that render the shell open no socket.
14. **View tabs in e2e.** Part 6 expected ARIA tabs (`role="tab"`, `aria-selected`); Part 4 renders `nav[aria-label="Views"]` links with `aria-current="page"`, covered by its unit tests. The e2e selectors follow Part 4.
15. **Styles.** Rules repeated from `base.css` were removed: `.stats`, `.hint`, `.who` from `panels.css`; `.key` from `charts.css`; the crumb, metaline, small, stats, figure-header, button, copy, tag, who, table, path, key and command rules from Part 4's `PAGES_CSS` (the lines left are page layouts and overrides); `.hx-ed-btn` and `.hx-ed-crumb` from `editor.css` (the editor uses `.btn` and `.crumb`, and a `<div>` instead of a nested `<main>`). Part 4's `StatStrip` draws through Part 2's panel; Part 5's preview reuses `panelLetter` and `clampSpan` from Part 4.
16. **Kept apart on purpose.** Number formatters with different jobs stay separate (`fmtValue`, 3 significant digits, in charts; `fmtNum`, 3 decimals in [−1, 1], in data panels; `fmtScore`, 4 decimals as in the ui-v4 mockup, on pages). Part 2's state-driven `.hx-tip` tooltip stays next to the palette's `.tip`. Run links inside panels (Parts 2 and 3) are plain `<a href>` so panels need no router; on pages, `PanelBody` (Task 25) routes plain clicks on them in-app with Task 23 `useInAppLinks`, so they do not reload the page (a reload refetches every query and reconnects the event stream). Page links use `AppLink`.
17. **Moved step.** Part 2's visual check of the training task needed the Task page, which did not exist at Task 13; it is now in Task 37 Step 6.
18. **Removed text.** Per-part intros and per-part review-focus lists were replaced by the global sections; every test they named is still in its task. Group references were rewritten to task numbers and backend part numbers to "the backend plan". Where an edit changed a file's test count, the Expected line changed; whole-suite runs after wiring expect `0 fail`.
