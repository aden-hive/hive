#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`544`-compliant **type alias reducers** (i.e., low-level
callables converting higher-level protocols to lower-level type hints more
readily consumable by :mod:`beartype`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep544Exception
from beartype._check.metadata.hint.hintsane import (
    HINT_SANE_IGNORABLE,
    HintOrSane,
)
from beartype._data.typing.datatypingport import Hint
from beartype._util.hint.pep.proposal.pep544 import (
    HINT_PEP484_IO_GENERIC_TO_PEP544_PROTOCOL,
    init_HINT_PEP484_IO_GENERIC_TO_PEP544_PROTOCOL,
    is_hint_pep484_generic_io,
    is_hint_pep544_protocol_supertype,
)
from beartype._util.hint.pep.utilpepget import (
    get_hint_pep_origin_or_none,
    get_hint_pep_typeargs_packed,
)

# ....................{ REDUCERS                           }....................
def reduce_hint_pep544(hint: Hint, exception_prefix: str) -> HintOrSane:
    '''
    Reduce the passed :pep:`544`-compliant **protocol** (i.e., user-defined
    subclass of the :class:`typing.Protocol` abstract base class (ABC)) to the
    ignorable :data:`.HINT_SANE_IGNORABLE` singleton if this protocol is a
    parametrization of this ABC by one or more :pep:`484`-compliant **type
    variables** (i.e., :class:`typing.TypeVar` objects).

    As the name implies, this ABC is generic and thus fails to impose any
    meaningful constraints. Since a type variable in and of itself also fails to
    impose any meaningful constraints, these parametrizations are safely
    ignorable in all possible runtime contexts: e.g.,

    .. code-block:: python

       from typing import Protocol, TypeVar
       T = TypeVar('T')
       def noop(param_hint_ignorable: Protocol[T]) -> T: pass

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

    Parameters
    ----------
    hint : Hint
        Type hint to be reduced.
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    All remaining passed keyword parameters are silently ignored.

    Returns
    -------
    HintOrSane
        Lower-level type hint currently supported by :mod:`beartype`.
    '''

    # If this protocol is an unsubscripted
    # "(typing|typing_extension|beartype.typing).Protocol" superclass, then this
    # protocol is ignorable. Reduce this ignorable protocol to the ignorable
    # singleton.
    #
    # For unknown (but probably) uninteresting reasons, *ALL* possible objects
    # satisfy these protocol superclasses. Ergo, these superclasses and *ALL*
    # parametrizations of these superclasses are synonymous with the root
    # "object" superclass: e.g.,
    #     >>> from typing as Protocol
    #     >>> isinstance(object(), Protocol)
    #     True
    #     >>> isinstance('wtfbro', Protocol)
    #     True
    #     >>> isinstance(0x696969, Protocol)
    #     True
    if is_hint_pep544_protocol_supertype(hint):
        return HINT_SANE_IGNORABLE

    # Type originating this protocol if any *OR* "None" otherwise.
    #
    # Note that we intentionally avoid calling the
    # get_hint_pep_origin_type_isinstanceable_or_none() function here, which has
    # been intentionally designed to exclude PEP-compliant type hints
    # originating from "typing" type origins for stability reasons.
    hint_origin = get_hint_pep_origin_or_none(hint)

    # If...
    if (
        # Some type originates this protocol *AND*...
        hint_origin is not None and
        # This origin type is an unsubscripted
        # "(typing|typing_extension|beartype.typing).Protocol" superclass...
        is_hint_pep544_protocol_supertype(hint_origin)
    ):
        # Then the passed protocol is a
        # "(typing|typing_extension|beartype.typing).Protocol" superclass
        # subscripted by one or more PEP 484-compliant type variables (e.g.,
        # "typing.Protocol[T]"). Since these type variables convey *NO*
        # meaningful semantics in this context, this protocol is ignorable by a
        # similar argument as above.
        #
        # Note that protocol superclasses can *ONLY* be parametrized by type
        # variables.
        return HINT_SANE_IGNORABLE
    # Else, this protocol is unignorable.

    # Preserve this unignorable protocol.
    return hint


