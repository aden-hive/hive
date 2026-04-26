#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`646`- and :pep:`692`-compliant **tuple type hint utilities**
(i.e., low-level callables generically applicable to :pep:`646`-compliant tuple
type hints *and* :pep:`692`-compliant unpacked typed dictionaries alike).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep646692Exception
from beartype._cave._cavefast import (
    HintGenericSubscriptedType,
    HintPep646TypeVarTupleType,
)
from beartype._data.typing.datatypingport import (
    Hint,
    TupleHints,
)
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.hint.sign.datahintsigns import (
    HintSignPep646TypeVarTupleUnpacked,
    HintSignPep692TypedDictUnpacked,
)

# ....................{ RAISERS                            }....................
#FIXME: Unit test us up, please. *sigh*
def die_unless_hint_pep646_typevartuple_packed(hint: Hint) -> None:
    '''
    Raise an exception unless the passed hint is a :pep:`646`-compliant **packed
    type variable tuple** (i.e., :class:`TypeVarTuple` object).

    Parameters
    ----------
    hint : Hint
        Hint to be validated.

    Raises
    ------
    BeartypeDecorHintPep646692Exception
        If this hint is *not* a :pep:`646`-compliant packed type variable tuple.
    '''

    # If this hint is *NOT* a PEP 646-compliant type variable tuple, raise an
    # exception.
    if not isinstance(hint, HintPep646TypeVarTupleType):
        raise BeartypeDecorHintPep646692Exception(
            f'Type hint {repr(hint)} not PEP 646 type variable tuple '
            f'(i.e., "typing.TypeVarTuple" object).'
        )
    # Else, this hint is a PEP 646-compliant type variable tuple.

