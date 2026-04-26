#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`696`-compliant **type parameter default** (i.e., child type
hints specified as the default type hints to which type parameters with no other
concrete mappings default under Python >= 3.13) utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep696Exception
from beartype._data.kind.datakindiota import SENTINEL
from beartype._data.typing.datatyping import (
    Pep484612646TypeArgPacked,
    TypeException,
)
from beartype._data.typing.datatypingport import (
    # Hint,
    HintOrSentinel,
)
from beartype._util.py.utilpyversion import IS_PYTHON_AT_LEAST_3_13

# ....................{ GETTERS                            }....................
#FIXME: Unit test us up, please. *sigh*
def get_hint_pep484612646_typearg_packed_default_or_sentinel(
    # Mandatory parameters.
    hint: Pep484612646TypeArgPacked,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep696Exception,
    exception_prefix: str = '',
) -> HintOrSentinel:
    '''
    :pep:`696`-compliant **type parameter default** (i.e., child hint that may
    be an unquoted forward reference referring to a currently undefined type,
    initially passed as the value of the optional ``default`` parameter on the
    construction of the passed type parameter) defined on the passed **type
    parameter** (i.e., :pep:`484`-compliant type variable or
    :pep:`646`-compliant type variable tuple) if any *or* the sentinel
    placeholder otherwise (i.e., if no default was defined on this type
    parameter).

    This getter intentionally returns the sentinel placeholder (rather than
    :data:`None`) when either of these attributes is the null subhint value.
    Why? To enable callers to distinguish between type parameters lacking
    defaults and type parameters whose defaults are actually :data:`None`, which
    is (of course) a valid :pep:`484`-compliant type hint.

    This getter is intentionally *not* memoized (e.g., by the
    ``@callable_cached`` decorator), as the implementation trivially reduces to
    a one-liner.

    Parameters
    ----------
    hint : Pep484612646TypeArgPacked
        Type parameter to be inspected.
    exception_cls : TypeException, default: BeartypeDecorHintPep696Exception
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`.BeartypeDecorHintPep696Exception`.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    HintOrSentinel
        Either:

        * If this type parameter defines a default, that default.
        * Else, the sentinel placeholder.

    Raises
    ------
    exception_cls
        If the passed type hint is *not* a type parameter.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.proposal.pep484612646 import (
        die_unless_hint_pep484612646_typearg_packed)
    from beartype._util.hint.pep.proposal.pep749 import (
        get_hint_pep749_subhint_optional)

    # If this hint is *NOT* a packed type parameter, raise an exception.
    die_unless_hint_pep484612646_typearg_packed(
        hint=hint,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this hint is a packed type parameter.

    # Child hint to which this type parameter defaults if this type parameter
    # has a default *OR* the sentinel placeholder otherwise.
    hint_default = SENTINEL

    # If the active Python interpreter targets Python >= 3.13 and thus supports
    # PEP 696.
    if IS_PYTHON_AT_LEAST_3_13:
        # Defer version-specific imports.
        from beartype.typing import NoDefault  # pyright: ignore

        # Child hint to which this type parameter defaults if this type
        # parameter has a default *OR* the sentinel placeholder otherwise.
        hint_default = get_hint_pep749_subhint_optional(
            hint=hint,  # pyright: ignore
            subhint_name_dynamic='evaluate_default',
            subhint_name_static='__default__',
            subhint_value_null=NoDefault,
            exception_cls=exception_cls,
            exception_prefix=exception_prefix,
        )
    # Else, the active Python interpreter targets Python < 3.12 and thus fails
    # to support PEP 696.

    # Return this type parameter default.
    return hint_default
