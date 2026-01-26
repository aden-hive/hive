#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype Inferential Type-hint Engine (BITE) third-party type hint inferrers**
(i.e., lower-level functions dynamically inferring subscripted type hints
describing non-standard popular third-party objects such as NumPy arrays and
PyTorch tensors).
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Annotated,
    Callable,
    Dict,
    Optional,
)
from beartype._util.api.external.utilnumpy import reduce_numpy_dtype
from beartype._util.module.utilmodget import get_object_module_name_or_none

# ....................{ INFERERS                           }....................
#FIXME: Unit test us up, please.
def infer_hint_thirdparty(obj: object, **kwargs) -> Optional[object]:
    '''
    **Third-party type hint** (i.e., possibly subscripted type hint factory
    published by a non-standard popular third-party package) recursively
    validating the passed object (including *all* items transitively reachable
    from this object) if this object derives from such a package *or*
    :data:`None` otherwise (i.e., if this object derives from *no* such
    package).

    This function *cannot* be memoized, due to necessarily accepting the
    ``__beartype_obj_ids_seen__`` parameter unique to each call to the parent
    :func:`beartype.bite.infer_hint` function. Moreover, this function exhibits
    worst-case constant time complexity :math:`O(1)`; memoization is irrelevant.

    Parameters
    ----------
    obj : object
        Object to infer a type hint from.

    All remaining keyword parameters are silently ignored.

    Returns
    -------
    Optional[object]
        Either:

        * If this object derives from a non-standard popular third-party
          package, a possibly subscripted type hint factory published by that
          package validating this object.
        * Else, :data:`None`.
    '''

    # Type of this object.
    obj_type = obj.__class__

    # Hint to be returned, defaulting to "None" as a fallback.
    hint: object = None

    # Fully-qualified name of the package declaring this type if any *OR* "None"
    # otherwise (e.g., if this type is dynamically declared in-memory and thus
    # resides outside any package structure).
    obj_type_package_name = get_object_module_name_or_none(obj_type)

    # If a package declares this type...
    if obj_type_package_name:
        # Dictionary mapping from the unqualified basename of that type to the
        # type hint inferer inferring type hints for this type if this is a
        # non-standard popular third-party type supported by this submodule *OR*
        # "None" otherwise (i.e., if this type is unsupported).
        type_basename_to_inferer = (
            _PACKAGE_NAME_TO_TYPE_BASENAME_TO_INFERER_get(
                obj_type_package_name))

        # If this package is recognized...
        if type_basename_to_inferer is not None:
            # Type hint inferer inferring type hints for this type if this is a
            # non-standard popular third-party type supported by this submodule
            # *OR* "None" otherwise (i.e., if this type is unsupported).
            #
            # Note that, unlike the "__module__" dunder attribute, the
            # "__name__" is effectively required to both exist and be non-empty
            # for all possible types -- even types declared in-memory.
            hint_inferer = type_basename_to_inferer.get(obj_type.__name__)

            # If this type is supported...
            if hint_inferer is not None:
                # Hint inferred by this type hint inferer.
                hint = hint_inferer(obj, **kwargs)
            # Else, this type is unsupported. In this case, fallback to
            # returning "None".
        # Else, this package is recognized. In this case, fallback to returning
        # "None".
    # Else, *NO* package declares this object. In this case, fallback to
    # returning "None".

    # Return this hint.
    return hint

# ....................{ PRIVATE ~ inferers                 }....................
def _infer_hint_thirdparty_numpy_ndarray(obj: object, **kwargs) -> object:
    '''
    **NumPy array type hint** validating the passed NumPy array.

    This function creates and returns a new :pep:`593`-compliant
    :obj:`typing.Annotated` type hint subscripted by (in order):

    * A non-standard :obj:`numpy.typing.NDArray` type hint factory subscripted
      by the **dtype** of the passed NumPy array.
    * A beartype-specific :obj:`beartype.vale.IsAttr` validator validating the
      **dimensionality** (i.e., :attr:`numpy.ndarray.ndim` instance variable) to
      be that of the passed NumPy array.
    '''

    # ....................{ IMPORTS                        }....................
    # Defer package-specific imports.
    from beartype.vale import (
        IsAttr,
        IsEqual,
    )
    from numpy import ndarray  # pyright: ignore
    from numpy.typing import NDArray  # type: ignore[attr-defined]

    # Validate sanity.
    assert isinstance(obj, ndarray), f'{repr(obj)} not NumPy array.'

    # ....................{ DTYPE                          }....................
    # Coarse-grained NumPy-agnostic builtin type (e.g., "int") reduced from the
    # fine-grained NumPy-specific data type of the passed NumPy array (e.g.,
    # "numpy.int64"). Everybody wants the former. Nobody wants the latter.
    numpy_dtype = reduce_numpy_dtype(obj.dtype)  # type: ignore[name-defined]

    # Hint to be returned, defaulting to the "NDArray" type hint factory
    # subscripted by the dtype .
    hint: object = NDArray[numpy_dtype]  # type: ignore[misc,valid-type]

    # ....................{ SHAPE                          }....................
    # Generalize this hint to additionally validate the dimensionality
    # (i.e., number of dimensions equivalent to the length of the
    # "obj.shape" property) to be that of this array.
    hint = Annotated[hint, IsAttr['ndim', IsEqual[obj.ndim]]]  # type: ignore[name-defined]
    # Else, "typing(|_extensions).Annotated" is unimportable. In this case...

    # ....................{ RETURN                         }....................
    # Return this hint.
    return hint

# ....................{ PRIVATE ~ globals                  }....................
_PACKAGE_NAME_TO_TYPE_BASENAME_TO_INFERER: Dict[str, Dict[str, Callable]] = {
    # NumPy.
    'numpy': {
        # NumPy array.
        'ndarray': _infer_hint_thirdparty_numpy_ndarray,
    }
}
'''
Dictionary mapping from the fully-qualified package name of each non-standard
popular third-party type supported by this submodule to a nested dictionary
mapping from the unqualified basename of that type to the type hint inferer
inferring type hints for this type.

This data structure enables efficient constant time :math:`O(1)` lookups of
third-party types *without* requiring inefficient string munging.
'''


_PACKAGE_NAME_TO_TYPE_BASENAME_TO_INFERER_get = (
    _PACKAGE_NAME_TO_TYPE_BASENAME_TO_INFERER.get)
'''
:meth:`dict.get` method bound to the global
:data:`_PACKAGE_NAME_TO_TYPE_BASENAME_TO_INFERER` dictionary for negligible
lookup efficiency.
'''
