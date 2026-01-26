#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`695`-compliant **type alias** (i.e., objects created via the
``type`` statement under Python >= 3.12) utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: Consider generalizing @beartype's PEP 695 implementation to additionally
#support local type aliases (i.e., defined in the local scope of a callable
#rather than at global scope) containing one or more unquoted forward
#references. Currently, @beartype intentionally fails to support this: e.g.,
#    type global_alias = ...
#    die_if_unbearable('lolwut', global_alias)  # <-- this is fine
#
#    def muh_func(...) -> ...:
#        type local_alias = ...
#        die_if_unbearable('lolwut', local_alias)  # <-- raises an exception
#
#The reasons are obscure. Very well. CPython's current implementation of local
#type aliases is probably very buggy. An upstream issue describing this
#bugginess should be submitted. When doing so, please publicly declare that PEP
#695 appears to have been poorly tested. As evidence, note that PEP 695 itself
#advises use of the following idiom:
#    # A type alias that includes a forward reference
#    type AnimalOrVegetable = Animal | "Vegetable"
#
#*THAT DOES NOT ACTUALLY WORK AT RUNTIME.* Nobody tested that. This is why I
#facepalm. Notably, PEP 604-compliant new-style unions prohibit strings. They
#probably shouldn't, but they've *ALWAYS* behaved that way, and nobody's updated
#them to behave more intelligently -- probably because doing so would require
#updating the isinstance() builtin (which also accepts PEP 604-compliant
#new-style unions) to behave more intelligiently and ain't nobody goin' there:
#e.g.,
#
#    $ python3.12
#    >>> type AnimalOrVegetable = "Animal" | "Vegetable"
#    >>> AnimalOrVegetable.__value__
#    Traceback (most recent call last):
#      Cell In[3], line 1
#        AnimalOrVegetable.__value__
#      Cell In[2], line 1 in AnimalOrVegetable
#        type AnimalOrVegetable = "Animal" | "Vegetable"
#    TypeError: unsupported operand type(s) for |: 'str' and 'str'
#
#For further details, see the comment below prefixed by:
#           # If that module fails to define this alias as a global variable,
#
#Since CPython is unlikely to resolve its bugginess anytime soon, it inevitably
#falls to @beartype to resolve this. Thankfully, @beartype *CAN* resolve this.
#Unthankfully, doing so will require @beartype to implement a new PEP
#695-specific AST transform from the "beartype.claw" subpackage augmenting *ALL*
#PEP 695-compliant local type aliases (so, probably *ALL* type aliases
#regardless of scope for simplicity) as follows:
#    # "beartype.claw" should transform this...
#    type {alias_name} = {alias_value}
#
#    # ...into this.
#    from beartype._util.hint.pep.proposal.pep695 import (
#        iter_hint_pep695_unsubbed_forwardrefs as
#        __iter_hint_pep695_forwardref_beartype__
#    )
#    type {alias_name} = {alias_value}
#    for __hint_pep695_forwardref_beartype__ in (
#        __iter_hint_pep695_forwardref_beartype__({alias_name})):
#        # If the current scope is module scope, prefer an efficient
#        # non-exec()-based solution. Note that this optimization does *NOT*
#        # generalize to other scopes, for obscure reasons delineated here:
#        #     https://stackoverflow.com/a/8028772/2809027
#        if globals() is locals():
#            globals()[__hint_pep695_forwardref_beartype__.__name_beartype__] =
#                __hint_pep695_forwardref_beartype__)
#        # Else, the current scope is *NOT* module scope. In this case,
#        # fallback to an inefficient exec()-based solution.
#        else:
#            exec(f'{__hint_pep695_forwardref_beartype__.__name_beartype__} = __hint_pep695_forwardref_beartype__')
#
#    #FIXME: Technically, this *ONLY* needs to be done if the
#    #iter_hint_pep695_unsubbed_forwardrefs() iterator returned something. *shrug*
#    # Intentionally redefine this alias. Although this appears to be an
#    # inefficient noop, this is in fact an essential operation. Why?
#    # Because the prior successful access of the "__value__" dunder
#    # variable silently cached and thus froze the value of this alias.
#    # However, alias values are *NOT* necessarily safely freezable at
#    # alias definition time. The canonical example of alias values that
#    # are *NOT* safely freezable at alias definition time are mutually
#    # recursive aliases (i.e., aliases whose values circularly refer to
#    # one another): e.g.,
#    #     type a = b
#    #     type b = a
#    #
#    # PEP 695 provides no explicit means of uncaching alias values.
#    # Our only recourse is to repetitiously redefine this alias.
#    type {alias_name} = {alias_value}
#
#We're currently unclear whether anyone actually cares about this. Ergo, we
#adopted the quick-and-dirty approach of raising exceptions instead. Yikes!

