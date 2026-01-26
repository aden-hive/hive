#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **PEP-agnostic type hint coercers** (i.e., mid-level callables
*permanently* converting type hints from one format into another, either
losslessly or in a lossy manner).

Type hint coercions imposed by this submodule are externalized outside
:mod:`beartype` as globally scoped changes accessible to other modules. These
coercions are permanently applied to the ``__annotations__`` dunder dictionaries
of the classes and callables annotated by these type hints.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: [PEP 544] coerce_hint() should also coerce PEP 544-compatible protocols
#*NOT* decorated by @typing.runtime_checkable to be decorated by that decorator,
#as such protocols are unusable at runtime. Yes, we should always try something
#*REALLY* sneaky and clever.
#
#Specifically, rather than accept "typing" nonsense verbatim, we could instead:
#* Detect PEP 544-compatible protocol type hints *NOT* decorated by
#  @typing.runtime_checkable. The existing is_type_isinstanceable() tester now
#  detects whether arbitrary classes are isinstanceable, so just call that.
#* Emit a non-fatal warning advising the end user to resolve this on their end.
#* Meanwhile, beartype can simply:
#  * Dynamically fabricate a new PEP 544-compatible protocol decorated by
#    @typing.runtime_checkable using the body of the undecorated user-defined
#    protocol as its base. Indeed, simply subclassing a new subclass decorated
#    by @typing.runtime_checkable from the undecorated user-defined protocol as
#    its base with a noop body of "pass" should suffice.
#  * Replacing all instances of the undecorated user-defined protocol with that
#    decorated beartype-defined protocol in annotations. Note this would
#    strongly benefit from some form of memoization or caching. Since this edge
#    case should be fairly rare, even a dictionary would probably be overkill.
#    Just implementing something resembling the following memoized getter
#    in the "utilpep544" submodule would probably suffice:
#        @callable_cached
#        def get_pep544_protocol_checkable_from_protocol_uncheckable(
#            protocol_uncheckable: object) -> Protocol:
#            ...
#
#Checkmate, "typing". Checkmate.

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Union,
)
from beartype._cave._cavefast import NotImplementedType
# from beartype._cave._cavemap import NoneTypeOr
from beartype._data.func.datafunc import METHOD_NAMES_DUNDER_BINARY
from beartype._data.func.datafuncarg import ARG_NAME_RETURN
from beartype._data.typing.datatypingport import Hint
from beartype._check.forward.fwdresolve import resolve_hint
from beartype._check.metadata.metadecor import BeartypeDecorMeta
from beartype._util.cache.map.utilmapbig import CacheUnboundedStrong
from beartype._util.hint.pep.proposal.pep484.pep484union import (
    make_hint_pep484_union)
from beartype._util.hint.utilhinttest import is_hint_cacheworthy

