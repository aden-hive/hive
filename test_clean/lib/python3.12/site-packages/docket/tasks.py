import asyncio
import logging
from datetime import datetime, timezone

from .dependencies import (
    CurrentDocket,
    CurrentExecution,
    CurrentWorker,
    Retry,
    TaskLogger,
)
from .docket import Docket, TaskCollection
from .execution import Execution
from .worker import Worker


async def trace(
    message: str,
    logger: "logging.LoggerAdapter[logging.Logger]" = TaskLogger(),
    docket: Docket = CurrentDocket(),
    worker: Worker = CurrentWorker(),
    execution: Execution = CurrentExecution(),
) -> None:
    logger.info(
        "%s: %r added to docket %r %s ago now running on worker %r",
        message,
        execution.key,
        docket.name,
        (datetime.now(timezone.utc) - execution.when),
        worker.name,
    )


async def fail(
    message: str,
    docket: Docket = CurrentDocket(),
    worker: Worker = CurrentWorker(),
    execution: Execution = CurrentExecution(),
    retry: Retry = Retry(attempts=2),
) -> None:
    raise Exception(
        f"{message}: {execution.key} added to docket "
        f"{docket.name} {datetime.now(timezone.utc) - execution.when} "
        f"ago now running on worker {worker.name}"
    )


async def sleep(
    seconds: float, logger: "logging.LoggerAdapter[logging.Logger]" = TaskLogger()
) -> None:
    logger.info("Sleeping for %s seconds", seconds)
    await asyncio.sleep(seconds)


standard_tasks: TaskCollection = [
    trace,
    fail,
    sleep,
]
