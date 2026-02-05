import ast
import operator
import math
from typing import Any

# Safe operators whitelist
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.LShift: operator.lshift,
    ast.RShift: operator.rshift,
    ast.BitOr: operator.or_,
    ast.BitXor: operator.xor,
    ast.BitAnd: operator.and_,
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
    ast.In: lambda x, y: x in y,
    ast.NotIn: lambda x, y: x not in y,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
    ast.Not: operator.not_,
    ast.Invert: operator.inv,
}

# Safe functions whitelist
SAFE_FUNCTIONS = {
    "len": len,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "tuple": tuple,
    "set": set,
    "min": min,
    "max": max,
    "sum": sum,
    "abs": abs,
    "round": round,
    "all": all,
    "any": any,
    "range": range,
    "enumerate": enumerate,
    "zip": zip,
    "reversed": reversed,
    "sorted": sorted,
    # Math functions
    "math": math,
    "sqrt": math.sqrt,
    "ceil": math.ceil,
    "floor": math.floor,
}

# Allowed methods whitelist
ALLOWED_METHODS = {
    # String methods
    "lower", "upper", "strip", "lstrip", "rstrip", "split", "rsplit",
    "replace", "join", "startswith", "endswith", "find", "rfind",
    "count", "index", "isdigit", "isalpha", "isalnum", "isspace",
    "title", "capitalize", "zfill", "center",

    # List/Tuple methods
    "append", "extend", "insert", "remove", "pop", "clear",
    "sort", "reverse", "copy",

    # Dict methods
    "get", "keys", "values", "items",

    # Set methods
    "union", "intersection", "difference", "symmetric_difference", "issubset", "issuperset",
}


