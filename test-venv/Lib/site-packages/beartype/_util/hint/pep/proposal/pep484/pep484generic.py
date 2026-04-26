#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`-compliant **generic type hint utilities** (i.e.,
callables generically applicable to :pep:`484`-compliant generic classes).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep484Exception
from beartype.typing import Generic
from beartype._data.cls.datacls import TYPES_PEP484544_GENERIC
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import TypeException
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.cls.utilclstest import is_type_subclass
from beartype._util.py.utilpyversion import IS_PYTHON_AT_LEAST_3_11

# ....................{ TESTERS                            }....................
#FIXME: Unit test us up, please.
def is_hint_pep484_generic_subbed(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed object is a :pep:`484`-compliant
    **subscripted generic** (i.e., object subscripted by one or more child type
    hints originating from a :class:`typing.Generic` subclass, typically due to
    originally subclassing at least one PEP-compliant type hint defined by the
    standard :mod:`typing` module).

    This tester is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation trivially reduces to
    an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a :pep:`484`-compliant subscripted
        generic.

    See Also
    --------
    :func:`.is_hint_pep484_generic_unsubbed`
        Further details.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import get_hint_pep_origin_or_none

    # Arbitrary object originating this hint if any *OR* "None" otherwise.
    hint_origin = get_hint_pep_origin_or_none(hint)

    # Return true only if...
    return (
        # Some object originates this hint *AND*...
        hint_origin is not None and
        # This origin object is an unsubscripted generic type, which would then
        # imply this hint to be a subscripted generic. If this strikes you as
        # insane, you're not alone
        is_hint_pep484_generic_unsubbed(hint_origin)
    )


#FIXME: Unit test us up, please.
def is_hint_pep484_generic_unsubbed(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed object is a :pep:`484`-compliant
    **unsubscripted generic** (i.e., :class:`typing.Generic` subclass, typically
    due to originally subclassing at least one PEP-compliant type hint defined
    by the standard :mod:`typing` module).

    This tester returns :data:`True` only if this object was originally defined
    as a class subclassing a combination of:

    * At least one of:

      * The :pep:`484`-compliant :mod:`typing.Generic` superclass.
      * The :pep:`544`-compliant :mod:`typing.Protocol` superclass.

    * Zero or more non-class :mod:`typing` pseudo-superclasses (e.g.,
      ``typing.List[int]``).
    * Zero or more other standard superclasses.

    This tester is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation trivially reduces to
    an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a :pep:`484`-compliant unsubscripted
        generic.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import get_hint_pep_args

    # Return true only if this hint is a subclass of the "typing.Generic"
    # superclass, in which case this hint is a generic.
    #
    # Note that:
    # * This test is robust against edge cases, as the "typing" module
    #   guarantees all user-defined classes subclassing one or more "typing"
    #   pseudo-superclasses to subclass the "typing.Generic" abstract base class
    #   (ABC) regardless of whether those classes did so explicitly. How? By
    #   type erasure, of course, the malignant gift that keeps on giving:
    #       >>> import typing as t
    #       >>> class MuhList(t.List): pass
    #       >>> MuhList.__orig_bases__
    #       (typing.List)
    #       >>> MuhList.__mro__
    #       (__main__.MuhList, list, typing.Generic, object)
    # * This issubclass() call implicitly performs a surprisingly
    #   inefficient search over the method resolution order (MRO) of all
    #   superclasses of this hint. In theory, the cost of this search might
    #   be circumventable by observing that this ABC is expected to reside
    #   at the second-to-last index of the tuple exposing this MRO far all
    #   generics by virtue of fragile implementation details violating
    #   privacy encapsulation. In practice, this codebase is already
    #   fragile enough.
    # * The following logic superficially appears to implement the same
    #   test *WITHOUT* the onerous cost of a search:
    #       return len(get_hint_pep484_generic_bases_unerased_or_none(hint)) > 0
    #   Why didn't we opt for that, then? Because this tester is routinely
    #   passed objects that *CANNOT* be guaranteed to be PEP-compliant.
    #   Indeed, the high-level is_hint_pep() tester establishing the
    #   PEP-compliance of arbitrary objects internally calls this
    #   lower-level tester to do so. Since the
    #   get_hint_pep484_generic_bases_unerased_or_none() getter internally
    #   reduces to returning the tuple of the general-purpose
    #   "__orig_bases__" dunder attribute formalized by PEP 560, testing
    #   whether that tuple is non-empty or not in no way guarantees this
    #   object to be a PEP-compliant generic.
    return (
        # If the active Python interpreter targets Python >= 3.11, a subclass
        # test suffices to detect a PEP 484-compliant unsubscripted generic;
        is_type_subclass(hint, Generic)  # type: ignore[arg-type]
        if IS_PYTHON_AT_LEAST_3_11 else
        # Else, the active Python interpreter targets Python <= 3.10. In this
        # case, a simple subclass test does *NOT* suffice to detect a PEP
        # 484-compliant unsubscripted generic. Why? Because Python <= 3.10
        # implements PEP 484-compliant subscripted generics as types! But
        # PEP 484-compliant unsubscripted generics are also types, of course:
        #     $ python3.10
        #     >>> from typing import List
        #     >>> class MuhGeneric(List): pass
        #     >>> isinstance(MuhGeneric, type)
        #     True  # <-- good
        #     >>> isinstance(MuhGeneric[str], type)
        #     True  # <-- *BAD*
        #
        #     $ python3.11
        #     >>> from typing import List
        #     >>> class MuhGeneric(List): pass
        #     >>> isinstance(MuhGeneric, type)
        #     True  # <-- good
        #     >>> isinstance(MuhGeneric[str], type)
        #     False  # <-- good
        #
        # Disambiguating this edge case requires also detecting whether this PEP
        # 484-compliant generic is subscripted by one or more child hints.
        (
            # This hint is a subclass of the PEP 484-compliant "typing.Generic"
            # superclass *AND*...
            is_type_subclass(hint, Generic) and  # type: ignore[arg-type]
            # This PEP 484-compliant generic is unsubscripted.
            not get_hint_pep_args(hint)
        )
    )

# ....................{ GETTERS                            }....................
@callable_cached
def get_hint_pep484_generic_bases_unerased(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep484Exception,
    exception_prefix: str = '',
) -> tuple:
    '''
    Tuple of all unerased :mod:`typing` **pseudo-superclasses** (i.e.,
    :mod:`typing` objects originally listed as superclasses prior to their
    implicit type erasure under :pep:`560`) of the passed :pep:`484`-compliant
    **generic** (i.e., either subscripted or unsubscripted type subclassing at
    least one non-class :mod:`typing` object).

    This getter is memoized for efficiency.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.
    exception_cls : TypeException
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintPep484Exception`.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    tuple
        Tuple of the one or more unerased pseudo-superclasses of this
        :mod:`typing` generic. Specifically:

        * If this generic defines an ``__orig_bases__`` dunder instance
          variable, the value of that variable as is.
        * Else, the value of the ``__mro__`` dunder instance variable stripped
          of all ignorable classes conveying *no* semantic meaning, including:

          * This generic itself.
          * The :class:`object` root superclass.

    Raises
    ------
    exception_cls
        If this hint is either:

        * *Not* a :mod:`typing` generic.
        * A :mod:`typing` generic that erased *none* of its superclasses but
          whose method resolution order (MRO) lists strictly less than four
          classes. Valid :pep:`484`-compliant generics should list at least
          four classes, including (in order):

          #. This class itself.
          #. The one or more :mod:`typing` objects directly subclassed by this
             generic.
          #. The :class:`typing.Generic` superclass.
          #. The zero or more non-:mod:`typing` superclasses subsequently
             subclassed by this generic (e.g., :class:`abc.ABC`).
          #. The :class:`object` root superclass.

    See Also
    --------
    :func:`beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget.get_hint_pep484585_generic_bases_unerased`
        Further details.
    '''

    #FIXME: This tuple appears to be implemented erroneously -- at least under
    #Python 3.7, anyway. Although this tuple is implemented correctly for the
    #common case of user-defined types directly subclassing "typing" types,
    #this tuple probably is *NOT* implemented correctly for the edge case of
    #user-defined types indirectly subclassing "typing" types: e.g.,
    #    >>> import collections.abc, typing
    #    >>> T = typing.TypeVar('T')
    #    >>> class Direct(collections.abc.Sized, typing.Generic[T]): pass
    #    >>> Direct.__orig_bases__
    #    (collections.abc.Sized, typing.Generic[~T])
    #    >>> class Indirect(collections.abc.Container, Direct): pass
    #    >>> Indirect.__orig_bases__
    #    (collections.abc.Sized, typing.Generic[~T])
    #
    #*THAT'S COMPLETELY INSANE.* Clearly, their naive implementation failed to
    #account for actual real-world use cases.
    #
    #On the bright side, the current implementation prevents us from actually
    #having to perform a breadth-first traversal of all original superclasses
    #of this class in method resolution order (MRO). On the dark side, it's
    #pants-on-fire balls -- but there's not much we can do about that. *sigh*
    #
    #If we ever need to perform that breadth-first traversal, resurrect this:
    #
    #    # If this class was *NOT* subject to type erasure, reduce to a noop.
    #    if not hint_bases:
    #        return hint_bases
    #
    #    # Fixed list of all typing super attributes to be returned.
    #    superattrs = acquire_fixed_list(FIXED_LIST_SIZE_MEDIUM)
    #
    #    # 0-based index of the last item of this list.
    #    superattrs_index = 0
    #
    #    # Fixed list of all transitive superclasses originally listed by this
    #    # class iterated in method resolution order (MRO).
    #    hint_orig_mro = acquire_fixed_list(FIXED_LIST_SIZE_MEDIUM)
    #
    #    # 0-based indices of the current and last items of this list.
    #    hint_orig_mro_index_curr = 0
    #    hint_orig_mro_index_last = 0
    #
    #    # Initialize this list with the tuple of all direct superclasses of this
    #    # class, which iteration then expands to all transitive superclasses.
    #    hint_orig_mro[:len(hint_bases)] = hint_bases
    #
    #    # While the heat death of the universe has been temporarily forestalled...
    #    while (True):
    #        # Currently visited superclass of this class.
    #        hint_base = hint_orig_mro[hint_orig_mro_index_curr]
    #
    #        # If this superclass is a typing attribute...
    #        if is_hint_pep_type_typing(hint_base):
    #            # Avoid inserting this attribute into the "hint_orig_mro" list.
    #            # Most typing attributes are *NOT* actual classes and those that
    #            # are have no meaningful public superclass. Ergo, iteration
    #            # terminates with typing attributes.
    #            #
    #            # Insert this attribute at the current item of this list.
    #            superattrs[superattrs_index] = hint_base
    #
    #            # Increment this index to the next item of this list.
    #            superattrs_index += 1
    #
    #            # If this class subclasses more than the maximum number of "typing"
    #            # attributes supported by this function, raise an exception.
    #            if superattrs_index >= FIXED_LIST_SIZE_MEDIUM:
    #                raise BeartypeDecorHintPep560Exception(
    #                    '{} PEP type {!r} subclasses more than '
    #                    '{} "typing" types.'.format(
    #                        exception_prefix,
    #                        hint,
    #                        FIXED_LIST_SIZE_MEDIUM))
    #        # Else, this superclass is *NOT* a typing attribute. In this case...
    #        else:
    #            # Tuple of all direct superclasses originally listed by this class
    #            # prior to PEP 484 type erasure if any *OR* the empty tuple
    #            # otherwise.
    #            hint_base_bases = getattr(hint_base, '__orig_bases__')
    #
    #            #FIXME: Implement breadth-first traversal here.
    #
    #    # Tuple sliced from the prefix of this list assigned to above.
    #    superattrs_tuple = tuple(superattrs[:superattrs_index])
    #
    #    # Release and nullify this list *AFTER* defining this tuple.
    #    release_fixed_list(superattrs)
    #    del superattrs
    #
    #    # Return this tuple as is.
    #    return superattrs_tuple
    #
    #Also resurrect this docstring snippet:
    #
    #    Raises
    #    ----------
    #    BeartypeDecorHintPep560Exception
    #        If this object defines the ``__orig_bases__`` dunder attribute but that
    #        attribute transitively lists :data:`FIXED_LIST_SIZE_MEDIUM` or more :mod:`typing`
    #        attributes.
    #
    #Specifically:
    #  * Acquire a fixed list of sufficient size (e.g., 64). We probably want
    #    to make this a constant in "utilcachelistfixedpool" for reuse
    #    everywhere, as this is clearly becoming a common idiom.
    #  * Slice-assign "__orig_bases__" into this list.
    #  * Maintain two simple 0-based indices into this list:
    #    * "bases_index_curr", the current base being visited.
    #    * "bases_index_last", the end of this list also serving as the list
    #      position to insert newly discovered bases at.
    #  * Iterate over this list and keep slice-assigning from either
    #    "__orig_bases__" (if defined) or "__mro__" (otherwise) into
    #    "list[bases_index_last:len(__orig_bases__)]". Note that this has the
    #    unfortunate disadvantage of temporarily iterating over duplicates,
    #    but... *WHO CARES.* It still works and we subsequently
    #    eliminate duplicates at the end.
    #  * Return a frozenset of this list, thus implicitly eliminating
    #    duplicate superclasses.
    #FIXME: Actually, a simpler implementation could now be defined in terms of
    #the new iter_hint_pep560_bases_unerased() iterator. Still, let's
    #avoid doing so until we *ABSOLUTELY* must. *sigh*

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget import (
        get_hint_pep484585_generic_type_or_none)

    # Either the unsubscripted generic reduced from this possibly subscripted
    # generic if this hint is a generic *OR* "None". Specifically, either:
    # * If this generic if unsubscripted, this unsubscripted generic as is.
    # * If this generic if subscripted, the unsubscripted generic underlying
    #   this subscripted generic.
    # * If this generic is *NOT* actually a generic, "None".
    hint = get_hint_pep484585_generic_type_or_none(hint)  # pyright: ignore

    # If this hint is *NOT* a PEP 484- or 544-compliant unsubscripted generic,
    # raise an exception.
    if not is_hint_pep484_generic_unsubbed(hint):
        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} not '
            f'PEP 484 or 585 unsubscripted generic.'
        )
    # Else, this hint is a PEP 484- or 544-compliant unsubscripted generic.
    #
    # If this hint is a PEP 484- or 544-compliant generic superclass in either
    # unsubscripted form (e.g., "typing.Generic", "typing.Protocol") or
    # subscripted form (e.g., "typing.Generic[T]", "typing.Protocol[T]"), then
    # (by definition) this superclass subclasses *NO* pseudo-superclasses. In
    # this case, trivially return the empty tuple.

    #FIXME: Unit test this edge case up, please.
    elif hint in TYPES_PEP484544_GENERIC:
        return ()
    # Else, this hint is *NOT* a PEP 484- or 544-compliant generic superclass.

    # Unerased pseudo-superclasses of this generic if any *OR* "None" otherwise
    # (e.g., if this generic is a single-inherited protocol).
    hint_bases = getattr(hint, '__orig_bases__', None)

    # If this generic erased its superclasses, return these superclasses as is.
    if hint_bases is not None:
        return hint_bases
    # Else, this generic erased *NONE* of its superclasses. These superclasses
    # *MUST* by definition be unerased and thus safely returnable as is.

    # Unerased superclasses of this generic defined by the method resolution
    # order (MRO) for this generic.
    hint_bases = hint.__mro__  # pyright: ignore

    # If this MRO lists strictly less than four classes, raise an exception.
    # The MRO for any unerased generic should list at least four classes:
    # 1. This class itself.
    # 2. The one or more "typing" objects directly subclassed by this generic.
    # 3. The "typing.Generic" superclass. Note that this superclass is typically
    #    but *NOT* necessarily the second-to-last superclass. Since this ad-hoc
    #    heuristic is *NOT* an actual constraint, we intentionally avoid
    #    asserting this to be the case. An example in which "typing.Generic" is
    #    *NOT* the second-to-last superclass is:
    #        >>> from abc import ABC
    #        >>> from typing import Protocol
    #        >>> class ProtocolCustomSuperclass(Protocol): pass
    #        >>> class ProtocolCustomABC(ProtocolCustomSuperclass, ABC): pass
    #        >>> print(ProtocolCustomABC.__mro__)
    #        (<class '__main__.ProtocolCustomABC'>,
    #         <class '__main__.ProtocolCustomSuperclass'>,
    #         <class 'typing.Protocol'>,
    #         <class 'typing.Generic'>,
    #         <class 'abc.ABC'>,
    #         <class 'object'>)
    # 4. The "object" root superclass.
    if len(hint_bases) < 4:
        raise exception_cls(
            f'{exception_prefix}PEP 484 generic {repr(hint)} '
            f'subclasses less than four superclasses {repr(hint_bases)}.'
        )
    # Else, this MRO lists at least four classes.
    #
    # If any class listed by this MRO fails to comply with the above
    # expectations, raise an exception.
    elif hint_bases[0] is not hint:
        raise exception_cls(
            f'{exception_prefix}PEP 484 generic {repr(hint)} '
            f'first superclass {repr(hint_bases[0])} != {repr(hint)}.'
        )
    elif hint_bases[-1] is not object:
        raise exception_cls(
            f'{exception_prefix}PEP 484 generic {repr(hint)} '
            f'last superclass {repr(hint_bases[-1])} != {repr(object)}.'
        )
    # Else, all classes listed by this MRO comply with the above expectations.

    # Return a slice of this tuple preserving *ONLY* the non-ignorable
    # superclasses listed by this tuple for conformance with the tuple returned
    # by this getter from the "__orig_bases__", which similarly lists *ONLY*
    # non-ignorable superclasses. Specifically, strip from this tuple:
    # * This class itself.
    # * The "object" root superclass.
    #
    # Ideally, the ignorable "(beartype.|)typing.(Generic|Protocol)"
    # superclasses would also be stripped. Sadly, as exemplified by the above
    # counter-example, those superclasses are *NOT* guaranteed to occupy the
    # third- and second-to-last positions (respectively) of this tuple. Ergo,
    # stripping these superclasses safely would require an inefficient
    # iterative O(n) search across this tuple for those superclasses. Instead,
    # we defer ignoring these superclasses to the caller -- which necessarily
    # already (and hopefully efficiently) ignores ignorable superclasses.
    return hint_bases[1:-1]
