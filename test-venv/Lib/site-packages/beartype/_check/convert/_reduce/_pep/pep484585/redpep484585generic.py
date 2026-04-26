#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`- and :pep:`585`-compliant **generic reducers** (i.e.,
low-level callables converting higher-level subscripted and unsubscripted
generics to lower-level type hints more readily consumable by :mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Generic,
    Optional,
)
from beartype._data.typing.datatypingport import Hint
from beartype._check.metadata.hint.hintsane import (
    HINT_SANE_IGNORABLE,
    HintOrSane,
    HintSane,
)
from beartype._util.hint.pep.proposal.pep544 import is_hint_pep484_generic_io
from beartype._util.hint.pep.utilpepget import get_hint_pep_origin_or_none

# ....................{ REDUCERS                           }....................
def reduce_hint_pep484585_generic_subbed(
    hint: Hint,
    hint_parent_sane: Optional[HintSane],
    exception_prefix: str,
    **kwargs,
) -> HintOrSane:
    '''
    Reduce the passed :pep:`484`- or :pep:`585`-compliant **subscripted
    generic** (i.e., object subscripted by one or more child type hints
    originating from a type originally subclassing at least one subscripted
    :pep:`484`- or :pep:`585`-compliant pseudo-superclass) to a more suitable
    type hint better supported by :mod:`beartype` if necessary.

    This reducer ignores *all* parametrizations of the :class:`typing.Generic`
    abstract base class (ABC) by one or more type variables. As the name
    implies, this ABC is generic and thus fails to impose any meaningful
    constraints. Since a type variable in and of itself also fails to impose any
    meaningful constraints, these parametrizations are safely ignorable in all
    possible contexts: e.g.,

    .. code-block:: python

       from typing import Generic, TypeVar
       T = TypeVar('T')
       def noop(param_hint_ignorable: Generic[T]) -> T: pass

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

    Parameters
    ----------
    hint : Hint
        Subscripted generic to be reduced.
    hint_parent_sane : Optional[HintSane]
        Either:

        * If the passed hint is a **root** (i.e., top-most parent hint of a tree
          of child hints), :data:`None`.
        * Else, the passed hint is a **child** of some parent hint. In this
          case, the **sanified parent type hint metadata** (i.e., immutable and
          thus hashable object encapsulating *all* metadata previously returned
          by :mod:`beartype._check.convert.convmain` sanifiers after sanitizing
          the possibly PEP-noncompliant parent hint of this child hint into a
          fully PEP-compliant parent hint).
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    All remaining passed keyword parameters are silently ignored.

    Returns
    -------
    HintOrSane
        Either:

        * If the unsubscripted hint (e.g., :class:`typing.Generic`) originating
          this subscripted hint (e.g., ``typing.Generic[S, T]``) is
          unparametrized by type variables, that unsubscripted hint as is.
        * Else, that unsubscripted hint is parametrized by one or more type
          variables. In this case, the **sanified type hint metadata** (i.e.,
          :class:`.HintSane` object) describing this reduction.
    '''

    # Avoid circular import dependencies.
    from beartype._check.convert._reduce._pep.redpep484612646 import (
        reduce_hint_pep484612646_subbed_typeargs_to_hints)

    # If this subscripted generic is the "typing.Generic" superclass directly
    # parametrized by one or more type variables (e.g., "typing.Generic[T]"),
    # this generic is ignorable. In this case, reduce this ignorable generic to
    # the ignorable singleton.
    #
    # Note that we intentionally avoid calling the
    # get_hint_pep_origin_type_isinstanceable_or_none() function here, which has
    # been intentionally designed to exclude PEP-compliant type hints
    # originating from "typing" type origins for stability reasons.
    if get_hint_pep_origin_or_none(hint) is Generic:
        # print(f'Testing generic hint {repr(hint)} deep ignorability... True')
        return HINT_SANE_IGNORABLE
    # Else, this subscripted generic is *NOT* the "typing.Generic" superclass
    # directly parametrized by one or more type variables and thus *NOT* an
    # ignorable non-protocol.
    #
    # Note that this condition being false is *NOT* sufficient to declare this
    # hint to be unignorable. Notably, the origin type originating both
    # ignorable and unignorable protocols is "Protocol" rather than "Generic".
    # Ergo, this generic could still be an ignorable protocol.

    # Useful PEP 544-compliant unsubscripted protocol possibly reduced from this
    # useless PEP 484- or 585-compliant subscripted IO generic if this hint is a
    # subscripted IO generic *OR* this hint as is otherwise.
    #
    # Note that we reduce this subscripted IO generic *BEFORE* stripping all
    # child hints subscripting this IO generic, as this reducers requires these
    # child hints to correctly reduce this IO generic.
    hint_reduced = _reduce_hint_pep484585_generic_io(hint, exception_prefix)

    # If this hint was reduced to an unsubscripted generic from this subscripted
    # IO generic, return this reduced hint.
    if hint_reduced is not hint:
        return hint_reduced
    # Else, this hint was *NOT* reduced to an unsubscripted generic from this
    # subscripted IO generic (i.e., "hint_reduced is hint").

    # Reduce this subscripted generic to:
    # * The semantically useful unsubscripted generic originating this
    #   semantically useless subscripted generic.
    # * The type variable lookup table mapping all type variables parametrizing
    #   this unsubscripted generic to all non-type variable hints subscripting
    #   this subscripted generic.
    # print(f'[reduce_hint_pep484585_generic_subbed] Reducing subscripted generic {repr(hint)}...')
    hint_reduced = reduce_hint_pep484612646_subbed_typeargs_to_hints(
        hint=hint,
        hint_parent_sane=hint_parent_sane,
        exception_prefix=exception_prefix,
    )
    # print(f'[reduce_hint_pep484585_generic_subbed] ...to unsubscripted generic {repr(hint_reduced)}.')

    # Return this reduced hint.
    return hint_reduced


