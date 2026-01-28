"""Strike list with optional Redis synchronization.

This module provides the StrikeList class which manages strike conditions
for blocking task execution. When connected to Redis, it monitors a stream
for strike/restore instructions issued by external processes.
"""

import abc
import asyncio
import enum
import logging
from contextlib import contextmanager
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Generator,
    Hashable,
    Literal,
    Mapping,
    NoReturn,
    cast,
)

import cloudpickle  # type: ignore[import]
import redis.exceptions
from opentelemetry.instrumentation.utils import suppress_instrumentation
from redis.asyncio import ConnectionPool, Redis
from typing_extensions import Self

if TYPE_CHECKING:
    from .execution import Execution

from ._redis import connection_pool_from_url

logger: logging.Logger = logging.getLogger(__name__)

Message = dict[bytes, bytes]


class Operator(str, enum.Enum):
    EQUAL = "=="
    NOT_EQUAL = "!="
    GREATER_THAN = ">"
    GREATER_THAN_OR_EQUAL = ">="
    LESS_THAN = "<"
    LESS_THAN_OR_EQUAL = "<="
    BETWEEN = "between"


LiteralOperator = Literal["==", "!=", ">", ">=", "<", "<=", "between"]


class StrikeInstruction(abc.ABC):
    direction: Literal["strike", "restore"]
    operator: Operator

    def __init__(
        self,
        function: str | None,
        parameter: str | None,
        operator: Operator,
        value: Hashable,
    ) -> None:
        self.function = function
        self.parameter = parameter
        self.operator = operator
        self.value = value

    def as_message(self) -> Message:
        message: dict[bytes, bytes] = {b"direction": self.direction.encode()}
        if self.function:
            message[b"function"] = self.function.encode()
        if self.parameter:
            message[b"parameter"] = self.parameter.encode()
        message[b"operator"] = self.operator.encode()
        message[b"value"] = cloudpickle.dumps(self.value)  # type: ignore[arg-type]
        return message

    @classmethod
    def from_message(cls, message: Message) -> "StrikeInstruction":
        direction = cast(Literal["strike", "restore"], message[b"direction"].decode())
        function = message[b"function"].decode() if b"function" in message else None
        parameter = message[b"parameter"].decode() if b"parameter" in message else None
        operator = cast(Operator, message[b"operator"].decode())
        value = cloudpickle.loads(message[b"value"])
        if direction == "strike":
            return Strike(function, parameter, operator, value)
        else:
            return Restore(function, parameter, operator, value)

    def labels(self) -> Mapping[str, str]:
        labels: dict[str, str] = {}
        if self.function:
            labels["docket.task"] = self.function

        if self.parameter:
            labels["docket.parameter"] = self.parameter
            labels["docket.operator"] = self.operator
            labels["docket.value"] = repr(self.value)

        return labels

    def call_repr(self) -> str:
        return (
            f"{self.function or '*'}"
            "("
            f"{self.parameter or '*'}"
            " "
            f"{self.operator}"
            " "
            f"{repr(self.value) if self.parameter else '*'}"
            ")"
        )


class Strike(StrikeInstruction):
    direction: Literal["strike", "restore"] = "strike"


class Restore(StrikeInstruction):
    direction: Literal["strike", "restore"] = "restore"


MinimalStrike = tuple[Operator, Hashable]
ParameterStrikes = dict[str, set[MinimalStrike]]
TaskStrikes = dict[str, ParameterStrikes]


