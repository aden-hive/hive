#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype decorator return code generator** (i.e., low-level callables
dynamically generating Python expressions type-checking the annotated return of
the callable currently being decorated by the :func:`beartype.beartype`
decorator in a general-purpose manner).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._check.checkmake import (
    make_code_raiser_func_pith_check,
    make_code_raiser_func_pep484_noreturn_check,
)
from beartype._check.convert.convmain import sanify_hint_root_func
from beartype._check.metadata.hint.hintsane import HINT_SANE_IGNORABLE
from beartype._check.metadata.metadecor import BeartypeDecorMeta
from beartype._data.code.pep.datacodepep484 import PEP484_CODE_CHECK_NORETURN
from beartype._data.error.dataerrmagic import EXCEPTION_PLACEHOLDER
from beartype._data.func.datafuncarg import (
    ARG_NAME_RETURN,
    ARG_NAME_RETURN_REPR,
)
from beartype._data.typing.datatyping import LexicalScope
from beartype._data.typing.datatypingport import Hint
from beartype._data.code.datacodefunc import CODE_CALL_CHECKED_format
from beartype._decor._nontype._wrap._wraputil import unmemoize_func_wrapper_code
from beartype._util.error.utilerrraise import reraise_exception_placeholder
from beartype._util.error.utilerrwarn import reissue_warnings_placeholder
from beartype._util.hint.utilhinttest import is_hint_needs_cls_stack
from beartype._util.kind.maplike.utilmapset import update_mapping
from beartype._util.text.utiltextprefix import prefix_callable_return
from beartype._data.kind.datakindiota import SENTINEL
from typing import NoReturn
from warnings import catch_warnings

