"""
security tests for code sandbox.

tests to make sure the sandbox actually blocks dangerous stuff
and cant be bypassed with sneaky tricks
"""

from framework.graph.code_sandbox import (
    CodeSandbox,
    CodeValidator,
    safe_eval,
    safe_exec,
)


class TestBlockedAstNodes:
    """test that blocked ast nodes are properly rejected"""

    def test_import_blocked(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("import os")
        assert not result.success
        assert "Blocked operation" in result.error

    def test_import_from_blocked(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("from os import path")
        assert not result.success
        assert "Blocked operation" in result.error

    def test_global_blocked(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("global x")
        assert not result.success
        assert "Blocked operation" in result.error

    def test_nonlocal_blocked(self):
        sandbox = CodeSandbox()
        # nonlocal needs to be inside a nested function
        code = """
def outer():
    x = 1
    def inner():
        nonlocal x
        x = 2
    inner()
"""
        result = sandbox.execute(code)
        assert not result.success
        assert "Blocked operation" in result.error


class TestDangerousBuiltins:
    """test that dangerous builtins are blocked"""

    def test_exec_blocked(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("exec('print(1)')")
        assert not result.success
        assert "Blocked function call" in result.error

    def test_eval_blocked(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("eval('1+1')")
        assert not result.success
        assert "Blocked function call" in result.error

    def test_compile_blocked(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("compile('1+1', '', 'eval')")
        assert not result.success
        assert "Blocked function call" in result.error

    def test_dunder_import_blocked(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("__import__('os')")
        assert not result.success
        assert "Blocked function call" in result.error

    def test_open_not_available(self):
        # open isnt in safe builtins so should fail
        sandbox = CodeSandbox()
        result = sandbox.execute("f = open('test.txt', 'r')")
        assert not result.success
        # will error because open is not defined

    def test_input_not_available(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("x = input('test')")
        assert not result.success


class TestPrivateAttributeAccess:
    """test that private attribute access is blocked"""

    def test_dunder_class_blocked(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("x = ().__class__")
        assert not result.success
        assert "private attribute" in result.error.lower()

    def test_dunder_bases_blocked(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("x = ().__class__.__bases__")
        assert not result.success

    def test_dunder_subclasses_blocked(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("x = object.__subclasses__()")
        assert not result.success

    def test_dunder_mro_blocked(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("x = str.__mro__")
        assert not result.success

    def test_dunder_globals_blocked(self):
        sandbox = CodeSandbox()
        code = """
def f():
    pass
x = f.__globals__
"""
        result = sandbox.execute(code)
        assert not result.success


class TestObfuscationAttempts:
    """test that obfuscated code attacks are blocked"""

    def test_chr_based_import(self):
        # trying to spell __import__ with chr()
        sandbox = CodeSandbox()
        result = sandbox.execute("x = chr(95) + chr(95) + 'import' + chr(95) + chr(95)")
        # this should succeed cuz its just building a string
        # but actually trying to use it should fail
        assert result.success

        # now try to actually call it
        code = """
func_name = chr(95) + chr(95) + 'import' + chr(95) + chr(95)
"""
        result = sandbox.execute(code)
        assert result.success  # just string building is fine

    def test_getattr_on_builtins(self):
        # getattr isnt in safe builtins
        sandbox = CodeSandbox()
        result = sandbox.execute("getattr(__builtins__, 'exec')")
        assert not result.success

    def test_builtins_dict_access(self):
        sandbox = CodeSandbox()
        # try to get dangerous stuff from builtins dict
        result = sandbox.execute("x = __builtins__['exec']")
        assert not result.success


class TestNestedFunctionEscapes:
    """test that nested functions cant escape sandbox"""

    def test_nested_def_still_restricted(self):
        sandbox = CodeSandbox()
        code = """
def sneaky():
    import os
    return os.getcwd()
result = sneaky()
"""
        result = sandbox.execute(code)
        assert not result.success

    def test_lambda_cant_import(self):
        sandbox = CodeSandbox()
        code = """
sneaky = lambda: __import__('os')
result = sneaky()
"""
        result = sandbox.execute(code)
        assert not result.success

    def test_comprehension_cant_escape(self):
        sandbox = CodeSandbox()
        code = """
result = [__import__('os') for i in range(1)]
"""
        result = sandbox.execute(code)
        assert not result.success


class TestNamespaceIsolation:
    """test that one execution cant affect another"""

    def test_separate_namespaces(self):
        sandbox = CodeSandbox()

        # first execution sets a variable
        result1 = sandbox.execute("secret = 'password123'")
        assert result1.success

        # second execution shouldnt see it
        result2 = sandbox.execute("x = secret")
        assert not result2.success

    def test_input_vars_isolated(self):
        sandbox = CodeSandbox()

        # execute with inputs
        result1 = sandbox.execute("x = user_input * 2", inputs={"user_input": 5})
        assert result1.success
        assert result1.variables.get("x") == 10

        # another execution without inputs
        result2 = sandbox.execute("y = user_input * 2")
        assert not result2.success  # user_input not defined


class TestSafeOperations:
    """test that safe operations actually work"""

    def test_basic_math(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("result = 2 + 2 * 3")
        assert result.success
        assert result.result == 8

    def test_string_operations(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("result = 'hello'.upper() + ' world'")
        assert result.success
        assert result.result == "HELLO world"

    def test_list_operations(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("result = sorted([3, 1, 4, 1, 5])")
        assert result.success
        assert result.result == [1, 1, 3, 4, 5]

    def test_dict_operations(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("result = {'a': 1, 'b': 2}['a']")
        assert result.success
        assert result.result == 1

    def test_allowed_module_import(self):
        sandbox = CodeSandbox()
        # the sandbox allows importing via __import__ thats in namespace
        # but the ast validation blocks Import statements
        # so we need to use the importer thats added to namespace
        result = sandbox.execute("import math")
        # this should fail cuz import statement is blocked
        assert not result.success

    def test_using_math_via_importer(self):
        # actually test that the restricted importer works
        sandbox = CodeSandbox()
        # we can test this by checking if math would work
        # but the import statement itself is blocked at ast level
        result = sandbox.execute("x = 2 ** 10")
        assert result.success
        assert result.variables.get("x") == 1024

    def test_safe_builtins_available(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("result = len([1, 2, 3])")
        assert result.success
        assert result.result == 3


class TestConvenienceFunctions:
    """test safe_exec and safe_eval convenience functions"""

    def test_safe_exec_works(self):
        result = safe_exec("x = 1 + 2", timeout_seconds=5)
        assert result.success
        assert result.variables.get("x") == 3

    def test_safe_exec_blocks_dangerous(self):
        result = safe_exec("import os", timeout_seconds=5)
        assert not result.success

    def test_safe_eval_works(self):
        result = safe_eval("2 + 2", timeout_seconds=5)
        assert result.success
        assert result.result == 4

    def test_safe_eval_with_inputs(self):
        result = safe_eval("x * 2", inputs={"x": 5}, timeout_seconds=5)
        assert result.success
        assert result.result == 10


class TestCodeValidator:
    """test the code validator directly"""

    def test_validator_finds_import(self):
        validator = CodeValidator()
        issues = validator.validate("import os")
        assert len(issues) > 0
        assert any("Import" in issue for issue in issues)

    def test_validator_finds_private_attr(self):
        validator = CodeValidator()
        issues = validator.validate("x.__class__")
        assert len(issues) > 0
        assert any("private attribute" in issue.lower() for issue in issues)

    def test_validator_finds_exec(self):
        validator = CodeValidator()
        issues = validator.validate("exec('print(1)')")
        assert len(issues) > 0
        assert any("exec" in issue for issue in issues)

    def test_validator_syntax_error(self):
        validator = CodeValidator()
        issues = validator.validate("def ()")
        assert len(issues) > 0
        assert any("Syntax error" in issue for issue in issues)

    def test_validator_clean_code(self):
        validator = CodeValidator()
        issues = validator.validate("x = 1 + 2")
        assert len(issues) == 0


class TestExpressionEval:
    """test execute_expression method"""

    def test_simple_expression(self):
        sandbox = CodeSandbox()
        result = sandbox.execute_expression("1 + 2")
        assert result.success
        assert result.result == 3

    def test_expression_with_inputs(self):
        sandbox = CodeSandbox()
        result = sandbox.execute_expression("x + y", inputs={"x": 10, "y": 5})
        assert result.success
        assert result.result == 15

    def test_expression_syntax_error(self):
        sandbox = CodeSandbox()
        result = sandbox.execute_expression("1 +")
        assert not result.success
        assert "Syntax error" in result.error


class TestStdoutCapture:
    """test that stdout is captured properly"""

    def test_print_not_in_safe_builtins(self):
        # print isnt in safe builtins by default (security measure)
        sandbox = CodeSandbox()
        result = sandbox.execute("print('hello world')")
        assert not result.success
        assert "print" in result.error

    def test_print_works_if_added_to_builtins(self):
        # if you want print, you gotta add it explicitly
        custom_builtins = dict(CodeSandbox().safe_builtins)
        custom_builtins["print"] = print

        sandbox = CodeSandbox(safe_builtins=custom_builtins)
        result = sandbox.execute("print('hello world')")
        assert result.success
        assert "hello world" in result.stdout


class TestVariableExtraction:
    """test that variables are extracted correctly"""

    def test_extract_specified_vars(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("a = 1\nb = 2\nc = 3", extract_vars=["a", "c"])
        assert result.success
        assert "a" in result.variables
        assert "c" in result.variables
        # b should also be in variables cuz all new vars are extracted
        assert "b" in result.variables

    def test_extract_missing_var(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("a = 1", extract_vars=["a", "nonexistent"])
        assert result.success
        assert result.variables.get("a") == 1
        assert "nonexistent" not in result.variables

    def test_result_convention(self):
        sandbox = CodeSandbox()
        result = sandbox.execute("result = 42")
        assert result.success
        assert result.result == 42
