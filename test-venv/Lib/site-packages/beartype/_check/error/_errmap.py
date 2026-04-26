#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype exception data** (i.e., high-level globals and constants leveraged
throughout the :mod:`beartype._check.error` subpackage).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Callable,
    Dict,
    Optional,
)
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._check.error.errcause import ViolationCause

# ....................{ GLOBALS                            }....................
# Initialized with automated inspection below in the _init() function.
HINT_SIGN_TO_GET_CAUSE_FUNC: Dict[
    Optional[HintSign], Callable[[ViolationCause], ViolationCause]] = {}
'''
Dictionary mapping each **sign** (i.e., arbitrary object uniquely identifying a
category of type hints) to a private getter function defined by this submodule
whose signature matches that of the :func:`._find_cause` function and
which is dynamically dispatched by that function to describe type-checking
failures specific to that unsubscripted :mod:`typing` attribute.
'''

# ....................{ PRIVATE ~ initializers             }....................
def _init() -> None:
    '''
    Initialize this submodule.
    '''

    # ....................{ IMPORTS                        }....................
    # Defer heavyweight imports.
    from beartype._data.hint.sign.datahintsigns import (
        HintSignAnnotated,
        HintSignForwardRef,
        HintSignLiteral,
        HintSignNoReturn,
        HintSignPep484585GenericUnsubbed,
        HintSignPep484585TupleFixed,
        HintSignType,
    )
    from beartype._data.hint.sign.datahintsignset import (
        HINT_SIGNS_MAPPING,
        HINT_SIGNS_ORIGIN_ISINSTANCEABLE,
        HINT_SIGNS_CONTAINER_ARGS_1,
        HINT_SIGNS_UNION,
    )
    from beartype._check.error._nonpep.errnonpeptype import (
        find_cause_instance_type_forwardref,
        find_cause_nonpep,
        find_cause_type_instance_origin,
    )
    from beartype._check.error._pep.errpep484604 import (
        find_cause_pep484604_union)
    from beartype._check.error._pep.errpep586 import find_cause_pep586_literal
    from beartype._check.error._pep.errpep593 import find_cause_pep593_annotated
    from beartype._check.error._pep.pep484.errpep484noreturn import (
        find_cause_pep484_noreturn)
    from beartype._check.error._pep.pep484585.errpep484585container import (
        find_cause_pep484585_container_args_1,
        find_cause_pep484585_tuple_fixed,
    )
    from beartype._check.error._pep.pep484585.errpep484585generic import (
        find_cause_pep484585_generic_unsubbed)
    from beartype._check.error._pep.pep484585.errpep484585mapping import (
        find_cause_pep484585_mapping)
    from beartype._check.error._pep.pep484585.errpep484585subclass import (
        find_cause_pep484585_subclass)

    # ....................{ FALLBACKS                      }....................
    # Map each originative sign to the appropriate finder *BEFORE* any other
    # mappings. This is merely a generalized fallback subsequently replaced by
    # sign-specific finders below.
    for hint_sign in HINT_SIGNS_ORIGIN_ISINSTANCEABLE:
        HINT_SIGN_TO_GET_CAUSE_FUNC[hint_sign] = find_cause_type_instance_origin

    # Map each 1-argument container sign to its corresponding finder.
    for hint_sign in HINT_SIGNS_CONTAINER_ARGS_1:
        HINT_SIGN_TO_GET_CAUSE_FUNC[hint_sign] = (
            find_cause_pep484585_container_args_1)

    # Map each 2-argument mapping sign to its corresponding finder.
    for hint_sign in HINT_SIGNS_MAPPING:
        HINT_SIGN_TO_GET_CAUSE_FUNC[hint_sign] = find_cause_pep484585_mapping

    # Map each union-specific sign to its corresponding finder.
    for hint_sign in HINT_SIGNS_UNION:
        HINT_SIGN_TO_GET_CAUSE_FUNC[hint_sign] = find_cause_pep484604_union

    # ....................{ SPECIFICS                      }....................
    # Map each sign validated by a unique finder to that finder *AFTER* all
    # other mappings. These sign-specific finders are intended to replace all
    # other automated mappings above.
    HINT_SIGN_TO_GET_CAUSE_FUNC.update({
        # ....................{ NON-PEP                    }....................
        # Map PEP-noncompliant hints identified by *NO* PEP-compliant signs to
        # the catch-all PEP-noncompliant cause finder.
        None: find_cause_nonpep,

        # ....................{ PEP 484                    }....................
        HintSignForwardRef: find_cause_instance_type_forwardref,
        HintSignNoReturn: find_cause_pep484_noreturn,

        # ....................{ PEP (484|585)              }....................
        HintSignPep484585GenericUnsubbed: (
            find_cause_pep484585_generic_unsubbed),
        HintSignPep484585TupleFixed: find_cause_pep484585_tuple_fixed,
        HintSignType: find_cause_pep484585_subclass,

        # ....................{ PEP 586                    }....................
        HintSignLiteral: find_cause_pep586_literal,

        # ....................{ PEP 593                    }....................
        HintSignAnnotated: find_cause_pep593_annotated,
    })


# Initialize this submodule.
_init()
