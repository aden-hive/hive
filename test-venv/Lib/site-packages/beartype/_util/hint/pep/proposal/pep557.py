#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`557`-compliant type hint utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep557Exception
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import TypeException
from beartype._data.hint.sign.datahintsigns import (
    HintSignPep557DataclassInitVar)

# ....................{ GETTERS                            }....................
def get_hint_pep557_initvar_arg(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep557Exception,
    exception_prefix: str = '',
) -> Hint:
    '''
    PEP-compliant child type hint subscripting the passed :pep:`557`-compliant
    **dataclass initialization-only instance variable type hint** (i.e.,
    subscription of the :class:`dataclasses.InitVar` type hint factory).

    This getter is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation trivially reduces to
    an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`.BeartypeDecorHintPep557Exception`.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    Hint
        PEP-compliant child type hint subscripting this parent type hint.

    Raises
    ------
    BeartypeDecorHintPep557Exception
        If this object is *not* a dataclass initialization-only instance
        variable type hint.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none

    # Sign uniquely identifying this hint if this hint is identifiable *OR*
    # "None" otherwise.
    hint_sign = get_hint_pep_sign_or_none(hint)

    # If this hint is *NOT* a dataclass initialization-only instance variable
    # type hint, raise an exception.
    if hint_sign is not HintSignPep557DataclassInitVar:
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')
        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} not '
            f'PEP 557-compliant "dataclasses.TypeVar" instance.'
        )
    # Else, this hint is such a hint.

    # Return the child type hint subscripting this parent type hint. Yes, this
    # hint exposes this child via a non-standard instance variable rather than
    # the "__args__" dunder tuple standardized by PEP 484.
    return hint.type  # type: ignore[attr-defined]
