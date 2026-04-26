#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **callable globals** (i.e., global constants describing various
well-known functions and methods).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ SETS                               }....................
OBJECT_SLOT_WRAPPERS = frozenset(
    # This slow wrapper.
    object_attr_value
    # For the name of each attribute defined by the root "object" superclass...
    for object_attr_name, object_attr_value in object.__dict__.items()
    # If the value of this attribute is callable and thus a low-level C-based
    # slot wrapper whose default implementation is mostly useless.
    if callable(object_attr_value)
)
'''
Frozen set of all **object slot wrappers** (i.e., low-level C-based callables
bound to the root :class:`object` superclass providing mostly useless default
implementations of popular dunder methods).

The default implementations of object slot wrappers have no intrinsic value in
any meaningful context and only serve to obfuscate actually intrinsically
valuable methods declared by concrete subclasses. Detecting and ignoring object
slot wrappers is thus a common desire.
'''


METHOD_NAMES_DUNDER_BINARY = frozenset((
    '__add__',
    '__and__',
    '__cmp__',
    '__divmod__',
    '__div__',
    '__eq__',
    '__floordiv__',
    '__ge__',
    '__gt__',
    '__iadd__',
    '__iand__',
    '__idiv__',
    '__ifloordiv__',
    '__ilshift__',
    '__imatmul__',
    '__imod__',
    '__imul__',
    '__ior__',
    '__ipow__',
    '__irshift__',
    '__isub__',
    '__itruediv__',
    '__ixor__',
    '__le__',
    '__lshift__',
    '__lt__',
    '__matmul__',
    '__mod__',
    '__mul__',
    '__ne__',
    '__or__',
    '__pow__',
    '__radd__',
    '__rand__',
    '__rdiv__',
    '__rfloordiv__',
    '__rlshift__',
    '__rmatmul__',
    '__rmod__',
    '__rmul__',
    '__ror__',
    '__rpow__',
    '__rrshift__',
    '__rshift__',
    '__rsub__',
    '__rtruediv__',
    '__rxor__',
    '__sub__',
    '__truediv__',
    '__xor__',
))
'''
Frozen set of the unqualified names of all **binary dunder methods** (i.e.,
methods whose names are both prefixed and suffixed by ``__``, which the active
Python interpreter implicitly calls to perform binary operations on instances
whose first operands are instances of the classes declaring those methods).
'''
