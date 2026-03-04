"""Agent graph construction for Universal Document Intake & Action Agent."""

from pathlib import Path

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult
from framework.graph.checkpoint_config import CheckpointConfig
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry
from framework.runtime.agent_runtime import AgentRuntime, create_agent_runtime
from framework.runtime.execution_stream import EntryPointSpec

# from .config import default_config, metadata  # Will define inline for now
from .nodes import (
    intake_node,
    classify_node,
    extract_node,
    merge_node,
    review_node,
)

# Goal definition
goal = Goal(
    id="universal-document-intake",
    name="Universal Document Intake & Action",
    description=(
        "Accept any business document (invoices, contracts, receipts, bank statements, forms), "
        "extract structured data, classify the document type, validate completeness, "
        "and route to the appropriate workflow with confidence-based human-in-the-loop."
    ),
    success_criteria=[
        SuccessCriterion(
            id="format-detection",
            description="Document format is correctly detected and supported",
            metric="format_accuracy",
            target="100%",
            weight=0.15,
        ),
        SuccessCriterion(
            id="classification-accuracy",
            description="Document is classified into the correct category",
            metric="classification_accuracy",
            target=">=85%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="extraction-completeness",
            description="All required fields for the document type are extracted",
            metric="field_completeness",
            target=">=80%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="routing-decision",
            description="Appropriate routing decision made based on confidence and validation",
            metric="routing_accuracy",
            target="100%",
            weight=0.20,
        ),
        SuccessCriterion(
            id="processing-speed",
            description="Document processed within reasonable time limits",
            metric="processing_time",
            target="<30s",
            weight=0.15,
        ),
    ],
    constraints=[
        Constraint(
            id="no-data-loss",
            description="Original document content must be preserved and accessible",
            constraint_type="functional",
            category="data_integrity",
        ),
        Constraint(
            id="confident-automation",
            description="Only auto-process documents with high confidence classification",
            constraint_type="quality",
            category="automation",
        ),
        Constraint(
            id="human-review-low-confidence",
            description="Route low confidence or complex documents to human review",
            constraint_type="functional",
            category="quality_control",
        ),
        Constraint(
            id="structured-output",
            description="All outputs must follow the ProcessedDocument schema",
            constraint_type="technical",
            category="data_format",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    classify_node,
    extract_node,
    merge_node,
    review_node,
]

# Edge definitions - with FANOUT/FANIN pattern
edges = [
    # intake -> fanout to parallel classification and extraction
    EdgeSpec(
        id="intake-to-classify",
        source="intake",
        target="classify",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="intake-to-extract",
        source="intake",
        target="extract",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # fanin: both branches -> merge
    EdgeSpec(
        id="classify-to-merge",
        source="classify",
        target="merge",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    EdgeSpec(
        id="extract-to-merge",
        source="extract",
        target="merge",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # merge -> review
    EdgeSpec(
        id="merge-to-review",
        source="merge",
        target="review",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
    # review -> intake (for continuous processing)
    EdgeSpec(
        id="review-to-intake",
        source="review",
        target="intake",
        condition=EdgeCondition.ON_SUCCESS,
        priority=1,
    ),
]

# Entry node and points
entry_node = "intake"
entry_points = {"start": "intake"}

# Pause nodes for human interaction
pause_nodes = ["review"]

# Terminal nodes (empty for forever-alive agent)
terminal_nodes = []

# Conversation mode for context continuity
conversation_mode = "continuous"

# Agent identity
identity_prompt = (
    "You are the Universal Document Intake & Action Agent. You process any business "
    "document by extracting structured data, classifying the document type, validating "
    "completeness, and routing to the appropriate workflow. You maintain high accuracy "
    "through confidence-based human-in-the-loop for complex or uncertain cases."
)

# Loop configuration
loop_config = {
    "max_iterations": 100,
    "max_tool_calls_per_turn": 30,
    "max_history_tokens": 32000,
}

# Runtime configuration
default_config = {
    "llm_provider": "litellm",
    "model": "claude-sonnet-4-5-20250929",
    "max_tokens": 4096,
    "storage_path": Path.home() / ".hive" / "agents" / "document_intake_agent",
}

metadata = {
    "name": "Universal Document Intake Agent",
    "version": "0.1.0",
    "description": (
        "Intelligent document processing agent that accepts any business document, "
        "extracts structured data, classifies the document type, validates completeness, "
        "and routes to the appropriate workflow with confidence-based automation."
    ),
    "author": "Hive Framework Contributor",
    "supported_formats": ["PDF", "Images (PNG/JPG/TIFF)", "CSV", "Text", "DOCX", "Email"],
    "supported_categories": [
        "Invoice", "Receipt", "Contract", "Bank Statement", "Tax Form",
        "Purchase Order", "Expense Report", "Onboarding Form", "Compliance Document"
    ],
}

# Agent class
class DocumentIntakeAgent:
    """Universal Document Intake & Action Agent."""

    def __init__(self, config=None):
        self.config = config or default_config
        self._runtime = None
        self._tool_registry = None

    @property
    def runtime(self) -> AgentRuntime:
        """Get or create the agent runtime."""
        if self._runtime is None:
            self._runtime = create_agent_runtime(
                storage_path=self.config["storage_path"],
                llm_provider=LiteLLMProvider(
                    model=self.config["model"],
                    max_tokens=self.config["max_tokens"],
                )
            )
        return self._runtime

    @property
    def tool_registry(self) -> ToolRegistry:
        """Get or create the tool registry."""
        if self._tool_registry is None:
            self._tool_registry = ToolRegistry()
        return self._tool_registry

    def validate(self) -> bool:
        """Validate the agent configuration."""
        try:
            # Validate goal
            assert goal.id is not None
            assert goal.name is not None
            assert len(goal.success_criteria) > 0

            # Validate nodes
            assert len(nodes) > 0
            node_ids = {node.id for node in nodes}

            # Validate edges
            for edge in edges:
                assert edge.source in node_ids, f"Source node {edge.source} not found"
                assert edge.target in node_ids, f"Target node {edge.target} not found"

            # Validate entry node
            assert entry_node in node_ids, f"Entry node {entry_node} not found"

            return True
        except Exception as e:
            print(f"Validation failed: {e}")
            return False

# Default agent instance
default_agent = DocumentIntakeAgent()