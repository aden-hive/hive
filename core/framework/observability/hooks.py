"""
Observability hooks protocol and implementations.

This module defines the ObservabilityHooks protocol that all hook implementations
must follow, as well as a no-op implementation for zero overhead when disabled.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any

from framework.observability.types import (
    DecisionData,
    EdgeTraversalData,
    NodeContext,
    NodeResult,
    RetryData,
    RunContext,
    RunOutcome,
)

logger = logging.getLogger(__name__)


class ObservabilityHooks(ABC):
    """
    Abstract base class for observability hooks.

    Hook implementations receive callbacks at key execution points in the
    agent lifecycle. Implementations can:
    - Log events to console or files
    - Export metrics to monitoring systems
    - Create distributed traces
    - Send events to external services

    All methods are async to support non-blocking I/O. The default
    implementations are no-ops, so subclasses only need to override
    the methods they care about.

    Example:
        class MyHooks(ObservabilityHooks):
            async def on_run_start(self, context: RunContext) -> None:
                print(f"Run started: {context.run_id}")

            async def on_node_complete(
                self, context: NodeContext, result: NodeResult
            ) -> None:
                print(f"Node {context.node_id}: {result.success}")
    """

    @abstractmethod
    async def on_run_start(self, context: RunContext) -> None:
        """
        Called when a run starts.

        Args:
            context: Context containing run metadata like run_id, goal_id, etc.
        """
        pass

    @abstractmethod
    async def on_run_complete(self, context: RunContext, outcome: RunOutcome) -> None:
        """
        Called when a run completes.

        Args:
            context: Context containing run metadata.
            outcome: The final outcome of the run.
        """
        pass

    @abstractmethod
    async def on_node_start(self, context: NodeContext) -> None:
        """
        Called when a node starts execution.

        Args:
            context: Context containing node metadata.
        """
        pass

    @abstractmethod
    async def on_node_complete(self, context: NodeContext, result: NodeResult) -> None:
        """
        Called when a node completes execution.

        Args:
            context: Context containing node metadata.
            result: The result of the node execution.
        """
        pass

    @abstractmethod
    async def on_node_error(
        self, context: NodeContext, error: str, result: NodeResult | None = None
    ) -> None:
        """
        Called when a node encounters an error.

        Args:
            context: Context containing node metadata.
            error: The error message.
            result: Optional partial result if available.
        """
        pass

    @abstractmethod
    async def on_decision_made(self, decision: DecisionData) -> None:
        """
        Called when the agent makes a decision.

        Args:
            decision: Data about the decision including options and reasoning.
        """
        pass

    @abstractmethod
    async def on_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: str,
        context: NodeContext,
        is_error: bool = False,
        latency_ms: int = 0,
    ) -> None:
        """
        Called when a tool is invoked.

        Args:
            tool_name: Name of the tool being called.
            args: Arguments passed to the tool.
            result: Result returned by the tool.
            context: Node context where the tool was called.
            is_error: Whether the tool call resulted in an error.
            latency_ms: Time taken for the tool call in milliseconds.
        """
        pass

    @abstractmethod
    async def on_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        context: NodeContext,
        latency_ms: int = 0,
        cached_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        """
        Called when an LLM call is made.

        Args:
            model: The model identifier (e.g., "claude-3-opus-20240229").
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            context: Node context where the LLM was called.
            latency_ms: Time taken for the LLM call in milliseconds.
            cached_tokens: Number of tokens served from cache.
            error: Error message if the call failed.
        """
        pass

    @abstractmethod
    async def on_edge_traversed(self, data: EdgeTraversalData) -> None:
        """
        Called when an edge is traversed in the graph.

        Args:
            data: Data about the edge traversal.
        """
        pass

    @abstractmethod
    async def on_retry(self, data: RetryData) -> None:
        """
        Called when a node is retried.

        Args:
            data: Data about the retry including retry count and error.
        """
        pass


class NoOpHooks(ObservabilityHooks):
    """
    No-op implementation of observability hooks.

    This implementation does nothing and has zero overhead. It's used
    when observability is disabled or when no exporters are configured.

    All methods are pass statements that return immediately.
    """

    async def on_run_start(self, context: RunContext) -> None:
        pass

    async def on_run_complete(self, context: RunContext, outcome: RunOutcome) -> None:
        pass

    async def on_node_start(self, context: NodeContext) -> None:
        pass

    async def on_node_complete(self, context: NodeContext, result: NodeResult) -> None:
        pass

    async def on_node_error(
        self, context: NodeContext, error: str, result: NodeResult | None = None
    ) -> None:
        pass

    async def on_decision_made(self, decision: DecisionData) -> None:
        pass

    async def on_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: str,
        context: NodeContext,
        is_error: bool = False,
        latency_ms: int = 0,
    ) -> None:
        pass

    async def on_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        context: NodeContext,
        latency_ms: int = 0,
        cached_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        pass

    async def on_edge_traversed(self, data: EdgeTraversalData) -> None:
        pass

    async def on_retry(self, data: RetryData) -> None:
        pass


class CompositeHooks(ObservabilityHooks):
    """
    Composite hooks that delegates to multiple hook implementations.

    This allows combining multiple exporters/hooks together, where each
    hook receives all events.

    Example:
        hooks = CompositeHooks([
            ConsoleExporter(),
            FileExporter(path="logs/observability.jsonl"),
        ])
    """

    def __init__(self, hooks: list[ObservabilityHooks]) -> None:
        """
        Initialize composite hooks.

        Args:
            hooks: List of hook implementations to delegate to.
        """
        self._hooks = hooks

    def add_hook(self, hook: ObservabilityHooks) -> None:
        """
        Add a hook to the composite.

        Args:
            hook: Hook implementation to add.
        """
        self._hooks.append(hook)

    async def on_run_start(self, context: RunContext) -> None:
        for hook in self._hooks:
            try:
                await hook.on_run_start(context)
            except Exception as e:
                logger.warning(f"Hook error in on_run_start: {e}")

    async def on_run_complete(self, context: RunContext, outcome: RunOutcome) -> None:
        for hook in self._hooks:
            try:
                await hook.on_run_complete(context, outcome)
            except Exception as e:
                logger.warning(f"Hook error in on_run_complete: {e}")

    async def on_node_start(self, context: NodeContext) -> None:
        for hook in self._hooks:
            try:
                await hook.on_node_start(context)
            except Exception as e:
                logger.warning(f"Hook error in on_node_start: {e}")

    async def on_node_complete(self, context: NodeContext, result: NodeResult) -> None:
        for hook in self._hooks:
            try:
                await hook.on_node_complete(context, result)
            except Exception as e:
                logger.warning(f"Hook error in on_node_complete: {e}")

    async def on_node_error(
        self, context: NodeContext, error: str, result: NodeResult | None = None
    ) -> None:
        for hook in self._hooks:
            try:
                await hook.on_node_error(context, error, result)
            except Exception as e:
                logger.warning(f"Hook error in on_node_error: {e}")

    async def on_decision_made(self, decision: DecisionData) -> None:
        for hook in self._hooks:
            try:
                await hook.on_decision_made(decision)
            except Exception as e:
                logger.warning(f"Hook error in on_decision_made: {e}")

    async def on_tool_call(
        self,
        tool_name: str,
        args: dict[str, Any],
        result: str,
        context: NodeContext,
        is_error: bool = False,
        latency_ms: int = 0,
    ) -> None:
        for hook in self._hooks:
            try:
                await hook.on_tool_call(tool_name, args, result, context, is_error, latency_ms)
            except Exception as e:
                logger.warning(f"Hook error in on_tool_call: {e}")

    async def on_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        context: NodeContext,
        latency_ms: int = 0,
        cached_tokens: int = 0,
        error: str | None = None,
    ) -> None:
        for hook in self._hooks:
            try:
                await hook.on_llm_call(
                    model, input_tokens, output_tokens, context, latency_ms, cached_tokens, error
                )
            except Exception as e:
                logger.warning(f"Hook error in on_llm_call: {e}")

    async def on_edge_traversed(self, data: EdgeTraversalData) -> None:
        for hook in self._hooks:
            try:
                await hook.on_edge_traversed(data)
            except Exception as e:
                logger.warning(f"Hook error in on_edge_traversed: {e}")

    async def on_retry(self, data: RetryData) -> None:
        for hook in self._hooks:
            try:
                await hook.on_retry(data)
            except Exception as e:
                logger.warning(f"Hook error in on_retry: {e}")
