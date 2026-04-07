"""Tests for custom session-backed runtime logging paths."""

from pathlib import Path
from unittest.mock import MagicMock

from framework.orchestrator.orchestrator import Orchestrator
from framework.runtime.runtime_log_store import RuntimeLogStore
from framework.runtime.runtime_logger import RuntimeLogger


def test_graph_executor_uses_custom_session_dir_name_for_runtime_logs():
    executor = Orchestrator(
        runtime=MagicMock(),
        storage_path=Path("/tmp/test-agent/sessions/my-custom-session"),
    )

    assert executor._get_runtime_log_session_id() == "my-custom-session"


def test_runtime_logger_creates_session_log_dir_for_custom_session_id(tmp_path):
    base = tmp_path / ".hive" / "agents" / "test_agent"
    base.mkdir(parents=True)
    store = RuntimeLogStore(base)
    logger = RuntimeLogger(store=store, agent_id="test-agent")

    run_id = logger.start_run(goal_id="goal-1", session_id="my-custom-session")

    assert run_id == "my-custom-session"
    assert (base / "sessions" / "my-custom-session" / "logs").is_dir()
