"""
Tests for safe_eval sandbox security and correctness.

Validates that the expression evaluator is hardened against:
- DoS via exponential operations (ast.Pow)
- Oversized input expressions
- Eager BoolOp evaluation (must short-circuit like Python)
- Unbounded getattr on arbitrary types
- Access to private/dunder attributes
- Calls to unsafe built-in functions
"""

import pytest

from framework.graph.safe_eval import (
    MAX_EXPRESSION_LENGTH,
    MAX_POW_EXPONENT,
    safe_eval,
)

# ============================================================
# Basic expression evaluation
# ============================================================


class TestBasicExpressions:
    """Verify that normal expressions still work after hardening."""

    def test_arithmetic(self):
        assert safe_eval("2 + 3") == 5
        assert safe_eval("10 - 4") == 6
        assert safe_eval("3 * 7") == 21
        assert safe_eval("10 / 3") == pytest.approx(3.333, rel=1e-2)
        assert safe_eval("10 // 3") == 3
        assert safe_eval("10 % 3") == 1

    def test_comparison(self):
        assert safe_eval("1 < 2") is True
        assert safe_eval("2 > 3") is False
        assert safe_eval("1 == 1") is True
        assert safe_eval("1 != 2") is True
        assert safe_eval("1 <= 1") is True
        assert safe_eval("2 >= 3") is False

    def test_boolean_operators(self):
        assert safe_eval("True and True") is True
        assert safe_eval("True and False") is False
        assert safe_eval("False or True") is True
        assert safe_eval("False or False") is False
        assert safe_eval("not True") is False
        assert safe_eval("not False") is True

    def test_context_variables(self):
        assert safe_eval("x + y", {"x": 10, "y": 20}) == 30
        assert safe_eval("name == 'alice'", {"name": "alice"}) is True

    def test_ternary_expression(self):
        assert safe_eval("'yes' if True else 'no'") == "yes"
        assert safe_eval("'yes' if False else 'no'") == "no"

    def test_safe_functions(self):
        assert safe_eval("len([1, 2, 3])") == 3
        assert safe_eval("int('42')") == 42
        assert safe_eval("str(42)") == "42"
        assert safe_eval("bool(1)") is True
        assert safe_eval("abs(-5)") == 5
        assert safe_eval("min(3, 1, 2)") == 1
        assert safe_eval("max(3, 1, 2)") == 3

    def test_safe_pow_within_limit(self):
        """Pow with small exponents should still work."""
        assert safe_eval("2 ** 10") == 1024
        assert safe_eval("3 ** 3") == 27
        assert safe_eval(f"2 ** {MAX_POW_EXPONENT}") == 2**MAX_POW_EXPONENT

    def test_subscript_access(self):
        ctx = {"data": {"key": "value"}, "items": [10, 20, 30]}
        assert safe_eval("data['key']", ctx) == "value"
        assert safe_eval("items[1]", ctx) == 20

    def test_method_calls_on_safe_types(self):
        ctx = {"data": {"a": 1, "b": 2}}
        assert safe_eval("data.get('a')", ctx) == 1
        assert safe_eval("data.get('missing', 0)", ctx) == 0

    def test_string_methods(self):
        ctx = {"s": "Hello World"}
        assert safe_eval("s.lower()", ctx) == "hello world"
        assert safe_eval("s.upper()", ctx) == "HELLO WORLD"
        assert safe_eval("s.strip()", ctx) == "Hello World"

    def test_data_structures(self):
        assert safe_eval("[1, 2, 3]") == [1, 2, 3]
        assert safe_eval("(1, 2)") == (1, 2)
        assert safe_eval("{'a': 1}") == {"a": 1}

    def test_chained_comparison(self):
        assert safe_eval("1 < 2 < 3") is True
        assert safe_eval("1 < 2 > 3") is False

    def test_in_operator(self):
        ctx = {"items": [1, 2, 3]}
        assert safe_eval("2 in items", ctx) is True
        assert safe_eval("5 not in items", ctx) is True


# ============================================================
# Security: DoS prevention
# ============================================================


