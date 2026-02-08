"""
Structural tests for Support Debugger Agent.

Tests graph topology, edge routing, loop termination, and mock execution
without real LLM calls or network access.

Follows patterns from core/tests/test_graph_executor.py.
"""

import json
from pathlib import Path

import pytest

from framework.graph.edge import EdgeCondition
from framework.graph.executor import GraphExecutor
from framework.graph.goal import Goal
from framework.graph.node import NodeResult
from framework.graph.output_cleaner import CleansingConfig
from framework.llm.provider import Tool

# Disable output cleansing in tests — it has no LLM and corrupts
# result.output by overwriting it with memory.read_all() during
# the validation-then-clean path.
_NO_CLEANSING = CleansingConfig(enabled=False)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_ticket():
    """Load sample ticket from fixtures."""
    with open(FIXTURES_DIR / "sample_ticket.json") as f:
        return json.load(f)


@pytest.fixture
def agent():
    """Create a fresh SupportDebuggerAgent."""
    from examples.templates.support_debugger.agent import SupportDebuggerAgent

    return SupportDebuggerAgent()


@pytest.fixture
def graph(agent):
    """Build the GraphSpec from the agent."""
    return agent._build_graph()


@pytest.fixture
def mock_tools():
    """Create minimal Tool stubs matching the investigate node's tool declarations."""
    return [
        Tool(name="search_knowledge_base", description="mock"),
        Tool(name="fetch_ticket_history", description="mock"),
        Tool(name="fetch_runtime_logs", description="mock"),
    ]


# ---------------------------------------------------------------------------
# Dummy runtime (no real logging) — mirrors core/tests/test_graph_executor.py
# ---------------------------------------------------------------------------


class DummyRuntime:
    def start_run(self, **kwargs):
        return "run-1"

    def end_run(self, **kwargs):
        pass

    def report_problem(self, **kwargs):
        pass


# ---------------------------------------------------------------------------
# Fake node implementations for deterministic testing
# ---------------------------------------------------------------------------


class FakeBuildContext:
    """Returns a fixed TechnicalContext."""

    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={
                "technical_context": {
                    "product": "Automate",
                    "platform": "macOS",
                    "framework": "Pytest",
                    "language": "Python",
                    "confidence": 0.9,
                }
            },
            tokens_used=1,
            latency_ms=1,
        )


class FakeGenerateHypotheses:
    """Returns a fixed hypothesis list."""

    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={
                "hypotheses": [
                    {
                        "description": "Missing framework_name in config",
                        "category": "config",
                        "confidence": 0.6,
                        "required_evidence": ["runtime logs", "docs"],
                        "resolved": False,
                    },
                    {
                        "description": "SDK version incompatibility",
                        "category": "dependency",
                        "confidence": 0.3,
                        "required_evidence": ["package versions"],
                        "resolved": False,
                    },
                ]
            },
            tokens_used=1,
            latency_ms=1,
        )


class FakeInvestigate:
    """Returns fixed evidence."""

    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={
                "evidence": [
                    {
                        "tool_name": "fetch_runtime_logs",
                        "query_used": "session_id=abc123",
                        "summary": "Logs show missing framework_name key",
                        "evidence": [
                            {
                                "source_type": "logs",
                                "source_id": "abc123",
                                "snippet": "ValueError: Missing required key 'framework_name'",
                                "metadata": {},
                            }
                        ],
                        "confidence": 0.9,
                    }
                ]
            },
            tokens_used=1,
            latency_ms=1,
        )


class FakeRefineComplete:
    """Returns refined hypotheses with investigation_complete=True."""

    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={
                "hypotheses": [
                    {
                        "description": "Missing framework_name in config",
                        "category": "config",
                        "confidence": 0.95,
                        "required_evidence": ["runtime logs", "docs"],
                        "resolved": False,
                    },
                    {
                        "description": "SDK version incompatibility",
                        "category": "dependency",
                        "confidence": 0.1,
                        "required_evidence": ["package versions"],
                        "resolved": True,
                    },
                ],
                "investigation_complete": True,
            },
            tokens_used=1,
            latency_ms=1,
        )


