#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype decorator parameter code generator** (i.e., low-level callables
dynamically generating Python expressions type-checking all annotated parameters
of the callable currently being decorated by the :func:`beartype.beartype`
decorator in a general-purpose manner).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
# All "FIXME:" comments for this submodule reside in this package's "__init__"
# submodule to improve maintainability and readability here.

# ....................{ IMPORTS                            }....................
from beartype.roar import (
    BeartypeDecorHintPepException,
    BeartypeDecorParamNameException,
)
from beartype.typing import (
    Optional,
    Set,
)
from beartype._data.code.datacodename import ARG_NAME_ARGS_NAME_KEYWORDABLE
from beartype._check.checkmake import make_code_raiser_func_pith_check
from beartype._check.convert.convmain import sanify_hint_root_func
from beartype._check.metadata.hint.hintsane import (
    HINT_SANE_IGNORABLE,
    HintSane,
)
from beartype._check.metadata.metadecor import BeartypeDecorMeta
from beartype._data.error.dataerrmagic import EXCEPTION_PLACEHOLDER
from beartype._data.func.datafuncarg import ARG_NAME_RETURN
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import LexicalScope
from beartype._data.code.datacodefunc import (
    CODE_INIT_ARGS_LEN,
    # EXCEPTION_PREFIX_DEFAULT,
    ARG_KIND_TO_CODE_LOCALIZE,
)
from beartype._decor._nontype._wrap._wraputil import unmemoize_func_wrapper_code
from beartype._util.error.utilerrraise import reraise_exception_placeholder
from beartype._util.error.utilerrwarn import (
    # issue_warning,
    reissue_warnings_placeholder,
)
from beartype._util.func.arg.utilfuncargiter import (
    ArgKind,
    # ArgMandatory,
    iter_func_args,
)
from beartype._util.func.arg.utilfuncargtest import is_func_arg_variadic_keyword
from beartype._util.hint.utilhinttest import is_hint_needs_cls_stack
from beartype._util.kind.maplike.utilmapset import update_mapping
# from beartype._util.text.utiltextmunge import lowercase_str_char_first
from beartype._util.text.utiltextprefix import (
    prefix_callable_arg_name,
    # prefix_pith_value,
)
from beartype._data.kind.datakindiota import SENTINEL
from warnings import catch_warnings

