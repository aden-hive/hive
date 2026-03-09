"""Tests for the safe_eval expression evaluator.

Covers resource exhaustion protections (DoS via exponentiation and
string/list multiplication) and correct short-circuit semantics for
boolean operators.
"""

import pytest

from framework.graph.safe_eval import safe_eval


# ---------------------------------------------------------------------------
# Basic functionality (sanity checks)
# ---------------------------------------------------------------------------

class TestBasicEval:
    def test_arithmetic(self):
        assert safe_eval("2 + 3") == 5
        assert safe_eval("10 - 4") == 6
        assert safe_eval("5 * 10") == 50
        assert safe_eval("9 / 3") == 3.0

    def test_comparison(self):
        assert safe_eval("1 < 2") is True
        assert safe_eval("2 >= 2") is True
        assert safe_eval("3 == 4") is False

    def test_variable_lookup(self):
        assert safe_eval("x + 1", {"x": 10}) == 11
        assert safe_eval("name", {"name": "alice"}) == "alice"

    def test_function_calls(self):
        assert safe_eval("len(x)", {"x": [1, 2, 3]}) == 3
        assert safe_eval("abs(-5)") == 5
        assert safe_eval("int(3.7)") == 3

    def test_ternary(self):
        assert safe_eval("'yes' if x else 'no'", {"x": True}) == "yes"
        assert safe_eval("'yes' if x else 'no'", {"x": False}) == "no"

    def test_moderate_exponentiation(self):
        assert safe_eval("2 ** 10") == 1024
        assert safe_eval("3 ** 3") == 27
        assert safe_eval("10 ** 0") == 1

    def test_small_string_repeat(self):
        assert safe_eval('"ha" * 3') == "hahaha"
        assert safe_eval('"x" * 0') == ""

    def test_small_list_repeat(self):
        assert safe_eval("[0] * 5") == [0, 0, 0, 0, 0]


# ---------------------------------------------------------------------------
# DoS protection: exponentiation bounds
# ---------------------------------------------------------------------------

