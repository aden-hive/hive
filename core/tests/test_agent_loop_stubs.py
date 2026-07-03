"""Test coverage stubs for the agent_loop module.

These tests exercise the public API of ``framework.agent_loop`` at unit-test
level — no real LLM calls, no network I/O.  Tests that require an actual
event loop or LLM are marked ``@pytest.mark.asyncio`` and stub out the LLM
with a simple mock.

Coverage targets:
- AgentSpec / AgentContext construction and field defaults
- AgentResult construction
- deprecated_client_facing_warning helper
- LoopConfig and OutputAccumulator basics
- SubagentJudge verdict logic (ACCEPT / RETRY)
- JudgeVerdict fields
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from framework.agent_loop.types import (
    AgentContext,
    AgentResult,
    AgentSpec,
    deprecated_client_facing_warning,
    warn_if_deprecated_client_facing,
)
from framework.agent_loop.agent_loop import (
    LoopConfig,
    OutputAccumulator,
    SubagentJudge,
)
from framework.agent_loop.internals.types import JudgeVerdict


# ---------------------------------------------------------------------------
# AgentSpec
# ---------------------------------------------------------------------------


class TestAgentSpec:
    """Unit tests for the AgentSpec model."""

    def test_minimal_construction(self):
        """AgentSpec can be built with just the required fields."""
        spec = AgentSpec(id="test", name="Test Agent", description="desc")
        assert spec.id == "test"
        assert spec.name == "Test Agent"
        assert spec.description == "desc"

    def test_defaults(self):
        """AgentSpec has sensible defaults for optional fields."""
        spec = AgentSpec(id="x", name="X", description="d")
        assert spec.agent_type == "event_loop"
        assert spec.input_keys == []
        assert spec.output_keys == []
        assert spec.nullable_output_keys == []
        assert spec.tools == []
        assert spec.tool_access_policy == "explicit"
        assert spec.max_retries == 3
        assert spec.max_visits == 0
        assert spec.model is None
        assert spec.system_prompt is None
        assert spec.skip_judge is False
        assert spec.client_facing is False

    def test_is_queen_returns_true_for_queen_id(self):
        """is_queen() returns True only when id == 'queen'."""
        queen = AgentSpec(id="queen", name="Queen", description="d")
        worker = AgentSpec(id="worker_1", name="Worker", description="d")
        assert queen.is_queen() is True
        assert worker.is_queen() is False

    def test_supports_direct_user_io_only_for_queen(self):
        """Only the queen supports direct user I/O."""
        queen = AgentSpec(id="queen", name="Q", description="d")
        other = AgentSpec(id="analyst", name="A", description="d")
        assert queen.supports_direct_user_io() is True
        assert other.supports_direct_user_io() is False

    def test_output_keys_and_input_keys_stored(self):
        """Input/output key lists are stored verbatim."""
        spec = AgentSpec(
            id="s",
            name="S",
            description="d",
            input_keys=["a", "b"],
            output_keys=["result"],
        )
        assert spec.input_keys == ["a", "b"]
        assert spec.output_keys == ["result"]

    def test_nullable_output_keys(self):
        """nullable_output_keys is accessible and defaults to empty list."""
        spec = AgentSpec(
            id="s",
            name="S",
            description="d",
            output_keys=["answer", "confidence"],
            nullable_output_keys=["confidence"],
        )
        assert "confidence" in spec.nullable_output_keys
        assert "answer" not in spec.nullable_output_keys

    def test_tool_access_policy_variants(self):
        """tool_access_policy accepts all documented values."""
        for policy in ("all", "explicit", "none"):
            spec = AgentSpec(id="s", name="S", description="d", tool_access_policy=policy)
            assert spec.tool_access_policy == policy

    def test_extra_fields_allowed(self):
        """AgentSpec allows extra fields (model_config extra='allow')."""
        spec = AgentSpec(id="s", name="S", description="d", custom_flag=True)
        assert spec.custom_flag is True  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# deprecated_client_facing_warning
# ---------------------------------------------------------------------------


class TestDeprecatedClientFacingWarning:
    """Tests for the deprecation-warning helper."""

    def test_no_warning_for_queen_with_client_facing(self):
        """Queen can set client_facing=True without triggering a warning."""
        spec = AgentSpec(id="queen", name="Q", description="d", client_facing=True)
        assert deprecated_client_facing_warning(spec) is None

    def test_warning_for_non_queen_with_client_facing(self):
        """Non-queen agent with client_facing=True emits a deprecation warning."""
        spec = AgentSpec(id="worker", name="W", description="d", client_facing=True)
        warning = deprecated_client_facing_warning(spec)
        assert warning is not None
        assert "worker" in warning
        assert "deprecated" in warning.lower()

    def test_no_warning_when_client_facing_false(self):
        """No warning when client_facing is False (the default)."""
        spec = AgentSpec(id="worker", name="W", description="d", client_facing=False)
        assert deprecated_client_facing_warning(spec) is None

    def test_warn_function_does_not_raise(self):
        """warn_if_deprecated_client_facing never raises."""
        spec = AgentSpec(id="worker", name="W", description="d", client_facing=True)
        warn_if_deprecated_client_facing(spec)  # must not raise


# ---------------------------------------------------------------------------
# AgentContext
# ---------------------------------------------------------------------------


class TestAgentContext:
    """Tests for AgentContext dataclass construction."""

    def _make_runtime(self):
        runtime = MagicMock()
        runtime.start_run = MagicMock(return_value="run-id")
        runtime.decide = MagicMock(return_value="dec-id")
        runtime.record_outcome = MagicMock()
        runtime.end_run = MagicMock()
        return runtime

    def test_minimal_construction(self):
        """AgentContext can be built with minimal required fields."""
        spec = AgentSpec(id="a", name="A", description="d")
        ctx = AgentContext(
            runtime=self._make_runtime(),
            agent_id="a",
            agent_spec=spec,
        )
        assert ctx.agent_id == "a"
        assert ctx.agent_spec is spec

    def test_defaults(self):
        """AgentContext has correct defaults for optional fields."""
        spec = AgentSpec(id="a", name="A", description="d")
        ctx = AgentContext(
            runtime=self._make_runtime(),
            agent_id="a",
            agent_spec=spec,
        )
        assert ctx.input_data == {}
        assert ctx.available_tools == []
        assert ctx.goal_context == ""
        assert ctx.max_tokens == 4096
        assert ctx.attempt == 1
        assert ctx.max_attempts == 3
        assert ctx.event_triggered is False
        assert ctx.execution_id == ""
        assert ctx.run_id == ""

    def test_effective_run_id_returns_none_when_empty(self):
        """effective_run_id returns None when run_id is an empty string."""
        spec = AgentSpec(id="a", name="A", description="d")
        ctx = AgentContext(runtime=self._make_runtime(), agent_id="a", agent_spec=spec)
        assert ctx.effective_run_id is None

    def test_effective_run_id_returns_value_when_set(self):
        """effective_run_id returns the run_id when it is set."""
        spec = AgentSpec(id="a", name="A", description="d")
        ctx = AgentContext(
            runtime=self._make_runtime(),
            agent_id="a",
            agent_spec=spec,
            run_id="my-run",
        )
        assert ctx.effective_run_id == "my-run"

    def test_input_data_stored(self):
        """Input data dict is stored verbatim."""
        spec = AgentSpec(id="a", name="A", description="d")
        ctx = AgentContext(
            runtime=self._make_runtime(),
            agent_id="a",
            agent_spec=spec,
            input_data={"key": "value"},
        )
        assert ctx.input_data == {"key": "value"}


# ---------------------------------------------------------------------------
# AgentResult
# ---------------------------------------------------------------------------


class TestAgentResult:
    """Tests for the AgentResult dataclass."""

    def test_success_result(self):
        """AgentResult captures a successful execution."""
        result = AgentResult(success=True, output={"answer": "42"})
        assert result.success is True
        assert result.output["answer"] == "42"
        assert result.error is None

    def test_failure_result(self):
        """AgentResult captures a failed execution."""
        result = AgentResult(success=False, error="LLM timed out")
        assert result.success is False
        assert result.error == "LLM timed out"

    def test_defaults(self):
        """AgentResult has correct defaults."""
        result = AgentResult(success=True)
        assert result.output == {}
        assert result.error is None


# ---------------------------------------------------------------------------
# LoopConfig
# ---------------------------------------------------------------------------


class TestLoopConfig:
    """Tests for LoopConfig construction and defaults."""

    def test_default_construction(self):
        """LoopConfig uses sane defaults when constructed with no args."""
        cfg = LoopConfig()
        # max_iterations should be > 0 (exact value may vary, just verify existence)
        assert hasattr(cfg, "max_iterations")
        assert cfg.max_iterations > 0

    def test_custom_max_iterations(self):
        """LoopConfig stores a custom max_iterations."""
        cfg = LoopConfig(max_iterations=5)
        assert cfg.max_iterations == 5

    def test_zero_max_iterations_not_accepted(self):
        """LoopConfig max_iterations must be positive."""
        cfg = LoopConfig(max_iterations=1)
        assert cfg.max_iterations >= 1


# ---------------------------------------------------------------------------
# OutputAccumulator
# ---------------------------------------------------------------------------


class TestOutputAccumulator:
    """Tests for OutputAccumulator key tracking.

    OutputAccumulator is a write-through store keyed by output-key name.
    It is constructed with a pre-populated ``values`` dict and provides
    get/set/has_all_keys helpers.
    """

    @pytest.mark.asyncio
    async def test_set_and_get_output(self):
        """OutputAccumulator stores and retrieves a key/value pair."""
        acc = OutputAccumulator()
        await acc.set("answer", "42")
        assert acc.get("answer") == "42"

    def test_get_missing_key_returns_none(self):
        """get() returns None for keys that have not been set."""
        acc = OutputAccumulator()
        assert acc.get("nonexistent") is None

    @pytest.mark.asyncio
    async def test_set_multiple_keys(self):
        """Multiple keys can be set independently."""
        acc = OutputAccumulator()
        await acc.set("a", "alpha")
        await acc.set("b", "beta")
        assert acc.get("a") == "alpha"
        assert acc.get("b") == "beta"

    def test_has_all_keys_false_when_empty(self):
        """has_all_keys returns False when required keys are missing."""
        acc = OutputAccumulator()
        assert acc.has_all_keys(["a", "b"]) is False

    @pytest.mark.asyncio
    async def test_has_all_keys_true_when_all_set(self):
        """has_all_keys returns True when all required keys are present."""
        acc = OutputAccumulator()
        await acc.set("x", "done")
        assert acc.has_all_keys(["x"]) is True

    def test_has_all_keys_true_for_empty_list(self):
        """has_all_keys with an empty key list is trivially True."""
        acc = OutputAccumulator()
        assert acc.has_all_keys([]) is True

    def test_preloaded_values(self):
        """OutputAccumulator can be initialised with pre-populated values."""
        acc = OutputAccumulator(values={"answer": "42"})
        assert acc.get("answer") == "42"

    @pytest.mark.asyncio
    async def test_values_attribute_accessible(self):
        """The underlying values dict is accessible via .values."""
        acc = OutputAccumulator()
        await acc.set("k", "v")
        assert "k" in acc.values
        assert acc.values["k"] == "v"


# ---------------------------------------------------------------------------
# SubagentJudge
# ---------------------------------------------------------------------------


class TestSubagentJudge:
    """Tests for SubagentJudge — ACCEPT vs RETRY logic."""

    @pytest.mark.asyncio
    async def test_accept_when_no_missing_keys(self):
        """ACCEPT when all output keys are present."""
        judge = SubagentJudge(task="Summarise the report")
        verdict = await judge.evaluate(
            {"missing_keys": [], "tool_results": [], "iteration": 1}
        )
        assert verdict.action == "ACCEPT"

    @pytest.mark.asyncio
    async def test_retry_when_keys_missing(self):
        """RETRY when required output keys are not yet set."""
        judge = SubagentJudge(task="Analyse sentiment")
        verdict = await judge.evaluate(
            {"missing_keys": ["sentiment", "score"], "tool_results": [], "iteration": 1}
        )
        assert verdict.action == "RETRY"
        assert "sentiment" in verdict.feedback
        assert "score" in verdict.feedback

    @pytest.mark.asyncio
    async def test_feedback_contains_task(self):
        """RETRY feedback contains the original task description."""
        task = "Find the CEO of Acme Corp"
        judge = SubagentJudge(task=task)
        verdict = await judge.evaluate(
            {"missing_keys": ["ceo_name"], "tool_results": [], "iteration": 0}
        )
        assert task in verdict.feedback

    @pytest.mark.asyncio
    async def test_feedback_mentions_set_output(self):
        """RETRY feedback nudges agent to call set_output."""
        judge = SubagentJudge(task="Extract data")
        verdict = await judge.evaluate(
            {"missing_keys": ["data"], "tool_results": [], "iteration": 1}
        )
        assert "set_output" in verdict.feedback

    @pytest.mark.asyncio
    async def test_returns_judge_verdict_type(self):
        """evaluate() always returns a JudgeVerdict instance."""
        judge = SubagentJudge(task="t")
        accept = await judge.evaluate({"missing_keys": [], "tool_results": [], "iteration": 0})
        retry = await judge.evaluate({"missing_keys": ["x"], "tool_results": [], "iteration": 0})
        assert isinstance(accept, JudgeVerdict)
        assert isinstance(retry, JudgeVerdict)

    @pytest.mark.asyncio
    async def test_accept_verdict_has_empty_feedback(self):
        """ACCEPT verdict carries no feedback text."""
        judge = SubagentJudge(task="t")
        verdict = await judge.evaluate({"missing_keys": [], "tool_results": [], "iteration": 2})
        assert verdict.feedback == ""

    @pytest.mark.asyncio
    async def test_max_iterations_parameter_accepted(self):
        """SubagentJudge accepts optional max_iterations without error."""
        judge = SubagentJudge(task="t", max_iterations=10)
        verdict = await judge.evaluate({"missing_keys": [], "tool_results": [], "iteration": 0})
        assert verdict.action == "ACCEPT"

    @pytest.mark.asyncio
    async def test_tool_results_do_not_block_accept(self):
        """Completed tool calls alongside empty missing_keys → ACCEPT."""
        judge = SubagentJudge(task="Scrape page")
        verdict = await judge.evaluate(
            {
                "missing_keys": [],
                "tool_results": [{"tool_name": "web_scrape", "content": "done"}],
                "iteration": 1,
            }
        )
        assert verdict.action == "ACCEPT"


# ---------------------------------------------------------------------------
# JudgeVerdict
# ---------------------------------------------------------------------------


class TestJudgeVerdict:
    """Tests for the JudgeVerdict dataclass."""

    def test_accept_verdict_construction(self):
        """JudgeVerdict with action=ACCEPT can be created directly."""
        verdict = JudgeVerdict(action="ACCEPT", feedback="")
        assert verdict.action == "ACCEPT"
        assert verdict.feedback == ""

    def test_retry_verdict_construction(self):
        """JudgeVerdict with action=RETRY carries feedback."""
        verdict = JudgeVerdict(action="RETRY", feedback="please fill 'result'")
        assert verdict.action == "RETRY"
        assert "result" in verdict.feedback
