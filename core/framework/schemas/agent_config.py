"""Declarative agent configuration schema.

Allows defining agents via JSON/YAML config files instead of Python modules.
The ``AgentConfig`` model is the top-level schema loaded from ``agent.json``.
The runner detects this format by checking for a ``name`` key at the top level.

Template variables
------------------
System prompts and identity_prompt support ``{{variable_name}}`` placeholders.
These are resolved at load time from ``AgentConfig.variables``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolAccessConfig(BaseModel):
    """Declarative tool access policy.

    Controls which tools a node/agent has access to.

    * ``explicit`` -- only tools listed in ``allowed`` (default; empty = zero tools).
    * ``none``     -- no tools at all.

    ``all`` is not permitted — agents must declare every tool they use.
    """

    model_config = ConfigDict(populate_by_name=True)

    policy: str = Field(
        default="explicit",
        description="One of: 'explicit', 'none'. 'all' is not allowed.",
    )
    allowed: list[str] = Field(
        default_factory=list,
        description="Tool names when policy='explicit'.",
        alias="tools",
    )
    denied: list[str] = Field(
        default_factory=list,
        description="Tool names to deny (applied after allowed).",
    )

    @model_validator(mode="after")
    def _reject_policy_all(self) -> ToolAccessConfig:
        if self.policy == "all":
            raise ValueError(
                "tool policy 'all' is not allowed — "
                "list every tool explicitly in 'allowed' instead. "
                "This ensures agents only see the tools they need."
            )
        return self


class NodeConfig(BaseModel):
    """Declarative node definition."""

    id: str
    name: str | None = None
    description: str | None = None
    node_type: str = Field(
        default="event_loop",
        description="event_loop",
    )
    system_prompt: str | None = None
    tools: ToolAccessConfig = Field(default_factory=ToolAccessConfig)
    model: str | None = None
    input_keys: list[str] = Field(default_factory=list)
    output_keys: list[str] = Field(default_factory=list)
    nullable_output_keys: list[str] = Field(default_factory=list)
    max_iterations: int = 30
    max_node_visits: int = 1
    client_facing: bool = False
    success_criteria: str | None = None
    failure_criteria: str | None = None
    skip_judge: bool = False
    max_retries: int | None = None


class EdgeConfig(BaseModel):
    """Declarative edge definition."""

    from_node: str = Field(description="Source node ID.")
    to_node: str = Field(description="Target node ID.")
    condition: str = Field(
        default="on_success",
        description="always | on_success | on_failure | conditional | llm_decide",
    )
    condition_expr: str | None = None
    input_mapping: dict[str, str] = Field(default_factory=dict)
    priority: int = 1


class GoalConfig(BaseModel):
    """Simplified goal definition for declarative config."""

    description: str
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class EntryPointConfig(BaseModel):
    """Entry point configuration."""

    id: str = "default"
    name: str = "Default"
    entry_node: str | None = None  # defaults to AgentConfig.entry_node
    trigger_type: str = Field(
        default="manual",
        description="manual | scheduled | timer",
    )
    trigger_config: dict = Field(default_factory=dict)
    isolation_level: str = "shared"
    max_concurrent: int | None = None


class MCPServerRef(BaseModel):
    """Reference to an MCP server to connect for this agent."""

    name: str
    config: dict | None = None


class MetadataConfig(BaseModel):
    """Agent metadata for display / intro messages."""

    intro_message: str = ""


class AgentConfig(BaseModel):
    """Top-level declarative agent configuration.

    Load from ``agent.json`` and pass to
    :func:`framework.loader.agent_loader.load_agent_config` to build
    the worker spec.

    Example (YAML)::

        name: lead-enrichment-agent
        version: 1.0.0
        variables:
          spreadsheet_id: "1ZVx..."
          sheet_name: "contacts"
        goal:
          description: "Enrich leads in Google Sheets"
          success_criteria:
            - "All unprocessed leads enriched"
          constraints:
            - "Browser-only research"
        identity_prompt: |
          You are the Lead Enrichment Agent...
        nodes:
          - id: start
            tools: {policy: explicit, allowed: [google_sheets_get_values]}
            system_prompt: |
              Spreadsheet ID: {{spreadsheet_id}}
              ...
    """

    name: str
    version: str = "1.0.0"
    description: str | None = None
    metadata: MetadataConfig = Field(default_factory=MetadataConfig)

    # Template variables -- substituted into prompts via {{var_name}}
    variables: dict[str, str] = Field(default_factory=dict)

    # Goal
    goal: GoalConfig

    # Graph structure
    nodes: list[NodeConfig]
    edges: list[EdgeConfig]
    entry_node: str
    terminal_nodes: list[str] = Field(default_factory=list)
    pause_nodes: list[str] = Field(default_factory=list)

    # Entry points (if omitted, a single "default" manual entry is created)
    entry_points: list[EntryPointConfig] = Field(default_factory=list)

    # Agent-level tool defaults (nodes inherit unless they override)
    tools: ToolAccessConfig = Field(default_factory=ToolAccessConfig)
    mcp_servers: list[MCPServerRef] = Field(default_factory=list)

    # LLM / execution
    model: str | None = None
    max_tokens: int = 4096
    conversation_mode: str = "continuous"
    identity_prompt: str = ""
    loop_config: dict = Field(
        default_factory=lambda: {
            "max_iterations": 100,
            "max_tool_calls_per_turn": 30,
            "max_context_tokens": 32000,
        },
    )

    # Pipeline overrides (per-agent, merged with global config)
    pipeline: dict = Field(
        default_factory=dict,
        description="Per-agent pipeline stage overrides. Same format as global pipeline config.",
    )

    # Resource limits
    max_cost_per_run: float | None = None