class FakeRefineIncomplete:
    """Returns refined hypotheses with investigation_complete=False."""

    call_count: int = 0

    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        self.call_count += 1
        # Complete on second call to prevent infinite loop
        complete = self.call_count >= 2
        return NodeResult(
            success=True,
            output={
                "hypotheses": [
                    {
                        "description": "Missing framework_name in config",
                        "category": "config",
                        "confidence": 0.7 if not complete else 0.95,
                        "required_evidence": ["runtime logs", "docs"],
                        "resolved": False,
                    },
                ],
                "investigation_complete": complete,
            },
            tokens_used=1,
            latency_ms=1,
        )


class FakeGenerateResponse:
    """Returns a fixed final response."""

    def validate_input(self, ctx):
        return []

    async def execute(self, ctx):
        return NodeResult(
            success=True,
            output={
                "final_response": {
                    "root_cause": "Missing framework_name in browserstack.yml",
                    "explanation": "The SDK requires framework_name to be set.",
                    "fix_steps": ["Add framework_name: pytest to browserstack.yml"],
                    "config_snippet": "framework_name: pytest",
                    "validation_steps": ["Re-run and check dashboard"],
                    "confidence": 0.95,
                }
            },
            tokens_used=1,
            latency_ms=1,
        )


# ---------------------------------------------------------------------------
# Test 1: Validate passes
# ---------------------------------------------------------------------------


class TestValidation:
    def test_validate_passes(self, agent):
        """Agent structural validation must pass."""
        result = agent.validate()
        assert result["valid"], f"Validation errors: {result['errors']}"

    def test_validate_no_warnings(self, agent):
        """Validation should produce no warnings."""
        result = agent.validate()
        assert result["warnings"] == []


# ---------------------------------------------------------------------------
# Test 2: Graph topology
# ---------------------------------------------------------------------------


class TestGraphTopology:
    def test_graph_has_five_nodes(self, graph):
        assert len(graph.nodes) == 5

    def test_graph_has_five_edges(self, graph):
        assert len(graph.edges) == 5

    def test_entry_node(self, graph):
        assert graph.entry_node == "build-context"

    def test_terminal_node(self, graph):
        assert "generate-response" in graph.terminal_nodes

    def test_all_nodes_reachable_from_entry(self, graph):
        """Every node must be reachable via edges from the entry node."""
        reachable = set()
        frontier = {graph.entry_node}
        while frontier:
            current = frontier.pop()
            if current in reachable:
                continue
            reachable.add(current)
            for edge in graph.get_outgoing_edges(current):
                frontier.add(edge.target)
        node_ids = {n.id for n in graph.nodes}
        assert reachable == node_ids, f"Unreachable: {node_ids - reachable}"

    def test_investigate_has_tools(self, graph):
        node = graph.get_node("investigate")
        assert len(node.tools) == 3

    def test_loop_edges_from_refine(self, graph):
        outgoing = graph.get_outgoing_edges("refine-hypotheses")
        assert len(outgoing) == 2
        targets = {e.target for e in outgoing}
        assert targets == {"investigate", "generate-response"}

    def test_conditional_edges_have_expressions(self, graph):
        for edge in graph.edges:
            if edge.condition == EdgeCondition.CONDITIONAL:
                assert edge.condition_expr, f"Edge {edge.id} missing condition_expr"


# ---------------------------------------------------------------------------
# Test 3: Mock run completes (full graph with fake nodes)
# ---------------------------------------------------------------------------


