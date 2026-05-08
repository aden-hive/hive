"""
OpenRouter Agent — free open-source model access for the Hive framework.

Features:
  1. Session memory  — remembers context across runs (~/.hive/openrouter_agent/MEMORY.md)
  2. Model picker    — TUI lets you choose any free model before starting
  3. Web search      — web_search, read_file, write_file tools built in
  4. Default skills  — hive.note-taking and hive.task-decomposition enabled
  5. Fallback chain  — auto-retries with next free model on 429 rate limits

Quick start:
    export OPENROUTER_API_KEY=sk-or-v1-...
    uv run hive run
    # pick "OpenRouter Agent" from the TUI
"""

from .agent import OpenRouterAgent, configure_for_account, goal, list_connected_accounts
from .config import AgentMetadata, default_config, metadata
from .nodes import build_chat_node

__version__ = "1.0.0"

__all__ = [
    "OpenRouterAgent",
    "goal",
    "list_connected_accounts",
    "configure_for_account",
    "AgentMetadata",
    "default_config",
    "metadata",
    "build_chat_node",
]
