#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **code object globals** (i.e., global constants describing code
objects of callables, classes, and modules).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ STRINGS                            }....................
FUNC_CODEOBJ_NAME_MODULE = '<module>'
'''
Arbitrary string constant unconditionally assigned to the ``co_name`` instance
variables of the code objects of all pure-Python modules (i.e., the top-most
lexical scope of each module in the current call stack).

This constant enables callers to reliably differentiate between code objects
encapsulating:

* Module scopes, whose ``co_name`` variable is this constant.
* Callable scopes, whose ``co_name`` variable is *not* this constant.
'''
