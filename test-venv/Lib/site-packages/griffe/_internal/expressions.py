# This module contains the data classes that represent resolvable names and expressions.
# First we declare data classes for each kind of expression, mostly corresponding to Python's AST nodes.
# Then we declare builder methods, that iterate AST nodes and build the corresponding data classes,
# and two utilities `_yield` and `_join` to help iterate on expressions.
# Finally we declare a few public helpers to safely get expressions from AST nodes in different scenarios.

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from dataclasses import fields as getfields
from enum import IntEnum, auto
from functools import partial
from typing import TYPE_CHECKING, Any, Protocol

from griffe._internal.agents.nodes.parameters import get_parameters
from griffe._internal.enumerations import LogLevel, ParameterKind
from griffe._internal.exceptions import NameResolutionError
from griffe._internal.logger import logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence
    from pathlib import Path

    from griffe._internal.models import Class, Function, Module


class _OperatorPrecedence(IntEnum):
    # Adapted from:
    #
    # - https://docs.python.org/3/reference/expressions.html#operator-precedence
    # - https://github.com/python/cpython/blob/main/Lib/_ast_unparse.py
    # - https://github.com/astral-sh/ruff/blob/6abafcb56575454f2caeaa174efcb9fd0a8362b1/crates/ruff_python_ast/src/operator_precedence.rs

    # The enum members are declared in ascending order of precedence.

    # A virtual precedence level for contexts that provide their own grouping, like list brackets or
    # function call parentheses. This ensures parentheses will never be added for the direct children of these nodes.
    # NOTE: `ruff_python_formatter::expression::parentheses`'s state machine would be more robust
    # but would introduce significant complexity.
    NONE = auto()

    YIELD = auto()  # `yield`, `yield from`
    ASSIGN = auto()  # `target := expr`
    STARRED = auto()  # `*expr` (omitted by Python docs, see ruff impl)
    LAMBDA = auto()
    IF_ELSE = auto()  # `expr if cond else expr`
    OR = auto()
    AND = auto()
    NOT = auto()
    COMP_MEMB_ID = auto()  # `<`, `<=`, `>`, `>=`, `!=`, `==`, `in`, `not in`, `is`, `is not`
    BIT_OR = auto()  # `|`
    BIT_XOR = auto()  # `^`
    BIT_AND = auto()  # `&`
    LEFT_RIGHT_SHIFT = auto()  # `<<`, `>>`
    ADD_SUB = auto()  # `+`, `-`
    MUL_DIV_REMAIN = auto()  # `*`, `@`, `/`, `//`, `%`
    POS_NEG_BIT_NOT = auto()  # `+x`, `-x`, `~x`
    EXPONENT = auto()  # `**`
    AWAIT = auto()
    CALL_ATTRIBUTE = auto()  # `x[index]`, `x[index:index]`, `x(arguments...)`, `x.attribute`
    ATOMIC = auto()  # `(expressions...)`, `[expressions...]`, `{key: value...}`, `{expressions...}`


def _yield(
    element: str | Expr | tuple[str | Expr, ...],
    *,
    flat: bool = True,
    is_left: bool = False,
    outer_precedence: _OperatorPrecedence = _OperatorPrecedence.ATOMIC,
) -> Iterator[str | Expr]:
    if isinstance(element, Expr):
        element_precedence = _get_precedence(element)
        needs_parens = False
        # Lower inner precedence, e.g. `(a + b) * c`, `+(10) < *(11)`.
        if element_precedence < outer_precedence:
            needs_parens = True
        elif element_precedence == outer_precedence:
            # Right-association, e.g. parenthesize left-hand side in `(a ** b) ** c`, (a if b else c) if d else e
            is_right_assoc = isinstance(element, ExprIfExp) or (
                isinstance(element, ExprBinOp) and element.operator == "**"
            )
            if is_right_assoc:
                if is_left:
                    needs_parens = True
            # Left-association, e.g. parenthesize right-hand side in `a - (b - c)`.
            elif isinstance(element, (ExprBinOp, ExprBoolOp)) and not is_left:
                needs_parens = True

        if needs_parens:
            yield "("
            if flat:
                yield from element.iterate(flat=True)
            else:
                yield element
            yield ")"
        elif flat:
            yield from element.iterate(flat=True)
        else:
            yield element
    elif isinstance(element, tuple):
        for elem in element:
            yield from _yield(elem, flat=flat, outer_precedence=outer_precedence, is_left=is_left)
    else:
        yield element


def _join(
    elements: Iterable[str | Expr | tuple[str | Expr, ...]],
    joint: str | Expr,
    *,
    flat: bool = True,
) -> Iterator[str | Expr]:
    """Apply a separator between elements.

    The caller is assumed to provide their own grouping
    (e.g. lists, tuples, slice) and will prevent parentheses from being added.
    """
    it = iter(elements)
    try:
        # Since we are in a sequence, don't parenthesize items.
        # Avoids [a + b, c + d] being serialized as [(a + b), (c + d)]
        yield from _yield(next(it), flat=flat, outer_precedence=_OperatorPrecedence.NONE)
    except StopIteration:
        return
    for element in it:
        yield from _yield(joint, flat=flat, outer_precedence=_OperatorPrecedence.NONE)
        yield from _yield(element, flat=flat, outer_precedence=_OperatorPrecedence.NONE)


def _field_as_dict(
    element: str | bool | Expr | list[str | Expr] | None,  # noqa: FBT001
    **kwargs: Any,
) -> str | bool | None | list | dict:
    if isinstance(element, Expr):
        return _expr_as_dict(element, **kwargs)
    if isinstance(element, list):
        return [_field_as_dict(elem, **kwargs) for elem in element]
    return element


def _expr_as_dict(expression: Expr, **kwargs: Any) -> dict[str, Any]:
    fields = {
        field.name: _field_as_dict(getattr(expression, field.name), **kwargs)
        for field in sorted(getfields(expression), key=lambda f: f.name)
        if field.name != "parent"
    }
    fields["cls"] = expression.classname
    return fields