# ....................{ TESTERS                            }....................
#FIXME: *INSUFFICIENT.* Technically, it's true that *MOST* real-world unpacked
#tuples are low-level C objects created with the "*" unary prefix and thus
#correctly matched by this tester. That said, *SOME* real-world unpacked
#tuples are high-level pure-Python objects created by the "typing.Unpack[...]"
#hint factory and thus incorrectly *NOT* matched by this tester.
#
#Notably, PEP 696 explicitly insists that the unpacked tuple hint
#"Unpack[tuple[str, int]]" is semantically equivalent to the unpacked tuple hint
#"*tuple[str, int]":
#    DefaultTs = TypeVarTuple("DefaultTs", default=Unpack[tuple[str, int]])
#
#That said, it could be tricky to attempt to match both with this low-level
#tester function. Since this tester is *ONLY* called by
#get_hint_pep_sign_or_none(), it'd be better to go the disambiguation route.
#Notably:
#* Generalize the disambiguate_hint_pep646692_unpacked_sign() function defined
#  below to additionally support unpacked tuple hints. *shrug*
#FIXME: Unit test us up, please.
def is_hint_pep646_tuple_unpacked_prefix(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed hint is a :pep:`646`-compliant **prefix-based
    unpacked child tuple hint** (i.e., of the form "*tuple[{hint_child_child_1},
    ..., {hint_child_child_M}]" subscripting a parent tuple hint of the form
    "tuple[{hint_child_1}, ..., *tuple[{hint_child_child_1}, ...,
    {hint_child_child_M}], ..., {hint_child_N}]").

    If this tester returns :data:`True`, this unpacked child tuple hint is
    guaranteed to define the ``__args__`` dunder attribute to be either:

    * A 2-tuple ``({hint_child}, ...)``, in which case this child tuple hint
      unpacks to a variable-length tuple hint over ``{hint_child}`` types.
    * An n-tuple ``({hint_child_1}, ..., {hint_child_N})`` where ``...`` in this
      case is merely a placeholder connoting one or more child hints, in which
      case this child tuple hint unpacks to a fixed-length tuple hint over these
      exact ``{hint_child_I}`` types.

    This getter is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation trivially reduces to
    an efficient one-liner.

    Motivation
    ----------
    Interestingly, even detecting accursed unpacked child tuple hints at runtime
    is highly non-trivial. They do *not* have a sane unambiguous type,
    significantly complicating detection. For some utterly inane reason, their
    type is simply the ambiguous type :class:`types.GenericAlias` (i.e.,
    :class:`.HintGenericSubscriptedType`). That... wasn't what we were expecting
    *at all*. For example, under Python 3.13:

    .. code-block:: python

       # Note that Python *REQUIRES* unpacked tuple type hints to be embedded in
       # some larger syntactic construct. So, just throw it into a list. This is
       # insane, because we're only going to rip it right back out of that list.
       # Blame the CPython interpreter. *shrug*
       >>> yam = [*tuple[int, str]]

       # Arbitrary unpacked tuple type hint.
       >>> yim = yam[0]
       >>> repr(yim)
       *tuple[int, str]  # <-- gud
       >>> type(yim)
       <class 'types.GenericAlias'>  # <-- *TOTALLY NOT GUD. WTF, PYTHON!?*

       # Now look at this special madness. The type of this object isn't even in
       # its method-resolution order (MRO)!?!? I've actually never seen that
       # before. The type of any object is *ALWAYS* the first item in its
       # method-resolution order (MRO), isn't it? I... guess not. *facepalm*
       >>> yim.__mro__
       (<class 'tuple'>, <class 'object'>)

       # So, "*tuple[int, str]" is literally both a tuple *AND* a "GenericAlias"
       # at the same time. That makes no sense, but here we are. What are the
       # contents of this unholy abomination?
       >>> dir(yim)
       ['__add__', '__args__', '__bases__', '__class__', '__class_getitem__',
       '__contains__', '__copy__', '__deepcopy__', '__delattr__', '__dir__',
       '__doc__', '__eq__', '__format__', '__ge__', '__getattribute__',
       '__getitem__', '__getnewargs__', '__getstate__', '__gt__', '__hash__',
       '__init__', '__init_subclass__', '__iter__', '__le__', '__len__', '__lt__',
       '__mro_entries__', '__mul__', '__ne__', '__new__', '__origin__',
       '__parameters__', '__reduce__', '__reduce_ex__', '__repr__', '__rmul__',
       '__setattr__', '__sizeof__', '__str__', '__subclasshook__',
       '__typing_unpacked_tuple_args__', '__unpacked__', 'count', 'index']

       # Lotsa weird stuff there, honestly. Let's poke around a bit.
       >>> yim.__args__
       (<class 'int'>, <class 'str'>)  # <-- gud
       >>> yim.__typing_unpacked_tuple_args__
       (<class 'int'>, <class 'str'>)  # <-- gud, albeit weird
       >>> yim.__unpacked__
       True  # <-- *WTF!?!? what the heck is this nonsense?*
       >>> yim.__origin__
       tuple  # <-- so you lie about everything, huh?

    Basically, the above means that the only means of reliably detecting an
    unpacked tuple hint at runtime is by heuristically introspecting for both
    the existence *and* values of various dunder attributes exhibited above.
    Introspecting merely the existence of these attributes is insufficient; only
    the combination of both existence and values suffices to effectively
    guarantee disambiguity. Likewise, introspecting merely one or even two of
    these attributes is insufficient; only the combination of three or more of
    these attributes suffices to effectively guarantee disambiguity.

    Note there *are* no means of actually guaranteeing disambiguity. Malicious
    third-party objects could attempt to masquerade as unpacked child tuple
    hints by defining similar dunder attributes. We can only reduce the
    likelihood of false positives by increasing the number of dunder attributes
    introspected by this tester. Don't blame us. We didn't start the fire.

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this hint is an unpacked child tuple hint.
    '''
    # print(f'dir({hint}): {dir(hint)}')
    # print(f'{hint}.__class__: {hint.__class__}')
    # print(f'{hint}.__args__: {getattr(hint, '__args__', False)}')
    # print(f'{hint}.__typing_unpacked_tuple_args__: {getattr(hint, '__typing_unpacked_tuple_args__', True)}')

    # Return true only if...
    return (
        # This hint's type is that of all unpacked child tuple hints (as well as
        # many other unrelated first- and third-party hints, sadly) *AND*...
        hint.__class__ is HintGenericSubscriptedType and
        (
            # The tuple of all child hints subscripting this parent hint is also
            # the tuple of all child hints subscripting this unpacked child
            # tuple hint. Since only unpacked child tuple hints *SHOULD* define
            # the PEP 646-compliant and frankly outrageously verbose
            # "__typing_unpacked_tuple_args__" dunder attribute, this
            # equivalence *SHOULD* suffice to disambiguate this hint as an
            # unpacked child tuple hint.
            getattr(hint, '__args__', False) ==
            getattr(hint, '__typing_unpacked_tuple_args__', True)
        )
        #FIXME: Probably unnecessary for the moment. Let's avoid violating
        #fragile privacy encapsulation any more than we must, please. *sigh*
        # # This hint's method-resolution order (MRO) is that of all unpacked
        # # child tuple hints *AND*...
        # getattr(hint, '__mro__', None) == _PEP646_HINT_TUPLE_UNPACKED_MRO and  # pyright: ignore
        # # This hint defines a dunder attribute uniquely defined *ONLY* by
        # # unpacked child tuple hints with a value guaranteed to be set by all
        # # unpacked child tuple hints.
        # getattr(hint, '__unpacked__', None) is True
    )

# ....................{ DISAMBIGUATORS                     }....................
#FIXME: Unit test us up, including:
#* "typing.Unpack[tuple[...]]" type hints. See discussion above. *sigh*
#* Unsubscripted "typing.Unpack" type hints, which should be unconditionally
#  *PROHIBITED.* They signify nothing. "typing.Unpack" should *ALWAYS* be
#  subscripted by at least something.
def disambiguate_hint_pep646692_unpacked_sign(hint: Hint) -> HintSign:
    '''
    Disambiguate the passed **unpacked type hint** (i.e., :pep:`646`- or
    :pep:`692`-compliant ``typing.Unpack[...]`` hint) ambiguously identified by
    the :data:`.HintSignUnpack` sign into whichever of the unambiguous
    :data:`.HintSignPep646TypeVarTupleUnpacked` or
    :data:`.HintSignPep692TypedDictUnpacked` signs uniquely identify this kind
    of unpacked type hint.

    This low-level getter assists the higher-level
    :func:`beartype._util.hint.pep.utilpepget.get_hint_pep_sign_or_none` getter
    to disambiguate the originally ambiguous :data:`.HintSignUnpack` sign.

    This low-level getter is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as only function calling this getter is the
    aforementioned higher-level getter, which itself is memoized.

    Parameters
    ----------
    hint : Hint
        Unpacked type hint to be disambiguated.

    Returns
    -------
    HintSign
        Sign uniquely and unambiguously identifying this hint. Specifically, if
        this hint is a:

        * :pep:`646`-compliant **unpacked type variable tuple** (i.e., child
          hint of the form "*{typevartuple}" where "{typevartuple}" is an
          instance of the :class:`typing.TypeVarTuple` type), this getter
          returns :data:`.HintSignPep646TypeVarTupleUnpacked`.
        * :pep:`692`-compliant **unpacked typed dictionary** (i.e., hint of the
          form "*{typeddict}" where "{typeddict}" is an instance of the
          :class:`typing.TypedDict` type factory), this getter
          returns :data:`.HintSignPep692TypedDictUnpacked`.

    Raises
    ------
    BeartypeDecorHintPep646692Exception
        If this hint is neither :pep:`646`- nor :pep:`692`-compliant (i.e., is a
        ``typing.Unpack[...]`` hint subscripted by a child hint that is neither
        an unpacked type variable tuple nor unpacked typed dictionary).
    '''
    # Note that this lower-level getter is directly called by the higher-level
    # get_hint_pep_sign_or_none() getter. Ergo, the former *CANNOT* recursively
    # pass the passed hint to the latter (e.g., as a means of validating that
    # the passed hint is indeed a "typing.Unpack[...]" hint). This getter *MUST*
    # assume the caller to pass a "typing.Unpack[...]" hint. It is what it is.
    # print(f'Disambiguating unpack hint {repr(hint)}...')

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._util.hint.pep.proposal.pep589 import is_hint_pep589
    from beartype._util.hint.pep.utilpepget import get_hint_pep_args
    from beartype._util.hint.utilhinttest import die_as_hint_unsupported

    # ....................{ LOCALS                         }....................
    # Child hints subscripting this parent tuple hint.
    hint_childs = get_hint_pep_args(hint)
    # print(f'hint_childs: {hint_childs}')

    # If this parent unpack hint is subscripted by exactly one child hint...
    #
    # Note that the "typing.Unpack" type hint factory has already pre-validated
    # this factory to accept at most one child type hint. Nonetheless, one can
    # never be too careful where the "typing" module is concerned:
    #     >>> from typing import Unpack
    #     >>> Unpack['shaking', 'my', 'head']
    #     TypeError: typing.Unpack accepts only single type. Got ('shaking',
    #     'my', 'head').
    if len(hint_childs) == 1:
        # Child hint subscripting this parent unpack hint.
        hint_child = hint_childs[0]

        # If this child hint is a PEP 646-compliant type variable tuple, return
        # the sign disambiguating this parent unpack hint as a PEP 646-compliant
        # unpacked type variable tuple.
        if isinstance(hint_child, HintPep646TypeVarTupleType):
            return HintSignPep646TypeVarTupleUnpacked
        # Else, this child hint is *NOT* a PEP 646-compliant unpacked type
        # variable tuple.
        #
        # If this child hint is a PEP 589-compliant typed dictionary, return
        # the sign disambiguating this parent unpack hint as a PEP 692-compliant
        # unpacked typed dictionary.
        elif is_hint_pep589(hint_child):
            return HintSignPep692TypedDictUnpacked
        # Else, this child hint is *NOT* a PEP 589-compliant typed dictionary.
    # Else, this parent unpack hint is subscripted by either no child hints *OR*
    # two or more child hints.

    # ....................{ EXCEPTION                      }....................
    # Raise an exception. The child hint subscripting this parent unpack hint is
    # unrecognized and thus either PEP-noncompliant *OR* PEP-compliant but
    # unsupported by beartype. In either case, the caller deserves to know.
    die_as_hint_unsupported(
        hint=hint, exception_cls=BeartypeDecorHintPep646692Exception)

# ....................{ FACTORIES ~ tuple                  }....................
def make_hint_pep646_tuple_unpacked_prefix(hints_child: TupleHints) -> Hint:
    '''
    Dynamically create and return a new :pep:`646`-compliant **prefix-based
    unpacked child tuple hint** (i.e., of the form "*tuple[{hint_child_child_1},
    ..., {hint_child_child_M}]" subscripting a parent tuple hint of the form
    "tuple[{hint_child_1}, ..., *tuple[{hint_child_child_1}, ...,
    {hint_child_child_M}], ..., {hint_child_N}]") subscripted by all child hints
    in the passed tuple.

    This factory exists to streamline access to unpacked child tuple hints,
    whose definition is otherwise non-trivial. Python requires unpacked child
    tuple hints to be syntactically embedded inside larger containers -- even if
    those hints are semantically invalid inside those containers: e.g.,

    .. code-block:: pycon

       >>> [*tuple[int, str]]
       [*tuple[int, str]]  # <-- makes no sense, but ok.
       >>> *tuple[int, str]
       SyntaxError: can't use starred expression here  # <-- this is awful.

    This factory circumvents these non-trivial usability concerns.

    Parameters
    ----------
    hints_child : TupleHints
        Tuple of all child hints to be unpacked.

    Returns
    -------
    Hint
        Unpacked child tuple hint subscripted by these child hints.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.proposal.pep484585646 import (
        make_hint_pep484585_tuple_fixed)

    # PEP 585-compliant tuple hint subscripted by these child hints.
    pep585_tuple = make_hint_pep484585_tuple_fixed(hints_child)

    #FIXME: Uncomment after dropping Python <= 3.10 support, which raises a
    #"SyntaxError" if we even try doing this. *SADNESS*
    # return *hint

    # Tuple subscripted by this PEP 646-compliant type tuple hint unpacked into
    # a PEP 646-compliant unpacked tuple child hint. This is insane, because
    # we're only going to rip this tuple child hint right back out of this
    # tuple. Blame the Python <= 3.10 interpreter.
    #
    # Note that a tuple was intentionally chosen for both space and time
    # efficiency. Although *ANY* container would satisfy Python <= 3.10, a tuple
    # has the advantage of being Python's most optimized container type.
    tuple_unpacked_parent = (*pep585_tuple,)  # type: ignore[valid-type]

    # PEP 646-compliant unpacked child tuple hint subscripting this parent.
    tuple_unpacked = tuple_unpacked_parent[0]

    # Return this unpacked child tuple hint.
    return tuple_unpacked

