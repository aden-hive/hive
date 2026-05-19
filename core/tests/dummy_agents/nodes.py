"""Minimal helper nodes for deterministic control-flow tests.

Most tests use real EventLoopNode with real LLM calls. These helpers
exist only for tests that need predictable failure/success patterns
(retry, feedback loop, parallel failure modes).
"""

from __future__ import annotations

from framework.graph.node import NodeContext, NodeProtocol, NodeResult


class SuccessNode(NodeProtocol):
    """Always succeeds with configurable output dict."""

    def __init__(self, output: dict | None = None):
        self._output = output or {"status": "ok"}
        self.executed = False
        self.execute_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.executed = True
        self.execute_count += 1
        return NodeResult(success=True, output=self._output, tokens_used=1, latency_ms=1)


class FailNode(NodeProtocol):
    """Always fails with configurable error."""

    def __init__(self, error: str = "node failed"):
        self._error = error
        self.attempt_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempt_count += 1
        return NodeResult(success=False, error=self._error)


class FlakyNode(NodeProtocol):
    """Fails N times then succeeds. For retry tests."""

    def __init__(self, fail_times: int = 2, output: dict | None = None):
        self.fail_times = fail_times
        self._output = output or {"status": "recovered"}
        self.attempt_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        self.attempt_count += 1
        if self.attempt_count <= self.fail_times:
            return NodeResult(success=False, error=f"fail #{self.attempt_count}")
        return NodeResult(success=True, output=self._output, tokens_used=1, latency_ms=1)


class StatefulNode(NodeProtocol):
    """Returns different outputs on successive calls. For feedback loop tests."""

    def __init__(self, outputs: list[NodeResult]):
        self._outputs = outputs
        self.call_count = 0

    async def execute(self, ctx: NodeContext) -> NodeResult:
        idx = min(self.call_count, len(self._outputs) - 1)
        self.call_count += 1
        return self._outputs[idx]
