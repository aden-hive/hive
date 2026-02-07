"""Tests for safe_eval — the sandboxed expression evaluator used by edge conditions.

Covers: literals, data structures, arithmetic, comparisons, boolean logic
(including short-circuit semantics), variable lookup, subscript/attribute
access, whitelisted function calls, method calls, ternary expressions,
chained comparisons, and security boundaries (private attrs, disallowed
AST nodes, disallowed function calls).
"""

import pytest

from framework.graph.safe_eval import safe_eval


# ---------------------------------------------------------------------------
# Literals and constants
# ---------------------------------------------------------------------------


class TestLiterals:
    def test_integer(self):
        assert safe_eval("42") == 42

    def test_negative_integer(self):
        assert safe_eval("-1") == -1

    def test_float(self):
        assert safe_eval("3.14") == pytest.approx(3.14)

    def test_string(self):
        assert safe_eval("'hello'") == "hello"

    def test_double_quoted_string(self):
        assert safe_eval('"world"') == "world"

    def test_boolean_true(self):
        assert safe_eval("True") is True

    def test_boolean_false(self):
        assert safe_eval("False") is False

    def test_none(self):
        assert safe_eval("None") is None


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class TestDataStructures:
    def test_list(self):
        assert safe_eval("[1, 2, 3]") == [1, 2, 3]

    def test_empty_list(self):
        assert safe_eval("[]") == []

    def test_nested_list(self):
        assert safe_eval("[[1, 2], [3, 4]]") == [[1, 2], [3, 4]]

    def test_tuple(self):
        assert safe_eval("(1, 2, 3)") == (1, 2, 3)

    def test_dict(self):
        assert safe_eval("{'a': 1, 'b': 2}") == {"a": 1, "b": 2}

    def test_empty_dict(self):
        assert safe_eval("{}") == {}


# ---------------------------------------------------------------------------
# Arithmetic and binary operators
# ---------------------------------------------------------------------------


class TestArithmetic:
    def test_addition(self):
        assert safe_eval("2 + 3") == 5

    def test_subtraction(self):
        assert safe_eval("10 - 4") == 6

    def test_multiplication(self):
        assert safe_eval("3 * 7") == 21

    def test_division(self):
        assert safe_eval("10 / 4") == 2.5

    def test_floor_division(self):
        assert safe_eval("10 // 3") == 3

    def test_modulo(self):
        assert safe_eval("10 % 3") == 1

    def test_power(self):
        assert safe_eval("2 ** 10") == 1024

    def test_complex_expression(self):
        assert safe_eval("(2 + 3) * 4 - 1") == 19


# ---------------------------------------------------------------------------
# Unary operators
# ---------------------------------------------------------------------------


class TestUnaryOps:
    def test_negation(self):
        assert safe_eval("-5") == -5

    def test_positive(self):
        assert safe_eval("+5") == 5

    def test_not_true(self):
        assert safe_eval("not True") is False

    def test_not_false(self):
        assert safe_eval("not False") is True

    def test_bitwise_invert(self):
        assert safe_eval("~0") == -1


# ---------------------------------------------------------------------------
# Comparisons
# ---------------------------------------------------------------------------


class TestComparisons:
    def test_equal(self):
        assert safe_eval("1 == 1") is True

    def test_not_equal(self):
        assert safe_eval("1 != 2") is True

    def test_less_than(self):
        assert safe_eval("1 < 2") is True

    def test_greater_than(self):
        assert safe_eval("2 > 1") is True

    def test_less_equal(self):
        assert safe_eval("2 <= 2") is True

    def test_greater_equal(self):
        assert safe_eval("3 >= 2") is True

    def test_is_none(self):
        assert safe_eval("x is None", {"x": None}) is True

    def test_is_not_none(self):
        assert safe_eval("x is not None", {"x": 42}) is True

    def test_in_list(self):
        assert safe_eval("'a' in x", {"x": ["a", "b", "c"]}) is True

    def test_not_in_list(self):
        assert safe_eval("'z' not in x", {"x": ["a", "b"]}) is True

    def test_chained_comparison(self):
        """Chained comparisons like 1 < x < 10 should work."""
        assert safe_eval("1 < x < 10", {"x": 5}) is True

    def test_chained_comparison_false(self):
        assert safe_eval("1 < x < 3", {"x": 5}) is False

    def test_chained_three_way(self):
        assert safe_eval("0 <= x <= 100", {"x": 50}) is True


