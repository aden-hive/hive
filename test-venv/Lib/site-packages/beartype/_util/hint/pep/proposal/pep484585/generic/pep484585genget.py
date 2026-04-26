#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`- and :pep:`585`-compliant **generic type hint
getters** (i.e., low-level callables generically introspecting various
properties common to both :pep:`484`- and :pep:`585`-compliant generic classes).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep484585Exception
from beartype.typing import (
    List,
    Optional,
    Union,
)
from beartype._cave._cavefast import CallableOrClassTypes
from beartype._data.typing.datatypingport import (
    Hint,
    HintOrNone,
    ListHints,
    Pep484612646TypeArgUnpackedToHint,
    TupleHints,
)
from beartype._data.typing.datatyping import (
    FrozenSetStrs,
    TypeException,
)
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.hint.sign.datahintsignmap import (
    HINT_MODULE_NAME_TO_HINT_BASE_EXTRINSIC_BASENAME_TO_SIGN)
from beartype._data.kind.datakindmap import FROZENDICT_EMPTY
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.hint.pep.proposal.pep484.pep484generic import (
    get_hint_pep484_generic_bases_unerased)
from beartype._util.hint.pep.proposal.pep484612646 import (
    is_hint_pep484612646_typearg_unpacked)
from beartype._util.hint.pep.proposal.pep585 import (
    get_hint_pep585_generic_bases_unerased,
    is_hint_pep585_generic,
)
from beartype._util.kind.sequence.utilseqmake import make_stack
from beartype._util.text.utiltextjoin import join_delimited_disjunction
from itertools import count

