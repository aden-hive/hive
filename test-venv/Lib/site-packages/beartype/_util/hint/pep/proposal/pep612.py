#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`612`-compliant **parameter specification** (i.e.,
:obj:`typing.ParamSpec` type hints and instance variables of those hints)
utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep612Exception
from beartype.typing import (
    Callable,
    Optional,
    Union,
)
from beartype._cave._cavefast import (
    EllipsisType,
    HintPep612ParamSpecType,
    HintPep612ParamSpecArgType,
    HintPep612ParamSpecKwargType,
)
from beartype._check.metadata.metadecor import BeartypeDecorMeta
from beartype._data.typing.datatypingport import (
    Hint,
    ListHints,
)
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.hint.sign.datahintsigns import (
    HintSignParamSpecArgs,
    HintSignParamSpecKwargs,
)
from beartype._util.api.standard.utiltyping import import_typing_attr_or_none
from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none
from beartype._util.func.arg.utilfuncargget import (
    get_func_arg_meta_variadic_keyword_or_none,
    get_func_arg_meta_variadic_positional_or_none,
)
from beartype._util.func.arg.utilfuncargiter import (
    ARG_META_INDEX_NAME,
    ArgKind,
)
from beartype._util.func.arg.utilfuncargtest import (
    is_func_arg_name_variadic_keyword,
    is_func_arg_name_variadic_positional,
)
from beartype._data.kind.datakindiota import SENTINEL

# ....................{ GETTERS                            }....................
def get_hint_pep612_paramspec(
    paramspec_var: Union[
        HintPep612ParamSpecArgType,
        HintPep612ParamSpecKwargType,
    ]
) -> HintPep612ParamSpecType:
    '''
    :pep:`612`-compliant **parameter specification** (i.e., low-level C-based
    :obj:`typing.ParamSpec` object) containing the passed **parameter
    specification variadic parameter instance variable** (i.e., low-level
    C-based :obj:`typing.ParamSpecArgs` object annotating a variadic parameter
    with syntax resembling ``*args: P.args`` and ``**kwargs: P.kwargs`` for
    ``P`` a low-level C-based :obj:`typing.ParamSpec` parent object) as a child
    instance variable.

    Parameters
    ----------
    paramspec_var : HintPep612ParamSpecVarTypes
        Parameter specification variadic parameter instance variable to be
        inspected.

    Returns
    -------
    typing.ParamSpec
        Parameter specification containing this variable.
    '''
    #FIXME: *lol*. This assert fails when using "typing_extensions.ParamSpec"
    #under Python < 3.10. Whatevahs! Just ignore quality assurance for now. \o/
    # assert isinstance(paramspec_var, HintPep612ParamSpecVarTypes), (
    #     f'{repr(paramspec_var)} not '
    #     f'PEP 612-compliant parameter specification variable.'
    # )

    # One-liners are fine. One-liners never cross the line! ¯\_(ツ)_/¯
    return paramspec_var.__origin__  # type: ignore[union-attr]

