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
    queen_executor: Any = None  # GraphExecutor for queen input injection
    queen_task: asyncio.Task | None = None  # asyncio.Task for queen loop
    judge_task: asyncio.Task | None = None  # asyncio.Task for judge loop
    escalation_sub: str | None = None  # EventBus subscription ID


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

            # Load queen + judge monitoring (skip for hive_coder itself)
            if agent_path.name != "hive_coder" and runtime:
                await self._load_queen_and_judge(slot, runner._storage_path)

            return slot

        except Exception:
            async with self._lock:
                self._loading.discard(resolved_id)
            raise

    async def _load_queen_and_judge(self, slot: AgentSlot, storage_path: str | Path) -> None:
        """Start health judge and interactive queen as independent conversations.

        Mirrors tui/app.py:_load_judge_and_queen but adapted for the HTTP
        server (no TUI widgets, no MCP tools, no ChatRepl).

        Three-conversation architecture:
        - **Queen**: persistent interactive GraphExecutor (user chat interface)
        - **Judge**: timer-driven background GraphExecutor (silent monitoring)
        - **Worker**: the existing AgentRuntime (unchanged)
        """
        from framework.graph.executor import GraphExecutor
        from framework.monitoring import judge_goal, judge_graph
        from framework.runner.tool_registry import ToolRegistry
        from framework.runtime.core import Runtime
        from framework.runtime.event_bus import EventType as _ET
        from framework.tools.queen_lifecycle_tools import register_queen_lifecycle_tools
        from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

        try:
            storage_path = Path(storage_path)
            runtime = slot.runtime
            event_bus = runtime._event_bus
            llm = runtime._llm

            # 1. Monitoring tools — standalone registry, NOT merged into worker
            monitoring_registry = ToolRegistry()
            register_worker_monitoring_tools(
                monitoring_registry,
                event_bus,
                storage_path,
                worker_graph_id=runtime._graph_id,
            )

            # 2. Storage dirs
            judge_dir = storage_path / "graphs" / "worker_health_judge" / "session"
            judge_dir.mkdir(parents=True, exist_ok=True)
            queen_dir = storage_path / "graphs" / "queen" / "session"
            queen_dir.mkdir(parents=True, exist_ok=True)

            # 3. Health judge — background task, fires every 2 minutes
            judge_runtime = Runtime(storage_path / "graphs" / "worker_health_judge")
            monitoring_tools = list(monitoring_registry.get_tools().values())
            monitoring_executor = monitoring_registry.get_executor()

            async def _judge_loop():
                interval = 120
                first = True
                while True:
                    if not first:
                        await asyncio.sleep(interval)
                    first = False
                    try:
                        executor = GraphExecutor(
                            runtime=judge_runtime,
                            llm=llm,
                            tools=monitoring_tools,
                            tool_executor=monitoring_executor,
                            event_bus=event_bus,
                            stream_id="worker_health_judge",
                            storage_path=judge_dir,
                            loop_config=judge_graph.loop_config,
                        )
                        await executor.execute(
                            graph=judge_graph,
                            goal=judge_goal,
                            input_data={
                                "event": {"source": "timer", "reason": "scheduled"},
                            },
                            session_state={"resume_session_id": "persistent"},
                        )
                    except Exception:
                        logger.error("Health judge tick failed", exc_info=True)

            slot.judge_task = asyncio.create_task(_judge_loop())

            # 4. Queen — persistent interactive conversation
            from framework.agents.hive_coder.agent import queen_goal, queen_graph as _queen_graph

            queen_registry = ToolRegistry()

            # No MCP tools on server — queen gets only lifecycle + monitoring tools
            register_queen_lifecycle_tools(
                queen_registry,
                worker_runtime=runtime,
                event_bus=event_bus,
                storage_path=storage_path,
            )
            register_worker_monitoring_tools(
                queen_registry,
                event_bus,
                storage_path,
                stream_id="queen",
                worker_graph_id=runtime._graph_id,
            )
            queen_tools = list(queen_registry.get_tools().values())
            queen_tool_executor = queen_registry.get_executor()

            # Build worker identity for queen's system prompt
            worker_graph_id = runtime._graph_id
            worker_goal_name = getattr(runtime.goal, "name", worker_graph_id)
            worker_goal_desc = getattr(runtime.goal, "description", "")
            worker_identity = (
                f"\n\n# Current Session\n"
                f"Worker agent: {worker_graph_id}\n"
                f"Goal: {worker_goal_name}\n"
            )
            if worker_goal_desc:
                worker_identity += f"Description: {worker_goal_desc}\n"
            worker_identity += "Status at session start: idle (not started)."

            # Filter queen graph tools to what's registered and inject identity
            registered_tool_names = set(queen_registry.get_tools().keys())
            _orig_queen_node = _queen_graph.nodes[0]
            declared_tools = _orig_queen_node.tools or []
            available_tools = [t for t in declared_tools if t in registered_tool_names]

            node_updates: dict = {}
            if set(available_tools) != set(declared_tools):
                missing = sorted(set(declared_tools) - registered_tool_names)
                logger.warning("Queen: tools not available (no MCP on server): %s", missing)
                node_updates["tools"] = available_tools
            base_prompt = _orig_queen_node.system_prompt or ""
            node_updates["system_prompt"] = base_prompt + worker_identity

            adjusted_node = _orig_queen_node.model_copy(update=node_updates)
            queen_graph = _queen_graph.model_copy(update={"nodes": [adjusted_node]})

            queen_runtime = Runtime(storage_path / "graphs" / "queen")

            async def _queen_loop():
                try:
                    executor = GraphExecutor(
                        runtime=queen_runtime,
                        llm=llm,
                        tools=queen_tools,
                        tool_executor=queen_tool_executor,
                        event_bus=event_bus,
                        stream_id="queen",
                        storage_path=queen_dir,
                        loop_config=queen_graph.loop_config,
                    )
                    slot.queen_executor = executor
                    logger.info(
                        "Queen starting with %d tools: %s",
                        len(queen_tools),
                        [t.name for t in queen_tools],
                    )
                    await executor.execute(
                        graph=queen_graph,
                        goal=queen_goal,
                        input_data={"greeting": "Session started."},
                        session_state={"resume_session_id": "persistent"},
                    )
                    logger.warning("Queen executor returned (should be forever-alive)")
                except Exception:
                    logger.error("Queen conversation crashed", exc_info=True)
                finally:
                    slot.queen_executor = None

            slot.queen_task = asyncio.create_task(_queen_loop())

            # 5. Judge escalation → inject into queen conversation
            async def _on_escalation(event):
                ticket = event.data.get("ticket", {})
                executor = slot.queen_executor
                if executor is None:
                    logger.warning("Escalation received but queen executor is None")
                    return
                node = executor.node_registry.get("queen")
                if node is not None and hasattr(node, "inject_event"):
                    import json as _json

                    msg = "[ESCALATION TICKET from Health Judge]\n" + _json.dumps(
                        ticket, indent=2, ensure_ascii=False
                    )
                    await node.inject_event(msg)
                else:
                    logger.warning("Escalation received but queen node not ready")

            slot.escalation_sub = event_bus.subscribe(
                event_types=[_ET.WORKER_ESCALATION_TICKET],
                handler=_on_escalation,
            )

            logger.info("Queen + health judge active for agent '%s'", slot.id)

        except Exception as e:
            logger.error("Failed to load queen/judge for '%s': %s", slot.id, e, exc_info=True)

    async def unload_agent(self, agent_id: str) -> bool:
        """Unload an agent and release its resources.

        Returns True if the agent was found and unloaded.
        """
        async with self._lock:
            slot = self._slots.pop(agent_id, None)

        if slot is None:
            return False

        # Stop queen + judge monitoring
        self._stop_monitoring(slot)

        try:
            await slot.runner.cleanup_async()
        except Exception as e:
            logger.error(f"Error cleaning up agent '{agent_id}': {e}")

        logger.info(f"Agent '{agent_id}' unloaded")
        return True

    def _stop_monitoring(self, slot: AgentSlot) -> None:
        """Cancel judge/queen tasks and unsubscribe escalation events."""
        if slot.judge_task is not None:
            slot.judge_task.cancel()
            slot.judge_task = None
        if slot.queen_task is not None:
            slot.queen_task.cancel()
            slot.queen_task = None
        slot.queen_executor = None
        if slot.escalation_sub is not None and slot.runtime:
            try:
                slot.runtime._event_bus.unsubscribe(slot.escalation_sub)
            except Exception:
                pass
            slot.escalation_sub = None

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
