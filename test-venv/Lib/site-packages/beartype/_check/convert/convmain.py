#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **PEP-agnostic type hint sanitizers** (i.e., high-level callables
converting type hints from one format into another, either permanently or
temporarily and either losslessly or in a lossy manner).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import Optional
from beartype._cave._cavemap import NoneTypeOr
from beartype._check.convert._convcoerce import (
    coerce_func_hint_root,
    coerce_hint_root,
)
from beartype._check.convert._reduce.redmain import reduce_hint
from beartype._check.metadata.hint.hintsane import HintSane
from beartype._check.metadata.metadecor import BeartypeDecorMeta
from beartype._conf.confmain import BeartypeConf
from beartype._conf.confcommon import BEARTYPE_CONF_DEFAULT
from beartype._data.error.dataerrmagic import EXCEPTION_PLACEHOLDER
from beartype._data.func.datafuncarg import ARG_NAME_RETURN
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.kind.datakindiota import SENTINEL
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import (
    HintSignOrNoneOrSentinel,
    TypeStack,
)
from beartype._util.func.arg.utilfuncargiter import ArgKind
from beartype._util.hint.pep.proposal.pep484585.pep484585func import (
    reduce_hint_pep484585_func_return)

# ....................{ SANIFIERS ~ root                   }....................
#FIXME: Unit test us up, please.
def sanify_hint_root_func(
    # Mandatory parameters.
    decor_meta: BeartypeDecorMeta,
    hint: Hint,
    pith_name: str,

    # Optional parameters.
    arg_kind: Optional[ArgKind] = None,
    exception_prefix: str = EXCEPTION_PLACEHOLDER,
) -> HintSane:
    '''
    Type hint sanified (i.e., sanitized) from the passed **possibly insane root
    type hint** (i.e., possibly PEP-noncompliant hint annotating the parameter
    or return with the passed name of the passed callable) if this hint is both
    reducible and unignorable, this hint unmodified if this hint is both
    irreducible and unignorable, or :data:`.HINT_SANE_IGNORABLE` otherwise (i.e., if
    this hint is ignorable).

    Specifically, this function:

    * If this hint is a **PEP-noncompliant tuple union** (i.e., tuple of one or
      more standard classes and forward references to standard classes):

      * Coerces this tuple union into the equivalent :pep:`484`-compliant
        union.
      * Replaces this tuple union in the ``__annotations__`` dunder tuple of
        this callable with this :pep:`484`-compliant union.
      * Returns this :pep:`484`-compliant union.

    * Else if this hint is already PEP-compliant, preserves and returns this
      hint unmodified as is.
    * Else (i.e., if this hint is neither PEP-compliant nor -noncompliant and
      thus invalid as a type hint), raise an exception.

    Caveats
    -------
    This sanifier *cannot* be meaningfully memoized, since the passed type hint
    is *not* guaranteed to be cached somewhere. Only functions passed cached
    type hints can be meaningfully memoized. Even if this function *could* be
    meaningfully memoized, there would be no benefit; this function is only
    called once per parameter or return of the currently decorated callable.

    This sanifier is intended to be called *after* all possibly
    :pep:`563`-compliant **deferred type hints** (i.e., type hints persisted as
    evaluatable strings rather than actual type hints) annotating this callable
    if any have been evaluated into actual type hints.

    Parameters
    ----------
    decor_meta : BeartypeDecorMeta
        Decorated callable directly annotated by this hint.
    hint : Hint
        Possibly PEP-noncompliant root type hint to be sanified.
    pith_name : str
        Either:

        * If this hint annotates a parameter, the name of that parameter.
        * If this hint annotates the return, ``"return"``.
    arg_kind : Optional[ArgKind]
        Either:

        * If this hint annotates a parameter, that parameter's **kind** (i.e.,
          :class:`.ArgKind` enumeration member conveying the syntactic class of
          that parameter, constraining how the callable declaring that parameter
          requires that parameter to be passed).
        * If this hint annotates the return, :data:`None`.

        Defaults to :data:`None`.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to :data:`.EXCEPTION_PLACEHOLDER`.

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
    BeartypeDecorHintNonpepException
        If this object is neither:

        * A PEP-noncompliant type hint.
        * A supported PEP-compliant type hint.
    '''
    assert isinstance(arg_kind, NoneTypeOr[ArgKind]), (
        f'{repr(arg_kind)} neither argument kind nor "None".')

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Synchronize with the sanify_hint_root_statement() sanitizer.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # PEP-compliant hint coerced from this possibly PEP-noncompliant hint if
    # this hint is coercible *OR* this hint as is otherwise. Since the passed
    # hint is *NOT* necessarily PEP-compliant, perform this coercion *BEFORE*
    # validating this hint to be PEP-compliant.
    hint_coerced = coerce_func_hint_root(
        decor_meta=decor_meta,
        hint=hint,
        pith_name=pith_name,
        exception_prefix=exception_prefix,
    )

    # If this possibly PEP-noncompliant hint was actually coerced into a
    # PEP-compliant hint...
    if hint_coerced is not hint:
        # Note this coercion.
        hint = hint_coerced

        # Safely set the hint annotating the parameter or return with the passed
        # name of the decorated callable to the passed hint in a portable manner
        # consistent with both PEP 649 and Python >= 3.14.
        decor_meta.set_func_pith_hint(pith_name=pith_name, hint=hint)
    # Else, this possibly PEP-noncompliant hint was *NOT* coerced into a
    # PEP-compliant hint, implying this hint to already be PEP-compliant.

    # If this hint annotates the return, then (in order):
    # * If this hint is contextually invalid for this callable (e.g., generator
    #   whose return is not annotated as "Generator[...]"), raise an exception.
    # * If this hint is either PEP 484- or 585-compliant *AND* requires
    #   reduction (e.g., from "Coroutine[None, None, str]" to just "str"),
    #   reduce this hint accordingly.
    #
    # Perform this reduction *BEFORE* performing subsequent tests (e.g., to
    # accept "Coroutine[None, None, typing.NoReturn]" as expected). Note that
    # this logic *ONLY* pertains to callables (rather than statements) and is
    # thus *NOT* performed by the sanify_hint_root_statement() sanitizer.
    if pith_name == ARG_NAME_RETURN:
        hint = reduce_hint_pep484585_func_return(
            func=decor_meta.func_wrappee,
            func_annotations=decor_meta.func_annotations,
            exception_prefix=exception_prefix,
        )
    # Else, this hint annotates a parameter.

    # Sane child hint reduced from this possibly insane child hint if reducing
    # this hint did not generate supplementary metadata *OR* that metadata
    # otherwise (i.e., if reducing this hint generated supplementary metadata).
    # Reductions simplify subsequent logic elsewhere by transparently converting
    # non-trivial hints (e.g., numpy.typing.NDArray[...]) into semantically
    # equivalent trivial hints (e.g., beartype validators).
    #
    # Whereas the above coercion permanently persists for the duration of the
    # active Python process (i.e., by replacing the original type hint in the
    # annotations dunder dictionary of this callable), this reduction only
    # temporarily persists for the duration of the current call stack. Why?
    # Because hints explicitly coerced above are assumed to be either:
    # * PEP-noncompliant and thus harmful (in the general sense).
    # * PEP-compliant but semantically deficient and thus equally harmful (in
    #   the general sense).
    #
    # In either case, coerced type hints are generally harmful in *ALL* possible
    # contexts for *ALL* possible consumers (including other competing runtime
    # type-checkers). Reduced type hints, however, are *NOT* harmful in any
    # sense whatsoever; they're simply non-trivial for @beartype to support in
    # their current form and thus temporarily reduced in-memory into a more
    # convenient form for beartype-specific type-checking elsewhere.
    hint_sane = reduce_hint(
        hint=hint,
        conf=decor_meta.conf,
        decor_meta=decor_meta,
        arg_kind=arg_kind,
        cls_stack=decor_meta.cls_stack,
        pith_name=pith_name,
        exception_prefix=exception_prefix,
    )

    # Return this hint if this hint is unignorable *OR* "typing.Any" otherwise.
    return hint_sane


