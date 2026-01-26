import abc
import inspect
import logging
import time
from contextlib import AsyncExitStack, asynccontextmanager
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncContextManager,
    AsyncGenerator,
    Awaitable,
    Callable,
    ContextManager,
    Counter,
    Generic,
    NoReturn,
    TypeVar,
    cast,
)

from .docket import Docket
from .execution import Execution, ExecutionProgress, TaskFunction, get_signature
from .instrumentation import CACHE_SIZE
# Run and RunProgress have been consolidated into Execution

if TYPE_CHECKING:  # pragma: no cover
    from .worker import Worker


class Dependency(abc.ABC):
    single: bool = False

    docket: ContextVar[Docket] = ContextVar("docket")
    worker: ContextVar["Worker"] = ContextVar("worker")
    execution: ContextVar[Execution] = ContextVar("execution")

    @abc.abstractmethod
    async def __aenter__(self) -> Any: ...  # pragma: no cover

    async def __aexit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc_value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> bool: ...  # pragma: no cover


class _CurrentWorker(Dependency):
    async def __aenter__(self) -> "Worker":
        return self.worker.get()


def CurrentWorker() -> "Worker":
    """A dependency to access the current Worker.

    Example:

    ```python
    @task
    async def my_task(worker: Worker = CurrentWorker()) -> None:
        assert isinstance(worker, Worker)
    ```
    """
    return cast("Worker", _CurrentWorker())


class _CurrentDocket(Dependency):
    async def __aenter__(self) -> Docket:
        return self.docket.get()


def CurrentDocket() -> Docket:
    """A dependency to access the current Docket.

    Example:

    ```python
    @task
    async def my_task(docket: Docket = CurrentDocket()) -> None:
        assert isinstance(docket, Docket)
    ```
    """
    return cast(Docket, _CurrentDocket())


class _CurrentExecution(Dependency):
    async def __aenter__(self) -> Execution:
        return self.execution.get()


def CurrentExecution() -> Execution:
    """A dependency to access the current Execution.

    Example:

    ```python
    @task
    async def my_task(execution: Execution = CurrentExecution()) -> None:
        assert isinstance(execution, Execution)
    ```
    """
    return cast(Execution, _CurrentExecution())


class _TaskKey(Dependency):
    async def __aenter__(self) -> str:
        return self.execution.get().key


def TaskKey() -> str:
    """A dependency to access the key of the currently executing task.

    Example:

    ```python
    @task
    async def my_task(key: str = TaskKey()) -> None:
        assert isinstance(key, str)
    ```
    """
    return cast(str, _TaskKey())


class _TaskArgument(Dependency):
    parameter: str | None
    optional: bool

    def __init__(self, parameter: str | None = None, optional: bool = False) -> None:
        self.parameter = parameter
        self.optional = optional

    async def __aenter__(self) -> Any:
        assert self.parameter is not None
        execution = self.execution.get()
        try:
            return execution.get_argument(self.parameter)
        except KeyError:
            if self.optional:
                return None
            raise


def TaskArgument(parameter: str | None = None, optional: bool = False) -> Any:
    """A dependency to access a argument of the currently executing task.  This is
    often useful in dependency functions so they can access the arguments of the
    task they are injected into.

    Example:

    ```python
    async def customer_name(customer_id: int = TaskArgument()) -> str:
        ...look up the customer's name by ID...
        return "John Doe"

    @task
    async def greet_customer(customer_id: int, name: str = Depends(customer_name)) -> None:
        print(f"Hello, {name}!")
    ```
    """
    return cast(Any, _TaskArgument(parameter, optional))


class _TaskLogger(Dependency):
    async def __aenter__(self) -> "logging.LoggerAdapter[logging.Logger]":
        execution = self.execution.get()
        logger = logging.getLogger(f"docket.task.{execution.function_name}")
        return logging.LoggerAdapter(
            logger,
            {
                **self.docket.get().labels(),
                **self.worker.get().labels(),
                **execution.specific_labels(),
            },
        )


def TaskLogger() -> "logging.LoggerAdapter[logging.Logger]":
    """A dependency to access a logger for the currently executing task.  The logger
    will automatically inject contextual information such as the worker and docket
    name, the task key, and the current execution attempt number.

    Example:

    ```python
    @task
    async def my_task(logger: "LoggerAdapter[Logger]" = TaskLogger()) -> None:
        logger.info("Hello, world!")
    ```
    """
    return cast("logging.LoggerAdapter[logging.Logger]", _TaskLogger())


