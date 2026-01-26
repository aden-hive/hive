#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`- and :pep:`585`-compliant **generic type hint
testers** (i.e., low-level callables generically validating and detecting both
:pep:`484`- and :pep:`585`-compliant generic classes).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep484585Exception
from beartype._data.cls.datacls import TYPES_PEP484544_GENERIC
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import TypeException
from beartype._util.bear.utilbearblack import is_object_blacklisted
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.hint.pep.proposal.pep484.pep484generic import (
    is_hint_pep484_generic_subbed,
    is_hint_pep484_generic_unsubbed,
)
from beartype._util.hint.pep.proposal.pep585 import (
    is_hint_pep585_generic_subbed,
    is_hint_pep585_generic_unsubbed,
    is_hint_pep585_builtin_subbed,
)

# ....................{ RAISERS                            }....................
def die_unless_hint_pep484585_generic_unsubbed(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep484585Exception,
    exception_prefix: str = '',
) -> None:
    '''
    Raise the passed exception unless the passed type hint is an **unsubscripted
    generic** (i.e., type originally subclassing at least one subscripted
    :pep:`484`- or :pep:`585`-compliant pseudo-superclass).

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.
    exception_cls : TypeException
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintPep484585Exception`.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    exception_cls
        If this hint is *not* an unsubscripted generic.
    '''

    # If this hint is *NOT* an unsubscripted generic...
    if not is_hint_pep484585_generic_unsubbed(hint):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not type.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Raise an exception of this type prefixed by this prefix.
        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} not '
            f'PEP 484 or 585 unsubscripted generic.'
        )
    # Else, this hint is an unsubscripted generic.

