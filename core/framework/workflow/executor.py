"""Workflow executor with retry and circuit breaker."""

import time
import asyncio
from typing import Dict, Any
from .dag import DAG, Task, TaskState


class WorkflowExecutor:
    """Execute workflows with advanced features."""

    def __init__(self, dag: DAG):
        self.dag = dag
        self._task_results: Dict[str, Any] = {}
        self._circuit_breaker_states: Dict[str, Dict] = {}

    async def execute(self, max_concurrency: int = 10) -> Dict[str, Any]:
        """Execute the workflow."""
        while True:
            ready_tasks = self.dag.get_ready_tasks()
            if not ready_tasks:
                if all(
                    t.state in [TaskState.SUCCESS, TaskState.FAILED, TaskState.SKIPPED]
                    for t in self.dag.tasks
                ):
                    break
                await asyncio.sleep(0.1)
                continue

            running_count = sum(
                1 for t in self.dag.tasks if t.state == TaskState.RUNNING
            )
            tasks_to_run = ready_tasks[:max_concurrency - running_count]

            await asyncio.gather(
                *[self._execute_task(task) for task in tasks_to_run],
                return_exceptions=True
            )

        return {
            "dag_id": self.dag.dag_id,
            "tasks": {t.id: t.state for t in self.dag.tasks},
            "results": self._task_results
        }

    async def _execute_task(self, task: Task) -> None:
        """Execute a single task with retry and timeout."""
        task.state = TaskState.RUNNING

        if self._is_circuit_open(task.id):
            task.state = TaskState.FAILED
            task.error = "Circuit breaker is open"
            return

        try:
            result = await asyncio.wait_for(
                self._execute_with_retry(task),
                timeout=task.timeout
            )
            task.result = result
            task.state = TaskState.SUCCESS
            self._task_results[task.id] = result
            self._reset_circuit_breaker(task.id)

        except asyncio.TimeoutError:
            task.state = TaskState.FAILED
            task.error = f"Timeout after {task.timeout}s"
            self._record_circuit_breaker_failure(task.id)

        except Exception as e:
            task.state = TaskState.FAILED
            task.error = str(e)
            self._record_circuit_breaker_failure(task.id)

    async def _execute_with_retry(self, task: Task) -> Any:
        """Execute task with exponential backoff."""
        for attempt in range(task.retries + 1):
            try:
                dep_results = {
                    dep: self._task_results[dep]
                    for dep in task.dependencies
                    if dep in self._task_results
                }
                params = {**task.params, **dep_results}

                if task.func:
                    return await task.func(**params)
                return None

            except Exception as e:
                if attempt < task.retries:
                    delay = task.retry_delay * (task.retry_backoff ** attempt)
                    task.state = TaskState.RETRYING
                    await asyncio.sleep(delay)
                else:
                    raise

    def _is_circuit_open(self, task_id: str) -> bool:
        """Check if circuit breaker is open."""
        state = self._circuit_breaker_states.get(task_id, {})
        failures = state.get("failures", 0)
        last_failure_time = state.get("last_failure_time")

        if failures >= 5:
            if last_failure_time and (time.time() - last_failure_time) > 60:
                self._reset_circuit_breaker(task_id)
                return False
            return True
        return False

    def _record_circuit_breaker_failure(self, task_id: str) -> None:
        """Record circuit breaker failure."""
        state = self._circuit_breaker_states.setdefault(task_id, {
            "failures": 0,
            "last_failure_time": None
        })
        state["failures"] += 1
        state["last_failure_time"] = time.time()

    def _reset_circuit_breaker(self, task_id: str) -> None:
        """Reset circuit breaker."""
        self._circuit_breaker_states[task_id] = {
            "failures": 0,
            "last_failure_time": None
        }
