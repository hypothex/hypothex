"""Background run supervisor.

Started by ``spawn_supervisor`` as::

    python -m hypothex.core.supervisor <run_id> --home <hypothex home>

It executes the run only once ``supervisor.pid`` in the run folder names this
process. The spawner writes that file right after starting it; if the spawner
fails or dies first, the start never committed and this process exits without
touching the run.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from hypothex.core.context import Context
from hypothex.core.execution import SUPERVISOR_PID_FILE, execute_run
from hypothex.core.records import RunStatus

SUPERVISOR_WAIT_SECONDS = 30.0


def owns_run(run_dir: Path, wait: float) -> bool:
    """
    Wait until ``supervisor.pid`` in ``run_dir`` names this process.

    Parameters
    ----------
    run_dir : Path
        The run folder.
    wait : float
        Seconds to wait for the spawner to write the file.

    Returns
    -------
    bool
        True when the file names this pid; False after ``wait`` seconds.
    """
    deadline = time.monotonic() + wait
    while True:
        try:
            info = json.loads((run_dir / SUPERVISOR_PID_FILE).read_text(encoding="utf-8"))
            if info["pid"] == os.getpid():
                return True
        except (OSError, ValueError, KeyError, TypeError):
            pass
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)


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
    run_dir = ctx.run_dir(ctx.find_record(args.run_id))
    wait = float(os.environ.get("HYPOTHEX_SUPERVISOR_WAIT", SUPERVISOR_WAIT_SECONDS))
    if not owns_run(run_dir, wait):
        print(
            f"hypothex supervisor {os.getpid()}: supervisor.pid does not name this process; "
            f"not starting {args.run_id}",
            file=sys.stderr,
        )
        return 1
    record = execute_run(ctx, args.run_id)
    return 0 if record.status == RunStatus.FINISHED else 1


if __name__ == "__main__":
    raise SystemExit(main())
