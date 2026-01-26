"""
Tests for the Guardrails Framework.
"""

import pytest
import time
from unittest.mock import MagicMock

from framework.runtime.guardrails import (
    Guardrail,
    GuardrailResult,
    GuardrailViolation,
    GuardrailContext,
    GuardrailSeverity,
    GuardrailPhase,
    GuardrailRegistry,
    BudgetGuardrail,
    RateLimitGuardrail,
    ContentFilterGuardrail,
    MaxStepsGuardrail,
    CustomGuardrail,
)


@pytest.fixture
def basic_context():
    """Create a basic guardrail context for testing."""
    return GuardrailContext(
        node_id="test_node",
        node_type="llm_generate",
        input_data={"query": "test query"},
        goal_id="test_goal",
        run_id="test_run_123",
        total_tokens=0,
        total_cost_usd=0.0,
        step_count=0,
    )


class TestGuardrailResult:
    """Tests for GuardrailResult creation."""

    def test_allow_creates_passing_result(self):
        result = GuardrailResult.allow("test", GuardrailPhase.PRE_EXECUTION)
        assert result.passed is True
        assert result.guardrail_id == "test"
        assert result.violation is None

    def test_deny_creates_failing_result(self):
        result = GuardrailResult.deny(
            guardrail_id="test",
            phase=GuardrailPhase.PRE_EXECUTION,
            message="Test violation",
            severity=GuardrailSeverity.HARD_BLOCK,
        )
        assert result.passed is False
        assert result.violation is not None
        assert result.violation.message == "Test violation"
        assert result.violation.severity == GuardrailSeverity.HARD_BLOCK


class TestBudgetGuardrail:
    """Tests for BudgetGuardrail."""

    def test_passes_when_under_limits(self, basic_context):
        guardrail = BudgetGuardrail(max_cost_usd=10.0, max_tokens=100000)
        basic_context.total_cost_usd = 5.0
        basic_context.total_tokens = 50000
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is True

    def test_blocks_when_cost_exceeded(self, basic_context):
        guardrail = BudgetGuardrail(max_cost_usd=10.0)
        basic_context.total_cost_usd = 15.0
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is False
        assert "Cost limit exceeded" in result.violation.message

    def test_blocks_when_tokens_exceeded(self, basic_context):
        guardrail = BudgetGuardrail(max_tokens=1000)
        basic_context.total_tokens = 1500
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is False
        assert "Token limit exceeded" in result.violation.message

    def test_warning_threshold(self, basic_context):
        guardrail = BudgetGuardrail(max_cost_usd=10.0, warning_threshold=0.8)
        basic_context.total_cost_usd = 8.5  # 85% of limit
        
        result = guardrail.check_pre_execution(basic_context)
        # Should pass but with warnings in metadata
        assert result.passed is True
        assert len(result.metadata.get("warnings", [])) > 0


class TestRateLimitGuardrail:
    """Tests for RateLimitGuardrail."""

    def test_passes_under_limit(self, basic_context):
        guardrail = RateLimitGuardrail(max_requests_per_minute=100)
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is True

    def test_blocks_when_minute_limit_exceeded(self, basic_context):
        guardrail = RateLimitGuardrail(max_requests_per_minute=3)
        
        # Make 3 successful requests
        for _ in range(3):
            result = guardrail.check_pre_execution(basic_context)
            assert result.passed is True
        
        # 4th request should be blocked
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is False
        assert "Rate limit exceeded" in result.violation.message

    def test_records_requests_over_time(self, basic_context):
        guardrail = RateLimitGuardrail(max_requests_per_minute=10)
        
        # Make some requests
        for _ in range(5):
            guardrail.check_pre_execution(basic_context)
        
        # Should have 5 recorded requests
        current_time = time.time()
        count = guardrail._count_requests_in_window(current_time, 60)
        assert count == 5


class TestContentFilterGuardrail:
    """Tests for ContentFilterGuardrail."""

    def test_passes_clean_content(self, basic_context):
        guardrail = ContentFilterGuardrail(
            blocked_keywords=["password", "secret"]
        )
        basic_context.input_data = {"message": "Hello world"}
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is True

    def test_blocks_keyword(self, basic_context):
        guardrail = ContentFilterGuardrail(
            blocked_keywords=["password", "secret"]
        )
        basic_context.input_data = {"message": "My password is 12345"}
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is False
        assert "Blocked content detected" in result.violation.message

    def test_blocks_regex_pattern(self, basic_context):
        guardrail = ContentFilterGuardrail(
            blocked_patterns=[r"api[_-]?key\s*[:=]\s*\S+"]
        )
        basic_context.input_data = {"message": "api_key=sk-12345abcde"}
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is False

    def test_case_insensitive_by_default(self, basic_context):
        guardrail = ContentFilterGuardrail(
            blocked_keywords=["password"]
        )
        basic_context.input_data = {"message": "My PASSWORD is hidden"}
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is False

    def test_post_execution_checks_output(self, basic_context):
        guardrail = ContentFilterGuardrail(
            blocked_keywords=["secret"]
        )
        basic_context.output_data = {"response": "The secret answer is 42"}
        
        result = guardrail.check_post_execution(basic_context)
        assert result.passed is False


