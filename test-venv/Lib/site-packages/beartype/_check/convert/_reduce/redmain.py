#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **type hint reducers** (i.e., low-level callables converting type
hints from one format into another, either losslessly or in a lossy manner).

Type hint reductions imposed by this submodule are purely internal to
:mod:`beartype` itself and thus transient in nature. These reductions are *not*
permanently applied to the ``__annotations__`` dunder dictionaries of the
classes and callables annotated by these type hints.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.meta import URL_ISSUES
from beartype.roar import BeartypeDecorHintRecursionException
from beartype.typing import Optional
from beartype._cave._cavemap import NoneTypeOr
from beartype._check.convert._reduce._redmap import (
    HINT_SIGN_TO_REDUCE_HINT_CACHED_get,
    HINT_SIGN_TO_REDUCE_HINT_UNCACHED_get,
)
from beartype._check.convert._reduce._redrecurse import (
    is_hint_recursive,
    make_hint_sane_recursable,
)
from beartype._check.metadata.metadecor import BeartypeDecorMeta
from beartype._check.metadata.hint.hintsane import (
    HINT_IGNORABLE,
    HINT_SANE_IGNORABLE,
    HintOrSane,
    HintSane,
)
from beartype._conf.confmain import BeartypeConf
from beartype._conf.confcommon import BEARTYPE_CONF_DEFAULT
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.kind.datakindiota import SENTINEL
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import (
    DictStrToAny,
    HintSignOrNoneOrSentinel,
    TypeStack,
)
from beartype._util.func.arg.utilfuncargiter import ArgKind
from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none
from beartype._util.kind.maplike.utilmapset import remove_mapping_keys