#FIXME: Unit test us up, please.
def sanify_hint_root_statement(
    hint: Hint,
    conf: BeartypeConf,
    exception_prefix: str,
) -> HintSane:
    '''
    PEP-compliant type hint sanified (i.e., sanitized) from the passed **root
    type hint** (i.e., possibly PEP-noncompliant type hint that has *no* parent
    type hint) if this hint is both reducible and unignorable, this hint
    unmodified if this hint is both irreducible and unignorable, or
    :data:`.HINT_SANE_IGNORABLE` otherwise (i.e., if this hint is ignorable).

    This sanifier is principally intended to be called by a **statement-level
    type-checker factory** (i.e., a function creating and returning a runtime
    type-checker type-checking this hint, outside the context of any standard
    type hinting annotation like a user-defined class variable, callable
    parameter or return, or assignment statement). Such factories include:

    * The private :func:`beartype._check.checkmake.make_func_tester` factory,
      internally called by:

      * The public :func:`beartype.door.die_if_unbearable` function.
      * The public :func:`beartype.door.is_bearable` function.
      * The public :meth:`beartype.door.TypeHint.die_if_unbearable` method.
      * The public :meth:`beartype.door.TypeHint.is_bearable` method.

    Parameters
    ----------
    hint : Hint
        Possibly PEP-noncompliant root type hint to be sanified.
    conf : BeartypeConf
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all settings configuring type-checking for the passed object).
    exception_prefix : str
        Human-readable substring prefixing raised exception messages.

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
    BeartypeDecorHintNonpepException
        If this object is neither:

        * A PEP-noncompliant type hint.
        * A supported PEP-compliant type hint.

    See Also
    --------
    :func:`.sanify_hint_root_func`
        Further details.
    '''

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Synchronize with the sanify_hint_root_func() sanitizer, please.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # PEP-compliant type hint coerced from this possibly PEP-noncompliant type
    # hint if this hint is coercible *OR* this hint as is otherwise. Since the
    # passed hint is *NOT* necessarily PEP-compliant, perform this coercion
    # *BEFORE* validating this hint to be PEP-compliant.
    hint = coerce_hint_root(hint=hint, exception_prefix=exception_prefix)

    # Metadata encapsulating the sanification of this hint.
    hint_sane = reduce_hint(
        hint=hint, conf=conf, exception_prefix=exception_prefix)

    # Return this metadat.
    return hint_sane

