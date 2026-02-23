"""
PersonalityInjector - Transforms DNA into prompt behavioral guidance.

Injects personality DNA into agent prompts to guide behavior at runtime.
The injector:

1. Loads current DNA for an agent
2. Generates personality prompt blocks
3. Provides both full and summary views
4. Supports trait-specific injection

This enables agents to "remember" their personality across sessions
and evolution cycles.
"""

import logging
from datetime import datetime
from typing import Any

from framework.personality.dna import (
    AgentPersonalityDNA,
    BehaviorPattern,
    CommunicationProfile,
    CommunicationStyle,
    DecisionProfile,
    EscalationProfile,
    Heuristic,
)
from framework.personality.store import FilePersonalityStore, PersonalityStore

logger = logging.getLogger(__name__)


class PersonalityInjector:
    """
    Transforms DNA into prompt behavioral guidance.

    Generates prompt blocks that materialize personality traits
    into actionable behavioral guidance for the LLM.

    Example:
        store = FilePersonalityStore(Path.home() / ".hive" / "personality")
        injector = PersonalityInjector(store)

        # Get full personality block
        block = injector.generate_prompt_block("support-agent")

        # Get trait-specific guidance
        guidance = injector.get_communication_guidance("support-agent")
    """

    def __init__(self, store: PersonalityStore):
        self.store = store

    def generate_prompt_block(
        self,
        agent_id: str,
        include_heuristics: bool = True,
        include_patterns: bool = True,
        max_heuristics: int = 5,
        max_patterns: int = 3,
    ) -> str:
        """
        Generate full personality prompt block for an agent.

        Args:
            agent_id: The agent's identifier
            include_heuristics: Whether to include domain heuristics
            include_patterns: Whether to include behavior patterns
            max_heuristics: Maximum number of heuristics to include
            max_patterns: Maximum number of patterns per category

        Returns:
            Formatted prompt block string
        """
        dna = self.store.load_dna(agent_id)
        if dna is None:
            return ""

        return self._generate_block_from_dna(
            dna,
            include_heuristics=include_heuristics,
            include_patterns=include_patterns,
            max_heuristics=max_heuristics,
            max_patterns=max_patterns,
        )

    def generate_prompt_block_from_dna(
        self,
        dna: AgentPersonalityDNA,
        include_heuristics: bool = True,
        include_patterns: bool = True,
        max_heuristics: int = 5,
        max_patterns: int = 3,
    ) -> str:
        """Generate prompt block from DNA object directly."""
        return self._generate_block_from_dna(
            dna,
            include_heuristics=include_heuristics,
            include_patterns=include_patterns,
            max_heuristics=max_heuristics,
            max_patterns=max_patterns,
        )

    def _generate_block_from_dna(
        self,
        dna: AgentPersonalityDNA,
        include_heuristics: bool,
        include_patterns: bool,
        max_heuristics: int,
        max_patterns: int,
    ) -> str:
        """Internal: Generate prompt block from DNA."""
        lines = [
            "## Personality DNA",
            "",
            "Your behavioral identity has evolved through experience. "
            "The following traits represent patterns that have proven effective.",
            "",
        ]

        lines.extend(self._generate_communication_section(dna.communication_style))

        lines.extend(self._generate_decision_section(dna.decision_patterns))

        lines.extend(self._generate_escalation_section(dna.escalation_behavior))

        if include_heuristics and dna.domain_heuristics:
            lines.extend(
                self._generate_heuristics_section(
                    dna.domain_heuristics,
                    max_heuristics,
                )
            )

        if include_patterns:
            if dna.successful_patterns:
                lines.extend(
                    self._generate_successful_patterns_section(
                        dna.successful_patterns,
                        max_patterns,
                    )
                )

            if dna.avoided_patterns:
                lines.extend(
                    self._generate_avoided_patterns_section(
                        dna.avoided_patterns,
                        max_patterns,
                    )
                )

        lines.append("---")

        return "\n".join(lines)

    def _generate_communication_section(self, profile: CommunicationProfile) -> list[str]:
        """Generate communication style section."""
        lines = [
            "### Communication Style",
            "",
        ]

        style_guidance = self._get_style_guidance(profile.style)
        lines.append(f"**Tone**: {style_guidance}")

        if profile.confidence > 0.6:
            formality_desc = self._describe_formality(profile.formality_score)
            lines.append(f"**Formality**: {formality_desc}")

        if profile.technical_depth > 0.6:
            lines.append("**Technical Depth**: Use precise technical terminology when appropriate.")
        elif profile.technical_depth < 0.4:
            lines.append("**Technical Depth**: Prefer accessible language over jargon.")

        if profile.emoji_usage > 0.5:
            lines.append("**Emoji Usage**: Feel free to use emojis to convey tone and emotion.")
        elif profile.emoji_usage > 0.2:
            lines.append("**Emoji Usage**: Use emojis sparingly and contextually.")

        if profile.signature_phrases:
            phrases = ", ".join(f'"{p}"' for p in profile.signature_phrases[:3])
            lines.append(f"**Signature Phrases**: {phrases}")

        if profile.avoided_phrases:
            avoided = ", ".join(f'"{p}"' for p in profile.avoided_phrases[:3])
            lines.append(f"**Avoid Phrases**: {avoided}")

        lines.append("")
        return lines

    def _generate_decision_section(self, profile: DecisionProfile) -> list[str]:
        """Generate decision-making section."""
        lines = [
            "### Decision-Making",
            "",
        ]

        risk_guidance = self._get_risk_guidance(profile.risk_tolerance)
        lines.append(f"**Risk Approach**: {risk_guidance}")

        if profile.confirmation_threshold > 0.7:
            lines.append("**Confirmation**: Verify important decisions before proceeding.")
        elif profile.confirmation_threshold < 0.4:
            lines.append("**Confirmation**: Move quickly; you can adjust course as needed.")

        if profile.exploration_vs_exploitation > 0.6:
            lines.append("**Approach**: Explore new options when reasonable alternatives exist.")
        elif profile.exploration_vs_exploitation < 0.4:
            lines.append("**Approach**: Stick with proven approaches when they work well.")

        if profile.preferred_decision_types:
            types = ", ".join(profile.preferred_decision_types[:3])
            lines.append(f"**Preferred Methods**: {types}")

        lines.append("")
        return lines

    def _generate_escalation_section(self, profile: EscalationProfile) -> list[str]:
        """Generate escalation behavior section."""
        lines = [
            "### Human Collaboration",
            "",
        ]

        escalation_guidance = self._get_escalation_guidance(profile.trigger)
        lines.append(f"**Escalation**: {escalation_guidance}")

        if profile.trigger != EscalationTrigger.NEVER:
            threshold_desc = (
                "high"
                if profile.uncertainty_threshold > 0.7
                else "moderate"
                if profile.uncertainty_threshold > 0.4
                else "low"
            )
            lines.append(
                f"**Uncertainty Threshold**: {threshold_desc.title()} - ask for help when uncertain."
            )

        if profile.escalation_phrases:
            phrases = ", ".join(f'"{p}"' for p in profile.escalation_phrases[:2])
            lines.append(f"**Escalation Phrases**: {phrases}")

        lines.append("")
        return lines

    def _generate_heuristics_section(
        self,
        heuristics: dict[str, Heuristic],
        max_count: int,
    ) -> list[str]:
        """Generate domain heuristics section."""
        lines = [
            "### Domain Heuristics",
            "",
            "Context-specific rules learned from experience:",
            "",
        ]

        sorted_heuristics = sorted(
            heuristics.items(),
            key=lambda x: x[1].confidence,
            reverse=True,
        )[:max_count]

        for context, heuristic in sorted_heuristics:
            if heuristic.confidence < 0.5:
                continue

            confidence_pct = int(heuristic.confidence * 100)
            lines.append(f"- **[{context}]** {heuristic.rule} ({confidence_pct}% confidence)")

        lines.append("")
        return lines

    def _generate_successful_patterns_section(
        self,
        patterns: list[BehaviorPattern],
        max_count: int,
    ) -> list[str]:
        """Generate successful patterns section."""
        lines = [
            "### Successful Patterns",
            "",
            "Behaviors that have consistently worked well:",
            "",
        ]

        sorted_patterns = sorted(
            patterns,
            key=lambda p: p.success_rate,
            reverse=True,
        )[:max_count]

        for pattern in sorted_patterns:
            if pattern.confidence < 0.5:
                continue

            success_pct = int(pattern.success_rate * 100)
            lines.append(f"- **{pattern.name}**: {pattern.description} ({success_pct}% success)")

        lines.append("")
        return lines

    def _generate_avoided_patterns_section(
        self,
        patterns: list[BehaviorPattern],
        max_count: int,
    ) -> list[str]:
        """Generate avoided patterns section."""
        lines = [
            "### Patterns to Avoid",
            "",
            "Behaviors that have not worked well:",
            "",
        ]

        sorted_patterns = sorted(
            patterns,
            key=lambda p: p.occurrence_count,
            reverse=True,
        )[:max_count]

        for pattern in sorted_patterns:
            lines.append(f"- **{pattern.name}**: {pattern.description}")

        lines.append("")
        return lines

    def _get_style_guidance(self, style: CommunicationStyle) -> str:
        """Get guidance text for communication style."""
        guidance = {
            CommunicationStyle.FORMAL: "Maintain a professional, structured tone. Use complete sentences and formal language.",
            CommunicationStyle.CASUAL: "Be friendly and approachable. Use conversational language and contractions.",
            CommunicationStyle.ADAPTIVE: "Match your tone to the context and user. Be flexible in your communication style.",
            CommunicationStyle.TECHNICAL: "Be precise and technical when discussing complex topics. Don't oversimplify.",
            CommunicationStyle.CONCISE: "Get to the point quickly. Avoid unnecessary elaboration.",
            CommunicationStyle.VERBOSE: "Provide thorough explanations. Include context and examples.",
        }
        return guidance.get(style, "Communicate naturally and effectively.")

    def _describe_formality(self, score: float) -> str:
        """Describe formality level."""
        if score > 0.7:
            return "High - use formal language and structure"
        elif score > 0.5:
            return "Moderate - balance formality with accessibility"
        elif score > 0.3:
            return "Low - use conversational language"
        else:
            return "Very casual - friendly and relaxed"

    def _get_risk_guidance(self, level) -> str:
        """Get guidance text for risk tolerance."""
        from framework.personality.dna import RiskToleranceLevel

        guidance = {
            RiskToleranceLevel.CONSERVATIVE: "Take a cautious approach. Verify before acting. Prefer proven solutions.",
            RiskToleranceLevel.MODERATE: "Balance risk and reward. Consider tradeoffs carefully.",
            RiskToleranceLevel.AGGRESSIVE: "Move quickly. Accept calculated risks. Iterate fast.",
            RiskToleranceLevel.ADAPTIVE: "Adjust your risk tolerance based on context and stakes.",
        }
        return guidance.get(level, "Make balanced decisions.")

    def _get_escalation_guidance(self, trigger) -> str:
        """Get guidance text for escalation trigger."""
        from framework.personality.dna import EscalationTrigger

        guidance = {
            EscalationTrigger.NEVER: "Work autonomously. Only escalate for critical blockers.",
            EscalationTrigger.ON_ERROR: "Ask for help when encountering errors you cannot resolve.",
            EscalationTrigger.ON_UNCERTAINTY: "Escalate when uncertain about the best course of action.",
            EscalationTrigger.ON_COMPLEXITY: "Involve humans for complex decisions with significant impact.",
            EscalationTrigger.ALWAYS: "Frequently check in with humans on decisions.",
        }
        return guidance.get(trigger, "Use judgment on when to escalate.")

    def get_communication_guidance(self, agent_id: str) -> str:
        """Get communication-style specific guidance only."""
        dna = self.store.load_dna(agent_id)
        if dna is None:
            return ""

        return "\n".join(self._generate_communication_section(dna.communication_style))

    def get_decision_guidance(self, agent_id: str) -> str:
        """Get decision-making specific guidance only."""
        dna = self.store.load_dna(agent_id)
        if dna is None:
            return ""

        return "\n".join(self._generate_decision_section(dna.decision_patterns))

    def get_heuristics_guidance(self, agent_id: str, context: str | None = None) -> str:
        """Get domain heuristics guidance, optionally filtered by context."""
        dna = self.store.load_dna(agent_id)
        if dna is None:
            return ""

        if context:
            heuristic = dna.get_heuristic(context)
            if heuristic and heuristic.confidence > 0.5:
                return f"[{context}]: {heuristic.rule} (confidence: {heuristic.confidence:.0%})"
            return ""

        return "\n".join(self._generate_heuristics_section(dna.domain_heuristics, 10))

    def generate_summary(self, agent_id: str) -> str:
        """Generate a brief personality summary for quick reference."""
        dna = self.store.load_dna(agent_id)
        if dna is None:
            return "No personality DNA found."

        parts = [
            f"Communication: {dna.communication_style.style.value}",
            f"Risk: {dna.decision_patterns.risk_tolerance.value}",
            f"Escalation: {dna.escalation_behavior.trigger.value}",
        ]

        if dna.domain_heuristics:
            top_heuristic = max(
                dna.domain_heuristics.values(),
                key=lambda h: h.confidence,
            )
            parts.append(f"Top heuristic: {top_heuristic.context}")

        parts.append(f"Sessions: {dna.total_sessions_analyzed}")
        parts.append(f"Success rate: {dna.overall_success_rate:.0%}")

        return " | ".join(parts)

    def inject_into_system_prompt(
        self,
        agent_id: str,
        base_prompt: str,
        position: str = "end",
    ) -> str:
        """
        Inject personality into an existing system prompt.

        Args:
            agent_id: The agent's identifier
            base_prompt: The base system prompt
            position: Where to inject ("start", "end", "after_identity")

        Returns:
            Modified system prompt with personality injected
        """
        personality_block = self.generate_prompt_block(agent_id)
        if not personality_block:
            return base_prompt

        if position == "start":
            return f"{personality_block}\n\n{base_prompt}"
        elif position == "after_identity":
            identity_marker = "\n\nYou are"
            if identity_marker in base_prompt:
                parts = base_prompt.split(identity_marker, 1)
                return f"{parts[0]}{identity_marker}{parts[1]}\n\n{personality_block}"
            return f"{base_prompt}\n\n{personality_block}"
        else:
            return f"{base_prompt}\n\n{personality_block}"

    def get_injection_metadata(self, agent_id: str) -> dict[str, Any]:
        """Get metadata about DNA available for injection."""
        dna = self.store.load_dna(agent_id)
        if dna is None:
            return {
                "has_dna": False,
                "agent_id": agent_id,
            }

        return {
            "has_dna": True,
            "agent_id": agent_id,
            "dna_id": dna.dna_id,
            "generation": dna.generation,
            "total_sessions": dna.total_sessions_analyzed,
            "success_rate": dna.overall_success_rate,
            "average_confidence": dna.average_trait_confidence,
            "heuristic_count": len(dna.domain_heuristics),
            "successful_pattern_count": len(dna.successful_patterns),
            "avoided_pattern_count": len(dna.avoided_patterns),
            "last_updated": dna.updated_at.isoformat(),
        }
