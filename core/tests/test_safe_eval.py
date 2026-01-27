"""
Tests for the safe_eval module.

Tests cover:
- Arithmetic, comparison, and boolean operations
- String operations and dict/list access
- Safety enforcement (reject imports, exec, eval, dunder access)
- Edge cases (empty expressions, None values, type mismatches)
"""

import pytest

from framework.graph.safe_eval import safe_eval, SafeEvalVisitor, SAFE_OPERATORS, SAFE_FUNCTIONS


class TestArithmeticOperations:
    """Tests for basic arithmetic operations."""

    def test_addition(self):
        """Test addition operator."""
        assert safe_eval("2 + 3") == 5
        assert safe_eval("x + y", {"x": 10, "y": 5}) == 15

    def test_subtraction(self):
        """Test subtraction operator."""
        assert safe_eval("10 - 3") == 7
        assert safe_eval("a - b", {"a": 100, "b": 30}) == 70

    def test_multiplication(self):
        """Test multiplication operator."""
        assert safe_eval("4 * 5") == 20
        assert safe_eval("x * y", {"x": 7, "y": 8}) == 56

    def test_division(self):
        """Test division operators."""
        assert safe_eval("10 / 2") == 5.0
        assert safe_eval("10 // 3") == 3  # floor division

    def test_modulo(self):
        """Test modulo operator."""
        assert safe_eval("17 % 5") == 2
        assert safe_eval("x % y", {"x": 10, "y": 3}) == 1

    def test_power(self):
        """Test power operator."""
        assert safe_eval("2 ** 3") == 8
        assert safe_eval("base ** exp", {"base": 3, "exp": 4}) == 81

    def test_unary_operators(self):
        """Test unary negation and positive."""
        assert safe_eval("-5") == -5
        assert safe_eval("+5") == 5
        assert safe_eval("-x", {"x": 10}) == -10

    def test_bitwise_operators(self):
        """Test bitwise operations."""
        assert safe_eval("5 | 3") == 7  # OR
        assert safe_eval("5 & 3") == 1  # AND
        assert safe_eval("5 ^ 3") == 6  # XOR
        assert safe_eval("8 >> 2") == 2  # right shift
        assert safe_eval("2 << 3") == 16  # left shift

    def test_complex_arithmetic(self):
        """Test complex arithmetic expressions."""
        assert safe_eval("(2 + 3) * 4") == 20
        assert safe_eval("2 + 3 * 4") == 14  # operator precedence
        assert safe_eval("(a + b) * (c - d)", {"a": 1, "b": 2, "c": 5, "d": 3}) == 6


class TestComparisonOperations:
    """Tests for comparison operators."""

    def test_equality(self):
        """Test equality operators."""
        assert safe_eval("5 == 5") is True
        assert safe_eval("5 != 3") is True
        assert safe_eval("x == y", {"x": 10, "y": 10}) is True

    def test_ordering(self):
        """Test ordering operators."""
        assert safe_eval("5 > 3") is True
        assert safe_eval("5 < 3") is False
        assert safe_eval("5 >= 5") is True
        assert safe_eval("5 <= 5") is True

    def test_identity(self):
        """Test identity operators."""
        assert safe_eval("None is None") is True
        assert safe_eval("x is not None", {"x": 5}) is True

    def test_membership(self):
        """Test membership operators."""
        assert safe_eval("'a' in items", {"items": ["a", "b", "c"]}) is True
        assert safe_eval("'x' not in items", {"items": ["a", "b", "c"]}) is True
        assert safe_eval("key in data", {"key": "name", "data": {"name": "test"}}) is True

    def test_chained_comparisons(self):
        """Test chained comparison operators."""
        assert safe_eval("1 < 2 < 3") is True
        assert safe_eval("1 < 2 > 3") is False
        assert safe_eval("a < b < c", {"a": 1, "b": 5, "c": 10}) is True


class TestBooleanOperations:
    """Tests for boolean operations."""

    def test_and_operator(self):
        """Test logical AND."""
        assert safe_eval("True and True") is True
        assert safe_eval("True and False") is False
        assert safe_eval("x and y", {"x": True, "y": True}) is True

    def test_or_operator(self):
        """Test logical OR."""
        assert safe_eval("True or False") is True
        assert safe_eval("False or False") is False
        assert safe_eval("x or y", {"x": False, "y": True}) is True

    def test_not_operator(self):
        """Test logical NOT."""
        assert safe_eval("not True") is False
        assert safe_eval("not False") is True
        assert safe_eval("not x", {"x": False}) is True

    def test_complex_boolean(self):
        """Test complex boolean expressions."""
        assert safe_eval("(True and False) or True") is True
        assert safe_eval("not (x and y)", {"x": True, "y": False}) is True