# ....................{ REDUCERS                           }....................
def reduce_hint(
    # Mandatory parameters.
    hint: Hint,

    # Optional keyword-only parameters.
    *,
    arg_kind: Optional[ArgKind] = None,
    cls_stack: TypeStack = None,
    conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
    decor_meta: Optional[BeartypeDecorMeta] = None,
    hint_parent_sane: Optional[HintSane] = None,
    hint_sign_seed: HintSignOrNoneOrSentinel = SENTINEL,
    is_hint_ignorable_preserved: bool = False,
    pith_name: Optional[str] = None,
    reductions_count: int = 0,
    exception_prefix: str = '',
) -> HintSane:
    '''
    Lower-level type hint reduced (i.e., converted) from the passed higher-level
    type hint if this hint is reducible *or* this hint as is otherwise (i.e., if
    this hint is irreducible).

    This reducer *cannot* be meaningfully memoized, since multiple passed
    parameters (e.g., ``pith_name``, ``cls_stack``) are typically isolated to a
    handful of callables across the codebase currently being decorated by
    :mod:`beartype`. Memoizing this reducer would needlessly consume space and
    time. To improve efficiency, this reducer is instead implemented in terms of
    two lower-level private reducers:

    * The memoized :func:`._reduce_hint_cached` reducer, responsible for
      efficiently reducing *most* (but not all) type hints.
    * The unmemoized :func:`._reduce_hint_uncached` reducer, responsible for
      inefficiently reducing the small subset of type hints contextually
      requiring these problematic parameters.

    Parameters
    ----------
    hint : Hint
        Type hint to be possibly reduced.
    arg_kind : Optional[ArgKind]
        Either:

        * If this hint annotates a parameter of some callable, that parameter's
          **kind** (i.e., :class:`.ArgKind` enumeration member conveying the
          syntactic class of that parameter, constraining how the callable
          declaring that parameter requires that parameter to be passed).
        * Else, :data:`None`.

        Defaults to :data:`None`.
    cls_stack : TypeStack, optional
        **Type stack** (i.e., either a tuple of the one or more
        :func:`beartype.beartype`-decorated classes lexically containing the
        class variable or method annotated by this hint *or* :data:`None`).
        Defaults to :data:`None`.
    conf : BeartypeConf, optional
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all settings configuring type-checking for the passed object). Defaults
        to the default beartype configuration.
    decor_meta : Optional[BeartypeDecorMeta], optional
        Either:

        * If this hint annotates a parameter or return of some callable, the
          :mod:`beartype`-specific decorator metadata describing that callable.
        * Else, :data:`None`.

        Defaults to :data:`None`.
    hint_parent_sane : Optional[HintSane], default: None
        Either:

        * If the passed hint is a **root** (i.e., top-most parent hint of a tree
          of child hints), :data:`None`.
        * Else, the passed hint is a **child** of some parent hint. In this
          case, the **sanified parent type hint metadata** (i.e., immutable and
          thus hashable object encapsulating *all* metadata previously returned
          by :mod:`beartype._check.convert.convmain` sanifiers after
          sanitizing the possibly PEP-noncompliant parent hint of this child
          hint into a fully PEP-compliant parent hint).

        Defaults to :data:`None`.
    hint_sign_seed :  HintSignOrNoneOrSentinel, default: SENTINEL
        **Type hint seed sign** (i.e., sign identifying this hint with respect
        to the first reduction performed by this sanification) if this hint is
        ambiguously identifiable by two or more signs *or* the sentinel
        otherwise (i.e., if this hint is uniquely identifiable by one sign).

        This sign is used to seed (i.e., initialize) the first reduction
        internally performed by this sanification, which otherwise defaults to
        the sign returned by the :func:`.get_hint_pep_sign_or_none` getter. This
        parameter should only be passed to handle edge cases in which a hint is
        ambiguously identifiable by two or more signs, including:

        * **Typed dictionary generics** (i.e., user-defined types subclassing
          both the :pep:`484`-compliant :class:`typing.Generic` superclass and
          :pep:`589`-compliant :class:`typing.TypedDict` superclass), which are
          identifiable as both generics *and* typed dictionaries.

        Defaults to the sentinel.
    is_hint_ignorable_preserved : bool, default: False
        Either:

        * If the caller prefers that ignorable hints reduced to a unique
          :data:`.HintSane` object *not* equal to the standard
          :data:`.HINT_SANE_IGNORABLE` singleton but instead encapsulating the
          :data:`.HINT_IGNORABLE` type hint and unique metadata describing the
          ignored hint reduce to that :data:`.HintSane` object rather than the
          :data:`.HINT_SANE_IGNORABLE` singleton, data:`True`.
        * If the caller prefers that ignorable hints reduced to a unique
          :data:`.HintSane` object *not* equal to the standard
          :data:`.HINT_SANE_IGNORABLE` singleton be transparently reduced to the
          :data:`.HINT_SANE_IGNORABLE` singleton, data:`False`. This preference
          is substantially easier for callers to handle but also technically
          lossy, as all unique metadata associated with this reduction is lost.

        Defaults to :data:`False`, as most callers neither require nor desire
        this distinction and are thus incapable of handling ignorable hints
        reduced to unique :data:`.HintSane` objects *not* equal to the standard
        :data:`.HINT_SANE_IGNORABLE` singleton. Most callers only expect the
        :data:`.HINT_SANE_IGNORABLE` singleton.
    pith_name : Optional[str], default: None
        Either:

        * If this hint annotates a parameter of some callable, the name of that
          parameter.
        * If this hint annotates the return of some callable, ``"return"``.
        * Else, :data:`None`.

        Defaults to :data:`None`.
    reductions_count : int, default: None
        Current number of total reductions internally performed by *all* calls
        to this function rooted at this function in the current call stack,
        guarding against accidental infinite recursion between lower-level
        reducers and this higher-level function. Defaults to 0.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    HintSane
        Either:

        * If this hint is ignorable, :data:`.HINT_SANE_IGNORABLE`.
        * Else if this unignorable hint is reducible to another hint, metadata
          encapsulating this reduction.
        * Else, this unignorable hint is irreducible. In this case, metadata
          encapsulating this hint unmodified.

    Raises
    ------
    BeartypeDecorHintRecursionException
        If the number of total reductions internally performed by the current
        call to this function exceeds the maximum. This exception guards against
        accidental infinite recursion between lower-level hint-specific reducers
        internally called by this higher-level hint-agnostic reducer.
    '''

    # ....................{ PREAMBLE                       }....................
    assert isinstance(arg_kind, NoneTypeOr[ArgKind]), (
        f'{repr(arg_kind)} neither argument kind nor "None".')
    assert isinstance(cls_stack, NoneTypeOr[tuple]), (
        f'{repr(cls_stack)} neither tuple nor "None".')
    assert isinstance(conf, BeartypeConf), f'{repr(conf)} not configuration.'
    assert isinstance(decor_meta, NoneTypeOr[BeartypeDecorMeta]), (
        f'{repr(hint_parent_sane)} neither decoration metadata nor "None".')
    assert isinstance(hint_parent_sane, NoneTypeOr[HintSane]), (
        f'{repr(hint_parent_sane)} neither sanified hint metadata nor "None".')
    assert isinstance(is_hint_ignorable_preserved, bool), (
        f'{repr(is_hint_ignorable_preserved)} not boolean.')
    assert isinstance(pith_name, NoneTypeOr[str]), (
        f'{repr(pith_name)} neither string nor "None".')
    assert isinstance(reductions_count, int), (
        f'{repr(reductions_count)} not integer.')
    assert isinstance(exception_prefix, str), (
        f'{repr(exception_prefix)} not string.')

    # ....................{ LOCALS                         }....................
    # Original unreduced hint passed to this reducer, preserved so as to be
    # embedded in human-readable exception messages.
    hint_old = hint

    # Currently reduced instance of this hint.
    hint_curr: Hint = hint

    # Currently reduced instance of either this hint *OR* metadata encapsulating
    # the sanification of this hint, initialized to this unreduced hint.
    hint_or_sane_curr: HintOrSane = hint

    # Previously reduced instance of either this hint *OR* metadata
    # encapsulating this hint, initialized to this unreduced hint.
    hint_or_sane_prev: HintOrSane = hint

    # Delete the passed "hint" parameter for safety. Permitting this parameter
    # to exist would only promote subtle lexical issues below, where the local
    # variable "hint_curr" is strongly preferred for disambiguity.
    del hint

    # ....................{ SEARCH                         }....................
    # Repeatedly reduce this hint to increasingly irreducible hints until this
    # hint is no longer reducible. This algorithm iteratively reduces this hint
    # with a battery of increasingly non-trivial reductions. For efficiency,
    # reductions are intentionally ordered from most to least efficient.
    while True:
        # ....................{ REDUCE                     }....................
        #FIXME: [SPEED] Optimize into a "while" loop, please. *sigh*
        # For each lower-level reducer...
        for hint_reducer in _HINT_REDUCERS:
            # print(f'[reduce_hint] Reducing {hint_curr} with parent {hint_parent_sane} via {hint_reducer}...')

            # Either:
            # * If this reducer reduces this hint:
            #   * If this reduction produced supplementary metadata, metadata
            #     encapsulating the reduction of this hint by this reducer.
            #   * Else, the reduced hint reduced by this reducer.
            # * Else, this unreduced hint as is.
            hint_or_sane_curr = hint_reducer(
                hint=hint_curr,
                hint_parent_sane=hint_parent_sane,
                arg_kind=arg_kind,
                cls_stack=cls_stack,
                conf=conf,
                decor_meta=decor_meta,
                hint_sign_seed=hint_sign_seed,
                pith_name=pith_name,
                reductions_count=reductions_count,
                exception_prefix=exception_prefix,
            )
            # print(f'[reduce_hint] Reduced to {hint_or_sane_curr}!')

            # If this reduced hint is *NOT* this unreduced hint, this reducer
            # reduced this hint. Halt reducing by these lower-level reducers,
            # enabling the outer loop to decide whether to continue reducing.
            if hint_or_sane_curr is not hint_curr:
                # If this hint reduces to the ignorable "HINT_SANE_IGNORABLE"
                # metadata singleton, then halt reducing immediately.
                #
                # Note that this is merely an optimization avoiding unnecessary
                # iteration. Without this test, hints reduced to this ignorable
                # singleton would require an additional loop through the
                # "_HINT_REDUCERS" tuple. This test elides that iteration.
                if hint_or_sane_curr is HINT_SANE_IGNORABLE:
                    # print(f'[reduce_hint] Ignorably reduced!')
                    return HINT_SANE_IGNORABLE
                # Else, this hint is currently unignorable.
                # print(f'[reduce_hint] Incrementally reduced!')

                # Halt reducing immediately.
                break
            # Else, this unreduced hint remains unmodified. Since this reducer
            # failed to reduce this hint, silently continue to the next reducer.
        # If the above iteration failed to "break", then this unreduced hint
        # remains unmodified across all lower-level reducers. This implies this
        # hint to now be irreducible. Halt reducing immediately.
        else:
            # print(f'[reduce_hint] Irreducible!')
            break
        # Else, the above iteration hit a "break". This hint was reduced by a
        # lower-level reducer above, implying that this hint *COULD* still be
        # reducible. Silently continue reducing.

        # ....................{ RESPOND                    }....................
        # Respond to the lower-level reduction performed above.

        # If reducing this hint generated supplementary metadata...
        if isinstance(hint_or_sane_curr, HintSane):
            # Extract the currently reduced hint from this metadata.
            hint_curr = hint_or_sane_curr.hint

            #FIXME: Should probably be performed down below outside this loop.
            # If this hint reduces to the ignorable "HINT_IGNORABLE"
            # singleton, then halt reducing immediately.
            #
            # Note that this is *NOT* merely an optimization avoiding
            # unnecessary iteration as above. While similar, this logic is
            # distinct from that above. This edge case arises when a reducer
            # avoids reducing to an ignorable hint to the higher-level ignorable
            # "HINT_SANE_IGNORABLE" metadata singleton but instead encapsulates
            # the lower-level "HINT_IGNORABLE" type hint singleton with a new
            # "HintSane" object providing unique metadata describing the ignored
            # type hint. That unique metadata enables parent reducers to
            # selectively decide how to handle ignorable child type hints.
            #
            # Examples include:
            # * The reduce_hint_pep484604() reducer for union type hints.
            if hint_curr is HINT_IGNORABLE:
                # Return either...
                return (
                    # If the caller requests that unique "HintSane" objects
                    # encapsulating the "HINT_IGNORABLE" singleton be preserved,
                    # do so by returning this metadata as is. Note that this is
                    # *NOT* what most callers expect and thus not the default;
                    hint_or_sane_curr
                    if is_hint_ignorable_preserved else
                    # Else, reduce this metadata to the standard ignorable
                    # "HINT_SANE_IGNORABLE" singleton describing ignorable
                    # hints. Note that this is what *MOST* callers expect and
                    # thus the default.
                    HINT_SANE_IGNORABLE
                )
            # Else, this hint does *NOT* reduce to the ignorable
            # "HINT_IGNORABLE" singleton. Ergo, this hint is unignorable.

            # Replace the sanified type hint metadata of the parent hint of this
            # hint by the sanified type hint metadata of this hint itself. Doing
            # so ensures that the next reducer passed the "hint_parent_sane"
            # parameter preserves this metadata during its reduction. Since the
            # most recent reducer call received the prior "hint_parent_sane"
            # parameter, that reducer has already safely preserved the parent
            # metadata by compositing that metadata into this
            # "hint_or_sane_curr" metadata that that reducer returned. Srsly.
            hint_parent_sane = hint_or_sane_curr
        # Else, reducing this hint did *NOT* generate supplementary metadata,
        # implying "hint_or_sane_curr" to be the currently reduced hint. In this
        # case, record this currently reduced hint.
        else:
            hint_curr = hint_or_sane_curr

        #FIXME: Should probably be performed above the prior "if" conditional.
        #FIXME: Currently unused, but useful. Could be required at some point.
        # If this currently reduced hint is exactly the previously reduced hint,
        # the above reducers failed to reduce this hint. Halt reducing entirely.
        #
        # Note that this is a rare (albeit valid) edge case that arises for
        # reducers that unconditionally create and return new... The above
        # "else:" block of the above "for hint_reducer in _HINT_REDUCERS:" loop
        # if hint_or_sane_curr == hint_or_sane_prev:
        #     break

        # ....................{ RECURSION                  }....................
        # Guard against infinite recursion in lower-level reductions with
        # human-readable exceptions.

        # Increment the current number of total reductions internally performed
        # by this call *BEFORE* detecting accidental recursion below.
        reductions_count += 1

        #FIXME: Unit test this, please. No idea how yet. I sigh. *sigh*
        # If the current number of total reductions internally performed
        # by this call exceeds the maximum, raise an exception.
        #
        # Note that this should *NEVER* happen, but probably nonetheless will.
        if reductions_count >= _REDUCTIONS_COUNT_MAX:  # pragma: no cover
            raise BeartypeDecorHintRecursionException(
                f'{exception_prefix}type hint {repr(hint_old)} irreducible. '
                f'Recursion detected when reducing between reduced type hints '
                f'{repr(hint_or_sane_curr)} and {repr(hint_or_sane_prev)}. '
                f'Please submit this exception traceback as a new issue '
                f'to our friendly issue tracker:\n'
                f'\t{URL_ISSUES}\n'
                f'Beartype thanks you for your noble (yet ultimately tragic) '
                f'sacrifice.'
            )
        # Else, the current number of total reductions internally performed
        # by this call is still less than the maximum. In this case, continue.

        # ....................{ PREPARE                    }....................
        # Prepare for the next iterative reduction of this "while" loop.

        # Previously reduced instance of this hint.
        hint_or_sane_prev = hint_or_sane_curr

        # Currently reduced instance of this hint, reverting back to the
        # currently visited hint in preparation for subsequent reduction.
        hint_or_sane_curr = hint_curr

    # ....................{ RETURN                         }....................
    # If this hint is *NOT* already sanified type hint metadata, this hint is
    # unignorable. Why? Because, if this hint were ignorable, this hint would
    # have been reduced to the "HINT_SANE_IGNORABLE" singleton. In this case...
    if not isinstance(hint_or_sane_curr, HintSane):
        # Encapsulate this hint with such metadata, defined as either...
        hint_or_sane_curr = (
            # If this hint has *NO* parent, this is a root hint. In this case,
            # the trivial metadata shallowly encapsulating this root hint;
            HintSane(hint_or_sane_curr)
            if hint_parent_sane is None else
            # Else, this hint has a parent. In this case, the non-trivial
            # metadata deeply encapsulating both this non-root hint *AND* all
            # metadata already associated with this parent hint.
            hint_parent_sane.permute_sane(hint=hint_or_sane_curr)
        )
    # Else, this hint is already sanified type hint metadata. In this case,
    # preserve this metadata as is.

    # Return this possibly reduced hint.
    return hint_or_sane_curr


