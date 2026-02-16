"""Agent graph construction for Contract Evaluation Agent."""

from framework.graph import EdgeSpec, EdgeCondition, Goal, SuccessCriterion, Constraint
from framework.graph.edge import GraphSpec
from framework.graph.executor import ExecutionResult, GraphExecutor
from framework.llm import LiteLLMProvider
from framework.runner.tool_registry import ToolRegistry

from .config import default_config, metadata
from .nodes import (
    intake_node,
    classify_node,
    confidentiality_node,
    liability_node,
    terms_node,
    synthesis_node_instance,
    human_review_node_instance,
    report_node,
)

# Goal definition
goal = Goal(
    id="contract-evaluation",
    name="Contract Evaluation & Risk Assessment",
    description=(
        "Analyze NDA contracts to identify risk factors, extract key terms, "
        "check compliance, and generate comprehensive evaluation reports. "
        "Escalate high-risk contracts to human legal reviewers."
    ),
    success_criteria=[
        SuccessCriterion(
            id="extraction-completeness",
            description="All key contract elements extracted",
            metric="extraction_coverage",
            target="90%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="risk-identification",
            description="Critical risk factors identified",
            metric="risk_detection_rate",
            target="85%",
            weight=0.30,
        ),
        SuccessCriterion(
            id="report-quality",
            description="Clear, actionable reports generated",
            metric="report_completeness",
            target="95%",
            weight=0.25,
        ),
        SuccessCriterion(
            id="human-escalation",
            description="Appropriate escalation to human reviewers",
            metric="escalation_accuracy",
            target="90%",
            weight=0.20,
        ),
    ],
    constraints=[
        Constraint(
            id="no-legal-advice",
            description="Agent provides analysis only, not legal advice",
            constraint_type="functional",
            category="disclaimer",
        ),
        Constraint(
            id="human-oversight",
            description="High-risk contracts must be reviewed by humans",
            constraint_type="functional",
            category="oversight",
        ),
        Constraint(
            id="accuracy-over-speed",
            description="Prioritize accuracy in risk assessment",
            constraint_type="quality",
            category="accuracy",
        ),
    ],
)

# Node list
nodes = [
    intake_node,
    classify_node,
    confidentiality_node,
    liability_node,
    terms_node,
    synthesis_node_instance,
    human_review_node_instance,
    report_node,
]

# Edge definitions
edges = [
    # intake -> classification
    EdgeSpec(
        id="intake-to-classify",
        source="document_ingestion",
        target="classification",
        condition=EdgeCondition.ALWAYS,
        priority=1,
    ),
    # classification -> parallel analysis nodes (if NDA)
    EdgeSpec(
        id="classify-to-confidentiality",
        source="classification",
        target="confidentiality_analysis",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="is_nda == True",
        priority=1,
    ),
    EdgeSpec(
        id="classify-to-liability",
        source="classification",
        target="liability_analysis",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="is_nda == True",
        priority=1,
    ),
    EdgeSpec(
        id="classify-to-terms",
        source="classification",
        target="term_obligations",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="is_nda == True",
        priority=1,
    ),
    # All analysis nodes -> synthesis
    EdgeSpec(
        id="confidentiality-to-synthesis",
        source="confidentiality_analysis",
        target="synthesis",
        condition=EdgeCondition.ALWAYS,
        priority=1,
    ),
    EdgeSpec(
        id="liability-to-synthesis",
        source="liability_analysis",
        target="synthesis",
        condition=EdgeCondition.ALWAYS,
        priority=1,
    ),
    EdgeSpec(
        id="terms-to-synthesis",
        source="term_obligations",
        target="synthesis",
        condition=EdgeCondition.ALWAYS,
        priority=1,
    ),
    # synthesis -> human_review (if needed) or report
    EdgeSpec(
        id="synthesis-to-human-review",
        source="synthesis",
        target="human_review",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="needs_human_review == True",
        priority=1,
    ),
    EdgeSpec(
        id="synthesis-to-report",
        source="synthesis",
        target="report_generation",
        condition=EdgeCondition.CONDITIONAL,
        condition_expr="needs_human_review == False",
        priority=2,
    ),
    # human_review -> report
    EdgeSpec(
        id="human-review-to-report",
        source="human_review",
        target="report_generation",
        condition=EdgeCondition.ALWAYS,
        priority=1,
    ),
]

# Graph configuration
entry_node = "document_ingestion"
entry_points = {"start": "document_ingestion"}
pause_nodes = ["human_review"]  # Pause for human input
terminal_nodes = ["report_generation"]


class ContractEvaluationAgent:
    """Contract Evaluation Agent — NDA analysis pipeline with HITL review.
    
    Flow: intake -> classify -> [confidentiality, liability, terms] -> synthesis
                                                                           |
                                                                     needs review?
                                                                    /            \\
                                                           human_review        report
                                                                    \\            /
                                                                      report
    """

    def __init__(self, config=None):
        self.config = config or default_config
        self.metadata = metadata
        self.executor = None
        self.tool_registry = None
        self.llm_provider = None

    def _build_graph(self):
        """Build the GraphSpec."""
        return GraphSpec(
            nodes={node.id: node for node in nodes},
            edges=edges,
            entry_points=entry_points,
            terminal_nodes=terminal_nodes,
            pause_nodes=pause_nodes,
            goal=goal,
        )

    def _setup(self):
        """Set up the executor with all components."""
        # Initialize LLM provider
        self.llm_provider = LiteLLMProvider(
            model=self.config.model,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            api_key=self.config.api_key,
            api_base=self.config.api_base,
        )

        # Initialize tool registry (if needed)
        self.tool_registry = ToolRegistry()

        # Build graph
        graph_spec = self._build_graph()

        # Create executor
        self.executor = GraphExecutor(
            graph_spec=graph_spec,
            llm_provider=self.llm_provider,
            tool_registry=self.tool_registry,
        )

    def start(self):
        """Set up the agent (initialize executor and tools)."""
        self._setup()

    def stop(self):
        """Clean up resources."""
        pass

    async def trigger_and_wait(
        self,
        entry_point: str,
        input_data: dict,
        timeout: float | None = None,
        session_state: dict | None = None,
    ) -> ExecutionResult:
        """Execute the graph and wait for completion."""
        if not self.executor:
            self.start()

        result = await self.executor.execute(
            entry_point=entry_point,
            input_data=input_data,
            session_state=session_state,
            timeout=timeout,
        )

        return result

    async def run(self, context: dict, session_state=None) -> dict:
        """Run the agent (convenience method for single execution)."""
        result = await self.trigger_and_wait(
            entry_point="start",
            input_data=context,
            session_state=session_state,
        )

        return result.final_output if result else {}

    def info(self):
        """Get agent information."""
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "description": self.metadata.description,
            "contract_types_supported": self.metadata.contract_types_supported,
            "nodes": [node.id for node in nodes],
            "entry_point": entry_node,
            "terminal_nodes": terminal_nodes,
        }

    def validate(self):
        """Validate agent structure."""
        graph = self._build_graph()
        # Add validation logic here
        return True


# Create default instance
default_agent = ContractEvaluationAgent()