class StrikeList:
    """A strike list that manages conditions for blocking task execution.

    When a URL is provided, the strike list will connect to Redis and monitor
    a stream for strike/restore instructions. External processes (like Docket)
    can issue strikes, and all StrikeList instances listening to the same
    stream will receive and apply those updates.

    Example using context manager with Redis:
        async with StrikeList(url="redis://localhost:6379/0", name="my-docket") as strikes:
            # External process issues: await docket.strike("my_task", "customer_id", "==", "blocked")

            if strikes.is_stricken({"customer_id": "blocked"}):
                print("Customer is blocked")

    Example with Docket (managed internally):
        async with Docket(name="my-docket", url="redis://localhost:6379/0") as docket:
            # Docket manages its own StrikeList internally
            await docket.strike(None, "customer_id", "==", "blocked")

    Example using explicit connect/close:
        strikes = StrikeList(url="redis://localhost:6379/0", name="my-docket")
        await strikes.connect()
        try:
            if strikes.is_stricken({"customer_id": "blocked"}):
                print("Customer is blocked")
        finally:
            await strikes.close()

    Example without Redis (local-only):
        strikes = StrikeList()  # No URL = no Redis connection
        strikes.update(Strike(None, "customer_id", Operator.EQUAL, "blocked"))
        if strikes.is_stricken({"customer_id": "blocked"}):
            print("Customer is blocked")
    """

    task_strikes: TaskStrikes
    parameter_strikes: ParameterStrikes
    _conditions: list[Callable[["Execution"], bool]]
    _connection_pool: ConnectionPool | None
    _monitor_task: asyncio.Task[NoReturn] | None
    _strikes_loaded: asyncio.Event | None

    def __init__(
        self,
        url: str | None = None,
        name: str = "strikelist",
        enable_internal_instrumentation: bool = False,
    ) -> None:
        """Initialize a StrikeList.

        Args:
            url: Redis connection URL. Use "memory://" for in-memory testing.
                 If None, no Redis connection is made (local-only mode).
            name: Name used as prefix for Redis keys (should match the Docket name
                  if you want to receive strikes from that Docket).
            enable_internal_instrumentation: If True, allows OpenTelemetry spans
                for internal Redis operations. Default False suppresses these spans.
        """
        self.url = url
        self.name = name
        self.enable_internal_instrumentation = enable_internal_instrumentation
        self.task_strikes = {}
        self.parameter_strikes = {}
        self._conditions = [self._matches_task_or_parameter_strike]
        self._connection_pool = None
        self._monitor_task = None
        self._strikes_loaded = None

    @property
    def prefix(self) -> str:
        """Return the key prefix for this strike list.

        All Redis keys for this strike list are prefixed with this value.
        """
        return self.name

    @property
    def strike_key(self) -> str:
        """Redis stream key for strike instructions."""
        return f"{self.prefix}:strikes"

    @contextmanager
    def _maybe_suppress_instrumentation(self) -> Generator[None, None, None]:
        """Suppress OTel auto-instrumentation for internal Redis operations."""
        if not self.enable_internal_instrumentation:
            with suppress_instrumentation():
                yield
        else:
            yield

    async def connect(self) -> None:
        """Connect to Redis and start monitoring for strike updates.

        If no URL was provided during initialization, this is a no-op.
        This method sets up the Redis connection pool and starts a background
        task that monitors the strike stream for updates.
        """
        if self.url is None:
            return  # No Redis connection needed

        if self._connection_pool is not None:
            return  # Already connected

        self._connection_pool = await connection_pool_from_url(self.url)

        self._strikes_loaded = asyncio.Event()
        self._monitor_task = asyncio.create_task(
            self._monitor_strikes(), name="docket.strikelist.monitor"
        )

    async def close(self) -> None:
        """Close the Redis connection and stop monitoring.

        This method cancels the background monitoring task and disconnects
        from Redis. It is safe to call multiple times.
        """
        if self._monitor_task is not None:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        self._strikes_loaded = None

        if self._connection_pool is not None:
            await asyncio.shield(self._connection_pool.disconnect())
            self._connection_pool = None

    async def __aenter__(self) -> Self:
        """Async context manager entry - connects to Redis if URL provided."""
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Async context manager exit - closes Redis connection."""
        await self.close()

    def add_condition(self, condition: Callable[["Execution"], bool]) -> None:
        """Adds a temporary condition that indicates an execution is stricken."""
        self._conditions.insert(0, condition)

    def remove_condition(self, condition: Callable[["Execution"], bool]) -> None:
        """Removes a temporary condition that indicates an execution is stricken."""
        assert condition is not self._matches_task_or_parameter_strike
        self._conditions.remove(condition)

    async def wait_for_strikes_loaded(self) -> None:
        """Wait for all existing strikes to be loaded from the stream.

        This method blocks until the strike monitor has completed its initial
        non-blocking read of all existing strike messages. Call this before
        making decisions that depend on the current strike state.

        If not connected to Redis (local-only mode), returns immediately.
        """
        if self._strikes_loaded is None:
            return
        await self._strikes_loaded.wait()

    async def send_instruction(self, instruction: StrikeInstruction) -> None:
        """Send a strike instruction to Redis and update local state.

        Args:
            instruction: The Strike or Restore instruction to send.

        Raises:
            RuntimeError: If not connected to Redis.
        """
        if self._connection_pool is None:
            raise RuntimeError(
                "Cannot send strike instruction: not connected to Redis. "
                "Use connect() or async context manager first."
            )

        async with Redis(connection_pool=self._connection_pool) as r:
            await r.xadd(self.strike_key, instruction.as_message())  # type: ignore[arg-type]

        self.update(instruction)

    async def strike(
        self,
        function: str | None = None,
        parameter: str | None = None,
        operator: "Operator | LiteralOperator" = "==",
        value: Hashable | None = None,
    ) -> None:
        """Issue a strike to block matching tasks or parameters.

        Args:
            function: Task function name to strike, or None for all tasks.
            parameter: Parameter name to match, or None for entire task.
            operator: Comparison operator for the value.
            value: Value to compare against.
        """
        instruction = Strike(function, parameter, Operator(operator), value)
        await self.send_instruction(instruction)

    async def restore(
        self,
        function: str | None = None,
        parameter: str | None = None,
        operator: "Operator | LiteralOperator" = "==",
        value: Hashable | None = None,
    ) -> None:
        """Restore a previously issued strike.

        Args:
            function: Task function name to restore, or None for all tasks.
            parameter: Parameter name to match, or None for entire task.
            operator: Comparison operator for the value.
            value: Value to compare against.
        """
        instruction = Restore(function, parameter, Operator(operator), value)
        await self.send_instruction(instruction)

    def is_stricken(self, target: "Execution | Mapping[str, Any]") -> bool:
        """Check if a target matches any strike condition.

        Args:
            target: Either an Execution object (for Docket/Worker use) or
                   a dictionary of parameter names to values (for standalone use).

        Returns:
            True if any parameter matches a strike condition.
        """
        # Check if this is a dict-like object (Mapping)
        if isinstance(target, Mapping):
            return self._is_dict_stricken(target)

        # Otherwise it's an Execution - use the full condition checking
        return any(condition(target) for condition in self._conditions)

    def _is_dict_stricken(self, params: Mapping[str, Any]) -> bool:
        """Check if a parameter dict matches any strike condition.

        Args:
            params: Dictionary of parameter names to values.

        Returns:
            True if any parameter matches a strike condition.
        """
        for parameter, argument in params.items():
            if parameter not in self.parameter_strikes:
                continue

            for operator, strike_value in self.parameter_strikes[parameter]:
                if self._is_match(argument, operator, strike_value):
                    return True

        return False

    def _matches_task_or_parameter_strike(self, execution: "Execution") -> bool:
        from .execution import get_signature

        function_name = execution.function_name

        # Check if the entire task is stricken (without parameter conditions)
        task_strikes = self.task_strikes.get(function_name, {})
        if function_name in self.task_strikes and not task_strikes:
            return True

        signature = get_signature(execution.function)

        try:
            bound_args = signature.bind(*execution.args, **execution.kwargs)
            bound_args.apply_defaults()
        except TypeError:
            # If we can't make sense of the arguments, just assume the task is fine
            return False

        all_arguments = {
            **bound_args.arguments,
            **{
                k: v
                for k, v in execution.kwargs.items()
                if k not in bound_args.arguments
            },
        }

        for parameter, argument in all_arguments.items():
            for strike_source in [task_strikes, self.parameter_strikes]:
                if parameter not in strike_source:
                    continue

                for operator, strike_value in strike_source[parameter]:
                    if self._is_match(argument, operator, strike_value):
                        return True

        return False

    def _is_match(self, value: Any, operator: Operator, strike_value: Any) -> bool:
        """Determines if a value matches a strike condition."""
        try:
            match operator:
                case "==":
                    return value == strike_value
                case "!=":
                    return value != strike_value
                case ">":
                    return value > strike_value
                case ">=":
                    return value >= strike_value
                case "<":
                    return value < strike_value
                case "<=":
                    return value <= strike_value
                case "between":  # pragma: no branch
                    lower, upper = strike_value
                    return lower <= value <= upper
                case _:  # pragma: no cover
                    raise ValueError(f"Unknown operator: {operator}")
        except (ValueError, TypeError):
            # If we can't make the comparison due to incompatible types, just log the
            # error and assume the task is not stricken
            logger.warning(
                "Incompatible type for strike condition: %r %s %r",
                strike_value,
                operator,
                value,
                exc_info=True,
            )
            return False

    def update(self, instruction: StrikeInstruction) -> None:
        try:
            hash(instruction.value)
        except TypeError:
            logger.warning(
                "Incompatible type for strike condition: %s %r",
                instruction.operator,
                instruction.value,
            )
            return

        if isinstance(instruction, Strike):
            self._strike(instruction)
        elif isinstance(instruction, Restore):  # pragma: no branch
            self._restore(instruction)

    def _strike(self, strike: Strike) -> None:
        if strike.function and strike.parameter:
            try:
                task_strikes = self.task_strikes[strike.function]
            except KeyError:
                task_strikes = self.task_strikes[strike.function] = {}

            try:
                parameter_strikes = task_strikes[strike.parameter]
            except KeyError:
                parameter_strikes = task_strikes[strike.parameter] = set()

            parameter_strikes.add((strike.operator, strike.value))

        elif strike.function:
            try:
                task_strikes = self.task_strikes[strike.function]
            except KeyError:
                task_strikes = self.task_strikes[strike.function] = {}

        elif strike.parameter:  # pragma: no branch
            try:
                parameter_strikes = self.parameter_strikes[strike.parameter]
            except KeyError:
                parameter_strikes = self.parameter_strikes[strike.parameter] = set()

            parameter_strikes.add((strike.operator, strike.value))

    def _restore(self, restore: Restore) -> None:
        if restore.function and restore.parameter:
            try:
                task_strikes = self.task_strikes[restore.function]
            except KeyError:
                return

            try:
                parameter_strikes = task_strikes[restore.parameter]
            except KeyError:
                task_strikes.pop(restore.parameter, None)
                return

            try:
                parameter_strikes.remove((restore.operator, restore.value))
            except KeyError:
                pass

            if not parameter_strikes:
                task_strikes.pop(restore.parameter, None)
                if not task_strikes:
                    self.task_strikes.pop(restore.function, None)

        elif restore.function:
            try:
                task_strikes = self.task_strikes[restore.function]
            except KeyError:
                return

            # If there are no parameter strikes, this was a full task strike
            if not task_strikes:
                self.task_strikes.pop(restore.function, None)

        elif restore.parameter:  # pragma: no branch
            try:
                parameter_strikes = self.parameter_strikes[restore.parameter]
            except KeyError:
                return

            try:
                parameter_strikes.remove((restore.operator, restore.value))
            except KeyError:
                pass

            if not parameter_strikes:
                self.parameter_strikes.pop(restore.parameter, None)

    async def _monitor_strikes(self) -> NoReturn:
        """Background task that monitors Redis for strike updates."""
        from .instrumentation import REDIS_DISRUPTIONS, STRIKES_IN_EFFECT

        last_id = "0-0"
        initial_load_complete = False
        while True:
            try:
                async with Redis(connection_pool=self._connection_pool) as r:
                    while True:
                        with self._maybe_suppress_instrumentation():
                            # Non-blocking for initial load (block=None), then block
                            # for new messages (block=60_000). Note: block=0 means
                            # "block forever" in Redis, not "non-blocking".
                            streams = await r.xread(
                                {self.strike_key: last_id},
                                count=100,
                                block=60_000 if initial_load_complete else None,
                            )

                        # If no messages and we haven't signaled yet, initial load is done
                        if not streams and not initial_load_complete:
                            initial_load_complete = True
                            # _strikes_loaded is always set when _monitor_strikes runs
                            assert self._strikes_loaded is not None
                            self._strikes_loaded.set()
                            continue

                        for _, messages in streams:
                            for message_id, message in messages:
                                last_id = message_id
                                instruction = StrikeInstruction.from_message(message)
                                self.update(instruction)
                                logger.info(
                                    "%s %r",
                                    (
                                        "Striking"
                                        if instruction.direction == "strike"
                                        else "Restoring"
                                    ),
                                    instruction.call_repr(),
                                )

                                STRIKES_IN_EFFECT.add(
                                    1 if instruction.direction == "strike" else -1,
                                    {
                                        "docket.name": self.name,
                                        **instruction.labels(),
                                    },
                                )

            except redis.exceptions.ConnectionError:  # pragma: no cover
                REDIS_DISRUPTIONS.add(1, {"docket": self.name})
                logger.warning("Connection error, sleeping for 1 second...")
                await asyncio.sleep(1)
            except Exception:  # pragma: no cover
                logger.exception("Error monitoring strikes")
                await asyncio.sleep(1)
