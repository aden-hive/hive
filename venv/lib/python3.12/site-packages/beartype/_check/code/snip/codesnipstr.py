#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **type-checking expression snippets** (i.e., triple-quoted pure-Python
string constants formatted and concatenated together to dynamically generate
boolean expressions type-checking arbitrary objects against various type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

#FIXME: Refactor the gutted remainder of this submodule into new submodules
#residing in the new "beartype._data.code.pep" subpackage, please. *sigh*

# ....................{ IMPORTS                            }....................
from beartype._data.typing.datatyping import CallableStrFormat

# ....................{ HINT ~ placeholder : forwardref    }....................
CODE_HINT_REF_TYPE_BASENAME_PLACEHOLDER_PREFIX = '${FORWARDREF:'
'''
Prefix of each **placeholder unqualified forward reference classname
substring** (i.e., placeholder to be globally replaced by a Python code snippet
evaluating to the currently visited unqualified forward reference hint
canonicalized into a fully-qualified classname relative to the external
caller-defined module declaring the currently decorated callable).
'''


CODE_HINT_REF_TYPE_BASENAME_PLACEHOLDER_SUFFIX = ']?'
'''
Suffix of each **placeholder unqualified forward reference classname
substring** (i.e., placeholder to be globally replaced by a Python code snippet
evaluating to the currently visited unqualified forward reference hint
canonicalized into a fully-qualified classname relative to the external
caller-defined module declaring the currently decorated callable).
'''

# ....................{ HINT ~ pep : 572                   }....................
CODE_PEP572_PITH_ASSIGN_EXPR = '''{pith_curr_var_name} := {pith_curr_expr}'''
'''
Assignment expression assigning the full Python expression yielding the value of
the current pith to a unique local variable, enabling child type hints to obtain
this pith via this efficient variable rather than via this inefficient full
Python expression.
'''


#FIXME: Preserved for posterity in the likelihood we'll need this again. *sigh*
# CODE_PEP572_PITH_ASSIGN_AND = '''
# {indent_curr}    # Localize this pith as a stupidly fast assignment expression.
# {indent_curr}    ({pith_curr_assign_expr}) is {pith_curr_var_name} and'''
# '''
# Code snippet embedding an assignment expression assigning the full Python
# expression yielding the value of the current pith to a unique local variable.
#
# This snippet is itself intended to be embedded in higher-level code snippets as
# the first child expression of those snippets, enabling subsequent expressions in
# those snippets to efficiently obtain this pith via this efficient variable
# rather than via this inefficient full Python expression.
#
# This snippet is a tautology that is guaranteed to evaluate to :data:`True`,
# with the intentional side effect of this assignment expression. Note that
# there exist numerous less efficient alternatives, including:
#
# * ``({pith_curr_assign_expr}).__class__``, which is also guaranteed to evaluate
#   to :data:`True` but which implicitly triggers the ``__getattr__()`` dunder
#   method and thus incurs a performance penalty for user-defined objects
#   inefficiently overriding that method.
# * ``isinstance({pith_curr_assign_expr}, object)``, which is also guaranteed to
#   evaluate :data:`True` but which is surprisingly inefficient in all cases.
# '''

# ....................{ HINT ~ pep : 484 : instance        }....................
CODE_PEP484_INSTANCE = '''isinstance({pith_curr_expr}, {hint_curr_expr})'''
'''
:pep:`484`-compliant code snippet type-checking the current pith against the
current child PEP-compliant type expected to be a trivial non-:mod:`typing`
type (e.g., :class:`int`, :class:`str`).

Caveats
-------
**This snippet is intentionally compact rather than embedding a human-readable
comment.** For example, this snippet intentionally avoids doing this:

.. code-block:: python

   CODE_PEP484_INSTANCE = '
   {indent_curr}# True only if this pith is of this type.
   {indent_curr}isinstance({pith_curr_expr}, {hint_curr_expr})'

Although feasible, doing that would significantly complicate code generation for
little to *no* tangible gain. Indeed, we actually tried doing that once. We
failed hard after breaking everything. **Avoid the mistakes of the past.**
'''

# ..................{ FORMATTERS                             }..................
# str.format() methods, globalized to avoid inefficient dot lookups elsewhere.
# This is an absurd micro-optimization. *fight me, github developer community*
CODE_PEP484_INSTANCE_format: CallableStrFormat = (
    CODE_PEP484_INSTANCE.format)
# CODE_PEP572_PITH_ASSIGN_AND_format: CallableStrFormat = (
#     CODE_PEP572_PITH_ASSIGN_AND.format)
CODE_PEP572_PITH_ASSIGN_EXPR_format: CallableStrFormat = (
    CODE_PEP572_PITH_ASSIGN_EXPR.format)
