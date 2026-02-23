"""
Unit tests for Agent Personality DNA (APDNA) module.
"""

import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from framework.personality import (
    AgentPersonalityDNA,
    BehaviorPattern,
    CommunicationProfile,
    CommunicationStyle,
    DNADiff,
    DNAMutation,
    DecisionProfile,
    EscalationProfile,
    EscalationTrigger,
    EvolutionContext,
    FilePersonalityStore,
    Heuristic,
    PersonalityExtractor,
    PersonalityFitnessEvaluator,
    PersonalityInjector,
    PersonalitySignal,
    PersonalitySynthesizer,
    RiskToleranceLevel,
)
from framework.personality.dna import DNADiff
from framework.personality.evolution_bridge import DNAEvolutionBridge


class TestAgentPersonalityDNA:
    """Tests for AgentPersonalityDNA schema."""

    def test_create_dna(self):
        """Test creating a basic DNA instance."""
        dna = AgentPersonalityDNA(agent_id="test-agent")

        assert dna.agent_id == "test-agent"
        assert dna.schema_version == "1.0"
        assert dna.generation == 1
        assert dna.total_sessions_analyzed == 0

    def test_dna_with_traits(self):
        """Test creating DNA with specific traits."""
        dna = AgentPersonalityDNA(
            agent_id="test-agent",
            communication_style=CommunicationProfile(
                style=CommunicationStyle.CASUAL,
                formality_score=0.3,
                emoji_usage=0.7,
            ),
            decision_patterns=DecisionProfile(
                risk_tolerance=RiskToleranceLevel.AGGRESSIVE,
            ),
        )

        assert dna.communication_style.style == CommunicationStyle.CASUAL
        assert dna.communication_style.formality_score == 0.3
        assert dna.decision_patterns.risk_tolerance == RiskToleranceLevel.AGGRESSIVE

    def test_overall_success_rate(self):
        """Test success rate calculation."""
        dna = AgentPersonalityDNA(
            agent_id="test-agent",
            total_successful_sessions=7,
            total_failed_sessions=3,
        )

        assert dna.overall_success_rate == 0.7

    def test_update_session_stats(self):
        """Test session stats update."""
        dna = AgentPersonalityDNA(agent_id="test-agent")

        dna.update_session_stats(success=True)
        assert dna.total_sessions_analyzed == 1
        assert dna.total_successful_sessions == 1

        dna.update_session_stats(success=False)
        assert dna.total_sessions_analyzed == 2
        assert dna.total_failed_sessions == 1

    def test_add_heuristic(self):
        """Test adding domain heuristics."""
        dna = AgentPersonalityDNA(agent_id="test-agent")

        heuristic = dna.add_or_update_heuristic(
            context="tech_startups",
            rule="Use casual tone with emojis",
            success=True,
        )

        assert "tech_startups" in dna.domain_heuristics
        assert heuristic.rule == "Use casual tone with emojis"
        assert heuristic.success_count == 1

    def test_add_successful_pattern(self):
        """Test adding successful patterns."""
        dna = AgentPersonalityDNA(agent_id="test-agent")

        pattern = dna.add_successful_pattern(
            name="empathetic_opening",
            description="Start with empathetic greeting",
            example="I understand this is frustrating. Let me help.",
            context="support",
        )

        assert len(dna.successful_patterns) == 1
        assert pattern.name == "empathetic_opening"
        assert pattern.occurrence_count == 1

    def test_record_mutation(self):
        """Test recording mutations."""
        dna = AgentPersonalityDNA(agent_id="test-agent")

        mutation = dna.record_mutation(
            mutation_type="evolution",
            trait_path="communication_style.style",
            old_value="formal",
            new_value="casual",
            reason="Better engagement",
            trigger="user_feedback",
        )

        assert len(dna.mutation_history) == 1
        assert mutation.mutation_type == "evolution"
        assert mutation.trait_path == "communication_style.style"

    def test_compute_hash(self):
        """Test DNA hash computation."""
        dna1 = AgentPersonalityDNA(agent_id="test-agent")
        dna2 = AgentPersonalityDNA(agent_id="test-agent")

        hash1 = dna1.compute_hash()
        hash2 = dna2.compute_hash()

        assert hash1 == hash2
        assert len(hash1) == 16

    def test_to_prompt_block(self):
        """Test prompt block generation."""
        dna = AgentPersonalityDNA(
            agent_id="test-agent",
            communication_style=CommunicationProfile(
                style=CommunicationStyle.CASUAL,
                formality_score=0.3,
            ),
        )

        block = dna.to_prompt_block()

        assert "Personality DNA" in block
        assert "Communication Style" in block
        assert "casual" in block

    def test_serialization(self):
        """Test DNA serialization/deserialization."""
        dna = AgentPersonalityDNA(
            agent_id="test-agent",
            communication_style=CommunicationProfile(style=CommunicationStyle.TECHNICAL),
        )
        dna.add_or_update_heuristic("context1", "rule1", success=True)

        data = dna.model_dump(mode="json")
        restored = AgentPersonalityDNA.model_validate(data)

        assert restored.agent_id == dna.agent_id
        assert restored.communication_style.style == CommunicationStyle.TECHNICAL
        assert "context1" in restored.domain_heuristics


