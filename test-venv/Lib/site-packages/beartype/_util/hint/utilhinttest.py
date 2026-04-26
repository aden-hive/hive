#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **PEP-agnostic type hint tester utilities** (i.e., callables
validating arbitrary objects to be type hints supported by :mod:`beartype`,
regardless of whether those hints comply with PEP standards or not).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.meta import URL_ISSUES
from beartype.roar import BeartypeDecorHintNonpepException
from beartype.typing import NoReturn
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import TypeException
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.hint.nonpep.utilnonpeptest import (
    die_unless_hint_nonpep,
    is_hint_nonpep,
)
from beartype._util.hint.pep.utilpepget import get_hint_pep_typeargs_packed
from beartype._util.hint.pep.utilpeptest import (
    die_if_hint_pep_unsupported,
    is_hint_pep,
    is_hint_pep_supported,
)
from beartype._util.hint.pep.proposal.pep585 import (
    is_hint_pep585_builtin_subbed)
from beartype._util.hint.pep.proposal.pep484604 import is_hint_pep604

# ....................{ RAISERS                            }....................
def die_unless_hint(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is a **supported type hint**
    (i.e., object supported by the :func:`beartype.beartype` decorator as a
    valid type hint annotating callable parameters and return values).

    Specifically, this function raises an exception if this object is neither:

    * A **supported PEP-compliant type hint** (i.e., :mod:`beartype`-agnostic
      annotation compliant with annotation-centric PEPs currently supported
      by the :func:`beartype.beartype` decorator).
    * A **PEP-noncompliant type hint** (i.e., :mod:`beartype`-specific
      annotation intentionally *not* compliant with annotation-centric PEPs).

    Efficiency
    ----------
    This validator is effectively (but technically *not*) memoized. The passed
    ``exception_prefix`` parameter is usually unique to each call to this
    validator; memoizing this validator would uselessly consume excess space
    *without* improving time efficiency. Instead, this validator first calls the
    memoized :func:`.is_hint_pep` tester. If that tester returns :data:`True`,
    this validator immediately returns :data:`True` and is thus effectively
    memoized; else, this validator inefficiently raises a human-readable
    exception without memoization. Since efficiency is mostly irrelevant in
    exception handling, this validator remains effectively memoized.

    Parameters
    ----------
    hint : Hint
        Object to be validated.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    BeartypeDecorHintPepUnsupportedException
        If this object is a PEP-compliant type hint currently unsupported by
        the :func:`beartype.beartype` decorator.
    BeartypeDecorHintNonpepException
        If this object is neither a:

        * Supported PEP-compliant type hint.
        * Supported PEP-noncompliant type hint.
    '''

    # If this object is a supported type hint, reduce to a noop.
    if is_hint(hint):
        return
    # Else, this object is *NOT* a supported type hint. In this case,
    # subsequent logic raises an exception specific to the passed parameters.

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # BEGIN: Synchronize changes here with is_hint() below.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # If this hint is PEP-compliant *AND* currently unsupported by @beartype,
    # raise an exception.
    if is_hint_pep(hint):
        die_if_hint_pep_unsupported(
            hint=hint, exception_prefix=exception_prefix)
    # Else, this hint is PEP-noncompliant. In this case...

    # If this PEP-noncompliant hint is currently unsupported by @beartype, raise
    # an exception.
    die_unless_hint_nonpep(hint=hint, exception_prefix=exception_prefix)


def die_as_hint_unsupported(
    # Mandatory parameters.
    hint: object,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintNonpepException,
    exception_prefix: str = '',
) -> NoReturn:
    '''
    Unconditionally raise an exception describing the failure of the passed
    object to be a **supported type hint** (i.e., object supported by the
    :func:`beartype.beartype` decorator as a valid type hint annotating callable
    parameters and return values).

    This low-level raiser is intended to be called only after this object has
    already been validated to *not* be a supported type hint. This raiser
    centralizes similar logic previously duplicated throughout the codebase.

    Parameters
    ----------
    hint : object
        Object to be validated.
    exception_cls : type[Exception]
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintNonpepException`.
    exception_prefix : str, optional
        Human-readable substring prefixing the raised exception message.
        Defaults to the empty string.

    Raises
    ------
    exception_cls
        Unconditionally.
    '''
    assert isinstance(exception_cls, type), f'{repr(exception_cls)} not type.'
    assert isinstance(exception_prefix, str), (
        f'{repr(exception_prefix)} not string.')

    # Raise this generic exception message.
    raise exception_cls(
        f'{exception_prefix}type hint {repr(hint)} invalid or unrecognized. '
        f'This hint is either:\n'
        f'* PEP-noncompliant (and thus invalid). '
        f"This is your bad. Rejoice! @beartype isn't to blame for once.\n"
        f'* PEP-compliant but currently unsupported by @beartype '
        f'(and thus unrecognized). '
        f'This is our bad. Disaster! @beartype is to blame like always. '
        f'You suddenly feel encouraged to submit a feature request '
        f'for this unsupported hint to our friendly issue tracker at:\n'
        f'\t{URL_ISSUES}'
    )

# ....................{ TESTERS                            }....................
@callable_cached
def is_hint(hint: object) -> bool:
    '''
    :data:`True` only if the passed object is a **supported type hint** (i.e.,
    object supported by the :func:`beartype.beartype` decorator as a valid type
    hint annotating callable parameters and return values).

    This tester is memoized for efficiency.

    Parameters
    ----------
    hint : object
        Object to be validated.

    Returns
    -------
    bool
        :data:`True` only if this object is either:

        * A **PEP-compliant type hint** (i.e., :mod:`beartype`-agnostic
          annotation compliant with annotation-centric PEPs).
        * A **PEP-noncompliant type hint** (i.e., :mod:`beartype`-specific
          annotation intentionally *not* compliant with annotation-centric
          PEPs).

    Raises
    ------
    TypeError
        If this object is **unhashable** (i.e., *not* hashable by the builtin
        :func:`hash` function and thus unusable in hash-based containers like
        dictionaries and sets). All supported type hints are hashable.
    '''

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # BEGIN: Synchronize changes here with die_unless_hint() above.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # Return true only if...
    return (
        # This is a PEP-compliant type hint supported by @beartype *OR*...
        is_hint_pep_supported(hint) if is_hint_pep(hint) else
        # This is a PEP-noncompliant type hint, which by definition is
        # necessarily supported by @beartype.
        is_hint_nonpep(hint=hint, is_forwardref_valid=True)
    )


#FIXME: Unit test us up, please.
def is_hint_cacheworthy(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed type hint is **cache-worthy.**

    A hint is cache-worthy if *all* of the following constraints hold:

    * This hint is *not* already **self-cached** (i.e., internally memoized) by
      its owner class or module. Although most hints *used* to self-cache, most
      modern hints no longer self-cache. Why? No idea. It's probably an
      accidental oversight in PEP implementations across different CPython
      developers that nobody ever bothered to report: e.g.,

      .. code-block:: pycon

         # PEP 585 type hints do *NOT* self-cache and are thus cache-worthy.
         >>> list[int] is list[int]
         False  # <-- horrible! pep 585, you are horrible!

         # PEP 484 type hints do self-cache and are thus *NOT* cache-worthy.
         >>> import typing
         >>> typing.List[int] is typing.List[int]
         True  # <-- wonderful. pep 484, you are wonderful.

    * The **machine-readable representation** (i.e., string returned by passing
      this hint to the :func:`repr` builtin) of this hint is **unambiguous**
      (i.e., there exists a one-to-one mapping between this representation and
      the contents of this representation such that only equal hints have equal
      representations). Although most hints have unambiguous representations,
      some hints have ambiguous representations -- including:

      * Type hints transitively parametrized by one or more **type variables**
        (i.e., :obj:`typing.TypeVar` objects) have ambiguous representations and
        are thus *not* cache-worthy. Note that the existence of even a single
        type variable parametrizing a single child type hint subscripting a
        parent type hint sadly renders the *entire* representation of that
        parent type hint ambiguous: e.g.,

        .. code-block:: pycon

           >>> from typing import TypeVar
           >>> T_int = TypeVar('T', bound=int)
           >>> T_str = TypeVar('T', bound=str)
           >>> repr(list[T_int])
           list[T]  # <-- ...ok
           >>> repr(list[T_str])
           list[T]  # <-- WUT U SAY!?
           >>> repr(list[T_int]) == repr(list[T_str])
           True  # <-- horrible! "TypeVar", you are horrible!

    Caveats
    -------
    This function *cannot* be meaningfully memoized, since the passed type hint
    is *not* guaranteed to be cached somewhere. Only functions passed cached
    type hints can be meaningfully memoized. Since this high-level function
    internally defers to unmemoized low-level functions that are ``O(n)`` for
    ``n`` the size of the inheritance hierarchy of this hint, this function
    should be called sparingly.

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this type hint is uncached.

    See Also
    --------
    :func:`beartype._check.convert._convcoerce.coerce_hint_any`
        Further details.
    '''

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Avoid detecting the kind of this hint by calling any of the
    # get_hint_pep_sign_*() family of memoized getters. Doing so would consume
    # excess time and space when this hint is uncached, as passing this hint to
    # any of those getters would then cache against a hint that it is
    # functionally useless to cache against.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # Return true only if this hint is...
    return (
        # *NOT* transitively parametrized by one or type variables (e.g.,
        # "list[tuple[T]]"). All first-party hints (i.e., hints defined by
        # CPython's standard library) and all third-party hints supported by
        # @beartype have unambiguous representations *EXCEPT* for hints
        # transitively parametrized by one or type variables, as type variables
        # themselves have ambiguous representations.
        not get_hint_pep_typeargs_packed(hint) and
        # Either...
        (
            # PEP 585-compliant (e.g., "list[str]"). This hint is *NOT*
            # self-caching (e.g., "list[str] is not list[str]").
            #
            # Note that this additionally includes all third-party type hints
            # that derive from the "types.GenericAlias" superclass, including:
            # * "numpy.typing.NDArray[...]" type hints.
            is_hint_pep585_builtin_subbed(hint) or
            # PEP 604-compliant (e.g., "int | str"). This hint is *NOT*
            # self-caching (e.g., "int | str is not int | str").
            #
            # Note that this hint could also be implicitly cached by coercing
            # this non-self-caching PEP 604-compliant union into a self-caching
            # PEP 484-compliant union (e.g., from "int | str" to "Union[int,
            # str]"). Since doing so would consume substantially more time for
            # *NO* tangible gain, we strongly prefer the current trivial and
            # efficient approach.
            is_hint_pep604(hint)
        )
    )

# ....................{ TESTERS ~ needs                    }....................
@callable_cached
def is_hint_needs_cls_stack(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed type hint is **type stack-dependent** (i.e.,
    if :mod:`beartype` requires the tuple of all classes lexically declaring the
    class variables or methods annotated by this hint to generate code
    type-checking this hint).

    This tester returns :data:`False` for most hints; only a small subset of
    hints are type stack-dependent. This includes:

    * :pep:`673`-compliant self type hint (i.e., :obj:`typing.Self`), which is
      contextually valid *only* inside a lexical class declaration.

    This tester is memoized for efficiency.

    Motivation
    ----------
    **This tester should only be called to decide whether memoized callables
    should be passed a type stack.** Passing memoized callables a type stack
    substantially reduces the likelihood of a cache hit and thus the
    average-case efficiency of calls to those callables. Notably:

    * Most type hints do *not* require a type stack.
    * Most type hints annotate class variables and methods of differing classes
      and thus do *not* share the same type stack.

    Ergo, passing memoized callables both a type hint *and* a type stack
    effectively unmemoizes those callables. Thankfully, callers can elide this
    inefficiency by calling this tester first; when this tester returns:

    * :data:`False`, the caller can safely pass memoized callables a type hint
      and :data:`None` for the type stack, thus preserving memoization. This is
      the common case and thus absolutely worth optimizing for.
    * :data:`True`, the caller has *no* choice but to pass memoized callables
      both a type hint *and* a type stack. Grr!

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this type hint is type stack-dependent.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.utilhintget import get_hint_repr

    # Machine-readable representation of this hint.
    hint_repr = get_hint_repr(hint)

    # Return true only if this representation embeds the representation of:
    # * A PEP 673-compliant self type hint (i.e., "typing.Self").
    #
    # Note:
    # * The fully-qualified names of exact typing modules (e.g., "typing",
    #   "typing_extensions") is intentionally ignored. Although we could
    #   certainly explicitly test for both, doing so would only needlessly
    #   reduce efficiency. By omitting explicit tests for both, this tester
    #   intentionally returns false positives for extremely edge case hints
    #   whose representations contain syntactically related but semantically
    #   unrelated substrings (e.g., "typing.Literal['.Self']", which is clearly
    #   *NOT* a PEP 673-compliant self type hint but erroneously matched as one
    #   by this heuristic). This is non-ideal but thankfully ignorable. See the
    #   "Motivation" section of the docstring for further commentary.
    # * This string is intentionally *NOT* preceded by a "." delimiter (e.g., as
    #   ".Self" rather than "Self"). Previously, this string was intentionally
    #   preceded by a "." delimiter; doing so satisfied most edge cases while
    #   reducing the likelihood of a false positive. Sadly, doing so also failed
    #   to match "Self" type hints stringified by PEP 563. Grrr!
    # * That the "in" operator is known to be the fastest means of performing
    #   substring matching in Python. Indeed:
    #   * "in" is faster than the str.find() method, which is *SUBSTANTIALLY*
    #     faster than the re.match() function, which is an entire of magnitude
    #     slower than "in".
    #   * re.match() only begins to catch up to "in" when concurrently testing
    #     for more than 10 or so substrings (e.g., r'(0|1|2|3|4|5|6|7|8|9)').
    #
    # See also the extensive timings documented at this StackOverflow question:
    #     https://stackoverflow.com/questions/4901523/whats-a-faster-operation-re-match-search-or-str-find
    return 'Self' in hint_repr
