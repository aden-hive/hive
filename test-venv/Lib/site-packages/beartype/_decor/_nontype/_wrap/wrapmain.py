#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype decorator code generator.**

This private submodule dynamically generates both the signature and body of the
wrapper function type-checking all annotated parameters and return value of the
the callable currently being decorated by the :func:`beartype.beartype`
decorator in a general-purpose manner. For genericity, this relatively
high-level submodule implements *no* support for annotation-based PEPs (e.g.,
:pep:`484`); other lower-level submodules do so instead.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
# All "FIXME:" comments for this submodule reside in this package's "__init__"
# submodule to improve maintainability and readability here.

# ....................{ IMPORTS                            }....................
from beartype._check.metadata.metacheck import BeartypeCheckMeta
from beartype._check.metadata.metadecor import BeartypeDecorMeta
from beartype._check.signature.sigmake import make_func_signature
from beartype._data.code.datacodefunc import CODE_SIGNATURE
from beartype._data.code.datacodename import (
    ARG_NAME_CHECK_META,
    ARG_NAME_FUNC,
)
from beartype._decor._nontype._wrap._wrapargs import (
    code_check_args as _code_check_args)
from beartype._decor._nontype._wrap._wrapreturn import (
    code_check_return as _code_check_return)

# ....................{ GENERATORS                         }....................
def generate_code(decor_meta: BeartypeDecorMeta) -> str:
    '''
    Generate a Python code snippet dynamically defining the wrapper function
    type-checking the passed decorated callable.

    This high-level function implements this decorator's core type-checking,
    converting all unignorable PEP-compliant type hints annotating this
    callable into pure-Python code type-checking the corresponding parameters
    and return values of each call to this callable.

    Parameters
    ----------
    decor_meta : BeartypeDecorMeta
        Decorated callable to be type-checked.

    Returns
    -------
    str
        Generated function wrapper code. Specifically, either:

        * If the decorated callable requires *no* type-checking (e.g., due to
          all type hints annotating this callable being ignorable), the empty
          string. Note this edge case is distinct from a related edge case at
          the head of the :func:`beartype.beartype` decorator reducing to a noop
          for unannotated callables. By compare, this boolean is ``True`` only
          for callables annotated with **ignorable type hints** (i.e.,
          :class:`object`, :class:`beartype.cave.AnyType`, :class:`typing.Any`):
          e.g.,

          .. code-block:: python

             >>> from beartype.cave import AnyType
             >>> from typing import Any
             >>> def muh_func(
             ...     muh_param1: AnyType, muh_param2: object) -> Any: pass
             >>> muh_func is beartype(muh_func)
             True

        * Else, a code snippet defining the wrapper function type-checking the
          decorated callable, including (in order):

          * A signature declaring this wrapper, accepting both beartype-agnostic
            and -specific parameters. The latter include:

            * A private ``__beartype_func`` parameter initialized to the
              decorated callable. In theory, this callable should be accessible
              as a closure-style local in this wrapper. For unknown reasons
              (presumably, a subtle bug in the exec() builtin), this is *not*
              the case. Instead, a closure-style local must be simulated by
              passing this callable at function definition time as the default
              value of an arbitrary parameter. To ensure this default is *not*
              overwritten by a function accepting a parameter of the same name,
              this unlikely edge case is guarded against elsewhere.

          * Statements type checking parameters passed to the decorated
            callable.
          * A call to the decorated callable.
          * A statement type checking the value returned by the decorated
            callable.

    Raises
    ------
    BeartypeDecorParamNameException
        If the name of any parameter declared on this callable is prefixed by
        the reserved substring ``__bear``.
    BeartypeDecorHintNonpepException
        If any type hint annotating any parameter of this callable is neither:

        * **PEP-compliant** (i.e., :mod:`beartype`-agnostic hint compliant with
          annotation-centric PEPs).
        * **PEP-noncompliant** (i.e., :mod:`beartype`-specific type hint *not*
          compliant with annotation-centric PEPs)).
    _BeartypeUtilMappingException
        If generated code type-checking any pair of parameters and returns
        erroneously declares an optional private beartype-specific parameter of
        the same name with differing default value. Since this should *never*
        happen, a private non-human-readable exception is raised in this case.
    '''

    # ....................{ ARGS                           }....................
    # Python code snippet type-checking all callable parameters if one or more
    # such parameters are annotated with unignorable type hints *OR* the empty
    # string otherwise.
    code_check_params = _code_check_args(decor_meta)

    # ....................{ (RETURN|YIELD)                 }....................
    # Python code snippet type-checking the callable return if this return is
    # annotated with an unignorable type hint *OR* the empty string otherwise.
    code_check_return = _code_check_return(decor_meta)

    # If the callable return requires *NO* type-checking...
    #
    # Note that this branch *CANNOT* be embedded in the prior call to the
    # code_check_return() function, as doing so would prevent us from
    # efficiently reducing to a noop here.
    if not code_check_return:
        # If all callable parameters also require *NO* type-checking, this
        # callable itself requires *NO* type-checking. In this case, return the
        # empty string instructing the parent @beartype decorator to reduce to a
        # noop (i.e., the identity decorator returning this callable as is).
        if not code_check_params:
            return ''
        # Else, one or more callable parameters require type-checking.

        # Python code snippet calling this callable unchecked, returning the
        # value returned by this callable from this wrapper.
        code_check_return = decor_meta.func_wrapper_code_return_unchecked
    # Else, the callable return requires type-checking.

    # ....................{ SCOPE                          }....................
    # Dictionary mapping from the name to value of each attribute referenced in
    # the signature of this wrapper function, localized merely for readability.
    func_scope = decor_meta.func_wrapper_scope

    # Expose private beartype type-checking call metadata (i.e.,
    # "beartype"-specific hidden parameter whose default value is the
    # "BeartypeCheckMeta" dataclass instance encapsulating *ALL* metadata
    # required by each call to this wrapper function) to this wrapper function.
    # Doing so dramatically simplifies calls to the get_func_pith_violation()
    # getter inside the body of this wrapper function by enabling this metadata
    # to be passed as a single unified parameter (rather than individually as
    # multiple distinct parameters).
    func_scope[ARG_NAME_CHECK_META] = BeartypeCheckMeta.make_from_decor_meta(
        decor_meta)

    # Expose the callable currently being decorated to this wrapper function.
    # Technically, doing so is merely an optimization; this callable is also
    # accessible as the "ARG_NAME_CHECK_META.func" instance variable in the body
    # of this wrapper function. Pragmatically, doing so is a trivial
    # optimization that could yield non-trivial benefits (e.g., if this wrapper
    # function is frequently called).
    func_scope[ARG_NAME_FUNC] = decor_meta.func_wrappee

    # ....................{ SIGNATURE                      }....................
    # Python code snippet declaring the signature of this type-checking wrapper
    # function, deferred for efficiency until *AFTER* confirming that a wrapper
    # function is even required.
    code_signature = make_func_signature(
        func_name=decor_meta.func_wrapper_name,
        func_scope=func_scope,
        code_signature_format=CODE_SIGNATURE,
        code_signature_prefix=decor_meta.func_wrapper_code_signature_prefix,
        conf=decor_meta.conf,
    )

    # ....................{ TYPE-CHECK                     }....................
    # Return Python code defining the wrapper type-checking this callable.
    #
    # While there exist numerous alternatives to string formatting (e.g.,
    # appending to a list or bytearray before joining the items of that
    # iterable into a string), these alternatives are either:
    # * Slower, as in the case of a list (e.g., due to the high up-front cost
    #   of list construction).
    # * Cumbersome, as in the case of a bytearray.
    #
    # Since string concatenation is heavily optimized by the official CPython
    # interpreter, the simplest approach is the most ideal. KISS, bro.
    return f'{code_signature}{code_check_params}{code_check_return}'
