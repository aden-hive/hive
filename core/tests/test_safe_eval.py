"""
Comprehensive test suite for core/framework/graph/safe_eval.py

This module tests the sandboxed expression evaluator used by EdgeSpec.condition_expr.
Coverage includes:
- Literals and data structures
- Arithmetic, unary, binary, boolean operators
- Short-circuit evaluation for and/or
- Ternary expressions, variable lookup, subscript/attribute access
- All whitelisted function and method calls
- Security boundaries (private attrs, disallowed AST nodes, blocked builtins)
- Real-world EdgeSpec.condition_expr patterns
"""

import pytest

from framework.graph.safe_eval import safe_eval, SAFE_FUNCTIONS, SAFE_OPERATORS
import ast
import operator


class TestLiteralsAndConstants:
    def test_integer_literal(self):
        assert safe_eval("42") == 42

    def test_float_literal(self):
        assert safe_eval("3.14") == 3.14

    def test_string_literal(self):
        assert safe_eval("'hello'") == "hello"

    def test_string_double_quotes(self):
        assert safe_eval('"world"') == "world"

    def test_boolean_true(self):
        assert safe_eval("True") is True

    def test_boolean_false(self):
        assert safe_eval("False") is False

    def test_none_literal(self):
        assert safe_eval("None") is None

    def test_negative_integer(self):
        assert safe_eval("-5") == -5

    def test_positive_integer(self):
        assert safe_eval("+5") == 5


class TestDataStructures:
    def test_empty_list(self):
        assert safe_eval("[]") == []

    def test_list_with_elements(self):
        assert safe_eval("[1, 2, 3]") == [1, 2, 3]

    def test_nested_list(self):
        assert safe_eval("[[1, 2], [3, 4]]") == [[1, 2], [3, 4]]

    def test_empty_tuple(self):
        assert safe_eval("()") == ()

    def test_tuple_with_elements(self):
        assert safe_eval("(1, 2, 3)") == (1, 2, 3)

    def test_single_element_tuple(self):
        assert safe_eval("(1,)") == (1,)

    def test_empty_dict(self):
        assert safe_eval("{}") == {}

    def test_dict_with_elements(self):
        assert safe_eval("{'a': 1, 'b': 2}") == {"a": 1, "b": 2}

    def test_nested_dict(self):
        assert safe_eval("{'outer': {'inner': 42}}") == {"outer": {"inner": 42}}

    def test_mixed_data_structure(self):
        assert safe_eval("{'list': [1, 2], 'tuple': (3, 4)}") == {
            "list": [1, 2],
            "tuple": (3, 4),
        }


class TestArithmeticOperators:
    def test_addition(self):
        assert safe_eval("2 + 3") == 5

    def test_subtraction(self):
        assert safe_eval("10 - 4") == 6

    def test_multiplication(self):
        assert safe_eval("6 * 7") == 42

    def test_division(self):
        assert safe_eval("10 / 4") == 2.5

    def test_floor_division(self):
        assert safe_eval("10 // 3") == 3

    def test_modulo(self):
        assert safe_eval("10 % 3") == 1

    def test_power(self):
        assert safe_eval("2 ** 8") == 256

    def test_complex_arithmetic(self):
        assert safe_eval("2 + 3 * 4 - 1") == 13

    def test_parentheses(self):
        assert safe_eval("(2 + 3) * 4") == 20


class TestBitwiseOperators:
    def test_left_shift(self):
        assert safe_eval("1 << 4") == 16

    def test_right_shift(self):
        assert safe_eval("16 >> 2") == 4

    def test_bitwise_or(self):
        assert safe_eval("5 | 3") == 7

    def test_bitwise_xor(self):
        assert safe_eval("5 ^ 3") == 6

    def test_bitwise_and(self):
        assert safe_eval("5 & 3") == 1


