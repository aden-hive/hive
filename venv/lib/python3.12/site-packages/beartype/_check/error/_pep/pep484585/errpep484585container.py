#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`484`- and :pep:`585`-compliant **single-argument sequence type
hint violation finders** (i.e., functions returning human-readable strings
explaining violations of :pep:`484`- and :pep:`585`-compliant type hints
subscripted by one child type hint constraining *all* items contained in that
container satisfying the :class:`collections.abc.Container` protocol).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeCallHintPepRaiseException
from beartype._check.logic.logmap import (
    HINT_SIGN_PEP484585_CONTAINER_TO_LOGIC_get)
from beartype._check.error.errcause import ViolationCause
from beartype._check.error._errtype import find_cause_type_instance_origin
from beartype._check.metadata.hint.hintsane import HINT_SANE_IGNORABLE
from beartype._data.hint.sign.datahintsigns import HintSignPep484585TupleFixed
from beartype._data.hint.sign.datahintsignmap import (
    HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE)
from beartype._data.hint.sign.datahintsignset import (
    HINT_SIGNS_CONTAINER_ARGS_1)
from beartype._util.hint.pep.proposal.pep484585646 import (
    is_hint_pep484585646_tuple_empty)
from beartype._util.text.utiltextansi import color_type
from beartype._util.text.utiltextprefix import prefix_pith_type
from beartype._util.text.utiltextrepr import represent_pith
from collections.abc import (
    Collection as CollectionABC,
)