class TestRunMock:
    @pytest.mark.asyncio
    async def test_run_mock_completes(self, graph, mock_tools):
        """Full graph execution with fake nodes must succeed."""
        runtime = DummyRuntime()
        executor = GraphExecutor(
            runtime=runtime,
            tools=mock_tools,
            cleansing_config=_NO_CLEANSING,
            node_registry={
                "build-context": FakeBuildContext(),
                "generate-hypotheses": FakeGenerateHypotheses(),
                "investigate": FakeInvestigate(),
                "refine-hypotheses": FakeRefineComplete(),
                "generate-response": FakeGenerateResponse(),
            },
        )

        goal = Goal(
            id="support-debugging",
            name="test-goal",
            description="test",
        )

        result = await executor.execute(
            graph=graph,
            goal=goal,
            input_data={
                "ticket": {
                    "subject": "Test",
                    "description": "Test description",
                }
            },
        )

        assert result.success is True
        assert result.steps_executed >= 5
        assert "build-context" in result.path
        assert "generate-response" in result.path

    @pytest.mark.asyncio
    async def test_output_accumulates_investigation_state(self, graph, mock_tools):
        """Execution output must include accumulated investigation state."""
        runtime = DummyRuntime()
        executor = GraphExecutor(
            runtime=runtime,
            tools=mock_tools,
            cleansing_config=_NO_CLEANSING,
            node_registry={
                "build-context": FakeBuildContext(),
                "generate-hypotheses": FakeGenerateHypotheses(),
                "investigate": FakeInvestigate(),
                "refine-hypotheses": FakeRefineComplete(),
                "generate-response": FakeGenerateResponse(),
            },
        )

        goal = Goal(
            id="support-debugging",
            name="test-goal",
            description="test",
        )

        result = await executor.execute(
            graph=graph,
            goal=goal,
            input_data={"ticket": {"subject": "T", "description": "D"}},
        )

        assert result.success is True
        # Intermediate outputs accumulate in memory via edge map_inputs.
        # Terminal node output (generate-response) is NOT in memory
        # because there are no outgoing edges from it.
        assert "technical_context" in result.output
        assert "hypotheses" in result.output
        assert "evidence" in result.output
        assert "investigation_complete" in result.output
        assert result.output["investigation_complete"] is True


# ---------------------------------------------------------------------------
# Test 4: Loop terminates
# ---------------------------------------------------------------------------


class TestLoopTermination:
    @pytest.mark.asyncio
    async def test_loop_terminates_on_convergence(self, graph, mock_tools):
        """When refine returns investigation_complete=True, loop exits."""
        runtime = DummyRuntime()
        executor = GraphExecutor(
            runtime=runtime,
            tools=mock_tools,
            cleansing_config=_NO_CLEANSING,
            node_registry={
                "build-context": FakeBuildContext(),
                "generate-hypotheses": FakeGenerateHypotheses(),
                "investigate": FakeInvestigate(),
                "refine-hypotheses": FakeRefineComplete(),
                "generate-response": FakeGenerateResponse(),
            },
        )

        goal = Goal(
            id="support-debugging",
            name="test-goal",
            description="test",
        )

        result = await executor.execute(
            graph=graph,
            goal=goal,
            input_data={"ticket": {"subject": "T", "description": "D"}},
        )

        assert result.success is True
        # With FakeRefineComplete (immediate True), the loop should not
        # revisit investigate after the first refine pass.
        # Path: build-context → generate-hypotheses → investigate →
        #        refine-hypotheses → generate-response
        assert result.path.count("investigate") == 1

    @pytest.mark.asyncio
    async def test_loop_iterates_when_incomplete(self, graph, mock_tools):
        """When refine returns investigation_complete=False first, loop continues."""
        runtime = DummyRuntime()
        refine_node = FakeRefineIncomplete()
        executor = GraphExecutor(
            runtime=runtime,
            tools=mock_tools,
            cleansing_config=_NO_CLEANSING,
            node_registry={
                "build-context": FakeBuildContext(),
                "generate-hypotheses": FakeGenerateHypotheses(),
                "investigate": FakeInvestigate(),
                "refine-hypotheses": refine_node,
                "generate-response": FakeGenerateResponse(),
            },
        )

        goal = Goal(
            id="support-debugging",
            name="test-goal",
            description="test",
        )

        result = await executor.execute(
            graph=graph,
            goal=goal,
            input_data={"ticket": {"subject": "T", "description": "D"}},
        )

        assert result.success is True
        # FakeRefineIncomplete returns False on first call, True on second.
        # So investigate should be visited twice.
        assert result.path.count("investigate") == 2
        assert refine_node.call_count == 2


