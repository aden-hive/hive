import asyncio
import base64
import enum
import inspect
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Literal,
    Mapping,
    Protocol,
    TypedDict,
    cast,
)

import cloudpickle  # type: ignore[import]
import opentelemetry.context
from opentelemetry import propagate, trace
from typing_extensions import Self

from .annotations import Logged
from .instrumentation import CACHE_SIZE, message_getter, message_setter

if TYPE_CHECKING:
    from .docket import Docket, RedisMessageID

logger: logging.Logger = logging.getLogger(__name__)

TaskFunction = Callable[..., Awaitable[Any]]
Message = dict[bytes, bytes]


class _schedule_task(Protocol):
    async def __call__(
        self, keys: list[str], args: list[str | float | bytes]
    ) -> str: ...  # pragma: no cover


_signature_cache: dict[Callable[..., Any], inspect.Signature] = {}


def get_signature(function: Callable[..., Any]) -> inspect.Signature:
    if function in _signature_cache:
        CACHE_SIZE.set(len(_signature_cache), {"cache": "signature"})
        return _signature_cache[function]

    signature_attr = getattr(function, "__signature__", None)
    if isinstance(signature_attr, inspect.Signature):
        _signature_cache[function] = signature_attr
        CACHE_SIZE.set(len(_signature_cache), {"cache": "signature"})
        return signature_attr

    signature = inspect.signature(function)
    _signature_cache[function] = signature
    CACHE_SIZE.set(len(_signature_cache), {"cache": "signature"})
    return signature


class ExecutionState(enum.Enum):
    """Lifecycle states for task execution."""

    SCHEDULED = "scheduled"
    """Task is scheduled and waiting in the queue for its execution time."""

    QUEUED = "queued"
    """Task has been moved to the stream and is ready to be claimed by a worker."""

    RUNNING = "running"
    """Task is currently being executed by a worker."""

    COMPLETED = "completed"
    """Task execution finished successfully."""

    FAILED = "failed"
    """Task execution failed."""

    CANCELLED = "cancelled"
    """Task was explicitly cancelled before completion."""


class ProgressEvent(TypedDict):
    type: Literal["progress"]
    key: str
    current: int | None
    total: int
    message: str | None
    updated_at: str | None


class StateEvent(TypedDict):
    type: Literal["state"]
    key: str
    state: ExecutionState
    when: str
    worker: str | None
    started_at: str | None
    completed_at: str | None
    error: str | None


