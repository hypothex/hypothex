Agent guide
===========

Hypothex is built for agents that run and compare experiments on their own. An agent
can use the CLI, the MCP server, the skill file, or the HTTP API. All four apply the
same rules.

Rules for agents
----------------

- Name yourself. A launch whose author is ``agent:<name>`` must have a hypothesis; it
  is refused without one.
- Use at least 3 seeds before you claim a win. On the leaderboard,
  ``within_noise_of_best: true`` means "not a real win yet".
- Read what was tried (hypotheses and notes of the top runs) before you start a new
  idea.
- Never delete run folders. Hide a dead end with ``hx archive``.
- Never change a metric's code without a version bump in ``hypothex.yaml``; then
  re-evaluate the task.
- A remote run on a ``stale`` host keeps going and is not lost. Do not rerun it; wait,
  or reconnect the host.

1. CLI
------

Set ``HYPOTHEX_AGENT`` to your name and always pass ``--json``. Runs then record
``agent:<name>`` as the author. Errors come back as ``{"error": ..., "type": ...}``
with exit code 1.

.. code-block:: bash

   export HYPOTHEX_AGENT=claude
   hx tasks --json
   hx leaderboard toy-test --json
   hx run -t toy-test -H "why this run exists" --seed 1 --json -- \
       python train_eval.py --model rf --seed '{seed}'

On remote hosts:

.. code-block:: bash

   hx hosts status --json                                      # where can I run?
   hx launch --json --host gpu-box --gpus 1 --queue -t toy-test -H "why" --seed 1 -- \
       python train_eval.py --model rf --seed '{seed}'
   hx sweep --json -t toy-test -H "why" --grid model=logreg,rf --seeds 3 \
       --host gpu-box --gpus 1 --queue -- python train_eval.py --model '{model}' --seed '{seed}'
   hx sweep show SWEEP_ID --json                               # progress, best cell, cost
   hx pull RUN_ID --artifact checkpoint --json                 # copy a checkpoint to the hub

See :doc:`cli` for every command.

2. Skill
--------

``skills/hypothex/SKILL.md`` teaches an agent the experiment loop, the rules, views,
and remote hosts and sweeps.

- Claude Code: copy ``skills/hypothex/`` into ``~/.claude/skills/``. It loads in any
  repo with a ``hypothex.yaml``.
- Codex and other agents: reference the skill file from your project's ``AGENTS.md``.

3. MCP over stdio
-----------------

.. code-block:: bash

   claude mcp add hypothex -- hx mcp
   # or, from a source checkout:
   claude mcp add hypothex -- uv run --project /path/to/hypothex hx mcp

The client launches ``hx mcp`` over stdio. Tools take an ``agent`` argument (default
``mcp``); pass your name. The host and sweep tools need ``hx serve`` on the hub. See
:doc:`mcp` for every tool.

4. MCP over HTTP
----------------

.. code-block:: bash

   hx serve

Then connect an MCP client to ``http://127.0.0.1:7777/mcp/``.

5. HTTP API
-----------

With ``hx serve`` running, the OpenAPI docs are at
``http://127.0.0.1:7777/api/docs``. Set ``created_by`` to ``agent:<name>`` on
launches. See :doc:`http_api`.

A typical loop
--------------

1. ``hx tasks --json``, then ``hx task show TASK --json``: pick the task.
2. ``hx leaderboard TASK --json``: what is best, and what is within noise.
3. ``hx show RUN_ID --json`` on the top rows: read the hypotheses and notes.
4. ``hx hosts status --json``: pick a host with free GPUs, or queue.
5. Launch 3 seeds, or a sweep, with a one-sentence hypothesis.
6. ``hx compare NEW BEST --json`` and ``hx examples BEST NEW --metric METRIC --json``.
7. ``hx note RUN_ID "what I learned and what is next" --json``.
