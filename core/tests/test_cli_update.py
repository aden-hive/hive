import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

from framework.runner.cli import cmd_update


def test_cmd_update_success():
    """Test successful update flow."""
    # Patch subprocess.run inside the framework.runner.cli module
    # and Path as well.
    with (
        patch("framework.runner.cli.subprocess.run") as mock_run,
        patch("framework.runner.cli.Path") as mock_path_class,
    ):
        # Setup mock project root
        mock_project_root = MagicMock(spec=Path)
        mock_git_dir = MagicMock(spec=Path)
        mock_git_dir.is_dir.return_value = True

        # Path(__file__).resolve()
        mock_file_path = MagicMock(spec=Path)
        mock_path_class.return_value = mock_file_path  # For generic Path() calls
        mock_file_path.resolve.return_value = mock_file_path
        mock_file_path.parents = [mock_project_root]

        # (parent / ".git").is_dir()
        mock_project_root.__truediv__.return_value = mock_git_dir

        # Mock git status (no changes)
        res_no_changes = MagicMock()
        res_no_changes.stdout = ""

        # Mock success for other commands
        res_success = MagicMock()

        mock_run.side_effect = [
            res_no_changes,  # git status
            res_success,  # git pull
            res_success,  # uv sync
        ]

        args = argparse.Namespace(no_stash=False)
        # Suppress prints during test
        with patch("builtins.print"):
            result = cmd_update(args)

        assert result == 0
        assert mock_run.call_count == 3


def test_cmd_update_no_git():
    """Test update when no git repo is found."""
    with patch("framework.runner.cli.Path") as mock_path_class:
        mock_file_path = MagicMock(spec=Path)
        mock_file_path.resolve.return_value = mock_file_path
        mock_file_path.parents = []
        mock_path_class.return_value = mock_file_path

        # Fallback to CWD
        mock_cwd = MagicMock(spec=Path)
        mock_path_class.cwd.return_value = mock_cwd
        mock_cwd.__truediv__.return_value.is_dir.return_value = False

        args = argparse.Namespace(no_stash=False)
        with patch("builtins.print"):
            result = cmd_update(args)

        assert result == 1
