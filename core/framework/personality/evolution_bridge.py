"""
DNAEvolutionBridge - Preserves and mutates DNA during agent evolution.

Bridges the gap between agent evolution and personality preservation:

1. Preserves DNA when evolution is for unrelated changes
2. Mutates only specific traits when personality caused failure
3. Provides selective mutation recommendations
4. Tracks evolution impact on personality

This ensures agents maintain their "soul" even as their code evolves.
"""

import logging
from datetime import datetime
from typing import Any

from framework.personality.dna import (
    AgentPersonalityDNA,
    DNADiff,
    DNAMutation,
)
from framework.personality.fitness import PersonalityFitnessEvaluator
from framework.personality.store import FilePersonalityStore, PersonalityStore

logger = logging.getLogger(__name__)


class EvolutionContext:
    """Context for an evolution event."""

    def __init__(
        self,
        evolution_type: str,
        trigger: str,
        reason: str,
        affected_components: list[str] | None = None,
        failure_traits: list[str] | None = None,
    ):
        self.evolution_type = evolution_type
        self.trigger = trigger
        self.reason = reason
        self.affected_components = affected_components or []
        self.failure_traits = failure_traits or []
        self.timestamp = datetime.now()

    @property
    def is_personality_related(self) -> bool:
        """Check if evolution is related to personality issues."""
        personality_keywords = [
            "communication",
            "tone",
            "style",
            "behavior",
            "personality",
            "trait",
            "response",
            "escalation",
        ]

        reason_lower = self.reason.lower()
        return any(kw in reason_lower for kw in personality_keywords)

    @property
    def should_preserve_dna(self) -> bool:
        """Check if DNA should be fully preserved."""
        return not self.is_personality_related and not self.failure_traits


