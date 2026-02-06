"""Tests for safe_eval expression evaluator with structured exceptions."""

import pytest

from framework.graph.safe_eval import (
    SafeEvalAttributeError,
    SafeEvalError,
    SafeEvalNameError,
    SafeEvalSecurityError,
    SafeEvalTypeError,
    safe_eval,
)


class TestSafeEvalBasics:
    """Test basic safe_eval functionality."""

    def test_simple_arithmetic(self):
        """Test basic arithmetic expressions."""
        assert safe_eval("2 + 3") == 5
        assert safe_eval("10 - 4") == 6
        assert safe_eval("3 * 4") == 12
        assert safe_eval("10 / 2") == 5.0

    def test_with_variables(self):
        """Test expressions with variables from context."""
        ctx = {"x": 10, "y": 5}
        assert safe_eval("x + y", context=ctx) == 15
        assert safe_eval("x * y", context=ctx) == 50
        assert safe_eval("x > y", context=ctx) is True

    def test_comparisons(self):
        """Test comparison operators."""
        assert safe_eval("5 > 3") is True
        assert safe_eval("5 < 3") is False
        assert safe_eval("5 == 5") is True
        assert safe_eval("5 != 3") is True

    def test_boolean_operators(self):
        """Test boolean operations."""
        assert safe_eval("True and True") is True
        assert safe_eval("True and False") is False
        assert safe_eval("True or False") is True
        assert safe_eval("not False") is True

    def test_safe_builtins(self):
        """Test safe builtin functions."""
        assert safe_eval("len([1, 2, 3])") == 3
        assert safe_eval("max([1, 5, 3])") == 5
        assert safe_eval("min([1, 5, 3])") == 1
        assert safe_eval("sum([1, 2, 3])") == 6

    def test_collections(self):
        """Test list, dict, tuple creation."""
        assert safe_eval("[1, 2, 3]") == [1, 2, 3]
        assert safe_eval("{'a': 1, 'b': 2}") == {"a": 1, "b": 2}
        assert safe_eval("(1, 2, 3)") == (1, 2, 3)

    def test_string_methods(self):
        """Test allowed string methods."""
        assert safe_eval("'hello'.upper()") == "HELLO"
        assert safe_eval("'HELLO'.lower()") == "hello"
        assert safe_eval("'hello world'.split()") == ["hello", "world"]
        assert safe_eval("'  hello  '.strip()") == "hello"

    def test_dict_methods(self):
        """Test allowed dict methods."""
        ctx = {"data": {"a": 1, "b": 2}}
        assert safe_eval("data.get('a')", context=ctx) == 1
        assert safe_eval("data.get('c', 99)", context=ctx) == 99
        assert set(safe_eval("data.keys()", context=ctx)) == {"a", "b"}


class TestSafeEvalSecurityErrors:
    """Test that unsafe operations raise SafeEvalSecurityError."""

    def test_disallow_import(self):
        """Test that import statements are blocked."""
        # import is a statement, not an expression, so it raises SyntaxError in eval mode
        with pytest.raises(SyntaxError):
            safe_eval("import os")

    def test_disallow_exec(self):
        """Test that exec is blocked."""
        # exec is not in SAFE_FUNCTIONS, so accessing it raises SafeEvalNameError
        with pytest.raises(SafeEvalNameError):
            safe_eval("exec('x = 1')")

    def test_disallow_eval(self):
        """Test that eval is blocked."""
        # eval is not in SAFE_FUNCTIONS, so accessing it raises SafeEvalNameError
        with pytest.raises(SafeEvalNameError):
            safe_eval("eval('1 + 1')")

    def test_disallow_private_attribute_access(self):
        """Test that private attribute access is blocked."""
        ctx = {"obj": object()}
        with pytest.raises(SafeEvalSecurityError) as exc_info:
            safe_eval("obj.__class__", context=ctx)
        assert "private attribute" in str(exc_info.value).lower()

    def test_disallow_forbidden_function_call(self):
        """Test that calling non-whitelisted functions raises error."""
        # open is not in SAFE_FUNCTIONS, so accessing it raises SafeEvalNameError
        with pytest.raises(SafeEvalNameError):
            safe_eval("open('file.txt')")

    def test_error_context_shows_allowed_functions(self):
        """Test that error message hints at available functions when accessing undefined name."""
        with pytest.raises(SafeEvalNameError) as exc_info:
            safe_eval("os.system('ls')")
        error_msg = str(exc_info.value)
        # Should mention available functions as context hint
        assert "Available" in error_msg or "len" in error_msg