# ....................{ GETTERS ~ args                     }....................
#FIXME: *SUPER-INTENSE.* Shift this into a more appropriate submodule, please --
#say, a new "pep484585genfind" submodule. This isn't so much a getter as a
#finder, really. There's a deep algorithm here.
#FIXME: Document all of the edge cases in which this getter raises exceptions.
#FIXME: Unit test this getter with respect to generics subscripted by PEP
#646-compliant unpacked type variable tuples: e.g.,
#    class MuhGeneric[*Ts](Generic[*Ts]): ...
#
#We currently only test this getter with respect to generics subscripted by PEP
#484-compliant type variables. *sigh*
@callable_cached
def get_hint_pep484585_generic_args_full(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    hint_base_target: HintOrNone = None,
    exception_cls: TypeException = BeartypeDecorHintPep484585Exception,
    exception_prefix: str = '',
) -> TupleHints:
    '''
    Tuple of the one or more **full child type hints** (i.e., complete tuple of
    *all* type hints directly subscripting both the passed generic *and*
    one or more pseudo-superclasses of this generic) transitively subscripting
    the passed :pep:`484`- or :pep:`585`-compliant **generic** (i.e., class
    superficially subclassing at least one PEP-compliant type hint that is
    possibly *not* an actual class) if this object is a generic *or* raise an
    exception otherwise (i.e., if this object is not a generic).

    This getter greedily replaces in the passed tuple as many abstract
    :pep:`484`-compliant **type parameters** (i.e., :class:`typing.TypeVar`
    objects) as there are concrete child type hints directly subscripting the
    passed generic. Doing so effectively "bubbles up" these concrete children up
    the class hierarchy into the "empty placeholders" established by the type
    variables transitively subscripting all pseudo-superclasses of this generic.

    This getter is guaranteed to return a non-empty tuple. By definition, a
    generic subclasses one or more generic superclasses necessarily subscripted
    by one or more child type hints.

    This getter is memoized for efficiency.

    Caveats
    -------
    **This getter is computationally complex in both space and time.** This
    getter exhibits:

    * Amortized :math:`O(1)` constant time complexity, thanks to memoization.
    * Non-amortized worst-case :math:`O(jk)` quadratic time complexity for:

      * :math:`j` the largest number of child type hints transitively
        subscripting a pseudo-superclass of this generic.
      * :math:`k` the total number of transitive pseudo-superclasses of this
        generic.

    **This getter is currently implemented with recursion.** Doing so yields a
    relatively trivial algorithm at a relatively non-trivial increase in runtime
    overhead, due to overhead associated with function calls in Python.

    Parameters
    ----------
    hint : Hint
        Generic type hint to be inspected.
    hint_base_target : Optional[Hint] = None
        **Target pseudo-superclass** (i.e., erased transitive pseudo-superclass
        of the passed generic to specifically search, filter, and return the
        child type hints of). Defaults to :data:`None`. Specifically:

        * If this parameter is :data:`None`, this getter returns the complete
          tuple of *all* type hints directly subscripting both the passed
          generic *and* one or more pseudo-superclasses of this generic.
        * If this parameter is *not* :data:`None`, this getter returns the
          partial tuple of *only* type hints directly subscripting both the
          passed generic *and* this passed pseudo-superclass of this generic.

        A target pseudo-superclass is passed to deduce whether two generics are
        related according to the :func:`beartype.door.is_subhint` relation. If
        all child type hints in the tuple returned by this getter (when passed
        some generic and its pseudo-superclass) are subhints of all child type
        hints in the tuple returned by this getter passed *only* that
        pseudo-superclass, then that generic is necessarily a subhint of that
        pseudo-superclass. Look. Just go with it, people.

        Lastly, note that this getter intentionally ignores *all* child hints
        subscripting this target pseudo-superclass. For search purposes, *any*
        child hints subscripting this target pseudo-superclass are not only
        irrelevant but harmful -- promoting false negatives in higher-level
        functions (e.g., :func:`beartype.door.is_subhint`) internally leveraging
        this lower-level getter. Ignoring these child hints is thus imperative.
        Since deciding child hint compatibility between the passed generic and
        this target pseudo-superclass is a non-trivial decision problem, this
        lower-level getter defers that problem to the caller by unconditionally
        returning the same result regardless of child hints subscripting this
        target pseudo-superclass.

        For example, consider the :pep:`484`-compliant :obj:`typing.Any`.
        Clearly, this getter should return the same tuple when passed an
        unsubscripted target pseudo-superclass as when passed a target
        pseudo-superclass subscripted by :obj:`typing.Any`: e.g.,

        .. code-block:: pycon

           >>> from typing import Any, Generic
           >>> class MuhGeneric[S, T](Generic[S, T]): pass
           >>> get_hint_pep484585_generic_args_full(
           ...     MuhGeneric, hint_base_target=Generic)
           (S, T)
           >>> get_hint_pep484585_generic_args_full(
           ...     MuhGeneric, hint_base_target=Generic[Any])
           (S, T)
           >>> get_hint_pep484585_generic_args_full(
           ...     MuhGeneric, hint_base_target=Generic[S, T])
           (S, T)
           >>> get_hint_pep484585_generic_args_full(
           ...     MuhGeneric, hint_base_target=Generic[int, float])
           (S, T)

    exception_cls : TypeException
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintPep484585Exception`.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    Tuple[Hint, ...]
        Tuple of the one or more full child type hints transitively subscripting
        this generic.

    Raises
    ------
    exception_cls
        If this hint is either:

        * Neither a :pep:`484`- nor :pep:`585`-compliant generic.
        * A :pep:`484`- or :pep:`585`-compliant generic subclassing *no*
          pseudo-superclasses.

    Examples
    --------
    .. code-block:: pycon

       >>> from beartype.typing import Generic, TypeVar
       >>> from beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget import (
       ...     get_hint_pep484585_generic_args_full)

       >>> S = TypeVar('S')
       >>> T = TypeVar('T')

       >>> class GenericSuperclass(Generic[S], list[T]): pass
       >>> class GenericList(list[complex]): pass
       >>> class GenericSubclass(GenericSuperclass[int, T], GenericList): pass

       >>> get_hint_pep484585_generic_args_full(GenericSuperclass)
       (S, T)
       >>> get_hint_pep484585_generic_args_full(GenericSuperclass[int, float])
       (int, float)
       >>> get_hint_pep484585_generic_args_full(GenericSubclass)
       (int, T, complex)
       >>> get_hint_pep484585_generic_args_full(GenericSubclass[float])
       (int, float, complex)
       >>> get_hint_pep484585_generic_args_full(GenericSubclass[float])
       (int, float, complex)
    '''
    assert isinstance(exception_cls, type), (
        f'{repr(exception_cls)} not exception type.')
    assert isinstance(exception_prefix, str), (
        f'{repr(exception_prefix)} not string.')

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._util.hint.pep.proposal.pep484585.generic.pep484585gentest import (
        is_hint_pep484585_generic_user)
    from beartype._util.hint.pep.utilpepget import get_hint_pep_args

    # ....................{ PREAMBLE                       }....................
    # If the caller explicitly passed a pseudo-superclass target...
    #
    # Note that this is the common case for this getter and thus tested first.
    if hint_base_target:
        hint_base_target = (
            # If this pseudo-superclass target is this generic, this
            # pseudo-superclass target is effectively meaningless (albeit
            # technically valid). In this case, silently ignore this
            # pseudo-superclass target.
            None
            if hint is hint_base_target else
            # Else, this pseudo-superclass target is *NOT* this generic. In this
            # case, the unsubscripted generic underlying this possibly
            # subscripted target pseudo-superclass generic. See the docstring.
            get_hint_pep484585_generic_type(  # pyright: ignore
                hint=hint_base_target,
                exception_cls=exception_cls,
                exception_prefix=exception_prefix,
            )
        )
    # Else, the caller passed *NO* pseudosuperclass target. In this case...

    # ....................{ LOCALS                         }....................
    # Metadata describing the passed generic, used to seed the depth-first
    # search (DFS) below with the first pseudo-superclass to be visited.
    hint_root_data: ListHints = [  # pyright: ignore
        # This generic.
        hint,

        # Metadata describing the direct parent pseudo-superclass of this
        # generic. By definition, this generic is the root of this n-ary tree
        # and thus has *NO* parent (either direct or indirect).
        None,  # pyright: ignore
    ]

    # Unvisited pseudo-superclass stack (i.e., efficiently poppable list of
    # metadata describing *ALL* unvisited transitive pseudo-superclasses of this
    # generic, intentionally reordered in reverse order to enable the
    # non-recursive depth-first search (DFS) performed below to both visit and
    # pop these pseudo-superclasses in the expected order), seeded with metadata
    # describing the passed generic.
    #
    # Each item of this stack is a list of metadata describing an unvisited
    # transitive pseudo-superclass of this generic such that this list is
    # either:
    # * If this pseudo-superclass has yet to be visited by this DFS, a 2-list
    #   "(hint, hint_super_data)" where:
    #   * "hint" is this pseudo-superclass.
    #   * "hint_super_data" is either:
    #     * If this pseudo-superclass has a parent pseudo-superclass, the item
    #       of this stack describing that parent pseudo-superclass.
    #     * Else, this pseudo-superclass is the passed generic. Since this
    #       generic has *NO* parent pseudo-superclass, "None".
    # * If this pseudo-superclass is itself a user-defined generic (i.e.,
    #   defined by a third-party downstream package) that has already been
    #   visited by this DFS, a 4-list "(hint, hint_super_data, hint_args_stack,
    #   hint_args_full)" where:
    #   * "hint" is this pseudo-superclass.
    #   * "hint_super_data" is as defined above.
    #   * "hint_args_stack" is this pseudo-superclass' direct child hint stack
    #     (i.e., list of the zero or more child hints directly subscripting this
    #     pseudo-superclass in reverse order, embodying an efficiently poppable
    #     stack of these hints), popped off while recursing up from the child
    #     pseudo-superclasses of this pseudo-superclass.
    #   * "hint_args_full" is the list of zero or more child hints transitively
    #     subscripting this pseudo-superclass, defined while recursing up from
    #     the child pseudo-superclasses of this pseudo-superclass.
    #
    # In short, there be dragons here -- albeit extremely efficient dragons.
    hint_bases_data: _HintBasesData = [hint_root_data]  # type: ignore[list-item]

    # Dictionary mapping from each previously observed PEP 484-compliant type
    # variable (i.e., "typing.TypeVar" object) subscripting a transitive
    # pseudo-superclass of this generic to the corresponding child hint "bubbled
    # up" from a subclass of that pseudo-superclass into that type parameter.
    #
    # This dictionary enables the DFS below to reliably "bubble up" a single
    # child hint to the same type parameter appearing multiple times throughout a
    # generics hierarchy. For example, this dictionary enables the "int" child
    # hint subscripting the "GenericList" generic to be "bubbled up" into the
    # type parameter "T" subscripting the pseudo-superclasses "List" and
    # "Generic" of this generic: e.g.,
    #     >>> class GenericList[T](List[T], Generic[T]): pass
    #     >>> get_hint_pep484585_generic_args_full(GenericList[int])
    #     (int, int)
    #
    # For the above call, this contents of this dictionary resemble:
    #     typearg_to_hint = {T: int}
    typearg_to_hint: Pep484612646TypeArgUnpackedToHint = {}

    # ....................{ LOCALS ~ target                }....................
    # List of zero or more child hints transitively subscripting the passed
    # target pseudo-superclass of this generic if this pseudo-superclass has
    # already been visited by the DFS below *OR* "None" otherwise (i.e., if this
    # pseudo-superclass has yet to be visited by this DFS).
    hint_base_target_args_full: Optional[ListHints] = None

    # True only if the pseudo-superclass currently visited by the DFS below is
    # still transitively subscripted by one or more PEP 484-compliant type
    # variables (i.e., "TypeVar" objects) that have yet to be replaced by
    # concrete hints of a parent pseudo-superclass of that pseudo-superclass.
    is_hint_base_arg_typearg = False

    # ....................{ SEARCH                         }....................
    # Iteration simulating a recursive depth-first search (DFS), efficiently
    # deciding the tuple of all child hints transitively subscripting the
    # desired pseudo-superclass of this generic.

    # With at least one transitive pseudo-superclass of this generic remains
    # unvisited...
    while hint_bases_data:
        # Metadata describing the currently visited transitive pseudo-superclass
        # of this generic defined as the top-most item of this stack.
        #
        # Note that we intentionally avoid popping this pseudo-superclass off
        # this stack yet. We only pop a pseudo-superclass off this stack *AFTER*
        # resolving all child pseudo-superclasses of that pseudo-superclass,
        # which simulates the "backing out" performed by genuine recursion.
        hint_base_data = hint_bases_data[-1]

        # Currently visited transitive pseudo-superclass of this generic.
        hint_base = hint_base_data[_HINT_BASES_INDEX_HINT]

        # True only if the metadata describing this pseudo-superclass is still
        # its initial size, implying that this DFS has yet to visit this
        # pseudo-superclass by recursing down into the child pseudo-superclasses
        # of this pseudo-superclass.
        is_hint_base_leaf = len(hint_base_data) == _HINT_BASE_DATA_LEN_LEAF

        # If...
        if (
            # This DFS has yet to visit this pseudo-superclass *AND*...
            is_hint_base_leaf and
            # This pseudo-superclass is itself a PEP 484- or 585-compliant
            # user-defined generic. Standard generics (i.e., that are *NOT*
            # user-defined) have *NO* pseudo-superclasses and are thus omitted.
            # Examples of omittable standard generics include:
            # * "dict[str, U]".
            # * "typing.Generic[S, int]").
            # * "typing.Protocol[float, T]").
            #
            # Note that this tester is mildly slower than the prior test and
            # thus intentionally tested later.
            is_hint_pep484585_generic_user(hint_base)  # type: ignore[arg-type]
        # Then this DFS is currently recursing down into the child
        # pseudo-superclasses of this pseudo-superclass. In this case...
        ):
            # Expand the metadata describing this pseudo-superclass from its
            # current 2-list "(hint, hint_super_data)" into the expanded 4-list
            # "(hint, hint_super_data, hint_args_stack, hint_args_full)".
            # Specifically, append (in order):
            hint_base_data.extend((
                # Poppable stack of the zero or more child hints directly
                # subscripting this child pseudo-superclass.
                make_stack(get_hint_pep_args(hint_base)),
                # List of the zero or more child hints transitively subscripting
                # this child pseudo-superclass.
                [],
            ))

            # Tuple of the one or more child pseudo-superclasses of this
            # pseudo-superclass.
            # print(f'Introspecting generic {hint} unerased bases...')
            hint_child_bases = get_hint_pep484585_generic_bases_unerased(
                hint=hint_base,  # type: ignore[arg-type]
                exception_cls=exception_cls,
                exception_prefix=exception_prefix,
            )
            # print(f'Generic {hint} unerased bases: {hint_child_bases}')

            # For each child pseudo-superclass of this pseudo-superclass,
            # intentionally iterated in reverse order so as to ensure that the
            # *FIRST* child pseudo-superclass is the *LAST* item of this stack
            # (and thus the *FIRST* unvisited pseudo-superclass to be visited by
            # this depth-first search (DFS) next).
            #
            # Note that the reversed() builtin is well-known to be the most
            # efficient means of producing a reversed iterable for iteration
            # purposes. See also:
            #     https://stackoverflow.com/a/16514411/2809027
            for hint_child_base in reversed(hint_child_bases):
                # Push metadata describing this unvisited child
                # pseudo-superclass onto this stack.
                hint_bases_data.append([
                    # This child pseudo-superclass.
                    hint_child_base,

                    # Metadata describing the direct parent
                    # pseudo-superclass of this child pseudo-superclass.
                    hint_base_data,
                ])
        # Else, either:
        # * This DFS has already visited this pseudo-superclass *OR*...
        # * This pseudo-superclass is a "terminal" leaf generic *OR*...
        # * This pseudo-superclass is *NOT* a generic.
        #
        # In any case, this DFS should *NOT* recurse (back) down into this
        # pseudo-superclass. Therefore, this DFS is currently recursing back up
        # out of this pseudo-superclass into its parent pseudo-superclass.
        else:
            # Pop this pseudo-superclass off this stack.
            hint_bases_data.pop()
            # print(f'Resuming generic {hint} pseudo-superclass {hint_base} args {hint_base_args}...')

            # List of the zero or more child hints transitively subscripting
            # this pseudo-superclass, defined as either...
            hint_base_args_full: ListHints = (  # pyright: ignore
                # If this is a terminal leaf pseudo-superclass, the tuple of
                # zero or more child hints directly subscripting this
                # pseudo-superclass. Why? Because this pseudo-superclass has
                # *NO* child pseudo-superclass to recurse down into. If this
                # pseudo-superclass had one or more child pseudo-superclasses to
                # recurse down into, then those child pseudo-superclasses would
                # have defined the "hint_base_data[_HINT_BASES_INDEX_ARGS_FULL]"
                # list accessed by the next branch, providing the list of zero
                # or more child hints transitively subscripting this
                # pseudo-superclass. Although that list remains undefined, the
                # tuple of zero or more child hints directly subscripting this
                # pseudo-superclass is semantically equivalent to what that list
                # would have been (had that list actually been defined).
                list(get_hint_pep_args(hint_base))  # type: ignore[assignment]
                if is_hint_base_leaf else
                # Else, this is *NOT* a terminal leaf pseudo-superclass. In this
                # case, the list of zero or more child hints transitively
                # subscripting this pseudo-superclass previously defined by
                # child pseudo-superclasses of this pseudo-superclass in
                # lower-level recursion.
                hint_base_data[_HINT_BASES_INDEX_ARGS_FULL]
            )

            # Reset this boolean to its default value (i.e., "False") *BEFORE*
            # possibly setting this boolean to "True" below, facilitating
            # efficient communication between the "if hint_base_args_full:" and
            # "if hint_base_target:" branches below.
            #
            # Equivalently, record that this pseudo-superclass is transitively
            # subscripted by *NO* type parameters. Since the "if
            # hint_base_args_full:" branch below works as hard as possible to
            # ensure that this is the case, this default is sensible until
            # proven otherwise below.
            is_hint_base_arg_typearg = False

            # If this pseudo-superclass is transitively subscripted by
            # at least one child hint...
            if hint_base_args_full:
                # Metadata describing the direct parent pseudo-superclass of
                # this pseudo-superclass.
                hint_base_super_data = hint_base_data[_HINT_BASES_INDEX_PARENT]
                # print(f'Resuming generic {hint} pseudo {hint_base} parent {hint_base_super_data[0]}...')

                # If this pseudo-superclass has a parent pseudo-superclass
                # (i.e., this pseudo-superclass is *NOT* the passed root generic
                # and is thus a transitive child of this generic)...
                if hint_base_super_data:
                    # Poppable stack of the zero or more child hints directly
                    # subscripting this parent pseudo-superclass.
                    hint_base_super_args_stack = hint_base_super_data[  # pyright: ignore
                        _HINT_BASES_INDEX_ARGS_STACK]

                    # For the 0-based index of each child hint transitively
                    # subscripting this pseudo-superclass and this hint...
                    #
                    # Note that this iteration could be fenced behind an "if"
                    # conditional resembling:
                    #     if not (
                    #         hint_base_super_args_stack or
                    #         typearg_to_hint
                    #     ):
                    #
                    # However, doing so would be almost entirely pointless. Why?
                    # Because almost *ALL* generics are transitively subscripted
                    # by one or more type parameters. Ergo, "typearg_to_hint" is
                    # almost *ALWAYS* non-empty. Ergo, the above "if"
                    # conditional reduces to "if True:" in most cases. We sigh.
                    for hint_base_arg_full_index, hint_base_arg_full in (
                        enumerate(hint_base_args_full)):
                        # If this hint is a type parameter...
                        if is_hint_pep484612646_typearg_unpacked(
                            hint_base_arg_full):
                            # If a concrete (i.e., non-type parameter) child
                            # hint directly subscripting a sibling
                            # pseudo-superclass of this pseudo-superclass has
                            # already been "bubbled up" into this type
                            # parameter, preserve that bubbling by re-bubbling
                            # up the same child hint back into this type
                            # parameter. <-- lol
                            if hint_base_arg_full in typearg_to_hint:
                                # print(f'Rebubbling hint {typearg_to_hint[hint_base_arg]} into...')
                                # print(f'base {hint_base} typevar {hint_base_arg}!')
                                hint_base_args_full[hint_base_arg_full_index] = (
                                    typearg_to_hint[hint_base_arg_full])  # type: ignore[index]
                            # Else, *NO* child hint directly subscripting a
                            # sibling pseudo-superclass of this child
                            # pseudo-superclass has already been "bubbled up"
                            # into this type parameter.
                            #
                            # If this parent pseudo-superclass of this child
                            # pseudo-superclass is still directly subscripted by
                            # one or more child hints that have yet to "bubble
                            # up" the class hierarchy (i.e., by replacing the
                            # first unused type parameter transitively
                            # subscripting this child pseudo-superclass),
                            # "bubble up" the currently unassigned child hint
                            # directly subscripting this parent
                            # pseudo-superclass into the "empty placeholder"
                            # signified by this type parameter in this list of
                            # child hints transitively subscripting this child
                            # pseudo-superclass. <-- wat
                            elif hint_base_super_args_stack:
                                # print(f'Bubbling hint {hint_base_super_args_stack[-1]} into...')
                                # print(f'base {hint_base} typevar {hint_base_arg}!')
                                hint_base_arg_full_new = (  # pyright: ignore
                                hint_base_args_full[hint_base_arg_full_index]) = (
                                    hint_base_super_args_stack.pop())  # type: ignore[assignment]

                                # If the currently unassigned child hint
                                # directly subscripting this parent
                                # pseudo-superclass is itself a type parameter,
                                # record that this child pseudo-superclass is
                                # now known to be subscripted by at least one
                                # type parameter.
                                if is_hint_pep484612646_typearg_unpacked(
                                    hint_base_arg_full_new):  # pyright: ignore
                                    # print(f'Recording pseudo {hint_base} typevarred args {hint_base_arg_full}...')
                                    is_hint_base_arg_typearg = True
                                # Else, the currently unassigned child hint
                                # directly subscripting this parent
                                # pseudo-superclass is *NOT* itself a type
                                # parameter. In this case, record that this
                                # child hint has now been "bubbled up" into this
                                # type parameter for subsequent lookup.
                                #
                                # Note that bubbling up a type parameter into
                                # another type parameter would be entirely
                                # pointless. Type parameters are only
                                # meaningfully replaceable with concrete hints.
                                # Moreover, doing so here would erroneously map
                                # this type parameter to this other type
                                # parameter in the "typearg_to_hint" dictionary
                                # -- which would then inhibit this "if"
                                # conditional from subsequently bubbling up a
                                # concrete hint into this type parameter. <- omg
                                else:
                                    # print(f'Recording non-typevar {hint_base_arg_full} -> {hint_base_arg_full_new}...')
                                    typearg_to_hint[hint_base_arg_full] = (  # type: ignore[index]
                                        hint_base_arg_full_new)  # type: ignore[assignment]
                            # Else, all child hints directly subscripting this
                            # parent pseudo-superclass have already been
                            # "bubbled up" the class hierarchy. But this hint is
                            # a type parameter! Record that this child
                            # pseudo-superclass is now known to be subscripted
                            # by at least one type parameter.
                            else:
                                is_hint_base_arg_typearg = True
                            #print(f'Bubbled up generic {hint} arg {hint_args[hint_args_index_curr]}...')
                            #print(f'...into pseudo-superclass {hint_base} args {hint_base_args}!')
                        # Else, this hint is *NOT* a type parameter. In this
                        # case, preserve this hint and continue to the next.

                    # Parent list of the zero or more child hints transitively
                    # subscripting this parent pseudo-superclass of this
                    # pseudo-superclass.
                    hint_base_super_args_full = hint_base_super_data[  # pyright: ignore
                        _HINT_BASES_INDEX_ARGS_FULL]

                    # Append to this parent list this child list of all child
                    # hints transitively subscripting this pseudo-superclass.
                    hint_base_super_args_full.extend(hint_base_args_full)  # pyright: ignore
                    # print(f'Inspected generic {hint} pseudo-superclass {hint_base} args {hint_base_args}!')
                # Else, this pseudo-superclass is the passed root generic.
            # Else, this pseudo-superclass is transitively unsubscripted.

            # If searching for a target pseudo-superclass...
            if hint_base_target:
                # Unsubscripted generic underlying this possibly subscripted
                # pseudo-superclass generic. Strip this pseudo-superclass of
                # *ALL* child hints, allowing this unsubscripted current
                # pseudo-superclass to be compared against this
                # unsubscripted target pseudo-superclass.
                hint_base_type = get_hint_pep484585_generic_type(
                    hint=hint_base,  # type: ignore[arg-type]
                    exception_cls=exception_cls,
                    exception_prefix=exception_prefix,
                )

                # If this pseudo-superclass is the desired target...
                if hint_base_type == hint_base_target:
                    # If this target pseudo-superclass is no longer subscripted
                    # by any type parameters requiring subsequent replacement by
                    # concrete child hints, this target pseudo-superclass is
                    # *ONLY* subscripted by concrete child hints. In this case,
                    # immediately return a tuple of these hints.
                    #
                    # Note that:
                    # * This efficiently short-circuits this recursion in the
                    #   best case and is one of several reasons to prefer a
                    #   non-recursive algorithm. This algorithm was initially
                    #   implemented recursively (supposedly for simplicity);
                    #   doing so introduced significant unforeseen complications
                    #   by effectively preventing short-circuiting. After all, a
                    #   recursive algorithm *CANNOT* efficiently short-circuit
                    #   up out of a deeply nested recursive call stack --
                    #   without inefficiently raising an exception, which is so
                    #   inefficient as to defeat the point in most cases.
                    # * This recursion *CANNOT* be short-circuited in the worst
                    #   case, which occurs when the passed root generic is
                    #   directly subscripted by a concrete child hint that will
                    #   only be subsequently "bubbled up" into a type hint
                    #   transitively subscripting this target pseudo-superclass
                    #   *AFTER* this DFS recurses through the tree of all
                    #   pseudo-superclasses and back up into this generic. In
                    #   this worst case, the full dictionary of type parameter
                    #   mappings and thus the list of child hints transitively
                    #   subscripting this target pseudo-superclass is only
                    #   decidable *AFTER* this DFS fully recurses out.
                    #
                    # Consider this torturous hierarchy, in which bubbling up
                    # the child hint "complex" subscripting the root generic
                    # "ListFloat[complex]" into the child type parameter "U"
                    # subscripting the child pseudo-superclass "Generic[U]"
                    # requires recursing through the full tree:
                    #     >>> from typing import Generic
                    #     >>> class ListTU(list[T], Generic[U]): pass
                    #     >>> class ListFloat(ListTU[float]): pass
                    #     >>> get_hint_pep484585_generic_args_full(
                    #     ...     hint=ListFloat[complex],
                    #     ...     hint_base_target=Generic[U],
                    #     ... )
                    #     (complex,)
                    if not is_hint_base_arg_typearg:
                        return tuple(hint_base_args_full)
                    # Else, this target pseudo-superclass is still subscripted
                    # by one or more type parameters requiring subsequent
                    # replacement by concrete child hints. In this case,
                    # continue "bubbling up" child hints into these type
                    # variables. Doing so enables final logic below to replace
                    # these type parameters with these hints *AFTER* recursing
                    # through the full entirety of this DFS.

                    # List of zero or more child hints transitively subscripting
                    # this target pseudo-superclass.
                    hint_base_target_args_full = hint_base_args_full
                    # print(f'Found target {hint_base} args {hint_base_args_full}!')
                # Else, this pseudo-superclass is *NOT* equal to this target.
            # Else, *NO* target pseudo-superclass is being searched for.

    # ....................{ RETURN                         }....................
    # List of the one or more full child type hints transitively subscripting
    # the passed generic, to be coerced into a tuple and returned.
    hint_args_full: ListHints = None  # type: ignore[assignment]

    # If the caller passed a target pseudo-superclass...
    if hint_base_target:
        # If the DFS above failed to find the list of zero or more child hints
        # transitively subscripting this target, this DFS failed to find this
        # target. Since this implies this target is *NOT* a pseudo-superclass of
        # this generic, raise an exception.
        if hint_base_target_args_full is None:
            raise exception_cls(
                f'{exception_prefix}PEP 484 or 585 generic {repr(hint)} '
                f'pseudo-superclass target {repr(hint_base_target)} not found.'
            )
        # Else, this DFS found the list of zero or more child hints transitively
        # subscripting this target.

        # List of the zero or more child hints transitively subscripting this
        # target pseudo-superclass, to be coerced into a tuple and returned.
        hint_args_full = hint_base_target_args_full

        # For the 0-based index of each child hint transitively subscripting
        # this target pseudo-superclass and this hint...
        for hint_arg_full_index, hint_arg_full in enumerate(hint_args_full):
            # If this hint is a type parameter...
            if is_hint_pep484612646_typearg_unpacked(hint_arg_full):
                # Either:
                # * If a child hint directly subscripting a sibling
                #   pseudo-superclass of this target pseudo-superclass has
                #   already been "bubbled up" into this type parameter, preserve
                #   that bubbling by re-bubbling up the same child hint back
                #   into this # type parameter. <-- lol
                # * If *NO* child hint directly subscripting a sibling
                #   pseudo-superclass of this target pseudo-superclass has
                #   already been "bubbled up" into this type parameter, preserve
                #   this type parameter as is.
                hint_args_full[hint_arg_full_index] = typearg_to_hint.get(  # type: ignore[call-overload]
                    hint_arg_full, hint_arg_full)  # type: ignore[arg-type]
            # Else, this hint is *NOT* a type parameter.
    # Else, the caller did *NOT* pass a target pseudo-superclass.
    else:
        # If the metadata describing the passed generic is still its initial size,
        # then the above DFS failed to expand this metadata with the
        # "_HINT_BASES_INDEX_ARGS_FULL" index accessed below. In turn, this implies
        # that the above DFS failed to recurse down into the child
        # pseudo-superclasses of this generic. However, by definition, *ALL*
        # generics subclass one or more pseudo-superclasses. The above DFS should
        # have recursed down into those pseudo-superclasses. In this case, raise an
        # exception.
        #
        # Note that this should *NEVER* occur.
        if len(hint_root_data) == _HINT_BASE_DATA_LEN_LEAF:  # pragma: no cover
            raise exception_cls(
                f'{exception_prefix}PEP 484 or 585 generic {repr(hint)} '
                f'pseudo-superclasses not found.'
            )
        # Else, the above DFS expanded the metadata describing the passed generic
        # with the "_HINT_BASES_INDEX_ARGS_FULL" index accessed below.

        # List of the zero or more child hints transitively subscripting this
        # generic discovered by the above DFS.
        hint_args_full = hint_root_data[_HINT_BASES_INDEX_ARGS_FULL]  # type: ignore[assignment]

    # Return a tuple coerced from this list.
    return tuple(hint_args_full)