class TestDataStructures:
    """Tests for data structure operations."""

    def test_list_literals(self):
        """Test list literal creation."""
        assert safe_eval("[1, 2, 3]") == [1, 2, 3]
        assert safe_eval("[x, y]", {"x": 1, "y": 2}) == [1, 2]

    def test_tuple_literals(self):
        """Test tuple literal creation."""
        assert safe_eval("(1, 2, 3)") == (1, 2, 3)

    def test_dict_literals(self):
        """Test dict literal creation."""
        assert safe_eval("{'a': 1, 'b': 2}") == {"a": 1, "b": 2}

    def test_subscript_access(self):
        """Test subscript access for lists and dicts."""
        assert safe_eval("items[0]", {"items": [10, 20, 30]}) == 10
        assert safe_eval("data['key']", {"data": {"key": "value"}}) == "value"
        assert safe_eval("items[-1]", {"items": [1, 2, 3]}) == 3

    def test_nested_access(self):
        """Test nested data structure access."""
        data = {"outer": {"inner": [1, 2, 3]}}
        assert safe_eval("data['outer']['inner'][1]", {"data": data}) == 2


class TestSafeFunctions:
    """Tests for whitelisted safe functions."""

    def test_len_function(self):
        """Test len() function."""
        assert safe_eval("len(items)", {"items": [1, 2, 3]}) == 3
        assert safe_eval("len('hello')") == 5

    def test_type_conversion(self):
        """Test type conversion functions."""
        assert safe_eval("int('42')") == 42
        assert safe_eval("float('3.14')") == 3.14
        assert safe_eval("str(42)") == "42"
        assert safe_eval("bool(1)") is True

    def test_collection_functions(self):
        """Test collection creation functions."""
        assert safe_eval("list((1, 2, 3))") == [1, 2, 3]
        assert safe_eval("tuple([1, 2, 3])") == (1, 2, 3)
        assert safe_eval("set([1, 2, 2, 3])") == {1, 2, 3}

    def test_math_functions(self):
        """Test math-related functions."""
        assert safe_eval("min(1, 2, 3)") == 1
        assert safe_eval("max(1, 2, 3)") == 3
        assert safe_eval("sum([1, 2, 3])") == 6
        assert safe_eval("abs(-5)") == 5
        assert safe_eval("round(3.7)") == 4

    def test_any_all_functions(self):
        """Test any() and all() functions."""
        assert safe_eval("any([False, True, False])") is True
        assert safe_eval("all([True, True, True])") is True
        assert safe_eval("all([True, False, True])") is False


class TestSafeMethodCalls:
    """Tests for safe method calls on objects."""

    def test_dict_get_method(self):
        """Test dict.get() method."""
        assert safe_eval("data.get('key')", {"data": {"key": "value"}}) == "value"
        assert safe_eval("data.get('missing')", {"data": {}}) is None
        assert safe_eval("data.get('missing', 'default')", {"data": {}}) == "default"

    def test_dict_keys_values_items(self):
        """Test dict.keys(), values(), items() methods."""
        data = {"a": 1, "b": 2}
        assert list(safe_eval("data.keys()", {"data": data})) == ["a", "b"]
        assert list(safe_eval("data.values()", {"data": data})) == [1, 2]

    def test_string_methods(self):
        """Test string methods."""
        assert safe_eval("text.lower()", {"text": "HELLO"}) == "hello"
        assert safe_eval("text.upper()", {"text": "hello"}) == "HELLO"
        assert safe_eval("text.strip()", {"text": "  hello  "}) == "hello"
        assert safe_eval("text.split(',')", {"text": "a,b,c"}) == ["a", "b", "c"]


class TestTernaryExpressions:
    """Tests for ternary (if-else) expressions."""

    def test_ternary_true(self):
        """Test ternary expression when condition is true."""
        assert safe_eval("'yes' if True else 'no'") == "yes"
        assert safe_eval("x if x > 0 else -x", {"x": 5}) == 5

    def test_ternary_false(self):
        """Test ternary expression when condition is false."""
        assert safe_eval("'yes' if False else 'no'") == "no"
        assert safe_eval("x if x > 0 else -x", {"x": -5}) == 5


