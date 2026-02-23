"""
Agent Personality DNA (APDNA) - Persistent Behavioral Identity Across Evolution.

This module provides a complete system for capturing, preserving, and evolving
an agent's emergent behavioral patterns across sessions and evolution cycles.

Key Components:
- AgentPersonalityDNA: Schema defining behavioral traits
- PersonalityExtractor: Mines personality signals from session logs
- PersonalitySynthesizer: Aggregates signals into stable traits
- PersonalityInjector: Transforms DNA into system prompt guidance
- PersonalityStore: File-based storage for DNA persistence
- PersonalityFitnessEvaluator: Tracks trait-success correlations
- DNAEvolutionBridge: Preserves/mutates DNA during agent evolution

Quick Start:
    from framework.personality import (
        AgentPersonalityDNA,
        FilePersonalityStore,
        PersonalityExtractor,
        PersonalitySynthesizer,
        PersonalityInjector,
    )

    # Set up storage
    store = FilePersonalityStore(Path.home() / ".hive" / "personality")

    # Extract signals from session
    extractor = PersonalityExtractor()
    signals = await extractor.extract_from_session(
        agent_id="support-agent",
        session_id="session-001",
        session_state=session_state,
        conversations=conversations,
    )

    # Synthesize into DNA
    synthesizer = PersonalitySynthesizer(store)
    dna = await synthesizer.synthesize("support-agent", signals)

    # Inject into prompts
    injector = PersonalityInjector(store)
    personality_block = injector.generate_prompt_block("support-agent")

Integration with Agents:
    DNA can be injected into agent system prompts:

    ```python
    # In agent configuration
    identity_prompt = f\"\"\"
    {base_identity_prompt}

    {injector.generate_prompt_block(agent_id)}
    \"\"\"
    ```

Evolution Integration:
    DNA is preserved across evolution cycles:

    ```python
    bridge = DNAEvolutionBridge(store)

    # Before evolution
    context = EvolutionContext(
        evolution_type="bug_fix",
        trigger="test_failure",
        reason="Fixed email formatting bug",
    )
    preserved_dna = bridge.prepare_for_evolution(agent_id, context)

    # After evolution
    new_dna = bridge.finalize_evolution(agent_id, preserved_dna, context)
    ```
"""

from framework.personality.dna import (
    AgentPersonalityDNA,
    BehaviorPattern,
    CommunicationProfile,
    CommunicationStyle,
    DNADiff,
    DNAMutation,
    DecisionProfile,
    EscalationProfile,
    EscalationTrigger,
    Heuristic,
    PersonalitySignal,
    RiskToleranceLevel,
)
from framework.personality.evolution_bridge import (
    DNAEvolutionBridge,
    EvolutionContext,
)
from framework.personality.extractor import PersonalityExtractor
from framework.personality.fitness import (
    PersonalityFitnessEvaluator,
    TraitFitness,
)
from framework.personality.injector import PersonalityInjector
from framework.personality.store import (
    FilePersonalityStore,
    PersonalityStore,
)
from framework.personality.synthesizer import PersonalitySynthesizer

__all__ = [
    "AgentPersonalityDNA",
    "BehaviorPattern",
    "CommunicationProfile",
    "CommunicationStyle",
    "DNADiff",
    "DNAMutation",
    "DNAEvolutionBridge",
    "DecisionProfile",
    "EscalationProfile",
    "EscalationTrigger",
    "EvolutionContext",
    "FilePersonalityStore",
    "Heuristic",
    "PersonalityExtractor",
    "PersonalityFitnessEvaluator",
    "PersonalityInjector",
    "PersonalitySignal",
    "PersonalityStore",
    "PersonalitySynthesizer",
    "RiskToleranceLevel",
    "TraitFitness",
]