# ....................{ FACTORIES                          }....................
#FIXME: This should probably be memoized by @callable_cached. Probably. *sigh*
def make_hint_pep612_concatenate_list_or_none(
    hints_child_first: ListHints,
    hint_child_last: Union[Hint, EllipsisType],  # type: ignore[valid-type]
) -> Hint:
    '''
    :pep:`612`-compliant **parameter concatenation** (i.e., high-level
    pure-Python object created and returned by subscripting the standard
    :func:`typing.Concatenate` type hint factory) dynamically subscripted first
    by all child type hints in the passed ``hints_child_first`` list and then by
    the child type hint ``hint_child_last` if this hint factory is importable
    under the active Python interpreter *or* :data:`None` otherwise (i.e., if
    this hint factory is unimportable under the active Python interpreter).

    Parameters
    ----------
    hints_child_first : ListHints
        List of all leading child type hints to subscript the returned
        ``typing.Concatenate[...]`` type hint with.
    hint_child_last : Union[Hint, EllipsisType]
        Trailing child type hint to subscript the returned
        ``typing.Concatenate[...]`` type hint with. Note that both :pep:`612`
        *and* the runtime implementation of the :func:`typing.Concatenate` type
        hint factory require that this hint be either:

        * A **parameter specification** (i.e., low-level C-based
          :pep:`612`-compliant :obj:`typing.ParamSpec` object).
        * An **ellipsis** (i.e., ``...``), silently ignoring *all* remaining
          arbitrary trailing parameters accepted by the callable matched by the
          parent :pep:`484`- or :pep:`585`-compliant ``Callable[...]`` type
          hint.

    Returns
    -------
    Hint
        Either:

        * If :func:`typing.Concatenate` is importable, the
          ``typing.Concatenate[...]`` type hint subscripted by these child type
          hints.
        * Else, :data:`None`.

    Raises
    ------
    TypeError
        If ``hint_child_last`` is neither:

        * A parameter specification.
        * An ellipsis.
    '''
    assert isinstance(hints_child_first, list), (
        f'{repr(hints_child_first)} not list.')

    # "Concatenate[...]" hint to be returned, subscripted by these child hints.
    hint = None

    # PEP 612-compliant "typing(|_extensions).Concatenate" hint factory if
    # importable *OR* "None" otherwise.
    Concatenate = import_typing_attr_or_none('Concatenate')

    #FIXME: When Python 3.10 support is dropped, this can and should be
    #reduced to this elegant one-liner employing list unpacking:
    #    hint = Concatenate[*hints_child_first, hint_child_last]

    # If this hint factory is importable...
    if Concatenate is not None:
        # Tuple of all child hints to subscript "Concatenate[...]" with.
        #
        # Note that the Concatenate.__getitem__() implementation *REQUIRES* that
        # the passed parameter be a tuple. Sanity is out the window, folks.
        hints_child = tuple(hints_child_first) + (hint_child_last,)
        # print(f'hints_child_first: {hints_child_first}; hint_child_last: {hint_child_last}')

        # "Concatenate[...]" hint dynamically subscripted by this tuple.
        hint = Concatenate.__getitem__(hints_child)  # type: ignore[misc]
    # Else, this hint factory is unimportable. In this case, fallback to
    # returning "None".

    # Return this "Concatenate[...]" hint.
    return hint  # pyright: ignore

# ....................{ REDUCERS                           }....................
def reduce_hint_pep612_args(hint: object, **kwargs,) -> object:
    '''
    Reduce the passed :pep:`612`-compliant **parameter specification variadic
    positional parameter instance variable** (i.e., low-level C-based
    :obj:`typing.ParamSpecArgs` object annotating a variadic positional parameter
    with syntax resembling ``*args: P.args`` for ``P`` a low-level C-based
    :obj:`typing.ParamSpec` parent object) to the ignorable :class:`object`
    superclass.

    This reducer effectively ignores *all* :obj:`typing.ParamSpecArgs` objects.
    Although these objects do convey meaningful metadata and semantics, they do
    so in a manner uniquely suited to pure static type-checkers. Why? Because
    type-checking these objects requires tracking parameter specifications
    across disparate callable signatures separated - in the worst case - in both
    space and time. Although :mod:`beartype` could type-check these objects at a
    later date, doing so is highly non-trivial and thus deferred to the
    sacrificial blood sacrifice that is reading this. Sorry. That's you.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

    Parameters
    ----------
    hint : object
        :pep:`612`-compliant parameter specification variadic positional
        parameter type hint to be reduced.

    All remaining keyword parameters are passed as is to the lower-level
    :func:`._reduce_hint_pep612_args_or_kwargs` reducer.

    Returns
    -------
    object
        Lower-level type hint currently supported by :mod:`beartype`.

    Raises
    ------
    BeartypeDecorHintPep612Exception
        If this hint does *not* annotate a variadic positional parameter.

    See Also
    --------
    :func:`._reduce_hint_pep612_args_or_kwargs`
        Further details.
    '''

    # Defer to this lower-level general-purpose reducer.
    return _reduce_hint_pep612_args_or_kwargs(
        hint=hint,
        arg_kind_expected=ArgKind.VARIADIC_POSITIONAL,
        pith_name_label=_VAR_POS_PITH_NAME_LABEL,
        pith_name_syntax=_VAR_POS_PITH_NAME_SYNTAX,
        other_hint=get_hint_pep612_paramspec(hint).kwargs,  # type: ignore[attr-defined,arg-type]
        other_hint_sign=HintSignParamSpecKwargs,
        other_pith_name_getter=get_func_arg_meta_variadic_keyword_or_none,
        other_pith_name_label=_VAR_KW_PITH_NAME_LABEL,
        **kwargs
    )