# ---------------------------------------------------------------------------
# Boolean operators (with short-circuit semantics)
# ---------------------------------------------------------------------------


class TestBooleanOps:
    def test_and_true(self):
        assert safe_eval("True and True") is True

    def test_and_false(self):
        assert safe_eval("True and False") is False

    def test_or_true(self):
        assert safe_eval("False or True") is True

    def test_or_false(self):
        assert safe_eval("False or False") is False

    def test_and_returns_last_truthy(self):
        """Python `and` returns the last value if all truthy."""
        assert safe_eval("1 and 2 and 3") == 3

    def test_and_returns_first_falsy(self):
        """Python `and` returns the first falsy value."""
        assert safe_eval("1 and 0 and 3") == 0

    def test_or_returns_first_truthy(self):
        """Python `or` returns the first truthy value."""
        assert safe_eval("0 or '' or 42") == 42

    def test_or_returns_last_falsy(self):
        """Python `or` returns the last value if all falsy."""
        assert safe_eval("0 or '' or None") is None

    def test_and_short_circuits(self):
        """and should NOT evaluate the right side if left is falsy.

        This is the bug we fixed — previously this would crash with
        TypeError because all operands were eagerly evaluated.
        """
        # x is None, so `x.get("key")` would crash if evaluated
        assert safe_eval("x is not None and x.get('key')", {"x": None}) is False

    def test_or_short_circuits(self):
        """or should NOT evaluate the right side if left is truthy."""
        # x is truthy, so the crash-prone right side should never run
        assert safe_eval("x or y.get('missing')", {"x": "found", "y": {}}) == "found"

    def test_and_guard_pattern_truthy(self):
        """Guard pattern: check not None, then access — when value exists."""
        ctx = {"x": {"key": "value"}}
        assert safe_eval("x is not None and x.get('key')", ctx) == "value"

    def test_multi_and(self):
        assert safe_eval("True and True and True") is True

    def test_multi_or(self):
        assert safe_eval("False or False or True") is True

    def test_mixed_and_or(self):
        assert safe_eval("True or False and False") is True


# ---------------------------------------------------------------------------
# Ternary (if/else) expressions
# ---------------------------------------------------------------------------


class TestTernary:
    def test_ternary_true_branch(self):
        assert safe_eval("'yes' if True else 'no'") == "yes"

    def test_ternary_false_branch(self):
        assert safe_eval("'yes' if False else 'no'") == "no"

    def test_ternary_with_context(self):
        assert safe_eval("x * 2 if x > 0 else -x", {"x": 5}) == 10

    def test_ternary_false_with_context(self):
        assert safe_eval("x * 2 if x > 0 else -x", {"x": -3}) == 3


# ---------------------------------------------------------------------------
# Variable lookup
# ---------------------------------------------------------------------------


