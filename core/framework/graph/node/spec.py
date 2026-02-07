"""Node specification for graph nodes.

Defines the declarative specification of a node - what it does,
what it needs, and what it produces.
"""

from pydantic import BaseModel, Field


class NodeSpec(BaseModel):
    """Specification for a node in the graph.

    This is the declarative definition of a node - what it does,
    what it needs, and what it produces. The actual implementation
    is separate (NodeProtocol).

    Example:
        NodeSpec(
            id="calculator",
            name="Calculator Node",
            description="Performs mathematical calculations",
            node_type="llm_tool_use",
            input_keys=["expression"],
            output_keys=["result"],
            tools=["calculate", "math_function"],
            system_prompt="You are a calculator..."
        )
    """

    id: str
    name: str
    description: str

    # Node behavior type
    node_type: str = Field(
        default="llm_tool_use",
        description=(
            "Type: 'event_loop', 'function', 'router', 'human_input'. "
            "Deprecated: 'llm_tool_use', 'llm_generate' (use 'event_loop' instead)."
        ),
    )

    # Data flow
    input_keys: list[str] = Field(
        default_factory=list, description="Keys this node reads from shared memory or input"
    )
    output_keys: list[str] = Field(
        default_factory=list, description="Keys this node writes to shared memory or output"
    )
    nullable_output_keys: list[str] = Field(
        default_factory=list,
        description="Output keys that can be None without triggering validation errors",
    )

    # Optional schemas for validation and cleansing
    input_schema: dict[str, dict] = Field(
        default_factory=dict,
        description=(
            "Optional schema for input validation. "
            "Format: {key: {type: 'string', required: True, description: '...'}}"
        ),
    )
    output_schema: dict[str, dict] = Field(
        default_factory=dict,
        description=(
            "Optional schema for output validation. "
            "Format: {key: {type: 'dict', required: True, description: '...'}}"
        ),
    )

    # For LLM nodes
    system_prompt: str | None = Field(default=None, description="System prompt for LLM nodes")
    tools: list[str] = Field(default_factory=list, description="Tool names this node can use")
    model: str | None = Field(
        default=None, description="Specific model to use (defaults to graph default)"
    )

    # For function nodes
    function: str | None = Field(
        default=None, description="Function name or path for function nodes"
    )

    # For router nodes
    routes: dict[str, str] = Field(
        default_factory=dict, description="Condition -> target_node_id mapping for routers"
    )

    # Retry behavior
    max_retries: int = Field(default=3)
    retry_on: list[str] = Field(default_factory=list, description="Error types to retry on")

    # Visit limits (for feedback/callback edges)
    max_node_visits: int = Field(
        default=1,
        description=(
            "Max times this node executes in one graph run. "
            "Set >1 for feedback loops. 0 = unlimited (max_steps guards)."
        ),
    )

    # Pydantic model for output validation
    output_model: type[BaseModel] | None = Field(
        default=None,
        description=(
            "Optional Pydantic model class for validating and parsing LLM output. "
            "When set, the LLM response will be validated against this model."
        ),
    )
    max_validation_retries: int = Field(
        default=2,
        description="Maximum retries when Pydantic validation fails (with feedback to LLM)",
    )

    # Client-facing behavior
    client_facing: bool = Field(
        default=False,
        description="If True, this node streams output to the end user and can request input.",
    )

    model_config = {"extra": "allow", "arbitrary_types_allowed": True}


__all__ = ["NodeSpec"]
