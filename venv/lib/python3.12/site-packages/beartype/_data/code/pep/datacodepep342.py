#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`342` **type-checking expression snippets** (i.e.,
triple-quoted pure-Python string constants formatted and concatenated together
to dynamically generate boolean expressions type-checking arbitrary objects
against :pep:`342`-compliant asynchronous generator factories).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.code.datacodename import (
    ARG_NAME_FUNC,
    VAR_NAME_PITH_ROOT,
)

# ....................{ CODE                               }....................
# Note that outstanding deficiencies in CPython's Parser Expression Grammar
# (PEG) requires the inner "yield from" expression to be parenthesized. Why
# Because PEP 380-compliant "yield from" syntax isn't a full-blown expression;
# it's an expression prefix. That syntax can appear only at the *START* of an
# expression. The "return" and "yield from" keywords *CANNOT* be directly
# combined. Attempting to do so induces CPython to raise a non-descriptive
# "SyntaxError" resembling:
#     >>> def bad_generator_should_be_good():
#     ...     return yield from ()
#                    ^^^^^
#     SyntaxError: invalid syntax
#
# Yes, this is nonsensical. We didn't write that PEG. Somebody who hates us did.
CODE_PEP342_RETURN_CHECKED = f'''
    # Value returned by this synchronous generator if this generator returns a
    # value or "None" otherwise, obtained *AFTER* the caller successfully
    # exhausts all values yielded by this generator.
    return (yield from {VAR_NAME_PITH_ROOT})'''
'''
:pep:`342`-compliant code snippet facilitating full-blown bidirectional
communication between the higher-level caller and lower-level synchronous
generator factory wrapped by :func:`beartype.beartype`-driven type-checking.
'''


CODE_PEP342_RETURN_UNCHECKED = f'''
    return (yield from {ARG_NAME_FUNC}(*args, **kwargs))'''
'''
:pep:`342`-compliant code snippet facilitating full-blown bidirectional
communication between the higher-level caller and lower-level synchronous
generator factory wrapped by :func:`beartype.beartype` *without* type-checking
any values asynchronously produced by that generator (including yields, sends,
and returns).

This snippet is an optimization for the common case in which the return of that
factory is left unannotated.
'''