def reduce_hint_pep484_generic_io_to_pep544_protocol(
    hint: Hint, exception_prefix: str) -> Hint:
    '''
    :pep:`544`-compliant :mod:`beartype` **IO protocol** (i.e., either
    :class:`._Pep544IO` itself *or* a subclass of that class defined by this
    submodule intentionally designed to be usable at runtime) corresponding to
    the passed :pep:`484`-compliant :mod:`typing` **IO generic base class**
    (i.e., either :class:`typing.IO` itself *or* a subclass of
    :class:`typing.IO` defined by the :mod:`typing` module effectively unusable
    at runtime due to botched implementation details).

    This reducer is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner thanks to caching internally performed by this
    reducer.

    Parameters
    ----------
    hint : Hint
        :pep:`484`-compliant :mod:`typing` IO generic base class to be replaced
        by the corresponding :pep:`544`-compliant :mod:`beartype` IO protocol.
    exception_prefix : str
        Human-readable label prefixing the representation of this object in the
        exception message.

    Returns
    -------
    Protocol
        :pep:`544`-compliant :mod:`beartype` IO protocol corresponding to this
        :pep:`484`-compliant :mod:`typing` IO generic base class.

    Raises
    ------
    BeartypeDecorHintPep544Exception
        If this object is *not* a :pep:`484`-compliant IO generic base class.
    '''

    # If this object is *NOT* a PEP 484-compliant "typing" IO generic,
    # raise an exception.
    if not is_hint_pep484_generic_io(hint):
        raise BeartypeDecorHintPep544Exception(
            f'{exception_prefix}type hint {repr(hint)} not '
            f'PEP 484 IO generic base class '
            f'(i.e., "typing.IO", "typing.BinaryIO", or "typing.TextIO").'
        )
    # Else, this object is *NOT* a PEP 484-compliant "typing" IO generic.
    #
    # If this dictionary has yet to be initialized, this submodule has yet to be
    # initialized. In this case, do so.
    #
    # Note that this initialization is intentionally deferred until required.
    # Why? Because this initialization performs somewhat space- and
    # time-intensive work -- including importation of the "beartype.vale"
    # subpackage, which we strictly prohibit importing from global scope.

    #FIXME: Awkward API. Technically, this is fine. It works. So, that's good.
    #Still, the ideal API would be a "dict" subclass that auto-initializes
    #itself on the first call to the dict.get() method called below -- probably
    #by just trivially overriding the dict.get() method to instead perform the
    #logic currently performed by this
    #init_HINT_PEP484_IO_GENERIC_TO_PEP544_PROTOCOL() initialization method.
    elif not HINT_PEP484_IO_GENERIC_TO_PEP544_PROTOCOL:
        init_HINT_PEP484_IO_GENERIC_TO_PEP544_PROTOCOL()
    # In any case, this dictionary is now initialized.

    # PEP 544-compliant IO protocol implementing this PEP 484-compliant IO
    # generic if any *OR* "None" otherwise.
    pep544_protocol = HINT_PEP484_IO_GENERIC_TO_PEP544_PROTOCOL.get(hint)

    # If *NO* PEP 544-compliant IO protocol implements this generic...
    if pep544_protocol is None:
        # Tuple of zero or more type variables parametrizing this hint.
        hint_typevars = get_hint_pep_typeargs_packed(hint)

        #FIXME: Unit test us up, please.
        # If this hint is unparametrized, raise an exception.
        if not hint_typevars:
            raise BeartypeDecorHintPep544Exception(
                f'{exception_prefix}PEP 484 IO generic base class '
                f'{repr(hint)} invalid (i.e., not subscripted (indexed) by '
                f'either "str", "bytes", "typing.Any", or "typing.AnyStr").'
            )
        # Else, this hint is parametrized and thus defines the "__origin__"
        # dunder attribute whose value is the type originating this hint.

        #FIXME: Attempt to actually handle this type variable, please.
        # Reduce this parametrized hint (e.g., "typing.IO[typing.AnyStr]") to
        # the equivalent unparametrized hint (e.g., "typing.IO"), effectively
        # ignoring the type variable parametrizing this hint.
        hint_unparametrized: type = get_hint_pep_origin_or_none(hint)  # type: ignore[assignment]

        #FIXME: The caching-specific assignment
        #"HINT_PEP484_IO_GENERIC_TO_PEP544_PROTOCOL[hint] = \" should no longer
        #be required (or desired), as this reducer is itself memoized.
        # PEP 544-compliant IO protocol implementing this unparametrized PEP
        # 484-compliant IO generic. For efficiency, we additionally cache this
        # mapping under the original parametrized hint to minimize the cost of
        # similar reductions under subsequent annotations.
        pep544_protocol = \
            HINT_PEP484_IO_GENERIC_TO_PEP544_PROTOCOL[hint] = \
            HINT_PEP484_IO_GENERIC_TO_PEP544_PROTOCOL[hint_unparametrized]
    # Else, some PEP 544-compliant IO protocol implements this generic.

    # Return this protocol.
    return pep544_protocol
