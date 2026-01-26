#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`-, :pep:`612`-, or :pep:`646`-compliant **type parameter
reducers** (i.e., low-level callables converting arbitrary hints parametrized by
zero or more :pep:`484`-compliant type variables, :pep:`612`-compliant parameter
specifications, and/or :pep:`646`-compliant type variable tuples to lower-level
type hints more readily consumable by :mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: [PEP 612] *WOOPS.* Generics can be subscripted by PEP 612-compliant
#parameter specifications: e.g.,
#    # This example literally appears in PEP 696.
#    Ts = TypeVarTuple("Ts")
#    P = ParamSpec("P", default=[float, bool])
#    class Foo(Generic[Ts, P]): ...  # Valid
#
#Brutal. Welp. Let's implement that if somebody actually complains about that,
#please. Doing so will warrant renaming this reducer to "redpep484612646" and
#generalizing everything below. Pretty annoying, but... what can you do? *sigh*

#FIXME: [PEP 696] Handle "PEP 696 – Type Defaults for Type Parameters" under
#Python >= 3.13:
#    https://peps.python.org/pep-0696
#
#This PEP induces edge cases in _make_hint_pep484612646_typearg_to_hint().
#Notably, when the caller passes more type parameters than child hints to that
#factory, we currently silently ignore and thus preserve those "excess" type
#parameters. Under Python >= 3.13, however, we *MUST* instead now:
#* Manually iterate over those any excess *LEADING* type parameters in
#  left-to-right parametrization order. For each such parameter:
#  * If that type parameter defines a default, map that parameter to that
#    default.
#  * Else, halt this iteration immediately.
#
#Note that:
#* Some (or even all) of the above logic may actually already be implicitly
#  supported due to the reduce_hint_pep484612646_typearg() reducer, which now
#  supports PEP 696-compliant defaults.
#* This does apply to both PEP 484-compliant type variables *AND* PEP
#  646-compliant unpacked type variable tuples. Both can be defaulted.
#* This does *NOT* apply to *TRAILING* type parameters. PEP 696 mandates that
#  @beartype should raise an exception if *ANY* trailing type parameter
#  following an unpacked type variable tuple has a default. Just "Ugh!"

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep484612646Exception
from beartype.typing import (
    Optional,
    # TypeVar,
)
from beartype._check.convert._reduce._redrecurse import (
    is_hint_recursive,
    make_hint_sane_recursable,
)
from beartype._check.metadata.hint.hintsane import (
    HINT_SANE_IGNORABLE,
    HINT_SANE_RECURSIVE,
    HintOrSane,
    HintSane,
)
from beartype._check.pep.checkpep484typevar import (
    die_if_hint_pep484_typevar_bound_unbearable)
from beartype._data.error.dataerrmagic import EXCEPTION_PLACEHOLDER
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.hint.sign.datahintsigns import (
    HintSignTypeVar,
    HintSignPep646TypeVarTupleUnpacked,
)
from beartype._data.kind.datakindiota import SENTINEL
from beartype._data.typing.datatyping import (
    Pep484612646TypeArgUnpacked,
    TuplePep484612646TypeArgsUnpacked,
)
from beartype._data.typing.datatypingport import (
    Hint,
    Pep484612646TypeArgUnpackedToHint,
    TupleHints,
)
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.error.utilerrraise import reraise_exception_placeholder
from beartype._util.hint.pep.proposal.pep484.pep484typevar import (
    get_hint_pep484_typevar_bounded_constraints_or_none,
    # is_hint_pep484_typevar,
)
from beartype._util.hint.pep.proposal.pep484612646 import (
    die_unless_hint_pep484612646_typearg_unpacked,
    is_hint_pep484612646_typearg_unpacked,
    pack_hint_pep484612646_typearg_unpacked,
)
from beartype._util.hint.pep.proposal.pep646692 import (
    make_hint_pep646_tuple_unpacked_prefix)
from beartype._util.hint.pep.proposal.pep696 import (
    get_hint_pep484612646_typearg_packed_default_or_sentinel)
from beartype._util.hint.pep.utilpepget import (
    get_hint_pep_args,
    get_hint_pep_origin,
    get_hint_pep_typeargs_unpacked,
)
from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none
from beartype._util.kind.maplike.utilmapfrozen import FrozenDict

# ....................{ REDUCERS                           }....................
def reduce_hint_pep484612646_typearg(
    hint: Hint,
    hint_parent_sane: Optional[HintSane],
    exception_prefix: str,
    **kwargs
) -> HintSane:
    '''
    Reduce the passed :pep:`484`-, :pep:`612`-, or :pep:`646`-compliant **type
    parameter** (i.e., :pep:`484`-compliant type variable, :pep:`612`-compliant
    parameter specification, or :pep:`646`-compliant type variable tuple) to a
    lower-level type hint currently supported by :mod:`beartype`.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

    Parameters
    ----------
    hint : Hint
        Type parameter to be reduced.
    hint_parent_sane : Optional[HintSane]
        Either:

        * If the passed hint is a **root** (i.e., top-most parent hint of a tree
          of child hints), :data:`None`.
        * Else, the passed hint is a **child** of some parent hint. In this
          case, the **sanified parent type hint metadata** (i.e., immutable and
          thus hashable object encapsulating *all* metadata previously returned
          by :mod:`beartype._check.convert.convmain` sanifiers after
          sanitizing the possibly PEP-noncompliant parent hint of this child
          hint into a fully PEP-compliant parent hint).
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    All remaining keyword-only parameters are silently ignored.

    Returns
    -------
    HintSane
        Either:

        * If this type parameter is **recursive** (i.e., previously transitively
          mapped to itself by a prior call to this reducer), this type parameter
          *must* be ignored to avoid infinite recursion. In this case, the
          :data:`.HINT_SANE_RECURSIVE` singleton.
        * Else if the type parameter lookup table encapsulated by the passed
          sanified parent type hint metadata maps this type parameter to another
          type hint, the latter.
        * Else if this type parameter is both unbounded and unconstrained, this
          type parameter is ignorable. In this case, the
          :data:`.HINT_SANE_IGNORABLE` singleton.
        * Else, this type parameter's lover-level bounds or constraints.
    '''
    # print(f'Reducing PEP 484 type parameter {hint} with parent hint {hint_parent_sane}...')

    # ....................{ PHASE                          }....................
    # This reducer is divided into a series of sequential phases:
    # * Decide whether this type parameter is recursive.
    # * Map this type parameter to its associated target hint by the lookup
    #    table previously associated with this type parameter (if any).
    # * Reduce this type parameter to its default (if any).
    # * Reduce this type parameter to its bounded constraints (if any).
    # * Decide the recursion guard for this type parameter.
    #
    # All phases are non-trivial. The output of each phase is sanified hint
    # metadata (i.e., a "HintSane" object) containing the result of the decision
    # problem decided by that phase.

    # ....................{ PHASE ~ 0 : recurse            }....................
    # If this type parameter is recursive (i.e., previously transitively mapped
    # to itself by a prior call to this reducer), ignore this type parameter to
    # avoid infinite recursion.
    if is_hint_recursive(
        hint=hint,
        hint_parent_sane=hint_parent_sane,
        hint_recursable_depth_max=_TYPEARG_RECURSABLE_DEPTH_MAX,
    ):
        # print(f'Ignoring recursive type parameter {hint} with parent {hint_parent_sane}!')
        return HINT_SANE_RECURSIVE
    # Else, this type parameter is *NOT* recursive.

    # ....................{ PHASE ~ 1 : lookup             }....................
    # Reduced hint to be returned, defaulting to this type parameter.
    hint_reduced = hint

    # If...
    if (
        # This type parameter is not a root hint and thus has a parent hint
        # *AND*...
        hint_parent_sane is not None and
        # A parent hint of this type parameter maps one or more type
        # parameters...
        hint_parent_sane.typearg_to_hint
    ):
        # Type parameter lookup table of this parent hint, localized for
        # usability and negligible efficiency.
        typearg_to_hint = hint_parent_sane.typearg_to_hint

        # If a parent hint of this type parameter maps exactly one type
        # parameter, prefer a dramatically faster and simpler approach.
        if len(typearg_to_hint) == 1:
            # Hint mapped to by this type parameter if one or more parent hints
            # previously mapped this type parameter to a hint *OR* this hint as
            # is otherwise (i.e., if this type parameter is unmapped).
            #
            # Note that this one-liner looks ridiculous, but actually works.
            # More importantly, this is the fastest way to accomplish this.
            hint_reduced = typearg_to_hint.get(hint, hint)  # type: ignore[call-overload]
        # Else, a parent hint of this type parameter mapped two or more type
        # parameters. In this case, fallback to a slower and more complicated
        # approach that avoids worst-case edge cases. This includes recursion in
        # type parameter mappings, which arises in non-trivial class hierarchies
        # involving two or more generics subscripted by two or more type
        # parameters that circularly cycle between one another: e.g.,
        #     from typing import Generic
        #     class GenericRoot[T](Generic[T]): pass
        #
        #     # This directly maps "{T: S}".
        #     class GenericLeaf[S](GenericRoot[S]): pass
        #
        #     # This directly maps "{S: T}", which then combines with the above
        #     # mapping to indirectly map "{S: T, T: S}". Clearly, this indirect
        #     # mapping provokes infinite recursion unless explicitly handled.
        #     GenericLeaf[T]
        else:
            # Type hints previously reduced from this type parameter,
            # initialized to this type parameter.
            hint_reduced_prev = hint

            # Shallow copy of this type parameter lookup table, coerced from an
            # immutable frozen dictionary into a mutable standard dictionary.
            # This enables type parameters reduced by the iteration below to be
            # popped off this copy as a simple (but effective) recursion guard.
            typearg_to_hint_stack = typearg_to_hint.copy()

            #FIXME: [SPEED] *INEFFICIENT.* This has to be done either way, but
            #rather than reperform this O(n) algorithm on every single instance
            #of this type parameter, this algorithm should simply be performed
            #exactly *ONCE* in the
            #reduce_hint_pep484612646_subbed_typeargs_to_hints() reducer. Please
            #refactor this iteration over there *AFTER* the dust settles here.
            #FIXME: Actually, it's unclear how exactly this could be refactored
            #into the reduce_hint_pep484612646_subbed_typeargs_to_hints()
            #reducer. This reduction here only searches for a single typevar in
            #O(n) time. Refactoring this over to
            #reduce_hint_pep484612646_subbed_typeargs_to_hints() would require
            #generalizing this into an O(n**2) algorithm there, probably. Yow!

            # While...
            while (
                # This stack still contains one or more type parameters that
                # have yet to be reduced by this iteration *AND*...
                typearg_to_hint_stack and
                # This hint is still a type parameter...
                is_hint_pep484612646_typearg_unpacked(hint_reduced)
            ):
                # Hint mapped to by this type parameter if one or more parent
                # hints previously mapped this type parameter to a hint *OR* this
                # hint as is (i.e., if this type parameter is unmapped).
                #
                # Note that this one-liner destructively pops this type parameter
                # off this temporary stack to prevent this type parameter from
                # being reduced more than once by an otherwise recursive
                # mapping. Since this stack is local to this reducer, this
                # behaviour is only locally destructive and thus safe.
                hint_reduced = typearg_to_hint_stack.pop(
                    hint_reduced_prev, hint_reduced_prev)  # pyright: ignore

                # If this type parameter maps to itself, this mapping is both
                # ignorable *AND* terminates this reduction.
                if hint_reduced is hint_reduced_prev:
                    break
                # Else, this type parameter does *NOT* map to itself.

                # Map this type parameter to this hint.
                hint_reduced_prev = hint_reduced
        # print(f'...to hint {hint} via type parameter lookup table!')
    # Else, this type parameter is unmapped.

    # ....................{ PHASE ~ 2 : default            }....................
    # If this hint is still an unpacked type parameter...
    if is_hint_pep484612646_typearg_unpacked(hint_reduced):
        # Packed type parameter underlying this unpacked type parameter.
        hint_packed = pack_hint_pep484612646_typearg_unpacked(
            hint=hint_reduced, exception_prefix=exception_prefix)

        # PEP 696-compliant default parametrizing this type parameter if any
        # *OR* the sentinel placeholder otherwise (i.e., if this type parameter
        # has *NO* default).
        hint_default = get_hint_pep484612646_typearg_packed_default_or_sentinel(
            hint=hint_packed, exception_prefix=exception_prefix)

        # If this type parameter has a default, reduce this type parameter to
        # this default.
        if hint_default is not SENTINEL:
            hint_reduced = hint_default
        # Else, this type parameter has *NO* default. In this case, preserve
        # this type parameter as is (for the moment).
    # Else, this hint is no longer a type parameter.

    # ....................{ PHASE ~ 3 : bounds             }....................
    # Sign uniquely identifying this type parameter.
    hint_reduced_sign = get_hint_pep_sign_or_none(hint_reduced)  # pyright: ignore

    # If this hint is still a PEP 484-compliant type variable (e.g., due to
    # either not being mapped by this lookup table *OR* being mapped by this
    # lookup table to yet another type variable)...
    if hint_reduced_sign is HintSignTypeVar:
        # PEP-compliant hint synthesized from all bounded constraints
        # parametrizing this type parameter if any *OR* "None" otherwise (i.e.,
        # if this type parameter is both unbounded *AND* unconstrained).
        #
        # Note this call is passed positional parameters due to memoization.
        hint_reduced = get_hint_pep484_typevar_bounded_constraints_or_none(
            hint_reduced, exception_prefix)  # pyright: ignore

        # If this type parameter is both unbounded *AND* unconstrained, this
        # type parameter is currently *NOT* type-checkable and is thus
        # ignorable. Reduce this type parameter to the ignorable singleton.
        if hint_reduced is None:
            return HINT_SANE_IGNORABLE
        # Else, this type parameter is either bounded *OR* constrained. In
        # either case, preserve this newly synthesized hint.
        # print(f'Reducing PEP 484 type parameter {repr(hint)} to {repr(hint_bound)}...')
        # print(f'Reducing non-beartype PEP 593 type hint {repr(hint)}...')
    # Else, this hint is *NOT* a PEP 484-compliant type variable. If this hint
    # was a type variable, one or more transitive parent hints previously mapped
    # this type parameter to a non-type variable.
    #
    # In any case, only type variables currently accept bounds and constraints;
    # neither PEP 612-compliant parameter specifications *NOR* PEP 646-compliant
    # type variable tuples accept bounds or constraints. Both are unconstrained
    # and thus are currently *NOT* type-checkable and thus are ignorable.
    #
    # If this hint is still a PEP 646-compliant unpacked type variable tuple
    # (e.g., due to either not being mapped by this lookup table *OR* being
    # mapped by this lookup table to yet another unpacked type variable tuple),
    # reduce this unconstrained type parameter to the ignorable singleton.
    elif hint_reduced_sign is HintSignPep646TypeVarTupleUnpacked:
        #FIXME: *HMMM*. This is *ABSOLUTELY* wrong. Type variable tuples aren't
        #like type variables. They actually signify something: notably, that
        #zero or more child hints should be matched. To do so, type variables
        #tuples should be reduced to the PEP 646-compliant unpacked fixed tuple
        #hint "*tuple[object, ...]". Ergo, this should instead resemble here:
        #    return make_hint_pep646_tuple_unpacked_prefix((object, ...))
        #
        #Of course, repeatedly recreating the same hint for *EVERY* single
        #type variable tuple is awful. Instead:
        #* Append a new public global variable to "pep646692" resembling:
        #      HINT_PEP646_TUPLE_UNPACKED_VARIADIC_ANY = make_hint_pep646_tuple_unpacked_prefix(
        #          (object, ...))
        #* Import and return that instead here: e.g.,
        #      return HINT_PEP646_TUPLE_UNPACKED_VARIADIC_ANY
        return HINT_SANE_IGNORABLE
    # Else, this hint is *NOT* a PEP 646-compliant unpacked type variable tuple.
    # In this case, this hint is *NOT* an unconstrained type parameter and thus
    # *NOT* trivially ignorable. Preserve this reduced hint as is.

    # ....................{ PHASE ~ 4 : guard              }....................
    # Decide the recursion guard protecting this possibly recursive type
    # parameter against infinite recursion.
    #
    # Note that this guard intentionally applies to the original unreduced type
    # parameter rather than the newly reduced hint decided by the prior phase.
    # Thus, we pass "hint_recursable=hint" rather than
    # "hint_recursable=hint_reduced".
    hint_sane = make_hint_sane_recursable(
        # The recursable form of this type parameter is its original unreduced
        # form tested by the is_hint_recursive() recursion guard above.
        hint_recursable=hint,
        # The non-recursable form of this type parameter is its new reduced form.
        hint_nonrecursable=hint_reduced,  # pyright: ignore
        hint_parent_sane=hint_parent_sane,
    )

    # ....................{ RETURN                         }....................
    # Return this metadata.
    return hint_sane


#FIXME: Document how PEP 646-compliant unpacked type variable tuples intersect
#with the "Caveats" in the docstring below, please. *megasigh*
def reduce_hint_pep484612646_subbed_typeargs_to_hints(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    hint_parent_sane: Optional[HintSane] = None,
    exception_prefix: str = '',
) -> HintOrSane:
    '''
    Reduce the passed **subscripted hint** (i.e., derivative hint produced by
    subscripting an unsubscripted hint originally parametrized by one or more
    **type parameters** (i.e., :pep:`484`-compliant type variables or
    :pep:`646`-compliant type variable tuples) with one or more child hints) to
    that unsubscripted hint and corresponding **type parameter lookup table**
    (i.e., immutable dictionary mapping from those same type parameters to those
    same child hints).

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

    Caveats
    -------
    This reducer does *not* validate these type parameters to actually be type
    parameters. Instead, this function defers that validation to the caller.
    Why? Efficiency, mostly. Avoiding the need to explicitly validate these type
    parameters reduces the underlying mapping operation to a fast one-liner.

    Let:

    * ``hints_typearg`` be the tuple of the zero or more type parameters
      parametrizing the unsubscripted hint underlying the passed subscripted
      hint.
    * ``hints_child`` be the tuple of the zero or more child hints subscripting
      the passed subscripted hint.

    Then this reducer validates the sizes of these tuple to be constrained as:

    .. code-block:: python

       len(hints_typearg) >= len(hints_child) > 0

    Equally, the passed hint *must* be subscripted by at least one child hint.
    For each such child hint, the unsubscripted hint originating this
    subscripted hint *must* be parametrized by a corresponding type parameter.
    The converse is *not* the case, as:

    * For the first type parameter, there also *must* exist a corresponding
      child hint to map to that type parameter.
    * For *all* type parameters following the first, there need *not* exist a
      corresponding child hint to map to that type parameter. Type parameters
      with *no* corresponding child hints are simply silently ignored (i.e.,
      preserved as type parameters rather than mapped to other hints).

    Equivalently:

    * Both of these tuples *must* be **non-empty** (i.e., contain one or more
      items).
    * This tuple of type parameters *must* contain at least as many items as
      this tuple of child hints. Therefore:

      * This tuple of type parameters *may* contain exactly as many items as
        this tuple of child hints.
      * This tuple of type parameters *may* contain strictly more items than
        this tuple of child hints.
      * This tuple of type parameters must *not* contain fewer items than this
        tuple of child hints.

    Parameters
    ----------
    hint : Hint
        Subscripted hint to be inspected.
    hint_parent_sane : Optional[HintSane]
        Either:

        * If the passed hint is a **root** (i.e., top-most parent hint of a tree
          of child hints), :data:`None`.
        * Else, the passed hint is a **child** of some parent hint. In this
          case, the **sanified parent type hint metadata** (i.e., immutable and
          thus hashable object encapsulating *all* metadata previously returned
          by :mod:`beartype._check.convert.convmain` sanifiers after
          sanitizing the possibly PEP-noncompliant parent hint of this child
          hint into a fully PEP-compliant parent hint).

        Defaults to :data:`None`.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    HintOrSane
        Either:

        * If the unsubscripted hint (e.g., :class:`typing.Generic`) originating
          this subscripted hint (e.g., ``typing.Generic[S, T]``) is
          unparametrized by type parameters, that unsubscripted hint as is.
        * Else, that unsubscripted hint is parametrized by one or more type
          parameters. In this case, the **sanified type hint metadata** (i.e.,
          :class:`.HintSane` object) describing this reduction.

    Raises
    ------
    BeartypeDecorHintPep484612646Exception
        If this type hint is unsubscripted.
    BeartypeDecorHintPep484TypeVarViolation
        If one of these type hints violates the bounds or constraints of one of
        these type parameters.
    '''

    # ....................{ LOCALS                         }....................
    # Unsubscripted type alias originating this subscripted hint.
    hint_unsubbed = get_hint_pep_origin(
        hint=hint,
        exception_cls=BeartypeDecorHintPep484612646Exception,
        exception_prefix=exception_prefix,
    )

    #FIXME: [SPEED] Inefficient. This getter internally creates and then
    #discards a full-blown list object just to create this unpacked tuple.
    #Instead, we should:
    #* Call get_hint_pep_typeargs_packed() instead here.
    #* In the _make_hint_pep484612646_typearg_to_hint() factory:
    #  * Detect packed rather than unpacked type variable tuples everywhere.
    #  * Manually pack the detected type variable tuple when mapping this type
    #    variable tuple to another hint: e.g.,
    #        hint_pep646_typevartuple_unpacked = (
    #            make_hint_pep646_typevartuple_unpacked_subbed(
    #                 hint_pep646_typevartuple))
    #        typearg_to_hint[hint_pep646_typevartuple_unpacked] = (
    #            hints_child_excess_tuple_unpacked)

    # Tuple of all unpacked type parameters parametrizing this unsubscripted
    # hint.
    #
    # Note that:
    # * PEP 484-compliant subscripted parametrized generics incorrectly report
    #   being unparametrized, due to outstanding issues in the "typing" module.
    #   Since these issues *ONLY* apply to subscripted rather than unsubscripted
    #   parametrized generics, we strongly prefer the latter for the purposes of
    #   introspecting type parameters:
    #       >>> from beartype.typing import Generic, TypeVar
    #       >>> T = TypeVar('T')
    #       >>> class Ugh(Generic[T]): pass
    #       >>> get_hint_pep_typeargs_packed(Ugh)
    #       (~T,)  # <-- this is good
    #       >>> get_hint_pep_typeargs_packed(Ugh[int])
    #       ()  # <----- THIS IS BAD. wtf, "typing"?
    # * PEP 695-compliant "type" alias syntax superficially appears to
    #   erroneously permit type aliases to be parametrized by non-type
    #   parameters. In truth, "type" syntax simply permits type aliases to be
    #   parametrized by type parameters that ambiguously share the same names as
    #   builtin types -- which then silently shadow those types for the duration
    #   of those aliases:
    #     >>> type muh_alias[int] = float | complex  # <-- *gulp* >>>
    #     muh_alias.__parameters__ (int,)  # <-- doesn't look good so far >>>
    #     muh_alias.__parameters__[0] is int False  # <-- something good finally happened
    hints_typearg = get_hint_pep_typeargs_unpacked(hint_unsubbed)
    # print(f'hints_typearg: {hints_typearg}')

    # Tuple of all child hints subscripting this subscripted hint.
    hints_child = get_hint_pep_args(hint)
    # print(f'hints_child: {hints_child}')

    # ....................{ REDUCE                         }....................
    # Decide the type parameter lookup table for this hint. Specifically, reduce
    # this subscripted hint to:
    # * The semantically useful unsubscripted hint originating this semantically
    #   useless subscripted hint.
    # * The type parameter lookup table mapping all type parameters parametrizing
    #   this unsubscripted hint to all non-type parameter hints subscripting
    #   this subscripted hint.

    # ....................{ REDUCE ~ noop                  }....................
    # If either...
    if (
        # This unsubscripted hint is parametrized by no type parameters *OR*...
        #
        # In this case, *NO* type parameter lookup table can be produced by this
        # reduction. Note this is an uncommon edge case. Examples include:
        # * Parametrizations of the PEP 484-compliant "typing.Generic"
        #   superclass (e.g., "typing.Generic[S, T]"). In this case, the
        #   original unsubscripted "typing.Generic" superclass remains
        #   unparametrized despite that superclass later being parametrized.
        not hints_typearg or
        # This unsubscripted hint is parametrized by the exact same type
        # parameters as this subscripted hint is subscripted by, in which case
        # the resulting type parameter lookup table would uselessly be the
        # identity mapping from each of these type parameters to itself. While
        # an identity type parameter lookup table could trivially be produced,
        # doing so would convey *NO* meaningful semantics and thus be pointless.
        hints_child == hints_typearg
    # Then reduce this subscripted hint to simply this unsubscripted hint, as
    # type parameter lookup tables are then irrelevant.
    ):
        return hint_unsubbed
    # Else, this unsubscripted hint is parametrized by one or more type
    # parameters. In this case, produce a type parameter lookup table mapping
    # these type parameters to child hints subscripting this subscripted hint.

    # ....................{ REDUCE ~ map                   }....................
    # Attempt to...
    try:
        # Type parameter lookup table mapping from each of these type parameters
        # to each of these corresponding child hints.
        #
        # Note that we pass parameters positionally due to memoization.
        typearg_to_hint = _make_hint_pep484612646_typearg_to_hint(
            hint, hints_typearg, hints_child)
    # print(f'Mapped hint {hint} to type parameter lookup table {typearg_to_hint}!')
    # If doing so raises *ANY* exception, reraise this exception with each
    # placeholder substring (i.e., "EXCEPTION_PLACEHOLDER" instance) replaced by
    # an explanatory prefix.
    except Exception as exception:
        reraise_exception_placeholder(
            exception=exception, target_str=exception_prefix)

    # ....................{ REDUCE ~ composite             }....................
    # Sanified metadata to be returned.
    hint_sane: HintSane = None  # type: ignore[assignment]

    # If this hint has *NO* parent, this is a root hint. In this case...
    if hint_parent_sane is None:
        # Metadata encapsulating this hint and type parameter lookup table.
        hint_sane = HintSane(
            hint=hint_unsubbed, typearg_to_hint=typearg_to_hint)
    # Else, this hint has a parent. In this case...
    else:
        # If the parent hint is also associated with a type parameter lookup
        # table...
        if hint_parent_sane.typearg_to_hint:
            # Full type parameter lookup table merging the table associated this
            # parent hint with the table just decided above for this child hint,
            # efficiently defined as...
            typearg_to_hint = (
                # The type parameter lookup table describing all transitive
                # parent hints of this hint with...
                hint_parent_sane.typearg_to_hint |  # type: ignore[operator]
                # The type parameter lookup table describing this hint.
                #
                # Note that this table is intentionally the second rather than
                # first operand of this "|" operation, efficiently ensuring that
                # type parameters mapped by this hint take precedence over type
                # parameters mapped by transitive parent hints of this hint.
                typearg_to_hint
            )
        # Else, the parent hint is associated with *NO* such table.

        # Metadata encapsulating this hint and type parameter lookup table,
        # while "cascading" any other metadata associated with this parent hint
        # (e.g., recursable hint IDs) down onto this child hint as well.
        hint_sane = hint_parent_sane.permute_sane(
            hint=hint_unsubbed, typearg_to_hint=typearg_to_hint)

    # ....................{ RETURN                         }....................
    # print(f'Reduced subscripted hint {repr(hint)} to unsubscripted hint metadata {repr(hint_sane)}.')

    # Return this metadata.
    return hint_sane

# ....................{ PRIVATE ~ constants                }....................
_TYPEARG_RECURSABLE_DEPTH_MAX = 0
'''
Value of the optional ``hint_recursable_depth_max`` parameter passed to the
:func:`.is_hint_recursive` tester by the :func:`.reduce_hint_pep484_typevar`
reducer.

This depth ensures that :pep:`484`- or :pep:`646`-compliant type parameters are
considered to be recursive *only* after having been recursed into at most this
many times before (i.e., *only* after having been visited exactly once as a
child hint of an arbitrary parent hint). By definition, type parameters are
guaranteed to *never* be parent hints. Ergo, recursing into type parameters
exactly once suffices to expand exactly one nesting level of non-trivial
recursive data structures. This mirrors the restrained recursion allowed by
other reducers.

Consider :pep:`695`-compliant type aliases, for example. Unlike type parameters,
type aliases are guaranteed to *always* be parent hints. The value of the
optional ``hint_recursable_depth_max`` parameter passed to the
:func:`.is_hint_recursive` tester by :pep:`695`-specific reducers is thus one
greater than the value of this global. Nonetheless, the real-world effect is
exactly the same: exactly one nesting level of type aliases is expanded.

Consider the following :pep:`484`-compliant generic recursively subscripted by
itself via a :pep:`484`-compliant type variable ``T``:

.. code-block:: python

   class GenericList[T](): ...
   RecursiveGenericList = GenericList[GenericList]

Instances of this generic satisfying the type hint ``RecursiveGenericList``
contain an arbitrary number of other instances of this generic, exhibiting this
internal structure:

.. code-block:: python

   recursive_generic_list = GenericList()
   recursive_generic_list.append(recursive_generic_list)

Halting recursion at the first expansion of the type parameter ``T`` then
reduces the type hint ``RecursiveGenericList`` to
``GenericList[GenericList[T]]``, , which reduces to
``GenericList[GenericList[HINT_SANE_RECURSIVE]]``, , which reduces to
``GenericList[GenericList]`` -- conveying exactly one layer of the internal
semantics of this recursive data structure.
'''

# ....................{ PRIVATE ~ raisers                  }....................
def _die_unless_hint_pep484_typevar_bound_bearable(
    hint_child: Hint,
    hint_typearg: Pep484612646TypeArgUnpacked,
    hint_typearg_sign: Optional[HintSign],
) -> None:
    '''
    Raise an exception if either:

    * The passed type parameter is a :pep:`484`-compliant type variable *and*
      the passed child hint violates this type variable's bounds and/or
      constraints.
    * The passed type parameter is *not* a :pep:`484`-compliant type variable.

    Parameters
    ----------
    hint_child : Hint
        Child hint to be inspected.
    hint_typearg : Pep484612646TypeArgUnpacked
        Type parameter to be inspected.
    hint_typearg_sign : Optional[HintSign]
        Sign uniquely identifying this type parameter.

    Raises
    ------
    BeartypeDecorHintPep484612646Exception
        If this type parameter is *not* a :pep:`484`-compliant type variable.
    BeartypeDecorHintPep484TypeVarViolation
        If this type parameter is a :pep:`484`-compliant type variable *and*
        this child hint violates this type variable's bounds and/or constraints.
    '''

    # If this type parameter is a PEP 484-compliant type variable...
    if hint_typearg_sign is HintSignTypeVar:
        # If this child hint violates this type variable's bounds and/or
        # constraints, raise an exception.
        die_if_hint_pep484_typevar_bound_unbearable(
            hint=hint_child,
            typevar=hint_typearg,  # type: ignore[arg-type]
            exception_prefix=EXCEPTION_PLACEHOLDER,
        )
        # Else, this child hint satisfies this type variable's bounds and/or
        # constraints.
    # Else, this type parameter is *NOT* a PEP 484-compliant type variable.
    # Ergo, this type parameter is *NOT* an unpacked type parameter! *ROAR*.
    #
    # Note that this should *NEVER* occur. Python itself syntactically
    # guarantees *ALL* child hints parametrizing a PEP-compliant subscripted
    # hint to be unpacked type parameters. Nonetheless, the caller is under
    # no such constraints. To guard against dev bitrot, we validate this.
    else:
        die_unless_hint_pep484612646_typearg_unpacked(
            hint=hint_typearg, exception_prefix=EXCEPTION_PLACEHOLDER)  # pyright: ignore

# ....................{ PRIVATE ~ factories                }....................
#FIXME: Unit test that this reducer reduces PEP 646-compliant unpacked type
#variable tuples, please. *sigh*
@callable_cached
def _make_hint_pep484612646_typearg_to_hint(
    hint: Hint,
    hints_typearg: TuplePep484612646TypeArgsUnpacked,
    hints_child: TupleHints,
) -> Pep484612646TypeArgUnpackedToHint:
    '''
    Type parameter lookup table mapping from the passed :pep:`484`- or
    :pep:`646`-compliant **type parameters** (i.e., :pep:`484`-compliant type
    variables or :pep:`646`-compliant type variable tuples) to the associated
    passed type hints as key-value pairs of this table.

    This getter is memoized for efficiency. Notably, this getter creates and
    returns a dictionary mapping each type parameter in the passed tuple of type
    parameters to the associated type hint in the passed tuple of type hints
    with the same 0-based tuple index as that type parameter.

    Parameters
    ----------
    hint: Hint
        Parent hint presumably both subscripted by these child hints. This
        parent hint is currently only used to generate human-readable exception
        messages in the event of fatal errors.
    hints_typearg : TuplePep484612646TypeArgsUnpacked
        Tuple of one or more child type parameters originally parametrizing the
        origin underlying this parent hint.
    hints_child : TupleHints
        Tuple of zero or more child type hints subscripting this parent hint,
        which those type parameters map to.

    Returns
    -------
    Pep484612646TypeArgUnpackedToHint
        Type parameter lookup table mapping these type parameters to these child
        hints.

    Raises
    ------
    BeartypeDecorHintPep484612646TypeArgException
        If either:

        * This tuple of type parameters is empty.
        * This tuple of type hints is empty.
        * This tuple of type hints contains more items than this tuple of type
          parameters.
    BeartypeDecorHintPep484TypeVarViolation
        If one of these type hints violates the bounds or constraints of one of
        these type parameters.
    '''
    assert isinstance(hints_typearg, tuple), (
        f'{repr(hints_typearg)} not tuple.')
    assert isinstance(hints_child, tuple), (
        f'{repr(hints_child)} not tuple.')
    # print(f'hints_typearg: {hints_typearg}')
    # print(f'hints_child: {hints_child}')

    # ....................{ PREAMBLE                       }....................
    # Number of passed type parameters and child hints respectively.
    hints_typearg_len = len(hints_typearg)
    hints_child_len = len(hints_child)

    # If *NO* type parameters were passed, raise an exception.
    if not hints_typearg_len:
        raise BeartypeDecorHintPep484612646Exception(
            f'{EXCEPTION_PLACEHOLDER}type hint {repr(hint)} '
            f'parametrized by no type parameters (i.e., '
            f'PEP 484 type variables, '
            f'PEP 612 unpacked parameter specifications, or '
            f'PEP 646 unpacked type variable tuples).'
        )
    # Else, one or more type parameters were passed.

    # ....................{ LOCALS                         }....................
    # Type parameter lookup table to be returned.
    typearg_to_hint: Pep484612646TypeArgUnpackedToHint = {}

    # 0-based index of the current type parameter *AND* corresponding child hint
    # of the passed tuples visited by the "while" loop below.
    hints_index_curr = 0

    # 0-based index of the last type parameter *AND* corresponding child hint of
    # the passed tuples to be visited by the "while" loop below, intentionally
    # defined as the maximum number of type parameters or child hints. Why?
    # Because two relevant edge cases then arise:
    # * If more type parameters than child hints were passed, this calculation
    #   induces the "while" loop below to silently ignore those trailing type
    #   parameters that lack corresponding trailing child hints -- exactly as
    #   required and documented by the above docstring. This case is valid! \o/
    # * If more child hints than type parameters were passed, two sub-edge cases
    #   now arise:
    #   * If one of these type parameters is a PEP 646-compliant unpacked type
    #     variable tuple, this parent edge case is valid. Although more child
    #     hints than type parameters were passed, a single unpacked type
    #     variable tuple consumes zero or more excess child hints (i.e., child
    #     hints *NOT* already consumed by one or more trailing PEP 484-compliant
    #     type variables).
    #   * If none of these type parameters is a PEP 646-compliant unpacked type
    #     variable tuple, this parent edge case is invalid. Validation below
    #     will subsequently detect this invalid case and raise an exception.
    hints_index_last = max(hints_typearg_len, hints_child_len) - 1

    # Either:
    # * If the passed tuple of type parameters contains one or more PEP
    #   646-compliant unpacked type variable tuples, the 0-based index of
    #   the first such type parameter.
    # * Else, "None".
    #
    # This local variable is used to detect and track such type parameters.
    hints_pep646_typevartuple_index: Optional[int] = None

    # ....................{ PHASE 1 ~ pep 484 : typevar    }....................
    # In this first phase, we map all *LEADING* PEP 484-compliant type variables
    # parametrizing the beginning of this parent subscripted hint until
    # discovering the first PEP 646-compliant type variable tuple (if any)
    # parametrizing the middle of this parent subscripted hint. Notably:
    # * Type variables only map to and thus "consume" a single child hint.
    #   Mapping leading type variables is trivial.
    # * Type variable tuples map to and thus "consume" zero or more child hints.
    #   Mapping both type variable tuples *AND* the trailing type variables that
    #   follow them is comparatively non-trivial. Special care is warranted.

    # While the 0-based index of the current leading type variable does *NOT*
    # exceed that of the last child hint to be visited by this loop, one or
    # more leading type variables remain unvisited. In this case...
    while hints_index_curr <= hints_index_last:
        # print(f'Visiting leading type parameter index {hints_index_curr} <= {hints_index_last}...')

        # If the 0-based index of this leading type variable exceeds that of the
        # last type variable, more child hints than type parameters were passed.
        # Why? Because, if fewer or the same number of child hints as type
        # parameters were passed, then this index would *NEVER* exceed that of
        # the last type variable. But this index exceeded that of the last type
        # variable! The converse must thus be true. Raise an exception.
        #
        # Note that it is conditionally valid for the caller to pass more child
        # hints than type parameters if one of the previously visited type
        # parameters is a PEP 646-compliant unpacked type variable tuple, which
        # would have then consumed all excess child hints. However, one of these
        # type parameters is *NOT* an unpacked type variable tuple. Why? Because
        # if one of these type parameters was such a tuple, then this "while"
        # loop would have already been prematurely terminated by the "break"
        # statement below. Clearly, though, this "while" loop is still
        # iterating! Ergo, the converse must yet again be true.
        if hints_index_curr >= hints_typearg_len:
            raise BeartypeDecorHintPep484612646Exception(
                f'{EXCEPTION_PLACEHOLDER}type hint {repr(hint)} '
                f'number of subscripted child hints {hints_child_len} exceeds '
                f'number of parametrized type parameters {hints_typearg_len} '
                f'(i.e., {hints_child_len} > {hints_typearg_len}).'
            )
        # Else, the 0-based index of this type variable does *NOT* exceed that
        # of the last child hint.

        # Current leading type parameter.
        hint_typearg = hints_typearg[hints_index_curr]

        # Sign uniquely identifying this type parameter.
        hint_typearg_sign = get_hint_pep_sign_or_none(hint_typearg)  # pyright: ignore
        # print(f'Visiting leading type parameter {hint_typearg} of {hint_typearg_sign}...')

        # If this type parameter is a PEP 646-compliant unpacked type variable
        # tuple...
        if hint_typearg_sign is HintSignPep646TypeVarTupleUnpacked:
            # 0-based index of this unpacked type variable tuple.
            hints_pep646_typevartuple_index = hints_index_curr

            # Immediately halt all further visitation of type parameters and
            # child hints by this iteration. Unpacked type variable tuples
            # greedily consume all remaining child hints and thus warrant
            # special handling below.
            break
        # Else, this type parameter is *NOT* an unpacked type variable tuple.
        #
        # If the 0-based index of this trailing child hint exceeds that of the
        # last child hint, more type parameters than child hints were passed by
        # similar logic as above. In this case...
        #
        # Note that this condition is intentionally tested here *AFTER* ensuring
        # that this parent hint is parametrized by *NO* unpacked type variable
        # tuple. Why? Because it is conditionally valid for the caller to pass
        # exactly *ONE* more type parameter than child hints if one of those
        # type parameters is an unpacked type variable tuple, which would have
        # then consumed *ZERO* child hints and thus effectively *NOT* have been
        # passed at all. Testing this condition *AFTER* detecting an unpacked
        # type variable tuple enables that type parameter to be correctly mapped
        # to the empty tuple below.
        elif hints_index_curr >= hints_child_len:
            # If *NO* child hints were passed, raise an exception.
            #
            # Note that this condition is intentionally tested here *AFTER*
            # ensuring that this parent hint is parametrized by *NO* unpacked
            # type variable tuple. Why? Because it is conditionally valid for
            # the caller to pass exactly *ZERO* child hints and *ONE* unpacked
            # type variable tuple, which would have then consumed *ZERO* child
            # hints and thus effectively *NOT* have been passed at all.
            if not hints_child_len:
                raise BeartypeDecorHintPep484612646Exception(
                    f'{EXCEPTION_PLACEHOLDER}type hint {repr(hint)} '
                    f'subscripted by no child type hints but '
                    f'parametrized by PEP 484 type variables '
                    f'{repr(hints_typearg)} necessarily matching '
                    f'at least one child hint.'
                )
            # Else, one or more child hints were passed.

            # Immediately halt all further visitation of type parameters and
            # child hints by this iteration. All remaining type variables will
            # be silently ignored and thus preserved as is *WITHOUT* being
            # mapped -- a valid edge case.
            break
        # Else, the 0-based index of this child hint does *NOT* exceed that
        # of the last child hint.

        # Current leading child hint.
        hint_child = hints_child[hints_index_curr]
        # print(f'Mapping typearg {typearg} -> hint {hint}...')
        # print(f'is_hint_nonpep_type({hint})? {is_hint_nonpep_type(hint, False)}')

        # Raise an exception if either:
        # * This type parameter is a PEP 484-compliant type variable *AND*
        #   this child hint violates this type variable's bounded constraints.
        # * This type parameter is *NOT* a PEP 484-compliant type variable.
        _die_unless_hint_pep484_typevar_bound_bearable(
            hint_child=hint_child,
            hint_typearg=hint_typearg,
            hint_typearg_sign=hint_typearg_sign,
        )
        # Else, this type parameter is a PEP 484-compliant type variable *AND*
        # this child hint satisfies this type variable's bounded constraints.

        # Map this type variable to this hint with an optimally efficient
        # one-liner, silently overwriting any prior such mapping of this type
        # variable by either this call or a prior call of this function.
        typearg_to_hint[hint_typearg] = hint_child
        # print(f'Mapping {hint_typearg} to {hint_child}...')

        # Iterate the 0-based index of the current type parameter *AND*
        # corresponding child hint to be visited by the next loop iteration.
        hints_index_curr += 1

    # If a PEP 646-compliant unpacked type variable tuple was visited by the
    # "while" loop above...
    if hints_pep646_typevartuple_index is not None:
        # ....................{ PHASE 2 ~ pep 484 : typevar}....................
        # In this next phase, we map all *TRAILING* PEP 484-compliant type
        # variables parametrizing the ending of this parent subscripted hint.
        # These variables follow the first (and ideally only) PEP 646-compliant
        # type variable tuple parametrizing the middle of this parent
        # subscripted hint.
        #
        # The "while" loop above iterates forward over type variables starting
        # at the first type variable, as is customary for most iteration. In
        # contrast, the "while" loop below iterates backward over type variables
        # starting at the last type variable. Why? Because type variable tuples
        # greedily consume all remaining child hints that have yet to be
        # consumed by a trailing type variable. To decide which child hints
        # remain to be consumed by a type variable tuple requires that we first
        # consume as many trailing child hints as possible by as many trailing
        # type variables exist. Whatever child hints remain are then apportioned
        # to the type variable tuple.
        # print(f'hints_pep646_typevartuple_index: {hints_pep646_typevartuple_index}')

        # This unpacked type variable tuple.
        hint_pep646_typevartuple = hints_typearg[
            hints_pep646_typevartuple_index]

        # 0-based index of the current trailing type parameter visited by the
        # "while" loop below, initialized to that of the last type parameter.
        hints_pep646_typearg_index_curr = hints_typearg_len - 1
        # print(f'hints_pep646_typearg_index_curr: {hints_pep646_typearg_index_curr}')

        # 0-based index of the current trailing child hint visited by the
        # "while" loop below, initialized to that of the last child hint.
        hints_pep646_child_index_curr = hints_child_len - 1
        # print(f'hints_pep646_child_index_curr: {hints_pep646_child_index_curr}')

        # 0-based index of the first trailing type parameter to be visited last
        # by the "while" loop below, initialized to that of the first type
        # parameter following this unpacked type variable tuple. This and all
        # following type parameters have yet to consume any child hints and thus
        # *MUST* thus consume those child hints before this unpacked type
        # variable tuple if given a fallback chance to greedily do so below.
        # Every type parameter necessarily consumes exactly one child hint and
        # thus assumes precedence over any unpacked type variable tuple, which
        # permissively consumes zero or more child hints.
        hints_pep646_typearg_index_first = hints_pep646_typevartuple_index + 1
        # print(f'hints_pep646_typearg_index_first: {hints_pep646_typearg_index_first}')

        # 0-based index of the first trailing child hint to be visited last by
        # the "while" loop below, initialized to that of the first child hint
        # following the last *LEADING* child hint consumed by the "while" loop
        # above. This and all following child hints have yet to be consumed and
        # thus remain available for consumption by trailing type parameters.
        hints_pep646_child_index_first = hints_index_curr
        # print(f'hints_pep646_child_index_first: {hints_pep646_child_index_first}')

        # While the 0-based index of the current trailing type parameter still
        # follows that of the unpacked type variable tuple to *NOT* be visited
        # by this loop, one or more trailing type parameters remain unconsumed.
        # In this case...
        while (
            hints_pep646_typearg_index_curr >=
            hints_pep646_typearg_index_first
        ):
            # print(f'Visiting trailing type parameter index {hints_pep646_typearg_index_curr}...')
            # print(f'>= {hints_pep646_typearg_index_first}...')

            # Current trailing type parameter.
            hint_typearg = hints_typearg[hints_pep646_typearg_index_curr]

            # Sign uniquely identifying this type parameter.
            hint_typearg_sign = get_hint_pep_sign_or_none(hint_typearg)  # pyright: ignore
            # print(f'Visiting trailing type parameter {hint_typearg} of {hint_typearg_sign}...')

            # If this type parameter is a second PEP 646-compliant unpacked type
            # variable tuple, raise an exception. PEP 646 mandates that generics
            # be parametrized by at most one unpacked type variable tuple.
            if hint_typearg_sign is HintSignPep646TypeVarTupleUnpacked:
                raise BeartypeDecorHintPep484612646Exception(
                    f'{EXCEPTION_PLACEHOLDER}type hint {repr(hint)} '
                    f'parametrized by PEP 646-noncompliant type parameters '
                    f'{repr(hints_typearg)} containing two or more PEP 646 '
                    f'unpacked type variable tuples, including:\n'
                    f'* {repr(hint_pep646_typevartuple)} at index '
                    f'{hints_pep646_typevartuple_index}.\n'
                    f'* {repr(hint_typearg)} at index '
                    f'{hints_pep646_typearg_index_curr}.\n'
                )
            # Else, this type parameter is *NOT* a second PEP 646-compliant
            # unpacked type variable tuple.
            #
            # If the 0-based index of this trailing child hint precedes that of
            # the first trailing child hint, more type parameters than child
            # hints were passed by similar logic as above. In this case,
            # immediately halt all further visitation of type parameters and
            # child hints by this iteration. All remaining type variables will
            # be silently ignored and thus preserved as is *WITHOUT* being
            # mapped -- a valid edge case.
            #
            # Note that, unlike above, it is valid for *NO* child hints to be
            # passed. Why? Because this parent hint is parametrized by an
            # unpacked type variable tuple, which will then consume *ZERO* child
            # hints below.
            elif (
                hints_pep646_child_index_curr <
                hints_pep646_child_index_first
            ):
                # print('Ignoring all trailing excess type parameters...')
                break
            # Else, the 0-based index of this trailing child hint exceeds or is
            # equal to that of the first trailing child hint.

            # Current trailing child hint.
            hint_child = hints_child[hints_pep646_child_index_curr]

            # Raise an exception if either:
            # * This type parameter is a PEP 484-compliant type variable *AND*
            #   this child hint violates this type variable's bounds.
            # * This type parameter is *NOT* a PEP 484-compliant type variable.
            _die_unless_hint_pep484_typevar_bound_bearable(
                hint_child=hint_child,
                hint_typearg=hint_typearg,
                hint_typearg_sign=hint_typearg_sign,
            )
            # Else, this type parameter is a PEP 484-compliant type variable
            # *AND* this child hint satisfies this type variable's bounds.

            # Map this type variable to this child hint with an efficient
            # one-liner, overwriting any prior such mapping of this type
            # variable by either this call or a prior call of this function.
            typearg_to_hint[hint_typearg] = hint_child
            # print(f'Mapping {hint_typearg} to {hint_child}...')

            # Iterate the 0-based indices of the current type parameter *AND*
            # corresponding child hint to be visited by the next loop iteration.
            hints_pep646_typearg_index_curr -= 1
            hints_pep646_child_index_curr -= 1

        # ....................{ PHASE 3 ~ pep 646 : tuple  }....................
        # In this next phase, we map the sole PEP 646-compliant unpacked type
        # variable tuple parametrizing the middle of this parent subscripted
        # hint. This unpacked type variable tuple:
        # * Follows the leading PEP 484-compliant type variables mapped by the
        #   first phase above.
        # * Precedes the trailing PEP 484-compliant type variables mapped by the
        #   second phase above.
        #
        # If...
        if (
            # The 0-based index of the current type parameter to be consumed is
            # that of the middle unpacked type variable tuple *AND*...
            #
            # In this case, *ALL* trailing type parameters were consumed. The
            # only remaining type parameter to be consumed is the middle
            # unpacked type variable tuple.
            (
                hints_pep646_typearg_index_curr ==
                hints_pep646_typevartuple_index
            ) and
            # The 0-based index of the current trailing child hint to be
            # consumed is or exceeds that of the last *LEADING* child hint
            # consumed by the "while" loop far above...
            #
            # Two cases arise. The 0-based index of the current trailing child
            # hint to be consumed is either:
            # * Exactly that of the last *LEADING* child hint. Then *ALL*
            #   trailing child hints were consumed by the "while" loop above.
            #   Zero trailing child hints remain to be consumed by this unpacked
            #   type variable tuple -- a valid edge case.
            # * Greater than that of the last *LEADING* child hint. Then one or
            #   more trailing child hints were *NOT* consumed by the "while"
            #   loop above. One or more trailing child hints remain to be
            #   consumed by this unpacked type variable tuple -- also a valid
            #   use case.
            #
            # In either case, zero or more trailing child hints were *NOT*
            # consumed by the "while" loop above. Since an unpacked type
            # variable tuple permissively consumes zero or more child hints,
            # this unpacked type variable tuple should now do so.
            (
                hints_pep646_child_index_curr >=
                hints_pep646_child_index_first - 1
            )
        ):
            # print('Mapping unpacked type variable tuple to excess child hints...')

            # Tuple of the zero or more excess child hints *NOT* already
            # consumed above by a trailing type variable, defined here as the
            # slice of the tuple of the zero or more trailing child hints...
            #
            # Note that raw tuples are, by definition, PEP-noncompliant. Ergo,
            # this tuple is PEP-noncompliant as well and thus unsuitable for
            # being directly mapped to this unpacked type variable tuple.
            hints_child_excess = hints_child[
                # Starting at the index of the first trailing child hint
                # *AND*...
                hints_pep646_child_index_first:
                # Ending at the index of the last excess trailing child hint.
                # Note that slice syntax requires incrementing the last index,
                # which it treats as analogous to a length. Specifically, slice
                # syntax ignores the item at the last index.
                #
                # Oh, Python... You sweet summer child.
                hints_pep646_child_index_curr + 1
            ]
            # print(f'hints_child_excess: {hints_child_excess}')

            # Target hint to which this unpacked type variable will be mapped
            # below, synthesized from this PEP-noncompliant tuple slice into a
            # PEP-compliant type hint.
            hint_pep646_typevartuple_target: Hint = SENTINEL  # type: ignore[assignment]

            # If exactly one child hint has *NOT* already consumed, directly map
            # this unpacked type variable to this child hint rather than mapping
            # this unpacked type variable to the 1-tuple containing this child
            # hint.
            #
            # Note that this is *NOT* merely a negligible optimization, although
            # this is technically that. This edge case is required to correctly
            # map unpacked type variable tuples to other unpacked type variable
            # tuples *WITHOUT* triggering infinite recursion. Why? Because the
            # reduce_hint_pep484612646_typearg() function reduces unpacked type
            # variable tuples that have been previously mapped to unpacked type
            # variable tuples with iteration over the returned "typearg_to_hint"
            # dictionary. For efficiency and simplicity, that iteration only
            # supports direct mappings. That iteration does *NOT* support an
            # unpacked type variable tuple mapping to a 1-tuple containing an
            # unpacked type variable tuple. Consider an example that would
            # induce infinite recursion (unless explicitly handled):
            #     from typing import Generic, TypeVarTuple
            #
            #     Ts = TypeVarTuple('Ts')
            #     Tt = TypeVarTuple('Tt')
            #
            #     class RootGeneric(    Generic[*Ts]): pass
            #     class StemGeneric(RootGeneric[*Tt]): pass
            #     class LeafGeneric(StemGeneric[*Ts]): pass#
            if len(hints_child_excess) == 1:
                hint_pep646_typevartuple_target = hints_child_excess[0]
            # Else, either zero or two or more child hints have *NOT* already
            # consumed. In either case, only a tuple of child hints correctly
            # expresses this excessive mapping.
            else:
                #FIXME: [SPEED] Inefficient. This factory internally creates and
                #then discards a full-blown list object just to create this
                #unpacked tuple. Instead, we should:
                #* Define a new make_hint_pep646_tuple_unpacked_pure() factory,
                #  dynamically creating and returning a new semantically equivalent
                #  pure-Python "typing.Unpack[tuple[...]]" hint.
                #* Call that factory here instead.

                # PEP 646-compliant unpacked tuple hint of the form
                # "*tuple[hints_child_excess[0], ..., hints_child_excess[N]]".
                hint_pep646_typevartuple_target = (
                    make_hint_pep646_tuple_unpacked_prefix(hints_child_excess))
            # print(f'hint_pep646_typevartuple_target: {hint_pep646_typevartuple_target}')

            # Map this unpacked type variable tuple to this hint with a
            # one-liner, overwriting any prior such mapping of this type
            # variable by either this call or a prior call of this function.
            #
            # Note that PEP standards support mapping type variable tuples
            # *ONLY* to other type variable tuples or unpacked tuple hints.
            # Since the former fails to apply here, only the latter applies.
            # Consider PEP 696, for example, which explicitly states:
            #     TypeVarTuple defaults are defined using the same syntax as
            #     TypeVars but use an unpacked tuple of types instead of a
            #     single type or another in-scope TypeVarTuple (see Scoping
            #     Rules).
            #
            #     DefaultTs = TypeVarTuple(
            #         "DefaultTs", default=Unpack[tuple[str, int]])
            #
            # In the terminology of this factory function, the above example
            # would effectively add this mapping to "typearg_to_hint":
            #     {DefaultTs: *tuple[str, int]], ...}
            typearg_to_hint[hint_pep646_typevartuple] = (
                hint_pep646_typevartuple_target)
    # Else, a PEP 646-compliant unpacked type variable tuple was *NOT* visited
    # by the "while" loop above. In this case, that loop has already
    # successfully visited all PEP 484-compliant type variables and thus all
    # type parameters parametrizing this parent subscripted hint. We are done!

    # ....................{ RETURN                         }....................
    # Return this table, coerced into an immutable frozen dictionary.
    return FrozenDict(typearg_to_hint)