# ....................{ SANIFIERS ~ any                    }....................
#FIXME: This function accepting a "pith_name" parameter is *SUPER-WEIRD.* If
#this function did *NOT* accept a "pith_name" parameter, then the implementation
#could internally reduce to calling the safer reduce_hint_child() function.
#Instead, the current implementation has *NO* choice but to call the less safe
#reduce_hint() function. Clearly, the docstring below suggests this has
#something suspicious to do with error-handling. Investigate, please. *sigh*
#FIXME: Unit test us up, please.
def sanify_hint_child(
    # Mandatory parameters.
    hint: Hint,
    hint_parent_sane: Optional[HintSane],

    # Optional parameters.
    cls_stack: TypeStack = None,
    conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
    hint_sign_seed: HintSignOrNoneOrSentinel = SENTINEL,
    pith_name: Optional[str] = None,
    exception_prefix: str = '',
) -> HintSane:
    '''
    Metadata encapsulating the sanification (i.e., sanitization) of the passed
    **possibly insane child type hint** (i.e., possibly PEP-noncompliant hint
    transitively subscripting the root hint annotating a parameter or return of
    the currently decorated callable) if this hint is both reducible and
    unignorable, this hint unmodified if this hint is both irreducible and
    unignorable, or :obj:`.HINT_SANE_IGNORABLE` otherwise (i.e., if this hint is
    ignorable).

    Parameters
    ----------
    hint : Hint
        Child type hint to be sanified.
    hint_parent_sane : Optional[HintSane]
        Either:

        * If this hint is actually a **root type hint,** :data:`None`.
        * Else, **Sanified parent type hint metadata** (i.e., immutable and thus
          hashable object encapsulating *all* metadata previously returned by
          :mod:`beartype._check.convert.convmain` sanifiers after sanitizing
          the possibly PEP-noncompliant parent hint of this child hint into a
          fully PEP-compliant parent hint).
    cls_stack : TypeStack, default: None
        **Type stack** (i.e., either a tuple of the one or more
        :func:`beartype.beartype`-decorated classes lexically containing the
        class variable or method annotated by this hint *or* :data:`None`).
        Defaults to :data:`None`.
    conf : BeartypeConf, default: BEARTYPE_CONF_DEFAULT
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all settings configuring type-checking for the passed object). Defaults
        to :obj:`.BEARTYPE_CONF_DEFAULT`, the default beartype configuration.
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
    pith_name : Optional[str], default: None
        Either:

        * If this hint directly annotates a callable parameter (as the root type
          hint of that parameter), the name of this parameter.
        * If this hint directly annotates a callable return (as the root type
          hint of that return), the magic string ``"return"``.
        * Else, :data:`None`.

        Note that:

        * This parameter should only be passed during exception raising (i.e.,
          from within the :func:`beartype._check.error` subpackage).
        * This parameter should *never* be passed during code generation (i.e.,
          by the :func:`beartype._check.code.codemain.make_check_expr` code
          factory).

        Defaults to :data:`None`.
    exception_prefix : str, default: ''
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
    '''
    # print(f'Sanifying child hint {repr(hint)} with type variable lookup table {repr(typearg_to_hint)}...')

    # This sanifier covers the proper subset of logic performed by the
    # sanify_hint_root_statement() sanifier applicable to child type hints.
    #
    # Note that this subset is currently the lower-level reduce_hint() reducer.
    # Technically, this implies that this sanifier could simply be a trivial
    # alias of that reducer. Pragmatically, doing so would only negligibly
    # improve decoration-time speed (which is *SORTA* good) while demonstrably
    # harming code maintainability (which is *DEFINITELY* bad). Ergo, we
    # intentionally maintain this sanifier as a distinct and separate function.
    # You'll thank me ten years from now, older self. *high five*

    # Metadata encapsulating the sanification of this child hint.
    #
    # Note that this function intentionally performs *NO* hint coercion (e.g.,
    # by calling the coerce_hint_any() coercer). Although feasible, doing so
    # would be pointless. Why? Because hint coercion coerces unmemoized hints
    # into memoized hints as a means of deduplicating hints across
    # "__annotations__" dunder dictionaries. However, there exists *NO*
    # "__annotations__" dunder dictionary to deduplicate across here. There
    # exists *NO* space to be compacted here and thus *NO* demonstrable
    # reason to perform hint coercion.
    hint_sane = reduce_hint(
        hint=hint,
        hint_parent_sane=hint_parent_sane,
        hint_sign_seed=hint_sign_seed,
        conf=conf,
        cls_stack=cls_stack,
        pith_name=pith_name,
        exception_prefix=exception_prefix,
    )
    # print(f'[sanify] Detecting hint {repr(hint)} reduction {repr(hint_sane)} ignorability...')

    # Return this metadata.
    return hint_sane


