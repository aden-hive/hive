#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype decorator **type-checking expression magic** (i.e., global string
constants embedded in the implementations of boolean expressions type-checking
arbitrary objects against arbitrary PEP-compliant type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.error.dataerrmagic import EXCEPTION_PLACEHOLDER
# from itertools import count

# ....................{ EXCEPTION                          }....................
EXCEPTION_PREFIX_FUNC_WRAPPER_LOCAL = (
    f'{EXCEPTION_PLACEHOLDER}wrapper parameter ')
'''
Human-readable substring describing a new wrapper parameter required by the
current root type hint in exception messages.
'''


EXCEPTION_PREFIX_HINT = f'{EXCEPTION_PLACEHOLDER}type hint '
'''
Human-readable substring describing the current root type hint generically
(i.e., agnostic of the specific PEP standard to which this hint conforms) in
exception messages.
'''