# ....................{ COERCERS ~ root                    }....................
#FIXME: Document mypy-specific coercion in the docstring as well, please.
def coerce_func_hint_root(
    hint: Hint,
    decor_meta: BeartypeDecorMeta,
    pith_name: str,
    exception_prefix: str,
) -> Hint:
    '''
    PEP-compliant type hint coerced (i.e., converted) from the passed **root
    type hint** (i.e., possibly PEP-noncompliant type hint annotating the
    parameter or return with the passed name of the passed callable) if this
    hint is coercible *or* this hint as is otherwise (i.e., if this hint is
    *not* coercible).

    This function is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator). Since the hint returned by this
    function conditionally depends upon the passed callable, memoizing this
    function would consume space needlessly with *no* useful benefit.

    Caveats
    -------
    This function *cannot* be meaningfully memoized, since the passed type hint
    is *not* guaranteed to be cached somewhere. Only functions passed cached
    type hints can be meaningfully memoized. Since this high-level function
    internally defers to unmemoized low-level functions that are :math:`O(n)`
    for :math:``n` the size of the inheritance hierarchy of this hint, this
    function should be called sparingly. See the
    :mod:`beartype._decor.cache.cachehint` submodule for further details.

    Parameters
    ----------
    hint : Hint
        Possibly PEP-noncompliant type hint to be possibly coerced.
    decor_meta : BeartypeDecorMeta
        Decorated callable directly annotated by this hint.
    pith_name : str
        Either:

        * If this hint annotates a parameter of some callable, the name of that
          parameter.
        * If this hint annotates the return of some callable, ``"return"``.
    exception_prefix : str
        Human-readable label prefixing raised exception messages.

    Returns
    -------
    Hint
        Either:

        * If this possibly PEP-noncompliant hint is coercible, a PEP-compliant
          type hint coerced from this hint.
        * Else, this hint as is unmodified.
    '''
    assert isinstance(pith_name, str), (
        f'{repr(pith_name)} not string.')
    assert isinstance(decor_meta, BeartypeDecorMeta), (
        f'{repr(decor_meta)} not @beartype metadata.')
    # print(f'Coercing pith "{pith_name}" annotated by type hint {repr(hint)}...')

    # ..................{ FORWARD REFERENCE                  }..................
    # If this hint is stringified (e.g., as a PEP 484- or 563-compliant forward
    # reference), resolve this hint to the non-string hint to which this hint
    # refers *BEFORE* performing any subsequent logic with this hint -- *ALL* of
    # which assumes this hint to be a non-string hint.
    if isinstance(hint, str):
        # print(f'Resolving {repr(decor_meta)} string hint {repr(hint)}...')
        hint = resolve_hint(
            hint=hint, decor_meta=decor_meta, exception_prefix=exception_prefix)  # pyright: ignore
    # Else, this hint is *NOT* stringified.
    #
    # In either case, this hint is guaranteed to now be a non-string hint.

    # ..................{ MYPY                               }..................
    # If...
    if (
        # This hint annotates the return for the decorated callable *AND*...
        pith_name == ARG_NAME_RETURN and
        # The decorated callable is a binary dunder method (e.g., __eq__())...
        decor_meta.func_wrapper_name in METHOD_NAMES_DUNDER_BINARY
    ):
        # Expand this hint to accept both this hint *AND* the "NotImplemented"
        # singleton as valid returns from this method. Why? Because this
        # expansion has been codified by mypy and is thus a de-facto typing
        # standard, albeit one currently lacking formal PEP standardization.
        #
        # Consider this representative binary dunder method:
        #     class MuhClass:
        #         @beartype
        #         def __eq__(self, other: object) -> bool:
        #             if isinstance(other, TheCloud):
        #                 return self is other
        #             return NotImplemented
        #
        # Technically, that method *COULD* be retyped to return:
        #         def __eq__(self, other: object) -> Union[
        #             bool, type(NotImplemented)]:
        #
        # Pragmatically, mypy and other static type checkers do *NOT* currently
        # support the type() builtin in a sane manner and thus raise errors
        # given the otherwise valid logic above. This means that the following
        # equivalent approach also yields the same errors:
        #     NotImplementedType = type(NotImplemented)
        #     class MuhClass:
        #         @beartype
        #         def __eq__(self, other: object) -> Union[
        #             bool, NotImplementedType]:
        #             if isinstance(other, TheCloud):
        #                 return self is other
        #             return NotImplemented
        #
        # Of course, the latter approach can be manually rectified by
        # explicitly typing that type as "Any": e.g.,
        #     NotImplementedType: Any = type(NotImplemented)
        #
        # Of course, expecting users to be aware of these ludicrous sorts of
        # mypy idiosyncrasies merely to annotate an otherwise normal binary
        # dunder method is one expectation too far.
        #
        # In theory, official CPython developers have already resolved this
        # under Python >= 3.10 by defining the "types.NotImplementedType" type.
        # In practice, that fails to assist older Python versions. Mypy has
        # thus taken the surprisingly sensible course of silently ignoring this
        # edge case by effectively performing the same type expansion as
        # performed here. *applause*
        return Union[hint, NotImplementedType]  # type: ignore[return-value]  # pyright: ignore

    # Defer to the function-agnostic root hint coercer as a generic fallback.
    return coerce_hint_root(hint=hint, exception_prefix=exception_prefix)


