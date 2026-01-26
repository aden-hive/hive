#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`3119`-compliant **class detectors** (i.e., callables
validating and testing various properties of arbitrary classes standardized by
:pep:`3119`).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep3119Exception
from beartype.roar._roarexc import _BeartypeHintForwardRefExceptionMixin
from beartype.typing import Callable
from beartype._data.cls.datacls import TYPES_EXCEPTION_NAMESPACE
from beartype._data.typing.datatypingport import TypeIs
from beartype._data.typing.datatyping import (
    IsBuiltinOrSubclassableTypes,
    TypeException,
)
from beartype._util.cache.utilcachecall import callable_cached

# ....................{ RAISERS ~ instance                 }....................
def die_unless_object_isinstanceable(
    # Mandatory parameters.
    obj: IsBuiltinOrSubclassableTypes,

    # Optional parameters.
    is_forwardref_valid: bool = True,
    exception_cls: TypeException = BeartypeDecorHintPep3119Exception,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception of the passed type unless the passed object is
    **isinstanceable** (i.e., valid as the second parameter to the
    :func:`isinstance` builtin).

    Specifically, this function raises an exception unless this object is
    either:

    * An **isinstanceable class** (i.e., class whose metaclass does *not* define
      an ``__instancecheck__()`` dunder method that raises a :exc:`TypeError`
      exception).
    * Tuple of one or more isinstanceable classes.
    * A :pep:`604`-compliant **new union** (i.e., objects created by expressions
      of the form ``{type1} | {type2} | ... | {typeN}``) under Python >= 3.10.
      By definition, *all* new unions are isinstanceable.

    Parameters
    ----------
    obj : IsBuiltinOrSubclassableTypes
        Object to be validated.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to be a
        **forward reference proxy** (i.e., :mod:`beartype`-specific private type
        proxying an external type that may currently be undefined). Defaults to
        :data:`True`. If this boolean is:

        * :data:`True`, this object is valid only when this object is either an
          isinstanceable classes *or* a forward reference proxy.
        * :data:`False`, this object is valid only when this object is an
          isinstanceable class. Note that forward reference proxies are
          isinstanceable classes *if and only if* the external classes they
          refer to have already been defined.
    exception_cls : TypeException, optional
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintPep3119Exception`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    BeartypeDecorHintPep3119Exception
        If this object is neither:

        * An isinstanceable class.
        * A tuple containing only isinstanceable classes.
        * A :pep:`604`-compliant new union.
    '''

    # Defer to this lower-level general-purpose raiser.
    _die_if_object_uncheckable(
        obj=obj,
        obj_pith=None,
        obj_raiser=die_unless_type_isinstanceable,
        obj_tester=isinstance,  # type: ignore[arg-type]
        is_forwardref_valid=is_forwardref_valid,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )


def die_unless_type_isinstanceable(
    # Mandatory parameters.
    cls: type,

    # Optional parameters.
    is_forwardref_valid: bool = True,
    exception_cls: TypeException = BeartypeDecorHintPep3119Exception,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception of the passed type unless the passed object is an
    **isinstanceable class** (i.e., class whose metaclass does *not* define an
    ``__instancecheck__()`` dunder method that raises a :exc:`TypeError`
    exception).

    Classes that are *not* isinstanceable include most PEP-compliant type hints,
    notably:

    * **Generic aliases** (i.e., subscriptable classes overriding the
      ``__class_getitem__()`` class dunder method standardized by :pep:`560`
      subscripted by an arbitrary object) under Python >= 3.9, whose metaclasses
      define an ``__instancecheck__()`` dunder method to unconditionally raise
      an exception. Generic aliases include:

      * :pep:`484`-compliant **subscripted generics.**
      * :pep:`585`-compliant type hints.

    * User-defined classes whose metaclasses define an ``__instancecheck__()``
      dunder method to unconditionally raise an exception, including:

      * :pep:`544`-compliant protocols *not* decorated by the
        :func:`typing.runtime_checkable` decorator.

    Motivation
    ----------
    When a class whose metaclass defines an ``__instancecheck__()`` dunder
    method is passed as the second parameter to the :func:`isinstance` builtin,
    that builtin defers to that method rather than testing whether the first
    parameter passed to that builtin is an instance of that class. If that
    method raises an exception, that builtin raises the same exception,
    preventing callers from deciding whether arbitrary objects are instances
    of that class. For brevity, we refer to that class as "non-isinstanceable."

    Most classes are isinstanceable, because deciding whether arbitrary objects
    are instances of those classes is a core prerequisite for object-oriented
    programming. Most classes that are also PEP-compliant type hints, however,
    are *not* isinstanceable, because they're *never* intended to be
    instantiated into objects (and typically prohibit instantiation in various
    ways); they're only intended to be referenced as type hints annotating
    callables, an arguably crude form of callable markup.

    :mod:`beartype`-decorated callables typically check the types of arbitrary
    objects at runtime by passing those objects and types as the first and
    second parameters to the :func:`isinstance` builtin. If those types are
    non-isinstanceable, those type-checks will typically raise
    non-human-readable exceptions (e.g., ``"TypeError: isinstance() argument 2
    cannot be a parameterized generic"`` for :pep:`585`-compliant type hints).
    This is non-ideal both because those exceptions are non-human-readable *and*
    because those exceptions are raised at call rather than decoration time,
    where users expect the :func:`beartype.beartype` decorator to raise
    exceptions for erroneous type hints.

    Thus the existence of this function, which the :func:`beartype.beartype`
    decorator frequently calls to validate the usability of type hints that are
    classes *before* checking objects against those classes at call time.

    Caveats
    -------
    **This function considers all classes whose metaclasses define
    ``__instancecheck__()`` dunder methods that raise exceptions other than**
    :exc:`TypeError` **to be isinstanceable.** This function *only* considers
    classes whose metaclasses define ``__instancecheck__()`` dunder methods that
    raise :exc:`TypeError` exceptions to be non-isinstanceable; all other
    classes are isinstanceable.

    Ideally, this function would consider any class whose metaclass defines an
    ``__instancecheck__()`` dunder method that raises any exception (rather than
    merely a :exc:`TypeError` exception) to be non-isinstanceable.
    Pragmatically, doing so would raise false positives in common edge cases --
    and previously did so, in fact, which is why we no longer do so.

    In particular, the metaclass of the passed class may *not* necessarily be
    fully initialized at the early time that this function is called (typically,
    at :func:`beartype.beartype` decoration time). If this is the case, then
    eagerly passing that class to :func:`isinstance` is likely to raise an
    exception. For example, doing so raises an :exc:`AttributeError` when the
    ``__instancecheck__()`` dunder method defined by that metaclass references
    an external attribute that has yet to be defined:

    .. code-block:: python

       from beartype import beartype

       class MetaFoo(type):
           def __instancecheck__(cls, other):
               return g()

       class Foo(metaclass=MetaFoo):
           pass

       # @beartype transitively calls this function to validate that "Foo" is
       # isinstanceable. However, since g() has yet to be defined at this time,
       # doing so raises an "AttributeError" exception despite this logic
       # otherwise being sound.
       @beartype
       def f(x: Foo):
           pass

       def g():
           return True

    This function thus constrains itself to merely the :exc:`TypeError`
    exception, which all non-isinstanceable classes defined by the standard
    :mod:`typing` module unconditionally raise. This suggests that there is
    currently an unambiguous one-to-one mapping between non-isinstanceable
    classes and classes whose metaclass ``__instancecheck__()`` dunder methods
    raise :exc:`TypeError` exceptions. May this mapping hold true forever!

    Parameters
    ----------
    cls : object
        Object to be validated.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to be a
        **forward reference proxy** (i.e., :mod:`beartype`-specific private type
        proxying an external type that may currently be undefined). Defaults to
        :data:`True`. If this boolean is:

        * :data:`True`, this object is valid only when this object is either an
          isinstanceable classes *or* a forward reference proxy.
        * :data:`False`, this object is valid only when this object is an
          isinstanceable class. Note that forward reference proxies are
          isinstanceable classes *if and only if* the external classes they
          refer to have already been defined.
    exception_cls : TypeException, optional
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintPep3119Exception`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    BeartypeDecorHintPep3119Exception
        If this object is *not* an isinstanceable class.

    See Also
    --------
    :func:`.die_unless_type_isinstanceable`
        Further details.
    '''

    # Avoid circular import dependencies.
    from beartype._util.cls.utilclstest import die_unless_type

    # If this object is *NOT* a class, raise an exception.
    die_unless_type(
        cls=cls, exception_cls=exception_cls, exception_prefix=exception_prefix)
    # Else, this object is a class.

    # If this class is isinstanceable, silently reduce to a noop.
    #
    # Note that this merely constitutes an optimization -- albeit a
    # non-negligible optimization. The is_type_isinstanceable() tester is
    # memoized against inefficiencies, including:
    # * An inefficient implementation leveraging the EAFP (Easier to Ask for
    #   Permission than Foregiveness) principle.
    # * Worst-case behaviour in which the metaclass of this class defines an
    #   inefficient __instancecheck__() method outside our control.
    if is_type_isinstanceable(cls, is_forwardref_valid):
        return
    # Else, this class is *NOT* isinstanceable. In this case, raise a
    # human-readable exception embedding the original (typically unreadable)
    # "TypeError" exception implicitly raised by the metaclass of this class.

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Synchronize with the is_type_isinstanceable() tester.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # Attempt to pass this class as the second parameter to isinstance().
    try:
        isinstance(None, cls)  # type: ignore[arg-type]
    # If doing so raised *ANY* exception, this class is *NOT* isinstanceable. In
    # this case, raise a human-readable exception.
    #
    # See the docstring for further discussion.
    except Exception as exception:
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not exception class.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # If this exception ambiguously fails to indicate non-isinstanceability,
        # silently reduce to a noop.
        if _is_exception_ambiguous(exception):
            return
        # Else, this exception unambiguously indicates non-isinstanceability.
        #
        # If this exception already human-readably describes this
        # non-isinstanceability, re-raise this exception as is.
        elif _is_exception_sufficient(exception):
            raise
        # Else, this exception fails to human-readably describe this
        # non-isinstanceability.

        #FIXME: Uncomment after we uncover why doing so triggers an infinite
        #circular exception chain when "hint" is a "GenericAlias". It's clearly
        #the is_hint_pep544_protocol() call, but why? In any case, the simplest
        #workaround would just be to inline the logic of
        #is_hint_pep544_protocol() here directly. Yes, we know. *shrug*

        # # Human-readable exception message to be raised as either...
        # exception_message = (
        #     # If this class is a PEP 544-compliant protocol, a message
        #     # documenting this exact issue and how to resolve it;
        #     (
        #         f'{exception_prefix}PEP 544 protocol {hint} '
        #         f'uncheckable at runtime (i.e., '
        #         f'not decorated by @typing.runtime_checkable).'
        #     )
        #     if is_hint_pep544_protocol(hint) else
        #     # Else, a fallback message documenting this general issue.
        #     (
        #         f'{exception_prefix}type {hint} uncheckable at runtime (i.e., '
        #         f'not passable as second parameter to isinstance() '
        #         f'due to raising "{exception}" from metaclass '
        #         f'__instancecheck__() method).'
        #     )
        # )

        # Exception message to be raised.
        exception_message = (
            f'{exception_prefix}{repr(cls)} uncheckable at runtime '
            f'(i.e., not passable as second parameter to isinstance(), '
            f'due to raising "{exception.__class__.__name__}: {exception}" '
            f'from metaclass '
            f'{cls.__class__.__name__}.__instancecheck__() method).'
        )

        # Raise this exception chained onto this lower-level exception.
        raise exception_cls(exception_message) from exception

# ....................{ RAISERS ~ subclass                 }....................
def die_unless_object_issubclassable(
    # Mandatory parameters.
    obj: IsBuiltinOrSubclassableTypes,

    # Optional parameters.
    is_forwardref_valid: bool = True,
    exception_cls: TypeException = BeartypeDecorHintPep3119Exception,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception of the passed type unless the passed object is
    **issubclassable** (i.e., valid as the second parameter to the
    :func:`issubclass` builtin).

    Specifically, this function raises an exception unless this object is
    either:

    * An **issubclassable class** (i.e., class whose metaclass does *not* define
      an ``__subclasscheck__()`` dunder method that raises a :exc:`TypeError`
      exception).
    * Tuple of one or more issubclassable classes.
    * A :pep:`604`-compliant **new union** (i.e., objects created by expressions
      of the form ``{type1} | {type2} | ... | {typeN}``) under Python >= 3.10.
      By definition, *all* new unions are issubclassable.

    Parameters
    ----------
    obj : object
        Object to be validated.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to be a
        **forward reference proxy** (i.e., :mod:`beartype`-specific private type
        proxying an external type that may currently be undefined). Defaults to
        :data:`True`. If this boolean is:

        * :data:`True`, this object is valid only when this object is either an
          isinstanceable classes *or* a forward reference proxy.
        * :data:`False`, this object is valid only when this object is an
          isinstanceable class. Note that forward reference proxies are
          isinstanceable classes *if and only if* the external classes they
          refer to have already been defined.
    exception_cls : TypeException, optional
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintPep3119Exception`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    BeartypeDecorHintPep3119Exception
        If this object is neither:

        * An issubclassable class.
        * A tuple containing only issubclassable classes.
        * A :pep:`604`-compliant new union.
    '''

    # Defer to this lower-level general-purpose raiser.
    _die_if_object_uncheckable(
        obj=obj,
        obj_pith=type,
        obj_raiser=die_unless_type_issubclassable,
        obj_tester=issubclass,  # type: ignore[arg-type]
        is_forwardref_valid=is_forwardref_valid,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )


def die_unless_type_issubclassable(
    # Mandatory parameters.
    cls: type,

    # Optional parameters.
    is_forwardref_valid: bool = True,
    exception_cls: TypeException = BeartypeDecorHintPep3119Exception,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception of the passed type unless the passed object is an
    **issubclassable class** (i.e., class whose metaclass does *not* define a
    ``__subclasscheck__()`` dunder method that raise a :exc:`TypeError`
    exception).

    Classes that are *not* issubclassable include most PEP-compliant type
    hints, notably:

    * **Generic aliases** (i.e., subscriptable classes overriding the
      ``__class_getitem__()`` class dunder method standardized by :pep:`560`
      subscripted by an arbitrary object) under Python >= 3.9, whose
      metaclasses define an ``__subclasscheck__()`` dunder method to
      unconditionally raise an exception. Generic aliases include:

      * :pep:`484`-compliant **subscripted generics.**
      * :pep:`585`-compliant type hints.

    * User-defined classes whose metaclasses define a ``__subclasscheck__()``
      dunder method to unconditionally raise an exception, including:

      * :pep:`544`-compliant protocols *not* decorated by the
        :func:`typing.runtime_checkable` decorator.

    Motivation
    ----------
    See also the "Motivation" and "Caveats" sections of the
    :func:`.die_unless_type_isinstanceable` docstring for further discussion,
    substituting:

    * ``__instancecheck__()`` for ``__subclasscheck__()``.
    * :func:`isinstance` for :func:`issubclass`.

    Parameters
    ----------
    cls : object
        Object to be validated.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to be a
        **forward reference proxy** (i.e., :mod:`beartype`-specific private type
        proxying an external type that may currently be undefined). Defaults to
        :data:`True`. If this boolean is:

        * :data:`True`, this object is valid only when this object is either an
          isinstanceable classes *or* a forward reference proxy.
        * :data:`False`, this object is valid only when this object is an
          isinstanceable class. Note that forward reference proxies are
          isinstanceable classes *if and only if* the external classes they
          refer to have already been defined.
    exception_cls : TypeException, optional
        Type of exception to be raised. Defaults to
        :exc:`BeartypeDecorHintPep3119Exception`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    BeartypeDecorHintPep3119Exception
        If this object is *not* an issubclassable class.
    '''

    # Avoid circular import dependencies.
    from beartype._util.cls.utilclstest import die_unless_type

    # If this hint is *NOT* a class, raise an exception.
    die_unless_type(
        cls=cls, exception_cls=exception_cls, exception_prefix=exception_prefix)
    # Else, this hint is a class.

    # If this class is issubclassable, silently reduce to a noop.
    #
    # Note that this merely constitutes an optimization -- albeit a
    # non-negligible optimization. The is_type_issubclassable() tester is
    # memoized against inefficiencies, including:
    # * An inefficient implementation leveraging the EAFP (Easier to Ask for
    #   Permission than Foregiveness) principle.
    # * Worst-case behaviour in which the metaclass of this class defines an
    #   inefficient __subclasscheck__() method outside our control.
    if is_type_issubclassable(cls, is_forwardref_valid):
        return
    # Else, this class is *NOT* issubclassable. In this case, raise a
    # human-readable exception embedding the original (typically unreadable)
    # "TypeError" exception implicitly raised by the metaclass of this class.

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Synchronize with the is_type_issubclassable() tester.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # Attempt to pass this class as the second parameter to issubclass().
    try:
        issubclass(type, cls)  # type: ignore[arg-type]
    # If doing so raised *ANY* exception, this class is *NOT* issubclassable. In
    # this case, raise a human-readable exception.
    #
    # See the die_unless_type_isinstanceable() docstring for details.
    except Exception as exception:
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not exception class.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # If this exception ambiguously fails to indicate non-issubclassability,
        # silently reduce to a noop.
        if _is_exception_ambiguous(exception):
            return
        # Else, this exception unambiguously indicates non-issubclassability.
        #
        # If this exception already human-readably describes this
        # non-issubclassability, re-raise this exception as is.
        elif _is_exception_sufficient(exception):
            raise
        # Else, this exception fails to human-readably describe this
        # non-issubclassability.

        # Exception message to be raised.
        exception_message = (
            f'{exception_prefix}{repr(cls)} uncheckable at runtime '
            f'(i.e., not passable as second parameter to issubclass(), '
            f'due to raising "{exception.__class__.__name__}: {exception}" '
            f'from metaclass '
            f'{cls.__class__.__name__}.__subclasscheck__() method).'
        )

        # Raise this exception chained onto this lower-level exception.
        raise exception_cls(exception_message) from exception

# ....................{ TESTERS ~ isinstanceable           }....................
#FIXME: Define is_object_isinstanceable() similar to as done below, please.

#FIXME: Unit test up the "is_forwardref_valid" parameter, please.
@callable_cached
def is_type_isinstanceable(
    # Mandatory parameters.
    cls: object,

    # Optional parameters.
    is_forwardref_valid: bool = True,
) -> TypeIs[type]:
    '''
    :data:`True` only if the passed object is an **isinstanceable type** (i.e.,
    class whose metaclass does *not* define an ``__instancecheck__()`` dunder
    method that raises a :exc:`TypeError` exception).

    This tester is memoized for efficiency.

    Caveats
    -------
    **This tester may return false positives in unlikely edge cases.**
    Internally, this tester tests whether this class is isinstanceable by
    detecting whether passing the :data:`None` singleton and this class to the
    :func:`isinstance` builtin raises a :exc:`TypeError` exception. If that call
    raises *no* exception, this class is probably but *not* necessarily
    isinstanceable. Since the metaclass of this class could define an
    ``__instancecheck__()`` dunder method to conditionally raise exceptions
    *except* when passed the :data:`None` singleton, there exists *no* perfect
    means of deciding whether an arbitrary class is fully isinstanceable in the
    general sense. Since most classes that are *not* isinstanceable are
    unconditionally isinstanceable (i.e., the metaclasses of those classes
    define an ``__instancecheck__()`` dunder method to unconditionally raise
    exceptions), this distinction is generally meaningless in the real world.
    This test thus generally suffices.

    Parameters
    ----------
    cls : object
        Object to be tested.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to be a
        **forward reference proxy** (i.e., :mod:`beartype`-specific private type
        proxying an external type that may currently be undefined). Defaults to
        :data:`True`. If this boolean is:

        * :data:`True`, this object is valid only when this object is either an
          isinstanceable classes *or* a forward reference proxy.
        * :data:`False`, this object is valid only when this object is an
          isinstanceable class. Note that forward reference proxies are
          isinstanceable classes *if and only if* the external classes they
          refer to have already been defined.

    Returns
    -------
    bool
        :data:`True` only if this object is an isinstanceable class.

    See Also
    --------
    :func:`.die_unless_type_isinstanceable`
        Further details.
    '''
    assert isinstance(is_forwardref_valid, bool), (
        f'{repr(is_forwardref_valid)} not bool.')

    # Avoid circular import dependencies.
    from beartype._check.forward.reference.fwdreftest import (
        is_beartype_forwardref)
    # print('Start!')

    # If this object is *NOT* a class, immediately return false.
    if not isinstance(cls, type):
        # print(f'{repr(cls)} not type!')
        return False
    # Else, this object is a class.
    #
    # If the caller allows this class to be a forward reference proxy type
    # regardless of whether the external type this proxy refers to has been
    # defined yet and this class is such a type, immediately return true.
    #
    # Note that this test is efficient and thus tested *BEFORE*
    # isinstanceability, which is less efficient.
    elif is_forwardref_valid and is_beartype_forwardref(cls):
        # print(f'{repr(cls)} is forward reference proxy!')
        return True
    # Else, either the caller prefers to disregard this distinction *OR* this
    # class is not a forward reference proxy type.
    # print('Going!')

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Synchronize with die_unless_type_isinstanceable().
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # Attempt to pass this class as the second parameter to the isinstance()
    # builtin to decide whether or not this class is safely usable as a
    # standard class or not.
    #
    # Note that this leverages an EAFP (i.e., "It is easier to ask forgiveness
    # than permission") approach and thus imposes a minor performance penalty,
    # but that there exists *NO* faster alternative applicable to arbitrary
    # user-defined classes, whose metaclasses may define an __instancecheck__()
    # dunder method to raise exceptions and thus prohibit being passed as the
    # second parameter to the isinstance() builtin, the primary means employed
    # by @beartype wrapper functions to check arbitrary types.
    try:
        isinstance(None, cls)  # type: ignore[arg-type]
    # If the prior function call raised *ANY* exception, return true only if
    # this exception ambiguously suggests that this class could still be
    # isinstanceable.
    except Exception as exception:
        return _is_exception_ambiguous(exception)

    # Return true, as the prior isinstance() call raised *NO* exception,
    # implying this class to probably (but *NOT* necessarily) be isinstanceable.
    return True

# ....................{ TESTERS ~ issubclassable           }....................
#FIXME: Unit test us up, please.
@callable_cached
def is_object_issubclassable(
    # Mandatory parameters.
    obj: object,

    # Optional parameters.
    is_forwardref_valid: bool = True,
) -> TypeIs[IsBuiltinOrSubclassableTypes]:
    '''
    :data:`True` only if the passed object is **issubclassable** (i.e., valid as
    the second parameter to the :func:`issubclass` builtin).

    This tester is memoized for efficiency.

    Caveats
    -------
    See also the "Caveats" sections of the
    :func:`.is_type_isinstanceable` docstring for further discussion,
    substituting:

    * ``__instancecheck__()`` for ``__subclasscheck__()``.
    * :func:`isinstance` for :func:`issubclass`.

    Parameters
    ----------
    obj : IsBuiltinOrSubclassableTypes
        Object to be tested.
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

        Defaults to :data:`True`, but probably shouldn't.

    Returns
    -------
    bool
        :data:`True` only if this object is either:

        * An issubclassable class.
        * A tuple containing only issubclassable classes.
        * A :pep:`604`-compliant new union.

    See Also
    --------
    :func:`.die_unless_type_issubclassable`
        Further details.
    '''

    # If this object is a type, defer to this lower-level type-specific tester.
    if isinstance(obj, type):
        return is_type_issubclassable(obj, is_forwardref_valid)
    # Else, this object is *NOT* a type.

    # Avoid circular import dependencies.
    from beartype._util.cls.utilclstest import is_type_or_types
    from beartype._util.hint.pep.proposal.pep484604 import is_hint_pep604

    # If this object is neither...
    if not (
        # A PEP 604-compliant new union *NOR*...
        is_hint_pep604(obj) or
        # A tuple of types...
        is_type_or_types(obj)
    # Then this object *CANNOT* be runtime-checkable. In this case, immediately
    # short-circuit by returning false.
    ):
        return False
    # Else, this object *COULD* be runtime-checkable. To decide whether this
    # object is runtime-checkable, further handling is warranted.

    #FIXME: *UGH*. DRY violation between this tester and the
    #is_type_issubclassable(). Consider refactoring out into a new private
    #_is_object_issubclassable_slow() tester, please. *sigh*

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Synchronize with die_unless_type_issubclassable().
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # Attempt to pass this object as the second parameter to the issubclass()
    # builtin to decide whether or not this object is safely usable as a
    # standard class or not.
    #
    # Note that this leverages an EAFP (i.e., "It is easier to ask forgiveness
    # than permission") approach and thus imposes a minor performance penalty,
    # but that there exists *NO* faster alternative applicable to arbitrary
    # user-defined classes, whose metaclasses may define a __subclasscheck__()
    # dunder method to raise exceptions and thus prohibit being passed as the
    # second parameter to the issubclass() builtin, the primary means employed
    # by @beartype wrapper functions to check arbitrary types.
    try:
        issubclass(type, obj)  # type: ignore[arg-type]

        # If the prior function call raised *NO* exception, this object is
        # probably but *NOT* necessarily issubclassable. Return true.
    # If the prior function call raised *ANY* exception, return true only if
    # this exception ambiguously suggests that this object could still be
    # issubclassable.
    except Exception as exception:
        return _is_exception_ambiguous(exception)

    # Look. Just do it. *sigh*
    return True


#FIXME: Unit test up the "is_forwardref_valid" parameter, please.
@callable_cached
def is_type_issubclassable(
    # Mandatory parameters.
    cls: object,

    # Optional parameters.
    is_forwardref_valid: bool = True,
) -> TypeIs[type]:
    '''
    :data:`True` only if the passed object is an **issubclassable class** (i.e.,
    class whose metaclass does *not* define a ``__subclasscheck__()`` dunder
    method that raises a :exc:`TypeError` exception).

    This tester is memoized for efficiency.

    Caveats
    -------
    See also the "Caveats" sections of the
    :func:`.is_type_isinstanceable` docstring for further discussion,
    substituting:

    * ``__instancecheck__()`` for ``__subclasscheck__()``.
    * :func:`isinstance` for :func:`issubclass`.

    Parameters
    ----------
    cls : object
        Object to be tested.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to be a
        **forward reference proxy** (i.e., :mod:`beartype`-specific private type
        proxying an external type that may currently be undefined). Defaults to
        :data:`True`. If this boolean is:

        * :data:`True`, this object is valid only when this object is either an
          isinstanceable classes *or* a forward reference proxy.
        * :data:`False`, this object is valid only when this object is an
          isinstanceable class. Note that forward reference proxies are
          isinstanceable classes *if and only if* the external classes they
          refer to have already been defined.

    Returns
    -------
    bool
        :data:`True` only if this object is an issubclassable class.

    See Also
    --------
    :func:`.die_unless_type_issubclassable`
        Further details.
    '''
    assert isinstance(is_forwardref_valid, bool), (
        f'{repr(is_forwardref_valid)} not bool.')

    # Avoid circular import dependencies.
    from beartype._check.forward.reference.fwdreftest import (
        is_beartype_forwardref)

    # If this object is *NOT* a class, immediately return false.
    if not isinstance(cls, type):
        return False
    # Else, this object is a class.
    #
    # If the caller allows this class to be a forward reference proxy type
    # regardless of whether the external type this proxy refers to has been
    # defined yet and this class is such a type, immediately return true.
    #
    # Note that this test is efficient and thus tested *BEFORE*
    # isinstanceability, which is less efficient.
    elif is_forwardref_valid and is_beartype_forwardref(cls):
        return True
    # Else, either the caller prefers to disregard this distinction *OR* this
    # class is not a forward reference proxy type.

    #FIXME: *UGH*. DRY violation between this tester and the
    #is_object_issubclassable(). Consider refactoring out into a new private
    #_is_object_issubclassable_slow() tester, please. *sigh*

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Synchronize with die_unless_type_issubclassable().
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # Attempt to pass this class as the second parameter to the issubclass()
    # builtin to decide whether or not this class is safely usable as a
    # standard class or not.
    #
    # Note that this leverages an EAFP (i.e., "It is easier to ask forgiveness
    # than permission") approach and thus imposes a minor performance penalty,
    # but that there exists *NO* faster alternative applicable to arbitrary
    # user-defined classes, whose metaclasses may define a __subclasscheck__()
    # dunder method to raise exceptions and thus prohibit being passed as the
    # second parameter to the issubclass() builtin, the primary means employed
    # by @beartype wrapper functions to check arbitrary types.
    try:
        issubclass(type, cls)  # type: ignore[arg-type]

        # If the prior function call raised *NO* exception, this class is
        # probably but *NOT* necessarily issubclassable. Return true.
    # If the prior function call raised *ANY* exception, return true only if
    # this exception ambiguously suggests that this class could still be
    # issubclassable.
    except Exception as exception:
        return _is_exception_ambiguous(exception)

    # Look. Just do it. *sigh*
    return True

# ....................{ PRIVATE ~ raisers                  }....................
def _die_if_object_uncheckable(
    obj: IsBuiltinOrSubclassableTypes,
    obj_pith: object,
    obj_raiser: Callable,
    obj_tester: Callable[[object, IsBuiltinOrSubclassableTypes], bool],
    is_forwardref_valid: bool,
    exception_cls: TypeException,
    exception_prefix: str,
) -> None:
    '''
    Raise an exception of the passed type unless the passed object is
    **runtime-checkable** (i.e., valid as the second parameter to either the
    :func:`isinstance` or :func:`issubclass` builtins) according to the passed
    object tester and raiser.

    Parameters
    ----------
    obj : object
        Object to be validated.
    obj_pith : object
        Object guaranteed to satisfy the ``obj_tester`` callable when ``obj`` is
        runtime-typecheckable (i.e., when ``obj_tester`` is called as
        ``obj_tester(obj_pith, obj)``).
    obj_raiser : Callable
        Callable raising an exception unless this object is runtime-checkable
        according to this predicate, which should be either:

        * :func:`.die_unless_type_isinstanceable`.
        * :func:`.die_unless_type_issubclassable`.
    obj_tester : Callable[[object, IsBuiltinOrSubclassableTypes], bool]
        Callable returning :data:`True` only if this object is runtime-checkable
        according to this predicate, which should be either:

        * :func:`isinstance`.
        * :func:`issubclass`.
    is_forwardref_valid : bool, optional
        :data:`True` only if this function permits this object to be a
        **forward reference proxy** (i.e., :mod:`beartype`-specific private type
        proxying an external type that may currently be undefined). Defaults to
        :data:`True`. If this boolean is:

        * :data:`True`, this object is valid only when this object is either an
          isinstanceable classes *or* a forward reference proxy.
        * :data:`False`, this object is valid only when this object is an
          isinstanceable class. Note that forward reference proxies are
          isinstanceable classes *if and only if* the external classes they
          refer to have already been defined.
    exception_cls : TypeException
        Type of exception to be raised.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message.

    Raises
    ------
    BeartypeDecorHintPep3119Exception
        If this object is *not* runtime-checkable according to the passed
        object tester and raiser.
    '''
    assert callable(obj_raiser), f'{repr(obj_raiser)} uncallable.'
    assert callable(obj_tester), f'{repr(obj_tester)} uncallable.'

    # Avoid circular import dependencies.
    from beartype._util.cls.utilclstest import die_unless_type_or_types
    from beartype._util.hint.pep.proposal.pep484604 import is_hint_pep604
    from beartype._util.hint.pep.utilpepget import get_hint_pep_args

    # If this object is *NOT* a PEP 604-compliant new union...
    if not is_hint_pep604(obj):
        # If this object is neither a class nor tuple of classes, raise an
        # exception.
        die_unless_type_or_types(
            type_or_types=obj,
            exception_cls=exception_cls,
            exception_prefix=exception_prefix,
        )
        # Else, this object is either a class or tuple of classes.
    # Else, this object is a PEP 604-compliant new union.
    #
    # In any case, this object *COULD* now be runtime-checkable. To decide
    # whether this object is runtime-checkable, further handling is warranted.

    #FIXME: *UHHHH... WAT!?* This is totally busted, guys. Since this object is
    #now a PEP 604-compliant new union, this object clearly is neither a type
    #nor a tuple of types; it's a union! So, most of the code below no longer
    #makes any sense whatsoever. Actually, maybe it's just this "if
    #isinstance(obj, type):" branch that no longer makes sense? Maybe just
    #remove that branch and quietly pretend this never happened. Note that we
    #still do require the passed "obj_raiser" parameter, however. I sigh. *sigh*

    # If this object is a class...
    if isinstance(obj, type):
        # If this class is *NOT* runtime-checkable, raise an exception.
        obj_raiser(
            cls=obj,
            is_forwardref_valid=is_forwardref_valid,
            exception_cls=exception_cls,
            exception_prefix=exception_prefix,
        )
        # Else, this class is runtime-checkable.
    # Else, this object *MUST* (by process of elimination and validation above)
    # be either a tuple of classes *OR* a PEP 604-compliant new union. In either
    # case...
    else:
        # Attempt to pass this object as the second parameter to isinstance().
        try:
            obj_tester(obj_pith, obj)  # type: ignore[arg-type]
        # If doing so raises *ANY* exception, this object is *NOT*
        # runtime-checkable. In this case, raise a human-readable exception.
        #
        # See the die_unless_type_isinstanceable() docstring for details.
        except Exception as exception:
            assert isinstance(exception_cls, type), (
                f'{repr(exception_cls)} not exception class.')
            assert isinstance(exception_prefix, str), (
                f'{repr(exception_prefix)} not string.')

            # If this exception ambiguously fails to indicate
            # non-isinstanceability, silently reduce to a noop.
            if _is_exception_ambiguous(exception):
                return
            # Else, this exception unambiguously indicates
            # non-isinstanceability.

            # Tuple of all items of this iterable object.
            obj_items: tuple = None  # type: ignore[assignment]

            # Human-readable label describing this object in this exception
            # message.
            obj_label: str = None  # type: ignore[assignment]

            # Human-readable label describing the first non-runtime-checkable
            # item of this object in this exception message.
            obj_item_label: str = None  # type: ignore[assignment]

            # If this object is a tuple, define these locals accordingly.
            if isinstance(obj, tuple):
                obj_items = obj
                obj_label = 'tuple union'
                obj_item_label = 'tuple union item'
            # Else, this object is a new union. Define these locals accordingly.
            else:
                obj_items = get_hint_pep_args(obj)
                obj_label = 'PEP 604 new union'
                obj_item_label = 'new union child type'

            # Exception message to be raised.
            exception_message = (
                f'{exception_prefix} {obj_label} {repr(obj)} '
                f'uncheckable at runtime'
            )

            # For the 0-based index of each tuple class and that class...
            for cls_index, cls in enumerate(obj_items):
                # If this class is *NOT* runtime-checkable, raise an exception.
                obj_raiser(
                    cls=cls,
                    exception_cls=exception_cls,
                    exception_prefix=(
                        f'{exception_message}, as '
                        f'{obj_item_label} {cls_index} '
                    ),
                )
                # Else, this class is runtime-checkable. Continue to the next.

            # Raise this exception chained onto this lower-level exception.
            # Although this should *NEVER* happen (as we should have already
            # raised an exception above), we nonetheless do so for safety.
            raise exception_cls(f'{exception_message}.') from exception

# ....................{ PRIVATE ~ testers                  }....................
#FIXME: Unit test us up, please.
def _is_exception_ambiguous(exception: Exception) -> bool:
    '''
    :data:`True` only if the passed exception is **ambiguous** (i.e., an
    instance of the standard :exc:`AttributeError` or :exc:`NameError` types).

    Equivalently, this tester returns :data:`True` only if it cannot be decided
    whether this exception unambiguously signifies the failure of an associated
    class to be isinstanceable or issubclassable when the metaclass of this
    class defines the ``__instancecheck__()`` or ``__subclasscheck__()`` dunder
    method raising this exception. Why? Because this metaclass may *not*
    necessarily be fully initialized at the early time that this tester is
    called (typically, at :func:`beartype.beartype` decoration time). When this
    is the case, eagerly passing this class to the :func:`isinstance` or
    :func:`issubclass` builtins is likely to raise an :exc:`AttributeError`
    after referencing an undefined external attribute: e.g.,

    .. code-block:: python

       from beartype import beartype

       class MetaFoo(type):
           def __instancecheck__(cls, other):
               return g()

       class Foo(metaclass=MetaFoo):
           pass

       # @beartype transitively calls this function to validate that "Foo" is
       # isinstanceable. However, since g() has yet to be defined at this time,
       # doing so raises an "AttributeError" exception despite this logic
       # otherwise being sound.
       @beartype
       def f(x: Foo):
           pass

       def g():
           return True

    Parameters
    ----------
    exception : Exception
        Exception previously raised by a recent call to either the
        ``__instancecheck__()`` or ``__subclasscheck__()`` dunder method defined
        by the metaclass of the class passed as the second parameter to the
        :func:`isinstance` or :func:`issubclass` builtins.

    Returns
    -------
    bool
        :data:`True` only if this exception is ambiguous.
    '''

    # Faster than one-liner speed!
    return isinstance(exception, TYPES_EXCEPTION_NAMESPACE)


def _is_exception_sufficient(exception: Exception) -> bool:
    '''
    :data:`True` only if the passed exception is **sufficient** (i.e., an
    instance of the :mod:`beartype`-specific
    :exc:`._BeartypeHintForwardRefExceptionMixin` type).

    Equivalently, this tester returns :data:`True` only if this exception's
    message already suffices to human-readably describe the failure of an
    associated class to be isinstanceable or issubclassable when the metaclass
    of this class defines the ``__instancecheck__()`` or ``__subclasscheck__()``
    dunder method raising this exception. Currently, this includes *all*
    exceptions pertaining to :mod:`beartype`-specific forward references. Why?
    Because these exceptions already convey the issue. Wrapping these exceptions
    in additional exceptions only obfuscates the underlying issue: e.g.,

    .. code-block:: python

       # This original exception...
       BeartypeCallHintForwardRefException: Forward reference "OfPearl"
       unimportable from module
       "beartype_test.a00_unit.data.pep.pep563.data_pep563_resolve".

       # ...is considerably more useful to end users than this insane wrapper.
       beartype.roar.BeartypeDecorHintNonpepException: Die_if_unbearable()
       <forwardref OfPearl(__name_beartype__='OfPearl',
       __scope_name_beartype__='beartype_test.a00_unit.data.pep.pep563.data_pep563_resolve')>
       uncheckable at runtime (i.e., not passable as second parameter to
       isinstance(), due to raising "BeartypeCallHintForwardRefException:
       Forward reference "OfPearl" unimportable from module
       "beartype_test.a00_unit.data.pep.pep563.data_pep563_resolve"." from
       metaclass BeartypeForwardRefMeta.__instancecheck__() method).

    Parameters
    ----------
    exception : Exception
        Exception previously raised by a recent call to either the
        ``__instancecheck__()`` or ``__subclasscheck__()`` dunder method defined
        by the metaclass of the class passed as the second parameter to the
        :func:`isinstance` or :func:`issubclass` builtins.

    Returns
    -------
    bool
        :data:`True` only if this exception is sufficient.
    '''

    # Fear the one-liner reaper!
    return isinstance(exception, _BeartypeHintForwardRefExceptionMixin)
