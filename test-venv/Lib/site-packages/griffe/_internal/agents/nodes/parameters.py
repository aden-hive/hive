# This module contains utilities for extracting information from parameter nodes.

from __future__ import annotations

import ast
from itertools import zip_longest
from typing import TYPE_CHECKING

from griffe._internal.enumerations import ParameterKind

if TYPE_CHECKING:
    from collections.abc import Iterable

ParametersType = list[tuple[str, ast.AST | None, ParameterKind, str | ast.AST | None]]
"""Type alias for the list of parameters of a function."""


def get_parameters(node: ast.arguments) -> ParametersType:
    parameters: ParametersType = []

    # TODO: Probably some optimizations to do here.
    args_kinds_defaults: Iterable = reversed(
        (
            *zip_longest(
                reversed(
                    (
                        *zip_longest(
                            node.posonlyargs,
                            [],
                            fillvalue=ParameterKind.positional_only,
                        ),
                        *zip_longest(node.args, [], fillvalue=ParameterKind.positional_or_keyword),
                    ),
                ),
                reversed(node.defaults),
                fillvalue=None,
            ),
        ),
    )
    arg: ast.arg
    kind: ParameterKind
    arg_default: ast.AST | None
    for (arg, kind), arg_default in args_kinds_defaults:
        parameters.append((arg.arg, arg.annotation, kind, arg_default))

    if node.vararg:
        parameters.append(
            (
                node.vararg.arg,
                node.vararg.annotation,
                ParameterKind.var_positional,
                "()",
            ),
        )

    # TODO: Probably some optimizations to do here.
    kwargs_defaults: Iterable = reversed(
        (
            *zip_longest(
                reversed(node.kwonlyargs),
                reversed(node.kw_defaults),
                fillvalue=None,
            ),
        ),
    )
    kwarg: ast.arg
    kwarg_default: ast.AST | None
    for kwarg, kwarg_default in kwargs_defaults:
        parameters.append(
            (kwarg.arg, kwarg.annotation, ParameterKind.keyword_only, kwarg_default),
        )

    if node.kwarg:
        parameters.append(
            (
                node.kwarg.arg,
                node.kwarg.annotation,
                ParameterKind.var_keyword,
                "{}",
            ),
        )

    return parameters
