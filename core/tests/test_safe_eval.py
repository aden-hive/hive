"""Comprehensive tests for safe_eval security hardening (issue #5109).

Tests cover:
  1. Pow exponent cap (DoS prevention)
  2. BoolOp short-circuit semantics
  3. Type-safe method whitelist
  4. Recursion depth limit
  5. Baseline regression tests
"""

import os
import sys

# Ensure framework package is importable without full install
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from framework.graph.safe_eval import safe_eval

# =========================================================================
# 1. Pow exponent cap (issue #5109 vuln 1)
# =========================================================================


class TestPowExponentCap:
    """Verify that large exponents are rejected to prevent CPU DoS."""

    def test_small_exponent_allowed(self):
        assert safe_eval("2 ** 10") == 1024

    def test_exponent_at_limit(self):
        result = safe_eval("2 ** 1000")
        assert result == 2**1000

    def test_exponent_over_limit_rejected(self):
        with pytest.raises(ValueError, match="exceeds safe limit"):
            safe_eval("2 ** 1001")

    def test_negative_large_exponent_rejected(self):
        with pytest.raises(ValueError, match="exceeds safe limit"):
            safe_eval("2 ** (-1001)")

    def test_float_exponent_over_limit_rejected(self):
        with pytest.raises(ValueError, match="exceeds safe limit"):
            safe_eval("2 ** 1500.0")

    def test_chained_pow_with_safe_values(self):
        # 2 ** (3 ** 2) = 2 ** 9 = 512
        assert safe_eval("2 ** 3 ** 2") == 512

    def test_zero_exponent(self):
        assert safe_eval("999 ** 0") == 1

    def test_exponent_one(self):
        assert safe_eval("42 ** 1") == 42


# =========================================================================
# 2. BoolOp short-circuit semantics (issue #5109 vuln 2)
# =========================================================================


class TestBoolOpShortCircuit:
    """Verify that and/or short-circuit like standard Python."""

    def test_and_short_circuits_on_false(self):
        """False and <undefined> should NOT evaluate the second operand."""
        ctx = {"x": False}
        result = safe_eval("x and x.missing_method()", ctx)
        assert result is False

    def test_and_evaluates_when_true(self):
        ctx = {"x": True, "y": 42}
        assert safe_eval("x and y", ctx) == 42

    def test_or_short_circuits_on_true(self):
        """True or <undefined> should NOT evaluate the second operand."""
        ctx = {"x": True}
        result = safe_eval("x or x.missing_method()", ctx)
        assert result is True

    def test_or_evaluates_when_false(self):
        ctx = {"x": False, "y": "hello"}
        assert safe_eval("x or y", ctx) == "hello"

    def test_and_returns_falsy_value(self):
        ctx = {"x": 0, "y": 5}
        assert safe_eval("x and y", ctx) == 0

    def test_or_returns_truthy_value(self):
        ctx = {"x": 0, "y": 5}
        assert safe_eval("x or y", ctx) == 5

    def test_guard_pattern_none_check(self):
        """output.get('data') is not None and len(...) > 0 — short-circuits on None."""
        ctx = {"output": {"data": None}}
        result = safe_eval(
            "output.get('data') is not None and len(output.get('data')) > 0",
            ctx,
        )
        assert not result

    def test_guard_pattern_with_valid_data(self):
        ctx = {"output": {"data": [1, 2, 3]}}
        result = safe_eval(
            "output.get('data') is not None and len(output.get('data')) > 0",
            ctx,
        )
        assert result is True

    def test_chained_and(self):
        ctx = {"a": True, "b": True, "c": 99}
        assert safe_eval("a and b and c", ctx) == 99

    def test_chained_or(self):
        ctx = {"a": False, "b": False, "c": 99}
        assert safe_eval("a or b or c", ctx) == 99


# =========================================================================
# 3. Type-safe method whitelist (issue #5109 vuln 3)
# =========================================================================


