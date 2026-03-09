import ast
import operator
from typing import Any

# Limits to prevent resource exhaustion via crafted expressions
MAX_EXPONENT = 100  # cap for ** operator
MAX_REPEAT = 10_000  # cap for string/list repetition with *


def _safe_pow(base: Any, exp: Any) -> Any:
    """Bounded power operator to prevent DoS via huge exponents."""
    if isinstance(exp, (int, float)) and abs(exp) > MAX_EXPONENT:
        raise ValueError(
            f"Exponent {exp} exceeds maximum allowed ({MAX_EXPONENT})"
        )
    return operator.pow(base, exp)


def _safe_mult(a: Any, b: Any) -> Any:
    """Bounded multiplication that prevents huge string/list repetitions."""
    if isinstance(a, (str, list, tuple, bytes)) and isinstance(b, int):
        if b > MAX_REPEAT:
            raise ValueError(
                f"Repeat count {b} exceeds maximum allowed ({MAX_REPEAT})"
            )
    elif isinstance(b, (str, list, tuple, bytes)) and isinstance(a, int):
        if a > MAX_REPEAT:
            raise ValueError(
                f"Repeat count {a} exceeds maximum allowed ({MAX_REPEAT})"
            )
    return operator.mul(a, b)


# Safe operators whitelist
SAFE_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: _safe_mult,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: _safe_pow,
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
}

# Method whitelist with allowed receiver types.
# Only these (method, type) combinations are auto-approved.
SAFE_METHODS: dict[str, tuple[type, ...]] = {
    "get": (dict,),
    "keys": (dict,),
    "values": (dict,),
    "items": (dict,),
    "lower": (str,),
    "upper": (str,),
    "strip": (str,),
    "split": (str,),
}


class SafeEvalVisitor(ast.NodeVisitor):
    MAX_DEPTH = 50  # prevent stack overflow from deeply nested expressions

    def __init__(self, context: dict[str, Any]):
        self.context = context
        self._depth = 0

    def visit(self, node: ast.AST) -> Any:
        self._depth += 1
        if self._depth > self.MAX_DEPTH:
            raise ValueError(
                f"Expression nesting depth exceeds limit ({self.MAX_DEPTH})"
            )
        try:
            method = "visit_" + node.__class__.__name__
            visitor = getattr(self, method, self.generic_visit)
            return visitor(node)
        finally:
            self._depth -= 1

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
        # Lazy evaluation matching Python short-circuit semantics.
        # `x and y` returns x if x is falsy, otherwise y.
        # `x or y` returns x if x is truthy, otherwise y.
        if isinstance(node.op, ast.And):
            result: Any = True
            for v in node.values:
                result = self.visit(v)
                if not result:
                    return result
            return result
        elif isinstance(node.op, ast.Or):
            result = False
            for v in node.values:
                result = self.visit(v)
                if result:
                    return result
            return result
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

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        # value.attr
        # STRICT CHECK: No access to private attributes (starting with _)
        if node.attr.startswith("_"):
            raise ValueError(f"Access to private attribute '{node.attr}' is not allowed")

        val = self.visit(node.value)

        # Safe attribute access: only allow if it's in the dict (if val is dict)
        # or it's a safe property of a basic type?
        # Actually, for flexibility, people often use dot access for dicts in these expressions.
        # But standard Python dict doesn't support dot access.
        # If val is a dict, Attribute access usually fails in Python unless wrapped.
        # If the user context provides objects, we might want to allow attribute access.
        # BUT we must be careful not to allow access to dangerous things like __class__ etc.
        # The check starts_with("_") covers __class__, __init__, etc.

        try:
            return getattr(val, node.attr)
        except AttributeError:
            # Fallback: maybe it's a dict and they want dot access?
            # (Only if we want to support that sugar, usually not standard python)
            # Let's stick to standard python behavior + strict private check.
            pass

        raise AttributeError(f"Object has no attribute '{node.attr}'")

    def visit_Call(self, node: ast.Call) -> Any:
        # Only allow calling whitelisted functions or type-checked methods.

        is_safe = False

        if isinstance(node.func, ast.Name):
            if node.func.id in SAFE_FUNCTIONS:
                is_safe = True

        if isinstance(node.func, ast.Attribute):
            method_name = node.func.attr
            allowed_types = SAFE_METHODS.get(method_name)
            if allowed_types:
                # Evaluate the receiver and check its type before approving
                receiver = self.visit(node.func.value)
                if isinstance(receiver, allowed_types):
                    is_safe = True
                    # Build the bound method directly so we don't re-visit
                    func = getattr(receiver, method_name)
                    args = [self.visit(arg) for arg in node.args]
                    keywords = {kw.arg: self.visit(kw.value) for kw in node.keywords}
                    return func(*args, **keywords)

        func = self.visit(node.func)

        if not is_safe and func not in SAFE_FUNCTIONS.values():
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
