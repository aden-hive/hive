"""Prompt composition for continuous agent mode.

Composes the three-layer system prompt (onion model) and generates
transition markers inserted into the conversation at phase boundaries.

Layer 1 — Identity (static, defined at agent level, never changes):
  "You are a thorough research agent. You prefer clarity over jargon..."

Layer 2 — Narrative (auto-generated from conversation/memory state):
  "We've finished scoping the project. The user wants to focus on..."

Layer 3 — Focus (per-node system_prompt, reframed as focus directive):
  "Your current attention: synthesize findings into a report..."
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.graph.edge import GraphSpec
    from framework.graph.node import NodeSpec, SharedMemory

logger = logging.getLogger(__name__)


def _with_datetime(prompt: str) -> str:
    """Append current datetime with local timezone to a system prompt."""
    local = datetime.now().astimezone()
    stamp = f"Current date and time: {local.strftime('%Y-%m-%d %H:%M %Z (UTC%z)')}"
    return f"{prompt}\n\n{stamp}" if prompt else stamp


def build_accounts_prompt(accounts: list[dict[str, Any]]) -> str:
    """Build a prompt section describing connected accounts.

    Args:
        accounts: List of account info dicts from CredentialStoreAdapter.get_all_account_info().

    Returns:
        Formatted accounts block, or empty string if no accounts.
    """
    if not accounts:
        return ""
    lines = [
        "Connected accounts (use the alias as the `account` parameter "
        "when calling tools to target a specific account):"
    ]
    for acct in accounts:
        provider = acct.get("provider", "unknown")
        alias = acct.get("alias", "unknown")
        identity = acct.get("identity", {})
        detail_parts = [f"{k}: {v}" for k, v in identity.items() if v]
        detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
        lines.append(f"- {provider}/{alias}{detail}")
    return "\n".join(lines)


def compose_system_prompt(
    identity_prompt: str | None,
    focus_prompt: str | None,
    narrative: str | None = None,
    accounts_prompt: str | None = None,
) -> str:
    """Compose the three-layer system prompt.

    Args:
        identity_prompt: Layer 1 — static agent identity (from GraphSpec).
        focus_prompt: Layer 3 — per-node focus directive (from NodeSpec.system_prompt).
        narrative: Layer 2 — auto-generated from conversation state.
        accounts_prompt: Connected accounts block (sits between identity and narrative).

    Returns:
        Composed system prompt with all layers present, plus current datetime.
    """
    parts: list[str] = []

    # Layer 1: Identity (always first, anchors the personality)
    if identity_prompt:
        parts.append(identity_prompt)

    # Accounts (semi-static, deployment-specific)
    if accounts_prompt:
        parts.append(f"\n{accounts_prompt}")

    # Layer 2: Narrative (what's happened so far)
    if narrative:
        parts.append(f"\n--- Context (what has happened so far) ---\n{narrative}")

    # Layer 3: Focus (current phase directive)
    if focus_prompt:
        parts.append(f"\n--- Current Focus ---\n{focus_prompt}")

    return _with_datetime("\n".join(parts) if parts else "")


def build_narrative(
    memory: SharedMemory,
    execution_path: list[str],
    graph: GraphSpec,
) -> str:
    """Build Layer 2 (narrative) from structured state.

    Deterministic — no LLM call. Reads SharedMemory and execution path
    to describe what has happened so far. Cheap and fast.

    Args:
        memory: Current shared memory state.
        execution_path: List of node IDs visited so far.
        graph: Graph spec (for node names/descriptions).

    Returns:
        Narrative string describing the session state.
    """
    parts: list[str] = []

    # Describe execution path
    if execution_path:
        phase_descriptions: list[str] = []
        for node_id in execution_path:
            node_spec = graph.get_node(node_id)
            if node_spec:
                phase_descriptions.append(f"- {node_spec.name}: {node_spec.description}")
            else:
                phase_descriptions.append(f"- {node_id}")
        parts.append("Phases completed:\n" + "\n".join(phase_descriptions))

    # Describe key memory values (skip very long values)
    all_memory = memory.read_all()
    if all_memory:
        memory_lines: list[str] = []
        for key, value in all_memory.items():
            if value is None:
                continue
            val_str = str(value)
            if len(val_str) > 200:
                val_str = val_str[:200] + "..."
            memory_lines.append(f"- {key}: {val_str}")
        if memory_lines:
            parts.append("Current state:\n" + "\n".join(memory_lines))

    return "\n\n".join(parts) if parts else ""


def build_transition_marker(
    previous_node: NodeSpec,
    next_node: NodeSpec,
    memory: SharedMemory,
    cumulative_tool_names: list[str],
    data_dir: Path | str | None = None,
    adapt_content: str | None = None,
) -> str:
    """Build a 'State of the World' transition marker.

    Inserted into the conversation as a user message at phase boundaries.
    Gives the LLM full situational awareness: what happened, what's stored,
    what tools are available, and what to focus on next.

    Args:
        previous_node: NodeSpec of the phase just completed.
        next_node: NodeSpec of the phase about to start.
        memory: Current shared memory state.
        cumulative_tool_names: All tools available (cumulative set).
        data_dir: Path to spillover data directory.
        adapt_content: Agent working memory (adapt.md) content.

    Returns:
        Transition marker message text.
    """
    sections: list[str] = []

    # Header
    sections.append(f"--- PHASE TRANSITION: {previous_node.name} → {next_node.name} ---")

    # What just completed
    sections.append(f"\nCompleted: {previous_node.name}")
    sections.append(f"  {previous_node.description}")

    # Outputs in memory
    all_memory = memory.read_all()
    if all_memory:
        memory_lines: list[str] = []
        for key, value in all_memory.items():
            if value is None:
                continue
            val_str = str(value)
            if len(val_str) > 300:
                val_str = val_str[:300] + "..."
            memory_lines.append(f"  {key}: {val_str}")
        if memory_lines:
            sections.append("\nOutputs available:\n" + "\n".join(memory_lines))

    # Files in data directory
    if data_dir:
        data_path = Path(data_dir)
        if data_path.exists():
            files = sorted(data_path.iterdir())
            if files:
                file_lines = [
                    f"  {f.name} ({f.stat().st_size:,} bytes)" for f in files if f.is_file()
                ]
                if file_lines:
                    sections.append(
                        "\nData files (use read_file to access):\n" + "\n".join(file_lines)
                    )

    # Agent working memory
    if adapt_content:
        sections.append(f"\n--- Agent Memory ---\n{adapt_content}")

    # Available tools
    if cumulative_tool_names:
        sections.append("\nAvailable tools: " + ", ".join(sorted(cumulative_tool_names)))

    # Next phase
    sections.append(f"\nNow entering: {next_node.name}")
    sections.append(f"  {next_node.description}")

    # Reflection prompt (engineered metacognition)
    sections.append(
        "\nBefore proceeding, briefly reflect: what went well in the "
        "previous phase? Are there any gaps or surprises worth noting?"
    )

    sections.append("\n--- END TRANSITION ---")

    return "\n".join(sections)