def sanify_hint_any(
    # Mandatory parameters.
    hint: Hint,

    # Optional parameters.
    hint_parent_sane: Optional[HintSane] = None,
    **kwargs
) -> HintSane:
    '''
    Metadata encapsulating the sanification (i.e., sanitization) of the passed
    **possibly insane type hint** (i.e., possibly PEP-noncompliant hint
    transitively subscripting the root hint annotating a parameter or return of
    the currently decorated callable) if this hint is both reducible and
    unignorable, this hint unmodified if this hint is both irreducible and
    unignorable, or :obj:`.HINT_SANE_IGNORABLE` otherwise (i.e., if this hint is
    ignorable).

    Caveats
    -------
    **The more fine-grained** :func:`.sanify_hint_child` **sanifier should
    typically be called instead.** This more coarse-grained sanifier drops the
    mandatory ``hint_parent_sane`` parameter required by the former, which is
    *not* necessarily a good thing. That parameter should typically be passed.
    Failing to pass that parameter drops essential metadata required to properly
    sanitize many insane type hints.

    Parameters
    ----------
    hint : Hint
        Child type hint to be sanified.
    hint_parent_sane : Optional[HintSane], default: None
        Either:

        * If this hint is actually a **root type hint,** :data:`None`.
        * Else, **Sanified parent type hint metadata** (i.e., immutable and thus
          hashable object encapsulating *all* metadata previously returned by
          :mod:`beartype._check.convert.convmain` sanifiers after sanitizing
          the possibly PEP-noncompliant parent hint of this child hint into a
          fully PEP-compliant parent hint).

        Defaults to :data:`None`.

    All remaining keyword parameters are as accepted by the comparable
    :func:`.sanify_hint_child` sanifier.

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

    # Defer to our betters.
    return sanify_hint_child(
        hint=hint, hint_parent_sane=hint_parent_sane, **kwargs)
