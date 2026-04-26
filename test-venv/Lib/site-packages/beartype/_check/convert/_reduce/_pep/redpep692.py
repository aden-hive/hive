#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`692`-compliant **unpacked typed dictionary reducers** (i.e.,
low-level callables converting ``typing.Unpack[...]`` type hints subscripted by
:pep:`692`-compliant :class:`typing.TypedDict` subclasses to lower-level type
hints more readily consumable by :mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: [PEP 692] Actually implement deep type-checking support for PEP
#692-compliant unpack type hints of the form "**kwargs:
#typing.Unpack[UserTypedDict]". Doing so will *ALMOST CERTAINLY* necessitate a
#new logic pathway for dynamically generating type-checking code efficiently
#type-checking the passed variadic keyword argument dictionary "**kwargs"
#against that user-defined "UserTypedDict". Feasible, but non-trivial. *sigh*

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep692Exception
from beartype.typing import Optional
from beartype._check.metadata.hint.hintsane import (
    HINT_SANE_IGNORABLE,
    HintSane,
)
from beartype._data.typing.datatypingport import Hint
from beartype._util.func.arg.utilfuncargiter import ArgKind

# ....................{ REDUCERS                           }....................
#FIXME: Split into disparate reducers:
#* A new reduce_hint_pep646_unpacked_typevartuple() reducer targeting
#  "HintSignPep646TypeVarTupleUnpacked".
#* A new reduce_hint_pep692() reducer targeting
#  "HintSignPep692TypedDictUnpacked".
#
#For the moment, both should continue reducing to "object". Oh! Wait. Right. We
#need to return "HINT_SANE_IGNORABLE" instead now, right? Make it so, please.
def reduce_hint_pep692(
    hint: Hint,
    arg_kind: Optional[ArgKind],
    exception_prefix: str,
    **kwargs
) -> HintSane:
    '''
    Reduce the passed :pep:`692`-compliant **unpacked typed dictionary** (i.e.,
    hint of the form "typing.Unpack[{typeddict}]" where "{typeddict}" is a
    :class:`typing.TypedDict` subclass) to a more readily digestible hint.

    This reducer effectively ignores this hint by reduction to the ignorable
    :class:`object` superclass (e.g., from ``**kwargs:
    typing.Unpack[UserTypedDict]`` to simply ``**kwargs``). Although non-ideal,
    generating code type-checking these hints is sufficiently non-trivial to
    warrant a (hopefully) temporary delay in doing so properly.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

    Parameters
    ----------
    hint : Hint
        :pep:`646`- or :pep:`692`-compliant unpack type hint to be reduced.
    arg_kind : Optional[ArgKind]
        Either:

        * If this hint annotates a parameter of some callable, that parameter's
          **kind** (i.e., :class:`.ArgKind` enumeration member conveying the
          syntactic class of that parameter, constraining how the callable
          declaring that parameter requires that parameter to be passed).
        * Else, :data:`None`.
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    All remaining keyword-only parameters are silently ignored.

    Returns
    -------
    Hint
        Lower-level type hint currently supported by :mod:`beartype`.

    Raises
    ------
    BeartypeDecorHintPep692Exception
        If this hint annotates a variadic keyword parameter but is *not*
        subscripted by a single :pep:`589`-compliant :class:`typing.TypedDict`
        subclass.
    '''

    # If this hint does *NOT* directly annotate a variadic keyword parameter,
    # this hint is PEP 692-noncompliant. In this case, raise an exception.
    if arg_kind is not ArgKind.VARIADIC_KEYWORD:
        raise BeartypeDecorHintPep692Exception(
            f'{exception_prefix}PEP 692 unpacked typed dictionary {repr(hint)} '
            f'does not annotate variadic keyword parameter (i.e., callable '
            f'parameter of type {repr(arg_kind)} not variadic keyword).'
        )
        # Else, this child hint is a PEP 589-compliant "typing.TypeDict"
        # subclass.
    # Else, this hint directly annotates a variadic keyword parameter.

    # Silently reduce to a noop by returning this ignorable singleton global.
    # While non-ideal, worky is preferable to non-worky.
    return HINT_SANE_IGNORABLE