#FIXME: Ideally, this would be annotated as ": Hint". Mypy likes that but
#pyright hates that. This is why we can't have good things.
_HintBaseData = List[Union[Hint, ListHints, '_HintBaseData']]
'''
PEP-compliant type hint matching each **unvisited pseudo-superclass** (i.e.,
item of the ``hint_bases`` fixed list local to the
:func:`.get_hint_pep484585_generic_args_full` getter, describing each
pseudo-superclass of the generic passed to that getter that has yet to be
internally visited by the depth-first search (DFS) performed by that getter).
'''


_HintBasesData = List[_HintBaseData]
'''
PEP-compliant type hint matching the ``hint_bases`` fixed list local to the
:func:`.get_hint_pep484585_generic_args_full` getter.
'''


# Iterator yielding the next integer incrementation starting at 0, to be safely
# deleted *AFTER* defining the following 0-based indices via this iterator.
__hint_bases_counter = count(start=0, step=1)


_HINT_BASES_INDEX_HINT = next(__hint_bases_counter)
'''
0-based index into each **pseudo-superclass metadata** (i.e., list describing a
transitive pseudo-superclass of the :pep:`484`- or :pep:`585`-compliant generic
passed to the :func:`.get_hint_pep484585_generic_args_full` getter) stored in
the ``hint_bases`` list local to that getter, providing the currently visited
pseudo-superclass itself.
'''


