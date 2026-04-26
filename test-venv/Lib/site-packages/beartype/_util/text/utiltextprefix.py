#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **text prefix utilities** (i.e., low-level callables creating and
returning human-readable strings describing prominent objects or types and
*always* suffixed by exactly one space character, intended to prefix
human-readable error messages).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._data.func.datafuncarg import ARG_NAME_RETURN
from beartype._data.typing.datatyping import (
    BeartypeableT,
    BoolTristate,
)
from beartype._util.text.utiltextlabel import (
    label_callable,
    label_type,
)
from collections.abc import Callable

# ....................{ PREFIXERS ~ object                 }....................
#FIXME: Unit test this prefixer up with respect to classes, please.
def prefix_object(obj: object, **kwargs) -> str:
    '''
    Human-readable label describing the passed arbitrary object suffixed by
    delimiting whitespace.

    Parameters
    ----------
    obj : object
        Object to be labelled.

    All remaining parameters are passed as is to the lower-level
    :func:`.label_object` function.

    Returns
    -------
    str
        Human-readable label describing this object.
    '''

    # Avoid circular import dependencies.
    from beartype._util.text.utiltextlabel import label_object

    # Return the label describing this object suffixed by delimiting whitespace.
    return f'{label_object(obj, **kwargs)} '

# ....................{ PREFIXERS : callable : name        }....................
def prefix_callable_pith(
    # Mandatory parameters.
    func: Callable,
    pith_name: str,

    # Optional parameters.
    is_color: BoolTristate = False,
) -> str:
    '''
    Human-readable label describing either the parameter with the passed name
    *or* return value if this name is ``"return"`` of the passed **beartypeable
    callable** (i.e., callable wrapped by the :func:`beartype.beartype`
    decorator with a wrapper function type-checking that callable) suffixed by
    delimiting whitespace.

    Parameters
    ----------
    func : Callable
        Decorated callable to be labelled.
    pith_name : str
        Name of the parameter or return value of this callable to be labelled.
    is_color : BoolTristate, optional
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.

    Returns
    -------
    str
        Human-readable label describing either the name of this parameter *or*
        this return value.
    '''
    assert isinstance(pith_name, str), f'{repr(pith_name)} not string.'

    # Return a human-readable label describing either...
    return (
        # If this name is "return", the return value of this callable.
        prefix_callable_return(func=func, is_color=is_color)
        if pith_name == ARG_NAME_RETURN else
        # Else, the parameter with this name of this callable.
        prefix_callable_arg_name(
            func=func, arg_name=pith_name, is_color=is_color)
    )


def prefix_callable_arg_name(
    # Mandatory parameters.
    func: Callable,
    arg_name: str,

    # Optional parameters.
    is_color: BoolTristate = False,
) -> str:
    '''
    Human-readable label describing the parameter with the passed name of the
    passed **decorated callable** (i.e., callable wrapped by the
    :func:`beartype.beartype` decorator with a wrapper function type-checking
    that callable) suffixed by delimiting whitespace.

    Parameters
    ----------
    func : Callable
        Decorated callable to be labelled.
    arg_name : str
        Name of the parameter of this callable to be labelled.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.

    Returns
    -------
    str
        Human-readable label describing this parameter's name.
    '''
    assert isinstance(arg_name, str), f'{repr(arg_name)} not string.'

    # Avoid circular import dependencies.
    from beartype._util.text.utiltextansi import color_arg_name

    # Double-quote this argument name.
    arg_name = f'"{arg_name}"'

    # Create and return this label.
    return (
        f'{prefix_object(obj=func, is_color=is_color)}'
        f'parameter {color_arg_name(text=arg_name, is_color=is_color)} '
    )


def prefix_callable_return(
    # Mandatory parameters.
    func: Callable,

    # Optional parameters.
    is_color: BoolTristate = False,
) -> str:
    '''
    Human-readable label describing the return of the passed **decorated
    callable** (i.e., callable wrapped by the :func:`beartype.beartype`
    decorator with a wrapper function type-checking that callable) suffixed by
    delimiting whitespace.

    Parameters
    ----------
    func : Callable
        Decorated callable to be labelled.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.

    Returns
    -------
    str
        Human-readable label describing this return.
    '''

    # Create and return this label.
    return f'{prefix_object(obj=func, is_color=is_color)}return '

