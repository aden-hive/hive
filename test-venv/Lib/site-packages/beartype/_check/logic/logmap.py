#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **hint sign logic mappings** (i.e., dictionary globals mapping from
signs uniquely identifying various kinds of type hints to corresponding
dataclasses encapsulating all low-level Python code snippets and associated
metadata required to dynamically generate high-level Python code snippets fully
type-checking those type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import Dict
from beartype._check.logic.logcls import (
    HintLogicABC,
    HintLogicQuasiiterable,
    HintLogicReiterable,
    HintLogicSequence,
)
from beartype._data.hint.sign.datahintsigncls import HintSign

# ....................{ MAPPINGS                           }....................
# Initialized by the _init() function defined below.
HINT_SIGN_PEP484585_CONTAINER_TO_LOGIC: Dict[HintSign, HintLogicABC] = {}
'''
Dictionary mapping from the sign uniquely identifying each applicable kind of
**standard single-argument container type hint** (i.e., :pep:`484`- or
:pep:`585`-compliant type hint describing a standard container, subscripted by
exactly one child type hint constraining *all* items contained in that
container) to the hint sign logic dataclass dynamically generating Python code
snippets type-checking that kind of type hint.
'''

HINT_SIGN_PEP484585_CONTAINER_TO_LOGIC_get = (
    HINT_SIGN_PEP484585_CONTAINER_TO_LOGIC.get)
'''
:meth:`dict.get` method bound to the
:data:`.HINT_PEP484585_CONTAINER_TO_LOGIC` global for efficiency.
'''

# ..................{ PRIVATE ~ main                         }..................
def _init() -> None:
    '''
    Initialize this submodule.
    '''

    # ....................{ IMPORTS                        }....................
    # Defer function-specific imports.
    from beartype._data.hint.sign.datahintsignset import (
        HINT_SIGNS_QUASIITERABLE,
        HINT_SIGNS_REITERABLE,
        HINT_SIGNS_SEQUENCE,
    )

    # ....................{ DEFINE                         }....................
    # Hint sign logic singletons.
    hint_logic_quasiiterable = HintLogicQuasiiterable()
    hint_logic_reiterable = HintLogicReiterable()
    hint_logic_sequence = HintLogicSequence()

    # For each sign identifying a single-argument uniiterable hint...
    for hint_sign in HINT_SIGNS_QUASIITERABLE:
        # Map this sign to this logic dataclass.
        HINT_SIGN_PEP484585_CONTAINER_TO_LOGIC[hint_sign] = (
            hint_logic_quasiiterable)

    # For each sign identifying a single-argument reiterable hint...
    for hint_sign in HINT_SIGNS_REITERABLE:
        # Map this sign to this logic dataclass.
        HINT_SIGN_PEP484585_CONTAINER_TO_LOGIC[hint_sign] = (
            hint_logic_reiterable)

    # For each sign identifying a single-argument sequence hint...
    for hint_sign in HINT_SIGNS_SEQUENCE:
        # Map this sign to this logic dataclass.
        HINT_SIGN_PEP484585_CONTAINER_TO_LOGIC[hint_sign] = hint_logic_sequence


# Initialize this submodule.
_init()
