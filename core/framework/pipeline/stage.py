"""Pipeline stage base class and request/response types."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal


class PipelineRejectedError(Exception):
    """Raised by ``AgentHost.trigger`` when a stage rejects the request."""

    def __init__(self, stage_name: str, reason: str) -> None:
        super().__init__(f"Pipeline rejected by {stage_name}: {reason}")
        self.stage_name = stage_name
        self.reason = reason


@dataclass
class PipelineContext:
    """Carries request data through the pipeline."""

    entry_point_id: str
    input_data: dict[str, Any]
    correlation_id: str | None = None
    session_state: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineResult:
    """Outcome of a stage's ``process`` call."""

    action: Literal["continue", "reject", "transform"] = "continue"
    input_data: dict[str, Any] | None = None
    rejection_reason: str | None = None


class PipelineStage(ABC):
    """Base class for all middleware stages.

    Infrastructure stages (LLM, MCP, credentials, skills) set typed
    attributes during ``initialize()`` that the host reads after all
    stages have initialized.  Request-level stages (rate limit, input
    validation, cost guard) implement ``process()``.

    Attributes set by infrastructure stages:
        llm: LLM provider instance (set by LlmProviderStage)
        tool_registry: ToolRegistry with discovered MCP tools (set by McpRegistryStage)
        accounts_prompt: Connected accounts system prompt block (set by CredentialResolverStage)
        accounts_data: Raw account info list (set by CredentialResolverStage)
        tool_provider_map: Tool name -> provider mapping (set by CredentialResolverStage)
        skills_manager: SkillsManager instance (set by SkillRegistryStage)
    """

    order: int = 100

    # Infrastructure stage outputs -- typed so _apply_pipeline_results
    # doesn't need hasattr() sniffing.
    llm: Any = None
    tool_registry: Any = None
    accounts_prompt: str = ""
    accounts_data: list[dict] | None = None
    tool_provider_map: dict[str, str] | None = None
    skills_manager: Any = None

    async def initialize(self) -> None:
        """Called once when the runtime starts."""
        return None

    @abstractmethod
    async def process(self, ctx: PipelineContext) -> PipelineResult:
        """Process the incoming request."""

    async def post_process(self, ctx: PipelineContext, result: Any) -> Any:
        """Optional post-execution hook. Default: pass-through."""
        return result
