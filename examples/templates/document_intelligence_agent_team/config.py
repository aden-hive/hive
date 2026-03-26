"""Configuration for Document Intelligence Agent Team."""

from dataclasses import dataclass, field


@dataclass
class ValidationConfig:
    """Output validation thresholds for Worker Bee handoff gates.

    Controls circuit breaker behavior: when a worker fails validation,
    the pipeline degrades gracefully rather than halting.
    """

    max_retries: int = 1  # Retry once before marking as failed
    min_confidence: float = 0.0  # Flag outputs below this threshold
    require_confidence_score: bool = True
    require_structured_output: bool = True


@dataclass
class LTMConfig:
    """Long-term memory configuration for cross-session pattern retention."""

    enabled: bool = True
    ltm_file: str = "ltm_analyses.json"
    behavior_log_file: str = "worker_behavior.jsonl"
    max_prior_sessions: int = 10  # Cap retrieval to last N sessions


@dataclass
class RuntimeConfig:
    """Runtime configuration for the agent."""

    model: str | None = None  # Use system default
    max_concurrent: int = 10
    verbose: bool = False
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    ltm: LTMConfig = field(default_factory=LTMConfig)


@dataclass
class WorkerModels:
    """Per-worker model overrides for A2A multi-model cross-reference.

    Each Worker Bee can use a different LLM model to enable diverse
    analytical perspectives and cross-model verification.
    Set to None to inherit the system default.
    """

    coordinator: str | None = None
    researcher: str | None = None
    analyst: str | None = None
    strategist: str | None = None


# Default model configuration
worker_models = WorkerModels()

# Default runtime configuration
default_config = RuntimeConfig()


@dataclass
class AgentMetadata:
    """Agent metadata for identification and display."""

    name: str = "Document Intelligence Agent Team"
    version: str = "0.1.0"
    description: str = (
        "A2A agent team that performs multi-perspective document analysis "
        "using Queen Bee (Coordinator) + Worker Bees (Researcher, Analyst, "
        "Strategist) with delegate_to_sub_agent coordination."
    )
    intro_message: str = (
        "📄 **Document Intelligence Agent Team**\n\n"
        "I coordinate a team of specialist agents to analyze your documents:\n"
        "- 🔬 **Researcher** — Entity extraction, fact verification, citations\n"
        "- 🔍 **Analyst** — Internal consistency, contradiction detection\n"
        "- 📊 **Strategist** — Risk assessment, impact analysis, action items\n\n"
        "Paste or describe a document and I'll dispatch my team for "
        "multi-perspective analysis with cross-reference synthesis."
    )
    tags: list[str] = field(
        default_factory=lambda: ["a2a", "multi-agent", "document-analysis", "queen-bee"]
    )


# Default metadata instance
metadata = AgentMetadata()
