#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **mapping singletons** (i.e., dictionaries commonly required
throughout this codebase, reducing space and time consumption by preallocating
widely used dictionary-centric objects).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._util.kind.maplike.utilmapfrozen import FrozenDict

# ....................{ DICTS                              }....................
FROZENDICT_EMPTY = FrozenDict()
'''
**Empty frozen dictionary** (i.e., :class:`.FrozenDict` object containing *no*
key-value pairs).

Whereas Python guarantees the **empty tuple** (i.e., ``()``) to be a singleton,
Python does *not* extend that guarantee to dictionaries. This empty dictionary
singleton amends that oversight, providing efficient reuse of empty
dictionaries: e.g.,

.. code-block:: pycon

   >>> () is ()
   True  # <-- good. this is good.
   >>> {} is {}
   False  # <-- bad. this is bad.
   >>> from beartype._data.kind.datakindmap import FROZENDICT_EMPTY
   >>> FROZENDICT_EMPTY is FROZENDICT_EMPTY
   True  # <-- good. this is good, because we made it so.
'''
