"""Developer notifications for OutcomeAggregator events (Phase 4).

A small, dependency-free notifier abstraction. The aggregator calls
``notifier.notify_failure(report)`` (and optionally ``notify_progress``)
whenever a goal evaluation completes. Concrete implementations can fan
the event out to logs, stdout, a webhook, Slack, etc.

Kept intentionally minimal — no async fan-out, no retry logic. The point
is to give developers an actionable signal in real time without coupling
the runtime to any specific transport.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any, Protocol
from urllib import error as urlerror
from urllib import request as urlrequest

if TYPE_CHECKING:
    from framework.schemas.failure_report import FailureReport

logger = logging.getLogger(__name__)


class DeveloperNotifier(Protocol):
    """Sink for developer-facing evaluation events."""

    def notify_failure(self, report: "FailureReport") -> None: ...

    def notify_progress(self, progress: dict[str, Any]) -> None: ...


class ConsoleNotifier:
    """Default notifier — writes a one-line summary to stdout/logger.

    Useful as a development default and as a base when no webhook is
    configured. Printing rather than logging makes the signal visible
    even when the host process suppresses framework logs.
    """

    def notify_failure(self, report: "FailureReport") -> None:
        line = (
            f"[hive] FAILURE goal={report.goal_name} ({report.goal_id}) "
            f"unmet={len(report.unmet_criteria)} "
            f"violated={len(report.violated_constraints)} "
            f"v={report.version}"
        )
        print(line)
        logger.info(line)

    def notify_progress(self, progress: dict[str, Any]) -> None:
        pct = progress.get("overall_progress", 0.0)
        logger.info(f"[hive] progress {pct:.1%}")


class WebhookNotifier:
    """POST a JSON payload to a webhook URL on each failure.

    Best-effort: network errors are logged but never raised, so a flaky
    notification endpoint can never break a runtime evaluation.
    """

    def __init__(self, url: str, timeout: float = 5.0) -> None:
        self._url = url
        self._timeout = timeout

    def notify_failure(self, report: "FailureReport") -> None:
        payload = {
            "event": "goal_failure",
            "goal_id": report.goal_id,
            "goal_name": report.goal_name,
            "version": report.version,
            "unmet_criteria": [c.criterion_id for c in report.unmet_criteria],
            "violated_constraints": [
                v.constraint_id for v in report.violated_constraints
            ],
            "node_ids": list(report.node_ids),
            "edge_ids": list(report.edge_ids),
            "summary": report.summary,
            "metrics": {
                "total_decisions": report.total_decisions,
                "successful_outcomes": report.successful_outcomes,
                "failed_outcomes": report.failed_outcomes,
            },
        }
        self._post(payload)

    def notify_progress(self, progress: dict[str, Any]) -> None:
        self._post({"event": "goal_progress", **progress})

    def _post(self, payload: dict[str, Any]) -> None:
        try:
            data = json.dumps(payload, default=str).encode("utf-8")
            req = urlrequest.Request(
                self._url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlrequest.urlopen(req, timeout=self._timeout) as resp:
                if resp.status >= 400:
                    logger.warning(
                        f"WebhookNotifier non-2xx response: {resp.status}"
                    )
        except (urlerror.URLError, TimeoutError, OSError) as e:
            logger.warning(f"WebhookNotifier post failed: {e}")
