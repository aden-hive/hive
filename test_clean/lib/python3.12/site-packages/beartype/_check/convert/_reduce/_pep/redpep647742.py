#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`647`- or :pep:`742`-compliant **type guard** (i.e., objects
created by subscripting the :obj:`typing.TypeGuard` or :obj:`typing.TypeIs` type
hint factories) utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import (
    BeartypeDecorHintPep647Exception,
    BeartypeDecorHintPep742Exception,
)
from beartype.typing import (
    Optional,
    Type,
)
from beartype._data.func.datafuncarg import ARG_NAME_RETURN
from beartype._data.typing.datatypingport import Hint
from beartype._data.hint.sign.datahintsigns import (
    HintSignTypeGuard,
    HintSignTypeIs,
)

# ....................{ REDUCERS                           }....................
def reduce_hint_pep647742(
    hint: Hint,
    pith_name: Optional[str],
    exception_prefix: str,
    **kwargs
) -> Type[bool]:
    '''
    Reduce the passed :pep:`647`-compliant **old-style type guard** (i.e.,
    subscription of the :obj:`typing.TypeGuard` type hint factory) *or*
    :pep:`742`-compliant **new-style type guard** (i.e., subscription of the
    :obj:`typing.TypeIs` type hint factory) to the builtin :class:`bool` class
    as advised by both :pep:`647` and :pep:`742` when performing runtime
    type-checking if this hint annotates the return of some callable (i.e., if
    ``pith_name`` is ``"return"``) *or* raise an exception otherwise (i.e., if
    this hint annotates the return of *no* callable).

    This reducer is intentionally *not* memoized (e.g., by the
    ``@callable_cached`` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        Final type hint to be reduced.
    pith_name : Optional[str]
        Either:

        * If this hint annotates a parameter of some callable, the name of that
          parameter.
        * If this hint annotates the return of some callable, ``"return"``.
        * Else, :data:`None`.
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    All remaining passed arguments are silently ignored.

    Returns
    -------
    Type[bool]
        Builtin :class:`bool` class.

    Raises
    ------
    BeartypeDecorHintPep647Exception
        If this type guard does *not* annotate the return of some callable
        (i.e., if ``pith_name`` is *not* :data:`.ARG_NAME_RETURN`).
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign

    # If this type guard annotates the return of some callable, reduce this type
    # guard to the builtin "bool" class. Sadly, type guards are useless at
    # runtime and exist exclusively as a means of superficially improving the
    # computational intelligence of (...wait for it) static type-checkers.
    if pith_name == ARG_NAME_RETURN:
        return bool
    # Else, this type guard does *NOT* annotate the return of some callable.

    # Sign uniquely identifying this type guard.
    hint_sign = get_hint_pep_sign(hint)

    # Substring suffixing the exception message raised below.
    exception_message_suffix = (
        f'invalid in this type hint context (i.e., '
        f'{repr(hint)} valid only as non-nested return annotation).'
    )

    # If this is a PEP 674-compliant type guard, raise an appropriate exception.
    # Type guards are contextually valid *ONLY* as top-level return annotations.
    if hint_sign is HintSignTypeGuard:
        raise BeartypeDecorHintPep647Exception(
            f'{exception_prefix}PEP 647 type guard {repr(hint)} '
            f'{exception_message_suffix}'
        )

    # Else, this *MUST* be a PEP 742-compliant type guard (by process of
    # elimination). Raise an appropriate exception.
    assert hint_sign is HintSignTypeIs, f'{repr(hint)} not PEP 742 type guard.'
    raise BeartypeDecorHintPep742Exception(
        f'{exception_prefix}PEP 742 type guard {repr(hint)} '
        f'{exception_message_suffix}'
    )
