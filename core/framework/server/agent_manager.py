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


async def _extract_subgraph_steps(nodes: list, llm: Any) -> None:
    """Extract workflow steps from system prompts for frontend visualization.

    Called once during agent load. Iterates event_loop nodes with system prompts,
    asks the LLM to decompose each prompt into a DAG of steps, and stores the
    result on node.subgraph_steps. Non-critical — failures are logged and skipped.
    """
    candidates = [
        n for n in nodes if n.node_type == "event_loop" and n.system_prompt and not n.subgraph_steps
    ]
    if not candidates:
        return

    for node in candidates:
        try:
            prompt = (
                f"Analyze this system prompt for an AI agent node "
                f"and extract the workflow steps.\n\n"
                f"The node has these tools available: {json.dumps(node.tools)}\n"
                f"The node reads these inputs: {json.dumps(node.input_keys)}\n"
                f"The node must produce these outputs: {json.dumps(node.output_keys)}\n\n"
                f"System prompt:\n---\n{node.system_prompt}\n---\n\n"
                f"Extract a JSON array of workflow steps. For each step:\n"
                f'- "id": short snake_case identifier\n'
                f'- "label": human-readable description (5-10 words)\n'
                f'- "tool": the tool name this step uses, or null for reasoning/decision steps\n'
                f'- "depends_on": list of step ids that must complete before this one starts\n'
                f'- "type": "action" (does work), "decision" '
                f'(branches/loops), "loop" (repeats), or '
                f'"output" (sets output)\n\n'
                f"IMPORTANT:\n"
                f"- Look for parallelism: if multiple tools can run "
                f"independently after the same step, "
                f"give them the SAME depends_on — this creates fan-out\n"
                f"- Look for convergence: if a step needs results from multiple prior steps, "
                f"list ALL of them in depends_on — this creates fan-in\n"
                f"- Look for loops: if the prompt says 'repeat', 'go back to', 'if more then...', "
                f"model it as a decision step\n"
                f"- Do NOT make a simple linear chain unless the "
                f"prompt truly describes a strictly sequential "
                f"process\n\n"
                f"Return ONLY a JSON array of step objects. No explanation."
            )

            response = await llm.acomplete(
                messages=[{"role": "user", "content": prompt}],
                max_tokens=4096,
                json_mode=True,
            )

            # Parse the JSON array from the response
            text = response.content.strip()
            # Handle responses wrapped in {"steps": [...]} or just [...]
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "steps" in parsed:
                steps = parsed["steps"]
            elif isinstance(parsed, list):
                steps = parsed
            else:
                logger.warning(f"Subgraph extraction for '{node.id}': unexpected format")
                continue

            # Basic validation
            if not isinstance(steps, list) or not all(
                isinstance(s, dict) and s.get("id") and s.get("label") and "depends_on" in s
                for s in steps
            ):
                logger.warning(f"Subgraph extraction for '{node.id}': invalid step structure")
                continue

            node.subgraph_steps = steps
            logger.info(f"Extracted {len(steps)} subgraph steps for node '{node.id}'")

        except Exception as e:
            logger.warning(f"Subgraph extraction failed for node '{node.id}': {e}")
            continue


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
        import uuid
        from datetime import datetime

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

            # Generate a shared session ID for queen, judge, and worker.
            # All three use the same ID so conversations are scoped to this
            # agent load and start fresh each time.
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            session_id = f"session_{ts}_{uuid.uuid4().hex[:8]}"

            # 1. Monitoring tools — standalone registry, NOT merged into worker
            monitoring_registry = ToolRegistry()
            register_worker_monitoring_tools(
                monitoring_registry,
                event_bus,
                storage_path,
                worker_graph_id=runtime._graph_id,
            )

            # 2. Storage dirs — global, not per-agent. Queen and judge are
            #    supervisory components that outlive any single worker.
            hive_home = Path.home() / ".hive"
            judge_dir = hive_home / "judge" / "session" / session_id
            judge_dir.mkdir(parents=True, exist_ok=True)
            queen_dir = hive_home / "queen" / "session" / session_id
            queen_dir.mkdir(parents=True, exist_ok=True)

            # 3. Health judge — background task, fires every 2 minutes
            judge_runtime = Runtime(hive_home / "judge")
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
                            stream_id="judge",
                            storage_path=judge_dir,
                            loop_config=judge_graph.loop_config,
                        )
                        await executor.execute(
                            graph=judge_graph,
                            goal=judge_goal,
                            input_data={
                                "event": {"source": "timer", "reason": "scheduled"},
                            },
                            session_state={"resume_session_id": session_id},
                        )
                    except Exception:
                        logger.error("Health judge tick failed", exc_info=True)

            slot.judge_task = asyncio.create_task(_judge_loop())

            # 4. Queen — persistent interactive conversation
            from framework.agents.hive_coder.agent import queen_goal, queen_graph as _queen_graph

            queen_registry = ToolRegistry()

            # Coding tools from hive_coder's MCP config (read_file, write_file, etc.)
            import framework.agents.hive_coder as _hive_coder_pkg
            hive_coder_dir = Path(_hive_coder_pkg.__file__).parent
            mcp_config = hive_coder_dir / "mcp_servers.json"
            if mcp_config.exists():
                try:
                    queen_registry.load_mcp_config(mcp_config)
                    logger.info("Queen: loaded MCP tools from %s", mcp_config)
                except Exception:
                    logger.warning("Queen: MCP config failed to load", exc_info=True)

            register_queen_lifecycle_tools(
                queen_registry,
                worker_runtime=runtime,
                event_bus=event_bus,
                storage_path=storage_path,
                session_id=session_id,
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

            # Build worker profile for queen's system prompt
            from framework.tools.queen_lifecycle_tools import build_worker_profile
            worker_identity = build_worker_profile(runtime)

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

            queen_runtime = Runtime(hive_home / "queen")

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
                        session_state={"resume_session_id": session_id},
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

    async def load_queen_session(
        self,
        session_id: str | None = None,
        model: str | None = None,
    ) -> AgentSlot:
        """Start a queen-only session with coding tools but no worker agent.

        Creates a standalone queen conversation backed by MCP coding tools
        (read_file, write_file, etc.) without requiring a loaded worker.
        Useful for building agents from scratch or general coding tasks.
        """
        import uuid
        from datetime import datetime

        from framework.agents.hive_coder.agent import queen_goal, queen_graph as _queen_graph
        from framework.graph.executor import GraphExecutor
        from framework.llm.litellm import LiteLLMProvider
        from framework.runner.tool_registry import ToolRegistry
        from framework.runtime.core import Runtime
        from framework.runtime.event_bus import EventBus

        resolved_id = session_id or "queen"
        resolved_model = model or self._model

        async with self._lock:
            if resolved_id in self._slots:
                raise ValueError(f"Session '{resolved_id}' is already active")

        # Session ID for storage scoping
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        sid = f"session_{ts}_{uuid.uuid4().hex[:8]}"

        # Create standalone LLM + event bus (no worker runtime needed)
        llm = LiteLLMProvider(model=resolved_model) if resolved_model else LiteLLMProvider()
        event_bus = EventBus()

        # Storage path — global, same location as queen-with-worker
        hive_home = Path.home() / ".hive"
        queen_dir = hive_home / "queen" / "session" / sid
        queen_dir.mkdir(parents=True, exist_ok=True)

        # Register MCP coding tools
        queen_registry = ToolRegistry()
        import framework.agents.hive_coder as _hive_coder_pkg

        hive_coder_dir = Path(_hive_coder_pkg.__file__).parent
        mcp_config = hive_coder_dir / "mcp_servers.json"
        if mcp_config.exists():
            try:
                queen_registry.load_mcp_config(mcp_config)
                logger.info("Queen session: loaded MCP tools from %s", mcp_config)
            except Exception:
                logger.warning("Queen session: MCP config failed to load", exc_info=True)

        queen_tools = list(queen_registry.get_tools().values())
        queen_tool_executor = queen_registry.get_executor()

        # Adjust queen prompt: no worker, no delegation
        _orig_node = _queen_graph.nodes[0]
        no_worker_identity = (
            "\n\n# Worker Profile\n"
            "No worker agent loaded. You are operating independently.\n"
            "Handle all tasks directly using your coding tools."
        )
        base_prompt = _orig_node.system_prompt or ""
        registered_tool_names = set(queen_registry.get_tools().keys())
        adjusted_node = _orig_node.model_copy(
            update={
                "system_prompt": base_prompt + no_worker_identity,
                "tools": [t for t in (_orig_node.tools or []) if t in registered_tool_names],
            }
        )
        queen_graph = _queen_graph.model_copy(update={"nodes": [adjusted_node]})

        queen_runtime = Runtime(queen_dir)

        slot = AgentSlot(
            id=resolved_id,
            agent_path=queen_dir,
            runner=None,
            runtime=None,
            info=None,
            loaded_at=time.time(),
        )

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
                    "Queen session starting with %d tools: %s",
                    len(queen_tools),
                    [t.name for t in queen_tools],
                )
                await executor.execute(
                    graph=queen_graph,
                    goal=queen_goal,
                    input_data={"greeting": "Session started. No worker agent loaded."},
                    session_state={"resume_session_id": sid},
                )
                logger.warning("Queen session executor returned (should be forever-alive)")
            except Exception:
                logger.error("Queen session crashed", exc_info=True)
            finally:
                slot.queen_executor = None

        slot.queen_task = asyncio.create_task(_queen_loop())

        async with self._lock:
            self._slots[resolved_id] = slot

        logger.info("Queen-only session '%s' started", resolved_id)
        return slot

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
