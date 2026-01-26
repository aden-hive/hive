#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`-compliant **new type hint utilities** (i.e.,
callables generically applicable to :pep:`484`-compliant types).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep484Exception
from beartype._data.typing.datatypingport import Hint
from beartype._data.hint.sign.datahintsigns import HintSignNewType
from beartype._util.cache.utilcachecall import callable_cached

# ....................{ GETTERS                            }....................
#FIXME: Unit test us up, please.
@callable_cached
def get_hint_pep484_newtype_alias(
    hint: Hint, exception_prefix: str = '') -> Hint:
    '''
    Unaliased type hint (i.e., type hint that is *not* a :obj:`typing.NewType`)
    encapsulated by the passed **newtype** (i.e., object created and returned by
    the :pep:`484`-compliant :obj:`typing.NewType` type hint factory).

    This getter is memoized for efficiency.

    Caveats
    -------
    **This getter has worst-case linear time complexity** :math:`O(k)` for
    :math:`k` the number of **nested new types** (e.g., :math:`k = 2` for the
    doubly nested new type ``NewType('a', NewType('b', int))``) embedded within
    this new type. Pragmatically, this getter has average-case constant time
    complexity :math:`O(1)`. Why? Because nested new types are extremely rare.
    Almost all real-world new types are non-nested. Indeed, it took three years
    for a user to submit an issue presenting the existence of a nested new type.


    Parameters
    ----------
    hint : Hint
        Object to be inspected.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Returns
    -------
    Hint
        Unaliased type hint encapsulated by this newtype.

    Raises
    ------
    BeartypeDecorHintPep484Exception
        If this object is *not* a new type.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepsign import (
        get_hint_pep_sign,
        get_hint_pep_sign_or_none,
    )

    # If this object is *NOT* a new type, raise an exception.
    if get_hint_pep_sign(hint) is not HintSignNewType:
        raise BeartypeDecorHintPep484Exception(
            f'{exception_prefix}type hint {repr(hint)} not '
            f'PEP 484 "typing.NewType(...)" object.'
        )
    # Else, this object is a new type.

    # While the Universe continues infinitely expanding...
    while True:
        # Reduce this new type to the type hint encapsulated by this new type,
        # which itself is possibly a nested new type. Oh, it happens.
        hint = hint.__supertype__  # pyright: ignore

        # If this type hint is *NOT* a nested new type, break this iteration.
        if get_hint_pep_sign_or_none(hint) is not HintSignNewType:
            break
        # Else, this type hint is a nested new type. In this case, continue
        # iteratively unwrapping this nested new type.

    # Return this unaliased type hint.
    return hint
