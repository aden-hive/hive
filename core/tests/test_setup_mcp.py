"""Tests for setup_mcp.py - MCP server installation and configuration script."""

import json
import logging
import subprocess
import sys
from unittest.mock import MagicMock, Mock, mock_open, patch

import pytest

# Import the module under test
import setup_mcp
from setup_mcp import (
    Colors,
    log_error,
    log_step,
    log_success,
    main,
    run_command,
    setup_logger,
)


class TestSetupLogger:
    """Tests for setup_logger function."""

    def test_setup_logger_configures_handler(self):
        """setup_logger() should configure logging with StreamHandler."""
        # Clear any existing handlers
        setup_mcp.logger.handlers.clear()

        setup_logger()

        assert len(setup_mcp.logger.handlers) == 1
        assert isinstance(setup_mcp.logger.handlers[0], logging.StreamHandler)
        assert setup_mcp.logger.level == logging.INFO

    def test_setup_logger_idempotent(self):
        """setup_logger() should not add duplicate handlers."""
        # Clear handlers first
        setup_mcp.logger.handlers.clear()

        setup_logger()
        handler_count = len(setup_mcp.logger.handlers)

        # Call again
        setup_logger()

        assert len(setup_mcp.logger.handlers) == handler_count

    def test_setup_logger_formatter(self):
        """setup_logger() should set correct formatter."""
        setup_mcp.logger.handlers.clear()

        setup_logger()

        handler = setup_mcp.logger.handlers[0]
        formatter = handler.formatter
        assert formatter is not None
        assert formatter._fmt == "%(message)s"


class TestColors:
    """Tests for Colors class."""

    def test_colors_defined(self):
        """Colors class should have all ANSI color codes."""
        assert hasattr(Colors, "GREEN")
        assert hasattr(Colors, "YELLOW")
        assert hasattr(Colors, "RED")
        assert hasattr(Colors, "BLUE")
        assert hasattr(Colors, "NC")
        assert Colors.GREEN == "\033[0;32m"
        assert Colors.NC == "\033[0m"


class TestLogFunctions:
    """Tests for log_step, log_success, log_error functions."""

    @patch("setup_mcp.logger")
    def test_log_step(self, mock_logger):
        """log_step() should log message with yellow color."""
        log_step("Test step")

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "Test step" in call_args
        assert Colors.YELLOW in call_args
        assert Colors.NC in call_args

    @patch("setup_mcp.logger")
    def test_log_success(self, mock_logger):
        """log_success() should log message with green color and checkmark."""
        log_success("Test success")

        mock_logger.info.assert_called_once()
        call_args = mock_logger.info.call_args[0][0]
        assert "Test success" in call_args
        assert Colors.GREEN in call_args
        assert "✓" in call_args

    @patch("setup_mcp.logger")
    def test_log_error(self, mock_logger):
        """log_error() should log message with red color and cross mark."""
        log_error("Test error")

        mock_logger.error.assert_called_once()
        call_args = mock_logger.error.call_args[0][0]
        assert "Test error" in call_args
        assert Colors.RED in call_args
        assert "✗" in call_args


class TestRunCommand:
    """Tests for run_command function."""

    @patch("subprocess.run")
    @patch("setup_mcp.log_error")
    @patch("setup_mcp.logger")
    def test_run_command_success(self, mock_logger, mock_log_error, mock_subprocess):
        """run_command() should return True on successful command execution."""
        mock_subprocess.return_value = Mock(returncode=0)

        result = run_command(["echo", "test"], "Error message")

        assert result is True
        mock_subprocess.assert_called_once_with(
            ["echo", "test"], check=True, capture_output=True, text=True
        )
        mock_log_error.assert_not_called()

    @patch("subprocess.run")
    @patch("setup_mcp.log_error")
    @patch("setup_mcp.logger")
    def test_run_command_failure(self, mock_logger, mock_log_error, mock_subprocess):
        """run_command() should return False and log error on failure."""
        error = subprocess.CalledProcessError(1, "cmd", stderr="error output")
        mock_subprocess.side_effect = error

        result = run_command(["false"], "Command failed")

        assert result is False
        mock_log_error.assert_called_once_with("Command failed")
        mock_logger.error.assert_called_once()
        assert "error output" in mock_logger.error.call_args[0][0]

    @patch("subprocess.run")
    def test_run_command_captures_output(self, mock_subprocess):
        """run_command() should capture command output."""
        mock_subprocess.return_value = Mock(returncode=0)

        run_command(["test", "command"], "Error")

        call_kwargs = mock_subprocess.call_args[1]
        assert call_kwargs["capture_output"] is True
        assert call_kwargs["text"] is True


