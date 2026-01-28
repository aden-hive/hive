#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype PEP-compliant generic type hint exception raisers** (i.e., functions
raising human-readable exceptions called by :mod:`beartype`-decorated callables
on the first invalid parameter or return value failing a type-check against the
PEP-compliant generic type hint annotating that parameter or return).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.hint.sign.datahintsigns import (
    HintSignPep484585GenericUnsubbed)
from beartype._check.error.errcause import ViolationCause
from beartype._check.error._errtype import find_cause_instance_type
from beartype._check.pep.checkpep484585generic import (
    get_hint_pep484585_generic_unsubbed_bases_unerased_kwargs)
from beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget import (
    get_hint_pep484585_generic_type_isinstanceable)
from beartype._util.text.utiltextansi import color_hint

# ....................{ GETTERS                            }....................
def find_cause_pep484585_generic_unsubbed(
    cause: ViolationCause) -> ViolationCause:
    '''
    Output cause describing whether the pith of the passed input cause either
    satisfies or violates the :pep:`484`- or :pep:`585`-compliant
    **unsubscripted generic** (i.e., type hint subclassing a combination of one
    or more of the :mod:`typing.Generic` superclass, the :mod:`typing.Protocol`
    superclass, and/or other :mod:`typing` non-class pseudo-superclasses) of
    that cause.

    Parameters
    ----------
    cause : ViolationCause
        Input cause providing this data.

    Returns
    -------
    ViolationCause
        Output cause type-checking this data.
    '''
    assert isinstance(cause, ViolationCause), f'{repr(cause)} not cause.'
    assert cause.hint_sign is HintSignPep484585GenericUnsubbed, (
        f'{repr(cause.hint_sign)} not generic.')
    # print(f'[find_cause_generic] cause.pith: {cause.pith}')
    # print(f'[find_cause_generic] cause.hint [pre-reduction]: {cause.hint}')

    # Origin type originating this generic, deduced by stripping all child type
    # hints subscripting this hint from this hint.
    hint_type = get_hint_pep484585_generic_type_isinstanceable(
        hint=cause.hint, exception_prefix=cause.exception_prefix)

    # Shallow output cause to be returned, type-checking only whether this pith
    # is instance of this origin type.
    cause_type = cause.permute_cause_hint_child_insane(hint_type)
    cause_shallow = find_cause_instance_type(cause_type)
    # print(f'[find_cause_generic] cause.hint [post-reduction]: {cause.hint}')

    # If this pith is *NOT* an instance of this type, return this cause.
    if cause_shallow.cause_str_or_none is not None:
        return cause_shallow
    # Else, this pith is an instance of this type.

    # For metadata encapsulating the sanification of each unignorable unerased
    # transitive pseudo-superclass originally declared as a superclass of this
    # unsubscripted generic *AND* the sign identifying this pseudo-superclass...
    for hint_child_sane, hint_child_sign in (
        get_hint_pep484585_generic_unsubbed_bases_unerased_kwargs(
            hint_sane=cause.hint_sane,
            cls_stack=cause.cls_stack,
            conf=cause.conf,
            exception_prefix=cause.exception_prefix,
        )
    ):
        # Deep output cause to be returned, permuted from this input cause to
        # reflect this pseudo-superclass.
        cause_deep = cause.permute_cause(
            hint_sane=hint_child_sane, hint_sign=hint_child_sign).find_cause()
        # print(f'tuple pith: {pith_item}\ntuple hint child: {hint_child}')

        # If this pseudo-superclass is the cause of this failure...
        if cause_deep.cause_str_or_none is not None:
            # Human-readable string prefixing this failure with additional
            # metadata describing this pseudo-superclass.
            cause_deep.cause_str_or_none = (
                f'generic superclass '
                f'{color_hint(text=repr(hint_child_sane.hint), is_color=cause.conf.is_color)} of '
                f'{cause_deep.cause_str_or_none}'
            )

            # Return this cause.
            return cause_deep
        # Else, this pseudo-superclass is *NOT* the cause of this failure.
        # Silently continue to the next.
        # print(f'[find_cause_generic] Ignoring satisfied base {hint_child}...')

    # Return this cause as is. This pith satisfies both this generic itself
    # *AND* all pseudo-superclasses subclassed by this generic, implying this
    # pith to deeply satisfy this hint.
    return cause