# ....................{ CODERS                             }....................
def code_check_args(decor_meta: BeartypeDecorMeta) -> str:
    '''
    Generate a Python code snippet type-checking all annotated parameters of the
    decorated callable if any *or* the empty string otherwise (i.e., if these
    parameters are unannotated).

    Parameters
    ----------
    decor_meta : BeartypeDecorMeta
        Decorated callable to be type-checked.

    Returns
    -------
    str
        Code type-checking all annotated parameters of the decorated callable.

    Raises
    ------
    BeartypeDecorParamNameException
        If the name of any parameter declared on this callable is prefixed by
        the reserved substring ``__bear``.
    BeartypeDecorHintNonpepException
        If any type hint annotating any parameter of this callable is neither:

        * A PEP-noncompliant type hint.
        * A supported PEP-compliant type hint.
    '''
    assert isinstance(decor_meta, BeartypeDecorMeta), (
        f'{repr(decor_meta)} not beartype call.')

    # ..................{ LOCALS ~ func                      }..................
    # If *NO* callable parameters are annotated, silently reduce to a noop.
    #
    # Note that this is purely an optimization short-circuit mildly improving
    # efficiency for the common case of callables accepting either no
    # parameters *OR* one or more parameters, all of which are unannotated.
    if (
        # That callable is annotated by only one type hint *AND*...
        len(decor_meta.func_annotations) == 1 and
        # That type hint annotates that callable's return rather than a
        # parameter accepted by that callable...
        ARG_NAME_RETURN in decor_meta.func_annotations
    ):
        return ''
    # Else, one or more callable parameters are annotated.

    # Python code snippet to be returned, defaulting to the empty string
    # implying this callable's parameters to all either be unannotated *OR*
    # annotated only by safely ignorable type hints.
    func_wrapper_code = ''

    # Lexical scope (i.e., dictionary mapping from the relative unqualified name
    # to value of each locally or globally scoped attribute accessible to a
    # callable or class), initialized to "None" for safety.
    func_scope: LexicalScope = None  # type: ignore[assignment]

    # ..................{ LOCALS ~ parameter                 }..................
    #FIXME: Remove this *AFTER* optimizing signature generation, please.
    # True only if that callable possibly accepts one or more positional
    # parameters.
    is_args_positional = False

    #FIXME: ******UNIT TEST US UP, PLEASE.******* Do so exhaustively until
    #exhausted. This is super-critical. Yo!
    #FIXME: Remove the "args_name_keywordable" local variable and associated
    #"ARG_NAME_ARGS_NAME_KEYWORDABLE" global variable *AFTER* refactoring
    #@beartype to generate callable-specific wrapper signatures.

    # Either...
    args_name_keywordable: Optional[Set[str]] = (
        #FIXME: [SPEED] Minor optimization. If the decorated callable *ONLY*
        #accepts an annotated variadic keyword parameter and no other
        #parameters, then the empty set reused from a global "SET_EMPTY" import
        #suffices here. Probably. Consider, anyway. *sigh*
        # If the decorated callable accepts an annotated variadic keyword
        # parameter (e.g., "**kwargs: int"), the set of the names of all
        # keywordable parameters (i.e., parameters that may be passed by
        # keyword), defined as the union of the:
        # * Set of the names of all flexible parameters (i.e., parameters that
        #   may be passed either positionally or by keyword).
        # * Set of the names of all keyword-only parameters.
        #
        # This set is required in the body of the type-checking function
        # wrapping the decorated callable to differentiate between:
        # * Keyword parameters explicitly accepted by the decorated callable,
        #   which are trivially type-checked by existing logic.
        # * Keyword parameters *NOT* explicitly accepted by the decorated
        #   callable and thus implicitly accepted only as excess keyword
        #   parameters added by CPython itself to the annotated variadic keyword
        #   parameter (e.g., "**kwargs: int") accepted by the decorated
        #   callable. Excess keyword parameters *CANNOT* be trivially
        #   type-checked by existing logic, due to the non-triviality of
        #   deciding whether a keyword parameter even is "excess" or not.
        set()
        if is_func_arg_variadic_keyword(
            # See the call to the iter_func_args() generator function below for
            # further commentary on these parameters.
            func=decor_meta.func_wrappee_wrappee, is_unwrap=False) else
        # Else, "None".
        None
    )

    # ..................{ LOCALS ~ hint                      }..................
    # Possibly insane hint annotating the current parameter if any *OR* the
    # sentinel placeholder otherwise (i.e., if this parameter is unannotated).
    hint_insane: Hint = None  # type: ignore[assignment]

    # Sanified hint metadata annotating the current parameter, sanified from
    # this possibly insane hint.
    hint_sane: HintSane = None  # type: ignore[assignment]

    # ..................{ GENERATE                           }..................
    #FIXME: Locally remove the "arg_index" local variable (and thus avoid
    #calling the enumerate() builtin here) *AFTER* refactoring @beartype to
    #generate callable-specific wrapper signatures.

    # Kind and name of this parameter.
    arg_kind: ArgKind = None  # type: ignore[assignment]
    arg_name: str     = None  # type: ignore[assignment]

    #FIXME: Uncomment as needed, please. *sigh*
    # # Default value of this parameter if this parameter is optional *OR* the
    # # "ArgMandatory" singleton otherwise (i.e., if this parameter is mandatory).
    # arg_default: object = None

    # For the 0-based index of each parameter accepted by that callable and the
    # "ArgMeta" 3-tuple describing this parameter (in declaration order)...
    for arg_index, arg_meta in enumerate(iter_func_args(
        # Possibly lowest-level wrappee underlying the possibly higher-level
        # wrapper currently being decorated by the @beartype decorator. The
        # latter typically fails to convey the same callable metadata conveyed
        # by the former -- including the names and kinds of parameters accepted
        # by the possibly unwrapped callable. This renders the latter mostly
        # useless for our purposes.
        func=decor_meta.func_wrappee_wrappee,
        func_codeobj=decor_meta.func_wrappee_wrappee_codeobj,
        # Avoid inefficiently attempting to re-unwrap this wrappee. The
        # previously called BeartypeDecorMeta.reinit() method has already
        # guaranteed this wrappee to be isomorphically unwrapped.
        is_unwrap=False,
    )):
        # Localize metadata for both efficiency and f-string purposes.
        #
        # Note that list unpacking is substantially more efficient than
        # manually indexing list items. The former requires only a single Python
        # statement, whereas the latter requires "n" Python statements.
        (
            arg_kind,
            arg_name,
            _,  # arg_default,
        ) = arg_meta

        # If...
        if (
            # The set of the names of all keywordable parameters must be decided
            # to type-check the decorated callable *AND*...
            args_name_keywordable is not None and
            # This parameter is keywordable...
            arg_kind in _ARG_KINDS_KEYWORD
        ):
            # Add the name of this parameter to that set.
            args_name_keywordable.add(arg_name)
        # Else, this parameter *CANNOT* be passed by keyword.

        # Type hint annotating this parameter if any *OR* the sentinel
        # placeholder otherwise (i.e., if this parameter is unannotated).
        #
        # Note that "None" is a semantically meaningful PEP 484-compliant type
        # hint equivalent to "type(None)". Ergo, we *MUST* explicitly
        # distinguish between that type hint and unannotated parameters.
        hint_insane = decor_meta.func_annotations_get(  # type: ignore[assignment]
            arg_name, SENTINEL)

        # If this parameter is unannotated, continue to the next parameter.
        if hint_insane is SENTINEL:
            continue
        # Else, this parameter is annotated.

        # Attempt to...
        try:
            # With a context manager "catching" *ALL* non-fatal warnings emitted
            # during this logic for subsequent "playback" below...
            with catch_warnings(record=True) as warnings_issued:
                # If this parameter's name is reserved for use by the @beartype
                # decorator, raise an exception.
                if arg_name.startswith('__bear'):
                    raise BeartypeDecorParamNameException(
                        f'{EXCEPTION_PLACEHOLDER}reserved by @beartype.')
                # Else, this parameter's name is *NOT* reserved for use by the
                # @beartype decorator.

                # Sane hint sanified from this possibly insane parameter hint if
                # sanifying this hint generated no supplementary metadata *OR*
                # that metadata otherwise. Additionally, if this hint is
                # unsupported by @beartype, raise an exception.
                hint_sane = sanify_hint_root_func(
                    decor_meta=decor_meta,
                    hint=hint_insane,
                    pith_name=arg_name,
                    arg_kind=arg_kind,
                    exception_prefix=EXCEPTION_PLACEHOLDER,
                )

                # If this hint is ignorable, continue to the next parameter.
                if hint_sane is HINT_SANE_IGNORABLE:
                    # print(f'Ignoring {decor_meta.func_name} parameter {arg_name} hint {repr(hint)}...')
                    continue
                # Else, this hint is unignorable.

                #FIXME: Fundamentally unsafe and thus temporarily disabled *FOR
                #THE MOMENT.* The issue is that our current implementation of
                #the is_bearable() tester internally called by this function
                #refuses to resolve relative forward references -- which is
                #obviously awful. Ideally, that tester *ABSOLUTELY* should
                #resolve relative forward references. Until it does, however,
                #this is verboten dark magic that is unsafe in the general case.
                #FIXME: Note that there exist even *MORE* edge cases, however:
                #@dataclass fields, which violate typing semantics: e.g.,
                #    from dataclasses import dataclass, field
                #    from typing import Dict
                #
                #    from beartype import beartype
                #
                #    @beartype
                #    @dataclass
                #    class A:
                #        test_dict: Dict[str, str] = field(default_factory=dict)
                #FIXME: Once this has been repaired, please reenable:
                #* The "test_decor_arg_kind_flex_optional" unit test.

                # # If this parameter is optional *AND* the default value of this
                # # optional parameter violates this hint, raise an exception.
                # _die_if_arg_default_unbearable(
                #     decor_meta=decor_meta, arg_default=arg_default, hint=hint)
                # # Else, this parameter is either optional *OR* the default value
                # # of this optional parameter satisfies this hint.

                # If this parameter either may *OR* must be passed positionally,
                # record this fact.
                #
                # Note this conditional branch *MUST* be tested after validating
                # this parameter to be unignorable; if this branch were instead
                # nested *BEFORE* validating this parameter to be unignorable,
                # beartype would fail to reduce to a noop for otherwise
                # ignorable callables -- which would be rather bad, really.
                if arg_kind in _ARG_KINDS_POSITIONAL:
                    is_args_positional = True
                # Else, this parameter *CANNOT* be passed positionally.

                #FIXME: [SPEED] Negligibly optimized the ".get" access away:
                #    ARG_LOCALIZE_TEMPLATE = ARG_KIND_TO_CODE_LOCALIZE_get(  # type: ignore
                #        arg_kind, None)
                # Python code template localizing this parameter if this kind of
                # parameter is supported *OR* "None" otherwise.
                ARG_LOCALIZE_TEMPLATE = ARG_KIND_TO_CODE_LOCALIZE.get(  # type: ignore
                    arg_kind, None)

                # If this kind of parameter is unsupported, raise an exception.
                #
                # Note this edge case should *NEVER* occur, as the parent
                # function should have simply ignored this parameter.
                if ARG_LOCALIZE_TEMPLATE is None:
                    raise BeartypeDecorHintPepException(
                        f'{EXCEPTION_PLACEHOLDER}kind {repr(arg_kind)} '
                        f'currently unsupported by @beartype.'
                    )
                # Else, this kind of parameter is supported. Ergo, this code is
                # non-"None".

                #FIXME: DRY violation. The same logic appears in "_wrapreturn"
                #as well. It looks like what we *PROBABLY* want to do here is:
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

                # Type stack if required by this hint *OR* "None" otherwise. See
                # the is_hint_needs_cls_stack() tester for further discussion.
                #
                # Note that the original unsanitized "hint_insane" (e.g.,
                # "typing.Self") rather than the new sanitized "hint" (e.g., the
                # class currently being decorated by @beartype) is passed to
                # that tester. Why? Because the latter may already have been
                # reduced above to a different (and seemingly innocuous) type
                # hint that does *NOT* appear to require a type stack at late
                # *EXCEPTION RAISING TIME* (i.e., the
                # beartype._check.error.errmain.get_func_pith_violation()
                # function) but actually does. Only the original unsanitized
                # "hint_insane" is truth.
                cls_stack = (
                    decor_meta.cls_stack
                    if is_hint_needs_cls_stack(hint_insane) else
                    None
                )
                # print(f'arg "{arg_name}" hint {repr(hint)} cls_stack: {repr(cls_stack)}')

                # Code snippet type-checking any parameter with arbitrary name.
                (
                    code_arg_check_pith,
                    func_scope,
                    hint_refs_type_basename,
                ) = make_code_raiser_func_pith_check(
                    hint_sane,
                    decor_meta.conf,
                    cls_stack,
                    True,  # <-- True only for parameters
                )

                # Merge the local scope required to check this parameter into
                # the local scope currently required by the current wrapper
                # function.
                update_mapping(decor_meta.func_wrapper_scope, func_scope)

                # Python code snippet localizing this parameter.
                code_arg_localize = ARG_LOCALIZE_TEMPLATE.format(
                    arg_name=arg_name, arg_index=arg_index)

                # Unmemoize this snippet against the current parameter.
                code_arg_check = unmemoize_func_wrapper_code(
                    decor_meta=decor_meta,
                    func_wrapper_code=code_arg_check_pith,
                    pith_repr=repr(arg_name),
                    hint_refs_type_basename=hint_refs_type_basename,
                )

                # Append code type-checking this parameter against this hint.
                func_wrapper_code += f'{code_arg_localize}{code_arg_check}'

            # If one or more warnings were issued, reissue these warnings with
            # each placeholder substring (i.e., "EXCEPTION_PLACEHOLDER"
            # instance) replaced by a human-readable description of this
            # callable and annotated parameter.
            if warnings_issued:
                # print(f'warnings_issued: {warnings_issued}')
                reissue_warnings_placeholder(
                    warnings=warnings_issued,
                    target_str=prefix_callable_arg_name(
                        func=decor_meta.func_wrappee,
                        arg_name=arg_name,
                        is_color=decor_meta.conf.is_color,
                    ),
                )
            # Else, *NO* warnings were issued.
        # If any exception was raised, reraise this exception with each
        # placeholder substring (i.e., "EXCEPTION_PLACEHOLDER" instance)
        # replaced by a human-readable description of this callable and
        # annotated parameter.
        except Exception as exception:
            reraise_exception_placeholder(
                exception=exception,
                #FIXME: Embed the kind of parameter both here and above as well
                #(e.g., "positional-only", "keyword-only", "variadic
                #positional"), ideally by improving the existing
                #prefix_callable_arg_name() function to introspect this kind from
                #the callable code object.
                target_str=prefix_callable_arg_name(
                    func=decor_meta.func_wrappee,
                    arg_name=arg_name,
                    is_color=decor_meta.conf.is_color,
                ),
            )

    # ..................{ RETURN                             }..................
    # If that callable accepts an annotated variadic keyword parameter, expose
    # the set of the names of all keywordable parameters to this wrapper
    # function needed to type-check that annotated variadic keyword parameter.
    if args_name_keywordable is not None:
        decor_meta.func_wrapper_scope[ARG_NAME_ARGS_NAME_KEYWORDABLE] = (
            args_name_keywordable)
    # Else, that callable accepts *NO* annotated variadic parameter.

    # If that callable accepts one or more annotated positional parameters,
    # prefix this code by a snippet localizing the number of these parameters.
    if is_args_positional:
        func_wrapper_code = f'{CODE_INIT_ARGS_LEN}{func_wrapper_code}'
    # Else, that callable accepts *NO* annotated positional parameters.

    # Return this code.
    return func_wrapper_code

