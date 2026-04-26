#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **jaxtyping utilities** (i.e., low-level callables handling the
third-party :mod:`jaxtyping` package).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: The top-level of this module should avoid importing from third-party
# optional libraries, both because those libraries cannot be guaranteed to be
# either installed or importable here *AND* because those imports are likely to
# be computationally expensive, particularly for imports transitively importing
# C extensions (e.g., anything from NumPy or SciPy).
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
from beartype._cave._cavefast import FunctionType
from collections.abc import Callable

# ....................{ TESTERS                            }....................
#FIXME: *OVERKILL.* This functionality should be folded into the existing
#is_object_blacklisted() tester. Doing so will probably
#necessitate generalizing that tester to accommodate the specific ad-hoc
#heuristic required by this tester here. *shrug*
def is_func_jaxtyped(func: Callable) -> bool:
    '''
    :data:`True` only if the passed callable is **jaxtyped** (i.e., has already
    been decorated by the third-party :func:`jaxtyping.jaxtyped` decorator).

    Parameters
    ----------
    func : Callable
        Callable to be inspected.

    Returns
    -------
    bool
        :data:`True` only if that callable is jaxtyped.
    '''
    assert callable(func), f'{repr(func)} uncallable.'

    # Return true only if...
    return (
        # The passed callable is a pure-Python function *AND*...
        isinstance(func, FunctionType) and

        # The actual lexical global scope accessible to this function declares
        # this function to be defined by the third-party "jaxtyping" package,
        # this function is a low-level runtime type-checking wrapper function
        # previously created and returned by the @jaxtyping.jaxtyped decorator
        # at the time that it decorated a user-defined function. In this case,
        # this function is jaxtyped.
        #
        # Note that:
        # * *ALL* pure-Python functions are guaranteed to define the
        #   "__globals__" dunder attribute. Ergo, this attribute may be safely
        #   *DIRECTLY* accessed.
        # * Pure-Python functions are *NOT* guaranteed to define the
        #   "__package__" dunder attribute in their lexical global scopes. Ergo,
        #   this attribute may only be safely *INDIRECTLY* accessed.
        func.__globals__.get('__package__') == 'jaxtyping'
    )
