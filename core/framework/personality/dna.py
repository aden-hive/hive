"""
Agent Personality DNA (APDNA) Schema - Persistent behavioral identity for agents.

APDNA captures, preserves, and evolves an agent's emergent behavioral patterns
across sessions and evolution cycles. This ensures that when agents evolve
to fix bugs or improve functionality, they retain their learned "personality" -
the patterns that make each agent unique and effective.

Key Concepts:
- DNA is extracted from session outcomes (what worked, what didn't)
- DNA is synthesized across multiple sessions using Bayesian aggregation
- DNA is injected into prompts to guide behavior
- DNA is preserved across evolution cycles
- DNA fitness is tracked to identify successful traits

Version History:
- v1.0: Initial implementation (2026-02-24)
"""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field


class CommunicationStyle(StrEnum):
    """Communication style patterns for an agent."""

    FORMAL = "formal"
    CASUAL = "casual"
    ADAPTIVE = "adaptive"
    TECHNICAL = "technical"
    CONCISE = "concise"
    VERBOSE = "verbose"


class RiskToleranceLevel(StrEnum):
    """Risk tolerance levels for decision-making."""

    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"
    ADAPTIVE = "adaptive"


class EscalationTrigger(StrEnum):
    """When to escalate to human intervention."""

    NEVER = "never"
    ON_UNCERTAINTY = "on_uncertainty"
    ON_ERROR = "on_error"
    ON_COMPLEXITY = "on_complexity"
    ALWAYS = "always"


class CommunicationProfile(BaseModel):
    """
    Communication style and patterns.

    Captures how the agent communicates with users and other systems.
    """

    style: CommunicationStyle = CommunicationStyle.ADAPTIVE
    formality_score: float = Field(default=0.5, ge=0.0, le=1.0)
    technical_depth: float = Field(default=0.5, ge=0.0, le=1.0)
    emoji_usage: float = Field(default=0.0, ge=0.0, le=1.0)
    response_length_preference: str = "medium"

    signature_phrases: list[str] = Field(default_factory=list)
    avoided_phrases: list[str] = Field(default_factory=list)

    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    sample_count: int = 0

    model_config = {"extra": "allow"}


class DecisionProfile(BaseModel):
    """
    Decision-making patterns and risk tolerance.

    Captures how the agent makes choices and handles uncertainty.
    """

    risk_tolerance: RiskToleranceLevel = RiskToleranceLevel.MODERATE
    risk_score: float = Field(default=0.5, ge=0.0, le=1.0)

    confirmation_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    exploration_vs_exploitation: float = Field(default=0.5, ge=0.0, le=1.0)

    preferred_decision_types: list[str] = Field(default_factory=list)

    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    sample_count: int = 0

    model_config = {"extra": "allow"}


class EscalationProfile(BaseModel):
    """
    Escalation behavior and human intervention patterns.

    Captures when and how the agent asks for help.
    """

    trigger: EscalationTrigger = EscalationTrigger.ON_UNCERTAINTY
    uncertainty_threshold: float = Field(default=0.6, ge=0.0, le=1.0)
    complexity_threshold: float = Field(default=0.7, ge=0.0, le=1.0)

    escalation_phrases: list[str] = Field(default_factory=list)

    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    sample_count: int = 0

    model_config = {"extra": "allow"}


