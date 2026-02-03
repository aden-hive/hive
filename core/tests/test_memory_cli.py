"""Tests for memory CLI commands."""

import json
from argparse import Namespace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from framework.memory.cli import _get_storage_path, cmd_inspect, cmd_list, cmd_stats
from framework.schemas.decision import Decision, Outcome
from framework.schemas.run import Run, RunMetrics, RunStatus, RunSummary


@pytest.fixture
def mock_run():
    """Create a mock Run object with test data."""
    return Run(
        id="run_20260131_123456",
        goal_id="test-goal",
        goal_description="Test goal for searching AI news",
        status=RunStatus.COMPLETED,
        started_at=datetime(2026, 1, 31, 12, 34, 56),
        completed_at=datetime(2026, 1, 31, 12, 35, 56),
        duration_ms=60000,
        input_data={"query": "test query"},
        output_data={
            "query": "latest AI news",
            "search_results": [{"title": "AI Breakthrough", "url": "https://example.com"}],
            "summary": "Recent AI developments include major breakthroughs in LLMs.",
        },
        metrics=RunMetrics(
            total_decisions=5,
            successful_decisions=4,
            failed_decisions=1,
            nodes_executed=["search_node", "summarize_node"],
        ),
        decisions=[
            Decision(
                id="dec1",
                node_id="search_node",
                intent="Search for AI news",
                chosen="web_search",
                outcome=Outcome(
                    success=True,
                    summary="Found 10 relevant articles",
                ),
            )
        ],
    )


@pytest.fixture
def mock_run_empty_memory():
    """Create a mock Run with empty output_data."""
    return Run(
        id="run_empty",
        goal_id="test-goal",
        goal_description="Test goal",
        status=RunStatus.COMPLETED,
        started_at=datetime(2026, 1, 31, 12, 34, 56),
        completed_at=datetime(2026, 1, 31, 12, 35, 56),
        duration_ms=1000,
        output_data={},
        metrics=RunMetrics(),
    )


@pytest.fixture
def mock_summary():
    """Create a mock RunSummary."""
    return RunSummary(
        run_id="run_20260131_123456",
        goal_id="test-goal",
        status=RunStatus.COMPLETED,
        duration_ms=60000,
        decision_count=5,
        success_rate=0.8,
        problem_count=0,
        narrative="Test run completed successfully",
        started_at=datetime(2026, 1, 31, 12, 34, 56),
    )