class ExecutionProgress:
    """Manages user-reported progress for a task execution.

    Progress data is stored in Redis hash {docket}:progress:{key} and includes:
    - current: Current progress value (integer)
    - total: Total/target value (integer)
    - message: User-provided status message (string)
    - updated_at: Timestamp of last update (ISO 8601 string)

    This data is ephemeral and deleted when the task completes.
    """

    def __init__(self, docket: "Docket", key: str) -> None:
        """Initialize progress tracker for a specific task.

        Args:
            docket: The docket instance
            key: The task execution key
        """
        self.docket = docket
        self.key = key
        self._redis_key = docket.key(f"progress:{key}")
        self.current: int | None = None
        self.total: int = 1
        self.message: str | None = None
        self.updated_at: datetime | None = None

    @classmethod
    async def create(cls, docket: "Docket", key: str) -> Self:
        """Create and initialize progress tracker by reading from Redis.

        Args:
            docket: The docket instance
            key: The task execution key

        Returns:
            ExecutionProgress instance with attributes populated from Redis
        """
        instance = cls(docket, key)
        await instance.sync()
        return instance

    async def set_total(self, total: int) -> None:
        """Set the total/target value for progress tracking.

        Args:
            total: The total number of units to complete. Must be at least 1.
        """
        if total < 1:
            raise ValueError("Total must be at least 1")

        updated_at_dt = datetime.now(timezone.utc)
        updated_at = updated_at_dt.isoformat()
        async with self.docket.redis() as redis:
            await redis.hset(
                self._redis_key,
                mapping={
                    "total": str(total),
                    "updated_at": updated_at,
                },
            )
        # Update instance attributes
        self.total = total
        self.updated_at = updated_at_dt
        # Publish update event
        await self._publish({"total": total, "updated_at": updated_at})

    async def increment(self, amount: int = 1) -> None:
        """Atomically increment the current progress value.

        Args:
            amount: Amount to increment by. Must be at least 1.
        """
        if amount < 1:
            raise ValueError("Amount must be at least 1")

        updated_at_dt = datetime.now(timezone.utc)
        updated_at = updated_at_dt.isoformat()
        async with self.docket.redis() as redis:
            new_current = await redis.hincrby(self._redis_key, "current", amount)
            await redis.hset(
                self._redis_key,
                "updated_at",
                updated_at,
            )
        # Update instance attributes using Redis return value
        self.current = new_current
        self.updated_at = updated_at_dt
        # Publish update event with new current value
        await self._publish({"current": new_current, "updated_at": updated_at})

    async def set_message(self, message: str | None) -> None:
        """Update the progress status message.

        Args:
            message: Status message describing current progress
        """
        updated_at_dt = datetime.now(timezone.utc)
        updated_at = updated_at_dt.isoformat()
        async with self.docket.redis() as redis:
            await redis.hset(
                self._redis_key,
                mapping={
                    "message": message,
                    "updated_at": updated_at,
                },
            )
        # Update instance attributes
        self.message = message
        self.updated_at = updated_at_dt
        # Publish update event
        await self._publish({"message": message, "updated_at": updated_at})

    async def sync(self) -> None:
        """Synchronize instance attributes with current progress data from Redis.

        Updates self.current, self.total, self.message, and self.updated_at
        with values from Redis. Sets attributes to None if no data exists.
        """
        async with self.docket.redis() as redis:
            data = await redis.hgetall(self._redis_key)
            if data:
                self.current = int(data.get(b"current", b"0"))
                self.total = int(data.get(b"total", b"100"))
                self.message = data[b"message"].decode() if b"message" in data else None
                self.updated_at = (
                    datetime.fromisoformat(data[b"updated_at"].decode())
                    if b"updated_at" in data
                    else None
                )
            else:
                self.current = None
                self.total = 100
                self.message = None
                self.updated_at = None

    async def delete(self) -> None:
        """Delete the progress data from Redis.

        Called internally when task execution completes.
        """
        async with self.docket.redis() as redis:
            await redis.delete(self._redis_key)
        # Reset instance attributes
        self.current = None
        self.total = 100
        self.message = None
        self.updated_at = None

    async def _publish(self, data: dict[str, Any]) -> None:
        """Publish progress update to Redis pub/sub channel.

        Args:
            data: Progress data to publish (partial update)
        """
        channel = self.docket.key(f"progress:{self.key}")
        # Create ephemeral Redis client for publishing
        async with self.docket.redis() as redis:
            # Use instance attributes for current state
            payload: ProgressEvent = {
                "type": "progress",
                "key": self.key,
                "current": self.current if self.current is not None else 0,
                "total": self.total,
                "message": self.message,
                "updated_at": data.get("updated_at"),
            }

            # Publish JSON payload
            await redis.publish(channel, json.dumps(payload))

    async def subscribe(self) -> AsyncGenerator[ProgressEvent, None]:
        """Subscribe to progress updates for this task.

        Yields:
            Dict containing progress update events with fields:
            - type: "progress"
            - key: task key
            - current: current progress value
            - total: total/target value (or None)
            - message: status message (or None)
            - updated_at: ISO 8601 timestamp
        """
        channel = self.docket.key(f"progress:{self.key}")
        async with self.docket.redis() as redis:
            async with redis.pubsub() as pubsub:
                await pubsub.subscribe(channel)
                try:
                    async for message in pubsub.listen():  # pragma: no cover
                        if message["type"] == "message":
                            yield json.loads(message["data"])
                finally:
                    # Explicitly unsubscribe to ensure clean shutdown
                    await pubsub.unsubscribe(channel)


