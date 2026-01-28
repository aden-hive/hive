#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`-compliant **reducers** (i.e., low-level callables
converting :pep:`484`-compliant type hints to lower-level type hints more
readily consumable by :mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.meta import URL_PEP585_DEPRECATIONS
from beartype.roar import BeartypeDecorHintPep585DeprecationWarning
from beartype._cave._cavefast import NoneType
from beartype._check.metadata.hint.hintsane import (
    HINT_SANE_IGNORABLE,
    HintSane,
)
from beartype._data.typing.datatypingport import Hint
from beartype._data.hint.datahintrepr import (
    HINTS_PEP484_REPR_PREFIX_DEPRECATED)
from beartype._util.error.utilerrwarn import issue_warning

# ....................{ REDUCERS                           }....................
def reduce_hint_pep484_deprecated(
    hint: Hint, exception_prefix: str, **kwargs) -> Hint:
    '''
    Preserve the passed :pep:`484`- or :pep:`585`-compliant type hint as is
    while emitting one non-fatal deprecation warning for this type hint if
    deprecated, due to being a :pep:`484`-compliant type hint obsoleted by an
    equivalent :pep:`585`-compliant type hint.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as doing so would prevent this reducer from
    emitting one warning per deprecated type hint.

    Parameters
    ----------
    hint : Hint
        Type hint to be reduced.
    exception_prefix : str
        Human-readable substring prefixing emitted warning messages.

    All remaining passed arguments are silently ignored.

    Returns
    -------
    Hint
        This hint unmodified.

    Warns
    -----
    BeartypeDecorHintPep585DeprecationWarning
        If this is a :pep:`484`-compliant type hint is deprecated by :pep:`585`.
    '''
    # print(f'Testing PEP 484 type hint {repr(hint)} for PEP 585 deprecation...')
    # print(f'{HINTS_PEP484_REPR_PREFIX_DEPRECATED}')

    # Avoid circular import dependencies.
    from beartype._util.hint.utilhintget import get_hint_repr

    # Machine-readable representation of this hint.
    hint_repr = get_hint_repr(hint)

    # Substring of the machine-readable representation of this hint preceding
    # the first "[" delimiter if this representation contains that delimiter
    # *OR* this representation as is otherwise.
    #
    # Note that the str.partition() method has been profiled to be the optimally
    # efficient means of parsing trivial prefixes.
    hint_repr_bare = hint_repr.partition('[')[0]

    # If this hint is a PEP 484-compliant type hint originating from an origin
    # type (e.g., "typing.List[int]"), this hint has been deprecated by the
    # equivalent PEP 585-compliant type hint (e.g., "list[int]"). In this
    # case...
    if hint_repr_bare in HINTS_PEP484_REPR_PREFIX_DEPRECATED:
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Emit a non-fatal PEP 585-specific deprecation warning.
        issue_warning(
            cls=BeartypeDecorHintPep585DeprecationWarning,
            message=(
                f'{exception_prefix}PEP 484 type hint {repr(hint)} '
                f'deprecated by PEP 585. '
                f'This hint is scheduled for removal in the first Python '
                f'version released after October 5th, 2025. To resolve this, '
                f'import this hint from "beartype.typing" rather than "typing". '
                f'For further commentary and alternatives, see also:\n'
                f'    {URL_PEP585_DEPRECATIONS}'
            ),
        )
    # Else, this hint is *NOT* deprecated. In this case, reduce to a noop.

    # Preserve this hint as is, regardless of deprecation.
    return hint

# ....................{ REDUCERS ~ singleton               }....................
def reduce_hint_pep484_any(hint: Hint, exception_prefix: str) -> HintSane:
    '''
    Reduce the passed :pep:`484`-compliant :obj:`typing.Any` singleton to the
    ignorable :data:`.HINT_SANE_IGNORABLE` singleton.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        :obj:`typing.Any` hint to be reduced.
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    Returns
    -------
    HintSane
        Ignorable :data:`.HINT_SANE_IGNORABLE` singleton.
    '''

    # Unconditionally ignore the "Any" singleton.
    return HINT_SANE_IGNORABLE


# Note that this reducer is intentionally typed as returning "type" rather than
# "NoneType". While the former would certainly be preferable, mypy erroneously
# emits false positives when this reducer is typed as returning "NoneType":
#     beartype._util.hint.pep.proposal.pep484.pep484.py:190: error: Variable
#     "beartype._cave._cavefast.NoneType" is not valid as a type [valid-type]
def reduce_hint_pep484_none(hint: Hint, exception_prefix: str) -> type:
    '''
    Reduce the passed :pep:`484`-compliant :data:`None` singleton to the type of
    :data:`None` (i.e., the builtin :class:`types.NoneType` class).

    While *not* explicitly defined by the :mod:`typing` module, :pep:`484`
    explicitly supports this singleton:

        When used in a type hint, the expression :data:`None` is considered
        equivalent to ``type(None)``.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        :data:`None` hint to be reduced.
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    Returns
    -------
    type[NoneType]
        Type of the :data:`None` singleton.
    '''
    assert hint is None, f'Type hint {hint} not "None" singleton.'

    # Unconditionally return the type of the "None" singleton.
    return NoneType
