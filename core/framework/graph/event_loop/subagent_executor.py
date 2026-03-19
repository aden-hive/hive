"""Subagent execution for the event loop.

Handles the full subagent lifecycle: validation, context setup, tool filtering,
conversation store derivation, execution, and cleanup.  Also includes the
_EscalationReceiver helper used for subagent → queen escalation routing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from framework.llm.provider import ToolResult, ToolUse

logger = logging.getLogger(__name__)


class EscalationReceiver:
    """Temporary receiver registered in node_registry for subagent escalation routing.

    When a subagent calls ``report_to_parent(wait_for_response=True)``, the callback
    creates one of these, registers it under a unique escalation ID in the executor's
    ``node_registry``, and awaits ``wait()``.  The TUI / runner calls
    ``inject_input(escalation_id, content)`` which the ``ExecutionStream`` routes here
    via ``inject_event()`` — matching the same ``hasattr(node, "inject_event")`` check
    used for regular ``EventLoopNode`` instances.
    """

    def __init__(self) -> None:
        self._event = asyncio.Event()
        self._response: str | None = None
        self._awaiting_input = True  # So inject_worker_message() can prefer us

    async def inject_event(self, content: str, *, is_client_input: bool = False) -> None:
        """Called by ExecutionStream.inject_input() when the user responds."""
        self._response = content
        self._event.set()

    async def wait(self) -> str | None:
        """Block until inject_event() delivers the user's response."""
        await self._event.wait()
        return self._response


