#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Public beartype decorator.**

This private submodule defines the core :func:`beartype` decorator, which the
:mod:`beartype.__init__` submodule then imports for importation as the public
:mod:`beartype.beartype` decorator by downstream callers -- completing the
virtuous cycle of code life.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
# All "FIXME:" comments for this submodule reside in this package's "__init__"
# submodule to improve maintainability and readability here.

# ....................{ IMPORTS                            }....................
from beartype._conf.confcommon import BEARTYPE_CONF_DEFAULT
from beartype._conf.confmain import BeartypeConf
from beartype._data.typing.datatyping import (
    BeartypeReturn,
    BeartypeableT,
)
from beartype._util.py.utilpyinterpreter import is_python_optimized
from typing import (
    TYPE_CHECKING,
    Optional,
)

# ....................{ DECORATORS                         }....................
# If the active Python interpreter is optimized either at process-invocation
# time (e.g., by the user passing one or more "-O" command-line options *OR*
# setting the '${PYTHONOPTIMIZE}" environment variable to a positive integer
# when the active Python interpreter was forked) *OR* after process-invocation
# time (e.g., by the user setting the '${PYTHONOPTIMIZE}" environment variable
# to a positive integer in an interactive REPL), then unconditionally disable
# @beartype-based type-checking across the entire codebase by reducing the
# @beartype decorator to the identity decorator.
#
# Note that:
# * Ideally, this would have been implemented at the top rather than bottom of
#   this submodule as a conditional resembling:
#     if __debug__:
#         def beartype(func: CallableTypes) -> CallableTypes:
#             return func
#         return
#
#   Sadly, Python fails to support module-scoped "return" statements. *sigh*
# * The "and not TYPE_CHECKING" condition assists static type-checkers to detect
#   the "real" implementation of the @beartype decorator imported below rather
#   than this optimized placeholder defined here. Since the
#   is_python_optimized() tester returns true when "TYPE_CHECKING" is true, this
#   condition iteratively reduces to the following under static type-checking:
#       if TYPE_CHECKING and not TYPE_CHECKING:
#       if True and not True:
#       if True and False:
#       if False:
if is_python_optimized() and not TYPE_CHECKING:
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Synchronize the signature of this identity decorator with the
    # non-identity decorator imported below.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    def beartype(
        obj: Optional[BeartypeableT] = None,

        # Optional keyword-only parameters.
        *,
        conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
    ) -> BeartypeReturn:
        # If passed an object to be decorated, this decorator is in decoration
        # rather than configuration mode. In this case, silently reduce to a
        # noop by returning this object as is unmodified.
        #
        # Note that this is the common case.
        if obj is not None:
            return obj
        # Else, this decorator was passed *NO* object to be decorated. In this
        # case, this decorator is in configuration rather than decoration mode.

        # Pretend to configure this decorator with this configuration by instead
        # returning the identity decorator -- which trivially returns the passed
        # object unmodified. Doing so ignores this configuration in the
        # optimally efficient manner, thus complying with external user demands
        # for optimization.
        return _beartype_optimized


    def _beartype_optimized(obj: BeartypeableT) -> BeartypeableT:
        '''
        Identity decorator returning the passed **beartypeable** (i.e.,
        pure-Python callable or class) unmodified due to the active Python
        interpreter being **optimized** (e.g., by either the
        ``${PYTHONOPTIMIZE}}`` environment variable being set *or* this
        interpreter being passed one or more ``"-O"`` command-line options).

        Parameters
        ----------
        obj : BeartypeableT
            Beartypeable to be decorated.

        Returns
        -------
        BeartypeableT
            Either:

            * If the passed object is a class, this existing class embellished
              with dynamically generated type-checking.
            * If the passed object is a callable, a new callable wrapping that
              callable with dynamically generated type-checking.

        See Also
        --------
        :func:`beartype.beartype`
            Further details.
        '''

        # Silently reduce to a noop by returning this object as is unmodified.
        return obj
# Else, the active Python interpreter is in a standard runtime state. In this
# case, define the @beartype decorator in the standard way.
else:
    # This is where @beartype *REALLY* lives. Grep here for all the goods.
    from beartype._decor.decorcache import beartype as beartype

