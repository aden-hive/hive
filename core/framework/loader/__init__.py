"""Loader layer -- agent loading from disk (JSON config, MCP, credentials)."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.loader.agent_loader import AgentLoader
    from framework.loader.tool_registry import ToolRegistry

__all__ = ["AgentLoader", "ToolRegistry"]

_EXPORTS = {
    "AgentLoader": ("framework.loader.agent_loader", "AgentLoader"),
    "ToolRegistry": ("framework.loader.tool_registry", "ToolRegistry"),
}


def __getattr__(name: str) -> Any:
    try:
        module_name, attr_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
