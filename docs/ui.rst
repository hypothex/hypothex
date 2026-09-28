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
  failures (with ``Open stderr``), and projects. Ideas are grouped by task, and each task
  has its own x axis, because tasks use different metrics.
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
  ``.hypothex/views/<task>/<name>.yaml``) or Copy as CLI. A new view cannot take the
  name of a view that is already there: open that view to edit it.

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
