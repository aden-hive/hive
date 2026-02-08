"""Domain models for Support Debugger Agent.

These Pydantic models define the typed data contracts that flow between nodes
in the investigation graph. They serve as:
- Schema documentation for each node's output shape
- Validation targets for LLM-generated structured output
- Type-safe contracts for tool return values
- Reference for Phase 3 prompt construction

Note: For event_loop nodes, output_model is metadata (EventLoopNode does not
validate against it at runtime). The models document the expected shape of
values stored via set_output().
"""

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------


class TicketInput(BaseModel):
    """A support ticket to investigate."""

    subject: str = Field(description="Ticket subject line")
    description: str = Field(
        description="Full ticket description with technical details"
    )


# ---------------------------------------------------------------------------
# Node outputs
# ---------------------------------------------------------------------------


class TechnicalContext(BaseModel):
    """Technical context extracted from a support ticket.

    Produced by: build-context node
    Stored at: SharedMemory["technical_context"]
    """

    product: str | None = Field(
        default=None, description="Product name (e.g., Automate, App Automate)"
    )
    platform: str | None = Field(
        default=None, description="Platform or OS (e.g., Windows, macOS, Linux)"
    )
    framework: str | None = Field(
        default=None, description="Test framework (e.g., Pytest, Selenium, Cypress)"
    )
    language: str | None = Field(
        default=None, description="Programming language (e.g., Python, Java)"
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confidence in context extraction"
    )


class Hypothesis(BaseModel):
    """A single hypothesis explaining the reported issue.

    Part of: SharedMemory["hypotheses"] (list)
    """

    description: str = Field(description="What this hypothesis claims")
    category: str = Field(
        description="Category: app, test, config, dependency, network, infra"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Current confidence score")
    required_evidence: list[str] = Field(
        default_factory=list,
        description="What evidence would confirm or refute this hypothesis",
    )
    resolved: bool = Field(
        default=False, description="Whether this hypothesis has been resolved"
    )


class Evidence(BaseModel):
    """A single piece of evidence gathered during investigation.

    Attached to: ToolResult.evidence (list)
    """

    source_type: str = Field(
        description="Evidence source: docs, logs, tickets, slack, jira"
    )
    source_id: str = Field(description="Identifier: URL, ticket ID, session ID")
    snippet: str = Field(description="Exact quoted text or log lines")
    metadata: dict[str, str] = Field(
        default_factory=dict, description="Additional context"
    )


class ToolResult(BaseModel):
    """Result from a single tool execution during investigation.

    Part of: SharedMemory["evidence"] (list)

    Note: This is a domain model, distinct from framework.llm.provider.ToolResult
    which represents the low-level tool call response.
    """

    tool_name: str = Field(description="Name of the tool that produced this result")
    query_used: str = Field(description="Exact query or parameters used")
    summary: str = Field(description="Condensed findings for LLM reasoning")
    evidence: list[Evidence] = Field(
        default_factory=list, description="Supporting evidence items"
    )
    confidence: float = Field(ge=0.0, le=1.0, description="Relevance confidence")


class InvestigationState(BaseModel):
    """Accumulated state of the investigation loop.

    Represents the combined output of investigate + refine-hypotheses nodes.
    Used to track convergence and determine loop termination.
    """

    hypotheses: list[Hypothesis] = Field(
        default_factory=list, description="Current hypotheses"
    )
    evidence: list[ToolResult] = Field(
        default_factory=list, description="All gathered evidence"
    )
    investigation_complete: bool = Field(
        default=False,
        description="True when top hypothesis confidence >= 0.9 with sufficient separation",
    )
    iteration: int = Field(default=0, description="Current investigation iteration")


class FinalResponse(BaseModel):
    """Final technical response with root cause and fix steps.

    Produced by: generate-response node
    Stored at: SharedMemory["final_response"]
    """

    root_cause: str = Field(description="Identified root cause of the issue")
    explanation: str = Field(
        description="Technical explanation of why the issue occurs"
    )
    fix_steps: list[str] = Field(description="Ordered steps to resolve the issue")
    config_snippet: str | None = Field(
        default=None, description="Example config if applicable"
    )
    validation_steps: list[str] = Field(
        default_factory=list,
        description="Steps to verify the fix worked",
    )
    confidence: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Confidence in the diagnosis"
    )
