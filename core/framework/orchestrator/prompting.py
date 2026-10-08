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
    binding_prompt: str = ""
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
    """Append the current DATE (day resolution) to a prompt.

    Deliberately not minute-resolution: this lands in the system prompt,
    which sits before the entire message history in the request. A
    minute-level stamp made byte-identical prompts hash differently every
    minute — defeating provider prompt-cache reuse across sessions and
    minting near-duplicate datalog blobs (measured in prod, 2026-07: five
    ~70 KB worker system blobs differing only by this stamp). Fine-grained
    temporal anchoring rides the conversation instead, as ``[YYYY-MM-DD
    HH:MM TZ]`` prefixes on injected messages (see agent_loop /
    cursor_persistence) — byte-stable once appended, so cache-safe.
    """
    local = datetime.now().astimezone()
    stamp = f"Current date: {local.strftime('%Y-%m-%d %Z (UTC%z)')}"
    return f"{prompt}\n\n{stamp}" if prompt else stamp


def build_binding_prompt(binding: Any) -> str:
    """Render a ColonyBinding into a static system-prompt block.

    Lives in the cache-stable prefix: the binding is constant for the
    life of a graph run, so emitting it once and letting the prompt
    cache hold it across iterations costs nothing. Returns "" when no
    binding is bound so the section disappears rather than rendering
    an empty heading.
    """
    if binding is None:
        return ""
    tracker_db = getattr(binding, "tracker_db", None)
    if not tracker_db:
        return ""
    return (
        f"Tracker DB: {tracker_db}\n"
        "(Your tracker_* tools target this automatically. "
        "Use it directly only when you script a batch operation on the "
        "DB, e.g. bulk-loading rows from other files.)"
    )


def build_accounts_prompt(
    accounts: list[dict[str, Any]],
    tool_provider_map: dict[str, str] | None = None,
    node_tool_names: list[str] | None = None,
) -> str:
    """Build a prompt section describing connected accounts.

    Format: a ``# Connected integrations`` heading, then one block per
    provider. Each provider header names the tools that accept an
    ``account=`` argument; each account is listed alias-first with the
    alias wrapped in double quotes so the model treats it as a literal
    identifier (not prose). Single-account providers collapse to a
    two-line block. Pure data — behavioral guidance lives in the node's
    planning_knowledge section, not here.
    """
    if not accounts:
        return ""

    def _format_identity(acct: dict[str, Any]) -> str:
        identity = acct.get("identity", {})
        parts = [str(v) for v in identity.values() if v]
        return f" ({', '.join(parts)})" if parts else ""

    def _format_account_line(acct: dict[str, Any]) -> str:
        alias = acct.get("alias", "unknown")
        source_tag = " [local]" if acct.get("source") == "local" else ""
        return f'- "{alias}"{_format_identity(acct)}{source_tag}'

    provider_accounts: dict[str, list[dict[str, Any]]] = {}
    for acct in accounts:
        provider_accounts.setdefault(acct.get("provider", "unknown"), []).append(acct)

    # Appended (only when any rendered provider has >1 account) so the model
    # knows to disambiguate instead of silently picking one.
    multi_account_note = "\nWhen a provider below has multiple accounts, ask the user which one to use and list the options — do not guess."

    # Simple path: no tool map — just group accounts by provider.
    if tool_provider_map is None:
        sections: list[str] = ["# Connected integrations"]
        for provider, acct_list in provider_accounts.items():
            sections.append(f"\n{provider}")
            for acct in acct_list:
                sections.append(_format_account_line(acct))
        if any(len(acct_list) > 1 for acct_list in provider_accounts.values()):
            sections.append(multi_account_note)
        return "\n".join(sections)

    provider_tools: dict[str, list[str]] = {}
    for tool_name, provider in tool_provider_map.items():
        provider_tools.setdefault(provider, []).append(tool_name)

    node_tool_set = set(node_tool_names) if node_tool_names else None

    sections = ["# Connected integrations"]
    has_multi_account = False

    for provider, acct_list in provider_accounts.items():
        tools_for_provider = sorted(provider_tools.get(provider, []))
        if node_tool_set is not None:
            tools_for_provider = [t for t in tools_for_provider if t in node_tool_set]
            if not tools_for_provider:
                continue

        all_local = all(acct.get("source") == "local" for acct in acct_list)
        tools_str = ", ".join(tools_for_provider)

        if tools_for_provider and not all_local:
            header_suffix = f' (use account="<alias>" with: {tools_str})'
        elif tools_for_provider and all_local:
            header_suffix = f" (tools: {tools_str})"
        else:
            header_suffix = ""

        sections.append(f"\n{provider}{header_suffix}")
        for acct in acct_list:
            sections.append(_format_account_line(acct))
        if len(acct_list) > 1:
            has_multi_account = True

    if len(sections) <= 1:
        return ""

    if has_multi_account:
        sections.append(multi_account_note)

    return "\n".join(sections)