# ....................{ CODERS                             }....................
def code_check_return(decor_meta: BeartypeDecorMeta) -> str:
    '''
    Generate a Python code snippet type-checking the annotated return declared
    by the decorated callable if any *or* the empty string otherwise (i.e., if
    this return is unannotated).

    Parameters
    ----------
    decor_meta : BeartypeDecorMeta
        Decorated callable to be type-checked.

    Returns
    -------
    str
        Code type-checking any annotated return of the decorated callable.

    Raises
    ------
    BeartypeDecorHintPep484585Exception
        If this callable is either:

        * A coroutine *not* annotated by a :obj:`typing.Coroutine` type hint.
        * A generator *not* annotated by a :obj:`typing.Generator` type hint.
        * An asynchronous generator *not* annotated by a
          :obj:`typing.AsyncGenerator` type hint.
    BeartypeDecorHintNonpepException
        If the type hint annotating this return (if any) of this callable is
        neither:

        * **PEP-compliant** (i.e., :mod:`beartype`-agnostic hint compliant with
          annotation-centric PEPs).
        * **PEP-noncompliant** (i.e., :mod:`beartype`-specific type hint *not*
          compliant with annotation-centric PEPs)).
    '''
    assert isinstance(decor_meta, BeartypeDecorMeta), (
        f'{repr(decor_meta)} not beartype call.')

    # ..................{ LOCALS                             }..................
    # Possibly insane hint annotating this callable's return if any *OR* the
    # sentinel placeholder otherwise (i.e., if this return is unannotated).
    #
    # Note that "None" is a semantically meaningful PEP 484-compliant hint
    # equivalent to "type(None)". Ergo, we *MUST* explicitly distinguish between
    # "None" and an unannotated return with a sentinel.
    hint_insane: Hint = decor_meta.func_annotations_get(  # type: ignore[assignment]
        ARG_NAME_RETURN, SENTINEL)
    # print(f'func {decor_meta} return hint_insane: {hint_insane}')

    # If this return is unannotated, silently reduce to a noop.
    if hint_insane is SENTINEL:
        return ''
    # Else, this return is annotated.

    # Python code snippet to be returned, defaulting to the empty string
    # implying this callable's return to either be unannotated *OR* annotated by
    # a safely ignorable type hint.
    func_wrapper_code = ''

    # Lexical scope (i.e., dictionary mapping from the relative unqualified name
    # to value of each locally or globally scoped attribute accessible to a
    # callable or class), initialized to "None" for safety.
    func_scope: LexicalScope = None  # type: ignore[assignment]

    # ..................{ GENERATE                           }..................
    # Attempt to...
    try:
        # With a context manager "catching" *ALL* non-fatal warnings emitted
        # during this logic for subsequent "playback" below...
        with catch_warnings(record=True) as warnings_issued:
            # Sanified hint metadata sanified from this possibly insane return.
            # If this hint is unsupported by @beartype, raise an exception.
            #
            # Note that:
            # * This hint must sanitized *BEFORE* testing this hint. Why? The
            #   PEP 484-compliant "typing.NoReturn" return hint in conjunction
            #   with PEP 563. If this return hint is "typing.NoReturn" *AND*
            #   this submodule enables PEP 563 via "from __future__ import
            #   annotations, then this hint will be the useless string
            #   "NoReturn" rather than the useful hint "typing.NoReturn". In
            #   this case, this hist *MUST* be sanitized first; doing so
            #   destringifies this string into a usable hint, enabling this hint
            #   to then be detected below.
            # * For the exact same reason, this sanitization *CANNOT* be
            #   performed in the low-level make_check_expr() dynamically
            #   generating code type-checking this hint.
            # print(f'Sanifying {repr(decor_meta)} return hint {repr(hint_insane)}...')
            hint_sane = sanify_hint_root_func(
                decor_meta=decor_meta,
                hint=hint_insane,
                pith_name=ARG_NAME_RETURN,
                exception_prefix=EXCEPTION_PLACEHOLDER,
            )
            # print(f'Sanified {repr(decor_meta)} return hint {repr(hint_insane)} to {repr(hint_sane)}.')

            # If this is the PEP 484-compliant "typing.NoReturn" type hint
            # allowed *ONLY* as a return annotation...
            if hint_sane.hint is NoReturn:
                # Pre-generated code snippet validating this callable to *NEVER*
                # successfully return by unconditionally generating a violation.
                code_noreturn_check = PEP484_CODE_CHECK_NORETURN.format(
                    func_call_prefix=decor_meta.func_wrapper_code_call_prefix)

                # Code snippet handling the previously generated violation by
                # either raising that violation as a fatal exception or emitting
                # that violation as a non-fatal warning.
                (
                    code_noreturn_violation,
                    func_scope,
                    _
                ) = make_code_raiser_func_pep484_noreturn_check(decor_meta.conf)

                # Full code snippet to be returned.
                func_wrapper_code = (
                    f'{code_noreturn_check}{code_noreturn_violation}')
            # Else, this is *NOT* "typing.NoReturn".
            #
            # If this hint is unignorable...
            elif hint_sane is not HINT_SANE_IGNORABLE:
                #FIXME: DRY violation. The same logic appears in "_wrapargs" as
                #well. It looks like what we *PROBABLY* want to do here is:
                #* Rename the existing make_code_raiser_func_pith_check()
                #  factory to _make_code_raiser_func_pith_check_cached().
                #* Define a new make_code_raiser_func_pith_check() factory that
                #  is unmemoized and has a simpler public API. Notably, this new
                #  factory should:
                #  * Accept a new "decor_meta" parameter.
                #  * Drop the existing "conf" and "cls_stack" parameters.
                #  * Pass parameters by keyword rather than positionally. This
                #    would be especially useful for the "is_param" parameter,
                #    which would suddenly become readable below.
                #  * Internally compute the "cls_stack" as given below.

                # Type stack if required by this hint *OR* "None" otherwise.
                # See is_hint_needs_cls_stack() for details.
                #
                # Note that the original unsanitized "hint_insane" (e.g.,
                # "typing.Self") rather than the new sanitized "hint" (e.g.,
                # the class currently being decorated by @beartype) is
                # passed to that tester. See _code_check_args() for details.
                cls_stack = (
                    decor_meta.cls_stack
                    if is_hint_needs_cls_stack(hint_insane) else
                    None
                )
                # print(f'return hint {repr(hint_insane)} -> {repr(hint)} cls_stack: {repr(cls_stack)}')

                # Code snippet type-checking any arbitrary return.
                (
                    code_return_check_pith,
                    func_scope,
                    hint_refs_type_basename,
                ) = make_code_raiser_func_pith_check(  # type: ignore[assignment]
                    hint_sane,
                    decor_meta.conf,
                    cls_stack,
                    False,  # <-- True only for parameters
                )

                # Unmemoize this snippet against this return.
                code_return_check = unmemoize_func_wrapper_code(
                    decor_meta=decor_meta,
                    func_wrapper_code=code_return_check_pith,
                    pith_repr=ARG_NAME_RETURN_REPR,
                    hint_refs_type_basename=hint_refs_type_basename,
                )

                # Code snippets prefixing and suffixing the type-checking of
                # this return.
                code_return_check_prefix = CODE_CALL_CHECKED_format(
                    func_call_prefix=decor_meta.func_wrapper_code_call_prefix)
                code_return_check_suffix = (
                    decor_meta.func_wrapper_code_return_checked)

                # Full code snippet to be returned, consisting of:
                # * Calling the decorated callable and localize its return
                #   *AND*...
                # * Type-checking this return *AND*...
                # * Returning this return from this wrapper function.
                func_wrapper_code = (
                    f'{code_return_check_prefix}'
                    f'{code_return_check}'
                    f'{code_return_check_suffix}'
                )
            # Else, this hint is ignorable.
            # if not func_wrapper_code: print(f'Ignoring {decor_meta.func_name} return hint {repr(hint)}...')
        # If one or more warnings were issued, reissue these warnings with each
        # placeholder substring (i.e., "EXCEPTION_PLACEHOLDER" instance)
        # replaced by a human-readable description of this callable and
        # annotated return.
        if warnings_issued:
            reissue_warnings_placeholder(
                warnings=warnings_issued,
                target_str=prefix_callable_return(
                    func=decor_meta.func_wrappee,
                    is_color=decor_meta.conf.is_color,
                ),
            )
        # Else, *NO* warnings were issued.
    # If any exception was raised, reraise this exception with each placeholder
    # substring (i.e., "EXCEPTION_PLACEHOLDER" instance) replaced by a
    # human-readable description of this callable and annotated return.
    except Exception as exception:
        reraise_exception_placeholder(
            exception=exception,
            target_str=prefix_callable_return(
                func=decor_meta.func_wrappee,
                is_color=decor_meta.conf.is_color,
            ),
        )

    # ..................{ RETURN                             }..................
    # If a local scope is required to type-check this return, merge this scope
    # into the local scope currently required by the current wrapper function.
    if func_scope:
        update_mapping(decor_meta.func_wrapper_scope, func_scope)
    # Else, *NO* local scope is required to type-check this return.

    # Return this code.
    return func_wrapper_code