def reduce_hint_child(hint: Hint, kwargs: DictStrToAny) -> HintSane:
    '''
    Lower-level child type hint reduced (i.e., converted) from the passed
    higher-level child type hint if reducible *or* this child type hint as is
    otherwise (i.e., if this child type hint is irreducible).

    This reducer is a convenience wrapper for the more general-purpose
    :func:`.reduce_hint` reducer, simplifying calls to that reducer when passed
    child hints.

    Parameters
    ----------
    hint : Hint
        Child type hint to be reduced.
    kwargs : DictStrToAny
        Keyword parameters to be passed after being unpacked to the lower-level
        :func:`.reduce_hint` reducer. For safety, this reducer silently ignores
        keyword parameters inapplicable to child hints. This includes:

        * ``arg_kind``, applicable *only* to root hints directly annotating
          callable parameters.
        * ``decor_meta``, applicable *only* to root hints directly annotating
          callable parameters or returns.
        * ``pith_name``, applicable *only* to root hints directly annotating
          callable parameters or returns.

    Returns
    -------
    HintSane
        Either:

        * If this hint is ignorable, :data:`.HINT_SANE_IGNORABLE`.
        * Else if this unignorable hint is reducible to another hint, metadata
          encapsulating this reduction.
        * Else, this unignorable hint is irreducible. In this case, metadata
          encapsulating this hint unmodified.
    '''

    # Remove all unsafe keyword parameters (i.e., parameters that are
    # inapplicable to child hints and thus *NOT* safely passable to the
    # subsequently called reduce_hint() function) from this dictionary.
    remove_mapping_keys(kwargs, _REDUCE_HINT_CHILD_ARG_NAMES_UNSAFE)

    # Return this child hint possibly reduced to a lower-level hint.
    return reduce_hint(hint=hint, **kwargs)