def build_credentials_summary(accounts: list[dict[str, Any]]) -> str:
    """Build a COMPACT connected-credentials summary for the system prompt.

    Replaces the full per-account ``build_accounts_prompt`` block in the
    queen's always-on prompt: by default the queen sees only provider names +
    counts (enough to know what exists), not every alias. Full detail is
    re-injected per-session only for credentials the queen explicitly attaches
    via the ``credentials`` tool. Returns "" when nothing is connected so the
    section disappears.
    """
    if not accounts:
        return (
            "# Credentials\n"
            "No credentials are connected yet. Use the `credentials` tool "
            "(action=collect) to add one, or action=browse to see what's available."
        )

    counts: dict[str, int] = {}
    for acct in accounts:
        provider = str(acct.get("provider") or acct.get("credential_id") or "unknown")
        counts[provider] = counts.get(provider, 0) + 1

    summary = ", ".join(f"{provider} ({n})" if n > 1 else provider for provider, n in sorted(counts.items()))
    return (
        "# Credentials\n"
        f"Connected: {summary}.\n"
        "Use the `credentials` tool (action=browse) for details or to collect "
        "new ones, and action=attach to pin the ones you'll reuse this session."
    )


def build_prompt_spec_from_node_context(
    ctx: Any,
    *,
    focus_prompt: str | None = None,
    narrative: str | None = None,
    memory_prompt: str | None = None,
) -> NodePromptSpec:
    """Convert a NodeContext-like object into structured prompt inputs."""
    from framework.skills.tool_gating import augment_catalog_for_tools

    resolved_memory_prompt = memory_prompt
    if resolved_memory_prompt is None:
        resolved_memory_prompt = getattr(ctx, "memory_prompt", "") or ""
        dynamic_memory_provider = getattr(ctx, "dynamic_memory_provider", None)
        if dynamic_memory_provider is not None:
            try:
                resolved_memory_prompt = dynamic_memory_provider() or ""
            except Exception:
                resolved_memory_prompt = getattr(ctx, "memory_prompt", "") or ""

    # Tool-gated pre-activation: inject full body of default skills whose
    # trigger tools are present in this node's tool list (e.g. browser_*
    # pulls in hive.browser-automation).
    tool_names = [getattr(t, "name", "") for t in (getattr(ctx, "available_tools", None) or [])]
    skills_catalog_prompt = augment_catalog_for_tools(ctx.skills_catalog_prompt or "", tool_names)

    binding_prompt = ""
    binding_provider = getattr(ctx, "colony_binding_provider", None)
    if binding_provider is not None:
        try:
            binding_prompt = build_binding_prompt(binding_provider())
        except Exception:
            binding_prompt = ""

    return NodePromptSpec(
        identity_prompt=ctx.identity_prompt or "",
        focus_prompt=focus_prompt if focus_prompt is not None else (ctx.node_spec.system_prompt or ""),
        narrative=narrative if narrative is not None else (ctx.narrative or ""),
        accounts_prompt=ctx.accounts_prompt or "",
        skills_catalog_prompt=skills_catalog_prompt,
        protocols_prompt=ctx.protocols_prompt or "",
        memory_prompt=resolved_memory_prompt,
        binding_prompt=binding_prompt,
        node_type=ctx.node_spec.node_type,
        output_keys=tuple(ctx.node_spec.output_keys or ()),
    )


def build_system_prompt_static(spec: NodePromptSpec) -> str:
    """Cache-stable prefix of the node system prompt.

    Holds the truly static layers — identity, connected accounts, skills
    catalog, protocols, recalled memory. These don't change during a
    single phase, so the provider's prompt cache keeps them warm across
    every iteration.

    The narrative + EXECUTION_SCOPE_PREAMBLE + focus block all live in
    the dynamic suffix, even though EXECUTION_SCOPE_PREAMBLE and focus
    are *technically* stable within a phase — keeping them adjacent to
    the narrative preserves the original layout (narrative → preamble →
    focus → timestamp) that downstream prompts and tests expect. The
    cache cost is small (focus + preamble are typically <2KB) and worth
    paying to avoid silently shuffling sections around the model's
    attention.
    """
    parts: list[str] = []

    if spec.identity_prompt:
        parts.append(spec.identity_prompt)

    if spec.binding_prompt:
        parts.append(f"\n{spec.binding_prompt}")

    if spec.accounts_prompt:
        parts.append(f"\n{spec.accounts_prompt}")

    if spec.skills_catalog_prompt:
        parts.append(f"\n{spec.skills_catalog_prompt}")

    if spec.protocols_prompt:
        parts.append(f"\n{spec.protocols_prompt}")

    if spec.memory_prompt:
        parts.append(
            "\nRelevant recalled memories may appear below. Treat them as point-in-time guidance and verify stale details against current context."
        )
        parts.append(f"\n{spec.memory_prompt}")

    return "\n".join(parts) if parts else ""