class TestFilePersonalityStore:
    """Tests for file-based DNA storage."""

    @pytest.fixture
    def temp_store(self):
        """Create temporary store for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            store = FilePersonalityStore(Path(tmpdir))
            yield store

    def test_save_and_load_dna(self, temp_store):
        """Test saving and loading DNA."""
        dna = AgentPersonalityDNA(agent_id="test-agent")
        dna.communication_style.style = CommunicationStyle.CASUAL

        temp_store.save_dna(dna)

        loaded = temp_store.load_dna("test-agent")

        assert loaded is not None
        assert loaded.agent_id == "test-agent"
        assert loaded.communication_style.style == CommunicationStyle.CASUAL

    def test_load_nonexistent_dna(self, temp_store):
        """Test loading DNA that doesn't exist."""
        loaded = temp_store.load_dna("nonexistent-agent")
        assert loaded is None

    def test_delete_dna(self, temp_store):
        """Test deleting DNA."""
        dna = AgentPersonalityDNA(agent_id="test-agent")
        temp_store.save_dna(dna)

        result = temp_store.delete_dna("test-agent")

        assert result is True
        assert temp_store.load_dna("test-agent") is None

    def test_list_agents(self, temp_store):
        """Test listing agents with DNA."""
        temp_store.save_dna(AgentPersonalityDNA(agent_id="agent-1"))
        temp_store.save_dna(AgentPersonalityDNA(agent_id="agent-2"))

        agents = temp_store.list_agents()

        assert len(agents) == 2
        assert "agent-1" in agents
        assert "agent-2" in agents

    def test_save_and_load_signals(self, temp_store):
        """Test saving and loading personality signals."""
        signals = [
            PersonalitySignal(
                session_id="session-1",
                agent_id="test-agent",
                trait_category="communication_style",
                trait_name="style",
                signal_type="observed",
                value="casual",
                confidence=0.8,
            ),
        ]

        temp_store.save_signals(signals)

        loaded = temp_store.load_signals("test-agent", "session-1")

        assert len(loaded) == 1
        assert loaded[0].trait_name == "style"

    def test_dna_history(self, temp_store):
        """Test DNA history tracking."""
        dna = AgentPersonalityDNA(agent_id="test-agent")
        temp_store.save_dna(dna)

        dna.generation = 2
        temp_store.save_dna(dna)

        history = temp_store.get_dna_history("test-agent")

        assert len(history) >= 1
        assert history[0].generation == 2

    def test_clone_dna(self, temp_store):
        """Test cloning DNA between agents."""
        source = AgentPersonalityDNA(agent_id="source-agent")
        source.communication_style.style = CommunicationStyle.TECHNICAL
        temp_store.save_dna(source)

        cloned = temp_store.clone_dna("source-agent", "target-agent")

        assert cloned is not None
        assert cloned.agent_id == "target-agent"
        assert cloned.communication_style.style == CommunicationStyle.TECHNICAL
        assert cloned.generation == source.generation + 1

    def test_path_traversal_protection(self, temp_store):
        """Test path traversal attack protection."""
        with pytest.raises(ValueError):
            temp_store.load_dna("../../../etc/passwd")

        with pytest.raises(ValueError):
            temp_store.load_dna("agent/../../../etc")