class TestMethodTypeEnforcement:
    """Verify that whitelisted methods are only allowed on correct types."""

    def test_dict_get_allowed(self):
        ctx = {"d": {"key": "value"}}
        assert safe_eval("d.get('key')", ctx) == "value"

    def test_dict_get_default(self):
        ctx = {"d": {"key": "value"}}
        assert safe_eval("d.get('missing', 'default')", ctx) == "default"

    def test_dict_keys_allowed(self):
        ctx = {"d": {"a": 1, "b": 2}}
        assert safe_eval("list(d.keys())", ctx) == ["a", "b"]

    def test_dict_values_allowed(self):
        ctx = {"d": {"a": 1, "b": 2}}
        assert safe_eval("list(d.values())", ctx) == [1, 2]

    def test_dict_items_allowed(self):
        ctx = {"d": {"a": 1}}
        assert safe_eval("list(d.items())", ctx) == [("a", 1)]

    def test_str_lower_allowed(self):
        ctx = {"s": "HELLO"}
        assert safe_eval("s.lower()", ctx) == "hello"

    def test_str_upper_allowed(self):
        ctx = {"s": "hello"}
        assert safe_eval("s.upper()", ctx) == "HELLO"

    def test_str_strip_allowed(self):
        ctx = {"s": "  hello  "}
        assert safe_eval("s.strip()", ctx) == "hello"

    def test_str_split_allowed(self):
        ctx = {"s": "a,b,c"}
        assert safe_eval("s.split(',')", ctx) == ["a", "b", "c"]

    def test_get_on_non_dict_rejected(self):
        """A non-dict object with a .get() method must be blocked."""

        class FakeDict:
            def get(self, key):
                return "pwned"

        ctx = {"obj": FakeDict()}
        with pytest.raises(ValueError, match="not allowed on type"):
            safe_eval("obj.get('key')", ctx)

    def test_split_on_non_str_rejected(self):
        """A non-str object with a .split() method must be blocked."""

        class FakeStr:
            def split(self):
                return "pwned"

        ctx = {"obj": FakeStr()}
        with pytest.raises(ValueError, match="not allowed on type"):
            safe_eval("obj.split()", ctx)

    def test_lower_on_non_str_rejected(self):
        class NotAStr:
            def lower(self):
                return "pwned"

        ctx = {"obj": NotAStr()}
        with pytest.raises(ValueError, match="not allowed on type"):
            safe_eval("obj.lower()", ctx)


# =========================================================================
# 4. Recursion depth limit (issue #5109 vuln 4)
# =========================================================================


class TestRecursionDepthLimit:
    """Verify that deeply nested expressions are rejected."""

    def test_shallow_nesting_ok(self):
        # 10 levels of unary + is fine
        expr = "+" * 10 + "42"
        assert safe_eval(expr) == 42

    def test_deep_unary_nesting_rejected(self):
        # 60 levels of unary + exceeds MAX_DEPTH=50
        expr = "+" * 60 + "42"
        with pytest.raises(ValueError, match="nesting depth exceeds limit"):
            safe_eval(expr)

    def test_deep_not_nesting_rejected(self):
        # not not not ... True — 60 levels exceeds MAX_DEPTH=50
        expr = "not " * 60 + "True"
        with pytest.raises(ValueError, match="nesting depth exceeds limit"):
            safe_eval(expr)

    def test_moderate_nesting_ok(self):
        # 20 levels should be fine
        expr = "+" * 20 + "1"
        assert safe_eval(expr) == 1


# =========================================================================
# 5. Baseline regression tests
# =========================================================================


class TestBaselineRegression:
    """Basic functionality that must continue to work after hardening."""

    def test_arithmetic(self):
        assert safe_eval("1 + 2 * 3") == 7

    def test_comparison(self):
        assert safe_eval("10 > 5") is True
        assert safe_eval("10 < 5") is False

    def test_string_operations(self):
        assert safe_eval("'hello' + ' ' + 'world'") == "hello world"

    def test_len(self):
        assert safe_eval("len([1, 2, 3])") == 3

    def test_list_literal(self):
        assert safe_eval("[1, 2, 3]") == [1, 2, 3]

    def test_dict_literal(self):
        assert safe_eval("{'a': 1}") == {"a": 1}

    def test_ternary(self):
        assert safe_eval("'yes' if True else 'no'") == "yes"
        assert safe_eval("'yes' if False else 'no'") == "no"

    def test_context_variable(self):
        assert safe_eval("x + y", {"x": 10, "y": 20}) == 30

    def test_bool_and(self):
        assert safe_eval("True and True") is True
        assert safe_eval("True and False") is False

    def test_bool_or(self):
        assert safe_eval("False or True") is True
        assert safe_eval("False or False") is False

    def test_not(self):
        assert safe_eval("not True") is False
        assert safe_eval("not False") is True

    def test_in_operator(self):
        ctx = {"items": [1, 2, 3]}
        assert safe_eval("2 in items", ctx) is True
        assert safe_eval("5 in items", ctx) is False

    def test_subscript(self):
        ctx = {"data": {"key": "value"}}
        assert safe_eval("data['key']", ctx) == "value"

    def test_chained_comparison(self):
        assert safe_eval("1 < 2 < 3") is True
        assert safe_eval("1 < 2 > 3") is False

    def test_undefined_name_raises(self):
        with pytest.raises(NameError):
            safe_eval("undefined_var")

    def test_unsafe_node_raises(self):
        with pytest.raises(SyntaxError):
            safe_eval("import os")

    def test_private_attribute_rejected(self):
        ctx = {"obj": "hello"}
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("obj.__class__", ctx)

    def test_safe_builtin_functions(self):
        assert safe_eval("abs(-5)") == 5
        assert safe_eval("min(3, 1, 2)") == 1
        assert safe_eval("max(3, 1, 2)") == 3
        assert safe_eval("sum([1, 2, 3])") == 6
        assert safe_eval("round(3.7)") == 4
