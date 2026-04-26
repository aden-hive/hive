#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`586` **type-checking expression snippets** (i.e., triple-quoted
pure-Python string constants formatted and concatenated together to dynamically
generate boolean expressions type-checking arbitrary objects against
:pep:`586`-compliant type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.typing.datatyping import CallableStrFormat

# ....................{ CODE                               }....................
CODE_PEP586_PREFIX = '''(
{{indent_curr}}    # True only if this pith is of one of these literal types.
{{indent_curr}}    isinstance({pith_curr_assign_expr}, {hint_child_types_expr}) and ('''
'''
:pep:`586`-compliant code snippet prefixing all code type-checking the current
pith against a :pep:`586`-compliant :class:`typing.Literal` type hint
subscripted by one or more literal objects.
'''


CODE_PEP586_SUFFIX = '''
{indent_curr}))'''
'''
:pep:`586`-compliant code snippet suffixing all code type-checking the current
pith against a :pep:`586`-compliant :class:`typing.Literal` type hint
subscripted by one or more literal objects.
'''


CODE_PEP586_LITERAL = '''
{{indent_curr}}        # True only if this pith is equal to this literal.
{{indent_curr}}        {pith_curr_var_name} == {hint_child_expr} or'''
'''
:pep:`586`-compliant code snippet type-checking the current pith against the
current child literal object subscripting a :pep:`586`-compliant
:class:`typing.Literal` type hint.

Caveats
-------
The caller is required to manually slice the trailing suffix ``" and"`` after
applying this snippet to the last subscripted argument of such a
:class:`typing.Literal` type. While there exist alternate and more readable
means of accomplishing this, this approach is the optimally efficient.

The ``{indent_curr}`` format variable is intentionally brace-protected to
efficiently defer its interpolation until the complete PEP-compliant code
snippet type-checking the current pith against *all* subscripted arguments of
this parent hint has been generated.
'''

# ....................{ FORMATTERS                         }....................
# str.format() methods, globalized to avoid inefficient dot lookups elsewhere.
# This is an absurd micro-optimization. *fight me, github developer community*
CODE_PEP586_LITERAL_format: CallableStrFormat = CODE_PEP586_LITERAL.format
CODE_PEP586_PREFIX_format: CallableStrFormat = CODE_PEP586_PREFIX.format