class TestMaxStepsGuardrail:
    """Tests for MaxStepsGuardrail."""

    def test_passes_under_limit(self, basic_context):
        guardrail = MaxStepsGuardrail(max_steps=50)
        basic_context.step_count = 10
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is True

    def test_blocks_at_limit(self, basic_context):
        guardrail = MaxStepsGuardrail(max_steps=50)
        basic_context.step_count = 50
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is False
        assert "Max steps exceeded" in result.violation.message


class TestCustomGuardrail:
    """Tests for CustomGuardrail."""

    def test_custom_check_passes(self, basic_context):
        def always_pass(ctx):
            return True, None
        
        guardrail = CustomGuardrail(
            guardrail_id="always_pass",
            check_fn=always_pass,
        )
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is True

    def test_custom_check_fails(self, basic_context):
        def always_fail(ctx):
            return False, "Custom failure message"
        
        guardrail = CustomGuardrail(
            guardrail_id="always_fail",
            check_fn=always_fail,
        )
        
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is False
        assert result.violation.message == "Custom failure message"

    def test_custom_check_with_context(self, basic_context):
        def check_node_type(ctx):
            if ctx.node_type == "function":
                return False, "Function nodes not allowed"
            return True, None
        
        guardrail = CustomGuardrail(
            guardrail_id="node_type_check",
            check_fn=check_node_type,
        )
        
        # Should pass for llm_generate
        basic_context.node_type = "llm_generate"
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is True
        
        # Should fail for function
        basic_context.node_type = "function"
        result = guardrail.check_pre_execution(basic_context)
        assert result.passed is False


class TestGuardrailRegistry:
    """Tests for GuardrailRegistry."""

    def test_add_and_list_guardrails(self):
        registry = GuardrailRegistry()
        registry.add(BudgetGuardrail(max_cost_usd=10.0))
        registry.add(MaxStepsGuardrail(max_steps=50))
        
        guardrails = registry.list_all()
        assert len(guardrails) == 2

    def test_remove_guardrail(self):
        registry = GuardrailRegistry()
        registry.add(BudgetGuardrail(max_cost_usd=10.0))
        
        removed = registry.remove("budget")
        assert removed is True
        assert len(registry.list_all()) == 0

    def test_get_guardrail(self):
        registry = GuardrailRegistry()
        budget = BudgetGuardrail(max_cost_usd=10.0)
        registry.add(budget)
        
        found = registry.get("budget")
        assert found is budget

    def test_check_pre_execution_all(self, basic_context):
        registry = GuardrailRegistry()
        registry.add(BudgetGuardrail(max_cost_usd=10.0))
        registry.add(MaxStepsGuardrail(max_steps=50))
        
        results = registry.check_pre_execution(basic_context)
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_has_violations(self, basic_context):
        registry = GuardrailRegistry()
        registry.add(MaxStepsGuardrail(max_steps=5))
        basic_context.step_count = 10
        
        results = registry.check_pre_execution(basic_context)
        assert registry.has_violations(results) is True

    def test_get_hard_blocks(self, basic_context):
        registry = GuardrailRegistry()
        registry.add(MaxStepsGuardrail(max_steps=5, severity=GuardrailSeverity.HARD_BLOCK))
        registry.add(RateLimitGuardrail(max_requests_per_minute=1, severity=GuardrailSeverity.SOFT_BLOCK))
        
        basic_context.step_count = 10
        
        results = registry.check_pre_execution(basic_context)
        hard_blocks = registry.get_hard_blocks(results)
        
        # Only max_steps should be a hard block
        assert len(hard_blocks) == 1
        assert hard_blocks[0].guardrail_id == "max_steps"

    def test_disabled_guardrails_skipped(self, basic_context):
        registry = GuardrailRegistry()
        
        budget = BudgetGuardrail(max_cost_usd=10.0)
        budget.enabled = False
        registry.add(budget)
        
        results = registry.check_pre_execution(basic_context)
        assert len(results) == 0


class TestGuardrailViolation:
    """Tests for GuardrailViolation."""

    def test_to_dict(self):
        violation = GuardrailViolation(
            guardrail_id="test",
            message="Test message",
            severity=GuardrailSeverity.HARD_BLOCK,
            details={"key": "value"},
            suggested_action="Try again",
        )
        
        data = violation.to_dict()
        assert data["guardrail_id"] == "test"
        assert data["message"] == "Test message"
        assert data["severity"] == "hard_block"
        assert data["details"] == {"key": "value"}
        assert data["suggested_action"] == "Try again"