# ....................{ PREFIXERS : callable : value       }....................
def prefix_callable_arg_value(
    # Mandatory parameters.
    func: Callable,
    arg_name: str,
    arg_value: object,

    # Optional parameters.
    is_color: BoolTristate = False,
) -> str:
    '''
    Human-readable label describing the parameter with the passed name and
    trimmed value of the passed **decorated callable** (i.e., callable wrapped
    by the :func:`beartype.beartype` decorator with a wrapper function
    type-checking that callable) suffixed by delimiting whitespace.

    Parameters
    ----------
    func : Callable
        Decorated callable to be labelled.
    arg_name : str
        Name of the parameter of this callable to be labelled.
    arg_value : object
        Value of the parameter of this callable to be labelled.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.

    Returns
    -------
    str
        Human-readable label describing this parameter's name and value.
    '''
    assert isinstance(arg_name, str), f'{repr(arg_name)} not string.'

    # Avoid circular import dependencies.
    #
    # Note that this function differs enough from the comparable
    # prefix_callable_arg_name() function to warrant a distinct implementation.
    from beartype._util.text.utiltextansi import color_arg_name

    # Create and return this label.
    return (
        f'{prefix_object(obj=func, is_color=is_color)}'
        f'parameter {color_arg_name(text=arg_name, is_color=is_color)}='
        f'{prefix_pith_value(pith=arg_value, is_color=is_color)}'
    )


def prefix_callable_return_value(
    # Mandatory parameters.
    func: Callable,
    return_value: object,

    # Optional parameters.
    is_color: BoolTristate = False,
) -> str:
    '''
    Human-readable label describing the passed trimmed return value of the
    passed **decorated callable** (i.e., callable wrapped by the
    :func:`beartype.beartype` decorator with a wrapper function type-checking
    that callable) suffixed by delimiting whitespace.

    Parameters
    ----------
    func : Callable
        Decorated callable to be labelled.
    return_value : object
        Value returned by this callable to be labelled.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.

    Returns
    -------
    str
        Human-readable label describing this return value.
    '''

    # Create and return this label.
    return (
        f'{prefix_callable_return(func=func, is_color=is_color)}'
        f'{prefix_pith_value(pith=return_value, is_color=is_color)}'
    )

# ....................{ PREFIXERS ~ pith                   }....................
def prefix_pith_type(
    # Mandatory parameters.
    pith: object,

    # Optional parameters.
    is_color: BoolTristate = False,
) -> str:
    '''
    Human-readable label describing the passed type of the **current pith**
    (i.e., arbitrary object violating the current type check) suffixed by
    delimiting whitespace.

    Parameters
    ----------
    pith : object
        Arbitrary object violating the current type check.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.

    Returns
    -------
    str
        Human-readable label describing this pith type.
    '''

    # Avoid circular import dependencies.
    from beartype._util.text.utiltextansi import color_type
    from beartype._util.text.utiltextlabel import label_object_type

    # To boldly go where no one-liner has gone before.
    return color_type(text=f'{label_object_type(pith)} ', is_color=is_color)


def prefix_pith_value(
    # Mandatory parameters.
    pith: object,

    # Optional parameters.
    is_color: BoolTristate = False,
) -> str:
    '''
    Human-readable label describing the passed value of the **current pith**
    (i.e., arbitrary object violating the current type check) suffixed by
    delimiting whitespace.

    Parameters
    ----------
    pith : object
        Arbitrary object violating the current type check.
    is_color : BoolTristate
        Tri-state colouring boolean governing ANSI usage. See the
        :attr:`beartype.BeartypeConf.is_color` attribute for further details.
        Defaults to :data:`False`.

    Returns
    -------
    str
        Human-readable label describing this pith value.
    '''

    # Avoid circular import dependencies.
    from beartype._util.text.utiltextlabel import label_pith_value

    # Create and return this label.
    return f'{label_pith_value(pith=pith, is_color=is_color)} '
