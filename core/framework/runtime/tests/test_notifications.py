"""Tests for the developer-notification sinks (Phase 4).

Covers ConsoleNotifier (stdout one-liner) and WebhookNotifier (POSTs JSON
payload, swallows network errors so a flaky endpoint can never break a
runtime evaluation).
"""

from __future__ import annotations

import json

import pytest

from framework.runtime.notifications import ConsoleNotifier, WebhookNotifier
from framework.schemas.failure_report import (
    FailureReport,
    UnmetCriterion,
    ViolatedConstraint,
)


class TestConsoleNotifier:
    def test_notify_failure_prints_summary(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        ConsoleNotifier().notify_failure(
            FailureReport(goal_id="g1", goal_name="G", version=2)
        )
        out = capsys.readouterr().out
        assert "FAILURE goal=G (g1)" in out
        assert "v=2" in out


class TestWebhookNotifier:
    def test_post_called_with_json_payload(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        class _Resp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout):  # noqa: ARG001
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode("utf-8"))
            return _Resp()

        monkeypatch.setattr(
            "framework.runtime.notifications.urlrequest.urlopen", fake_urlopen
        )

        WebhookNotifier("https://example.test/hook").notify_failure(
            FailureReport(
                goal_id="g1",
                goal_name="G",
                unmet_criteria=[
                    UnmetCriterion(
                        criterion_id="c1",
                        description="d",
                        metric="output_contains",
                        target="x",
                        weight=1.0,
                    )
                ],
                violated_constraints=[
                    ViolatedConstraint(
                        constraint_id="k1",
                        description="d",
                        constraint_type="hard",
                        violation_details="v",
                    )
                ],
                edge_ids=["a->b"],
            )
        )
        assert captured["url"] == "https://example.test/hook"
        assert captured["body"]["event"] == "goal_failure"
        assert captured["body"]["unmet_criteria"] == ["c1"]
        assert captured["body"]["edge_ids"] == ["a->b"]

    def test_network_failure_is_swallowed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(req, timeout):  # noqa: ARG001
            raise OSError("no route")

        monkeypatch.setattr(
            "framework.runtime.notifications.urlrequest.urlopen", boom
        )
        # Must not raise.
        WebhookNotifier("https://x").notify_failure(
            FailureReport(goal_id="g", goal_name="G")
        )
