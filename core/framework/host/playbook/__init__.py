"""Colony playbook runner.

A *playbook* is a deterministic Python script the queen authors to drive a
tracker table to convergence: it queries the rows that aren't done yet,
dispatches one worker per undone row, and re-queries until none remain.
The runner executes that script with a set of injected hooks
(``converge`` / ``worker`` / ``tracker_query`` / ``lane`` / ``deadletter``
/ ``log`` / ``phase``).

The runner is intentionally decoupled from the live colony: it receives
two async callables — ``dispatch_one`` (spawn + await one worker) and
``query_rows`` (run a tracker SELECT) — so the orchestration logic is
unit-testable without a running colony. The colony wiring lives in the
``run_playbook`` tool.
"""

from framework.host.playbook.runner import (
    DeadLetter,
    PlaybookError,
    PlaybookRun,
    PlaybookScriptError,
    run_playbook_script,
)

__all__ = [
    "DeadLetter",
    "PlaybookError",
    "PlaybookRun",
    "PlaybookScriptError",
    "run_playbook_script",
]
