import json
from pathlib import Path
from unittest.mock import patch

from aden_tools.cli.office_pack import main


def test_office_pack_cli_runs(tmp_path: Path):
    spec_path = tmp_path / "spec.json"
    spec = json.loads(
        (
            Path(__file__).resolve().parents[2] / "examples" / "pack_finance.json"
        ).read_text(encoding="utf-8")
    )
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        rc = main(["--spec", str(spec_path), "--workspace", "w", "--agent", "a", "--session", "s"])
        assert rc == 0


def test_office_pack_cli_dry_run(tmp_path: Path, capsys):
    spec_path = tmp_path / "spec.json"
    spec = json.loads(
        (
            Path(__file__).resolve().parents[2] / "examples" / "pack_finance.json"
        ).read_text(encoding="utf-8")
    )
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        rc = main(
            ["--spec", str(spec_path), "--workspace", "w", "--agent", "a", "--session", "s", "--dry-run"]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert '"dry_run": true' in out


def test_office_pack_cli_dry_run_markdown(tmp_path: Path, capsys):
    spec_path = tmp_path / "spec.json"
    spec = json.loads(
        (
            Path(__file__).resolve().parents[2] / "examples" / "pack_finance.json"
        ).read_text(encoding="utf-8")
    )
    spec_path.write_text(json.dumps(spec), encoding="utf-8")

    with patch("aden_tools.tools.file_system_toolkits.security.WORKSPACES_DIR", str(tmp_path)):
        rc = main(
            [
                "--spec",
                str(spec_path),
                "--workspace",
                "w",
                "--agent",
                "a",
                "--session",
                "s",
                "--dry-run",
                "--print-markdown",
            ]
        )
        assert rc == 0
        out = capsys.readouterr().out
        assert "Office Pack Output" in out
