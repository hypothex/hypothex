Connecting agents
==================

Hypothex is built for agents to run and compare experiments on their own. There are
four ways to connect one.

1. CLI
------

Set ``HYPOTHEX_AGENT=claude`` (or your agent's name) in the environment and always
pass ``--json``. Runs are then recorded with that name as the author, and Hypothex
rejects any run that has no hypothesis.

.. code-block:: bash

   export HYPOTHEX_AGENT=claude
   hx run -t TASK -H "why this run exists" --seed 1 --json -- python train.py --seed {seed}

2. Skill
--------

Copy ``skills/hypothex/`` into ``~/.claude/skills/`` for Claude Code, so it is loaded
automatically in any repo with a ``hypothex.yaml``. For Codex, reference the skill
file from your project's ``AGENTS.md`` instead.

3. MCP over stdio
------------------

.. code-block:: bash

   claude mcp add hypothex -- uv run --project /path/to/hypothex hx mcp

Registers Hypothex as an MCP server that Claude Code launches over stdio.

4. MCP over HTTP
-----------------

.. code-block:: bash

   hx serve

Start the HTTP/WebSocket server, then connect an MCP client to
``http://127.0.0.1:7777/mcp/``.

5. HTTP API
-----------

With ``hx serve`` running, the OpenAPI docs are at
``http://127.0.0.1:7777/api/docs``.
