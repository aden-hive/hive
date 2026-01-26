import asyncio
import enum
import importlib
import logging
import os
import socket
import sys
import time
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Annotated, Any, AsyncIterator, Collection

import typer
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.progress import (
    BarColumn,
    Progress,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
    TaskID,
)
from rich.table import Table

from . import __version__, tasks
from .docket import Docket, DocketSnapshot, WorkerInfo
from .execution import ExecutionState
from .strikelist import Operator
from .worker import Worker


async def iterate_with_timeout(
    iterator: AsyncIterator[dict[str, Any]], timeout: float
) -> AsyncIterator[dict[str, Any] | None]:
    """Iterate over an async iterator with timeout, ensuring proper cleanup.

    Wraps an async iterator to add timeout support and guaranteed cleanup.
    On timeout, yields None to allow the caller to handle polling fallback.

    Args:
        iterator: An async iterator (must have __anext__ and aclose methods)
        timeout: Timeout in seconds for each iteration

    Yields:
        Items from the iterator, or None if timeout expires
    """
    try:
        while True:
            try:
                yield await asyncio.wait_for(iterator.__anext__(), timeout=timeout)
            except asyncio.TimeoutError:
                # Yield None to signal timeout, allowing caller to handle polling
                yield None
            except StopAsyncIteration:
                break
    finally:
        await iterator.aclose()


app: typer.Typer = typer.Typer(
    help="Docket - A distributed background task system for Python functions",
    add_completion=True,
    no_args_is_help=True,
)


