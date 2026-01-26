#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype Decidedly Object-Oriented Runtime-checking (DOOR) class type hints**
(i.e., PEP-compliant type hints matching the hierarchy driving our
object-oriented type hint class hierarchy).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.door._cls.doorsuper import TypeHint
from beartype.typing import (
    Tuple,
)

# ....................{ HINTS                              }....................
TupleTypeHints = Tuple[TypeHint, ...]
'''
PEP-compliant type hint matching a tuple of zero or more **type hint wrappers**
(i.e., :data:`.TypeHint` objects).
'''
