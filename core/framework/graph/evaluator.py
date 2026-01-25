from typing import Any
import ast
import operator

class SafeEvaluator:
    """
    Secure AST-based expression evaluator for agent conditions.
    Allows basic types, operators, and whitelisted built-in functions.
    Strictly blocks arbitrary code execution and private attribute access.
    """
    
    # Supported operators
    OPERATORS = {
        ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
        ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
        ast.And: lambda x, y: x and y, ast.Or: lambda x, y: x or y,
        ast.Not: operator.not_, ast.In: lambda x, y: x in y,
        ast.NotIn: lambda x, y: x not in y, ast.Is: operator.is_,
        ast.IsNot: operator.is_not, ast.USub: operator.neg, ast.UAdd: operator.pos,
    }

    # Whitelisted built-in functions
    ALLOWED_FUNCTIONS = {
        "len": len, "int": int, "str": str, 
        "float": float, "bool": bool, "list": list, "dict": dict,
        "set": set, "min": min, "max": max,
        "abs": abs, "round": round, "sum": sum,
        "all": all, "any": any, "sorted": sorted,
        "reversed": reversed, "range": range,
        "zip": zip, "enumerate": enumerate
    }

    def evaluate(self, node: ast.AST, context: dict[str, Any]) -> Any:
        """Recursively evaluate an AST node in the given context."""
        method_name = f"_visit_{type(node).__name__}"
        visitor = getattr(self, method_name, self._generic_visit)
        return visitor(node, context)

    def _generic_visit(self, node: ast.AST, context: dict[str, Any]) -> Any:
        raise ValueError(f"Unsupported operation: {type(node).__name__}")

    def _visit_Expression(self, node: ast.Expression, context: dict[str, Any]) -> Any:
        return self.evaluate(node.body, context)

    def _visit_Constant(self, node: ast.Constant, context: dict[str, Any]) -> Any:
        return node.value

    def _visit_Name(self, node: ast.Name, context: dict[str, Any]) -> Any:
        if node.id in context:
            return context[node.id]
        raise NameError(f"Name '{node.id}' is not defined")

    def _visit_Subscript(self, node: ast.Subscript, context: dict[str, Any]) -> Any:
        value = self.evaluate(node.value, context)
        index = self.evaluate(node.slice, context)
        return value[index]

    def _visit_BinOp(self, node: ast.BinOp, context: dict[str, Any]) -> Any:
        op = self.OPERATORS.get(type(node.op))
        if not op:
            raise ValueError(f"Operator {type(node.op).__name__} not supported")
        return op(self.evaluate(node.left, context), self.evaluate(node.right, context))

    def _visit_UnaryOp(self, node: ast.UnaryOp, context: dict[str, Any]) -> Any:
        op = self.OPERATORS.get(type(node.op))
        if not op:
            raise ValueError(f"Operator {type(node.op).__name__} not supported")
        return op(self.evaluate(node.operand, context))

    def _visit_Compare(self, node: ast.Compare, context: dict[str, Any]) -> Any:
        left = self.evaluate(node.left, context)
        for op, right_node in zip(node.ops, node.comparators):
            op_func = self.OPERATORS.get(type(op))
            if not op_func:
                raise ValueError(f"Comparator {type(op).__name__} not supported")
            right = self.evaluate(right_node, context)
            if not op_func(left, right):
                return False
            left = right # For chained comparisons
        return True

    def _visit_BoolOp(self, node: ast.BoolOp, context: dict[str, Any]) -> Any:
        if isinstance(node.op, ast.And):
            return all(self.evaluate(v, context) for v in node.values)
        elif isinstance(node.op, ast.Or):
            return any(self.evaluate(v, context) for v in node.values)
        raise ValueError(f"Boolean operator {type(node.op).__name__} not supported")

    def _visit_Attribute(self, node: ast.Attribute, context: dict[str, Any]) -> Any:
        obj = self.evaluate(node.value, context)
        
        # Security Check: No private/magic attributes
        if node.attr.startswith("_"):
            raise ValueError(f"Private attribute '{node.attr}' is not allowed")
        
        return getattr(obj, node.attr)

    def _visit_Call(self, node: ast.Call, context: dict[str, Any]) -> Any:
        # Handle direct function calls: len(x)
        if isinstance(node.func, ast.Name):
            if node.func.id in self.ALLOWED_FUNCTIONS:
                func = self.ALLOWED_FUNCTIONS[node.func.id]
                args = [self.evaluate(arg, context) for arg in node.args]
                return func(*args)
            raise ValueError(f"Function '{node.func.id}' is not allowed in conditions")
        
        # Handle method calls: x.strip(), d.get()
        elif isinstance(node.func, ast.Attribute):
            obj = self.evaluate(node.func.value, context)
            method_name = node.func.attr
            
            # Security Check: No private/magic methods
            if method_name.startswith("_"):
                raise ValueError(f"Private method '{method_name}' is not allowed")
            
            method = getattr(obj, method_name, None)
            if not method:
                raise AttributeError(f"Object has no attribute '{method_name}'")
            
            args = [self.evaluate(arg, context) for arg in node.args]
            keywords = {kw.arg: self.evaluate(kw.value, context) for kw in node.keywords}
            return method(*args, **keywords)

        raise ValueError("Function call type not allowed")

    def _visit_List(self, node: ast.List, context: dict[str, Any]) -> Any:
        return [self.evaluate(elt, context) for elt in node.elts]

    def _visit_Dict(self, node: ast.Dict, context: dict[str, Any]) -> Any:
        return {self.evaluate(k, context): self.evaluate(v, context) for k, v in zip(node.keys, node.values)}

    def _visit_Set(self, node: ast.Set, context: dict[str, Any]) -> Any:
        return {self.evaluate(elt, context) for elt in node.elts}
