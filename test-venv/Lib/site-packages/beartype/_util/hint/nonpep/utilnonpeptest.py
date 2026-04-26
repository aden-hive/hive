#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **PEP-noncompliant type hint tester** (i.e., callable validating an
arbitrary object to be a PEP-noncompliant type hint) utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: Validate strings to be syntactically valid classnames via a globally
#scoped compiled regular expression. Raising early exceptions at decoration
#time is preferable to raising late exceptions at call time.
#FIXME: Indeed, we now provide such a callable:
#    from beartype._util.module.utilmodget import die_unless_module_attr_name

# ....................{ IMPORTS                            }....................
from beartype.meta import URL_ISSUES
from beartype.roar import BeartypeDecorHintNonpepException
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.cls.pep.clspep3119 import (
    die_unless_type_isinstanceable,
    is_type_isinstanceable,
)
from beartype._data.typing.datatyping import TypeException

# ....................{ VALIDATORS                         }....................
#FIXME: Unit test us up, please.
def die_if_hint_nonpep(
    # Mandatory parameters.
    hint: object,

    # Optional parameters.
    is_forwardref_valid: bool = False,
    exception_cls: TypeException = BeartypeDecorHintNonpepException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception if the passed object is a **PEP-noncompliant type hint**
    (i.e., :mod:`beartype`-specific annotation *not* compliant with
    annotation-centric PEPs).

    This validator is effectively (but technically *not*) memoized. See the
    :func:`beartype._util.hint.utilhinttest.die_unless_hint` validator.

    Parameters
    ----------
    hint : object
        Object to be validated.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to contain
        forward references. Defaults to :data:`False`. If this boolean is:

        * :data:`True`, this object is valid only when containing classes and/or
          forward references.
        * :data:`False`, this object is valid only when containing classes.
    exception_cls : type[Exception]
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintNonpepException`.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    exception_cls
        If this object is either:

        * An **isinstanceable type** (i.e., standard class passable as the
          second parameter to the :func:`isinstance` builtin and thus typically
          *not* compliant with annotation-centric PEPs).
        * A **non-empty tuple** (i.e., semantic union of types) containing one
          or more:

          * Non-:mod:`typing` types.
          * If ``is_forwardref_valid`` is :data:`True`, forward references.
    '''

    # If this object is a PEP-noncompliant type hint, raise an exception.
    #
    # Note that this memoized call is intentionally passed positional rather
    # than keyword parameters to maximize efficiency.
    if is_hint_nonpep(hint, is_forwardref_valid):
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not type.')
        assert issubclass(exception_cls, Exception), (
            f'{repr(exception_cls)} not exception type.')

        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} '
            f'is PEP-noncompliant (e.g., either ' +
            (
                (
                    'isinstanceable type, forward reference, or tuple of '
                    'isinstanceable types and/or forward references).'
                )
                if is_forwardref_valid else
                'isinstanceable type or tuple of isinstanceable types).'
            )
        )
    # Else, this object is *NOT* a PEP-noncompliant type hint.


#FIXME: Unit test this function with respect to non-isinstanceable classes.
def die_unless_hint_nonpep(
    # Mandatory parameters.
    hint: object,

    # Optional parameters.
    is_forwardref_valid: bool = False,
    exception_cls: TypeException = BeartypeDecorHintNonpepException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is a **PEP-noncompliant type
    hint** (i.e., :mod:`beartype`-specific annotation *not* compliant with
    annotation-centric PEPs).

    This validator is effectively (but technically *not*) memoized. See also the
    :func:`beartype._util.hint.utilhinttest.die_unless_hint` validator.

    Parameters
    ----------
    hint : object
        Object to be validated.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to contain
        forward references. Defaults to :data:`False`. If this boolean is:

        * :data:`True`, this object is valid only when containing classes and/or
          forward references.
        * :data:`False`, this object is valid only when containing classes.
    exception_cls : type[Exception], optional
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintNonpepException`.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    exception_cls
        If this object is neither:

        * An **isinstanceable type** (i.e., standard class passable as the
          second parameter to the :func:`isinstance` builtin and thus typically
          *not* compliant with annotation-centric PEPs).
        * A **non-empty tuple** (i.e., semantic union of types) containing one
          or more:

          * Non-:mod:`typing` types.
          * If ``is_forwardref_valid`` is :data:`True`, forward references.
    '''

    # If this object is a PEP-noncompliant type hint, reduce to a noop.
    #
    # Note that this memoized call is intentionally passed positional rather
    # than keyword parameters to maximize efficiency.
    if is_hint_nonpep(hint, is_forwardref_valid):
        return
    # Else, this object is *NOT* a PEP-noncompliant type hint. In this case,
    # subsequent logic raises an exception specific to the passed parameters.

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # BEGIN: Synchronize changes here with the is_hint_nonpep() tester below.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    assert isinstance(exception_cls, type), (
        f'{repr(exception_cls)} not type.')
    assert isinstance(exception_prefix, str), (
        f'{repr(exception_prefix)} not string.')

    # If this object is a type...
    if isinstance(hint, type):
        # If this type is *NOT* PEP-noncompliant (e.g., is either PEP-compliant
        # *OR* is not an isinstanceable type), raise an exception.
        die_unless_hint_nonpep_type(
            hint=hint,
            is_forwardref_valid=is_forwardref_valid,
            exception_prefix=exception_prefix,
            exception_cls=exception_cls,
        )
        # Else, this type is PEP-noncompliant and thus isinstanceable by
        # definition.

        # Silently accept this isinstanceable type as is.
        return
    # Else, this object is *NOT* a type.
    #
    # If this object is a tuple, raise a tuple-specific exception.
    elif isinstance(hint, tuple):
        die_unless_hint_nonpep_tuple(
            hint=hint,
            is_forwardref_valid=is_forwardref_valid,
            exception_prefix=exception_prefix,
            exception_cls=exception_cls,
        )
    # Else, this object is neither a type *NOR* tuple.

    # Avoid circular import dependencies.
    from beartype._util.hint.utilhinttest import die_as_hint_unsupported

    # Raise a generic exception message as a fallback.
    die_as_hint_unsupported(
        hint=hint,
        exception_prefix=exception_prefix,
        exception_cls=exception_cls,
    )

# ....................{ VALIDATORS ~ kind                  }....................
#FIXME: Unit test us up.
def die_unless_hint_nonpep_type(
    # Mandatory parameters.
    hint: type,

    # Optional parameters.
    is_forwardref_valid: bool = False,
    exception_cls: TypeException = BeartypeDecorHintNonpepException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is an **isinstanceable type**
    (i.e., standard class passable as the second parameter to the
    :func:`isinstance` builtin and thus typically *not* compliant with
    annotation-centric PEPs).

    This validator is effectively (but technically *not*) memoized. See the
    :func:`beartype._util.hint.utilhinttest.die_unless_hint` validator.

    Parameters
    ----------
    hint : type
        Object to be validated.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to be a
        forward reference. Defaults to :data:`False`. If this boolean is:

        * :data:`True`, this object is valid only when a class and/or forward
          reference.
        * :data:`False`, this object is valid only when a class.
    exception_cls : Optional[type]
        Type of the exception to be raised by this function. Defaults to
        :exc:`.BeartypeDecorHintNonpepException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    BeartypeDecorHintPep3119Exception
        If this object is *not* an isinstanceable class (i.e., class passable
        as the second argument to the :func:`isinstance` builtin).
    exception_cls
        If this object is a PEP-compliant type hint.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpeptest import die_if_hint_pep

    # If this object is a PEP-compliant type hint, raise an exception.
    die_if_hint_pep(
        hint=hint,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this object is *NOT* a PEP-compliant type hint.

    # If this object is *NOT* an isinstanceable class, raise an exception. Note
    # that this validation is typically slower than the prior validation and
    # thus intentionally performed last.
    die_unless_type_isinstanceable(
        cls=hint,
        is_forwardref_valid=is_forwardref_valid,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # If this object is an isinstanceable class.


#FIXME: Unit test this function with respect to tuples containing
#non-isinstanceable classes.
#FIXME: Optimize both this and the related _is_hint_nonpep_tuple() tester
#defined below. The key realization here is that EAFP is *MUCH* faster in this
#specific case than iteration. Why? Because iteration is guaranteed to
#internally raise a stop iteration exception, whereas EAFP only raises an
#exception if this tuple is invalid, in which case efficiency is no longer a
#concern. So, what do we do instead? Simple. We internally refactor:
#* If "is_forwardref_valid" is True, we continue to perform the existing
#  implementation of both functions. *shrug*
#* Else, we:
#  * Perform a new optimized EAFP-style isinstance() check resembling that
#    performed by die_unless_type_isinstanceable().
#  * Likewise for _is_hint_nonpep_tuple() vis-a-vis is_type_isinstanceable().
#Fortunately, tuple unions are now sufficiently rare in the wild (i.e., in
#real-world use cases) that this mild inefficiency probably no longer matters.
#FIXME: Indeed! Now that we have the die_unless_object_isinstanceable()
#validator, this validator should reduce to efficiently calling
#die_unless_object_isinstanceable() directly if "is_forwardref_valid" is False.
#die_unless_object_isinstanceable() performs the desired EAFP-style
#isinstance() check in an optimally efficient manner.
def die_unless_hint_nonpep_tuple(
    # Mandatory parameters.
    hint: object,

    # Optional parameters.
    is_forwardref_valid: bool = False,
    exception_cls: TypeException = BeartypeDecorHintNonpepException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is a **PEP-noncompliant tuple**
    (i.e., :mod:`beartype`-specific tuple of one or more PEP-noncompliant types
    *not* compliant with annotation-centric PEPs).

    This validator is effectively (but technically *not*) memoized. See the
    :func:`beartype._util.hint.utilhinttest.die_unless_hint` validator.

    Parameters
    ----------
    hint : object
        Object to be validated.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this tuple to contain
        forward references. Defaults to :data:`False`. If this boolean is:

        * :data:`True`, this tuple is valid only when containing classes and/or
          forward references.
        * :data:`False`, this tuple is valid only when containing classes.
    exception_cls : type, optional
        Type of the exception to be raised by this function. Defaults to
        :exc:`.BeartypeDecorHintNonpepException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    exception_cls
        If this object is neither:

        * A non-:mod:`typing` type (i.e., class *not* defined by the
          :mod:`typing` module, whose public classes are used to instantiate
          PEP-compliant type hints or objects satisfying such hints that
          typically violate standard class semantics and thus require
          PEP-specific handling).
        * A **non-empty tuple** (i.e., semantic union of types) containing one
          or more:

          * Non-:mod:`typing` types.
          * If ``is_forwardref_valid`` is :data:`True`, forward references.
    '''

    # If this object is a tuple union, reduce to a noop.
    #
    # Note that this memoized call is intentionally passed positional rather
    # than keyword parameters to maximize efficiency.
    if _is_hint_nonpep_tuple(hint, is_forwardref_valid):
        return
    # Else, this object is *NOT* a tuple union. In this case, subsequent logic
    # raises an exception specific to the passed parameters.
    #
    # Note that the prior call has already validated "is_forwardref_valid".
    assert isinstance(is_forwardref_valid, bool), (
        f'{repr(is_forwardref_valid)} not bool.')
    assert isinstance(exception_cls, type), f'{repr(exception_cls)} not type.'
    assert isinstance(exception_prefix, str), (
        f'{repr(exception_prefix)} not string.')

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # BEGIN: Synchronize changes here with the _is_hint_nonpep_tuple() tester.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # If this object is *NOT* a tuple, raise an exception.
    if not isinstance(hint, tuple):
        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} not tuple.')
    # Else, this object is a tuple.
    #
    # If this tuple is empty, raise an exception.
    elif not hint:
        raise exception_cls(f'{exception_prefix}tuple type hint empty.')
    # Else, this tuple is non-empty.

    # For each item of this tuple...
    for hint_item in hint:
        # Duplicate the above logic. For negligible efficiency gains (and more
        # importantly to avoid exhausting the stack), avoid calling this
        # function recursively to do so. *shrug*

        # If this item is a class...
        if isinstance(hint_item, type):
            # If this class is *NOT* isinstanceable, raise an exception.
            die_unless_type_isinstanceable(
                cls=hint_item,
                is_forwardref_valid=is_forwardref_valid,
                exception_prefix=exception_prefix,
                exception_cls=exception_cls,
            )
            # Else, this class is isinstanceable.
        # Else, this item is *NOT* a class.
        #
        # If this item is a forward reference...
        elif isinstance(hint_item, str):
            # If forward references are unsupported, raise an exception.
            if not is_forwardref_valid:
                raise exception_cls(
                    f'{exception_prefix}tuple type hint {repr(hint)} '
                    f'forward reference "{hint_item}" unsupported.'
                )
            # Else, silently accept this item.
        # Else, this item is neither a class nor forward reference. Ergo,
        # this item is *NOT* a PEP-noncompliant type hint. In this case,
        # raise an exception whose message contextually depends on whether
        # forward references are permitted or not.
        else:
            raise exception_cls(
                f'{exception_prefix}tuple type hint {repr(hint)} '
                f'item {repr(hint_item)} invalid '
                f'{"neither type nor string" if is_forwardref_valid else "not type"}.'
            )

