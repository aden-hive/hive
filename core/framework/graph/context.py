"""Shared graph execution context helpers.

This module centralizes:
- Graph-run shared state (`GraphContext`)
- Scoped buffer permission shaping for a node
- Per-node accounts prompt resolution
- Canonical `NodeContext` construction
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from framework.graph.edge import GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import DataBuffer, NodeContext, NodeProtocol, NodeSpec
from framework.runtime.core import DecisionTracker


@dataclass
class GraphContext:
    """Shared state for one graph execution run."""

    graph: GraphSpec
    goal: Goal
    buffer: DataBuffer
    runtime: DecisionTracker
    llm: Any  # LLMProvider
    tools: list[Any]  # list[Tool]
    tool_executor: Any  # Callable
    event_bus: Any  # GraphScopedEventBus
    execution_id: str
    stream_id: str
    run_id: str
    storage_path: Any  # Path | None
    runtime_logger: Any = None
    node_registry: dict[str, NodeProtocol] = field(default_factory=dict)
    node_spec_registry: dict[str, NodeSpec] = field(default_factory=dict)
    parallel_config: Any = None  # ParallelExecutionConfig | None
    enable_parallel_execution: bool = True
    is_continuous: bool = False
    continuous_conversation: Any = None
    cumulative_tools: list[Any] = field(default_factory=list)
    cumulative_tool_names: set[str] = field(default_factory=set)
    cumulative_output_keys: list[str] = field(default_factory=list)
    accounts_prompt: str = ""
    accounts_data: list[dict] | None = None
    tool_provider_map: dict[str, str] | None = None
    skills_catalog_prompt: str = ""
    protocols_prompt: str = ""
    skill_dirs: list[str] = field(default_factory=list)
    context_warn_ratio: float | None = None
    batch_init_nudge: str | None = None
    dynamic_tools_provider: Any = None
    dynamic_prompt_provider: Any = None
    dynamic_memory_provider: Any = None
    iteration_metadata_provider: Any = None
    loop_config: dict[str, Any] = field(default_factory=dict)
    path: list[str] = field(default_factory=list)
    node_visit_counts: dict[str, int] = field(default_factory=dict)
    _path_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _visits_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Fan-out buffer conflict tracking: key → worker_id that wrote it
    _fanout_written_keys: dict[str, str] = field(default_factory=dict)
    # Retry tracking: worker_id → retry_count (for execution quality assessment)
    retry_counts: dict[str, int] = field(default_factory=dict)
    nodes_with_retries: set[str] = field(default_factory=set)
    # Colony memory reflection at node handoff
    colony_memory_dir: Any = None  # Path | None
    worker_sessions_dir: Any = None  # Path | None
    colony_recall_cache: dict[str, str] = field(default_factory=dict)
    colony_reflect_llm: Any = None  # LLMProvider for reflection
    _colony_reflect_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def build_scoped_buffer(buffer: DataBuffer, node_spec: NodeSpec) -> DataBuffer:
    """Create a node-scoped buffer view.

    When permissions are already restricted, auto-include framework-managed
    `_`-prefixed keys used by the default skill protocols.
    """

    read_keys = list(node_spec.input_keys)
    write_keys = list(node_spec.output_keys)

    if read_keys or write_keys:
        from framework.skills.defaults import DATA_BUFFER_KEYS as _skill_keys

        existing_underscore = [k for k in buffer._data if k.startswith("_")]
        extra_keys = set(_skill_keys) | set(existing_underscore)

        for key in extra_keys:
            if read_keys and key not in read_keys:
                read_keys.append(key)
            if write_keys and key not in write_keys:
                write_keys.append(key)

    return buffer.with_permissions(read_keys=read_keys, write_keys=write_keys)


def build_node_accounts_prompt(
    *,
    accounts_prompt: str,
    accounts_data: list[dict] | None,
    tool_provider_map: dict[str, str] | None,
    node_tool_names: list[str] | None,
    fallback_to_default: bool = False,
) -> str:
    """Resolve the accounts prompt for one node."""

    resolved = accounts_prompt
    if accounts_data and tool_provider_map:
        from framework.graph.prompting import build_accounts_prompt

        filtered = build_accounts_prompt(
            accounts_data,
            tool_provider_map,
            node_tool_names=node_tool_names,
        )
        if filtered or not fallback_to_default:
            resolved = filtered

    return resolved


def _resolve_available_tools(
    *,
    node_spec: NodeSpec,
    tools: list[Any],
    override_tools: list[Any] | None,
) -> list[Any]:
    """Select tools available to the current node.

    Respects ``node_spec.tool_access_policy``:
    - ``"all"``      -- all tools from the registry (no filtering).
    - ``"explicit"``  -- only tools whose name appears in ``node_spec.tools``.
                        If the list is empty, **no tools** are given (default-deny).
    - ``"none"``     -- no tools at all.
    """

    if override_tools is not None:
        return list(override_tools)

    policy = getattr(node_spec, "tool_access_policy", "explicit")

    if policy == "none":
        return []

    if policy == "all":
        return list(tools)

    # "explicit" (default): only tools named in node_spec.tools.
    if not node_spec.tools:
        return []

    return [tool for tool in tools if tool.name in node_spec.tools]


def _derive_input_data(buffer: DataBuffer, input_keys: list[str]) -> dict[str, Any]:
    """Collect node inputs from the shared buffer."""

    input_data: dict[str, Any] = {}
    for key in input_keys:
        value = buffer.read(key)
        if value is not None:
            input_data[key] = value
    return input_data


def build_node_context(
    *,
    runtime: DecisionTracker,
    node_spec: NodeSpec,
    buffer: DataBuffer,
    goal: Goal,
    llm: Any,
    tools: list[Any],
    max_tokens: int,
    input_data: dict[str, Any] | None = None,
    derive_input_data_from_buffer: bool = False,
    runtime_logger: Any = None,
    pause_event: Any = None,
    continuous_mode: bool = False,
    inherited_conversation: Any = None,
    override_tools: list[Any] | None = None,
    cumulative_output_keys: list[str] | None = None,
    event_triggered: bool = False,
    accounts_prompt: str = "",
    accounts_data: list[dict] | None = None,
    tool_provider_map: dict[str, str] | None = None,
    fallback_to_default_accounts_prompt: bool = False,
    identity_prompt: str = "",
    narrative: str = "",
    execution_id: str = "",
    run_id: str = "",
    stream_id: str = "",
    node_registry: dict[str, NodeSpec] | None = None,
    all_tools: list[Any] | None = None,
    shared_node_registry: dict[str, NodeProtocol] | None = None,
    dynamic_tools_provider: Any = None,
    dynamic_prompt_provider: Any = None,
    dynamic_memory_provider: Any = None,
    iteration_metadata_provider: Any = None,
    skills_catalog_prompt: str = "",
    protocols_prompt: str = "",
    skill_dirs: list[str] | None = None,
    default_skill_warn_ratio: float | None = None,
    default_skill_batch_nudge: str | None = None,
    memory_prompt: str = "",
) -> NodeContext:
    """Build a canonical `NodeContext` for graph execution."""

    available_tools = _resolve_available_tools(
        node_spec=node_spec,
        tools=tools,
        override_tools=override_tools,
    )
    scoped_buffer = build_scoped_buffer(buffer, node_spec)
    node_accounts_prompt = build_node_accounts_prompt(
        accounts_prompt=accounts_prompt,
        accounts_data=accounts_data,
        tool_provider_map=tool_provider_map,
        node_tool_names=node_spec.tools,
        fallback_to_default=fallback_to_default_accounts_prompt,
    )

    resolved_input_data = (
        _derive_input_data(buffer, node_spec.input_keys)
        if input_data is None and derive_input_data_from_buffer
        else dict(input_data or {})
    )

    return NodeContext(
        runtime=runtime,
        node_id=node_spec.id,
        node_spec=node_spec,
        buffer=scoped_buffer,
        input_data=resolved_input_data,
        llm=llm,
        available_tools=available_tools,
        goal_context=goal.to_prompt_context(),
        goal=goal,
        max_tokens=max_tokens,
        runtime_logger=runtime_logger,
        pause_event=pause_event,
        continuous_mode=continuous_mode,
        inherited_conversation=inherited_conversation,
        cumulative_output_keys=cumulative_output_keys or [],
        event_triggered=event_triggered,
        accounts_prompt=node_accounts_prompt,
        identity_prompt=identity_prompt,
        narrative=narrative,
        memory_prompt=memory_prompt,
        execution_id=execution_id,
        run_id=run_id,
        stream_id=stream_id,
        node_registry=node_registry or {},
        all_tools=list(all_tools or tools),
        shared_node_registry=shared_node_registry or {},
        dynamic_tools_provider=dynamic_tools_provider,
        dynamic_prompt_provider=dynamic_prompt_provider,
        dynamic_memory_provider=dynamic_memory_provider,
        iteration_metadata_provider=iteration_metadata_provider,
        skills_catalog_prompt=skills_catalog_prompt,
        protocols_prompt=protocols_prompt,
        skill_dirs=list(skill_dirs or []),
        default_skill_warn_ratio=default_skill_warn_ratio,
        default_skill_batch_nudge=default_skill_batch_nudge,
    )


def build_node_context_from_graph_context(
    graph_context: GraphContext,
    *,
    node_spec: NodeSpec,
    pause_event: Any = None,
    input_data: dict[str, Any] | None = None,
    derive_input_data_from_buffer: bool = True,
    override_tools: list[Any] | None = None,
    inherited_conversation: Any = None,
    cumulative_output_keys: list[str] | None = None,
    event_triggered: bool = False,
    identity_prompt: str | None = None,
    narrative: str = "",
    node_registry: dict[str, NodeSpec] | None = None,
    fallback_to_default_accounts_prompt: bool = True,
) -> NodeContext:
    """Build `NodeContext` using shared graph-run state."""

    gc = graph_context
    resolved_override_tools = override_tools
    if resolved_override_tools is None and gc.is_continuous and gc.cumulative_tools:
        resolved_override_tools = list(gc.cumulative_tools)

    resolved_inherited_conversation = inherited_conversation
    if resolved_inherited_conversation is None and gc.is_continuous:
        resolved_inherited_conversation = gc.continuous_conversation

    resolved_output_keys = cumulative_output_keys
    if resolved_output_keys is None and gc.is_continuous:
        resolved_output_keys = list(gc.cumulative_output_keys)

    return build_node_context(
        runtime=gc.runtime,
        node_spec=node_spec,
        buffer=gc.buffer,
        goal=gc.goal,
        llm=gc.llm,
        tools=gc.tools,
        max_tokens=gc.graph.max_tokens,
        input_data=input_data,
        derive_input_data_from_buffer=derive_input_data_from_buffer,
        runtime_logger=gc.runtime_logger,
        pause_event=pause_event,
        continuous_mode=gc.is_continuous,
        inherited_conversation=resolved_inherited_conversation,
        override_tools=resolved_override_tools,
        cumulative_output_keys=resolved_output_keys,
        event_triggered=event_triggered,
        accounts_prompt=gc.accounts_prompt,
        accounts_data=gc.accounts_data,
        tool_provider_map=gc.tool_provider_map,
        fallback_to_default_accounts_prompt=fallback_to_default_accounts_prompt,
        identity_prompt=identity_prompt
        if identity_prompt is not None
        else getattr(gc.graph, "identity_prompt", "") or "",
        narrative=narrative,
        execution_id=gc.execution_id,
        run_id=gc.run_id,
        stream_id=gc.stream_id,
        node_registry=node_registry or gc.node_spec_registry,
        all_tools=gc.tools,
        shared_node_registry=gc.node_registry,
        dynamic_tools_provider=gc.dynamic_tools_provider,
        dynamic_prompt_provider=gc.dynamic_prompt_provider,
        dynamic_memory_provider=gc.dynamic_memory_provider,
        iteration_metadata_provider=gc.iteration_metadata_provider,
        skills_catalog_prompt=gc.skills_catalog_prompt,
        protocols_prompt=gc.protocols_prompt,
        skill_dirs=gc.skill_dirs,
        default_skill_warn_ratio=gc.context_warn_ratio,
        default_skill_batch_nudge=gc.batch_init_nudge,
    )