class LogLevel(str, enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class LogFormat(str, enum.Enum):
    RICH = "rich"
    PLAIN = "plain"
    JSON = "json"


def local_time(when: datetime) -> str:
    return when.astimezone().strftime("%Y-%m-%d %H:%M:%S %z")


def default_worker_name() -> str:
    return f"{socket.gethostname()}#{os.getpid()}"


def duration(duration_str: str | timedelta) -> timedelta:
    """
    Parse a duration string into a timedelta.

    Supported formats:
    - 123 = 123 seconds
    - 123s = 123 seconds
    - 123m = 123 minutes
    - 123h = 123 hours
    - 00:00 = mm:ss
    - 00:00:00 = hh:mm:ss
    """
    if isinstance(duration_str, timedelta):
        return duration_str

    if ":" in duration_str:
        parts = duration_str.split(":")
        if len(parts) == 2:  # mm:ss
            minutes, seconds = map(int, parts)
            return timedelta(minutes=minutes, seconds=seconds)
        elif len(parts) == 3:  # hh:mm:ss
            hours, minutes, seconds = map(int, parts)
            return timedelta(hours=hours, minutes=minutes, seconds=seconds)
        else:
            raise ValueError(f"Invalid duration string: {duration_str}")
    elif duration_str.endswith("s"):
        return timedelta(seconds=int(duration_str[:-1]))
    elif duration_str.endswith("m"):
        return timedelta(minutes=int(duration_str[:-1]))
    elif duration_str.endswith("h"):
        return timedelta(hours=int(duration_str[:-1]))
    else:
        return timedelta(seconds=int(duration_str))


def set_logging_format(format: LogFormat) -> None:
    root_logger = logging.getLogger()
    if format == LogFormat.JSON:
        from pythonjsonlogger.json import JsonFormatter

        formatter = JsonFormatter(
            "{name}{asctime}{levelname}{message}{exc_info}", style="{"
        )
        handler = logging.StreamHandler(stream=sys.stdout)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    elif format == LogFormat.PLAIN:
        handler = logging.StreamHandler(stream=sys.stdout)
        formatter = logging.Formatter(
            "[%(asctime)s] %(levelname)s - %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    else:
        from rich.logging import RichHandler

        handler = RichHandler()
        formatter = logging.Formatter("%(message)s", datefmt="[%X]")
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)


def set_logging_level(level: LogLevel) -> None:
    logging.getLogger().setLevel(level.value)


def validate_url(url: str) -> str:
    """
    Validate that the provided URL is compatible with the CLI.

    The memory:// backend is not compatible with the CLI as it doesn't persist
    across processes.
    """
    if url.startswith("memory://"):
        raise typer.BadParameter(
            "The memory:// URL scheme is not supported by the CLI.\n"
            "The memory backend does not persist across processes.\n"
            "Please use a persistent backend like Redis or Valkey."
        )
    return url


def handle_strike_wildcard(value: str) -> str | None:
    if value in ("", "*"):
        return None
    return value


def interpret_python_value(value: str | None) -> Any:
    if value is None:
        return None

    type, _, value = value.rpartition(":")
    if not type:
        # without a type hint, we assume the value is a string
        return value

    module_name, _, member_name = type.rpartition(".")
    module = importlib.import_module(module_name or "builtins")
    member = getattr(module, member_name)

    # special cases for common useful types
    if member is timedelta:
        return timedelta(seconds=int(value))
    elif member is bool:
        return value.lower() == "true"
    else:
        return member(value)


@app.command(
    help="Print the version of docket",
)
def version() -> None:
    print(__version__)


@app.command(
    help="Start a worker to process tasks",
)
def worker(
    tasks: Annotated[
        list[str],
        typer.Option(
            "--tasks",
            help=(
                "The dotted path of a task collection to register with the docket. "
                "This can be specified multiple times.  A task collection is any "
                "iterable of async functions."
            ),
            envvar="DOCKET_TASKS",
        ),
    ] = ["docket.tasks:standard_tasks"],
    docket_: Annotated[
        str,
        typer.Option(
            "--docket",
            help="The name of the docket",
            envvar="DOCKET_NAME",
        ),
    ] = "docket",
    url: Annotated[
        str,
        typer.Option(
            help="The URL of the Redis server",
            envvar="DOCKET_URL",
        ),
    ] = "redis://localhost:6379/0",
    name: Annotated[
        str | None,
        typer.Option(
            help="The name of the worker",
            envvar="DOCKET_WORKER_NAME",
        ),
    ] = default_worker_name(),
    logging_level: Annotated[
        LogLevel,
        typer.Option(
            help="The logging level",
            envvar="DOCKET_LOGGING_LEVEL",
            callback=set_logging_level,
        ),
    ] = LogLevel.INFO,
    logging_format: Annotated[
        LogFormat,
        typer.Option(
            help="The logging format",
            envvar="DOCKET_LOGGING_FORMAT",
            callback=set_logging_format,
        ),
    ] = LogFormat.RICH if sys.stdout.isatty() else LogFormat.PLAIN,
    concurrency: Annotated[
        int,
        typer.Option(
            help="The maximum number of tasks to process concurrently",
            envvar="DOCKET_WORKER_CONCURRENCY",
        ),
    ] = 10,
    redelivery_timeout: Annotated[
        timedelta,
        typer.Option(
            parser=duration,
            help="How long to wait before redelivering a task to another worker",
            envvar="DOCKET_WORKER_REDELIVERY_TIMEOUT",
        ),
    ] = timedelta(minutes=5),
    reconnection_delay: Annotated[
        timedelta,
        typer.Option(
            parser=duration,
            help=(
                "How long to wait before reconnecting to the Redis server after "
                "a connection error"
            ),
            envvar="DOCKET_WORKER_RECONNECTION_DELAY",
        ),
    ] = timedelta(seconds=5),
    minimum_check_interval: Annotated[
        timedelta,
        typer.Option(
            parser=duration,
            help="The minimum interval to check for tasks",
            envvar="DOCKET_WORKER_MINIMUM_CHECK_INTERVAL",
        ),
    ] = timedelta(milliseconds=100),
    scheduling_resolution: Annotated[
        timedelta,
        typer.Option(
            parser=duration,
            help="How frequently to check for future tasks to be scheduled",
            envvar="DOCKET_WORKER_SCHEDULING_RESOLUTION",
        ),
    ] = timedelta(milliseconds=250),
    schedule_automatic_tasks: Annotated[
        bool,
        typer.Option(
            "--schedule-automatic-tasks",
            help="Schedule automatic tasks",
        ),
    ] = True,
    enable_internal_instrumentation: Annotated[
        bool,
        typer.Option(
            "--enable-internal-instrumentation/--no-enable-internal-instrumentation",
            help="Enable OpenTelemetry spans for internal Redis polling operations",
            envvar="DOCKET_WORKER_ENABLE_INTERNAL_INSTRUMENTATION",
        ),
    ] = False,
    until_finished: Annotated[
        bool,
        typer.Option(
            "--until-finished",
            help="Exit after the current docket is finished",
        ),
    ] = False,
    healthcheck_port: Annotated[
        int | None,
        typer.Option(
            "--healthcheck-port",
            help="The port to serve a healthcheck on",
            envvar="DOCKET_WORKER_HEALTHCHECK_PORT",
        ),
    ] = None,
    metrics_port: Annotated[
        int | None,
        typer.Option(
            "--metrics-port",
            help="The port to serve Prometheus metrics on",
            envvar="DOCKET_WORKER_METRICS_PORT",
        ),
    ] = None,
    fallback_task: Annotated[
        str | None,
        typer.Option(
            "--fallback-task",
            help=(
                "Dotted path to a fallback task for unknown functions "
                "(e.g., myapp.tasks:my_fallback). Receives original args/kwargs "
                "and supports full dependency injection."
            ),
            envvar="DOCKET_FALLBACK_TASK",
        ),
    ] = None,
) -> None:
    asyncio.run(
        Worker.run(
            docket_name=docket_,
            url=url,
            name=name,
            concurrency=concurrency,
            redelivery_timeout=redelivery_timeout,
            reconnection_delay=reconnection_delay,
            minimum_check_interval=minimum_check_interval,
            scheduling_resolution=scheduling_resolution,
            schedule_automatic_tasks=schedule_automatic_tasks,
            enable_internal_instrumentation=enable_internal_instrumentation,
            until_finished=until_finished,
            healthcheck_port=healthcheck_port,
            metrics_port=metrics_port,
            tasks=tasks,
            fallback_task=fallback_task,
        )
    )


@app.command(help="Strikes a task or parameters from the docket")
def strike(
    function: Annotated[
        str,
        typer.Argument(
            help="The function to strike",
            callback=handle_strike_wildcard,
        ),
    ] = "*",
    parameter: Annotated[
        str,
        typer.Argument(
            help="The parameter to strike",
            callback=handle_strike_wildcard,
        ),
    ] = "*",
    operator: Annotated[
        Operator,
        typer.Argument(
            help="The operator to compare the value against",
        ),
    ] = Operator.EQUAL,
    value: Annotated[
        str | None,
        typer.Argument(
            help="The value to strike from the docket",
        ),
    ] = None,
    docket_: Annotated[
        str,
        typer.Option(
            "--docket",
            help="The name of the docket",
            envvar="DOCKET_NAME",
        ),
    ] = "docket",
    url: Annotated[
        str,
        typer.Option(
            help="The URL of the Redis server",
            envvar="DOCKET_URL",
            callback=validate_url,
        ),
    ] = "redis://localhost:6379/0",
) -> None:
    if not function and not parameter:
        raise typer.BadParameter(
            message="Must provide either a function and/or a parameter",
        )

    value_ = interpret_python_value(value)
    if parameter:
        function_name = f"{function or '(all tasks)'}"
        print(f"Striking {function_name} {parameter} {operator.value} {value_!r}")
    else:
        print(f"Striking {function}")

    async def run() -> None:
        async with Docket(name=docket_, url=url) as docket:
            await docket.strike(function, parameter, operator, value_)

    asyncio.run(run())


@app.command(help="Clear all queued and scheduled tasks from the docket")
def clear(
    docket_: Annotated[
        str,
        typer.Option(
            "--docket",
            help="The name of the docket",
            envvar="DOCKET_NAME",
        ),
    ] = "docket",
    url: Annotated[
        str,
        typer.Option(
            help="The URL of the Redis server",
            envvar="DOCKET_URL",
            callback=validate_url,
        ),
    ] = "redis://localhost:6379/0",
) -> None:
    async def run() -> None:
        async with Docket(name=docket_, url=url) as docket:
            cleared_count = await docket.clear()
            print(f"Cleared {cleared_count} tasks from docket '{docket_}'")

    asyncio.run(run())


@app.command(help="Restores a task or parameters to the Docket")
def restore(
    function: Annotated[
        str,
        typer.Argument(
            help="The function to restore",
            callback=handle_strike_wildcard,
        ),
    ] = "*",
    parameter: Annotated[
        str,
        typer.Argument(
            help="The parameter to restore",
            callback=handle_strike_wildcard,
        ),
    ] = "*",
    operator: Annotated[
        Operator,
        typer.Argument(
            help="The operator to compare the value against",
        ),
    ] = Operator.EQUAL,
    value: Annotated[
        str | None,
        typer.Argument(
            help="The value to restore to the docket",
        ),
    ] = None,
    docket_: Annotated[
        str,
        typer.Option(
            "--docket",
            help="The name of the docket",
            envvar="DOCKET_NAME",
        ),
    ] = "docket",
    url: Annotated[
        str,
        typer.Option(
            help="The URL of the Redis server",
            envvar="DOCKET_URL",
            callback=validate_url,
        ),
    ] = "redis://localhost:6379/0",
) -> None:
    if not function and not parameter:
        raise typer.BadParameter(
            message="Must provide either a function and/or a parameter",
        )

    value_ = interpret_python_value(value)
    if parameter:
        function_name = f"{function or '(all tasks)'}"
        print(f"Restoring {function_name} {parameter} {operator.value} {value_!r}")
    else:
        print(f"Restoring {function}")

    async def run() -> None:
        async with Docket(name=docket_, url=url) as docket:
            await docket.restore(function, parameter, operator, value_)

    asyncio.run(run())


tasks_app: typer.Typer = typer.Typer(
    help="Run docket's built-in tasks", no_args_is_help=True
)
app.add_typer(tasks_app, name="tasks")


@tasks_app.command(help="Adds a trace task to the Docket")
def trace(
    docket_: Annotated[
        str,
        typer.Option(
            "--docket",
            help="The name of the docket",
            envvar="DOCKET_NAME",
        ),
    ] = "docket",
    url: Annotated[
        str,
        typer.Option(
            help="The URL of the Redis server",
            envvar="DOCKET_URL",
            callback=validate_url,
        ),
    ] = "redis://localhost:6379/0",
    message: Annotated[
        str,
        typer.Argument(
            help="The message to print",
        ),
    ] = "Howdy!",
    delay: Annotated[
        timedelta,
        typer.Option(
            parser=duration,
            help="The delay before the task is added to the docket",
        ),
    ] = timedelta(seconds=0),
) -> None:
    async def run() -> None:
        async with Docket(name=docket_, url=url) as docket:
            when = datetime.now(timezone.utc) + delay
            execution = await docket.add(tasks.trace, when)(message)
            print(f"Added trace task {execution.key!r} to the docket {docket.name!r}")

    asyncio.run(run())


@tasks_app.command(help="Adds a fail task to the Docket")
def fail(
    docket_: Annotated[
        str,
        typer.Option(
            "--docket",
            help="The name of the docket",
            envvar="DOCKET_NAME",
        ),
    ] = "docket",
    url: Annotated[
        str,
        typer.Option(
            help="The URL of the Redis server",
            envvar="DOCKET_URL",
            callback=validate_url,
        ),
    ] = "redis://localhost:6379/0",
    message: Annotated[
        str,
        typer.Argument(
            help="The message to print",
        ),
    ] = "Howdy!",
    delay: Annotated[
        timedelta,
        typer.Option(
            parser=duration,
            help="The delay before the task is added to the docket",
        ),
    ] = timedelta(seconds=0),
) -> None:
    async def run() -> None:
        async with Docket(name=docket_, url=url) as docket:
            when = datetime.now(timezone.utc) + delay
            execution = await docket.add(tasks.fail, when)(message)
            print(f"Added fail task {execution.key!r} to the docket {docket.name!r}")

    asyncio.run(run())


@tasks_app.command(help="Adds a sleep task to the Docket")
def sleep(
    docket_: Annotated[
        str,
        typer.Option(
            "--docket",
            help="The name of the docket",
            envvar="DOCKET_NAME",
        ),
    ] = "docket",
    url: Annotated[
        str,
        typer.Option(
            help="The URL of the Redis server",
            envvar="DOCKET_URL",
            callback=validate_url,
        ),
    ] = "redis://localhost:6379/0",
    seconds: Annotated[
        float,
        typer.Argument(
            help="The number of seconds to sleep",
        ),
    ] = 1,
    delay: Annotated[
        timedelta,
        typer.Option(
            parser=duration,
            help="The delay before the task is added to the docket",
        ),
    ] = timedelta(seconds=0),
) -> None:
    async def run() -> None:
        async with Docket(name=docket_, url=url) as docket:
            when = datetime.now(timezone.utc) + delay
            execution = await docket.add(tasks.sleep, when)(seconds)
            print(f"Added sleep task {execution.key!r} to the docket {docket.name!r}")

    asyncio.run(run())


def relative_time(now: datetime, when: datetime) -> str:
    delta = now - when
    if delta < -timedelta(minutes=30):
        return f"at {local_time(when)}"
    elif delta < timedelta(0):
        return f"in {-delta}"
    elif delta < timedelta(minutes=30):
        return f"{delta} ago"
    else:
        return f"at {local_time(when)}"


def get_task_stats(
    snapshot: DocketSnapshot,
) -> dict[str, dict[str, int | datetime | None]]:
    """Get task count statistics by function name with timestamp data."""
    stats: dict[str, dict[str, int | datetime | None]] = {}

    # Count running tasks by function
    for execution in snapshot.running:
        func_name = execution.function_name
        if func_name not in stats:
            stats[func_name] = {
                "running": 0,
                "queued": 0,
                "total": 0,
                "oldest_queued": None,
                "latest_queued": None,
                "oldest_started": None,
                "latest_started": None,
            }
        stats[func_name]["running"] += 1
        stats[func_name]["total"] += 1

        # Track oldest/latest started times for running tasks
        started = execution.started
        if (
            stats[func_name]["oldest_started"] is None
            or started < stats[func_name]["oldest_started"]
        ):
            stats[func_name]["oldest_started"] = started
        if (
            stats[func_name]["latest_started"] is None
            or started > stats[func_name]["latest_started"]
        ):
            stats[func_name]["latest_started"] = started

    # Count future tasks by function
    for execution in snapshot.future:
        func_name = execution.function_name
        if func_name not in stats:
            stats[func_name] = {
                "running": 0,
                "queued": 0,
                "total": 0,
                "oldest_queued": None,
                "latest_queued": None,
                "oldest_started": None,
                "latest_started": None,
            }
        stats[func_name]["queued"] += 1
        stats[func_name]["total"] += 1

        # Track oldest/latest queued times for future tasks
        when = execution.when
        if (
            stats[func_name]["oldest_queued"] is None
            or when < stats[func_name]["oldest_queued"]
        ):
            stats[func_name]["oldest_queued"] = when
        if (
            stats[func_name]["latest_queued"] is None
            or when > stats[func_name]["latest_queued"]
        ):
            stats[func_name]["latest_queued"] = when

    return stats


@app.command(help="Shows a snapshot of what's on the docket right now")
def snapshot(
    tasks: Annotated[
        list[str],
        typer.Option(
            "--tasks",
            help=(
                "The dotted path of a task collection to register with the docket. "
                "This can be specified multiple times.  A task collection is any "
                "iterable of async functions."
            ),
            envvar="DOCKET_TASKS",
        ),
    ] = ["docket.tasks:standard_tasks"],
    docket_: Annotated[
        str,
        typer.Option(
            "--docket",
            help="The name of the docket",
            envvar="DOCKET_NAME",
        ),
    ] = "docket",
    url: Annotated[
        str,
        typer.Option(
            help="The URL of the Redis server",
            envvar="DOCKET_URL",
            callback=validate_url,
        ),
    ] = "redis://localhost:6379/0",
    stats: Annotated[
        bool,
        typer.Option(
            "--stats",
            help="Show task count statistics by function name",
        ),
    ] = False,
) -> None:
    async def run() -> DocketSnapshot:
        async with Docket(name=docket_, url=url) as docket:
            for task_path in tasks:
                docket.register_collection(task_path)

            return await docket.snapshot()

    snapshot = asyncio.run(run())

    relative = partial(relative_time, snapshot.taken)

    console = Console()

    summary_lines = [
        f"Docket: {docket_!r}",
        f"as of {local_time(snapshot.taken)}",
        (
            f"{len(snapshot.workers)} workers, "
            f"{len(snapshot.running)}/{snapshot.total_tasks} running"
        ),
    ]
    table = Table(title="\n".join(summary_lines))
    table.add_column("When", style="green")
    table.add_column("Function", style="cyan")
    table.add_column("Key", style="cyan")
    table.add_column("Worker", style="yellow")
    table.add_column("Started", style="green")

    for execution in snapshot.running:
        table.add_row(
            relative(execution.when),
            execution.function_name,
            execution.key,
            execution.worker,
            relative(execution.started),
        )

    for execution in snapshot.future:
        table.add_row(
            relative(execution.when),
            execution.function_name,
            execution.key,
            "",
            "",
        )

    console.print(table)

    # Display task statistics if requested. On Linux the Click runner executes
    # this CLI in a subprocess, so coverage cannot observe it. Mark as no cover.
    if stats:  # pragma: no cover
        task_stats = get_task_stats(snapshot)
        if task_stats:  # pragma: no cover
            console.print()  # Add spacing between tables
            stats_table = Table(title="Task Count Statistics by Function")
            stats_table.add_column("Function", style="cyan")
            stats_table.add_column("Total", style="bold magenta", justify="right")
            stats_table.add_column("Running", style="green", justify="right")
            stats_table.add_column("Queued", style="yellow", justify="right")
            stats_table.add_column("Oldest Queued", style="dim yellow", justify="right")
            stats_table.add_column("Latest Queued", style="dim yellow", justify="right")

            # Sort by total count descending to highlight potential runaway tasks
            for func_name in sorted(
                task_stats.keys(), key=lambda x: task_stats[x]["total"], reverse=True
            ):
                counts = task_stats[func_name]

                # Format timestamp columns
                oldest_queued = ""
                latest_queued = ""
                if counts["oldest_queued"] is not None:
                    oldest_queued = relative(counts["oldest_queued"])
                if counts["latest_queued"] is not None:
                    latest_queued = relative(counts["latest_queued"])

                stats_table.add_row(
                    func_name,
                    str(counts["total"]),
                    str(counts["running"]),
                    str(counts["queued"]),
                    oldest_queued,
                    latest_queued,
                )

            console.print(stats_table)


@app.command(help="Monitor progress of a specific task execution")
def watch(
    key: Annotated[str, typer.Argument(help="The task execution key to monitor")],
    url: Annotated[
        str,
        typer.Option(
            "--url",
            "-u",
            envvar="DOCKET_REDIS_URL",
            help="Redis URL (e.g., redis://localhost:6379/0)",
        ),
    ] = "redis://localhost:6379/0",
    docket_name: Annotated[
        str,
        typer.Option(
            "--docket",
            "-d",
            envvar="DOCKET_NAME",
            help="Docket name",
        ),
    ] = "docket",
) -> None:
    """Monitor the progress of a specific task execution in real-time using event-driven updates."""

    async def monitor() -> None:
        async with Docket(docket_name, url) as docket:
            execution = await docket.get_execution(key)
            if not execution:
                console = Console()
                console.print(
                    f"[red]Error:[/red] Task with key '{key}' not found or function not registered",
                    style="bold",
                )
                return

            console = Console()

            # State colors for display
            state_colors = {
                ExecutionState.SCHEDULED: "yellow",
                ExecutionState.QUEUED: "cyan",
                ExecutionState.RUNNING: "blue",
                ExecutionState.COMPLETED: "green",
                ExecutionState.FAILED: "red",
            }

            # Load initial snapshot
            await execution.sync()

            # Track current state for display
            current_state = execution.state
            worker_name: str | None = execution.worker
            error_message: str | None = execution.error

            # Initialize progress values
            current_val = (
                execution.progress.current
                if execution.progress.current is not None
                else 0
            )
            total_val = execution.progress.total
            progress_message = execution.progress.message

            active_progress = Progress(
                TextColumn("[bold blue]{task.description}"),
                BarColumn(bar_width=None),  # Auto width
                TaskProgressColumn(),
                TimeElapsedColumn(),
                expand=True,
            )

            progress_task_id = None

            def set_progress_start_time(task_id: TaskID, started_at: datetime) -> None:
                """Set progress bar start time based on execution start time."""
                elapsed_since_start = datetime.now(timezone.utc) - started_at
                monotonic_start = time.monotonic() - elapsed_since_start.total_seconds()
                active_progress.tasks[task_id].start_time = monotonic_start

            # Initialize progress task if we have progress data
            if current_val > 0 and total_val > 0:
                progress_task_id = active_progress.add_task(  # pragma: no cover
                    progress_message or "Processing...",
                    total=total_val,
                    completed=current_val,
                )
                # Set start time based on execution.started_at if available
                if execution.started_at is not None:  # pragma: no cover
                    set_progress_start_time(progress_task_id, execution.started_at)

            def create_display_layout() -> Layout:
                """Create the layout for watch display."""
                layout = Layout()

                # Build info lines
                info_lines = [
                    f"[bold]Task:[/bold] {key}",
                    f"[bold]Docket:[/bold] {docket_name}",
                ]

                # Add state with color
                state_color = state_colors.get(current_state, "white")
                info_lines.append(
                    f"[bold]State:[/bold] [{state_color}]{current_state.value.upper()}[/{state_color}]"
                )

                # Add worker if available
                if worker_name:  # pragma: no branch
                    info_lines.append(f"[bold]Worker:[/bold] {worker_name}")

                # Add error if failed
                if error_message:
                    info_lines.append(f"[red bold]Error:[/red bold] {error_message}")

                # Add completion status
                if current_state == ExecutionState.COMPLETED:
                    info_lines.append(
                        "[green bold]✓ Task completed successfully[/green bold]"
                    )
                elif current_state == ExecutionState.FAILED:
                    info_lines.append("[red bold]✗ Task failed[/red bold]")

                info_section = "\n".join(info_lines)

                # Build layout without big gaps
                if progress_task_id is not None:
                    # Choose the right progress instance
                    # Show info and progress together with minimal spacing
                    layout.split_column(
                        Layout(info_section, name="info", size=len(info_lines)),
                        Layout(active_progress, name="progress", size=2),
                    )
                else:
                    # Just show info
                    layout.update(Layout(info_section, name="info"))

                return layout

            # Create initial layout
            layout = create_display_layout()

            # If already in terminal state, display once and exit
            if current_state in (ExecutionState.COMPLETED, ExecutionState.FAILED):
                console.print(layout)
                return

            # Use Live for smooth updates
            with Live(layout, console=console, refresh_per_second=4) as live:
                # Subscribe to events and update display
                # Use polling fallback to handle missed pub/sub events
                poll_interval = 1.0  # Check state every 1 second if no events

                async for event in iterate_with_timeout(
                    execution.subscribe(), poll_interval
                ):  # pragma: no cover
                    if event is None:
                        # Timeout - poll state directly as fallback
                        await execution.sync()
                        if execution.state != current_state:
                            # State changed, create synthetic state event
                            event = {
                                "type": "state",
                                "state": execution.state.value,
                                "worker": execution.worker,
                                "error": execution.error,
                                "started_at": (
                                    execution.started_at.isoformat()
                                    if execution.started_at
                                    else None
                                ),
                            }
                        else:
                            # No state change, continue waiting
                            continue

                    # Process the event (from pub/sub or synthetic from polling)
                    if event["type"] == "state":
                        # Update state information
                        current_state = ExecutionState(event["state"])
                        if worker := event.get("worker"):
                            worker_name = worker
                        if error := event.get("error"):
                            error_message = error
                        if started_at := event.get("started_at"):
                            execution.started_at = datetime.fromisoformat(started_at)
                            # Update progress bar start time if we have a progress task
                            if progress_task_id is not None:
                                set_progress_start_time(
                                    progress_task_id, execution.started_at
                                )

                        # Update layout
                        layout = create_display_layout()
                        live.update(layout)

                        # Exit if terminal state reached
                        if current_state in (
                            ExecutionState.COMPLETED,
                            ExecutionState.FAILED,
                        ):
                            break

                    elif event["type"] == "progress":
                        # Update progress information
                        current_val = event["current"]
                        total_val: int = event.get("total", execution.progress.total)
                        progress_message = event.get(
                            "message", execution.progress.message
                        )

                        # Update or create progress task
                        if total_val > 0 and execution.started_at is not None:
                            if progress_task_id is None:
                                # Create new progress task (first time only)
                                progress_task_id = active_progress.add_task(
                                    progress_message or "Processing...",
                                    total=total_val,
                                    completed=current_val or 0,
                                )
                                # Set start time based on execution.started_at if available
                                if started_at := execution.started_at:
                                    set_progress_start_time(
                                        progress_task_id, execution.started_at
                                    )
                            else:
                                # Update existing progress task
                                active_progress.update(
                                    progress_task_id,
                                    completed=current_val,
                                    total=total_val,
                                    description=progress_message or "Processing...",
                                )

                        # Update layout
                        layout = create_display_layout()
                        live.update(layout)

    asyncio.run(monitor())


workers_app: typer.Typer = typer.Typer(
    help="Look at the workers on a docket", no_args_is_help=True
)
app.add_typer(workers_app, name="workers")


def print_workers(
    docket_name: str,
    workers: Collection[WorkerInfo],
    highlight_task: str | None = None,
) -> None:
    sorted_workers = sorted(workers, key=lambda w: w.last_seen, reverse=True)

    table = Table(title=f"Workers in Docket: {docket_name}")

    table.add_column("Name", style="cyan")
    table.add_column("Last Seen", style="green")
    table.add_column("Tasks", style="yellow")

    now = datetime.now(timezone.utc)

    for worker in sorted_workers:
        time_ago = now - worker.last_seen

        tasks = [
            f"[bold]{task}[/bold]" if task == highlight_task else task
            for task in sorted(worker.tasks)
        ]

        table.add_row(
            worker.name,
            f"{time_ago} ago",
            "\n".join(tasks) if tasks else "(none)",
        )

    console = Console()
    console.print(table)


@workers_app.command(name="ls", help="List all workers on the docket")
def list_workers(
    docket_: Annotated[
        str,
        typer.Option(
            "--docket",
            help="The name of the docket",
            envvar="DOCKET_NAME",
        ),
    ] = "docket",
    url: Annotated[
        str,
        typer.Option(
            help="The URL of the Redis server",
            envvar="DOCKET_URL",
            callback=validate_url,
        ),
    ] = "redis://localhost:6379/0",
) -> None:
    async def run() -> Collection[WorkerInfo]:
        async with Docket(name=docket_, url=url) as docket:
            return await docket.workers()

    workers = asyncio.run(run())

    print_workers(docket_, workers)


@workers_app.command(
    name="for-task",
    help="List the workers on the docket that can process a certain task",
)
def workers_for_task(
    task: Annotated[
        str,
        typer.Argument(
            help="The name of the task",
        ),
    ],
    docket_: Annotated[
        str,
        typer.Option(
            "--docket",
            help="The name of the docket",
            envvar="DOCKET_NAME",
        ),
    ] = "docket",
    url: Annotated[
        str,
        typer.Option(
            help="The URL of the Redis server",
            envvar="DOCKET_URL",
            callback=validate_url,
        ),
    ] = "redis://localhost:6379/0",
) -> None:
    async def run() -> Collection[WorkerInfo]:
        async with Docket(name=docket_, url=url) as docket:
            return await docket.task_workers(task)

    workers = asyncio.run(run())

    print_workers(docket_, workers, highlight_task=task)