# ....................{ PRIVATE ~ reducers                 }....................
def _reduce_hint_cached(
    hint: Hint,
    hint_sign_seed: HintSignOrNoneOrSentinel,
    exception_prefix: str,
    **kwargs
) -> HintOrSane:
    '''
    Lower-level type hint reduced (i.e., converted) from the passed higher-level
    type hint if this hint is reducible by a **memoized reducer** (i.e.,
    lower-level reducer accepting *only* a passed hint and thus readily amenable
    to memoization) *or* this hint as is otherwise (i.e., if this hint is *not*
    reducible by a memoized reducer).

    Parameters
    ----------
    hint : Hint
        Type hint to be possibly reduced.
    hint_sign_seed : HintSignOrNoneOrSentinel
        Sign with which to seed (i.e., initialize) this reduction. See also the
        :func:`.reduce_hint` docstring for further details.
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

    All remaining keyword parameters are silently ignored.

    Returns
    -------
    HintOrSane
        Either:

        * If this hint is ignorable, :data:`.HINT_SANE_IGNORABLE`.
        * Else if this unignorable hint is reducible to another hint by a
          memoized reducer, metadata encapsulating this reduction.
        * Else, this hint unmodified as is.
    '''
    assert (
        hint_sign_seed is SENTINEL or
        isinstance(hint_sign_seed, NoneTypeOr[HintSign])
    ), (f'{repr(hint_sign_seed)} neither hint sign, "None", nor sentinel.')

    # Reduced hint to be returned, defaulting to the passed unreduced hint.
    hint_or_sane: HintOrSane = hint

    # Sign uniquely identifying this hint if this hint is PEP-compliant *OR*
    # "None" otherwise (e.g., if this hint is PEP-noncompliant), defined as
    # either...
    hint_sign = (
        # If the caller did *NOT* explicitly pass a sign with which to seed this
        # reduction, the standard sign uniquely identifying this hint;
        get_hint_pep_sign_or_none(hint)
        if hint_sign_seed is SENTINEL else
        # Else, the caller explicitly passed a sign with which to seed this
        # reduction. In this case, that sign.
        hint_sign_seed
    )

    # Memoized reducer reducing this hint if any *OR* "None" otherwise.
    hint_reducer_cached = HINT_SIGN_TO_REDUCE_HINT_CACHED_get(hint_sign)  # type: ignore[arg-type]

    # If a memoized reducer reduces this hint...
    if hint_reducer_cached is not None:
        # print(f'[_reduce_hint_cached] Reducing cached hint {repr(hint)}...')

        #FIXME: [SPEED] Is there any point to passing the "exception_prefix"
        #parameter? Possibly. Not sure. Isn't this parameter a constant? No?
        #Does it actually vary with context? Can't recall. Investigate up!

        # Reduce this hint by calling this reducer.
        #
        # Note that parameters are intentionally passed positionally to this
        # possibly memoized callable prohibiting keyword parameters.
        hint_or_sane = hint_reducer_cached(hint, exception_prefix)
    # Else, *NO* memoized reducer reduces this hint. In this case, preserve this
    # hint as is.

    # Return this possibly reduced hint.
    return hint_or_sane


