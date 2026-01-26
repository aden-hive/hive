#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :mod:`functools` utilities (i.e., low-level callables handling
functionality defined by the standard :mod:`functools` module).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorWrappeeException
from beartype.roar._roarexc import _BeartypeUtilCallableException
from beartype.typing import (
    Any,
    Tuple,
)
from beartype._cave._cavefast import (
    CallableFunctoolsLruCacheType,
    CallableFunctoolsPartialType,
)
from beartype._data.typing.datatypingport import TypeIs
from beartype._data.typing.datatyping import (
    BeartypeableT,
    DictStrToAny,
    TypeException,
)
from collections.abc import Callable
from functools import lru_cache

# ....................{ TESTERS                            }....................
def is_func_functools_lru_cache(func: Any) -> TypeIs[Callable]:
    '''
    :data:`True` only if the passed object is a
    :func:`functools.lru_cache`-memoized **pseudo-callable** (i.e., low-level
    C-based callable object both created and returned by the standard
    :func:`functools.lru_cache` decorator).

    This tester enables callers to detect when a user-defined callable has been
    decorated by the :func:`functools.lru_cache` decorator, which creates
    low-level C-based callable objects requiring special handling elsewhere.

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a
        :func:`functools.lru_cache`-memoized callable.
    '''

    # Defer heavyweight tester-specific imports with potential side effects --
    # notably, increased costs to space and time complexity.

    # Return true only if the type of that callable is the low-level C-based
    # private type of all objects created and returned by the standard
    # @functools.lru_cache decorator.
    return isinstance(func, CallableFunctoolsLruCacheType)


def is_func_functools_partial(func: Any) -> TypeIs[
    CallableFunctoolsPartialType]:
    '''
    :data:`True` only if the passed object is a **partial** (i.e., pure-Python
    callable :class:`functools.partial` object wrapping a possibly C-based
    callable).

    Parameters
    ----------
    func : object
        Object to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this object is a
        :func:`functools.partial`-wrapped callable.
    '''

    # Return true only if the type of that callable is the high-level
    # pure-Python public type of all objects created and returned by the
    # standard functools.partial() factory.
    return isinstance(func, CallableFunctoolsPartialType)

# ....................{ GETTERS                            }....................
def get_func_functools_partial_args(
    func: CallableFunctoolsPartialType) -> Tuple[tuple, DictStrToAny]:
    '''
    2-tuple ``(args, kwargs)`` providing the positional and keyword parameters
    with which the passed **partial** (i.e., pure-Python callable
    :class:`functools.partial` object directly wrapping this possibly C-based
    callable) was originally partialized.

    Parameters
    ----------
    func : CallableFunctoolsPartialType
        Partial to be inspected.

    Returns
    -------
    Tuple[tuple, DictStrToAny]
        2-tuple ``(args, kwargs)`` such that:

        * ``args`` is the tuple of the zero or more positional parameters passed
          to the callable partialized by this partial.
        * ``kwargs`` is the dictionary mapping from the name to value of the
          zero or more keyword parameters passed to the callable partialized by
          this partial.
    '''
    assert isinstance(func, CallableFunctoolsPartialType), (
        f'{repr(func)} not "function.partial"-wrapped callable.')

    # Return a 2-tuple providing the positional and keyword parameters with
    # which this partial was originally partialized.
    return (func.args, func.keywords)