_HINT_BASES_INDEX_PARENT = next(__hint_bases_counter)
'''
0-based index into each **pseudo-superclass metadata** (i.e., list describing a
transitive pseudo-superclass of the :pep:`484`- or :pep:`585`-compliant generic
passed to the :func:`.get_hint_pep484585_generic_args_full` getter) stored in
the ``hint_bases`` list local to that getter, providing the currently visited
pseudo-superclass' **parent pseudo-superclass metadata** (i.e., list describing
the direct parent pseudo-superclass of this current pseudo-superclass).
'''


_HINT_BASES_INDEX_ARGS_STACK = next(__hint_bases_counter)
'''
0-based index into each **pseudo-superclass metadata** (i.e., list describing a
transitive pseudo-superclass of the :pep:`484`- or :pep:`585`-compliant generic
passed to the :func:`.get_hint_pep484585_generic_args_full` getter) stored in
the ``hint_bases`` list local to that getter, providing the currently visited
pseudo-superclass' **direct child hint stack** (i.e., list of the zero or more
child hints directly subscripting this pseudo-superclass in reverse order,
embodying an efficiently poppable stack of these hints).

Note that a seemingly sensible alternative to this list would be to preserve
this as a tuple of child hints and additionally record:

* The currently indexed child hint of that tuple.
* The total number of child hints in that tuple.

Although trivial, doing so would necessitate additional space *and* time
consumption (e.g., to both assign and access this metadata). Since the average
Python statement is so slow, a one-liner producing a poppable stack minimizes
the number of Python statements and thus the computational cost.
'''


