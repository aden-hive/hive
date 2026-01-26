#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`484`- or :pep:`585`-compliant **container type-checking code
factories** (i.e., low-level callables dynamically generating pure-Python code
snippets type-checking arbitrary objects against container type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPepException
from beartype._check.metadata.hint.hintsmeta import HintsMeta
from beartype._check.metadata.hint.hintsane import HINT_SANE_IGNORABLE
from beartype._check.logic.logmap import (
    HINT_SIGN_PEP484585_CONTAINER_TO_LOGIC_get)
from beartype._data.hint.sign.datahintsigns import HintSignTuple
from beartype._util.hint.pep.proposal.pep484585.pep484585 import (
    get_hint_pep484585_arg)
from beartype._util.hint.pep.utilpepget import (
    get_hint_pep_args,
    get_hint_pep_origin_type_isinstanceable,
)

# ....................{ FACTORIES                          }....................
def make_hint_pep484585_container_check_expr(hints_meta: HintsMeta) -> None:
    '''
    Either a Python code snippet type-checking the current pith against the
    passed :pep:`484`- or :pep:`585`-compliant container type hint.

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

    # ....................{ LOCALS                         }....................
    # This container hint, localized for both usability and efficiency.
    hint = hints_meta.hint_curr_meta.hint_sane.hint

    # Sign uniquely identifying this hint, localized for usability.
    hint_sign = hints_meta.hint_curr_meta.hint_sign

    # Python expression evaluating to the origin type of this hint as a hidden
    # beartype-specific parameter injected into the signature of this wrapper.
    hints_meta.hint_curr_expr = hints_meta.add_func_scope_type_or_types(
        get_hint_pep_origin_type_isinstanceable(hint))
    # print(f'Container type hint {hint_curr} origin type scoped: {hint_curr_expr}')

    # Tuple of all child hints subscripting this hint if any *OR* the empty
    # tuple otherwise (e.g., if this hint is its own unsubscripted factory).
    #
    # Note that the "__args__" dunder attribute is *NOT* guaranteed to exist for
    # arbitrary PEP-compliant type hints. Ergo, we obtain this attribute via a
    # higher-level utility getter.
    hint_childs = get_hint_pep_args(hint)

    # Possibly ignorable insane child hint subscripting this parent hint,
    # defined as either...
    hint_child = (  # pyright: ignore
        # If this parent hint is a variable-length tuple, the
        # get_hint_pep_sign() getter called above has already validated the
        # contents of this tuple. In this case, efficiently get the lone child
        # hint of this parent hint *WITHOUT* validation.
        hint_childs[0]
        if hint_sign is HintSignTuple else
        # Else, this hint is a single-argument container, in which case the
        # contents of this container have yet to be validated. In this case,
        # inefficiently get the lone child hint of this parent hint *WITH*
        # validation.
        get_hint_pep484585_arg(
            hint=hint, exception_prefix=hints_meta.exception_prefix)
    )
    # print(f'Sanifying container hint {repr(hint_curr)} child hint {repr(hint_child)}...')
    # print(f'...with type variable lookup table {repr(hint_curr_meta.typearg_to_hint)}.')

    # Metadata encapsulating the sanification of this child hint.
    hint_child_sane = hints_meta.sanify_hint_child(hint_child)

    # ....................{ FORMAT                         }....................
    # If this child hint is unignorable:
    # * Shallowly type-check the type of the current pith.
    # * Deeply type-check an efficiently retrievable item of this pith.
    if hint_child_sane is not HINT_SANE_IGNORABLE:
        # Hint logic type-checking this sign if any *OR* "None" otherwise.
        hint_logic = HINT_SIGN_PEP484585_CONTAINER_TO_LOGIC_get(hint_sign)  # type: ignore[arg-type]

        # If *NO* hint logic type-checks this sign, raise an exception.
        #
        # Note that this logic should *ALWAYS* be non-"None". Nonetheless...
        if hint_logic is None:  # pragma: no cover
            raise BeartypeDecorHintPepException(
                f'{hints_meta.exception_prefix}'
                f'1-argument container type hint {repr(hint)} '
                f'beartype sign {repr(hint_sign)} '
                f'code generation logic not found.'
            )
        # Else, some hint logic type-checks this sign.

        # Increase the indentation level of code type-checking this pith.
        hints_meta.indent_level_child += 1

        # Python expression deeply type-checking this pith against this hint.
        hint_logic.make_code(
            hints_meta=hints_meta, hint_child_sane=hint_child_sane)

        # Record whether this expression requires a pseudo-random integer.
        hints_meta.is_var_random_int_needed |= (
            hint_logic.is_var_random_int_needed)
    # Else, this child hint is ignorable. In this case, fallback to trivial code
    # shallowly type-checking this pith as an instance of this origin type.
