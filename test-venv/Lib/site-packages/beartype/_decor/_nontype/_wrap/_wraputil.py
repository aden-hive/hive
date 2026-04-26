#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype decorator code generator utilities** (i.e., low-level callables
assisting the parent :func:`beartype._decor._nontype._wrap.wrapmain` submodule).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._check.metadata.metadecor import BeartypeDecorMeta
from beartype._data.code.datacodename import CODE_PITH_ROOT_NAME_PLACEHOLDER
from beartype._check.code.codescope import add_func_scope_ref
from beartype._check.code.snip.codesnipstr import (
    CODE_HINT_REF_TYPE_BASENAME_PLACEHOLDER_PREFIX,
    CODE_HINT_REF_TYPE_BASENAME_PLACEHOLDER_SUFFIX,
)
from beartype._data.error.dataerrmagic import EXCEPTION_PLACEHOLDER
from beartype._util.hint.pep.proposal.pep484585.pep484585ref import (
    get_hint_pep484585_ref_names_relative_to)
from beartype._util.text.utiltextmunge import replace_str_substrs
from collections.abc import Iterable

# ....................{ CACHERS                            }....................
def unmemoize_func_wrapper_code(
    decor_meta: BeartypeDecorMeta,
    func_wrapper_code: str,
    pith_repr: str,
    hint_refs_type_basename: tuple,
) -> str:
    '''
    Convert the passed memoized code snippet type-checking any parameter or
    return of the decorated callable into an "unmemoized" code snippet
    type-checking a specific parameter or return of that callable.

    Specifically, this function (in order):

    #. Globally replaces all references to the
       :data:`.CODE_PITH_ROOT_NAME_PLACEHOLDER` placeholder substring
       cached into this code with the passed ``pith_repr`` parameter.
    #. Unmemoizes this code by globally replacing all relative forward
       reference placeholder substrings cached into this code with Python
       expressions evaluating to the classes referred to by those substrings
       relative to that callable when accessed via the private
       ``__beartypistry`` parameter.

    Parameters
    ----------
    decor_meta : BeartypeDecorMeta
        Decorated callable to be type-checked.
    func_wrapper_code : str
        Memoized callable-agnostic code snippet type-checking any parameter or
        return of the decorated callable.
    pith_repr : str
        Machine-readable representation of the name of this parameter or
        return.
    hint_refs_type_basename : tuple
        Tuple of the unqualified classnames referred to by all relative forward
        reference type hints visitable from the current root type hint.

    Returns
    -------
    str
        This memoized code unmemoized by globally resolving all relative
        forward reference placeholder substrings cached into this code relative
        to the currently decorated callable.
    '''
    assert decor_meta.__class__ is BeartypeDecorMeta, (
        f'{repr(decor_meta)} not @beartype call.')
    assert isinstance(func_wrapper_code, str), (
        f'{repr(func_wrapper_code)} not string.')
    assert isinstance(pith_repr, str), f'{repr(pith_repr)} not string.'
    assert isinstance(hint_refs_type_basename, Iterable), (
        f'{repr(hint_refs_type_basename)} not iterable.')

    # Generate an unmemoized parameter-specific code snippet type-checking this
    # parameter by replacing in this parameter-agnostic code snippet...
    func_wrapper_code = replace_str_substrs(
        text=func_wrapper_code,
        # This placeholder substring cached into this code with...
        old=CODE_PITH_ROOT_NAME_PLACEHOLDER,
        # This object representation of the name of this parameter or return.
        new=pith_repr,
    )

    # If this code contains one or more relative forward reference placeholder
    # substrings memoized into this code, unmemoize this code by globally
    # resolving these placeholders relative to the decorated callable.
    if hint_refs_type_basename:
        # Metadata describing the callable currently being decorated by
        # beartype, localized purely as a negligible optimization.
        func = decor_meta.func_wrappee
        func_scope = decor_meta.func_wrapper_scope
        cls_stack = decor_meta.cls_stack

        # For each unqualified classname referred to by a relative forward
        # reference type hints visitable from the current root type hint...
        for ref_basename in hint_refs_type_basename:
            # Possibly undefined fully-qualified module name and possibly
            # unqualified classname referred to by this relative forward
            # reference, relative to the decorated type stack and callable.
            ref_module_name, ref_name = get_hint_pep484585_ref_names_relative_to(
                hint=ref_basename,
                cls_stack=cls_stack,
                func=func,
                exception_prefix=EXCEPTION_PLACEHOLDER,
            )

            # Name of the hidden parameter providing this forward reference
            # proxy to be passed to this wrapper function.
            ref_expr = add_func_scope_ref(
                func_scope=func_scope,
                ref_module_name=ref_module_name,
                ref_name=ref_name,
                exception_prefix=EXCEPTION_PLACEHOLDER,
            )

            # Generate an unmemoized callable-specific code snippet checking
            # this class by globally replacing in this callable-agnostic code...
            func_wrapper_code = replace_str_substrs(
                text=func_wrapper_code,
                # This placeholder substring cached into this code with...
                old=(
                    f'{CODE_HINT_REF_TYPE_BASENAME_PLACEHOLDER_PREFIX}'
                    f'{ref_name}'
                    f'{CODE_HINT_REF_TYPE_BASENAME_PLACEHOLDER_SUFFIX}'
                ),
                # Python expression evaluating to this class when accessed via
                # this hidden parameter.
                new=ref_expr,
            )

    # Return this unmemoized callable-specific code snippet.
    return func_wrapper_code
