#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`- and :pep:`604`-compliant **union type hint utilities**
(i.e., low-level callables handling union type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep604Exception
from beartype._cave._cavefast import (
    HintPep604Type,
    HintPep604ItemTypes,
)
from beartype._data.kind.datakindiota import SENTINEL
from beartype._data.typing.datatypingport import (
    Hint,
    SequenceHints,
    TypeIs,
)
from beartype._util.cache.utilcachecall import callable_cached
from collections.abc import Sequence
from functools import reduce
from operator import __or__ as or_operator

# ....................{ RAISERS                        }....................
#FIXME: Unit test us up, please.
def die_if_hint_pep604_inconsistent(hint: Hint) -> None:
    '''
    Raise an exception if the passed object is a :pep:`604`-compliant
    **inconsistent type hint** (i.e., object permissible as an item of a
    :pep:`604`-compliant new union whose machine-readable representation is
    *not* the machine-readable representation of this hint in new unions).

    Motivation
    ----------
    This raiser protects the :mod:`beartype` codebase against inconsistencies in
    poorly implemented third-party type hints whose **machine-readable
    representations** (i.e., strings returned by passing those hints to the
    :func:`repr` builtin) differ from their representations in new unions
    containing those hints.

    Ideally, *no* such inconsistencies would ever exist. For unknown reasons,
    some third-party type hints induce such inconsistencies. :mod:`nptyping` is
    the canonical example. Type hint factories published by :mod:`nptyping`
    dynamically create in-memory classes all sharing the same fully-qualified
    names despite being distinct classes. Ye who code, grok and weep: e.g.,

    .. code-block:: pycon

       # Define two typical "nptyping" type hints.
       >>> from nptyping import Float64, NDArray, Shape
       >>> foo = NDArray[Shape["N, N"], Float64]
       >>> bar = NDArray[Shape["*"], Float64]

       >>> repr(foo)
       NDArray[Shape["N, N"], Float64]  # <-- this is sane
       >>> repr(bar)
       NDArray[Shape["*"], Float64]  # <-- this is sane, too

       >>> foo == bar
       False    # <-- still sane
       >>> foo.__name__
       NDArray  # <-- this is insane
       >>> bar.__name__
       NDArray  # <-- still insane after all these years

       >>> foo | None == bar | None
       False           # <-- back to sane
       >>> repr(foo | None)
       NDArray | None  # <-- big yikes
       >>> repr(bar | None)
       NDArray | None  # <-- yikes intensifies

    ``foo`` and ``bar`` are distinct type hints matching different NumPy arrays;
    their representations are likewise distinct. The new unions of those hints
    with :data:`None` are also distinct type hints; nonetheless, the
    representations of those new unions **are the exact same.**

    This raiser detects this inconsistency by raising an exception from the
    :func:`beartype.beartype` decorator. If we failed to do so, then
    :func:`beartype.beartype` would behave non-deterministically when presented
    with such hints. Consider the following decoration:

    .. code-block:: python

       @beartype
       def bad_func(first_array: foo | None, second_array: bar | None) -> None:
           ...

    Given that decoration, :func:`beartype.beartype` would (in order):

    #. Cache the first new union ``foo | None`` under the string representation
       ``"NDArray | None"``.
    #. Erroneously replace the second new union ``bar | None`` with the
       previously cached new union ``foo | None``. Why? Because those two new
       unions share the same representations. From the limited perspective of
       :mod:`beartype`, those two new unions are effectively the same new union
       and thus can be safely de-duplicated. *This is why we facepalm.*

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Raises
    ------
    BeartypeDecorHintPep604Exception
        If this object is a :pep:`604`-compliant inconsistent type hint.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.utilhintget import get_hint_repr

    # If this hint is invalid as an item of a PEP 604-compliant new union,
    # silently reduce to a noop.
    if not isinstance(hint, HintPep604ItemTypes):
        return
    # Else, this hint is valid as an item of a PEP 604-compliant new union.

    # Machine-readable representation of this hint.
    hint_repr = get_hint_repr(hint)

    # If this representation is prefixed by the "<" character, this
    # representation is assumed to be (at least *SOMEWHAT*) standardized and
    # thus internally consistent. This includes:
    # * Standard classes (e.g., "<class 'bool'>").
    # * @beartype-specific forward reference subclasses (e.g., "<forwardref
    #   UndeclaredClass(__beartype_scope__='some_package')>").
    #
    # This is *NOT* simply an optimization. Standardized representations
    # *MUST* be excluded from consideration, as the representations of new
    # unions containing these hints is *NOT* prefixed by "<": e.g.,
    #     >>> repr(bool)
    #     <class 'bool'>
    #     >>> bool | None
    #     bool | None
    if hint_repr[0] == '<':
        return
    # Else, this representation is *NOT* prefixed by the "<" character.

    # Arbitrary PEP 604-compliant new union defined as the conjunction
    # of this hint with an arbitrary builtin type guaranteed to exist.
    #
    # Note that order is significant.
    hint_pep604 = hint | int  # type: ignore[operator]

    # Machine-readable representation of this new union.
    hint_pep604_repr = get_hint_repr(hint_pep604)

    # If the representation of this new union is *NOT* prefixed by the
    # representation of this hint, raise an exception.
    if not hint_pep604_repr.startswith(hint_repr):
        raise BeartypeDecorHintPep604Exception(
            f'Type hint {hint_repr} inconsistent with respect to '
            f'repr() strings: e.g.,\n'
            f'\t>>> repr({hint_repr})\n'
            f'\t{hint_repr}  # <-- this is fine\n'
            f'\t>>> repr({hint_repr} | int)\n'
            f'\t{hint_pep604_repr}  # <-- *THIS IS REALLY SUPER BAD*\n'
            f'\n'
            f'\t# Ideally, that output should instead resemble:\n'
            f'\t>>> repr({hint_repr} | int)\n'
            f'\t{hint_repr} | int  # <-- what @beartype wants!\n'
            f'\n'
            f'Inconsistent type hints are unsupported by @beartype, '
            f'which requires consistency between type hints and '
            f'repr() strings. Consider reporting this issue to the '
            f'third-party developers implementing this hint, which '
            f'(probably) fails to define the PEP 585-compliant '
            f'"__args__" and "__origin__" dunder attributes standardized '
            f'by the "types.GenericAlias" API. See also:\n'
            f'\thttps://peps.python.org/pep-0585/#parameters-to-generics-are-available-at-runtime'
        )
    # Else, the representation of this new union is prefixed by the
    # representation of this hint as expected.

# ....................{ TESTERS                        }....................
def is_hint_pep604(hint: object) -> TypeIs[Hint]:
    '''
    :data:`True` only if the passed object is a :pep:`604`-compliant **union**
    (i.e., ``|``-delimited disjunction of two or more isinstanceable types).

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a :pep:`604`-compliant union.
    '''

    # Release the werecars, Bender!
    return isinstance(hint, HintPep604Type)


# ....................{ FACTORIES                          }....................
#FIXME: Unit test us up, please.
@callable_cached
def make_hint_pep484604_union(hint_childs: SequenceHints) -> Hint:
    '''
    :pep:`604`- or :pep:`484`-compliant union type hint synthesized from the
    passed sequence of two or more PEP-compliant type hints if this sequence
    contains two or more items, the one PEP-compliant type hint in this sequence
    if this sequence contains only one item, *or* raise an exception otherwise
    (i.e., if this sequence is empty).

    This factory preferentially creates and returns (in descending order of
    preference):

    * If *all* of the items in the passed sequence are valid items of a
      :pep:`604`-compliant **new-style union** (``|``-delimited union of two or
      more types under Python >= 3.10), that union of these items.
    * Else, a :pep:`484`-compliant **old-style union** (i.e.,
      :obj:`typing.Union` subscription) of these items.

    This factory is memoized for efficiency. Technically, the
    :attr:`typing.Union` type hint factory already caches its subscripted
    arguments. Pragmatically, that caching is slow and thus worth optimizing
    with trivial optimization on our end. Moreover, this factory is called by
    the performance-sensitive
    :func:`beartype._check.convert._convcoerce.coerce_hint_any` coercer in an
    early-time code path of the :func:`beartype.beartype` decorator. Optimizing
    this factory thus optimizes :func:`beartype.beartype` itself. Even more
    importantly, :pep:`604`-compliant new-style unions are *not* self-caching:

    .. code-block:: pycon

       >>> int | bool is int | bool
       False  # <-- *BIG YIKES*

    Parameters
    ----------
    hint_childs : SequenceHints
        Sequence of all child type hints to be unioned together.

    Returns
    -------
    Hint
        Either:

        * If this sequence contains two or more items, the union type hint
          synthesized from these items.
        * If this sequence contains only one item, this item as is.

    Raises
    ------
    BeartypeDecorHintPep604Exception
        If this sequence is empty.
    '''
    assert isinstance(hint_childs, Sequence), (
        f'{repr(hint_childs)} not sequence.')

    # If this sequence is empty, raise an exception.
    if not hint_childs:
        raise BeartypeDecorHintPep604Exception('"hints" sequence empty.')
    # Else, this sequence contains one or more child type hints.
    #
    # If this sequence contains only one child type hint, return this hint
    # unmodified as is.
    elif len(hint_childs) == 1:
        return hint_childs[0]
    # Else, this sequence contains two or more child type hints.
    #
    # If this sequence is *NOT* already a tuple, coerce this sequence into a
    # tuple. The lower-level functions called below all expected a tuple, oddly.
    elif not isinstance(hint_childs, tuple):
        hint_childs = tuple(hint_childs)
    # Else, this sequence is already a tuple. In this case, preserve this tuple.

    # Union of these child type hints to be returned.
    hint_union: Hint = SENTINEL  # type: ignore[assignment]

    # Attempt to dynamically fabricate a PEP 604-compliant new-style union of
    # these items if these items are all PEP 604-compliant.
    try:
        hint_union = reduce(or_operator, hint_childs)  # type: ignore[assignment]
    # If *ANY* exception whatsoever is raised, one or more of these items are
    # PEP 604-noncompliant. In this case, silently ignore this exception in
    # favour of falling back to a PEP 484-compliant old-style union below. We
    # don't make breaky. We only fix breaky, people.
    except Exception:
        pass

    # If a PEP 604-compliant new-style union was *NOT* fabricated above...
    if hint_union is SENTINEL:
        # Avoid circular import dependencies.
        from beartype._util.hint.pep.proposal.pep484.pep484union import (
            make_hint_pep484_union)

        # Fallback to a PEP 484-compliant old-style union.
        hint_union = make_hint_pep484_union(hint_childs)
    # Else, a PEP 604-compliant new-style union was fabricated above.

    # Return this union.
    return hint_union