# ....................{ TESTERS                            }....................
def is_hint_nonpep(
    # Mandatory parameters.
    hint: object,

    # Optional parameters.
    is_forwardref_valid: bool = False,
) -> bool:
    '''
    :data:`True` only if the passed object is a **PEP-noncompliant type hint**
    (i.e., :mod:`beartype`-specific annotation *not* compliant with
    annotation-centric PEPs).

    This tester is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    hint : object
        Object to be inspected.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to contain
        forward references. If this boolean is:

        * :data:`True`, this object is valid only when containing classes and/or
          forward references.
        * :data:`False`, this object is valid only when containing classes.

        Defaults to :data:`False` for safety.

    Returns
    -------
    bool
        :data:`True` only if this object is either:

        * A non-:mod:`typing` type (i.e., class *not* defined by the
          :mod:`typing` module, whose public classes are used to instantiate
          PEP-compliant type hints or objects satisfying such hints that
          typically violate standard class semantics and thus require
          PEP-specific handling).
        * A **non-empty tuple** (i.e., semantic union of types) containing one
          or more:

          * Non-:mod:`typing` types.
          * If ``is_forwardref_valid`` is :data:`True`, forward references.
    '''
    assert isinstance(is_forwardref_valid, bool), (
        f'{repr(is_forwardref_valid)} not bool.')

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # BEGIN: Synchronize changes here with die_unless_hint_nonpep() above.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # Return true only if either...
    return (
        # If this object is a class, return true only if this is is a
        # PEP-noncompliant class (or possibly a caller-permitted forward
        # reference).
        is_hint_nonpep_type(
            hint, is_forwardref_valid) if isinstance(hint, type) else
        # Else, this object is *NOT* a class.
        #
        # If this object is a tuple, return true only if this tuple contains
        # only one or more PEP-noncompliant classes (and possibly
        # caller-permitted forward references).
        _is_hint_nonpep_tuple(
            hint, is_forwardref_valid) if isinstance(hint, tuple) else
        # Else, this object is neither a class nor tuple and thus *CANNOT* be
        # PEP-noncompliant. In this case, fallback to returning false.
        False
    )


