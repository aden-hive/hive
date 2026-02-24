"""Graph structures: Goals, Nodes, Edges, and Execution."""

from framework.graph.client_io import (
    ActiveNodeClientIO,
    ClientIOGateway,
    InertNodeClientIO,
    NodeClientIO,
)
from framework.graph.context_handoff import ContextHandoff, HandoffContext
from framework.graph.conversation import ConversationStore, Message, NodeConversation
from framework.graph.edge import DEFAULT_MAX_TOKENS, EdgeCondition, EdgeSpec, GraphSpec
from framework.graph.event_loop_node import (
    EventLoopNode,
    JudgeProtocol,
    JudgeVerdict,
    LoopConfig,
    OutputAccumulator,
)
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Constraint, Goal, GoalStatus, SuccessCriterion
from framework.graph.node import NodeContext, NodeProtocol, NodeResult, NodeSpec

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
    "GraphExecutor",
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
