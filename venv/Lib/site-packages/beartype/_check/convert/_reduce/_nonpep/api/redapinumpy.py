#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **PEP-noncompliant NumPy type hint reducers** (i.e., low-level
callables converting higher-level type hints defined by the third-party
:mod:`numpy` package that do *not* comply with any specific PEP but are
nonetheless shallowly supported by :mod:`beartype` to lower-level type hints
more readily consumable by :mod:`beartype`).

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
from beartype.roar import BeartypeDecorHintNonpepNumpyException
from beartype.typing import (
    Annotated,
    Any,
)
from beartype._data.typing.datatypingport import Hint
from beartype._util.api.external.utilnumpy import (
    get_numpy_dtype_type_abcs,
    make_numpy_dtype,
)
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.hint.pep.utilpepget import get_hint_pep_args
from beartype._util.utilobject import is_object_hashable

# ....................{ REDUCERS                           }....................
@callable_cached
def reduce_hint_numpy_ndarray(hint: Hint, exception_prefix: str) -> Hint:
    '''
    Reduce the passed **PEP-noncompliant typed NumPy array** (i.e.,
    subscription of the third-party :attr:`numpy.typing.NDArray` type hint
    factory) to the equivalent PEP-compliant beartype validator validating
    arbitrary objects be instances of that array type -- which has the
    substantial merit of already being well-supported, well-tested, and
    well-known to generate optimally efficient type-checking by the
    :func:`beartype.beartype` decorator.

    Technically, beartype could instead explicitly handle typed NumPy arrays
    throughout the codebase. Of course, doing so would yield *no* tangible
    benefits while imposing a considerable maintenance burden.

    This reducer is memoized for efficiency.

    Parameters
    ----------
    hint : Hint
        PEP-noncompliant typed NumPy array to be reduced.
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    Returns
    -------
    Hint
        This PEP-noncompliant typed NumPy array reduced to a PEP-compliant type
        hint supported by :mod:`beartype`.

    Raises
    ------
    BeartypeDecorHintNonpepNumpyException
        If this hint is a typed NumPy array but either:

        * *Not* subscripted by exactly two arguments.
        * Subscripted by exactly two arguments but whose second argument is
          neither:

          * A **NumPy data type** (i.e., :class:`numpy.dtype` instance).
          * An object coercible into a NumPy data type by passing to the
            :meth:`numpy.dtype.__init__` method.
    '''

    # ..................{ IMPORTS                            }..................
    # Defer heavyweight imports until *AFTER* validating this hint to be a typed
    # NumPy array. Why? Because these imports are *ONLY* safely importable if
    # this hint is a typed NumPy array. Why? Because instantiating this hint
    # required these imports. QED.
    #
    # Note that third-party packages should typically *ONLY* be imported via
    # utility functions raising human-readable exceptions when those packages
    # are either uninstalled or unimportable. In this case, however, NumPy will
    # almost *ALWAYS* be importable. Why? Because this hint was externally
    # instantiated by the user by first importing the "numpy.typing.NDArray"
    # attribute passed to this getter.
    from beartype.vale import (
        IsAttr,
        IsEqual,
        IsSubclass,
    )
    from numpy import ndarray  # pyright: ignore
    from numpy.typing import NDArray  # type: ignore[attr-defined]

    #FIXME: Consider submitting an upstream issue about this. We don't
    #particularly feel like arguing tonight, because that's a lonely hill.

    # If this hint is the unsubscripted "NDArray" type hint, this hint
    # permissively matches *ALL* NumPy arrays rather than strictly matching
    # *ONLY* appropriately typed NumPy arrays. In this case, reduce this hint
    # to the untyped "numpy.ndarray" class.
    #
    # Note the similar test matching the subscripted "NDArray[Any]" hint below.
    # Moreover, note this test *CANNOT* be performed elsewhere (e.g., by
    # adding "HintSignNumpyArray" to the "HINT_SIGNS_ORIGIN_ISINSTANCEABLE"
    # frozen set of all signs whose unsubscripted type hint factories are
    # shallowly type-checkable). Why? Because the "NDArray" type hint factory
    # violates type hinting standards. Specifically, this factory implicitly
    # subscripts *AND* parametrizes itself with the "numpy.ScalarType" type
    # variable bounded above by the "numpy.generic" abstract base class for
    # NumPy scalars.
    #
    # We have *NO* idea why NumPy does this. This implicit behaviour is
    # semantically lossy rather than lossless and thus arguably constitutes an
    # upstream bug. Why? Because this behaviour violates:
    # * The NumPy API. The "NDArray" type hint factory is subscriptable by more
    #   than merely NumPy scalar types. Ergo, "NDArray" is semantically
    #   inaccurate!
    # * PEP 484, which explicitly standardizes an equivalence between
    #   unsubscripted type hint factories and the same factories subscripted by
    #   the "typing.Any" singleton. However, "NDArray" is *MUCH* semantically
    #   narrower than and thus *NOT* equivalent to "NDArray[Any]"!
    #
    # Of course, upstream is unlikely to see it that way. We're *NOT* dying on
    # an argumentative hill about semantics. Upstream makes the rules. Do it.
    if hint is NDArray:
        return ndarray
    # Else, this hint is *NOT* the unsubscripted "NDArray" type hint.

    # ..................{ CONSTANTS                          }..................
    # Frozen set of all NumPy scalar data type abstract base classes (ABCs).
    NUMPY_DTYPE_TYPE_ABCS = get_numpy_dtype_type_abcs()

    # ..................{ ARGS                               }..................
    # Objects subscripting this hint if any *OR* the empty tuple otherwise.
    hint_args = get_hint_pep_args(hint)

    # If this hint was *NOT* subscripted by exactly two arguments, this hint is
    # malformed as a typed NumPy array. In this case, raise an exception.
    if len(hint_args) != 2:
        raise BeartypeDecorHintNonpepNumpyException(
            f'{exception_prefix}typed NumPy array {repr(hint)} '
            f'not subscripted by exactly two arguments.'
        )
    # Else, this hint was subscripted by exactly two arguments.

    # Data type subhint subscripting this hint. Yes, the "numpy.typing.NDArray"
    # type hint bizarrely encapsulates its data type argument into a private
    # "numpy._DTypeMeta" type subhint. Why? We have absolutely no idea, but we
    # have no say in the matter. NumPy, you're on notice for stupidity.
    hint_dtype_subhint = hint_args[1]

    # Objects subscripting this subhint if any *OR* the empty tuple otherwise.
    hint_dtype_subhint_args = get_hint_pep_args(hint_dtype_subhint)

    # If this hint was *NOT* subscripted by exactly one argument, this subhint
    # is malformed as a data type subhint. In this case, raise an exception.
    if len(hint_dtype_subhint_args) != 1:
        raise BeartypeDecorHintNonpepNumpyException(
            f'{exception_prefix}typed NumPy array {repr(hint)} '
            f'data type subhint {repr(hint_dtype_subhint)} '
            f'not subscripted by exactly one argument.'
        )
    # Else, this subhint was subscripted by exactly one argument.

    # Data type-like object subscripting this subhint. Look, just do it.
    hint_dtype_like = hint_dtype_subhint_args[0]

    # If this dtype-like is "typing.Any", this hint permissively matches *ALL*
    # NumPy arrays rather than strictly matching *ONLY* appropriately typed
    # NumPy arrays. In this case, reduce this hint to the untyped
    # "numpy.ndarray" class.
    #
    # Note the similar test matching the unsubscripted "NDArray" hint above.
    if hint_dtype_like is Any:
        return ndarray  # pyright: ignore
    # Else, this dtype-like is *NOT* "typing.Any".

    # ..................{ REDUCTION                          }..................
    # Equivalent nested beartype validator reduced from this hint.
    hint_validator = None  # type: ignore[assignment]

    # If...
    if (
        # This dtype-like is hashable *AND*...
        is_object_hashable(hint_dtype_like) and
        # This dtype-like is a scalar data type abstract base class (ABC)...
        hint_dtype_like in NUMPY_DTYPE_TYPE_ABCS
    ):
        # Then avoid attempting to coerce this possibly non-dtype into a proper
        # dtype. Although NumPy previously silently coerced these ABCs into
        # dtypes (e.g., from "numpy.floating" to "numpy.float64"), recent
        # versions of NumPy now emit non-fatal deprecation warnings on doing so
        # and will presumably raise fatal exceptions in the near future:
        #     >>> import numpy as np
        #     >>> np.dtype(np.floating)
        #     DeprecationWarning: Converting `np.inexact` or `np.floating` to a
        #     dtype is deprecated. The current result is `float64` which is not
        #     strictly correct.
        #
        # Instead, we follow mypy's lead. Presumably defined somewhere in the
        # incredibly complex innards of NumPy's mypy plugin (which we admittedly
        # failed to grep despite ~~wasting~~ "investing" several hours in doing
        # so), mypy treats subscriptions of the "numpy.typing.NDArray" type hint
        # factory by one of these ABCs (rather than either a scalar or proper
        # dtype) as a type inheritance (rather than object equality) relation.
        # Since this is sensible, we do too.

        # Equivalent nested beartype validator reduced from this hint.
        hint_validator = (
            IsAttr['dtype', IsAttr['type', IsSubclass[hint_dtype_like]]])
    # Else, this dtype-like is either unhashable *OR* not such an ABC. In this
    # case...
    else:
        # Proper dtype coerced from this possibly non-dtype.
        hint_dtype = make_numpy_dtype(
            dtype=hint_dtype_like,
            exception_prefix=exception_prefix,
            exception_cls=BeartypeDecorHintNonpepNumpyException,
        )

        # Equivalent nested beartype validator reduced from this hint.
        hint_validator = IsAttr['dtype', IsEqual[hint_dtype]]

    # Replace the usually less readable representation of this validator with
    # the usually more readable representation of this hint (e.g.,
    # "numpy.ndarray[typing.Any, numpy.float64]").
    hint_validator.get_repr = repr(hint)

    # Return this validator annotating the NumPy array type.
    return Annotated[ndarray, hint_validator]  # type: ignore[return-value]  # pyright: ignore