# ....................{ FINDERS                            }....................
def find_cause_pep484585_container_args_1(cause: ViolationCause) -> ViolationCause:
    '''
    Output cause describing whether the pith of the passed input cause either
    satisfies or violates the **single-argument container type hint**
    (i.e., :pep:`484`- or :pep:`585`-compliant type hint subscripted by one
    child type hint constraining *all* items contained in that container
    satisfying the :class:`collections.abc.Container` protocol) of that cause.

    Parameters
    ----------
    cause : ViolationCause
        Input violation cause finder to be inspected.

    Returns
    -------
    ViolationCause
        Output violation cause finder type-checking this input.
    '''
    assert isinstance(cause, ViolationCause), f'{repr(cause)} not cause.'
    assert cause.hint_sign in HINT_SIGNS_CONTAINER_ARGS_1, (
        f'{repr(cause.hint)} not 1-argument container type hint.')

    # Number of child type hints expected to be subscripting this hint.
    hints_child_len_expected = (
        HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE[cause.hint_sign])

    # Assert this hint was subscripted by the expected number of child type
    # hints. Note that prior logic should have already guaranteed this.
    assert len(cause.hint_childs_sane) in hints_child_len_expected, (
        f'Container type hint {repr(cause.hint)} number of child type hints '
        f'{len(cause.hint_childs_sane)} not in {hints_child_len_expected}.'
    )

    # Shallow output cause describing the failure of this path to be a shallow
    # instance of the type originating this hint (e.g., "list" for the hint
    # "list[str]") if this pith is not an instance of this type *OR* "None"
    # otherwise (i.e., if this pith is an instance of this type).
    cause_shallow = find_cause_type_instance_origin(cause)

    # If this pith is *NOT* an instance of this type, return this shallow cause.
    if cause_shallow.cause_str_or_none is not None:
        return cause_shallow
    # Else, this pith is an instance of this type.

    # First sanified child hint metadata subscripting this parent container
    # hint. All remaining child hints if any are ignorable. Specifically, if
    # this hint is:
    # * A standard container (e.g., "typing.List[str]"), this hint is subscripted
    #   by only one child hint.
    # * A variadic tuple (e.g., "typing.Tuple[str, ...]"), this hint is
    #   subscripted by only two child hints -- the latter of which is guaranteed
    #   to be an ellipses and thus ignorable syntactic chuff.
    hint_child_sane = cause.hint_childs_sane[0]

    # If either...
    if (
        # This container is empty, *ALL* items of this container (of which there
        # are none) are necessarily valid *OR*...
        #
        # Note that this test *CANNOT* safely be optimized away to simply:
        #     not cause.pith or
        #
        # Why? Because a container being a collection does *NOT* necessarily
        # imply that container to sanely implement the __bool__() dunder method.
        # The canonical example is the third-party "tensor.Torch" type, a
        # collection whose __bool__() dunder method raises exceptions for
        # tensors containing one or more values: e.g.,
        #     RuntimeError: Boolean value of Tensor with more than one value is
        #     ambiguous
        not len(cause.pith) or
        # This child hint is ignorable...
        hint_child_sane is HINT_SANE_IGNORABLE
    ):
        # Then this container satisfies this hint. In this case, return the
        # passed cause as is.
        return cause
    # Else, this container is non-empty *AND* this child hint is unignorable.

    # Hint logic type-checking this sign if any *OR* "None" otherwise.
    hint_logic = HINT_SIGN_PEP484585_CONTAINER_TO_LOGIC_get(cause.hint_sign)

    # If *NO* hint logic type-checks this sign, raise an exception. Note
    # that this logic should *ALWAYS* be non-"None". Nonetheless, assumptions.
    if hint_logic is None:  # pragma: no cover
        raise _BeartypeCallHintPepRaiseException(
            f'{cause.exception_prefix}1-argument container type hint '
            f'{repr(cause.hint)} beartype sign {repr(cause.hint_sign)} '
            f'code generation logic not found.'
        )
    # Else, some hint logic type-checks this sign.

    # If this pith is a collection, this pith is at least safely reiterable here
    # and thus deeply introspectable. In this case...
    if isinstance(cause.pith, CollectionABC):
        # Arbitrary iterator over this container configured by this beartype
        # configuration satisfying the enumerate() protocol. This iterator
        # yields zero or more 2-tuples of the form "(item_index, item)", where:
        # * "item_index" is the 0-based index of each item.
        # * "item" is an arbitrary item of this container.
        pith_enumerator = hint_logic.enumerate_cause_items(cause)

        # For each enumerated item of this container...
        for pith_item_index, pith_item in pith_enumerator:
            # Deep output cause describing the failure of this item to satisfy
            # this child hint if this item violates this child hint *OR* "None"
            # otherwise (i.e., if this item satisfies this child hint).
            cause_deep = cause.permute_cause(
                hint_sane=hint_child_sane, pith=pith_item).find_cause()

            # If this item is the cause of this failure...
            if cause_deep.cause_str_or_none is not None:
                # Human-readable substring prefixing this failure with metadata
                # describing this item.
                cause_deep.cause_str_or_none = (
                    f'{prefix_pith_type(pith=cause.pith, is_color=cause.conf.is_color)}'
                    f'index {color_type(text=str(pith_item_index), is_color=cause.conf.is_color)} '
                    f'item {cause_deep.cause_str_or_none}'
                )

                # Return this cause.
                return cause_deep
            # Else, this item is *NOT* the cause of this failure. Silently
            # continue to the next item.
    # Else, this pith is *NOT* collection and thus *NOT* safely reiterable here.
    # We have *NO* recourse but to assume this pith deeply satisfies this hint.

    # Return this cause as is; all items of this container are valid, implying
    # this container to deeply satisfy this hint.
    return cause


