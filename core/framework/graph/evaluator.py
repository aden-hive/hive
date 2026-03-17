"""NodeEvaluator protocol for execution-time quality evaluation."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from framework.graph.node import NodeResult, NodeSpec
from framework.schemas.eval_report import EvalReport


@runtime_checkable
class NodeEvaluator(Protocol):
    """Structural protocol for node-level quality evaluation.

    Implementations receive the node specification, its execution result,
    and the current shared-memory snapshot.  They return an ``EvalReport``
    with per-dimension scores.

    The protocol is ``runtime_checkable`` so callers can use
    ``isinstance(obj, NodeEvaluator)`` if needed.
    """

    async def evaluate(
        self,
        node_spec: NodeSpec,
        node_result: NodeResult,
        memory: dict[str, Any],
    ) -> EvalReport: ...
