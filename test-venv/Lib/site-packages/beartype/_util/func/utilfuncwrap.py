#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **callable wrapper** (i.e., higher-level callable, typically
implemented as a decorator, wrapping a lower-level callable) utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilCallableWrapperException
from beartype.typing import (
    Optional,
    Union,
)
from beartype._cave._cavefast import MethodBoundInstanceOrClassType
from beartype._data.typing.datatyping import TypeException
from collections.abc import Callable

# ....................{ UNWRAPPERS ~ once                  }....................
#FIXME: Unit test us up, please.
def unwrap_func_once(func: Callable) -> Callable:
    '''
    Immediate **wrappee** (i.e., callable wrapped by the passed wrapper
    callable) of the passed higher-level **wrapper** (i.e., callable wrapping
    the wrappee callable to be returned) if the passed callable is a wrapper
    *or* that callable as is otherwise (i.e., if that callable is *not* a
    wrapper).

    Specifically, this getter undoes the work performed by any of the following:

    * A single use of the :func:`functools.wrap` decorator on the wrappee
      callable to be returned.
    * A single call to the :func:`functools.update_wrapper` function on the
      wrappee callable to be returned.

    Parameters
    ----------
    func : Callable
        Wrapper callable to be unwrapped.

    Returns
    -------
    Callable
        The immediate wrappee callable wrapped by the passed wrapper callable.

    Raises
    ------
    _BeartypeUtilCallableWrapperException
        If the passed callable is *not* a wrapper.
    '''

    # Immediate wrappee callable wrapped by the passed wrapper callable if any
    # *OR* "None" otherwise (i.e., if that callable is *NOT* a wrapper).
    func_wrappee = getattr(func, '__wrapped__', None)

    # If that callable is *NOT* a wrapper, raise an exception.
    if func_wrappee is None:
        raise _BeartypeUtilCallableWrapperException(
            f'Callable {repr(func)} not wrapper '
            f'(i.e., has no "__wrapped__" dunder attribute '
            f'defined by @functools.wrap or functools.update_wrapper()).'
        )
    # Else, that callable is a wrapper.

    # Return this immediate wrappee callable.
    return func_wrappee