def reduce_hint_pep612_kwargs(hint: object, **kwargs) -> object:
    '''
    Reduce the passed :pep:`612`-compliant **parameter specification variadic
    keyword parameter instance variable** (i.e., low-level C-based
    :obj:`typing.ParamSpecKwargs` object annotating a variadic keyword
    parameter with syntax resembling ``**kwargs: P.kwargs`` for ``P`` a low-level
    C-based :obj:`typing.ParamSpec` parent object) to the ignorable
    :class:`object` superclass.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

    See Also
    --------
    :func:`.reduce_hint_pep612_args`
        Further details.
    '''
    # print('!!HERE!!')

    # Defer to this lower-level general-purpose reducer.
    return _reduce_hint_pep612_args_or_kwargs(
        hint=hint,
        arg_kind_expected=ArgKind.VARIADIC_KEYWORD,
        pith_name_label=_VAR_KW_PITH_NAME_LABEL,
        pith_name_syntax=_VAR_KW_PITH_NAME_SYNTAX,
        other_hint=get_hint_pep612_paramspec(hint).args,  # type: ignore[attr-defined,arg-type]
        other_hint_sign=HintSignParamSpecArgs,
        other_pith_name_getter=get_func_arg_meta_variadic_positional_or_none,
        other_pith_name_label=_VAR_POS_PITH_NAME_LABEL,
        **kwargs
    )

# ....................{ PRIVATE ~ constants : positional   }....................
_VAR_POS_PITH_NAME_LABEL = 'positional'
'''
Human-readable substring describing a :pep:`612`-compliant parameter
specification variadic positional parameter type hint.
'''


_VAR_POS_PITH_NAME_SYNTAX = '*args'
'''
Standard machine-readable syntax declaring a variadic positional parameter.
'''


_VAR_POS_PITH_NAME_TESTER = is_func_arg_name_variadic_positional
'''
Human-readable substring validating that a :pep:`612`-compliant parameter
specification variadic positional parameter type hint annotates a variadic
positional parameter.
'''

# ....................{ PRIVATE ~ constants : keyword      }....................
_VAR_KW_PITH_NAME_LABEL = 'keyword'
'''
Human-readable substring describing a :pep:`612`-compliant parameter
specification variadic keyword parameter type hint.
'''


_VAR_KW_PITH_NAME_SYNTAX = '*args'
'''
Standard machine-readable syntax declaring a variadic positional parameter.
'''


_VAR_KW_PITH_NAME_TESTER = is_func_arg_name_variadic_keyword
'''
Human-readable substring validating that a :pep:`612`-compliant parameter
specification variadic keyword parameter type hint annotates a variadic keyword
parameter.
'''

