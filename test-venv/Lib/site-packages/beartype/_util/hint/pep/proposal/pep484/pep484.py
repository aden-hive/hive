#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`-compliant type hint utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
# Intentionally import PEP 484-compliant "typing" type hint factories rather
# than possibly PEP 585-compliant "beartype.typing" type hint factories.
from typing import Tuple

# ....................{ HINTS                              }....................
#FIXME: This very much does *NOT* belong here.
HINT_PEP484_TUPLE_EMPTY = Tuple[()]
'''
:pep:`484`-compliant empty fixed-length tuple type hint.
'''
