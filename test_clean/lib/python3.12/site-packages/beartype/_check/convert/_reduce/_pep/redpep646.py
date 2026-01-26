#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`646`-compliant **type hint reducers** (i.e., low-level
callables converting :pep:`646`-compliant hints to lower-level type hints more
readily consumable by :mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: Currently, we only shallowly type-check PEP 646-compliant mixed
#fixed-variadic tuple hints as... tuples. It's not much. Obviously, we need to
#deeply type-check these tuple data structures as soon as feasible. There exist
#two distinct use cases here:
#* Fixed-variadic tuple hints containing exactly one unpacked child tuple hint
#  (e.g., "tuple[int, *tuple[str, ...], float]"). Note that a tuple hint may
#  only contain *AT MOST* one unpacked child tuple hint.
#* Fixed-variadic tuple hints containing exactly one type variable tuple, either
#  as:
#  * The first child hint (e.g., "tuple[*Ts, int]").
#  * The last child hint (e.g., "tuple[str, bytes, *Ts]"). Note that this case
#    has a prominent edge case. Fixed-variadic tuple hints of the form
#    "tuple[hint_child, *Ts]" for *ANY* "hint_child" and type variable tuple
#    "Ts" trivially reduce to variadic tuple hints of the form
#    "tuple[hint_child, ...]" at the moment, as we silently ignore *ALL* type
#    variable tuples. Ergo, if a hint is a fixed-variadic tuple hint whose last
#    child hint is a type variable tuple, this hint *MUST* by definition be
#    prefixed by two or more child hints that are *NOT* type variable tuples.
#  * Any child hint other than the first or last (e.g.,
#    "tuple[float, *Ts, bool]").
#
#  Note that:
#  * A parent tuple hint can contain at most *ONE* unpacked child tuple hint.
#    So, we'll now need to record the number of unpacked child tuple hints that
#    have been previously visited and raise an exception if two or more are
#    seen. Ugh!
#  * Again, these cases have a prominent edge case. Fixed-variadic tuple hints
#    of the form "tuple[*Ts]" for *ANY* type variable tuple "Ts" trivially
#    reduce to the builtin type "tuple" at the moment, as we silently ignore
#    *ALL* type variable tuples.
#  * Fixed-variadic tuple hints *CANNOT* contain both an unpacked type variable
#    tuple *AND* unpacked child tuple hint (e.g., "tuple[*Ts, *tuple[int,
#    ...]]"). Fixed-variadic tuple hints can contain at most one unpacked child
#    hint. Hopefully, this constraint reduces the complexity of code generation.
#
#The first place to start with all of this is implementing a new code generation
#algorithm for the new "HintSignPep646TupleFixedVariadic" sign, which currently
#just shallowly reduces to the builtin "tuple" type. Obviously, that's awful.
#The first-draft implementation of this algorithm should just focus on
#fixed-variadic tuple hints containing exactly one type variable tuple (e.g.,
#"tuple[float, *Ts, bool]") for now, as that's the simpler use case. Of course,
#even that's *NOT* simple -- but it's a more reasonable start than unpacked
#child tuple hints, which spiral into madness far faster and harder.
#
#Lastly, note that we can trivially handle unpacked child tuple hints in a
#simple, effective way *WITHOUT* actually investing any effort in doing so. How?
#By simply treating each unpacked child tuple hint as a type variable tuple
#(e.g., by treating "tuple[str, *tuple[int, ...], bytes]" as equivalent to
#"tuple[str, *Ts, bytes]"). Since we already need to initially handle type
#variable tuples anyway, we shatter two birds with one hand. Yes! Yes!
#FIXME: Actually, it's *DEFINITELY* not the case that we "silently ignore *ALL*
#type variable tuples." We reduce both type variables and type variable tuples
#to lookup tables. So, stop ignoring type variable tuples below, please.
#
#Otherwise, everything above seems great -- by which I mean, exhausting.

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep646Exception
from beartype.typing import Optional
from beartype._data.typing.datatypingport import (
    Hint,
    ListHints,
    TupleHints,
)
from beartype._data.hint.sign.datahintsigns import (
    HintSignPep646TupleUnpacked,
    HintSignPep646TypeVarTupleUnpacked,
)
from beartype._data.hint.sign.datahintsignset import (
    HINT_SIGNS_PEP646_TUPLE_HINT_CHILD_UNPACKED)