class Progress(Dependency):
    """A dependency to report progress updates for the currently executing task.

    Tasks can use this to report their current progress (current/total values) and
    status messages to external observers.

    Example:

    ```python
    @task
    async def process_records(records: list, progress: Progress = Progress()) -> None:
        await progress.set_total(len(records))
        for i, record in enumerate(records):
            await process(record)
            await progress.increment()
            await progress.set_message(f"Processed {record.id}")
    ```
    """

    def __init__(self) -> None:
        self._progress: ExecutionProgress | None = None

    async def __aenter__(self) -> "Progress":
        execution = self.execution.get()
        self._progress = execution.progress
        return self

    @property
    def current(self) -> int | None:
        """Current progress value."""
        assert self._progress is not None, "Progress must be used as a dependency"
        return self._progress.current

    @property
    def total(self) -> int:
        """Total/target value for progress tracking."""
        assert self._progress is not None, "Progress must be used as a dependency"
        return self._progress.total

    @property
    def message(self) -> str | None:
        """User-provided status message."""
        assert self._progress is not None, "Progress must be used as a dependency"
        return self._progress.message

    async def set_total(self, total: int) -> None:
        """Set the total/target value for progress tracking."""
        assert self._progress is not None, "Progress must be used as a dependency"
        await self._progress.set_total(total)

    async def increment(self, amount: int = 1) -> None:
        """Atomically increment the current progress value."""
        assert self._progress is not None, "Progress must be used as a dependency"
        await self._progress.increment(amount)

    async def set_message(self, message: str | None) -> None:
        """Update the progress status message."""
        assert self._progress is not None, "Progress must be used as a dependency"
        await self._progress.set_message(message)


class ForcedRetry(Exception):
    """Raised when a task requests a retry via `in_` or `at`"""


class Retry(Dependency):
    """Configures linear retries for a task.  You can specify the total number of
    attempts (or `None` to retry indefinitely), and the delay between attempts.

    Example:

    ```python
    @task
    async def my_task(retry: Retry = Retry(attempts=3)) -> None:
        ...
    ```
    """

    single: bool = True

    def __init__(
        self, attempts: int | None = 1, delay: timedelta = timedelta(0)
    ) -> None:
        """
        Args:
            attempts: The total number of attempts to make.  If `None`, the task will
                be retried indefinitely.
            delay: The delay between attempts.
        """
        self.attempts = attempts
        self.delay = delay
        self.attempt = 1

    async def __aenter__(self) -> "Retry":
        execution = self.execution.get()
        retry = Retry(attempts=self.attempts, delay=self.delay)
        retry.attempt = execution.attempt
        return retry

    def at(self, when: datetime) -> NoReturn:
        now = datetime.now(timezone.utc)
        diff = when - now
        diff = diff if diff.total_seconds() >= 0 else timedelta(0)

        self.in_(diff)

    def in_(self, when: timedelta) -> NoReturn:
        self.delay: timedelta = when
        raise ForcedRetry()


class ExponentialRetry(Retry):
    """Configures exponential retries for a task.  You can specify the total number
    of attempts (or `None` to retry indefinitely), and the minimum and maximum delays
    between attempts.

    Example:

    ```python
    @task
    async def my_task(retry: ExponentialRetry = ExponentialRetry(attempts=3)) -> None:
        ...
    ```
    """

    def __init__(
        self,
        attempts: int | None = 1,
        minimum_delay: timedelta = timedelta(seconds=1),
        maximum_delay: timedelta = timedelta(seconds=64),
    ) -> None:
        """
        Args:
            attempts: The total number of attempts to make.  If `None`, the task will
                be retried indefinitely.
            minimum_delay: The minimum delay between attempts.
            maximum_delay: The maximum delay between attempts.
        """
        super().__init__(attempts=attempts, delay=minimum_delay)
        self.maximum_delay = maximum_delay

    async def __aenter__(self) -> "ExponentialRetry":
        execution = self.execution.get()

        retry = ExponentialRetry(
            attempts=self.attempts,
            minimum_delay=self.delay,
            maximum_delay=self.maximum_delay,
        )
        retry.attempt = execution.attempt

        if execution.attempt > 1:
            backoff_factor = 2 ** (execution.attempt - 1)
            calculated_delay = self.delay * backoff_factor

            if calculated_delay > self.maximum_delay:
                retry.delay = self.maximum_delay
            else:
                retry.delay = calculated_delay

        return retry