# ....................{ IMPORTS                            }....................
from beartype.meta import URL_ISSUES
from beartype.roar import BeartypeDecorHintPep695Exception
from beartype.typing import (
    Iterable,
    Optional,
)
from beartype._cave._cavefast import (
    # HintGenericSubscriptedType,
    HintPep695TypeAlias,
    Pep695ParameterizableTypes,
)
from beartype._check.forward.reference.fwdrefmake import (
    make_forwardref_indexable_subtype)
from beartype._check.forward.reference.fwdrefmeta import BeartypeForwardRefMeta
from beartype._data.typing.datatypingport import Hint
from beartype._data.typing.datatyping import (
    LexicalScope,
    Pep695Parameterizable,
    TuplePep484612646TypeArgsPacked,
)
from beartype._util.error.utilerrget import get_name_error_attr_name
from beartype._util.module.utilmodget import get_module_imported_or_none
from beartype._util.py.utilpyversion import IS_PYTHON_AT_LEAST_3_12
from beartype._data.kind.datakindiota import SENTINEL

# ....................{ TESTERS                            }....................
def is_hint_pep695_subbed(hint: Hint) -> bool:
    '''
    :data:`True` only if the passed type hint is a :pep:`695`-compliant
    **subscripted type alias** (i.e., object created by subscripting an object
    created by a statement of the form ``type {alias_name}[{type_var}] =
    {alias_value}`` by one or more child type hints) is ignorable.

    This tester disambiguates between **unrecognized subscripted builtin type
    hints** (i.e., C-based type hints instantiated by subscripting pure-Python
    origin types unrecognized by :mod:`beartype` and thus PEP-noncompliant)
    from subscripted type aliases (which are clearly :pep:`695`-compliant).
    Superficially, subscripted type aliases resemble unrecognized subscripted
    builtin type hints due to internally reusing the same low-level
    :pep:`585`-compliant :class:`types.GenericAlias` architecture. We sigh.

    This tester is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation efficiently reduces to
    a one-liner.

    Caveats
    -------
    Note that, although subscriptable type aliases superficially appear to be
    "pre-subscripted" by :pep:`484`-compliant type variables, this
    "pre-subscription" is simply syntactic sugar; subscriptable type aliases
    remain unsubscripted until explicitly subscripted by concrete types: e.g.,

    .. code-block:: pycon

       >>> from beartype._util.hint.pep.proposal.pep695 import (
       ...     is_hint_pep695_subbed)
       >>> type subscriptable_alias[T] = int | T
       >>> is_hint_pep695_subbed(subscriptable_alias)
       False
       >>> is_hint_pep695_subbed(subscriptable_alias[float])
       True

    Parameters
    ----------
    hint : Hint
        Type hint to be inspected.

    Returns
    -------
    bool
        :data:`True` only if this hint is a subscripted type alias.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.utilpepget import get_hint_pep_origin_or_none
    # from beartype._util.hint.pep.proposal.pep585 import (
    #     is_hint_pep585_builtin_subbed)

    #FIXME: Actually, this test is surprisingly computationally expensive.
    #Ignore for now as the test below currently suffices. *shrug*
    # # If this hint is a PEP 585-compliant subscripted builtin hint, immediately
    # # return false. All PEP 695-compliant subscripted type aliases are
    # # implemented as PEP 585-compliant subscripted builtin hints, interestingly.
    # if not is_hint_pep585_builtin_subbed(hint):
    #     return False
    # # Else, this hint is a PEP 585-compliant subscripted builtin hint and thus
    # # *COULD* be a PEP 695-compliant subscripted type alias. Further detection
    # # is warranted.

    # Origin (i.e., value of the "__origin__" dunder attribute) originating this
    # hint if this hint originates from such a type *OR* "None" otherwise (i.e.,
    # if this hint originates from such a type).
    hint_origin = get_hint_pep_origin_or_none(hint)

    # Return true only if this origin is a PEP 695-compliant unsubscripted type
    # alias. Yes. It really is this non-trivial, folks. *sigh*
    return isinstance(hint_origin, HintPep695TypeAlias)

# ....................{ GETTERS                            }....................
#FIXME: Unit test us up, please.
def get_hint_pep695_unsubbed_alias(
    # Mandatory parameters.
    hint: HintPep695TypeAlias,

    # Optional parameters.
    exception_prefix: str = '',
) -> Hint:
    '''
    **Non-alias type hint** (i.e., type hint that is *not* a
    :pep:`695`-compliant type alias) encapsulated by the passed
    :pep:`695`-compliant **unsubscripted type alias** (i.e., object created by a
    statement of the form ``type {alias_name} = {alias_value}``).

    This getter is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), for subtle reasons pertaining to unquoted
    forward references. Notably, memoizing this getter would prevent the
    external caller of the higher-level
    :func:`.iter_hint_pep695_unsubbed_forwardrefs` iterator calling this
    lower-level getter from externally modifying this type alias by forcefully
    injecting forward reference proxies into this alias.

    Parameters
    ----------
    hint : HintPep695TypeAlias
        Unsubscripted type alias to be inspected.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    Hint
        Unaliased type hint encapsulated by this type alias.

    Raises
    ------
    BeartypeDecorHintPep695Exception
        If this type hint is *not* an unsubscripted type alias.
    NameError
        If this unsubscripted type alias contains one or more **unquoted forward
        references** to undefined types.
    '''

    # If this hint is *NOT* a PEP 695-compliant unsubscripted type alias, raise
    # an exception.
    if not isinstance(hint, HintPep695TypeAlias):
        raise BeartypeDecorHintPep695Exception(
            f'{exception_prefix}type hint {repr(hint)} '
            f'not PEP 695 unsubscripted type alias.'
        )
    # Else, this hint is a PEP 695-compliant unsubscripted type alias.

    # While the Universe continues infinitely expanding...
    while True:
        # Reduce this type alias to the type hint aliased by this alias, which
        # itself is possibly a nested type alias. Oh, it happens.
        #
        # Note that doing so implicitly raises a "NameError" if this alias
        # contains one or more unquoted forward references to undefined types.
        hint = hint.__value__  # type: ignore[attr-defined]

        # If this type hint is *NOT* a nested type alias, break this iteration.
        if not isinstance(hint, HintPep695TypeAlias):
            break
        # Else, this type hint is a nested type alias. In this case, continue
        # iteratively unwrapping this nested type alias.

    # Return this unaliased type alias.
    return hint

# ....................{ ADDERS                             }....................
#FIXME: Unit test us up, please.
def add_func_scope_hint_pep695_parameterizable_typeparams(
    # Mandatory parameters.
    func_scope: LexicalScope,
    parameterizable: Pep695Parameterizable,

    # Optional parameters.
    exception_prefix: str = '',
) -> None:
    '''
    Add one key-value pair mapping the name to value of each **type parameter**
    (i.e., :pep:`484`-compliant type variable, pep:`612`-compliant parameter
    specification, or :pep:`646`-compliant type variable tuple) implicitly
    instantiated with :pep:`695`-compliant type parameter syntax parametrizing
    the **parameterizable** (i.e., pure-Python class, pure-Python function, or
    :pep:`695`-compliant type alias) described by the passed lexical scope.

    Caveats
    -------
    This function silently overrides existing key-value pairs sharing the same
    names as type parameters parametrizing this parameterizable. Why? Because
    doing so mimics lexical scoping implemented by the CPython parser itself,
    which this function effectively masquerades as.

    Parameters
    ----------
    func_scope : LexicalScope
        Local or global scope to map these type parameters to.
    parameterizable : Pep695Parameterizable
        :pep:`695`-compliant parameterizable to be inspected.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    BeartypeDecorHintPep695Exception
        If either:

        * This object is *not* a :pep:`695`-compliant parameterizable.
        * This object is a :pep:`695`-compliant parameterizable parametrized by
          a type parameter already parametrizing a **parent lexical scope**
          (e.g., class) of this parameterizable. By :pep:`695`, type parameters
          are *not* safely reusable across nested lexical scopes:

              Consistent with the scoping rules defined in PEP 484, type
              checkers should generate an error if inner-scoped generic classes,
              functions, or type aliases reuse the same type parameter name as
              an outer scope.
    '''
    assert isinstance(func_scope, dict), f'{repr(func_scope)} not dictionary.'
    # print(f'Updating PEP 695 parameterizable {repr(parameterizable)} scope {repr(func_scope)}...')

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype._util.hint.pep.proposal.pep484612646 import (
        get_hint_pep484612646_typearg_packed_name,
        is_hint_pep484612646_typearg_packed,
    )

    # ....................{ LOCALS                         }....................
    # Tuple of all type parameters parametrizing this parameterizable.
    typeparams = _get_hint_pep695_parameterizable_typeparams(
        parameterizable=parameterizable, exception_prefix=exception_prefix)
    # print(f'Adding PEP 695 parameterizable {repr(parameterizable)} type parameters {repr(typeparams)}...')

    # ....................{ LOOP                           }....................
    # For each type parameter parametrizing this parameterizable...
    for typeparam in typeparams:
        # Unqualified basename of this type parameter.
        typeparam_name = get_hint_pep484612646_typearg_packed_name(
            hint=typeparam, exception_prefix=exception_prefix)

        # Existing attribute sharing the same name already added to this forward
        # scope by the caller if any *OR* the placeholder sentinel otherwise
        # (i.e., if this scope contains no attribute with this name).
        func_scope_attr = func_scope.get(typeparam_name, SENTINEL)

        # If...
        if (
            # This scope already contains an attribute with this name *AND*...
            func_scope_attr is not SENTINEL and
            # This attribute is also a type parameter...
            is_hint_pep484612646_typearg_packed(func_scope_attr)
        ):
            assert isinstance(exception_prefix, str), (
                f'{repr(exception_prefix)} not string.')

            # Then this previously added type parameter conflicts with this
            # currently iterated type parameter. This common case arises when
            # callers erroneously reuse the name of a type parameter across
            # nested lexical scopes, as explicitly prohibited by PEP 695: e.g.,
            #     class MuhGeneric[T]:       # <-- good
            #         def muh_func[T](): ... # <-- *BAD* according to PEP 695
            raise BeartypeDecorHintPep695Exception(
                f'{exception_prefix}'
                f'nested {repr(parameterizable)} '
                f'PEP 695 type parameter {repr(typeparam)} shadows parent '
                f'PEP 695 type parameter of same name; '
                f'however, PEP 695 prohibits type parameter reuse across '
                f'nested lexical scopes.'
            )
        # Else, either this scope does not already contain an attribute with
        # this name *OR* this scope does but this attribute is not also a type
        # parameter. In either case, this type parameter silently shadows (i.e.,
        # overrides) this attribute. Although attribute shadowing could be
        # regarded as a problematic design pattern indicative of a genuine
        # issue, both CPython and PEP 695 explicitly allow, enable, and arguably
        # encourage attribute shadowing where the attribute being shadowed is
        # itself *NOT* also a type parameter. It's not for @beartype to police
        # valid use cases. That's what static type-checkers do. So, we don't.

        # Map this basename to this type parameter in this lexical scope,
        # silently shadowing any existing attribute of the same name (if any).
        func_scope[typeparam_name] = typeparam


def _get_hint_pep695_parameterizable_typeparams(
    # Mandatory parameters.
    parameterizable: Pep695Parameterizable,

    # Optional parameters.
    exception_prefix: str = '',
) -> TuplePep484612646TypeArgsPacked:
    '''
    Tuple of the zero or more **type parameters** (i.e., :pep:`484`-compliant
    type variables, pep:`612`-compliant parameter specifications, and
    :pep:`646`-compliant type variable tuples) implicitly instantiated with
    :pep:`695`-compliant type parameter syntax parametrizing the passed
    **parameterizable** (i.e., pure-Python class, pure-Python function, or
    :pep:`695`-compliant type alias).

    Parameters
    ----------
    parameterizable : Pep695Parameterizable
        :pep:`695`-compliant parameterizable to be inspected.
    exception_prefix : str, optional
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Returns
    -------
    TuplePep484612646TypeArgsPacked
        Tuple of all type parameters parametrizing this parameterizable.

    Raises
    ------
    BeartypeDecorHintPep695Exception
        If this object is *not* a :pep:`695`-compliant parameterizable.
    '''

    # If this object is *NOT* parameterizable under PEP 695, raise an exception.
    if not isinstance(parameterizable, Pep695ParameterizableTypes):
        raise BeartypeDecorHintPep695Exception(
            f'{exception_prefix}'
            f'{repr(parameterizable)} not PEP 695-parameterizable '
            f'(i.e., neither pure-Python type, pure-Python function, nor '
            f'PEP 695-compliant type alias).'
        )
    # Else, this object is parameterizable under PEP 695.

    # Return either...
    return (
        # If the active Python interpreter targets Python >= 3.12 and thus
        # supports PEP 695, the PEP 695-compliant tuple of all type parameters
        # parametrizing this object.
        parameterizable.__type_params__  # type: ignore[return-value,union-attr]
        if IS_PYTHON_AT_LEAST_3_12 else
        # Else, the active Python interpreter targets Python <= 3.11 and thus
        # fails to support PEP 695. In this case, the empty tuple.
        ()
    )

# ....................{ ITERATORS                          }....................
def iter_hint_pep695_unsubbed_forwardrefs(
    # Mandatory parameters.
    hint: HintPep695TypeAlias,

    # Optional parameters.
    exception_prefix: str = '',
) -> Iterable[BeartypeForwardRefMeta]:
    '''
    Iteratively create and yield one **forward reference proxy** (i.e.,
    :class:`beartype._check.forward.reference.fwdrefabc.BeartypeForwardRefABC`
    subclass) for each unquoted relative forward reference in the passed
    :pep:`695`-compliant **unsubscripted type alias** (i.e., object created by a
    statement of the form ``type {alias_name} = {alias_value}``) to the
    underlying type hint lazily referred to by this type alias.

    This iterator is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as this iterator is intended to be
    called only once per unsubscripted type alias in userspace code dynamically
    instrumented by beartype import hook abstract syntax tree (AST) node
    transformers. Since those transformers are expected to replace *all*
    unquoted relative forward references in this unsubscripted type alias with
    corresponding forward reference proxies, calling this iterator again on any
    unsubscripted type alias instrumented in this way *should* silently reduce
    to a noop. "Should" is doing a lot of heavy lifting here.

    Parameters
    ----------
    hint : HintPep695TypeAlias
        Unsubscripted type alias to be iterated over.
    exception_prefix : str, optional
        Human-readable substring prefixing exception messages raised by this
        reducer. Defaults to the empty string.

    Yields
    ------
    BeartypeForwardRefMeta
        Forward reference proxy encapsulating the next unquoted relative forward
        reference in this unsubscripted type alias.

    Raises
    ------
    BeartypeDecorHintPep695Exception
        If this type hint is *not* an unsubscripted type alias.
    '''

    # Unqualified basename of the previous undeclared attribute in this alias.
    hint_ref_name_prev: Optional[str] = None

    # While this alias still contains one or more forward references to
    # attributes *NOT* defined by the module declaring this alias...
    while True:
        # Attempt to...
        try:
            # print(f'type {hint.__name__} = {hint.__value__}')

            # Reduce this alias to the type hint it lazily refers to. If this
            # alias contains *NO* forward references to undeclared attributes,
            # this reduction *SHOULD* succeed. Let's pretend we mean that.
            #
            # Note that _get_hint_pep695_unsubbed_alias() is memoized and
            # thus intentionally called with positional arguments.
            get_hint_pep695_unsubbed_alias(hint, exception_prefix)

            # This reduction raised *NO* exception and thus succeeded. In this
            # case, immediately halt iteration.
            break
        # If doing so raises a builtin "NameError" exception, this alias
        # contains one or more forward references to undeclared attributes. In
        # this case...
        except NameError as exception:
            # Unqualified basename of this alias (i.e., name of the global or
            # local variable assigned to by the left-hand side of this alias).
            hint_name = repr(hint)

            # Fully-qualified name of the external third-party module defining
            # this alias.
            hint_module_name = hint.__module__
            # print(f'hint_module_name: {hint_module_name}')

            # If this alias defines *NO* module name, raise an exception.
            #
            # Note that this should *NEVER* happen. Nonetheless, static
            # type-checkers like mypy insist this can happen. It almost
            # certainly can't. Nonetheless, let's dot our i's and cross our t's.
            if not hint_module_name:
                raise BeartypeDecorHintPep695Exception(
                    f'{exception_prefix}PEP 695 type alias "{hint_name}" '
                    f'module undefined (i.e., "__module__" attribute '
                    f'either "None" or the empty string).'
                ) from exception
            # Else, this alias defines a module name.

            # That module as its previously imported object.
            hint_module = get_module_imported_or_none(hint_module_name)

            # Unqualified basename of the next remaining undeclared attribute
            # contained in this alias relative to that module.
            hint_ref_name = get_name_error_attr_name(exception)
            # print(f'hint: {hint}; hint_ref_name: {hint_ref_name}')

            # If this attribute is the same as that of the prior iteration of
            # this "while" loop, then that iteration *MUST* have failed to
            # define this attribute as a global variable of that module. In this
            # case, raise an exception.
            #
            # Note that this should *NEVER* happen. Of course, this frequently
            # happens. Specifically, this happens whenever the caller defines a
            # callable defining type alias as a local variable containing one or
            # more unquoted relative forward reference to user-defined classes
            # that have yet to be defined. Why? Because CPython's low-level
            # C-based implementation of PEP 695-compliant type aliases currently
            # fails to properly resolve unquoted relative forward references
            # defined in a local rather than global scope: e.g.,
            #    >>> def foo():
            #    ...     type bar = wut
            #    ...     globals()['wut'] = str
            #    ...     print(bar.__value__)
            #    ...     class wut(object): pass  # <-- causes madness; WTF!?!?
            #    >>> foo()
            #    NameError: cannot access free variable 'wut' where it is not
            #    associated with a value in enclosing scope
            #
            # Why does this matter? Because the abstract syntax tree (AST)
            # transformation implemented by "beartype.claw" import hooks
            # dynamically declares the objects that these forward references
            # refer. Due to deficiencies [read: bugs] in CPython's type alias
            # implementation, local type aliases remain unable to resolve either
            # global *OR* local referees that are defined dynamically. Ergo, we
            # have no recourse but to detect this edge case and raise a
            # human-readable exception advising the caller with recommendations.
            if hint_ref_name == hint_ref_name_prev:
                raise BeartypeDecorHintPep695Exception(
                    f'{exception_prefix}PEP 695 local type alias "{hint_name}" '
                    f'unquoted relative forward reference "{hint_ref_name}" '
                    f"unsupported, due to severe deficiencies in CPython's "
                    f'runtime implementation of PEP 695 local type aliases '
                    f"outside beartype's control. Consider either:\n"
                    f'* Refactoring this local type alias into a '
                    f'global type alias:\n'
                    f'      # Instead of a local type alias '
                    f'defined in a callable like this...\n'
                    f'      def muh_func(...) -> ...:\n'
                    f'          type {hint_name} = ...\n'
                    f'\n'
                    f'      # Prefer a global type alias defined at module scope.\n'
                    f'      type {hint_name} = ...\n'
                    f'* Quoting this forward reference in this type alias:\n'
                    f'      # Instead of an unquoted forward reference '
                    f'like this...\n'
                    f'      type {hint_name} = ... {hint_ref_name} ...\n'
                    f'\n'
                    f'      # Prefer a quoted forward reference.\n'
                    f'      type {hint_name} = ... "{hint_ref_name}" ...'
                ) from exception
            # Else, this attribute differs from that of the prior iteration of
            # this "while" loop.
            #
            # If that module paradoxically claims to already define this
            # attribute as a global variable, raise an exception.
            #
            # Note that this should *NEVER* happen. Of course, this will happen.
            elif hasattr(hint_module, hint_ref_name):
                raise BeartypeDecorHintPep695Exception(  # pragma: no cover
                    f'{exception_prefix}PEP 695 type alias "{hint_name}" '
                    f'unquoted relative forward reference "{hint_ref_name}" '
                    f'already defined in module "{hint_module_name}", '
                    f'despite purportedly being undefined. '
                    f'In theory, this should never happen. '
                    f'Of course, this happened. You suddenly feel the '
                    f'horrifying urge to report this grievous failure to the '
                    f'beartype issue tracker:\n\t{URL_ISSUES}'
                ) from exception
            # Else, that module does *NOT* yet define this attribute.

            # Forward reference proxy to this undeclared attribute.
            #
            # Note that:
            # * This call is intentionally passed only positional parameters to
            #   satisfy the @callable_cached decorator memoizing this function.
            # * A full-blown forward reference proxy rather than a trivial
            #   stringified forward reference (i.e., the relative name of the
            #   undefined attribute being referred to, equivalent to
            #   "hint_ref_name") is required here. Why? Subscription. A
            #   stringified forward reference *CANNOT* be subscripted by
            #   arbitrary child type hints; a forward reference proxy can be.
            hint_ref = make_forwardref_indexable_subtype(
                hint_module_name, hint_ref_name)

            # Yield this forward reference proxy to the caller.
            yield hint_ref

            # Store the unqualified basename of this previously undeclared
            # attribute for detection by the next iteration of this loop.
            hint_ref_name_prev = hint_ref_name