class TestMain:
    """Tests for main function."""

    @patch("setup_mcp.setup_logger")
    @patch("setup_mcp.run_command")
    @patch("setup_mcp.log_step")
    @patch("setup_mcp.log_success")
    @patch("setup_mcp.logger")
    @patch("os.chdir")
    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.exists")
    def test_main_success_with_existing_config(
        self,
        mock_exists,
        mock_file_open,
        mock_chdir,
        mock_logger,
        mock_log_success,
        mock_log_step,
        mock_run_command,
        mock_setup_logger,
        tmp_path,
    ):
        """main() should complete successfully when .mcp.json exists."""
        # Setup mocks
        mock_run_command.return_value = True
        mock_exists.return_value = True  # .mcp.json exists

        config = {
            "mcpServers": {
                "agent-builder": {
                    "command": "python",
                    "args": ["-m", "framework.mcp.agent_builder_server"],
                }
            }
        }
        mock_file_open.return_value.read.return_value = json.dumps(config)
        mock_file_open.return_value.__enter__.return_value.read.return_value = json.dumps(config)

        with patch("setup_mcp.Path") as mock_path_class:
            mock_path_instance = MagicMock()
            mock_path_instance.parent.absolute.return_value = tmp_path
            mock_path_class.return_value = mock_path_instance

            main()

        # Verify setup_logger was called
        mock_setup_logger.assert_called_once()

        # Verify run_command was called for pip installations
        assert mock_run_command.call_count >= 2  # Package install + MCP deps

    @patch("setup_mcp.setup_logger")
    @patch("setup_mcp.run_command")
    @patch("setup_mcp.log_error")
    @patch("setup_mcp.logger")
    @patch("os.chdir")
    @patch("pathlib.Path.exists")
    def test_main_exits_on_package_install_failure(
        self,
        mock_exists,
        mock_chdir,
        mock_logger,
        mock_log_error,
        mock_run_command,
        mock_setup_logger,
        tmp_path,
    ):
        """main() should exit with code 1 if package installation fails."""
        mock_run_command.return_value = False  # Simulate failure

        with patch("setup_mcp.Path") as mock_path_class:
            mock_path_instance = MagicMock()
            mock_path_instance.parent.absolute.return_value = tmp_path
            mock_path_class.return_value = mock_path_instance

            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 1

    @patch("setup_mcp.setup_logger")
    @patch("setup_mcp.run_command")
    @patch("setup_mcp.log_step")
    @patch("setup_mcp.log_success")
    @patch("setup_mcp.logger")
    @patch("os.chdir")
    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.exists")
    def test_main_creates_config_if_missing(
        self,
        mock_exists,
        mock_file_open,
        mock_chdir,
        mock_logger,
        mock_log_success,
        mock_log_step,
        mock_run_command,
        mock_setup_logger,
        tmp_path,
    ):
        """main() should create .mcp.json if it doesn't exist."""
        mock_run_command.return_value = True
        mock_exists.return_value = False  # .mcp.json doesn't exist

        with patch("setup_mcp.Path") as mock_path_class:
            mock_path_instance = MagicMock()
            mock_path_instance.parent.absolute.return_value = tmp_path
            mock_path_class.return_value = mock_path_instance

            main()

        # Verify file was opened for writing
        mock_file_open.assert_called()

    @patch("setup_mcp.setup_logger")
    @patch("setup_mcp.run_command")
    @patch("setup_mcp.log_error")
    @patch("setup_mcp.logger")
    @patch("os.chdir")
    @patch("pathlib.Path.exists")
    @patch("subprocess.run")
    def test_main_exits_on_mcp_server_test_failure(
        self,
        mock_subprocess,
        mock_exists,
        mock_chdir,
        mock_logger,
        mock_log_error,
        mock_run_command,
        mock_setup_logger,
        tmp_path,
    ):
        """main() should exit if MCP server module test fails."""
        # First two run_command calls succeed (package and MCP install)
        mock_run_command.return_value = True
        mock_exists.return_value = True

        # subprocess.run for module test fails
        mock_subprocess.side_effect = subprocess.CalledProcessError(1, "cmd", stderr="import error")

        config = {"mcpServers": {}}
        with patch("builtins.open", mock_open(read_data=json.dumps(config))):
            with patch("setup_mcp.Path") as mock_path_class:
                mock_path_instance = MagicMock()
                mock_path_instance.parent.absolute.return_value = tmp_path
                mock_path_class.return_value = mock_path_instance

                with pytest.raises(SystemExit) as exc_info:
                    main()

                assert exc_info.value.code == 1

    @patch("setup_mcp.setup_logger")
    @patch("setup_mcp.run_command")
    @patch("setup_mcp.logger")
    @patch("os.chdir")
    @patch("pathlib.Path.exists")
    def test_main_uses_sys_executable(
        self,
        mock_exists,
        mock_chdir,
        mock_logger,
        mock_run_command,
        mock_setup_logger,
        tmp_path,
    ):
        """main() should use sys.executable for pip commands."""
        mock_run_command.return_value = True
        mock_exists.return_value = True

        config = {"mcpServers": {}}
        with patch("builtins.open", mock_open(read_data=json.dumps(config))):
            with patch("setup_mcp.Path") as mock_path_class:
                mock_path_instance = MagicMock()
                mock_path_instance.parent.absolute.return_value = tmp_path
                mock_path_class.return_value = mock_path_instance

                main()

        # Check that sys.executable was used in pip commands
        calls = mock_run_command.call_args_list
        pip_calls = [call for call in calls if "-m" in str(call) and "pip" in str(call)]
        assert len(pip_calls) >= 2  # At least 2 pip install commands

        for call in pip_calls:
            cmd = call[0][0]
            assert cmd[0] == sys.executable
            assert cmd[1:3] == ["-m", "pip"]