class Perpetual(Dependency):
    """Declare a task that should be run perpetually.  Perpetual tasks are automatically
    rescheduled for the future after they finish (whether they succeed or fail).  A
    perpetual task can be scheduled at worker startup with the `automatic=True`.

    Example:

    ```python
    @task
    async def my_task(perpetual: Perpetual = Perpetual()) -> None:
        ...
    ```
    """

    single = True

    every: timedelta
    automatic: bool

    args: tuple[Any, ...]
    kwargs: dict[str, Any]

    cancelled: bool

    def __init__(
        self,
        every: timedelta = timedelta(0),
        automatic: bool = False,
    ) -> None:
        """
        Args:
            every: The target interval between task executions.
            automatic: If set, this task will be automatically scheduled during worker
                startup and continually through the worker's lifespan.  This ensures
                that the task will always be scheduled despite crashes and other
                adverse conditions.  Automatic tasks must not require any arguments.
        """
        self.every = every
        self.automatic = automatic
        self.cancelled = False

    async def __aenter__(self) -> "Perpetual":
        execution = self.execution.get()
        perpetual = Perpetual(every=self.every)
        perpetual.args = execution.args
        perpetual.kwargs = execution.kwargs
        return perpetual

    def cancel(self) -> None:
        self.cancelled = True

    def perpetuate(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


class Timeout(Dependency):
    """Configures a timeout for a task.  You can specify the base timeout, and the
    task will be cancelled if it exceeds this duration.  The timeout may be extended
    within the context of a single running task.

    Example:

    ```python
    @task
    async def my_task(timeout: Timeout = Timeout(timedelta(seconds=10))) -> None:
        ...
    ```
    """

    single: bool = True

    base: timedelta
    _deadline: float

    def __init__(self, base: timedelta) -> None:
        """
        Args:
            base: The base timeout duration.
        """
        self.base = base

    async def __aenter__(self) -> "Timeout":
        timeout = Timeout(base=self.base)
        timeout.start()
        return timeout

    def start(self) -> None:
        self._deadline = time.monotonic() + self.base.total_seconds()

    def expired(self) -> bool:
        return time.monotonic() >= self._deadline

    def remaining(self) -> timedelta:
        """Get the remaining time until the timeout expires."""
        return timedelta(seconds=self._deadline - time.monotonic())

    def extend(self, by: timedelta | None = None) -> None:
        """Extend the timeout by a given duration.  If no duration is provided, the
        base timeout will be used.

        Args:
            by: The duration to extend the timeout by.
        """
        if by is None:
            by = self.base
        self._deadline += by.total_seconds()


R = TypeVar("R")

DependencyFunction = Callable[
    ..., R | Awaitable[R] | ContextManager[R] | AsyncContextManager[R]
]


_parameter_cache: dict[
    TaskFunction | DependencyFunction[Any],
    dict[str, Dependency],
] = {}


def get_dependency_parameters(
    function: TaskFunction | DependencyFunction[Any],
) -> dict[str, Dependency]:
    if function in _parameter_cache:
        CACHE_SIZE.set(len(_parameter_cache), {"cache": "parameter"})
        return _parameter_cache[function]

    dependencies: dict[str, Dependency] = {}

    signature = get_signature(function)

    for parameter, param in signature.parameters.items():
        if not isinstance(param.default, Dependency):
            continue

        dependencies[parameter] = param.default

    _parameter_cache[function] = dependencies
    CACHE_SIZE.set(len(_parameter_cache), {"cache": "parameter"})
    return dependencies


class _Depends(Dependency, Generic[R]):
    dependency: DependencyFunction[R]

    cache: ContextVar[dict[DependencyFunction[Any], Any]] = ContextVar("cache")
    stack: ContextVar[AsyncExitStack] = ContextVar("stack")

    def __init__(
        self,
        dependency: Callable[
            [], R | Awaitable[R] | ContextManager[R] | AsyncContextManager[R]
        ],
    ) -> None:
        self.dependency = dependency

    async def _resolve_parameters(
        self,
        function: TaskFunction | DependencyFunction[Any],
    ) -> dict[str, Any]:
        stack = self.stack.get()

        arguments: dict[str, Any] = {}
        parameters = get_dependency_parameters(function)

        for parameter, dependency in parameters.items():
            # Special case for TaskArguments, they are "magical" and infer the parameter
            # they refer to from the parameter name (unless otherwise specified)
            if isinstance(dependency, _TaskArgument) and not dependency.parameter:
                dependency.parameter = parameter

            arguments[parameter] = await stack.enter_async_context(dependency)

        return arguments

    async def __aenter__(self) -> R:
        cache = self.cache.get()

        if self.dependency in cache:
            return cache[self.dependency]

        stack = self.stack.get()
        arguments = await self._resolve_parameters(self.dependency)

        raw_value: R | Awaitable[R] | ContextManager[R] | AsyncContextManager[R] = (
            self.dependency(**arguments)
        )

        # Handle different return types from the dependency function
        resolved_value: R
        if isinstance(raw_value, AsyncContextManager):
            # Async context manager: await enter_async_context
            resolved_value = await stack.enter_async_context(raw_value)
        elif isinstance(raw_value, ContextManager):
            # Sync context manager: use enter_context (no await needed)
            resolved_value = stack.enter_context(raw_value)
        elif inspect.iscoroutine(raw_value) or isinstance(raw_value, Awaitable):
            # Async function returning awaitable: await it
            resolved_value = await cast(Awaitable[R], raw_value)
        else:
            # Sync function returning a value directly, use as-is
            resolved_value = cast(R, raw_value)

        cache[self.dependency] = resolved_value
        return resolved_value


def Depends(dependency: DependencyFunction[R]) -> R:
    """Include a user-defined function as a dependency.  Dependencies may be:
    - Synchronous functions returning a value
    - Asynchronous functions returning a value (awaitable)
    - Synchronous context managers (using @contextmanager)
    - Asynchronous context managers (using @asynccontextmanager)

    If a dependency returns a context manager, it will be entered and exited around
    the task, giving an opportunity to control the lifetime of a resource.

    **Important**: Synchronous dependencies should NOT include blocking I/O operations
    (file access, network calls, database queries, etc.). Use async dependencies for
    any I/O. Sync dependencies are best for:
    - Pure computations
    - In-memory data structure access
    - Configuration lookups from memory
    - Non-blocking transformations

    Examples:

    ```python
    # Sync dependency - pure computation, no I/O
    def get_config() -> dict:
        # Access in-memory config, no I/O
        return {"api_url": "https://api.example.com", "timeout": 30}

    # Sync dependency - compute value from arguments
    def build_query_params(
        user_id: int = TaskArgument(),
        config: dict = Depends(get_config)
    ) -> dict:
        # Pure computation, no I/O
        return {"user_id": user_id, "timeout": config["timeout"]}

    # Async dependency - I/O operations
    async def get_user(user_id: int = TaskArgument()) -> User:
        # Network I/O - must be async
        return await fetch_user_from_api(user_id)

    # Async context manager - I/O resource management
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def get_db_connection():
        # I/O operations - must be async
        conn = await db.connect()
        try:
            yield conn
        finally:
            await conn.close()

    @task
    async def my_task(
        params: dict = Depends(build_query_params),
        user: User = Depends(get_user),
        db: Connection = Depends(get_db_connection),
    ) -> None:
        await db.execute("UPDATE users SET ...", params)
    ```
    """
    return cast(R, _Depends(dependency))


class ConcurrencyLimit(Dependency):
    """Configures concurrency limits for a task based on specific argument values.

    This allows fine-grained control over task execution by limiting concurrent
    tasks based on the value of specific arguments.

    Example:

    ```python
    async def process_customer(
        customer_id: int,
        concurrency: ConcurrencyLimit = ConcurrencyLimit("customer_id", max_concurrent=1)
    ) -> None:
        # Only one task per customer_id will run at a time
        ...

    async def backup_db(
        db_name: str,
        concurrency: ConcurrencyLimit = ConcurrencyLimit("db_name", max_concurrent=3)
    ) -> None:
        # Only 3 backup tasks per database name will run at a time
        ...
    ```
    """

    single: bool = True

    def __init__(
        self, argument_name: str, max_concurrent: int = 1, scope: str | None = None
    ) -> None:
        """
        Args:
            argument_name: The name of the task argument to use for concurrency grouping
            max_concurrent: Maximum number of concurrent tasks per unique argument value
            scope: Optional scope prefix for Redis keys (defaults to docket name)
        """
        self.argument_name = argument_name
        self.max_concurrent = max_concurrent
        self.scope = scope
        self._concurrency_key: str | None = None
        self._initialized: bool = False

    async def __aenter__(self) -> "ConcurrencyLimit":
        execution = self.execution.get()
        docket = self.docket.get()

        # Get the argument value to group by
        try:
            argument_value = execution.get_argument(self.argument_name)
        except KeyError:
            # If argument not found, create a bypass limit that doesn't apply concurrency control
            limit = ConcurrencyLimit(
                self.argument_name, self.max_concurrent, self.scope
            )
            limit._concurrency_key = None  # Special marker for bypassed concurrency
            limit._initialized = True  # Mark as initialized but bypassed
            return limit

        # Create a concurrency key for this specific argument value
        scope = self.scope or docket.name
        self._concurrency_key = (
            f"{scope}:concurrency:{self.argument_name}:{argument_value}"
        )

        limit = ConcurrencyLimit(self.argument_name, self.max_concurrent, self.scope)
        limit._concurrency_key = self._concurrency_key
        limit._initialized = True  # Mark as initialized
        return limit

    @property
    def concurrency_key(self) -> str | None:
        """Redis key used for tracking concurrency for this specific argument value.
        Returns None when concurrency control is bypassed due to missing arguments.
        Raises RuntimeError if accessed before initialization."""
        if not self._initialized:
            raise RuntimeError(
                "ConcurrencyLimit not initialized - use within task context"
            )
        return self._concurrency_key

    @property
    def is_bypassed(self) -> bool:
        """Returns True if concurrency control is bypassed due to missing arguments."""
        return self._initialized and self._concurrency_key is None


D = TypeVar("D", bound=Dependency)


def get_single_dependency_parameter_of_type(
    function: TaskFunction, dependency_type: type[D]
) -> D | None:
    assert dependency_type.single, "Dependency must be single"
    for _, dependency in get_dependency_parameters(function).items():
        if isinstance(dependency, dependency_type):
            return dependency
    return None


def get_single_dependency_of_type(
    dependencies: dict[str, Dependency], dependency_type: type[D]
) -> D | None:
    assert dependency_type.single, "Dependency must be single"
    for _, dependency in dependencies.items():
        if isinstance(dependency, dependency_type):
            return dependency
    return None


def validate_dependencies(function: TaskFunction) -> None:
    parameters = get_dependency_parameters(function)

    counts = Counter(type(dependency) for dependency in parameters.values())

    for dependency_type, count in counts.items():
        if dependency_type.single and count > 1:
            raise ValueError(
                f"Only one {dependency_type.__name__} dependency is allowed per task"
            )


class FailedDependency:
    def __init__(self, parameter: str, error: Exception) -> None:
        self.parameter = parameter
        self.error = error


@asynccontextmanager
async def resolved_dependencies(
    worker: "Worker", execution: Execution
) -> AsyncGenerator[dict[str, Any], None]:
    # Capture tokens for all contextvar sets to ensure proper cleanup
    docket_token = Dependency.docket.set(worker.docket)
    worker_token = Dependency.worker.set(worker)
    execution_token = Dependency.execution.set(execution)
    cache_token = _Depends.cache.set({})

    try:
        async with AsyncExitStack() as stack:
            stack_token = _Depends.stack.set(stack)
            try:
                arguments: dict[str, Any] = {}

                parameters = get_dependency_parameters(execution.function)
                for parameter, dependency in parameters.items():
                    kwargs = execution.kwargs
                    if parameter in kwargs:
                        arguments[parameter] = kwargs[parameter]
                        continue

                    # Special case for TaskArguments, they are "magical" and infer the parameter
                    # they refer to from the parameter name (unless otherwise specified).  At
                    # the top-level task function call, it doesn't make sense to specify one
                    # _without_ a parameter name, so we'll call that a failed dependency.
                    if (
                        isinstance(dependency, _TaskArgument)
                        and not dependency.parameter
                    ):
                        arguments[parameter] = FailedDependency(
                            parameter, ValueError("No parameter name specified")
                        )
                        continue

                    try:
                        arguments[parameter] = await stack.enter_async_context(
                            dependency
                        )
                    except Exception as error:
                        arguments[parameter] = FailedDependency(parameter, error)

                yield arguments
            finally:
                _Depends.stack.reset(stack_token)
    finally:
        _Depends.cache.reset(cache_token)
        Dependency.execution.reset(execution_token)
        Dependency.worker.reset(worker_token)
        Dependency.docket.reset(docket_token)
