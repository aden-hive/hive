#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`484`- or :pep:`585`-compliant **generic type-checking code
factories** (i.e., low-level callables dynamically generating pure-Python code
snippets type-checking arbitrary objects against generic type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._check.metadata.hint.hintsmeta import HintsMeta
from beartype._check.pep.checkpep484585generic import (
    get_hint_pep484585_generic_unsubbed_bases_unerased)
from beartype._data.code.pep.datacodepep484585 import (
    CODE_PEP484585_GENERIC_CHILD_format,
    CODE_PEP484585_GENERIC_PREFIX,
    CODE_PEP484585_GENERIC_SUFFIX,
)
from beartype._data.code.datacodelen import LINE_RSTRIP_INDEX_AND
from beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget import (
    get_hint_pep484585_generic_type_isinstanceable)

# ....................{ FACTORIES                          }....................
def make_hint_pep484585_generic_unsubbed_check_expr(
    hints_meta: HintsMeta) -> None:
    '''
    Either a Python code snippet type-checking the current pith against the
    passed :pep:`484`- or :pep:`585`-compliant **unsubscripted generic,**
    defined as either:

    * :pep:`484`-compliant **unsubscripted generic** (i.e., user-defined class
      subclassing a combination of one or more of the :class:`typing.Generic`
      superclass and other :mod:`typing` non-class pseudo-superclasses) *or*...
    * :pep:`544`-compliant **unsubscripted protocol** (i.e., class subclassing a
      combination of one or more of the :class:`typing.Protocol` superclass and
      other :mod:`typing` non-class pseudo-superclasses) *or*...
    * :pep:`585`-compliant unsubscripted generic (i.e., user-defined class
      subclassing at least one non-class :pep:`585`-compliant
      pseudo-superclasses).

    This factory is intentionally *not* memoized (e.g., by the
    :func:`.callable_cached` decorator), as the ``hints_meta`` parameter is
    **context-sensitive** (i.e., contextually depends on context unique to the
    code being generated for the currently decorated callable).

    Parameters
    ----------
    hints_meta : HintsMeta
        Stack of metadata describing all visitable hints previously discovered
        by this breadth-first search (BFS).
    '''
    assert isinstance(hints_meta, HintsMeta), (
        f'{repr(hints_meta)} not "HintsMeta" object.')
    # print(f'Visiting generic type {repr(hint_curr)}...')

    # ....................{ LOCALS                         }....................
    # Metadata encapsulating the sanification of this unsubscripted generic,
    # localized for both usability and efficiency.
    hint_sane = hints_meta.hint_curr_meta.hint_sane

    # Unsubscripted generic encapsulated by this metadata.
    hint = hint_sane.hint

    # Isinstanceable type against which to type-check instances of this generic,
    # defaulting to this generic. Although most generics are isinstanceable,
    # some are not. This type enables this code generator to transparently
    # support the subset of generics that are *NOT* isinstanceable.
    hint_isinstanceable = get_hint_pep484585_generic_type_isinstanceable(
        hint=hint, exception_prefix=hints_meta.exception_prefix)

    # ....................{ FORMAT                         }....................
    # Initialize the code type-checking this pith against this generic to the
    # substring prefixing all such code.
    hints_meta.func_curr_code = CODE_PEP484585_GENERIC_PREFIX

    # For metadata encapsulating the sanification of each unignorable unerased
    # transitive pseudo-superclass originally declared as a superclass of this
    # unsubscripted generic *AND* the sign identifying this pseudo-superclass...
    for hint_child_sane, hint_child_sign in (
        get_hint_pep484585_generic_unsubbed_bases_unerased(
            hint_sane,
            hints_meta.cls_stack,
            hints_meta.conf,
            hints_meta.exception_prefix,
        )
    ):
        # print(f'Visiting generic type hint {hint_curr_sane} unerased base {hint_child_sane}...')

        # Append code type-checking this pith against this pseudo-superclass.
        hints_meta.func_curr_code += CODE_PEP484585_GENERIC_CHILD_format(
            hint_child_placeholder=hints_meta.enqueue_hint_child_sane(
                hint_sane=hint_child_sane,
                hint_sign=hint_child_sign,
                # Python expression efficiently reusing the value of this pith
                # previously assigned to a local variable by the prior
                # expression.
                pith_expr=hints_meta.pith_curr_var_name,
            ),
        )

    # Munge this code to...
    hints_meta.func_curr_code = (
        # Strip the erroneous " and" suffix appended by the last child hint from
        # this code.
        f'{hints_meta.func_curr_code[:LINE_RSTRIP_INDEX_AND]}'
        # Suffix this code by the substring suffixing all such code.
        f'{CODE_PEP484585_GENERIC_SUFFIX}'
    # Format...
    ).format(
        # Indentation deferred above for efficiency.
        indent_curr=hints_meta.indent_curr,
        pith_curr_assign_expr=hints_meta.pith_curr_assign_expr,
        # Python expression evaluating to this unsubscripted isinstanceable
        # generic type.
        hint_curr_expr=hints_meta.add_func_scope_type_or_types(
            hint_isinstanceable),
    )
    # print(f'{hint_curr_exception_prefix} PEP generic {repr(hint)} handled.')
