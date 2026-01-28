#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **dictionary testers** (i.e., low-level callables testing and
validating the contents of passed dictionaries in various general-purpose ways).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilMappingException
from beartype.typing import AbstractSet
from collections.abc import (
    Hashable,
    Mapping,
    Set,
)

# ....................{ VALIDATORS                         }....................
def die_if_mappings_two_items_collide(
    mapping_a: Mapping, mapping_b: Mapping) -> None:
    '''
    Raise an exception if the two passed mappings contain a **key-value
    collision** (i.e., the same key such that the values associated with that
    key in these mappings differ).

    A key-value collision occurs when any key ``ka`` and associated value
    ``va`` of the first mapping and any key ``kb`` and associated value ``vb``
    of the second mapping satisfy ``ka == kb && va != vb``. Equivalently, a
    key-value collision occurs when any common keys shared between both
    mappings are associated with different values.

    Parameters
    ----------
    mapping_a: Mapping
        First mapping to be inspected.
    mapping_b: Mapping
        Second mapping to be inspected.

    Raises
    ------
    _BeartypeUtilMappingException
        If these mappings contain one or more key-value collisions.
    '''
    assert isinstance(mapping_a, Mapping), f'{repr(mapping_a)} not mapping.'
    assert isinstance(mapping_b, Mapping), f'{repr(mapping_b)} not mapping.'

    # For each key of the first mapping...
    for mapping_a_key in mapping_a:
        # If...
        #
        # Note this simplistic detection logic has been exhaustively optimized
        # with iterative profiling to be the most performant solution. Notably,
        # alternative solutions calling dictionary methods (e.g., dict.items(),
        # dict.get()) are *DRAMATICALLY* slower -- which is really fascinating.
        # CPython appears to have internally optimized pure dictionary syntax.
        if (
            # This key resides in the second mapping as well *AND*...
            mapping_a_key in mapping_b and
            # This key unsafely maps to a different value in the second
            # mapping...
            mapping_a[mapping_a_key] is not mapping_b[mapping_a_key]
        ):
        # Immediately short-circuit this iteration to raise an exception below.
        # Merging these mappings would silently and thus unsafely override the
        # values associated with these keys in the first mapping with the
        # values associated with these keys in the second mapping.
            break
    # Else, all key collisions are safe (i.e., all shared keys are associated
    # with the same values in both mappings). Since merging these mappings as
    # is will *NOT* silently and thus unsafely override any values of either
    # mapping, accept these mappings as is.
    #
    # Note that this awkward branching structure has been profiled to be
    # optimally efficient, for reasons that honestly elude us. Notably, this
    # structure is faster than:
    # * The equivalent "any(...)" generator comprehension -- suggesting we
    #   should similarly unroll *ALL* calls to the any() and all() builtins in
    #   our critical performance path. Thanks, CPython.
    # * The equivalent test against items intersection, which has the
    #   additional caveat of raising an exception when one or more mapping
    #   items are unhashable and is thus substantially more fragile: e.g.,
    #       if len(mapping_keys_shared) == len(mapping_a.items() & mapping_b.items()):
    #           return
    else:
        return

    # Set of all key collisions (i.e., keys residing in both mappings). Since
    # keys are necessarily hashable, this set intersection is guaranteed to be
    # safe and thus *NEVER* raise a "TypeError" exception.
    #
    # Note that omitting the keys() method call on the latter but *NOT* former
    # mapping behaves as expected and offers a helpful microoptimization.
    mapping_keys_shared = mapping_a.keys() & mapping_b  # type: ignore[operator]

    # Set of all keys in all item collisions (i.e., items residing in both
    # mappings). Equivalently, this is the set of all safe key collisions (i.e.,
    # all shared keys associated with the same values in both mappings).
    #
    # Ideally, we would efficiently intersect these items as follows:
    #     mapping_items_shared = mapping_a.items() & mapping_b.items()
    # Sadly, doing so raises a "TypeError" if one or more values of these
    # mappings are unhashable -- as they typically are in common use cases
    # throughout this codebase. Ergo, we fallback to a less efficient but
    # considerably more robust alternative supporting unhashable values.
    mapping_keys_shared_safe = {
        # For each possibly unsafe key collision (i.e., shared key associated
        # with possibly different values in both mappings), this key...
        mapping_key_shared
        for mapping_key_shared in mapping_keys_shared
        # If this key maps to the same value in both mappings and is thus safe.
        if (
            mapping_a[mapping_key_shared] is
            mapping_b[mapping_key_shared]
        )
    }

    # Dictionary of all unsafe key-value pairs (i.e., pairs such that merging
    # these keys would silently override the values associated with these keys
    # in either the first or second mappings) from these mappings.
    mapping_a_unsafe = dict(
        (key_shared_unsafe, mapping_a[key_shared_unsafe])
        for key_shared_unsafe in mapping_keys_shared
        if key_shared_unsafe not in mapping_keys_shared_safe
    )
    mapping_b_unsafe = dict(
        (key_shared_unsafe, mapping_b[key_shared_unsafe])
        for key_shared_unsafe in mapping_keys_shared
        if key_shared_unsafe not in mapping_keys_shared_safe
    )

    # Raise a human-readable exception.
    exception_message = (
        f'Mappings not safely mergeable due to key-value collisions:\n'
        f'~~~~[ mapping_a collisions ]~~~~\n{repr(mapping_a_unsafe)}\n'
        f'~~~~[ mapping_b collisions ]~~~~\n{repr(mapping_b_unsafe)}'
    )
    # print(exception_message)
    raise _BeartypeUtilMappingException(exception_message)

