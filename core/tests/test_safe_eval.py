"""
Tests for safe_eval module - safe expression evaluation.

Tests cover:
- Arithmetic, comparison, and boolean operations
- String operations and dict/list access
- Safety enforcement (reject imports, exec, eval, dunder access)
- Edge cases (empty expressions, None values, type mismatches)
"""

import pytest

from framework.graph.safe_eval import safe_eval, SafeEvalVisitor, SAFE_FUNCTIONS, SAFE_OPERATORS
import ast


class TestArithmeticOperations:
    """Tests for arithmetic operations in safe_eval."""

    def test_addition(self):
        assert safe_eval("2 + 3") == 5

    def test_subtraction(self):
        assert safe_eval("10 - 4") == 6

    def test_multiplication(self):
        assert safe_eval("3 * 4") == 12

    def test_division(self):
        assert safe_eval("10 / 4") == 2.5

    def test_floor_division(self):
        assert safe_eval("10 // 3") == 3

    def test_modulo(self):
        assert safe_eval("10 % 3") == 1

    def test_power(self):
        assert safe_eval("2 ** 3") == 8

    def test_complex_expression(self):
        assert safe_eval("(2 + 3) * 4 - 5") == 15

    def test_negative_numbers(self):
        assert safe_eval("-5") == -5

    def test_unary_plus(self):
        assert safe_eval("+5") == 5


class TestComparisonOperations:
    """Tests for comparison operations in safe_eval."""

    def test_equal(self):
        assert safe_eval("5 == 5") is True
        assert safe_eval("5 == 6") is False

    def test_not_equal(self):
        assert safe_eval("5 != 6") is True
        assert safe_eval("5 != 5") is False

    def test_less_than(self):
        assert safe_eval("3 < 5") is True
        assert safe_eval("5 < 3") is False

    def test_less_than_or_equal(self):
        assert safe_eval("3 <= 5") is True
        assert safe_eval("5 <= 5") is True
        assert safe_eval("6 <= 5") is False

    def test_greater_than(self):
        assert safe_eval("5 > 3") is True
        assert safe_eval("3 > 5") is False

    def test_greater_than_or_equal(self):
        assert safe_eval("5 >= 3") is True
        assert safe_eval("5 >= 5") is True
        assert safe_eval("3 >= 5") is False

    def test_chained_comparison(self):
        assert safe_eval("1 < 2 < 3") is True
        assert safe_eval("1 < 3 < 2") is False
        assert safe_eval("5 > 3 > 1") is True

    def test_is_operator(self):
        assert safe_eval("a is None", {"a": None}) is True
        obj_a = object()
        obj_b = object()
        assert safe_eval("a is b", {"a": obj_a, "b": obj_b}) is False
        assert safe_eval("a is b", {"a": obj_a, "b": obj_a}) is True

    def test_is_not_operator(self):
        assert safe_eval("a is not None", {"a": 1}) is True
        assert safe_eval("a is not b", {"a": 1, "b": 2}) is True


class TestBooleanOperations:
    """Tests for boolean operations in safe_eval."""

    def test_and_operator(self):
        assert safe_eval("True and True") is True
        assert safe_eval("True and False") is False
        assert safe_eval("False and True") is False
        assert safe_eval("False and False") is False

    def test_or_operator(self):
        assert safe_eval("True or True") is True
        assert safe_eval("True or False") is True
        assert safe_eval("False or True") is True
        assert safe_eval("False or False") is False

    def test_not_operator(self):
        assert safe_eval("not True") is False
        assert safe_eval("not False") is True

    def test_combined_boolean(self):
        assert safe_eval("True and False or True") is True
        assert safe_eval("(True or False) and False") is False

    def test_ternary_expression(self):
        assert safe_eval("1 if True else 2") == 1
        assert safe_eval("1 if False else 2") == 2


class TestStringOperations:
    """Tests for string operations in safe_eval."""

    def test_string_literal(self):
        assert safe_eval("'hello'") == "hello"

    def test_string_concatenation(self):
        assert safe_eval("'hello' + ' world'") == "hello world"

    def test_string_comparison(self):
        assert safe_eval("'a' < 'b'") is True
        assert safe_eval("'abc' == 'abc'") is True

    def test_string_in_operator(self):
        assert safe_eval("'ell' in 'hello'") is True
        assert safe_eval("'xyz' in 'hello'") is False

    def test_string_not_in_operator(self):
        assert safe_eval("'xyz' not in 'hello'") is True
        assert safe_eval("'ell' not in 'hello'") is False

    def test_string_multiplication(self):
        assert safe_eval("'ab' * 3") == "ababab"


