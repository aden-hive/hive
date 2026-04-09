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
    resolved_memory = memory_prompt
    if resolved_memory is None:
        resolved_memory = getattr(ctx, "memory_prompt", "") or ""
        dynamic = getattr(ctx, "dynamic_memory_provider", None)
        if dynamic is not None:
            try:
                resolved_memory = dynamic() or ""
            except Exception:
                resolved_memory = getattr(ctx, "memory_prompt", "") or ""
    return PromptSpec(
        identity_prompt=ctx.identity_prompt or "",
        focus_prompt=focus_prompt
        if focus_prompt is not None
        else (ctx.agent_spec.system_prompt or ""),
        narrative=narrative if narrative is not None else (ctx.narrative or ""),
        accounts_prompt=ctx.accounts_prompt or "",
        skills_catalog_prompt=ctx.skills_catalog_prompt or "",
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
    spec = build_prompt_spec(
        ctx, focus_prompt=focus_prompt, narrative=narrative, memory_prompt=memory_prompt
    )
    return build_system_prompt(spec)
