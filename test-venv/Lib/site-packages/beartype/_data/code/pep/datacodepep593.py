#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`593` **type-checking expression snippets** (i.e.,
triple-quoted pure-Python string constants formatted and concatenated together
to dynamically generate boolean expressions type-checking arbitrary objects
against :pep:`593`-compliant type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.typing.datatyping import CallableStrFormat

# ....................{ CODE                               }....................
CODE_PEP593_VALIDATOR_PREFIX = '''('''
'''
:pep:`593`-compliant code snippet prefixing all code type-checking the current
pith against a :pep:`593`-compliant :obj:`typing.Annotated` type hint
subscripted by one or more :mod:`beartype.vale` validators.
'''


CODE_PEP593_VALIDATOR_SUFFIX = '''
{indent_curr})'''
'''
:pep:`593`-compliant code snippet suffixing all code type-checking the current
pith against each a :pep:`593`-compliant :class:`typing.Annotated` type hint
subscripted by one or more :mod:`beartype.vale` validators.
'''


CODE_PEP593_VALIDATOR_METAHINT = '''
{indent_curr}    {hint_child_placeholder} and'''
'''
:pep:`593`-compliant code snippet type-checking the current pith against the
**metahint** (i.e., first child type hint) subscripting a obj:`typing.Annotated`
type hint subscripted by one or more :mod:`beartype.vale` validators.
'''


CODE_PEP593_VALIDATOR_IS = '''
{indent_curr}    # True only if this pith satisfies this caller-defined
{indent_curr}    # validator of this annotated metahint.
{indent_curr}    {hint_child_expr} and'''
'''
:pep:`593`-compliant code snippet type-checking the current pith against
:mod:`beartype`-specific **data validator code** (i.e., caller-defined
:meth:`beartype.vale.BeartypeValidator._is_valid_code` string) of the current
child :mod:`beartype.vale` validator subscripting a parent :pep:`593`-compliant
:class:`typing.Annotated` type hint.

Caveats
-------
The caller is required to manually slice the trailing suffix ``" and"`` after
applying this snippet to the last subscripted argument of such a
:class:`typing.Annotated` type. While there exist alternate and more readable
means of accomplishing this, this approach is the optimally efficient.
'''

# ....................{ FORMATTERS                         }....................
# str.format() methods, globalized to avoid inefficient dot lookups elsewhere.
# This is an absurd micro-optimization. *fight me, github developer community*
CODE_PEP593_VALIDATOR_IS_format: CallableStrFormat = (
    CODE_PEP593_VALIDATOR_IS.format)
CODE_PEP593_VALIDATOR_METAHINT_format: CallableStrFormat = (
    CODE_PEP593_VALIDATOR_METAHINT.format)
CODE_PEP593_VALIDATOR_SUFFIX_format: CallableStrFormat = (
    CODE_PEP593_VALIDATOR_SUFFIX.format)