class TestListOperations:
    """Tests for list operations in safe_eval."""

    def test_list_literal(self):
        assert safe_eval("[1, 2, 3]") == [1, 2, 3]

    def test_list_indexing(self):
        assert safe_eval("[1, 2, 3][0]") == 1
        assert safe_eval("[1, 2, 3][-1]") == 3

    def test_list_in_operator(self):
        assert safe_eval("2 in [1, 2, 3]") is True
        assert safe_eval("5 in [1, 2, 3]") is False

    def test_list_concatenation(self):
        assert safe_eval("[1, 2] + [3, 4]") == [1, 2, 3, 4]

    def test_nested_lists(self):
        assert safe_eval("[[1, 2], [3, 4]]") == [[1, 2], [3, 4]]


class TestDictOperations:
    """Tests for dict operations in safe_eval."""

    def test_dict_literal(self):
        assert safe_eval("{'a': 1, 'b': 2}") == {"a": 1, "b": 2}

    def test_dict_access(self):
        assert safe_eval("{'a': 1}['a']") == 1

    def test_dict_with_variable(self):
        context = {"d": {"key": "value"}}
        assert safe_eval("d['key']", context) == "value"

    def test_nested_dict(self):
        assert safe_eval("{'outer': {'inner': 1}}") == {"outer": {"inner": 1}}


class TestTupleOperations:
    """Tests for tuple operations in safe_eval."""

    def test_tuple_literal(self):
        assert safe_eval("(1, 2, 3)") == (1, 2, 3)

    def test_tuple_indexing(self):
        assert safe_eval("(1, 2, 3)[0]") == 1

    def test_tuple_in_operator(self):
        assert safe_eval("2 in (1, 2, 3)") is True


class TestVariableAccess:
    """Tests for variable access in safe_eval."""

    def test_simple_variable(self):
        assert safe_eval("x", {"x": 10}) == 10

    def test_variable_in_expression(self):
        assert safe_eval("x + y", {"x": 5, "y": 3}) == 8

    def test_undefined_variable_raises_error(self):
        with pytest.raises(NameError) as exc_info:
            safe_eval("undefined_var")
        assert "undefined_var" in str(exc_info.value)

    def test_none_value(self):
        assert safe_eval("x", {"x": None}) is None

    def test_none_comparison(self):
        assert safe_eval("x is None", {"x": None}) is True
        assert safe_eval("x is not None", {"x": 1}) is True


class TestSafeFunctions:
    """Tests for whitelisted safe functions."""

    def test_len_function(self):
        assert safe_eval("len([1, 2, 3])") == 3
        assert safe_eval("len('hello')") == 5

    def test_int_function(self):
        assert safe_eval("int('42')") == 42
        assert safe_eval("int(3.7)") == 3

    def test_float_function(self):
        assert safe_eval("float('3.14')") == 3.14
        assert safe_eval("float(5)") == 5.0

    def test_str_function(self):
        assert safe_eval("str(42)") == "42"

    def test_bool_function(self):
        assert safe_eval("bool(1)") is True
        assert safe_eval("bool(0)") is False

    def test_list_function(self):
        assert safe_eval("list((1, 2, 3))") == [1, 2, 3]

    def test_dict_function(self):
        assert safe_eval("dict([('a', 1)])") == {"a": 1}

    def test_tuple_function(self):
        assert safe_eval("tuple([1, 2, 3])") == (1, 2, 3)

    def test_set_function(self):
        assert safe_eval("set([1, 2, 2, 3])") == {1, 2, 3}

    def test_min_function(self):
        assert safe_eval("min(1, 2, 3)") == 1
        assert safe_eval("min([5, 3, 7])") == 3

    def test_max_function(self):
        assert safe_eval("max(1, 2, 3)") == 3
        assert safe_eval("max([5, 3, 7])") == 7

    def test_sum_function(self):
        assert safe_eval("sum([1, 2, 3])") == 6

    def test_abs_function(self):
        assert safe_eval("abs(-5)") == 5
        assert safe_eval("abs(5)") == 5

    def test_round_function(self):
        assert safe_eval("round(3.14159, 2)") == 3.14

    def test_all_function(self):
        assert safe_eval("all([True, True, True])") is True
        assert safe_eval("all([True, False, True])") is False

    def test_any_function(self):
        assert safe_eval("any([False, False, True])") is True
        assert safe_eval("any([False, False, False])") is False