def coerce_hint_root(hint: Hint, exception_prefix: str) -> Hint:
    '''
    PEP-compliant type hint coerced (i.e., converted) from the passed **root
    type hint** (i.e., possibly PEP-noncompliant type hint that has *no* parent
    type hint) if this hint is coercible *or* this hint as is otherwise (i.e.,
    if this hint is *not* coercible).

    Specifically, if the passed hint is:

    * A **PEP-noncompliant tuple union** (i.e., tuple of one or more standard
      classes and forward references to standard classes), this function:

      * Coerces this tuple union into the equivalent :pep:`484`-compliant
        union.
      * Replaces this tuple union in the ``__annotations__`` dunder tuple of
        this callable with this :pep:`484`-compliant union.
      * Returns this :pep:`484`-compliant union.

    This function is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator). See caveats that follow.

    Caveats
    -------
    This function *cannot* be meaningfully memoized, since the passed type hint
    is *not* guaranteed to be cached somewhere. Only functions passed cached
    type hints can be meaningfully memoized. Since this high-level function
    internally defers to unmemoized low-level functions that are ``O(n)`` for
    ``n`` the size of the inheritance hierarchy of this hint, this function
    should be called sparingly. See the :mod:`beartype._decor.cache.cachehint`
    submodule for further details.

    Parameters
    ----------
    hint : object
        Possibly PEP-noncompliant type hint to be possibly coerced.
    exception_prefix : str
        Human-readable label prefixing the representation of this object in the
        exception message.

    Returns
    -------
    Hint
        Either:

        * If this possibly PEP-noncompliant hint is coercible, a PEP-compliant
          type hint coerced from this hint.
        * Else, this hint as is unmodified.
    '''

    # ..................{ NON-PEP                            }..................
    # If this hint is a PEP-noncompliant tuple union, coerce this union into
    # the equivalent PEP-compliant union subscripted by the same child hints.
    # By definition, PEP-compliant unions are a superset of PEP-noncompliant
    # tuple unions and thus accept all child hints accepted by the latter.
    if isinstance(hint, tuple):
        return make_hint_pep484_union(hint)
    # Else, this hint is *NOT* a PEP-noncompliant tuple union.

    # Since none of the above conditions applied, this hint could *NOT* be
    # specifically coerced as a root type hint. Nonetheless, this hint may
    # still be generically coercible as a hint irrespective of its contextual
    # position relative to other type hints.
    #
    # Return this hint, possibly coerced as a context-agnostic type hint.
    return coerce_hint_any(hint)

