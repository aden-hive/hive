#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **abstract syntax tree (AST) testers** (i.e., low-level callables
testing various properties of various nodes in the currently visited AST).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.typing.datatyping import NodeCallable

# ....................{ TESTERS                            }....................
def is_node_callable_typed(node: NodeCallable) -> bool:
    '''
    :data:`True` only if the passed **callable node** (i.e., node signifying the
    definition of a pure-Python function or method) is **typed** (i.e.,
    annotated by a return type hint and/or one or more parameter type hints).

    Parameters
    ----------
    node : NodeCallable
        Callable node to be tested.

    Returns
    -------
    bool
        :data:`True` only if this callable node is typed.
    '''

    # Note that this algorithm is intentionally implemented in an unintuitive
    # order so as to increase the likelihood of efficiently deciding this
    # problem in best-case O(1) time. Specifically:
    # * It is most efficient to test whether that callable is annotated by a
    #   return type hint.
    # * It is next-most efficient to test whether that callable accepts a
    #   variadic positional or keyword argument annotated by a type hint.
    # * It is least efficient to test whether that callable accepts a
    #   non-variadic parameter annotated by a type hint, as doing so requires
    #   O(n) iteration for "n" the number of such arguments.
    #
    # Lastly, note that we could naively avoid doing this entirely and instead
    # unconditionally decorate *ALL* callables by @beartype -- in which case
    # @beartype would simply reduce to a noop for untyped callables annotated by
    # *NO* type hints. Technically, that works. Pragmatically, that would almost
    # certainly be slower than the current approach under the common assumption
    # that any developer annotating one or more non-variadic parameters of a
    # callable would also annotate the return of that callable -- in which case
    # this detection reduces to O(1) time complexity. Even where this is *NOT*
    # the case, however, this is still almost certainly slightly faster or of an
    # equivalent speed to the naive approach. Why? Because treating untyped
    # callables as typed would needlessly:
    # * Increase space complexity by polluting this AST with needlessly many
    #   "Name" child nodes performing untyped @beartype decorations.
    # * Increase time complexity by instantiating, initializing, and inserting
    #   (the three dread i's) those nodes.
    #
    # Admittedly, this approach is *CONSIDERABLY* slower for untyped callables,
    # where this detection exhibits worst-case O(n) time complexity. In theory,
    # the "beartype.claw" API that calls this tester function once per callable
    # should *NEVER* be applied to untyped callables. In practice, that API
    # almost certainly will be. We (largely) consider that the responsibility of
    # the caller, however. Beartype can't be faulted for optimizing for the
    # ideal case of well-typed packages... *CAN IT*!?!? o_O

    # If the return of that callable is typed, that callable is typed. In this
    # case, immediately and efficiently return true.
    if node.returns:
        return True
    # Else, the return of that callable is untyped.

    # Child arguments node of all arguments accepted by that callable.
    node_arg_nodes = node.args

    # If either...
    #
    # Note that PEP 484-compliant typed variadic positional arguments (e.g.,
    # "*args: str") are considerably more common than PEP 692-compliant typed
    # variadic keyword arguments (e.g., "**kwargs: SomeTypedDict", where
    # "SomeTypedDict" is a user-defined "typing.TypedDict" subclass). Ergo, we
    # intentionally detect typed variadic positional arguments *BEFORE* typed
    # variadic keyword arguments.
    if (
        (
            # That callable accepts a variadic positional argument *AND*...
            node_arg_nodes.vararg and
            # That parameter is typed...
            node_arg_nodes.vararg.annotation
        # *OR*...
        ) or
        (
            # That callable accepts a variadic keyword argument *AND*...
            node_arg_nodes.kwarg and
            # That parameter is typed...
            node_arg_nodes.kwarg.annotation
        )
    # That callable is typed. In this case, return true.
    ):
        return True
    # Else, that callable is still possibly untyped.

    # Fallback to deciding whether that callable accepts one or more typed
    # non-variadic parameters. Since doing is considerably more computationally
    # expensive, we do so *ONLY* as needed.
    #
    # Note that manual iteration is considerably more efficient than more
    # syntactically concise any() and all() generator expressions.
    #
    # Specifically, if that callable accepts non-variadic flexible parameters...
    if node_arg_nodes.args:
        # For each non-variadic flexible parameter...
        for node_arg_nonvar in node_arg_nodes.args:
            # If this parameter is typed, that callable is typed. In this case,
            # return true.
            if node_arg_nonvar.annotation:
                return True
            # Else, this parameter is untyped. Continue to the next.
    # Else, that callable is still possibly untyped.

    # If that callable accepts non-variadic keyword-only parameters...
    if node_arg_nodes.kwonlyargs:
        # For each non-variadic keyword-only parameter...
        for node_arg_nonvar in node_arg_nodes.kwonlyargs:
            # If this parameter is typed, that callable is typed. In this case,
            # return true.
            if node_arg_nonvar.annotation:
                return True
            # Else, this parameter is untyped. Continue to the next.
    # Else, that callable is still possibly untyped.

    # If that callable accepts non-variadic positional-only parameters...
    if node_arg_nodes.posonlyargs:
        # For each non-variadic positional-only parameter...
        for node_arg_nonvar in node_arg_nodes.posonlyargs:
            # If this parameter is typed, that callable is typed. In this case,
            # return true.
            if node_arg_nonvar.annotation:
                return True
            # Else, this parameter is untyped. Continue to the next.
    # Else, that callable is now known to be untyped.

    # Return false.
    return False
