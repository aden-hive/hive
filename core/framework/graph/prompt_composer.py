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
    from framework.graph.node import NodeSpec, DataBuffer

logger = logging.getLogger(__name__)

# Injected into every worker node's system prompt so the LLM understands
# it is one step in a multi-node pipeline and should not overreach.
EXECUTION_SCOPE_PREAMBLE = (
    "EXECUTION SCOPE: You are one node in a multi-step workflow graph. "
    "Focus ONLY on the task described in your instructions below. "
    "Call set_output() for each of your declared output keys, then stop. "
    "Do NOT attempt work that belongs to other nodes — the framework "
    "routes data between nodes automatically."
)


def _with_datetime(prompt: str) -> str:
    """Append current datetime with local timezone to a system prompt."""
    local = datetime.now().astimezone()
    stamp = f"Current date and time: {local.strftime('%Y-%m-%d %H:%M %Z (UTC%z)')}"
    return f"{prompt}\n\n{stamp}" if prompt else stamp


def build_accounts_prompt(
    accounts: list[dict[str, Any]],
    tool_provider_map: dict[str, str] | None = None,
    node_tool_names: list[str] | None = None,
) -> str:
    """Build a prompt section describing connected accounts.

    When tool_provider_map is provided, produces structured output grouped
    by provider with tool mapping, so the LLM knows which ``account`` value
    to pass to which tool.

    When node_tool_names is also provided, filters to only show providers
    whose tools overlap with the node's tool list.

    Args:
        accounts: List of account info dicts from
            CredentialStoreAdapter.get_all_account_info().
        tool_provider_map: Mapping of tool_name -> provider_name
            (e.g. {"gmail_list_messages": "google"}).
        node_tool_names: Tool names available to the current node.
            When provided, only providers with matching tools are shown.

    Returns:
        Formatted accounts block, or empty string if no accounts.
    """
    if not accounts:
        return ""

    # Flat format (backward compat) when no tool mapping provided
    if tool_provider_map is None:
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

    # --- Structured format: group by provider with tool mapping ---

    # Invert tool_provider_map to provider -> [tools]
    provider_tools: dict[str, list[str]] = {}
    for tool_name, provider in tool_provider_map.items():
        provider_tools.setdefault(provider, []).append(tool_name)

    # Filter to relevant providers based on node tools
    node_tool_set = set(node_tool_names) if node_tool_names else None

    # Group accounts by provider
    provider_accounts: dict[str, list[dict[str, Any]]] = {}
    for acct in accounts:
        provider = acct.get("provider", "unknown")
        provider_accounts.setdefault(provider, []).append(acct)

    sections: list[str] = ["Connected accounts:"]

    for provider, acct_list in provider_accounts.items():
        tools_for_provider = sorted(provider_tools.get(provider, []))

        # If node tools specified, only show providers with overlapping tools
        if node_tool_set is not None:
            relevant_tools = [t for t in tools_for_provider if t in node_tool_set]
            if not relevant_tools:
                continue
            tools_for_provider = relevant_tools

        # Local-only providers: tools read from env vars, no account= routing
        all_local = all(a.get("source") == "local" for a in acct_list)

        # Provider header with tools
        display_name = provider.replace("_", " ").title()
        if tools_for_provider and not all_local:
            tools_str = ", ".join(tools_for_provider)
            sections.append(f'\n{display_name} (use account="<alias>" with: {tools_str}):')
        elif tools_for_provider and all_local:
            tools_str = ", ".join(tools_for_provider)
            sections.append(f"\n{display_name} (tools: {tools_str}):")
        else:
            sections.append(f"\n{display_name}:")

        # Account entries
        for acct in acct_list:
            alias = acct.get("alias", "unknown")
            identity = acct.get("identity", {})
            detail_parts = [f"{k}: {v}" for k, v in identity.items() if v]
            detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
            source_tag = " [local]" if acct.get("source") == "local" else ""
            sections.append(f"  - {provider}/{alias}{detail}{source_tag}")

    # If filtering removed all providers, return empty
    if len(sections) <= 1:
        return ""

    return "\n".join(sections)


