"""Graph structures: Goals, Nodes, Edges, and Flexible Execution."""

from framework.graph.client_io import (
    ActiveNodeClientIO,
    ClientIOGateway,
    InertNodeClientIO,
    NodeClientIO,
)
from framework.graph.code_sandbox import CodeSandbox, safe_eval, safe_exec
from framework.graph.context_handoff import ContextHandoff, HandoffContext
from framework.graph.conversation import ConversationStore, Message, NodeConversation
from framework.graph.edge import EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.event_loop_node import (
    EventLoopNode,
    JudgeProtocol,
    JudgeVerdict,
    LoopConfig,
    OutputAccumulator,
)
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
    # Conversation
    "NodeConversation",
    "ConversationStore",
    "Message",
    # Event Loop
    "EventLoopNode",
    "LoopConfig",
    "OutputAccumulator",
    "JudgeProtocol",
    "JudgeVerdict",
    # Context Handoff
    "ContextHandoff",
    "HandoffContext",
    # Client I/O
    "NodeClientIO",
    "ActiveNodeClientIO",
    "InertNodeClientIO",
    "ClientIOGateway",
]
