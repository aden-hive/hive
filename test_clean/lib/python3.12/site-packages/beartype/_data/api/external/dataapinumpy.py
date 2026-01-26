#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **NumPy globals** (i.e., global constants pertaining to the
third-party :mod:`numpy` package).

This private submodule is *not* intended for importation by downstream callers.

Caveats
-------
**Never unconditionally import this submodule from global scope.** Only
conditionally import this submodule after validating that :mod:`numpy` is
importable under the active Python interpreter: e.g.,

.. code-block:: python

   from beartype._util.module.utilmodtest import is_module
   if is_module('numpy'):
       from beartype._data.api import dataapinumpy
       ...
'''

#FIXME: Currently unused, but preserved for posterity. What can you do? *shrug*
# # ....................{ IMPORTS                            }....................
# from numpy import (
#     bool_,
#     bytes_,
#     str_,
# )
#
# # ....................{ DICTS                              }....................
# NUMPY_DTYPE_SIMPLE_TO_BUILTIN_TYPE = {
#     bool_: bool,
#     bytes_: bytes,
#     str_: str,
# }
# '''
# Dictionary mapping from **simple NumPy dtypes** (i.e., dtypes *not* constrained
# to a predefined bitsize) to corresponding builtin types.
# '''