def _reduce_hint_uncached(
    hint: Hint,
    hint_sign_seed: HintSignOrNoneOrSentinel,
    **kwargs
) -> HintOrSane:
    '''
    Lower-level type hint reduced (i.e., converted) from the passed higher-level
    type hint if this hint is reducible by a **unmemoized reducer** (i.e.,
    lower-level reducer accepting *only* a passed hint and thus readily amenable
    to memoization) *or* this hint as is otherwise (i.e., if this hint is *not*
    reducible by a unmemoized reducer).

    Parameters
    ----------
    hint : Hint
        Type hint to be possibly reduced.
    hint_sign_seed : HintSignOrNoneOrSentinel
        Sign with which to seed (i.e., initialize) this reduction. See also the
        :func:`.reduce_hint` docstring for further details.

    All remaining keyword parameters are silently ignored.

    Returns
    -------
    HintOrSane
        Either:

        * If this hint is ignorable, :data:`.HINT_SANE_IGNORABLE`.
        * Else if this unignorable hint is reducible to another hint by a
          unmemoized reducer, metadata encapsulating this reduction.
        * Else, this hint unmodified as is.
    '''
    assert (
        hint_sign_seed is SENTINEL or
        isinstance(hint_sign_seed, NoneTypeOr[HintSign])
    ), (f'{repr(hint_sign_seed)} neither hint sign, "None", nor sentinel.')

    # Reduced hint to be returned, defaulting to the passed unreduced hint.
    hint_or_sane: HintOrSane = hint

    # Sign uniquely identifying this hint if this hint is PEP-compliant *OR*
    # "None" otherwise (e.g., if this hint is PEP-noncompliant), defined as
    # either...
    hint_sign = (
        # If the caller did *NOT* explicitly pass a sign with which to seed this
        # reduction, the standard sign uniquely identifying this hint;
        get_hint_pep_sign_or_none(hint)
        if hint_sign_seed is SENTINEL else
        # Else, the caller explicitly passed a sign with which to seed this
        # reduction. In this case, that sign.
        hint_sign_seed
    )

    # Unmemoized reducer reducing this hint if any *OR* "None" otherwise.
    hint_reducer_uncached = HINT_SIGN_TO_REDUCE_HINT_UNCACHED_get(hint_sign)  # type: ignore[arg-type]

    # If a unmemoized reducer reduces this hint...
    if hint_reducer_uncached is not None:
        # print(f'[_reduce_hint_cached] Reducing cached hint {repr(hint)}...')

        # Reduce this hint by calling this reducer.
        hint_or_sane = hint_reducer_uncached(hint=hint, **kwargs)
    # Else, *NO* unmemoized reducer reduces this hint. In this case, preserve
    # this hint as is.

    # Return this possibly reduced hint.
    return hint_or_sane


