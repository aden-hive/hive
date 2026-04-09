"""Stub — shared state removed in colony refactor."""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)


class IsolationLevel(StrEnum):
    ISOLATED = "isolated"
    SHARED = "shared"
    SYNCHRONIZED = "synchronized"


class StateScope(StrEnum):
    EXECUTION = "execution"
    STREAM = "stream"
    GLOBAL = "global"


class SharedBufferManager:
    def __init__(self):
        self._global_state: dict[str, Any] = {}
        self._stream_states: dict[str, dict[str, Any]] = {}
        self._execution_states: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def create_buffer(
        self,
        execution_id: str,
        stream_id: str = "",
        isolation: IsolationLevel = IsolationLevel.ISOLATED,
    ):
        execution_key = f"{stream_id}:{execution_id}"
        if execution_key not in self._execution_states:
            self._execution_states[execution_key] = {}
        return self._execution_states[execution_key]

    def get_stream_state(self, stream_id: str) -> dict[str, Any]:
        return self._stream_states.setdefault(stream_id, {})

    def get_global_state(self) -> dict[str, Any]:
        return self._global_state