# ....................{ FACTORIES ~ typevartuple           }....................
#FIXME: Unit test us up, please. *sigh*
def make_hint_pep646_typevartuple_unpacked_prefix(
    hint: HintPep646TypeVarTupleType) -> Hint:
    '''
    Dynamically create and return a new :pep:`646`-compliant **prefix-based
    unpacked type variable tuple** (i.e., of the form ``*hint``) prefixing the
    passed type variable tuple by the unary unpacking ``*`` operator.

    Parameters
    ----------
    hint: HintPep646TypeVarTupleType
        Type variable tuple to be unpacked.

    Returns
    -------
    Hint
        Unpacked type variable tuple synthesized from this type variable tuple.

    See Also
    --------
    :func:`.make_hint_pep646_tuple_unpacked_prefix`
        Further discussion on prefix-based unpacking.
    '''

    # If this hint is *NOT* a type variable tuple, raise an exception.
    die_unless_hint_pep646_typevartuple_packed(hint)  # pyright: ignore
    # Else, this hint is a type variable tuple.

    #FIXME: Uncomment after dropping Python <= 3.10 support, which raises a
    #"SyntaxError" if we even try doing this. *SADNESS*
    # return *hint

    # Tuple subscripted by this PEP 646-compliant type variable tuple unpacked
    # into a PEP 646-compliant unpacked type variable tuple. This is insane,
    # because we're only going to rip this unpacked type variable tuple right
    # back out of this tuple. Blame the Python <= 3.10 interpreter.
    #
    # Note that a tuple was intentionally chosen for both space and time
    # efficiency. Although *ANY* container would satisfy Python <= 3.10, a tuple
    # has the advantage of being Python's most optimized container type.
    typevartuple_unpacked_parent = (*hint,)  # type: ignore[misc]

    # PEP 646-compliant unpacked child tuple hint subscripting this parent.
    typevartuple_unpacked = typevartuple_unpacked_parent[0]

    # Return this unpacked type variable tuple.
    return typevartuple_unpacked