def _reduce_hint_overrides(
    hint: Hint,
    conf: BeartypeConf,
    hint_parent_sane: Optional[HintSane],
    **kwargs
) -> HintOrSane:
    '''
    Lower-level type hint reduced (i.e., converted) from the passed higher-level
    type hint if this hint is reducible as a **hint override** (i.e., key of
    the :attr:`.BeartypeConf.hint_overrides` dictionary of the passed beartype
    configuration) *or* this hint as is otherwise (i.e., if this hint is *not*
    as a hint override).

    Parameters
    ----------
    hint : Hint
        Type hint to be possibly reduced.
    conf : BeartypeConf
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all settings configuring type-checking for the passed object).
    hint_parent_sane : Optional[HintSane]
        Either:

        * If the passed hint is a **root** (i.e., top-most parent hint of a tree
          of child hints), :data:`None`.
        * Else, the passed hint is a **child** of some parent hint. In this
          case, the **sanified parent type hint metadata** (i.e., immutable and
          thus hashable object encapsulating *all* metadata previously returned
          by :mod:`beartype._check.convert.convmain` sanifiers after
          sanitizing the possibly PEP-noncompliant parent hint of this child
          hint into a fully PEP-compliant parent hint).

    All remaining keyword parameters are silently ignored.

    Returns
    -------
    HintOrSane
        Either:

        * If this hint has already been overridden by a prior recursive
          reduction in the current tree of reductions, this hint before being
          overridden yet again (i.e., this hint as is).
        * Else if this unignorable hint is overridden by another hint, metadata
          encapsulating this override.
        * Else, this unignorable hint is *not* overridden by another hint, this
          hint as is.
    '''

    # Overridden hint to be returned, defaulting to the passed un-overridden
    # hint for safety and simplicity.
    hint_or_sane: HintOrSane = hint

    # Attempt to...
    #
    # Note that the is_object_hashable() tester is internally implemented with
    # the same Easier to Ask for Permission than Forgiveness (EAFP)-based
    # "try-except" block and is thus equally inefficient. In fact, the current
    # approach avoids an extraneous call to that tester and is thus marginally
    # faster. (Emphasis on "marginally.")
    try:
        # Hint overriding this hint if this configuration overrides this hint
        # *OR* the sentinel otherwise (i.e., if this hist is *NOT* overridden).
        #
        # Note that this raises "TypeError" when this hint is unhashable.
        # print(f'Overriding hint {repr(hint)} via {repr(conf.hint_overrides)}...')
        hint_overridden = conf.hint_overrides.get(hint, SENTINEL)

        # If neither...
        if not (
            # This hint is not overridden *NOR*...
            hint_overridden is SENTINEL or
            # Else, this hint is overridden.
            #
            # If this overridden hint is recursive, this hint has already been
            # overridden by a previously performed reduction. Avoid attempting
            # to reoverride this hint again with the same hint override; doing
            # so would provoke infinite recursion. Instead, preserve this
            # un-overridden hint by returning this hint as is.
            #
            # Certainly, various approaches to type-checking recursive hints
            # exists. @beartype currently embraces the easiest, fastest, and
            # laziest approach: just ignore all recursion! \o/
            #
            # Note that:
            # * This tester raises "TypeError" when this hint is unhashable.
            # * This tester intentionally accepts the default value "0" for the
            #   optional parameter "hint_recursable_depth_max", ensuring this
            #   overridden hint is considered to be recursive when this
            #   overridden hint has already been overridden a single time.
            #   Unlike comparable kinds of recursable hints (e.g., PEP
            #   695-compliant type aliases), hint overrides typically convey
            #   *NO* internal structure and thus merit *NO* deeper recursion.
            #   Hint overrides instruct @beartype to perform simple
            #   global-search-and-replacements on exactly matching type hints.
            #   Recursion is neither desirable nor necessary.
            #
            #   Consider the prototypical hint overrides of
            #   "BeartypeConf(hint_overrides={float: float | int})". After
            #   expanding the builtin "float" type to the PEP 604-compliant
            #   union "float | int", attempting to recursively re-apply the same
            #   expansion silently reduces to a noop (e.g., "float | int"
            #   expands to "float | float | int", equal to "float | int").
            is_hint_recursive(hint=hint, hint_parent_sane=hint_parent_sane)
        ):
            # Then this overridden hint is *NOT* recursive, implying this hint
            # *CANNOT* have already been overridden by a previously performed
            # reduction. Why? Because an overridden hint revisited by the
            # current breadth-first search would by definition by recursive.

            # Metadata guarding this hint against infinite recursion, recording
            # this hint as already having been overridden *BEFORE* reducing and
            # thus forgetting this hint.
            #
            # Note that this intentionally replaces the metadata encapsulating
            # the sanification of the parent hint of this hint by the metadata
            # encapsulating the sanification of this hint itself. Doing so
            # ensures that the next reducer passed the "hint_parent_sane"
            # parameter preserves this metadata during its reduction. Since the
            # most recent reducer call received the prior "hint_parent_sane"
            # parameter, that reducer has already safely preserved the parent
            # metadata by compositing that metadata into this
            # "hint_or_sane_curr" metadata that that reducer returned. Srsly.
            hint_or_sane = make_hint_sane_recursable(
                # The recursable form of this overridden hint is the
                # pre-overridden hint tested above by the is_hint_recursive()
                # recursion guard.
                hint_recursable=hint,
                # The non-recursable form of this overridden hint is the
                # overridden hint encapsulated by the metadata returned by this
                # factory.
                hint_nonrecursable=hint_overridden,
                hint_parent_sane=hint_parent_sane,
            )
        # Else, this overridden hint is recursive. In this case, preserve this
        # un-overridden hint rather than reducing this hint to the ignorable
        # "HINT_SANE_IGNORABLE" singleton. Why? Because un-overridden hints are
        # themselves valid type hints and thus have semantic meaning in and of
        # themselves (e.g., the "float" in the hint override
        # "BeartypeConf(hint_overrides={float: float | int})" has semantic
        # meaning as a builtin type).
    # If doing so raises a "TypeError", this hint is unhashable and thus
    # inapplicable for hint overriding. In this case, preserve this hint as is.
    except TypeError:
        pass

    # Return this possibly overridden hint.
    return hint_or_sane