# ....................{ TESTERS                            }....................
def is_hint_pep484585_generic_user(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed :pep:`484`- or :pep:`585`-compliant generic
    is **user-defined** (i.e., defined by a third-party downstream codebase
    rather than CPython's first-party upstream standard library).

    Specifically, this tester returns :data:`True` only if this generic is
    neither:

    * A :pep:`484`- or :pep:`544`-compliant superclass defined by the
      :mod:`typing` module (e.g., :class:`typing.Generic`,
      :class:`typing.Protocol`) *nor*...
    * A :pep:`585`-compliant superclass (e.g., ``list[T]``).

    This tester is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation trivially reduces to
    an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this is a user-defined generic.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import (
        get_hint_pep_origin_type_or_none)

    # Return true only if...
    return (
        # This object is a generic that is neither...
        is_hint_pep484585_generic(hint) and not (
            # A PEP 585-compliant subscripted superclass (e.g., "list[T]")
            # *NOR*...
            is_hint_pep585_builtin_subbed(hint) or

            #FIXME: *YIKES.* This approach omits "typing_extensions.Protocol",
            #which is a distinct type from "typing.Protocol". Instead of
            #dogmatically testing raw types, consider a more flexible approach
            #that portably tests higher-level names: e.g.,
            #    hint_origin = get_hint_pep_origin_type_or_none(
            #        hint=hint,
            #        # Preserve "typing.Generic" and "typing.Protocol" as themselves,
            #        # as doing so dramatically simplifies this test. *shrug*
            #        is_self_fallback=True,
            #    )
            #    if (
            #        is_hint_pep_type_typing(hint_origin) and
            #        hint_origin.__name__ in frozenset(('Generic', 'Protocol',))
            #    ):
            #        return False
            #FIXME: *HMM.* The above approach is certainly better, but still
            #falls short. Below, we suggest that the PEP 484-compliant
            #subscripted pseudo-superclass "typing.Generic[S]" should also be
            #seen as *NOT* a user-defined generic. Makes sense... except that
            #the above logic erroneously returns "True" for "typing.Generic[S]"!
            #Clearly, we also need to discard subscriptions. *sigh*
            #FIXME: Excise "TYPES_PEP484544_GENERIC" entirely. That tuple is
            #implicitly non-portable and thus bad news all around, really.

            # A subscripted or unsubscripted PEP 484- or 544-compliant
            # superclass defined by the standard "typing" module, including:
            # * "typing.Generic".
            # * "typing.Generic[S]".
            # * "typing.Protocol".
            # * "typing.Protocol[S]".
            get_hint_pep_origin_type_or_none(
                hint=hint,
                # Preserve "typing.Generic" and "typing.Protocol" as themselves,
                # as doing so dramatically simplifies this test. *shrug*
                is_self_fallback=True,
            ) in TYPES_PEP484544_GENERIC
        )
    )

# ....................{ TESTERS ~ kind                     }....................
@callable_cached
def is_hint_pep484585_generic(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed object is either a :pep:`484`- or
    :pep:`585`-compliant **generic** (i.e., either a type originally subclassing
    at least one subscripted :pep:`484`- or :pep:`585`-compliant
    pseudo-superclass *or* an object subscripted by one or more child type hints
    originating from such a type).

    This tester returns :data:`True` only if this object is either:

    * A :pep:`484`-compliant generic as tested by the lower-level
      :func:`.is_hint_pep484_generic` function.
    * A :pep:`585`-compliant generic as tested by the lower-level
      :func:`.is_hint_pep585_generic` function.

    This tester is memoized for efficiency.

    Caveats
    -------
    **Generics are not necessarily classes,** despite originally being declared
    as classes. Although *most* generics are classes, subscripting a generic
    class usually produces a generic non-class that *must* nonetheless be
    transparently treated as a generic class: e.g.,

    .. code-block:: pycon

       >>> from typing import Generic, TypeVar
       >>> S = TypeVar('S')
       >>> T = TypeVar('T')
       >>> class MuhGeneric(Generic[S, T]): pass
       >>> non_class_generic = MuhGeneric[S, T]
       >>> isinstance(non_class_generic, type)
       False

    Parameters
    ----------
    hint : Hint
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a generic.

    See Also
    --------
    :func:`beartype._util.hint.pep.utilpepget.get_hint_pep_typeargs_packed`
        Commentary on the relation between generics and parametrized hints.
    '''

    # Return true only if...
    return (
        # This hint is either a...
        (
            # PEP 484-compliant generic *OR*...
            #
            # Note these tests trivially reduce to fast O(1) operations and are
            # thus tested first.
            is_hint_pep484_generic_unsubbed(hint) or
            is_hint_pep484_generic_subbed(hint) or
            # PEP 585-compliant generic.
            #
            # Note this test is O(n) for n the number of pseudo-superclasses
            # originally subclassed by this generic and is thus tested last.
            is_hint_pep585_generic_unsubbed(hint) or
            is_hint_pep585_generic_subbed(hint)
        # *AND*...
        ) and
        # This generic is *NOT* beartype-blacklisted.
        not _is_hint_pep484585_generic_blacklisted(hint)
    )


def is_hint_pep484585_generic_subbed(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed object is either a :pep:`484`- or
    :pep:`585`-compliant **subscripted generic** (i.e., object subscripted by
    one or more child type hints originating from a type originally subclassing
    at least one subscripted :pep:`484`- or :pep:`585`-compliant
    pseudo-superclass).

    This tester returns :data:`True` only if this object is either:

    * A :pep:`484`-compliant subscripted generic as tested by the lower-level
      :func:`.is_hint_pep484_generic_subbed` function.
    * A :pep:`585`-compliant subscripted generic as tested by the lower-level
      :func:`.is_hint_pep585_generic_subbed` function.

    This tester is memoized for efficiency.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a subscripted generic.
    '''

    # Return true only if...
    return (
        # This hint is either a...
        (
            # PEP 484-compliant subscripted generic *OR*...
            #
            # Note this test trivially reduces to a fast O(1) operation and is
            # thus tested first.
            is_hint_pep484_generic_subbed(hint) or
            # PEP 585-compliant subscripted generic.
            #
            # Note this test is O(n) for n the number of pseudo-superclasses
            # originally subclassed by this generic and is thus tested last.
            is_hint_pep585_generic_subbed(hint)
        # *AND*...
        ) and
        # This generic is *NOT* beartype-blacklisted.
        not _is_hint_pep484585_generic_blacklisted(hint)
    )


def is_hint_pep484585_generic_unsubbed(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed object is either a :pep:`484`- or
    :pep:`585`-compliant **unsubscripted generic** (i.e., type originally
    subclassing at least one subscripted :pep:`484`- or :pep:`585`-compliant
    pseudo-superclass).

    This tester returns :data:`True` only if this object is either:

    * A :pep:`484`-compliant unsubscripted generic as tested by the lower-level
      :func:`.is_hint_pep484_generic_unsubbed` function.
    * A :pep:`585`-compliant unsubscripted generic as tested by the lower-level
      :func:`.is_hint_pep585_generic_unsubbed` function.

    This tester is memoized for efficiency.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a unsubscripted generic.
    '''

    # Return true only if...
    return (
        # This hint is either a...
        (
            # PEP 484-compliant unsubscripted generic *OR*...
            #
            # Note this test trivially reduces to a fast O(1) operation and is
            # thus tested first.
            is_hint_pep484_generic_unsubbed(hint) or
            # PEP 585-compliant unsubscripted generic.
            #
            # Note this test is O(n) for n the number of pseudo-superclasses
            # originally subclassed by this generic and is thus tested last.
            is_hint_pep585_generic_unsubbed(hint)
        # *AND*...
        ) and
        # This generic is *NOT* beartype-blacklisted.
        not _is_hint_pep484585_generic_blacklisted(hint)
    )

# ....................{ PRIVATE ~ testers                  }....................
#FIXME: Call above, please.
@callable_cached
def _is_hint_pep484585_generic_blacklisted(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed :pep:`484`- or :pep:`585`-compliant generic
    is **beartype-blacklisted** (i.e., defined in a third-party package or
    module known to be hostile to runtime type-checking).

    This tester is memoized for efficiency.

    Parameters
    ----------
    hint : Hint
        Generic to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this generic is beartype-blacklisted.

    See Also
    --------
    :func:`.is_object_blacklisted`
        Further details on beartype-blacklisting.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.proposal.pep484585.generic.pep484585genget import (
        get_hint_pep484585_generic_type)

    # Either:
    # * If this generic is already unsubscripted, this generic as is.
    # * Else, this generic is subscripted. In this case, the unsubscripted
    #   generic underlying this subscripted generic.
    hint_type = get_hint_pep484585_generic_type(hint)

    # For each possibly erased superclass of this generic, arbitrarily iterated
    # according to the method resolution order (MRO) for this generic...
    for hint_base in hint_type.__mro__:
        # If this superclass is beartype-blacklisted (i.e., defined in a
        # third-party package or module known to be hostile to runtime
        # type-checking), return true immediately.
        if is_object_blacklisted(hint_base):
            return True
        # Else, this superclass is *NOT* beartype-blacklisted. In this case,
        # continue to the next such superclass of this generic.
    # Else, all superclasses of this generic are *NOT* beartype-blacklisted.

    # Return false as a sane fallback.
    return False