_modern_types = {
    "typing.Tuple": "tuple",
    "typing.Dict": "dict",
    "typing.List": "list",
    "typing.Set": "set",
}


@dataclass
class Expr:
    """Base class for expressions."""

    def __str__(self) -> str:
        return "".join(elem if isinstance(elem, str) else elem.name for elem in self.iterate(flat=True))  # ty:ignore[unresolved-attribute]

    def __iter__(self) -> Iterator[str | Expr]:
        """Iterate on the expression syntax and elements."""
        yield from self.iterate(flat=False)

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:  # noqa: ARG002
        """Iterate on the expression elements.

        Parameters:
            flat: Expressions are trees.

                When flat is false, this method iterates only on the first layer of the tree.
                To iterate on all the subparts of the expression, you have to do so recursively.
                It allows to handle each subpart specifically (for example subscripts, attribute, etc.),
                without them getting rendered as strings.

                On the contrary, when flat is true, the whole tree is flattened as a sequence
                of strings and instances of [Names][griffe.ExprName].

        Yields:
            Strings and names when flat, strings and expressions otherwise.
        """
        yield from ()

    def modernize(self) -> Expr:
        """Modernize the expression.

        For example, use PEP 604 type unions `|` instead of `typing.Union`.

        Returns:
            A modernized expression.
        """
        return self

    def as_dict(self, **kwargs: Any) -> dict[str, Any]:
        """Return the expression as a dictionary.

        Parameters:
            **kwargs: Configuration options (none available yet).


        Returns:
            A dictionary.
        """
        return _expr_as_dict(self, **kwargs)

    @property
    def classname(self) -> str:
        """The expression class name."""
        return self.__class__.__name__

    @property
    def path(self) -> str:
        """Path of the expressed name/attribute."""
        return str(self)

    @property
    def canonical_path(self) -> str:
        """Path of the expressed name/attribute."""
        return str(self)

    @property
    def canonical_name(self) -> str:
        """Name of the expressed name/attribute/parameter."""
        # We must handle things like `griffe.Visitor` and `griffe.Visitor(code)`.
        return self.canonical_path.rsplit(".", 1)[-1].split("(", 1)[-1].removesuffix(")")

    @property
    def is_classvar(self) -> bool:
        """Whether this attribute is annotated with `ClassVar`."""
        return isinstance(self, ExprSubscript) and self.canonical_name == "ClassVar"

    @property
    def is_tuple(self) -> bool:
        """Whether this expression is a tuple."""
        return isinstance(self, ExprSubscript) and self.canonical_name.lower() == "tuple"

    @property
    def is_iterator(self) -> bool:
        """Whether this expression is an iterator."""
        return isinstance(self, ExprSubscript) and self.canonical_name == "Iterator"

    @property
    def is_generator(self) -> bool:
        """Whether this expression is a generator."""
        return isinstance(self, ExprSubscript) and self.canonical_name == "Generator"

    @staticmethod
    def _to_binop(elements: Sequence[Expr], op: str) -> ExprBinOp:
        if len(elements) == 2:  # noqa: PLR2004
            left, right = elements
            if isinstance(left, Expr):
                left = left.modernize()
            if isinstance(right, Expr):
                right = right.modernize()
            return ExprBinOp(left=left, operator=op, right=right)

        left = ExprSubscript._to_binop(elements[:-1], op=op)
        right = elements[-1]
        if isinstance(right, Expr):
            right = right.modernize()
        return ExprBinOp(left=left, operator=op, right=right)


@dataclass(eq=True, slots=True)
class ExprAttribute(Expr):
    """Attributes like `a.b`."""

    values: list[str | Expr]
    """The different parts of the dotted chain."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        precedence = _get_precedence(self)
        yield from _yield(self.values[0], flat=flat, outer_precedence=precedence, is_left=True)
        for value in self.values[1:]:
            yield "."
            yield from _yield(value, flat=flat, outer_precedence=precedence)

    def modernize(self) -> ExprName | ExprAttribute:
        if modern := _modern_types.get(self.canonical_path):
            return ExprName(modern, parent=self.last.parent)
        return self

    def append(self, value: ExprName) -> None:
        """Append a name to this attribute.

        Parameters:
            value: The expression name to append.
        """
        if value.parent is None:
            value.parent = self.last
        self.values.append(value)

    @property
    def last(self) -> ExprName:
        """The last part of this attribute (on the right)."""
        # All values except the first one can *only* be names:
        # we can't do `a.(b or c)` or `a."string"`.
        return self.values[-1]  # ty:ignore[invalid-return-type]

    @property
    def first(self) -> str | Expr:
        """The first part of this attribute (on the left)."""
        return self.values[0]

    @property
    def path(self) -> str:
        """The path of this attribute."""
        return self.last.path

    @property
    def canonical_path(self) -> str:
        """The canonical path of this attribute."""
        return self.last.canonical_path


@dataclass(eq=True, slots=True)
class ExprBinOp(Expr):
    """Binary operations like `a + b`."""

    left: str | Expr
    """Left part."""
    operator: str
    """Binary operator."""
    right: str | Expr
    """Right part."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        precedence = _get_precedence(self)
        right_precedence = precedence
        if self.operator == "**" and isinstance(self.right, ExprUnaryOp):
            # Unary operators on the right have higher precedence, e.g. `a ** -b`.
            right_precedence = _OperatorPrecedence(precedence - 1)
        yield from _yield(self.left, flat=flat, outer_precedence=precedence, is_left=True)
        yield f" {self.operator} "
        yield from _yield(self.right, flat=flat, outer_precedence=right_precedence, is_left=False)


@dataclass(eq=True, slots=True)
class ExprBoolOp(Expr):
    """Boolean operations like `a or b`."""

    operator: str
    """Boolean operator."""
    values: Sequence[str | Expr]
    """Operands."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        precedence = _get_precedence(self)
        it = iter(self.values)
        yield from _yield(next(it), flat=flat, outer_precedence=precedence, is_left=True)
        for value in it:
            yield f" {self.operator} "
            yield from _yield(value, flat=flat, outer_precedence=precedence, is_left=False)


@dataclass(eq=True, slots=True)
class ExprCall(Expr):
    """Calls like `f()`."""

    function: Expr
    """Function called."""
    arguments: Sequence[str | Expr]
    """Passed arguments."""

    @property
    def canonical_path(self) -> str:
        """The canonical path of this subscript's left part."""
        return self.function.canonical_path

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield from _yield(self.function, flat=flat, outer_precedence=_get_precedence(self))
        yield "("
        yield from _join(self.arguments, ", ", flat=flat)
        yield ")"


