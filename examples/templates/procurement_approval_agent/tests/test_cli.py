"""CLI tests for procurement approval agent."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from procurement_approval_agent.__main__ import cli


def test_reset_setup_command_removes_state(monkeypatch) -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        storage_root = Path.cwd() / "storage"
        setup_path = storage_root / "procurement_approval_agent" / "setup_config.json"
        setup_path.parent.mkdir(parents=True, exist_ok=True)
        setup_path.write_text('{"setup_completed": true, "preferred_sync_method": "csv"}')

        monkeypatch.setenv("HIVE_AGENT_STORAGE_ROOT", str(storage_root))
        result = runner.invoke(cli, ["reset-setup"])

        assert result.exit_code == 0
        assert "Removed setup state" in result.output
        assert setup_path.exists() is False
