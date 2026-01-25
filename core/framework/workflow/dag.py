"""DAG-based workflow orchestration."""

from typing import Dict, List, Set, Optional, Any
from enum import Enum
from pydantic import BaseModel
import asyncio


class TaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class Task(BaseModel):
    """A single workflow task."""
    id: str
    name: str
    func: callable = None
    dependencies: List[str] = []
    params: Dict[str, Any] = {}

    # Execution settings
    timeout: Optional[int] = None
    retries: int = 0
    retry_delay: int = 5
    retry_backoff: float = 2.0

    # State
    state: TaskState = TaskState.PENDING
    result: Any = None
    error: Optional[str] = None


class DAG:
    """Directed Acyclic Graph for workflow orchestration."""

    def __init__(self, dag_id: str, description: str = ""):
        self.dag_id = dag_id
        self.description = description
        self._tasks: Dict[str, Task] = {}
        self._edges: Dict[str, List[str]] = {}

    def add_task(self, task: Task) -> None:
        """Add a task to the DAG."""
        if task.id in self._tasks:
            raise ValueError(f"Task {task.id} already exists")

        self._validate_no_circular_deps(task.id, task.dependencies)

        self._tasks[task.id] = task
        for dep in task.dependencies:
            if dep not in self._edges:
                self._edges[dep] = []
            self._edges[dep].append(task.id)

    def _validate_no_circular_deps(self, task_id: str, dependencies: List[str]) -> None:
        """Validate no circular dependencies."""
        visited = set()
        recursion_stack = set()

        def dfs(node: str) -> bool:
            visited.add(node)
            recursion_stack.add(node)

            for neighbor in self._edges.get(node, []):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in recursion_stack:
                    return True

            recursion_stack.remove(node)
            return False

        # Add temporary edges
        for dep in dependencies:
            self._edges.setdefault(dep, []).append(task_id)

        has_cycle = any(
            dfs(tid) for tid in list(self._tasks.keys()) + [task_id]
            if tid not in visited
        )

        # Remove temporary edges
        for dep in dependencies:
            self._edges[dep].remove(task_id)

        if has_cycle:
            raise ValueError("Circular dependency detected")

    def get_ready_tasks(self) -> List[Task]:
        """Get tasks with all dependencies satisfied."""
        ready = []
        for task_id, task in self._tasks.items():
            if task.state == TaskState.PENDING:
                deps_satisfied = all(
                    self._tasks[dep].state == TaskState.SUCCESS
                    for dep in task.dependencies
                    if dep in self._tasks
                )
                if deps_satisfied:
                    ready.append(task)
        return ready

    @property
    def tasks(self) -> List[Task]:
        """Get all tasks."""
        return list(self._tasks.values())
