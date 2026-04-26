#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`484`- or :pep:`604`-compliant **union type-checking code
factories** (i.e., low-level callables dynamically generating pure-Python code
snippets type-checking arbitrary objects against union type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: Validate that PEP 695-compliant type aliases aliasing recursive unions
#behave as expected: e.g.,
#    type recursive_union = int | recursive_union
#FIXME: Likewise, note that our current *EXTREMELY* non-trivial handling of
#"hint_overrides"-based recursive unions below could probably benefit from being
#refactored into the same approach used to handle PEP 695-based recursive
#unions. The approach below is wild -- and not the good kind of "wild," either.

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    List,
    Tuple,
)
from beartype._check.metadata.hint.hintsmeta import HintsMeta
from beartype._check.metadata.hint.hintsane import (
    HINT_IGNORABLE,
    HintSane,
    DictHintSaneToAny,
    ListHintSane,
    TupleHintSane,
)
from beartype._data.code.datacodelen import LINE_RSTRIP_INDEX_OR
from beartype._data.code.pep.datacodepep484604 import (
    CODE_PEP484604_UNION_CHILD_PEP_format,
    CODE_PEP484604_UNION_CHILD_NONPEP_format,
    CODE_PEP484604_UNION_PREFIX,
    CODE_PEP484604_UNION_SUFFIX,
)
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import DictTypeToAny
from beartype._data.hint.sign.datahintsignset import HINT_SIGNS_UNION
from beartype._util.cache.pool.utilcachepoolinstance import (
    acquire_instance,
    release_instance,
)
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.hint.pep.utilpepget import get_hint_pep_args
from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none
from beartype._util.hint.pep.utilpeptest import is_hint_pep
from beartype._data.kind.datakindiota import SENTINEL