class SafeEvalVisitor(ast.NodeVisitor):
    def __init__(self, context: dict[str, Any]):
        self.context = context

    def visit(self, node: ast.AST) -> Any:
        # Override visit to prevent default behavior and ensure only explicitly allowed nodes work
        method = "visit_" + node.__class__.__name__
        visitor = getattr(self, method, self.generic_visit)
        return visitor(node)

    def generic_visit(self, node: ast.AST):
        raise ValueError(f"Use of {node.__class__.__name__} is not allowed")

    def visit_Expression(self, node: ast.Expression) -> Any:
        return self.visit(node.body)

    def visit_Expr(self, node: ast.Expr) -> Any:
        return self.visit(node.value)

    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    # --- Data Structures ---
    def visit_List(self, node: ast.List) -> list:
        return [self.visit(elt) for elt in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> tuple:
        return tuple(self.visit(elt) for elt in node.elts)

    def visit_Dict(self, node: ast.Dict) -> dict:
        return {
            self.visit(k): self.visit(v)
            for k, v in zip(node.keys, node.values, strict=False)
            if k is not None
        }

    def visit_Set(self, node: ast.Set) -> set:
        return {self.visit(elt) for elt in node.elts}

    # --- Comprehensions ---
    def visit_ListComp(self, node: ast.ListComp) -> list:
        return self._execute_comprehension(node.elt, node.generators, list)

    def visit_SetComp(self, node: ast.SetComp) -> set:
        return self._execute_comprehension(node.elt, node.generators, set)

    def visit_DictComp(self, node: ast.DictComp) -> dict:
        return self._execute_dict_comprehension(node.key, node.value, node.generators)

    def _execute_comprehension(self, elt, generators, container_type):
        results = []

        def recurse(gens, current_context):
            if not gens:
                old_context = self.context
                self.context = current_context
                try:
                    val = self.visit(elt)
                    results.append(val)
                finally:
                    self.context = old_context
                return

            gen = gens[0]
            remaining = gens[1:]

            old_context = self.context
            self.context = current_context
            try:
                iter_val = self.visit(gen.iter)
            finally:
                self.context = old_context

            if not hasattr(iter_val, '__iter__'):
                 raise ValueError(f"Object {type(iter_val)} is not iterable")

            for item in iter_val:
                new_context = current_context.copy()
                self._assign(gen.target, item, new_context)

                include = True
                self.context = new_context
                try:
                    for if_expr in gen.ifs:
                        if not self.visit(if_expr):
                            include = False
                            break
                finally:
                     pass

                if include:
                    recurse(remaining, new_context)

        recurse(generators, self.context)

        if container_type is list:
            return results
        elif container_type is set:
            return set(results)
        return results

    def _execute_dict_comprehension(self, key_node, value_node, generators):
        results = {}

        def recurse(gens, current_context):
            if not gens:
                old_context = self.context
                self.context = current_context
                try:
                    k = self.visit(key_node)
                    v = self.visit(value_node)
                    results[k] = v
                finally:
                    self.context = old_context
                return

            gen = gens[0]
            remaining = gens[1:]

            old_context = self.context
            self.context = current_context
            try:
                iter_val = self.visit(gen.iter)
            finally:
                self.context = old_context

            for item in iter_val:
                new_context = current_context.copy()
                self._assign(gen.target, item, new_context)

                include = True
                self.context = new_context
                try:
                    for if_expr in gen.ifs:
                        if not self.visit(if_expr):
                            include = False
                            break
                finally:
                    pass

                if include:
                    recurse(remaining, new_context)

        recurse(generators, self.context)
        return results

    def _assign(self, target, value, context):
        if isinstance(target, ast.Name):
            context[target.id] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            try:
                items = list(value)
            except TypeError:
                raise ValueError(f"Cannot unpack non-iterable {type(value)}")

            if len(target.elts) != len(items):
                raise ValueError(f"not enough values to unpack (expected {len(target.elts)}, got {len(items)})")

            for t, v in zip(target.elts, items):
                self._assign(t, v, context)
        else:
             raise ValueError("Unsupported assignment target in comprehension")

    # --- Operations ---
    def visit_BinOp(self, node: ast.BinOp) -> Any:
        op_func = SAFE_OPERATORS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Operator {type(node.op).__name__} is not allowed")
        return op_func(self.visit(node.left), self.visit(node.right))

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        op_func = SAFE_OPERATORS.get(type(node.op))
        if op_func is None:
            raise ValueError(f"Operator {type(node.op).__name__} is not allowed")
        return op_func(self.visit(node.operand))

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            op_func = SAFE_OPERATORS.get(type(op))
            if op_func is None:
                raise ValueError(f"Operator {type(op).__name__} is not allowed")
            right = self.visit(comparator)
            if not op_func(left, right):
                return False
            left = right  # Chain comparisons
        return True

    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        values = [self.visit(v) for v in node.values]
        if isinstance(node.op, ast.And):
            return all(values)
        elif isinstance(node.op, ast.Or):
            return any(values)
        raise ValueError(f"Boolean operator {type(node.op).__name__} is not allowed")

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        # Ternary: true_val if test else false_val
        if self.visit(node.test):
            return self.visit(node.body)
        else:
            return self.visit(node.orelse)

    # --- Variables and Attributes ---
    def visit_Name(self, node: ast.Name) -> Any:
        if isinstance(node.ctx, ast.Load):
            if node.id in self.context:
                return self.context[node.id]
            raise NameError(f"Name '{node.id}' is not defined")
        raise ValueError("Only reading variables is allowed")

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        # value[slice]
        val = self.visit(node.value)
        idx = self.visit(node.slice)
        return val[idx]

    def visit_Slice(self, node: ast.Slice) -> slice:
        lower = self.visit(node.lower) if node.lower else None
        upper = self.visit(node.upper) if node.upper else None
        step = self.visit(node.step) if node.step else None
        return slice(lower, upper, step)

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        # value.attr
        # STIRCT CHECK: No access to private attributes (starting with _)
        if node.attr.startswith("_"):
            raise ValueError(f"Access to private attribute '{node.attr}' is not allowed")

        val = self.visit(node.value)

        try:
            return getattr(val, node.attr)
        except AttributeError:
            pass

        raise AttributeError(f"Object has no attribute '{node.attr}'")

    def visit_Call(self, node: ast.Call) -> Any:
        # Only allow calling whitelisted functions
        func = self.visit(node.func)

        is_safe = False
        if isinstance(node.func, ast.Name):
            if node.func.id in SAFE_FUNCTIONS:
                is_safe = True

        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            if method_name in ALLOWED_METHODS:
                is_safe = True

        if not is_safe and func not in SAFE_FUNCTIONS.values():
             pass
        elif is_safe:
             pass
        else:
             if func in SAFE_FUNCTIONS.values():
                 is_safe = True

        if not is_safe:
            raise ValueError("Call to function/method is not allowed")

        args = [self.visit(arg) for arg in node.args]
        keywords = {kw.arg: self.visit(kw.value) for kw in node.keywords}

        return func(*args, **keywords)

    def visit_Index(self, node: ast.Index) -> Any:
        # Python < 3.9
        return self.visit(node.value)


def safe_eval(expr: str, context: dict[str, Any] | None = None) -> Any:
    """
    Safely evaluate a python expression string.

    Args:
        expr: The expression string to evaluate.
        context: Dictionary of variables available in the expression.

    Returns:
        The result of the evaluation.

    Raises:
        ValueError: If unsafe operations or syntax are detected.
        SyntaxError: If the expression is invalid Python.
    """
    if context is None:
        context = {}

    # Add safe builtins to context
    full_context = context.copy()
    full_context.update(SAFE_FUNCTIONS)

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise SyntaxError(f"Invalid syntax in expression: {e}") from e

    visitor = SafeEvalVisitor(full_context)
    return visitor.visit(tree)
