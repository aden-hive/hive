"""Graph structures -- backward-compat re-export package.

Real code lives in framework.orchestrator/ and framework.agent_loop/.
This package exists so old ``from framework.graph import X`` still works.
"""

# Lazy imports to avoid circular dependencies.
# The orchestrator/ and agent_loop/ packages import from graph/event_loop/*
# which would create import cycles if we eagerly loaded everything here.


def __getattr__(name: str):
    """Lazy re-export from new locations."""
    # Orchestrator layer
    _orchestrator_names = {
        "GraphContext", "EdgeCondition", "EdgeSpec", "GraphSpec",
        "DEFAULT_MAX_TOKENS", "Orchestrator", "ExecutionResult",
        "Goal", "SuccessCriterion", "Constraint", "GoalStatus",
        "NodeSpec", "NodeContext", "NodeProtocol", "NodeResult",
        "DataBuffer", "NodeWorker", "Activation", "FanOutTag",
        "FanOutTracker", "WorkerCompletion", "WorkerLifecycle",
    }
    if name in _orchestrator_names:
        import framework.orchestrator as _o
        return getattr(_o, name)

    # Agent loop layer
    _agent_loop_names = {
        "AgentLoop", "EventLoopNode", "LoopConfig", "OutputAccumulator",
        "JudgeProtocol", "JudgeVerdict",
        "ConversationStore", "Message", "NodeConversation",
    }
    if name in _agent_loop_names:
        import framework.agent_loop as _a
        return getattr(_a, name)

    # Local modules that stayed in graph/
    _local = {
        "ContextHandoff", "HandoffContext",
    }
    if name in _local:
        from framework.graph.context_handoff import ContextHandoff, HandoffContext
        return {"ContextHandoff": ContextHandoff, "HandoffContext": HandoffContext}[name]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
