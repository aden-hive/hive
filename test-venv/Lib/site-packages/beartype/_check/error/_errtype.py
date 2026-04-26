#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype class type hint violation describers** (i.e., functions returning
human-readable strings explaining violations of type hints that are standard
isinstanceable classes rather than PEP-specific objects).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import (
    BeartypeCallHintForwardRefException,
    BeartypePlugInstancecheckStrException,
)
from beartype.roar._roarexc import _BeartypeCallHintPepRaiseException
from beartype.typing import Optional
from beartype._data.typing.datatyping import TupleTypes
from beartype._data.hint.sign.datahintsigns import HintSignForwardRef
from beartype._check.error.errcause import ViolationCause
from beartype._util.cls.pep.clspep3119 import die_unless_type_isinstanceable
from beartype._util.func.arg.utilfuncargtest import (
    die_unless_func_args_len_flexible_equal)
from beartype._util.hint.nonpep.utilnonpeptest import (
    die_unless_hint_nonpep_tuple)
from beartype._util.hint.pep.proposal.pep484585.pep484585ref import (
    import_pep484585_ref_type)
from beartype._util.hint.pep.utilpepget import (
    get_hint_pep_origin_type_isinstanceable_or_none)
from beartype._util.text.utiltextjoin import join_delimited_disjunction_types
from beartype._util.text.utiltextlabel import label_type
from beartype._util.text.utiltextrepr import represent_pith

# ....................{ GETTERS ~ instance : type          }....................
def find_cause_instance_type(cause: ViolationCause) -> ViolationCause:
    '''
    Output cause describing whether the pith of the passed input cause either is
    or is not an instance of the isinstanceable class of that cause.

    Parameters
    ----------
    cause : ViolationCause
        Input cause providing this data.

    Returns
    -------
    BeartypePlugInstancecheckStrException
        If the metaclass of this isinstanceable class defines the
        :mod:`beartype`-specific ``__instancecheck_str__()`` dunder method but
        either:

        * This method is *not* a pure-Python callable.
        * This method is a pure-Python callable with an unexpected signature
          that differs from the expected API:

          .. code-block:: python

             def __instancecheck_str__(cls, obj: typing.Any) -> str:

        * This method is a pure-Python callable with the expected signature that
          returns either:

          * An object that is *not* a string.
          * The empty string.
    ViolationCause
        Output cause type-checking this data.
    '''
    assert isinstance(cause, ViolationCause), f'{repr(cause)} not cause.'

    # Isinstanceable class against which this pith was type-checked.
    hint: type = cause.hint  # type: ignore[assignment]

    # Pith type-checked against this isinstanceable class.
    pith = cause.pith

    # If this hint is *NOT* an isinstanceable class, raise an exception.
    die_unless_type_isinstanceable(
        cls=hint,
        exception_cls=_BeartypeCallHintPepRaiseException,
        exception_prefix=cause.exception_prefix,
    )
    # Else, this hint is an isinstanceable class.

    # Output cause justification. If this pith either:
    # * Violates this hint, this is a human-readable substring describing this
    #   violation.
    # * Satisfies this hint, "None".
    cause_str_or_none: Optional[str] = None

    # If this pith is *NOT* an instance of this class...
    if not isinstance(pith, hint):
        # Metaclass-specific __instancecheck_str__() dunder method if the
        # metaclass of this class defines this method *OR* "None" otherwise
        # (i.e., if that metaclass does *NOT* define this method).
        #
        # Note that this constitutes a plugin API. Although currently
        # beartype-specific, this API is intended to receive widespread adoption
        # as a pseudo-standard throughout the runtime type-checking community
        # (e.g., by typeguard and possibly Pydantic). Various third-party
        # packages that publish custom type hint factories currently leverage
        # this API to generate package-specific violation messages, including:
        # * @patrick-kidger's "jaxtyping" package. For the good of Google!
        get_hint_violation_str = getattr(hint, '__instancecheck_str__', None)

        # If the metaclass of this class defines this dunder method...
        if get_hint_violation_str:
            # Human-readable substring prefixing *ALL* exceptions raised below.
            EXCEPTION_PREFIX = (
                f'{cause.exception_prefix}{repr(hint)} '
                f'beartype-specific dunder method __instancecheck_str__() '
            )

            # If this method is *NOT* a pure-Python callable accepting exactly
            # two parameters, this method does *NOT* satisfy the expected API:
            #      def __instancecheck_str__(cls, obj: typing.Any) -> str:
            #
            # In this case, raise an exception.
            die_unless_func_args_len_flexible_equal(
                func=get_hint_violation_str,
                func_args_len_flexible=2,
                exception_cls=BeartypePlugInstancecheckStrException,
                exception_prefix=EXCEPTION_PREFIX,
            )
            # Else, this method satisfies the expected API.

            # Human-readable substring describing this violation generated by
            # the metaclass of this class.
            cause_str_or_none = get_hint_violation_str(pith)

            # If this string is *NOT* actually a string, raise an exception.
            if not isinstance(cause_str_or_none, str):
                raise BeartypePlugInstancecheckStrException(
                    f'{EXCEPTION_PREFIX}return {cause_str_or_none} not string.')
            # Else, this string is actually a string.
            #
            # If this string is empty, raise an exception.
            elif not cause_str_or_none:
                raise BeartypePlugInstancecheckStrException(
                    f'{EXCEPTION_PREFIX}return string empty.')
            # Else, this string is non-empty.
        # Else, the metaclass of this class does *NOT* define this method. In
        # this case, fallback to a standard substring describing this violation.
        else:
            cause_str_or_none = (
                f'{represent_pith(pith)} not instance of '
                f'{label_type(cls=hint, is_color=cause.conf.is_color)}'
            )
    # Else, this pith is an instance of this class.

    # Output cause to be returned, permuted from this input cause with this
    # output cause justification.
    cause_return = cause.permute_cause(cause_str_or_none=cause_str_or_none)

    # Return this output cause.
    return cause_return