#FIXME: Unit test us up, please.
def is_hint_nonpep_type(
    # Mandatory parameters.
    hint: object,

    # Optional parameters.
    is_forwardref_valid: bool = False,
) -> bool:
    '''
    :data:`True` only if the passed object is a PEP-noncompliant isinstanceable
    type (and/or forward reference proxy when ``is_forwardref_valid`` is
    :data:`True`).

    This tester is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the implementation trivially reduces
    to an efficient one-liner.

    Parameters
    ----------
    hint : object
        Object to be inspected.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to be a
        **forward reference proxy** (i.e., :mod:`beartype`-specific private type
        proxying an external type that may currently be undefined). If this
        boolean is:

        * :data:`True`, this object is valid only when this object is either:

          * An isinstanceable type.
          * A forward reference proxy (regardless of whether this proxy is
            currently resolvable to an isinstanceable type that has already been
            externally defined).

        * :data:`False`, this object is valid only when this object is either:

          * An isinstanceable type.
          * A forward reference proxy that is currently resolvable to an
            isinstanceable type that has already been externally defined.

        Defaults to :data:`False` for safety.

    Returns
    -------
    bool
        :data:`True` only if this object is a PEP-noncompliant isinstanceable
        type (and/or forward reference proxy when ``is_forwardref_valid`` is
        :data:`True`).
    '''

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # BEGIN: Synchronize changes here with die_unless_hint_nonpep() above.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpeptest import is_hint_pep

    # Return true only if...
    return (
        # This object is an isinstanceable type *AND*...
        is_type_isinstanceable(hint, is_forwardref_valid) and
        # This object is *NOT* a PEP-compliant type, in which case this object
        # is a PEP-noncompliant type by definition.
        not is_hint_pep(hint)
    )