def compose_system_prompt(
    identity_prompt: str | None,
    focus_prompt: str | None,
    narrative: str | None = None,
    accounts_prompt: str | None = None,
    skills_catalog_prompt: str | None = None,
    protocols_prompt: str | None = None,
    execution_preamble: str | None = None,
    node_type_preamble: str | None = None,
) -> str:
    """Compose the multi-layer system prompt.

    Args:
        identity_prompt: Layer 1 — static agent identity (from GraphSpec).
        focus_prompt: Layer 3 — per-node focus directive (from NodeSpec.system_prompt).
        narrative: Layer 2 — auto-generated from conversation state.
        accounts_prompt: Connected accounts block (sits between identity and narrative).
        skills_catalog_prompt: Available skills catalog XML (Agent Skills standard).
        protocols_prompt: Default skill operational protocols section.
        execution_preamble: EXECUTION_SCOPE_PREAMBLE for worker nodes
            (prepended before focus so the LLM knows its pipeline scope).
        node_type_preamble: Node-type-specific preamble, e.g. GCU browser
            best-practices prompt (prepended before focus).

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

    # Skills catalog (discovered skills available for activation)
    if skills_catalog_prompt:
        parts.append(f"\n{skills_catalog_prompt}")

    # Operational protocols (default skill behavioral guidance)
    if protocols_prompt:
        parts.append(f"\n{protocols_prompt}")

    # Layer 2: Narrative (what's happened so far)
    if narrative:
        parts.append(f"\n--- Context (what has happened so far) ---\n{narrative}")

    # Execution scope preamble (worker nodes — tells the LLM it is one
    # step in a multi-node pipeline and should not overreach)
    if execution_preamble:
        parts.append(f"\n{execution_preamble}")

    # Node-type preamble (e.g. GCU browser best-practices)
    if node_type_preamble:
        parts.append(f"\n{node_type_preamble}")

    # Layer 3: Focus (current phase directive)
    if focus_prompt:
        parts.append(f"\n--- Current Focus ---\n{focus_prompt}")

    return _with_datetime("\n".join(parts) if parts else "")


def build_narrative(
    buffer: DataBuffer,
    execution_path: list[str],
    graph: GraphSpec,
) -> str:
    """Build Layer 2 (narrative) from structured state.

    Deterministic — no LLM call. Reads data buffer and execution path
    to describe what has happened so far. Cheap and fast.

    Args:
        buffer: Current data buffer state.
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

    # Describe key buffer values (skip very long values)
    all_buffer = buffer.read_all()
    if all_buffer:
        memory_lines: list[str] = []
        for key, value in all_buffer.items():
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
    buffer: DataBuffer,
    cumulative_tool_names: list[str],
    data_dir: Path | str | None = None,
) -> str:
    """Build a 'State of the World' transition marker.

    Inserted into the conversation as a user message at phase boundaries.
    Gives the LLM full situational awareness: what happened, what's stored,
    what tools are available, and what to focus on next.

    Args:
        previous_node: NodeSpec of the phase just completed.
        next_node: NodeSpec of the phase about to start.
        buffer: Current data buffer state.
        cumulative_tool_names: All tools available (cumulative set).
        data_dir: Path to spillover data directory.

    Returns:
        Transition marker message text.
    """
    sections: list[str] = []

    # Header
    sections.append(f"--- PHASE TRANSITION: {previous_node.name} → {next_node.name} ---")

    # What just completed
    sections.append(f"\nCompleted: {previous_node.name}")
    sections.append(f"  {previous_node.description}")

    # Outputs in buffer — use file references for large values so the
    # next node loads full data from disk instead of seeing truncated
    # inline previews that look deceptively complete.
    all_buffer = buffer.read_all()
    if all_buffer:
        memory_lines: list[str] = []
        for key, value in all_buffer.items():
            if value is None:
                continue
            val_str = str(value)
            if len(val_str) > 300 and data_dir:
                # Auto-spill large transition values to data files
                import json as _json

                data_path = Path(data_dir)
                data_path.mkdir(parents=True, exist_ok=True)
                ext = ".json" if isinstance(value, (dict, list)) else ".txt"
                filename = f"output_{key}{ext}"
                try:
                    write_content = (
                        _json.dumps(value, indent=2, ensure_ascii=False)
                        if isinstance(value, (dict, list))
                        else str(value)
                    )
                    (data_path / filename).write_text(write_content, encoding="utf-8")
                    file_size = (data_path / filename).stat().st_size
                    val_str = (
                        f"[Saved to '{filename}' ({file_size:,} bytes). "
                        f"Use load_data(filename='{filename}') to access.]"
                    )
                except Exception:
                    val_str = val_str[:300] + "..."
            elif len(val_str) > 300:
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
                        "\nData files (use load_data to access):\n" + "\n".join(file_lines)
                    )

    # Available tools
    if cumulative_tool_names:
        sections.append("\nAvailable tools: " + ", ".join(sorted(cumulative_tool_names)))

    # Next phase
    sections.append(f"\nNow entering: {next_node.name}")
    sections.append(f"  {next_node.description}")
    if next_node.output_keys:
        sections.append(
            f"\nYour ONLY job in this phase: complete the task above and call "
            f"set_output() for {next_node.output_keys}. Do NOT do work that "
            f"belongs to later phases."
        )

    # Reflection prompt (engineered metacognition)
    sections.append(
        "\nBefore proceeding, briefly reflect: what went well in the "
        "previous phase? Are there any gaps or surprises worth noting?"
    )

    sections.append("\n--- END TRANSITION ---")

    return "\n".join(sections)
