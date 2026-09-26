"""Background run supervisor.

Started by ``launch_run`` as::

    python -m hypothex.core.supervisor <run_id> --home <hypothex home>
"""

from __future__ import annotations

import argparse
from pathlib import Path

from hypothex.core.context import Context
from hypothex.core.execution import execute_run
from hypothex.core.records import RunStatus


def main(argv: list[str] | None = None) -> int:
    """
    Execute one queued run; exit 0 if it finished, else 1.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit code.
    """
    parser = argparse.ArgumentParser(prog="hypothex.core.supervisor")
    parser.add_argument("run_id")
    parser.add_argument("--home", required=True)
    args = parser.parse_args(argv)
    ctx = Context.open(Path(args.home))
    record = execute_run(ctx, args.run_id)
    return 0 if record.status == RunStatus.FINISHED else 1


if __name__ == "__main__":
    raise SystemExit(main())
