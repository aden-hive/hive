#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **callable testers** (i.e., utility functions dynamically
validating and inspecting various properties of passed callables).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilCallableException
from beartype.typing import (
    Any,
    Optional,
)
from beartype._cave._cavefast import (
    CallableCodeObjectType,
    MethodBoundInstanceOrClassType,
    MethodDecoratorClassOrStaticTypes,
    MethodDecoratorClassType,
    MethodDecoratorPropertyType,
    MethodDecoratorStaticType,
)
from beartype._data.typing.datatypingport import TypeIs
from beartype._data.typing.datatyping import (
    Codeobjable,
    TypeException,
)
# from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.func.arg.utilfuncarglen import (
    get_func_args_nonvariadic_len)
from beartype._util.func.arg.utilfuncargtest import (
    is_func_arg_variadic_positional,
    is_func_arg_variadic_keyword,
)
from beartype._util.func.utilfunccodeobj import get_func_codeobj_or_none
from collections.abc import Callable
from inspect import (
    CO_ASYNC_GENERATOR,
    CO_COROUTINE,
    CO_GENERATOR,
)

# ....................{ CONSTANTS                          }....................
#FIXME: Shift into the "beartype._data.func.datafunc" submodule, please.
FUNC_NAME_LAMBDA = '<lambda>'
'''
Default name of all **pure-Python lambda functions** (i.e., function declared
as a ``lambda`` expression embedded in a larger statement rather than as a
full-blown ``def`` statement).

Python initializes the names of *all* lambda functions to this lambda-specific
placeholder string on lambda definition.

Caveats
-------
**Usage of this placeholder to differentiate lambda from non-lambda callables
invites false positives in unlikely edge cases.** Technically, malicious third
parties may externally change the name of any lambda function *after* defining
that function. Pragmatically, no one sane should ever do such a horrible thing.
While predictably absurd, this is also the only efficient (and thus sane) means
of differentiating lambda from non-lambda callables. Alternatives require
AST-based parsing, which comes with its own substantial caveats, concerns,
edge cases, and false positives. If you must pick your poison, pick this one.
'''

