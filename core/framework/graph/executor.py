import asyncio
import copy
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from framework.graph.edge import EdgeSpec, GraphSpec
from framework.graph.goal import Goal
from framework.graph.node import (
    FunctionNode,
    LLMNode,
    NodeContext,
    NodeProtocol,
    NodeResult,
    NodeSpec,
    RouterNode,
    SharedMemory,
)
from framework.graph.output_cleaner import CleansingConfig, OutputCleaner
from framework.graph.validator import OutputValidator
from framework.llm.provider import LLMProvider, Tool
from framework.runtime.core import Runtime


@dataclass
class ExecutionResult:
    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    steps_executed: int = 0
    total_tokens: int = 0
    total_latency_ms: int = 0
    path: list[str] = field(default_factory=list)


class GraphExecutor:
    def __init__(
        self,
        runtime: Runtime,
        llm: LLMProvider | None = None,
        tools: list[Tool] | None = None,
        tool_executor: Callable | None = None,
        node_registry: dict[str, NodeProtocol] | None = None,
        cleansing_config: CleansingConfig | None = None,
    ):
        self.runtime = runtime
        self.llm = llm
        self.tools = tools or []
        self.tool_executor = tool_executor
        self.node_registry = node_registry or {}
        self.validator = OutputValidator()
        self.logger = logging.getLogger(__name__)
        self.cleansing_config = cleansing_config or CleansingConfig()
        self.output_cleaner = OutputCleaner(self.cleansing_config, llm)

    async def execute(
        self,
        graph: GraphSpec,
        goal: Goal,
        input_data: dict[str, Any] | None = None,
    ) -> ExecutionResult:

        committed_state: dict[str, Any] = copy.deepcopy(input_data or {})
        steps = 0
        path: list[str] = []
        current_node_id = graph.entry_node
        retry_counts: dict[str, int] = {}

        self.runtime.start_run(goal.id, goal.description, committed_state)

        while steps < graph.max_steps:
            steps += 1
            node_spec = graph.get_node(current_node_id)
            path.append(current_node_id)

            retry_counts.setdefault(current_node_id, 0)
            max_retries = node_spec.max_retries or 1

            while retry_counts[current_node_id] < max_retries:
                memory = SharedMemory(_data=copy.deepcopy(committed_state))

                ctx = self._build_context(
                    node_spec=node_spec,
                    memory=memory,
                    goal=goal,
                    input_data=committed_state,
                    max_tokens=graph.max_tokens,
                )

                node_impl = self._get_node_implementation(node_spec)
                result = await node_impl.execute(ctx)

                if result.success:
                    for k, v in result.output.items():
                        memory.write(k, v, validate=False)

                    committed_state = copy.deepcopy(memory._data)
                    break

                retry_counts[current_node_id] += 1

            else:
                self.runtime.end_run(
                    success=False,
                    narrative=f"Node {node_spec.name} failed after retries",
                )
                return ExecutionResult(
                    success=False,
                    error=f"Node {node_spec.name} failed after retries",
                    steps_executed=steps,
                    path=path,
                )

            if current_node_id in graph.terminal_nodes:
                break

            edges = graph.get_outgoing_edges(current_node_id)
            current_node_id = edges[0].target if edges else None
            if not current_node_id:
                break

        # ✅ FIX: narrative must be a STRING
        self.runtime.end_run(
            success=True,
            narrative=f"Executed {steps} steps through path: {' -> '.join(path)}",
        )

        return ExecutionResult(
            success=True,
            output=committed_state,
            steps_executed=steps,
            path=path,
        )

    def _build_context(
        self,
        node_spec: NodeSpec,
        memory: SharedMemory,
        goal: Goal,
        input_data: dict[str, Any],
        max_tokens: int,
    ) -> NodeContext:
        scoped_memory = memory.with_permissions(
            read_keys=node_spec.input_keys,
            write_keys=node_spec.output_keys,
        )

        return NodeContext(
            runtime=self.runtime,
            node_id=node_spec.id,
            node_spec=node_spec,
            memory=scoped_memory,
            input_data=input_data,
            llm=self.llm,
            available_tools=[],
            goal_context=goal.to_prompt_context(),
            goal=goal,
            max_tokens=max_tokens,
        )

    def _get_node_implementation(self, node_spec: NodeSpec) -> NodeProtocol:
        if node_spec.id in self.node_registry:
            return self.node_registry[node_spec.id]
        raise RuntimeError(f"Node '{node_spec.id}' not registered")

    def register_node(self, node_id: str, implementation: NodeProtocol) -> None:
        self.node_registry[node_id] = implementation
