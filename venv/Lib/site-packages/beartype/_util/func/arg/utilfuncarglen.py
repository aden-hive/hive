#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **callable parameter length getter utilities** (i.e., low-level
functions introspecting the numbers of various kinds of parameters accepted by
arbitrary callables).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilCallableException
from beartype.typing import Tuple
from beartype._cave._cavefast import (
    FunctionType,
    MethodBoundInstanceOrClassType,
)
from beartype._data.typing.datatyping import (
    Codeobjable,
    TypeException,
)
from beartype._util.func.utilfunccodeobj import get_func_codeobj
from inspect import (
    CO_VARARGS,
    CO_VARKEYWORDS,
)
from itertools import count

# ....................{ HINTS                              }....................
CallableArgsLens = Tuple[int, int, bool, bool]
'''
PEP-compliant type hint matching **callable parameter length metadata** returned
by the :func:`.get_func_args_lens` getter, defined as the 4-tuple
``(args_len_posonly_or_flex, args_len_kwonly, args_len_var_pos,
args_len_var_kw)`` such that:

* ``args_len_posonly_or_flex`` is the total number of all **non-keyword-only
  parameters** (i.e., both optional and mandatory positional-only, positional,
  and keyword parameters) accepted by the callable passed to that getter.
* ``args_len_kwonly`` is the total number of all **keyword-only parameters**
  (i.e., both optional and mandatory keyword-only parameters) accepted by the
  callable passed to that getter.
* ``args_len_var_pos`` is either:

  * If the callable passed to that getter accepts a variadic positional
    parameter, ``1``.
  * Else, ``0``.

* ``args_len_var_kw`` is either:

  * If the callable passed to that getter accepts a variadic keyword parameter,
    ``1``.
  * Else, ``0``.
'''

# ....................{ CONSTANTS ~ index                  }....................
# Iterator yielding the next integer incrementation starting at 0, to be safely
# deleted *AFTER* defining the following 0-based indices via this iterator.
__args_lens_index_counter = count(start=0, step=1)


ARGS_LENS_INDEX_POSONLY_OR_FLEX = next(__args_lens_index_counter)
'''
0-based index into each 4-tuple returned the :func:`.get_func_args_lens` getter
of the total number of all **non-keyword-only parameters** (i.e., both optional
and mandatory positional-only, positional, and keyword parameters) accepted by
the callable passed to that getter.
'''


ARGS_LENS_INDEX_KWONLY = next(__args_lens_index_counter)
'''
0-based index into each 4-tuple returned the :func:`.get_func_args_lens` getter
of the total number of all **keyword-only parameters** (i.e., both optional and
mandatory keyword-only parameters) accepted by the callable passed to that
getter.
'''


ARGS_LENS_INDEX_VAR_POS = next(__args_lens_index_counter)
'''
0-based index into each 4-tuple returned the :func:`.get_func_args_lens` getter
of either:

* If the callable passed to that getter accepts a variadic positional parameter,
  ``1``.
* Else, ``0``.
'''


ARGS_LENS_INDEX_VAR_KW = next(__args_lens_index_counter)
'''
0-based index into each 4-tuple returned the :func:`.get_func_args_lens` getter
of either:

* If the callable passed to that getter accepts a variadic keyword parameter,
  ``1``.
* Else, ``0``.
'''


# Delete the above counter for safety and sanity in equal measure.
del __args_lens_index_counter

# ....................{ GETTERS                            }....................
#FIXME: Unit test us up, please.
def get_func_args_len(*args, **kwargs) -> int:
    '''
    Total number of parameters accepted by the passed pure-Python callable,
    regardless of the kind of those parameters.

    Parameters
    ----------
    All parameters are passed as is to the lower-level
    :func:`.get_func_codeobj` getter.

    Returns
    -------
    int
        Total number of parameters accepted by that callable.

    Raises
    ------
    exception_cls
         If that callable is *not* pure-Python.
    '''

    # Number of various kinds of parameters accepted by that callable.
    (
        # Number of both optional and mandatory non-keyword-only parameters
        # (i.e., positional-only *AND* flexible (i.e., positional or keyword)
        # parameters) accepted by that callable.
        args_len_posonly_or_flex,
        # Number of both optional and mandatory keyword-only parameters accepted
        # by that callable.
        args_len_kwonly,
        # 1 only if that callable accepts variadic positional or keyword
        # parameters and 0 otherwise.
        is_arg_var_pos,
        is_arg_var_kw,
    ) = get_func_args_lens(*args, **kwargs)

    # Return the total number of parameters accepted by that callable.
    return (
        args_len_posonly_or_flex +
        args_len_kwonly +
        is_arg_var_pos +
        is_arg_var_kw
    )


