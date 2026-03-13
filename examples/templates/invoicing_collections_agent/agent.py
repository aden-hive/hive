"""Agent graph construction for Invoicing & Collections Agent."""

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.runtime.event_bus import EventBus
from framework.runtime.core import Runtime
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import (
    scan_invoices_node,
    classify_overdue_node,
    send_reminders_node,
    judge_reminders_node,
    escalate_review_node,
    generate_report_node
)