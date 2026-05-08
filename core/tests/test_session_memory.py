"""Tests for openrouter_agent session_memory — all file I/O is mocked.

Run:
    cd core && uv run pytest tests/test_session_memory.py -v
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestReadMemory:
    def test_returns_empty_when_file_missing(self, tmp_path):
        with patch(
            "framework.agents.openrouter_agent.session_memory._MEMORY_FILE",
            tmp_path / "MEMORY.md",
        ):
            from framework.agents.openrouter_agent.session_memory import read_memory

            assert read_memory() == ""

    def test_returns_empty_for_seed_template(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text(
            "# OpenRouter Agent Memory\n\n*No sessions recorded yet.*\n\n## What",
            encoding="utf-8",
        )
        with patch("framework.agents.openrouter_agent.session_memory._MEMORY_FILE", mem_file):
            import importlib

            from framework.agents.openrouter_agent import session_memory

            importlib.reload(session_memory)
            assert session_memory.read_memory() == ""

    def test_returns_real_content(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("## User likes Python.", encoding="utf-8")
        with patch("framework.agents.openrouter_agent.session_memory._MEMORY_FILE", mem_file):
            import importlib

            from framework.agents.openrouter_agent import session_memory

            importlib.reload(session_memory)
            assert "Python" in session_memory.read_memory()


class TestFormatForInjection:
    def test_empty_string_when_no_memory(self, tmp_path):
        with patch(
            "framework.agents.openrouter_agent.session_memory._MEMORY_FILE",
            tmp_path / "MEMORY.md",
        ):
            import importlib

            from framework.agents.openrouter_agent import session_memory

            importlib.reload(session_memory)
            result = session_memory.format_for_injection()
            assert result == ""

    def test_includes_memory_block(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mem_file.write_text("User prefers concise answers.", encoding="utf-8")
        with patch("framework.agents.openrouter_agent.session_memory._MEMORY_FILE", mem_file):
            import importlib

            from framework.agents.openrouter_agent import session_memory

            importlib.reload(session_memory)
            result = session_memory.format_for_injection()
            assert "User prefers concise answers." in result
            assert "Memory From Previous Sessions" in result


class TestConsolidateMemory:
    @pytest.mark.asyncio
    async def test_writes_updated_memory(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mem_file.parent.mkdir(parents=True, exist_ok=True)

        mock_llm = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "User asked about Paris and likes history."
        mock_llm.acomplete = AsyncMock(return_value=mock_response)

        history = [
            {"role": "user", "content": "Tell me about Paris"},
            {"role": "assistant", "content": "Paris is the capital of France."},
        ]

        with (
            patch("framework.agents.openrouter_agent.session_memory._MEMORY_FILE", mem_file),
            patch("framework.agents.openrouter_agent.session_memory._AGENT_DIR", tmp_path),
        ):
            import importlib

            from framework.agents.openrouter_agent import session_memory

            importlib.reload(session_memory)
            await session_memory.consolidate_memory(history, mock_llm)

        assert mem_file.exists()
        content = mem_file.read_text(encoding="utf-8")
        assert "Paris" in content

    @pytest.mark.asyncio
    async def test_empty_history_skips_write(self, tmp_path):
        mem_file = tmp_path / "MEMORY.md"
        mock_llm = MagicMock()
        mock_llm.acomplete = AsyncMock()

        with patch("framework.agents.openrouter_agent.session_memory._MEMORY_FILE", mem_file):
            import importlib

            from framework.agents.openrouter_agent import session_memory

            importlib.reload(session_memory)
            await session_memory.consolidate_memory([], mock_llm)

        assert not mem_file.exists()
        mock_llm.acomplete.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_does_not_raise(self, tmp_path):
        mock_llm = MagicMock()
        mock_llm.acomplete = AsyncMock(side_effect=RuntimeError("network error"))
        history = [{"role": "user", "content": "hello"}]

        with (
            patch(
                "framework.agents.openrouter_agent.session_memory._MEMORY_FILE",
                tmp_path / "MEMORY.md",
            ),
            patch("framework.agents.openrouter_agent.session_memory._AGENT_DIR", tmp_path),
        ):
            import importlib

            from framework.agents.openrouter_agent import session_memory

            importlib.reload(session_memory)
            # Should NOT raise — failures are silently logged
            await session_memory.consolidate_memory(history, mock_llm)
