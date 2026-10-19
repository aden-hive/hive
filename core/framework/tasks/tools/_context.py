"""Context resolution for task-tool executors.

Tool executors run synchronously inside ``ToolRegistry.get_executor()``;
they need the calling agent's id and session_id to know which list to
write to. We pull both from contextvars set by the runner /
ColonyRuntime / orchestrator before each agent's iteration.
"""

from __future__ import annotations

from typing import Any

from framework.loader.tool_registry import _execution_context


def current_context() -> dict[str, Any]:
    return dict(_execution_context.get() or {})


def current_agent_id() -> str | None:
    return current_context().get("agent_id")


def current_session_id() -> str | None:
    return current_context().get("session_id")


def current_usage_agent_id() -> str | None:
    """Identity stamped on Hive-LLM-proxy calls for cloud usage attribution.

    Distinct from ``agent_id`` (which is held to the literal "queen" /
    worker_name slug). This carries the cloud ``agents.id`` shape — queen
    profile slug for queen calls, ``worker_{colony_id}`` for worker calls.
    """
    return current_context().get("usage_agent_id")
