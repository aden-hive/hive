"""
PersonalityFitnessEvaluator - Tracks trait-success correlations.

Evaluates the fitness of personality traits by correlating them with
session outcomes. This enables:

1. Identifying which traits contribute to success
2. Recommending mutations for problematic traits
3. Tracking personality fitness over time
4. Guiding DNA evolution decisions

Fitness scores help determine whether to preserve, modify, or prune traits.
"""

import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from framework.personality.dna import (
    AgentPersonalityDNA,
    BehaviorPattern,
    DNAMutation,
    Heuristic,
)
from framework.personality.store import FilePersonalityStore, PersonalityStore

logger = logging.getLogger(__name__)


class TraitFitness:
    """Fitness metrics for a single trait."""

    def __init__(
        self,
        trait_path: str,
        trait_value: Any,
    ):
        self.trait_path = trait_path
        self.trait_value = trait_value
        self.success_count = 0
        self.failure_count = 0
        self.total_sessions = 0
        self.recent_outcomes: list[bool] = []
        self.max_recent = 10

    @property
    def success_rate(self) -> float:
        """Calculate overall success rate."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.5
        return self.success_count / total

    @property
    def recent_success_rate(self) -> float:
        """Calculate recent success rate (last N sessions)."""
        if not self.recent_outcomes:
            return 0.5
        return sum(self.recent_outcomes) / len(self.recent_outcomes)

    @property
    def confidence(self) -> float:
        """Confidence in the fitness score based on sample size."""
        total = self.success_count + self.failure_count
        return min(1.0, total / 20)

    @property
    def fitness_score(self) -> float:
        """
        Calculate overall fitness score.

        Combines success rate with confidence and recent trend.
        """
        if self.total_sessions == 0:
            return 0.5

        base_score = self.success_rate

        recent_weight = 0.3
        recent_adjustment = (self.recent_success_rate - base_score) * recent_weight

        trend_bonus = 0
        if len(self.recent_outcomes) >= 3:
            recent_trend = sum(self.recent_outcomes[-3:]) / 3
            older_trend = sum(self.recent_outcomes[:-3]) / max(1, len(self.recent_outcomes) - 3)
            if recent_trend > older_trend:
                trend_bonus = 0.1
            elif recent_trend < older_trend:
                trend_bonus = -0.1

        score = base_score + recent_adjustment + trend_bonus
        return max(0.0, min(1.0, score))

    @property
    def recommendation(self) -> str:
        """Get recommendation for this trait."""
        if self.total_sessions < 3:
            return "insufficient_data"

        score = self.fitness_score

        if score >= 0.8:
            return "preserve"
        elif score >= 0.6:
            return "maintain"
        elif score >= 0.4:
            return "monitor"
        elif score >= 0.2:
            return "consider_mutating"
        else:
            return "mutate"

    def record_outcome(self, success: bool) -> None:
        """Record a session outcome for this trait."""
        self.total_sessions += 1
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1

        self.recent_outcomes.append(success)
        if len(self.recent_outcomes) > self.max_recent:
            self.recent_outcomes.pop(0)


class PersonalityFitnessEvaluator:
    """
    Evaluates personality trait fitness.

    Tracks correlations between traits and session outcomes to
    identify which traits contribute to success.

    Example:
        store = FilePersonalityStore(Path.home() / ".hive" / "personality")
        evaluator = PersonalityFitnessEvaluator(store)

        # Evaluate current DNA fitness
        report = await evaluator.evaluate_fitness("support-agent")

        # Get mutation recommendations
        recommendations = evaluator.get_mutation_recommendations("support-agent")
    """

    def __init__(self, store: PersonalityStore):
        self.store = store
        self._trait_fitness: dict[str, dict[str, TraitFitness]] = defaultdict(dict)

    async def evaluate_fitness(
        self,
        agent_id: str,
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        """
        Evaluate fitness of all traits for an agent.

        Args:
            agent_id: The agent's identifier
            lookback_days: How many days of history to consider

        Returns:
            Fitness report with scores and recommendations
        """
        dna = self.store.load_dna(agent_id)
        if dna is None:
            return {
                "agent_id": agent_id,
                "error": "No DNA found",
            }

        self._analyze_traits(agent_id, dna)

        trait_scores = self._compute_trait_scores(dna)

        overall_fitness = self._compute_overall_fitness(trait_scores)

        return {
            "agent_id": agent_id,
            "dna_id": dna.dna_id,
            "generation": dna.generation,
            "evaluated_at": datetime.now().isoformat(),
            "overall_fitness": overall_fitness,
            "trait_scores": trait_scores,
            "recommendations": self._get_recommendations(trait_scores),
            "session_stats": {
                "total": dna.total_sessions_analyzed,
                "successful": dna.total_successful_sessions,
                "failed": dna.total_failed_sessions,
                "success_rate": dna.overall_success_rate,
            },
        }

    def _analyze_traits(self, agent_id: str, dna: AgentPersonalityDNA) -> None:
        """Analyze trait fitness from DNA and history."""
        agent_traits = self._trait_fitness[agent_id]

        trait_path = "communication_style.style"
        if trait_path not in agent_traits:
            agent_traits[trait_path] = TraitFitness(trait_path, dna.communication_style.style.value)
        trait = agent_traits[trait_path]
        trait.success_count = dna.total_successful_sessions
        trait.failure_count = dna.total_failed_sessions
        trait.total_sessions = dna.total_sessions_analyzed

        trait_path = "decision_patterns.risk_tolerance"
        if trait_path not in agent_traits:
            agent_traits[trait_path] = TraitFitness(
                trait_path, dna.decision_patterns.risk_tolerance.value
            )
        trait = agent_traits[trait_path]
        trait.success_count = dna.total_successful_sessions
        trait.failure_count = dna.total_failed_sessions
        trait.total_sessions = dna.total_sessions_analyzed

        trait_path = "escalation_behavior.trigger"
        if trait_path not in agent_traits:
            agent_traits[trait_path] = TraitFitness(
                trait_path, dna.escalation_behavior.trigger.value
            )
        trait = agent_traits[trait_path]
        trait.success_count = dna.total_successful_sessions
        trait.failure_count = dna.total_failed_sessions
        trait.total_sessions = dna.total_sessions_analyzed

        for context, heuristic in dna.domain_heuristics.items():
            trait_path = f"heuristic.{context}"
            if trait_path not in agent_traits:
                agent_traits[trait_path] = TraitFitness(trait_path, heuristic.rule)
            trait = agent_traits[trait_path]
            trait.success_count = heuristic.success_count
            trait.failure_count = heuristic.failure_count
            trait.total_sessions = heuristic.success_count + heuristic.failure_count

    def _compute_trait_scores(self, dna: AgentPersonalityDNA) -> dict[str, dict[str, Any]]:
        """Compute fitness scores for all traits."""
        scores = {}
        agent_traits = self._trait_fitness.get(dna.agent_id, {})

        for trait_path, fitness in agent_traits.items():
            scores[trait_path] = {
                "value": fitness.trait_value,
                "fitness_score": fitness.fitness_score,
                "success_rate": fitness.success_rate,
                "confidence": fitness.confidence,
                "recommendation": fitness.recommendation,
                "sample_size": fitness.total_sessions,
            }

        for pattern in dna.successful_patterns:
            trait_path = f"pattern.success.{pattern.name}"
            scores[trait_path] = {
                "value": pattern.description,
                "fitness_score": pattern.success_rate,
                "success_rate": pattern.success_rate,
                "confidence": pattern.confidence,
                "recommendation": "preserve" if pattern.success_rate > 0.7 else "monitor",
                "sample_size": pattern.occurrence_count,
            }

        for pattern in dna.avoided_patterns:
            trait_path = f"pattern.avoided.{pattern.name}"
            scores[trait_path] = {
                "value": pattern.description,
                "fitness_score": 1.0
                - (pattern.occurrence_count / max(1, dna.total_sessions_analyzed)),
                "success_rate": 0.0,
                "confidence": min(1.0, pattern.occurrence_count / 5),
                "recommendation": "avoid",
                "sample_size": pattern.occurrence_count,
            }

        return scores

    def _compute_overall_fitness(self, trait_scores: dict[str, dict[str, Any]]) -> float:
        """Compute overall DNA fitness from trait scores."""
        if not trait_scores:
            return 0.5

        weighted_sum = 0.0
        total_weight = 0.0

        for trait_path, score_data in trait_scores.items():
            if trait_path.startswith("pattern.avoided."):
                continue

            fitness = score_data["fitness_score"]
            confidence = score_data["confidence"]

            weighted_sum += fitness * confidence
            total_weight += confidence

        if total_weight == 0:
            return 0.5

        return weighted_sum / total_weight

    def _get_recommendations(self, trait_scores: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """Get actionable recommendations based on trait scores."""
        recommendations = []

        for trait_path, score_data in trait_scores.items():
            if score_data["recommendation"] in ("mutate", "consider_mutating"):
                recommendations.append(
                    {
                        "trait": trait_path,
                        "action": score_data["recommendation"],
                        "reason": f"Low fitness score: {score_data['fitness_score']:.2f}",
                        "current_value": score_data["value"],
                    }
                )

        recommendations.sort(
            key=lambda r: trait_scores.get(r["trait"], {}).get("fitness_score", 0.5)
        )

        return recommendations[:5]

    def get_mutation_recommendations(
        self,
        agent_id: str,
        threshold: float = 0.4,
    ) -> list[dict[str, Any]]:
        """
        Get specific mutation recommendations for low-fitness traits.

        Args:
            agent_id: The agent's identifier
            threshold: Fitness score below which to recommend mutation

        Returns:
            List of mutation recommendations
        """
        dna = self.store.load_dna(agent_id)
        if dna is None:
            return []

        self._analyze_traits(agent_id, dna)
        agent_traits = self._trait_fitness.get(agent_id, {})

        recommendations = []

        for trait_path, fitness in agent_traits.items():
            if fitness.fitness_score < threshold and fitness.confidence > 0.3:
                recommendations.append(
                    {
                        "trait_path": trait_path,
                        "current_value": fitness.trait_value,
                        "fitness_score": fitness.fitness_score,
                        "suggested_action": self._suggest_mutation(trait_path, fitness),
                        "confidence": fitness.confidence,
                    }
                )

        return recommendations

    def _suggest_mutation(self, trait_path: str, fitness: TraitFitness) -> str:
        """Suggest a mutation action for a low-fitness trait."""
        if trait_path == "communication_style.style":
            if fitness.success_rate < 0.4:
                return "Consider adjusting to 'adaptive' style"
            return "Review and adjust based on context"

        if trait_path == "decision_patterns.risk_tolerance":
            if fitness.trait_value == "aggressive":
                return "Consider more conservative approach"
            elif fitness.trait_value == "conservative":
                return "Consider more aggressive approach"
            return "Review risk tolerance settings"

        if trait_path == "escalation_behavior.trigger":
            if fitness.success_rate < 0.5:
                return "Adjust escalation threshold"
            return "Review escalation triggers"

        if trait_path.startswith("heuristic."):
            return "Remove or modify this heuristic"

        return "Review and adjust this trait"

    def record_session_outcome(
        self,
        agent_id: str,
        session_id: str,
        success: bool,
        active_traits: list[str] | None = None,
    ) -> None:
        """
        Record a session outcome for trait fitness tracking.

        Args:
            agent_id: The agent's identifier
            session_id: The session's identifier
            success: Whether the session was successful
            active_traits: Optional list of traits that were active
        """
        agent_traits = self._trait_fitness[agent_id]

        if active_traits:
            for trait_path in active_traits:
                if trait_path in agent_traits:
                    agent_traits[trait_path].record_outcome(success)
        else:
            for trait in agent_traits.values():
                trait.record_outcome(success)

    def get_fitness_trend(
        self,
        agent_id: str,
        days: int = 7,
    ) -> dict[str, Any]:
        """
        Get fitness trend over time.

        Args:
            agent_id: The agent's identifier
            days: Number of days to analyze

        Returns:
            Trend analysis report
        """
        history = self.store.get_dna_history(agent_id, limit=days)

        if len(history) < 2:
            return {
                "agent_id": agent_id,
                "trend": "insufficient_data",
                "data_points": len(history),
            }

        fitness_scores = []
        for dna in history:
            self._analyze_traits(agent_id, dna)
            scores = self._compute_trait_scores(dna)
            fitness_scores.append(self._compute_overall_fitness(scores))

        if len(fitness_scores) >= 2:
            first_half = fitness_scores[: len(fitness_scores) // 2]
            second_half = fitness_scores[len(fitness_scores) // 2 :]

            avg_first = sum(first_half) / len(first_half)
            avg_second = sum(second_half) / len(second_half)

            if avg_second > avg_first + 0.05:
                trend = "improving"
            elif avg_second < avg_first - 0.05:
                trend = "declining"
            else:
                trend = "stable"
        else:
            trend = "insufficient_data"

        return {
            "agent_id": agent_id,
            "trend": trend,
            "data_points": len(fitness_scores),
            "first_half_avg": avg_first if len(fitness_scores) >= 2 else None,
            "second_half_avg": avg_second if len(fitness_scores) >= 2 else None,
            "latest_fitness": fitness_scores[-1] if fitness_scores else None,
        }

    def should_preserve_dna(self, agent_id: str) -> bool:
        """
        Determine if DNA should be preserved during evolution.

        DNA should be preserved if:
        - Overall fitness is good (> 0.6)
        - No critical traits need mutation
        - Success rate is acceptable
        """
        dna = self.store.load_dna(agent_id)
        if dna is None:
            return False

        self._analyze_traits(agent_id, dna)
        scores = self._compute_trait_scores(dna)
        overall = self._compute_overall_fitness(scores)

        if overall < 0.4:
            return False

        critical_mutations = sum(
            1 for s in scores.values() if s["fitness_score"] < 0.3 and s["confidence"] > 0.5
        )

        if critical_mutations > 2:
            return False

        return True

    def get_stats(self, agent_id: str) -> dict[str, Any]:
        """Get fitness evaluation statistics."""
        agent_traits = self._trait_fitness.get(agent_id, {})

        return {
            "agent_id": agent_id,
            "traits_tracked": len(agent_traits),
            "total_observations": sum(t.total_sessions for t in agent_traits.values()),
            "traits_by_recommendation": {
                rec: sum(1 for t in agent_traits.values() if t.recommendation == rec)
                for rec in [
                    "preserve",
                    "maintain",
                    "monitor",
                    "consider_mutating",
                    "mutate",
                    "insufficient_data",
                ]
            },
        }