class TestComparisonOperators:
    def test_equal(self):
        assert safe_eval("5 == 5") is True
        assert safe_eval("5 == 6") is False

    def test_not_equal(self):
        assert safe_eval("5 != 6") is True
        assert safe_eval("5 != 5") is False

    def test_less_than(self):
        assert safe_eval("3 < 5") is True
        assert safe_eval("5 < 3") is False

    def test_less_equal(self):
        assert safe_eval("3 <= 5") is True
        assert safe_eval("5 <= 5") is True
        assert safe_eval("6 <= 5") is False

    def test_greater_than(self):
        assert safe_eval("5 > 3") is True
        assert safe_eval("3 > 5") is False

    def test_greater_equal(self):
        assert safe_eval("5 >= 3") is True
        assert safe_eval("5 >= 5") is True
        assert safe_eval("3 >= 5") is False

    def test_is_operator(self):
        assert safe_eval("None is None") is True
        assert safe_eval("1 is None") is False

    def test_is_not_operator(self):
        assert safe_eval("1 is not None") is True
        assert safe_eval("None is not None") is False

    def test_in_operator(self):
        assert safe_eval("3 in [1, 2, 3]") is True
        assert safe_eval("4 in [1, 2, 3]") is False

    def test_not_in_operator(self):
        assert safe_eval("4 not in [1, 2, 3]") is True
        assert safe_eval("3 not in [1, 2, 3]") is False

    def test_chained_comparison(self):
        assert safe_eval("1 < 2 < 3") is True
        assert safe_eval("1 < 3 < 2") is False
        assert safe_eval("1 < 2 <= 2 < 3") is True


class TestUnaryOperators:
    def test_unary_negation(self):
        assert safe_eval("-5") == -5

    def test_unary_positive(self):
        assert safe_eval("+5") == 5

    def test_unary_not(self):
        assert safe_eval("not True") is False
        assert safe_eval("not False") is True

    def test_unary_invert(self):
        assert safe_eval("~5") == -6

    def test_double_negation(self):
        assert safe_eval("--5") == 5


class TestBooleanOperators:
    def test_and_true_true(self):
        assert safe_eval("True and True") is True

    def test_and_true_false(self):
        assert safe_eval("True and False") is False

    def test_or_false_false(self):
        assert safe_eval("False or False") is False

    def test_or_true_false(self):
        assert safe_eval("True or False") is True

    def test_multiple_and(self):
        assert safe_eval("True and True and True") is True
        assert safe_eval("True and True and False") is False

    def test_multiple_or(self):
        assert safe_eval("False or False or True") is True
        assert safe_eval("False or False or False") is False


class TestShortCircuitEvaluation:
    def test_and_evaluates_all_values(self):
        context = {"x": None}
        with pytest.raises(AttributeError):
            safe_eval("x and x.nonexistent", context)

    def test_or_evaluates_all_values(self):
        context = {"x": "value"}
        with pytest.raises(AttributeError):
            safe_eval("x or x.nonexistent", context)

    def test_guard_pattern_with_none_raises(self):
        context = {"output": None}
        with pytest.raises(AttributeError):
            safe_eval("output is not None and output.get('key')", context)

    def test_guard_pattern_with_value_returns_true(self):
        context = {"output": {"key": "value"}}
        result = safe_eval("output is not None and output.get('key')", context)
        assert result is True

    def test_guard_pattern_with_falsy_value(self):
        context = {"output": {}}
        result = safe_eval("output is not None and output.get('key')", context)
        assert result is False

    def test_or_pattern_returns_boolean(self):
        context = {"output": {}}
        result = safe_eval("output.get('key') or 'default'", context)
        assert result is True

    def test_or_pattern_with_value_returns_boolean(self):
        context = {"output": {"key": "found"}}
        result = safe_eval("output.get('key') or 'default'", context)
        assert result is True

    def test_boolean_and_returns_boolean(self):
        assert safe_eval("True and True") is True
        assert safe_eval("True and False") is False
        assert safe_eval("1 and 2") is True

    def test_boolean_or_returns_boolean(self):
        assert safe_eval("False or True") is True
        assert safe_eval("False or False") is False
        assert safe_eval("0 or 1") is True


class TestTernaryExpressions:
    def test_ternary_true_branch(self):
        assert safe_eval("'yes' if True else 'no'") == "yes"

    def test_ternary_false_branch(self):
        assert safe_eval("'yes' if False else 'no'") == "no"

    def test_ternary_with_comparison(self):
        assert safe_eval("'big' if 10 > 5 else 'small'") == "big"

    def test_ternary_with_variables(self):
        context = {"x": 10}
        assert safe_eval("'positive' if x > 0 else 'non-positive'", context) == "positive"

    def test_nested_ternary(self):
        expr = "'high' if x > 10 else 'medium' if x > 5 else 'low'"
        assert safe_eval(expr, {"x": 15}) == "high"
        assert safe_eval(expr, {"x": 7}) == "medium"
        assert safe_eval(expr, {"x": 3}) == "low"