# ....................{ FACTORIES                          }....................
def make_hint_pep484604_check_expr(hints_meta: HintsMeta) -> None:
    '''
    Either a Python code snippet type-checking the current pith against the
    passed :pep:`484`- or :pep:`604`-compliant union type hint if this union is
    **unignorable** (i.e., subscripted by *no* ignorable child type hints) *or*
    :data:`None` otherwise (i.e., if this union is ignorable).

    This factory is intentionally *not* memoized (e.g., by the
    :func:`.callable_cached` decorator), due to accepting **context-sensitive
    parameters** (i.e., whose values contextually depend on context unique to
    the code being generated for the currently decorated callable) such as
    ``pith_curr_assign_expr``.

    Caveats
    -------
    Unions are non-physical abstractions of physical types and thus *not*
    themselves subject to type-checking; only the subscripted arguments of
    unions are type-checked. This differs from :mod:`typing` pseudo-containers
    like ``List[int]``, in which both the parent :obj:`typing.List` and child
    :class:`int` types represent physical types to be type-checked. Ergo, unions
    themselves impose no narrowing of the current pith expression and thus
    *cannot* by definition benefit from assignment expressions. This differs
    from :mod:`typing` pseudo-containers, which narrow the current pith
    expression and thus do benefit from assignment expressions.

    Parameters
    ----------
    hints_meta : HintsMeta
        Stack of metadata describing all visitable hints currently discovered by
        this breadth-first search (BFS).
    '''
    assert isinstance(hints_meta, HintsMeta), (
        f'{repr(hints_meta)} not "HintsMeta" object.')

    # ....................{ LOCALS                         }....................
    # Flattened tuple of two or more child hints subscripting this parent union
    # such that *ALL* nested child hints subscripting child unions are expanded
    # directly into this tuple, thus non-destructively eliminating child unions.
    #
    # Note that this getter is memoized and thus requires:
    # * Positional parameters.
    # * "hint_meta" instance variables to be explicitly passed rather than the
    #   "hint_meta" object in entirety. Why? Memoization, of course. Passing the
    #   "hint_meta" object in entirety would effectively inhibit the memoization
    #   of this getter, which entirely defeats the point.
    hint_childs_sane = _get_hint_pep484604_union_args_flattened(hints_meta)
    # print(f'Unflattened union {repr(hints_meta.hint_curr_meta.hint)}...')
    # print(f'...child hints {repr(hint_childs_sane)}.')

    # Dictionary whose keys comprise the set of all PEP-noncompliant child hints
    # subscripting this union and whose values are ignorable. Whereas sets fail
    # to preserve insertion order, dictionaries preserve insertion order. While
    # a set would be preferable for simplicity, the fact that sets are currently
    # unordered leaves us no choice but to abuse dictionaries.
    #
    # The order of union child hints is insignificant in the common case but
    # *NOT* the worst case, where order is significant. Examples include:
    # * A union over classes whose metaclasses define custom type-checking by
    #   overriding the __instancecheck__() dunder method. Callers might
    #   intentionally order those classes in that union to maximize
    #   type-checking efficiency. How? In descending order of the efficiency of
    #   those __instancecheck__() implementations. The most efficiently
    #   type-checkable classes would be listed first in that union; the least
    #   efficiently type-checkable classes, last.
    # * A union over classes registered as pseudo-subclasses with the
    #   collections.abc.ABCMeta.register() method. Callers might intentionally
    #   order those classes in that union to prevent type-checking code
    #   dynamically generated by beartype from raising unexpected exceptions in
    #   the event that those classes fail to fully satisfy the API of the ABC
    #   they were registered with. See also this issue:
    #       https://github.com/beartype/beartype/issues/499#issuecomment-2683400721
    #
    # Since PEP-compliant and -noncompliant child hints require fundamentally
    # different forms of type-checking, prefiltering child hints into these
    # dictionaries *BEFORE* generating code type-checking these child hints
    # improves both efficiency and maintainability.
    hint_childs_nonpep: DictTypeToAny = acquire_instance(dict)

    # Dictionary whose keys comprise the set of all PEP-compliant child hints
    # subscripting this union and whose values are ignorable. See above.
    hint_childs_sane_pep: DictHintSaneToAny = acquire_instance(dict)

    # ....................{ FILTER                         }....................
    #FIXME: Optimize by refactoring into a "while" loop. Naturally, profile that
    #doing so actually *IS* an optimization before doing so. *sigh*

    # For each child hint subscripting this union...
    for hint_child_sane in hint_childs_sane:
        #FIXME: Uncomment as desired for debugging. This test is currently a bit
        #too costly to warrant uncommenting.
        # Assert that this child hint is *NOT* shallowly ignorable. Why? Because
        # any union containing one or more shallowly ignorable child hints is
        # deeply ignorable and should thus have already been ignored after a
        # call to the is_hint_ignorable() tester passed this union on handling
        # the parent hint of this union.
        # assert (
        #     repr(hint_curr) not in HINTS_REPR_IGNORABLE_SHALLOW), (
        #     f'{hint_curr_exception_prefix} {repr(hint_curr)} child '
        #     f'{repr(hint_child)} ignorable but not ignored.')

        # Child hint encapsulated by this metadata.
        hint_child = hint_child_sane.hint

        #FIXME: *WOOOOOOOOOOOOOAH.* Waitjustaminute. Not all PEP-compliant type
        #hints are hashable! Seriously. Here's one obvious example:
        #    Annotated[object, []]
        #
        #There's absolutely *NO* way that's hashable. We... kinda messed up
        #here, folks. Thankfully, this edge case has yet to actually hit anyone.
        #This suggests that nearly all type hints of real-world interest are
        #hashable. Still, that's a pretty bad assumption. Let's generalize this
        #with "try" logic resembling:
        #    if is_hint_pep(hint_child):
        #        try:
        #            hint_childs_sane_pep[hint_child_sane] = None
        #        except TypeError:
        #            hint_childs_sane_pep_unhashable.append(hint_child_sane)
        #    else:
        #        hint_childs_nonpep[hint_child] = None  # type: ignore[index]
        #
        #As the above logic suggests, this edge case *ONLY* applies to
        #PEP-compliant type hints. All PEP-noncompliant type hints are
        #isinstanceable types -- which, by definition, are all hashable. \o/
        #
        #Naturally, we'll then need to:
        #* Rename "hint_childs_sane_pep" to "hint_childs_sane_pep_hashable".
        #* Define "hint_childs_sane_pep_unhashable" as a list above.
        #* Handle "hint_childs_sane_pep_unhashable" below. The most reliable way
        #  to do that is to:
        #  * First define a new tuple resembling:
        #      hint_childs_sane_pep_list = (
        #          list(hint_childs_sane_pep.keys()) +
        #          hint_childs_sane_pep_unhashable
        #      )
        #  * Then iterate over "hint_childs_sane_pep_list" rather than
        #    "hint_childs_sane_pep.keys()" below.

        # If this child hint is PEP-compliant, filter this child hint *AND* all
        # associated metadata (if any) into this dictionary of PEP-compliant
        # child hints.
        #
        # Note that this PEP-compliant child hint *CANNOT* also be filtered into
        # the dictionary of PEP-noncompliant child hints, even if this child
        # hint originates from a non-"typing" type (e.g., "List[int]" from
        # "list"). Why? Because that would then induce false positives when the
        # current pith shallowly satisfies this non-"typing" type but does *NOT*
        # deeply satisfy this child hint.
        if is_hint_pep(hint_child):
            hint_childs_sane_pep[hint_child_sane] = None
        # Else, this child hint is PEP-noncompliant. In this case, filter this
        # child hint into this dictionary of PEP-noncompliant child hints. Since
        # PEP-noncompliant hints are by definition associated with *NO*
        # meaningful metadata, silently ignore this metadata.
        else:
            hint_childs_nonpep[hint_child] = None  # type: ignore[index]

    # ....................{ FORMAT ~ non-pep               }....................
    # Initialize the code type-checking the current pith against these arguments
    # to the substring prefixing all such code.
    hints_meta.func_curr_code = CODE_PEP484604_UNION_PREFIX

    # If this union is subscripted by one or more PEP-noncompliant child hints,
    # generate and append efficient code type-checking these child hints
    # *BEFORE* less efficient code type-checking any PEP-compliant child hints
    # subscripting this union.
    if hint_childs_nonpep:
        hints_meta.func_curr_code += CODE_PEP484604_UNION_CHILD_NONPEP_format(
            # Python expression yielding the value of the current pith.
            # Specifically...
            pith_curr_expr=(
                # If this union is also subscripted by one or more
                # PEP-compliant child hints, prefer the expression assigning
                # this value to a local variable efficiently reused by
                # subsequent code generated for those PEP-compliant child
                # hints.
                hints_meta.pith_curr_assign_expr
                if hint_childs_sane_pep else
                # Else, this union is subscripted by *NO* PEP-compliant
                # child hints. Since this is the first and only test
                # generated for this union, prefer the expression yielding
                # the value of the current pith *WITHOUT* assigning this
                # value to a local variable, which would needlessly go
                # unused.
                hints_meta.pith_curr_expr
            ),
            # Python expression evaluating to a tuple of these arguments.
            #
            # Note that we would ideally avoid coercing this set into a
            # tuple when this set only contains one type by passing that
            # type directly to the _add_func_wrapper_local_type() function.
            # Sadly, the "set" class defines no convenient or efficient
            # means of retrieving the only item of a 1-set. Indeed, the most
            # efficient means of doing so is to iterate over that set and
            # immediately halt iteration:
            #     for first_item in muh_set: break
            #
            # While we *COULD* technically leverage that approach here,
            # doing so would also mandate adding multiple intermediate
            # tests, mitigating any performance gains. Ultimately, we avoid
            # doing so by falling back to the usual approach. See also this
            # relevant self-StackOverflow post:
            #       https://stackoverflow.com/a/40054478/2809027
            hint_curr_expr=hints_meta.add_func_scope_type_or_types(
                hint_childs_nonpep.keys()),
        )

    # ....................{ FORMAT ~ pep                   }....................
    # For the 0-based index of each PEP-compliant child hint of this union *AND*
    # that hint...
    for hint_child_sane_pep_index, hint_child_sane_pep in enumerate(
        hint_childs_sane_pep.keys()):
        # print(f'Enqueing union {hints_meta.hint_curr_meta.hint_sane.hint}...')
        # print(f'...PEP-compliant child {hint_child_sane_pep}.')

        # Code deeply type-checking this child hint.
        hints_meta.func_curr_code += CODE_PEP484604_UNION_CHILD_PEP_format(
            # Expression yielding the value of this pith.
            hint_child_placeholder=hints_meta.enqueue_hint_child_sane(
                hint_sane=hint_child_sane_pep,
                pith_expr=(
                    # If either...
                    #
                    # Then prefer the expression efficiently reusing the value
                    # previously assigned to a local variable by either the
                    # above conditional or prior iteration of the current
                    # conditional.
                    hints_meta.pith_curr_var_name
                    if (
                        # This union is also subscripted by one or more
                        # PEP-noncompliant child hints *OR*...
                        hint_childs_nonpep or
                        # This is any PEP-compliant child hint *EXCEPT* the
                        # first...
                        hint_child_sane_pep_index
                    ) else
                    # Then this union is not subscripted by any PEP-noncompliant
                    # child hints *AND* this is the first PEP-compliant child
                    # hint. In this case, preface this code with an expression
                    # assigning this value to a local variable efficiently
                    # reused by code generated by subsequent iteration.
                    #
                    # Note this child hint is guaranteed to be followed by at
                    # least one more child hint. Why? Because the "typing"
                    # module forces unions to be subscripted by two or more
                    # child hints. By deduction, those child hints *MUST* be
                    # PEP-compliant. Ergo, we need *NOT* explicitly validate
                    # that constraint here.
                    hints_meta.pith_curr_assign_expr
                ),
            ),
        )

    # ....................{ RETURN                         }....................
    # Release this pair of sets back to their respective pools.
    release_instance(hint_childs_nonpep)
    release_instance(hint_childs_sane_pep)

    # If this code is *NOT* its initial value, this union is subscripted by one
    # or more unignorable child hints and the above logic generated code
    # type-checking these child hints. In this case...
    if hints_meta.func_curr_code is not CODE_PEP484604_UNION_PREFIX:
        # Munge this code to...
        hints_meta.func_curr_code = (
            # Strip the erroneous " or" suffix appended by the last child hint
            # from this code.
            f'{hints_meta.func_curr_code[:LINE_RSTRIP_INDEX_OR]}'
            # Suffix this code by the substring suffixing all such code.
            f'{CODE_PEP484604_UNION_SUFFIX}'
        # Format the "indent_curr" prefix into this code, deferred above for
        # efficiency.
        ).format(indent_curr=hints_meta.indent_curr)
    # Else, this snippet is its initial value and thus ignorable.