class TestPersonalityExtractor:
    """Tests for personality signal extraction."""

    @pytest.fixture
    def extractor(self):
        """Create extractor instance."""
        return PersonalityExtractor()

    @pytest.mark.asyncio
    async def test_extract_communication_signals(self, extractor):
        """Test extracting communication style signals."""
        conversations = [
            {"role": "assistant", "content": "Hey there! 👋 How can I help ya today?"},
            {"role": "user", "content": "I need help with my account"},
            {"role": "assistant", "content": "No problem! Let's sort this out real quick 😊"},
        ]

        signals = await extractor.extract_from_session(
            agent_id="test-agent",
            session_id="session-1",
            session_state={"status": "completed"},
            conversations=conversations,
        )

        comm_signals = [s for s in signals if s.trait_category == "communication_style"]

        assert len(comm_signals) > 0
        style_signal = next((s for s in comm_signals if s.trait_name == "style"), None)
        assert style_signal is not None

    @pytest.mark.asyncio
    async def test_extract_decision_signals(self, extractor):
        """Test extracting decision pattern signals."""
        decisions = [
            {
                "reasoning": "I'll verify this first to be safe",
                "options": [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}],
                "chosen_option_id": "a",
            },
        ]

        signals = await extractor.extract_from_session(
            agent_id="test-agent",
            session_id="session-1",
            session_state={"status": "completed"},
            decisions=decisions,
        )

        decision_signals = [s for s in signals if s.trait_category == "decision_patterns"]

        assert len(decision_signals) > 0

    @pytest.mark.asyncio
    async def test_extract_escalation_signals(self, extractor):
        """Test extracting escalation behavior signals."""
        conversations = [
            {"role": "assistant", "content": "I'm not sure about this. Let me ask for guidance."},
            {"role": "user", "content": "OK"},
            {"role": "assistant", "content": "I recommend consulting with a specialist."},
        ]

        signals = await extractor.extract_from_session(
            agent_id="test-agent",
            session_id="session-1",
            session_state={"status": "completed"},
            conversations=conversations,
        )

        escalation_signals = [s for s in signals if s.trait_category == "escalation_behavior"]

        assert len(escalation_signals) > 0

    def test_determine_session_outcome(self, extractor):
        """Test session outcome determination."""
        assert extractor._determine_session_outcome({"status": "completed"}) == "success"
        assert extractor._determine_session_outcome({"status": "failed"}) == "failure"
        assert extractor._determine_session_outcome({"status": "unknown"}) == "unknown"


class TestPersonalitySynthesizer:
    """Tests for personality signal synthesis."""

    @pytest.fixture
    def temp_store(self):
        """Create temporary store for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FilePersonalityStore(Path(tmpdir))

    @pytest.mark.asyncio
    async def test_synthesize_signals(self, temp_store):
        """Test synthesizing signals into DNA."""
        synthesizer = PersonalitySynthesizer(temp_store)

        signals = [
            PersonalitySignal(
                session_id="session-1",
                trait_category="communication_style",
                trait_name="style",
                signal_type="observed",
                value="casual",
                confidence=0.8,
                session_outcome="success",
            ),
        ]

        dna = await synthesizer.synthesize("test-agent", signals)

        assert dna is not None
        assert dna.total_sessions_analyzed == 1

    @pytest.mark.asyncio
    async def test_synthesize_preserves_existing(self, temp_store):
        """Test that synthesis preserves existing DNA."""
        existing = AgentPersonalityDNA(
            agent_id="test-agent",
            communication_style=CommunicationProfile(
                style=CommunicationStyle.FORMAL,
                sample_count=10,
            ),
        )
        temp_store.save_dna(existing)

        synthesizer = PersonalitySynthesizer(temp_store)

        signals = [
            PersonalitySignal(
                session_id="session-2",
                trait_category="communication_style",
                trait_name="style",
                signal_type="observed",
                value="casual",
                confidence=0.8,
                session_outcome="success",
            ),
        ]

        dna = await synthesizer.synthesize("test-agent", signals)

        assert dna is not None
        assert dna.communication_style.sample_count == 11


class TestPersonalityInjector:
    """Tests for personality prompt injection."""

    @pytest.fixture
    def temp_store(self):
        """Create temporary store for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FilePersonalityStore(Path(tmpdir))

    def test_generate_prompt_block(self, temp_store):
        """Test generating prompt block."""
        dna = AgentPersonalityDNA(
            agent_id="test-agent",
            communication_style=CommunicationProfile(
                style=CommunicationStyle.CASUAL,
                formality_score=0.3,
            ),
        )
        temp_store.save_dna(dna)

        injector = PersonalityInjector(temp_store)
        block = injector.generate_prompt_block("test-agent")

        assert "Personality DNA" in block
        assert "Communication Style" in block

    def test_generate_prompt_block_no_dna(self, temp_store):
        """Test generating prompt block when no DNA exists."""
        injector = PersonalityInjector(temp_store)
        block = injector.generate_prompt_block("nonexistent-agent")

        assert block == ""

    def test_inject_into_system_prompt(self, temp_store):
        """Test injecting personality into system prompt."""
        dna = AgentPersonalityDNA(agent_id="test-agent")
        temp_store.save_dna(dna)

        injector = PersonalityInjector(temp_store)

        base_prompt = "You are a helpful assistant."
        modified = injector.inject_into_system_prompt("test-agent", base_prompt)

        assert "Personality DNA" in modified
        assert "You are a helpful assistant." in modified

    def test_get_injection_metadata(self, temp_store):
        """Test getting injection metadata."""
        dna = AgentPersonalityDNA(
            agent_id="test-agent",
            total_sessions_analyzed=10,
        )
        temp_store.save_dna(dna)

        injector = PersonalityInjector(temp_store)
        metadata = injector.get_injection_metadata("test-agent")

        assert metadata["has_dna"] is True
        assert metadata["total_sessions"] == 10


