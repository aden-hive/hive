#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Memoized beartype decorator.**

This private submodule defines the core :func:`beartype.beartype` decorator,
conditionally imported (in order):

#. Into the parent :mod:`beartype._decor.decormain` submodule if this decorator
   is *not* currently reducing to a noop (e.g., due to ``python3 -O``
   optimization).
#. Into the root :mod:`beartype.__init__` submodule if the :mod:`beartype`
   package is *not* currently being installed by :mod:`setuptools`.

This private submodule is literally the :func:`beartype.beartype` decorator,
despite *not* actually being that decorator (due to being unmemoized).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
# from beartype.roar import BeartypeConfException
from beartype.typing import (
    Dict,
    Optional,
)
from beartype._conf.confmain import BeartypeConf
from beartype._conf.confcommon import BEARTYPE_CONF_DEFAULT
from beartype._conf.conftest import die_unless_conf
from beartype._data.typing.datatyping import (
    BeartypeConfedDecorator,
    BeartypeReturn,
    BeartypeableT,
)
from beartype._decor.decorcore import beartype_object
from collections.abc import Callable

# Intentionally import the standard mypy-friendly @typing.overload decorator
# rather than a possibly mypy-unfriendly @beartype.typing.overload decorator --
# which, in any case, would be needlessly inefficient and thus bad.
from typing import overload

# ....................{ OVERLOADS                          }....................
# Declare PEP 484-compliant overloads to avoid breaking downstream code
# statically type-checked by a static type checker (e.g., mypy). The concrete
# @beartype decorator declared below is permissively annotated as returning a
# union of multiple types desynchronized from the types of the passed arguments
# and thus fails to accurately convey the actual public API of that decorator.
# See also:
#     https://www.python.org/dev/peps/pep-0484/#function-method-overloading
#
# Note that the "Callable[[BeartypeableT], BeartypeableT]" type hint should
# ideally instead be a reference to our "BeartypeConfedDecorator" type hint.
# Indeed, it used to be. Unfortunately, a significant regression in mypy
# required us to inline that type hint away. See also this issue:
#     https://github.com/beartype/beartype/issues/332
@overload
def beartype(obj: BeartypeableT) -> BeartypeableT: ...
@overload
def beartype(*, conf: BeartypeConf) -> (
    Callable[[BeartypeableT], BeartypeableT]): ...

# ....................{ DECORATORS                         }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: Synchronize the signature of this non-identity decorator with the
# identity decorator defined by the "beartype._decor.decormain" submodule.
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: The parent "beartype._decor.decormain" submodule intentionally
# defines the docstring for this decorator.
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
def beartype(
    # Optional positional or keyword parameters.
    obj: Optional[BeartypeableT] = None,

    # Optional keyword-only parameters.
    *,
    conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
) -> BeartypeReturn:

    # If this configuration is invalid, raise an exception.
    die_unless_conf(conf)
    # Else, this configuration is valid.

    # If passed an object to be decorated, this decorator is in decoration
    # rather than configuration mode. In this case, decorate this object with
    # type-checking configured by this configuration.
    #
    # Note this branch is typically *ONLY* entered when the "conf" parameter
    # is *NOT* explicitly passed and thus defaults to the default
    # configuration. While callers may technically run this decorator in
    # decoration mode with a non-default configuration, doing so would be both
    # highly irregular *AND* violate PEP 561-compliance by violating the
    # decorator overloads declared above. Nonetheless, we're largely permissive
    # here; callers that are doing this are sufficiently intelligent to be
    # trusted to violate PEP 561-compliance if they so choose. So... *shrug*
    if obj is not None:
        return beartype_object(obj, conf)
    # Else, this decorator was passed *NO* object to be decorated. In this case,
    # this decorator is in configuration rather than decoration mode.

    # Private decorator (possibly previously generated and cached by a prior
    # call to this decorator also in configuration mode) generically applying
    # this configuration to any beartypeable object passed to that decorator
    # if a prior call to this public decorator has already been passed the same
    # configuration (and thus generated and cached this private decorator) *OR*
    # "None" otherwise (i.e., if this is the first call to this public
    # decorator passed this configuration in configuration mode). Phew!
    beartype_confed_cached = _bear_conf_to_decor.get(conf)

    # If a prior call to this public decorator has already been passed the same
    # configuration (and thus generated and cached this private decorator),
    # return this private decorator for subsequent use in decoration mode.
    if beartype_confed_cached:
        return beartype_confed_cached
    # Else, this is the first call to this public decorator passed this
    # configuration in configuration mode.

    # Define a private decorator generically applying this configuration to any
    # beartypeable object passed to this decorator.
    def _beartype_confed(obj: BeartypeableT) -> BeartypeableT:
        '''
        Decorate the passed **beartypeable** (i.e., pure-Python callable or
        class) with optimal type-checking dynamically generated unique to
        that beartypeable under the beartype configuration passed to a
        prior call to the :func:`beartype.beartype` decorator.

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

        # Decorate this object with type-checking configured by this
        # configuration.
        return beartype_object(obj, conf)

    # Cache this private decorator against this configuration.
    _bear_conf_to_decor[conf] = _beartype_confed

    # Return this private decorator.
    return _beartype_confed

# ....................{ SINGLETONS                         }....................
_bear_conf_to_decor: Dict[BeartypeConf, BeartypeConfedDecorator] = {}
'''
Non-thread-safe **beartype decorator cache.**

This cache is implemented as a singleton dictionary mapping from each
**beartype configuration** (i.e., self-caching dataclass encapsulating all
flags, options, settings, and other metadata configuring the current decoration
of the decorated callable or class) to the corresponding **configured beartype
decorator** (i.e., closure created and returned from the
:func:`beartype.beartype` decorator when passed a beartype configuration via
the optional ``conf`` parameter rather than an object to be decorated via
the optional ``obj`` parameter).

Caveats
----------
**This cache is not thread-safe.** Although rendering this cache thread-safe
would be trivial, doing so would needlessly reduce efficiency. This cache is
merely a runtime optimization and thus need *not* be thread-safe.
'''
