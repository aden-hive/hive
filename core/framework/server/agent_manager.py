"""Multi-agent lifecycle manager for the HTTP API server.

Manages loading, unloading, and listing agents. Each loaded agent
is tracked as an AgentSlot holding a runner, runtime, and metadata.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AgentSlot:
    """A loaded agent with its runtime resources."""

    id: str
    agent_path: Path
    runner: Any  # AgentRunner
    runtime: Any  # AgentRuntime
    info: Any  # AgentInfo
    loaded_at: float


class AgentManager:
    """Manages concurrent agent lifecycles.

    Thread-safe via asyncio.Lock. Agents are loaded via run_in_executor
    (blocking I/O) then started on the event loop — same pattern as
    tui/app.py.
    """

    def __init__(self, model: str | None = None) -> None:
        self._slots: dict[str, AgentSlot] = {}
        self._loading: set[str] = set()
        self._model = model
        self._lock = asyncio.Lock()

    async def load_agent(
        self,
        agent_path: str | Path,
        agent_id: str | None = None,
        model: str | None = None,
    ) -> AgentSlot:
        """Load an agent from disk and start its runtime.

        Args:
            agent_path: Path to agent folder (containing agent.json or agent.py).
            agent_id: Optional identifier; defaults to directory name.
            model: LLM model override; falls back to manager default.

        Returns:
            The AgentSlot for the loaded agent.

        Raises:
            ValueError: If agent_id is already loaded.
            FileNotFoundError: If agent_path is invalid.
        """
        from framework.runner import AgentRunner

        agent_path = Path(agent_path)
        resolved_id = agent_id or agent_path.name
        resolved_model = model or self._model

        async with self._lock:
            if resolved_id in self._slots:
                raise ValueError(f"Agent '{resolved_id}' is already loaded")
            if resolved_id in self._loading:
                raise ValueError(f"Agent '{resolved_id}' is currently loading")
            self._loading.add(resolved_id)  # claim slot

        try:
            # Blocking I/O — load in executor (same as tui/app.py:362-368)
            loop = asyncio.get_running_loop()
            runner = await loop.run_in_executor(
                None,
                lambda: AgentRunner.load(
                    agent_path,
                    model=resolved_model,
                    interactive=False,
                ),
            )

            # Setup (LLM provider, runtime, tools)
            if runner._agent_runtime is None:
                await loop.run_in_executor(None, runner._setup)

            runtime = runner._agent_runtime

            # Start runtime on event loop
            if runtime and not runtime.is_running:
                await runtime.start()

            info = runner.info()

            slot = AgentSlot(
                id=resolved_id,
                agent_path=agent_path,
                runner=runner,
                runtime=runtime,
                info=info,
                loaded_at=time.time(),
            )

            async with self._lock:
                self._slots[resolved_id] = slot
                self._loading.discard(resolved_id)

            logger.info(f"Agent '{resolved_id}' loaded from {agent_path}")
            return slot

        except Exception:
            async with self._lock:
                self._loading.discard(resolved_id)
            raise

    async def unload_agent(self, agent_id: str) -> bool:
        """Unload an agent and release its resources.

        Returns True if the agent was found and unloaded.
        """
        async with self._lock:
            slot = self._slots.pop(agent_id, None)

        if slot is None:
            return False

        try:
            await slot.runner.cleanup_async()
        except Exception as e:
            logger.error(f"Error cleaning up agent '{agent_id}': {e}")

        logger.info(f"Agent '{agent_id}' unloaded")
        return True

    def get_agent(self, agent_id: str) -> AgentSlot | None:
        return self._slots.get(agent_id)

    def is_loading(self, agent_id: str) -> bool:
        return agent_id in self._loading

    def list_agents(self) -> list[AgentSlot]:
        return list(self._slots.values())

    async def shutdown_all(self) -> None:
        """Gracefully unload all agents. Called on server shutdown."""
        agent_ids = list(self._slots.keys())
        for agent_id in agent_ids:
            await self.unload_agent(agent_id)
        logger.info("All agents unloaded")
