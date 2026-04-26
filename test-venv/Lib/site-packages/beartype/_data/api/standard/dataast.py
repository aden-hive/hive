#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **abstract syntax tree (AST) singletons** (i.e., objects pertaining
to ASTs commonly required throughout this codebase, reducing space and time
consumption by preallocating widely used AST-centric objects).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from ast import (
    ClassDef,
    FunctionDef,
    Load,
    Store,
)

# ....................{ NODES                              }....................
NODE_CONTEXT_LOAD = Load()
'''
**Node context load singleton** (i.e., object suitable for passing as the
``ctx`` keyword parameter accepted by the ``__init__()`` method of various
abstract syntax tree (AST) node classes).
'''


NODE_CONTEXT_STORE = Store()
'''
**Node context store singleton** (i.e., object suitable for passing as the
``ctx`` keyword parameter accepted by the ``__init__()`` method of various
abstract syntax tree (AST) node classes).
'''

# ....................{ TYPES                              }....................
TYPES_NODE_LEXICAL_SCOPE = frozenset((
    ClassDef,
    FunctionDef,
))
'''
Frozen set of all **lexically scoping abstract syntax tree (AST) node types**
(i.e., types of all AST nodes whose declaration defines a new lexical scope).
'''
