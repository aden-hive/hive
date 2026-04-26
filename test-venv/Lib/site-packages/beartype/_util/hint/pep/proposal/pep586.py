#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`586`-compliant type hint utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep586Exception
from beartype._data.cls.datacls import TYPES_PEP586_ARG
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import TypeException
from beartype._data.hint.sign.datahintsigns import HintSignLiteral
from beartype._util.text.utiltextjoin import join_delimited_disjunction_types

# ....................{ VALIDATORS                         }....................
def die_unless_hint_pep586(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep586Exception,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception of the passed type unless the passed object is a
    :pep:`586`-compliant type hint (i.e., subscription of either the
    :attr:`typing.Literal` or :attr:`typing_extensions.Literal` type hint
    factories).

    Ideally, the :attr:`typing.Literal` singleton would internally validate the
    literal objects subscripting that singleton at subscription time (i.e., in
    the body of the ``__class_getitem__()`` dunder method). Whereas *all* other
    :mod:`typing` attributes do just that, :attr:`typing.Literal` permissively
    accepts all possible arguments like a post-modern philosopher hopped up on
    too much tenure. For inexplicable reasons, :pep:`586` explicitly requires
    third-party type checkers (that's us) to validate these hints rather than
    standardizing that validation in the :mod:`typing` module. Weep, Guido!

    Caveats
    -------
    **This function is slow** and should thus be called only once per
    visitation of a :pep:`586`-compliant type hint. Specifically, this function
    is :math:`O(n)` for :math:`n` the number of arguments subscripting this
    hint.

    Parameters
    ----------
    hint : Hint
        Object to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised in the event of fatal error. Defaults to
        :exc:`.BeartypeDecorHintPep586Exception`.
    exception_prefix : str, optional
        Human-readable substring prefixing the representation of this object in
        the exception message. Defaults to the empty string.

    Raises
    ------
    exception_cls
        If this object either:

        * Is *not* a subscription of either the :attr:`typing.Literal` or
          :attr:`typing_extensions.Literal` type hint factories.
        * Subscripts either factory with zero arguments via the empty tuple,
          which these factories sadly fails to guard against.
        * Subscripts either factory with one or more arguments that are *not*
          **valid literals**, defined as the set of all:

          * Booleans.
          * Byte strings.
          * Integers.
          * Unicode strings.
          * :class:`enum.Enum` members.
          * The :data:`None` singleton.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import get_hint_pep_args
    from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign

    # If this hint is *NOT* PEP 586-compliant, raise an exception.
    if get_hint_pep_sign(hint) is not HintSignLiteral:
        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} not PEP 586-compliant '
            f'(e.g., "typing.Literal[...]", "typing_extensions.Literal[...]").'
        )
    # Else, this hint is PEP 586-compliant.

    # Tuple of zero or more literal objects subscripting this hint.
    hint_literals = get_hint_pep_args(hint)

    # If this hint is unsubscripted...
    if not hint_literals:
        # Exception message to be raised.
        exception_message = f'{exception_prefix}PEP 586 type hint {repr(hint)} '

        # If this hint defines the standard "__args__" dunder attribute, this
        # hint *MUST* have been subscripted by the the empty tuple. Ideally, the
        # "typing.Literal" factory would guard against this itself. It does not;
        # thus, we do. Construct an appropriate message.
        if hasattr(hint_literals, '__args__'):
            exception_message += (
                'subscripted by empty tuple, '
                'which is not a valid literal object.'
            )
        # Else, this hint fails to define the standard "__args__" dunder
        # attribute. In this case, this hint *MUST* be the unsubscripted
        # "typing.Literal" factory -- which conveys *NO* meaningful semantics
        # and is thus invalid as a type hint. Construct an appropriate message.
        else:
            exception_message += (
                'unsubscripted (i.e., subscripted by no literal objects).')

        # Raise this exception.
        raise exception_cls(exception_message)
    # If this hint is subscripted by one or more literal objects.

    # For each argument subscripting this hint...
    #
    # Sadly, despite PEP 586 imposing strict restrictions on the types of
    # objects permissible as arguments subscripting the "typing.Literal"
    # singleton, PEP 586 explicitly offloads the odious chore of enforcing those
    # restrictions onto third-party type checkers by intentionally implementing
    # that singleton to permissively accept *ALL* possible objects when
    # subscripted:
    #     Although the set of parameters Literal[...] may contain at type check
    #     time is very small, the actual implementation of typing.Literal will
    #     not perform any checks at runtime.
    for hint_literal_index, hint_literal in enumerate(hint_literals):
        # If this argument is invalid as a literal argument...
        if not isinstance(hint_literal, TYPES_PEP586_ARG):
            # Human-readable concatenation of the types of all valid literal
            # arguments, delimited by commas and/or "or".
            hint_literal_types = join_delimited_disjunction_types(
                TYPES_PEP586_ARG)

            # Raise an exception.
            raise exception_cls(
                f'{exception_prefix}PEP 586 type hint {repr(hint)} '
                f'argument {hint_literal_index} '
                f'{repr(hint_literal)} not {hint_literal_types}.'
            )
        # Else, this argument is valid as a literal argument.

# ....................{ GETTERS                            }....................
#FIXME: Unit test us up, please.
def get_hint_pep586_literals(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep586Exception,
    exception_prefix: str = '',
) -> tuple:
    '''
    Tuple of zero or more literal objects subscripting the passed
    :pep:`586`-compliant type hint (i.e., subscription of either the
    :attr:`typing.Literal` or :attr:`typing_extensions.Literal` type hint
    factories).

    This getter is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Caveats
    -------
    **This low-level getter performs no validation of the contents of this
    tuple.** Consider calling the high-level :func:`die_unless_hint_pep586`
    validator to do so before leveraging this tuple elsewhere.

    Parameters
    ----------
    hint : Hint
        :pep:`586`-compliant type hint to be inspected.
    exception_cls : TypeException
        Type of exception to be raised. Defaults to
        :exc:`BeartypeDecorHintPep586Exception`.
    exception_prefix : str, optional
        Human-readable substring prefixing the representation of this object in
        the exception message. Defaults to the empty string.

    Returns
    -------
    tuple
        Tuple of zero or more literal objects subscripting this hint.

    Raises
    ------
    exception_cls
        If this object is *not* a :pep:`586`-compliant type hint.
    '''

    # If this hint is *NOT* PEP 586-compliant, raise an exception.
    die_unless_hint_pep586(hint=hint, exception_prefix=exception_prefix)
    # Else, this hint is PEP 586-compliant.

    # Return the standard tuple of all literals subscripting this hint.
    return hint.__args__  # pyright: ignore