@dataclass(eq=True, slots=True)
class ExprCompare(Expr):
    """Comparisons like `a > b`."""

    left: str | Expr
    """Left part."""
    operators: Sequence[str]
    """Comparison operators."""
    comparators: Sequence[str | Expr]
    """Things compared."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        precedence = _get_precedence(self)
        yield from _yield(self.left, flat=flat, outer_precedence=precedence, is_left=True)
        for op, comp in zip(self.operators, self.comparators, strict=False):
            yield f" {op} "
            yield from _yield(comp, flat=flat, outer_precedence=precedence)


@dataclass(eq=True, slots=True)
class ExprComprehension(Expr):
    """Comprehensions like `a for b in c if d`."""

    target: str | Expr
    """Comprehension target (value added to the result)."""
    iterable: str | Expr
    """Value iterated on."""
    conditions: Sequence[str | Expr]
    """Conditions to include the target in the result."""
    is_async: bool = False
    """Async comprehension or not."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        if self.is_async:
            yield "async "
        yield "for "
        yield from _yield(self.target, flat=flat)
        yield " in "
        yield from _yield(self.iterable, flat=flat)
        if self.conditions:
            yield " if "
            yield from _join(self.conditions, " if ", flat=flat)


# TODO: `ExprConstant` is never instantiated,
# see `_build_constant` below (it always returns the value directly).
# Maybe we could simply get rid of it, as it wouldn't bring much value
# if used anyway.
@dataclass(eq=True, slots=True)
class ExprConstant(Expr):
    """Constants like `"a"` or `1`."""

    value: str
    """Constant value."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:  # noqa: ARG002
        yield self.value


@dataclass(eq=True, slots=True)
class ExprDict(Expr):
    """Dictionaries like `{"a": 0}`."""

    keys: Sequence[str | Expr | None]
    """Dict keys."""
    values: Sequence[str | Expr]
    """Dict values."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "{"
        yield from _join(
            (("None" if key is None else key, ": ", value) for key, value in zip(self.keys, self.values, strict=False)),
            ", ",
            flat=flat,
        )
        yield "}"


@dataclass(eq=True, slots=True)
class ExprDictComp(Expr):
    """Dict comprehensions like `{k: v for k, v in a}`."""

    key: str | Expr
    """Target key."""
    value: str | Expr
    """Target value."""
    generators: Sequence[Expr]
    """Generators iterated on."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "{"
        yield from _yield(self.key, flat=flat)
        yield ": "
        yield from _yield(self.value, flat=flat)
        yield " "
        yield from _join(self.generators, " ", flat=flat)
        yield "}"


@dataclass(eq=True, slots=True)
class ExprExtSlice(Expr):
    """Extended slice like `a[x:y, z]`."""

    dims: Sequence[str | Expr]
    """Dims."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield from _join(self.dims, ", ", flat=flat)


@dataclass(eq=True, slots=True)
class ExprFormatted(Expr):
    """Formatted string like `{1 + 1}`."""

    value: str | Expr
    """Formatted value."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "{"
        # Prevent parentheses from being added, avoiding `{(1 + 1)}`
        yield from _yield(self.value, flat=flat, outer_precedence=_OperatorPrecedence.NONE)
        yield "}"


@dataclass(eq=True, slots=True)
class ExprGeneratorExp(Expr):
    """Generator expressions like `a for b in c for d in e`."""

    element: str | Expr
    """Yielded element."""
    generators: Sequence[Expr]
    """Generators iterated on."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield from _yield(self.element, flat=flat)
        yield " "
        yield from _join(self.generators, " ", flat=flat)


@dataclass(eq=True, slots=True)
class ExprIfExp(Expr):
    """Conditions like `a if b else c`."""

    body: str | Expr
    """Value if test."""
    test: str | Expr
    """Condition."""
    orelse: str | Expr
    """Other expression."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        precedence = _get_precedence(self)
        yield from _yield(self.body, flat=flat, outer_precedence=precedence, is_left=True)
        yield " if "
        # If the test itself is another if/else, its precedence is the same, which will not give
        # a parenthesis: force it.
        test_outer_precedence = _OperatorPrecedence(precedence + 1)
        yield from _yield(self.test, flat=flat, outer_precedence=test_outer_precedence)
        yield " else "
        # If/else is right associative. For example, a nested if/else
        # `a if b else c if d else e` is effectively `a if b else (c if d else e)`, so produce a
        # flattened version without parentheses.
        if isinstance(self.orelse, ExprIfExp):
            yield from self.orelse.iterate(flat=flat)
        else:
            yield from _yield(self.orelse, flat=flat, outer_precedence=precedence, is_left=False)


@dataclass(eq=True, slots=True)
class ExprInterpolation(Expr):
    """Template string interpolation like `{name}`."""

    value: str | Expr
    """Interpolated value."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "{"
        # Prevent parentheses from being added, avoiding `{(1 + 1)}`
        yield from _yield(self.value, flat=flat, outer_precedence=_OperatorPrecedence.NONE)
        yield "}"


@dataclass(eq=True, slots=True)
class ExprJoinedStr(Expr):
    """Joined strings like `f"a {b} c"`."""

    values: Sequence[str | Expr]
    """Joined values."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "f'"
        yield from _join(self.values, "", flat=flat)
        yield "'"


@dataclass(eq=True, slots=True)
class ExprKeyword(Expr):
    """Keyword arguments like `a=b`."""

    name: str
    """Name."""
    value: str | Expr
    """Value."""

    # Griffe is designed around accessing Python objects
    # with the dot notation, for example `module.Class`.
    # Function parameters were not taken into account
    # because they are not accessible the same way.
    # But we still want to be able to cross-reference
    # documentation of function parameters in downstream
    # tools like mkdocstrings. So we add a special case
    # for keyword expressions, where they get a meaningful
    # canonical path (contrary to most other expressions that
    # aren't or do not begin with names or attributes)
    # of the form `path.to.called_function(param_name)`.
    # For this we need to store a reference to the `func` part
    # of the call expression in the keyword one,
    # hence the following field.
    # We allow it to be None for backward compatibility.
    function: Expr | None = None
    """Expression referencing the function called with this parameter."""

    @property
    def canonical_path(self) -> str:
        """Path of the expressed keyword."""
        if self.function:
            return f"{self.function.canonical_path}({self.name})"
        return super(ExprKeyword, self).canonical_path

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield self.name
        yield "="
        yield from _yield(self.value, flat=flat)


@dataclass(eq=True, slots=True)
class ExprVarPositional(Expr):
    """Variadic positional parameters like `*args`."""

    value: Expr
    """Starred value."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "*"
        yield from _yield(self.value, flat=flat)


@dataclass(eq=True, slots=True)
class ExprVarKeyword(Expr):
    """Variadic keyword parameters like `**kwargs`."""

    value: Expr
    """Double-starred value."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "**"
        yield from _yield(self.value, flat=flat)


@dataclass(eq=True, slots=True)
class ExprLambda(Expr):
    """Lambda expressions like `lambda a: a.b`."""

    parameters: Sequence[ExprParameter]
    """Lambda's parameters."""
    body: str | Expr
    """Lambda's body."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        pos_only = False
        pos_or_kw = False
        kw_only = False
        length = len(self.parameters)
        yield "lambda"
        if length:
            yield " "
        for index, parameter in enumerate(self.parameters, 1):
            if parameter.kind is ParameterKind.positional_only:
                pos_only = True
            elif parameter.kind is ParameterKind.var_positional:
                yield "*"
            elif parameter.kind is ParameterKind.var_keyword:
                yield "**"
            elif parameter.kind is ParameterKind.positional_or_keyword and not pos_or_kw:
                pos_or_kw = True
            elif parameter.kind is ParameterKind.keyword_only and not kw_only:
                kw_only = True
                yield "*, "
            if parameter.kind is not ParameterKind.positional_only and pos_only:
                pos_only = False
                yield "/, "
            yield parameter.name
            if parameter.default and parameter.kind not in (ParameterKind.var_positional, ParameterKind.var_keyword):
                yield "="
                yield from _yield(parameter.default, flat=flat)
            if index < length:
                yield ", "
        yield ": "
        # Body of lambda should not have parentheses, avoiding `lambda: a.b`
        yield from _yield(self.body, flat=flat, outer_precedence=_OperatorPrecedence.NONE)


@dataclass(eq=True, slots=True)
class ExprList(Expr):
    """Lists like `[0, 1, 2]`."""

    elements: Sequence[Expr]
    """List elements."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "["
        yield from _join(self.elements, ", ", flat=flat)
        yield "]"


@dataclass(eq=True, slots=True)
class ExprListComp(Expr):
    """List comprehensions like `[a for b in c]`."""

    element: str | Expr
    """Target value."""
    generators: Sequence[Expr]
    """Generators iterated on."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "["
        yield from _yield(self.element, flat=flat)
        yield " "
        yield from _join(self.generators, " ", flat=flat)
        yield "]"


@dataclass(eq=False, slots=True)
class ExprName(Expr):  # noqa: PLW1641
    """This class represents a Python object identified by a name in a given scope."""

    name: str
    """Actual name."""
    parent: str | ExprName | Module | Class | Function | None = None
    """Parent (for resolution in its scope)."""
    member: str | None = None
    """Member name (for resolution in its scope)."""

    def __eq__(self, other: object) -> bool:
        """Two name expressions are equal if they have the same `name` value (`parent` is ignored)."""
        if isinstance(other, ExprName):
            return self.name == other.name
        return NotImplemented

    def iterate(self, *, flat: bool = True) -> Iterator[ExprName]:  # noqa: ARG002
        yield self

    def modernize(self) -> ExprName:
        if modern := _modern_types.get(self.canonical_path):
            return ExprName(modern, parent=self.parent)
        return self

    @property
    def path(self) -> str:
        """The full, resolved name.

        If it was given when creating the name, return that.
        If a callable was given, call it and return its result.
        It the name cannot be resolved, return the source.
        """
        if isinstance(self.parent, ExprName):
            return f"{self.parent.path}.{self.name}"
        return self.name

    @property
    def canonical_path(self) -> str:
        """The canonical name (resolved one, not alias name)."""
        if self.parent is None:
            return self.name
        if isinstance(self.parent, ExprName):
            return f"{self.parent.canonical_path}.{self.name}"
        if isinstance(self.parent, str):
            return f"{self.parent}.{self.name}"
        parent = self.parent.members.get(self.member, self.parent)  # ty:ignore[no-matching-overload]
        try:
            return parent.resolve(self.name)
        except NameResolutionError:
            return self.name

    @property
    def resolved(self) -> Module | Class | None:
        """The resolved object this name refers to."""
        try:
            return self.parent.modules_collection[self.parent.resolve(self.name)]  # ty:ignore[unresolved-attribute]
        except Exception:  # noqa: BLE001
            return self.parent.resolved[self.name]  # ty:ignore[not-subscriptable, unresolved-attribute]

    @property
    def is_enum_class(self) -> bool:
        """Whether this name resolves to an enumeration class."""
        try:
            bases = self.resolved.bases  # ty:ignore[unresolved-attribute]
        except Exception:  # noqa: BLE001
            return False

        # TODO: Support inheritance?
        # TODO: Support `StrEnum` and `IntEnum`.
        return any(isinstance(base, Expr) and base.canonical_path == "enum.Enum" for base in bases)

    @property
    def is_enum_instance(self) -> bool:
        """Whether this name resolves to an enumeration instance."""
        try:
            return self.parent.is_enum_class  # ty:ignore[unresolved-attribute]
        except Exception:  # noqa: BLE001
            return False

    @property
    def is_enum_value(self) -> bool:
        """Whether this name resolves to an enumeration value."""
        try:
            return self.name == "value" and self.parent.is_enum_instance  # ty:ignore[unresolved-attribute]
        except Exception:  # noqa: BLE001
            return False

    @property
    def is_type_parameter(self) -> bool:
        """Whether this name resolves to a type parameter."""
        return "[" in self.canonical_path


@dataclass(eq=True, slots=True)
class ExprNamedExpr(Expr):
    """Named/assignment expressions like `a := b`."""

    target: Expr
    """Target name."""
    value: str | Expr
    """Value."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield from _yield(self.target, flat=flat)
        yield " := "
        yield from _yield(self.value, flat=flat)


@dataclass(eq=True, slots=True)
class ExprParameter(Expr):
    """Parameters in function signatures like `a: int = 0`."""

    name: str
    """Parameter name."""
    kind: ParameterKind = ParameterKind.positional_or_keyword
    """Parameter kind."""
    annotation: Expr | None = None
    """Parameter type."""
    default: str | Expr | None = None
    """Parameter default."""


@dataclass(eq=True, slots=True)
class ExprSet(Expr):
    """Sets like `{0, 1, 2}`."""

    elements: Sequence[str | Expr]
    """Set elements."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "{"
        yield from _join(self.elements, ", ", flat=flat)
        yield "}"


@dataclass(eq=True, slots=True)
class ExprSetComp(Expr):
    """Set comprehensions like `{a for b in c}`."""

    element: str | Expr
    """Target value."""
    generators: Sequence[Expr]
    """Generators iterated on."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "{"
        yield from _yield(self.element, flat=flat)
        yield " "
        yield from _join(self.generators, " ", flat=flat)
        yield "}"


@dataclass(eq=True, slots=True)
class ExprSlice(Expr):
    """Slices like `[a:b:c]`."""

    lower: str | Expr | None = None
    """Lower bound."""
    upper: str | Expr | None = None
    """Upper bound."""
    step: str | Expr | None = None
    """Iteration step."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        if self.lower is not None:
            yield from _yield(self.lower, flat=flat)
        yield ":"
        if self.upper is not None:
            yield from _yield(self.upper, flat=flat)
        if self.step is not None:
            yield ":"
            yield from _yield(self.step, flat=flat)


@dataclass(eq=True, slots=True)
class ExprSubscript(Expr):
    """Subscripts like `a[b]`."""

    left: str | Expr
    """Left part."""
    slice: str | Expr
    """Slice part."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield from _yield(self.left, flat=flat, outer_precedence=_get_precedence(self))
        yield "["
        # Prevent parentheses from being added, avoiding `a[(b)]`
        yield from _yield(self.slice, flat=flat, outer_precedence=_OperatorPrecedence.NONE)
        yield "]"

    def modernize(self) -> ExprBinOp | ExprSubscript:
        if self.canonical_path == "typing.Union":
            return self._to_binop(self.slice.elements, op="|")  # ty:ignore[unresolved-attribute]
        if self.canonical_path == "typing.Optional":
            left = self.slice if isinstance(self.slice, str) else self.slice.modernize()
            return ExprBinOp(left=left, operator="|", right="None")
        return ExprSubscript(
            left=self.left if isinstance(self.left, str) else self.left.modernize(),
            slice=self.slice if isinstance(self.slice, str) else self.slice.modernize(),
        )

    @property
    def path(self) -> str:
        """The path of this subscript's left part."""
        if isinstance(self.left, str):
            return self.left
        return self.left.path

    @property
    def canonical_path(self) -> str:
        """The canonical path of this subscript's left part."""
        if isinstance(self.left, str):
            return self.left
        return self.left.canonical_path


@dataclass(eq=True, slots=True)
class ExprTemplateStr(Expr):
    """Template strings like `t"a {name}"`."""

    values: Sequence[str | Expr]
    """Joined values."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "t'"
        yield from _join(self.values, "", flat=flat)
        yield "'"


@dataclass(eq=True, slots=True)
class ExprTuple(Expr):
    """Tuples like `(0, 1, 2)`."""

    elements: Sequence[str | Expr]
    """Tuple elements."""
    implicit: bool = False
    """Whether the tuple is implicit (e.g. without parentheses in a subscript's slice)."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        if not self.implicit:
            yield "("
        yield from _join(self.elements, ", ", flat=flat)
        if len(self.elements) == 1:
            yield ","
        if not self.implicit:
            yield ")"

    def modernize(self) -> ExprTuple:
        return ExprTuple(
            elements=[el if isinstance(el, str) else el.modernize() for el in self.elements],
            implicit=self.implicit,
        )


@dataclass(eq=True, slots=True)
class ExprUnaryOp(Expr):
    """Unary operations like `-1`."""

    operator: str
    """Unary operator."""
    value: str | Expr
    """Value."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield self.operator
        if self.operator == "not":
            yield " "
        yield from _yield(self.value, flat=flat, outer_precedence=_get_precedence(self))


@dataclass(eq=True, slots=True)
class ExprYield(Expr):
    """Yield statements like `yield a`."""

    value: str | Expr | None = None
    """Yielded value."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "yield"
        if self.value is not None:
            yield " "
            yield from _yield(self.value, flat=flat)


@dataclass(eq=True, slots=True)
class ExprYieldFrom(Expr):
    """Yield statements like `yield from a`."""

    value: str | Expr
    """Yielded-from value."""

    def iterate(self, *, flat: bool = True) -> Iterator[str | Expr]:
        yield "yield from "
        yield from _yield(self.value, flat=flat)


_unary_op_map = {
    ast.Invert: "~",
    ast.Not: "not",
    ast.UAdd: "+",
    ast.USub: "-",
}

_binary_op_map = {
    ast.Add: "+",
    ast.BitAnd: "&",
    ast.BitOr: "|",
    ast.BitXor: "^",
    ast.Div: "/",
    ast.FloorDiv: "//",
    ast.LShift: "<<",
    ast.MatMult: "@",
    ast.Mod: "%",
    ast.Mult: "*",
    ast.Pow: "**",
    ast.RShift: ">>",
    ast.Sub: "-",
}

_bool_op_map = {
    ast.And: "and",
    ast.Or: "or",
}

_compare_op_map = {
    ast.Eq: "==",
    ast.NotEq: "!=",
    ast.Lt: "<",
    ast.LtE: "<=",
    ast.Gt: ">",
    ast.GtE: ">=",
    ast.Is: "is",
    ast.IsNot: "is not",
    ast.In: "in",
    ast.NotIn: "not in",
}

# TODO: Support `ast.Await`.
_precedence_map = {
    # Literals and names.
    ExprName: lambda _: _OperatorPrecedence.ATOMIC,
    ExprConstant: lambda _: _OperatorPrecedence.ATOMIC,
    ExprJoinedStr: lambda _: _OperatorPrecedence.ATOMIC,
    ExprFormatted: lambda _: _OperatorPrecedence.ATOMIC,
    # Container displays.
    ExprList: lambda _: _OperatorPrecedence.ATOMIC,
    ExprTuple: lambda _: _OperatorPrecedence.ATOMIC,
    ExprSet: lambda _: _OperatorPrecedence.ATOMIC,
    ExprDict: lambda _: _OperatorPrecedence.ATOMIC,
    # Comprehensions are self-contained units that produce a container.
    ExprListComp: lambda _: _OperatorPrecedence.ATOMIC,
    ExprSetComp: lambda _: _OperatorPrecedence.ATOMIC,
    ExprDictComp: lambda _: _OperatorPrecedence.ATOMIC,
    ExprAttribute: lambda _: _OperatorPrecedence.CALL_ATTRIBUTE,
    ExprSubscript: lambda _: _OperatorPrecedence.CALL_ATTRIBUTE,
    ExprCall: lambda _: _OperatorPrecedence.CALL_ATTRIBUTE,
    ExprUnaryOp: lambda e: {"not": _OperatorPrecedence.NOT}.get(e.operator, _OperatorPrecedence.POS_NEG_BIT_NOT),
    ExprBinOp: lambda e: {
        "**": _OperatorPrecedence.EXPONENT,
        "*": _OperatorPrecedence.MUL_DIV_REMAIN,
        "@": _OperatorPrecedence.MUL_DIV_REMAIN,
        "/": _OperatorPrecedence.MUL_DIV_REMAIN,
        "//": _OperatorPrecedence.MUL_DIV_REMAIN,
        "%": _OperatorPrecedence.MUL_DIV_REMAIN,
        "+": _OperatorPrecedence.ADD_SUB,
        "-": _OperatorPrecedence.ADD_SUB,
        "<<": _OperatorPrecedence.LEFT_RIGHT_SHIFT,
        ">>": _OperatorPrecedence.LEFT_RIGHT_SHIFT,
        "&": _OperatorPrecedence.BIT_AND,
        "^": _OperatorPrecedence.BIT_XOR,
        "|": _OperatorPrecedence.BIT_OR,
    }[e.operator],
    ExprBoolOp: lambda e: {"and": _OperatorPrecedence.AND, "or": _OperatorPrecedence.OR}[e.operator],
    ExprCompare: lambda _: _OperatorPrecedence.COMP_MEMB_ID,
    ExprIfExp: lambda _: _OperatorPrecedence.IF_ELSE,
    ExprNamedExpr: lambda _: _OperatorPrecedence.ASSIGN,
    ExprLambda: lambda _: _OperatorPrecedence.LAMBDA,
    # NOTE: Ruff categorizes as atomic, but `(a for a in b).c` implies its less than `CALL_ATTRIBUTE`.
    ExprGeneratorExp: lambda _: _OperatorPrecedence.LAMBDA,
    ExprVarPositional: lambda _: _OperatorPrecedence.STARRED,
    ExprVarKeyword: lambda _: _OperatorPrecedence.STARRED,
    ExprYield: lambda _: _OperatorPrecedence.YIELD,
    ExprYieldFrom: lambda _: _OperatorPrecedence.YIELD,
    # These are not standalone, they appear in specific contexts where precendence is not a concern.
    # NOTE: `for ... in ... if` part, not the whole `[...]`.
    ExprComprehension: lambda _: _OperatorPrecedence.NONE,
    ExprExtSlice: lambda _: _OperatorPrecedence.NONE,
    ExprKeyword: lambda _: _OperatorPrecedence.NONE,
    ExprParameter: lambda _: _OperatorPrecedence.NONE,
    ExprSlice: lambda _: _OperatorPrecedence.NONE,
}


def _get_precedence(expr: Expr) -> _OperatorPrecedence:
    return _precedence_map.get(type(expr), lambda _: _OperatorPrecedence.NONE)(expr)  # ty:ignore[no-matching-overload]


def _build_attribute(node: ast.Attribute, parent: Module | Class, **kwargs: Any) -> Expr:
    left = _build(node.value, parent, **kwargs)
    if isinstance(left, ExprAttribute):
        left.append(ExprName(node.attr))
        return left
    if isinstance(left, ExprName):
        return ExprAttribute([left, ExprName(node.attr, left)])
    if isinstance(left, str):
        return ExprAttribute([left, ExprName(node.attr, "str")])
    return ExprAttribute([left, ExprName(node.attr)])


def _build_binop(node: ast.BinOp, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprBinOp(
        _build(node.left, parent, **kwargs),
        _binary_op_map[type(node.op)],  # ty:ignore[invalid-argument-type]
        _build(node.right, parent, **kwargs),
    )


def _build_boolop(node: ast.BoolOp, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprBoolOp(
        _bool_op_map[type(node.op)],  # ty:ignore[invalid-argument-type]
        [_build(value, parent, **kwargs) for value in node.values],
    )


def _build_call(node: ast.Call, parent: Module | Class, **kwargs: Any) -> Expr:
    function = _build(node.func, parent, **kwargs)
    positional_args = [_build(arg, parent, **kwargs) for arg in node.args]
    keyword_args = [_build(kwarg, parent, function=function, **kwargs) for kwarg in node.keywords]
    return ExprCall(function, [*positional_args, *keyword_args])


def _build_compare(node: ast.Compare, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprCompare(
        _build(node.left, parent, **kwargs),
        [_compare_op_map[type(op)] for op in node.ops],  # ty:ignore[invalid-argument-type]
        [_build(comp, parent, **kwargs) for comp in node.comparators],
    )


def _build_comprehension(node: ast.comprehension, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprComprehension(
        _build(node.target, parent, compr_target=True, **kwargs),
        _build(node.iter, parent, **kwargs),
        [_build(condition, parent, **kwargs) for condition in node.ifs],
        is_async=bool(node.is_async),
    )


def _build_constant(
    node: ast.Constant,
    parent: Module | Class,
    *,
    in_formatted_str: bool = False,
    in_joined_str: bool = False,
    parse_strings: bool = False,
    literal_strings: bool = False,
    **kwargs: Any,
) -> str | Expr:
    if isinstance(node.value, str):
        if in_joined_str and not in_formatted_str:
            # We're in a f-string, not in a formatted value, don't keep quotes.
            return node.value
        if parse_strings and not literal_strings:
            # We're in a place where a string could be a type annotation
            # (and not in a Literal[...] type annotation).
            # We parse the string and build from the resulting nodes again.
            # If we fail to parse it (syntax errors), we consider it's a literal string and log a message.
            try:
                parsed = compile(
                    node.value,
                    mode="eval",
                    filename="<string-annotation>",
                    flags=ast.PyCF_ONLY_AST,
                    optimize=1,
                )
            except SyntaxError:
                logger.debug(
                    "Tried and failed to parse %r as Python code, "
                    "falling back to using it as a string literal "
                    "(postponed annotations might help: https://peps.python.org/pep-0563/)",
                    node.value,
                )
            else:
                return _build(parsed.body, parent, **kwargs)  # ty:ignore[unresolved-attribute]
    return {type(...): lambda _: "..."}.get(type(node.value), repr)(node.value)  # ty:ignore[no-matching-overload]


def _build_dict(node: ast.Dict, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprDict(
        [None if key is None else _build(key, parent, **kwargs) for key in node.keys],
        [_build(value, parent, **kwargs) for value in node.values],
    )


def _build_dictcomp(node: ast.DictComp, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprDictComp(
        _build(node.key, parent, **kwargs),
        _build(node.value, parent, **kwargs),
        [_build(gen, parent, **kwargs) for gen in node.generators],
    )


def _build_formatted(
    node: ast.FormattedValue,
    parent: Module | Class,
    *,
    in_formatted_str: bool = False,  # noqa: ARG001
    **kwargs: Any,
) -> Expr:
    return ExprFormatted(_build(node.value, parent, in_formatted_str=True, **kwargs))


def _build_generatorexp(node: ast.GeneratorExp, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprGeneratorExp(
        _build(node.elt, parent, **kwargs),
        [_build(gen, parent, **kwargs) for gen in node.generators],
    )


def _build_ifexp(node: ast.IfExp, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprIfExp(
        _build(node.body, parent, **kwargs),
        _build(node.test, parent, **kwargs),
        _build(node.orelse, parent, **kwargs),
    )


def _build_joinedstr(
    node: ast.JoinedStr,
    parent: Module | Class,
    *,
    in_joined_str: bool = False,  # noqa: ARG001
    **kwargs: Any,
) -> Expr:
    return ExprJoinedStr([_build(value, parent, in_joined_str=True, **kwargs) for value in node.values])


def _build_keyword(node: ast.keyword, parent: Module | Class, function: Expr | None = None, **kwargs: Any) -> Expr:
    if node.arg is None:
        return ExprVarKeyword(_build(node.value, parent, **kwargs))
    return ExprKeyword(node.arg, _build(node.value, parent, **kwargs), function=function)


def _build_lambda(node: ast.Lambda, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprLambda(
        parameters=[
            ExprParameter(
                name=name,
                kind=kind,
                annotation=None,
                default=default
                if isinstance(default, str)
                else safe_get_expression(default, parent=parent, parse_strings=False),
            )
            for name, _, kind, default in get_parameters(node.args)
        ],
        body=_build(node.body, parent, **kwargs),
    )


def _build_list(node: ast.List, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprList([_build(el, parent, **kwargs) for el in node.elts])


def _build_listcomp(node: ast.ListComp, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprListComp(_build(node.elt, parent, **kwargs), [_build(gen, parent, **kwargs) for gen in node.generators])


def _build_name(node: ast.Name, parent: Module | Class, member: str | None = None, **kwargs: Any) -> Expr:  # noqa: ARG001
    return ExprName(node.id, parent, member)


def _build_named_expr(node: ast.NamedExpr, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprNamedExpr(_build(node.target, parent, **kwargs), _build(node.value, parent, **kwargs))


def _build_set(node: ast.Set, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprSet([_build(el, parent, **kwargs) for el in node.elts])


def _build_setcomp(node: ast.SetComp, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprSetComp(_build(node.elt, parent, **kwargs), [_build(gen, parent, **kwargs) for gen in node.generators])


def _build_slice(node: ast.Slice, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprSlice(
        None if node.lower is None else _build(node.lower, parent, **kwargs),
        None if node.upper is None else _build(node.upper, parent, **kwargs),
        None if node.step is None else _build(node.step, parent, **kwargs),
    )


def _build_starred(node: ast.Starred, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprVarPositional(_build(node.value, parent, **kwargs))


def _build_subscript(
    node: ast.Subscript,
    parent: Module | Class,
    *,
    parse_strings: bool = False,
    literal_strings: bool = False,
    subscript_slice: bool = False,  # noqa: ARG001
    **kwargs: Any,
) -> Expr:
    left = _build(node.value, parent, **kwargs)
    if parse_strings:
        if isinstance(left, (ExprAttribute, ExprName)) and left.canonical_path in {
            "typing.Literal",
            "typing_extensions.Literal",
        }:
            literal_strings = True
        slice_expr = _build(
            node.slice,
            parent,
            parse_strings=True,
            literal_strings=literal_strings,
            subscript_slice=True,
            **kwargs,
        )
    else:
        slice_expr = _build(node.slice, parent, subscript_slice=True, **kwargs)
    return ExprSubscript(left, slice_expr)


def _build_tuple(
    node: ast.Tuple,
    parent: Module | Class,
    *,
    subscript_slice: bool = False,
    compr_target: bool = False,
    **kwargs: Any,
) -> Expr:
    return ExprTuple([_build(el, parent, **kwargs) for el in node.elts], implicit=subscript_slice or compr_target)


def _build_unaryop(node: ast.UnaryOp, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprUnaryOp(_unary_op_map[type(node.op)], _build(node.operand, parent, **kwargs))  # ty:ignore[invalid-argument-type]


def _build_yield(node: ast.Yield, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprYield(None if node.value is None else _build(node.value, parent, **kwargs))


def _build_yield_from(node: ast.YieldFrom, parent: Module | Class, **kwargs: Any) -> Expr:
    return ExprYieldFrom(_build(node.value, parent, **kwargs))


class _BuildCallable(Protocol):
    def __call__(self, node: Any, parent: Module | Class, **kwargs: Any) -> Expr: ...


_node_map: dict[type, _BuildCallable] = {
    ast.Attribute: _build_attribute,
    ast.BinOp: _build_binop,
    ast.BoolOp: _build_boolop,
    ast.Call: _build_call,
    ast.Compare: _build_compare,
    ast.comprehension: _build_comprehension,
    ast.Constant: _build_constant,
    ast.Dict: _build_dict,
    ast.DictComp: _build_dictcomp,
    ast.FormattedValue: _build_formatted,
    ast.GeneratorExp: _build_generatorexp,
    ast.IfExp: _build_ifexp,
    ast.JoinedStr: _build_joinedstr,
    ast.keyword: _build_keyword,
    ast.Lambda: _build_lambda,
    ast.List: _build_list,
    ast.ListComp: _build_listcomp,
    ast.Name: _build_name,
    ast.NamedExpr: _build_named_expr,
    ast.Set: _build_set,
    ast.SetComp: _build_setcomp,
    ast.Slice: _build_slice,
    ast.Starred: _build_starred,
    ast.Subscript: _build_subscript,
    ast.Tuple: _build_tuple,
    ast.UnaryOp: _build_unaryop,
    ast.Yield: _build_yield,
    ast.YieldFrom: _build_yield_from,
}  # ty:ignore[invalid-assignment]

if sys.version_info >= (3, 14):

    def _build_interpolation(node: ast.Interpolation, parent: Module | Class, **kwargs: Any) -> Expr:
        return ExprInterpolation(_build(node.value, parent, **kwargs))

    def _build_templatestr(
        node: ast.TemplateStr,
        parent: Module | Class,
        **kwargs: Any,
    ) -> Expr:
        return ExprTemplateStr([_build(value, parent, in_joined_str=True, **kwargs) for value in node.values])

    _node_map.update(
        {
            ast.Interpolation: _build_interpolation,
            ast.TemplateStr: _build_templatestr,
        },
    )


def _build(node: ast.AST, parent: Module | Class, /, **kwargs: Any) -> Expr:
    return _node_map[type(node)](node, parent, **kwargs)


def get_expression(
    node: ast.AST | None,
    parent: Module | Class,
    *,
    member: str | None = None,
    parse_strings: bool | None = None,
) -> Expr | None:
    """Build an expression from an AST.

    Parameters:
        node: The annotation node.
        parent: The parent used to resolve the name.
        member: The member name (for resolution in its scope).
        parse_strings: Whether to try and parse strings as type annotations.

    Returns:
        A string or resovable name or expression.
    """
    if node is None:
        return None
    if parse_strings is None:
        try:
            module = parent.module
        except ValueError:
            parse_strings = False
        else:
            parse_strings = not module.imports_future_annotations
    return _build(node, parent, member=member, parse_strings=parse_strings)


def safe_get_expression(
    node: ast.AST | None,
    parent: Module | Class,
    *,
    member: str | None = None,
    parse_strings: bool | None = None,
    log_level: LogLevel | None = LogLevel.error,
    msg_format: str = "{path}:{lineno}: Failed to get expression from {node_class}: {error}",
) -> Expr | None:
    """Safely (no exception) build a resolvable annotation.

    Parameters:
        node: The annotation node.
        parent: The parent used to resolve the name.
        member: The member name (for resolution in its scope).
        parse_strings: Whether to try and parse strings as type annotations.
        log_level: Log level to use to log a message. None to disable logging.
        msg_format: A format string for the log message. Available placeholders:
            path, lineno, node, error.

    Returns:
        A string or resovable name or expression.
    """
    try:
        return get_expression(node, parent, member=member, parse_strings=parse_strings)
    except Exception as error:  # noqa: BLE001
        if log_level is None:
            return None
        node_class = node.__class__.__name__
        try:
            path: Path | str = parent.relative_filepath
        except ValueError:
            path = "<in-memory>"
        lineno = node.lineno  # ty:ignore[unresolved-attribute]
        error_str = f"{error.__class__.__name__}: {error}"
        message = msg_format.format(path=path, lineno=lineno, node_class=node_class, error=error_str)
        getattr(logger, log_level.value)(message)
    return None


_msg_format = "{path}:{lineno}: Failed to get %s expression from {node_class}: {error}"
get_annotation = partial(get_expression, parse_strings=None)
safe_get_annotation = partial(
    safe_get_expression,
    parse_strings=None,
    msg_format=_msg_format % "annotation",
)
get_base_class = partial(get_expression, parse_strings=False)
safe_get_base_class = partial(
    safe_get_expression,
    parse_strings=False,
    msg_format=_msg_format % "base class",
)
get_class_keyword = partial(get_expression, parse_strings=False)
safe_get_class_keyword = partial(
    safe_get_expression,
    parse_strings=False,
    msg_format=_msg_format % "class keyword",
)
get_condition = partial(get_expression, parse_strings=False)
safe_get_condition = partial(
    safe_get_expression,
    parse_strings=False,
    msg_format=_msg_format % "condition",
)
