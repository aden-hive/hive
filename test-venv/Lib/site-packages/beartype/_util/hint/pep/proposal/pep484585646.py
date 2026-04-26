#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`-, :pep:`585`-, and :pep:`646`-compliant **tuple type
hint utilities** (i.e., low-level callables generically applicable to
:pep:`484`- and :pep:`585`-compliant purely fixed- and variadic-length tuple
type hints *and* :pep:`646`-compliant mixed fixed-variadic tuple type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import Tuple
from beartype._data.typing.datatypingport import (
    Hint,
    TupleHints,
)
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.hint.sign.datahintsigns import (
    HintSignPep484585TupleFixed,
    HintSignPep484585TupleVariadic,
    HintSignPep646TupleFixedVariadic,
)
from beartype._data.hint.sign.datahintsignset import (
    HINT_SIGNS_PEP646_TUPLE_HINT_CHILD_UNPACKED)
from beartype._util.hint.pep.proposal.pep484.pep484 import (
    HINT_PEP484_TUPLE_EMPTY)
from beartype._util.hint.pep.proposal.pep585 import (
    HINT_PEP585_TUPLE_EMPTY)

# ....................{ TESTERS                            }....................
def is_hint_pep484585646_tuple_variadic(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed object is either a :pep:`484`-, :pep:`585`-,
    or :pep:`646`-compliant **variable-length tuple hint** (i.e., parent hint
    subscripted by exactly two child hints, the former of which is any arbitrary
    hint and the latter of which is an **ellipsis** (i.e., the :data:`Ellipsis`
    singleton specified in code as an unquoted ``...``)).

    This tester returns :data:`True` if this hint is either:

    * A :pep:`484`-compliant variable-length tuple hint of the form
      ``typing.Tuple[{hint_child}, ...]`` for any ``{hint_child}``.
    * A :pep:`585`-compliant variable-length tuple hint of the form
      ``tuple[{hint_child}, ...]`` for any ``{hint_child}``.
    * A :pep:`646`-compliant unpacked variable-length child tuple hint of the
      form ``*tuple[{hint_child}, ...]`` for any ``{hint_child}``.

    This tester is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as this tester trivially reduces to an
    efficient one-liner.

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a variable-length tuple hint.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import get_hint_pep_args

    # Child hints subscripting this tuple hint.
    hint_childs = get_hint_pep_args(hint)

    # Return true only if...
    return (
        # This parent tuple hint is subscripted by two child hints *AND*...
        len(hint_childs) == 2 and
        # This second child hint is the PEP 484- and 585-compliant ellipsis
        # singleton (e.g., the unquoted character sequence "..." in
        # "tuple[str, ...]").
        hint_childs[1] is Ellipsis
    )


def is_hint_pep484585646_tuple_empty(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed object is either a :pep:`484`- or
    :pep:`585`-compliant **empty fixed-length tuple type hint** (i.e., hint
    constraining objects to be the empty tuple).

    Since type variables are not themselves types but rather placeholders
    dynamically replaced with types by type checkers according to various
    arcane heuristics, both type variables and types parametrized by type
    variables warrant special-purpose handling.

    This tester is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as this tester trivially reduces to an
    efficient one-liner and, in any case, is only called under rare edge cases.

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is an empty fixed-length tuple hint.
    '''

    # Return true only if this hint resembles either the PEP 484- or
    # 585-compliant fixed-length empty tuple type hint. Since there only exist
    # two such hints *AND* comparison against these hints is mostly fast, this
    # test is efficient in the general case.
    #
    # Note that this test may also be inefficiently performed by explicitly
    # obtaining this hint's sign and then subjecting this hint to specific
    # tests conditionally depending on which sign and thus PEP this hint
    # complies with: e.g.,
    #     # Return true only if this hint is either...
    #     return true (
    #         # A PEP 585-compliant "tuple"-based hint subscripted by no
    #         # child hints *OR*...
    #         (
    #             hint.__origin__ is tuple and
    #             hint_childs_len == 0
    #         ) or
    #         # A PEP 484-compliant "typing.Tuple"-based hint subscripted
    #         # by exactly one child hint *AND* this child hint is the
    #         # empty tuple,..
    #         (
    #             hint.__origin__ is Tuple and
    #             hint_childs_len == 1 and
    #             hint_childs[0] == ()
    #         )
    #     )
    return (
        hint == HINT_PEP585_TUPLE_EMPTY or
        hint == HINT_PEP484_TUPLE_EMPTY
    )

# ....................{ DISAMBIGUATORS                     }....................
#FIXME: Unit test us up, please.
def disambiguate_hint_pep484585646_tuple_sign(hint: Hint) -> HintSign:
    '''
    Disambiguate the passed **tuple type hint** (i.e., :pep:`484`- or
    :pep:`585`-compliant purely fixed- and variable-length tuple type hint *or*
    :pep:`646`-compliant mixed fixed-variadic tuple type hint) ambiguously
    identified by the :data:`.HintSignTuple` sign into whichever of the
    unambiguous :data:`.HintSignPep484585TupleFixed`,
    :data:`.HintSignPep484585TupleVariadic`, or
    :data:`.HintSignPep646TupleFixedVariadic` signs uniquely identify this kind
    of tuple type hint.

    This low-level getter assists the higher-level
    :func:`beartype._util.hint.pep.utilpepget.get_hint_pep_sign_or_none` getter
    to disambiguate the originally ambiguous :data:`.HintSignTuple` sign.

    This low-level getter is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as only function calling this getter is the
    aforementioned higher-level getter, which itself is memoized.

    Caveats
    -------
    **This getter exhibits worst-case** :math:`O(n)` **linear time complexity**
    for :math:`n` the number of child hints subscripting this tuple hint. Since
    this low-level getter is only called by higher-level memoized getters, this
    getter nonetheless effectively exhibits amortized worst-case :math:`O(1)`
    constant time complexity.

    Parameters
    ----------
    hint : Hint
        Tuple type hint to be disambiguated.

    Returns
    -------
    HintSign
        Sign uniquely and unambiguously identifying this hint. Specifically, if
        this hint is a:

        * :pep:`484`- or :pep:`585`-compliant **fixed-length tuple hint** (e.g.,
          of the form ``tuple[{hint_child_1}, ..., {hint_child_N}]``), this
          getter returns :data:`.HintSignPep484585TupleFixed`.
        * :pep:`484`- or :pep:`585`-compliant **variable-length tuple hint**
          (e.g., of the form ``tuple[{hint_child}, ...]``), this getter returns
          :data:`.HintSignPep484585TupleVariadic`.
        * :pep:`646`-compliant **fixed-variable tuple hint** (e.g., of the form
          ``tuple[{hint_child_1}, ..., {type_var_tuple}, ...,
          {hint_child_N}]``), this getter returns
          :data:`.HintSignPep646TupleFixedVariadic`.
    '''
    # print(f'Disambiguating tuple hint {repr(hint)}...')

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import get_hint_pep_args
    from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none

    # ....................{ LOCALS                         }....................
    # Child hints subscripting this parent tuple hint.
    hint_childs = get_hint_pep_args(hint)
    # print(f'hint_childs: {hint_childs}')

    # Number of child hints subscripting this parent tuple hint.
    hint_childs_len = len(hint_childs)

    # ....................{ PEP (484|585) ~ variadic       }....................
    # If this parent tuple hint is subscripted by *NO* child hints, this hint is
    # the unsubscripted "typing.Tuple" type hint factory semantically equivalent
    # to the PEP 484-compliant variable-length tuple hint "typing.Tuple[object,
    # ...]". In this case, return the sign uniquely identifying these hints.
    if not hint_childs_len:
        return HintSignPep484585TupleVariadic
    # Else, this parent tuple hint is subscripted by one or more child hints.

    # ....................{ PEP 646                        }....................
    # For each child hint subscripting this parent tuple hint...
    for hint_child in hint_childs:
        # Sign uniquely identifying this child hint if this child hint is
        # PEP-compliant *OR* "None" otherwise.
        hint_child_sign = get_hint_pep_sign_or_none(hint_child)
        # print(f'Detected hint child {hint_child} sign {hint_child_sign}...')

        # If this child hint is either:
        # * A PEP 646-compliant unpacked type variable tuple *OR*...
        # * A PEP 646-compliant unpacked child tuple hint...
        # ...then this parent tuple hint is PEP 646-compliant. In this case,
        # return the sign uniquely identifying these hints.
        if hint_child_sign in HINT_SIGNS_PEP646_TUPLE_HINT_CHILD_UNPACKED:
            return HintSignPep646TupleFixedVariadic
        # Else, this child hint is PEP 484- or 585-compliant.
    # Else, all child hints subscripting this parent tuple hint are *ONLY* PEP
    # 484- or 585-compliant, implying this parent tuple hint to itself be PEP
    # 484- or 585-compliant.

    # ....................{ PEP (484|585) ~ variadic       }....................
    # Return the sign uniquely identifying either...
    return (
        # Variable-length tuple hints if this hint is variadic;
        HintSignPep484585TupleVariadic
        if is_hint_pep484585646_tuple_variadic(hint) else
        # Fixed-length tuple hints otherwise.
        HintSignPep484585TupleFixed
    )

# ....................{ FACTORIES                          }....................
#FIXME: Unit test us up, please.
def make_hint_pep484585_tuple_fixed(hints_child: TupleHints) -> Hint:
    '''
    Dynamically create and return a new :pep:`484`- or :pep:`585`-compliant
    **fixed-length tuple hint** of the form ``tuple[{hint_child1}, ...,
    {hint_childN}]`` subscripted by all child hints in the passed tuple.

    Parameters
    ----------
    hints_child : TupleHints
        Tuple of all child hints with which to subscript the returned hint.

    Returns
    -------
    Hint
        Fixed-length tuple hint subscripted by these child hints.
    '''
    assert isinstance(hints_child, tuple), f'{repr(hints_child)} not tuple.'

    # Return a fixed-length tuple type hint subscripted by these child hints,
    # defined as either...
    return (
        #FIXME: Uncomment after dropping Python <= 3.10 support, which raises a
        #"SyntaxError" if we even try doing this. *SADNESS*
        # # If the active Python interpreter targets Python >= 3.11 and thus
        # # supports list unpacking in arbitrary expressions, prefer an efficient
        # # expression leveraging a list unpacking;
        # Tuple[*hints]
        # if IS_PYTHON_AT_LEAST_3_11 else
        # Else, the active Python interpreter targets Python <= 3.10.
        #
        # Dynamically subscript the builtin "tuple" type.
        Tuple.__class_getitem__(hints_child)  # type: ignore[attr-defined]
    )