class TestPersonalityFitnessEvaluator:
    """Tests for personality fitness evaluation."""

    @pytest.fixture
    def temp_store(self):
        """Create temporary store for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FilePersonalityStore(Path(tmpdir))

    @pytest.mark.asyncio
    async def test_evaluate_fitness(self, temp_store):
        """Test fitness evaluation."""
        dna = AgentPersonalityDNA(
            agent_id="test-agent",
            total_successful_sessions=8,
            total_failed_sessions=2,
        )
        temp_store.save_dna(dna)

        evaluator = PersonalityFitnessEvaluator(temp_store)
        report = await evaluator.evaluate_fitness("test-agent")

        assert "overall_fitness" in report
        assert "trait_scores" in report
        assert report["session_stats"]["success_rate"] == 0.8

    def test_get_mutation_recommendations(self, temp_store):
        """Test getting mutation recommendations."""
        dna = AgentPersonalityDNA(agent_id="test-agent")
        for i in range(10):
            dna.add_or_update_heuristic(f"context_{i}", f"rule_{i}", success=False)
        temp_store.save_dna(dna)

        evaluator = PersonalityFitnessEvaluator(temp_store)
        recommendations = evaluator.get_mutation_recommendations("test-agent", threshold=0.5)

        assert isinstance(recommendations, list)

    def test_should_preserve_dna(self, temp_store):
        """Test DNA preservation decision."""
        dna = AgentPersonalityDNA(
            agent_id="test-agent",
            total_successful_sessions=8,
            total_failed_sessions=2,
        )
        temp_store.save_dna(dna)

        evaluator = PersonalityFitnessEvaluator(temp_store)

        assert evaluator.should_preserve_dna("test-agent") is True


class TestDNAEvolutionBridge:
    """Tests for DNA evolution bridge."""

    @pytest.fixture
    def temp_store(self):
        """Create temporary store for testing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield FilePersonalityStore(Path(tmpdir))

    def test_prepare_for_evolution(self, temp_store):
        """Test preparing DNA for evolution."""
        dna = AgentPersonalityDNA(agent_id="test-agent")
        temp_store.save_dna(dna)

        bridge = DNAEvolutionBridge(temp_store)
        context = EvolutionContext(
            evolution_type="bug_fix",
            trigger="test_failure",
            reason="Fixed formatting bug",
        )

        preserved = bridge.prepare_for_evolution("test-agent", context)

        assert preserved is not None
        assert preserved.agent_id == "test-agent"

    def test_finalize_evolution_preserve(self, temp_store):
        """Test finalizing evolution with DNA preservation."""
        dna = AgentPersonalityDNA(
            agent_id="test-agent",
            communication_style=CommunicationProfile(style=CommunicationStyle.CASUAL),
        )
        temp_store.save_dna(dna)

        bridge = DNAEvolutionBridge(temp_store)
        context = EvolutionContext(
            evolution_type="bug_fix",
            trigger="test_failure",
            reason="Fixed formatting bug",
        )

        preserved = bridge.prepare_for_evolution("test-agent", context)
        final = bridge.finalize_evolution("test-agent", preserved, context)

        assert final.communication_style.style == CommunicationStyle.CASUAL
        assert final.generation == 2

    def test_finalize_evolution_mutate(self, temp_store):
        """Test finalizing evolution with DNA mutation."""
        dna = AgentPersonalityDNA(
            agent_id="test-agent",
            communication_style=CommunicationProfile(style=CommunicationStyle.FORMAL),
        )
        temp_store.save_dna(dna)

        bridge = DNAEvolutionBridge(temp_store)
        context = EvolutionContext(
            evolution_type="personality_fix",
            trigger="user_feedback",
            reason="Communication style too formal",
            failure_traits=["communication_style.style"],
        )

        preserved = bridge.prepare_for_evolution("test-agent", context)
        final = bridge.finalize_evolution("test-agent", preserved, context)

        assert final.generation == 2
        assert len(final.mutation_history) > 0

    def test_evolution_context(self):
        """Test evolution context properties."""
        context = EvolutionContext(
            evolution_type="personality_fix",
            trigger="user_feedback",
            reason="Agent communication style is too formal",
        )

        assert context.is_personality_related is True
        assert context.should_preserve_dna is False

    def test_evolution_checkpoint(self, temp_store):
        """Test creating evolution checkpoints."""
        dna = AgentPersonalityDNA(agent_id="test-agent")
        temp_store.save_dna(dna)

        bridge = DNAEvolutionBridge(temp_store)
        checkpoint_id = bridge.create_evolution_checkpoint("test-agent", "before-refactor")

        assert checkpoint_id is not None