class Heuristic(BaseModel):
    """
    A learned rule-of-thumb for specific contexts.

    Domain-specific knowledge extracted from successful interactions.
    """

    id: str
    context: str
    rule: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    success_count: int = 0
    failure_count: int = 0
    last_updated: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}

    @computed_field
    @property
    def success_rate(self) -> float:
        """Calculate success rate for this heuristic."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.5
        return self.success_count / total


class BehaviorPattern(BaseModel):
    """
    A recurring pattern of behavior observed across sessions.

    Can be either a successful pattern (to repeat) or avoided pattern (to avoid).
    """

    id: str
    name: str
    description: str
    pattern_type: str = "success"
    examples: list[str] = Field(default_factory=list)

    success_rate: float = Field(default=0.5, ge=0.0, le=1.0)
    occurrence_count: int = 0
    contexts: list[str] = Field(default_factory=list)

    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    last_observed: datetime = Field(default_factory=datetime.now)

    model_config = {"extra": "allow"}


class DNAMutation(BaseModel):
    """
    A recorded change to the DNA.

    Tracks how DNA evolves over time.
    """

    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    timestamp: datetime = Field(default_factory=datetime.now)
    mutation_type: str
    trait_path: str
    old_value: Any = None
    new_value: Any = None
    reason: str = ""
    trigger: str = ""

    model_config = {"extra": "allow"}


class AgentPersonalityDNA(BaseModel):
    """
    Complete personality DNA for an agent.

    This is the primary data structure for APDNA, containing all behavioral
    traits, learned patterns, and evolution metadata.

    The DNA is:
    - Extracted: From session outcomes and decision logs
    - Synthesized: Across multiple sessions using Bayesian aggregation
    - Injected: Into system prompts to guide behavior
    - Preserved: Across evolution cycles
    - Tracked: For fitness correlation with success metrics

    Example:
        dna = AgentPersonalityDNA(
            agent_id="support-agent-001",
            communication_style=CommunicationProfile(
                style=CommunicationStyle.CASUAL,
                formality_score=0.3,
                emoji_usage=0.7,
            ),
            domain_heuristics={
                "tech_startups": Heuristic(
                    id="heuristic-001",
                    context="tech_startups",
                    rule="Use casual tone with emojis for tech startup prospects",
                    confidence=0.87,
                )
            }
        )
    """

    schema_version: str = "1.0"

    agent_id: str
    dna_id: str = Field(default_factory=lambda: str(uuid4())[:12])

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    communication_style: CommunicationProfile = Field(default_factory=CommunicationProfile)
    decision_patterns: DecisionProfile = Field(default_factory=DecisionProfile)
    escalation_behavior: EscalationProfile = Field(default_factory=EscalationProfile)

    domain_heuristics: dict[str, Heuristic] = Field(default_factory=dict)
    successful_patterns: list[BehaviorPattern] = Field(default_factory=list)
    avoided_patterns: list[BehaviorPattern] = Field(default_factory=list)

    generation: int = 1
    parent_hash: str | None = None
    mutation_history: list[DNAMutation] = Field(default_factory=list)
    trait_fitness_scores: dict[str, float] = Field(default_factory=dict)

    total_sessions_analyzed: int = 0
    total_successful_sessions: int = 0
    total_failed_sessions: int = 0

    model_config = {"extra": "allow"}

    @computed_field
    @property
    def overall_success_rate(self) -> float:
        """Calculate overall session success rate."""
        total = self.total_successful_sessions + self.total_failed_sessions
        if total == 0:
            return 0.5
        return self.total_successful_sessions / total

    @computed_field
    @property
    def average_trait_confidence(self) -> float:
        """Calculate average confidence across all traits."""
        confidences = [
            self.communication_style.confidence,
            self.decision_patterns.confidence,
            self.escalation_behavior.confidence,
        ]
        for heuristic in self.domain_heuristics.values():
            confidences.append(heuristic.confidence)
        for pattern in self.successful_patterns + self.avoided_patterns:
            confidences.append(pattern.confidence)

        if not confidences:
            return 0.5
        return sum(confidences) / len(confidences)

    def record_mutation(
        self,
        mutation_type: str,
        trait_path: str,
        old_value: Any,
        new_value: Any,
        reason: str = "",
        trigger: str = "",
    ) -> DNAMutation:
        """Record a mutation to the DNA."""
        mutation = DNAMutation(
            mutation_type=mutation_type,
            trait_path=trait_path,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            trigger=trigger,
        )
        self.mutation_history.append(mutation)
        self.updated_at = datetime.now()
        return mutation

    def update_session_stats(self, success: bool) -> None:
        """Update session statistics."""
        self.total_sessions_analyzed += 1
        if success:
            self.total_successful_sessions += 1
        else:
            self.total_failed_sessions += 1
        self.updated_at = datetime.now()

    def get_heuristic(self, context: str) -> Heuristic | None:
        """Get a heuristic for a specific context."""
        return self.domain_heuristics.get(context)

    def add_or_update_heuristic(
        self,
        context: str,
        rule: str,
        success: bool,
    ) -> Heuristic:
        """Add or update a domain heuristic."""
        if context in self.domain_heuristics:
            heuristic = self.domain_heuristics[context]
            if success:
                heuristic.success_count += 1
            else:
                heuristic.failure_count += 1
            heuristic.confidence = heuristic.success_rate
            heuristic.last_updated = datetime.now()
        else:
            heuristic = Heuristic(
                id=f"heuristic-{len(self.domain_heuristics) + 1:04d}",
                context=context,
                rule=rule,
                confidence=1.0 if success else 0.0,
                success_count=1 if success else 0,
                failure_count=0 if success else 1,
            )
            self.domain_heuristics[context] = heuristic

        self.updated_at = datetime.now()
        return heuristic

    def add_successful_pattern(
        self,
        name: str,
        description: str,
        example: str,
        context: str = "general",
    ) -> BehaviorPattern:
        """Add or reinforce a successful behavior pattern."""
        for pattern in self.successful_patterns:
            if pattern.name == name:
                pattern.occurrence_count += 1
                pattern.last_observed = datetime.now()
                if example not in pattern.examples:
                    pattern.examples.append(example)
                if context not in pattern.contexts:
                    pattern.contexts.append(context)
                pattern.success_rate = min(1.0, pattern.success_rate + 0.05)
                self.updated_at = datetime.now()
                return pattern

        pattern = BehaviorPattern(
            id=f"pattern-{len(self.successful_patterns) + len(self.avoided_patterns) + 1:04d}",
            name=name,
            description=description,
            pattern_type="success",
            examples=[example],
            contexts=[context],
            occurrence_count=1,
        )
        self.successful_patterns.append(pattern)
        self.updated_at = datetime.now()
        return pattern

    def add_avoided_pattern(
        self,
        name: str,
        description: str,
        example: str,
        context: str = "general",
    ) -> BehaviorPattern:
        """Add or reinforce an avoided behavior pattern."""
        for pattern in self.avoided_patterns:
            if pattern.name == name:
                pattern.occurrence_count += 1
                pattern.last_observed = datetime.now()
                if example not in pattern.examples:
                    pattern.examples.append(example)
                if context not in pattern.contexts:
                    pattern.contexts.append(context)
                self.updated_at = datetime.now()
                return pattern

        pattern = BehaviorPattern(
            id=f"pattern-{len(self.successful_patterns) + len(self.avoided_patterns) + 1:04d}",
            name=name,
            description=description,
            pattern_type="avoided",
            examples=[example],
            contexts=[context],
            occurrence_count=1,
        )
        self.avoided_patterns.append(pattern)
        self.updated_at = datetime.now()
        return pattern

    def compute_hash(self) -> str:
        """Compute a hash of the current DNA state."""
        import hashlib
        import json

        dna_dict = self.model_dump(
            exclude={"mutation_history", "updated_at"},
            mode="json",
        )
        dna_json = json.dumps(dna_dict, sort_keys=True, default=str)
        return hashlib.sha256(dna_json.encode()).hexdigest()[:16]

    def to_prompt_block(self) -> str:
        """Generate a prompt block for LLM injection."""
        lines = [
            "## Personality DNA",
            "",
            "### Communication Style",
            f"- Style: {self.communication_style.style.value}",
            f"- Formality: {self.communication_style.formality_score:.0%}",
            f"- Technical depth: {self.communication_style.technical_depth:.0%}",
        ]

        if self.communication_style.signature_phrases:
            lines.append(
                f"- Signature phrases: {', '.join(self.communication_style.signature_phrases[:3])}"
            )

        lines.extend(
            [
                "",
                "### Decision-Making",
                f"- Risk tolerance: {self.decision_patterns.risk_tolerance.value}",
                f"- Confirmation threshold: {self.decision_patterns.confirmation_threshold:.0%}",
                "",
                "### Escalation",
                f"- Trigger: {self.escalation_behavior.trigger.value}",
                f"- Uncertainty threshold: {self.escalation_behavior.uncertainty_threshold:.0%}",
            ]
        )

        if self.domain_heuristics:
            lines.extend(["", "### Domain Heuristics"])
            for context, heuristic in list(self.domain_heuristics.items())[:5]:
                if heuristic.confidence > 0.6:
                    lines.append(
                        f"- [{context}]: {heuristic.rule} (confidence: {heuristic.confidence:.0%})"
                    )

        if self.successful_patterns:
            lines.extend(["", "### Successful Patterns to Emulate"])
            for pattern in self.successful_patterns[:3]:
                if pattern.confidence > 0.6:
                    lines.append(f"- {pattern.name}: {pattern.description}")

        if self.avoided_patterns:
            lines.extend(["", "### Patterns to Avoid"])
            for pattern in self.avoided_patterns[:3]:
                lines.append(f"- {pattern.name}: {pattern.description}")

        return "\n".join(lines)


class PersonalitySignal(BaseModel):
    """
    A raw signal extracted from a session.

    Signals are extracted by PersonalityExtractor and then aggregated
    by PersonalitySynthesizer into stable traits.
    """

    session_id: str
    timestamp: datetime = Field(default_factory=datetime.now)

    signal_type: str
    trait_category: str
    trait_name: str
    value: Any
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)

    context: str = ""
    evidence: str = ""

    session_outcome: str = "unknown"

    model_config = {"extra": "allow"}


class DNADiff(BaseModel):
    """
    Difference between two DNA versions.

    Used to visualize changes during evolution.
    """

    from_generation: int
    to_generation: int
    from_hash: str
    to_hash: str

    added_traits: list[str] = Field(default_factory=list)
    removed_traits: list[str] = Field(default_factory=list)
    modified_traits: dict[str, dict[str, Any]] = Field(default_factory=dict)

    mutations: list[DNAMutation] = Field(default_factory=list)

    summary: str = ""

    model_config = {"extra": "allow"}
