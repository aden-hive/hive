"""Test coverage stubs for the orchestrator module.

Tests the public API of ``framework.orchestrator`` at unit-test level.
No LLM calls, no network I/O.

Coverage targets:
- NodeSpec construction and field defaults
- NodeSpec.is_queen_node / supports_direct_user_io / agent_type alias
- deprecated_client_facing_warning helper
- DataBuffer read / write / write permission enforcement
- DataBufferWriteError on suspicious long content
- NodeContext construction and defaults
- NodeResult construction
- safe_eval: arithmetic, comparisons, booleans, context variables
- safe_eval: rejects unsafe operations (imports, function defs, exec)
- OutputValidator.validate_output_keys: pass / missing keys / nullable keys
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from framework.orchestrator.node import (
    DataBuffer,
    DataBufferWriteError,
    NodeContext,
    NodeResult,
    NodeSpec,
    deprecated_client_facing_warning,
    warn_if_deprecated_client_facing,
)
from framework.orchestrator.safe_eval import safe_eval
from framework.orchestrator.validator import OutputValidator, ValidationResult


# ---------------------------------------------------------------------------
# NodeSpec
# ---------------------------------------------------------------------------


class TestNodeSpec:
    """Tests for the NodeSpec Pydantic model."""

    def test_minimal_construction(self):
        """NodeSpec can be built with the three required fields."""
        spec = NodeSpec(id="n1", name="Node 1", description="Does stuff")
        assert spec.id == "n1"
        assert spec.name == "Node 1"
        assert spec.description == "Does stuff"

    def test_defaults(self):
        """NodeSpec uses expected defaults for optional fields."""
        spec = NodeSpec(id="n", name="N", description="d")
        assert spec.node_type == "event_loop"
        assert spec.input_keys == []
        assert spec.output_keys == []
        assert spec.nullable_output_keys == []
        assert spec.tools == []
        assert spec.tool_access_policy == "explicit"
        assert spec.max_retries == 3
        assert spec.max_node_visits == 0
        assert spec.model is None
        assert spec.system_prompt is None
        assert spec.skip_judge is False
        assert spec.client_facing is False

    def test_is_queen_node_true_for_queen_id(self):
        """is_queen_node() returns True only when id == 'queen'."""
        q = NodeSpec(id="queen", name="Q", description="d")
        w = NodeSpec(id="worker", name="W", description="d")
        assert q.is_queen_node() is True
        assert w.is_queen_node() is False

    def test_is_queen_alias(self):
        """is_queen is an alias for is_queen_node."""
        spec = NodeSpec(id="queen", name="Q", description="d")
        assert spec.is_queen() is True

    def test_agent_type_property(self):
        """agent_type property returns node_type (for AgentLoop compatibility)."""
        spec = NodeSpec(id="n", name="N", description="d", node_type="gcu")
        assert spec.agent_type == "gcu"

    def test_supports_direct_user_io_only_queen(self):
        """Only the queen node may talk directly to the user."""
        queen = NodeSpec(id="queen", name="Q", description="d")
        other = NodeSpec(id="analyst", name="A", description="d")
        assert queen.supports_direct_user_io() is True
        assert other.supports_direct_user_io() is False

    def test_output_and_input_keys_stored(self):
        """Input and output keys are stored verbatim."""
        spec = NodeSpec(
            id="n", name="N", description="d",
            input_keys=["x", "y"],
            output_keys=["result"],
        )
        assert spec.input_keys == ["x", "y"]
        assert spec.output_keys == ["result"]

    def test_nullable_output_keys(self):
        """nullable_output_keys is accessible and defaults to empty."""
        spec = NodeSpec(
            id="n", name="N", description="d",
            output_keys=["a", "b"],
            nullable_output_keys=["b"],
        )
        assert "b" in spec.nullable_output_keys
        assert "a" not in spec.nullable_output_keys

    def test_extra_fields_allowed(self):
        """NodeSpec allows extra fields (model_config extra='allow')."""
        spec = NodeSpec(id="n", name="N", description="d", custom_param=42)
        assert spec.custom_param == 42  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# deprecated_client_facing_warning
# ---------------------------------------------------------------------------


class TestDeprecatedClientFacingWarning:
    """Tests for the deprecated client_facing compatibility helper."""

    def test_no_warning_for_queen(self):
        """Queen node with client_facing=True does not generate a warning."""
        spec = NodeSpec(id="queen", name="Q", description="d", client_facing=True)
        assert deprecated_client_facing_warning(spec) is None

    def test_warning_for_non_queen_client_facing(self):
        """Non-queen node with client_facing=True generates a deprecation warning."""
        spec = NodeSpec(id="helper", name="H", description="d", client_facing=True)
        warning = deprecated_client_facing_warning(spec)
        assert warning is not None
        assert "helper" in warning
        assert "deprecated" in warning.lower()

    def test_no_warning_when_not_client_facing(self):
        """No warning when client_facing is False."""
        spec = NodeSpec(id="helper", name="H", description="d", client_facing=False)
        assert deprecated_client_facing_warning(spec) is None

    def test_warn_function_does_not_raise(self):
        """warn_if_deprecated_client_facing never raises, even for deprecated specs."""
        spec = NodeSpec(id="helper", name="H", description="d", client_facing=True)
        warn_if_deprecated_client_facing(spec)  # must not raise


# ---------------------------------------------------------------------------
# DataBuffer
# ---------------------------------------------------------------------------


class TestDataBuffer:
    """Tests for DataBuffer read / write / permission enforcement."""

    def test_write_and_read(self):
        """Writing a key stores it; reading retrieves it."""
        buf = DataBuffer()
        buf.write("answer", "42", validate=False)
        assert buf.read("answer") == "42"

    def test_write_overrides_existing(self):
        """Writing to an existing key replaces the value."""
        buf = DataBuffer()
        buf.write("k", "first", validate=False)
        buf.write("k", "second", validate=False)
        assert buf.read("k") == "second"

    def test_read_missing_key_returns_none(self):
        """Reading a key that was never written returns None."""
        buf = DataBuffer()
        assert buf.read("missing") is None

    def test_write_permission_enforced(self):
        """Writing a key not in the allowed-write set raises PermissionError."""
        buf = DataBuffer(_allowed_write={"allowed_key"})
        with pytest.raises(PermissionError):
            buf.write("forbidden_key", "value", validate=False)

    def test_write_allowed_key_succeeds(self):
        """Writing an allowed key does not raise."""
        buf = DataBuffer(_allowed_write={"ok"})
        buf.write("ok", "val", validate=False)
        assert buf.read("ok") == "val"

    def test_write_with_no_restriction_allows_any_key(self):
        """Empty _allowed_write set means any key can be written."""
        buf = DataBuffer()
        buf.write("anything", 123, validate=False)
        assert buf.read("anything") == 123

    def test_write_rejects_long_code_like_string(self):
        """A suspiciously long string with code patterns raises DataBufferWriteError."""
        buf = DataBuffer()
        # Craft a value > 5000 chars that contains a code indicator
        long_code = "def fake_function():\n    pass\n" * 200  # ~6000 chars with code
        with pytest.raises(DataBufferWriteError):
            buf.write("result", long_code, validate=True)

    def test_write_short_string_not_rejected(self):
        """Short strings are never flagged as code regardless of content."""
        buf = DataBuffer()
        buf.write("snippet", "def hello(): pass", validate=True)
        assert buf.read("snippet") == "def hello(): pass"

    def test_write_validate_false_skips_content_check(self):
        """validate=False bypasses the suspicious-content check."""
        buf = DataBuffer()
        long_code = "def fake():\n    pass\n" * 300
        buf.write("code", long_code, validate=False)  # must not raise
        assert buf.read("code") == long_code

    def test_write_non_string_not_content_checked(self):
        """Non-string values are never content-checked."""
        buf = DataBuffer()
        buf.write("num", 12345, validate=True)
        buf.write("lst", [1, 2, 3], validate=True)
        assert buf.read("num") == 12345
        assert buf.read("lst") == [1, 2, 3]

    @pytest.mark.asyncio
    async def test_write_async_stores_value(self):
        """write_async stores the value identically to write."""
        buf = DataBuffer()
        await buf.write_async("async_key", "async_val", validate=False)
        assert buf.read("async_key") == "async_val"

    @pytest.mark.asyncio
    async def test_write_async_permission_enforced(self):
        """write_async also enforces the allowed-write set."""
        buf = DataBuffer(_allowed_write={"a"})
        with pytest.raises(PermissionError):
            await buf.write_async("b", "v", validate=False)


# ---------------------------------------------------------------------------
# NodeResult
# ---------------------------------------------------------------------------


class TestNodeResult:
    """Tests for the NodeResult dataclass."""

    def test_success_result(self):
        """NodeResult captures a successful execution."""
        result = NodeResult(success=True, output={"answer": "42"})
        assert result.success is True
        assert result.output["answer"] == "42"
        assert result.error is None

    def test_failure_result(self):
        """NodeResult captures a failed execution."""
        result = NodeResult(success=False, error="Validation failed")
        assert result.success is False
        assert result.error == "Validation failed"

    def test_defaults(self):
        """NodeResult has empty output and no error by default."""
        result = NodeResult(success=True)
        assert result.output == {}
        assert result.error is None


# ---------------------------------------------------------------------------
# NodeContext
# ---------------------------------------------------------------------------


class TestNodeContext:
    """Tests for NodeContext construction and defaults."""

    def _make_runtime(self):
        rt = MagicMock()
        rt.start_run = MagicMock(return_value="run-id")
        rt.decide = MagicMock(return_value="dec-id")
        rt.record_outcome = MagicMock()
        return rt

    def test_minimal_construction(self):
        """NodeContext can be built with minimal required fields."""
        spec = NodeSpec(id="n", name="N", description="d")
        ctx = NodeContext(
            runtime=self._make_runtime(),
            node_id="n",
            node_spec=spec,
            buffer=DataBuffer(),
        )
        assert ctx.node_id == "n"
        assert ctx.node_spec is spec

    def test_defaults(self):
        """NodeContext uses correct defaults for optional fields."""
        spec = NodeSpec(id="n", name="N", description="d")
        ctx = NodeContext(
            runtime=self._make_runtime(),
            node_id="n",
            node_spec=spec,
            buffer=DataBuffer(),
        )
        assert ctx.input_data == {}
        assert ctx.available_tools == []
        assert ctx.goal_context == ""
        assert ctx.max_tokens == 4096
        assert ctx.attempt == 1
        assert ctx.max_attempts == 3
        assert ctx.continuous_mode is False

    def test_input_data_stored(self):
        """NodeContext stores the input_data dict verbatim."""
        spec = NodeSpec(id="n", name="N", description="d")
        ctx = NodeContext(
            runtime=self._make_runtime(),
            node_id="n",
            node_spec=spec,
            buffer=DataBuffer(),
            input_data={"prompt": "hello"},
        )
        assert ctx.input_data["prompt"] == "hello"


# ---------------------------------------------------------------------------
# safe_eval
# ---------------------------------------------------------------------------


class TestSafeEval:
    """Tests for the safe_eval expression evaluator."""

    # --- Arithmetic ---
    def test_integer_arithmetic(self):
        assert safe_eval("2 + 3") == 5
        assert safe_eval("10 - 4") == 6
        assert safe_eval("3 * 7") == 21
        assert safe_eval("8 / 2") == 4.0
        assert safe_eval("9 // 2") == 4
        assert safe_eval("10 % 3") == 1

    def test_power(self):
        assert safe_eval("2 ** 10") == 1024

    def test_float_arithmetic(self):
        assert abs(safe_eval("1.5 + 2.5") - 4.0) < 1e-9

    # --- Comparisons ---
    def test_comparison_true(self):
        assert safe_eval("3 > 2") is True
        assert safe_eval("2 < 5") is True
        assert safe_eval("4 == 4") is True
        assert safe_eval("3 != 5") is True
        assert safe_eval("3 >= 3") is True
        assert safe_eval("2 <= 2") is True

    def test_comparison_false(self):
        assert safe_eval("5 < 3") is False
        assert safe_eval("1 == 2") is False

    # --- Boolean logic ---
    def test_boolean_not(self):
        assert safe_eval("not True") is False
        assert safe_eval("not False") is True

    def test_membership(self):
        assert safe_eval("1 in [1, 2, 3]") is True
        assert safe_eval("4 in [1, 2, 3]") is False
        assert safe_eval("'x' not in ['a', 'b']") is True

    # --- String / list / dict literals ---
    def test_string_literal(self):
        assert safe_eval('"hello"') == "hello"

    def test_list_literal(self):
        assert safe_eval("[1, 2, 3]") == [1, 2, 3]

    def test_dict_literal(self):
        assert safe_eval('{"a": 1}') == {"a": 1}

    # --- Context variable access ---
    def test_context_variable(self):
        assert safe_eval("x + 1", context={"x": 10}) == 11

    def test_context_dict_get(self):
        assert safe_eval('d.get("k")', context={"d": {"k": "v"}}) == "v"

    def test_context_string_method(self):
        assert safe_eval('s.lower()', context={"s": "HELLO"}) == "hello"

    # --- Safe built-in functions ---
    def test_len_function(self):
        assert safe_eval("len([1, 2, 3])") == 3

    def test_str_function(self):
        assert safe_eval("str(42)") == "42"

    def test_int_function(self):
        assert safe_eval("int('7')") == 7

    def test_bool_function(self):
        assert safe_eval("bool(0)") is False
        assert safe_eval("bool(1)") is True

    # --- Rejection of unsafe operations ---
    def test_rejects_import(self):
        """import statements are not valid in expression mode."""
        with pytest.raises((ValueError, SyntaxError)):
            safe_eval("import os")

    def test_rejects_function_def(self):
        """Function definitions are statements, not expressions."""
        with pytest.raises((ValueError, SyntaxError)):
            safe_eval("def f(): pass")

    def test_rejects_attribute_exec(self):
        """__import__ is not in the sandbox context and raises NameError."""
        with pytest.raises((ValueError, TypeError, NameError)):
            safe_eval('__import__("os")')

    def test_rejects_large_power(self):
        """Power operations that would produce astronomically large ints are rejected."""
        with pytest.raises((ValueError, OverflowError)):
            safe_eval("2 ** 100000")

    def test_invalid_syntax_raises_syntax_error(self):
        """Malformed expressions raise SyntaxError."""
        with pytest.raises(SyntaxError):
            safe_eval("1 +* 2")


# ---------------------------------------------------------------------------
# OutputValidator
# ---------------------------------------------------------------------------


class TestOutputValidator:
    """Tests for OutputValidator.validate_output_keys."""

    def test_valid_output_passes(self):
        """All expected keys present with non-empty values → success."""
        validator = OutputValidator()
        result = validator.validate_output_keys(
            output={"answer": "42", "confidence": "high"},
            expected_keys=["answer", "confidence"],
        )
        assert result.success is True
        assert result.errors == []

    def test_missing_key_fails(self):
        """Missing expected keys → ValidationResult.success == False."""
        validator = OutputValidator()
        result = validator.validate_output_keys(
            output={"answer": "42"},
            expected_keys=["answer", "confidence"],
        )
        assert result.success is False
        assert any("confidence" in e for e in result.errors)

    def test_all_keys_missing_fails(self):
        """Empty output against non-empty expected_keys → failure."""
        validator = OutputValidator()
        result = validator.validate_output_keys(output={}, expected_keys=["x", "y"])
        assert result.success is False
        assert len(result.errors) >= 1

    def test_nullable_key_can_be_none(self):
        """nullable_keys allows None values without failing validation."""
        validator = OutputValidator()
        result = validator.validate_output_keys(
            output={"answer": "done", "optional": None},
            expected_keys=["answer", "optional"],
            nullable_keys=["optional"],
        )
        assert result.success is True

    def test_non_nullable_none_fails(self):
        """A None value for a non-nullable key is a validation error."""
        validator = OutputValidator()
        result = validator.validate_output_keys(
            output={"answer": None},
            expected_keys=["answer"],
        )
        assert result.success is False

    def test_no_expected_keys_always_passes(self):
        """No expected keys → validation always succeeds."""
        validator = OutputValidator()
        result = validator.validate_output_keys(output={}, expected_keys=[])
        assert result.success is True

    def test_validation_result_error_property(self):
        """ValidationResult.error joins errors into a single string."""
        result = ValidationResult(success=False, errors=["missing 'a'", "missing 'b'"])
        assert "a" in result.error
        assert "b" in result.error

    def test_validation_result_no_error_when_success(self):
        """ValidationResult.error is empty when there are no errors."""
        result = ValidationResult(success=True, errors=[])
        assert result.error == ""