_HINT_BASE_DATA_LEN_LEAF = _HINT_BASES_INDEX_ARGS_STACK
'''
**Leaf pseudo-superclass metadata length** (i.e., total number of sub-items of
each item describing a **leaf pseudo-superclass** (i.e., that either is not
user-defined by a third-party package *or* is user-defined by a third-party
package but has yet to be identified as such) of the ``hint_bases`` list local
to the :func:`.get_hint_pep484585_generic_args_full` getter).
'''


_HINT_BASES_INDEX_ARGS_FULL = next(__hint_bases_counter)
'''
0-based index into each **pseudo-superclass metadata** (i.e., list describing a
transitive pseudo-superclass of the :pep:`484`- or :pep:`585`-compliant generic
passed to the :func:`.get_hint_pep484585_generic_args_full` getter) stored in
the ``hint_bases`` list local to that getter, providing the currently visited
pseudo-superclass' **transitive child hints** (i.e., list of the zero or more
child hints transitively subscripting this pseudo-superclass).
'''


# Delete the above counter for safety and sanity in equal measure.
del __hint_bases_counter

# ....................{ GETTERS ~ base                     }....................
def get_hint_pep484585_generic_base_extrinsic_sign_or_none(
    # Mandatory parameters.
    hint_base: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep484585Exception,
    exception_prefix: str = '',
) -> Optional[HintSign]:
    '''
    **Sign** (i.e., :data:`.HintSign` object) additionally identifying the
    passed **unerased pseudo-superclass** (i.e., PEP-compliant object originally
    declared as a transitive superclass prior to type erasure of some
    :pep:`484`- or :pep:`585`-compliant generic type) if this pseudo-superclass
    is extrinsically identifiable by a sign *or* :data:`None` otherwise (i.e.,
    if this pseudo-superclass is *not* extrinsically identifiable by a sign).

    This getter enables callers to distinguish extrinsic from intrinsic
    pseudo-superclasses. Notably, when passed:

    * An **intrinsic pseudo-superclass** (i.e., whose type-checking is
      intrinsically defined as a type hint such that all data required to
      type-check this pseudo-superclass is fully defined by this hint), this
      getter returns :data:`None`. This is the common case and, indeed, almost
      all cases. Examples include :pep:`484`- and :pep:`585`-compliant
      subscripted container type hints: e.g.,

      .. code-block:: pycon

         # The PEP 585-compliant "list[T]" pseudo-superclass is a valid hint
         # whose type-checking is intrinsic to this hint.
         >>> class GenericList[T](list[T]):
         ...     def generic_method(self, arg: T) -> T:
         ...         return arg

         # This pseudo-superclass has *NO* extrinsic sign.
         >>> get_hint_pep484585_generic_unsubbed_sign_extrinsic_or_none(
         ...     list[T])
         None

    * An **extrinsic pseudo-superclass (i.e., whose type-checking is
      extrinsically defined by this unsubscripted generic such that only the
      combination of this pseudo-superclass and this unsubscripted generic
      suffices to provide all data required to type-check this
      pseudo-superclass), the sign identifying this pseudo-superclass. Extrinsic
      pseudo-superclasses are *not* necessarily valid type hints, though some
      might be. Examples include:

      * **Generic named tuples** (i.e., types subclassing both the
        :pep:`484`-compliant :class:`typing.Generic` superclass *and* the
        :pep:`484`-compliant :class:`typing.NamedTuple` superclass): e.g.,

        .. code-block:: pycon

           # The PEP 484-compliant "NamedTuple" pseudo-superclass is *NOT* a
           # valid hint (due to being a function rather than a type) whose
           # type-checking is extrinsic to this hint.
           >>> from typing import Generic, NamedTuple
           >>> class GenericNamedTuple[T](NamedTuple, Generic[T]):
           ...     generic_item: T

           # This pseudo-superclass has an extrinsic sign.
           >>> get_hint_pep484585_generic_unsubbed_sign_extrinsic_or_none(
           ...     NamedTuple)
           HintSignNamedTuple

      * **Generic typed dictionaries** (i.e., types subclassing both the
        :pep:`484`-compliant :class:`typing.Generic` superclass *and* the
        :pep:`589`-compliant :class:`typing.TypedDict` superclass): e.g.,

        .. code-block:: pycon

           # The PEP 589-compliant "TypedDict" pseudo-superclass is a valid hint
           # (due to being a type) but whose type-checking is still extrinsic to
           # this hint.
           >>> from typing import Generic, TypedDict
           >>> class GenericTypedDict[T](TypedDict, Generic[T]):
           ...     generic_item: T

           # This pseudo-superclass has an extrinsic sign.
           >>> get_hint_pep484585_generic_unsubbed_sign_extrinsic_or_none(
           ...     TypedDict)
           HintSignTypedDict

    This getter is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    hint_base : Hint
        Pseudo-superclass to be inspected.

    Returns
    -------
    Optional[HintSign]
        Either:

        * If this pseudo-superclass is extrinsic, the sign uniquely identifying
          this pseudo-superclass.
        * If this pseudo-superclass is intrinsic, :data:`None`.
    '''

    # ..................{ SYNOPSIS                           }..................
    # For efficiency, this tester identifies the sign of this pseudo-superclass
    # with multiple phases performed in descending order of average time
    # complexity (i.e., expected efficiency).
    #
    # Note that we intentionally avoid validating this pseudo-superclass to be a
    # PEP-compliant type hint (e.g., by calling the die_unless_hint_pep()
    # validator). Why? Because some pseudo-superclasses are *NOT* PEP-compliant
    # type hints in the global sense; they're only PEP-compliant when
    # contextually listed as a pseudo-superclass (e.g., the "typing.NamedTuple"
    # function, which is a function and thus invalid as a type hint).

    # ..................{ PHASE ~ (class|callable)           }..................
    # This phase attempts to map from the fully-qualified name of this
    # pseudo-superclass if this pseudo-superclass is either a type or callable
    # to a sign identifying *ALL* extrinsic pseudo-superclasss that are
    # literally that type or callable.

    # If this pseudo-superclass is either a type or callable, this
    # pseudo-superclass necessarily defines the "__qualname__" dunder attribute
    # tested below. In this case...
    if isinstance(hint_base, CallableOrClassTypes):
        #FIXME: Is this actually the case? Do non-physical classes dynamically
        #defined at runtime actually define *BOTH* of these dunder attributes:
        #* "pseudo-superclass_type.__module__"?
        #* "pseudo-superclass_type.__qualname__"?

        # Dictionary mapping from the unqualified basenames of all extrinsic
        # pseudo-superclasses that are types or callables residing in the
        # package defining this hint that are uniquely identifiable by those
        # types or callables to their identifying signs if that package is
        # recognized *OR* the empty dictionary otherwise (i.e., if the package
        # defining this pseudo-superclass is unrecognized).
        hint_base_extrinsic_basename_to_sign = (
            HINT_MODULE_NAME_TO_HINT_BASE_EXTRINSIC_BASENAME_TO_SIGN.get(
                hint_base.__module__, FROZENDICT_EMPTY))

        # Sign identifying this pseudo-superclass if this pseudo-superclass is
        # identifiable by its basename *OR* "None" otherwise.
        hint_base_extrinsic_sign = hint_base_extrinsic_basename_to_sign.get(
            hint_base.__qualname__)
        # print(f'pseudo-superclass: {pseudo-superclass}')
        # print(f'pseudo-superclass_sign [by self]: {pseudo-superclass_sign}')
        # print(f'lookup table: {HINT_MODULE_NAME_TO_HINT_BASENAME_TO_SIGN}')

        # If this pseudo-superclass is identifiable by its basename, return
        # this sign.
        if hint_base_extrinsic_sign:
            return hint_base_extrinsic_sign
        # Else, this pseudo-superclass is *NOT* identifiable by its basename.
    # Else, this pseudo-superclass is *NOT* a class.

    # ..................{ RETURN                             }..................
    # This pseudo-superclass *MUST* be intrinsic, which is the common case.

    # Return "None" to inform the caller this pseudo-superclass is intrinsic.
    return None

