"""
CLI entry point for the Meeting Notes Agent.

Usage:
    hive run examples/templates/meeting_notes_agent --input '{"transcript": "..."}'

    # Or directly:
    PYTHONPATH=examples/templates uv run python -m meeting_notes_agent run \\
        --input '{"transcript": "...", "slack_channel": "#team-standup"}'

    # With Gemini as LLM:
    PYTHONPATH=examples/templates uv run python -m meeting_notes_agent run \\
        --input '{"transcript": "...", "llm_provider": "gemini"}'

    # Validate structure:
    PYTHONPATH=examples/templates uv run python -m meeting_notes_agent validate

    # Run tests:
    PYTHONPATH=examples/templates uv run python -m meeting_notes_agent test
"""

import sys
import os

# Allow running from repo root with PYTHONPATH=examples/templates
sys.path.insert(0, os.path.dirname(__file__))

from framework.runner import run_agent_cli  # noqa: E402

if __name__ == "__main__":
    run_agent_cli(agent_dir=os.path.dirname(__file__))