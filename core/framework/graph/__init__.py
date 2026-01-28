"""Graph structures: Goals, Nodes, Edges, and Flexible Execution."""

from framework.graph.code_sandbox import CodeSandbox, safe_eval, safe_exec
from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.executor import GraphExecutor
from framework.graph.flexible_executor import ExecutorConfig, FlexibleGraphExecutor
from framework.graph.goal import Constraint, Goal, GoalStatus, SuccessCriterion
from framework.graph.judge import HybridJudge, create_default_judge
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec

# Flexible execution (Worker-Judge pattern)
from framework.graph.plan import (
    ActionSpec,
    ActionType,
    # HITL (Human-in-the-loop)
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResult,
    EvaluationRule,
    ExecutionStatus,
    Judgment,
    JudgmentAction,
    Plan,
    PlanExecutionResult,
    PlanStep,
    StepStatus,
    load_export,
)
from framework.graph.worker_node import StepExecutionResult, WorkerNode

__all__ = [
    # Goal
    "Goal",
    "SuccessCriterion",
    "Constraint",
    "GoalStatus",
    # Node
    "NodeSpec",
    "NodeContext",
    "NodeResult",
    "NodeProtocol",
    # Edge
    "EdgeSpec",
    "EdgeCondition",
    "GraphSpec",
    # Executor (fixed graph)
    "GraphExecutor",
    # Plan (flexible execution)
    "Plan",
    "PlanStep",
    "ActionSpec",
    "ActionType",
    "StepStatus",
    "Judgment",
    "JudgmentAction",
    "EvaluationRule",
    "PlanExecutionResult",
    "ExecutionStatus",
    "load_export",
    # HITL (Human-in-the-loop)
    "ApprovalDecision",
    "ApprovalRequest",
    "ApprovalResult",
    # Worker-Judge
    "HybridJudge",
    "create_default_judge",
    "WorkerNode",
    "StepExecutionResult",
    "FlexibleGraphExecutor",
    "ExecutorConfig",
    # Code Sandbox
    "CodeSandbox",
    "safe_exec",
    "safe_eval",
]
