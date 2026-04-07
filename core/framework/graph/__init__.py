"""Graph structures: Goals, Nodes, Edges, and Execution."""

from framework.graph.context import GraphContext
from framework.graph.context_handoff import ContextHandoff, HandoffContext
from framework.graph.conversation import ConversationStore, Message, NodeConversation
from framework.graph.edge import DEFAULT_MAX_TOKENS, EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.event_loop_node import (
    AgentLoop,
    JudgeProtocol,
    JudgeVerdict,
    LoopConfig,
    OutputAccumulator,
)
from framework.graph.executor import Orchestrator
from framework.graph.goal import Constraint, Goal, GoalStatus, SuccessCriterion
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec
from framework.graph.worker_agent import (
    Activation,
    FanOutTag,
    FanOutTracker,
    NodeWorker,
    WorkerCompletion,
    WorkerLifecycle,
)

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
    "DEFAULT_MAX_TOKENS",
    # Executor
    "Orchestrator",
    # Conversation
    "NodeConversation",
    "ConversationStore",
    "Message",
    # Event Loop
    "AgentLoop",
    "LoopConfig",
    "OutputAccumulator",
    "JudgeProtocol",
    "JudgeVerdict",
    # Context Handoff
    "ContextHandoff",
    "HandoffContext",
    # Worker Agent
    "NodeWorker",
    "WorkerLifecycle",
    "WorkerCompletion",
    "Activation",
    "FanOutTag",
    "FanOutTracker",
    "GraphContext",
]
