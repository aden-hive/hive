import json
import os
import time
from pathlib import Path
import subprocess
import sys
import shutil

import pytest
from framework.schemas.run import Run, RunMetrics, RunStatus
from framework.storage.backend import FileStorage

def create_test_run(run_id: str, goal_id: str = "test_goal") -> Run:
    """Create a minimal Run object."""
    metrics = RunMetrics(
        total_decisions=1,
        successful_decisions=1,
        failed_decisions=0,
        nodes_executed=["node_1"],
    )
    return Run(
        id=run_id,
        goal_id=goal_id,
        status=RunStatus.COMPLETED,
        metrics=metrics,
        narrative="Test run.",
    )

def create_dummy_agent(path: Path, agent_id: str, name: str, description: str):
    """Create a dummy agent folder with agent.json."""
    agent_dir = path / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)

    agent_data = {
        "graph": {
            "id": name,
            "description": description,
            "nodes": [],
            "edges": []
        },
        "goal": {
            "id": f"goal-{agent_id}",
            "name": f"Goal for {name}",
            "description": "Test goal"
        }
    }

    with open(agent_dir / "agent.json", "w") as f:
        json.dump(agent_data, f)

class TestStorageCleanup:
    def test_cleanup_old_runs(self, tmp_path):
        storage = FileStorage(tmp_path)

        # 1. Create fresh and old runs
        # Run 1: Fresh (0 days old)
        run_fresh = create_test_run("run_fresh")
        storage.save_run(run_fresh)

        # Run 2: Old (will be set to 10 days old)
        run_old = create_test_run("run_old")
        storage.save_run(run_old)

        # Manually set modification time back 10 days
        old_time = time.time() - (10 * 24 * 60 * 60 + 3600)  # 10 days + 1 hour
        run_path = tmp_path / "runs" / "run_old.json"
        os.utime(run_path, (old_time, old_time))

        # 2. Verify both exist
        assert storage.load_run("run_fresh") is not None
        assert storage.load_run("run_old") is not None

        # 3. Cleanup runs older than 5 days
        deleted = storage.cleanup_old_runs(days=5)

        # 4. Assertions
        assert deleted == 1
        assert storage.load_run("run_fresh") is not None
        assert storage.load_run("run_old") is None

        # Verify indexes are also cleaned (by status index as example)
        completed_runs = storage.get_runs_by_status(RunStatus.COMPLETED)
        assert "run_fresh" in completed_runs
        assert "run_old" not in completed_runs

class TestCLIFeatures:
    @pytest.fixture
    def core_dir(self):
        return Path(__file__).resolve().parent.parent

    def test_cli_search(self, tmp_path, core_dir):
        # Setup dummy agents
        agents_dir = tmp_path / "agents"
        create_dummy_agent(agents_dir, "email_agent", "Email Processor", "Sends and receives emails")
        create_dummy_agent(agents_dir, "db_agent", "Database Manager", "Handles SQL queries")
        create_dummy_agent(agents_dir, "file_agent", "File System", "Reads and writes files")

        # Run hive search
        # Using python -m framework to avoid path issues with console_scripts in tests
        env = os.environ.copy()
        env["PYTHONPATH"] = str(core_dir) + os.pathsep + env.get("PYTHONPATH", "")

        # Case 1: Search for 'email'
        result = subprocess.run(
            [sys.executable, "-m", "framework", "search", "email", str(agents_dir)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(core_dir)
        )
        assert result.returncode == 0
        assert "Email Processor" in result.stdout
        assert "Database Manager" not in result.stdout

        # Case 2: Search for 'manage' (in description)
        result = subprocess.run(
            [sys.executable, "-m", "framework", "search", "manage", str(agents_dir)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(core_dir)
        )
        assert result.returncode == 0
        assert "Database Manager" in result.stdout
        assert "Email Processor" not in result.stdout

    def test_cli_clean(self, tmp_path, core_dir):
        storage_dir = tmp_path / "storage"
        storage = FileStorage(storage_dir)

        # Create an old run
        run_old = create_test_run("run_old")
        storage.save_run(run_old)

        # Set back in time
        old_time = time.time() - (10 * 24 * 60 * 60 + 3600)
        run_path = storage_dir / "runs" / "run_old.json"
        os.utime(run_path, (old_time, old_time))

        assert (storage_dir / "runs" / "run_old.json").exists()

        # Run hive clean
        env = os.environ.copy()
        env["PYTHONPATH"] = str(core_dir) + os.pathsep + env.get("PYTHONPATH", "")

        result = subprocess.run(
            [sys.executable, "-m", "framework", "clean", "--days", "5", "--storage", str(storage_dir)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(core_dir)
        )

        assert result.returncode == 0
        assert "[OK] Deleted 1 old runs" in result.stdout
        assert not (storage_dir / "runs" / "run_old.json").exists()
