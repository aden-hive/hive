#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`695`-compliant **type alias reducers** (i.e., low-level
callables converting higher-level objects created via the ``type`` statement
under Python >= 3.12 to lower-level type hints more readily consumable by
:mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep695Exception
from beartype.typing import Optional
from beartype._cave._cavefast import HintPep695TypeAlias
from beartype._check.convert._reduce._redrecurse import (
    is_hint_recursive,
    make_hint_sane_recursable,
)
from beartype._check.metadata.hint.hintsane import (
    HINT_SANE_RECURSIVE,
    HintOrSane,
    HintSane,
)
from beartype._data.typing.datatypingport import Hint
from beartype._util.error.utilerrget import get_name_error_attr_name
from beartype._util.hint.pep.proposal.pep695 import (
    get_hint_pep695_unsubbed_alias)

# ....................{ REDUCERS                           }....................
def reduce_hint_pep695_subbed(
    hint: Hint,
    hint_parent_sane: Optional[HintSane],
    exception_prefix: str,
    **kwargs,
) -> HintOrSane:
    '''
    Reduce the passed :pep:`695`-compliant **subscripted type alias** (i.e.,
    object created by a statement of the form ``type
    {alias_name}[{typevar_name}] = {alias_value}``) to that unsubscripted alias
    and corresponding **type variable lookup table** (i.e., immutable dictionary
    mapping from those same type variables to those same child hints).

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

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
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    Returns
    -------
    HintSane
        **Sanified type hint metadata** (i.e., :class:`.HintSane` object)
        describing this reduction.

    Raises
    ------
    BeartypeDecorHintPep484TypeVarViolation
        If one of these type hints violates the bounds or constraints of one of
        these type variables.

    See Also
    --------
    ``reduce_hint_pep484612646_subbed_typeargs_to_hints``
        Further details.
    '''
    # print(f'Reducing PEP 695 subscripted type alias {hint} with parent {hint_parent_sane}...')

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._check.convert._reduce._pep.redpep484612646 import (
        reduce_hint_pep484612646_subbed_typeargs_to_hints)

    # ....................{ RECURSE                        }....................
    # If this PEP 695-compliant subscripted type alias is recursive, ignore this
    # recursive alias to avoid infinite recursion.
    #
    # Certainly, various approaches to generating code type-checking recursive
    # hints exists. @beartype currently embraces the easiest, fastest, and
    # laziest approach: just ignore all recursion! Ignorance works wonders.
    if is_hint_recursive(
        hint=hint,
        hint_parent_sane=hint_parent_sane,
        hint_recursable_depth_max=_HINT_PEP695_RECURSABLE_DEPTH_MAX,
    ):
        # print(f'Ignoring recursive PEP 695 subscripted type alias {hint} with parent {hint_parent_sane}...')
        return HINT_SANE_RECURSIVE
    # Else, this hint is *NOT* recursive.

    # ....................{ PHASE                          }....................
    # This reducer is divided into two phases:
    # 1. The first phase decides the type variable lookup table for this alias.
    # 2. The second phase decides the recursion guard for this alias.
    #
    # Both phases are non-trivial. The output of each phase is sanified hint
    # metadata (i.e., a "HintSane" object) containing the result of the decision
    # problem decided by that phase.

    # ....................{ PHASE ~ 1                      }....................
    # Decide the type variable lookup table for this alias. Specifically, reduce
    # this PEP 695-compliant subscripted type alias to:
    # * The semantically useful unsubscripted alias originating this
    #   semantically useless subscripted alias.
    # * The type variable lookup table mapping all type variables parametrizing
    #   this unsubscripted alias to all non-type variable hints subscripting
    #   this subscripted alias.
    # print(f'[reduce_hint_pep484585_generic_subbed] Reducing subscripted generic {repr(hint)}...')
    hint_or_sane = reduce_hint_pep484612646_subbed_typeargs_to_hints(
        hint=hint,
        hint_parent_sane=hint_parent_sane,
        exception_prefix=exception_prefix,
    )

    # ....................{ PHASE ~ 2                      }....................
    # If the prior phase generated metadata...
    if isinstance(hint_or_sane, HintSane):
        # Non-recursable form of this type alias, defined as the *UNSUBSCRIPTED*
        # type alias encapsulated by this metadata.
        hint_nonrecursable = hint_or_sane.hint

        # Sanified parent type hint metadata encapsulating the sanification of
        # both the parent hint (if any) *AND* the previously decided type
        # variable lookup table for this alias. Since this new metadata is
        # guaranteed to be the superset of the old metadata applying *ONLY* to
        # the parent hint, we intentionally replace the latter with the former
        # here. See also further discussion below.
        hint_parent_sane = hint_or_sane
    # Else, the prior phase generated *NO* metadata. In this case...
    else:
        # Non-recursable form of this type alias, defined as the *UNSUBSCRIPTED*
        # type alias directly returned by the prior call to the
        # reduce_hint_pep484612646_subbed_typeargs_to_hints() reducer.
        hint_nonrecursable = hint_or_sane

    # Decide the recursion guard protecting this possibly recursive alias
    # against infinite recursion. Note that:
    # * This guard intentionally applies to the original *SUBSCRIPTED* PEP
    #   695-compliant type alias (rather rather than the *UNSUBSCRIPTED* PEP
    #   695-compliant type alias decided by the prior phase). Thus, we pass
    #   "hint_recursable=hint" rather than "hint_recursable=hint_or_sane.hint".
    # * The type variable lookup table decided in the first phase *MUST* also be
    #   preserved. Thus, we pass a new "hint_parent_sane" rather than the same
    #   "hint_parent_sane" as in the prior phase. Indeed, the new
    #   "hint_parent_sane" object should safely encapsulate all metadata
    #   encapsulated by the prior "hint_parent_sane" object.
    hint_sane = make_hint_sane_recursable(
        # The recursable form of this type alias is the original *SUBSCRIPTED*
        # type alias tested above by the is_hint_recursive() recursion guard.
        hint_recursable=hint,
        # The non-recursable form of this type alias is the new *UNSUBSCRIPTED*
        # type alias encapsulated by the metadata returned by the prior call to
        # the reduce_hint_pep484612646_subbed_typeargs_to_hints() reducer.
        hint_nonrecursable=hint_nonrecursable,
        hint_parent_sane=hint_parent_sane,
    )

    # ....................{ RETURN                         }....................
    # Return this metadata.
    return hint_sane


