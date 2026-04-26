#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`484`- and :pep:`585`-compliant **mapping type hint violation
describers** (i.e., functions returning human-readable strings explaining
violations of :pep:`484`- and :pep:`585`-compliant mapping type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype import BeartypeStrategy
from beartype.typing import (
    Hashable,
    Iterable,
    Tuple,
)
from beartype._check.error.errcause import ViolationCause
from beartype._check.error._errtype import find_cause_type_instance_origin
from beartype._check.metadata.hint.hintsane import HINT_SANE_IGNORABLE
from beartype._data.hint.sign.datahintsignmap import (
    HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE)
from beartype._data.hint.sign.datahintsigns import HintSignCounter
from beartype._data.hint.sign.datahintsignset import HINT_SIGNS_MAPPING
from beartype._util.text.utiltextprefix import prefix_pith_type
from beartype._util.text.utiltextrepr import represent_pith

# ....................{ FINDERS                            }....................
def find_cause_pep484585_mapping(cause: ViolationCause) -> ViolationCause:
    '''
    Output cause describing whether the pith of the passed input cause either
    satisfies or violates the **mapping type hint** (i.e., PEP-compliant type
    hint accepting exactly two subscripted arguments constraining *all*
    key-value pairs of this pith, which necessarily satisfies the
    :class:`collections.abc.Mapping` protocol) of that cause.

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
    assert cause.hint_sign in HINT_SIGNS_MAPPING, (
        f'{repr(cause.hint)} not mapping hint.')

    # Number of child type hints expected to be subscripting this hint.
    hints_child_len_expected = (
        HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE[cause.hint_sign])

    # Assert this hint was subscripted by the expected number of child type
    # hints. Note that prior logic should have already guaranteed this.
    assert len(cause.hint_childs_sane) in hints_child_len_expected, (
        f'Mapping type hint {repr(cause.hint)} number of child type hints '
        f'{len(cause.hint_childs_sane)} not in {hints_child_len_expected}.'
    )

    # Shallow output cause describing the failure of this path to be a shallow
    # instance of the type originating this hint (e.g., "dict" for the hint
    # "dict[str, int]") if this pith is not an instance of this type *OR* "None"
    # otherwise (i.e., if this pith is an instance of this type).
    cause_shallow = find_cause_type_instance_origin(cause)

    # If this pith is *NOT* an instance of this type, return this shallow cause.
    if cause_shallow.cause_str_or_none is not None:
        return cause_shallow
    # Else, this pith is an instance of this type and thus a mapping.
    #
    # If this mapping is empty, all items of this mapping (of which there are
    # none) are valid. By definition, this mapping satisfies this hint. In this
    # case, return the passed cause as is.
    #
    # Note that this test *CANNOT* safely be optimized away to simply:
    #     not cause.pith or
    #
    # Why? Because a container being a mapping does *NOT* necessarily imply that
    # mapping to sanely implement the __bool__() dunder method. Although all
    # popular third-party mappings currently do implement sane __bool__() dunder
    # methods, that could change at any time. Notably, popular third-party
    # collections like PyTorch tensors and NumPy arrays do *NOT* implement sane
    # __bool__() dunder methods. Since they don't, similar third-party
    # mappings could implement similarly insane __bool__() dunder methods.
    #
    # See the "errpep484585container" submodule for additional commentary.
    elif not len(cause.pith):
        return cause
    # Else, this mapping is non-empty.

    # Child key hint subscripting this parent mapping hint.
    hint_key_sane = cause.hint_childs_sane[0]

    # Child value hint subscripting this parent mapping hint, defined as
    # either...
    hint_value_sane = (
        # If this hint describes a "collections.Counter" dictionary subclass,
        # the standard "int" type. See related logic in the
        # beartype._check.code.codemain.make_check_expr() factory for details.
        cause.sanify_hint_child(int)
        # Else, this hint does *NOT* describes a "collections.Counter"
        # dictionary subclass. In this case, this child value hint as is.
        if cause.hint_sign is HintSignCounter else
        cause.hint_childs_sane[1]
    )

    # True only if these hints are unignorable.
    is_hint_key_unignorable = hint_key_sane is not HINT_SANE_IGNORABLE
    is_hint_value_unignorable = hint_value_sane is not HINT_SANE_IGNORABLE

    # Arbitrary iterator vaguely satisfying the dict.items() protocol, yielding
    # zero or more 2-tuples of the form "(key, value)", where:
    # * "key" is the key of the current key-value pair.
    # * "value" is the value of the current key-value pair.
    pith_items: Iterable[Tuple[Hashable, object]] = None  # type: ignore[assignment]

    # If the only the first key-value pair of this mapping was type-checked by
    # the parent @beartype-generated wrapper function in O(1) time, type-check
    # only this key-value pair of this mapping in O(1) time as well.
    if cause.conf.strategy is BeartypeStrategy.O1:
        # First key-value pair of this mapping.
        pith_item = next(iter(cause.pith.items()))

        # Tuple containing only this pair.
        pith_items = (pith_item,)
        # print(f'Checking item {pith_item_index} in O(1) time!')
    # Else, this mapping was iterated by the parent @beartype-generated wrapper
    # function in O(n) time. In this case, type-check *ALL* key-value pairs of
    # this mapping in O(n) time as well.
    else:
        # Iterator yielding all key-value pairs of this mapping.
        pith_items = cause.pith.items()
        # print('Checking mapping in O(n) time!')

    # For each key-value pair of this mapping...
    for pith_key, pith_value in pith_items:
        # If this child key hint is unignorable...
        if is_hint_key_unignorable:
            # Deep output cause describing the failure of this key to satisfy
            # this child key hint if this key violates this child key hint *OR*
            # "None" otherwise (i.e., if this key satisfies this child key
            # hint).
            cause_deep = cause.permute_cause(
                hint_sane=hint_key_sane, pith=pith_key).find_cause()

            # If this key is the cause of this failure...
            if cause_deep.cause_str_or_none is not None:
                # Human-readable substring prefixing this failure with
                # metadata describing this key.
                cause_deep.cause_str_or_none = (
                    f'{prefix_pith_type(pith=cause.pith, is_color=True)}'
                    f'key {cause_deep.cause_str_or_none}'
                )

                # Return this cause.
                return cause_deep
            # Else, this key is *NOT* the cause of this failure. Silently
            # continue to this key's associated value.
        # Else, this child key hint is ignorable.

        # If this child value hint is unignorable...
        if is_hint_value_unignorable:
            # Deep output cause describing the failure of this value to satisfy
            # this child value hint if this value violates this child value hint
            # *OR* "None" otherwise (i.e., if this value satisfies this child
            # value hint).
            cause_deep = cause.permute_cause(
                hint_sane=hint_value_sane, pith=pith_value).find_cause()

            # If this value is the cause of this failure...
            if cause_deep.cause_str_or_none is not None:
                # Human-readable substring prefixing this failure with
                # metadata describing this value.
                cause_deep.cause_str_or_none = (
                    f'{prefix_pith_type(pith=cause.pith, is_color=True)}'
                    f'key {represent_pith(pith_key)} '
                    f'value {cause_deep.cause_str_or_none}'
                )

                # Return this cause.
                return cause_deep
            # Else, this value is *NOT* the cause of this failure. Silently
            # continue to the key-value pair.
        # Else, this child value hint is ignorable.

    # Return this cause as is; all items of this mapping are valid, implying
    # this mapping to deeply satisfy this hint.
    return cause
