import pytest
import math
from framework.graph.safe_eval import safe_eval

def test_basic_types():
    assert safe_eval("1") == 1
    assert safe_eval("1.5") == 1.5
    assert safe_eval("'hello'") == "hello"
    assert safe_eval("True") is True
    assert safe_eval("False") is False
    assert safe_eval("None") is None
    assert safe_eval("[1, 2]") == [1, 2]
    assert safe_eval("{'a': 1}") == {'a': 1}
    assert safe_eval("{1, 2}") == {1, 2}

def test_arithmetic():
    assert safe_eval("1 + 2") == 3
    assert safe_eval("2 * 3") == 6
    assert safe_eval("10 / 2") == 5.0
    assert safe_eval("10 // 3") == 3
    assert safe_eval("10 % 3") == 1
    assert safe_eval("2 ** 3") == 8
    assert safe_eval("-(1)") == -1
    assert safe_eval("+(1)") == 1

def test_comparisons():
    assert safe_eval("1 < 2") is True
    assert safe_eval("1 > 2") is False
    assert safe_eval("1 <= 1") is True
    assert safe_eval("1 == 1") is True
    assert safe_eval("1 != 2") is True
    assert safe_eval("1 in [1, 2]") is True
    assert safe_eval("3 not in [1, 2]") is True

def test_logic():
    assert safe_eval("True and False") is False
    assert safe_eval("True or False") is True
    assert safe_eval("not True") is False
    assert safe_eval("True if True else False") is True

def test_context_access():
    ctx = {"x": 10, "y": 20}
    assert safe_eval("x + y", ctx) == 30
    assert safe_eval("x * 2", ctx) == 20

def test_string_methods():
    ctx = {"s": " Hello World "}
    assert safe_eval("s.lower()", ctx) == " hello world "
    assert safe_eval("s.strip()", ctx) == "Hello World"
    assert safe_eval("s.strip().split()", ctx) == ["Hello", "World"]
    assert safe_eval("s.replace('World', 'Universe')", ctx) == " Hello Universe "
    assert safe_eval("s.strip().startswith('He')", ctx) is True
    assert safe_eval("'a,b,c'.split(',')") == ['a', 'b', 'c']
    assert safe_eval("'-'.join(['a', 'b'])") == "a-b"
    assert safe_eval("'hello'.find('e')") == 1
    assert safe_eval("'hello'.count('l')") == 2
    assert safe_eval("'123'.isdigit()") is True

def test_list_operations():
    ctx = {"l": [1, 2, 3, 4, 5]}
    assert safe_eval("len(l)", ctx) == 5
    assert safe_eval("l[0]", ctx) == 1
    assert safe_eval("l[-1]", ctx) == 5
    assert safe_eval("l[1:3]", ctx) == [2, 3]
    assert safe_eval("l[:2]", ctx) == [1, 2]
    assert safe_eval("l[3:]", ctx) == [4, 5]
    assert safe_eval("l[::2]", ctx) == [1, 3, 5]
    assert safe_eval("sum(l)", ctx) == 15
    assert safe_eval("max(l)", ctx) == 5
    assert safe_eval("min(l)", ctx) == 1

    # Methods
    assert safe_eval("l.copy()", ctx) == [1, 2, 3, 4, 5]

    # Note: methods like pop modify the list.
    # safe_eval doesn't guarantee immutability of context objects if methods are allowed.
    # But usually context is passed by reference.
    l2 = [1, 2, 3]
    assert safe_eval("l.pop()", {"l": l2}) == 3
    assert l2 == [1, 2]

def test_list_comprehension():
    ctx = {"l": [1, 2, 3]}
    assert safe_eval("[x * 2 for x in l]", ctx) == [2, 4, 6]
    assert safe_eval("[x for x in l if x > 1]", ctx) == [2, 3]
    # Nested
    assert safe_eval("[x + y for x in [1, 2] for y in [10, 20]]") == [11, 21, 12, 22]
    # Unpacking
    assert safe_eval("[x + y for x, y in [[1, 2], [3, 4]]]") == [3, 7]
    # Using range
    assert safe_eval("[x**2 for x in range(3)]") == [0, 1, 4]

def test_dict_comprehension():
    ctx = {"l": [("a", 1), ("b", 2)]}
    assert safe_eval("{k: v * 2 for k, v in l}", ctx) == {"a": 2, "b": 4}
    assert safe_eval("{x: x**2 for x in range(3)}") == {0: 0, 1: 1, 2: 4}

def test_set_comprehension():
    assert safe_eval("{x % 2 for x in [1, 2, 3, 4, 5]}") == {0, 1}

def test_builtins_extras():
    assert safe_eval("list(range(3))") == [0, 1, 2]
    assert safe_eval("sorted([3, 1, 2])") == [1, 2, 3]
    assert safe_eval("dict(zip(['a', 'b'], [1, 2]))") == {'a': 1, 'b': 2}
    assert safe_eval("list(reversed([1, 2]))") == [2, 1]
    assert safe_eval("list(enumerate(['a', 'b']))") == [(0, 'a'), (1, 'b')]

def test_math_functions():
    assert safe_eval("math.sqrt(4)") == 2.0
    assert safe_eval("sqrt(9)") == 3.0
    assert safe_eval("floor(3.7)") == 3
    assert safe_eval("ceil(3.2)") == 4

def test_security_access_control():
    # 1. Access to private attributes
    with pytest.raises(ValueError, match="Access to private attribute"):
        safe_eval("''.__class__")

    # 2. Access to dangerous builtins not in whitelist
    with pytest.raises(NameError):
        safe_eval("eval('1+1')")

    with pytest.raises(NameError):
        safe_eval("__import__('os')")

    # 3. Method call on dangerous object (if somehow obtained)
    # It's hard to obtain a dangerous object without __import__ or __class__

    # 4. Calling disallowed method
    # format is not in whitelist
    with pytest.raises(ValueError, match="Call to function/method is not allowed"):
        safe_eval("'{}'.format(1)")

def test_assignment_unpacking_error():
    with pytest.raises(ValueError, match="not enough values to unpack"):
        safe_eval("[x for x, y in [[1]]]")

def test_missing_variable():
    with pytest.raises(NameError):
        safe_eval("unknown_var")
