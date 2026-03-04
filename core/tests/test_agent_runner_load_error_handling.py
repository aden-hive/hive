"""Tests for AgentRunner.load() error handling with malformed agent.json."""

import json
import tempfile
from pathlib import Path
import pytest

from framework.runner import AgentRunner


class TestAgentRunnerLoadErrorHandling:
    """Test error handling when loading agents with problematic agent.json files."""

    def test_empty_agent_json(self):
        """Test that empty agent.json raises clear ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            agent_json = agent_path / "agent.json"
            agent_json.write_text("")

            with pytest.raises(ValueError) as exc_info:
                AgentRunner.load(agent_path)

            assert "agent.json is empty" in str(exc_info.value)

    def test_whitespace_only_agent_json(self):
        """Test that whitespace-only agent.json raises clear ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            agent_json = agent_path / "agent.json"
            agent_json.write_text("   \n\n  \t  ")

            with pytest.raises(ValueError) as exc_info:
                AgentRunner.load(agent_path)

            assert "agent.json is empty" in str(exc_info.value)

    def test_agent_json_is_directory(self):
        """Test that agent.json being a directory raises clear ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            agent_json = agent_path / "agent.json"
            agent_json.mkdir()

            with pytest.raises(ValueError) as exc_info:
                AgentRunner.load(agent_path)

            assert "agent.json is not a file" in str(exc_info.value)
            assert "directory" in str(exc_info.value)

    def test_invalid_json_in_agent_json(self):
        """Test that invalid JSON in agent.json raises clear ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)
            agent_json = agent_path / "agent.json"
            agent_json.write_text("{invalid json content")

            with pytest.raises(ValueError) as exc_info:
                AgentRunner.load(agent_path)

            assert "not valid JSON" in str(exc_info.value)

    def test_no_agent_files(self):
        """Test that missing both agent.py and agent.json raises FileNotFoundError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            agent_path = Path(tmpdir)

            with pytest.raises(FileNotFoundError) as exc_info:
                AgentRunner.load(agent_path)

            assert "No agent.py or agent.json found" in str(exc_info.value)