# ....................{ RAISERS                            }....................
def die_unless_func_python(
    # Mandatory parameters.
    func: Codeobjable,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception if the passed callable is **C-based** (i.e., implemented
    in C as either a builtin bundled with the active Python interpreter *or*
    third-party C extension function).

    Equivalently, this validator raises an exception unless the passed function
    is **pure-Python** (i.e., implemented in Python as either a function or
    method).

    Parameters
    ----------
    func : Codeobjable
        Callable to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised. Defaults to
        :class:`._BeartypeUtilCallableException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    exception_cls
         If the passed callable is C-based.

    See Also
    --------
    :func:`.is_func_codeobjable`
        Further details.
    '''

    # If that callable is *NOT* pure-Python, raise an exception.
    if not is_func_codeobjable(func):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not class.')
        assert issubclass(exception_cls, Exception), (
            f'{repr(exception_cls)} not exception subclass.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # If that callable is uncallable, raise an appropriate exception.
        if not callable(func):
            raise exception_cls(f'{exception_prefix}{repr(func)} not callable.')
        # Else, that callable is callable.

        # Raise a human-readable exception.
        raise exception_cls(
            f'{exception_prefix}{repr(func)} not pure-Python function.')
    # Else, that callable is pure-Python.

# ....................{ RAISERS ~ descriptors              }....................
#FIXME: Unit test us up, please.
def die_unless_func_boundmethod(
    # Mandatory parameters.
    func: Any,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is a **C-based bound instance
    method descriptor** callable implicitly instantiated and assigned on the
    instantiation of an object whose class declares an instance function (whose
    first parameter is typically named ``self``) as an instance variable of that
    object such that that callable unconditionally passes that object as the
    value of that first parameter on all calls to that callable).

    Parameters
    ----------
    func : Any
        Object to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised. Defaults to
        :class:`._BeartypeUtilCallableException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    exception_cls
         If the passed object is *not* a bound method descriptor.

    See Also
    --------
    :func:`.is_func_boundmethod`
        Further details.
    '''

    # If this object is *NOT* a bound method descriptor, raise an exception.
    if not is_func_boundmethod(func):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not class.')
        assert issubclass(exception_cls, Exception), (
            f'{repr(exception_cls)} not exception subclass.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Raise a human-readable exception.
        raise exception_cls(
            f'{exception_prefix}{repr(func)} not '
            f'C-based bound instance method descriptor.'
        )
    # Else, this object is a bound method descriptor.


#FIXME: Unit test us up, please.
def die_unless_func_class_or_static_method(
    # Mandatory parameters.
    func: Any,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is a **C-based unbound class or
    static method descriptor** (i.e., method decorated by either the builtin
    :class:`classmethod` or :class:`staticmethod` decorators, yielding a
    non-callable instance of that decorator class implemented in low-level C and
    accessible via the low-level :attr:`object.__dict__` dictionary rather than
    as class or instance attributes).

    Parameters
    ----------
    func : Any
        Object to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised. Defaults to
        :exc:`._BeartypeUtilCallableException`.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    exception_cls
         If the passed object is *not* a class or static method descriptor.

    See Also
    --------
    :func:`.is_func_classmethod`
        Further details.
    '''

    # If this object is neither a class *NOR* static method descriptor, raise an
    # exception.
    if not isinstance(func, MethodDecoratorClassOrStaticTypes):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not class.')
        assert issubclass(exception_cls, Exception), (
            f'{repr(exception_cls)} not exception subclass.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Raise a human-readable exception.
        raise exception_cls(
            f'{exception_prefix}{repr(func)} not '
            f'C-based unbound @classmethod or @staticmethod descriptor.'
        )
    # Else, this object is a class or static method descriptor.


#FIXME: Currently unused, but extensively tested. *shrug*
def die_unless_func_classmethod(
    # Mandatory parameters.
    func: Any,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is a **C-based unbound class
    method descriptor** (i.e., method decorated by the builtin
    :class:`classmethod` decorator, yielding a non-callable instance of that
    :class:`classmethod` decorator class implemented in low-level C and
    accessible via the low-level :attr:`object.__dict__` dictionary rather than
    as class or instance attributes).

    Parameters
    ----------
    func : Any
        Object to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised. Defaults to
        :class:`._BeartypeUtilCallableException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    exception_cls
         If the passed object is *not* a class method descriptor.

    See Also
    --------
    :func:`.is_func_classmethod`
        Further details.
    '''

    # If this object is *NOT* a class method descriptor, raise an exception.
    if not is_func_classmethod(func):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not class.')
        assert issubclass(exception_cls, Exception), (
            f'{repr(exception_cls)} not exception subclass.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Raise a human-readable exception.
        raise exception_cls(
            f'{exception_prefix}{repr(func)} not '
            f'C-based unbound class method descriptor.'
        )
    # Else, this object is a class method descriptor.


def die_unless_func_property(
    # Mandatory parameters.
    func: Any,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is a **C-based unbound property
    method descriptor** (i.e., method decorated by the builtin :class:`property`
    decorator, yielding a non-callable instance of that :class:`property`
    decorator class implemented in low-level C and accessible as a class rather
    than instance attribute).

    Parameters
    ----------
    func : Any
        Object to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised. Defaults to
        :property:`_BeartypeUtilCallableException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    exception_cls
         If the passed object is *not* a property method descriptor.

    See Also
    --------
    :func:`.is_func_property`
        Further details.
    '''

    # If this object is *NOT* a property method descriptor, raise an exception.
    if not is_func_property(func):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not class.')
        assert issubclass(exception_cls, Exception), (
            f'{repr(exception_cls)} not exception subclass.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Raise a human-readable exception.
        raise exception_cls(
            f'{exception_prefix}{repr(func)} not '
            f'C-based unbound property method descriptor.'
        )
    # Else, this object is a property method descriptor.


#FIXME: Currently unused, but extensively tested. *shrug*
def die_unless_func_staticmethod(
    # Mandatory parameters.
    func: Any,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is a **C-based unbound static
    method descriptor** (i.e., method decorated by the builtin
    :class:`staticmethod` decorator, yielding a non-callable instance of that
    :class:`staticmethod` decorator class implemented in low-level C and
    accessible via the low-level :attr:`object.__dict__` dictionary rather than
    as class or instance attributes).

    Parameters
    ----------
    func : Any
        Object to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised. Defaults to
        :static:`_BeartypeUtilCallableException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Raises
    ------
    exception_cls
         If the passed object is *not* a static method descriptor.

    See Also
    --------
    :func:`.is_func_staticmethod`
        Further details.
    '''

    # If this object is *NOT* a static method descriptor, raise an exception.
    if not is_func_staticmethod(func):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not class.')
        assert issubclass(exception_cls, Exception), (
            f'{repr(exception_cls)} not exception subclass.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Raise a human-readable exception.
        raise exception_cls(
            f'{exception_prefix}{repr(func)} not '
            f'C-based unbound static method descriptor.'
        )
    # Else, this object is a static method descriptor.

# ....................{ TESTERS                            }....................
def is_func_codeobjable(func: object) -> TypeIs[Callable]:
    '''
    :data:`True` only if the passed object is **code-objectable** (i.e., either
    a pure-Python callable, low-level code object underlying a pure-Python
    callable, or related object encapsulating such a low-level code object).

    This tester effectively tests whether this object is a **pure-Python
    callable** (i.e., implemented in Python as either a function or method
    rather than in C as either a builtin bundled with the active Python
    interpreter *or* third-party C extension function).

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is code-objectable.
    '''

    # Return true only if a pure-Python code object underlies this object.
    # C-based callables are associated with *NO* code objects.
    return get_func_codeobj_or_none(func) is not None


def is_func_lambda(func: Any) -> TypeIs[Callable]:
    '''
    :data:`True` only if the passed object is a **pure-Python lambda function**
    (i.e., function declared as a ``lambda`` expression embedded in a larger
    statement rather than as a full-blown ``def`` statement).

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a pure-Python lambda function.
    '''

    # Return true only if this both...
    return (
        # This callable is pure-Python *AND*...
        is_func_codeobjable(func) and
        # This callable's name is the lambda-specific placeholder name
        # initially given by Python to *ALL* lambda functions. Technically,
        # this name may be externally changed by malicious third parties after
        # the declaration of this lambda. Pragmatically, no one sane would ever
        # do such a horrible thing. Would they!?!?
        #
        # While predictably absurd, this is also the only efficient (and thus
        # sane) means of differentiating lambda from non-lambda callables.
        # Alternatives require AST-based parsing, which comes with its own
        # substantial caveats, concerns, and edge cases.
        func.__name__ == FUNC_NAME_LAMBDA
    )

# ....................{ TESTERS ~ descriptor               }....................
#FIXME: Unit test us up, please.
def is_func_boundmethod(func: Any) -> TypeIs[MethodBoundInstanceOrClassType]:
    '''
    :data:`True` only if the passed object is a **C-based bound instance method
    descriptor** (i.e., callable implicitly instantiated and assigned on the
    instantiation of an object whose class declares an instance function (whose
    first parameter is typically named ``self``) as an instance variable of that
    object such that that callable unconditionally passes that object as the
    value of that first parameter on all calls to that callable).

    Caveats
    -------
    Instance method objects are *only* directly accessible as instance
    attributes. When accessed as either class attributes *or* via the low-level
    :attr:`object.__dict__` dictionary, instance methods are only functions
    (i.e., instances of the standard :class:`beartype.cave.FunctionType` type).

    Instance method objects are callable. Indeed, the callability of instance
    method objects is the entire point of instance method objects.

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a C-based bound instance method
        descriptor.
    '''

    # Only the penitent one-liner shall pass.
    return isinstance(func, MethodBoundInstanceOrClassType)

# ....................{ TESTERS ~ descriptor : uncallable  }....................
#FIXME: Unit test us up, please.
#FIXME: Currently unused but preserved for posterity. We'll want this someday!
# def is_func_class_property_or_static_method(func: Any)  -> TypeIs[
#     MethodDescriptorBuiltin]:
#     '''
#     :data:`True` only if the passed object is an **unbound class, property, or
#     static method descriptor** (i.e., C-based decorator type builtin to Python
#     whose instance is typically uncallable but encapsulates a callable
#     pure-Python method).
#
#     These method objects are *not* callable, as their implementations fail to
#     define the ``__call__()`` dunder method.
#
#     Parameters
#     ----------
#     func : object
#         Object to be inspected.
#
#     Returns
#     -------
#     bool
#         :data:`True` only if this object is an unbound class, property, or
#         static method descriptor.
#     '''
#
#     # Line up for the one-liner you never knew you needed in your life.
#     return isinstance(func, MethodDecoratorBuiltinTypes)


def is_func_classmethod(func: Any) -> TypeIs[MethodDecoratorClassType]:
    '''
    :data:`True` only if the passed object is an **unbound class method
    descriptor** (i.e., method decorated by the builtin :class:`classmethod`
    decorator, yielding a non-callable instance of that :class:`classmethod`
    decorator class implemented in low-level C and accessible via the low-level
    :attr:`object.__dict__` dictionary rather than as class or instance
    attributes).

    Caveats
    -------
    Class method objects are *only* directly accessible via the low-level
    :attr:`object.__dict__` dictionary. When accessed as class or instance
    attributes, class methods are indistinguishable from **bound method
    descriptors** (i.e., :class:`MethodBoundInstanceOrClassType` instances)
    bound to that class.

    Class method objects are *not* callable, as their implementations fail to
    define the ``__call__()`` dunder method.

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is an unbound class method descriptor.
    '''

    # Now you too have seen the pure light of the one-liner.
    return isinstance(func, MethodDecoratorClassType)


def is_func_property(func: Any) -> TypeIs[MethodDecoratorPropertyType]:
    '''
    :data:`True` only if the passed object is a **C-based unbound property
    method descriptor** (i.e., method decorated by the builtin :class:`property`
    decorator, yielding a non-callable instance of that :class:`property`
    decorator class implemented in low-level C and accessible as a class rather
    than instance attribute).

    Caveats
    -------
    Property objects are directly accessible both as class attributes *and* via
    the low-level :attr:`object.__dict__` dictionary. Property objects are *not*
    accessible as instance attributes, for hopefully obvious reasons.

    Property objects are *not* callable, as their implementations fail to define
    the ``__call__`` dunder method.

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a pure-Python property.
    '''

    # We rejoice in the shared delight of one-liners.
    return isinstance(func, MethodDecoratorPropertyType)


def is_func_staticmethod(func: Any) -> TypeIs[MethodDecoratorStaticType]:
    '''
    :data:`True` only if the passed object is a **C-based unbound static method
    descriptor** (i.e., method decorated by the builtin :class:`staticmethod`
    decorator, yielding a non-callable instance of that :class:`staticmethod`
    decorator class implemented in low-level C and accessible via the low-level
    :attr:`object.__dict__` dictionary rather than as class or instance
    attributes).

    Caveats
    -------
    Static method objects are *only* directly accessible via the low-level
    :attr:`object.__dict__` dictionary. When accessed as class or instance
    attributes, static methods reduce to instances of the standard
    :class:`FunctionType` type.

    Static method objects are *not* callable, as their implementations fail to
    define the ``__call__`` dunder method.

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a pure-Python static method.
    '''

    # Does the one-liner have Buddhahood? Mu.
    return isinstance(func, MethodDecoratorStaticType)

# ....................{ TESTERS ~ async                    }....................
def is_func_async(func: object) -> TypeIs[Callable]:
    '''
    :data:`True` only if the passed object is an **asynchronous callable
    factory** (i.e., awaitable factory callable implicitly creating and
    returning an awaitable object (i.e., satisfying the
    :class:`collections.abc.Awaitable` protocol) by being declared via the
    ``async def`` syntax and thus callable *only* when preceded by comparable
    ``await`` syntax).

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is an asynchronous callable.

    See Also
    --------
    :func:`inspect.iscoroutinefunction`
    :func:`inspect.isasyncgenfunction`
        Stdlib functions strongly inspiring this implementation.
    '''

    # Code object underlying this pure-Python callable if any *OR* "None".
    #
    # Note this tester intentionally:
    # * Inlines the tests performed by the is_func_coro() and
    #   is_func_async_generator() testers for efficiency.
    # * Calls the get_func_codeobj_or_none() with "is_unwrap" disabled
    #   rather than enabled. Why? Because the asynchronicity of this possibly
    #   higher-level wrapper has *NO* relation to that of the possibly
    #   lower-level wrappee wrapped by this wrapper. Notably, it is both
    #   feasible and commonplace for third-party decorators to enable:
    #   * Synchronous callables to be called asynchronously by wrapping
    #     synchronous callables with asynchronous closures.
    #   * Asynchronous callables to be called synchronously by wrapping
    #     asynchronous callables with synchronous closures. Indeed, our
    #     top-level "conftest.py" pytest plugin does exactly this -- enabling
    #     asynchronous tests to be safely called by pytest's currently
    #     synchronous framework.
    func_codeobj = get_func_codeobj_or_none(func)

    # If this object is *NOT* a pure-Python callable, immediately return false.
    if func_codeobj is None:
        return False
    # Else, this object is a pure-Python callable.

    # Bit field of OR-ed binary flags describing this callable.
    func_codeobj_flags = func_codeobj.co_flags

    # Return true only if these flags imply this callable to be either...
    return (
        # An asynchronous coroutine *OR*...
        func_codeobj_flags & CO_COROUTINE != 0 or
        # An asynchronous generator.
        func_codeobj_flags & CO_ASYNC_GENERATOR != 0
    )


def is_func_coro(func: object) -> TypeIs[Callable]:
    '''
    :data:`True` only if the passed object is an **asynchronous coroutine
    factory** (i.e., awaitable callable containing *no* ``yield`` expression
    implicitly creating and returning an awaitable object (i.e., satisfying the
    :class:`collections.abc.Awaitable` protocol) by being declared via the
    ``async def`` syntax and thus callable *only* when preceded by comparable
    ``await`` syntax).

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is an asynchronous coroutine factory.

    See Also
    --------
    :func:`inspect.iscoroutinefunction`
        Stdlib function strongly inspiring this implementation.
    '''

    # Code object underlying this pure-Python callable if any *OR* "None".
    func_codeobj = get_func_codeobj_or_none(func)

    # Return true only if...
    return (
        # This object is a pure-Python callable *AND*...
        func_codeobj is not None and
        # This callable's code object implies this callable to be an
        # asynchronous coroutine.
        func_codeobj.co_flags & CO_COROUTINE != 0
    )


def is_func_async_generator(func: object) -> TypeIs[Callable]:
    '''
    :data:`True` only if the passed object is an **asynchronous generator
    factory** (i.e., awaitable callable containing one or more ``yield``
    expressions implicitly creating and returning an awaitable object (i.e.,
    satisfying the :class:`collections.abc.Awaitable` protocol) by being
    declared via the ``async def`` syntax and thus callable *only* when preceded
    by comparable ``await`` syntax).

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is an asynchronous generator.

    See Also
    --------
    :func:`inspect.isasyncgenfunction`
        Stdlib function strongly inspiring this implementation.
    '''

    # Code object underlying this pure-Python callable if any *OR* "None".
    func_codeobj = get_func_codeobj_or_none(func)

    # Return true only if...
    return (
        # This object is a pure-Python callable *AND*...
        func_codeobj is not None and
        # This callable's code object implies this callable to be an
        # asynchronous generator.
        func_codeobj.co_flags & CO_ASYNC_GENERATOR != 0
    )

# ....................{ TESTERS ~ sync                     }....................
def is_func_sync_generator(func: object) -> TypeIs[Callable]:
    '''
    :data:`True` only if the passed object is an **synchronous generator
    factory** (i.e., iterable callable containing one or more ``yield``
    expressions implicitly creating and returning a generator object (i.e.,
    satisfying the :class:`collections.abc.Generator` protocol) by being
    declared via the ``def`` rather than ``async def`` syntax).

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a synchronous generator.

    See Also
    --------
    :func:`inspect.isgeneratorfunction`
        Stdlib function strongly inspiring this implementation.
    '''

    # If this object is neither...
    #
    # This logic enables this tester to differentiate synchronous generator
    # *FACTORIES* from synchronous generator *OBJECTS* (i.e., the objects those
    # factories implicitly create and return). Whereas neither asynchronous
    # coroutine objects *NOR* asynchronous generator objects have code objects
    # whose "CO_COROUTINE" and "CO_ASYNC_GENERATOR" flags are enabled,
    # synchronous generator objects do have code objects whose "CO_GENERATOR"
    # flag is enabled. Ergo, synchronous generator factories create and return
    # synchronous generator objects that are themselves technically valid
    # synchronous generator factories... which, frankly, is absurd. Explicitly
    # prohibit this ambiguity by differentiating the two here.
    if not (
        # A callable *NOR*...
        callable(func) or
        # A code object (which is uncallable by definition).
        isinstance(func, CallableCodeObjectType)
    ):
        # Then immediately return false to prevent synchronous generator objects
        # from being ambiguously conflated with synchronous generator factories.
        return False
    # Else, this object is either callable *OR* a code object. In either case,
    # this object is *NOT* a synchronous generator object.

    # Code object underlying this pure-Python callable if any *OR* "None".
    func_codeobj = get_func_codeobj_or_none(func)

    # Return true only if...
    return (
        # This object is a pure-Python callable *AND*...
        func_codeobj is not None and
        # This callable's code object implies this callable to be a
        # synchronous generator.
        func_codeobj.co_flags & CO_GENERATOR != 0
    )

# ....................{ TESTERS : nested                   }....................
def is_func_nested(func: Callable) -> bool:
    '''
    :data:`True` only if the passed callable is **nested** (i.e., a pure-Python
    callable declared in the body of another pure-Python callable or class).

    Equivalently, this tester returns :data:`True` only if that callable is
    either:

    * A closure, which by definition is nested inside another callable.
    * A method, which by definition is nested inside its class.
    * A **nested non-closure function** (i.e., a closure-like function that does
      *not* reference local attributes of the parent callable enclosing that
      function and is thus technically *not* a closure): e.g.,

      .. code-block:: python

         def muh_parent_callable():           # <-- parent callable
             def muh_nested_callable(): pass  # <-- nested non-closure function
             return muh_nested_callable

    Parameters
    ----------
    func : Callable
        Callable to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this callable is nested.
    '''

    # Return true only if either...
    return (
        # That callable is a closure (in which case that closure is necessarily
        # nested inside another callable) *OR*...
        #
        # Note that this tester intentionally tests for whether that callable is
        # a closure first, as doing so efficiently reduces to a constant-time
        # attribute test -- whereas the following test for non-closure nested
        # callables inefficiently requires a linear-time string search.
        is_func_closure(func) or
        # The fully-qualified name of that callable contains one or more "."
        # delimiters, each signifying a nested lexical scope. Since *ALL*
        # callables (i.e., both pure-Python and C-based) define a non-empty
        # "__qualname__" dunder variable containing at least their unqualified
        # names, this simplistic test is guaranteed to be safe.
        #
        # Note this tester intentionally tests for the general-purpose existence
        # of a "." delimiter rather than the special-cased existence of a
        # ".<locals>." placeholder substring. Why? Because there are two types
        # of nested callables:
        # * Non-methods, which are lexically nested in a parent callable whose
        #   scope encapsulates all previously declared local variables. For
        #   unknown reasons, the unqualified names of nested non-method
        #   callables are *ALWAYS* prefixed by ".<locals>." in their
        #   "__qualname__" variables:
        #       >>> from collections.abc import Callable
        #       >>> def muh_parent_callable() -> Callable:
        #       ...     def muh_nested_callable() -> None: pass
        #       ...     return muh_nested_callable
        #       >>> muh_nested_callable = muh_parent_callable()
        #       >>> muh_parent_callable.__qualname__
        #       'muh_parent_callable'
        #       >>> muh_nested_callable.__qualname__
        #       'muh_parent_callable.<locals>.muh_nested_callable'
        # * Methods, which are lexically nested in the scope encapsulating all
        #   previously declared class variables (i.e., variables declared in
        #   class scope and thus accessible as method annotations). For unknown
        #   reasons, the unqualified names of methods are *NEVER* prefixed by
        #   ".<locals>." in their "__qualname__" variables: e.g.,
        #       >>> from typing import ClassVar
        #       >>> class MuhClass(object):
        #       ...    # Class variable declared in class scope.
        #       ...    muh_class_var: ClassVar[type] = int
        #       ...    # Instance method annotated by this class variable.
        #       ...    def muh_method(self) -> muh_class_var: return 42
        #       >>> MuhClass.muh_method.__qualname__
        #       'MuhClass.muh_method'
        '.' in func.__qualname__
    )

# ....................{ TESTERS ~ nested : closure         }....................
def is_func_closure(func: Any) -> TypeIs[Callable]:
    '''
    :data:`True` only if the passed callable is a **closure** (i.e., nested
    callable accessing one or more variables declared by the parent callable
    also declaring that callable).

    Note that all closures are necessarily nested callables but that the
    converse is *not* necessarily the case. In particular, a nested callable
    accessing *no* variables declared by the parent callable also declaring that
    callable is *not* a closure; it's simply a nested callable.

    Parameters
    ----------
    func : Callable
        Callable to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this callable is a closure.
    '''

    # Return true only if that callable defines the closure-specific
    # "__closure__" dunder variable whose value is either:
    # * If that callable is a closure, a tuple of zero or more cell variables.
    # * If that callable is a pure-Python non-closure, "None".
    # * If that callable is C-based, undefined.
    return getattr(func, '__closure__', None) is not None

# ....................{ TESTERS ~ wrapper                  }....................
def is_func_wrapper(func: Any) -> TypeIs[Callable]:
    '''
    :data:`True` only if the passed object is a **callable wrapper** (i.e.,
    callable decorated by the standard :func:`functools.wraps` decorator for
    wrapping a pure-Python callable with additional functionality defined by a
    higher-level decorator).

    Note that this tester returns :data:`True` for both pure-Python and C-based
    callable wrappers. As an example of the latter, the standard
    :func:`functools.lru_cache` decorator creates and returns low-level C-based
    callable wrappers of the private type :class:`functools._lru_cache_wrapper`
    wrapping pure-Python callables.

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a callable wrapper.
    '''

    # Return true only if this object defines a dunder attribute uniquely
    # specific to the @functools.wraps decorator.
    #
    # Technically, *ANY* callable (including non-wrappers *NOT* created by the
    # @functools.wraps decorator) could trivially define this attribute; ergo,
    # this invites the possibility of false positives. Pragmatically, doing so
    # would violate ad-hoc standards and real-world practice across the
    # open-source ecosystem; ergo, this effectively excludes false positives.
    return hasattr(func, '__wrapped__')


def is_func_wrapper_isomorphic(
    # Mandatory parameters.
    func: Any,

    # Optional parameters.
    wrapper: Optional[Callable] = None,
) -> TypeIs[Callable]:
    '''
    :data:`True` only if the passed object is an **isomorphic wrapper** (i.e.,
    callable decorated by the standard :func:`functools.wraps` decorator for
    wrapping a pure-Python callable with additional functionality defined by a
    higher-level decorator such that that wrapper isomorphically preserves both
    the number and types of all passed parameters and returns by accepting only
    a variadic positional argument and a variadic keyword argument).

    This tester enables callers to detect when a user-defined callable has been
    decorated by an isomorphic decorator, which constitutes *most* real-world
    decorators of interest.

    This tester is currently *not* memoized for efficiency, despite performing a
    relatively non-trivial (albeit technically :math:`O(1)`) operation. Why?
    Because this tester should typically be called at most once by the parent
    :func:`beartype._util.func.utilfuncwrap.unwrap_func_all_isomorphic`
    function, which is currently:

    * The *only* other function calling this tester.
    * Itself currently unmemoized.

    Caveats
    -------
    **This tester is merely a heuristic** -- albeit a reasonably robust
    heuristic likely to succeed in almost all real-world use cases. Nonetheless,
    this tester *could* return false positives and negatives in edge cases.

    Parameters
    ----------
    func : object
        Object to be inspected.
    wrapper : Optional[Callable]
        Wrapper callable to be unwrapped in the event that the callable to be
        inspected for isomorphism differs from the callable to be unwrapped.
        Typically, these two callables are the same. Edge cases in which these
        two callables differ include:

        * When ``wrapper`` is a **pseudo-callable** (i.e., otherwise uncallable
          object whose type renders that object callable by defining the
          ``__call__()`` dunder method) *and* ``func`` is that ``__call__()``
          dunder method. If that pseudo-callable wraps a lower-level callable,
          then that pseudo-callable (rather than ``__call__()`` dunder method)
          defines the ``__wrapped__`` instance variable providing that callable.

        Defaults to :data:`None`, in which case this parameter *actually*
        defaults to ``func``.

    Returns
    -------
    bool
        :data:`True` only if this object is an isomorphic decorator wrapper.
    '''

    # If the caller failed to explicitly pass a callable to be unwrapped,
    # default the callable to be unwrapped to the passed callable.
    if wrapper is None:
        wrapper = func
    # Else, the caller explicitly passed a callable to be unwrapped. In this
    # case, preserve that callable as is.

    # If that callable is *NOT* a wrapper, immediately return false.
    if not is_func_wrapper(wrapper):
        return False
    # Else, that callable is a wrapper.

    # Number of non-variadic arguments permitted for this wrapper if isomorphic,
    # defaulting to 0.
    func_args_nonvariadic_len = 0

    # If this object is a C-based bound method descriptor...
    if is_func_boundmethod(func):
        # Avoid circular import dependencies.
        from beartype._util.func.utilfuncwrap import (
            unwrap_func_boundmethod_once)
        # print(f'Detecting bound method f{repr(func)} isomorphism...')

        # Unwrap this descriptor to the pure-Python callable encapsulated by
        # this descriptor.
        func = unwrap_func_boundmethod_once(func)

        # Permit this pure-Python callable to accept exactly one non-variadic
        # argument, typically named "self" whose value is the object to which
        # this bound method descriptor was bound at object instantiation time.
        func_args_nonvariadic_len = 1
    # Else, this object is *NOT* a C-based bound method descriptor.

    # Code object underlying that callable as is (rather than possibly unwrapped
    # to another code object entirely) if that callable is pure-Python *OR*
    # "None" otherwise (i.e., if that callable is C-based).
    func_codeobj = get_func_codeobj_or_none(func)

    # If that callable is C-based...
    if not func_codeobj:  # pragma: no cover
        print(f'Detecting C-based callable {repr(func)} isomorphism...')
        # Return true only if that C-based callable is the __call__() dunder
        # method of a pseudo-callable parent object. Although this tester
        # *CANNOT* positively decide whether that object is isomorphic or not,
        # *ALMOST* all __call__() dunder methods are C-based. Technically, this
        # *COULD* constitute a false positive in various edge cases.
        # Pragmatically, the alternatives are all worse. Blindly rejecting *ALL*
        # C-based __call__() dunder methods as non-isomorphic would effectively
        # prevent @beartype from decorating numerous pseudo-callable objects of
        # interest, including:
        # * Pseudo-callables dynamically generated by the third-party
        #   "@jax.jit" decorator: e.g.,
        #       from beartype import beartype
        #       from jax import jit
        #
        #       # The @jax.jit decorator creates and returns a C-based
        #       # pseudo-callable object defining an isomorphic __call__()
        #       # dunder method. If this tester erroneously rejected that method
        #       # as non-isomorphic, @beartype would be unable to decorate these
        #       # pseudo-callable objects! Clearly, that would be bad.
        #       @beartype
        #       @jit
        #       def muh_func(muh_arg: int) -> int:
        #           return muh_arg
        return func.__name__ == '__call__'
    # Else, that callable is pure-Python.

    # Return true only if...
    return (
        # That callable accepts no non-variadic arguments *AND*...
        (
            get_func_args_nonvariadic_len(func_codeobj) ==
            func_args_nonvariadic_len
        ) and
        # That callable accepts variadic positional and/or keyword arguments.
        (
            is_func_arg_variadic_positional(func_codeobj) or
            is_func_arg_variadic_keyword(func_codeobj)
        )
    )
