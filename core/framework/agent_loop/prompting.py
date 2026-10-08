"""Prompt composition for agent loops.

Builds canonical system prompts from AgentContext fields.
Extracted from the former orchestrator/prompting module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from framework.agent_loop.internals.synthetic_tools import build_structured_output_instruction


@dataclass(frozen=True)
class PromptSpec:
    identity_prompt: str = ""
    focus_prompt: str = ""
    narrative: str = ""
    accounts_prompt: str = ""
    skills_catalog_prompt: str = ""
    protocols_prompt: str = ""
    memory_prompt: str = ""
    binding_prompt: str = ""
    agent_type: str = "event_loop"
    output_keys: tuple[str, ...] = ()
    report_schema_instruction: str = ""


def stamp_prompt_datetime(prompt: str) -> str:
    """Day-resolution date stamp (no callers in this module — kept in sync
    with the live twin in orchestrator/prompting.py; see its docstring for
    why minute resolution is a prompt-cache buster)."""
    local = datetime.now().astimezone()
    stamp = f"Current date: {local.strftime('%Y-%m-%d %Z (UTC%z)')}"
    return f"{prompt}\n\n{stamp}" if prompt else stamp


def build_binding_prompt(binding: Any) -> str:
    """Render a ColonyBinding into a static system-prompt block.

    Lives in the cache-stable prefix: the binding is constant for the
    life of a session, so emitting it once and letting the prompt cache
    hold it across turns costs nothing. Returns "" when no binding is
    bound (independent-mode queen pre-fork) so the section disappears
    rather than appearing empty.
    """
    if binding is None:
        return ""
    tracker_db = getattr(binding, "tracker_db", None)
    if not tracker_db:
        return ""
    return (
        f"Tracker DB: {tracker_db}\n"
        "(Your tracker_* tools target this automatically — never pass the path "
        "to them. Use it directly only when you script a batch operation on the "
        "DB, e.g. bulk-loading rows from other files.)"
    )


def build_prompt_spec(
    ctx: Any,
    *,
    focus_prompt: str | None = None,
    narrative: str | None = None,
    memory_prompt: str | None = None,
) -> PromptSpec:
    from framework.skills.tool_gating import augment_catalog_for_tools

    resolved_memory = memory_prompt
    if resolved_memory is None:
        resolved_memory = getattr(ctx, "memory_prompt", "") or ""
        dynamic = getattr(ctx, "dynamic_memory_provider", None)
        if dynamic is not None:
            try:
                resolved_memory = dynamic() or ""
            except Exception:
                resolved_memory = getattr(ctx, "memory_prompt", "") or ""

    # Tool-gated pre-activation: inject full body of default skills whose
    # trigger tools are present in this agent's tool list (e.g. browser_*
    # pulls in hive.browser-automation). Keeps non-browser agents lean.
    # Tiered workers gate on the CURRENT eager set (always-enabled ∪ loaded
    # via search_tools), not the full spawn pool — a worker whose browser
    # tools are all deferred must not carry the browser foundation guide;
    # promoting one pulls the guide in on the next prompt rebuild.
    _tier = getattr(ctx, "tool_tier_state", None)
    if _tier is not None:
        tool_names = [getattr(t, "name", "") for t in _tier.get_current_tools()]
    else:
        tool_names = [getattr(t, "name", "") for t in (getattr(ctx, "available_tools", None) or [])]
    raw_catalog = ctx.skills_catalog_prompt or ""
    dynamic_catalog = getattr(ctx, "dynamic_skills_catalog_provider", None)
    if dynamic_catalog is not None:
        try:
            raw_catalog = dynamic_catalog() or ""
        except Exception:
            raw_catalog = ctx.skills_catalog_prompt or ""
    skills_catalog_prompt = augment_catalog_for_tools(raw_catalog, tool_names)

    binding_prompt = ""
    binding_provider = getattr(ctx, "colony_binding_provider", None)
    if binding_provider is not None:
        try:
            binding_prompt = build_binding_prompt(binding_provider())
        except Exception:
            binding_prompt = ""

    return PromptSpec(
        identity_prompt=ctx.identity_prompt or "",
        focus_prompt=focus_prompt if focus_prompt is not None else (ctx.agent_spec.system_prompt or ""),
        narrative=narrative if narrative is not None else (ctx.narrative or ""),
        accounts_prompt=ctx.accounts_prompt or "",
        skills_catalog_prompt=skills_catalog_prompt,
        protocols_prompt=ctx.protocols_prompt or "",
        memory_prompt=resolved_memory,
        binding_prompt=binding_prompt,
        agent_type=ctx.agent_spec.agent_type,
        output_keys=tuple(ctx.agent_spec.output_keys or ()),
        report_schema_instruction=build_structured_output_instruction(getattr(ctx.agent_spec, "report_schema", None)),
    )


def build_system_prompt_static(spec: PromptSpec) -> str:
    """Build the cache-stable static prefix of the system prompt.

    Everything that doesn't change turn-to-turn lives here: identity,
    accounts, skills catalog, protocols, memory, and the agent's focus
    prompt. The narrative is intentionally excluded — it's rebuilt every
    iteration from buffer state + execution path and mutates the cache
    key when concatenated. See ``build_system_prompt_dynamic_suffix``.
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
        parts.append(f"\n{spec.memory_prompt}")
    if spec.focus_prompt:
        parts.append(f"\n{spec.focus_prompt}")
    if spec.report_schema_instruction:
        parts.append(f"\n{spec.report_schema_instruction}")
    return "\n".join(parts)


