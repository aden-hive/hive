#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`484`-compliant :attr:`typing.NoReturn` **type hint violation
describers** (i.e., functions returning human-readable strings explaining
violations of :pep:`484`-compliant :attr:`typing.NoReturn` type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import Callable
from beartype._data.hint.sign.datahintsigns import HintSignNoReturn
from beartype._check.error.errcause import ViolationCause
from beartype._util.text.utiltextlabel import label_callable
from beartype._util.text.utiltextrepr import represent_pith

# ....................{ GETTERS                            }....................
def find_cause_pep484_noreturn(cause: ViolationCause) -> ViolationCause:
    '''
    Output cause describing describing the failure of the decorated callable to
    *not* return a value in violation of the passed :pep:`484`-compliant
    :attr:`typing.NoReturn` type hint.

    Parameters
    ----------
    cause : ViolationCause
        Input cause providing this data.

    Returns
    -------
    ViolationCause
        Output cause type-checking this data.
    '''
    assert isinstance(cause, ViolationCause), f'{repr(cause)} not cause.'
    assert cause.hint_sign is HintSignNoReturn, (
        f'{repr(cause.hint)} not "HintSignNoReturn".')

    # Decorated callable originating this violation.
    func: Callable = cause.func  # type: ignore[assignment]

    # Output cause to be returned, permuted from this input cause such that the
    # justification is a human-readable string describing this failure.
    cause_return = cause.permute_cause(cause_str_or_none=(
        f'{label_callable(func)} annotated by PEP 484 return type hint '
        f'"typing.NoReturn" returned {represent_pith(cause.pith)}'
    ))

    # Return this cause.
    return cause_return
