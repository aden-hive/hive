"""Graph structures: Goals, Nodes, Edges, and Flexible Execution."""

from framework.graph.goal import Goal, SuccessCriterion, Constraint, GoalStatus
from framework.graph.node import NodeSpec, NodeContext, NodeResult, NodeProtocol
from framework.graph.edge import EdgeSpec, EdgeCondition
from framework.graph.executor import GraphExecutor, ExecutionResult

# Error handling
from framework.graph.execution_errors import (
    ExecutionError,
    FatalExecutionError,
    RetriableExecutionError,
    ValidationExecutionError,
    DependencyExecutionError,
    UserExecutionError,
    ErrorCode,
    ErrorCategory,
    classify_error,
)

# Flexible execution (Worker-Judge pattern)
from framework.graph.plan import (
    Plan,
    PlanStep,
    ActionSpec,
    ActionType,
    StepStatus,
    Judgment,
    JudgmentAction,
    EvaluationRule,
    PlanExecutionResult,
    ExecutionStatus,
    load_export,
    # HITL (Human-in-the-loop)
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResult,
)
from framework.graph.judge import HybridJudge, create_default_judge
from framework.graph.worker_node import WorkerNode, StepExecutionResult
from framework.graph.flexible_executor import FlexibleGraphExecutor, ExecutorConfig
from framework.graph.code_sandbox import CodeSandbox, safe_exec, safe_eval

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
    # Executor (fixed graph)
    "GraphExecutor",
    "ExecutionResult",
    # Error handling
    "ExecutionError",
    "FatalExecutionError",
    "RetriableExecutionError",
    "ValidationExecutionError",
    "DependencyExecutionError",
    "UserExecutionError",
    "ErrorCode",
    "ErrorCategory",
    "classify_error",
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
