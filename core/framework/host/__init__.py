"""Host layer -- how agents are triggered and hosted.

Imported when first used, so ``framework.host.event_bus`` can be used without loading the
colony runtime.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from framework.host.colony_runtime import ColonyConfig, ColonyRuntime, StreamEventBus, TriggerSpec
    from framework.host.event_bus import AgentEvent, EventBus, EventType
    from framework.host.worker import Worker, WorkerInfo, WorkerResult, WorkerStatus

__all__ = [
    "AgentEvent",
    "ColonyConfig",
    "ColonyRuntime",
    "EventBus",
    "EventType",
    "StreamEventBus",
    "TriggerSpec",
    "Worker",
    "WorkerInfo",
    "WorkerResult",
    "WorkerStatus",
]

_EXPORTS = {
    "ColonyConfig": "framework.host.colony_runtime",
    "ColonyRuntime": "framework.host.colony_runtime",
    "StreamEventBus": "framework.host.colony_runtime",
    "TriggerSpec": "framework.host.colony_runtime",
    "AgentEvent": "framework.host.event_bus",
    "EventBus": "framework.host.event_bus",
    "EventType": "framework.host.event_bus",
    "Worker": "framework.host.worker",
    "WorkerInfo": "framework.host.worker",
    "WorkerResult": "framework.host.worker",
    "WorkerStatus": "framework.host.worker",
}


def __getattr__(name: str) -> Any:
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module), name)
    globals()[name] = value  # resolved once
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})
