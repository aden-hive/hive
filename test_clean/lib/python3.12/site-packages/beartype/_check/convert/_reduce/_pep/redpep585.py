#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`585`-compliant **type alias reducers** (i.e., low-level
callables converting higher-level objects created via the ``type`` statement
under Python >= 3.12 to lower-level type hints more readily consumable by
:mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.typing.datatypingport import Hint
from beartype._util.hint.pep.utilpepget import get_hint_pep_origin_type

# ....................{ REDUCERS                           }....................
#FIXME: Unit test us up, please.
#FIXME: Heavily refactor according to the discussion in the "redmain" submodule,
#please. *sigh*
def reduce_hint_pep585_builtin_subbed_unknown(
    hint: Hint, exception_prefix: str) -> type:
    '''
    Reduce the passed :pep:`585`-compliant **unrecognized subscripted builtin
    type hints** (i.e., C-based type hints that are *not* isinstanceable types,
    instantiated by subscripting pure-Python origin classes subclassing the
    C-based :class:`types.GenericAlias` superclass such that those classes are
    unrecognized by :mod:`beartype` and thus *not* type-checkable as is) to
    their unsubscripted origin classes (which are almost always pure-Python
    isinstanceable types and thus type-checkable as is).

    This reducer is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        Type hint to be reduced.
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    Returns
    -------
    type
        Unsubscripted origin class originating this unrecognized subscripted
        builtin type hint.
    '''

    # Pure-Python origin class originating this unrecognized subscripted builtin
    # type hint if this hint originates from such a class *OR* raise an
    # exception otherwise (i.e., if this hint originates from *NO* such class).
    origin_type = get_hint_pep_origin_type(hint)

    # Return this origin.
    return origin_type
