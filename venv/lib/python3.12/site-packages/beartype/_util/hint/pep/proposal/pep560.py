#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`560`-compliant **generic type hint iterators** (i.e.,
low-level callables generically iterating over the ``__orig_bases__`` dunder
attribute defining the pseudo-superclasses of :pep:`484`- and
:pep:`560`-compliant generic class hierarchies).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep560Exception
from beartype._data.typing.datatypingport import (
    Hint,
    IterableHints,
)
from beartype._data.typing.datatyping import TypeException
from beartype._util.cache.pool.utilcachepoollistfixed import (
    FIXED_LIST_SIZE_MEDIUM,
    acquire_fixed_list,
    release_fixed_list,
)

# ....................{ TESTERS                            }....................
def is_hint_pep560(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed hint is :pep:`560`-compliant (i.e., defines
    the ``__orig_bases__`` dunder attribute), strongly implying this hint to be
    a :pep:`560`-compliant generic.

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this hint is :pep:`560`-compliant.
    '''

    # Return true only if this hint defines this dunder attribute.
    return hasattr(hint, '__orig_bases__')

# ....................{ ITERATORS                          }....................
#FIXME: Unit test us up, please.
def iter_hint_pep560_bases_unerased(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep560Exception,
    exception_prefix: str = '',
) -> IterableHints:
    '''
    Generator iteratively yielding the one or more **unerased
    pseudo-superclasses** (i.e., unignorable PEP-compliant type hints originally
    declared as transitive superclasses prior to type erasure) of the passed
    **generic** (i.e., :pep:`484`- or :pep:`585`-compliant subscriptable type in
    either unsubscripted or subscripted form), effectively performing a
    breadth-first search (BFS) over these pseudo-superclasses.

    This generator yields the full tree of all pseudo-superclasses by
    transitively visiting both all direct pseudo-superclasses of this generic
    *and* all indirect pseudo-superclasses transitively superclassing all direct
    pseudo-superclasses of this generic. For efficiency, this generator is
    internally implemented with an efficient imperative First In First Out
    (FILO) queue rather than an inefficient (and dangerous, due to both
    unavoidable stack exhaustion and avoidable infinite recursion) tree of
    recursive function calls.

    This generator intentionally defers to *no* other :pep:`484`- or
    :pep:`585`-compliant generic functionality, enabling this generator to be
    safely called by that functionality without concern for circular logic.

    This generator is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator). Memoization is the caller's responsibility.

    Caveats
    -------
    **The higher-level**
    :func:`beartype._check.pep.get_hint_pep484585_generic_unsubbed_bases_unerased`
    **generator should typically be called instead.** This lower-level generator
    is *only* intended to be called by equally low-level utility functions
    throughout the :mod:`beartype._util.hint.pep.proposal` subpackage.

    **This generator exhibits** :math:`O(n)` **linear time complexity for**
    :math:`n` the number of transitive pseudo-superclasses of this generic. So,
    this generator is slow. The caller is expected to memoize *all* calls to
    this generator, which is itself *not* memoized.

    Parameters
    ----------
    hint : Hint
        Generic to be inspected.
    exception_cls : TypeException, default: BeartypeDecorHintPep560Exception
        Type of exception to be raised in the event of fatal error. Defaults to
        :exc:`.BeartypeDecorHintPep560Exception`.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Yields
    ------
    Hint
        Unerased transitive pseudo-superclass originally declared as a
        superclass prior to its type erasures by this generic.

    Raises
    ------
    exception_cls
        If this hint is *not* a generic.
    '''

    # ....................{ LOCALS ~ bases : direct        }....................
    # Tuple of the one or more unerased pseudo-superclasses (i.e., originally
    # listed as superclasses prior to type erasure) of the passed generic if
    # this generic is actually a PEP 560-compliant generic *OR* "None".
    hint_bases_direct = getattr(hint, '__orig_bases__', None)
    # print(f'generic {hint} hint_bases_direct: {hint_bases_direct}')

    # If this generic is *NOT* actually a PEP 560-compliant generic...
    if hint_bases_direct is None:
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not exception type.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Raise an exception.
        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} '
            f'not PEP 484- or 585-compliant generic.'
        )
    # Else, this generic is a PEP 560-compliant generic.

    # ....................{ LOCALS ~ bases : indirect      }....................
    # Fixed list of the one or more unerased transitive pseudo-superclasses
    # originally listed as superclasses prior to their type erasure by this
    # generic that have yet to be visited by the breadth-first search (BFS) over
    # these pseudo-superclasses performed below.
    hint_bases = acquire_fixed_list(size=FIXED_LIST_SIZE_MEDIUM)

    # 0-based index of the currently visited pseudo-superclass of this list.
    hint_bases_index_curr = 0

    # 0-based index of one *PAST* the last pseudo-superclass of this list.
    hint_bases_index_past_last = len(hint_bases_direct)

    # Initialize this list to these direct pseudo-superclasses of this generic.
    hint_bases[0:hint_bases_index_past_last] = hint_bases_direct

    # ....................{ SEARCH                         }....................
    # While the 0-based index of the next visited pseudo-superclass does *NOT*
    # exceed that of the last pseudo-superclass in this list, there remains one
    # or more pseudo-superclasses to be visited in this BFS. Let us do so.
    while hint_bases_index_curr < hint_bases_index_past_last:
        # ....................{ LOCALS                     }....................
        # Currently visited transitive pseudo-superclass of the passed generic.
        hint_base = hint_bases[hint_bases_index_curr]

        # Yield this pseudo-superclass to the caller.
        yield hint_base

        # Tuple of the one or more unerased pseudo-superclasses of this
        # pseudo-superclass if this pseudo-superclass is itself a PEP
        # 560-compliant generic *OR* "None" otherwise (i.e., if this
        # pseudo-superclass is *NOT* a PEP 560-compliant generic).
        hint_base_bases_direct = getattr(hint_base, '__orig_bases__', None)

        # If this pseudo-superclass is a PEP 560-compliant generic...
        if hint_base_bases_direct is not None:
            # 0-based index of the last pseudo-superclass of this list
            # *BEFORE* adding onto this list.
            hint_bases_index_past_last_prev = hint_bases_index_past_last

            # 0-based index of the last pseudo-superclass of this list
            # *AFTER* adding onto this list.
            hint_bases_index_past_last += len(hint_base_bases_direct)

            # Enqueue all parent pseudo-superclasses of this child
            # pseudo-superclass onto this list for later visitation by this BFS.
            hint_bases[
                hint_bases_index_past_last_prev:hint_bases_index_past_last] = (
                hint_base_bases_direct)
        # Else, this pseudo-superclass is *NOT* a PEP 560-compliant generic.

        #FIXME: *NICE*. For safety, we should also be doing something similar in
        #our make_check_expr()-driven dynamic code generator as well.
        # Nullify the previously visited pseudo-superclass in this list,
        # avoiding spurious memory leaks by encouraging garbage collection.
        hint_bases[hint_bases_index_curr] = None

        # Increment the 0-based index of the next visited pseudo-superclass in
        # this list *BEFORE* visiting that pseudo-superclass but *AFTER*
        # performing all other logic for the current pseudo-superclass.
        hint_bases_index_curr += 1

    # ....................{ POSTAMBLE                      }....................
    # Release this list. Pray for salvation, for we find none here.
    release_fixed_list(hint_bases)
