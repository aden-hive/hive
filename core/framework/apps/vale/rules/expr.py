"""The expression language of world rules: small, safe, and read like Python.

A world's rules are data (``rules.toml``), and the arithmetic inside them is written as
expressions: ``clamp(keep * prev.blight[dst] + (1 - keep) * carry * prev.blight[src])``.
They are parsed with ``ast`` and walked here; nothing is ever passed to ``eval``. Only
literals, names, arithmetic, comparisons, ``and``/``or``/``not``, ``x if c else y``, lists,
dicts, comprehensions, subscripts, dotted names and the functions in ``Scope.functions``
are allowed. Any other construct is refused when the rules are loaded.

Names resolve, in order, to: the step's local variables, the world's constants, the
special names (``day``, ``wave``, ``places``, ``villagers``, ``state``, ``prev``,
``overgod``, villager fields such as ``health``), and finally the hidden state itself.
A name, key or attribute that does not exist reads as 0, as in the world's conditions.
"""

from __future__ import annotations

import ast
import operator
from collections.abc import Callable
from functools import lru_cache
from typing import Any

_BIN: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}
_CMP: dict[type, Callable[[Any, Any], bool]] = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}
_ALLOWED = (
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.IfExp, ast.Compare, ast.Call, ast.Name, ast.Attribute,
    ast.Subscript, ast.Constant, ast.List, ast.Tuple, ast.Dict, ast.ListComp, ast.DictComp, ast.comprehension,
    ast.Load, ast.Store, ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd, ast.keyword, *_BIN, *_CMP,
)  # fmt: skip


class RuleError(ValueError):
    """A rule that cannot be read or run, with the offending source."""


@lru_cache(maxsize=4096)
def parse(source: str) -> ast.Expression:
    """Parse once, and refuse anything outside the language."""
    try:
        tree = ast.parse(str(source).strip(), mode="eval")
    except SyntaxError as exc:
        raise RuleError(f"cannot read the rule {source!r}: {exc.msg}") from None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED):
            raise RuleError(f"the rule {source!r} uses {type(node).__name__}, which world rules do not allow")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise RuleError(f"the rule {source!r} reaches for a private name")
        if isinstance(node, ast.Call) and not isinstance(node.func, ast.Name):
            raise RuleError(f"the rule {source!r} calls something that is not one of the rule functions")
    return tree


def _read(container: Any, key: Any) -> Any:
    if isinstance(container, dict):
        return container.get(key, 0)
    if hasattr(container, "read"):  # villager fields
        return container.read(key)
    return container[key]