#FIXME: [SPEED] Attempt to restore caching. See internal commentary. *sigh*
#FIXME: Unit test us up, please.
def get_func_args_lens(
    # Mandatory parameters.
    func: Codeobjable,

    # Optional parameters.
    is_unwrap: bool = True,
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> CallableArgsLens:
    '''
    4-tuple ``(args_len_posonly_or_flex, args_len_kwonly, args_len_var_pos,
    args_len_var_kw)`` of all **callable parameter length metadata** describing
    the total number of various kinds of parameters accepted by the passed
    pure-Python callable.

    This getter is memoized (i.e., cached) via a :mod:`beartype`-specific
    ``__beartype_args_lens`` instance variable on that callable for efficiency.

    Parameters
    ----------
    func : Codeobjable
        Pure-Python callable, frame, or code object to be inspected.
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
    CallableArgsLens
        4-tuple ``(args_len_posonly_or_flex, args_len_kwonly, args_len_var_pos,
        args_len_var_kw)`` of all **callable parameter length metadata.** See
        :data:`.CallableArgsLens` for further details.

    Raises
    ------
    exception_cls
         If that callable is *not* pure-Python.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.utilfuncwrap import unwrap_func_all_isomorphic

    # If unwrapping that callable, do so *BEFORE* obtaining the code object of
    # that callable for safety (to avoid desynchronization between the two).
    if is_unwrap:
        func = unwrap_func_all_isomorphic(func)  # type: ignore[arg-type]
    # Else, that callable is assumed to have already been unwrapped by the
    # caller. We should probably assert that, but doing so requires an
    # expensive call to hasattr(). What you gonna do?

    # Beartype-specific callable parameter length metadata previously computed
    # for this callable if any *OR* "None" otherwise.
    func_args_lens = getattr(func, '__beartype_args_lens', None)

    # If this metadata has been previously computed, return this metadata.
    if func_args_lens:
        return func_args_lens
    # Else, this metadata has *NOT* been previously computed.

    # Code object underlying the passed pure-Python callable unwrapped.
    func_codeobj = get_func_codeobj(
        func=func,
        is_unwrap=False,  # <-- "func" was already unwrapped above. I sigh.
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # Bit field of OR-ed binary flags describing this callable.
    func_codeobj_flags = func_codeobj.co_flags

    # Callable parameter length metadata, defined as the 4-tuple of...
    func_args_lens = (
        # Number of both optional and mandatory non-keyword-only parameters
        # (i.e., positional-only *AND* flexible (i.e., positional or keyword)
        # parameters) accepted by that callable.
        func_codeobj.co_argcount,
        # Number of both optional and mandatory keyword-only parameters accepted
        # by that callable.
        func_codeobj.co_kwonlyargcount,
        # 1 only if that callable accepts variadic positional or keyword
        # parameters. Note that:
        # * Python implements booleans as integers. The standard "bool" type is
        #   a subclass of the standard "int" type. Notably, boolean:
        #   * "True" is literally integer "1".
        #   * "False" is literally integer "0".
        # * Coercing:
        #   * Any positive integer to a boolean is the most efficient means of
        #     reducing that integer to "1".
        #   * The integer "0" to a boolean silently reduces to a noop.
        # * If that callable accepts:
        #   * A variadic positional parameter, then the operation
        #     "func_codeobj_flags & CO_VARARGS == 4". Coercing that to a boolean
        #     then reduces that to the integer "1" as desired.
        #   * A variadic keyword parameter, then the operation
        #     "func_codeobj_flags & CO_VARKEYWORDS == 8". Coercing that to a
        #     boolean then reduces that to the integer "1" as desired.
        #
        # Black magic. Black magic is what we're trying to say.
        bool(func_codeobj_flags & CO_VARARGS),
        bool(func_codeobj_flags & CO_VARKEYWORDS),
    )

    #FIXME: Unsafe, fascinatingly. Uncommenting this induces test failure.
    # If that callable is actually pure-Python, cache this metadata onto that
    # callable as this beartype-specific instance variable.
    #
    # Note that doing so is unsafe if that callable is *NOT* pure-Python (e.g.,
    # is a C-based code object, call stack frame, or other low-level non-Python
    # "CodeObjable"). Why? Because only pure-Python callables can be
    # monkey-patched. Other "CodeObjable" objects hate monkey-patching: e.g.,
    #     AttributeError: 'code' object has no attribute '__beartype_args_lens'
    #     and no __dict__ for setting new attributes
    if isinstance(func, FunctionType):
        func.__beartype_args_lens = func_args_lens  # type: ignore[attr-defined]
    # Else, that callable is *NOT* pure-Python. In this case, avoid attempting
    # to cache this metadata anywhere.

    # Return this metadata.
    return func_args_lens

# ....................{ GETTERS ~ kind                     }....................
def get_func_args_flexible_len(
    # Mandatory parameters.
    func: Codeobjable,

    # Optional parameters.
    is_unwrap: bool = True,
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> int:
    '''
    Number of **flexible parameters** (i.e., parameters passable as either
    positional or keyword arguments but *not* positional-only, keyword-only,
    variadic, or other more constrained kinds of parameters) accepted by the
    passed pure-Python callable.

    This getter transparently handles all of the following:

    * Conventional pure-Python callables.
    * If ``is_unwrap`` is :data:`True`:

      * Pure-Python **partials** (i.e., pure-Python callable
        :class:`functools.partial` objects directly wrapping pure-Python
        callables). If a partial is passed, this getter transparently returns
        the total number of flexible parameters accepted by the lower-level
        callable wrapped by this partial minus the number of flexible parameters
        partialized away by this partial.

    Parameters
    ----------
    func : Codeobjable
        Pure-Python callable, frame, or code object to be inspected.
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

    # Avoid circular import dependencies.
    from beartype._util.api.standard.utilfunctools import (
        get_func_functools_partial_args_flexible_len,
        is_func_functools_partial,
    )
    from beartype._util.func.utilfunctest import is_func_codeobjable

    # If the passed callable is pure-Python...
    if is_func_codeobjable(func):
        # Number of various kinds of parameters accepted by that callable.
        func_args_lens = get_func_args_lens(
            func=func,
            is_unwrap=is_unwrap,
            exception_cls=exception_cls,
            exception_prefix=exception_prefix,
        )

        # Number of all non-keyword-only parameters (i.e., both optional and
        # mandatory positional-only, positional, and keyword parameters)
        # accepted by that callable.
        return func_args_lens[ARGS_LENS_INDEX_POSONLY_OR_FLEX]
    # Else, that callable has *NO* code object.
    #
    # If that callable is *NOT* actually callable, raise an exception.
    elif not callable(func):
        raise exception_cls(f'{exception_prefix}{repr(func)} uncallable.')
    # Else, that callable is callable.
    #
    # If unwrapping that callable *AND* that callable is a partial (i.e.,
    # "functools.partial" object wrapping a lower-level callable), return the
    # total number of flexible parameters accepted by the pure-Python wrappee
    # callable wrapped by this partial minus the number of flexible parameters
    # passed by this partial to this wrappee.
    elif is_unwrap and is_func_functools_partial(func):
        return get_func_functools_partial_args_flexible_len(
            func=func,
            is_unwrap=is_unwrap,
            exception_cls=exception_cls,
            exception_prefix=exception_prefix,
        )
    # Else, that callable is *NOT* a partial.
    #
    # By process of elimination, that callable *MUST* be an otherwise uncallable
    # object whose class has intentionally made that object callable by defining
    # the __call__() dunder method. Fallback to introspecting that method.

    # "__call__" attribute of that callable if any *OR* "None" otherwise (i.e.,
    # if that callable is actually uncallable).
    func_call_attr = getattr(func, '__call__', None)

    # If that callable fails to define the "__call__" attribute, that callable
    # is actually uncallable. But the callable() builtin claimed that callable
    # to be callable above. In this case, raise an exception.
    #
    # Note that this should *NEVER* happen. Nonetheless, this just happened.
    if func_call_attr is None:  # pragma: no cover
        raise exception_cls(
            f'{exception_prefix}{repr(func)} uncallable '
            f'(i.e., defines no __call__() dunder method).'
        )
    # Else, that callable defines the __call__() dunder method.

    # Return the total number of flexible parameters accepted by the pure-Python
    # wrappee callable wrapped by this bound method descriptor minus one to
    # account for the first "self" parameter implicitly
    # passed by this descriptor to that callable.
    return _get_func_boundmethod_args_flexible_len(
        func=func_call_attr,
        is_unwrap=is_unwrap,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )


#FIXME: Unit test us up, please.
def get_func_args_nonvariadic_len(*args, **kwargs) -> int:
    '''
    Number of **non-variadic parameters** (i.e., parameters passable as either
    positional, positional-only, keyword, or keyword-only arguments) accepted by
    the passed pure-Python callable.

    Parameters
    ----------
    All parameters are passed as is to the lower-level
    :func:`.get_func_codeobj` getter.

    Returns
    -------
    int
        Number of flexible parameters accepted by this callable.

    Raises
    ------
    exception_cls
         If that callable is *not* pure-Python.
    '''

    # Number of various kinds of parameters accepted by the passed callable.
    func_args_lens = get_func_args_lens(*args, **kwargs)

    # Return the number of non-variadic parameters accepted by this callable.
    return (
        func_args_lens[ARGS_LENS_INDEX_POSONLY_OR_FLEX] +
        func_args_lens[ARGS_LENS_INDEX_KWONLY]
    )

# ....................{ PRIVATE ~ getters : len            }....................
def _get_func_boundmethod_args_flexible_len(
    # Mandatory parameters.
    func: MethodBoundInstanceOrClassType,

    # Optional parameters.
    is_unwrap: bool = True,
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> int:
    '''
    Number of **flexible parameters** (i.e., parameters passable as either
    positional or keyword arguments but *not* positional-only, keyword-only,
    variadic, or other more constrained kinds of parameters) accepted by the
    passed **C-based bound instance method descriptor** (i.e., callable
    implicitly instantiated and assigned on the instantiation of an object whose
    class declares an instance function (whose first parameter is typically
    named ``self``)).

    Specifically, this getter transparently returns one less than the total
    number of flexible parameters accepted by the lower-level callable wrapped
    by this descriptor to account for the first ``self`` parameter implicitly
    passed by this descriptor to that callable.

    Parameters
    ----------
    func : MethodBoundInstanceOrClassType
        Bound method descriptor to be inspected.
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

    # Avoid circular import dependencies.
    from beartype._util.func.utilfuncwrap import unwrap_func_boundmethod_once

    # Unbound pure-Python function encapsulated by this C-based bound method
    # descriptor bound to some callable object.
    wrappee = unwrap_func_boundmethod_once(
        func=func,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # Number of flexible parameters accepted by that function.
    #
    # Note that this recursive function call is guaranteed to immediately bottom
    # out and thus be safe for similar reasons as given above.
    wrappee_args_flexible_len = get_func_args_flexible_len(
        func=wrappee,
        is_unwrap=is_unwrap,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # If this number is zero, the caller maliciously defined a non-static
    # function accepting *NO* parameters. Since this paradoxically includes the
    # mandatory first "self" parameter for a bound method descriptor, it is
    # infeasible for this edge case to occur. Nonetheless, raise an exception.
    if not wrappee_args_flexible_len:  # pragma: no cover
        raise exception_cls(
            f'{exception_prefix}{repr(func)} accepts no '
            f'parameters despite being a bound instance method descriptor.'
        )
    # Else, this number is positive.

    # Return this number minus one to account for the fact that this bound
    # method descriptor implicitly passes the instance object to which this
    # method descriptor is bound as the first parameter to all calls of this
    # method descriptor.
    return wrappee_args_flexible_len - 1