def find_cause_pep484585_tuple_fixed(cause: ViolationCause) -> ViolationCause:
    '''
    Output cause describing whether the pith of the passed input cause either
    satisfies or violates the **fixed-length tuple type hint** (i.e.,
    PEP-compliant type hint accepting zero or more subscripted arguments
    iteratively constraining each item of this fixed-length tuple) of that
    cause.

    Parameters
    ----------
    cause : ViolationCause
        Input violation cause finder to be inspected.

    Returns
    -------
    ViolationCause
        Output violation cause finder type-checking this input.
    '''
    assert isinstance(cause, ViolationCause), f'{repr(cause)} not cause.'
    assert cause.hint_sign is HintSignPep484585TupleFixed, (
        f'{repr(cause.hint_sign)} not "HintSignPep484585TupleFixed".')

    # Shallow output cause describing the failure of this path to be a shallow
    # instance of the type originating this hint (e.g., "tuple" for the hint
    # "tuple[str]") if this pith is not an instance of this type *OR* "None"
    # otherwise (i.e., if this pith is an instance of this type).
    cause_shallow = find_cause_type_instance_origin(cause)

    # If this pith is *NOT* a tuple, return this shallow cause.
    if cause_shallow.cause_str_or_none is not None:
        return cause_shallow
    # Else, this pith is a tuple.
    #
    # If this hint is the empty fixed-length tuple, validate this pith to be
    # the empty tuple.
    elif is_hint_pep484585646_tuple_empty(cause.hint):
        # If this pith is the empty tuple, this path satisfies this hint.
        #
        # Note that this test *CANNOT* safely be optimized away to simply:
        #     not cause.pith or
        #
        # See above for additional commentary as to why.
        if not len(cause.pith):
            return cause
        # Else, this tuple is non-empty and thus fails to satisfy this hint.

        # Deep output cause to be returned, permuted from this input cause
        # with a human-readable string describing this failure.
        cause_deep = cause.permute_cause(cause_str_or_none=(
            f'tuple {represent_pith(cause.pith)} non-empty'))

        # Return this cause.
        return cause_deep
    # Else, this hint is a standard fixed-length tuple.
    #
    # If this pith and hint are of differing lengths, this tuple fails to
    # satisfy this hint. In this case...
    elif len(cause.pith) != len(cause.hint_childs_sane):
        # Deep output cause to be returned, permuted from this input cause
        # with a human-readable string describing this failure.
        cause_deep = cause.permute_cause(cause_str_or_none=(
            f'tuple {represent_pith(cause.pith)} length '
            f'{len(cause.pith)} != {len(cause.hint_childs_sane)}'
        ))

        # Return this cause.
        return cause_deep
    # Else, this pith and hint are of the same length.

    # For each enumerated item of this tuple...
    for pith_item_index, pith_item in enumerate(cause.pith):
        # Child hint corresponding to this tuple item. Since this pith and
        # hint are of the same length, this child hint exists.
        hint_child_sane = cause.hint_childs_sane[pith_item_index]
        # print(f'tuple pith: {repr(pith_item)}\ntuple hint child: {repr(hint_child)}')

        # If this child hint is ignorable, continue to the next.
        if hint_child_sane is HINT_SANE_IGNORABLE:
            continue
        # Else, this child hint is unignorable.

        # Deep output cause to be returned, type-checking whether this tuple
        # item satisfies this child hint.
        cause_deep = cause.permute_cause(
            hint_sane=hint_child_sane, pith=pith_item).find_cause()

        # If this item is the cause of this failure...
        if cause_deep.cause_str_or_none is not None:
            # print(f'tuple pith: {sleuth_copy.pith}\ntuple hint child: {sleuth_copy.hint}\ncause: {pith_item_cause}')

            # Human-readable substring prefixing this failure with metadata
            # describing this item.
            cause_deep.cause_str_or_none = (
                f'{prefix_pith_type(pith=cause.pith, is_color=cause.conf.is_color)}'
                f'index {color_type(text=str(pith_item_index), is_color=cause.conf.is_color)} '
                f'item {cause_deep.cause_str_or_none}'
            )

            # Return this cause.
            return cause_deep
        # Else, this item is *NOT* the cause of this failure. Silently
        # continue to the next.

    # Return this cause as is; all items of this fixed-length tuple are valid,
    # implying this pith to deeply satisfy this hint.
    return cause