# ....................{ PRIVATE ~ getters                  }....................
@callable_cached
def _get_hint_pep484604_union_args_flattened(
    hints_meta: HintsMeta) -> TupleHintSane:
    '''
    Flattened tuple of the two or more child hints subscripting the passed
    :pep:`604`- or :pep:`484`-compliant union hint such that *all* nested child
    hints subscripting *all* child union hints are **flattened** (i.e., expanded
    directly) into the returned tuple, thus non-destructively eliminating *all*
    child union hints of this parent union hint.

    This getter recursively flattens arbitrarily nested child union hints
    regardless of nesting depth in this parent union hint. Although non-trivial,
    doing so is required to support uncommon edge cases -- including:

    * :`pep:`695`-compliant type aliases, which technically enable users to
      deeply nest type aliases and thus unions to an arbitrarily deep nesting
      level: e.g.,

      .. code-block:: python

         # After reduction, the PEP 695-compliant "Level3" type alias defined
         # below effectively resembles:
         #     type Level3 = ((int | complex) | str) | float
         type Level1 = int | complex
         type Level2 = Level1 | str
         type Level3 = Level2 | float

    This getter is intentionally *not* memoized (e.g., by the
    :func:`.callable_cached` decorator), as the only function calling this
    getter *is* itself memoized.

    Caveats
    -------
    **This getter exhibits time complexity** :math:`O(k)` **for k the total
    number of all transitive child hints of this union hint across all deeply
    nested child unions of this parent union hint.** A looser bound but somewhat
    more intelligible upper complexity bound would be :math:`O(n**m)`, where:

    * :m.th:`n` is the maximum number of child hints in any deeply nested child
      union of this parent union hint.
    * :math:`m` is the maximum depth of the most deeply nested child union of
      this parent union hint.

    Parameters
    ----------
    hints_meta : HintsMeta
        **Type hint type-checking metadata queue** (i.e., low-level fixed list
        of metadata describing all visitable type hints currently discovered by
        the breadth-first search (BFS) dynamically generating pure-Python
        type-checking code snippets in the
        :func:`beartype._check.code.codemain.make_check_expr` factory).

    Returns
    -------
    Tuple[HintSane, ...]
        Flattened tuple of the two or more child hints *or* **sanified child
        hint metadatum** (i.e., :class:`.HintSane` objects) subscripting
        this parent union hint.

    Raises
    ------
    BeartypeDecorHintPep604Exception
        If this tuple is empty.
    '''
    # print(f'[484/604] hint_curr_meta: {repr(hints_meta.hint_curr_meta)}')

    # ....................{ LOCALS                         }....................
    # Metadata encapsulating the currently visited PEP 484- or 604-compliant
    # union type hint as well as that hint.
    union_hint_sane = hints_meta.hint_curr_meta.hint_sane
    union_hint = union_hint_sane.hint

    # ....................{ LOCALS ~ child                 }....................
    # Tuple of the two or more child hints subscripting this union.
    hint_childs = get_hint_pep_args(union_hint)

    # Number of these child hints.
    hint_childs_len = len(hint_childs)

    # Assert this union to be subscripted by two or more child hints.
    #
    # Note this should *ALWAYS* be the case, as:
    # * The unsubscripted "typing.Union" type hint factory is explicitly listed
    #   in the "HINTS_REPR_IGNORABLE_SHALLOW" set and should thus have already
    #   been ignored when present.
    # * The "typing" module explicitly prohibits empty union subscription: e.g.,
    #       >>> typing.Union[]
    #       SyntaxError: invalid syntax
    #       >>> typing.Union[()]
    #       TypeError: Cannot take a Union of no types.
    # * The "typing" module reduces unions of one child hint to that hint: e.g.,
    #     >>> import typing
    #     >>> typing.Union[int]
    #     int
    assert hint_childs_len >= 2, (
        f'{hints_meta.exception_prefix}'
        f'PEP 484 or 604 union type hint {repr(union_hint)} either '
        f'unsubscripted or subscripted by only one child type hint.'
    )

    # ....................{ LOCALS ~ list                  }....................
    # Input stack of all currently unflattened transitive child hints of this
    # union to be visited by the depth-first search (DFS) below such that each
    # item of this stack is a 2-tuple (hint_child_insane, hint_parent_sane),
    # where:
    # * "hint_child_insane" is an transitive child hint of this union that has
    #   yet to be sanified and thus possibly expanded into a nested union hint
    #   requiring flattening into this root union hint.
    # * "hint_parent_sane" is sanified metadata encapsulating the direct parent
    #   hint of "hint_child_insane". In theory, this should *ALWAYS* be a union
    #   hint -- either this root union hint *OR* a nested union hint thereof.
    hint_childs_insane_unflattened: List[Tuple[Hint, HintSane]] = (
        acquire_instance(list))

    # Efficiently initialize this input stack to the non-empty list of all
    # 2-tuples (hint_child_insane, union_hint_sane) containing all direct child
    # hints of this union, equivalent to the following inefficient iteration:
    #     for hint_child in hint_childs:
    #         hint_childs_insane_unflattened.append((
    #             hint_child, union_hint_sane))
    #
    # Specifically:
    # * "(union_hint_sane,)*hint_childs_len" expands to the n-tuple containing
    #   "n" repetitions of this root union hint, where n is the number of child
    #   hints subscripting this root union hint.
    # * This call to the zip() builtin creates an iterable of 2-tuples
    #   (hint_child_insane, union_hint_sane) for each such child hint.
    hint_childs_insane_unflattened.extend(zip(
        hint_childs, (union_hint_sane,)*hint_childs_len))

    # Output stack of all previously flattened transitive child hints of this
    # union that have already been visited by this DFS such that each item of
    # this list is sanified metadata encapsulating each such child hint,
    # initialized to the empty list. Equivalently, this is the list of all
    # sanified child hints from which to reconstitute this union below.
    #
    # Note that this stack orders these child hints in the *REVERSE* order that
    # these child hints were originally ordered by the user in this union.
    hint_childs_sane_flattened: ListHintSane = acquire_instance(list)

    # ....................{ SEARCH                         }....................
    # Repeatedly flatten all currently unflattened transitive child hints of
    # this union into an increasingly flat union until this union can no longer
    # be flattened (i.e., after these child hints have all been flattened).
    # Recursively perform a depth-first search (DFS) over these child hints with
    # non-recursive iteration for both efficiency and simplicity. While
    # non-recursive iteration is often non-trivial, this implementation is
    # surprisingly trivial.
    #
    # While the input stack of these child hints is still non-empty, one or more
    # transitive child hints of this union have yet to be flattened. Then...
    while hint_childs_insane_unflattened:
        # ....................{ SANIFY                     }....................
        # Currently unflattened transitive child hint to be flattened defined as
        # the 2-tuple (hint_child_insane, hint_parent_sane), where:
        # * "hint_child_insane" is an transitive child hint of this union that
        #   has yet to be sanified and thus possibly expanded into a nested
        #   union hint requiring flattening into this root union hint.
        # * "hint_parent_sane" is sanified metadata encapsulating the direct
        #   parent hint of "hint_child_insane". In theory, this should *ALWAYS*
        #   be a union hint -- either this root union hint *OR* a nested union
        #   hint sanified by a prior iteration of this loop below.
        hint_child_insane, hint_parent_sane = (
            hint_childs_insane_unflattened.pop())

        # Metadata encapsulating the sanification of the currently unflattened
        # transitive child hint to be flattened.
        hint_child_sane: HintSane = SENTINEL  # type: ignore[assignment]

        # Sanified hint metadata encapsulating the sanification of this
        # possibly insane child hint with respect to the previously sanified
        # metadata encapsulating the direct parent hint of this child hint.
        #
        # Note that this sanification is intentionally performed *BEFORE* the
        # sign of this child hint is tested. Why? Because some reductions expand
        # an arbitrary hint into a union. This includes:
        # * PEP 695-compliant type aliases aliased to unions. See above!
        # * The PEP-noncompliant "float' and "complex" types, implicitly
        #   expanded to the PEP 484-compliant "float | int" and "complex | float
        #   | int" type hints (respectively) when the non-default
        #   "conf.is_pep484_tower=True" parameter is enabled.
        # * User-defined "hint_overrides", a generalization of the prior item.
        #
        # Likewise, note that this sanification implicitly handles *ALL*
        # recursive edge cases. We need *NOT* do so explicitly above or below.
        # Notably, if this child hint has already been sanified by a previously
        # performed sanification in this recursive tree of all previously
        # performed sanifications, there now exist two divergent edge cases.
        # Either:
        # * This child hint has intrinsic value and *MUST* thus be preserved as
        #   a member of this union. This edge case currently arises *ONLY*
        #   through hint overrides. Consider overriding the child hint "float"
        #   with the PEP 604-compliant union "int | float". In this case:
        #   * The initial sanification of the child hint "float" performed above
        #     will expand that hint to "int | float".
        #   * The unflattening performed below will then append the child hints
        #     "int" and "float" for subsequent iteration by this "while" loop.
        #   * The child hint "float" will then be detected as having been
        #     previously sanified. This child hint *CANNOT* be removed or
        #     ignored, as doing so would omit this child hint from this union.
        #     This child hint thus has intrinsic value and *MUST* thus be
        #     preserved as a member of this union.
        #
        #   This edge case is implicitly handled by the
        #   hints_meta.sanify_hint_child() method called below, which
        #   transitively calls the reduce_hint() function, which detects
        #   recursion in an overridden hint and implicitly returns that hint as
        #   is *WITHOUT* recursively overriding that hint yet again.
        # * This child hint lacks intrinsic value and *MUST* thus be removed as
        #   a member of this union. This edge case currently arises *ONLY*
        #   through PEP 695-compliant recursive type aliases. Consider:
        #       type RecursiveUnion = int | RecursiveUnion
        #
        #   The recursive type alias "RecursiveAlias" merely has symbolic value
        #   and thus lacks intrinsic value. This type alias is semantically
        #   equivalent to the non-recursive type alias:
        #       type NonrecursiveAlias = int
        #
        #   Similar logic as with the prior edge case then applies, except that
        #   this hint *SHOULD* be removed and ignored (rather than preserved).
        #   Thankfully, this edge case as well is implicitly handled by the
        #   hints_meta.sanify_hint_child() method called below, which
        #   transitively calls the reduce_hint() function, which detects
        #   recursion in a non-overridden hint and explicitly returns
        #   "HINT_SANE_IGNORABLE" rather than recursing infinitely into that hint.
        # print(f'Sanifying union child hint {repr(hint_child)} under {repr(conf)}...')
        hint_child_sane = hints_meta.sanify_hint_child(
            hint_child_insane=hint_child_insane,
            hint_parent_sane=hint_parent_sane,
        )
        # print(f'Sanified union child hint {hint_child_insane} to {hint_child_sane}!')

        # Assert this child hint to be unignorable. The previously applied
        # reduction for PEP 484- and 604-compliant union hints (i.e., the
        # reduce_hint_pep484604() reducer) *SHOULD* have already ignored union
        # hints containing *ANY* ignorable child hints. However, this union was
        # *NOT* ignored! By elimination, this union must contain *NO* ignorable
        # child hints.
        assert hint_child_sane.hint is not HINT_IGNORABLE, (
            f'Union {repr(union_hint)} '
            f'containing ignorable child {repr(hint_child_insane)} '
            f'not itself ignored (i.e., reduced to "HINT_IGNORABLE" singleton).'
        )

        # ....................{ UNION                      }....................
        # Sane child hint encapsulated by this metadata.
        hint_child = hint_child_sane.hint

        # Sign of this sanified child hint if this hint is PEP-compliant *OR*
        # "None" otherwise (i.e., if this hint is PEP-noncompliant).
        hint_child_sign = get_hint_pep_sign_or_none(hint_child)

        # If this child hint is itself a child union nested in this parent
        # union, explicitly flatten this nested union by appending *ALL* child
        # child hints subscripting this child union onto this parent union.
        #
        # Note that this edge case currently *ONLY* arises when this child hint
        # has been expanded by the above call to the sanify_hint_child()
        # function from a non-union (e.g., "float") into a union (e.g., "float |
        # int"). The standard PEP 484-compliant "typing.Union" type hint factory
        # already implicitly flattens nested unions: e.g.,
        #     >>> from typing import Union
        #     >>> Union[float, Union[int, str]]
        #     typing.Union[float, int, str]
        if hint_child_sign in HINT_SIGNS_UNION:
            # Tuple of all child child hints subscripting this child union.
            hint_child_childs = get_hint_pep_args(hint_child)
            # print(f'Expanding union {repr(hint_curr)} with child union {repr(hint_child_childs)}...')

            # For each child child type subscripting this child union,
            # efficiently append the 2-tuple containing both this unsanified
            # child child hint *AND* this sanified child hint metadata to this
            # stack. This is equivalent to the following inefficient iteration:
            #     for hint_child_child in hint_child_childs:
            #         hint_childs_insane_unflattened.append((
            #             hint_child_child, hint_child_sane))
            #
            # See above for further discussion dissecting this madness.
            hint_childs_insane_unflattened.extend(zip(
                hint_child_childs, (hint_child_sane,)*len(hint_child_childs)))
        # ....................{ NON-UNION                  }....................
        # Else, this child hint is *NOT* itself a union. In this case, append
        # this child hint to this parent union.
        else:
            hint_childs_sane_flattened.append(hint_child_sane)
            # print(f'Flattened union child {repr(hint_child)} to {repr(hint_child_sane)}...')

    # ....................{ RETURN                         }....................
    # Tuple of all flattened transitive child hints of this union, reversed so
    # as to undo the reverse ordering applied by the above algorithm and thus
    # preserve the original ordering of these child hints of this union.
    hint_childs_sane_flattened_tuple = tuple(reversed(
        hint_childs_sane_flattened))

    # Release these stacks back to their respective pool.
    release_instance(hint_childs_insane_unflattened)
    release_instance(hint_childs_sane_flattened)
    # print(f'Flattened union to {repr(hint_childs_sane)}...')

    # Return this tuple.
    return hint_childs_sane_flattened_tuple
