#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **callable getters** (i.e., utility functions dynamically
querying and retrieving various properties of passed callables).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilCallableException
from beartype.typing import (
    Callable,
    Optional,
)
from beartype._cave._cavefast import MethodBoundInstanceOrClassType
from beartype._data.typing.datatyping import (
    Pep649HintableAnnotations,
    TypeException,
)

# ....................{ GETTERS ~ descriptors              }....................
#FIXME: Unit test us up, please.
#FIXME: Docstring us up, please.
def get_func_boundmethod_self(
    # Mandatory parameters.
    func: MethodBoundInstanceOrClassType,

    # Optional parameters.
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
) -> object:
    '''
    Instance object to which the passed **C-based bound instance method
    descriptor** (i.e., callable implicitly instantiated and assigned on the
    instantiation of an object whose class declares an instance function (whose
    first parameter is typically named ``self``) as an instance variable of that
    object such that that callable unconditionally passes that object as the
    value of that first parameter on all calls to that callable) was bound as an
    instance attribute at instantiation time.

    Parameters
    ----------
    func : object
        Bound method descriptor to be inspected.
    exception_cls : TypeException, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`._BeartypeUtilCallableWrapperException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Returns
    -------
    object
        Instance object to which this bound method descriptor is bound to.

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
    return func.__self__