# ....................{ PRIVATE ~ constants                }....................
#FIXME: Shift these constants into a more appropriate "beartype._data"
#submodule, please. *sigh*
_ARG_KINDS_KEYWORD = frozenset((
    ArgKind.KEYWORD_ONLY,
    ArgKind.POSITIONAL_OR_KEYWORD,
))
'''
Frozen set of all **keyword parameter kinds** (i.e., :attr:`ArgKind` enumeration
members signifying that a callable parameter either may *or* must be passed by
keyword).
'''


_ARG_KINDS_POSITIONAL = frozenset((
    ArgKind.POSITIONAL_ONLY,
    ArgKind.POSITIONAL_OR_KEYWORD,
))
'''
Frozen set of all **positional parameter kinds** (i.e., :class:`.ArgKind`
enumeration members signifying that a callable parameter either may *or* must be
passed positionally).
'''

# ....................{ PRIVATE ~ raisers                  }....................
#FIXME: Preserved for posterity. We'll almost certainly want to restore this at
#some future date. Until then, we sigh. *sigh*
# def _die_if_arg_default_unbearable(
#     decor_meta: BeartypeDecorMeta, arg_default: object, hint: Hint) -> None:
#     '''
#     Raise a violation exception if the annotated optional parameter of the
#     decorated callable with the passed default value violates the type hint
#     annotating that parameter at decoration time.
#
#     Parameters
#     ----------
#     decor_meta : BeartypeDecorMeta
#         Decorated callable to be type-checked.
#     arg_default : object
#         Either:
#
#         * If this parameter is mandatory, the :data:`.ArgMandatory` singleton.
#         * If this parameter is optional, the default value of this optional
#           parameter to be type-checked.
#     hint : Hint
#         Type hint to type-check against this default value.
#
#     Warns
#     -----
#     BeartypeDecorHintParamDefaultForwardRefWarning
#         If this type hint contains one or more forward references that *cannot*
#         be resolved at decoration time. While this does *not* necessarily
#         constitute a fatal error from the end user perspective, this does
#         constitute a non-fatal issue worth informing the end user of.
#
#     Raises
#     ------
#     BeartypeDecorHintParamDefaultViolation
#         If this default value violates this type hint.
#     '''
#     assert isinstance(decor_meta, BeartypeDecorMeta), (
#         f'{repr(decor_meta)} not beartype call.')
#
#     # ..................{ PREAMBLE                           }..................
#     # If this parameter is mandatory, silently reduce to a noop.
#     if arg_default is ArgMandatory:
#         return
#     # Else, this parameter is optional and thus defaults to a default value.
#
#     # ..................{ IMPORTS                            }..................
#     # Defer heavyweight imports prohibited at global scope.
#     from beartype.door import (
#         die_if_unbearable,
#         is_bearable,
#     )
#
#     # ..................{ MAIN                               }..................
#     # Attempt to...
#     try:
#         # If this default value satisfies this hint, silently reduce to a noop.
#         #
#         # Note that this is a non-negligible optimization. Technically, this
#         # preliminary test is superfluous: only the call to the
#         # die_if_unbearable() raiser below is required. Pragmatically, this
#         # preliminary test avoids a needlessly expensive dictionary copy in the
#         # common case that this value satisfies this hint.
#         if is_bearable(obj=arg_default, hint=hint, conf=decor_meta.conf):
#             return
#         # Else, this default value violates this hint.
#     #FIXME: Probably generalize this to *ANY* exception whatsoever, no?
#     # If doing so raises a forward hint exception, this hint contains one or
#     # more unresolvable forward references to user-defined objects that have yet
#     # to be defined. In all likelihood, these objects are subsequently defined
#     # after the definition of this decorated callable. While this does *NOT*
#     # necessarily constitute a fatal error from the end user perspective, this
#     # does constitute a non-fatal issue worth informing the end user of. In this
#     # case, we coerce this exception into a warning.
#     except _BeartypeHintForwardRefExceptionMixin as exception:
#         # Forward hint exception message raised above. To readably embed this
#         # message in the longer warning message emitted below, the first
#         # character of this message is lowercased as well.
#         exception_message = lowercase_str_char_first(str(exception))
#
#         # Emit this non-fatal warning.
#         issue_warning(
#             cls=BeartypeDecorHintParamDefaultForwardRefWarning,
#             message=(
#                 f'{EXCEPTION_PREFIX_DEFAULT}value '
#                 f'{prefix_pith_value(pith=arg_default, is_color=decor_meta.conf.is_color)}'
#                 f'uncheckable at @beartype decoration time, as '
#                 f'{exception_message}'
#             ),
#         )
#
#         # Loudly reduce to a noop. Since this forward reference is unresolvable,
#         # further type-checking attempts are entirely fruitless.
#         return
#
#     # Modifiable keyword dictionary encapsulating this beartype configuration.
#     conf_kwargs = decor_meta.conf.kwargs.copy()
#
#     #FIXME: This should probably be configurable as well. For now, this is fine.
#     #We shrug noncommittally. We shrug, everyone! *shrug*
#     # Set the type of violation exception raised by the subsequent call to the
#     # die_if_unbearable() function to the expected type.
#     conf_kwargs['violation_door_type'] = BeartypeDecorHintParamDefaultViolation
#
#     # New beartype configuration initialized by this dictionary.
#     conf = BeartypeConf(**conf_kwargs)
#
#     # Raise this type of violation exception.
#     die_if_unbearable(
#         obj=arg_default,
#         hint=hint,
#         conf=conf,
#         exception_prefix=EXCEPTION_PREFIX_DEFAULT,
#     )
