"""Framework-level worker monitoring package.

Provides the Worker Health Judge: a reusable secondary graph that attaches to
any worker agent runtime and monitors its execution health via periodic log
inspection. Emits structured EscalationTickets when degradation is detected.

Usage::

    from framework.monitoring import HEALTH_JUDGE_ENTRY_POINT, judge_goal, judge_graph
    from framework.tools.worker_monitoring_tools import register_worker_monitoring_tools

    # Register tools bound to the worker runtime's EventBus
    monitoring_registry = ToolRegistry()
    register_worker_monitoring_tools(monitoring_registry, worker_runtime._event_bus, storage_path)

    # Load judge as secondary graph on the worker runtime
    await worker_runtime.add_graph(
        graph_id="judge",
        graph=judge_graph,
        goal=judge_goal,
        entry_points={"health_check": HEALTH_JUDGE_ENTRY_POINT},
        storage_subpath="graphs/judge",
    )
"""

from .judge import HEALTH_JUDGE_ENTRY_POINT, judge_goal, judge_graph, judge_node

__all__ = [
    "HEALTH_JUDGE_ENTRY_POINT",
    "judge_goal",
    "judge_graph",
    "judge_node",
]