# ....................{ UNWRAPPERS ~ once : descriptor     }....................
#FIXME: Unit test us up, please.
def unwrap_func_boundmethod_once(
    # Mandatory parameters.
    func: MethodBoundInstanceOrClassType,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCallableWrapperException,
    exception_prefix: str = '',
) -> Callable:
    '''
    Pure-Python unbound function wrapped by the passed **C-based bound instance
    method descriptor** (i.e., callable implicitly instantiated and assigned on
    the instantiation of an object whose class declares an instance function
    (whose first parameter is typically named ``self``) as an instance variable
    of that object such that that callable unconditionally passes that object as
    the value of that first parameter on all calls to that callable).

    Parameters
    ----------
    func : MethodBoundInstanceOrClassType
        Bound method descriptor to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`._BeartypeUtilCallableWrapperException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Returns
    -------
    Callable
        Pure-Python unbound function wrapped by this bound method descriptor.

    Raises
    ------
    exception_cls
         If the passed object is *not* a bound method descriptor.

    See Also
    --------
    :func:`beartype._util.func.utilfunctest.is_func_boundmethod`
        Further details.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.utilfunctest import die_unless_func_boundmethod

    # If this object is *NOT* a class method descriptor, raise an exception.
    die_unless_func_boundmethod(
        func=func,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this object is a class method descriptor.

    # Return the pure-Python function wrapped by this descriptor. Just do it!
    return func.__func__


def unwrap_func_class_or_static_method_once(
    # Mandatory parameters.
    func: Union[classmethod, staticmethod],

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCallableWrapperException,
    exception_prefix: str = '',
) -> Callable:
    '''
    Pure-Python unbound function wrapped by the passed **C-based unbound class
    or static method descriptor** (i.e., method decorated by either the builtin
    :class:`classmethod` or :class:`staticmethod` decorators, yielding a
    non-callable instance of that decorator class implemented in low-level C and
    accessible via the low-level :attr:`object.__dict__` dictionary rather than
    as class or instance attributes).

    Parameters
    ----------
    func : Union[classmethod, staticmethod]
        Class or static method descriptor to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`._BeartypeUtilCallableWrapperException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Returns
    -------
    Callable
        Pure-Python unbound function wrapped by this method descriptor.

    Raises
    ------
    exception_cls
         If the passed object is *not* a class or static method descriptor.

    See Also
    --------
    :func:`beartype._util.func.utilfunctest.is_func_classmethod`
    :func:`beartype._util.func.utilfunctest.is_func_staticmethod`
        Further details.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.utilfunctest import (
        die_unless_func_class_or_static_method)

    # If this object is neither a class *NOR* static method descriptor, raise an
    # exception.
    die_unless_func_class_or_static_method(
        func=func,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this object is either a class or static method descriptor.

    # Return the pure-Python function wrapped by this descriptor. Just do it!
    return func.__func__


#FIXME: Currently unused, but extensively tested. *shrug*
def unwrap_func_classmethod_once(
    # Mandatory parameters.
    func: classmethod,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCallableWrapperException,
    exception_prefix: str = '',
) -> Callable:
    '''
    Pure-Python unbound function wrapped by the passed **C-based unbound class
    method descriptor** (i.e., method decorated by the builtin
    :class:`classmethod` decorator, yielding a non-callable instance of that
    :class:`classmethod` decorator class implemented in low-level C and
    accessible via the low-level :attr:`object.__dict__` dictionary rather than
    as class or instance attributes).

    Parameters
    ----------
    func : classmethod
        Class method descriptor to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`._BeartypeUtilCallableWrapperException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Returns
    -------
    Callable
        Pure-Python unbound function wrapped by this class method descriptor.

    Raises
    ------
    exception_cls
         If the passed object is *not* a class method descriptor.

    See Also
    --------
    :func:`beartype._util.func.utilfunctest.is_func_classmethod`
        Further details.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.utilfunctest import die_unless_func_classmethod

    # If this object is *NOT* a class method descriptor, raise an exception.
    die_unless_func_classmethod(
        func=func,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this object is a class method descriptor.

    # Return the pure-Python function wrapped by this descriptor. Just do it!
    return func.__func__


#FIXME: Currently unused, but extensively tested. *shrug*
def unwrap_func_staticmethod_once(
    # Mandatory parameters.
    func: staticmethod,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCallableWrapperException,
    exception_prefix: str = '',
) -> Callable:
    '''
    Pure-Python unbound function wrapped by the passed **C-based unbound static
    method descriptor** (i.e., method decorated by the builtin
    :class:`staticmethod` decorator, yielding a non-callable instance of that
    :class:`staticmethod` decorator class implemented in low-level C and
    accessible via the low-level :attr:`object.__dict__` dictionary rather than
    as class or instance attributes).

    Parameters
    ----------
    func : staticmethod
        Static method descriptor to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`._BeartypeUtilCallableWrapperException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Returns
    -------
    Callable
        Pure-Python unbound function wrapped by this static method descriptor.

    Raises
    ------
    exception_cls
         If the passed object is *not* a static method descriptor.

    See Also
    --------
    :func:`beartype._util.func.utilfunctest.is_func_staticmethod`
        Further details.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.utilfunctest import die_unless_func_staticmethod

    # If this object is *NOT* a static method descriptor, raise an exception.
    die_unless_func_staticmethod(
        func=func,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )
    # Else, this object is a static method descriptor.

    # Return the pure-Python function wrapped by this descriptor. Just do it!
    return func.__func__

# ....................{ UNWRAPPERS ~ all                   }....................
def unwrap_func_all(func: Callable) -> Callable:
    '''
    Lowest-level **wrappee** (i.e., callable wrapped by the passed wrapper
    callable) of the passed higher-level **wrapper** (i.e., callable wrapping
    the wrappee callable to be returned) if the passed callable is a wrapper
    *or* that callable as is otherwise (i.e., if that callable is *not* a
    wrapper).

    Specifically, this getter iteratively undoes the work performed by:

    * One or more consecutive uses of the :func:`functools.wrap` decorator on
      the wrappee callable to be returned.
    * One or more consecutive calls to the :func:`functools.update_wrapper`
      function on the wrappee callable to be returned.

    Parameters
    ----------
    func : Callable
        Wrapper callable to be unwrapped.

    Returns
    -------
    Callable
        Either:

        * If the passed callable is a wrapper, the lowest-level wrappee
          callable wrapped by that wrapper.
        * Else, the passed callable as is.
    '''

    #FIXME: Not even this suffices to avoid a circular import, sadly. *sigh*
    # Avoid circular import dependencies.
    # from beartype._util.func.utilfunctest import is_func_wrapper

    # While this callable still wraps another callable, unwrap one layer of
    # wrapping by reducing this wrapper to its next wrappee.
    while hasattr(func, '__wrapped__'):
    # while is_func_wrapper(func):
        func = func.__wrapped__  # type: ignore[attr-defined]

    # Return this wrappee, which is now guaranteed to *NOT* be a wrapper.
    return func


def unwrap_func_all_isomorphic(
    # Mandatory parameters.
    func: Callable,

    # Optional parameters.
    wrapper: Optional[Callable] = None,
) -> Callable:
    '''
    Lowest-level **non-isomorphic wrappee** (i.e., callable wrapped by the
    passed wrapper callable) of the passed higher-level **isomorphic wrapper**
    (i.e., closure wrapping the wrappee callable to be returned by accepting
    both a variadic positional and keyword argument and thus preserving both the
    positions and types of all parameters originally passed to that wrappee) if
    the passed callable is an isomorphic wrapper *or* that callable as is
    otherwise (i.e., if that callable is *not* an isomorphic wrapper).

    Specifically, this getter iteratively undoes the work performed by:

    * One or more consecutive decorations of the :func:`functools.wrap`
      decorator on the wrappee callable to be returned.
    * One or more consecutive calls to the :func:`functools.update_wrapper`
      function on the wrappee callable to be returned.

    Parameters
    ----------
    func : Callable
        Wrapper callable to be inspected for isomorphism. If ``wrapper`` is
        :data:`None` (as is the common case), this callable is also unwrapped.
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
    Callable
        Either:

        * If the passed callable is an isomorphic wrapper, the lowest-level
          non-isomorphic wrappee callable wrapped by that wrapper.
        * Else, the passed callable as is.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.utilfunctest import (
        # is_func_boundmethod,
        is_func_codeobjable,
        is_func_wrapper_isomorphic,
    )

    # If the caller failed to explicitly pass a callable to be unwrapped,
    # default the callable to be unwrapped to the passed callable.
    if wrapper is None:
        wrapper = func
    # Else, the caller explicitly passed a callable to be unwrapped. In this
    # case, preserve that callable as is.

    # While...
    while True:
        # This wrappee callable remains a higher-level wrapper callable
        # isomorphically wrapping a lower-level wrappee callable, undo one layer
        # of wrapping by reducing the former to the latter.
        if is_func_wrapper_isomorphic(func=func, wrapper=wrapper):
            func_wrapped = unwrap_func_once(wrapper)
            # print(f'Unwrapped isomorphic {repr(func)} wrapper {repr(wrapper)} to {repr(func_wrapped)}.')
        # Else, this wrappee callable is no longer a higher-level wrapper
        # callable isomorphically wrapping a lower-level wrappee callable.

        #FIXME: Unneeded at the moment, but preserved for posterity. *shrug*
        # # If this wrappee callable remains a higher-level bound method
        # # descriptor, this descriptor transparently proxies and thus (by
        # # definition) isomorphically wraps a lower-level unbound method. In this
        # # case, undo one layer of wrapping by reducing the former to the latter.
        # elif is_func_boundmethod(func):
        #     func_wrapped = unwrap_func_boundmethod_once(func)
        #     # print(f'Unwrapped bound method descriptor {repr(func)} to {repr(func_wrapped)}.')

        # Else, this wrappee callable is no longer a higher-level bound method
        # descriptor either. Since this wrappee callable no longer wraps
        # anything, halt iteration.
        else:
            break
        # print(f'Unwrapped isomorphic {repr(func)} wrapper {repr(wrapper)} to {repr(func_wrapped)}.')

        # If the lower-level object wrapped by this higher-level isomorphic
        # wrapper is *NOT* a pure-Python callable, this object is something
        # uselessly pathological like a class or C-based callable. Silently
        # ignore this useless object by halting iteration. Doing so preserves
        # this useful higher-level isomorphic wrapper as is.
        #
        # Note that this insane edge case arises due to the standard
        # @functools.wraps() decorator, which passively accepts possibly C-based
        # classes by wrapping those classes with pure-Python functions: e.g.,
        #     from beartype import beartype
        #     from functools import wraps
        #     from typing import Any
        #
        #     @beartype
        #     @wraps(list)
        #     def wrapper(*args: Any, **kwargs: Any):
        #         return list(*args, **kwargs)
        #
        # In the above example, the higher-level isomorphic wrapper wrapper()
        # wraps the lower-level C-based class "list".
        #
        # Unwrapping this wrapper to this class would induce insanity throughout
        # the codebase, which sanely expects wrappers to be callables rather
        # than classes. Clearly, classes have *NO* signatures. Technically, a
        # pure-Python class may define __new__() and/or __init__() dunder
        # methods that could be considered to be the signatures of those
        # classes. Nonetheless, C-based classes like "list" have *NO* such
        # analogues. The *ONLY* sane approach here is to pretend that we never
        # saw this pathological edge case.
        if not is_func_codeobjable(func_wrapped):
            break
        # Else, this lower-level callable is pure-Python.

        # Reduce this higher-level wrapper to this lower-level wrappee.
        func = wrapper = func_wrapped

    # Return this wrappee, which is now guaranteed to *NOT* be an isomorphic
    # wrapper but might very well still be a wrapper, which is fine.
    return func
