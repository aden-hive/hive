"""
PersonalitySynthesizer - Aggregates personality signals into stable traits.

Uses Bayesian-style aggregation to synthesize signals from multiple sessions
into stable, confident personality traits. The synthesizer:

1. Loads existing DNA as prior
2. Updates with new signals as evidence
3. Produces posterior distribution over traits
4. Updates DNA with synthesized traits

This approach ensures:
- Early sessions don't overly influence personality
- Confidence increases with consistent signals
- Outliers are downweighted
- Personality evolves gradually
"""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Any

from framework.personality.dna import (
    AgentPersonalityDNA,
    BehaviorPattern,
    CommunicationProfile,
    CommunicationStyle,
    DecisionProfile,
    EscalationProfile,
    EscalationTrigger,
    Heuristic,
    PersonalitySignal,
    RiskToleranceLevel,
)
from framework.personality.store import FilePersonalityStore, PersonalityStore

logger = logging.getLogger(__name__)


class PersonalitySynthesizer:
    """
    Synthesizes personality signals into stable traits.

    Uses Bayesian-style aggregation where:
    - Prior = existing DNA traits
    - Evidence = new signals
    - Posterior = updated traits

    Example:
        store = FilePersonalityStore(Path.home() / ".hive" / "personality")
        synthesizer = PersonalitySynthesizer(store)

        # Synthesize signals into DNA
        dna = await synthesizer.synthesize(
            agent_id="support-agent",
            signals=extracted_signals,
        )
    """

    def __init__(self, store: PersonalityStore):
        self.store = store

        self.trait_decay_rate = 0.95
        self.min_confidence = 0.3
        self.max_confidence = 0.95
        self.min_samples_for_confidence = 3

    async def synthesize(
        self,
        agent_id: str,
        signals: list[PersonalitySignal],
        preserve_existing: bool = True,
    ) -> AgentPersonalityDNA:
        """
        Synthesize signals into personality DNA.

        Args:
            agent_id: The agent's identifier
            signals: List of extracted personality signals
            preserve_existing: Whether to preserve existing DNA as prior

        Returns:
            Updated AgentPersonalityDNA
        """
        if preserve_existing:
            dna = self.store.load_dna(agent_id)
            if dna is None:
                dna = AgentPersonalityDNA(agent_id=agent_id)
        else:
            dna = AgentPersonalityDNA(agent_id=agent_id)

        signals_by_category: dict[str, list[PersonalitySignal]] = defaultdict(list)
        for signal in signals:
            signals_by_category[signal.trait_category].append(signal)

        if "communication_style" in signals_by_category:
            dna.communication_style = self._synthesize_communication(
                dna.communication_style,
                signals_by_category["communication_style"],
            )

        if "decision_patterns" in signals_by_category:
            dna.decision_patterns = self._synthesize_decision(
                dna.decision_patterns,
                signals_by_category["decision_patterns"],
            )

        if "escalation_behavior" in signals_by_category:
            dna.escalation_behavior = self._synthesize_escalation(
                dna.escalation_behavior,
                signals_by_category["escalation_behavior"],
            )

        if "domain_heuristics" in signals_by_category:
            self._synthesize_heuristics(
                dna,
                signals_by_category["domain_heuristics"],
            )

        if "successful_patterns" in signals_by_category:
            self._synthesize_successful_patterns(
                dna,
                signals_by_category["successful_patterns"],
            )

        if "avoided_patterns" in signals_by_category:
            self._synthesize_avoided_patterns(
                dna,
                signals_by_category["avoided_patterns"],
            )

        session_success = any(s.session_outcome == "success" for s in signals)
        dna.update_session_stats(session_success)

        self.store.save_dna(dna)

        logger.info(f"Synthesized {len(signals)} signals into DNA for {agent_id}")
        return dna

    def _synthesize_communication(
        self,
        current: CommunicationProfile,
        signals: list[PersonalitySignal],
    ) -> CommunicationProfile:
        """Synthesize communication style from signals."""
        style_votes: dict[str, list[float]] = defaultdict(list)
        formality_scores: list[float] = []
        emoji_scores: list[float] = []
        technical_scores: list[float] = []
        length_prefs: dict[str, int] = defaultdict(int)

        for signal in signals:
            weight = self._signal_weight(signal)

            if signal.trait_name == "style":
                style_votes[signal.value].append(weight)
            elif signal.trait_name == "formality_score":
                formality_scores.append(signal.value * weight)
            elif signal.trait_name == "emoji_usage":
                emoji_scores.append(signal.value * weight)
            elif signal.trait_name == "technical_depth":
                technical_scores.append(signal.value * weight)
            elif signal.trait_name == "response_length_preference":
                length_prefs[signal.value] += 1

        new_sample_count = len(signals)
        total_samples = current.sample_count + new_sample_count

        if style_votes:
            weighted_votes = {style: sum(weights) for style, weights in style_votes.items()}
            new_style = max(weighted_votes, key=weighted_votes.get)
            style_confidence = weighted_votes[new_style] / sum(weighted_votes.values())

            if current.sample_count > 0:
                if new_style == current.style.value:
                    new_style_enum = current.style
                else:
                    new_style_enum = CommunicationStyle(new_style)

                blend_factor = new_sample_count / (total_samples + 5)
                if blend_factor > 0.3:
                    current.style = new_style_enum
            else:
                current.style = CommunicationStyle(new_style)

            current.confidence = self._blend_confidence(
                current.confidence,
                style_confidence,
                current.sample_count,
                new_sample_count,
            )

        if formality_scores:
            avg_formality = sum(formality_scores) / len(formality_scores)
            current.formality_score = self._blend_value(
                current.formality_score,
                avg_formality,
                current.sample_count,
                new_sample_count,
            )

        if emoji_scores:
            avg_emoji = sum(emoji_scores) / len(emoji_scores)
            current.emoji_usage = self._blend_value(
                current.emoji_usage,
                avg_emoji,
                current.sample_count,
                new_sample_scores=len(emoji_scores),
            )

        if technical_scores:
            avg_technical = sum(technical_scores) / len(technical_scores)
            current.technical_depth = self._blend_value(
                current.technical_depth,
                avg_technical,
                current.sample_count,
                new_sample_scores=len(technical_scores),
            )

        if length_prefs:
            new_length = max(length_prefs, key=length_prefs.get)
            current.response_length_preference = new_length

        current.sample_count = total_samples
        current.confidence = min(self.max_confidence, current.confidence)

        return current

    def _synthesize_decision(
        self,
        current: DecisionProfile,
        signals: list[PersonalitySignal],
    ) -> DecisionProfile:
        """Synthesize decision patterns from signals."""
        risk_votes: dict[str, list[float]] = defaultdict(list)
        confirmation_scores: list[float] = []
        exploration_scores: list[float] = []

        for signal in signals:
            weight = self._signal_weight(signal)

            if signal.trait_name == "risk_tolerance":
                risk_votes[signal.value].append(weight)
            elif signal.trait_name == "confirmation_threshold":
                confirmation_scores.append(signal.value * weight)
            elif signal.trait_name == "exploration_vs_exploitation":
                exploration_scores.append(signal.value * weight)

        new_sample_count = len(signals)
        total_samples = current.sample_count + new_sample_count

        if risk_votes:
            weighted_votes = {level: sum(weights) for level, weights in risk_votes.items()}
            new_level = max(weighted_votes, key=weighted_votes.get)
            level_confidence = weighted_votes[new_level] / sum(weighted_votes.values())

            if current.sample_count > 0:
                if new_level != current.risk_tolerance.value:
                    blend_factor = new_sample_count / (total_samples + 5)
                    if blend_factor > 0.3:
                        current.risk_tolerance = RiskToleranceLevel(new_level)
            else:
                current.risk_tolerance = RiskToleranceLevel(new_level)

            current.confidence = self._blend_confidence(
                current.confidence,
                level_confidence,
                current.sample_count,
                new_sample_count,
            )

        if confirmation_scores:
            avg_confirmation = sum(confirmation_scores) / len(confirmation_scores)
            current.confirmation_threshold = self._blend_value(
                current.confirmation_threshold,
                avg_confirmation,
                current.sample_count,
                new_sample_scores=len(confirmation_scores),
            )

        if exploration_scores:
            avg_exploration = sum(exploration_scores) / len(exploration_scores)
            current.exploration_vs_exploitation = self._blend_value(
                current.exploration_vs_exploitation,
                avg_exploration,
                current.sample_count,
                new_sample_scores=len(exploration_scores),
            )

        risk_score = self._risk_level_to_score(current.risk_tolerance)
        current.risk_score = self._blend_value(
            current.risk_score,
            risk_score,
            current.sample_count,
            new_sample_count,
        )

        current.sample_count = total_samples
        current.confidence = min(self.max_confidence, current.confidence)

        return current

    def _synthesize_escalation(
        self,
        current: EscalationProfile,
        signals: list[PersonalitySignal],
    ) -> EscalationProfile:
        """Synthesize escalation behavior from signals."""
        escalation_rates: list[float] = []
        uncertainty_thresholds: list[float] = []

        for signal in signals:
            weight = self._signal_weight(signal)

            if signal.trait_name == "escalation_frequency":
                escalation_rates.append(signal.value * weight)
            elif signal.trait_name == "uncertainty_threshold":
                uncertainty_thresholds.append(signal.value * weight)

        new_sample_count = len(signals)
        total_samples = current.sample_count + new_sample_count

        if escalation_rates:
            avg_rate = sum(escalation_rates) / len(escalation_rates)

            if avg_rate < 0.1:
                new_trigger = EscalationTrigger.NEVER
            elif avg_rate < 0.3:
                new_trigger = EscalationTrigger.ON_ERROR
            elif avg_rate < 0.5:
                new_trigger = EscalationTrigger.ON_UNCERTAINTY
            else:
                new_trigger = EscalationTrigger.ON_COMPLEXITY

            if current.sample_count > 0:
                blend_factor = new_sample_count / (total_samples + 5)
                if blend_factor > 0.3:
                    current.trigger = new_trigger
            else:
                current.trigger = new_trigger

            current.confidence = self._blend_confidence(
                current.confidence,
                1.0 - abs(0.5 - avg_rate),
                current.sample_count,
                new_sample_count,
            )

        if uncertainty_thresholds:
            avg_threshold = sum(uncertainty_thresholds) / len(uncertainty_thresholds)
            current.uncertainty_threshold = self._blend_value(
                current.uncertainty_threshold,
                avg_threshold,
                current.sample_count,
                new_sample_scores=len(uncertainty_thresholds),
            )

        current.sample_count = total_samples
        current.confidence = min(self.max_confidence, current.confidence)

        return current

    def _synthesize_heuristics(
        self,
        dna: AgentPersonalityDNA,
        signals: list[PersonalitySignal],
    ) -> None:
        """Synthesize domain heuristics from signals."""
        for signal in signals:
            if not signal.context:
                continue

            weight = self._signal_weight(signal)
            existing = dna.get_heuristic(signal.context)

            if existing:
                if signal.signal_type == "success_pattern":
                    existing.success_count += 1
                elif signal.signal_type == "failure_pattern":
                    existing.failure_count += 1

                existing.confidence = min(
                    self.max_confidence,
                    existing.confidence + (0.1 * weight),
                )
                existing.last_updated = datetime.now()
            else:
                heuristic = Heuristic(
                    id=f"heuristic-{len(dna.domain_heuristics) + 1:04d}",
                    context=signal.context,
                    rule=str(signal.value),
                    confidence=weight * 0.5,
                    success_count=1 if signal.signal_type == "success_pattern" else 0,
                    failure_count=1 if signal.signal_type == "failure_pattern" else 0,
                )
                dna.domain_heuristics[signal.context] = heuristic

    def _synthesize_successful_patterns(
        self,
        dna: AgentPersonalityDNA,
        signals: list[PersonalitySignal],
    ) -> None:
        """Synthesize successful behavior patterns from signals."""
        for signal in signals:
            if not signal.trait_name:
                continue

            pattern_name = signal.trait_name
            description = signal.evidence or str(signal.value)[:100]
            example = str(signal.value)
            context = signal.context or "general"

            dna.add_successful_pattern(
                name=pattern_name,
                description=description,
                example=example,
                context=context,
            )

    def _synthesize_avoided_patterns(
        self,
        dna: AgentPersonalityDNA,
        signals: list[PersonalitySignal],
    ) -> None:
        """Synthesize avoided behavior patterns from signals."""
        for signal in signals:
            if not signal.trait_name:
                continue

            pattern_name = signal.trait_name
            description = signal.evidence or str(signal.value)[:100]
            example = str(signal.value)
            context = signal.context or "general"

            dna.add_avoided_pattern(
                name=pattern_name,
                description=description,
                example=example,
                context=context,
            )

    def _signal_weight(self, signal: PersonalitySignal) -> float:
        """Calculate weight for a signal based on confidence and outcome."""
        base_weight = signal.confidence

        if signal.session_outcome == "success":
            base_weight *= 1.2
        elif signal.session_outcome == "failure":
            base_weight *= 0.8

        return min(1.0, base_weight)

    def _blend_confidence(
        self,
        current: float,
        new: float,
        current_samples: int,
        new_samples: int,
    ) -> float:
        """Blend confidence values using Bayesian-style update."""
        if current_samples == 0:
            return new

        total = current_samples + new_samples
        weight_current = current_samples / total
        weight_new = new_samples / total

        blended = current * weight_current + new * weight_new

        consistency_bonus = 0.1 * (1 - abs(current - new))

        return min(self.max_confidence, blended + consistency_bonus)

    def _blend_value(
        self,
        current: float,
        new: float,
        current_samples: int,
        new_sample_scores: int = 1,
    ) -> float:
        """Blend numeric values using weighted average."""
        if current_samples == 0:
            return new

        total = current_samples + new_sample_scores
        weight_current = current_samples / total * self.trait_decay_rate
        weight_new = new_sample_scores / total

        return current * weight_current + new * weight_new

    def _risk_level_to_score(self, level: RiskToleranceLevel) -> float:
        """Convert risk tolerance level to numeric score."""
        mapping = {
            RiskToleranceLevel.CONSERVATIVE: 0.2,
            RiskToleranceLevel.MODERATE: 0.5,
            RiskToleranceLevel.AGGRESSIVE: 0.8,
            RiskToleranceLevel.ADAPTIVE: 0.5,
        }
        return mapping.get(level, 0.5)

    async def batch_synthesize(
        self,
        agent_id: str,
        sessions: list[list[PersonalitySignal]],
    ) -> AgentPersonalityDNA:
        """
        Synthesize signals from multiple sessions in batch.

        More efficient than repeated synthesize() calls as it
        processes all sessions together.
        """
        all_signals: list[PersonalitySignal] = []
        for session_signals in sessions:
            all_signals.extend(session_signals)

        return await self.synthesize(agent_id, all_signals)