from beartype._util.hint.pep.proposal.pep484585646 import (
    is_hint_pep484585646_tuple_variadic,
    make_hint_pep484585_tuple_fixed,
)
from beartype._util.hint.pep.utilpepget import get_hint_pep_args
from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none

# ....................{ REDUCERS                           }....................
#FIXME: Unit test us up, please.
def reduce_hint_pep646_tuple(
    hint: Hint, exception_prefix: str, **kwargs) -> Hint:
    '''
    Reduce the passed :pep:`646`-compliant **tuple hint** (i.e., parent tuple
    hints subscripted by either a :pep:`646`-compliant type variable tuples *or*
    :pep:`646`-compliant unpacked child tuple hint) to a lower-level type hint
    currently supported by :mod:`beartype`.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

    Parameters
    ----------
    hint : object
        :pep:`646`-compliant tuple hint to be reduced.
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    All remaining keyword-only parameters are silently ignored.

    Returns
    -------
    Hint
        Lower-level hint currently supported by :mod:`beartype`.

    Raises
    ------
    BeartypeDecorHintPep646Exception
        If this tuple hint is subscripted by either:

        * Two or more :pep:`646`-compliant type variable tuples.
        * Two or more :pep:`646`-compliant unpacked child tuple hints.
        * Two or more :pep:`646`-compliant type variable tuples.
        * A :pep:`646`-compliant type variable tuple *and* an unpacked child
          tuple hint.
    '''
    # print(f'Reducing PEP 646 tuple hint {repr(hint)}...')

    # ....................{ LOCALS                         }....................
    # Tuple of the one or more child hints subscripting this parent tuple hint.
    #
    # Note that the previously called
    # get_hint_pep484585646_tuple_sign_unambiguous() getter responsible for
    # disambiguating PEP 484- and 585-compliant tuple hints from this PEP
    # 646-compliant tuple hint has already pre-validated this tuple hint to be
    # subscripted by two or more child hints.
    hint_childs = get_hint_pep_args(hint)

    # Number of child hints subscripting this parent tuple hint.
    hint_childs_len = len(hint_childs)

    # Assert this parent tuple hint is subscripted by at least one child hint.
    #
    # Note that the previously called
    # get_hint_pep484585646_tuple_sign_unambiguous() getter should have already
    # guaranteed this. Ergo, we avoid raising a full-blown exception here.
    assert hint_childs_len >= 1, (
        f'PEP 646 tuple hint {repr(hint)} subscripted by no child hints.')

    # List of the zero or more new child hints with which to subscript a new
    # PEP 585-compliant parent tuple hint to reduce this PEP 646-compliant
    # parent tuple hint to if this PEP 646-compliant parent tuple hint is
    # reducible to a PEP 585-compliant parent tuple hint *OR* "None" otherwise.
    #
    # This list enables this reducer to reduce PEP 646-compliant parent tuple
    # hints to semantically equivalent PEP 585-compliant parent tuple hints.
    # Generating type-checking code and violation messages for PEP 585-compliant
    # parent tuple hints is both faster *AND* simpler than generating
    # type-checking code and violation messages for PEP 646-compliant parent
    # tuple hints, incentivizing this reduction.
    hint_pep585_childs: Optional[TupleHints] = None

    # ....................{ LENGTH                         }....................
    # If this parent tuple hint is subscripted by exactly one child hint...
    if hint_childs_len == 1:
        # Child hint subscripting this parent tuple hint.
        hint_child = hint_childs[0]

        # Sign uniquely identifying the child hint subscripting this parent
        # tuple hint if this child hint is PEP-compliant *OR* "None" otherwise.
        hint_child_sign = get_hint_pep_sign_or_none(hint_child)
        # print(f'hint_child_sign: {hint_child_sign}')

        # If this child hint is a PEP 646-compliant unpacked type variable tuple
        # (e.g., the "*Ts" in "tuple[*Ts]"), reduce this PEP 646-compliant tuple
        # hint to the builtin "tuple" type.
        #
        # The justification here is somewhat subtle. @beartype currently ignores
        # all type parameters -- including both PEP 484-compliant type variables
        # and 646-compliant type variable tuples. Whereas a conventional type
        # variable is trivially reducible to the ignorable "typing.Any"
        # singleton, however, type variable tuples are only reducible to the
        # less ignorable PEP 646-compliant unpacked child tuple hint
        # "*tuple[typing.Any, ...]". Type variable tuples imply *VARIADICITY*
        # (i.e., a requirement that zero or more tuple items be matched). This
        # requirement *CANNOT* be trivially ignored. Ergo, any PEP 646-complaint
        # parent tuple hint of the form "tuple[*Ts]" for *ANY* type variable
        # tuple "*Ts" is reducible to the also PEP 646-compliant parent tuple
        # hint "tuple[*tuple[typing.Any, ...]]", which unpacks to the PEP
        # 646-*AGNOSTIC* parent tuple hint "tuple[typing.Any, ...]", which then
        # simply reduces to the builtin "tuple" type.
        if hint_child_sign is HintSignPep646TypeVarTupleUnpacked:
            # Reduce this PEP 646-compliant tuple hint to the "tuple" type.
            return tuple
        # Else, this child hint is *NOT* a PEP 646-compliant unpacked type
        # variable tuple.
        #
        # If this child hint is a PEP 646-compliant unpacked child tuple hint
        # (e.g., the "*tuple[str, ...]" in "tuple[*tuple[str, ...]]"), reduce
        # this PEP 646-compliant tuple hint to the semantically equivalent PEP
        # 585-compliant tuple hint subscripted by the child child hints
        # subscripting this unpacked child tuple hint (e.g., from
        # "tuple[*tuple[str, ...]]" to "tuple[str, ...]"). This could be
        # regarded as a non-recursive "unboxing" or "unpacking" operation.
        #
        # Note that this edge case is syntactically permitted by PEP 646 for
        # orthogonality, despite being semantically superfluous and thus
        # conveying *NO* meaningful typing not already conveyed by the simpler
        # PEP 585-compliant tuple hint that this PEP 646-compliant tuple hint
        # reduces to. So it goes, Pythonistas. So it goes.
        elif hint_child_sign is HintSignPep646TupleUnpacked:
            # Reduce this PEP 646-compliant tuple hint to the semantically
            # equivalent PEP 585-compliant tuple hint subscripted by the zero or
            # more child child hints subscripting this unpacked child tuple
            # hint.
            #
            # Note that the CPython parser itself prevents unpacked child tuple
            # hints from being trivially subscripted by *NO* child child hints.
            # Interestingly, doing so is still non-trivially feasible by the
            # standard empty tuple "()" trick: e.g.,
            #     >>> tuple[*tuple[]]
            #                ^^^^^^^
            #     SyntaxError: invalid syntax. Perhaps you forgot a comma?
            #
            #     >>> tuple[*tuple[()]]
            #     tuple[*tuple[()]]
            hint_pep585_childs = get_hint_pep_args(hint_child)
        # Else, this child hint is *NOT* a PEP 646-compliant unpacked child
        # tuple hint. In this case, raise a fatal exception. Why? Because the
        # previously called get_hint_pep484585646_tuple_sign_unambiguous()
        # getter already validated this tuple hint to be PEP 646-compliant and
        # thus be subscripted by one or more PEP 646-compliant child hints, but
        # this hint is subscripted by only one PEP 646-noncompliant child hint!
        else:  # pragma: no cover
            raise BeartypeDecorHintPep646Exception(
                f'{exception_prefix}PEP 646 tuple type hint {repr(hint)} '
                f'child hint {repr(hint_child)} not PEP 646-compliant '
                f'(i.e., neither unpacked type variable tuple nor '
                f'unpacked child tuple type hint).'
            )
    # Else, this parent tuple hint is *NOT* subscripted by one child hint,
    # implying this parent tuple hint is subscripted by two or more child hints.
    # Since this hint is irreducible, preserve this hint as is.

    # ....................{ SEARCH                         }....................
    # If prior logic has *NOT* already decided this PEP 646-compliant parent
    # tuple hint to be trivially reducible to a PEP 585-compliant parent tuple
    # hint, attempt to non-trivially decide this with iteration over all child
    # hints subscripting this parent tuple hint.
    if hint_pep585_childs is None:
        # First PEP 646-compliant child hint subscripting this parent tuple hint
        # discovered by iteration below if this parent tuple hint is subscripted
        # by one or more PEP 646-compliant child hints *OR* "None" otherwise
        # (i.e., if this parent tuple hint is subscripted by *NO* such hints).
        #
        # Note that PEP 646-compliant child hints include:
        # * PEP 646-compliant unpacked type variable tuple (e.g., the "*Ts" in
        #   "tuple[str, *Ts]").
        # * PEP 646-compliant unpacked type variable tuple (e.g., the "*Ts" in
        #   "tuple[str, *Ts]").
        #
        # This local enables the iteration below to validate that this parent
        # tuple hint fully complies with PEP 646 by being subscripted by:
        # * Exactly one PEP 646-compliant child hint (e.g., "*Ts",
        #   "*tuple[int]").
        # * Zero or more PEP 646-noncompliant child hints (e.g., "int",
        #   "set[str]").
        #
        # PEP 646 prohibits parent tuple hints from being subscripted by two or
        # more PEP 646-compliant child hints.
        hint_child_pep646: Optional[Hint] = None

        # 0-based index of this first PEP 646-compliant child hint in this
        # parent tuple hint if any *OR* "None" otherwise.
        hint_child_pep646_index: Optional[int] = None

        #FIXME: [SPEED] Acquire and release a cached list instead, please.
        # Either:
        # * If this hint is subscripted somewhere by a PEP 646-compliant
        #   unpacked child fixed-length tuple hint (e.g., the "*tuple[str,
        #   float]" in "tuple[int, *tuple[str, float]]") and thus semantically
        #   reducible to a PEP 585-compliant parent fixed-length tuple hint
        #   (e.g., from "tuple[int, *tuple[str, float]]" to "tuple[int, str,
        #   float]"), the list of zero or more child hints with which to
        #   subscript a PEP 585-compliant parent fixed-length tuple hint to
        #   reduce this PEP 646-compliant parent tuple hint to.
        # * Else (i.e., if this PEP 646-compliant hint is *NOT* reducible to
        #   such a PEP 585-compliant hint), "None".
        #
        # PEP 646-compliant unpacked child fixed-length tuple hints are entirely
        # superfluous and supported by PEP 646 merely for orthogonality.
        # Although it is unlikely that *ANYONE* will everyone use PEP
        # 646-compliant unpacked child fixed-length tuple hints, the possibility
        # that someone might requires us to support this obscure edge case.
        hint_pep585_childs_list: Optional[ListHints] = []

        #FIXME: [SPEED] Optimize into a "while" loop, please. *sigh*
        # For the 0-based index of each child hint subscripting this parent
        # tuple hint as well as that child hint...
        for hint_child_index, hint_child in enumerate(hint_childs):
            # Sign uniquely identifying this child hint if this child hint is
            # PEP-compliant *OR* "None" otherwise.
            hint_child_sign = get_hint_pep_sign_or_none(hint_child)

            # If this child hint is PEP 646-compliant...
            if hint_child_sign in HINT_SIGNS_PEP646_TUPLE_HINT_CHILD_UNPACKED:
                # If this iteration has yet to discover a PEP 646-compliant
                # child hint of this parent tuple hint, this is the first PEP
                # 646-compliant child hint subscripting this parent tuple hint
                # discovered by this iteration. In this case, record this fact.
                if hint_child_pep646 is None:
                    hint_child_pep646 = hint_child
                    hint_child_pep646_index = hint_child_index

                    # If...
                    if (
                        # This list still exists, it is still unknown whether
                        # this hint is subscripted anywhere by a PEP
                        # 646-compliant unpacked child hint -- implying that
                        # this hint *COULD* still be subscripted somewhere by a
                        # PEP 646-compliant unpacked child fixed-length tuple
                        # hint (e.g., the "*tuple[str, float]" in "tuple[int,
                        # *tuple[str, float]]") *AND*...
                        hint_pep585_childs_list is not None and
                        # This child hint is a PEP 646-compliant unpacked child
                        # tuple hint *AND*...
                        hint_child_sign is HintSignPep646TupleUnpacked and
                        # This child hint is *NOT* a PEP 646-compliant unpacked
                        # child variable-length tuple hint, this child hint
                        # *MUST* by elimination be a PEP 646-compliant unpacked
                        # child fixed-length tuple hint.
                        not is_hint_pep484585646_tuple_variadic(hint_child)
                    ):
                        # Tuple of the zero or more child child hints
                        # subscripting this PEP 646-compliant unpacked child
                        # fixed-length tuple hint.
                        hint_child_childs = get_hint_pep_args(hint_child)
                        # print(f'Appending PEP 646 unpacked fixed-length tuple hint children {hint_child}...')

                        # Append all child child hints subscripting this PEP
                        # 646-compliant unpacked child fixed-length tuple hint
                        # to the end of this list, effectively unpacking this
                        # child hint directly into the new PEP 585-compliant
                        # parent fixed-length tuple hint to be returned.
                        hint_pep585_childs_list.extend(hint_child_childs)
                    # Else, this child hint is *NOT* a PEP 646-compliant
                    # unpacked child fixed-length tuple hint. But this child
                    # hint is PEP 646-compliant! By process of elimination, this
                    # child hint *MUST* be a PEP 646-compliant unpacked type
                    # variable tuple (e.g., the "*Ts" in "tuple[str, *Ts]"). In
                    # this case, notify logic below that this PEP 646-compliant
                    # parent tuple hint is irreducible to a PEP 585-compliant
                    # parent tuple hint.
                    else:
                        # print(f'Ignoring PEP 646 non-unpacked fixed-length tuple hint {hint_child}...')
                        hint_pep585_childs_list = None
                # Else, this iteration has already discovered a PEP
                # 646-compliant child hint of this parent tuple hint. Since the
                # currently visited child hint is also PEP 646-compliant, this
                # parent tuple hint is subscripted by two or more PEP
                # 646-compliant child hints and thus violates PEP 646. In this
                # case, raise an exception.
                else:
                    assert hint_child_pep646_index is not None
                    raise BeartypeDecorHintPep646Exception(  # pragma: no cover
                        f'{exception_prefix}PEP 646 tuple type hint {repr(hint)} '
                        f'erroneously subscripted by two (or more) '
                        f'PEP 646 unpacked child hints:\n'
                        f'* PEP 646 unpacked child hint {repr(hint_child_pep646)} '
                        f'at index {hint_child_pep646_index}.\n'
                        f'* PEP 646 unpacked child hint {repr(hint_child)} '
                        f'at index {hint_child_index}.'
                    )
            # Else, this child hint is PEP 646-noncompliant.
            #
            # If this PEP 646-compliant parent tuple hint is still possibly
            # reducible to a PEP 585-compliant parent tuple hint, append this
            # PEP 646-noncompliant child hint to the list of all such hints to
            # subscript this PEP 585-compliant parent tuple hint by.
            elif hint_pep585_childs_list is not None:
                # print(f'Appending non-PEP 646 child hint {hint_child}...')
                hint_pep585_childs_list.append(hint_child)
            # Else, this PEP 646-compliant parent tuple hint is no longer
            # reducible to a PEP 585-compliant parent tuple hint (presumably due
            # to being subscripted by one or more PEP 646-compliant unpacked
            # child hints). In this case, continue validating this hint to be
            # PEP 646-compliant.

        # If prior iteration decided this PEP 646-compliant parent tuple hint to
        # be reducible to a PEP 585-compliant parent tuple hint, coerce this
        # list into a tuple of child hints subscripting the latter.
        if hint_pep585_childs_list is not None:
            hint_pep585_childs = tuple(hint_pep585_childs_list)
        # Else, prior iteration decided this PEP 646-compliant parent tuple hint
        # to *NOT* be reducible to a PEP 585-compliant parent tuple hint.

    # ....................{ RETURN                         }....................
    # Reduce this non-trivial PEP 646-compliant tuple hint to either...
    hint_reduced = (
        #FIXME: *STOP DOING THIS* as soon as we implement a proper code
        #generator for PEP 646-compliant tuple hints, please. *sigh*
        # If this PEP 646-compliant parent tuple hint is irreducible to a PEP
        # 585-compliant parent tuple hint, the builtin "tuple" type as a
        # temporary means of shallowly ignoring *ALL* child hints subscripting
        # this hint. Although obviously non-ideal, this simplistic approach does
        # have the benefit of actually working -- an improvement over our prior
        # approach of raising fatal exceptions for these hints.
        tuple
        if hint_pep585_childs is None else
        # Else, this PEP 646-compliant parent tuple hint is reducible to a PEP
        # 585-compliant parent tuple hint. In this case, the latter.
        make_hint_pep484585_tuple_fixed(hint_pep585_childs)
    )

    # print(f'Reduced PEP 646 tuple hint {hint} to {hint_reduced}!')
    return hint_reduced