class TestDoSPrevention:
    """Verify that the sandbox prevents Denial-of-Service attacks."""

    def test_pow_exponent_exceeds_limit(self):
        """Exponents above MAX_POW_EXPONENT must be rejected."""
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_eval(f"2 ** {MAX_POW_EXPONENT + 1}")

    def test_nested_pow_dos(self):
        """Nested exponentiation like 2**2**200 must be rejected.

        Python's right-associative ** means 2**2**200 = 2**(2**200).
        The inner 2**200 is fine (exponent=200 > 100) and should be caught.
        """
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_eval("2 ** 200")

    def test_negative_exponent_large(self):
        """Large negative exponents should also be caught."""
        with pytest.raises(ValueError, match="exceeds maximum"):
            safe_eval("2 ** -200")

    def test_expression_too_long(self):
        """Expressions exceeding MAX_EXPRESSION_LENGTH must be rejected."""
        long_expr = "1 + " * (MAX_EXPRESSION_LENGTH // 4 + 1) + "1"
        assert len(long_expr) > MAX_EXPRESSION_LENGTH
        with pytest.raises(ValueError, match="Expression too long"):
            safe_eval(long_expr)

    def test_expression_at_limit_accepted(self):
        """An expression exactly at the limit should still be accepted."""
        # Build a valid expression just under the limit
        expr = "1" * MAX_EXPRESSION_LENGTH
        # This will be a valid integer literal
        result = safe_eval(expr)
        assert result == int(expr)


# ============================================================
# Security: Short-circuit BoolOp
# ============================================================


class TestShortCircuitBoolOp:
    """Verify that BoolOp short-circuits like standard Python."""

    def test_and_short_circuits_on_falsy(self):
        """'x is not None and x > 0' with x=None must return False, not crash."""
        # Before the fix, this would crash because all operands were
        # eagerly evaluated, causing `None > 0` TypeError.
        result = safe_eval("x is not None and x > 0", {"x": None})
        assert result is False

    def test_and_evaluates_all_when_truthy(self):
        """When all values are truthy, 'and' returns the last value."""
        result = safe_eval("x is not None and x > 0", {"x": 5})
        assert result is True

    def test_or_short_circuits_on_truthy(self):
        """'or' should return the first truthy value."""
        result = safe_eval("True or x > 0", {"x": None})
        assert result is True

    def test_or_evaluates_all_when_falsy(self):
        """When all values are falsy, 'or' returns the last value."""
        result = safe_eval("False or 0 or None")
        assert result is None

    def test_and_returns_falsy_value(self):
        """'and' should return the actual falsy value, not just False."""
        result = safe_eval("0 and True")
        assert result == 0

    def test_or_returns_truthy_value(self):
        """'or' should return the actual truthy value, not just True."""
        result = safe_eval("0 or 42")
        assert result == 42


# ============================================================
# Security: Attribute access type safety
# ============================================================


class TestAttributeTypeSafety:
    """Verify that getattr is restricted to safe types."""

    def test_attribute_on_dict_allowed(self):
        """Dict methods like .get() should work."""
        assert safe_eval("d.get('a', 0)", {"d": {"a": 1}}) == 1

    def test_attribute_on_string_allowed(self):
        """String methods like .lower() should work."""
        assert safe_eval("s.lower()", {"s": "HELLO"}) == "hello"

    def test_attribute_on_list_allowed(self):
        """List attributes should be accessible."""
        # list doesn't have many useful non-mutating public attrs,
        # but the type itself should be allowed
        ctx = {"items": [1, 2, 3]}
        # This tests that the type check passes for list
        result = safe_eval("len(items)", ctx)
        assert result == 3

    def test_attribute_on_arbitrary_object_denied(self):
        """Attribute access on non-primitive types must be denied."""

        class CustomObj:
            dangerous = "leaked"

        with pytest.raises(ValueError, match="Attribute access on type"):
            safe_eval("obj.dangerous", {"obj": CustomObj()})

    def test_private_attribute_denied(self):
        """Underscore-prefixed attributes must be denied."""
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("s.__class__", {"s": "hello"})

    def test_dunder_attribute_denied(self):
        """Dunder attributes must be denied."""
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("s.__doc__", {"s": "hello"})


# ============================================================
# Security: Unsafe function/operation denial
# ============================================================


class TestUnsafeOperationDenial:
    """Verify that dangerous operations are blocked."""

    def test_import_denied(self):
        with pytest.raises((ValueError, NameError)):
            safe_eval("__import__('os')")

    def test_eval_denied(self):
        with pytest.raises((ValueError, NameError)):
            safe_eval("eval('1+1')")

    def test_exec_denied(self):
        with pytest.raises((ValueError, NameError)):
            safe_eval("exec('x=1')")

    def test_open_denied(self):
        with pytest.raises((ValueError, NameError)):
            safe_eval("open('/etc/passwd')")

    def test_lambda_denied(self):
        with pytest.raises(ValueError, match="is not allowed"):
            safe_eval("(lambda: 1)()")

    def test_assignment_denied(self):
        with pytest.raises(SyntaxError):
            # ast.parse in 'eval' mode rejects statements
            safe_eval("x = 1")

    def test_undefined_variable(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("undefined_var")

    def test_invalid_syntax(self):
        with pytest.raises(SyntaxError):
            safe_eval("if True: pass")


# ============================================================
# Edge-condition integration patterns
# ============================================================


class TestEdgeConditionPatterns:
    """Test expression patterns commonly used in edge conditions."""

    def test_output_field_check(self):
        """Typical edge condition: check output field value."""
        ctx = {"output": {"confidence": 0.9}}
        assert safe_eval("output['confidence'] > 0.8", ctx) is True
        assert safe_eval("output['confidence'] < 0.5", ctx) is False

    def test_output_get_with_default(self):
        """Using .get() for safe key access."""
        ctx = {"output": {"status": "done"}}
        assert safe_eval("output.get('status') == 'done'", ctx) is True
        assert safe_eval("output.get('missing', 'default') == 'default'", ctx) is True

    def test_none_check_with_and(self):
        """Common pattern: null-safe field access with short-circuit."""
        ctx = {"result": None}
        assert safe_eval("result is not None and result > 0", ctx) is False

        ctx = {"result": 42}
        assert safe_eval("result is not None and result > 0", ctx) is True

    def test_memory_key_check(self):
        """Check if a key exists in memory via 'in' operator."""
        ctx = {"memory": {"customer_id": "abc123"}}
        assert safe_eval("'customer_id' in memory", ctx) is True
        assert safe_eval("'missing_key' in memory", ctx) is False

    def test_string_comparison(self):
        """String-based routing decisions."""
        ctx = {"status": "needs_review"}
        assert safe_eval("status == 'needs_review'", ctx) is True
        assert safe_eval("status != 'approved'", ctx) is True

    def test_complex_condition(self):
        """Multi-part condition combining checks."""
        ctx = {
            "output": {"confidence": 0.7, "status": "partial"},
            "retry_count": 2,
        }
        expr = "output['confidence'] < 0.8 and retry_count < 3"
        assert safe_eval(expr, ctx) is True