# ....................{ GETTERS ~ bases                    }....................
def get_hint_pep484585_generic_bases_unerased(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep484585Exception,
    exception_prefix: str = '',
) -> tuple:
    '''
    Tuple of the one or more **unerased pseudo-superclasses** (i.e.,
    PEP-compliant objects originally listed as superclasses prior to their
    implicit type erasure under :pep:`560`) of the passed :pep:`484`- or
    :pep:`585`-compliant **generic** (i.e., class superficially subclassing at
    least one PEP-compliant type hint that is possibly *not* an actual class) if
    this object is a generic *or* raise an exception otherwise (i.e., if this
    object is *not* a generic).

    This getter is guaranteed to return a non-empty tuple. By definition, a
    generic is a type subclassing one or more generic superclasses.

    This getter is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Caveats
    -------
    **This getter should always be called in lieu of attempting to directly
    access the low-level** ``__orig_bases__`` **dunder instance variable.**
    Most PEP-compliant type hints fail to declare that variable, guaranteeing
    :class:`AttributeError` exceptions from all general-purpose logic
    attempting to directly access that variable. Thus this function, which
    "fills in the gaps" by implementing this oversight.

    **This getter returns tuples possibly containing a mixture of actual
    superclasses and pseudo-superclasses superficially masquerading as actual
    superclasses subscripted by one or more PEP-compliant child hints or type
    variables** (e.g., ``(typing.Iterable[T], typing.Sized[T])``). Indeed, most
    type hints used as superclasses produced by subscripting PEP-compliant type
    hint factories are *not* actually types but singleton objects devilishly
    masquerading as types. Most actual :mod:`typing` superclasses are private,
    fragile, and prone to alteration or even removal between Python versions.

    Motivation
    ----------
    :pep:`560` (i.e., "Core support for typing module and generic types)
    formalizes the ``__orig_bases__`` dunder attribute first informally
    introduced by the :mod:`typing` module's implementation of :pep:`484`.
    Naturally, :pep:`560` remains as unusable as :pep:`484` itself. Ideally,
    :pep:`560` would have generalized the core intention of preserving each
    original user-specified subclass tuple of superclasses as a full-blown
    ``__orig_mro__`` dunder attribute listing the original method resolution
    order (MRO) of that subclass had that tuple *not* been modified.

    Naturally, :pep:`560` did no such thing. The original MRO remains obfuscated
    and effectively inaccessible. While computing that MRO would technically be
    feasible, doing so would also be highly non-trivial, expensive, and fragile.
    Instead, this function retrieves *only* the tuple of :mod:`typing`-specific
    pseudo-superclasses that this object's class originally attempted (but
    failed) to subclass.

    You are probably now agitatedly cogitating to yourself in the darkness: "But
    @leycec: what do you mean :pep:`560`? Wasn't :pep:`560` released *after*
    :pep:`484`? Surely no public API defined by the Python stdlib would be so
    malicious as to silently alter the tuple of base classes listed by a
    user-defined subclass?"

    As we've established both above and elsewhere throughout the codebase,
    everything developed for :pep:`484` -- including :pep:`560`, which derives
    its entire raison d'etre from :pep:`484` -- are fundamentally insane. In
    this case, :pep:`484` is insane by subjecting parametrized :mod:`typing`
    types employed as base classes to "type erasure," because:

         ...it is common practice in languages with generics (e.g. Java,
         TypeScript).

    Since Java and TypeScript are both terrible languages, blindly
    recapitulating bad mistakes baked into such languages is an equally bad
    mistake. In this case, "type erasure" means that the :mod:`typing` module
    *intentionally* destroys runtime type information for nebulous and largely
    unjustifiable reasons (i.e., Big Daddy Java and TypeScript do it, so it
    must be unquestionably good).

    Specifically, the :mod:`typing` module intentionally munges :mod:`typing`
    types listed as base classes in user-defined subclasses as follows:

    * All base classes whose origin is a builtin container (e.g.,
      ``typing.List[T]``) are reduced to that container (e.g., :class:`list`).
    * All base classes derived from an abstract base class declared by the
      :mod:`collections.abc` subpackage (e.g., ``typing.Iterable[T]``) are
      reduced to that abstract base class (e.g., ``collections.abc.Iterable``).
    * All surviving base classes that are parametrized (e.g.,
      ``typing.Generic[S, T]``) are stripped of that parametrization (e.g.,
      :class:`typing.Generic`).

    Since there exists no counterpart to the :class:`typing.Generic` superclass,
    the :mod:`typing` module preserves that superclass in unparametrized form.
    Naturally, this is useless, as an unparametrized :class:`typing.Generic`
    superclass conveys no meaningful type information. All other superclasses
    are reduced to their non-:mod:`typing` counterparts: e.g.,

        .. code-block:: pycon

        >>> from typing import TypeVar, Generic, Iterable, List
        >>> T = TypeVar('T')
        >>> class UserDefinedGeneric(List[T], Iterable[T], Generic[T]): pass
        # This is type erasure.
        >>> UserDefinedGeneric.__mro__
        (list, collections.abc.Iterable, Generic)
        # This is type preservation -- except the original MRO is discarded.
        # So, it's not preservation; it's reduction! We take what we can get.
        >>> UserDefinedGeneric.__orig_bases__
        (typing.List[T], typing.Iterable[T], typing.Generic[T])
        # Guess which we prefer?

    So, we prefer the generally useful ``__orig_bases__`` dunder tuple over the
    generally useless ``__mro__`` dunder tuple. Note, however, that the latter
    *is* still occasionally useful and thus occasionally returned by this
    getter. For inexplicable reasons, **single-inherited protocols** (i.e.,
    classes directly subclassing *only* the :pep:`544`-compliant
    :attr:`typing.Protocol` abstract base class (ABC)) are *not* subject to type
    erasure and thus constitute a notable exception to this heuristic:

        .. code-block:: pycon

        >>> from typing import Protocol
        >>> class UserDefinedProtocol(Protocol): pass
        >>> UserDefinedProtocol.__mro__
        (__main__.UserDefinedProtocol, typing.Protocol, typing.Generic, object)
        >>> UserDefinedProtocol.__orig_bases__
        AttributeError: type object 'UserDefinedProtocol' has no attribute
        '__orig_bases__'

    Welcome to :mod:`typing` hell, where even :mod:`typing` types lie broken and
    misshapen on the killing floor of overzealous theory-crafting purists.

    Parameters
    ----------
    hint : Hint
        Generic type hint to be inspected.
    exception_cls : TypeException
        Type of exception to be raised. Defaults to
        :exc:`BeartypeDecorHintPep484585Exception`.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    tuple
        Tuple of the one or more unerased pseudo-superclasses of this generic.

    Raises
    ------
    exception_cls
        If this hint is either:

        * Neither a :pep:`484`- nor :pep:`585`-compliant generic.
        * A :pep:`484`- or :pep:`585`-compliant generic subclassing *no*
          pseudo-superclasses.

    Examples
    --------
    .. code-block:: pycon

       >>> from beartype.typing import Container, Iterable, TypeVar
       >>> from beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget import (
       ...     get_hint_pep484585_generic_bases_unerased)

       >>> T = TypeVar('T')
       >>> class MuhIterable(Iterable[T], Container[T]): pass

       >>> get_hint_pep585_generic_bases_unerased(MuhIterable)
       (typing.Iterable[~T], typing.Container[~T])

       >>> MuhIterable.__mro__
       (MuhIterable,
        collections.abc.Iterable,
        collections.abc.Container,
        typing.Generic,
        object)
    '''

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._util.hint.pep.proposal.pep484585.generic.pep484585gentest import (
        is_hint_pep484585_generic_user)

    # ....................{ LOCALS                         }....................
    # Tuple of either...
    #
    # Note this implicitly raises a "BeartypeDecorHintPepException" if this
    # object is *NOT* a PEP-compliant generic. Ergo, we need not explicitly
    # validate that above.
    hint_pep_generic_bases_unerased = (
        # If this is a PEP 585-compliant generic, all unerased
        # pseudo-superclasses of this PEP 585-compliant generic.
        #
        # Note that this unmemoized getter accepts keyword arguments.
        get_hint_pep585_generic_bases_unerased(
            hint=hint,
            exception_cls=exception_cls,
            exception_prefix=exception_prefix,
        )
        if is_hint_pep585_generic(hint) else
        # Else, this *MUST* be a PEP 484-compliant generic. In this case, all
        # unerased pseudo-superclasses of this PEP 484-compliant generic.
        #
        # Note that this memoized getter prohibits keyword arguments.
        get_hint_pep484_generic_bases_unerased(
            hint, exception_cls, exception_prefix)
    )

    # ....................{ RETURN                         }....................
    # If this generic....
    if (
        # Subclasses no pseudo-superclasses *AND*...
        not hint_pep_generic_bases_unerased and
        # Is user-defined by a third-party downstream codebase.
        is_hint_pep484585_generic_user(hint)
    ):
        # Raise an exception. By definition, *ALL* user-defined generics should
        # subclass at least one pseudo-superclass. Note that this constraint:
        # * Does *NOT* apply to standard generics defined by either:
        #   * The standard "typing" module (e.g., "typing.Generic[S, T]").
        #   * The Python interpreter itself (e.g., "list[T]").
        #   Why? Because these generics are the root superclasses that other
        #   user-defined generics subclass. Clearly, they have no
        #   pseudo-superclasses.
        # * Should have already been guaranteed on our behalf by:
        #   * If this generic is PEP 484-compliant, the standard "typing" module.
        #   * If this generic is PEP 585-compliant, the Python interpreter itself.
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')
        raise exception_cls(
            f'{exception_prefix}PEP 484 or 585 generic {repr(hint)} '
            f'subclasses no superclasses.'
        )
    # Else, this generic subclasses one or more pseudo-superclasses.

    # Return this tuple of these pseudo-superclasses.
    return hint_pep_generic_bases_unerased