def reduce_hint_pep695_unsubbed(
    hint: Hint,
    hint_parent_sane: Optional[HintSane],
    exception_prefix: str,
    **kwargs,
) -> HintOrSane:
    '''
    Reduce the passed :pep:`695`-compliant **unsubscripted type alias** (i.e.,
    object created by a statement of the form ``type {alias_name} =
    {alias_value}``) to the underlying type hint referred to by this alias.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as this reducer accepts the contextual
    ``hint_parent_sane`` parameter and thus *cannot* be memoized.

    Parameters
    ----------
    hint : HintPep695TypeAlias
        Unsubscripted type alias to be reduced.
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

    All remaining passed keyword parameters are silently ignored.

    Returns
    -------
    HintSane
        **Sanified type hint metadata** (i.e., :class:`.HintSane` object)
        describing this reduction.

    Raises
    ------
    BeartypeDecorHintPep695Exception
        If this alias contains one or more unquoted relative forward references
        to undefined attributes. Note that this *only* occurs when callers avoid
        beartype import hooks in favour of manually decorating callables and
        classes with the :func:`beartype.beartype` decorator.
    '''
    assert isinstance(hint, HintPep695TypeAlias), (
        f'{repr(hint)} not PEP 695-compliant unsubscripted type alias.')

    # ....................{ RECURSE                        }....................
    #FIXME: *NON-IDEAL.* Ideally, @beartype would actually generate code
    #recursively type-checking recursive hints. However, doing so is *EXTREMELY*
    #non-trivial. Why?
    #
    #Non-triviality is one obvious concern. For each recursive hint, @beartype
    #must now:
    #* Dynamically generate one low-level recursive type-checking function
    #  unique to that recursive hint.
    #* Call each such function in higher-level wrapper functions to type-check
    #  each pith against the corresponding recursive hint.
    #
    #Safety is another obvious concern. Generated code *MUST* explicitly guard
    #against infinitely recursive containers:
    #    >>> infinite_list = []
    #    >>> infinite_list.append(infinite_list)  # <-- gg fam
    #
    #But guarding against infinitely recursive containers requires maintaining a
    #(...waitforit) frozen set of the IDs of all previously type-checked
    #objects, which must then be passed to each dynamically generated recursive
    #type-checking function that type-checks a specific recursive hint.
    #Maintaining these frozen sets then incurs a probably significant space and
    #time complexity hit.
    #
    #In short, it's pretty brutal stuff. For now, simply ignoring recursion
    #strikes us the sanest and certainly simplest approach. *sigh*

    # If this hint is recursive, ignore this hint to avoid infinite recursion.
    #
    # Certainly, various approaches to generating code type-checking recursive
    # hints exists. @beartype currently embraces the easiest, fastest, and
    # laziest approach: just ignore all recursion! Ignorance works wonders.
    if is_hint_recursive(
        hint=hint,  # pyright: ignore
        hint_parent_sane=hint_parent_sane,
        hint_recursable_depth_max=_HINT_PEP695_RECURSABLE_DEPTH_MAX,
    ):
        # print(f'Ignoring recursive PEP 695 unsubscripted type alias {hint} with parent {hint_parent_sane}...')
        return HINT_SANE_RECURSIVE
    # Else, this hint is *NOT* recursive.

    # ....................{ REDUCE                         }....................
    # Underlying type hint to be returned.
    hint_aliased: Hint = None  # pyright: ignore

    # Attempt to...
    try:
        # Reduce this alias to the type hint it lazily refers to. If this alias
        # contains *NO* forward references to undeclared attributes, this
        # reduction *SHOULD* succeed. Let's pretend we mean that.
        #
        # Note that this getter is memoized and thus intentionally called with
        # positional arguments.
        hint_aliased = get_hint_pep695_unsubbed_alias(
            hint, exception_prefix)
    # If doing so raises a builtin "NameError" exception, this alias contains
    # one or more forward references to undeclared attributes. In this case...
    except NameError as exception:
        # Unqualified basename of this alias (i.e., name of the global or local
        # variable assigned to by the left-hand side of this alias).
        hint_name = repr(hint)

        # Fully-qualified name of the third-party module defining this alias.
        hint_module_name = hint.__module__
        # print(f'hint_module_name: {hint_module_name}')

        # Unqualified basename of the next remaining undeclared attribute
        # contained in this alias relative to that module.
        hint_ref_name = get_name_error_attr_name(exception)
        # print(f'hint: {hint}; hint_ref_name: {hint_ref_name}')

        # Raise a human-readable exception describing this issue.
        raise BeartypeDecorHintPep695Exception(
            f'{exception_prefix}PEP 695 type alias "{hint_name}" '
            f'unquoted relative forward reference {repr(hint_ref_name)} in '
            f'module "{hint_module_name}" unsupported outside '
            f'"beartype.claw" import hooks. Consider either:\n'
            f'* Quoting this forward reference in this type alias: e.g.,\n'
            f'      # Instead of an unquoted forward reference...\n'
            f'      type {hint_name} = ... {hint_ref_name} ...\n'
            f'\n'
            f'      # Prefer a quoted forward reference.\n'
            f'      type {hint_name} = ... "{hint_ref_name}" ...\n'
            f'* Applying "beartype.claw" import hooks to '
            f'module "{hint_module_name}": e.g.,\n'
            f'      # In your "this_package.__init__" submodule:\n'
            f'      from beartype.claw import beartype_this_package\n'
            f'      beartype_this_package()'
        ) from exception
    # Else, doing so raised *NO* exceptions, implying this alias contains *NO*
    # forward references to undeclared attributes.

    # ....................{ RETURN                         }....................
    # Sanified metadata to be returned, guarded against infinite recursion.
    hint_sane = make_hint_sane_recursable(
        #FIXME: Document this. Kinda intense, yo. Copy-paste similar comments
        #inside _reduce_hint_overrides() to here, please. *sigh*
        hint_recursable=hint,  # pyright: ignore
        hint_nonrecursable=hint_aliased,
        hint_parent_sane=hint_parent_sane,
    )

    # Return this metadata.
    return hint_sane

