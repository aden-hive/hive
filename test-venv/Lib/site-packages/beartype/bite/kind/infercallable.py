#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype Inferential Type-hint Engine (BITE) callable type hint inferrers**
(i.e., lower-level functions dynamically subscripted type hints describing
callable objects).
'''

# ....................{ TODO                               }....................
#FIXME: We can and should do better. Currently, infer_hint_callable() reduces
#all unannotated variadic positional arguments (e.g., "*args") and annotated
#variadic positional arguments (e.g., "*args: int") to simply
#"Concatenate[...]", basically. Previously, we thought that was the best we
#could do. However, it turns out that PEP 646 under Python >= 3.11 provides an
#obscure means of representing variadic positional arguments with *UNPACKED
#TUPLE TYPE HINTS*. Notably:
#    The behavior of a Callable containing an unpacked item, whether the item is
#    a TypeVarTuple or a tuple type, is to treat the elements as if they were
#    the type for *args. So, Callable[[*Ts], None] is treated as the type of the
#    function:
#        def foo(*args: *Ts) -> None: ...
#
#    Callable[[int, *Ts, T], Tuple[T, *Ts]] is treated as the type of the
#    function:
#        def foo(*args: *Tuple[int, *Ts, T]) -> Tuple[T, *Ts]: ...
#
#Given the above, it *SHOULD* theoretically follow that the type hint inferred
#from a callable with signature:
#    def muh_func(*args: int) -> None:
#
#...is this "Callable[...]" type hint:
#    Callable[[*tuple[int]], None]
#
#We know. Looks weird, but that's what a casual reading of the above section
#explicitly suggests. Let's test that theory against mypy, please.
#FIXME: *HMM.* Looks like mypy currently fails to type-check this properly. mypy
#assorts that the following code snippet passes. Surely that isn't right,
#though?
#    from collections.abc import Callable
#
#    def muh_func(*args: int) -> None: pass
#    def moo_func(*args: float) -> None: pass
#    def ugh(glugh: Callable[[*tuple[int]], None]) -> None: pass
#
#    ugh(muh_func)  # <-- this passes. GOOD!
#    ugh(moo_func)  # <-- this passes, too. BAD!
#
#Why does mypy pass both? Is mypy bugged? Is our reading of PEP 646 bugged? Does
#mypy simply fail to fully support PEP 646? That would kinda explain why nobody
#has bothered @beartype about supporting PEP 646, frankly. We're currently
#inclined to believe that mypy has yet to implement this. Surely mypy should be
#saying *SOMETHING* about that case, even if that something is to just notify us
#of how "creative" we are. Let's check back sometime in 2025, please.

#    >>> from beartype.bite import infer_hint
#
#    # Ideally, this...
#    >>> infer_hint(lambda: None, True)
#    collections.abc.Callable
#
#    # ...should instead resemble this.
#    >>> infer_hint(lambda: None, True)
#    collections.abc.Callable[[], object]

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Callable,
    Optional,
)
from beartype._cave._cavefast import (
    HintPep612ParamSpecArgType,
    HintPep612ParamSpecType,
)
from beartype._data.func.datafuncarg import ARG_NAME_RETURN
from beartype._data.typing.datatypingport import (
    Hint,
    ListHints,
)
from beartype._data.hint.sign.datahintsigns import (
    HintSignParamSpecArgs,
    HintSignParamSpecKwargs,
)
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.func.arg.utilfuncargiter import (
    ArgKind,
    ArgMandatory,
    iter_func_args,
)
from beartype._util.func.utilfunctest import is_func_codeobjable
from beartype._util.func.utilfuncwrap import unwrap_func_all_isomorphic
from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none
from beartype._util.hint.pep.proposal.pep612 import (
    get_hint_pep612_paramspec,
    make_hint_pep612_concatenate_list_or_none,
)
from beartype._util.hint.pep.proposal.pep649 import (
    get_pep649_hintable_annotations)
from beartype._util.py.utilpyversion import IS_PYTHON_AT_LEAST_3_11
from collections.abc import (
    Callable as CallableABC,
)

# ....................{ INFERERS                           }....................
#FIXME: Unit test us up, please.
#FIXME: Revise docstring up, please.
@callable_cached
def infer_hint_callable(func: CallableABC) -> Hint:
    '''
    **Callable type hint** (i.e., :class:`collections.abc.Callable` protocol
    possibly subscripted by two or more child type hints describing the
    parameters and return) validating the passed callable.

    Specifically, this function (in order):

    #. If the passed callable is non-pure-Python *and*:

       * If the passed callable wraps a lower-level pure-Python callable (e.g.,
         via the standard :func:`functools.wraps` decorator), then the passed
         callable is iteratively unwrapped until obtaining the lowest-level
         pure-Python callable that is *not* such a wrapper.
       * Else, the unsubscripted :class:`collections.abc.Callable` protocol is
         returned as is.

    #. If that callable is unannotated, the unsubscripted
       :class:`collections.abc.Callable` protocol is returned as is.
    #. Else, that callable is annotated by one or more parameter and/or return
       child type hints. If that callable accepts *no* parameters, that callable
       *must* have been annotated by only a return child type hint. In this
       case, the :pep:`585`-compliant type hint ``collections.abc.Callable[...,
       {hint_return}]`` is returned.
    #. Else, that callable accepts one or more parameters. If those parameters
       are all unannotated, the :pep:`585`-compliant type hint
       ``collections.abc.Callable[..., {hint_return}]`` is again returned.
    #. Else, one or more of those parameters are annotated. If that callable
       accepts only mandatory positional-only and/or flexible parameters, the
       :pep:`585`-compliant type hint
       ``collections.abc.Callable[[{hint_arg_1}, ???, {hint_arg_N}],
       {hint_return}]`` is returned.
    #. Else, that callable accepts one or more of the following:

       * An optional positional-only parameter.
       * An optional flexible parameter.
       * A variadic positional parameter.
       * A keyword-only parameter.
       * A variadic keyword parameter.

       Several distinct cases now arise:

       * If that callable accepts a variadic positional parameter annotated by
         the :pep:`612`-compliant ``P.args`` parameter child type hint *and* a
         corresponding variadic keyword parameter annotated by the
         :pep:`612`-compliant ``P.kwargs`` parameter child type hint for some
         :pep:`612`-compliant **parameter specification** (i.e.,
         :obj:`typing.ParamSpec` object) ``P`` *and*:

         * No other parameters, the :pep:`612`-compliant type hint
           ``collections.abc.Callable[P, {hint_return}]`` is returned.
         * Only one or more mandatory positional-only and/or flexible
           parameters, the :pep:`612`-compliant type hint
           ``collections.abc.Callable[typing.Concatenate[{hint_arg_1}, ???,
           {hint_arg_N}, P]], {hint_return}]`` is returned.
         * Else, that callable accepts one or more parameters that *cannot* be
           annotated under any existing PEP standard. In this case, these
           unsupported parameters *must* be ignored by replacing the trailing
           ``P`` subscripting the prior ``typing.Concatenate[???]`` child type
           hint with an **ellipsis** (i.e., ``...`` singleton). Although
           undocumented, at least mypy_ and possibly other static type-checkers
           (e.g., pyright_) have extended :pep:`612` for unknown reasons to
           permit this replacement. Interestingly, this undocumented behaviour
           does *not* support both a parameter specification and an ellipsis;
           this behaviour only supports either a parameter specification *or* an
           ellipsis. While the ellipsis is necessary here, the parameter
           specification is not and *must* thus be dropped. Let ``N`` be the
           0-based index of the last mandatory positional-only and/or flexible
           parameter in the signature of that callable. Then, in this case, the
           ludicrous :pep:`612`-compliant type hint
           ``collections.abc.Callable[typing.Concatenate[{hint_arg_1}, ???,
           {hint_arg_N}, ...]], {hint_return}]`` is returned.

       * Else, that callable again accepts one or more parameters that *cannot*
         be annotated under any existing PEP standard. In this case, these
         unsupported parameters *must* be ignored by abusing the
         :pep:`612`-compliant :obj:`typing.Concatenate` type hint factory.
         Although the child parameter list of :pep:`585`-compliant
         ``collections.abc.Callable[[{hint_args}], {hint_return}]`` type hints
         does *not* support an ellipsis, the child parameter list of
         :pep:`612`-compliant
         ``collections.abc.Callable[typing.Concatenate[{hint_args}],
         {hint_return}]`` type hints does. In theory, :pep:`612` should *not*
         apply here, as that callable accepts *no* :pep:`612`-compliant
         parameter specification. In practice, :pep:`612` can be abused to
         support otherwise unsupportable parameters. Again, let ``N`` be the
         0-based index of the last mandatory positional-only and/or flexible
         parameter in the signature of that callable. Then, in this case, the
         ludicrous :pep:`612`-compliant type hint
         ``collections.abc.Callable[typing.Concatenate[{hint_arg_1}, ???,
         {hint_arg_N}, ...]], {hint_return}]`` is returned.

    Although admittedly imperfect, this inference strategy nonetheless supports
    a *much* broader set of callable signatures with *much* narrower type hints
    than existing PEP standards would superficially appear to support.

    This function is memoized for efficiency.

    Parameters
    ----------
    func : CallableABC
        Callable to infer a type hint from.

    Returns
    -------
    Hint
        Callable type hint validating this callable.

    See Also
    --------
    https://stackoverflow.com/a/77467213/2809027
        StackOverflow answer inspiring this implementation.
    '''

    # ....................{ LOCALS                         }....................
    # Preserve the passed callable under a different name for subsequent reuse.
    func_wrapper = func

    # If the passed callable isomorphically wraps another lower-level callable
    # (i.e., if the former is a @functools.wraps()-decorated callable accepting
    # *ONLY* "*args, **kwargs" parameters), reduce the former to the latter.
    func = unwrap_func_all_isomorphic(func_wrapper)

    #FIXME: *HANDLE THIS.* Do so in a similar manner to that of the
    #beartype._decor.decornontype.beartype_pseudofunc() function, please.
    #Namely, attempt to see whether the "func.__call__" instance variable exists
    #and is a pure-Python callable. If so, replace "func" with that: e.g.,
    #    func = getattr(func, '__call__', None)
    #    if func is None:
    #        return obj.__class__  # <-- don't return "Callable" here, because.
    #
    #Even then, we should embed this "Callable[...]" type hint inside an
    #"Annotated[...]" parent type hint ensuring that only objects of the passed
    #object's type are matched. See similar logic in the "infercollectionsabc"
    #submodule: e.g.,
    #    return Annotated[hint, IsInstance[obj.__class__]]

    # If this unwrapped callable is *NOT* pure-Python, this is a pseudo-callable
    # (i.e., arbitrary pure-Python *OR* C-based object whose class defines the
    # __call__() dunder method enabling this object to be called like a standard
    # callable). In this case, trivially return the unsubscripted
    # "collections.abc.Callable" protocol.
    if not is_func_codeobjable(func):
        return Callable
    # Else, this callable is pure-Python.

    # Hint to be returned, defaulting to the unsubscripted
    # "collections.abc.Callable" protocol.
    hint: Hint = Callable

    # Dictionary mapping from the name of each annotated parameter accepted by
    # that unwrapped callable to the type hint annotating that parameter.
    #
    # Note that:
    # * The functools.update_wrapper() function underlying the
    #   @functools.wrap decorator underlying all sane decorators propagates this
    #   dictionary from lower-level wrappees to higher-level wrappers by
    #   default. We intentionally access the annotations dictionary of this
    #   higher-level wrapper, which *SHOULD* be the superset of that of this
    #   lower-level wrappee (and thus more reflective of reality).
    # * Even if that callable is unannotated (i.e., this dictionary is empty),
    #   we explicitly do *NOT* silently reduce to a noop by returning the
    #   unsubscripted "collections.abc.Callable" protocol. Why not? Because this
    #   function infers more than merely the type hints annotating callable
    #   parameters and returns; this function also infers the *NUMBER* of
    #   parameters accepted by that callable: e.g.,
    #       # This function correctly infers that a lambda function accepting
    #       # *NO* parameters should be annotated as such.
    #       >>> infer_hint(lambda: None)
    #       collections.abc.Callable[[], object]
    pith_name_to_hint = get_pep649_hintable_annotations(func_wrapper)

    # dict.get() method bound to this dictionary, localized for efficiency.
    pith_name_to_hint_get = pith_name_to_hint.get

    # Child hint annotating the parameter(s) of that callable.
    #
    # This hint is initially defined as the list of all child hints annotating
    # *ONLY* the mandatory positional-only and mandatory flexible parameters of
    # that callable if that callable accepts such parameters *OR* the empty list
    # otherwise. This list is subsequently used to synthesize the lead child
    # hints subscripting the parent PEP 612-compliant "typing.Concatenate[...]"
    # hint, which then becomes the first child hint subscripting the returned
    # root PEP 585-compliant "typing.Callable[...]" hint.
    #
    # This initial list may be subsequently replaced with a more appropriate
    # hint suitable for use as the first child hint subscripting the returned
    # PEP 585-compliant "typing.Callable[...]" hint. In short: non-trivial af.
    hint_args: object = []

    # Child hint annotating the return of that callable, defined as either:
    # * If this return is annotated, the hint annotating this return.
    # * Else, by process of elimination, one or more parameters of this callable
    #   are annotated instead. Logic below synthesizes the parent hint to be
    #   returned by subscripting the "collections.abc.Callable" hint factory
    #   with the list of these parameter child hints. PEP 484 makes *NO*
    #   provision for subscripting this factory with only
    #   parameter child hints (and no return child hint); instead, PEP 484
    #   requires this factory *ALWAYS* be subscripted by both parameter and
    #   return child hints. Ergo, a return child hint is *ALWAYS* necessary.
    #   This being the case, we default to the ignorable "object" supertype.
    hint_return = pith_name_to_hint_get(ARG_NAME_RETURN, object)

    # True only if that callable accepts one or more parameters.
    is_args = False

    # True only if one or more parameters of that callable *cannot* be
    # annotated as parameter child type hints of a parent
    # "Callable[[...], Any]" type hint.
    #
    # See the docstring for detailed discussion of which kinds of parameters can
    # and cannot be annotated as parameter child type hints.
    is_arg_unhintable = False

    # PEP 612-compliant parameter specification variadic positional parameter
    # instance variable (e.g., "*args: P.args") if that callable accepts a
    # variadic positional parameter annotated by such a variable *OR* "None".
    pep612_paramspec_args: Optional[HintPep612ParamSpecArgType] = None

    # PEP 612-compliant parameter specification that is the parent of both
    # variadic positional and keyword parameter instance variables annotating
    # the variadic positional and keyword parameters accepted by that callable
    # (e.g., the "P" in "*args: P.args, **kwargs: P.kwargs") if that callable
    # accepts such parameters *OR* "None" otherwise.
    pep612_paramspec: Optional[HintPep612ParamSpecType] = None

    # ....................{ SEARCH                         }....................
    # For the kind, name, and default value of of each parameter accepted by
    # that callable (in declaration order)...
    for arg_kind, arg_name, arg_default in iter_func_args(
        # Possibly lowest-level wrappee underlying the passed possibly
        # higher-level wrapper. The latter typically fails to convey the same
        # callable metadata conveyed by the former -- including the names and
        # kinds of parameters accepted by the possibly unwrapped callable. This
        # renders the latter mostly useless for our purposes.
        func=func,
        # Avoid inefficiently attempting to re-unwrap this wrappee.
        is_unwrap=False,
    ):
        # Child hint annotating this parameter if any *OR* the root "object"
        # superclass otherwise.
        hint_arg: Hint = pith_name_to_hint_get(arg_name, object)

        # Note that that callable accepts one or more parameters.
        is_args = True

        # If this is a keyword-only parameter, this parameter is unsupported by
        # any existing PEP standard. Record this and halt iteration.
        if arg_kind is ArgKind.KEYWORD_ONLY:
            is_arg_unhintable = True
            break
        # Else, this is *NOT* a keyword-only parameter.
        #
        # If this is a variadic positional parameter...
        elif arg_kind is ArgKind.VARIADIC_POSITIONAL:
            # If this parameter is annotated...
            if hint_arg is not object:
                # Sign uniquely identifying this hint if this hint is
                # PEP-compliant *OR* "None" (i.e., if this hint is a
                # PEP-noncompliant type).
                hint_arg_sign = get_hint_pep_sign_or_none(hint_arg)

                # If this variadic positional parameter is annotated by a PEP
                # 612-compliant parameter specification variadic positional
                # parameter instance variable (e.g., resembling "*args:
                # P.args"), record this and continue to the next parameter.
                if hint_arg_sign is HintSignParamSpecArgs:
                    pep612_paramspec_args = hint_arg  # pyright: ignore
                    continue
                # Else, this variadic positional parameter is annotated by a
                # type hint unsupported by any existing PEP standard.
            # Else, this parameter is unannotated.

            # Else, this variadic positional parameter is either unannotated
            # *OR* annotated by a type hint unsupported by any existing PEP
            # standard. In either case, record this and halt iteration.
            is_arg_unhintable = True
            break
        # Else, this is *NOT* a variadic positional parameter.
        #
        # If this is a variadic keyword parameter...
        elif arg_kind is ArgKind.VARIADIC_KEYWORD:
            # If this parameter is annotated...
            if hint_arg is not object:
                # Sign uniquely identifying this hint if this hint is
                # PEP-compliant *OR* "None" (i.e., if this hint is a
                # PEP-noncompliant type).
                hint_arg_sign = get_hint_pep_sign_or_none(hint_arg)

                # If this variadic keyword parameter is annotated by a PEP
                # 612-compliant parameter specification variadic keyword
                # parameter instance variable (e.g., resembling "**kwargs:
                # P.kwargs")..., record this and continue to the next parameter.
                if hint_arg_sign is HintSignParamSpecKwargs:
                    # If that callable also accepts a variadic positional
                    # parameter annotated by a corresponding PEP 612-compliant
                    # parameter specification variadic positional parameter
                    # instance variable...
                    if pep612_paramspec_args:
                        # PEP 612-compliant parent parameter specifications
                        # containing this pair of instance variables.
                        pep612_paramspec_args_paramspec = (
                            get_hint_pep612_paramspec(
                                pep612_paramspec_args))
                        pep612_paramspec_kwargs_paramspec = (
                            get_hint_pep612_paramspec(hint_arg))  # pyright: ignore

                        # If this pair of instance variables derive from the
                        # same PEP 612-compliant parent parameter specification,
                        # record this and halt iteration. By definition, *NO*
                        # parameters follow this parameter; the variadic keyword
                        # parameter is *ALWAYS* the last possible parameter in
                        # any parameter list.
                        if (
                            pep612_paramspec_args_paramspec is
                            pep612_paramspec_kwargs_paramspec
                        ):
                            pep612_paramspec = (
                                pep612_paramspec_args_paramspec)
                            break
                        # Else, this pair of instance variables derive from
                        # different PEP 612-compliant parent parameter
                        # specifications. This is horrible. Who would do
                        # something horrible like this? Somebody horrible.
                    # Else, that callable fails to accept such a variadic
                    # positional parameter.
                # Else, this variadic keyword parameter is annotated by a type
                # hint unsupported by any existing PEP standard.
            # Else, this parameter is unannotated.

            # Else, this variadic keyword parameter is either unannotated *OR*
            # annotated by a type hint unsupported by any existing PEP standard.
            # In either case, record this and halt iteration.
            is_arg_unhintable = True
            break
        # Else, this is *NOT* a variadic keyword parameter. By process of
        # elimination, this *MUST* be either a positional-only or flexible
        # parameter.
        #
        # If this is an optional positional-only or flexible parameter, this
        # parameter is unsupported by any existing PEP standard. Record this and
        # halt iteration.
        elif arg_default is not ArgMandatory:
            is_arg_unhintable = True
            break
        # Else, this is either a mandatory positional-only *OR* mandatory
        # flexible parameter. In either case, append the child hint annotating
        # this mandatory parameter to the list of all child parameter hints.
        else:
            # print(f'arg "{arg_name}": Found Concatenate[...] child hint {hint_arg}...')
            hint_args.append(hint_arg)  # type: ignore[attr-defined]

    # ....................{ SUBSCRIPT                      }....................
    # If...
    if (
        # That callable accepts a variadic positional parameter annotated by a
        # PEP 612-compliant parameter specification variadic positional
        # parameter instance variable (e.g., resembling "*args: P.args")
        # *AND*...
        pep612_paramspec_args is not None and
        # That callable accepts *NO* corresponding variadic keyword parameter...
        pep612_paramspec is None
    ):
        # Record this variadic positional parameter to be unsupported by any
        # existing PEP standard.
        is_arg_unhintable = True

    # If that callable accepts *NO* parameters, preserve the list of all child
    # parameter hints as the empty list.
    if not is_args:
        pass
    # Else, that callable accepts one or more parameters.
    #
    # If that callable accepts one or more unsupported parameters...
    elif is_arg_unhintable:
        # If the active Python interpreter targets Python >= 3.11, then the PEP
        # 612-compliant "typing(|_extensions).Concatenate" hint factory is
        # subscriptable by a trailing ellipsis. In this case...
        if IS_PYTHON_AT_LEAST_3_11:
            # Generalize the list of all child parameter hints to this factory
            # subscripted by all child hints annotating all mandatory
            # positional-only and flexible parameters accepted by that callable
            # suffixed by the ellipsis ignoring all remaining unsupported
            # parameters.
            #
            # See the docstring for detailed discussion of this behaviour.
            hint_args = make_hint_pep612_concatenate_list_or_none(
                hints_child_first=hint_args, hint_child_last=...)  # type: ignore[arg-type]
            # print(f'PEP 612 Concatenate list: {repr(hint_args)}')

            # If this factory is unimportable, we sadly have *NO* recourse but
            # to silently ignore *ALL* parameters.
            if hint_args is None:
                hint_args = ...
            # Else, this factory is importable. In this case, preserve this hint
            # as is.
        # Else, the active Python interpreter targets Python < 3.11. In this
        # case, the PEP 612-compliant "typing(|_extensions).Concatenate" hint
        # factory is *NOT* subscriptable by a trailing ellipsis. Attempting to
        # do so raises:
        #     TypeError: The last parameter to Concatenate should be a ParamSpec
        #     variable.
        #
        # In this case, we sadly have *NO* recourse but to silently ignore *ALL*
        # parameters.
        else:
            hint_args = ...
    # Else, that callable accepts *NO* unsupported parameters.
    #
    # If that callable accepts a PEP 612-compliant parameter specification...
    elif pep612_paramspec is not None:
        # If that callable accepts one or more mandatory positional-only or
        # flexible parameters...
        if hint_args:
            # Generalize the list of all child parameter hints to the PEP
            # 612-compliant "Concatenate[...]"  hint factory subscripted by all
            # child hints annotating all mandatory positional-only and flexible
            # parameters accepted by that callable suffixed by the this
            # parameter specification.
            hint_args = make_hint_pep612_concatenate_list_or_none(
                hints_child_first=hint_args, hint_child_last=pep612_paramspec)  # type: ignore[arg-type]

            # If this factory is unimportable, we sadly have *NO* recourse but
            # to silently ignore *ALL* parameters.
            if hint_args is None:
                hint_args = ...
            # Else, this factory is importable. In this case, preserve this hint
            # as is.
        # Else, that callable accepts *NO* mandatory positional-only or flexible
        # parameters. In this case, set the list of all child parameter hints to
        # this parameter specification as is.
        else:
            hint_args = pep612_paramspec
    # Else, that callable accepts *NO* PEP 612-compliant parameter
    # specification. In this case, that callable accepts *ONLY* one or more
    # mandatory positional-only and/or flexible parameters. In this case,
    # preserve this list of all child parameter hints as is.

    # ....................{ RETURN                         }....................
    # Callable hint to be returned, defined as either...
    hint = (
        # The unsubscripted "collections.abc.Callable" protocol if...
        Callable
        if (
            # The list of all child parameter hints is the ellipsis (signifying
            # all parameters to be ignorable) *AND*...
            hint_args is ... and
            # The child return hint is the ignorable "object" superclass.
            hint_return is object
        ) else
        # Else, the "collections.abc.Callable" type hint factory subscripted by
        # these unignorable child parameter and return type hints.
        Callable[hint_args, hint_return]  # pyright: ignore
    )

    # Return this hint.
    return hint
