"""Tests for safe_eval module.

Tests the safe expression evaluation used for edge conditions.

Run with:
    cd core && python -m pytest tests/test_safe_eval.py -v
"""

import pytest

from framework.graph.safe_eval import SAFE_FUNCTIONS, safe_eval


class TestSafeEvalBasics:
    """Test basic safe_eval functionality."""

    def test_simple_arithmetic(self):
        """Test basic arithmetic operations."""
        assert safe_eval("1 + 2") == 3
        assert safe_eval("10 - 5") == 5
        assert safe_eval("3 * 4") == 12
        assert safe_eval("10 / 2") == 5.0

    def test_comparison_operators(self):
        """Test comparison operators."""
        assert safe_eval("5 > 3") is True
        assert safe_eval("2 == 2") is True
        assert safe_eval("3 != 4") is True
        assert safe_eval("1 < 2") is True

    def test_boolean_operators(self):
        """Test boolean logic."""
        assert safe_eval("True and True") is True
        assert safe_eval("True or False") is True
        assert safe_eval("not False") is True

    def test_context_variables(self):
        """Test expressions with context variables."""
        assert safe_eval("x + y", {"x": 10, "y": 5}) == 15
        assert safe_eval("x > y", {"x": 10, "y": 5}) is True


class TestSafeEvalBuiltins:
    """Test that required built-in functions work."""

    def test_isinstance_basic(self):
        """isinstance should work for type checking."""
        assert safe_eval("isinstance(x, dict)", {"x": {}}) is True
        assert safe_eval("isinstance(x, list)", {"x": []}) is True
        assert safe_eval("isinstance(x, str)", {"x": "hello"}) is True
        assert safe_eval("isinstance(x, int)", {"x": 42}) is True
        assert safe_eval("isinstance(x, dict)", {"x": []}) is False

    def test_isinstance_with_dict_get(self):
        """Common pattern: isinstance check with dict.get()."""
        expr = "isinstance(output, dict) and output.get('success')"
        assert safe_eval(expr, {"output": {"success": True}}) is True
        assert safe_eval(expr, {"output": {"success": False}}) is False
        # When output is not a dict, isinstance returns False (short-circuit)
        assert safe_eval("isinstance(output, dict)", {"output": []}) is False

    def test_type_function(self):
        """type() should work for type checking."""
        # Note: __name__ access is blocked for security, but type() itself works
        assert safe_eval("type(x) == dict", {"x": {}}) is True
        assert safe_eval("type(x) == list", {"x": []}) is True
        assert safe_eval("type(x) == str", {"x": "hello"}) is True

    def test_len_function(self):
        """len() should work."""
        assert safe_eval("len(x)", {"x": [1, 2, 3]}) == 3
        assert safe_eval("len(x)", {"x": "hello"}) == 5
        assert safe_eval("len(x) > 0", {"x": [1]}) is True

    def test_range_function(self):
        """range() should work."""
        assert safe_eval("list(range(3))") == [0, 1, 2]
        assert safe_eval("list(range(1, 4))") == [1, 2, 3]

    def test_all_any_functions(self):
        """all() and any() should work."""
        assert safe_eval("all([True, True, True])") is True
        assert safe_eval("all([True, False, True])") is False
        assert safe_eval("any([False, True, False])") is True

    def test_min_max_sum(self):
        """min(), max(), sum() should work."""
        assert safe_eval("min([3, 1, 2])") == 1
        assert safe_eval("max([3, 1, 2])") == 3
        assert safe_eval("sum([1, 2, 3])") == 6


class TestSafeEvalEdgeConditions:
    """Test patterns commonly used in edge conditions."""

    def test_output_success_pattern(self):
        """Test common success checking pattern."""
        expr = "output.get('success') == True"
        assert safe_eval(expr, {"output": {"success": True}}) is True
        assert safe_eval(expr, {"output": {"success": False}}) is False

    def test_result_validation_pattern(self):
        """Test result validation patterns."""
        expr = "isinstance(result, dict) and 'data' in result"
        assert safe_eval(expr, {"result": {"data": [1, 2]}}) is True
        assert safe_eval(expr, {"result": {"error": "failed"}}) is False
        assert safe_eval(expr, {"result": "string"}) is False

    def test_memory_check_pattern(self):
        """Test memory variable checking."""
        expr = "memory.get('step_count', 0) < 10"
        assert safe_eval(expr, {"memory": {"step_count": 5}}) is True
        assert safe_eval(expr, {"memory": {"step_count": 15}}) is False
        assert safe_eval(expr, {"memory": {}}) is True


class TestSafeEvalSecurity:
    """Test that dangerous operations are blocked."""

    def test_private_attr_blocked(self):
        """Private attributes should be blocked."""
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("x.__class__", {"x": {}})

    def test_dunder_blocked(self):
        """Dunder attributes should be blocked."""
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("x.__dict__", {"x": {}})

    def test_undefined_name_raises_error(self):
        """Undefined names should raise NameError."""
        with pytest.raises(NameError):
            safe_eval("undefined_var")

    def test_unsafe_function_not_available(self):
        """Unsafe functions like eval/exec should not be available."""
        with pytest.raises(NameError):
            safe_eval("eval('1+1')")
        with pytest.raises(NameError):
            safe_eval("exec('x=1')")


class TestSafeFunctionsWhitelist:
    """Test that SAFE_FUNCTIONS contains expected functions."""

    def test_type_checking_functions_present(self):
        """Type checking functions should be in whitelist."""
        assert "isinstance" in SAFE_FUNCTIONS
        assert "issubclass" in SAFE_FUNCTIONS
        assert "type" in SAFE_FUNCTIONS

    def test_iteration_functions_present(self):
        """Iteration utility functions should be in whitelist."""
        assert "enumerate" in SAFE_FUNCTIONS
        assert "filter" in SAFE_FUNCTIONS
        assert "map" in SAFE_FUNCTIONS
        assert "range" in SAFE_FUNCTIONS
        assert "sorted" in SAFE_FUNCTIONS
        assert "reversed" in SAFE_FUNCTIONS
        assert "zip" in SAFE_FUNCTIONS