# ....................{ TESTERS ~ private                  }....................
@callable_cached
def _is_hint_nonpep_tuple(hint: object, is_forwardref_valid: bool) -> bool:
    '''
    :data:`True` only if the passed object is a PEP-noncompliant non-empty tuple
    of one or more types.

    This tester is memoized for efficiency.

    Parameters
    ----------
    hint : object
        Object to be inspected.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this tuple to contain
        forward references. If this boolean is:

        * :data:`True`, this tuple is valid only when containing classes and/or
          classnames.
        * :data:`False`, this tuple is valid only when containing classes.

    Returns
    -------
    bool
        :data:`True` only if this object is a **non-empty tuple** (i.e.,
        semantic union of types) containing one or more:

          * Non-:mod:`typing` types.
          * If ``is_forwardref_valid`` is :data:`True`, forward references.
    '''
    assert isinstance(is_forwardref_valid, bool), (
        f'{repr(is_forwardref_valid)} not bool.')

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # BEGIN: Synchronize changes here with die_unless_hint_nonpep() above.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # If it is *NOT* the case that this object is...
    if not (
        # A tuple *AND*...
        isinstance(hint, tuple) and
        # This tuple is non-empty *AND*...
        hint
    ):
        # This object is either not a tuple *OR* is the empty tuple. In either
        # case, this object is *NOT* a non-empty tuple. Return false.
        return False
    # Else, this object is a non-empty tuple.

    # For each item of this tuple...
    for hint_item in hint:
        # print(f'Inspecting {repr(hint)} item {repr(hint_item)}...')

        # If this item is a type...
        if isinstance(hint_item, type):
            # If this type is *NOT* isinstanceable, return false.
            if not is_hint_nonpep_type(hint_item, is_forwardref_valid):
                # print(f'Non-isinstanceable type {repr(hint_item)} prohibited!')
                return False
            # Else, this type is isinstanceable.
        # Else, this item is *NOT* a type.
        #
        # If this item is a string...
        elif isinstance(hint_item, str):
            # If the caller prohibits forward references, return false.
            if not is_forwardref_valid:
                # print(f'Forward reference {repr(hint_item)} prohibited!')
                return False
            # Else, the caller permits forward references.
        # Else, this item is *NOT* a string. In this case, this item is
        # prohibited as a tuple item of a PEP-noncompliant tuple. Return false.
        else:
            # print(f'Unexpected item {repr(hint_item)} prohibited!')
            return False
    # Else, all items of this tuple are permitted as tuple items of a
    # PEP-noncompliant tuple.

    # Return true.
    return True