# ....................{ PRIVATE ~ globals                  }....................
_HINT_REDUCERS = (
    # ....................{ PHASE ~ override               }....................
    # Attempt to reduce this hint to another hint configured by a user-defined
    # hint override *BEFORE* applying standard reductions. User preference
    # assumes precedence over standard precedent. Nice one-liner, huh? </heh>
    _reduce_hint_overrides,

    # ....................{ PHASE ~ context-free           }....................
    # Attempt to reduce this hint with a context-free reduction *BEFORE*
    # reducing this hint with a contextual reduction. Due to *NOT* depending on
    # contextual state, context-free reductions are readily memoizable and thus
    # faster than contextual reductions.
    _reduce_hint_cached,

    # ....................{ PHASE ~ contextual             }....................
    # Attempt to reduce this hint with a contextual reduction. Due to depending
    # on contextual state, contextual reductions are *NOT* be readily memoizable
    # and thus slower than context-free reductions.
    _reduce_hint_uncached,
)
'''
Tuple of all private high-level reducers defined by this submodule above.
'''


_REDUCTIONS_COUNT_MAX = 64
'''
Maximum number of total reductions internally performed by each call of the
:func:`reduce_hint` function.

This constant is a relatively arbitrary magic number selected so as to guard
against accidental infinite recursion between lower-level PEP-specific reducers
internally called by :func:`reduce_hint`.
'''


_REDUCE_HINT_CHILD_ARG_NAMES_UNSAFE = frozenset((
    # Applicable *ONLY* to root hints directly annotating callable parameters.
    'arg_kind',

    # Applicable *ONLY* to root hints directly annotating callable parameters
    # or returns.
    'decor_meta',
    'pith_name',
))
'''
Frozen set of the names of all **unsafe child type hint reducer keyword
parameters** (i.e., keyword parameters inapplicable to child type hints and thus
*not* safely passable from the higher-level :func:`.reduce_hint_child` to
lower-level :func:`.reduce_hint` reducer.
'''