def build_system_prompt_dynamic_suffix(spec: PromptSpec) -> str:
    """Build the per-turn dynamic tail.

    Holds the pieces of the system prompt that mutate across iterations:
    today only the narrative (execution path + buffer state). The
    ``_build_system_message`` wrapper in ``framework.llm.litellm`` emits
    this as a SEPARATE Anthropic ``system`` content block, without the
    cache_control marker, so the static prefix stays cache-warm even as
    the tail churns. Returns ``""`` when there's nothing dynamic to emit.

    Deliberately NO wall-clock timestamp here: this block precedes the
    entire message history in the request, so a minute-resolution stamp
    would invalidate the history prefix cache every time the minute
    ticked. Temporal anchoring instead rides the conversation itself —
    the loop stamps ``[YYYY-MM-DD HH:MM TZ]`` onto the initial message
    and every injected event (see ``drain_injection_queue``), which are
    byte-stable once appended.
    """
    parts: list[str] = []
    if spec.narrative:
        parts.append(spec.narrative)
    return "\n".join(parts)


def build_system_prompt(spec: PromptSpec) -> str:
    """Concatenate static prefix + dynamic suffix.

    Back-compat shim for callers that haven't been migrated to the
    static/dynamic split yet. New callers should call
    ``build_system_prompt_static`` and ``build_system_prompt_dynamic_suffix``
    separately and pass the suffix to
    ``NodeConversation.update_system_prompt(static, dynamic_suffix=suffix)``
    so the LiteLLM wrapper can emit them as two cache-aware blocks.
    """
    static = build_system_prompt_static(spec)
    suffix = build_system_prompt_dynamic_suffix(spec)
    if not suffix:
        return static
    if not static:
        return suffix
    return f"{static}\n\n{suffix}"


def build_system_prompt_for_context(
    ctx: Any,
    *,
    focus_prompt: str | None = None,
    narrative: str | None = None,
    memory_prompt: str | None = None,
) -> str:
    """Back-compat single-string builder (static + suffix concatenated).

    New callers should prefer ``build_system_prompt_parts_for_context``
    so the cache breakpoint between static and dynamic survives.
    """
    spec = build_prompt_spec(ctx, focus_prompt=focus_prompt, narrative=narrative, memory_prompt=memory_prompt)
    return build_system_prompt(spec)


def build_system_prompt_parts_for_context(
    ctx: Any,
    *,
    focus_prompt: str | None = None,
    narrative: str | None = None,
    memory_prompt: str | None = None,
) -> tuple[str, str]:
    """Return ``(static_prefix, dynamic_suffix)`` for the given context.

    The static prefix is cache-stable across turns; the dynamic suffix
    holds the narrative + current timestamp. Pass the pair to
    ``NodeConversation.update_system_prompt(static, dynamic_suffix=suffix)``.
    """
    spec = build_prompt_spec(ctx, focus_prompt=focus_prompt, narrative=narrative, memory_prompt=memory_prompt)
    return build_system_prompt_static(spec), build_system_prompt_dynamic_suffix(spec)