class Execution:
    """Represents a task execution with state management and progress tracking.

    Combines task invocation metadata (function, args, when, etc.) with
    Redis-backed lifecycle state tracking and user-reported progress.
    """

    def __init__(
        self,
        docket: "Docket",
        function: TaskFunction,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
        key: str,
        when: datetime,
        attempt: int,
        trace_context: opentelemetry.context.Context | None = None,
        redelivered: bool = False,
        function_name: str | None = None,
    ) -> None:
        # Task definition (immutable)
        self._docket = docket
        self._function = function
        self._function_name = function_name or function.__name__
        self._args = args
        self._kwargs = kwargs
        self._key = key

        # Scheduling metadata
        self.when = when
        self.attempt = attempt
        self._trace_context = trace_context
        self._redelivered = redelivered

        # Lifecycle state (mutable)
        self.state: ExecutionState = ExecutionState.SCHEDULED
        self.worker: str | None = None
        self.started_at: datetime | None = None
        self.completed_at: datetime | None = None
        self.error: str | None = None
        self.result_key: str | None = None

        # Progress tracking
        self.progress: ExecutionProgress = ExecutionProgress(docket, key)

        # Redis key
        self._redis_key = docket.key(f"runs:{key}")

    # Task definition properties (immutable)
    @property
    def docket(self) -> "Docket":
        """Parent docket instance."""
        return self._docket

    @property
    def function(self) -> TaskFunction:
        """Task function to execute."""
        return self._function

    @property
    def args(self) -> tuple[Any, ...]:
        """Positional arguments for the task."""
        return self._args

    @property
    def kwargs(self) -> dict[str, Any]:
        """Keyword arguments for the task."""
        return self._kwargs

    @property
    def key(self) -> str:
        """Unique task identifier."""
        return self._key

    @property
    def function_name(self) -> str:
        """Name of the task function (from message, may differ from function.__name__ for fallback tasks)."""
        return self._function_name

    # Scheduling metadata properties
    @property
    def trace_context(self) -> opentelemetry.context.Context | None:
        """OpenTelemetry trace context."""
        return self._trace_context

    @property
    def redelivered(self) -> bool:
        """Whether this message was redelivered."""
        return self._redelivered

    def as_message(self) -> Message:
        return {
            b"key": self.key.encode(),
            b"when": self.when.isoformat().encode(),
            b"function": self.function_name.encode(),
            b"args": cloudpickle.dumps(self.args),  # type: ignore[arg-type]
            b"kwargs": cloudpickle.dumps(self.kwargs),  # type: ignore[arg-type]
            b"attempt": str(self.attempt).encode(),
        }

    @classmethod
    async def from_message(
        cls,
        docket: "Docket",
        message: Message,
        redelivered: bool = False,
        fallback_task: TaskFunction | None = None,
    ) -> Self:
        function_name = message[b"function"].decode()
        if not (function := docket.tasks.get(function_name)):
            if fallback_task is None:
                raise ValueError(
                    f"Task function {function_name!r} is not registered with the current docket"
                )
            function = fallback_task

        instance = cls(
            docket=docket,
            function=function,
            args=cloudpickle.loads(message[b"args"]),
            kwargs=cloudpickle.loads(message[b"kwargs"]),
            key=message[b"key"].decode(),
            when=datetime.fromisoformat(message[b"when"].decode()),
            attempt=int(message[b"attempt"].decode()),
            trace_context=propagate.extract(message, getter=message_getter),
            redelivered=redelivered,
            function_name=function_name,
        )
        await instance.sync()
        return instance

    def general_labels(self) -> Mapping[str, str]:
        return {"docket.task": self.function_name}

    def specific_labels(self) -> Mapping[str, str | int]:
        return {
            "docket.task": self.function_name,
            "docket.key": self.key,
            "docket.when": self.when.isoformat(),
            "docket.attempt": self.attempt,
        }

    def get_argument(self, parameter: str) -> Any:
        signature = get_signature(self.function)
        bound_args = signature.bind(*self.args, **self.kwargs)
        return bound_args.arguments[parameter]

    def call_repr(self) -> str:
        arguments: list[str] = []
        function_name = self.function_name

        signature = get_signature(self.function)
        logged_parameters = Logged.annotated_parameters(signature)
        parameter_names = list(signature.parameters.keys())

        for i, argument in enumerate(self.args[: len(parameter_names)]):
            parameter_name = parameter_names[i]
            if logged := logged_parameters.get(parameter_name):
                arguments.append(logged.format(argument))
            else:
                arguments.append("...")

        for parameter_name, argument in self.kwargs.items():
            if logged := logged_parameters.get(parameter_name):
                arguments.append(f"{parameter_name}={logged.format(argument)}")
            else:
                arguments.append(f"{parameter_name}=...")

        return f"{function_name}({', '.join(arguments)}){{{self.key}}}"

    def incoming_span_links(self) -> list[trace.Link]:
        initiating_span = trace.get_current_span(self.trace_context)
        initiating_context = initiating_span.get_span_context()
        return [trace.Link(initiating_context)] if initiating_context.is_valid else []

    async def schedule(
        self, replace: bool = False, reschedule_message: "RedisMessageID | None" = None
    ) -> None:
        """Schedule this task atomically in Redis.

        This performs an atomic operation that:
        - Adds the task to the stream (immediate) or queue (future)
        - Writes the execution state record
        - Tracks metadata for later cancellation

        Usage patterns:
        - Normal add: schedule(replace=False)
        - Replace existing: schedule(replace=True)
        - Reschedule from stream: schedule(reschedule_message=message_id)
          This atomically acknowledges and deletes the stream message, then
          reschedules the task to the queue. Prevents both task loss and
          duplicate execution when rescheduling tasks (e.g., due to concurrency limits).

        Args:
            replace: If True, replaces any existing task with the same key.
                    If False, raises an error if the task already exists.
            reschedule_message: If provided, atomically acknowledges and deletes
                    this stream message ID before rescheduling the task to the queue.
                    Used when a task needs to be rescheduled from an active stream message.
        """
        message: dict[bytes, bytes] = self.as_message()
        propagate.inject(message, setter=message_setter)

        key = self.key
        when = self.when
        known_task_key = self.docket.known_task_key(key)
        is_immediate = when <= datetime.now(timezone.utc)

        async with self.docket.redis() as redis:
            # Lock per task key to prevent race conditions between concurrent operations
            async with redis.lock(f"{known_task_key}:lock", timeout=10):
                # Register script for this connection (not cached to avoid event loop issues)
                schedule_script = cast(
                    _schedule_task,
                    redis.register_script(
                        # KEYS: stream_key, known_key, parked_key, queue_key, stream_id_key, runs_key
                        # ARGV: task_key, when_timestamp, is_immediate, replace, reschedule_message_id, worker_group_name, ...message_fields
                        """
                            local stream_key = KEYS[1]
                            -- TODO: Remove in next breaking release (v0.14.0) - legacy key locations
                            local known_key = KEYS[2]
                            local parked_key = KEYS[3]
                            local queue_key = KEYS[4]
                            local stream_id_key = KEYS[5]
                            local runs_key = KEYS[6]

                            local task_key = ARGV[1]
                            local when_timestamp = ARGV[2]
                            local is_immediate = ARGV[3] == '1'
                            local replace = ARGV[4] == '1'
                            local reschedule_message_id = ARGV[5]
                            local worker_group_name = ARGV[6]

                            -- Extract message fields from ARGV[7] onwards
                            local message = {}
                            local function_name = nil
                            local args_data = nil
                            local kwargs_data = nil

                            for i = 7, #ARGV, 2 do
                                local field_name = ARGV[i]
                                local field_value = ARGV[i + 1]
                                message[#message + 1] = field_name
                                message[#message + 1] = field_value

                                -- Extract task data fields for runs hash
                                if field_name == 'function' then
                                    function_name = field_value
                                elseif field_name == 'args' then
                                    args_data = field_value
                                elseif field_name == 'kwargs' then
                                    kwargs_data = field_value
                                end
                            end

                            -- Handle rescheduling from stream: atomically ACK message and reschedule to queue
                            -- This prevents both task loss (ACK before reschedule) and duplicate execution
                            -- (reschedule before ACK with slow reschedule causing redelivery)
                            if reschedule_message_id ~= '' then
                                -- Acknowledge and delete the message from the stream
                                redis.call('XACK', stream_key, worker_group_name, reschedule_message_id)
                                redis.call('XDEL', stream_key, reschedule_message_id)

                                -- Park task data for future execution
                                redis.call('HSET', parked_key, unpack(message))

                                -- Add to sorted set queue
                                redis.call('ZADD', queue_key, when_timestamp, task_key)

                                -- Update state in runs hash (clear stream_id since task is no longer in stream)
                                redis.call('HSET', runs_key,
                                    'state', 'scheduled',
                                    'when', when_timestamp,
                                    'function', function_name,
                                    'args', args_data,
                                    'kwargs', kwargs_data
                                )
                                redis.call('HDEL', runs_key, 'stream_id')

                                return 'OK'
                            end

                            -- Handle replacement: cancel existing task if needed
                            if replace then
                                -- Get stream ID from runs hash (check new location first)
                                local existing_message_id = redis.call('HGET', runs_key, 'stream_id')

                                -- TODO: Remove in next breaking release (v0.14.0) - check legacy location
                                if not existing_message_id then
                                    existing_message_id = redis.call('GET', stream_id_key)
                                end

                                if existing_message_id then
                                    redis.call('XDEL', stream_key, existing_message_id)
                                end

                                redis.call('ZREM', queue_key, task_key)
                                redis.call('DEL', parked_key)

                                -- TODO: Remove in next breaking release (v0.14.0) - clean up legacy keys
                                redis.call('DEL', known_key, stream_id_key)

                                -- Note: runs_key is updated below, not deleted
                            else
                                -- Check if task already exists (check new location first, then legacy)
                                local known_exists = redis.call('HEXISTS', runs_key, 'known') == 1
                                if not known_exists then
                                    -- Check if task is currently running (known field deleted at claim time)
                                    local state = redis.call('HGET', runs_key, 'state')
                                    if state == 'running' then
                                        return 'EXISTS'
                                    end
                                    -- TODO: Remove in next breaking release (v0.14.0) - check legacy location
                                    known_exists = redis.call('EXISTS', known_key) == 1
                                end
                                if known_exists then
                                    return 'EXISTS'
                                end
                            end

                            if is_immediate then
                                -- Add to stream for immediate execution
                                local message_id = redis.call('XADD', stream_key, '*', unpack(message))

                                -- Store state and metadata in runs hash
                                redis.call('HSET', runs_key,
                                    'state', 'queued',
                                    'when', when_timestamp,
                                    'known', when_timestamp,
                                    'stream_id', message_id,
                                    'function', function_name,
                                    'args', args_data,
                                    'kwargs', kwargs_data
                                )
                            else
                                -- Park task data for future execution
                                redis.call('HSET', parked_key, unpack(message))

                                -- Add to sorted set queue
                                redis.call('ZADD', queue_key, when_timestamp, task_key)

                                -- Store state and metadata in runs hash
                                redis.call('HSET', runs_key,
                                    'state', 'scheduled',
                                    'when', when_timestamp,
                                    'known', when_timestamp,
                                    'function', function_name,
                                    'args', args_data,
                                    'kwargs', kwargs_data
                                )
                            end

                            return 'OK'
                            """
                    ),
                )

                await schedule_script(
                    keys=[
                        self.docket.stream_key,
                        known_task_key,
                        self.docket.parked_task_key(key),
                        self.docket.queue_key,
                        self.docket.stream_id_key(key),
                        self._redis_key,
                    ],
                    args=[
                        key,
                        str(when.timestamp()),
                        "1" if is_immediate else "0",
                        "1" if replace else "0",
                        reschedule_message or b"",
                        self.docket.worker_group_name,
                        *[
                            item
                            for field, value in message.items()
                            for item in (field, value)
                        ],
                    ],
                )

        # Update local state based on whether task is immediate, scheduled, or being rescheduled
        if reschedule_message:
            # When rescheduling from stream, task is always parked and queued (never immediate)
            self.state = ExecutionState.SCHEDULED
            await self._publish_state(
                {"state": ExecutionState.SCHEDULED.value, "when": when.isoformat()}
            )
        elif is_immediate:
            self.state = ExecutionState.QUEUED
            await self._publish_state(
                {"state": ExecutionState.QUEUED.value, "when": when.isoformat()}
            )
        else:
            self.state = ExecutionState.SCHEDULED
            await self._publish_state(
                {"state": ExecutionState.SCHEDULED.value, "when": when.isoformat()}
            )

    async def claim(self, worker: str) -> None:
        """Atomically claim task and transition to RUNNING state.

        This consolidates worker operations when claiming a task into a single
        atomic Lua script that:
        - Sets state to RUNNING with worker name and timestamp
        - Initializes progress tracking (current=0, total=100)
        - Deletes known/stream_id fields to allow task rescheduling
        - Cleans up legacy keys for backwards compatibility

        Args:
            worker: Name of the worker claiming the task
        """
        started_at = datetime.now(timezone.utc)
        started_at_iso = started_at.isoformat()

        async with self.docket.redis() as redis:
            claim_script = redis.register_script(
                # KEYS: runs_key, progress_key, known_key, stream_id_key
                # ARGV: worker, started_at_iso
                """
                local runs_key = KEYS[1]
                local progress_key = KEYS[2]
                -- TODO: Remove in next breaking release (v0.14.0) - legacy key locations
                local known_key = KEYS[3]
                local stream_id_key = KEYS[4]

                local worker = ARGV[1]
                local started_at = ARGV[2]

                -- Update execution state to running
                redis.call('HSET', runs_key,
                    'state', 'running',
                    'worker', worker,
                    'started_at', started_at
                )

                -- Initialize progress tracking
                redis.call('HSET', progress_key,
                    'current', '0',
                    'total', '100'
                )

                -- Delete known/stream_id fields to allow task rescheduling
                redis.call('HDEL', runs_key, 'known', 'stream_id')

                -- TODO: Remove in next breaking release (v0.14.0) - legacy key cleanup
                redis.call('DEL', known_key, stream_id_key)

                return 'OK'
                """
            )

            await claim_script(
                keys=[
                    self._redis_key,  # runs_key
                    self.progress._redis_key,  # progress_key
                    self.docket.known_task_key(self.key),  # legacy known_key
                    self.docket.stream_id_key(self.key),  # legacy stream_id_key
                ],
                args=[worker, started_at_iso],
            )

        # Update local state
        self.state = ExecutionState.RUNNING
        self.worker = worker
        self.started_at = started_at
        self.progress.current = 0
        self.progress.total = 100

        # Publish state change event
        await self._publish_state(
            {
                "state": ExecutionState.RUNNING.value,
                "worker": worker,
                "started_at": started_at_iso,
            }
        )

    async def _mark_as_terminal(
        self,
        state: ExecutionState,
        *,
        error: str | None = None,
        result_key: str | None = None,
    ) -> None:
        """Mark task as having reached a terminal state.

        Args:
            state: The terminal state (COMPLETED, FAILED, or CANCELLED)
            error: Optional error message (for FAILED state)
            result_key: Optional key where the result/exception is stored

        Sets TTL on state data (from docket.execution_ttl), or deletes state
        immediately if execution_ttl is 0. Also deletes progress data.
        """
        completed_at = datetime.now(timezone.utc).isoformat()

        mapping: dict[str, str] = {
            "state": state.value,
            "completed_at": completed_at,
        }
        if error:
            mapping["error"] = error
        if result_key is not None:
            mapping["result_key"] = result_key

        async with self.docket.redis() as redis:
            await redis.hset(self._redis_key, mapping=mapping)
            if self.docket.execution_ttl:
                ttl_seconds = int(self.docket.execution_ttl.total_seconds())
                await redis.expire(self._redis_key, ttl_seconds)
            else:
                await redis.delete(self._redis_key)

        self.state = state
        if result_key is not None:
            self.result_key = result_key

        await self.progress.delete()

        state_data: dict[str, str] = {
            "state": state.value,
            "completed_at": completed_at,
        }
        if error:
            state_data["error"] = error
        await self._publish_state(state_data)

    async def mark_as_completed(self, result_key: str | None = None) -> None:
        """Mark task as completed successfully.

        Args:
            result_key: Optional key where the task result is stored
        """
        await self._mark_as_terminal(ExecutionState.COMPLETED, result_key=result_key)

    async def mark_as_failed(
        self, error: str | None = None, result_key: str | None = None
    ) -> None:
        """Mark task as failed.

        Args:
            error: Optional error message describing the failure
            result_key: Optional key where the exception is stored
        """
        await self._mark_as_terminal(
            ExecutionState.FAILED, error=error, result_key=result_key
        )

    async def mark_as_cancelled(self) -> None:
        """Mark task as cancelled."""
        await self._mark_as_terminal(ExecutionState.CANCELLED)

    async def get_result(
        self,
        *,
        timeout: timedelta | None = None,
        deadline: datetime | None = None,
    ) -> Any:
        """Retrieve the result of this task execution.

        If the execution is not yet complete, this method will wait using
        pub/sub for state updates until completion.

        Args:
            timeout: Optional duration to wait before giving up.
                    If None and deadline is None, waits indefinitely.
            deadline: Optional absolute datetime when to stop waiting.
                     If None and timeout is None, waits indefinitely.

        Returns:
            The result of the task execution, or None if the task returned None.

        Raises:
            ValueError: If both timeout and deadline are provided
            Exception: If the task failed, raises the stored exception
            TimeoutError: If timeout/deadline is reached before execution completes
        """
        # Validate that only one time limit is provided
        if timeout is not None and deadline is not None:
            raise ValueError("Cannot specify both timeout and deadline")

        # Convert timeout to deadline if provided
        if timeout is not None:
            deadline = datetime.now(timezone.utc) + timeout

        # Wait for execution to complete if not already done
        if self.state not in (ExecutionState.COMPLETED, ExecutionState.FAILED):
            # Calculate timeout duration if absolute deadline provided
            timeout_seconds = None
            if deadline is not None:
                timeout_seconds = (
                    deadline - datetime.now(timezone.utc)
                ).total_seconds()
                if timeout_seconds <= 0:
                    raise TimeoutError(
                        f"Timeout waiting for execution {self.key} to complete"
                    )

            try:

                async def wait_for_completion():
                    async for event in self.subscribe():  # pragma: no branch
                        if event["type"] == "state":
                            state = ExecutionState(event["state"])
                            if state in (
                                ExecutionState.COMPLETED,
                                ExecutionState.FAILED,
                            ):
                                # Sync to get latest data including result key
                                await self.sync()
                                break

                # Use asyncio.wait_for to enforce timeout
                await asyncio.wait_for(wait_for_completion(), timeout=timeout_seconds)
            except asyncio.TimeoutError:
                raise TimeoutError(
                    f"Timeout waiting for execution {self.key} to complete"
                )

        # If failed, retrieve and raise the exception
        if self.state == ExecutionState.FAILED:
            if self.result_key:
                # Retrieve serialized exception from result_storage
                result_data = await self.docket.result_storage.get(self.result_key)
                if result_data and "data" in result_data:
                    # Base64-decode and unpickle
                    pickled_exception = base64.b64decode(result_data["data"])
                    exception = cloudpickle.loads(pickled_exception)  # type: ignore[arg-type]
                    raise exception
            # If no stored exception, raise a generic error with the error message
            error_msg = self.error or "Task execution failed"
            raise Exception(error_msg)

        # If completed successfully, retrieve result if available
        if self.result_key:
            result_data = await self.docket.result_storage.get(self.result_key)
            if result_data is not None and "data" in result_data:
                # Base64-decode and unpickle
                pickled_result = base64.b64decode(result_data["data"])
                return cloudpickle.loads(pickled_result)  # type: ignore[arg-type]

        # No result stored - task returned None
        return None

    async def sync(self) -> None:
        """Synchronize instance attributes with current execution data from Redis.

        Updates self.state, execution metadata, and progress data from Redis.
        Sets attributes to None if no data exists.
        """
        async with self.docket.redis() as redis:
            data = await redis.hgetall(self._redis_key)
            if data:
                # Update state
                state_value = data.get(b"state")
                if state_value:
                    if isinstance(state_value, bytes):
                        state_value = state_value.decode()
                    self.state = ExecutionState(state_value)

                # Update metadata
                self.worker = data[b"worker"].decode() if b"worker" in data else None
                self.started_at = (
                    datetime.fromisoformat(data[b"started_at"].decode())
                    if b"started_at" in data
                    else None
                )
                self.completed_at = (
                    datetime.fromisoformat(data[b"completed_at"].decode())
                    if b"completed_at" in data
                    else None
                )
                self.error = data[b"error"].decode() if b"error" in data else None
                self.result_key = (
                    data[b"result_key"].decode() if b"result_key" in data else None
                )
            else:
                # No data exists - reset to defaults
                self.state = ExecutionState.SCHEDULED
                self.worker = None
                self.started_at = None
                self.completed_at = None
                self.error = None
                self.result_key = None

        # Sync progress data
        await self.progress.sync()

    async def _publish_state(self, data: dict) -> None:
        """Publish state change to Redis pub/sub channel.

        Args:
            data: State data to publish
        """
        channel = self.docket.key(f"state:{self.key}")
        # Create ephemeral Redis client for publishing
        async with self.docket.redis() as redis:
            # Build payload with all relevant state information
            payload = {
                "type": "state",
                "key": self.key,
                **data,
            }
            await redis.publish(channel, json.dumps(payload))

    async def subscribe(self) -> AsyncGenerator[StateEvent | ProgressEvent, None]:
        """Subscribe to both state and progress updates for this task.

        Emits the current state as the first event, then subscribes to real-time
        state and progress updates via Redis pub/sub.

        Yields:
            Dict containing state or progress update events with a 'type' field:
            - For state events: type="state", state, worker, timestamps, error
            - For progress events: type="progress", current, total, message, updated_at
        """
        # First, emit the current state
        await self.sync()

        # Build initial state event from current attributes
        initial_state: StateEvent = {
            "type": "state",
            "key": self.key,
            "state": self.state,
            "when": self.when.isoformat(),
            "worker": self.worker,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat()
            if self.completed_at
            else None,
            "error": self.error,
        }

        yield initial_state

        progress_event: ProgressEvent = {
            "type": "progress",
            "key": self.key,
            "current": self.progress.current,
            "total": self.progress.total,
            "message": self.progress.message,
            "updated_at": self.progress.updated_at.isoformat()
            if self.progress.updated_at
            else None,
        }

        yield progress_event

        # Then subscribe to real-time updates
        state_channel = self.docket.key(f"state:{self.key}")
        progress_channel = self.docket.key(f"progress:{self.key}")
        async with self.docket.redis() as redis:
            async with redis.pubsub() as pubsub:
                await pubsub.subscribe(state_channel, progress_channel)
                try:
                    async for message in pubsub.listen():  # pragma: no cover
                        if message["type"] == "message":
                            message_data = json.loads(message["data"])
                            if message_data["type"] == "state":
                                message_data["state"] = ExecutionState(
                                    message_data["state"]
                                )
                            yield message_data
                finally:
                    # Explicitly unsubscribe to ensure clean shutdown
                    await pubsub.unsubscribe(state_channel, progress_channel)


def compact_signature(signature: inspect.Signature) -> str:
    from .dependencies import Dependency

    parameters: list[str] = []
    dependencies: int = 0

    for parameter in signature.parameters.values():
        if isinstance(parameter.default, Dependency):
            dependencies += 1
            continue

        parameter_definition = parameter.name
        if parameter.annotation is not parameter.empty:
            annotation = parameter.annotation
            if hasattr(annotation, "__origin__"):
                annotation = annotation.__args__[0]

            type_name = getattr(annotation, "__name__", str(annotation))
            parameter_definition = f"{parameter.name}: {type_name}"

        if parameter.default is not parameter.empty:
            parameter_definition = f"{parameter_definition} = {parameter.default!r}"

        parameters.append(parameter_definition)

    if dependencies > 0:
        parameters.append("...")

    return ", ".join(parameters)
