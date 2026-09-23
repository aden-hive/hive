"""
Tests for framework.graph.safe_eval (the AST-interpreter safe_eval used by
edge conditions).

Tests cover:
- Bounded sequence repetition (`*`), the security fix for the unbounded
  DoS in `x * n` / `n * x` expressions (e.g. `'a' * 10**10`)
- Legitimate small repeats still working correctly
- Existing safety guards (unchanged) still hold
"""

import pytest

from framework.graph.safe_eval import (
    MAX_SEQUENCE_REPEAT_LENGTH,
    bounded_multiply,
    safe_eval,
)


class TestSequenceRepetitionBound:
    """Tests for the sequence-repetition DoS fix."""

    def test_blocks_huge_string_repeat(self):
        """'a' * 10**10 must be rejected, not allocated."""
        with pytest.raises(ValueError, match="exceeds the maximum"):
            safe_eval("'a' * 10**10")

    def test_blocks_huge_list_repeat(self):
        """[0] * 10**9 must be rejected, not allocated."""
        with pytest.raises(ValueError, match="exceeds the maximum"):
            safe_eval("[0] * 10**9")

    def test_blocks_int_times_seq_order(self):
        """n * 'a' (int on the left) must be bounded too."""
        with pytest.raises(ValueError, match="exceeds the maximum"):
            safe_eval("n * 'a'", {"n": 10**10})

    def test_blocks_huge_tuple_repeat(self):
        with pytest.raises(ValueError, match="exceeds the maximum"):
            safe_eval("(1, 2) * 10**9")

    def test_blocks_nested_repeats_each_step_checked(self):
        """
        Each multiplication step is checked, so a chain of individually
        'small' multiplications that compounds past the bound is still caught.
        """
        # 1000 * 1000 * 1000 = 1e9 elements, but even the intermediate
        # 1000 * 1000 = 1e6 already exceeds the bound and must raise there.
        with pytest.raises(ValueError, match="exceeds the maximum"):
            safe_eval("('a' * 1000) * 1000 * 1000")

    def test_bound_is_exact_boundary(self):
        """Exactly at the bound is allowed; one past it is rejected."""
        result = safe_eval(f"'a' * {MAX_SEQUENCE_REPEAT_LENGTH}")
        assert len(result) == MAX_SEQUENCE_REPEAT_LENGTH

        with pytest.raises(ValueError, match="exceeds the maximum"):
            safe_eval(f"'a' * {MAX_SEQUENCE_REPEAT_LENGTH + 1}")

    def test_legitimate_small_string_repeat(self):
        assert safe_eval("'ab' * 5") == "ababababab"

    def test_legitimate_small_list_repeat(self):
        assert safe_eval("[1, 2] * 3") == [1, 2, 1, 2, 1, 2]

    def test_legitimate_small_tuple_repeat(self):
        assert safe_eval("(1, 2) * 3") == (1, 2, 1, 2, 1, 2)

    def test_legitimate_int_times_seq_order(self):
        assert safe_eval("3 * 'ab'") == "ababab"

    def test_negative_multiplier_keeps_normal_semantics(self):
        """Negative multipliers produce an empty sequence, per normal Python."""
        assert safe_eval("'a' * -5") == ""
        assert safe_eval("[1, 2] * -1") == []

    def test_zero_multiplier_keeps_normal_semantics(self):
        assert safe_eval("'a' * 0") == ""
        assert safe_eval("[1, 2] * 0") == []

    def test_numeric_multiplication_unaffected(self):
        """Plain int/float multiplication is not a sequence-repetition and
        must behave exactly as before."""
        assert safe_eval("3 * 4") == 12
        assert safe_eval("3.5 * 2") == 7.0
        assert safe_eval("-3 * 4") == -12

    def test_bounded_multiply_matches_operator_mul_for_numbers(self):
        assert bounded_multiply(3, 4) == 12
        assert bounded_multiply(2.5, 2) == 5.0

    def test_mismatched_types_raise_type_error_like_normal_python(self):
        """Non-sequence, non-numeric combos should still raise the normal
        Python TypeError, not something swallowed by our bound check."""
        with pytest.raises(TypeError):
            bounded_multiply("a", "b")


class TestSafeEvalExistingGuards:
    """Spot-check other safety guards are untouched by this fix."""

    def test_blocked_private_attribute_access(self):
        with pytest.raises(ValueError):
            safe_eval("(1).__class__")

    def test_blocked_disallowed_node(self):
        """List comprehensions (and other unhandled AST nodes) fall through
        to generic_visit, which rejects them."""
        with pytest.raises(ValueError):
            safe_eval("[x for x in (1, 2, 3)]")

    def test_name_error_for_unknown_variable(self):
        with pytest.raises(NameError):
            safe_eval("undefined_var + 1")

    def test_basic_arithmetic_still_works(self):
        assert safe_eval("1 + 2 * 3") == 7

    def test_context_variables_still_work(self):
        assert safe_eval("x + y", {"x": 2, "y": 3}) == 5
