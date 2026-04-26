#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`585`-compliant type hint utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep585Exception
from beartype.typing import (
    Dict,
    TypeVar,
)
from beartype._cave._cavefast import HintGenericSubscriptedType
from beartype._data.typing.datatypingport import (
    Hint,
    TupleHints,
)
from beartype._data.typing.datatyping import (
    TupleTypeVars,
    TypeException,
)
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.kind.maplike.utilmapset import update_mapping_keys
from beartype._util.py.utilpyversion import IS_PYTHON_AT_LEAST_3_11

# ....................{ HINTS                              }....................
HINT_PEP585_TUPLE_EMPTY = tuple[()]
'''
:pep:`585`-compliant empty fixed-length tuple type hint.
'''

# ....................{ RAISERS                            }....................
def die_unless_hint_pep585_generic(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep585Exception,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is a :pep:`585`-compliant
    **generic** (i.e., either a type originally subclassing at least one
    subscripted :pep:`585`-compliant pseudo-superclass *or* an object
    subscripted by one or more child type hints originating from such a type).

    This raiser raises an exception unless this object is either a subscripted
    or unsubscripted :pep:`585`-compliant generic.

    Parameters
    ----------
    hint : Hint
        Object to be validated.
    exception_cls : TypeException
        Type of exception to be raised. Defaults to
        :exc:`BeartypeDecorHintPep585Exception`.
    exception_prefix : str, optional
        Human-readable substring prefixing the representation of this object in
        the exception message. Defaults to the empty string.

    Raises
    ------
    exception_cls
        If this object is *not* a :pep:`585`-compliant generic.
    '''

    # If this object is *NOT* a PEP 585-compliant generic, raise an exception.
    if not is_hint_pep585_generic(hint):
        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} not PEP 585 generic.')
    # Else, this object is a PEP 585-compliant generic.

# ....................{ TESTERS                            }....................
def is_hint_pep585_builtin_subbed(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed object is a :pep:`585`-compliant
    **subscripted builtin type hint** (i.e., C-based type hint instantiated by
    subscripting either a concrete builtin container class like :class:`list` or
    :class:`tuple` *or* an abstract base class (ABC) declared by the
    :mod:`collections.abc` submodule like :class:`collections.abc.Iterable` or
    :class:`collections.abc.Sequence`).

    This tester additionally returns :data:`True` for third-party type hints
    whose types subclass the :class:`types.GenericAlias` superclass, including:

    * ``numpy.typing.NDArray[...]`` type hints.

    This tester is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Caveats
    -------
    **This tester returns** :data:`False` for :pep:`585`-compliant generics,
    which fail to satisfy the same API as all other :pep:`585`-compliant type
    hints. Why? Because :pep:`560`-type erasure erases the low-level superclass
    detected by this tester on :pep:`585`-compliant generics immediately after
    those generics are declared, preventing their subsequent detection as
    :pep:`585`-compliant. Instead, :pep:`585`-compliant generics are only
    detectable by calling either:

    * The high-level PEP-agnostic
      :func:`beartype._util.hint.pep.utilpeptest.is_hint_pep484585_generic`
      tester.
    * The low-level :pep:`585`-specific :func:`.is_hint_pep585_generic` tester.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a :pep:`585`-compliant type hint.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.proposal.pep484585.generic.pep484585gentest import (
        is_hint_pep484585_generic)

    # Return true only if this hint...
    return (
        # Is either a PEP 484- or -585-compliant subscripted generic or
        # PEP 585-compliant builtin *AND*...
        isinstance(hint, HintGenericSubscriptedType) and
        # Is *NOT* a PEP 484- or -585-compliant subscripted generic.
        not is_hint_pep484585_generic(hint)  # pyright: ignore
    )


def is_hint_pep585_generic(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed object is a :pep:`585`-compliant **generic**
    (i.e., either a type originally subclassing at least one subscripted
    :pep:`585`-compliant pseudo-superclass *or* an object subscripted by one or
    more child type hints originating from such a type).

    This tester returns :data:`True` if this object is either a subscripted or
    unsubscripted :pep:`585`-compliant generic.

    This tester is memoized for efficiency.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a :pep:`585`-compliant generic.
    '''

    # Return true only if object is either...
    return (
        # A PEP 585-compliant unsubscripted generic *OR*...
        is_hint_pep585_generic_unsubbed(hint) or
        # A PEP 585-compliant subscripted generic.
        is_hint_pep585_generic_subbed(hint)
    )


#FIXME: Unit test us up, please.
def is_hint_pep585_generic_subbed(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed object is a :pep:`585`-compliant
    **subscripted generic** (i.e., object subscripted by one or more child type
    hints originating from a type originally subclassing at least one
    subscripted :pep:`585`-compliant pseudo-superclass).

    This tester is memoized for efficiency.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a :pep:`585`-compliant subscripted
        generic.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import (
        get_hint_pep_origin_or_none)

    # Arbitrary object originating this hint if any *OR* "None" otherwise.
    hint_origin = get_hint_pep_origin_or_none(hint)

    # Return true only if...
    return (
        # An object originates this hint *AND*...
        hint_origin is not None and
        # This origin object is an unsubscripted generic type, which would then
        # imply this hint to be a subscripted generic. If this strikes you as
        # insane, you're not alone.
        is_hint_pep585_generic_unsubbed(hint_origin)
    )


#FIXME: Unit test us up, please.
@callable_cached
def is_hint_pep585_generic_unsubbed(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed object is a :pep:`585`-compliant
    **unsubscripted generic** (i.e., type originally subclassing at least one
    subscripted :pep:`585`-compliant pseudo-superclass).

    This tester is memoized for efficiency.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a :pep:`585`-compliant unsubscripted
        generic.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import get_hint_pep_args
    from beartype._util.hint.pep.proposal.pep560 import (
        is_hint_pep560,
        iter_hint_pep560_bases_unerased,
    )

    # If it is *NOT* the case that...
    if not (
        # This hint is a type *AND*...
        isinstance(hint, type) and
        # This type is PEP 560-compliant and thus subclasses one or more
        # pseudo-superclasses *AND*...
        is_hint_pep560(hint) and
        # Either...
        (
            # The active Python interpreter targets Python >= 3.11 *OR*...
            IS_PYTHON_AT_LEAST_3_11 or
            # The active Python interpreter targets Python <= 3.10. In this
            # case, a simple subclass test does *NOT* suffice to detect a PEP
            # 585-compliant unsubscripted generic. Why? Because Python <=
            # 3.10 implements PEP 585-compliant subscripted generics as types!
            # But PEP 585-compliant unsubscripted generics are also types! Lo:
            #     $ python3.10
            #     >>> class MuhGeneric(list): pass
            #     >>> isinstance(MuhGeneric, type)
            #     True  # <-- good
            #     >>> isinstance(MuhGeneric[str], type)
            #     True  # <-- *BAD*
            #
            #     $ python3.11
            #     >>> class MuhGeneric(list): pass
            #     >>> isinstance(MuhGeneric, type)
            #     True  # <-- good
            #     >>> isinstance(MuhGeneric[str], type)
            #     False  # <-- good
            #
            # Disambiguating this edge case requires also detecting whether
            # this PEP 484-compliant generic is subscripted by one or more
            # child hints.
            #
            # This PEP 484-compliant generic is unsubscripted.
            not get_hint_pep_args(hint)
        )
    # Then this hint *CANNOT* be a PEP 585-compliant unsubscripted generic. In
    # this case, return false immediately.
    ):
        return False
    # Else, this hint is a PEP 560-compliant type subclassing one or more
    # pseudo-superclasses. Since this type *COULD* be a PEP 585-compliant
    # unsubscripted generic, continue testing.

    #FIXME: [SPEED] Optimize into a "while" loop. *sigh*
    # For each transitive pseudo-superclass of this PEP 560-compliant hint...
    #
    # Unsurprisingly, PEP 585-compliant generics have absolutely *NO*
    # commonality with PEP 484-compliant generics. While the latter are
    # trivially detectable as subclassing "typing.Generic" after type erasure,
    # the former are *NOT*. The only means of deterministically deciding whether
    # or not a hint is a PEP 585-compliant generic is if:
    # * That class defines both the __class_getitem__() dunder method *AND* the
    #   "__orig_bases__" instance variable. Note that this condition in and of
    #   itself is insufficient to decide PEP 585-compliance as a generic. Why?
    #   Because these dunder attributes have been standardized under various
    #   PEPs and may thus be implemented by *ANY* arbitrary classes.
    # * The "__orig_bases__" instance variable is a non-empty tuple.
    # * One or more objects listed in that tuple are PEP 585-compliant C-based
    #   subscripted generics (e.g., "list[str]").
    #
    # Note we could technically also test that this hint defines the
    # __class_getitem__() dunder method. Since that test would *NOT* suffice to
    # ensure that this hint is a PEP 585-compliant generic, however, there
    # exists little benefit to doing so.
    for hint_base in iter_hint_pep560_bases_unerased(hint):
        # If this transitive pseudo-superclass is itself a PEP 585-compliant
        # subscripted generic (e.g., "list[str]"), the passed hint transitively
        # subclasses a PEP 585-compliant generic. By transitivity, this hint
        # *MUST* be a PEP 585-compliant generic as well. Return true!
        if is_hint_pep585_builtin_subbed(hint_base):
            return True
        # Else, this pseudo-superclass is *NOT* a PEP 585-compliant subscripted
        # generic. In this case, continue to the next pseudo-superclass.

    # Since *NO* such pseudo-superclasses are PEP 585-compliant subscripted
    # generics, this hint is *NOT* a PEP 585-compliant generic. In this case,
    # return false.
    return False

# ....................{ GETTERS                            }....................
def get_hint_pep585_generic_bases_unerased(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep585Exception,
    exception_prefix: str = '',
) -> TupleHints:
    '''
    Tuple of all unerased :pep:`585`-compliant **pseudo-superclasses** (i.e.,
    :mod:`typing` objects originally listed as superclasses prior to their
    implicit type erasure under :pep:`560`) of the passed :pep:`585`-compliant
    **generic** (i.e., class subclassing at least one non-class
    :pep:`585`-compliant object).

    This getter is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.
    exception_cls : TypeException
        Type of exception to be raised. Defaults to
        :exc:`BeartypeDecorHintPep585Exception`.
    exception_prefix : str, optional
        Human-readable substring prefixing the representation of this object in
        the exception message. Defaults to the empty string.

    Returns
    -------
    Tuple[Hint, ...]
        Tuple of the one or more unerased pseudo-superclasses of this
        :pep:`585`-compliant generic.

    Raises
    ------
    exception_cls
        If this hint is *not* a :pep:`585`-compliant generic.

    See Also
    --------
    :func:`beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget.get_hint_pep484585_generic_bases_unerased`
        Further details.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget import (
        get_hint_pep484585_generic_type_or_none)

    # If this hint is *NOT* a class, reduce this hint to the object originating
    # this hint if any. See the is_hint_pep484_generic() tester for details.
    hint = get_hint_pep484585_generic_type_or_none(hint)  # type: ignore[assignment]

    # If this hint is *NOT* a PEP 585-compliant generic, raise an exception.
    die_unless_hint_pep585_generic(
        hint=hint,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this hint is a PEP 585-compliant generic.

    # Return the tuple of all unerased pseudo-superclasses of this generic.
    # While the "__orig_bases__" dunder instance variable is *NOT* guaranteed
    # to exist for PEP 484-compliant generic types, this variable is guaranteed
    # to exist for PEP 585-compliant generic types. Thanks for small favours.
    return hint.__orig_bases__  # pyright: ignore


@callable_cached
def get_hint_pep585_generic_typeargs_packed(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep585Exception,
    exception_prefix: str = '',
) -> TupleTypeVars:
    '''
    Tuple of all **unique type variables** (i.e., non-duplicated
    :class:`TypeVar` objects) originally parametrizing the passed
    :pep:`585`-compliant unsubscripted generic if this generic was parametrized
    by one or more type variables *or* the empty tuple otherwise (i.e., if this
    generic is unparametrized).

    This getter is memoized for efficiency.

    Motivation
    ----------
    This getter mimics the behaviour of the ``__parameters__`` dunder attributes
    for :pep:`484`-compliant generics, whose values similarly collect the tuples
    of all unique type variables originally parametrizing those generics. Sadly,
    the current implementation of :pep:`585` under at least Python 3.9—3.13 is
    fundamentally broken with respect to parametrized generics. While
    :pep:`484`-compliant generics properly propagate type variables from
    pseudo-superclasses to subclasses, :pep:`585` fails to do so. This getter
    "fills in the gaps" by recovering these type variables from parametrized
    :pep:`585`-compliant generics by iteratively constructing a new tuple from
    the type variables parametrizing all pseudo-superclasses of this generic.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.
    exception_cls : TypeException
        Type of exception to be raised. Defaults to
        :exc:`BeartypeDecorHintPep585Exception`.
    exception_prefix : str, optional
        Human-readable substring prefixing the representation of this object in
        the exception message. Defaults to the empty string.

    Returns
    -------
    Tuple[TypeVar, ...]
        Either:

        * If this :pep:`585`-compliant generic is:

          * Subscripted, the empty tuple. This mirrors the behaviour of the
            ``__parameters__`` dunder attribute defined on :pep:`484`-compliant
            subscripted generics, which is *always* set to the empty tuple.
          * Unsubscripted, the tuple of all unique type variables parametrizing
            this unsubscripted generic

        * Else, the empty tuple.

    Raises
    ------
    BeartypeDecorHintPep585Exception
        If this hint is *not* a :pep:`585`-compliant generic.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import get_hint_pep_typeargs_packed

    # If this hint is *NOT* a PEP 585-compliant generic, raise an exception.
    die_unless_hint_pep585_generic(
        hint=hint,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this hint is a PEP 585-compliant generic.

    # Tuple of all type variables parametrizing this generic if this is a PEP
    # 585-compliant subscripted generic *OR* "None" otherwise (i.e., is a PEP
    # 585-compliant unsubscripted generic). For known reasons, the
    # "__parameters__" dunder attribute is defined correctly for PEP
    # 585-compliant subscripted (but *NOT* unsubscripted) generics. *shrug*
    hint_typevars = getattr(hint, '__parameters__', None)

    # If this tuple is defined, return this tuple as is.
    if hint_typevars is not None:
        return hint_typevars
    # Else, this tuple is undefined. In this case, synthetically reconstruct
    # this tuple for this PEP 585-compliant unsubscripted generic.

    # Tuple of all pseudo-superclasses of this unsubscripted generic.
    hint_bases = get_hint_pep585_generic_bases_unerased(hint)

    # Dictionary mapping from all type variables parametrizing these
    # pseudo-superclasses to the "None" singleton, thus preserving the ordering
    # of these type variables while yet discarding duplicate type variables
    # parametrizing multiple pseudo-superclasses.
    #
    # Note that:
    # * A dictionary rather than set is intentionally leveraged. Why? Ordering.
    #   Order of type variables is *EXTREMELY* significant (e.g., when mapping
    #   type variables to child hints in a type variable lookup table). Whereas
    #   dictionaries preserve insertion order as of Python >= 3.7, sets
    #   currently do *NOT*. Since this algorithm *ONLY* employs a dictionary to
    #   preserve insertion order, the values of this dictionary are irrelevant
    #   and thus unconditionally set to the "None" singleton. I sigh so hard.
    # * The following inefficient iteration *CANNOT* be trivially reduced to a
    #   dictionary comprehension, as each get_hint_pep_typeargs_packed() call returns a
    #   tuple of type variables rather than a single type variable to be added
    #   to this dictionary.
    hint_typevars_to_none: Dict[TypeVar, None] = dict()

    # For each such pseudo-superclass...
    for hint_base in hint_bases:
        # Tuple of the zero or more type variables parametrizing this
        # pseudo-superclass.
        hint_base_typevars = get_hint_pep_typeargs_packed(hint_base)
        # print(f'hint_base_typevars: {hint_base} [{get_hint_pep_typeargs_packed(hint_base)}]')

        # Efficiently add these type variables as new keys of this dictionary.
        update_mapping_keys(hint_typevars_to_none, hint_base_typevars)

    # Return a tuple coerced from the keys of this dictionary.
    return tuple(hint_typevars_to_none.keys())