class TestTraitFitness:
    """Tests for trait fitness tracking."""

    def test_fitness_calculation(self):
        """Test fitness score calculation."""
        from framework.personality.fitness import TraitFitness

        fitness = TraitFitness("test.trait", "value")
        fitness.success_count = 8
        fitness.failure_count = 2
        fitness.total_sessions = 10

        assert fitness.success_rate == 0.8
        assert fitness.fitness_score > 0.5

    def test_recommendation(self):
        """Test fitness recommendation."""
        from framework.personality.fitness import TraitFitness

        fitness = TraitFitness("test.trait", "value")
        fitness.success_count = 9
        fitness.failure_count = 1
        fitness.total_sessions = 10

        assert fitness.recommendation == "preserve"

    def test_record_outcome(self):
        """Test recording outcomes."""
        from framework.personality.fitness import TraitFitness

        fitness = TraitFitness("test.trait", "value")

        fitness.record_outcome(True)
        fitness.record_outcome(True)
        fitness.record_outcome(False)

        assert fitness.total_sessions == 3
        assert fitness.success_count == 2
        assert len(fitness.recent_outcomes) == 3


class TestHeuristic:
    """Tests for domain heuristics."""

    def test_success_rate(self):
        """Test heuristic success rate calculation."""
        heuristic = Heuristic(
            id="h1",
            context="tech_startups",
            rule="Use casual tone",
            success_count=8,
            failure_count=2,
        )

        assert heuristic.success_rate == 0.8

    def test_zero_division(self):
        """Test success rate with no data."""
        heuristic = Heuristic(
            id="h1",
            context="test",
            rule="test rule",
        )

        assert heuristic.success_rate == 0.5


class TestBehaviorPattern:
    """Tests for behavior patterns."""

    def test_pattern_creation(self):
        """Test creating a behavior pattern."""
        pattern = BehaviorPattern(
            id="p1",
            name="empathetic_opening",
            description="Start with empathy",
            pattern_type="success",
            examples=["I understand your frustration"],
            success_rate=0.9,
        )

        assert pattern.pattern_type == "success"
        assert len(pattern.examples) == 1