class TestSafeMethods:
    """Tests for whitelisted safe methods."""

    def test_dict_get_method(self):
        context = {"d": {"a": 1}}
        assert safe_eval("d.get('a')", context) == 1
        assert safe_eval("d.get('b', 0)", context) == 0

    def test_dict_keys_method(self):
        context = {"d": {"a": 1, "b": 2}}
        result = safe_eval("list(d.keys())", context)
        assert set(result) == {"a", "b"}

    def test_dict_values_method(self):
        context = {"d": {"a": 1, "b": 2}}
        result = safe_eval("list(d.values())", context)
        assert set(result) == {1, 2}

    def test_dict_items_method(self):
        context = {"d": {"a": 1}}
        assert safe_eval("list(d.items())", context) == [("a", 1)]

    def test_string_lower_method(self):
        context = {"s": "HELLO"}
        assert safe_eval("s.lower()", context) == "hello"

    def test_string_upper_method(self):
        context = {"s": "hello"}
        assert safe_eval("s.upper()", context) == "HELLO"

    def test_string_strip_method(self):
        context = {"s": "  hello  "}
        assert safe_eval("s.strip()", context) == "hello"

    def test_string_split_method(self):
        context = {"s": "a,b,c"}
        assert safe_eval("s.split(',')", context) == ["a", "b", "c"]


class TestSecurityEnforcement:
    """Tests for security enforcement - rejecting dangerous operations."""

    def test_reject_import(self):
        with pytest.raises(NameError):
            safe_eval("__import__('os')")

    def test_reject_eval(self):
        with pytest.raises(NameError):
            safe_eval("eval('1+1')")

    def test_reject_exec(self):
        with pytest.raises(NameError):
            safe_eval("exec('x = 1')")

    def test_reject_dunder_access(self):
        with pytest.raises(ValueError) as exc_info:
            safe_eval("x.__class__", {"x": 1})
        assert "private attribute" in str(exc_info.value)

    def test_reject_dunder_dict_access(self):
        with pytest.raises(ValueError) as exc_info:
            safe_eval("x.__dict__", {"x": 1})
        assert "private attribute" in str(exc_info.value)

    def test_reject_private_attribute(self):
        with pytest.raises(ValueError) as exc_info:
            safe_eval("x._private", {"x": type("T", (), {"_private": 1})})
        assert "private attribute" in str(exc_info.value)

    def test_reject_open_function(self):
        with pytest.raises(NameError):
            safe_eval("open('/etc/passwd')")

    def test_reject_compile_function(self):
        with pytest.raises(NameError):
            safe_eval("compile('1+1', '', 'eval')")

    def test_reject_globals_access(self):
        with pytest.raises(NameError):
            safe_eval("globals()")

    def test_reject_locals_access(self):
        with pytest.raises(NameError):
            safe_eval("locals()")

    def test_reject_arbitrary_function_call(self):
        def dangerous():
            raise RuntimeError("Should not be called")

        with pytest.raises(ValueError):
            safe_eval("dangerous()", {"dangerous": dangerous})

    def test_reject_unsafe_method(self):
        context = {"s": "hello"}
        with pytest.raises(ValueError):
            safe_eval("s.format('{0}')", context)


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_expression_raises_syntax_error(self):
        with pytest.raises(SyntaxError):
            safe_eval("")

    def test_whitespace_only(self):
        with pytest.raises(SyntaxError):
            safe_eval("   ")

    def test_syntax_error_in_expression(self):
        with pytest.raises(SyntaxError):
            safe_eval("1 +")

    def test_unclosed_parenthesis(self):
        with pytest.raises(SyntaxError):
            safe_eval("(1 + 2")

    def test_none_context(self):
        assert safe_eval("1 + 2", None) == 3

    def test_empty_context(self):
        assert safe_eval("1 + 2", {}) == 3

    def test_context_with_none_value(self):
        assert safe_eval("x is None", {"x": None}) is True

    def test_type_mismatch_arithmetic(self):
        with pytest.raises(TypeError):
            safe_eval("'hello' + 5")

    def test_large_numbers(self):
        assert safe_eval("10 ** 100") == 10**100

    def test_float_precision(self):
        result = safe_eval("0.1 + 0.2")
        assert abs(result - 0.3) < 1e-10

    def test_division_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            safe_eval("1 / 0")

    def test_modulo_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            safe_eval("5 % 0")

    def test_index_out_of_range(self):
        with pytest.raises(IndexError):
            safe_eval("[1, 2, 3][10]")

    def test_key_error(self):
        with pytest.raises(KeyError):
            safe_eval("{'a': 1}['b']")


class TestSafeEvalVisitor:
    """Tests for SafeEvalVisitor class directly."""

    def test_visit_constant(self):
        visitor = SafeEvalVisitor({})
        node = ast.parse("42", mode="eval")
        assert visitor.visit(node) == 42

    def test_visit_name_from_context(self):
        visitor = SafeEvalVisitor({"x": 100})
        node = ast.parse("x", mode="eval")
        assert visitor.visit(node) == 100

    def test_generic_visit_rejects_unknown(self):
        visitor = SafeEvalVisitor({})
        yield_node = ast.Yield(value=ast.Constant(value=1))
        with pytest.raises(ValueError) as exc_info:
            visitor.generic_visit(yield_node)
        assert "not allowed" in str(exc_info.value)
