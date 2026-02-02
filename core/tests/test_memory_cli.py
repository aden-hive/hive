import argparse
import json
from pathlib import Path

from framework.memory.cli import cmd_memory_inspect, cmd_memory_list, cmd_memory_stats
from framework.schemas.run import Run, RunStatus
from framework.storage.backend import FileStorage


def _make_storage(tmp_path: Path) -> FileStorage:
    storage_path = tmp_path / "storage"
    return FileStorage(storage_path)


def _add_run(storage: FileStorage, run_id: str, status: RunStatus, output: dict) -> None:
    run = Run(
        id=run_id,
        goal_id="goal-1",
        status=status,
        output_data=output,
    )
    storage.save_run(run)


def test_memory_inspect_missing_storage(tmp_path, capsys):
    args = argparse.Namespace(
        agent_path="exports/agent",
        run_id="run-1",
        storage_path=str(tmp_path / "missing"),
        json=False,
    )

    assert cmd_memory_inspect(args) == 1
    captured = capsys.readouterr().out
    assert "Storage not found" in captured


def test_memory_inspect_missing_run(tmp_path, capsys):
    storage = _make_storage(tmp_path)
    args = argparse.Namespace(
        agent_path="exports/agent",
        run_id="run-1",
        storage_path=str(storage.base_path),
        json=False,
    )

    assert cmd_memory_inspect(args) == 1
    captured = capsys.readouterr().out
    assert "Run not found" in captured


def test_memory_inspect_returns_output_data(tmp_path, capsys):
    storage = _make_storage(tmp_path)
    _add_run(storage, "run-1", RunStatus.COMPLETED, {"answer": 42})

    args = argparse.Namespace(
        agent_path="exports/agent",
        run_id="run-1",
        storage_path=str(storage.base_path),
        json=True,
    )

    assert cmd_memory_inspect(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["run_id"] == "run-1"
    assert payload["output_data"] == {"answer": 42}


def test_memory_list_reports_runs(tmp_path, capsys):
    storage = _make_storage(tmp_path)
    _add_run(storage, "run-1", RunStatus.COMPLETED, {"x": 1})

    args = argparse.Namespace(
        agent_path="exports/agent",
        storage_path=str(storage.base_path),
        limit=50,
        json=False,
    )

    assert cmd_memory_list(args) == 0
    output = capsys.readouterr().out
    assert "run-1" in output


def test_memory_list_json_output(tmp_path, capsys):
    storage = _make_storage(tmp_path)
    _add_run(storage, "run-1", RunStatus.COMPLETED, {"x": 1})

    args = argparse.Namespace(
        agent_path="exports/agent",
        storage_path=str(storage.base_path),
        limit=50,
        json=True,
    )

    assert cmd_memory_list(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["run_id"] == "run-1"


def test_memory_stats_counts_statuses(tmp_path, capsys):
    storage = _make_storage(tmp_path)
    _add_run(storage, "run-1", RunStatus.COMPLETED, {"x": 1})
    _add_run(storage, "run-2", RunStatus.FAILED, {"x": 2})

    args = argparse.Namespace(
        agent_path="exports/agent",
        storage_path=str(storage.base_path),
        json=True,
    )

    assert cmd_memory_stats(args) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["by_status"]["completed"] == 1
    assert payload["by_status"]["failed"] == 1