def reduce_hint_pep484585_generic_unsubbed(
    hint: Hint, exception_prefix: str) -> HintOrSane:
    '''
    Reduce the passed :pep:`484`- or :pep:`585`-compliant **unsubscripted
    generic** (i.e., type originally subclassing at least one unsubscripted
    :pep:`484`- or :pep:`585`-compliant pseudo-superclass) to a more suitable
    type hint better supported by :mod:`beartype` if necessary.

    This reducer is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as reducers cannot be memoized.

    Parameters
    ----------
    hint : Hint
        Subscripted generic to be reduced.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages.

    Returns
    -------
    HintOrSane
        Either:

        * If this unsubscripted generic is ignorable, the
          :data:`.HINT_SANE_IGNORABLE` singleton.
        * Else, this unsubscripted generic possibly reduced to a more suitable
          hint.
    '''

    # If this unsubscripted generic is the "typing.Generic" superclass, this
    # generic is ignorable. In this case, reduce this ignorable generic to the
    # ignorable singleton.
    #
    # Note that we intentionally avoid calling the
    # get_hint_pep_origin_type_isinstanceable_or_none() function here, which has
    # been intentionally designed to exclude PEP-compliant type hints
    # originating from "typing" type origins for stability reasons.
    if hint is Generic:
        # print(f'Testing generic hint {repr(hint)} deep ignorability... True')
        return HINT_SANE_IGNORABLE
    # Else, this unsubscripted generic is *NOT* the "typing.Generic" superclass
    # and thus *NOT* an ignorable non-protocol.
    #
    # Note that this condition being false is *NOT* sufficient to declare this
    # hint to be unignorable. Notably, the origin type originating both
    # ignorable and unignorable protocols is "Protocol" rather than "Generic".
    # Ergo, this generic could still be an ignorable protocol.

    # Hint possibly reduced from this useless unsubscripted IO generic if this
    # hint is an unsubscripted IO generic *OR* this hint as is otherwise.
    hint_reduced = _reduce_hint_pep484585_generic_io(hint, exception_prefix)

    # Return this possibly reduced hint.
    return hint_reduced

# ....................{ PRIVATE ~ reducers                 }....................
def _reduce_hint_pep484585_generic_io(
    hint: Hint, exception_prefix: str) -> Hint:
    '''
    Reduce the passed :pep:`484`- or :pep:`585`-compliant **standard IO
    generic** (i.e., standard :obj:`typing.IO` generic (in either subscripted or
    unsubscripted forms) *or* the standard :obj:`BinaryIO` or :obj:`TextIO`
    unsubscripted generics) to a beartype-specific :pep:`544`-compliant protocol
    implementing this generic if this generic is a standard IO generic *or*
    silently ignore this generic otherwise.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

    Parameters
    ----------
    hint : Hint
        Standard IO generic to be reduced.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages.

    All remaining passed keyword parameters are silently ignored.

    Returns
    -------
    Hint
        This subscripted generic possibly reduced to a more suitable hint.
    '''

    # Avoid circular import dependencies.
    from beartype._check.convert._reduce._pep.redpep544 import (
        reduce_hint_pep484_generic_io_to_pep544_protocol)

    # If this hint is a PEP 484-compliant IO generic base class, reduce this
    # functionally useless hint to the corresponding functionally useful
    # beartype-specific PEP 544-compliant protocol implementing this hint.
    if is_hint_pep484_generic_io(hint):
        # print(f'Reducing IO generic {repr(hint)}...')
        hint = reduce_hint_pep484_generic_io_to_pep544_protocol(
            hint, exception_prefix)
        # print(f'...{repr(hint)}.')
    # Else, this hint is *NOT* a PEP 484-compliant IO generic base class.
    # Preserve this hint as is.

    # Return this possibly reduced hint.
    return hint