# ....................{ DECORATORS ~ doc                   }....................
# Document the @beartype decorator with the same documentation regardless of
# which of the above implementations currently implements that decorator.
beartype.__doc__ = (
    '''
    Decorate the passed **beartypeable** (i.e., pure-Python callable or
    class) with optimal type-checking dynamically generated unique to that
    beartypeable under the passed beartype configuration.

    This decorator supports two distinct (albeit equally efficient) modes
    of operation:

    * **Decoration mode.** The caller activates this mode by passing this
      decorator a type-checkable object via the ``obj`` parameter; this
      decorator then creates and returns a new callable wrapping that object
      with optimal type-checking. Specifically:

      * If this object is a callable, this decorator creates and returns a new
        **runtime type-checker** (i.e., pure-Python function validating all
        parameters and returns of all calls to that callable against all
        PEP-compliant type hints annotating those parameters and returns). The
        type-checker returned by this decorator is:

        * Optimized uniquely for the passed callable.
        * Guaranteed to run in ``O(1)`` constant-time with negligible constant
          factors.
        * Type-check effectively instantaneously.
        * Add effectively no runtime overhead to the passed callable.

      * If the passed object is a class, this decorator iteratively applies
        itself to all annotated methods of this class by dynamically wrapping
        each such method with a runtime type-checker (as described previously).

    * **Configuration mode.** The caller activates this mode by passing this
      decorator a beartype configuration via the ``conf`` parameter; this
      decorator then creates and returns a new beartype decorator enabling that
      configuration. That decorator may then be called (in decoration mode) to
      create and return a new callable wrapping the passed type-checkable
      object with optimal type-checking configured by that configuration.

    If optimizations are enabled by the active Python interpreter (e.g., due to
    option ``-O`` passed to this interpreter), this decorator silently reduces
    to a noop.

    Parameters
    ----------
    obj : Optional[BeartypeableT]
        **Beartypeable** (i.e., pure-Python callable or class) to be decorated.
        Defaults to :data:`None`, in which case this decorator is in
        configuration rather than decoration mode. In configuration mode, this
        decorator creates and returns an efficiently cached private decorator
        that generically applies the passed beartype configuration to any
        beartypeable object passed to that decorator. Look... It just works.
    conf : BeartypeConf, optional
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all settings configuring type-checking for the passed object). Defaults
        to ``BeartypeConf()``, the default :math:`O(1)` constant-time
        configuration.

    Returns
    -------
    BeartypeReturn
        Either:

        * If in decoration mode (i.e., ``obj`` is *not* ``None` while ``conf``
          is :data:`None`) *and*:

          * If ``obj`` is a callable, a new callable wrapping that callable
            with dynamically generated type-checking.
          * If ``obj`` is a class, this existing class embellished with
            dynamically generated type-checking.

        * If in configuration mode (i.e., ``obj`` is :data:`None` while ``conf``
          is *not* :data:`None`), a new beartype decorator enabling this
          configuration.

    Raises
    ------
    BeartypeConfException
        If the passed configuration is *not* actually a configuration (i.e.,
        instance of the :class:`BeartypeConf` class).
    BeartypeDecorHintException
        If any annotation on this callable is neither:

        * A **PEP-compliant type** (i.e., instance or class complying with a
          PEP supported by :mod:`beartype`), including:

          * :pep:`484` types (i.e., instance or class declared by the stdlib
            :mod:`typing` module).

        * A **PEP-noncompliant type** (i.e., instance or class complying with
          :mod:`beartype`-specific semantics rather than a PEP), including:

          * **Fully-qualified forward references** (i.e., strings specified as
            fully-qualified classnames).
          * **Tuple unions** (i.e., tuples containing one or more classes
            and/or forward references).
    BeartypePep563Exception
        If :pep:`563` is active for this callable and evaluating a **postponed
        annotation** (i.e., annotation whose value is a string) on this
        callable raises an exception (e.g., due to that annotation referring to
        local state no longer accessible from this deferred evaluation).
    BeartypeDecorParamNameException
        If the name of any parameter declared on this callable is prefixed by
        the reserved substring ``__beartype_``.
    BeartypeDecorWrappeeException
        If this callable is either:

        * Uncallable.
        * A class, which :mod:`beartype` currently fails to support.
        * A C-based callable (e.g., builtin, third-party C extension).
    BeartypeDecorWrapperException
        If this decorator erroneously generates a syntactically invalid wrapper
        function. This should *never* happen, but here we are, so this probably
        happened. Please submit an upstream issue with our issue tracker if you
        ever see this. (Thanks and abstruse apologies!)
    '''
)
