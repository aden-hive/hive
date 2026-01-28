#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **NumPy utilities** (i.e., low-level callables handling the
third-party :mod:`numpy` package).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: The top-level of this module should avoid importing from third-party
# optional libraries, both because those libraries cannot be guaranteed to be
# either installed or importable here *AND* because those imports are likely to
# be computationally expensive, particularly for imports transitively importing
# C extensions (e.g., anything from NumPy or SciPy).
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
from beartype.roar import BeartypeLibraryNumpyException
from beartype._data.typing.datatyping import (
    DictStrToType,
    FrozenSetTypes,
    TypeException,
)
from beartype._util.cache.utilcachecall import callable_cached
from string import digits

# ....................{ GETTERS                            }....................
#FIXME: File an upstream NumPy issue politely requesting they publicize either:
#* An equivalent container listing these types.
#* Documentation officially listing these types.
@callable_cached
def get_numpy_dtype_type_abcs() -> FrozenSetTypes:
    '''
    Frozen set of all **NumPy scalar data type abstract base classes** (i.e.,
    superclasses of all concrete NumPy scalar data types (e.g.,
    :class:`numpy.int64`, :class:`numpy.float32`)).

    This getter is memoized for efficiency. To defer the substantial cost of
    importing from NumPy, the frozen set memoized by this getter is
    intentionally deferred to call time rather than globalized as a constant.

    Caveats
    -------
    **NumPy currently provides no official container listing these classes.**
    Likewise, NumPy documentation provides no official list of these classes.
    Ergo, this getter. This has the dim advantage of working but the profound
    disadvantage of inviting inevitable discrepancies between the
    :mod:`beartype` and :mod:`numpy` codebases. So it goes.
    '''

    # Avoid third-party import dependencies.
    from numpy import (  # pyright: ignore
        character,
        complexfloating,
        flexible,
        floating,
        generic,
        inexact,
        integer,
        number,
        signedinteger,
        unsignedinteger,
    )

    # Create, return, and cache a frozen set listing these ABCs.
    return frozenset((
        character,
        complexfloating,
        flexible,
        floating,
        generic,
        inexact,
        integer,
        number,
        signedinteger,
        unsignedinteger,
    ))


#FIXME: Unit test us up, please.
@callable_cached
def get_numpy_dtype_name_sanitized_to_type_reduced() -> DictStrToType:
    '''
    Dictionary mapping from each **sanitized NumPy data type name** (i.e.,
    string value of the :attr:`numpy.dtype.name` instance variable after being
    translated by the :data:`._TRANSLATION_TABLE_DTYPE_NAME_SANITIZER`
    translation table) to the corresponding **reduced type** (i.e.,
    NumPy-agnostic builtin type if a such type corresponds to this data type
    *or* the direct NumPy-specific abstract base class (ABC) of this data type
    otherwise).

    This getter is memoized for efficiency. To defer the substantial cost of
    importing from NumPy, the frozen set memoized by this getter is
    intentionally deferred to call time rather than globalized as a constant.
    '''

    # Defer heavyweight imports.
    from numpy import unsignedinteger  # pyright: ignore

    # Dictionary mapping from each sanitized NumPy data type name to the
    # corresponding reduced type.
    #
    # Note that the family of "numpy.uint*" data types are the *ONLY* data types
    # lacking a corresponding builtin type, interestingly. Since Python itself
    # has no concept of an "unsigned integer" the NumPy-specific
    # "unsignedinteger" ABC is preferred instead.
    _DTYPE_NAME_SANITIZED_TO_BUILTIN_TYPE = {
        'bool': bool,
        'bytes': bytes,
        'complex': complex,
        'float': float,
        'int': int,
        'uint': unsignedinteger,
        'str': str,
        'void': memoryview,
    }

    # Return this dictionary.
    return _DTYPE_NAME_SANITIZED_TO_BUILTIN_TYPE

