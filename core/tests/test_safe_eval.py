import pytest

from framework.graph.safe_eval import safe_eval


def test_safe_eval_basic_operations():
    assert safe_eval("1 + 2") == 3
    assert safe_eval("10 / 2") == 5.0
    assert safe_eval("2 ** 3") == 8
    assert safe_eval("10 > 5 and True") is True
    assert safe_eval("5 if 10 > 5 else 0") == 5


def test_safe_eval_context():
    assert safe_eval("x + y", {"x": 10, "y": 20}) == 30

    # Custom objects should be BLOCKED from attribute access
    class CustomObj:
        def __init__(self):
            self.name = "test"

    with pytest.raises(
        ValueError, match="Attribute access is only allowed on basic types"
    ):
        safe_eval("obj.name", {"obj": CustomObj()})


def test_safe_eval_allowed_functions():
    assert safe_eval("len([1, 2, 3])") == 3
    assert safe_eval("int('42')") == 42
    assert safe_eval("str(123)") == "123"


def test_safe_eval_attribute_whitelist():
    # Allowed: basic types
    assert safe_eval("'abc'.upper()") == "ABC"

    # Blocked: dunder attributes even on basic types
    with pytest.raises(ValueError, match="Access to private attribute"):
        safe_eval("[1, 2].__len__")


def test_safe_eval_blocked_attributes():
    # Blocked: private/dunder
    with pytest.raises(ValueError, match="Access to private attribute"):
        safe_eval("''.__class__")


def test_safe_eval_malicious_blocked():
    # Blocked: built-ins not in whitelist (raises NameError because they aren't in context)
    with pytest.raises(NameError):
        safe_eval("eval('1+1')")

    with pytest.raises(NameError):
        safe_eval("open('/etc/passwd')")


def test_safe_eval_bytes_frozenset():
    # Verify my additions
    assert safe_eval("bytes([65, 66, 67])") == b"ABC"
    assert isinstance(safe_eval("frozenset([1, 2])"), frozenset)


def test_safe_eval_method_whitelist():
    # Allowed methods on strings
    assert safe_eval("'  abc  '.strip()") == "abc"
    assert safe_eval("'a,b,c'.split(',')") == ["a", "b", "c"]

    # Blocked methods (even if they exist on basic types)
    # E.g. list.append (it's not in the whitelist in visit_Call)
    with pytest.raises(ValueError, match="Call to function/method is not allowed"):
        safe_eval("[].append(1)")


def test_safe_eval_blocked_names():
    # Blocked: names starting with underscore
    with pytest.raises(ValueError, match="Access to private name"):
        safe_eval("__builtins__")

    with pytest.raises(ValueError, match="Access to private name"):
        safe_eval("_private_var", {"_private_var": 123})
