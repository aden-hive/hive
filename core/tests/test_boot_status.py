"""Tests for the launch-status surface (framework.server.boot_status +
GET /api/startup-status).

The web dashboard's loading overlay polls this while `hive open` cold
starts, so the report/ready transitions and the endpoint payload shape
are what the frontend depends on.
"""

from __future__ import annotations

import pytest

from framework.server import boot_status
from framework.server.app import handle_startup_status

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_state():
    """boot_status is process-global; leave it ready so other tests that
    happen to boot sessions aren't affected by ordering."""
    yield
    boot_status.mark_ready()


def test_report_marks_busy_and_ready_clears() -> None:
    boot_status.report("Starting tool servers", "MCP discovery")
    s = boot_status.get_status()
    assert s["ready"] is False
    assert s["stage"] == "Starting tool servers"
    assert s["detail"] == "MCP discovery"

    boot_status.report("Composing queen prompt")
    boot_status.mark_ready("Queen ready")
    s = boot_status.get_status()
    assert s["ready"] is True
    assert s["stage"] == "Queen ready"
    # History preserves the stage sequence for debugging.
    stages = [h["stage"] for h in s["history"]]
    assert stages[-3:] == ["Starting tool servers", "Composing queen prompt", "Queen ready"]


def test_history_is_bounded() -> None:
    for i in range(100):
        boot_status.report(f"stage-{i}")
    assert len(boot_status.get_status()["history"]) == 32


async def test_endpoint_payload_shape() -> None:
    boot_status.report("Reading session history")
    resp = await handle_startup_status(None)  # request is unused
    assert resp.status == 200
    import json

    body = json.loads(resp.text)
    assert body["ready"] is False
    assert body["stage"] == "Reading session history"
    assert isinstance(body["history"], list)