def get_func_functools_partial_args_flexible_len(
    # Mandatory parameters.
    func: CallableFunctoolsPartialType,

    # Optional parameters.
    is_unwrap: bool = True,
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> int:
    '''
    Number of **flexible parameters** (i.e., parameters passable as either
    positional or keyword arguments but *not* positional-only, keyword-only,
    variadic, or other more constrained kinds of parameters) accepted by the
    passed **partial** (i.e., pure-Python callable :class:`functools.partial`
    object directly wrapping this possibly C-based callable).

    Specifically, this getter transparently returns the total number of flexible
    parameters accepted by the lower-level callable wrapped by this partial
    minus the number of flexible parameters partialized away by this partial.

    Parameters
    ----------
    func : CallableFunctoolsPartialType
        Partial to be inspected.
    is_unwrap: bool, optional
        :data:`True` only if this getter implicitly calls the
        :func:`beartype._util.func.utilfuncwrap.unwrap_func_all` function.
        Defaults to :data:`True` for safety. See :func:`.get_func_codeobj` for
        further commentary.
    exception_cls : type, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :class:`._BeartypeUtilCallableException`.
    exception_prefix : str, optional
        Human-readable label prefixing the message of any exception raised in
        the event of a fatal error. Defaults to the empty string.

    Returns
    -------
    int
        Number of flexible parameters accepted by this callable.

    Raises
    ------
    exception_cls
         If that callable is *not* pure-Python.
    '''
    assert isinstance(func, CallableFunctoolsPartialType), (
        f'{repr(func)} not "function.partial"-wrapped callable.')

    # Avoid circular import dependencies.
    from beartype._util.func.arg.utilfuncarglen import (
        get_func_args_flexible_len)

    # Pure-Python wrappee callable wrapped by that partial.
    wrappee = unwrap_func_functools_partial_once(func)

    # Positional and keyword parameters implicitly passed by this partial to
    # this wrappee.
    partial_args, partial_kwargs = get_func_functools_partial_args(func)

    # Number of flexible parameters accepted by this wrappee.
    #
    # Note that this recursive function call is guaranteed to immediately bottom
    # out and thus be safe. Why? Because a partial *CANNOT* wrap itself, because
    # a partial has yet to be defined when the functools.partial.__init__()
    # method defining that partial is called. Technically, the caller *COULD*
    # violate sanity by directly interfering with the "func" instance variable
    # of this partial after instantiation. Pragmatically, a malicious edge case
    # like that is unlikely in the extreme. You are now reading this comment
    # because this edge case just blew up in your face, aren't you!?!? *UGH!*
    wrappee_args_flexible_len = get_func_args_flexible_len(
        func=wrappee,
        is_unwrap=is_unwrap,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # Number of flexible parameters passed by this partial to this wrappee.
    partial_args_flexible_len = len(partial_args) + len(partial_kwargs)

    # Number of flexible parameters accepted by this wrappee minus the number of
    # flexible parameters passed by this partial to this wrappee.
    func_args_flexible_len = (
        wrappee_args_flexible_len - partial_args_flexible_len)

    # If this number is negative, the caller maliciously defined an invalid
    # partial passing more flexible parameters than this wrappee accepts. In
    # this case, raise an exception.
    #
    # Note that the "functools.partial" factory erroneously allows callers to
    # define invalid partials passing more flexible parameters than their
    # wrappees accept. Ergo, validation is required to guarantee sanity.
    if func_args_flexible_len < 0:
        raise exception_cls(
            f'{exception_prefix}{repr(func)} passes '
            f'{partial_args_flexible_len} parameter(s) to '
            f'{repr(wrappee)} accepting only '
            f'{wrappee_args_flexible_len} parameter(s) '
            f'(i.e., {partial_args_flexible_len} > '
            f'{wrappee_args_flexible_len}).'
        )
    # Else, this number is non-negative. The caller correctly defined a valid
    # partial passing no more flexible parameters than this wrappee accepts.

    # Return this number.
    return func_args_flexible_len

# ....................{ UNWRAPPERS                         }....................
def unwrap_func_functools_partial_once(
    func: CallableFunctoolsPartialType) -> Callable:
    '''
    Possibly C-based callable directly wrapped by the passed **partial** (i.e.,
    pure-Python callable :class:`functools.partial` object directly wrapping
    this possibly C-based callable).

    Parameters
    ----------
    func : CallableFunctoolsPartialType
        Partial to be unwrapped.

    Returns
    -------
    Callable
        Possibly C-based callable directly wrapped by this partial.
    '''
    assert isinstance(func, CallableFunctoolsPartialType), (
        f'{repr(func)} not "function.partial"-wrapped callable.')

    # Return the public "func" instance variable of this partial wrapper as is.
    return func.func

# ....................{ DECORATORS                         }....................
def beartype_functools_lru_cache(
    pseudofunc: BeartypeableT, **kwargs) -> BeartypeableT:
    '''
    Monkey-patch the passed :func:`functools.lru_cache`-memoized
    **pseudo-callable** (i.e., low-level C-based callable object both created
    and returned by the standard :func:`functools.lru_cache` decorator) with
    dynamically generated type-checking.

    Parameters
    ----------
    pseudofunc : BeartypeableT
        Pseudo-callable to be monkey-patched by :func:`beartype.beartype`.

    All remaining keyword parameters are passed as is to the lower-level
    :func:`.beartype_func` decorator internally called by this higher-level
    decorator on the pure-Python function encapsulated in this descriptor.

    Returns
    -------
    BeartypeableT
        New pseudo-callable monkey-patched by :func:`beartype.beartype`.
    '''

    # Avoid circular and third-party import dependencies.
    from beartype._decor._nontype.decornontype import beartype_func
    from beartype._util.func.utilfuncwrap import unwrap_func_once

    # If this pseudo-callable is *NOT* actually a @functools.lru_cache-memoized
    # callable, raise an exception.
    if not is_func_functools_lru_cache(pseudofunc):
        raise BeartypeDecorWrappeeException(  # pragma: no cover
            f'@functools.lru_cache-memoized callable {repr(pseudofunc)} not  '
            f'decorated by @functools.lru_cache.'
        )
    # Else, this pseudo-callable is a @functools.lru_cache-memoized callable.

    # Original pure-Python callable decorated by @functools.lru_cache.
    func = unwrap_func_once(pseudofunc)  # pyright: ignore

    # Decorate that callable with type-checking.
    func_checked = beartype_func(func=func, **kwargs)

    # Dictionary mapping from the names of all keyword parameters originally
    # passed by the caller to that decorator, enabling the re-decoration of that
    # callable. Thankfully, that decorator preserves these parameters via the
    # decorator-specific "cache_parameters" instance variable whose value is a
    # bizarre argumentless lambda function (...for unknown reasons that are
    # probably indefensible) creating and returning this dictionary: e.g.,
    #     >>> from functools import lru_cache
    #     >>> @lru_cache(maxsize=3)
    #     ... def plus_one(n: int) -> int: return n +1
    #     >>> plus_one.cache_parameters()
    #     {'maxsize': 3, 'typed': False}
    lru_cache_kwargs = pseudofunc.cache_parameters()  # type: ignore[attr-defined]

    # Closure defined and returned by the @functools.lru_cache decorator when
    # passed these keyword parameters.
    lru_cache_configured = lru_cache(**lru_cache_kwargs)

    # Re-decorate that callable by @functools.lru_cache by the same parameters
    # originally passed by the caller to that decorator.
    pseudofunc_checked = lru_cache_configured(func_checked)

    # Return that new pseudo-callable.
    return pseudofunc_checked  # pyright: ignore