class TestSafeEvalNameError:
    """Test that undefined variables raise SafeEvalNameError."""

    def test_undefined_variable(self):
        """Test that accessing undefined variables raises SafeEvalNameError."""
        with pytest.raises(SafeEvalNameError) as exc_info:
            safe_eval("undefined_var")
        assert "not defined" in str(exc_info.value).lower()

    def test_error_context_shows_available_names(self):
        """Test that error includes helpful context about available names."""
        ctx = {"x": 1, "y": 2}
        with pytest.raises(SafeEvalNameError) as exc_info:
            safe_eval("z", context=ctx)
        error_msg = str(exc_info.value)
        # Should hint at available variables
        assert "Available" in error_msg or "x" in error_msg or "y" in error_msg


class TestSafeEvalAttributeError:
    """Test that invalid attribute access raises SafeEvalAttributeError."""

    def test_nonexistent_attribute(self):
        """Test that accessing nonexistent attributes raises error."""
        ctx = {"data": {"a": 1}}
        with pytest.raises(SafeEvalAttributeError):
            safe_eval("data.nonexistent_attr", context=ctx)

    def test_forbidden_private_attribute(self):
        """Test that accessing private attributes is blocked."""
        with pytest.raises(SafeEvalSecurityError):  # Security error, not attribute error
            safe_eval("'hello'._something")


class TestSafeEvalErrorContext:
    """Test that errors include helpful context information."""

    def test_error_has_message(self):
        """Test that errors have a descriptive message."""
        with pytest.raises(SafeEvalError) as exc_info:
            safe_eval("undefined")
        assert len(str(exc_info.value)) > 0

    def test_syntax_error_on_invalid_syntax(self):
        """Test that invalid syntax raises SyntaxError with context."""
        with pytest.raises(SyntaxError) as exc_info:
            safe_eval("x +")
        assert "Invalid syntax" in str(exc_info.value)

    def test_multiple_errors_in_complex_expr(self):
        """Test error handling in complex expressions."""
        # Undefined variable should take precedence
        with pytest.raises(SafeEvalNameError):
            safe_eval("x + undefined_y", context={"x": 1})


class TestSafeEvalEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_nested_structures(self):
        """Test nested list and dict structures."""
        expr = "{'items': [1, 2, 3], 'count': len([1, 2, 3])}"
        result = safe_eval(expr)
        assert result == {"items": [1, 2, 3], "count": 3}

    def test_chained_method_calls(self):
        """Test chained safe method calls."""
        assert safe_eval("'  HELLO  '.lower().strip()") == "hello"

    def test_subscript_access(self):
        """Test subscript notation."""
        ctx = {"data": [10, 20, 30]}
        assert safe_eval("data[1]", context=ctx) == 20

    def test_empty_context(self):
        """Test with empty context (only builtins)."""
        assert safe_eval("len([])") == 0
        assert safe_eval("max([5, 3, 1])") == 5

    def test_ternary_expression(self):
        """Test ternary/conditional expressions."""
        assert safe_eval("1 if True else 2") == 1
        assert safe_eval("1 if False else 2") == 2

    def test_complex_boolean_expression(self):
        """Test complex boolean logic."""
        ctx = {"x": 5, "y": 10}
        assert safe_eval("(x > 0) and (y < 20)", context=ctx) is True
        assert safe_eval("(x < 0) or (y > 5)", context=ctx) is True
