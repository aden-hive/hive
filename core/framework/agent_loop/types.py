"""Core types for the agent loop — the execution primitive of the colony.

AgentSpec:    Declarative definition of what an agent does.
AgentContext: Everything an agent loop needs to execute.
AgentResult:  What comes out of an agent loop execution.
AgentProtocol: Interface that all agent implementations must satisfy.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from framework.llm.provider import LLMProvider, Tool
from framework.tracker.decision_tracker import DecisionTracker


class AgentSpec(BaseModel):
    """Declarative definition of an agent's capabilities and configuration.

    This is the blueprint from which AgentLoop instances are created.
    Workers in a colony are exact copies of the queen's AgentSpec.
    """

    id: str
    name: str
    description: str

    agent_type: str = Field(
        default="event_loop",
        description="Type: 'event_loop' (recommended), 'gcu' (browser automation).",
    )

    input_keys: list[str] = Field(
        default_factory=list,
        description="Keys this agent reads from input data",
    )
    output_keys: list[str] = Field(
        default_factory=list,
        description="Keys this agent produces as output",
    )
    nullable_output_keys: list[str] = Field(
        default_factory=list,
        description="Output keys that can be None without triggering validation errors",
    )

    input_schema: dict[str, dict] = Field(
        default_factory=dict,
        description="Optional schema for input validation.",
    )
    output_schema: dict[str, dict] = Field(
        default_factory=dict,
        description="Optional schema for output validation.",
    )

    system_prompt: str | None = Field(default=None, description="System prompt for the LLM")
    tools: list[str] = Field(default_factory=list, description="Tool names this agent can use")
    tool_access_policy: str = Field(
        default="explicit",
        description=(
            "'all' = all tools from registry, "
            "'explicit' = only tools listed in `tools` (default), "
            "'none' = no tools at all."
        ),
    )
    model: str | None = Field(default=None, description="Specific model override")

    function: str | None = Field(default=None, description="Function name or path")
    routes: dict[str, str] = Field(default_factory=dict, description="Condition -> target mapping")

    max_retries: int = Field(default=3)
    retry_on: list[str] = Field(default_factory=list, description="Error types to retry on")

    max_visits: int = Field(
        default=0,
        description=("Max times this agent executes in one colony run. 0 = unlimited. Set >1 for one-shot agents."),
    )

    output_model: type[BaseModel] | None = Field(
        default=None,
        description="Optional Pydantic model for validating LLM output.",
    )
    max_validation_retries: int = Field(
        default=2,
        description="Maximum retries when Pydantic validation fails",
    )

    client_facing: bool = Field(
        default=False,
        description="Deprecated — the queen is intrinsically interactive.",
    )

    success_criteria: str | None = Field(
        default=None,
        description="Natural-language criteria for phase completion.",
    )

    skip_judge: bool = Field(
        default=False,
        description="When True, the implicit judge is bypassed entirely.",
    )

    model_config = {"extra": "allow", "arbitrary_types_allowed": True}

    def is_queen(self) -> bool:
        return self.id == "queen"

    def supports_direct_user_io(self) -> bool:
        return self.is_queen()


def deprecated_client_facing_warning(spec: AgentSpec) -> str | None:
    if spec.client_facing and not spec.is_queen():
        return (
            f"Agent '{spec.id}' sets deprecated client_facing=True. "
            "Non-queen direct human I/O is no longer supported; route worker "
            "questions and approvals through queen escalation instead."
        )
    return None


def warn_if_deprecated_client_facing(spec: AgentSpec) -> None:
    import logging

    warning = deprecated_client_facing_warning(spec)
    if warning:
        logging.getLogger(__name__).warning(warning)


@dataclass
class AgentContext:
    """Everything an agent loop needs to execute.

    Passed to every agent implementation and provides:
    - Runtime (for decision logging)
    - LLM access
    - Tools
    - Goal context
    - Execution metadata
    """

    runtime: DecisionTracker

    agent_id: str
    agent_spec: AgentSpec

    input_data: dict[str, Any] = field(default_factory=dict)

    llm: LLMProvider | None = None
    available_tools: list[Tool] = field(default_factory=list)

    goal_context: str = ""
    goal: Any = None

    max_tokens: int = 4096

    attempt: int = 1
    max_attempts: int = 3

    runtime_logger: Any = None
    pause_event: Any = None

    accounts_prompt: str = ""

    identity_prompt: str = ""
    narrative: str = ""
    memory_prompt: str = ""

    event_triggered: bool = False

    execution_id: str = ""
    run_id: str = ""

    @property
    def effective_run_id(self) -> str | None:
        return self.run_id or None

    stream_id: str = ""

    dynamic_tools_provider: Any = None
    dynamic_prompt_provider: Any = None
    # Optional Callable[[], str]: when set alongside ``dynamic_prompt_provider``,
    # the AgentLoop sends the system prompt as two pieces — the result of
    # ``dynamic_prompt_provider`` is the STATIC block (cached), and this
    # provider returns the DYNAMIC suffix (not cached). The LLM wrapper
    # emits them as two Anthropic system content blocks with a cache
    # breakpoint between them for providers that honor ``cache_control``.
    # For providers that don't, the two strings are concatenated. Used by
    # the Queen to keep her persona/role/tools block warm across iterations
    # while the recall + timestamp tail refreshes per user turn.
    dynamic_prompt_suffix_provider: Any = None
    dynamic_memory_provider: Any = None
    # Optional Callable[[], str]: when set, the current skills-catalog
    # prompt is sourced from this provider each iteration. Lets workers
    # pick up UI toggles without restarting the run. Queen agents already
    # rebuild the whole prompt via dynamic_prompt_provider — this field
    # is a surgical alternative used by colony workers where the rest of
    # the prompt stays constant and we don't want to thrash the cache.
    dynamic_skills_catalog_provider: Any = None

    skills_catalog_prompt: str = ""
    protocols_prompt: str = ""
    skill_dirs: list[str] = field(default_factory=list)
    default_skill_batch_nudge: str | None = None
    default_skill_warn_ratio: float | None = None

    iteration_metadata_provider: Any = None

    @property
    def is_queen_stream(self) -> bool:
        return self.stream_id == "queen" or self.agent_spec.is_queen()

    @property
    def emits_client_io(self) -> bool:
        return self.is_queen_stream

    @property
    def supports_direct_user_io(self) -> bool:
        return self.is_queen_stream and not self.event_triggered


@dataclass
class AgentResult:
    """Output of an agent loop execution."""

    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    next_agent: str | None = None
    route_reason: str | None = None

    tokens_used: int = 0
    latency_ms: int = 0

    validation_errors: list[str] = field(default_factory=list)

    conversation: Any = None

    # Machine-readable reason the loop stopped (see LoopExitReason in
    # agent_loop/internals/types.py). "?" means the loop didn't set one,
    # which should itself be treated as a diagnostic.
    exit_reason: str = "?"
    # Counters for reliability events surfaced during this execution.
    # Populated from the loop's TaskRegistry-style counters at return
    # time so callers can spot recurring failure modes without tailing
    # logs. Keys are stable strings; missing keys mean "zero".
    reliability_stats: dict[str, int] = field(default_factory=dict)

    def to_summary(self, spec: Any = None) -> str:
        if not self.success:
            return f"Failed: {self.error}"

        if not self.output:
            return "Completed (no output)"

        parts = [f"Completed with {len(self.output)} outputs:"]
        for key, value in list(self.output.items())[:5]:
            value_str = str(value)[:100]
            if len(str(value)) > 100:
                value_str += "..."
            parts.append(f"  - {key}: {value_str}")
        return "\n".join(parts)


class AgentProtocol(ABC):
    """Interface all agent implementations must satisfy."""

    @abstractmethod
    async def execute(self, ctx: AgentContext) -> AgentResult:
        pass

    def validate_input(self, ctx: AgentContext) -> list[str]:
        errors = []
        for key in ctx.agent_spec.input_keys:
            if key not in ctx.input_data:
                errors.append(f"Missing required input: {key}")
        return errors
