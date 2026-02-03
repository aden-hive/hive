"""
Tests for safe_eval module.
Ensures expressions are evaluated safely and dangerous operations are blocked.
"""
import pytest
from framework.graph.safe_eval import safe_eval


class TestBasicOperations:
    """Test basic arithmetic and comparison operations."""

    def test_addition(self):
        assert safe_eval("1 + 2") == 3

    def test_subtraction(self):
        assert safe_eval("5 - 3") == 2

    def test_multiplication(self):
        assert safe_eval("4 * 3") == 12

    def test_division(self):
        assert safe_eval("10 / 2") == 5.0

    def test_floor_division(self):
        assert safe_eval("7 // 2") == 3

    def test_modulo(self):
        assert safe_eval("10 % 3") == 1

    def test_power(self):
        assert safe_eval("2 ** 3") == 8

    def test_comparison_equal(self):
        assert safe_eval("1 == 1") is True

    def test_comparison_not_equal(self):
        assert safe_eval("1 != 2") is True

    def test_comparison_less_than(self):
        assert safe_eval("1 < 2") is True

    def test_comparison_greater_than(self):
        assert safe_eval("2 > 1") is True

    def test_comparison_chain(self):
        assert safe_eval("1 < 2 < 3") is True

    def test_boolean_and(self):
        assert safe_eval("True and True") is True
        assert safe_eval("True and False") is False

    def test_boolean_or(self):
        assert safe_eval("True or False") is True
        assert safe_eval("False or False") is False

    def test_boolean_not(self):
        assert safe_eval("not False") is True

    def test_ternary_expression(self):
        assert safe_eval("1 if True else 2") == 1
        assert safe_eval("1 if False else 2") == 2


class TestSafeFunctions:
    """Test whitelisted safe functions."""

    def test_len(self):
        assert safe_eval("len([1, 2, 3])") == 3

    def test_int(self):
        assert safe_eval("int('42')") == 42

    def test_float(self):
        assert safe_eval("float('3.14')") == 3.14

    def test_str(self):
        assert safe_eval("str(123)") == "123"

    def test_bool(self):
        assert safe_eval("bool(1)") is True
        assert safe_eval("bool(0)") is False

    def test_min(self):
        assert safe_eval("min(3, 1, 2)") == 1

    def test_max(self):
        assert safe_eval("max(1, 3, 2)") == 3

    def test_sum(self):
        assert safe_eval("sum([1, 2, 3])") == 6

    def test_abs(self):
        assert safe_eval("abs(-5)") == 5

    def test_round(self):
        assert safe_eval("round(3.7)") == 4

    def test_all(self):
        assert safe_eval("all([True, True])") is True
        assert safe_eval("all([True, False])") is False

    def test_any(self):
        assert safe_eval("any([False, True])") is True
        assert safe_eval("any([False, False])") is False


class TestContextVariables:
    """Test that context variables are accessible."""

    def test_simple_variable(self):
        assert safe_eval("x", {"x": 10}) == 10

    def test_variable_in_expression(self):
        assert safe_eval("x + y", {"x": 3, "y": 4}) == 7

    def test_variable_comparison(self):
        assert safe_eval("x > 5", {"x": 10}) is True

    def test_dict_access_bracket(self):
        assert safe_eval("data['key']", {"data": {"key": "value"}}) == "value"

    def test_dict_get_method(self):
        assert safe_eval("data.get('key')", {"data": {"key": "value"}}) == "value"

    def test_dict_get_with_default(self):
        assert safe_eval("data.get('missing', 'default')", {"data": {}}) == "default"

    def test_list_access(self):
        assert safe_eval("items[0]", {"items": [1, 2, 3]}) == 1

    def test_nested_access(self):
        assert safe_eval("data['nested']['key']", {"data": {"nested": {"key": 42}}}) == 42


class TestSafeMethodCalls:
    """Test whitelisted safe method calls."""

    def test_string_lower(self):
        assert safe_eval("s.lower()", {"s": "HELLO"}) == "hello"

    def test_string_upper(self):
        assert safe_eval("s.upper()", {"s": "hello"}) == "HELLO"

    def test_string_strip(self):
        assert safe_eval("s.strip()", {"s": "  hello  "}) == "hello"

    def test_string_split(self):
        assert safe_eval("s.split(',')", {"s": "a,b,c"}) == ["a", "b", "c"]

    def test_dict_keys(self):
        result = safe_eval("list(d.keys())", {"d": {"a": 1, "b": 2}})
        assert sorted(result) == ["a", "b"]

    def test_dict_values(self):
        result = safe_eval("list(d.values())", {"d": {"a": 1, "b": 2}})
        assert sorted(result) == [1, 2]


class TestDataStructures:
    """Test list, dict, tuple creation."""

    def test_list_literal(self):
        assert safe_eval("[1, 2, 3]") == [1, 2, 3]

    def test_dict_literal(self):
        assert safe_eval("{'a': 1, 'b': 2}") == {"a": 1, "b": 2}

    def test_tuple_literal(self):
        assert safe_eval("(1, 2, 3)") == (1, 2, 3)

    def test_nested_structure(self):
        assert safe_eval("[{'key': [1, 2]}]") == [{"key": [1, 2]}]


class TestBlockedOperations:
    """Test that dangerous operations are blocked."""

    def test_private_attribute_blocked(self):
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("obj._private", {"obj": object()})

    def test_dunder_attribute_blocked(self):
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("obj.__class__", {"obj": object()})

    def test_undefined_variable_raises(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("undefined_var")

    def test_unsafe_function_blocked(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("eval('1+1')")

    def test_import_blocked(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("__import__('os')")

    def test_exec_blocked(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("exec('x=1')")


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_context(self):
        assert safe_eval("1 + 1", None) == 2

    def test_syntax_error(self):
        with pytest.raises(SyntaxError):
            safe_eval("1 +")

    def test_division_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            safe_eval("1 / 0")

    def test_in_operator(self):
        assert safe_eval("'a' in ['a', 'b']") is True

    def test_not_in_operator(self):
        assert safe_eval("'c' not in ['a', 'b']") is True

    def test_is_operator(self):
        assert safe_eval("None is None") is True

    def test_is_not_operator(self):
        assert safe_eval("1 is not None") is True

    def test_unary_negative(self):
        assert safe_eval("-5") == -5

    def test_unary_positive(self):
        assert safe_eval("+5") == 5

    def test_bitwise_or(self):
        assert safe_eval("1 | 2") == 3

    def test_bitwise_and(self):
        assert safe_eval("3 & 1") == 1

    def test_bitwise_xor(self):
        assert safe_eval("3 ^ 1") == 2
