#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`593`-compliant **type metahint reducers** (i.e., low-level
low-level callables converting higher-level type hints created by subscripting
the :obj:`typing.Annotated` type hint factory to lower-level type hints more
readily consumable by :mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.typing.datatypingport import Hint
from beartype._util.hint.pep.proposal.pep593 import (
    get_hint_pep593_metahint,
    is_hint_pep593_beartype,
)

# ....................{ REDUCERS                           }....................
def reduce_hint_pep593(hint: Hint, exception_prefix: str) -> Hint:
    '''
    Reduce the passed :pep:`593`-compliant **type metahint** (i.e., subscription
    of the :obj:`typing.Annotated` hint factory) to a lower-level hint if this
    metahint contains *no* **beartype validators** (i.e., subscriptions of
    :mod:`beartype.vale` factories).

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation trivially reduces to a
    one-liner.

    Parameters
    ----------
    hint : Hint
        Type hint to be reduced.
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    Returns
    -------
    Hint
        Lower-level type hint currently supported by :mod:`beartype`.
    '''
    # print(f'Reducing non-beartype PEP 593 type hint {repr(hint)}...')

    # Return either...
    return (
        # If this metahint is beartype-specific, preserve this hint as is for
        # subsequent handling elsewhere;
        hint
        if is_hint_pep593_beartype(hint) else
        # Else, this metahint is beartype-agnostic and thus irrelevant to us. In
        # this case, ignore all annotations on this hint by reducing this hint
        # to the lower-level hint it annotates.
        get_hint_pep593_metahint(hint=hint, exception_prefix=exception_prefix)
    )
