"""Host layer -- how agents are triggered and hosted."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.host.colony_runtime import ColonyConfig, ColonyRuntime, StreamEventBus, TriggerSpec
    from framework.host.event_bus import AgentEvent, EventBus, EventType
    from framework.host.worker import Worker, WorkerInfo, WorkerResult, WorkerStatus

__all__ = [
    "ColonyConfig",
    "ColonyRuntime",
    "StreamEventBus",
    "TriggerSpec",
    "AgentEvent",
    "EventBus",
    "EventType",
    "Worker",
    "WorkerInfo",
    "WorkerResult",
    "WorkerStatus",
]

_EXPORTS = {
    "ColonyConfig": ("framework.host.colony_runtime", "ColonyConfig"),
    "ColonyRuntime": ("framework.host.colony_runtime", "ColonyRuntime"),
    "StreamEventBus": ("framework.host.colony_runtime", "StreamEventBus"),
    "TriggerSpec": ("framework.host.colony_runtime", "TriggerSpec"),
    "AgentEvent": ("framework.host.event_bus", "AgentEvent"),
    "EventBus": ("framework.host.event_bus", "EventBus"),
    "EventType": ("framework.host.event_bus", "EventType"),
    "Worker": ("framework.host.worker", "Worker"),
    "WorkerInfo": ("framework.host.worker", "WorkerInfo"),
    "WorkerResult": ("framework.host.worker", "WorkerResult"),
    "WorkerStatus": ("framework.host.worker", "WorkerStatus"),
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
