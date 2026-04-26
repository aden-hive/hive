#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype sanified type hint metadata dataclass** (i.e., class aggregating
*all* metadata returned by :mod:`beartype._check.convert.convmain` functions).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Optional,
)
from beartype._cave._cavemap import NoneTypeOr
from beartype._check.metadata.hint.hintsane import HintSane
from beartype._data.typing.datatypingport import Hint
from beartype._util.kind.maplike.utilmapfrozen import FrozenDict

# ....................{ TESTERS                            }....................
#FIXME: Unit test us up, please.
def is_hint_recursive(
    # Mandatory parameters.
    hint: Hint,
    hint_parent_sane: Optional[HintSane],

    # Optional parameters.
    hint_recursable_depth_max: int = 0,
) -> bool:
    '''
    :data:`True` only if the passed **recursable type hint** (i.e., type hint
    implicitly supporting recursion like, say, a :pep:`695`-compliant type
    alias) is actually **recursive** (i.e., has already been visited by the
    current breadth-first search (BFS) over all type hints transitively nested
    in some root type hint) with respect to the passed previously sanified
    metadata for the parent type hint of the passed type hint.

    Caveats
    -------
    **This tester assumes this hint to be hashable.** Although *most*
    PEP-compliant hints are hashable, some are not (e.g., :pep:`593`-compliant
    metahints annotated by unhashable objects like ``typing.Annotated[object,
    []]``). Callers that cannot guarantee this hint to be hashable should
    protect calls to this tester inside a ``try`` block explicitly catching the
    :exc:`TypeError` exception this tester raises when this hint is unhashable:

    .. code-block:: python

       # Attempt to test whether hint is recursive or not.
       try:
           if is_hint_recursive(hint=hint, hint_parent_sane=hint_parent_sane):
               pass
       # If doing so raises a "TypeError", this hint is unhashable and thus
       # inapplicable for hint recursion. In this case, ignore this hint.
       except TypeError:
           pass

    Parameters
    ----------
    hint : Hint
        Recursable type hint to be inspected.
    hint_parent_sane : Optional[HintSane]
        Either:

        * If this recursable hint is a root type hint, :data:`None`.
        * Else, **sanified parent type hint metadata** (i.e., immutable and thus
          hashable object encapsulating *all* metadata previously returned by
          :mod:`beartype._check.convert.convmain` sanifiers after sanitizing
          the possibly PEP-noncompliant parent hint of this recursable hint into
          a fully PEP-compliant parent hint).
    hint_recursable_depth_max : int, default: 0
        **Maximum recursion depth** (i.e., maximum total number of times this
        recursable hint is permitted to have been previously visited during the
        current search from the root type hint down to this recursable hint
        before considering this recursable hint to be "recursive").
        Specifically, this tester returns either:

        * If the total number of times this recursable hint has been previously
          visited is less than or equal to this integer, :data:`False`.
        * If the total number of times this recursable hint has been previously
          visited is greater than this integer, :data:`True`.

        Defaults to 0, in which case this recursable hint is considered to be
        "recursive" if this hint has been visited at least once before.

    Returns
    -------
    bool
        :data:`True` only if this recursable type hint is recursive.

    Raises
    ------
    TypeError
        If this hint is unhashable.
    '''
    assert isinstance(hint_parent_sane, NoneTypeOr[HintSane]), (
        f'{repr(hint_parent_sane)} neither sanified hint metadata nor "None".')
    assert isinstance(hint_recursable_depth_max, int), (
        f'{repr(hint_recursable_depth_max)} not integer.')
    assert hint_recursable_depth_max >= 0, (
        f'{repr(hint_recursable_depth_max)} < 0.')

    # True only if...
    is_hint_recursive_state = (
        # This hint has a parent *AND*...
        hint_parent_sane is not None and
        # The total number of times this hint has been visited is greater than
        # this maximum depth, implying this hint to be a transitive parent of
        # itself a sufficient number of times to consider this hint recursive.
        (
            hint_parent_sane.hint_recursable_to_depth.get(hint, 0) >
            hint_recursable_depth_max
        )
    )
    # print(f'Hint {hint} with parent {hint_parent_sane} recursive? {is_hint_recursive_state}')

    # Return this boolean.
    return is_hint_recursive_state