# ---------------------------------------------------------------------------
# Test 5: Edge routing
# ---------------------------------------------------------------------------


class TestEdgeRouting:
    @pytest.mark.asyncio
    async def test_complete_routes_to_response(self, graph, mock_tools):
        """investigation_complete=True must route to generate-response."""
        runtime = DummyRuntime()
        executor = GraphExecutor(
            runtime=runtime,
            tools=mock_tools,
            cleansing_config=_NO_CLEANSING,
            node_registry={
                "build-context": FakeBuildContext(),
                "generate-hypotheses": FakeGenerateHypotheses(),
                "investigate": FakeInvestigate(),
                "refine-hypotheses": FakeRefineComplete(),
                "generate-response": FakeGenerateResponse(),
            },
        )

        goal = Goal(
            id="support-debugging",
            name="test-goal",
            description="test",
        )

        result = await executor.execute(
            graph=graph,
            goal=goal,
            input_data={"ticket": {"subject": "T", "description": "D"}},
        )

        assert result.success is True
        # After refine-hypotheses (complete), next node should be generate-response
        refine_idx = result.path.index("refine-hypotheses")
        assert result.path[refine_idx + 1] == "generate-response"

    @pytest.mark.asyncio
    async def test_incomplete_routes_to_investigate(self, graph, mock_tools):
        """investigation_complete=False must route back to investigate."""
        runtime = DummyRuntime()
        refine_node = FakeRefineIncomplete()
        executor = GraphExecutor(
            runtime=runtime,
            tools=mock_tools,
            cleansing_config=_NO_CLEANSING,
            node_registry={
                "build-context": FakeBuildContext(),
                "generate-hypotheses": FakeGenerateHypotheses(),
                "investigate": FakeInvestigate(),
                "refine-hypotheses": refine_node,
                "generate-response": FakeGenerateResponse(),
            },
        )

        goal = Goal(
            id="support-debugging",
            name="test-goal",
            description="test",
        )

        result = await executor.execute(
            graph=graph,
            goal=goal,
            input_data={"ticket": {"subject": "T", "description": "D"}},
        )

        assert result.success is True
        # First refine returns incomplete → should route back to investigate
        first_refine = result.path.index("refine-hypotheses")
        assert result.path[first_refine + 1] == "investigate"

    @pytest.mark.asyncio
    async def test_on_success_edges_chain_correctly(self, graph, mock_tools):
        """ON_SUCCESS edges must chain: build-context → generate-hypotheses → investigate."""
        runtime = DummyRuntime()
        executor = GraphExecutor(
            runtime=runtime,
            tools=mock_tools,
            cleansing_config=_NO_CLEANSING,
            node_registry={
                "build-context": FakeBuildContext(),
                "generate-hypotheses": FakeGenerateHypotheses(),
                "investigate": FakeInvestigate(),
                "refine-hypotheses": FakeRefineComplete(),
                "generate-response": FakeGenerateResponse(),
            },
        )

        goal = Goal(
            id="support-debugging",
            name="test-goal",
            description="test",
        )

        result = await executor.execute(
            graph=graph,
            goal=goal,
            input_data={"ticket": {"subject": "T", "description": "D"}},
        )

        assert result.success is True
        assert result.path[0] == "build-context"
        assert result.path[1] == "generate-hypotheses"
        assert result.path[2] == "investigate"