async def execute_subagent(
    ctx: Any,  # NodeContext
    agent_id: str,
    task: str,
    *,
    accumulator: Any | None = None,  # OutputAccumulator
    event_bus: Any | None = None,  # EventBus
    config: Any = None,  # LoopConfig
    tool_executor: Any | None = None,  # Callable
    conversation_store: Any | None = None,  # ConversationStore
    subagent_instance_counter: dict[str, int] | None = None,
) -> ToolResult:
    """Execute a subagent and return the result as a ToolResult.

    The subagent:
    - Gets a fresh conversation with just the task
    - Has read-only access to the parent's readable memory
    - Cannot delegate to its own subagents (prevents recursion)
    - Returns its output in structured JSON format

    Args:
        ctx: Parent node's context (for memory, tools, LLM access).
        agent_id: The node ID of the subagent to invoke.
        task: The task description to give the subagent.
        accumulator: Parent's OutputAccumulator.
        event_bus: EventBus for lifecycle events.
        config: LoopConfig for iteration/tool limits.
        tool_executor: Tool executor callable.
        conversation_store: Parent conversation store (for deriving subagent store).
        subagent_instance_counter: Mutable counter dict for unique subagent paths.

    Returns:
        ToolResult with structured JSON output.
    """
    from framework.graph.node import NodeContext, SharedMemory

    # Log subagent invocation start
    logger.info(
        "\n" + "=" * 60 + "\n"
        "🤖 SUBAGENT INVOCATION\n"
        "=" * 60 + "\n"
        "Parent Node: %s\n"
        "Subagent ID: %s\n"
        "Task: %s\n" + "=" * 60,
        ctx.node_id,
        agent_id,
        task[:500] + "..." if len(task) > 500 else task,
    )

    # 1. Validate agent exists in registry
    if agent_id not in ctx.node_registry:
        return ToolResult(
            tool_use_id="",
            content=json.dumps(
                {
                    "message": f"Sub-agent '{agent_id}' not found in registry",
                    "data": None,
                    "metadata": {"agent_id": agent_id, "success": False, "error": "not_found"},
                }
            ),
            is_error=True,
        )

    subagent_spec = ctx.node_registry[agent_id]

    # 2. Create read-only memory snapshot
    parent_data = ctx.memory.read_all()

    # Merge in-flight outputs from the parent's accumulator.
    if accumulator:
        for key, value in accumulator.to_dict().items():
            if key not in parent_data:
                parent_data[key] = value

    subagent_memory = SharedMemory()
    for key, value in parent_data.items():
        subagent_memory.write(key, value, validate=False)

    read_keys = set(parent_data.keys()) | set(subagent_spec.input_keys or [])
    scoped_memory = subagent_memory.with_permissions(
        read_keys=list(read_keys),
        write_keys=[],  # Read-only!
    )

    # 2b. Set up report callback (one-way channel to parent / event bus)
    subagent_reports: list[dict] = []

    async def _report_callback(
        message: str,
        data: dict | None = None,
        *,
        wait_for_response: bool = False,
    ) -> str | None:
        subagent_reports.append({"message": message, "data": data, "timestamp": time.time()})
        if event_bus:
            await event_bus.emit_subagent_report(
                stream_id=ctx.node_id,
                node_id=f"{ctx.node_id}:subagent:{agent_id}",
                subagent_id=agent_id,
                message=message,
                data=data,
                execution_id=ctx.execution_id,
            )

        if not wait_for_response:
            return None

        if not event_bus:
            logger.warning(
                "Subagent '%s' requested user response but no event_bus available",
                agent_id,
            )
            return None

        # Create isolated receiver and register for input routing
        import uuid

        from framework.graph.event_loop_node import _EscalationReceiver

        escalation_id = f"{ctx.node_id}:escalation:{uuid.uuid4().hex[:8]}"
        receiver = _EscalationReceiver()
        registry = ctx.shared_node_registry

        registry[escalation_id] = receiver
        try:
            await event_bus.emit_escalation_requested(
                stream_id=ctx.stream_id or ctx.node_id,
                node_id=escalation_id,
                reason=f"Subagent report (wait_for_response) from {agent_id}",
                context=message,
                execution_id=ctx.execution_id,
            )
            # Block until queen responds
            return await receiver.wait()
        finally:
            registry.pop(escalation_id, None)

    # 3. Filter tools for subagent
    subagent_tool_names = set(subagent_spec.tools or [])
    tool_source = ctx.all_tools if ctx.all_tools else ctx.available_tools

    # GCU auto-population
    if subagent_spec.node_type == "gcu" and not subagent_tool_names:
        subagent_tools = [t for t in tool_source if t.name != "delegate_to_sub_agent"]
    else:
        subagent_tools = [
            t
            for t in tool_source
            if t.name in subagent_tool_names and t.name != "delegate_to_sub_agent"
        ]

    missing = subagent_tool_names - {t.name for t in subagent_tools}
    if missing:
        logger.warning(
            "Subagent '%s' requested tools not found in catalog: %s",
            agent_id,
            sorted(missing),
        )

    logger.info(
        "📦 Subagent '%s' configuration:\n"
        "   - System prompt: %s\n"
        "   - Tools available (%d): %s\n"
        "   - Memory keys inherited: %s",
        agent_id,
        (subagent_spec.system_prompt[:200] + "...")
        if subagent_spec.system_prompt and len(subagent_spec.system_prompt) > 200
        else subagent_spec.system_prompt,
        len(subagent_tools),
        [t.name for t in subagent_tools],
        list(parent_data.keys()),
    )

    # 4. Build subagent context
    max_iter = min(config.max_iterations, 10)
    subagent_ctx = NodeContext(
        runtime=ctx.runtime,
        node_id=f"{ctx.node_id}:subagent:{agent_id}",
        node_spec=subagent_spec,
        memory=scoped_memory,
        input_data={"task": task, **parent_data},
        llm=ctx.llm,
        available_tools=subagent_tools,
        goal_context=(
            f"Your specific task: {task}\n\n"
            f"COMPLETION REQUIREMENTS:\n"
            f"When your task is done, you MUST call set_output() "
            f"for each required key: {subagent_spec.output_keys}\n"
            f"Alternatively, call report_to_parent(mark_complete=true) "
            f"with your findings in message/data.\n"
            f"You have a maximum of {max_iter} turns to complete this task."
        ),
        goal=ctx.goal,
        max_tokens=ctx.max_tokens,
        runtime_logger=ctx.runtime_logger,
        is_subagent_mode=True,  # Prevents nested delegation
        report_callback=_report_callback,
        node_registry={},  # Empty - no nested subagents
        shared_node_registry=ctx.shared_node_registry,  # For escalation routing
    )

    # 5. Create and execute subagent EventLoopNode
    if subagent_instance_counter is not None:
        subagent_instance_counter.setdefault(agent_id, 0)
        subagent_instance_counter[agent_id] += 1
        subagent_instance = str(subagent_instance_counter[agent_id])
    else:
        subagent_instance = "1"

    subagent_conv_store = None
    if conversation_store is not None:
        from framework.storage.conversation_store import FileConversationStore

        parent_base = getattr(conversation_store, "_base", None)
        if parent_base is not None:
            conversations_dir = parent_base.parent
            subagent_dir_name = f"{agent_id}-{subagent_instance}"
            subagent_store_path = conversations_dir / subagent_dir_name
            subagent_conv_store = FileConversationStore(base_path=subagent_store_path)

    # Derive a subagent-scoped spillover dir
    subagent_spillover = None
    if config.spillover_dir:
        subagent_spillover = str(
            Path(config.spillover_dir) / agent_id / subagent_instance
        )

    # Import here to avoid circular imports at module level
    from framework.graph.event_loop_node import EventLoopNode, LoopConfig, SubagentJudge

    subagent_node = EventLoopNode(
        event_bus=event_bus,
        judge=SubagentJudge(task=task, max_iterations=max_iter),
        config=LoopConfig(
            max_iterations=max_iter,
            max_tool_calls_per_turn=config.max_tool_calls_per_turn,
            tool_call_overflow_margin=config.tool_call_overflow_margin,
            max_context_tokens=config.max_context_tokens,
            stall_detection_threshold=config.stall_detection_threshold,
            max_tool_result_chars=config.max_tool_result_chars,
            spillover_dir=subagent_spillover,
        ),
        tool_executor=tool_executor,
        conversation_store=subagent_conv_store,
    )

    # Inject a unique GCU browser profile for this subagent
    _profile_token = None
    try:
        from gcu.browser.session import set_active_profile as _set_gcu_profile

        _profile_token = _set_gcu_profile(f"{agent_id}-{subagent_instance}")
    except ImportError:
        pass  # GCU tools not installed; no-op

    try:
        logger.info("🚀 Starting subagent '%s' execution...", agent_id)
        start_time = time.time()
        result = await subagent_node.execute(subagent_ctx)
        latency_ms = int((time.time() - start_time) * 1000)

        separator = "-" * 60
        logger.info(
            "\n%s\n"
            "✅ SUBAGENT '%s' COMPLETED\n"
            "%s\n"
            "Success: %s\n"
            "Latency: %dms\n"
            "Tokens used: %s\n"
            "Output keys: %s\n"
            "%s",
            separator,
            agent_id,
            separator,
            result.success,
            latency_ms,
            result.tokens_used,
            list(result.output.keys()) if result.output else [],
            separator,
        )

        result_json = {
            "message": (
                f"Sub-agent '{agent_id}' completed successfully"
                if result.success
                else f"Sub-agent '{agent_id}' failed: {result.error}"
            ),
            "data": result.output,
            "reports": subagent_reports if subagent_reports else None,
            "metadata": {
                "agent_id": agent_id,
                "success": result.success,
                "tokens_used": result.tokens_used,
                "latency_ms": latency_ms,
                "report_count": len(subagent_reports),
            },
        }

        return ToolResult(
            tool_use_id="",
            content=json.dumps(result_json, indent=2, default=str),
            is_error=not result.success,
        )

    except Exception as e:
        logger.exception(
            "\n" + "!" * 60 + "\n❌ SUBAGENT '%s' FAILED\nError: %s\n" + "!" * 60,
            agent_id,
            str(e),
        )
        result_json = {
            "message": f"Sub-agent '{agent_id}' raised exception: {e}",
            "data": None,
            "metadata": {
                "agent_id": agent_id,
                "success": False,
                "error": str(e),
            },
        }
        return ToolResult(
            tool_use_id="",
            content=json.dumps(result_json, indent=2),
            is_error=True,
        )
    finally:
        # Restore the GCU profile context
        if _profile_token is not None:
            from gcu.browser.session import _active_profile as _gcu_profile_var

            _gcu_profile_var.reset(_profile_token)

            # Stop the browser session for this subagent's profile
            if tool_executor is not None:
                _subagent_profile = f"{agent_id}-{subagent_instance}"
                try:
                    _stop_use = ToolUse(
                        id="gcu-cleanup",
                        name="browser_stop",
                        input={"profile": _subagent_profile},
                    )
                    _stop_result = tool_executor(_stop_use)
                    if asyncio.iscoroutine(_stop_result) or asyncio.isfuture(_stop_result):
                        await _stop_result
                except Exception as _gcu_exc:
                    logger.warning(
                        "GCU browser_stop failed for profile %r: %s",
                        _subagent_profile,
                        _gcu_exc,
                    )