# ....................{ PRIVATE ~ constants                }....................
_HINT_PEP695_RECURSABLE_DEPTH_MAX = 1
'''
Value of the optional ``hint_recursable_depth_max`` parameter passed to the
:func:`.is_hint_recursive` tester by the :pep:`695`-compliant reducers defined
above.

This depth ensures that :pep:`695`-compliant type aliases are considered to be
recursive *only* after having been recursed into at most this many times before
(i.e., *only* after having been visited exactly twice, once as a parent alias
and again as a transitive child hint of this parent alias). :pep:`695`-compliant
type aliases typically describe non-trivial recursive data structures conveying
internal semantics that merit deeper recursion. This depth guarantees that.

Consider the following :pep:`695`-compliant subscripted type alias:

.. code-block:: python

   type RecursiveList[T] = list[RecursiveList[T] | T]

Lists satisfying the concrete type alias ``RecursiveList[int]`` contain an
arbitrary number of integers and other lists containing an arbitrary number of
integers, exhibiting this internal structure:

.. code-block:: python

   [42, [79]]
   [42, [79], 83]
   [42, [79], 83, [56, 12]]

Halting recursion at the first expansion of the concrete type alias
``RecursiveList[int]`` to ``list[RecursiveList[int] | int]`` would then reduce
the latter to ``list[HINT_SANE_RECURSIVE | int]``, which reduces to
``list[HINT_SANE_RECURSIVE]``, which reduces to :class:`list`, which clearly
fails to convey the internal semantics of this data structure.

Halting recursion at the second expansion of the concrete type alias
``RecursiveList[int]`` to ``list[RecursiveList[int] | int]`` instead reduces the
latter to ``list[list[RecursiveList[int] | int] | int]``, which reduces to
``list[list[HINT_SANE_RECURSIVE | int] | int]``, reducing to
``list[list[HINT_SANE_RECURSIVE] | int]``, which reduces to ``list[list |
int]`` -- conveying exactly one layer of the internal semantics of this
recursive data structure.
'''