class DNAEvolutionBridge:
    """
    Bridges agent evolution with personality DNA preservation.

    Ensures that personality traits survive evolution cycles while
    allowing targeted mutations when personality issues are identified.

    Example:
        store = FilePersonalityStore(Path.home() / ".hive" / "personality")
        bridge = DNAEvolutionBridge(store)

        # Before evolution
        context = EvolutionContext(
            evolution_type="bug_fix",
            trigger="test_failure",
            reason="Fixed email formatting bug",
        )
        preserved_dna = bridge.prepare_for_evolution("support-agent", context)

        # After evolution
        new_dna = bridge.finalize_evolution("support-agent", preserved_dna, context)
    """

    def __init__(
        self,
        store: PersonalityStore,
        fitness_evaluator: PersonalityFitnessEvaluator | None = None,
    ):
        self.store = store
        self.fitness_evaluator = fitness_evaluator or PersonalityFitnessEvaluator(store)

        self.preservation_rules = {
            "bug_fix": {
                "preserve_all": True,
                "allow_mutations": False,
            },
            "performance": {
                "preserve_all": True,
                "allow_mutations": False,
            },
            "feature_add": {
                "preserve_all": True,
                "allow_mutations": False,
            },
            "behavior_change": {
                "preserve_all": False,
                "allow_mutations": True,
                "mutation_scope": "specified_only",
            },
            "personality_fix": {
                "preserve_all": False,
                "allow_mutations": True,
                "mutation_scope": "problematic_only",
            },
            "full_rewrite": {
                "preserve_all": True,
                "allow_mutations": False,
            },
        }

    def prepare_for_evolution(
        self,
        agent_id: str,
        context: EvolutionContext,
    ) -> AgentPersonalityDNA | None:
        """
        Prepare DNA for evolution by creating a preserved copy.

        Args:
            agent_id: The agent's identifier
            context: Evolution context describing what's happening

        Returns:
            Preserved DNA to use after evolution
        """
        current_dna = self.store.load_dna(agent_id)
        if current_dna is None:
            logger.info(f"No DNA found for {agent_id}, will create new after evolution")
            return None

        logger.info(
            f"Preparing DNA for evolution: {context.evolution_type} "
            f"(preserve_all: {context.should_preserve_dna})"
        )

        return current_dna.model_copy(deep=True)

    def finalize_evolution(
        self,
        agent_id: str,
        preserved_dna: AgentPersonalityDNA | None,
        context: EvolutionContext,
        new_agent_id: str | None = None,
    ) -> AgentPersonalityDNA:
        """
        Finalize DNA after evolution completes.

        Args:
            agent_id: Original agent identifier
            preserved_dna: DNA prepared before evolution
            context: Evolution context
            new_agent_id: Optional new agent ID (if agent was renamed)

        Returns:
            Final DNA for the evolved agent
        """
        target_id = new_agent_id or agent_id

        if preserved_dna is None:
            new_dna = AgentPersonalityDNA(agent_id=target_id)
            new_dna.record_mutation(
                mutation_type="creation",
                trait_path="dna",
                old_value=None,
                new_value="new_dna",
                reason="Created new DNA after evolution",
                trigger=context.evolution_type,
            )
            self.store.save_dna(new_dna)
            return new_dna

        rules = self.preservation_rules.get(
            context.evolution_type,
            {"preserve_all": True, "allow_mutations": False},
        )

        if rules.get("preserve_all", True) and context.should_preserve_dna:
            preserved_dna.agent_id = target_id
            preserved_dna.generation += 1
            preserved_dna.parent_hash = preserved_dna.compute_hash()
            preserved_dna.record_mutation(
                mutation_type="preserve",
                trait_path="dna",
                old_value="previous_generation",
                new_value=f"generation_{preserved_dna.generation}",
                reason=f"Preserved during {context.evolution_type}",
                trigger=context.trigger,
            )
            self.store.save_dna(preserved_dna)
            logger.info(f"Preserved DNA for {target_id} (generation {preserved_dna.generation})")
            return preserved_dna

        if rules.get("allow_mutations", False):
            return self._apply_mutations(preserved_dna, context, target_id)

        preserved_dna.agent_id = target_id
        self.store.save_dna(preserved_dna)
        return preserved_dna

    def _apply_mutations(
        self,
        dna: AgentPersonalityDNA,
        context: EvolutionContext,
        target_id: str,
    ) -> AgentPersonalityDNA:
        """Apply selective mutations based on evolution context."""
        rules = self.preservation_rules.get(context.evolution_type, {})
        mutation_scope = rules.get("mutation_scope", "none")

        mutations_to_apply: list[tuple[str, Any, Any]] = []

        if mutation_scope == "specified_only" and context.failure_traits:
            for trait in context.failure_traits:
                mutation = self._plan_trait_mutation(dna, trait)
                if mutation:
                    mutations_to_apply.append(mutation)

        elif mutation_scope == "problematic_only":
            recommendations = self.fitness_evaluator.get_mutation_recommendations(
                dna.agent_id,
                threshold=0.5,
            )
            for rec in recommendations:
                trait_path = rec["trait_path"]
                new_value = self._suggest_new_value(trait_path, rec["current_value"])
                mutations_to_apply.append((trait_path, rec["current_value"], new_value))

        for trait_path, old_value, new_value in mutations_to_apply:
            self._apply_mutation(dna, trait_path, old_value, new_value, context)

        dna.agent_id = target_id
        dna.generation += 1
        dna.parent_hash = dna.compute_hash()

        if mutations_to_apply:
            logger.info(f"Applied {len(mutations_to_apply)} mutations to DNA for {target_id}")
        else:
            logger.info(f"No mutations applied to DNA for {target_id}")

        self.store.save_dna(dna)
        return dna

    def _plan_trait_mutation(
        self,
        dna: AgentPersonalityDNA,
        trait: str,
    ) -> tuple[str, Any, Any] | None:
        """Plan a mutation for a specific trait."""
        trait_lower = trait.lower()

        if "communication" in trait_lower or "style" in trait_lower:
            old_value = dna.communication_style.style.value
            new_value = self._get_alternative_style(dna.communication_style.style.value)
            return ("communication_style.style", old_value, new_value)

        if "risk" in trait_lower or "decision" in trait_lower:
            old_value = dna.decision_patterns.risk_tolerance.value
            new_value = self._get_alternative_risk(dna.decision_patterns.risk_tolerance.value)
            return ("decision_patterns.risk_tolerance", old_value, new_value)

        if "escalat" in trait_lower:
            old_value = dna.escalation_behavior.trigger.value
            new_value = self._get_alternative_escalation(dna.escalation_behavior.trigger.value)
            return ("escalation_behavior.trigger", old_value, new_value)

        if trait in dna.domain_heuristics:
            heuristic = dna.domain_heuristics[trait]
            return (f"heuristic.{trait}", heuristic.rule, None)

        return None

    def _apply_mutation(
        self,
        dna: AgentPersonalityDNA,
        trait_path: str,
        old_value: Any,
        new_value: Any,
        context: EvolutionContext,
    ) -> None:
        """Apply a single mutation to the DNA."""
        from framework.personality.dna import (
            CommunicationStyle,
            RiskToleranceLevel,
            EscalationTrigger,
        )

        if trait_path == "communication_style.style" and new_value:
            dna.communication_style.style = CommunicationStyle(new_value)

        elif trait_path == "decision_patterns.risk_tolerance" and new_value:
            dna.decision_patterns.risk_tolerance = RiskToleranceLevel(new_value)

        elif trait_path == "escalation_behavior.trigger" and new_value:
            dna.escalation_behavior.trigger = EscalationTrigger(new_value)

        elif trait_path.startswith("heuristic."):
            context_key = trait_path.replace("heuristic.", "")
            if context_key in dna.domain_heuristics:
                if new_value is None:
                    del dna.domain_heuristics[context_key]
                else:
                    dna.domain_heuristics[context_key].rule = new_value

        dna.record_mutation(
            mutation_type="evolution",
            trait_path=trait_path,
            old_value=old_value,
            new_value=new_value,
            reason=context.reason,
            trigger=context.trigger,
        )

    def _get_alternative_style(self, current: str) -> str:
        """Get an alternative communication style."""
        alternatives = {
            "formal": "adaptive",
            "casual": "adaptive",
            "technical": "adaptive",
            "concise": "adaptive",
            "verbose": "concise",
            "adaptive": "formal",
        }
        return alternatives.get(current, "adaptive")

    def _get_alternative_risk(self, current: str) -> str:
        """Get an alternative risk tolerance."""
        alternatives = {
            "conservative": "moderate",
            "moderate": "conservative",
            "aggressive": "moderate",
            "adaptive": "moderate",
        }
        return alternatives.get(current, "moderate")

    def _get_alternative_escalation(self, current: str) -> str:
        """Get an alternative escalation trigger."""
        alternatives = {
            "never": "on_error",
            "on_error": "on_uncertainty",
            "on_uncertainty": "on_complexity",
            "on_complexity": "on_uncertainty",
            "always": "on_complexity",
        }
        return alternatives.get(current, "on_uncertainty")

    def _suggest_new_value(self, trait_path: str, current_value: Any) -> Any:
        """Suggest a new value for a trait."""
        if "style" in trait_path:
            return self._get_alternative_style(current_value)
        if "risk" in trait_path:
            return self._get_alternative_risk(current_value)
        if "escalat" in trait_path:
            return self._get_alternative_escalation(current_value)
        return None

    def get_evolution_impact(
        self,
        agent_id: str,
        from_generation: int,
        to_generation: int,
    ) -> dict[str, Any]:
        """
        Analyze the impact of evolution on personality.

        Args:
            agent_id: The agent's identifier
            from_generation: Starting generation
            to_generation: Ending generation

        Returns:
            Impact analysis report
        """
        history = self.store.get_dna_history(agent_id, limit=50)

        from_dna = None
        to_dna = None

        for dna in history:
            if dna.generation == from_generation:
                from_dna = dna
            if dna.generation == to_generation:
                to_dna = dna

        if from_dna is None or to_dna is None:
            return {
                "error": "Could not find DNA for specified generations",
                "from_generation": from_generation,
                "to_generation": to_generation,
            }

        mutations_in_range = [
            m
            for m in to_dna.mutation_history
            if from_generation <= 0
            or m in to_dna.mutation_history[len(from_dna.mutation_history) :]
        ]

        style_changed = from_dna.communication_style.style != to_dna.communication_style.style
        risk_changed = (
            from_dna.decision_patterns.risk_tolerance != to_dna.decision_patterns.risk_tolerance
        )
        escalation_changed = (
            from_dna.escalation_behavior.trigger != to_dna.escalation_behavior.trigger
        )

        heuristics_added = len(to_dna.domain_heuristics) - len(from_dna.domain_heuristics)

        return {
            "agent_id": agent_id,
            "from_generation": from_generation,
            "to_generation": to_generation,
            "generations_span": to_generation - from_generation,
            "mutations_count": len(mutations_in_range),
            "core_traits_changed": {
                "communication_style": style_changed,
                "risk_tolerance": risk_changed,
                "escalation_trigger": escalation_changed,
            },
            "heuristics_added": heuristics_added,
            "success_rate_change": to_dna.overall_success_rate - from_dna.overall_success_rate,
            "preservation_rate": self._calculate_preservation_rate(from_dna, to_dna),
        }

    def _calculate_preservation_rate(
        self,
        from_dna: AgentPersonalityDNA,
        to_dna: AgentPersonalityDNA,
    ) -> float:
        """Calculate what percentage of traits were preserved."""
        if not from_dna.domain_heuristics:
            return 1.0

        preserved = 0
        total = len(from_dna.domain_heuristics)

        for context, heuristic in from_dna.domain_heuristics.items():
            if context in to_dna.domain_heuristics:
                new_h = to_dna.domain_heuristics[context]
                if new_h.rule == heuristic.rule:
                    preserved += 1
                elif abs(new_h.confidence - heuristic.confidence) < 0.3:
                    preserved += 0.5

        return preserved / total if total > 0 else 1.0

    def create_evolution_checkpoint(
        self,
        agent_id: str,
        checkpoint_name: str,
    ) -> str:
        """
        Create a named checkpoint of current DNA before evolution.

        Args:
            agent_id: The agent's identifier
            checkpoint_name: Name for the checkpoint

        Returns:
            Checkpoint DNA ID
        """
        current_dna = self.store.load_dna(agent_id)
        if current_dna is None:
            raise ValueError(f"No DNA found for agent {agent_id}")

        checkpoint_dna = current_dna.model_copy(deep=True)
        checkpoint_dna.record_mutation(
            mutation_type="checkpoint",
            trait_path="dna",
            old_value=None,
            new_value=checkpoint_name,
            reason=f"Created checkpoint: {checkpoint_name}",
            trigger="manual_checkpoint",
        )

        self.store.save_dna(checkpoint_dna)

        logger.info(f"Created DNA checkpoint '{checkpoint_name}' for {agent_id}")
        return checkpoint_dna.dna_id

    def rollback_to_checkpoint(
        self,
        agent_id: str,
        checkpoint_dna_id: str,
    ) -> AgentPersonalityDNA:
        """
        Rollback DNA to a checkpoint.

        Args:
            agent_id: The agent's identifier
            checkpoint_dna_id: DNA ID of the checkpoint

        Returns:
            Restored DNA
        """
        checkpoint_dna = self.store.load_dna_by_id(agent_id, checkpoint_dna_id)
        if checkpoint_dna is None:
            raise ValueError(f"Checkpoint {checkpoint_dna_id} not found for {agent_id}")

        restored_dna = checkpoint_dna.model_copy(deep=True)
        restored_dna.record_mutation(
            mutation_type="rollback",
            trait_path="dna",
            old_value="current",
            new_value=checkpoint_dna_id,
            reason=f"Rolled back to checkpoint",
            trigger="manual_rollback",
        )

        self.store.save_dna(restored_dna)

        logger.info(f"Rolled back DNA for {agent_id} to checkpoint {checkpoint_dna_id}")
        return restored_dna