def build_system_prompt_dynamic_suffix(spec: NodePromptSpec) -> str:
    """Per-turn dynamic tail for the node system prompt.

    Holds the narrative (execution path + buffer state), the conditional
    ``EXECUTION_SCOPE_PREAMBLE`` block, the focus prompt, and the
    wall-clock timestamp — in that order, matching the legacy
    single-string builder so the model sees identical content layout.

    Returns ``""`` only when every dynamic section is empty (rare —
    even a no-op iteration carries a fresh timestamp).
    """
    parts: list[str] = []

    if spec.narrative:
        parts.append(f"--- Context (what has happened so far) ---\n{spec.narrative}")

    if spec.node_type == "event_loop" and spec.output_keys:
        parts.append(f"{EXECUTION_SCOPE_PREAMBLE}")

    if spec.focus_prompt:
        parts.append(f"--- Current Focus ---\n{spec.focus_prompt}")

    body = "\n\n".join(parts)
    return stamp_prompt_datetime(body)


def build_system_prompt(spec: NodePromptSpec) -> str:
    """Concatenate static prefix + dynamic suffix.

    Back-compat shim for callers that haven't been migrated to the
    static/dynamic split. New callers should call
    ``build_system_prompt_static`` and
    ``build_system_prompt_dynamic_suffix`` separately and pass the
    suffix to ``NodeConversation.update_system_prompt(static,
    dynamic_suffix=suffix)`` so the LiteLLM wrapper can emit two
    cache-aware blocks.
    """
    static = build_system_prompt_static(spec)
    suffix = build_system_prompt_dynamic_suffix(spec)
    if not suffix:
        return static
    if not static:
        return suffix
    return f"{static}\n\n{suffix}"


def build_system_prompt_for_node_context(
    ctx: Any,
    *,
    focus_prompt: str | None = None,
    narrative: str | None = None,
    memory_prompt: str | None = None,
) -> str:
    """Build the combined system prompt (back-compat single-string)."""
    spec = build_prompt_spec_from_node_context(
        ctx,
        focus_prompt=focus_prompt,
        narrative=narrative,
        memory_prompt=memory_prompt,
    )
    return build_system_prompt(spec)


def build_system_prompt_parts_for_node_context(
    ctx: Any,
    *,
    focus_prompt: str | None = None,
    narrative: str | None = None,
    memory_prompt: str | None = None,
) -> tuple[str, str]:
    """Return ``(static_prefix, dynamic_suffix)`` for a NodeContext.

    Pass to ``NodeConversation.update_system_prompt(static,
    dynamic_suffix=suffix)`` so the LLM wrapper sends two cache-aware
    blocks.
    """
    spec = build_prompt_spec_from_node_context(
        ctx,
        focus_prompt=focus_prompt,
        narrative=narrative,
        memory_prompt=memory_prompt,
    )
    return build_system_prompt_static(spec), build_system_prompt_dynamic_suffix(spec)


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
        sections.append('\nData files (use terminal_exec("cat ...") to access):\n' + "\n".join(f"  {entry}" for entry in spec.data_files))

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

    sections.append("\nBefore proceeding, briefly reflect: what went well in the previous phase? Are there any gaps or surprises worth noting?")
    sections.append("\n--- END TRANSITION ---")
    return "\n".join(sections)


__all__ = [
    "EXECUTION_SCOPE_PREAMBLE",
    "NodePromptSpec",
    "TransitionSpec",
    "build_accounts_prompt",
    "build_binding_prompt",
    "build_credentials_summary",
    "build_narrative",
    "build_prompt_spec_from_node_context",
    "build_system_prompt",
    "build_system_prompt_dynamic_suffix",
    "build_system_prompt_for_node_context",
    "build_system_prompt_parts_for_node_context",
    "build_system_prompt_static",
    "build_transition_message",
    "stamp_prompt_datetime",
]
