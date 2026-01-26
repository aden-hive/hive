#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`484` and :pep:`604` **type-checking expression snippets** (i.e.,
triple-quoted pure-Python string constants formatted and concatenated together
to dynamically generate boolean expressions type-checking arbitrary objects
against :pep:`484`- and :pep:`604`-compliant type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.typing.datatyping import CallableStrFormat

# ....................{ CODE                               }....................
CODE_PEP484604_UNION_PREFIX = '''('''
'''
:pep:`484`-compliant code snippet prefixing all code type-checking the current
pith against each subscripted argument of a :class:`typing.Union` type hint.
'''


CODE_PEP484604_UNION_SUFFIX = '''
{indent_curr})'''
'''
:pep:`484`-compliant code snippet suffixing all code type-checking the current
pith against each subscripted argument of a :class:`typing.Union` type hint.
'''


CODE_PEP484604_UNION_CHILD_NONPEP = '''
{{indent_curr}}    # True only if this pith is of one of these types.
{{indent_curr}}    isinstance({pith_curr_expr}, {hint_curr_expr}) or'''
'''
:pep:`484`-compliant code snippet type-checking the current pith against the
current PEP-noncompliant child argument subscripting a parent
:class:`typing.Union` type hint.

See Also
--------
:data:`CODE_PEP484604_UNION_CHILD_PEP`
    Further details.
'''


CODE_PEP484604_UNION_CHILD_PEP = '''
{{indent_curr}}    {hint_child_placeholder} or'''
'''
:pep:`484`-compliant code snippet type-checking the current pith against the
current PEP-compliant child argument subscripting a parent :class:`typing.Union`
type hint.

Caveats
-------
The caller is required to manually slice the trailing suffix ``" or"`` after
applying this snippet to the last subscripted argument of such a hint. While
there exist alternate and more readable means of accomplishing this, this
approach is the optimally efficient.

The ``{indent_curr}`` format variable is intentionally brace-protected to
efficiently defer its interpolation until the complete PEP-compliant code
snippet type-checking the current pith against *all* subscripted arguments of
this parent hint has been generated.
'''

# ....................{ FORMATTERS                         }....................
# str.format() methods, globalized to avoid inefficient dot lookups elsewhere.
# This is an absurd micro-optimization. *fight me, github developer community*
CODE_PEP484604_UNION_CHILD_PEP_format: CallableStrFormat = (
    CODE_PEP484604_UNION_CHILD_PEP.format)
CODE_PEP484604_UNION_CHILD_NONPEP_format: CallableStrFormat = (
    CODE_PEP484604_UNION_CHILD_NONPEP.format)