# ....................{ COERCERS ~ any                     }....................
def coerce_hint_any(hint: Hint) -> Hint:
    '''
    PEP-compliant type hint coerced (i.e., converted) from the passed
    PEP-compliant type hint if this hint is coercible *or* this hint as is
    otherwise (i.e., if this hint is *not* coercible).

    Specifically, if the passed hint is:

    * A **PEP-compliant uncached type hint** (i.e., hint *not* already
      internally cached by its parent class or module), this function:

      * If this hint has already been passed to a prior call of this function,
        returns the semantically equivalent PEP-compliant type hint having the
        same machine-readable representation as this hint cached by that call.
        Doing so deduplicates this hint, which both:

        * Minimizes space complexity across the lifetime of this process.
        * Minimizes time complexity by enabling beartype-specific memoized
          callables to efficiently reduce to constant-time lookup operations
          when repeatedly passed copies of this hint nonetheless sharing the
          same machine-readable representation.

      * Else, internally caches this hint with a thread-safe global cache and
        returns this hint as is.

      Uncached hints include:

      * :pep:`484`-compliant subscripted generics under Python >= 3.9 (e.g.,
        ``from typing import List; class MuhPep484List(List): pass;
        MuhPep484List[int]``). See below for further commentary.
      * :pep:`585`-compliant type hints, including both:

        * Builtin :pep:`585`-compliant type hints (e.g., ``list[int]``).
        * User-defined :pep:`585`-compliant generics (e.g.,
          ``class MuhPep585List(list): pass; MuhPep585List[int]``).

    * Already cached, this hint is already PEP-compliant by definition. In this
      case, this function preserves and returns this hint as is.

    This function is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator). See caveats that follow.

    Design
    ------
    This function does *not* bother caching **self-caching type hints** (i.e.,
    type hints that externally cache themselves), as these hints are already
    cached elsewhere. Self-cached type hints include most type hints created by
    subscripting type hint factories declared by the :mod:`typing` module,
    which internally cache their resulting type hints: e.g.,

    .. code-block:: pycon

       >>> import typing
       >>> typing.List[int] is typing.List[int]
       True

    Equivalently, this function *only* caches **uncached type hints** (i.e.,
    type hints that do *not* externally cache themselves), as these hints are
    *not* already cached elsewhere. Uncached type hints include *all*
    :pep:`585`-compliant type hints produced by subscripting builtin container
    types, which fail to internally cache their resulting type hints: e.g.,

    .. code-block:: pycon

       >>> list[int] is list[int]
       False

    This function enables callers to coerce uncached type hints into
    :mod:`beartype`-cached type hints. :mod:`beartype` effectively requires
    *all* type hints to be cached somewhere! :mod:`beartype` does *not* care
    who, what, or how is caching those type hints -- only that they are cached
    before being passed to utility functions in the :mod:`beartype` codebase.
    Why? Because most such utility functions are memoized for efficiency by the
    :func:`beartype._util.cache.utilcachecall.callable_cached` decorator, which
    maps passed parameters (typically including the standard ``hint`` parameter
    accepting a type hint) based on object identity to previously cached return
    values. You see the problem, we trust.

    Uncached type hints that are otherwise semantically equal are nonetheless
    distinct objects and will thus be treated as distinct parameters by
    memoization decorators. If this function did *not* exist, uncached type
    hints could *not* be coerced into :mod:`beartype`-cached type hints and
    thus could *not* be memoized, dramatically reducing the efficiency of
    :mod:`beartype` for standard type hints.

    Caveats
    -------
    This function *cannot* be meaningfully memoized, since the passed type hint
    is *not* guaranteed to be cached somewhere. Only functions passed cached
    type hints can be meaningfully memoized. Since this high-level function
    internally defers to unmemoized low-level functions that are :math:`O(n)`
    for :math:`n` the size of the inheritance hierarchy of this hint, this
    function should be called sparingly.

    This function intentionally does *not* cache :pep:`484`-compliant generics
    subscripted by type variables under Python < 3.9. Those hints are
    technically uncached but silently treated by this function as self-cached
    and thus preserved as is. Why? Because correctly detecting those hints as
    uncached would require an unmemoized :math:`O(n)` search across the
    inheritance hierarchy of *all* passed objects and thus all type hints
    annotating callables decorated by :func:`beartype.beartype`. Since this
    failure only affects obsolete Python versions *and* since the only harms
    induced by this failure are a slight increase in space and time consumption
    for edge-case type hints unlikely to actually be used in real-world code,
    this tradeoff is more than acceptable. We're not the bad guy here. Right?

    Parameters
    ----------
    hint : Hint
        Type hint to be possibly coerced.

    Returns
    -------
    Hint
        Either:

        * If this PEP-compliant type hint is coercible, another PEP-compliant
          type hint coerced from this hint.
        * Else, this hint as is unmodified.
    '''

    # ..................{ NON-SELF-CACHING                   }..................
    # If this hint is *NOT* self-caching, this hint *MUST* thus be explicitly
    # cached here. Failing to do so would disable subsequent memoization,
    # reducing decoration- and call-time efficiency when decorating callables
    # repeatedly annotated by copies of this hint.
    #
    # Specifically, deduplicate this hint by either:
    # * If this is the first copy of this hint passed to this function, cache
    #   this hint under its machine-readable implementation.
    # * Else, one or more prior copies of this hint have already been passed to
    #   this function. In this case, replace this subsequent copy by the first
    #   copy of this hint originally passed to a prior call of this function.
    if is_hint_cacheworthy(hint):
        # print(f'Self-caching type hint {repr(hint)}...')

        #FIXME: [SPEED] Globalize the
        #_hint_repr_to_hint.cache_or_get_cached_value() bound method and call
        #that globalized bound method here instead as a negligible speedup.

        # Note that we intentionally call the unmemoized low-level repr()
        # builtin here rather than our memoized higher-level get_hint_repr()
        # getter. Why? Because the latter would significantly increase the space
        # consumption of that memoization, as the passed hint has *NOT* yet been
        # deduplicated by the logic performed here.
        return _hint_repr_to_hint.cache_or_get_cached_value(  # type: ignore[return-value]
            key=repr(hint), value=hint)
    # Else, this hint is (hopefully) self-caching.

    # Return this uncoerced hint as is.
    return hint