# ....................{ PRIVATE ~ reducers                 }....................
def _reduce_hint_pep612_args_or_kwargs(
    # General-purpose parameters passed by the higher-level
    # beartype._check.convert._reduce.redmain.reduce_hint() reducer to this
    # lower-level reducer.
    hint: object,
    decor_meta: Optional[BeartypeDecorMeta],
    pith_name: Optional[str],
    arg_kind: Optional[ArgKind],
    exception_prefix: str,

    # PEP 612-specific parameters passed by the higher-level
    # reduce_hint_pep612_args() or reduce_hint_pep612_kwargs() reducer to this
    # lower-level reducer.
    arg_kind_expected: ArgKind,
    pith_name_label: str,
    pith_name_syntax: str,
    other_hint: object,
    other_hint_sign: HintSign,
    other_pith_name_getter: Callable,
    other_pith_name_label: str,

    # Ignorable general-purpose parameters passed by the higher-level
    # beartype._check.convert._reduce.redmain.reduce_hint() reducer *NOT* required
    # by this lower-level reducer.
    **kwargs
) -> object:
    '''
    Reduce the passed :pep:`612`-compliant **parameter specification variadic
    positional parameter instance variable** (i.e., low-level C-based
    :obj:`typing.ParamSpecArgs` object annotating a variadic positional parameter
    with syntax resembling ``*args: P.args`` for ``P`` a low-level C-based
    :obj:`typing.ParamSpec` parent object) to the ignorable :class:`object`
    superclass.

    This reducer effectively ignores *all* :obj:`typing.ParamSpecArgs` objects.
    Although these objects do convey meaningful metadata and semantics, they do
    so in a manner uniquely suited to pure static type-checkers. Why? Because
    type-checking these objects requires tracking parameter specifications
    across disparate callable signatures separated - in the worst case - in both
    space and time. Although :mod:`beartype` could type-check these objects at a
    later date, doing so is highly non-trivial and thus deferred to the
    sacrificial blood sacrifice that is reading this. Sorry. That's you.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

    Parameters
    ----------
    hint : object
        :pep:`612`-compliant parameter specification variadic positional or
        keyword parameter type hint to be reduced.
    decor_meta : Optional[BeartypeDecorMeta]
        Either:

        * If this hint annotates a parameter or return of some callable, the
          :mod:`beartype`-specific decorator metadata describing that callable.
        * Else, :data:`None`.
    pith_name : Optional[str]
        Either:

        * If this hint annotates a parameter of some callable, the name of that
          parameter.
        * If this hint annotates the return of some callable, ``"return"``.
        * Else, :data:`None`.

        Defaults to :data:`None`.
    arg_kind : Optional[ArgKind]
        Either:

        * If this hint annotates a parameter of some callable, that parameter's
          **kind** (i.e., :class:`.ArgKind` enumeration member conveying the
          syntactic class of that parameter, constraining how the callable
          declaring that parameter requires that parameter to be passed).
        * Else, :data:`None`.
    exception_prefix : str
        Human-readable substring prefixing exception messages raised by this
        reducer.
    arg_kind_expected : ArgKind
        **Expected parameter kind**, defined as either:

        * If this hint is expected to annotate a variadic positional parameter,
          the :attr:`.ArgKind.VARIADIC_POSITIONAL` enumeration member.
        * If this hint is expected to annotate a variadic keyword parameter,
          the :attr:`.ArgKind.VARIADIC_KEYWORD` enumeration member.
    pith_name_label : str
        Either:

        * If this hint annotates a variadic positional parameter, the
          human-readable substring ``"positional"``.
        * If this hint annotates a variadic keyword parameter, the
          human-readable substring ``"keyword"``.
    pith_name_syntax : str
        Either:

        * If this hint annotates a variadic positional parameter, the
          machine-readable substring ``"*args"``.
        * If this hint annotates a variadic keyword parameter, the
          machine-readable substring ``"**kwargs"``.
    other_hint : object
        Either:

        * If this hint annotates a variadic positional parameter, the
          corresponding hint annotating a variadic keyword parameter.
        * If this hint annotates a variadic keyword parameter, the
          corresponding hint annotating a variadic positional parameter.
    other_hint_sign : HintSign
        Either:

        * If this hint annotates a variadic positional parameter, the
          :data:`.HintSignParamSpecKwargs` sign.
        * If this hint annotates a variadic keyword parameter, the
          :data:`.HintSignParamSpecArgs` sign.
    other_pith_name_getter : Callable
        Either:

        * If this hint annotates a variadic positional parameter, the
          :func:`beartype._util.func.arg.utilfuncargget.get_func_arg_meta_variadic_keyword_or_none`
          getter.
        * If this hint annotates a variadic keyword parameter, the
          :func:`beartype._util.func.arg.utilfuncargget.get_func_arg_meta_variadic_positional_or_none`
          getter.
    other_pith_name_label : str
        Either:

        * If this hint annotates a variadic positional parameter, the
          human-readable substring ``"keyword"``.
        * If this hint annotates a variadic keyword parameter, the
          human-readable substring ``"positional"``.

    All remaining passed parameters are silently ignored.

    Returns
    -------
    object
        Lower-level type hint currently supported by :mod:`beartype`.

    Raises
    ------
    BeartypeDecorHintPep612Exception
        If this hint does *not* annotate a variadic positional parameter.
    '''
    assert isinstance(arg_kind_expected, ArgKind), (
        f'{repr(arg_kind_expected)} not argument kind.')
    assert isinstance(pith_name_label, str), (
        f'{repr(pith_name_label)} not string.')
    assert isinstance(pith_name_syntax, str), (
        f'{repr(pith_name_syntax)} not string.')
    assert isinstance(other_hint_sign, HintSign), (
        f'{repr(other_hint_sign)} not type hint sign.')
    assert callable(other_pith_name_getter), (
        f'{repr(other_pith_name_getter)} uncallable.')
    assert isinstance(other_pith_name_label, str), (
        f'{repr(other_pith_name_label)} not string.')

    # ....................{ VALIDATE                       }....................
    # Validate basic sanity.

    # If this hint does *NOT* directly annotate a callable parameter or return,
    # raise an exception. By definition, PEP 612-compliant parameter
    # specification variadic positional and keyword parameter type hints *MUST*
    # directly annotate the variadic positional and keyword parameter
    # (respectively) of a callable.
    if decor_meta is None:
        raise BeartypeDecorHintPep612Exception(
            f'{exception_prefix}PEP 612 "ParamSpec" '
            f'variadic {pith_name_label} parameter '
            f'type hint {repr(hint)} erroneously subscripts '
            f'a parent type hint as a nested child type hint rather than '
            f'directly annotating '
            f'variadic {pith_name_label} parameter "{pith_name_syntax}" as a '
            f'root type hint'
            f'{_get_pep612_exception_message_suffix()}'
        )
    # Else, this hint directly annotates a callable parameter or return.

    # ....................{ LOCALS                         }....................
    # Callable directly annotated by this hint, localized for readability.
    func = decor_meta.func_wrappee_wrappee

    # Metadata describing the other variadic parameter accepted by that callable
    # if that callable accepts the other variadic parameter *OR* "None"
    # otherwise (i.e., if that callable accepts *NO* such parameter).
    other_arg_meta = other_pith_name_getter(
        func=func,
        is_unwrap=False,  # <-- "func" is already a fully unwrapped callable
        exception_cls=BeartypeDecorHintPep612Exception,
        exception_prefix=exception_prefix,
    )
    # print(f'other_arg_meta: {other_arg_meta}')

    # ....................{ VALIDATE ~ this                }....................
    # Validate the passed variadic positional or keyword parameter type hint.

    # If this hint directly annotates a callable parameter or return that is
    # *NOT* a variadic positional or keyword parameter, raise an exception.
    if arg_kind is not arg_kind_expected:
        raise BeartypeDecorHintPep612Exception(
            f'{exception_prefix}PEP 612 "ParamSpec" '
            f'variadic {pith_name_label} parameter '
            f'type hint {repr(hint)} erroneously annotates '
            f'parameter "{pith_name}" rather than '
            f'variadic {pith_name_label} parameter "{pith_name_syntax}"'
            f'{_get_pep612_exception_message_suffix(func=func)}'
        )
    # Else, this hint directly annotates a variadic positional or keyword
    # parameter.

    # ....................{ VALIDATE ~ other               }....................
    # Validate the other variadic positional or keyword parameter type hint
    # required by PEP 612 to be paired with the passed hint.

    # If that callable accepts *NO* other variadic parameter, raise an
    # exception.
    if other_arg_meta is None:
        raise BeartypeDecorHintPep612Exception(
            f'{exception_prefix}PEP 612 "ParamSpec" '
            f'variadic {pith_name_label} parameter '
            f'type hint {repr(hint)} not paired with '
            f'corresponding PEP 612 "ParamSpec" '
            f'variadic {other_pith_name_label} parameter '
            f'type hint {repr(other_hint)} (i.e., '
            f'that callable accepts no '
            f'variadic {other_pith_name_label} parameter)'
            f'{_get_pep612_exception_message_suffix(func=func)}'
        )
    # Else, that callable accepts the other variadic parameter.

    # Name of the other variadic parameter.
    other_arg_name = other_arg_meta[ARG_META_INDEX_NAME]

    # Type hint subscripting the other variadic parameter if any *OR* the
    # sentinel placeholder otherwise.
    other_arg_hint = decor_meta.func_annotations_get(
        other_arg_name, SENTINEL)

    # If the other variadic parameter is unannotated, raise an exception.
    if other_arg_hint is SENTINEL:
        raise BeartypeDecorHintPep612Exception(
            f'{exception_prefix}PEP 612 "ParamSpec" '
            f'variadic {pith_name_label} parameter '
            f'type hint {repr(hint)} paired with unannotated '
            f'variadic {other_pith_name_label} parameter (i.e., '
            f'variadic {other_pith_name_label} parameter annotated by no '
            f'corresponding PEP 612 "ParamSpec" '
            f'variadic {other_pith_name_label} parameter '
            f'type hint {repr(other_hint)})'
            f'{_get_pep612_exception_message_suffix(func=func)}'
        )
    # Else, the other variadic parameter is annotated by a hint.

    # Sign uniquely identifying the hint annotating other variadic parameter.
    other_arg_hint_sign = get_hint_pep_sign_or_none(other_arg_hint)  # pyright: ignore

    # If the hint annotating the other variadic parameter is *NOT* the other
    # variadic positional or keyword parameter hint required by PEP
    # 612 to be paired with the passed hint, raise an exception.
    if other_arg_hint_sign is not other_hint_sign:
        raise BeartypeDecorHintPep612Exception(
            f'{exception_prefix}PEP 612 "ParamSpec" '
            f'variadic {pith_name_label} parameter '
            f'type hint {repr(hint)} paired with '
            f'variadic {other_pith_name_label} parameter erroneously annotated '
            f'by type hint {repr(other_arg_hint)} rather than '
            f'corresponding PEP 612 "ParamSpec" '
            f'variadic {other_pith_name_label} parameter '
            f'type hint {repr(other_hint)}'
            f'{_get_pep612_exception_message_suffix(func=func)}'
        )
    # Else, the type hint annotating the other variadic parameter is the
    # other variadic positional or keyword parameter type hint required by PEP
    # 612 to be paired with the passed hint, raise an exception.

    # Reduce *ALL* PEP 612 type hints to an arbitrary ignorable type hint.
    return object

# ....................{ PRIVATE ~ constants                }....................
def _get_pep612_exception_message_suffix(
    func: Optional[Callable] = None) -> str:
    '''
    Human-readable substring suffixing *all*
    :class:`.BeartypeDecorHintPep612Exception` messages raised by the
    :func:`._reduce_hint_pep612_args_or_kwargs` reducer.

    Parameters
    ----------
    func : Optional[Callable], optional
        Either:

        * If that reducer was passed a callable, that callable.
        * Else, :data:`None`.

        Defaults to :data:`None`.
    '''

    # Unqualified name of the passed callable if a callable was passed *OR* a
    # placeholder name otherwise.
    func_name = (
        func.__name__
        if func is not None else
        'big_chad_energy'  # <-- lol... ok. so, it's not actually that funny.
    )

    # Return the expected human-readable substring.
    return (
        f': e.g.,\n'
        f"\t# This is what PEP 612 wants. It's a big ask, but please try.\n"
        f'\tdef {func_name}(*args: P.args, **kwargs: P.kwargs): ...\n'
        f'You can do this. PEP 612 believes in you. '
        f'More importantly, so do we.'
    )
