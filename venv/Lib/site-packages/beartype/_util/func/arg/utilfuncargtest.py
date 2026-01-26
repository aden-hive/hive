#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **callable parameter tester utilities** (i.e., low-level functions
validating and testing various kinds of parameters accepted by arbitrary
callables).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilCallableException
from beartype._util.func.arg.utilfuncargiter import (
    ARG_META_INDEX_NAME,
)
from beartype._util.func.arg.utilfuncarglen import (
    ARGS_LENS_INDEX_VAR_POS,
    ARGS_LENS_INDEX_VAR_KW,
    get_func_args_flexible_len,
    get_func_args_len,
    get_func_args_lens,
    get_func_args_nonvariadic_len,
)
from beartype._data.typing.datatyping import (
    Codeobjable,
    TypeException,
)

# ....................{ RAISERS                            }....................
def die_unless_func_args_len_flexible_equal(
    # Mandatory parameters.
    func: Codeobjable,
    func_args_len_flexible: int,

    # Optional parameters.
    is_unwrap: bool = True,
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed pure-Python callable accepts the passed
    number of **flexible parameters** (i.e., parameters passable as either
    positional or keyword arguments).

    Parameters
    ----------
    func : Codeobjable
        Pure-Python callable, frame, or code object to be inspected.
    func_args_len_flexible : int
        Number of flexible parameters to validate this callable as accepting.
    is_unwrap: bool, default: True
        :data:`True` only if this validator implicitly calls the
        :func:`beartype._util.func.utilfuncwrap.unwrap_func_all` function to
        unwrap this possibly higher-level wrapper into its possibly lowest-level
        wrappee *before* returning the code object of that wrappee. Note that
        doing so incurs worst-case time complexity :math:`O(n)` for :math:`n`
        the number of lower-level wrappees wrapped by this wrapper. Defaults to
        :data:`True` for robustness. Why? Because this validator *must* always
        introspect lowest-level wrappees rather than higher-level wrappers. The
        latter typically do *not* accurately replicate the signatures of the
        former. In particular, decorator wrappers typically wrap decorated
        callables with variadic positional and keyword parameters (e.g., ``def
        _decorator_wrapper(*args, **kwargs)``). Since neither constitutes a
        flexible parameter, this validator raises an exception when passed such
        a wrapper with this boolean set to :data:`False`. Only set this boolean
        to :data:`False` if you pretend to know what you're doing.
    exception_cls : type[Exception], default: _BeartypeUtilCallableException
        Type of exception to be raised in the event of a fatal error. Defaults
        to :class:`._BeartypeUtilCallableException`.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    exception_cls
        If this callable either:

        * Is *not* callable.
        * Is callable but is *not* pure-Python.
        * Is a pure-Python callable accepting either more or less than this
          Number of flexible parameters.
    '''
    assert isinstance(func_args_len_flexible, int)

    # Number of flexible parameters accepted by this callable.
    func_args_len_flexible_actual = get_func_args_flexible_len(
        func=func,
        is_unwrap=is_unwrap,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # If this callable accepts more or less than this number of flexible
    # parameters, raise an exception.
    if func_args_len_flexible_actual != func_args_len_flexible:
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not exception type.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        raise exception_cls(
            f'{exception_prefix}callable {repr(func)} flexible argument count '
            f'{func_args_len_flexible_actual} != {func_args_len_flexible} '
            f'(i.e., {repr(func)} accepts {func_args_len_flexible_actual} '
            f'rather than {func_args_len_flexible} positional and/or keyword '
            f'parameters).'
        )
    # Else, this callable accepts exactly this number of flexible parameters.


#FIXME: Uncomment as needed.
# def die_unless_func_argless(
#     # Mandatory parameters.
#     func: Codeobjable,
#
#     # Optional parameters.
#     func_label: str = 'Callable',
#     exception_cls: Type[Exception] = _BeartypeUtilCallableException,
# ) -> None:
#     '''
#     Raise an exception unless the passed pure-Python callable is
#     **argumentless** (i.e., accepts *no* arguments).
#
#     Parameters
#     ----------
#     func : Codeobjable
#         Pure-Python callable, frame, or code object to be inspected.
#     func_label : str, optional
#         Human-readable label describing this callable in exception messages
#         raised by this validator. Defaults to ``'Callable'``.
#     exception_cls : type, optional
#         Type of exception to be raised if this callable is neither a
#         pure-Python function nor method. Defaults to
#         :class:`_BeartypeUtilCallableException`.
#
#     Raises
#     ----------
#     exception_cls
#         If this callable either:
#
#         * Is *not* callable.
#         * Is callable but is *not* pure-Python.
#         * Is a pure-Python callable accepting one or more parameters.
#     '''
#
#     # If this callable accepts one or more arguments, raise an exception.
#     if is_func_argless(
#         func=func, func_label=func_label, exception_cls=exception_cls):
#         assert isinstance(func_label, str), f'{repr(func_label)} not string.'
#         assert isinstance(exception_cls, type), (
#             f'{repr(exception_cls)} not class.')
#
#         raise exception_cls(
#             f'{func_label} {repr(func)} not argumentless '
#             f'(i.e., accepts one or more arguments).'
#         )

# ....................{ TESTERS ~ kind                     }....................
def is_func_argless(
    # Mandatory parameters.
    func: Codeobjable,

    # Optional parameters.
    is_unwrap: bool = False,
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> bool:
    '''
    :data:`True` only if the passed pure-Python callable is **argumentless**
    (i.e., accepts *no* arguments).

    Parameters
    ----------
    func : Codeobjable
        Pure-Python callable, frame, or code object to be inspected.
    is_unwrap: bool, optional
        :data:`True` only if this getter implicitly calls the
        :func:`beartype._util.func.utilfuncwrap.unwrap_func_all` function.
        Defaults to :data:`False` to avoid confusion with decorator wrappers,
        which almost always accept variadic arguments despite the callable they
        wrap *not* accepting such arguments. See also
        :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj`.
    exception_cls : type, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :class:`._BeartypeUtilCallableException`.
    exception_prefix : str, optional
        Human-readable label prefixing the message of any exception raised in
        the event of a fatal error. Defaults to the empty string.

    Returns
    -------
    bool
        :data:`True` only if the passed callable accepts *no* arguments.

    Raises
    ------
    exception_cls
         If the passed callable is *not* pure-Python.
    '''

    # Return true only if the passed callable accepts *NO* parameters.
    return not get_func_args_len(
        func=func,
        is_unwrap=is_unwrap,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

# ....................{ TESTERS ~ kind : non-variadic      }....................
#FIXME: Unit test us up, please.
def is_func_arg_nonvariadic(*args, **kwargs) -> bool:
    '''
    :data:`True` only if the passed pure-Python callable accepts any
    **non-variadic parameters** (i.e., one or more positional, positional-only,
    keyword, or keyword-only arguments).

    Parameters
    ----------
    All parameters are passed as is to the lower-level
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj` getter.

    Returns
    -------
    bool
        :data:`True` only if that callable accepts any non-variadic parameters.

    Raises
    ------
    exception_cls
         If that callable is *not* pure-Python.
    '''

    # Return true only if this callable accepts any non-variadic parameters.
    return bool(get_func_args_nonvariadic_len(*args, **kwargs))

# ....................{ TESTERS ~ kind : variadic          }....................
def is_func_arg_variadic(*args, **kwargs) -> bool:
    '''
    :data:`True` only if the passed pure-Python callable accepts any **variadic
    parameters** (i.e., either a variadic positional argument (e.g.,
    ``*args``) *or* a variadic keyword argument (e.g., ``**kwargs``)).

    Parameters
    ----------
    All parameters are passed as is to the lower-level
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj` getter.

    Returns
    -------
    bool
        :data:`True` only if that callable accepts either:

        * Variadic positional arguments (e.g., ``*args``).
        * Variadic keyword arguments (e.g., ``**kwargs``).

    Raises
    ------
    exception_cls
         If that callable is *not* pure-Python.
    '''

    # Number of various kinds of parameters accepted by that callable.
    func_args_lens = get_func_args_lens(*args, **kwargs)

    # Return true only if this callable accepts any variadic argument.
    return bool(
        func_args_lens[ARGS_LENS_INDEX_VAR_POS] +
        func_args_lens[ARGS_LENS_INDEX_VAR_KW]
    )


def is_func_arg_variadic_positional(*args, **kwargs) -> bool:
    '''
    :data:`True` only if the passed pure-Python callable accepts a variadic
    positional argument (e.g., ``*args``).

    Parameters
    ----------
    All parameters are passed as is to the lower-level
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj` getter.

    Returns
    -------
    bool
        :data:`True` only if the passed callable accepts a variadic positional
        argument.

    Raises
    ------
    exception_cls
         If the passed callable is *not* pure-Python.
    '''

    # Number of various kinds of parameters accepted by that callable.
    func_args_lens = get_func_args_lens(*args, **kwargs)

    # Return true only if this callable accepts a variadic positional argument.
    return func_args_lens[ARGS_LENS_INDEX_VAR_POS]  # type: ignore[return-value]


def is_func_arg_variadic_keyword(*args, **kwargs) -> bool:
    '''
    :data:`True` only if the passed pure-Python callable accepts a variadic
    keyword argument (e.g., ``**kwargs``).

    Parameters
    ----------
    All parameters are passed as is to the lower-level
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj` getter.

    Returns
    -------
    bool
        :data:`True` only if the passed callable accepts a variadic keyword
        argument.

    Raises
    ------
    exception_cls
         If the passed callable is *not* pure-Python.
    '''

    # Number of various kinds of parameters accepted by that callable.
    func_args_lens = get_func_args_lens(*args, **kwargs)

    # Return true only if this callable accepts a variadic keyword argument.
    return func_args_lens[ARGS_LENS_INDEX_VAR_KW]  # type: ignore[return-value]

# ....................{ TESTERS ~ name                     }....................
def is_func_arg_name(arg_name: str, *args, **kwargs) -> bool:
    '''
    :data:`True` only if the passed pure-Python callable accepts an argument
    with the passed name.

    Parameters
    ----------
    arg_name : str
        Name of the argument to be searched for.

    All remaining parameters are passed as is to the lower-level
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj` getter.

    Returns
    -------
    bool
        :data:`True` only if that callable accepts an argument with this name.

    Raises
    ------
    exception_cls
         If the passed callable is *not* pure-Python.
    '''
    assert isinstance(arg_name, str), f'{repr(arg_name)} not string.'

    # Avoid circular import dependencies.
    from beartype._util.func.arg.utilfuncargget import get_func_arg_names

    # Tuple of the names of all parameters accepted by the passed callable.
    arg_names = get_func_arg_names(*args, **kwargs)

    # Return true only if the passed name is in this tuple.
    #
    # Technically, this search has linear-time complexity "O(n)" for "n" the
    # number of parameters accepted by that callable. Pragmatically, "n" is
    # typically quite small; ergo, the real-world constants associated with this
    # complexity are also quite small. Although this search *COULD* be trivially
    # reduced to constant-time complexity "O(1)" by coercing this tuple into a
    # set, doing so would also substantially increase the real-world constants
    # associated with that complexity. In the absence of compelling profilings,
    # we currently prefer to abide by Keep It Simple Stupid (KISS). Tuple wins!
    return arg_name in arg_names


def is_func_arg_name_variadic_positional(
    arg_name: str, *args, **kwargs) -> bool:
    '''
    :data:`True` only if the passed pure-Python callable accepts a variadic
    positional parameter with the passed name.

    Caveats
    -------
    **This tester exhibits worst-case linear-time complexity** :math:`O(n)`
    **for** :math:`O(n)` **the total number of parameters accepted by that
    callable** due to unavoidably performing a linear search for a variadic
    positional parameter with this name is this callable's parameter list. This
    tester should thus be called sparingly.

    Parameters
    ----------
    arg_name : str
        Name of the argument to be searched for.

    All remaining parameters are passed as is to the lower-level
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj` getter.

    Returns
    -------
    bool
        :data:`True` only if that callable accepts a variadic positional
        argument with this name.

    Raises
    ------
    exception_cls
         If the passed callable is *not* pure-Python.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.arg.utilfuncargget import (
        get_func_arg_meta_variadic_positional_or_none)

    # If the passed callable accepts *NO* parameter with the passed name,
    # immediately return false.
    if not is_func_arg_name(*args, arg_name=arg_name, **kwargs): # type: ignore[misc]
        return False
    # Else, that callable accepts a parameter with the passed name. In this
    # case, further testing is warranted.

    # Metadata describing the variadic positional parameter accepted by that
    # callable if that callable accepts a variadic positional parameter *OR*
    # "None" otherwise (i.e., if that callable accepts *NO* such parameter).
    arg_meta = get_func_arg_meta_variadic_positional_or_none(*args, **kwargs)

    # Return true only if...
    return (
        # That callable accepts a variadic positional parameter *AND*...
        arg_meta is not None and
        # The name of this parameter is the passed name.
        arg_meta[ARG_META_INDEX_NAME] == arg_name
    )


def is_func_arg_name_variadic_keyword(
    arg_name: str, *args, **kwargs) -> bool:
    '''
    :data:`True` only if the passed pure-Python callable accepts a variadic
    keyword parameter with the passed name.

    Caveats
    -------
    **This tester exhibits worst-case linear-time complexity** :math:`O(n)`
    **for** :math:`O(n)` **the total number of parameters accepted by that
    callable** due to unavoidably performing a linear search for a variadic
    keyword parameter with this name is this callable's parameter list. This
    tester should thus be called sparingly.

    Parameters
    ----------
    arg_name : str
        Name of the argument to be searched for.

    All remaining parameters are passed as is to the lower-level
    :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj` getter.

    Returns
    -------
    bool
        :data:`True` only if that callable accepts a variadic keyword parameter
        with this name.

    Raises
    ------
    exception_cls
         If the passed callable is *not* pure-Python.
    '''

    # Avoid circular import dependencies.
    from beartype._util.func.arg.utilfuncargget import (
        get_func_arg_meta_variadic_keyword_or_none)

    # If the passed callable accepts *NO* parameter with the passed name,
    # immediately return false.
    if not is_func_arg_name(*args, arg_name=arg_name, **kwargs): # type: ignore[misc]
        return False
    # Else, that callable accepts a parameter with the passed name. In this
    # case, further testing is warranted.

    # Metadata describing the variadic keyword parameter accepted by that
    # callable if that callable accepts a variadic keyword parameter *OR* "None"
    # otherwise (i.e., if that callable accepts *NO* such parameter).
    arg_meta = get_func_arg_meta_variadic_keyword_or_none(*args, **kwargs)

    # Return true only if...
    return (
        # That callable accepts a variadic keyword parameter *AND*...
        arg_meta is not None and
        # The name of this parameter is the passed name.
        arg_meta[ARG_META_INDEX_NAME] == arg_name
    )
