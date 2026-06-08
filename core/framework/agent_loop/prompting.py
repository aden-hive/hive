"""Prompt composition for agent loops.

Builds canonical system prompts from AgentContext fields.
Extracted from the former orchestrator/prompting module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class PromptSpec:
    identity_prompt: str = ""
    focus_prompt: str = ""
    narrative: str = ""
    accounts_prompt: str = ""
    skills_catalog_prompt: str = ""
    protocols_prompt: str = ""
    memory_prompt: str = ""
    agent_type: str = "event_loop"
    output_keys: tuple[str, ...] = ()


def stamp_prompt_datetime(prompt: str) -> str:
    local = datetime.now().astimezone()
    stamp = f"Current date and time: {local.strftime('%Y-%m-%d %H:%M %Z (UTC%z)')}"
    return f"{prompt}\n\n{stamp}" if prompt else stamp


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
    tool_names = [getattr(t, "name", "") for t in (getattr(ctx, "available_tools", None) or [])]
    raw_catalog = ctx.skills_catalog_prompt or ""
    dynamic_catalog = getattr(ctx, "dynamic_skills_catalog_provider", None)
    if dynamic_catalog is not None:
        try:
            raw_catalog = dynamic_catalog() or ""
        except Exception:
            raw_catalog = ctx.skills_catalog_prompt or ""
    skills_catalog_prompt = augment_catalog_for_tools(raw_catalog, tool_names)

    return PromptSpec(
        identity_prompt=ctx.identity_prompt or "",
        focus_prompt=focus_prompt if focus_prompt is not None else (ctx.agent_spec.system_prompt or ""),
        narrative=narrative if narrative is not None else (ctx.narrative or ""),
        accounts_prompt=ctx.accounts_prompt or "",
        skills_catalog_prompt=skills_catalog_prompt,
        protocols_prompt=ctx.protocols_prompt or "",
        memory_prompt=resolved_memory,
        agent_type=ctx.agent_spec.agent_type,
        output_keys=tuple(ctx.agent_spec.output_keys or ()),
    )


def build_system_prompt(spec: PromptSpec) -> str:
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
        parts.append(f"\n{spec.memory_prompt}")
    if spec.focus_prompt:
        parts.append(f"\n{spec.focus_prompt}")
    if spec.narrative:
        parts.append(f"\n{spec.narrative}")
    return "\n".join(parts)


def build_system_prompt_for_context(
    ctx: Any,
    *,
    focus_prompt: str | None = None,
    narrative: str | None = None,
    memory_prompt: str | None = None,
) -> str:
    spec = build_prompt_spec(ctx, focus_prompt=focus_prompt, narrative=narrative, memory_prompt=memory_prompt)
    return build_system_prompt(spec)