def test_inspect_with_run_id(mock_run, capsys, tmp_path):
    """Test inspecting a specific run by ID."""
    args = Namespace(
        agent_path="exports/test-agent",
        run_id="run_20260131_123456",
        json=False,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        with patch("framework.memory.cli.FileStorage") as MockStorage:
            mock_storage = MockStorage.return_value
            mock_storage.load_run.return_value = mock_run

            result = cmd_inspect(args)

            assert result == 0
            mock_storage.load_run.assert_called_once_with("run_20260131_123456")

            captured = capsys.readouterr()
            assert "run_20260131_123456" in captured.out
            assert "test-goal" in captured.out
            assert "completed" in captured.out.lower()

            # CRITICAL: Verify Memory State is displayed
            assert "Memory State:" in captured.out
            assert "query: latest AI news" in captured.out
            assert "search_results" in captured.out
            assert "summary: Recent AI developments" in captured.out
            assert "Total keys: 3" in captured.out


def test_inspect_without_run_id_defaults_to_last(mock_run, capsys, tmp_path):
    """Test inspecting last run when no run_id provided."""
    args = Namespace(
        agent_path="exports/test-agent",
        run_id=None,
        json=False,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        with patch("framework.memory.cli.FileStorage") as MockStorage:
            mock_storage = MockStorage.return_value
            mock_storage.list_all_runs.return_value = ["run_older", "run_20260131_123456"]
            mock_storage.load_run.return_value = mock_run

            result = cmd_inspect(args)

            assert result == 0
            mock_storage.list_all_runs.assert_called_once()
            mock_storage.load_run.assert_called_once_with("run_20260131_123456")

            captured = capsys.readouterr()
            assert "Memory State:" in captured.out


def test_inspect_json_output(mock_run, capsys, tmp_path):
    """Test JSON output format."""
    args = Namespace(
        agent_path="exports/test-agent",
        run_id="run_20260131_123456",
        json=True,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        with patch("framework.memory.cli.FileStorage") as MockStorage:
            mock_storage = MockStorage.return_value
            mock_storage.load_run.return_value = mock_run

            result = cmd_inspect(args)

            assert result == 0

            captured = capsys.readouterr()
            output = json.loads(captured.out)

            assert output["id"] == "run_20260131_123456"
            assert output["goal_id"] == "test-goal"
            assert output["status"] == "completed"

            # CRITICAL: Verify output_data (memory) is in JSON
            assert "output_data" in output
            assert output["output_data"]["query"] == "latest AI news"
            assert "search_results" in output["output_data"]
            assert "summary" in output["output_data"]


def test_inspect_empty_memory(mock_run_empty_memory, capsys, tmp_path):
    """Test inspecting run with empty memory state."""
    args = Namespace(
        agent_path="exports/test-agent",
        run_id="run_empty",
        json=False,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        with patch("framework.memory.cli.FileStorage") as MockStorage:
            mock_storage = MockStorage.return_value
            mock_storage.load_run.return_value = mock_run_empty_memory

            result = cmd_inspect(args)

            assert result == 0

            captured = capsys.readouterr()
            assert "Memory State: (empty)" in captured.out


def test_inspect_storage_not_found(capsys, tmp_path):
    """Test error when storage path doesn't exist."""
    args = Namespace(
        agent_path="exports/nonexistent-agent",
        run_id="run_123",
        json=False,
    )

    storage_path = tmp_path / "nonexistent"

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        result = cmd_inspect(args)

        assert result == 1

        captured = capsys.readouterr()
        assert "No memory found" in captured.err


def test_inspect_no_runs_found(capsys, tmp_path):
    """Test error when no runs exist and no run_id provided."""
    args = Namespace(
        agent_path="exports/test-agent",
        run_id=None,
        json=False,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        with patch("framework.memory.cli.FileStorage") as MockStorage:
            mock_storage = MockStorage.return_value
            mock_storage.list_all_runs.return_value = []

            result = cmd_inspect(args)

            assert result == 1

            captured = capsys.readouterr()
            assert "No runs found" in captured.err


def test_inspect_run_not_found(capsys, tmp_path):
    """Test error when specific run doesn't exist."""
    args = Namespace(
        agent_path="exports/test-agent",
        run_id="run_nonexistent",
        json=False,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        with patch("framework.memory.cli.FileStorage") as MockStorage:
            mock_storage = MockStorage.return_value
            mock_storage.load_run.return_value = None

            result = cmd_inspect(args)

            assert result == 1

            captured = capsys.readouterr()
            assert "run_nonexistent not found" in captured.err


def test_get_storage_path_with_agent_path():
    """Test extracting agent name from path."""
    path = _get_storage_path("exports/my-agent")
    assert path == Path.home() / ".hive" / "storage" / "my-agent"

    path = _get_storage_path("my-agent")
    assert path == Path.home() / ".hive" / "storage" / "my-agent"


def test_get_storage_path_no_agent_exits():
    """Test that missing agent path causes exit."""
    with patch("framework.memory.cli.Path.cwd") as mock_cwd:
        mock_cwd.return_value = Path("/some/random/path")

        with pytest.raises(SystemExit) as exc_info:
            _get_storage_path(None)

        assert exc_info.value.code == 1


def test_list_runs(mock_summary, capsys, tmp_path):
    """Test listing runs."""
    args = Namespace(
        agent_path="exports/test-agent",
        status=None,
        goal=None,
        limit=20,
        json=False,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        with patch("framework.memory.cli.FileStorage") as MockStorage:
            mock_storage = MockStorage.return_value
            mock_storage.list_all_runs.return_value = ["run_20260131_123456"]
            mock_storage.load_summary.return_value = mock_summary

            result = cmd_list(args)

            assert result == 0

            captured = capsys.readouterr()
            assert "Found 1 run(s)" in captured.out
            assert "run_20260131_123456" in captured.out
            assert "test-goal" in captured.out


def test_list_runs_with_status_filter(mock_summary, capsys, tmp_path):
    """Test listing runs filtered by status."""
    args = Namespace(
        agent_path="exports/test-agent",
        status="completed",
        goal=None,
        limit=20,
        json=False,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        with patch("framework.memory.cli.FileStorage") as MockStorage:
            mock_storage = MockStorage.return_value
            mock_storage.get_runs_by_status.return_value = ["run_20260131_123456"]
            mock_storage.load_summary.return_value = mock_summary

            result = cmd_list(args)

            assert result == 0
            mock_storage.get_runs_by_status.assert_called_once_with("completed")


def test_list_runs_json_output(mock_summary, capsys, tmp_path):
    """Test listing runs with JSON output."""
    args = Namespace(
        agent_path="exports/test-agent",
        status=None,
        goal=None,
        limit=20,
        json=True,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        with patch("framework.memory.cli.FileStorage") as MockStorage:
            mock_storage = MockStorage.return_value
            mock_storage.list_all_runs.return_value = ["run_20260131_123456"]
            mock_storage.load_summary.return_value = mock_summary

            result = cmd_list(args)

            assert result == 0

            captured = capsys.readouterr()
            output = json.loads(captured.out)
            assert isinstance(output, list)
            assert len(output) == 1


def test_list_runs_negative_limit(capsys, tmp_path):
    """Test that negative limit returns error."""
    args = Namespace(
        agent_path="exports/test-agent",
        status=None,
        goal=None,
        limit=-5,
        json=False,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        result = cmd_list(args)

        assert result == 1

        captured = capsys.readouterr()
        assert "limit must be a positive number" in captured.err


def test_stats(capsys, tmp_path):
    """Test statistics display."""
    args = Namespace(
        agent_path="exports/test-agent",
        json=False,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        with patch("framework.memory.cli.FileStorage") as MockStorage:
            mock_storage = MockStorage.return_value
            mock_storage.get_stats.return_value = {
                "total_runs": 10,
                "total_goals": 3,
                "storage_path": str(storage_path),
            }
            mock_storage.get_runs_by_status.side_effect = lambda status: {
                "completed": ["run1", "run2"],
                "failed": ["run3"],
                "running": [],
                "stuck": [],
                "cancelled": [],
            }.get(status, [])

            result = cmd_stats(args)

            assert result == 0

            captured = capsys.readouterr()
            assert "Memory Statistics" in captured.out
            assert "Total runs: 10" in captured.out
            assert "Total goals: 3" in captured.out
            assert "Completed: 2" in captured.out
            assert "Failed: 1" in captured.out


def test_stats_json_output(capsys, tmp_path):
    """Test statistics with JSON output."""
    args = Namespace(
        agent_path="exports/test-agent",
        json=True,
    )

    storage_path = tmp_path / "storage"
    storage_path.mkdir()

    with patch("framework.memory.cli._get_storage_path") as mock_get_path:
        mock_get_path.return_value = storage_path

        with patch("framework.memory.cli.FileStorage") as MockStorage:
            mock_storage = MockStorage.return_value
            mock_storage.get_stats.return_value = {
                "total_runs": 10,
                "total_goals": 3,
                "storage_path": str(storage_path),
            }
            mock_storage.get_runs_by_status.return_value = []

            result = cmd_stats(args)

            assert result == 0

            captured = capsys.readouterr()
            output = json.loads(captured.out)
            assert output["total_runs"] == 10
            assert output["total_goals"] == 3
            assert "by_status" in output
