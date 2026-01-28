import tempfile
from pathlib import Path

import pytest

from framework.storage.backend import FileStorage
from framework.schemas.run import Run, RunStatus
from datetime import datetime



# -------------------------
# Helpers
# -------------------------

from datetime import datetime

def make_run(run_id: str = "run1") -> Run:
    return Run(
        id=run_id,
        goal_id="goal1",
        status=RunStatus.COMPLETED,
        started_at=datetime.now(),
        input_data={},
        output_data={},
        decisions=[],
        problems=[],
    )


# -------------------------
# Tests
# -------------------------

def test_save_and_load_run():
    """Basic sanity test: save a run and load it back."""
    with tempfile.TemporaryDirectory() as tmp:
        storage = FileStorage(tmp)

        run = make_run("run1")
        storage.save_run(run)

        loaded = storage.load_run("run1")

        assert loaded is not None
        assert loaded.id == "run1"
        assert loaded.goal_id == "goal1"
        assert loaded.status == RunStatus.COMPLETED


def test_load_missing_run_returns_none():
    """Loading a non-existing run should return None."""
    with tempfile.TemporaryDirectory() as tmp:
        storage = FileStorage(tmp)

        result = storage.load_run("does_not_exist")
        assert result is None


def test_list_all_runs():
    """list_all_runs should return all saved run IDs."""
    with tempfile.TemporaryDirectory() as tmp:
        storage = FileStorage(tmp)

        storage.save_run(make_run("run1"))
        storage.save_run(make_run("run2"))

        runs = storage.list_all_runs()

        assert set(runs) == {"run1", "run2"}


def test_delete_run_removes_files_and_indexes():
    """delete_run should remove run and return True."""
    with tempfile.TemporaryDirectory() as tmp:
        storage = FileStorage(tmp)

        run = make_run("run1")
        storage.save_run(run)

        deleted = storage.delete_run("run1")

        assert deleted is True
        assert storage.load_run("run1") is None


def test_corrupted_run_file_is_handled_gracefully():
    """
    If a run JSON file is corrupted, FileStorage should NOT crash.
    It should fail gracefully and return None.
    """
    with tempfile.TemporaryDirectory() as tmp:
        storage = FileStorage(tmp)

        # write corrupted JSON directly
        run_path = Path(tmp) / "runs" / "bad.json"
        run_path.parent.mkdir(parents=True, exist_ok=True)
        run_path.write_text("{ invalid json", encoding="utf-8")

        result = storage.load_run("bad")

        # Expected behavior: no exception, return None
        assert result is None
