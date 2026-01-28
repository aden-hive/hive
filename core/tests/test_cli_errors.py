"""Tests for structured CLI error handling."""

import argparse

import pytest

from framework.errors import (
    CLIError,
    CLIErrorContext,
    _resolve_error,
    cli_error_handler,
    format_error,
)

# ---------------------------------------------------------------------------
# CLIError basics
# ---------------------------------------------------------------------------


class TestCLIError:
    def test_message_and_hint(self):
        err = CLIError("something broke", hint="try this")
        assert err.message == "something broke"
        assert err.hint == "try this"
        assert str(err) == "something broke"

    def test_defaults(self):
        err = CLIError("oops")
        assert err.hint == ""
        assert err.details == ""


# ---------------------------------------------------------------------------
# Error formatting
# ---------------------------------------------------------------------------


class TestFormatError:
    def test_basic_format(self):
        err = CLIError("Agent not found", hint="Run hive list")
        output = format_error(err)
        assert "Error: Agent not found" in output
        assert "Hint: Run hive list" in output

    def test_no_hint(self):
        err = CLIError("Boom")
        output = format_error(err)
        assert "Error: Boom" in output
        assert "Hint" not in output

    def test_with_details(self):
        err = CLIError("Bad input", details="line 3, col 5")
        output = format_error(err)
        assert "Details: line 3, col 5" in output


# ---------------------------------------------------------------------------
# Error resolution (exception mapping)
# ---------------------------------------------------------------------------


class TestResolveError:
    def test_key_error_known_rename(self):
        result = _resolve_error(KeyError("steps"))
        assert "steps" in result.message
        assert "nodes" in result.hint

    def test_key_error_unknown(self):
        result = _resolve_error(KeyError("foo_bar"))
        assert "foo_bar" in result.message
        assert "hive validate" in result.hint

    def test_file_not_found_agent(self):
        exc = FileNotFoundError("agent.json not found")
        exc.filename = "/path/to/agent.json"
        result = _resolve_error(exc)
        assert "agent.json" in result.message.lower() or "agent" in result.message.lower()
        assert "hive list" in result.hint

    def test_file_not_found_generic(self):
        exc = FileNotFoundError("no such file")
        exc.filename = "/some/config.yaml"
        result = _resolve_error(exc)
        assert "config.yaml" in result.message

    def test_module_not_found_framework(self):
        exc = ModuleNotFoundError("No module named 'framework'")
        exc.name = "framework"
        result = _resolve_error(exc)
        assert "PYTHONPATH" in result.hint

    def test_module_not_found_third_party(self):
        exc = ModuleNotFoundError("No module named 'pandas'")
        exc.name = "pandas"
        result = _resolve_error(exc)
        assert "pip install pandas" in result.hint

    def test_permission_error(self):
        result = _resolve_error(PermissionError("access denied"))
        assert "Permission" in result.message or "permission" in result.message

    def test_generic_fallback(self):
        result = _resolve_error(RuntimeError("unexpected thing"))
        assert "unexpected thing" in result.message
        assert "--verbose" in result.hint

    def test_cli_error_passthrough(self):
        original = CLIError("custom", hint="custom hint")
        result = _resolve_error(original)
        assert result is original


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


class TestCLIErrorHandler:
    def test_normal_return(self):
        @cli_error_handler
        def good_cmd(args):
            return 0

        assert good_cmd(argparse.Namespace()) == 0

    def test_catches_cli_error(self, capsys):
        @cli_error_handler
        def bad_cmd(args):
            raise CLIError("test error", hint="test hint")

        result = bad_cmd(argparse.Namespace())
        assert result == 1
        captured = capsys.readouterr()
        assert "Error: test error" in captured.err
        assert "Hint: test hint" in captured.err

    def test_catches_generic_exception(self, capsys):
        @cli_error_handler
        def exploding_cmd(args):
            raise KeyError("steps")

        result = exploding_cmd(argparse.Namespace())
        assert result == 1
        captured = capsys.readouterr()
        assert "steps" in captured.err

    def test_keyboard_interrupt(self, capsys):
        @cli_error_handler
        def interrupted_cmd(args):
            raise KeyboardInterrupt()

        result = interrupted_cmd(argparse.Namespace())
        assert result == 130

    def test_system_exit_passthrough(self):
        @cli_error_handler
        def exiting_cmd(args):
            raise SystemExit(42)

        with pytest.raises(SystemExit) as exc_info:
            exiting_cmd(argparse.Namespace())
        assert exc_info.value.code == 42

    def test_verbose_shows_traceback(self, capsys):
        @cli_error_handler
        def failing_cmd(args):
            raise ValueError("details matter")

        result = failing_cmd(argparse.Namespace(verbose=True))
        assert result == 1
        captured = capsys.readouterr()
        assert "ValueError" in captured.err


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestCLIErrorContext:
    def test_suppresses_exception(self, capsys):
        with CLIErrorContext():
            raise RuntimeError("boom")

        captured = capsys.readouterr()
        assert "boom" in captured.err

    def test_no_exception(self):
        with CLIErrorContext():
            pass  # no error

    def test_keyboard_interrupt_propagates(self):
        with pytest.raises(KeyboardInterrupt):
            with CLIErrorContext():
                raise KeyboardInterrupt()

    def test_system_exit_propagates(self):
        with pytest.raises(SystemExit):
            with CLIErrorContext():
                raise SystemExit(1)
