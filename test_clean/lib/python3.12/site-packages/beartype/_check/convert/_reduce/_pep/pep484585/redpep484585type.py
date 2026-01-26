#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`- and :pep:`585`-compliant **subclass hint reducers** (i.e.,
low-level callables converting higher-level subscripted and unsubscripted
:pep:`484`-compliant ``typing.Type[...]`` and :pep:`585`-compliant ``type[...]``
hints to lower-level hints more readily consumable by :mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._check.metadata.hint.hintsane import HINT_SANE_IGNORABLE
from beartype._data.typing.datatypingport import Hint
from beartype._util.hint.pep.proposal.pep484585.pep484585 import (
    get_hint_pep484585_arg)

# PEP 484-specific type hint factories intentionally imported as such.
from typing import (
    Type as typing_Type,
)

# ....................{ REDUCERS                           }....................
def reduce_hint_pep484585_type(
    hint: Hint, exception_prefix: str, **kwargs) -> Hint:
    '''
    Reduce the passed :pep:`484`- or :pep:`585`-compliant **subclass hint**
    (i.e., hint constraining objects to subclass that superclass) to the
    :class:`type` superclass if that hint is subscripted by an ignorable child
    hint *or* preserve this hint as is otherwise (i.e., if this hint is *not*
    subscripted by an ignorable child hint).

    This reducer is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as reducers cannot be memoized.

    Parameters
    ----------
    hint : Hint
        Subclass type hint to be reduced.
    exception_prefix : str
        Human-readable label prefixing the representation of this object in the
        exception message.

    All remaining passed keyword parameters are silently ignored.

    Returns
    -------
    Hint
        Lower-level hint reduced from this subclass hint.

    Raises
    ------
    BeartypeDecorHintPep484585Exception
        If this hint is neither a :pep:`484`- nor :pep:`585`-compliant subclass
        hint.
    '''

    # Avoid circular import dependencies.
    from beartype._check.convert._reduce._pep.pep484.redpep484 import (
        reduce_hint_pep484_deprecated)
    from beartype._check.convert._reduce.redmain import reduce_hint_child

    # If this is a PEP 484-compliant subclass hint, this hint has been
    # deprecated by PEP 585. In this case, issue a non-fatal warning.
    reduce_hint_pep484_deprecated(hint=hint, exception_prefix=exception_prefix)

    # If this hint is the unsubscripted PEP 484-compliant subclass type hint,
    # immediately reduce this hint to the "type" superclass.
    #
    # Note that this is *NOT* merely a nonsensical optimization. The
    # implementation of the unsubscripted PEP 484-compliant subclass type hint
    # significantly differs across Python versions. Under some but *NOT* all
    # supported Python versions (notably, Python 3.7 and 3.8), the "typing"
    # module subversively subscripts this hint by a type variable; under all
    # others, this hint remains unsubscripted. In the latter case, passing this
    # hint to the subsequent get_hint_pep484585_args() call would erroneously
    # raise an exception.
    if hint is typing_Type:
        # print(f'Reducing subclass hint {hint} to "type"...')
        hint = type  # pyright: ignore
    # Else, this hint is *NOT* the unsubscripted PEP 484-compliant subclass
    # type hint. In this case...
    else:
        # Superclass subscripting this hint.
        #
        # Note that we intentionally do *NOT* call the high-level
        # get_hint_pep484585_type_superclass() getter here, as the
        # validation performed by that function would raise exceptions for
        # various child type hints that are otherwise permissible (e.g.,
        # "typing.Any").
        hint_child = get_hint_pep484585_arg(
            hint=hint, exception_prefix=exception_prefix)

        # Lower-level child hint reduced from this higher-level child hint.
        hint_child_reduced = reduce_hint_child(hint_child, kwargs)

        # If this child hint is ignorable, reduce this subclass hint to merely
        # the "type" superclass.
        if hint_child_reduced is HINT_SANE_IGNORABLE:
            # print(f'Reducing subclass hint {hint} to "type"...')
            hint = type  # pyright: ignore
        # Else, this child hint is unignorable. Preserve this hint as is.

        #FIXME: [SPEED] Consider uncommenting this optimization at a later date.
        #Doing so is complicated by the fact that it's currently insufficient;
        #we'd also need to consider the case in which "hint_child_reduced" is
        #metadata encapsulating a child hint reduction. *sigh*
        # # If this child hint was reduced to a different hint, preserve this
        # # reduction by re-subscripting this type hint factory by this reduction.
        # elif hint_child_reduced is not hint_child:
        #     hint = type[hint_child_reduced]
        # # Else, this child hint is irreducible. In this case, preserve this
        # # hint as is.

    # Return this possibly reduced hint.
    return hint