class Scope:
    """Where an expression's names come from: locals, then constants, then the world."""

    def __init__(self, resolve: Callable[[str], Any], functions: dict[str, Callable[..., Any]], local: dict[str, Any] | None = None) -> None:
        self.resolve = resolve
        self.functions = functions
        self.vars: dict[str, Any] = dict(local or {})

    def child(self, **local: Any) -> Scope:
        """A scope for a loop's body: sees everything here, and its own loop variables."""
        sub = Scope(self.resolve, self.functions, self.vars)
        sub.vars.update(local)
        return sub

    def name(self, name: str) -> Any:
        if name in self.vars:
            return self.vars[name]
        if name in ("True", "true"):
            return True
        if name in ("False", "false"):
            return False
        if name in ("None", "none"):
            return None
        return self.resolve(name)

    # ------------------------------------------------------------------ reading

    def eval(self, source: Any) -> Any:
        """The value of an expression; numbers and booleans in TOML pass through as themselves."""
        if isinstance(source, bool | int | float) or source is None:
            return source
        return self._node(parse(str(source)).body)

    def _node(self, n: ast.AST) -> Any:
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Name):
            return self.name(n.id)
        if isinstance(n, ast.Attribute):
            return _read(self._node(n.value), n.attr)
        if isinstance(n, ast.Subscript):
            return _read(self._node(n.value), self._node(n.slice))
        if isinstance(n, ast.BinOp):
            return _BIN[type(n.op)](self._node(n.left), self._node(n.right))
        if isinstance(n, ast.UnaryOp):
            v = self._node(n.operand)
            return -v if isinstance(n.op, ast.USub) else +v if isinstance(n.op, ast.UAdd) else not v
        if isinstance(n, ast.BoolOp):  # short-circuits like Python: dice in a condition roll only when reached
            if isinstance(n.op, ast.And):
                v: Any = True
                for x in n.values:
                    v = self._node(x)
                    if not v:
                        return v
                return v
            v = False
            for x in n.values:
                v = self._node(x)
                if v:
                    return v
            return v
        if isinstance(n, ast.Compare):
            left = self._node(n.left)
            for op, right_node in zip(n.ops, n.comparators, strict=True):
                right = self._node(right_node)
                if not _CMP[type(op)](left, right):
                    return False
                left = right
            return True
        if isinstance(n, ast.IfExp):
            return self._node(n.body) if self._node(n.test) else self._node(n.orelse)
        if isinstance(n, ast.List | ast.Tuple):
            return [self._node(x) for x in n.elts]
        if isinstance(n, ast.Dict):
            return {self._node(k): self._node(v) for k, v in zip(n.keys, n.values, strict=True)}
        if isinstance(n, ast.ListComp):
            return [s._node(n.elt) for s in self._comprehend(n.generators)]
        if isinstance(n, ast.DictComp):
            return {s._node(n.key): s._node(n.value) for s in self._comprehend(n.generators)}
        if isinstance(n, ast.Call):
            fn = self.functions.get(n.func.id)  # type: ignore[attr-defined]
            if fn is None:
                raise RuleError(f"there is no rule function {n.func.id!r}")  # type: ignore[attr-defined]
            return fn(*[self._node(a) for a in n.args], **{k.arg: self._node(k.value) for k in n.keywords})
        raise RuleError(f"cannot evaluate {type(n).__name__}")

    def _comprehend(self, generators: list[ast.comprehension]):
        def walk(i: int, scope: Scope):
            if i == len(generators):
                yield scope
                return
            gen = generators[i]
            for item in list(scope._node(gen.iter)):
                sub = scope.child()
                sub._bind(gen.target, item)
                if all(sub._node(c) for c in gen.ifs):
                    yield from walk(i + 1, sub)

        yield from walk(0, self)

    def _bind(self, target: ast.AST, value: Any) -> None:
        if isinstance(target, ast.Name):
            self.vars[target.id] = value
        elif isinstance(target, ast.Tuple | ast.List):
            for t, v in zip(target.elts, value, strict=True):
                self._bind(t, v)
        else:
            raise RuleError("a loop can only name its variables")

    def bind(self, names: str, value: Any) -> None:
        """Bind a ``for`` step's names (``place`` or ``src, dst, carry``) to one item."""
        self._bind(parse(names).body, value)

    # ------------------------------------------------------------------ writing

    def assign(self, target: str, value: Any) -> None:
        """Write a value: a local if one has that name, else the world's state (``blight[dst]``, ``wolves.hunger``)."""
        node = parse(target).body
        if isinstance(node, ast.Name):
            if node.id in self.vars:
                self.vars[node.id] = value
            else:
                self.resolve(":state")[node.id] = value
            return
        container, key = self._place(node)
        if hasattr(container, "write"):
            container.write(key, value)
        else:
            container[key] = value

    def delete(self, target: str) -> None:
        node = parse(target).body
        if isinstance(node, ast.Name):
            self.resolve(":state").pop(node.id, None)
            return
        container, key = self._place(node)
        container.pop(key, None)

    def _place(self, node: ast.AST) -> tuple[Any, Any]:
        """The container and key a target writes to, making missing tables on the way (``overgod.ever.hummed``)."""
        if isinstance(node, ast.Attribute):
            return self._table(node.value), node.attr
        if isinstance(node, ast.Subscript):
            return self._table(node.value), self._node(node.slice)
        raise RuleError("a rule can only write to a name, a field or an entry")

    def _table(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Name):
            if node.id in self.vars:
                return self.vars[node.id]
            value = self.name(node.id)
            if isinstance(value, dict | list) or hasattr(value, "write"):
                return value
            state = self.resolve(":state")
            state[node.id] = {}
            return state[node.id]
        container, key = self._place(node)
        if hasattr(container, "write"):
            return container.read(key)
        value = container.get(key) if isinstance(container, dict) else container[key]
        if not isinstance(value, dict | list):
            container[key] = value = {}
        return value
