#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **chain set class hierarchy** (i.e., private classes implementing
mutable set-like chain mappings dynamically compositing the keys of two or more
mutable dictionaries treated as sets).
'''

# ....................{ IMPORTS                            }....................
from collections import ChainMap

# ....................{ CLASSES                            }....................
class ChainSet(ChainMap):
    '''
    **Chain set** (i.e., mutable set-like chain mappings dynamically compositing
    the keys of two or more mutable dictionaries treated as sets).

    This data structure is currently simply a trivial subclass of the standard
    :class:`.ChainMap` type. Although non-ideal, this subclass enables callers
    to at least differentiate between standard chain maps and set-like chain
    maps. Ideally, this subclass would be entirely reimplemented "from the
    ground up" *without* reference to the semantically unrelated
    :class:`.ChainMap` type. Until then, this approach perseveres.
    '''

    pass