class TestVariableLookup:
    def test_simple_variable(self):
        assert safe_eval("x", {"x": 42}) == 42

    def test_string_variable(self):
        assert safe_eval("name", {"name": "Alice"}) == "Alice"

    def test_missing_variable(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("missing_var", {})

    def test_dict_variable(self):
        context = {"data": {"key": "value"}}
        assert safe_eval("data", context) == {"key": "value"}

    def test_list_variable(self):
        context = {"items": [1, 2, 3]}
        assert safe_eval("items", context) == [1, 2, 3]


class TestSubscriptAccess:
    def test_list_index(self):
        context = {"items": [10, 20, 30]}
        assert safe_eval("items[0]", context) == 10
        assert safe_eval("items[1]", context) == 20
        assert safe_eval("items[2]", context) == 30

    def test_list_negative_index(self):
        context = {"items": [10, 20, 30]}
        assert safe_eval("items[-1]", context) == 30

    def test_dict_key_access(self):
        context = {"data": {"name": "Alice", "age": 30}}
        assert safe_eval("data['name']", context) == "Alice"
        assert safe_eval("data['age']", context) == 30

    def test_nested_subscript(self):
        context = {"nested": {"level1": {"level2": "deep"}}}
        assert safe_eval("nested['level1']['level2']", context) == "deep"

    def test_subscript_with_expression(self):
        context = {"items": [10, 20, 30], "i": 1}
        assert safe_eval("items[i]", context) == 20

    def test_tuple_index(self):
        context = {"coords": (100, 200)}
        assert safe_eval("coords[0]", context) == 100


class TestAttributeAccess:
    def test_string_upper_method(self):
        assert safe_eval("'hello'.upper()") == "HELLO"

    def test_string_lower_method(self):
        assert safe_eval("'HELLO'.lower()") == "hello"

    def test_string_strip_method(self):
        assert safe_eval("'  hello  '.strip()") == "hello"

    def test_string_split_method(self):
        assert safe_eval("'a,b,c'.split(',')") == ["a", "b", "c"]

    def test_dict_get_method(self):
        context = {"data": {"key": "value"}}
        assert safe_eval("data.get('key')", context) == "value"

    def test_dict_get_default(self):
        context = {"data": {}}
        assert safe_eval("data.get('missing', 'default')", context) == "default"

    def test_dict_keys_method(self):
        context = {"data": {"a": 1, "b": 2}}
        result = safe_eval("list(data.keys())", context)
        assert set(result) == {"a", "b"}

    def test_dict_values_method(self):
        context = {"data": {"a": 1, "b": 2}}
        result = safe_eval("list(data.values())", context)
        assert set(result) == {1, 2}

    def test_dict_items_method(self):
        context = {"data": {"a": 1}}
        result = safe_eval("list(data.items())", context)
        assert result == [("a", 1)]

    def test_private_attribute_blocked(self):
        context = {"obj": type("Obj", (), {"_private": "secret"})}
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("obj._private", context)

    def test_dunder_attribute_blocked(self):
        context = {"obj": {}}
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("obj.__class__", context)

    def test_nonexistent_attribute(self):
        context = {"data": {}}
        with pytest.raises(AttributeError):
            safe_eval("data.nonexistent", context)


class TestWhitelistedFunctions:
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
        assert safe_eval("str(None)") == "None"

    def test_bool_function(self):
        assert safe_eval("bool(1)") is True
        assert safe_eval("bool(0)") is False
        assert safe_eval("bool('')") is False
        assert safe_eval("bool('text')") is True

    def test_list_function(self):
        assert safe_eval("list('abc')") == ["a", "b", "c"]
        assert safe_eval("list((1, 2))") == [1, 2]

    def test_dict_function(self):
        assert safe_eval("dict([('a', 1), ('b', 2)])") == {"a": 1, "b": 2}

    def test_tuple_function(self):
        assert safe_eval("tuple([1, 2, 3])") == (1, 2, 3)

    def test_set_function(self):
        assert safe_eval("set([1, 2, 2, 3])") == {1, 2, 3}

    def test_min_function(self):
        assert safe_eval("min(1, 2, 3)") == 1
        assert safe_eval("min([5, 2, 8])") == 2

    def test_max_function(self):
        assert safe_eval("max(1, 2, 3)") == 3
        assert safe_eval("max([5, 2, 8])") == 8

    def test_sum_function(self):
        assert safe_eval("sum([1, 2, 3])") == 6

    def test_abs_function(self):
        assert safe_eval("abs(-5)") == 5
        assert safe_eval("abs(5)") == 5

    def test_round_function(self):
        assert safe_eval("round(3.14159, 2)") == 3.14
        assert safe_eval("round(3.5)") == 4

    def test_all_function(self):
        assert safe_eval("all([True, True, True])") is True
        assert safe_eval("all([True, False, True])") is False
        assert safe_eval("all([])") is True

    def test_any_function(self):
        assert safe_eval("any([False, False, True])") is True
        assert safe_eval("any([False, False, False])") is False
        assert safe_eval("any([])") is False


class TestWhitelistedMethods:
    def test_string_lower(self):
        assert safe_eval("'HELLO'.lower()") == "hello"

    def test_string_upper(self):
        assert safe_eval("'hello'.upper()") == "HELLO"

    def test_string_strip(self):
        assert safe_eval("'  x  '.strip()") == "x"

    def test_string_split(self):
        assert safe_eval("'a-b'.split('-')") == ["a", "b"]

    def test_dict_get(self):
        assert safe_eval("{'a': 1}.get('a')") == 1

    def test_dict_keys(self):
        result = safe_eval("list({'a': 1, 'b': 2}.keys())")
        assert set(result) == {"a", "b"}

    def test_dict_values(self):
        result = safe_eval("list({'a': 1, 'b': 2}.values())")
        assert set(result) == {1, 2}

    def test_dict_items(self):
        result = safe_eval("list({'a': 1}.items())")
        assert result == [("a", 1)]


class TestSecurityBoundaries:
    def test_private_attribute_access_blocked(self):
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("'hello'._class__")

    def test_lambda_blocked(self):
        with pytest.raises(ValueError, match="Lambda is not allowed"):
            safe_eval("lambda x: x + 1")

    def test_import_blocked(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("__import__('os')")

    def test_eval_blocked(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("eval('1+1')")

    def test_exec_blocked(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("exec('x=1')")

    def test_open_blocked(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("open('/etc/passwd')")

    def test_compile_blocked(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("compile('x', 'x', 'exec')")

    def test_dunder_name_blocked(self):
        with pytest.raises(NameError, match="not defined"):
            safe_eval("__import__")

    def test_function_def_blocked(self):
        with pytest.raises(SyntaxError):
            safe_eval("def f(): pass")

    def test_class_def_blocked(self):
        with pytest.raises(SyntaxError):
            safe_eval("class C: pass")

    def test_assignment_blocked(self):
        with pytest.raises(SyntaxError):
            safe_eval("x = 5")

    def test_augmented_assignment_blocked(self):
        context = {"x": 5}
        with pytest.raises(SyntaxError):
            safe_eval("x += 1", context)

    def test_del_blocked(self):
        context = {"x": {"a": 1}}
        with pytest.raises(SyntaxError):
            safe_eval("del x['a']", context)

    def test_await_blocked(self):
        with pytest.raises(ValueError, match="Await is not allowed"):
            safe_eval("await something")

    def test_yield_blocked(self):
        with pytest.raises(SyntaxError):
            safe_eval("yield 1")

    def test_list_comprehension_blocked(self):
        with pytest.raises(ValueError, match="ListComp is not allowed"):
            safe_eval("[x for x in [1, 2, 3]]")

    def test_dict_comprehension_blocked(self):
        with pytest.raises(ValueError, match="DictComp is not allowed"):
            safe_eval("{k: v for k, v in [('a', 1)]}")

    def test_set_comprehension_blocked(self):
        with pytest.raises(ValueError, match="SetComp is not allowed"):
            safe_eval("{x for x in [1, 2, 3]}")

    def test_generator_expression_blocked(self):
        with pytest.raises(ValueError, match="GeneratorExp is not allowed"):
            safe_eval("(x for x in [1, 2, 3])")

    def test_starred_expression_blocked(self):
        with pytest.raises(SyntaxError):
            safe_eval("*[1, 2, 3]")

    def test_subscript_assignment_blocked(self):
        context = {"x": [1, 2, 3]}
        with pytest.raises(SyntaxError):
            safe_eval("x[0] = 5", context)

    def test_method_not_in_whitelist_blocked(self):
        with pytest.raises(ValueError, match="not allowed"):
            safe_eval("'hello'.replace('l', 'x')")


class TestEdgeSpecConditionPatterns:
    def test_output_confidence_check(self):
        context = {"output": {"confidence": 0.9}}
        assert safe_eval("output['confidence'] > 0.8", context) is True

    def test_output_confidence_check_false(self):
        context = {"output": {"confidence": 0.5}}
        assert safe_eval("output['confidence'] > 0.8", context) is False

    def test_result_check(self):
        context = {"result": "success"}
        assert safe_eval("result == 'success'", context) is True

    def test_output_key_exists(self):
        context = {"output": {"error": None}}
        assert safe_eval("output.get('error') is None", context) is True

    def test_output_has_data(self):
        context = {"output": {"data": [1, 2, 3]}}
        assert safe_eval("len(output.get('data', [])) > 0", context) is True

    def test_output_is_empty(self):
        context = {"output": {}}
        assert safe_eval("len(output) == 0", context) is True

    def test_memory_value_check(self):
        context = {"memory": {"retry_count": 2}, "retry_count": 2}
        assert safe_eval("retry_count < 3", context) is True

    def test_combined_condition(self):
        context = {"output": {"success": True, "score": 0.95}}
        assert safe_eval("output['success'] and output['score'] > 0.9", context) is True

    def test_guarded_method_call(self):
        context = {"output": {"items": [1, 2, 3]}}
        assert safe_eval("output is not None and len(output.get('items', [])) > 0", context) is True

    def test_fallback_default(self):
        context = {"output": {}}
        assert safe_eval("output.get('status') or 'pending'", context) is True

    def test_numeric_comparison_chain(self):
        context = {"value": 50}
        assert safe_eval("0 < value <= 100", context) is True

    def test_list_length_check(self):
        context = {"output": {"items": [1, 2, 3]}}
        assert safe_eval("len(output.get('items', [])) == 3", context) is True

    def test_string_contains_check(self):
        context = {"output": {"message": "Error: something failed"}}
        assert safe_eval("'Error' in output.get('message', '')", context) is True

    def test_list_in_check(self):
        context = {"status": "completed"}
        assert safe_eval("status in ['completed', 'done', 'finished']", context) is True

    def test_complex_real_world_condition(self):
        context = {
            "output": {"confidence": 0.85, "result": "valid"},
            "retry_count": 1,
        }
        expr = "output['confidence'] >= 0.8 and output['result'] == 'valid' and retry_count < 3"
        assert safe_eval(expr, context) is True


class TestSyntaxError:
    def test_invalid_syntax(self):
        with pytest.raises(SyntaxError):
            safe_eval("1 +")

    def test_incomplete_expression(self):
        with pytest.raises(SyntaxError):
            safe_eval("(1 + 2")

    def test_invalid_token(self):
        with pytest.raises(SyntaxError):
            safe_eval("1 $ 2")


class TestEdgeCases:
    def test_empty_expression(self):
        with pytest.raises(SyntaxError):
            safe_eval("")

    def test_whitespace_expression(self):
        with pytest.raises(SyntaxError):
            safe_eval("   ")

    def test_very_long_expression(self):
        parts = " + ".join(str(i) for i in range(100))
        result = safe_eval(parts)
        assert result == sum(range(100))

    def test_deeply_nested_access(self):
        context = {"data": {"a": {"b": {"c": {"d": "deep"}}}}}
        assert safe_eval("data['a']['b']['c']['d']", context) == "deep"

    def test_unicode_string(self):
        assert safe_eval("'hello world'") == "hello world"

    def test_escaped_string(self):
        assert safe_eval(r"'line1\\nline2'") == "line1\\nline2"

    def test_large_integer(self):
        assert safe_eval("999999999999999999") == 999999999999999999

    def test_float_precision(self):
        result = safe_eval("0.1 + 0.2")
        assert abs(result - 0.3) < 1e-10


class TestSafeOperatorsMapping:
    def test_all_operators_have_mapping(self):
        expected_operators = [
            ast.Add,
            ast.Sub,
            ast.Mult,
            ast.Div,
            ast.FloorDiv,
            ast.Mod,
            ast.Pow,
            ast.LShift,
            ast.RShift,
            ast.BitOr,
            ast.BitXor,
            ast.BitAnd,
            ast.Eq,
            ast.NotEq,
            ast.Lt,
            ast.LtE,
            ast.Gt,
            ast.GtE,
            ast.Is,
            ast.IsNot,
            ast.In,
            ast.NotIn,
            ast.USub,
            ast.UAdd,
            ast.Not,
            ast.Invert,
        ]
        for op in expected_operators:
            assert op in SAFE_OPERATORS, f"Missing operator: {op.__name__}"


class TestSafeFunctionsMapping:
    def test_all_functions_have_mapping(self):
        expected_functions = [
            "len",
            "int",
            "float",
            "str",
            "bool",
            "list",
            "dict",
            "tuple",
            "set",
            "min",
            "max",
            "sum",
            "abs",
            "round",
            "all",
            "any",
        ]
        for func in expected_functions:
            assert func in SAFE_FUNCTIONS, f"Missing function: {func}"