class TestMainIntegration:
    """Integration-style tests for main function workflow."""

    @patch("setup_mcp.setup_logger")
    @patch("subprocess.run")
    @patch("os.chdir")
    @patch("builtins.open", new_callable=mock_open)
    @patch("pathlib.Path.exists")
    @patch("setup_mcp.logger")
    def test_main_full_workflow(
        self,
        mock_logger,
        mock_exists,
        mock_file_open,
        mock_chdir,
        mock_subprocess,
        mock_setup_logger,
        tmp_path,
    ):
        """Test full workflow: install packages, create/read config, test server."""
        # All subprocess calls succeed
        mock_subprocess.return_value = Mock(returncode=0, stderr="", stdout="")
        mock_exists.return_value = False  # Config doesn't exist initially

        with patch("setup_mcp.Path") as mock_path_class:
            mock_path_instance = MagicMock()
            mock_path_instance.parent.absolute.return_value = tmp_path
            mock_path_class.return_value = mock_path_instance

            main()

        # Verify all steps were executed
        # 1. Package installation
        # 2. MCP dependencies installation
        # 3. Config creation (since it didn't exist)
        # 4. MCP server test
        assert mock_subprocess.call_count >= 3

    @patch("setup_mcp.setup_logger")
    @patch("subprocess.run")
    @patch("os.chdir")
    @patch("pathlib.Path.exists")
    @patch("setup_mcp.logger")
    def test_main_changes_to_script_directory(
        self,
        mock_logger,
        mock_exists,
        mock_chdir,
        mock_subprocess,
        mock_setup_logger,
        tmp_path,
    ):
        """main() should change to script directory before operations."""
        mock_subprocess.return_value = Mock(returncode=0)
        mock_exists.return_value = True

        config = {"mcpServers": {}}
        with patch("builtins.open", mock_open(read_data=json.dumps(config))):
            with patch("setup_mcp.Path") as mock_path_class:
                mock_path_instance = MagicMock()
                mock_path_instance.parent.absolute.return_value = tmp_path
                mock_path_class.return_value = mock_path_instance

                main()

        # Verify os.chdir was called
        assert mock_chdir.called