class TestExponentiationBounds:
    def test_huge_exponent_blocked(self):
        """9 ** 9 ** 9 = 9^387420489, must not hang the process."""
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_eval("9 ** 9 ** 9")

    def test_large_exponent_blocked(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_eval("2 ** 1000")

    def test_negative_huge_exponent_blocked(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_eval("2 ** -1000")

    def test_boundary_exponent_allowed(self):
        """Exponent exactly at the limit should still work."""
        result = safe_eval("2 ** 100")
        assert result == 2**100

    def test_float_exponent_blocked(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_eval("1.5 ** 200.0")


# ---------------------------------------------------------------------------
# DoS protection: string/list multiplication bounds
# ---------------------------------------------------------------------------

class TestRepetitionBounds:
    def test_huge_string_repeat_blocked(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_eval('"a" * 100000000')

    def test_huge_list_repeat_blocked(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_eval("[1] * 100000000")

    def test_huge_tuple_repeat_blocked(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_eval("(1,) * 100000000")

    def test_reverse_operand_order_blocked(self):
        """100000000 * 'a' should also be caught."""
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_eval('100000000 * "a"')

    def test_numeric_multiplication_unaffected(self):
        """Normal number * number should never be blocked."""
        assert safe_eval("100000000 * 2") == 200000000
        assert safe_eval("999999 * 999999") == 999998000001


# ---------------------------------------------------------------------------
# BoolOp short-circuit semantics
# ---------------------------------------------------------------------------

class TestBoolOpShortCircuit:
    def test_and_short_circuits_on_falsy(self):
        """None and len(None) should return None, not raise TypeError."""
        result = safe_eval("x and len(x) > 0", {"x": None})
        assert result is None

    def test_and_short_circuits_on_zero(self):
        result = safe_eval("x and 1 / x", {"x": 0})
        assert result == 0

    def test_and_evaluates_all_if_truthy(self):
        result = safe_eval("x and len(x) > 0", {"x": [1, 2, 3]})
        assert result is True

    def test_and_returns_last_truthy(self):
        """Python `and` returns the last value if all truthy."""
        result = safe_eval("1 and 2 and 3")
        assert result == 3

    def test_and_returns_first_falsy(self):
        result = safe_eval("1 and 0 and 3")
        assert result == 0

    def test_or_short_circuits_on_truthy(self):
        result = safe_eval("x or 1 / 0", {"x": "hello"})
        assert result == "hello"

    def test_or_evaluates_all_if_falsy(self):
        result = safe_eval('x or "default"', {"x": ""})
        assert result == "default"

    def test_or_returns_first_truthy(self):
        result = safe_eval("0 or '' or 42 or 99")
        assert result == 42

    def test_or_returns_last_falsy(self):
        """If all falsy, Python `or` returns the last value."""
        result = safe_eval("0 or '' or None")
        assert result is None

    def test_nested_bool_ops(self):
        result = safe_eval(
            "(x or 'fallback') and len(x or 'fallback') > 0",
            {"x": None},
        )
        assert result is True

    def test_and_with_empty_list(self):
        result = safe_eval("x and x[0]", {"x": []})
        assert result == []


# ---------------------------------------------------------------------------
# Recursion depth limit
# ---------------------------------------------------------------------------

class TestRecursionDepthLimit:
    def test_deeply_nested_expression_blocked(self):
        """Nesting beyond MAX_DEPTH should raise ValueError, not RecursionError."""
        # Build an expression with 60 levels of nesting: not not not ... True
        expr = "not " * 60 + "True"
        with pytest.raises(ValueError, match="nesting depth exceeds"):
            safe_eval(expr)

    def test_moderate_nesting_allowed(self):
        # 10 levels of nesting should be fine
        expr = "not " * 10 + "True"
        result = safe_eval(expr)
        assert result is True  # even number of nots → True? No, 10 nots on True = True
        # Actually: not not not ... True with 10 `not`s = True (even count)
        assert result is True

    def test_nested_subscripts_allowed(self):
        ctx = {"x": {"a": {"b": {"c": 42}}}}
        assert safe_eval('x["a"]["b"]["c"]', ctx) == 42


# ---------------------------------------------------------------------------
# Method type checking
# ---------------------------------------------------------------------------

class TestMethodTypeChecking:
    def test_dict_get_allowed(self):
        assert safe_eval('x.get("key", "default")', {"x": {"key": "val"}}) == "val"
        assert safe_eval('x.get("missing", "default")', {"x": {}}) == "default"

    def test_str_lower_allowed(self):
        assert safe_eval('x.lower()', {"x": "HELLO"}) == "hello"

    def test_str_split_allowed(self):
        assert safe_eval('x.split(",")', {"x": "a,b,c"}) == ["a", "b", "c"]

    def test_dict_keys_allowed(self):
        result = safe_eval('list(x.keys())', {"x": {"a": 1, "b": 2}})
        assert sorted(result) == ["a", "b"]

    def test_get_on_non_dict_blocked(self):
        """Calling .get() on a non-dict type should not be auto-approved."""

        class FakeObj:
            def get(self):
                return "escaped!"

        with pytest.raises(ValueError, match="not allowed"):
            safe_eval("x.get()", {"x": FakeObj()})

    def test_lower_on_non_str_blocked(self):
        """Calling .lower() on a non-str should not be auto-approved."""

        class FakeObj:
            def lower(self):
                return "escaped!"

        with pytest.raises(ValueError, match="not allowed"):
            safe_eval("x.lower()", {"x": FakeObj()})


# ---------------------------------------------------------------------------
# Security (these should still be blocked)
# ---------------------------------------------------------------------------

class TestSecurityBlocking:
    def test_import_blocked(self):
        with pytest.raises(NameError):
            safe_eval('__import__("os")')

    def test_eval_blocked(self):
        with pytest.raises(NameError):
            safe_eval('eval("1+1")')

    def test_private_attribute_blocked(self):
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("x.__class__", {"x": 1})

    def test_subclass_escape_blocked(self):
        with pytest.raises(ValueError):
            safe_eval("().__class__.__bases__[0].__subclasses__()")