# ....................{ TESTERS                            }....................
#FIXME: Unit test us up, please.
def is_mapping_keys_all(
    mapping: Mapping, keys: AbstractSet[Hashable]) -> bool:
    '''
    :data:`True` only if the passed mapping contains *all* of the passed keys.

    Parameters
    ----------
    mapping: Mapping
        Mapping to be tested.
    keys: AbstractSet[Hashable]
        Set of one or more keys to test this mapping against.

    Returns
    -------
    bool
        :data:`True` only if this mapping contains *all* of these keys.
    '''
    assert isinstance(mapping, Mapping), f'{repr(mapping)} not mapping.'
    assert isinstance(keys, Set), f'{repr(keys)} not set.'
    assert bool(keys), 'Keys empty.'

    # Return true only if this mapping contains *ALL* of these keys,
    # equivalent to efficiently testing whether this set of one or more keys is
    # a strict subset of the set of all keys in this mapping.
    #
    # Note that we intentionally do *NOT* call the set.issubclass() method here.
    # Even standard set types that otherwise satisfy the "collections.abc.Set"
    # protocol do *NOT* necessarily define that method.
    return keys <= mapping.keys()


#FIXME: Unit test us up, please.
def is_mapping_keys_any(
    mapping: Mapping, keys: AbstractSet[Hashable]) -> bool:
    '''
    :data:`True` only if the passed mapping contains *any* (i.e., one or more,
    at least one) of the passed keys.

    Parameters
    ----------
    mapping: Mapping
        Mapping to be tested.
    keys: AbstractSet[Hashable]
        Set of one or more keys to test this mapping against.

    Returns
    -------
    bool
        :data:`True` only if this mapping contains *any* of these keys.
    '''
    assert isinstance(mapping, Mapping), f'{repr(mapping)} not mapping.'
    assert isinstance(keys, Set), f'{repr(keys)} not set.'
    assert bool(keys), 'Keys empty.'

    # Return true only if this mapping contains one or more of these keys,
    # equivalent to efficiently testing whether the set intersection between
    # this set of one or more keys *AND* the set of all keys in this mapping is
    # a non-empty set.
    return bool(keys & mapping.keys())