# ....................{ PRIVATE ~ mappings                 }....................
_hint_repr_to_hint = CacheUnboundedStrong()
'''
**Type hint cache** (i.e., thread-safe cache mapping from the machine-readable
representations of all non-self-cached type hints to cached singleton instances
of those hints).**

This cache caches:

* :pep:`585`-compliant type hints, which do *not* cache themselves.
* :pep:`604`-compliant unions, which do *not* cache themselves.

This cache does *not* cache:

* Type hints declared by the :mod:`typing` module, which implicitly cache
  themselves on subscription thanks to inscrutable metaclass magic.
* :pep:`563`-compliant **deferred type hints** (i.e., type hints persisted as
  evaluable strings rather than actual type hints). Ideally, this cache would
  cache the evaluations of *all* deferred type hints. Sadly, doing so is
  infeasible in the general case due to global and local namespace lookups
  (e.g., ``Dict[str, int]`` only means what you think it means if an
  importation resembling ``from typing import Dict`` preceded that type hint).

Design
------
**This dictionary is intentionally thread-safe.** Why? Because this dictionary
is used to modify the ``__attributes__`` dunder variable of arbitrary callables.
Since most such callables are either module- or class-scoped, that variable is
effectively global. To prevent race conditions between competing threads
contending over that variable, this dictionary *must* be thread-safe.

**This dictionary is intentionally designed as a naive dictionary rather than a
robust LRU cache,** for the same reasons that callables accepting hints are
memoized by the :func:`beartype._util.cache.utilcachecall.callable_cached`
rather than the :func:`functools.lru_cache` decorator. Why? Because:

* The number of different type hints instantiated across even worst-case
  codebases is negligible in comparison to the space consumed by those hints.
* The :attr:`sys.modules` dictionary persists strong references to all
  callables declared by previously imported modules. In turn, the
  ``func.__annotations__`` dunder dictionary of each such callable persists
  strong references to all type hints annotating that callable. In turn, these
  two statements imply that type hints are *never* garbage collected but
  instead persisted for the lifetime of the active Python process. Ergo,
  temporarily caching hints in an LRU cache is pointless, as there are *no*
  space savings in dropping stale references to unused hints.

**This dictionary intentionally caches machine-readable representation strings
hashes rather than alternative keys** (e.g., actual hashes). Why? Disambiguity.
Although comparatively less efficient in both space and time to construct than
hashes, the :func:`repr` strings produced for two dissimilar type hints *never*
ambiguously collide unless an external caller maliciously modified one or more
identifying dunder attributes of those hints (e.g., the ``__module__``,
``__qualname__``, and/or ``__name__`` dunder attributes). That should *never*
occur in production code. Meanwhile, the :func:`hash` values produced for two
dissimilar type hints *commonly* ambiguously collide. This is why hashable
containers (e.g., :class:`dict`, :class:`set`) explicitly handle hash table
collisions and why we are *not* going to do so.
'''
