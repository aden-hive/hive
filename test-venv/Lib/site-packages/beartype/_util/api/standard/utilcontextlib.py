#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :mod:`contextlib` utilities (i.e., low-level callables handling the
standard :mod:`contextlib` module).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Any,
    Optional,
)
from beartype._util.func.utilfunccodeobj import (
    get_func_codeobj_or_none,
    get_func_codeobj_basename,
)
from beartype._util.py.utilpyversion import IS_PYTHON_AT_MOST_3_10
from collections.abc import (
    Callable,
    # Generator,
)

# ....................{ GETTERS                            }....................
#FIXME: Generalize into a new get_func_contextlib_contextmanager_or_none()
#function behaving as follows:
#* If the passed callable is decorated by @contextlib.contextmanager, return
#  the contextlib.contextmanager() decorator function.
#* If the passed callable is decorated by @contextlib.asynccontextmanager, return
#  the contextlib.asynccontextmanager() decorator function.
#* Else, return "None".
#FIXME: Unit test us up, please.
def get_func_contextlib_contextmanager_or_none(func: Any) -> Optional[Callable]:
    '''
    :mod:`contextlib` decorator underlying the passed object if this object is a
    :mod:`contextlib`-based **isomorphic decorator closure** (i.e., closure both
    defined and returned by either the standard
    :func:`contextlib.contextmanager` or :func:`contextlib.asynccontextmanager`
    decorators where that closure isomorphically preserves both the number and
    types of all passed parameters and returns by accepting only a variadic
    positional argument and variadic keyword argument) *or* :data:`None`
    otherwise (i.e., if this object is *not* such a closure).

    Specifically, this getter returns either:

    * If the passed object was produced by a prior call to the
      :func:`contextlib.contextmanager` decorator, that decorator as a function.
    * If the passed object was produced by a prior call to the
      :func:`contextlib.asynccontextmanager` decorator, that decorator as a
      function.
    * Else, :data:`None`.

    This getter enables callers to detect when a user-defined callable has been
    decorated by a :mod:`contextlib` decorator and thus has a mismatch between
    the type hints annotating that decorated callable and the type of the object
    created and returned by that decorated callable.

    Caveats
    -------
    **This getter only supports Python >= 3.11.** Under Python <= 3.10, this
    getter erroneously returns **false negatives** (i.e., :data:`False` even
    when the passed callable is a valid :func:`contextlib.contextmanager`-based
    isomorphic decorator closure). Why? Because this getter detects these
    closures by internally testing the ``co_qualname`` instance variable on the
    code object of the passed callable, which only exists under Python >= 3.11.
    This is not the fault of :mod:`beartype` and *totally* outside our control.

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    Optional[Callable]
        Either:

        * If this object is a :func:`contextlib.asynccontextmanager`-based
          isomorphic decorator closure, :func:`contextlib.asynccontextmanager`.
        * If this object is a :func:`contextlib.contextmanager`-based isomorphic
          decorator closure, :func:`contextlib.contextmanager`.
        * Else, :data:`None`.

    See Also
    --------
    :obj:`beartype._data.func.datafunc.CONTEXTLIB_CONTEXTMANAGER_CO_NAME_QUALNAME`
        Further discussion.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.utilfunctest import is_func_closure

    # If either...
    if (
        # The active Python interpreter targets Python < 3.10 and thus fails to
        # define the "co_qualname" attribute on code objects required to
        # robustly implement this test *OR*...
        IS_PYTHON_AT_MOST_3_10 or
        # The passed callable is *NOT* a closure...
        not is_func_closure(func)
    ):
        # Then immediately return "None".
        return None
    # Else, that callable is a closure.

    # Code object underlying that callable as is (rather than possibly unwrapped
    # to another code object entirely) if that callable is pure-Python *OR*
    # "None" otherwise (i.e., if that callable is C-based).
    func_codeobj = get_func_codeobj_or_none(func)

    # If that callable is C-based, immediately return "None".
    if func_codeobj is None:
        return None
    # Else, that callable is pure-Python.

    # Defer heavyweight getter-specific imports with potential side effects --
    # notably, increased costs to space and time complexity.
    from beartype._data.api.standard.datacontextlib import (
        CONTEXTLIB_CONTEXTMANAGER_CODEOBJ_NAME_TO_DECORATOR)

    # Fully-qualified name of this code object.
    func_codeobj_name = get_func_codeobj_basename(func_codeobj)

    # Either:
    # * If the fully-qualified name of this code object is that of an isomorphic
    #   decorator closure created and returned by a standard "contextlib"
    #   decorator, that decorator.
    # * Else, "None".
    contextlib_decorator = (
        CONTEXTLIB_CONTEXTMANAGER_CODEOBJ_NAME_TO_DECORATOR.get(
            func_codeobj_name))

    # Return this decorator.
    #
    # Note that we *COULD* technically also explicitly test whether that
    # callable satisfies the is_func_wrapper_isomorphic() getter -- but that
    # there's no benefit and a minor efficiency cost to doing so.
    return contextlib_decorator  # type: ignore[return-value]
