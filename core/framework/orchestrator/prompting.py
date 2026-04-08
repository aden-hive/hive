"""Pure prompt rendering helpers for graph execution.

This module owns all prompt text assembly for graph nodes.
It intentionally avoids side effects so runtime code can prepare any
spill files or transition metadata separately and then pass plain data in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.orchestrator.edge import GraphSpec
    from framework.orchestrator.node import DataBuffer


# Injected into every worker node's system prompt so the LLM understands
# it is one step in a multi-node pipeline and should not overreach.
EXECUTION_SCOPE_PREAMBLE = (
    "EXECUTION SCOPE: You are one node in a multi-step workflow graph. "
    "Focus ONLY on the task described in your instructions below. "
    "Call set_output() for each of your declared output keys, then stop. "
    "Do NOT attempt work that belongs to other nodes - the framework "
    "routes data between nodes automatically."
)


@dataclass(frozen=True)
class NodePromptSpec:
    """Structured inputs for building one node system prompt."""

    identity_prompt: str = ""
    focus_prompt: str = ""
    narrative: str = ""
    accounts_prompt: str = ""
    skills_catalog_prompt: str = ""
    protocols_prompt: str = ""
    memory_prompt: str = ""
    node_type: str = "event_loop"
    output_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class TransitionSpec:
    """Structured inputs for a transition marker message."""

    previous_name: str
    previous_description: str
    next_name: str
    next_description: str
    next_output_keys: tuple[str, ...] = ()
    buffer_items: dict[str, str] = field(default_factory=dict)
    cumulative_tool_names: tuple[str, ...] = ()
    data_files: tuple[str, ...] = ()


def stamp_prompt_datetime(prompt: str) -> str:
    """Append current datetime with local timezone to a prompt."""
    local = datetime.now().astimezone()
    stamp = f"Current date and time: {local.strftime('%Y-%m-%d %H:%M %Z (UTC%z)')}"
    return f"{prompt}\n\n{stamp}" if prompt else stamp


def build_accounts_prompt(
    accounts: list[dict[str, Any]],
    tool_provider_map: dict[str, str] | None = None,
    node_tool_names: list[str] | None = None,
) -> str:
    """Build a prompt section describing connected accounts."""
    if not accounts:
        return ""

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

    provider_tools: dict[str, list[str]] = {}
    for tool_name, provider in tool_provider_map.items():
        provider_tools.setdefault(provider, []).append(tool_name)

    node_tool_set = set(node_tool_names) if node_tool_names else None

    provider_accounts: dict[str, list[dict[str, Any]]] = {}
    for acct in accounts:
        provider = acct.get("provider", "unknown")
        provider_accounts.setdefault(provider, []).append(acct)

    sections: list[str] = ["Connected accounts:"]

    for provider, acct_list in provider_accounts.items():
        tools_for_provider = sorted(provider_tools.get(provider, []))

        if node_tool_set is not None:
            relevant_tools = [
                tool_name for tool_name in tools_for_provider if tool_name in node_tool_set
            ]
            if not relevant_tools:
                continue
            tools_for_provider = relevant_tools

        all_local = all(acct.get("source") == "local" for acct in acct_list)
        display_name = provider.replace("_", " ").title()
        if tools_for_provider and not all_local:
            tools_str = ", ".join(tools_for_provider)
            sections.append(f'\n{display_name} (use account="<alias>" with: {tools_str}):')
        elif tools_for_provider and all_local:
            tools_str = ", ".join(tools_for_provider)
            sections.append(f"\n{display_name} (tools: {tools_str}):")
        else:
            sections.append(f"\n{display_name}:")

        for acct in acct_list:
            alias = acct.get("alias", "unknown")
            identity = acct.get("identity", {})
            detail_parts = [f"{k}: {v}" for k, v in identity.items() if v]
            detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
            source_tag = " [local]" if acct.get("source") == "local" else ""
            sections.append(f"  - {provider}/{alias}{detail}{source_tag}")

    if len(sections) <= 1:
        return ""

    return "\n".join(sections)


def build_prompt_spec_from_node_context(
    ctx: Any,
    *,
    focus_prompt: str | None = None,
    narrative: str | None = None,
    memory_prompt: str | None = None,
) -> NodePromptSpec:
    """Convert a NodeContext-like object into structured prompt inputs."""
    resolved_memory_prompt = memory_prompt
    if resolved_memory_prompt is None:
        resolved_memory_prompt = getattr(ctx, "memory_prompt", "") or ""
        dynamic_memory_provider = getattr(ctx, "dynamic_memory_provider", None)
        if dynamic_memory_provider is not None:
            try:
                resolved_memory_prompt = dynamic_memory_provider() or ""
            except Exception:
                resolved_memory_prompt = getattr(ctx, "memory_prompt", "") or ""
    return NodePromptSpec(
        identity_prompt=ctx.identity_prompt or "",
        focus_prompt=focus_prompt
        if focus_prompt is not None
        else (ctx.node_spec.system_prompt or ""),
        narrative=narrative if narrative is not None else (ctx.narrative or ""),
        accounts_prompt=ctx.accounts_prompt or "",
        skills_catalog_prompt=ctx.skills_catalog_prompt or "",
        protocols_prompt=ctx.protocols_prompt or "",
        memory_prompt=resolved_memory_prompt,
        node_type=ctx.node_spec.node_type,
        output_keys=tuple(ctx.node_spec.output_keys or ()),
    )


def build_system_prompt(spec: NodePromptSpec) -> str:
    """Compose one canonical system prompt for a node."""
    parts: list[str] = []

    if spec.identity_prompt:
        parts.append(spec.identity_prompt)

    if spec.accounts_prompt:
        parts.append(f"\n{spec.accounts_prompt}")

    if spec.skills_catalog_prompt:
        parts.append(f"\n{spec.skills_catalog_prompt}")

    if spec.protocols_prompt:
        parts.append(f"\n{spec.protocols_prompt}")

    if spec.memory_prompt:
        parts.append(
            "\nRelevant recalled memories may appear below. Treat them as "
            "point-in-time guidance and verify stale details against current context."
        )
        parts.append(f"\n{spec.memory_prompt}")

    if spec.narrative:
        parts.append(f"\n--- Context (what has happened so far) ---\n{spec.narrative}")

    if not False and spec.node_type == "event_loop" and spec.output_keys:
        parts.append(f"\n{EXECUTION_SCOPE_PREAMBLE}")



    if spec.focus_prompt:
        parts.append(f"\n--- Current Focus ---\n{spec.focus_prompt}")

    return stamp_prompt_datetime("\n".join(parts) if parts else "")


def build_system_prompt_for_node_context(
    ctx: Any,
    *,
    focus_prompt: str | None = None,
    narrative: str | None = None,
    memory_prompt: str | None = None,
) -> str:
    """Build a canonical system prompt from a NodeContext-like object."""
    spec = build_prompt_spec_from_node_context(
        ctx,
        focus_prompt=focus_prompt,
        narrative=narrative,
        memory_prompt=memory_prompt,
    )
    return build_system_prompt(spec)


def build_narrative(
    buffer: DataBuffer,
    execution_path: list[str],
    graph: GraphSpec,
) -> str:
    """Build a deterministic Layer 2 narrative from graph state."""
    parts: list[str] = []

    if execution_path:
        phase_descriptions: list[str] = []
        for node_id in execution_path:
            node_spec = graph.get_node(node_id)
            if node_spec:
                phase_descriptions.append(f"- {node_spec.name}: {node_spec.description}")
            else:
                phase_descriptions.append(f"- {node_id}")
        parts.append("Phases completed:\n" + "\n".join(phase_descriptions))

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


def build_transition_message(spec: TransitionSpec) -> str:
    """Build a pure transition marker message."""
    sections: list[str] = [
        f"--- PHASE TRANSITION: {spec.previous_name} -> {spec.next_name} ---",
        f"\nCompleted: {spec.previous_name}",
        f"  {spec.previous_description}",
    ]

    if spec.buffer_items:
        lines = [f"  {key}: {value}" for key, value in spec.buffer_items.items()]
        sections.append("\nOutputs available:\n" + "\n".join(lines))

    if spec.data_files:
        sections.append(
            "\nData files (use load_data to access):\n"
            + "\n".join(f"  {entry}" for entry in spec.data_files)
        )

    if spec.cumulative_tool_names:
        sections.append("\nAvailable tools: " + ", ".join(sorted(spec.cumulative_tool_names)))

    sections.append(f"\nNow entering: {spec.next_name}")
    sections.append(f"  {spec.next_description}")
    if spec.next_output_keys:
        sections.append(
            f"\nYour ONLY job in this phase: complete the task above and call "
            f"set_output() for {list(spec.next_output_keys)}. Do NOT do work that "
            f"belongs to later phases."
        )

    sections.append(
        "\nBefore proceeding, briefly reflect: what went well in the "
        "previous phase? Are there any gaps or surprises worth noting?"
    )
    sections.append("\n--- END TRANSITION ---")
    return "\n".join(sections)


__all__ = [
    "EXECUTION_SCOPE_PREAMBLE",
    "NodePromptSpec",
    "TransitionSpec",
    "build_accounts_prompt",
    "build_narrative",
    "build_prompt_spec_from_node_context",
    "build_system_prompt",
    "build_system_prompt_for_node_context",
    "build_transition_message",
    "stamp_prompt_datetime",
]