class TestVariables:
    def test_simple_variable(self):
        assert safe_eval("x", {"x": 42}) == 42

    def test_string_variable(self):
        assert safe_eval("name", {"name": "Alice"}) == "Alice"

    def test_dict_variable(self):
        ctx = {"output": {"status": "ok"}}
        assert safe_eval("output", ctx) == {"status": "ok"}

    def test_undefined_variable_raises(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("undefined_var")

    def test_multiple_variables(self):
        assert safe_eval("x + y", {"x": 10, "y": 20}) == 30


# ---------------------------------------------------------------------------
# Subscript access (indexing)
# ---------------------------------------------------------------------------


class TestSubscript:
    def test_dict_subscript(self):
        assert safe_eval("d['key']", {"d": {"key": "value"}}) == "value"

    def test_list_subscript(self):
        assert safe_eval("items[0]", {"items": [10, 20, 30]}) == 10

    def test_nested_subscript(self):
        ctx = {"data": {"users": [{"name": "Alice"}]}}
        assert safe_eval("data['users'][0]['name']", ctx) == "Alice"

    def test_missing_key_raises(self):
        with pytest.raises(KeyError):
            safe_eval("d['missing']", {"d": {}})


# ---------------------------------------------------------------------------
# Attribute access
# ---------------------------------------------------------------------------


class TestAttributeAccess:
    def test_private_attr_blocked(self):
        """Attributes starting with _ must be blocked for security."""
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("x.__class__", {"x": 42})

    def test_dunder_blocked(self):
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("x.__dict__", {"x": {}})

    def test_single_underscore_blocked(self):
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("x._internal", {"x": {}})


# ---------------------------------------------------------------------------
# Whitelisted function calls
# ---------------------------------------------------------------------------


class TestFunctionCalls:
    def test_len(self):
        assert safe_eval("len(x)", {"x": [1, 2, 3]}) == 3

    def test_int_conversion(self):
        assert safe_eval("int('42')") == 42

    def test_float_conversion(self):
        assert safe_eval("float('3.14')") == pytest.approx(3.14)

    def test_str_conversion(self):
        assert safe_eval("str(42)") == "42"

    def test_bool_conversion(self):
        assert safe_eval("bool(1)") is True

    def test_abs(self):
        assert safe_eval("abs(-5)") == 5

    def test_min(self):
        assert safe_eval("min(3, 1, 2)") == 1

    def test_max(self):
        assert safe_eval("max(3, 1, 2)") == 3

    def test_sum(self):
        assert safe_eval("sum(x)", {"x": [1, 2, 3]}) == 6

    def test_round(self):
        assert safe_eval("round(3.7)") == 4

    def test_all(self):
        assert safe_eval("all([True, True, True])") is True

    def test_any(self):
        assert safe_eval("any([False, False, True])") is True

    def test_list_constructor(self):
        assert safe_eval("list(x)", {"x": (1, 2, 3)}) == [1, 2, 3]

    def test_dict_constructor(self):
        assert safe_eval("dict(a=1, b=2)") == {"a": 1, "b": 2}

    def test_tuple_constructor(self):
        assert safe_eval("tuple(x)", {"x": [1, 2]}) == (1, 2)

    def test_set_constructor(self):
        assert safe_eval("set(x)", {"x": [1, 2, 2, 3]}) == {1, 2, 3}


# ---------------------------------------------------------------------------
# Whitelisted method calls
# ---------------------------------------------------------------------------


class TestMethodCalls:
    def test_dict_get(self):
        assert safe_eval("d.get('key', 'default')", {"d": {"key": "val"}}) == "val"

    def test_dict_get_missing(self):
        assert safe_eval("d.get('missing', 'default')", {"d": {}}) == "default"

    def test_dict_keys(self):
        result = safe_eval("list(d.keys())", {"d": {"a": 1, "b": 2}})
        assert sorted(result) == ["a", "b"]

    def test_dict_values(self):
        result = safe_eval("list(d.values())", {"d": {"a": 1, "b": 2}})
        assert sorted(result) == [1, 2]

    def test_string_lower(self):
        assert safe_eval("s.lower()", {"s": "HELLO"}) == "hello"

    def test_string_upper(self):
        assert safe_eval("s.upper()", {"s": "hello"}) == "HELLO"

    def test_string_strip(self):
        assert safe_eval("s.strip()", {"s": "  hi  "}) == "hi"

    def test_string_split(self):
        assert safe_eval("s.split(',')", {"s": "a,b,c"}) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Security: disallowed operations
# ---------------------------------------------------------------------------


class TestSecurity:
    def test_import_blocked(self):
        """__import__ is not in context, so NameError is raised."""
        with pytest.raises(NameError, match="not defined"):
            safe_eval("__import__('os')")

    def test_lambda_blocked(self):
        with pytest.raises(ValueError, match="not allowed"):
            safe_eval("(lambda: 1)()")

    def test_comprehension_blocked(self):
        with pytest.raises(ValueError, match="not allowed"):
            safe_eval("[x for x in range(10)]")

    def test_assignment_blocked(self):
        """Assignment expressions should not parse in eval mode."""
        with pytest.raises(SyntaxError):
            safe_eval("x = 5")

    def test_disallowed_function_blocked(self):
        """eval is not in safe functions, so NameError is raised."""
        with pytest.raises(NameError, match="not defined"):
            safe_eval("eval('1+1')")

    def test_exec_blocked(self):
        """exec is not in safe functions, so NameError is raised."""
        with pytest.raises(NameError, match="not defined"):
            safe_eval("exec('x=1')")

    def test_type_call_blocked(self):
        """type is not in safe functions, so NameError is raised."""
        with pytest.raises(NameError, match="not defined"):
            safe_eval("type(42)")

    def test_getattr_builtin_blocked(self):
        """getattr is not in safe functions, so NameError is raised."""
        with pytest.raises(NameError, match="not defined"):
            safe_eval("getattr(x, '__class__')", {"x": 42})

    def test_empty_expression_raises(self):
        with pytest.raises(SyntaxError):
            safe_eval("")


# ---------------------------------------------------------------------------
# Real-world edge condition patterns (from graph executor usage)
# ---------------------------------------------------------------------------


class TestEdgeConditionPatterns:
    """Patterns commonly used in EdgeSpec.condition_expr."""

    def test_output_key_exists_and_not_none(self):
        ctx = {"output": {"approved_contacts": ["alice@example.com"]}}
        assert safe_eval("output.get('approved_contacts') is not None", ctx) is True

    def test_output_key_missing(self):
        ctx = {"output": {}}
        assert safe_eval("output.get('approved_contacts') is not None", ctx) is False

    def test_output_key_check_with_fallback(self):
        ctx = {"output": {"redo_extraction": True}}
        assert safe_eval("output.get('redo_extraction') is not None", ctx) is True

    def test_guard_then_length_check(self):
        """Guard pattern: check key exists, then check length."""
        ctx = {"output": {"results": [1, 2, 3]}}
        assert (
            safe_eval(
                "output.get('results') is not None and len(output['results']) > 0",
                ctx,
            )
            is True
        )

    def test_guard_short_circuits_on_none(self):
        """Guard pattern: short-circuit prevents crash on None."""
        ctx = {"output": {}}
        assert (
            safe_eval(
                "output.get('results') is not None and len(output['results']) > 0",
                ctx,
            )
            is False
        )

    def test_success_flag_check(self):
        ctx = {"output": {"success": True}, "memory": {"attempts": 2}}
        assert safe_eval("output.get('success') == True", ctx) is True

    def test_memory_threshold(self):
        ctx = {"memory": {"score": 0.85}}
        assert safe_eval("memory.get('score', 0) >= 0.8", ctx) is True

    def test_string_contains_check(self):
        ctx = {"output": {"status": "completed_with_warnings"}}
        assert safe_eval("'completed' in output.get('status', '')", ctx) is True

    def test_fallback_chain(self):
        """or-chain for fallback values."""
        ctx = {"output": {}}
        result = safe_eval(
            "output.get('primary') or output.get('secondary') or 'default'",
            ctx,
        )
        assert result == "default"

    def test_no_context_needed(self):
        """Some edges use constant expressions."""
        assert safe_eval("True") is True
        assert safe_eval("1 == 1") is True
