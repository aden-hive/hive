"""Testing utilities for making assertions about scheduled tasks.

Example usage:
    from docket import Docket, testing

    docket = Docket("redis://localhost:6379/0")

    # Schedule a task
    await docket.add(my_task)("arg1", kwarg1="value1")

    # Assert it's scheduled
    await testing.assert_task_scheduled(docket, my_task, args=("arg1",))

    # After completion
    await worker.run_until_finished()
    await testing.assert_no_tasks(docket)
"""

from collections.abc import Callable
from typing import Any

from docket.docket import Docket
from docket.execution import Execution


def _matches_criteria(
    execution: Execution,
    function: str | Callable[..., Any],
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    key: str | None,
) -> bool:
    """Check if an execution matches the given criteria."""
    # Check function name
    function_name = function if isinstance(function, str) else function.__name__
    if execution.function_name != function_name:
        return False

    # Check key if specified
    if key is not None and execution.key != key:
        return False

    # Check args if specified
    if args is not None and execution.args != args:
        return False

    # Check kwargs if specified (subset matching)
    if kwargs is not None:
        for k, v in kwargs.items():
            if k not in execution.kwargs or execution.kwargs[k] != v:
                return False

    return True


def _format_criteria(
    function: str | Callable[..., Any],
    args: tuple[Any, ...] | None,
    kwargs: dict[str, Any] | None,
    key: str | None,
) -> str:
    """Format criteria for error messages."""
    parts: list[str] = []

    function_name = function if isinstance(function, str) else function.__name__
    parts.append(f"function={function_name}")

    if key is not None:
        parts.append(f"key={key!r}")
    if args is not None:
        parts.append(f"args={args!r}")
    if kwargs is not None:
        parts.append(f"kwargs={kwargs!r}")

    return ", ".join(parts)


async def assert_task_scheduled(
    docket: Docket,
    function: str | Callable[..., Any],
    *,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    key: str | None = None,
) -> None:
    """Assert that a task matching the criteria is scheduled.

    Args:
        docket: The Docket instance to check
        function: The task function or function name (string)
        args: Optional tuple of positional arguments to match
        kwargs: Optional dict of keyword arguments to match (subset matching)
        key: Optional task key to match

    Raises:
        AssertionError: If no matching task is found

    Example:
        await assert_task_scheduled(docket, my_task)
        await assert_task_scheduled(docket, my_task, args=("foo",))
        await assert_task_scheduled(docket, "my_task", key="task-123")
    """
    snapshot = await docket.snapshot()

    # Check all scheduled tasks (both immediate and future)
    all_tasks = list(snapshot.future)

    for execution in all_tasks:
        if _matches_criteria(execution, function, args, kwargs, key):
            return

    # Build error message
    criteria = _format_criteria(function, args, kwargs, key)
    function_name = function if isinstance(function, str) else function.__name__

    if not all_tasks:
        raise AssertionError(
            f"Task {function_name} not found: no tasks scheduled on docket"
        )

    # Show what we found instead
    found_tasks = [
        f"  - {e.function_name}(args={e.args!r}, kwargs={e.kwargs!r}, key={e.key!r})"
        for e in all_tasks
    ]
    found_str = "\n".join(found_tasks)

    raise AssertionError(
        f"Task {function_name} not found with {criteria}\n\n"
        f"Scheduled tasks:\n{found_str}"
    )


async def assert_task_not_scheduled(
    docket: Docket,
    function: str | Callable[..., Any],
    *,
    args: tuple[Any, ...] | None = None,
    kwargs: dict[str, Any] | None = None,
    key: str | None = None,
) -> None:
    """Assert that no task matching the criteria is scheduled.

    Args:
        docket: The Docket instance to check
        function: The task function or function name (string)
        args: Optional tuple of positional arguments to match
        kwargs: Optional dict of keyword arguments to match (subset matching)
        key: Optional task key to match

    Raises:
        AssertionError: If a matching task is found

    Example:
        await assert_task_not_scheduled(docket, my_task)
        await assert_task_not_scheduled(docket, my_task, args=("foo",))
    """
    snapshot = await docket.snapshot()

    # Check all scheduled tasks (both immediate and future)
    all_tasks = list(snapshot.future)

    for execution in all_tasks:
        if _matches_criteria(execution, function, args, kwargs, key):
            function_name = function if isinstance(function, str) else function.__name__
            raise AssertionError(
                f"Task {function_name} found but should not be scheduled\n"
                f"Found: {execution.function_name}(args={execution.args!r}, "
                f"kwargs={execution.kwargs!r}, key={execution.key!r})"
            )


async def assert_task_count(
    docket: Docket,
    function: str | Callable[..., Any] | None = None,
    *,
    count: int,
) -> None:
    """Assert the number of scheduled tasks matches the expected count.

    Args:
        docket: The Docket instance to check
        function: Optional task function or name to count (if None, counts all tasks)
        count: Expected number of tasks

    Raises:
        AssertionError: If the count doesn't match

    Example:
        await assert_task_count(docket, count=5)  # All tasks
        await assert_task_count(docket, my_task, count=2)  # Specific function
    """
    snapshot = await docket.snapshot()

    # Check all scheduled tasks (both immediate and future)
    all_tasks = list(snapshot.future)

    if function is None:
        actual_count = len(all_tasks)
        function_desc = "all tasks"
    else:
        function_name = function if isinstance(function, str) else function.__name__
        actual_count = sum(1 for e in all_tasks if e.function_name == function_name)
        function_desc = f"tasks for {function_name}"

    if actual_count != count:
        raise AssertionError(f"Expected {count} {function_desc}, found {actual_count}")


async def assert_no_tasks(docket: Docket) -> None:
    """Assert that no tasks are scheduled on the docket.

    Args:
        docket: The Docket instance to check

    Raises:
        AssertionError: If any tasks are scheduled

    Example:
        await assert_no_tasks(docket)
    """
    snapshot = await docket.snapshot()

    # Check all scheduled tasks (both immediate and future)
    all_tasks = list(snapshot.future)

    if all_tasks:
        found_tasks = [
            f"  - {e.function_name}(args={e.args!r}, kwargs={e.kwargs!r}, key={e.key!r})"
            for e in all_tasks
        ]
        found_str = "\n".join(found_tasks)
        raise AssertionError(
            f"Expected no tasks, found {len(all_tasks)} task(s) scheduled:\n{found_str}"
        )
