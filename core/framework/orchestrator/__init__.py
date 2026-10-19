"""Orchestrator layer -- how agents are composed via graphs.

Lazy imports to avoid circular dependencies with graph/event_loop/*.
"""


def __getattr__(name: str):
    if name in ("GraphContext",):
        from framework.orchestrator.context import GraphContext

        return GraphContext
    if name in ("DEFAULT_MAX_TOKENS", "EdgeCondition", "EdgeSpec", "GraphSpec"):
        from framework.orchestrator import edge as _e

        return getattr(_e, name)
    if name in ("Orchestrator", "ExecutionResult"):
        from framework.orchestrator import orchestrator as _o

        return getattr(_o, name)
    if name in ("Constraint", "Goal", "GoalStatus", "SuccessCriterion"):
        from framework.orchestrator import goal as _g

        return getattr(_g, name)
    if name in ("DataBuffer", "NodeContext", "NodeProtocol", "NodeResult", "NodeSpec"):
        from framework.orchestrator import node as _n

        return getattr(_n, name)
    if name in (
        "NodeWorker",
        "Activation",
        "FanOutTag",
        "FanOutTracker",
        "WorkerCompletion",
        "WorkerLifecycle",
    ):
        from framework.orchestrator import node_worker as _nw

        return getattr(_nw, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
