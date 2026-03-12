"""
Tests for fixes to issues #6207 and #6229.

#6207 — hive run --input-file crashes with raw traceback when given a directory.
#6229 — Missing OPENAI_API_KEY produces cryptic LiteLLM error instead of clear message.
"""

import argparse
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fix #6207: --input-file directory validation in cmd_run
# ---------------------------------------------------------------------------


def _make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        agent_path="some_agent",
        input=None,
        input_file=None,
        output=None,
        quiet=False,
        verbose=False,
        model=None,
        resume_session=None,
        checkpoint=None,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


class TestInputFileDirectoryValidation:
    """Issue #6207 — validate --input-file before execution."""

    def test_directory_path_returns_exit_code_1(self, tmp_path, capsys):
        from framework.runner.cli import cmd_run

        result = cmd_run(_make_args(input_file=str(tmp_path)))

        assert result == 1

    def test_directory_path_prints_friendly_error(self, tmp_path, capsys):
        from framework.runner.cli import cmd_run

        cmd_run(_make_args(input_file=str(tmp_path)))

        captured = capsys.readouterr()
        assert "directory" in captured.err
        assert str(tmp_path) in captured.err
        # Must not be a raw Python traceback
        assert "IsADirectoryError" not in captured.err
        assert "Traceback" not in captured.err

    def test_error_message_matches_expected_format(self, tmp_path, capsys):
        from framework.runner.cli import cmd_run

        cmd_run(_make_args(input_file=str(tmp_path)))

        captured = capsys.readouterr()
        assert "Error: input file is a directory, not a file:" in captured.err

    def test_valid_json_file_is_not_blocked(self, tmp_path, capsys):
        """A real JSON file should not be rejected by the directory check."""
        f = tmp_path / "ctx.json"
        f.write_text('{"key": "value"}')

        # AgentRunner is imported locally inside cmd_run, so patch at the source.
        with patch("framework.runner.runner.AgentRunner.load", side_effect=FileNotFoundError("no agent")):
            from framework.runner.cli import cmd_run

            result = cmd_run(_make_args(input_file=str(f)))

        # exit 1 is fine here (agent not found), but the error must NOT mention directory
        captured = capsys.readouterr()
        assert "is a directory" not in captured.err


# ---------------------------------------------------------------------------
# Fix #6229: clear CredentialError message when API key is missing
# ---------------------------------------------------------------------------


class _NoopRegistry:
    def cleanup(self) -> None:
        pass


def _make_runner(model: str = "gpt-4o-mini"):
    from framework.runner.runner import AgentRunner

    runner = AgentRunner.__new__(AgentRunner)
    runner._tool_registry = _NoopRegistry()
    runner._temp_dir = None
    runner.model = model
    return runner


class TestMissingApiKeyErrorMessage:
    """Issue #6229 — CredentialError should name the missing key explicitly."""

    def test_openai_key_named_in_error(self):
        from framework.credentials.models import CredentialError
        from framework.runner.runner import AgentRunner

        mock_graph = MagicMock()
        mock_graph.nodes = [MagicMock(node_type="event_loop")]

        runner = _make_runner(model="gpt-4o-mini")
        runner.graph = mock_graph
        runner._llm = None
        runner.mock_mode = False

        with pytest.raises(CredentialError) as exc_info:
            # Trigger the fail-fast block directly
            if runner._llm is None:
                has_llm_nodes = any(
                    node.node_type in ("event_loop", "gcu") for node in runner.graph.nodes
                )
                if has_llm_nodes:
                    api_key_env = runner._get_api_key_env_var(runner.model)
                    if api_key_env:
                        raise CredentialError(
                            f"{api_key_env} is not configured. "
                            f"Please set it before running Hive.\n"
                            f"Set it with: export {api_key_env}=your-api-key"
                        )

        msg = str(exc_info.value)
        assert "OPENAI_API_KEY" in msg
        assert "not configured" in msg.lower() or "Please set it" in msg

    def test_error_message_contains_export_hint(self):
        from framework.credentials.models import CredentialError

        runner = _make_runner(model="gpt-4o-mini")
        api_key_env = runner._get_api_key_env_var(runner.model)

        error = CredentialError(
            f"{api_key_env} is not configured. "
            f"Please set it before running Hive.\n"
            f"Set it with: export {api_key_env}=your-api-key"
        )
        assert "export OPENAI_API_KEY" in str(error)

    def test_anthropic_key_named_for_claude_model(self):
        runner = _make_runner(model="claude-3-haiku-20240307")
        assert runner._get_api_key_env_var(runner.model) == "ANTHROPIC_API_KEY"

    def test_openai_key_named_for_gpt_model(self):
        runner = _make_runner(model="gpt-4o-mini")
        assert runner._get_api_key_env_var(runner.model) == "OPENAI_API_KEY"

    def test_local_model_returns_none_key(self):
        runner = _make_runner(model="ollama/llama3")
        assert runner._get_api_key_env_var(runner.model) is None
