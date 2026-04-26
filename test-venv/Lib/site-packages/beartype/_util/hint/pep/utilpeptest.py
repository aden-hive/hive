#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **PEP-compliant type hint tester** (i.e., callable validating an
arbitrary object to be a PEP-compliant type hint) utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import (
    BeartypeDecorHintPepException,
    BeartypeDecorHintPepUnsupportedException,
    BeartypeDecorHintPep484Exception,
)
from beartype.typing import (
    NoReturn,
)
from beartype._data.typing.datatypingport import (
    Hint,
    TypeIs,
)
from beartype._data.typing.datatyping import TypeException
from beartype._data.hint.sign.datahintsignset import (
    HINT_SIGNS_SUPPORTED,
    HINT_SIGNS_TYPE_MIMIC,
)
from beartype._data.api.standard.datatyping import TYPING_MODULE_NAMES
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.module.utilmodget import get_object_module_name_or_none
from beartype._util.utilobject import get_object_type_unless_type

# ....................{ EXCEPTIONS                         }....................
def die_if_hint_pep(
    # Mandatory parameters.
    hint: object,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPepException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception of the passed type if the passed object is a
    **PEP-compliant type hint** (i.e., :mod:`beartype`-agnostic annotation
    compliant with annotation-centric PEPs).

    This validator is effectively (but technically *not*) memoized. See the
    :func:`beartype._util.hint.utilhinttest.die_unless_hint` validator.

    Parameters
    ----------
    hint : object
        Object to be validated.
    exception_cls : Type[Exception], optional
        Type of the exception to be raised by this function. Defaults to
        :exc:`.BeartypeDecorHintPepException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    exception_cls
        If this object is a PEP-compliant type hint.
    '''

    # If this hint is PEP-compliant...
    if is_hint_pep(hint):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not type.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Raise an exception of this class.
        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} is PEP-compliant '
            f'(e.g., rather than isinstanceable class).'
        )


def die_unless_hint_pep(
    # Mandatory parameters.
    hint: object,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPepException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is a **PEP-compliant type
    hint** (i.e., :mod:`beartype`-agnostic annotation compliant with
    annotation-centric PEPs).

    This validator is effectively (but technically *not*) memoized. See also the
    :func:`beartype._util.hint.utilhinttest.die_unless_hint` validator.

    Parameters
    ----------
    hint : object
        Object to be validated.
    exception_cls : Type[Exception], optional
        Type of the exception to be raised by this function. Defaults to
        :class:`.BeartypeDecorHintPepException`.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    exception_cls
        If this object is *not* a PEP-compliant type hint.
    '''

    # If this hint is *NOT* PEP-compliant, raise an exception.
    if not is_hint_pep(hint):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not type.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} not PEP-compliant.')

# ....................{ EXCEPTIONS ~ supported             }....................
def die_if_hint_pep_unsupported(
    # Mandatory parameters.
    hint: object,

    # Optional parameters.
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception if the passed object is a **PEP-compliant unsupported
    type hint** (i.e., :mod:`beartype`-agnostic annotation compliant with
    annotation-centric PEPs currently *not* supported by the
    :func:`beartype.beartype` decorator).

    This validator is effectively (but technically *not*) memoized. See the
    :func:`beartype._util.hint.utilhinttest.die_unless_hint` validator.

    Caveats
    -------
    **This validator only shallowly validates this object.** If this object is a
    subscripted PEP-compliant type hint (e.g., ``Union[str, List[int]]``), this
    validator ignores all subscripted arguments (e.g., ``List[int]``) on this
    hint and may thus return false positives for hints that are directly
    supported but whose subscripted arguments are not. To deeply validate this
    object, iteratively call this validator during a recursive traversal (such
    as a breadth-first search) over each subscripted argument of this object.

    Parameters
    ----------
    hint : object
        Object to be validated.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    BeartypeDecorHintPepException
        If this object is *not* a PEP-compliant type hint.
    BeartypeDecorHintPepUnsupportedException
        If this object is a PEP-compliant type hint but is currently
        unsupported by the :func:`beartype.beartype` decorator.
    BeartypeDecorHintPep484Exception
        If this object is the PEP-compliant :attr:`typing.NoReturn` type hint,
        which is contextually valid in only a single use case and thus
        supported externally by the :mod:`beartype._decor._nontype._wrap.wrapmain`
        submodule rather than with general-purpose automation.
    '''

    # If this object is a supported PEP-compliant type hint, reduce to a noop.
    #
    # Note that this memoized call is intentionally passed positional rather
    # than keyword parameters to maximize efficiency.
    if is_hint_pep_supported(hint):
        return
    # Else, this object is *NOT* a supported PEP-compliant type hint. In this
    # case, subsequent logic raises an exception specific to the passed
    # parameters.

    # If this hint is *NOT* PEP-compliant, raise a more readable exception.
    die_unless_hint_pep(hint=hint, exception_prefix=exception_prefix)
    assert isinstance(exception_prefix, str), (
        f'{repr(exception_prefix)} not string.')
    # Else, this hint is PEP-compliant.

    #FIXME: Pretty weird, honestly. This would almost certainly better be
    #raised in a reducer testing whether "arg_name == ARG_NAME_RETURN".
    # If this is the PEP 484-compliant "typing.NoReturn" type hint permitted
    # *ONLY* as a return annotation, raise an exception specific to this hint.
    if hint is NoReturn:
        raise BeartypeDecorHintPep484Exception(
            f'{exception_prefix}PEP 484 type hint "{repr(hint)}" '
            f'invalid in this type hint context (i.e., '
            f'"{repr(hint)}" valid only as non-nested return annotation).'
        )
    # Else, this is any PEP-compliant type hint other than "typing.NoReturn".

    # In this case, raise a general-purpose exception.
    #
    # Note that, by definition, the sign uniquely identifying this hint *SHOULD*
    # be in the "HINT_SIGNS_SUPPORTED" set. Regardless of whether it is or not,
    # we raise a similar exception in either case. Ergo, there is *NO* practical
    # benefit to validating that expectation here.
    raise BeartypeDecorHintPepUnsupportedException(
        f'{exception_prefix}type hint {repr(hint)} '
        f'currently unsupported by @beartype.'
    )

# ....................{ WARNINGS                           }....................
#FIXME: Unit test us up.
#FIXME: Actually use us in place of die_if_hint_pep_unsupported().
#FIXME: Actually, it's unclear whether we still require or desire this. See
#"_pephint" commentary for further details.
# def warn_if_hint_pep_unsupported(
#     # Mandatory parameters.
#     hint: object,
#
#     # Optional parameters.
#     exception_prefix: str = 'Annotated',
# ) -> bool:
#     '''
#     Return ``True`` and emit a non-fatal warning only if the passed object is a
#     **PEP-compliant unsupported type hint** (i.e., :mod:`beartype`-agnostic
#     annotation compliant with annotation-centric PEPs currently *not* supported
#     by the :func:`beartype.beartype` decorator).
#
#     This validator is effectively (but technically *not*) memoized. See the
#     :func:`beartype._util.hint.utilhinttest.die_unless_hint` validator.
#
#     Parameters
#     ----------
#     hint : object
#         Object to be validated.
#     exception_prefix : Optional[str]
#         Human-readable label prefixing this object's representation in the
#         warning message emitted by this function. Defaults to the empty string.
#
#     Returns
#     ----------
#     bool
#         ``True`` only if this PEP-compliant type hint is currently supported by
#         that decorator.
#
#     Raises
#     ----------
#     BeartypeDecorHintPepException
#         If this object is *not* a PEP-compliant type hint.
#
#     Warnings
#     ----------
#     BeartypeDecorHintPepUnsupportedWarning
#         If this object is a PEP-compliant type hint currently unsupported by
#         that decorator.
#     '''
#
#     # True only if this object is a supported PEP-compliant type hint.
#     #
#     # Note that this memoized call is intentionally passed positional rather
#     # than keyword parameters to maximize efficiency.
#     is_hint_pep_supported_test = is_hint_pep_supported(hint)
#
#     # If this object is an unsupported PEP-compliant type hint...
#     if not is_hint_pep_supported_test:
#         assert isinstance(exception_prefix, str), f'{repr(exception_prefix)} not string.'
#
#         # If this hint is *NOT* PEP-compliant, raise an exception.
#         die_unless_hint_pep(hint=hint, exception_prefix=exception_prefix)
#
#         # Else, this hint is PEP-compliant. In this case, emit a warning.
#         warn(
#             (
#                 f'{exception_prefix}PEP type hint {repr(hint)} '
#                 f'currently unsupported by @beartype.'
#             ),
#             BeartypeDecorHintPepUnsupportedWarning
#         )
#
#     # Return true only if this object is a supported PEP-compliant type hint.
#     return is_hint_pep_supported_test

# ....................{ TESTERS                            }....................
def is_hint_pep(hint: object) -> TypeIs[Hint]:
    '''
    :data:`True` only if the passed object is a **PEP-compliant type hint**
    (i.e., object complying with one or more :mod:`typing`-centric Python
    Enhancement Proposals (PEPs)).

    This tester is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Motivation
    ----------
    Standard Python types allow callers to test for compliance with protocols,
    interfaces, and abstract base classes by calling either the
    :func:`isinstance` or :func:`issubclass` builtins. This is the
    well-established Pythonic standard for deciding conformance to an API.

    Insanely, :pep:`484` *and* the :mod:`typing` module implementing :pep:`484`
    reject community standards by explicitly preventing callers from calling
    either the :func:`isinstance` or :func:`issubclass` builtins on most but
    *not* all :pep:`484` objects and types. Moreover, neither :pep:`484` nor
    :mod:`typing` implement public APIs for testing whether arbitrary objects
    comply with :pep:`484` or :mod:`typing`.

    Thus this function, which "fills in the gaps" by implementing this
    laughably critical oversight.

    Parameters
    ----------
    hint : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a PEP-compliant type hint.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none

    # Sign uniquely identifying this hint if this hint is PEP-compliant *OR*
    # "None" otherwise (i.e., if this hint is *NOT* PEP-compliant).
    hint_sign = get_hint_pep_sign_or_none(hint)  # pyright: ignore
    # print(f'hint: {repr(hint)}; sign: {repr(hint_sign)}')

    # Return true *ONLY* if this hint is uniquely identified by a sign and thus
    # PEP-compliant.
    return hint_sign is not None


#FIXME: Currently unused but preserved for posterity. *shrug*
# def is_hint_pep_deprecated(hint: object) -> bool:
#     '''
#     :data:`True` only if the passed PEP-compliant type hint is **deprecated**
#     (i.e., obsoleted by an equivalent PEP-compliant type hint standardized by a
#     more recently released PEP).
#
#     This tester is intentionally *not* memoized (e.g., by the
#     ``callable_cached`` decorator), as this tester is currently *only* called at
#     test time from our test suite.
#
#     Parameters
#     ----------
#     hint : object
#         PEP-compliant type hint to be inspected.
#
#     Returns
#     -------
#     bool
#         :data:`True` only if this PEP-compliant type hint is deprecated.
#     '''
#
#     # Avoid circular import dependencies.
#     from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign
#
#     # Sign uniquely identifying this hint.
#     hint_sign = get_hint_pep_sign(hint)
#
#     # Return true only if either...
#     return (
#         # This sign is that of an unconditionally deprecated type hint *OR*...
#         hint_sign in HINT_SIGNS_DEPRECATED or
#         # This is a PEP 484-compliant type hint (e.g., "typing.List[str]")
#         # conditionally deprecated by an equivalent PEP 585-compliant type hint
#         # (e.g., "list[str]") under Python >= 3.9.
#         #
#         # Note that, in this case, the sign of this hint does *NOT* convey
#         # enough metadata to ascertain whether this hint is deprecated. Ergo, a
#         # non-trivial tester dedicated to this discernment is required: e.g.,
#         # * "list[str]" has the sign "HintSignList" but is *NOT* deprecated.
#         # * "typing.List[str]" has the sign "HintSignList" but is deprecated.
#         is_hint_pep484_deprecated(hint)
#     )


#FIXME: Unit test us up, please.
def is_hint_pep_subbed(hint: object) -> bool:
    '''
    :data:`True` only if the passed PEP-compliant type hint is **subscripted**
    (i.e., indexed by one or more child type hints).

    This tester is intentionally *not* memoized (e.g., by the
    :func:`beartype._util.cache.utilcachecall.callable_cached` decorator), as
    the implementation trivially reduces to an efficient one-liner.

    Parameters
    ----------
    hint : object
        PEP-compliant type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this PEP-compliant type hint is subscripted.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import get_hint_pep_args

    # Return true only if the tuple of all child type hints subscripting this
    # hint contains one or more child type hints.
    return bool(get_hint_pep_args(hint))


@callable_cached
def is_hint_pep_supported(hint: object) -> bool:
    '''
    :data:`True` only if the passed object is a **PEP-compliant supported type
    hint** (i.e., :mod:`beartype`-agnostic annotation compliant with
    annotation-centric PEPs currently supported by the
    :func:`beartype.beartype` decorator).

    This tester is memoized for efficiency.

    Caveats
    -------
    **This tester only shallowly inspects this object.** If this object is a
    subscripted PEP-compliant type hint (e.g., ``Union[str, List[int]]``), this
    tester ignores all subscripted arguments (e.g., ``List[int]``) on this hint
    and may thus return false positives for hints that are directly supported
    but whose subscripted arguments are not.

    To deeply inspect this object, iteratively call this tester during a
    recursive traversal over each subscripted argument of this object.

    Parameters
    ----------
    hint : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a supported PEP-compliant type hint.
    '''

    # If this hint is *NOT* PEP-compliant, immediately return false.
    if not is_hint_pep(hint):
        return False
    # Else, this hint is PEP-compliant.

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign

    # Sign uniquely identifying this hint.
    hint_sign = get_hint_pep_sign(hint)

    # Return true only if this sign is supported.
    return hint_sign in HINT_SIGNS_SUPPORTED

# ....................{ TESTERS ~ typing                   }....................
#FIXME: Replace all hardcoded "'typing" strings throughout the codebase with
#access of "TYPING_MODULE_NAMES" instead. We only see one remaining in:
#* beartype._util.hint.pep.proposal.pep484.pep484.py
#
#Thankfully, nobody really cares about generalizing that one edge case to
#"testing_extensions", so it's mostly fine for various definitions of fine.
def is_hint_pep_typing(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed type hint is an attribute of a **typing
    module** (i.e., module officially declaring attributes usable for creating
    PEP-compliant type hints accepted by both static and runtime type checkers).

    This tester is intentionally *not* memoized (e.g., by the
    :func:`.callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this type hint is an attribute of a typing module.
    '''
    # print(f'is_hint_pep_typing({repr(hint)}')

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none

    # Return true only if this hint is either...
    return (
        # Any PEP-compliant type hint defined by a typing module (except those
        # maliciously masquerading as another type entirely) *OR*...
        get_object_module_name_or_none(hint) in TYPING_MODULE_NAMES or
        # Any PEP-compliant type hint defined by a typing module maliciously
        # masquerading as another type entirely.
        get_hint_pep_sign_or_none(hint) in HINT_SIGNS_TYPE_MIMIC  # pyright: ignore
    )


def is_hint_pep_type_typing(hint: Hint) -> bool:
    '''
    :data:`True` only if either the passed type hint is defined by a **typing
    module** (i.e., module officially declaring attributes usable for creating
    PEP-compliant type hints accepted by both static and runtime type checkers)
    if this hint is a class *or* the class of this hint is defined by a typing
    module otherwise (i.e., if this object is *not* a class).

    This tester is intentionally *not* memoized (e.g., by the
    :func:`.callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if either:

        * If this hint is a class, this class is defined by a typing module.
        * Else, the class of this hint is defined by a typing module.
    '''

    # This hint if this hint is a class *OR* this hint's class otherwise.
    hint_type = get_object_type_unless_type(hint)
    # print(f'pep_type_typing({repr(hint)}): {get_object_module_name(hint_type)}')

    # Return true only if this type is defined by a typing module.
    #
    # Note that this implementation could probably be reduced to the
    # leading portion of the body of the get_hint_pep_sign_or_none()
    # function testing this object's representation. While certainly more
    # compact and convenient than the current approach, that refactored
    # approach would also be considerably more fragile, failure-prone, and
    # subject to whimsical "improvements" in the already overly hostile
    # "typing" API. Why? Because the get_hint_pep_sign_or_none() function:
    # * Parses the machine-readable string returned by the __repr__()
    #   dunder method of "typing" types. Since that string is *NOT*
    #   standardized by PEP 484 or any other PEP, "typing" authors remain
    #   free to violate this pseudo-standard in any manner and at any time
    #   of their choosing.
    # * Suffers common edge cases for "typing" types whose __repr__()
    #   dunder methods fail to comply with the non-standard implemented by
    #   their sibling types. This includes the common "TypeVar" type.
    # * Calls this tester function to decide whether the passed object is a
    #   PEP-compliant type hint or not before subjecting that object to
    #   further introspection, which would clearly complicate implementing
    #   this tester function in terms of that getter function.
    #
    # In contrast, the current approach only tests the standard
    # "__module__" dunder attribute and is thus significantly more robust
    # against whimsical destruction by "typing" authors. Note that there
    # might exist an alternate means of deciding this boolean, documented
    # here merely for completeness:
    #     try:
    #         isinstance(obj, object)
    #         return False
    #     except TypeError as type_error:
    #         return str(type_error).endswith(
    #             'cannot be used with isinstance()')
    #
    # The above effectively implements an Aikido throw by using the fact
    # that "typing" types prohibit isinstance() calls against those types.
    # While clever (and deliciously obnoxious), the above logic:
    # * Requires catching exceptions in the common case and is thus *MUCH*
    #   less efficient than the preferable approach implemented here.
    # * Assumes that *ALL* "typing" types prohibit such calls. Sadly, only
    #   a proper subset of these types prohibit such calls.
    # * Assumes that those "typing" types that do prohibit such calls raise
    #   exceptions with reliable messages across *ALL* Python versions.
    #
    # In short, there is no general-purpose clever solution. *sigh*
    return hint_type.__module__ in TYPING_MODULE_NAMES