#FIXME: Unit test us up, please. *sigh*
def make_hint_pep646_typevartuple_unpacked_subbed(
    hint: HintPep646TypeVarTupleType) -> Hint:
    '''
    Dynamically create and return a new :pep:`646`-compliant
    **subscription-based unpacked type variable tuple** (i.e., of the form
    ``typing.Unpack[hint]``) subscripted by the passed type variable tuple.

    Parameters
    ----------
    hint: HintPep646TypeVarTupleType
        Type variable tuple to be unpacked.

    Returns
    -------
    Hint
        Unpacked type variable tuple subscripted by this type variable tuple.
    '''

    # Avoid version-specific imports.
    #
    # Note that the PEP 646-compliant "typing.Unpack[...]" hint factory is
    # defined *ONLY* under Python >= 3.11. Thankfully, the PEP 646-compliant
    # "typing.TypeVarTuple" type is also defined *ONLY* under Python >= 3.11.
    # Since the caller passed an instance of that type, the active Python
    # interpreter *MUST* by definition target Python >= 3.11.
    from beartype.typing import Unpack  # pyright: ignore

    # If this hint is *NOT* a type variable tuple, raise an exception.
    die_unless_hint_pep646_typevartuple_packed(hint)  # pyright: ignore
    # Else, this hint is a type variable tuple.

    # Return this unpacked child tuple hint.
    return Unpack.__getitem__(hint)  # pyright: ignore