# ....................{ FACTORIES                          }....................
#FIXME: Unit test us up, please.
def make_hint_sane_recursable(
    hint_recursable: Hint,
    hint_nonrecursable: Hint,
    hint_parent_sane: Optional[HintSane],
) -> HintSane:
    '''
    **Sanified type hint metadata** (i.e., :class:`.HintSane` object) safely
    encapsulating both the passed **recursable type hint** (i.e., type hint
    implicitly supporting recursion like, say, a :pep:`695`-compliant type
    alias) and the passed metadata encapsulating the previously sanified parent
    type hint of the passed type hint.

    This factory creates and returns metadata protecting this recursable type
    hint against infinite recursion. Notably, this factory adds this hint to the
    :attr:`HintSane.hint_recursable_to_depth` instance variable of this metadata
    implementing the recursion guard for this hint.

    Parameters
    ----------
    hint_recursable : Hint
        Recursable type hint to be added to the
        :attr:`.HintSane.hint_recursable_to_depth` frozen set of the returned metadata.
    hint_nonrecursable : Hint
        Non-recursable type hint to be encapsulated if this type hint has both
        recursable and non-recursable forms describing this type hint. The
        distinction is as follows:

        * The recursable form of this type hint (passed as the mandatory
          ``hint_recursable`` parameter) is the variant of this hint that will
          be subsequently passed to the :func:`.is_hint_recursive` tester to
          detect whether this hint has already been recursively visited or not.
        * The non-recursable form of this type hint (passed as this optional
          ``hint_nonrecursable`` parameter) is the variant of this hint that
          will be encapsulated as the :attr:`.HintSane.hint` instance variable
          of the returned metadata. This non-recursable form is typically the
          post-sanified hint produced by sanifying the recursable form of the
          pre-sanified hint passed as the ``hint_recursable`` parameter.
    hint_parent_sane : Optional[HintSane]
        Either:

        * If this recursable type hint is a root type hint, :data:`None`.
        * Else, **sanified parent type hint metadata** (i.e., immutable and thus
          hashable object encapsulating *all* metadata previously returned by
          :mod:`beartype._check.convert.convmain` sanifiers after sanitizing
          the possibly PEP-noncompliant parent hint of this hint into a fully
          PEP-compliant parent hint).

    Returns
    -------
    HintSane
        Sanified metadata encapsulating both:

        * This recursable type hint.
        * This sanified parent type hint metadata.
    '''
    assert hint_nonrecursable is not hint_recursable, (
        f'Non-recursable hint {repr(hint_nonrecursable)} == '
        f'recursable hint {repr(hint_recursable)}.'
    )
    assert isinstance(hint_parent_sane, NoneTypeOr[HintSane]), (
        f'{repr(hint_parent_sane)} neither sanified hint metadata nor "None".')

    # Sanified metadata to be returned.
    hint_sane: HintSane = None  # type: ignore[assignment]

    # If this hint has *NO* parent, this is a root hint. In this case...
    if hint_parent_sane is None:
        # Recursion guard recording the recursable form of this root hint to
        # have now been visited exactly once.
        hint_recursable_to_depth = FrozenDict({hint_recursable: 1})

        # Metadata encapsulating this hint and recursion guard.
        hint_sane = HintSane(
            hint=hint_nonrecursable,
            hint_recursable_to_depth=hint_recursable_to_depth,
        )
    # Else, this hint has a parent. In this case...
    else:
        # Total number of times this hint is permitted to have been previously
        # visited during the search from the root hint to this hint, trivially
        # defined as the prior total number of times plus one.
        hint_recursable_depth = (
            hint_parent_sane.hint_recursable_to_depth.get(hint_recursable, 0) +
            1
        )

        # Recursion guard recording the recursable form of this root hint to
        # have been visited this number of times.
        hint_recursable_to_depth = FrozenDict({
            hint_recursable: hint_recursable_depth})

        # If the parent hint is also associated with a recursion guard...
        if hint_parent_sane.hint_recursable_to_depth:
            # Full recursion guard merging the guard associated this parent hint
            # with the guard containing only this child hint, efficiently
            # defined as...
            #
            # Note that the order of operands in this "|" operation is
            # *SIGNIFICANT*. The guard protecting this hint takes precedence
            # over the guard protecting all transitive parent hints of this hint
            # and is thus intentionally passed as the second "|" operand.
            hint_recursable_to_depth = (
                # The guard protecting all transitive parent hints of this hint
                # with...
                hint_parent_sane.hint_recursable_to_depth |  # type: ignore[operator]
                # The guard protecting this hint.
                hint_recursable_to_depth
            )
        # Else, the parent hint is associated with *NO* such guard.

        # Metadata encapsulating this hint and recursion guard, while
        # "cascading" any other metadata associated with this parent hint (e.g.,
        # type variable lookup table) down onto this child hint as well.
        hint_sane = hint_parent_sane.permute_sane(
            hint=hint_nonrecursable,
            hint_recursable_to_depth=hint_recursable_to_depth,
        )

    # Return this underlying type hint.
    return hint_sane