def find_cause_instance_type_forwardref(
    cause: ViolationCause) -> ViolationCause:
    '''
    Output cause describing whether the pith of the passed input cause either is
    or is not an instance of the class referred to by the **forward reference
    type hint** (i.e., string whose value is the either absolute *or* relative
    name of a user-defined type which has yet to be defined) of that cause.

    Parameters
    ----------
    cause : ViolationCause
        Input cause providing this data.

    Returns
    -------
    ViolationCause
        Output cause type-checking this data.
    '''
    assert isinstance(cause, ViolationCause), f'{repr(cause)} not cause.'
    assert cause.hint_sign is HintSignForwardRef, (
        f'{cause.hint_sign} not forward reference.')

    # Class referred to by this absolute or relative forward reference.
    hint_ref_type = import_pep484585_ref_type(
        hint=cause.hint,  # type: ignore[arg-type]
        cls_stack=cause.cls_stack,
        func=cause.func,
        exception_cls=BeartypeCallHintForwardRefException,
        exception_prefix=cause.exception_prefix,
    )

    # Output cause to be returned.
    cause_return = cause.permute_cause_hint_child_insane(hint_ref_type)

    # Defer to the function handling isinstanceable classes. Neato!
    return find_cause_instance_type(cause_return)


def find_cause_type_instance_origin(cause: ViolationCause) -> ViolationCause:
    '''
    Output cause describing whether the pith of the passed input cause either is
    or is not an instance of the isinstanceable type underlying the
    **originative type hint** (i.e., PEP-compliant type hint originating from a
    non-:mod:`typing` class, typically due to being either a
    :pep:`585`-compliant type hint *or* a third-party type hint subclassing the
    :class:`types.GenericAlias` superclass defined by :pep:`585`) of that cause.

    Parameters
    ----------
    cause : ViolationCause
        Input cause providing this data.

    Returns
    -------
    ViolationCause
        Output cause type-checking this data.
    '''
    assert isinstance(cause, ViolationCause), f'{repr(cause)} not cause.'

    # Isinstanceable origin type originating this hint if any *OR* "None".
    hint_type = get_hint_pep_origin_type_isinstanceable_or_none(cause.hint)

    # If this hint does *NOT* originate from such a type, raise an exception.
    if hint_type is None:
        raise _BeartypeCallHintPepRaiseException(
            f'{cause.exception_prefix}type hint '
            f'{repr(cause.hint)} not originated from '
            f'isinstanceable origin type.'
        )
    # Else, this hint originates from such a type.

    # Output cause to be returned.
    cause_return = cause.permute_cause_hint_child_insane(hint_type)

    # Defer to the getter function handling non-"typing" classes. Presto!
    return find_cause_instance_type(cause_return)

# ....................{ GETTERS ~ instance : types         }....................
def find_cause_instance_types_tuple(cause: ViolationCause) -> ViolationCause:
    '''
    Output cause describing whether the pith of the passed input cause either is
    or is not an instance of one or more isinstanceable types in the tuple of
    these types of that cause.

    Parameters
    ----------
    cause : ViolationCause
        Input cause providing this data.

    Returns
    -------
    ViolationCause
        Output cause type-checking this data.
    '''
    assert isinstance(cause, ViolationCause), f'{repr(cause)} not cause.'

    # This tuple union.
    hint: TupleTypes = cause.hint  # type: ignore[assignment]

    # If this hint is *NOT* a tuple union, raise an exception.
    die_unless_hint_nonpep_tuple(
        hint=hint,
        exception_prefix=cause.exception_prefix,
        exception_cls=_BeartypeCallHintPepRaiseException,
    )
    # Else, this hint is a tuple union.

    # If this pith is an instance of one or more types in this tuple union,
    # record that this pith satisfies this tuple union.
    if isinstance(cause.pith, hint):
        cause_return = cause.permute_cause(cause_str_or_none=None)
    # Else, this pith is an instance of *NO* types in this tuple union. In
    # this case, this pith violates this tuple union.
    else:
        # Machine-readable representation of this tuple union.
        hint_repr = join_delimited_disjunction_types(
            types=hint, is_color=cause.conf.is_color)

        # Output cause to be returned, permuted from this input cause such that
        # the output cause justification is a substring describing this failure.
        cause_return = cause.permute_cause(cause_str_or_none=(
            f'{represent_pith(cause.pith)} not instance of {hint_repr}'))

    # Return this output cause.
    return cause_return