def get_hint_pep484585_generic_base_in_module_first(
    # Mandatory parameters.
    hint: Hint,
    module_names: FrozenSetStrs,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep484585Exception,
    exception_prefix: str = '',
) -> type:
    '''
    Iteratively find and return the first **unerased superclass** (i.e.,
    unerased pseudo-superclass that is an actual superclass) transitively
    defined under the third-party package(s) or module(s) with the passed
    name(s) subclassed by the unsubscripted generic type underlying the passed
    :pep:`484`- or :pep:`585`-compliant **generic** (i.e., object that may *not*
    actually be a class despite subclassing at least one PEP-compliant type hint
    that also may *not* actually be a class).

    This finder is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator). Although doing so *would* dramatically
    improve the efficiency of this getter, doing so:

    * Would require all passed parameters be passed positionally, which becomes
      rather cumbersome given the number of requisite parameters.
    * Would require callers to pass a placeholder ``exception_prefix`` rather
      than the true ``exception_prefix``, which is typically context-dependent
      and thus *not* readily memoizable. Although feasible, doing so becomes
      rather cumbersome... yet again.
    * Is (currently) unnecessary, as all callers of this function are themselves
      already memoized.

    Motivation
    ----------
    This finder is typically called to reduce **descriptive generics** (i.e.,
    generics defined in third-party packages intended to be used *only* as
    descriptive type hints rather than actually instantiated as objects as most
    generics are) to the isinstanceable classes those generics describe.
    Although the mere existence of descriptive generics should be considered to
    be a semantic (if not syntactic) violation of :pep:`484`, the widespread
    proliferation of descriptive generics leaves :mod:`beartype` with little
    choice but to grin wanly and bear the pain they subject us to. As example,
    this finder is currently called elsewhere to:

    * Reduce Pandera type hints (e.g., `pandera.typing.DataFrame[...]`) to the
      Pandas types they describe (e.g., `pandas.DataFrame`).
    * Reduce NumPy type hints (e.g., `numpy.typing.NDArray[...]`) to the
      NumPy types they describe (e.g., `numpy.ndarray`).

    See examples below for further discussion.

    Parameters
    ----------
    hint : Hint
        Generic type hint to be inspected.
    module_names : frozenset[str]
        Frozen set of the fully-qualified names of all third-party packages and
        modules to find the first class in this generic type hint of.
    exception_cls : TypeException
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintPep484585Exception`.
    exception_prefix : str, optional
        Human-readable substring prefixing the representation of this object in
        the exception message. Defaults to the empty string.

    Returns
    -------
    type
        First unerased superclass transitively defined under this package or
        module subclassed by the unsubscripted generic type underlying this
        generic type hint.

    Examples
    --------
    .. code-block:: python

       >>> from beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget import (
       ...     get_hint_pep484585_generic_base_in_module_first)

       # Reduce a Pandera type hint to the Pandas type it describes.
       >>> from pandera import DataFrameModel
       >>> from pandera.typing import DataFrame
       >>> class MuhModel(DataFrameModel): pass
       >>> get_hint_pep484585_generic_base_in_module_first(
       ...     hint=DataFrame[MuhModel], module_name='pandas', ...)
       <class 'pandas.DataFrame'>
    '''
    assert isinstance(module_names, frozenset), (
        f'{repr(module_names)} not frozen set.')
    assert all(
        isinstance(module_name, str) for module_name in module_names), (
        f'{repr(module_names)} not frozen set of strings.')

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._util.module.utilmodget import get_object_module_name_or_none

    # ....................{ LOCALS                         }....................
    # Either:
    # * If this generic is unsubscripted, this unsubscripted generic type as is.
    # * If this generic is subscripted, the unsubscripted generic type
    #   underlying this subscripted generic (e.g., the type
    #   "pandera.typing.pandas.DataFrame" given the type hint
    #   "pandera.typing.DataFrame[...]").
    hint_type = get_hint_pep484585_generic_type(
        hint=hint,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # Tuple of the one or more unerased pseudo-superclasses which this
    # unsubscripted generic type originally subclassed prior to type erasure.
    #
    # Note that we could also inspect the method-resolution order (MRO) of this
    # type via the "hint.__mro__" dunder tuple, but that doing so would only
    # needlessly reduce the efficiency of the following iteration by
    # substantially increasing the number of iterations required to find the
    # desired superclass and thus the worst-case complexity of that iteration.
    hint_type_bases = get_hint_pep484585_generic_bases_unerased(
        hint=hint,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # ....................{ SEARCH                         }....................
    # For each unerased pseudo-superclass of this unsubscripted generic type...
    for hint_base in hint_type_bases:
        # If this pseudo-superclass is *NOT* an actual superclass, silently
        # ignore this non-superclass and continue to the next pseudo-superclass.
        if not isinstance(hint_base, type):
            continue
        # Else, this pseudo-superclass is an actual superclass.

        # Fully-qualified name of the module declaring this superclass if any
        # *OR* "None" otherwise (i.e., if this type is only defined in-memory).
        hint_base_module_name = get_object_module_name_or_none(hint_base)

        # If this module exists...
        if hint_base_module_name:
            # If this module is one of the passed modules, return this
            # superclass as is.
            if hint_base_module_name in module_names:
                # print(f'Found generic {repr(hint)} type {repr(hint_type)} "{module_name}" superclass {repr(hint_base)}!')
                return hint_base
            # Else, this module is *NOT* one of the passed modules. However,
            # this module could still be a transitive submodule of one of the
            # passed packages.

            # Fully-qualified name of the root package transitively defining
            # the submodule declaring this superclass (e.g., "polars" when
            # "hint_base_module_name" is "polars.dataframe").
            #
            # Note this has been profiled to be the fastest one-liner parsing
            # the first "."-suffixed substring from a "."-delimited string.
            hint_base_package_name = hint_base_module_name.partition('.')[0]

            # If this package is one of the passed packages, return this
            # superclass as is.
            if hint_base_package_name in module_names:
                # print(f'Found generic {repr(hint)} type {repr(hint_type)} "{module_name}" superclass {repr(hint_base)}!')
                return hint_base
            # Else, this package is *NOT* one of the passed packages.
        # Else, this module does *NOT* exist.
        #
        # In any case, silently continue to the next superclass.
    # Else, *NO* superclass of this generic resides in the desired module.

    # ....................{ RAISE                          }....................
    # Human-readable double-quoted disjunction of all passed module names (e.g.,
    # '"ibix", "pandas", or "polars"').
    module_names_quoted = join_delimited_disjunction(
        strs=module_names, is_double_quoted=True)

    # Raise an exception of the passed type.
    raise exception_cls(
        f'{exception_prefix}PEP 484 or 585 generic {repr(hint)} '
        f'type {repr(hint_type)} subclasses no {module_names_quoted} type '
        f'(i.e., type with module name prefixed by {module_names_quoted} not '
        f'found in method resolution order (MRO) {repr(hint_type.__mro__)}).'
    )

# ....................{ GETTERS ~ type                     }....................
#FIXME: Unit test us up, please.
def get_hint_pep484585_generic_type_isinstanceable(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep484585Exception,
    exception_prefix: str = '',
) -> type:
    '''
    Either the passed :pep:`484`- or :pep:`585`-compliant **isinstanceable
    generic** (i.e., class superficially subclassing at least one PEP-compliant
    type hint that is possibly *not* an actual class such that this class may be
    passed as the second parameter to the :func:`isinstance` builtin) if
    **unsubscripted** (i.e., indexed by *no* arguments or type parameters), the
    unsubscripted isinstanceable generic underlying this generic if
    **subscripted** (i.e., indexed by one or more child type hints and/or type
    parameters), *or* raise an exception otherwise (i.e., if this hint is *not*
    a generic).

    Although most generics are isinstanceable, some are not. This getter enables
    callers to transparently support the subset of generics that are *not*
    implicitly isinstanceable.

    This getter is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        Generic type hint to be inspected.
    exception_cls : TypeException, default: BeartypeDecorHintPep484585Exception
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintPep484585Exception`.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    type
        Isinstanceable class originating this generic.

    Raises
    ------
    exception_cls
        If this hint is *not* a generic.

    See Also
    --------
    :func:`.get_hint_pep484585_generic_type`
        Further details.
    '''

    # This hint if this hint is an unsubscripted generic, the unsubscripted
    # generic underlying this hint if this hint is a subscripted generic, *OR*
    # raise an exception if this hint is not a generic.
    hint_generic_type_isinstanceable = get_hint_pep484585_generic_type(hint)

    # If the metaclass of this generic bound the __call__() dunder method to a
    # type, *ALL* user-defined instances of this generic are necessarily
    # instances of that type rather than instances of this generic. In this
    # case, assume that type to be isinstanceable. Certainly, this generic
    # itself is unlikely to be isinstanceable. Why? Because of the following
    # PEP-compliant edge cases triggering this condition:
    #
    # * User-defined subclasses inheriting both the PEP 484-compliant
    #   "typing.Generic" superclass *AND* the PEP 589-compliant
    #   "typing.TypedDict" superclass, whose metaclass is the private
    #   "typing._TypedDictMeta" metaclass, which:
    #   * Explicitly prevents these user-defined subclasses from being passed as
    #     the second parameters to the isinstance() and issubclass() builtins.
    #   * Implements the typing._TypedDictMeta.__new__() constructor responsible
    #     for dynamically creating and returning these user-defined subclasses
    #     to forcefully monkey-patch the __call__() dunder method of these
    #     subclasses to refer to the builtin "dict" type. By default, the
    #     __call__() dunder method is bound to the type.__call__() method.
    #     Replacing that method with "dict" ensures that *ALL*
    #     "typing.TypedDict" instances are actually "dict" rather than
    #     "typing.TypedDict" instances.
    if isinstance(hint_generic_type_isinstanceable.__call__, type):  # pyright: ignore
        hint_generic_type_isinstanceable = hint.__call__  # pyright: ignore
        # print(f'generic {hint} hint.__call__ type detected: {hint_isinstanceable}')
    # Else, the metaclass of this generic did *NOT* bind the __call__() dunder
    # method to a type.

    # Return this isinstanceable class.
    return hint_generic_type_isinstanceable


#FIXME: Unit test us up, please.
def get_hint_pep484585_generic_type(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep484585Exception,
    exception_prefix: str = '',
) -> type:
    '''
    Either the passed :pep:`484`- or :pep:`585`-compliant **generic** (i.e.,
    class superficially subclassing at least one PEP-compliant type hint that is
    possibly *not* an actual class) if **unsubscripted** (i.e., indexed by *no*
    arguments or type parameters), the unsubscripted generic underlying this
    generic if **subscripted** (i.e., indexed by one or more child type hints
    and/or type parameters), *or* raise an exception otherwise (i.e., if this
    hint is *not* a generic).

    Specifically, this getter returns (in order):

    * If this hint originates from an **origin type** (i.e., isinstanceable
      class such that *all* objects satisfying this hint are instances of that
      class), this type regardless of whether this hint is already a class.
    * Else if this hint is already a class, this hint as is.
    * Else, raise an exception.

    This getter is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Caveats
    -------
    **This getter returns false positives in edge cases.** That is, this getter
    returns non-:data:`None` values for both generics and non-generics --
    notably, non-generics defining the ``__origin__`` dunder attribute to an
    isinstanceable class. Callers *must* perform subsequent tests to distinguish
    these two cases.

    Parameters
    ----------
    hint : Hint
        Generic type hint to be inspected.
    exception_cls : TypeException, default: BeartypeDecorHintPep484585Exception
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintPep484585Exception`.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    type
        Class originating this generic.

    Raises
    ------
    exception_cls
        If this hint is *not* a generic.

    See Also
    --------
    :func:`.get_hint_pep484585_generic_type_or_none`
        Further details.
    '''

    # This hint if this hint is an unsubscripted generic, the unsubscripted
    # generic underlying this hint if this hint is a subscripted generic, *OR*
    # "None" if this hint is not a generic.
    hint_generic_type = get_hint_pep484585_generic_type_or_none(hint)

    # If this hint is *NOT* a generic, raise an exception.
    if hint_generic_type is None:
        raise exception_cls(
            f'{exception_prefix}PEP 484 or 585 generic {repr(hint)} '
            f'not generic (i.e., originates from no isinstanceable class).'
        )
    # Else, this hint is a generic.

    # Return this class.
    return hint_generic_type


def get_hint_pep484585_generic_type_or_none(hint: Hint) -> Optional[type]:
    '''
    Either the passed :pep:`484`- or :pep:`585`-compliant **generic** (i.e.,
    class superficially subclassing at least one PEP-compliant type hint that is
    possibly *not* an actual class) if **unsubscripted** (i.e., indexed by *no*
    arguments or type parameters), the unsubscripted generic underlying this
    generic if **subscripted** (i.e., indexed by one or more child type hints
    and/or type parameters), *or* :data:`None` otherwise (i.e., if this hint is
    *not* a generic).

    Specifically, this getter returns (in order):

    * If this hint originates from an **origin type** (i.e., isinstanceable
      class such that *all* objects satisfying this hint are instances of that
      class), this type regardless of whether this hint is already a class.
    * Else if this hint is already a class, this hint as is.
    * Else, :data:`None`.

    This getter is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Caveats
    -------
    **This getter returns false positives in edge cases.** That is, this getter
    returns non-:data:`None`` values for both generics and non-generics --
    notably, non-generics defining the ``__origin__`` dunder attribute to an
    isinstanceable class. Callers *must* perform subsequent tests to distinguish
    these two cases.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.

    Returns
    -------
    Optional[type]
        Either:

        * If this hint is a generic, the class originating this generic.
        * Else, :data:`None`.

    See Also
    --------
    :func:`get_hint_pep_origin_or_none`
        Further details.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import get_hint_pep_origin_or_none

    # Arbitrary object originating this hint if any *OR* "None" otherwise.
    hint_origin = get_hint_pep_origin_or_none(hint)
    # print(f'{repr(hint)} hint_origin: {repr(hint_origin)}')

    # If this origin is a type, this is the origin type originating this hint.
    # In this case, return this type.
    if isinstance(hint_origin, type):
        return hint_origin
    # Else, this origin is *NOT* a type.
    #
    # Else if this hint is already a type, this type is effectively already its
    # origin type. In this case, return this type as is.
    elif isinstance(hint, type):
        return hint
    # Else, this hint is *NOT* a type. In this case, this hint originates from
    # *NO* origin type.

    # Return the "None" singleton.
    return None