class TestSecurityEnforcement:
    """Tests for security enforcement - blocking dangerous operations."""

    def test_block_import(self):
        """Test that import statements are blocked."""
        # __import__ is not defined in the safe context, so it raises NameError
        # This is the correct security behavior - blocking by not exposing dangerous builtins
        with pytest.raises(NameError, match="not defined"):
            safe_eval("__import__('os')")

    def test_block_private_attributes(self):
        """Test that private attribute access is blocked."""
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("obj.__class__", {"obj": []})
        
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("obj._private", {"obj": type("Obj", (), {"_private": "secret"})()})

    def test_block_dunder_access(self):
        """Test that dunder attribute access is blocked."""
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("obj.__dict__", {"obj": {}})
        
        with pytest.raises(ValueError, match="private attribute"):
            safe_eval("obj.__bases__", {"obj": object})

    def test_block_unsafe_functions(self):
        """Test that unsafe function calls are blocked."""
        with pytest.raises((ValueError, NameError)):
            safe_eval("eval('1+1')")
        
        with pytest.raises((ValueError, NameError)):
            safe_eval("exec('x=1')")
        
        with pytest.raises((ValueError, NameError)):
            safe_eval("compile('x=1', '', 'exec')")

    def test_block_unsafe_methods(self):
        """Test that unsafe method calls are blocked."""
        # Trying to call arbitrary methods should fail
        with pytest.raises(ValueError, match="not allowed"):
            safe_eval("''.format_map({})")

    def test_block_lambda(self):
        """Test that lambda expressions are blocked."""
        with pytest.raises(ValueError, match="not allowed"):
            safe_eval("(lambda x: x)(5)")

    def test_block_comprehensions(self):
        """Test that list/dict comprehensions are blocked."""
        with pytest.raises(ValueError, match="not allowed"):
            safe_eval("[x for x in range(10)]")
        
        with pytest.raises(ValueError, match="not allowed"):
            safe_eval("{x: x for x in range(10)}")

    def test_block_generators(self):
        """Test that generator expressions are blocked."""
        with pytest.raises(ValueError, match="not allowed"):
            safe_eval("(x for x in range(10))")


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_expression(self):
        """Test handling of empty expressions."""
        with pytest.raises(SyntaxError):
            safe_eval("")

    def test_whitespace_only(self):
        """Test handling of whitespace-only expressions."""
        with pytest.raises(SyntaxError):
            safe_eval("   ")

    def test_undefined_variable(self):
        """Test access to undefined variables."""
        with pytest.raises(NameError, match="not defined"):
            safe_eval("undefined_var")

    def test_none_context(self):
        """Test with None context (should use empty dict)."""
        assert safe_eval("5 + 3", None) == 8

    def test_none_values(self):
        """Test operations with None values."""
        assert safe_eval("x is None", {"x": None}) is True
        assert safe_eval("x is not None", {"x": 5}) is True

    def test_invalid_syntax(self):
        """Test invalid Python syntax."""
        with pytest.raises(SyntaxError):
            safe_eval("5 +")
        
        with pytest.raises(SyntaxError):
            safe_eval("if True:")

    def test_type_mismatch(self):
        """Test operations with mismatched types."""
        with pytest.raises(TypeError):
            safe_eval("'string' + 5")

    def test_division_by_zero(self):
        """Test division by zero."""
        with pytest.raises(ZeroDivisionError):
            safe_eval("10 / 0")

    def test_index_out_of_range(self):
        """Test index out of range."""
        with pytest.raises(IndexError):
            safe_eval("items[10]", {"items": [1, 2, 3]})

    def test_key_not_found(self):
        """Test key not found in dict access."""
        with pytest.raises(KeyError):
            safe_eval("data['missing']", {"data": {}})


class TestContextVariables:
    """Tests for context variable handling."""

    def test_safe_functions_take_precedence(self):
        """Test that safe functions cannot be overridden by context."""
        # SAFE_FUNCTIONS take precedence over context to prevent security bypass
        # This is intentional security behavior - users cannot override len/str etc
        result = safe_eval("len([1, 2, 3])", {"len": 42})
        assert result == 3  # Uses real len, not the context value

    def test_nested_context(self):
        """Test with deeply nested context data."""
        context = {
            "level1": {
                "level2": {
                    "level3": {"value": "deep"}
                }
            }
        }
        assert safe_eval("level1['level2']['level3']['value']", context) == "deep"

    def test_list_of_dicts(self):
        """Test access to list of dicts."""
        data = [{"name": "Alice"}, {"name": "Bob"}]
        assert safe_eval("items[0]['name']", {"items": data}) == "Alice"

    def test_boolean_context_values(self):
        """Test boolean values in context."""
        assert safe_eval("success and enabled", {"success": True, "enabled": True}) is True
        assert safe_eval("success and enabled", {"success": True, "enabled": False}) is False


class TestRealWorldExpressions:
    """Tests for real-world expression patterns used in the framework."""

    def test_output_confidence_check(self):
        """Test the pattern used in edge conditions."""
        output = {"confidence": 0.85}
        assert safe_eval("output['confidence'] > 0.8", {"output": output}) is True
        assert safe_eval("output.get('confidence', 0) > 0.8", {"output": output}) is True

    def test_result_success_check(self):
        """Test checking result success status."""
        result = {"success": True, "data": "test"}
        assert safe_eval("result.get('success') == True", {"result": result}) is True

    def test_memory_key_check(self):
        """Test checking for keys in memory."""
        memory = {"user_id": "123", "session": "active"}
        assert safe_eval("'user_id' in memory", {"memory": memory}) is True
        assert safe_eval("memory.get('user_id') is not None", {"memory": memory}) is True

    def test_conditional_routing_expression(self):
        """Test expressions commonly used in graph edge conditions."""
        context = {
            "output": {"status": "complete", "count": 5},
            "memory": {"threshold": 3}
        }
        assert safe_eval(
            "output['status'] == 'complete' and output['count'] > memory['threshold']",
            context
        ) is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