# ....................{ REDUCERS                           }....................
#FIXME: Unit test us up, please.
def reduce_numpy_dtype(
    # Mandatory parameters.
    dtype: object,

    # Optional parameters.
    exception_prefix: str = '',
    exception_cls: TypeException = BeartypeLibraryNumpyException,
) -> type:
    '''
    Reduce the passed fine-grained **NumPy data type** (i.e., third-party
    :class:`numpy.dtype` object like :obj:`numpy.complex128`) to a
    coarse-grained **NumPy-agnostic builtin type** (e.g., :class:`complex`) if
    possible *or* simply return this data type as is otherwise (i.e., if this
    data type *cannot* be reduced to a builtin type).

    Parameters
    ----------
    dtype : object
        NumPy data type to be reduced.
    exception_prefix : str, optional
        Human-readable label prefixing raised exception messages. Defaults to
        the empty string.
    exception_cls : Type[Exception], optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`.BeartypeLibraryNumpyException`.

    Returns
    -------
    type
        Either:

        * If this data type is reducible to a NumPy-agnostic builtin type, that
          builtin type.
        * Else, this data type as is.

    Raises
    ------
    exception_cls
        If this NumPy data type is *not* actually a NumPy data type.
    '''

    # Proper dtype coerced from this possibly non-dtype.
    dtype = make_numpy_dtype(
        dtype=dtype,
        exception_prefix=exception_prefix,
        exception_cls=exception_cls,
    )

    # Sanitized name of this dtype, efficiently truncating *ALL* digits and
    # underscores from this name (e.g., sanitizing "complex128" to "complex").
    dtype_name_sanitized = dtype.name.translate(  # type: ignore[attr-defined]
        _TRANSLATION_TABLE_DTYPE_NAME_SANITIZER) 

    # Dictionary mapping from each sanitized NumPy data type name to the
    # corresponding reduced type (e.g., from the string "complex" to the
    # builtin type "complex").
    DTYPE_NAME_SANITIZED_TO_TYPE_REDUCED = (
        get_numpy_dtype_name_sanitized_to_type_reduced())

    # Possibly NumPy-agnostic builtin type reduced from this dtype if this dtype
    # is reducible to such a type *OR* this dtype as is otherwise.
    type_reduced = DTYPE_NAME_SANITIZED_TO_TYPE_REDUCED.get(
        dtype_name_sanitized, dtype)

    # Return this reduced type.
    return type_reduced

# ....................{ FACTORIES                          }....................
#FIXME: Unit test us up, please.
def make_numpy_dtype(
    # Mandatory parameters.
    dtype: object,

    # Optional parameters.
    exception_prefix: str = '',
    exception_cls: TypeException = BeartypeLibraryNumpyException,
) -> type:
    '''
    **NumPy data type** (i.e., third-party :class:`numpy.dtype` instance)
    coerced from the passed arbitrary object.

    This factory is effectively memoized due to the underlying
    :meth:`numpy.dtype.__new__` constructor already being memoized.

    Parameters
    ----------
    dtype : object
        Object to be coerced into a NumPy data type.
    exception_prefix : str, optional
        Human-readable label prefixing raised exception messages. Defaults to
        the empty string.
    exception_cls : Type[Exception], optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`.BeartypeLibraryNumpyException`.

    Parameters
    ----------
    numpy.dtype
        NumPy data type coerced from this object.

    Raises
    ------
    exception_cls
        If this object is *not* coercible into a NumPy data type.
    '''
    assert isinstance(exception_prefix, str), (
        f'{repr(exception_prefix)} not string.')
    assert isinstance(exception_cls, type), (
        f'{repr(exception_cls)} not exception type.')

    # Defer heavyweight imports.
    from numpy import dtype as numpy_dtype  # pyright: ignore

    # Attempt to coerce this possibly non-dtype into a proper dtype.
    #
    # Note that the dtype.__init__() constructor efficiently maps non-dtype
    # scalar types (e.g., "numpy.float64") to corresponding cached dtypes:
    #     >>> import numpy
    #     >>> i4_dtype = numpy.dtype('>i4')
    #     >>> numpy.dtype(i4_dtype) is numpy.dtype(i4_dtype)
    #     True
    #     >>> numpy.dtype(numpy.float64) is numpy.dtype(numpy.float64)
    #     True
    #
    # Ergo, the call to this constructor here is guaranteed to already
    # effectively be memoized.
    try:
        dtype = numpy_dtype(dtype)  # type: ignore[call-overload]
    # If this object is *NOT* coercible into a dtype, raise an exception. This
    # is essential. As of NumPy 1.21.0, "numpy.typing.NDArray" fails to validate
    # its subscripted argument to actually be a dtype: e.g.,
    #     >>> from numpy.typing import NDArray
    #     >>> NDArray['wut']
    #     numpy.ndarray[typing.Any, numpy.dtype['wut']]  # <-- you kidding me?
    except Exception as exception:
        raise exception_cls(
            f'{exception_prefix}NumPy data type {repr(dtype)} invalid '
            f'(i.e., neither data type nor coercible into data type).'
        ) from exception

    # Return this dtype.
    return dtype  # type: ignore[return-value]

# ....................{ PRIVATE ~ constants                }....................
_TRANSLATION_TABLE_DTYPE_NAME_SANITIZER = str.maketrans('', '', digits + '_')
'''
**Translation table** (i.e., object suitable for passing to the standard
:meth:`str.translate` method as the sole parameter) sanitizing arbitrary **NumPy
data type** (i.e., third-party :class:`numpy.dtype` object) names.

This table strips all ignorable trailing digits and underscores from NumPy data
type names, efficiently reducing the names of NumPy data types (e.g.,
``"complex128"``, ``"str_"``) to the corresponding names of builtin types (e.g.,
``"complex"``, ``"str"``).

See Also
--------
https://stackoverflow.com/a/12856384/2809027
    StackOverflow answer strongly inspiring this implementation.
'''
