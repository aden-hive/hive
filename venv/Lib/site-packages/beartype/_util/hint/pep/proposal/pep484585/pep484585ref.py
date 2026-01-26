#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`- and :pep:`585`-compliant **forward reference type hint
utilities** (i.e., callables generically applicable to both :pep:`484`- and
:pep:`585`-compliant forward reference type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintForwardRefException
from beartype.typing import (
    Optional,
    Tuple,
)
from beartype._cave._cavemap import NoneTypeOr
from beartype._data.cls.datacls import (
    TYPE_BUILTIN_NAME_TO_TYPE,
    TYPES_PEP484585_REF,
)
from beartype._data.typing.datatyping import (
    Pep484585ForwardRef,
    TypeException,
    TypeStack,
)
from beartype._data.api.standard.datapy import BUILTINS_MODULE_NAME
from beartype._util.module.utilmodget import get_object_module_name_or_none
from beartype._util.module.utilmodtest import is_module
from beartype._util.text.utiltextlabel import label_callable
from collections.abc import (
    Callable,
    Sequence,
)

# ....................{ RAISERS                            }....................
#FIXME: Validate that this forward reference string is *NOT* the empty string.
#FIXME: Validate that this forward reference string is a syntactically valid
#"."-delimited concatenation of Python identifiers. We already have logic
#performing that validation somewhere, so let's reuse that here, please.
#Right. So, we already have an is_identifier() tester; now, we just need to
#define a new die_unless_identifier() validator.
def die_unless_hint_pep484585_ref(
    # Mandatory parameters.
    hint: object,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintForwardRefException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise an exception unless the passed object is either a :pep:`484`- or
    :pep:`585`-compliant **forward reference type hint** (i.e., object
    referring to a user-defined class that typically has yet to be defined).

    Equivalently, this validator raises an exception if this object is neither:

    * A string whose value is the syntactically valid name of a class.
    * An instance of the :class:`typing.ForwardRef` class. The :mod:`typing`
      module implicitly replaces all strings subscripting :mod:`typing` objects
      (e.g., the ``MuhType`` in ``List['MuhType']``) with
      :class:`typing.ForwardRef` instances containing those strings as instance
      variables, for nebulous reasons that make little justifiable sense but
      what you gonna do 'cause this is 2020. *Fight me.*

    Parameters
    ----------
    hint : object
        Object to be validated.
    exception_cls : Type[Exception], default: BeartypeDecorHintForwardRefException
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`.BeartypeDecorHintForwardRefException`.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    exception_cls
        If this object is *not* a forward reference type hint.
    '''

    # If this object is *NOT* a forward reference type hint, raise an exception.
    if not isinstance(hint, TYPES_PEP484585_REF):
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not exception subclass.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} not forward reference '
            f'(i.e., neither string nor "typing.ForwardRef" object).'
        )
    # Else, this object is a forward reference type hint.

# ....................{ GETTERS                            }....................
#FIXME: Unit test us up, please.
def get_hint_pep484585_ref_names(
    # Mandatory parameters.
    hint: Pep484585ForwardRef,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintForwardRefException,
    exception_prefix: str = '',
) -> Tuple[Optional[str], str]:
    '''
    Possibly undefined fully-qualified module name and possibly qualified
    classname referred to by the passed **forward reference type hint** (i.e.,
    object indirectly referring to a user-defined class that typically has yet
    to be defined).

    This getter is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation mostly reduces to an
    efficient one-liner.

    Caveats
    -------
    **Callers are recommended to call the higher-level**
    :func:`.get_hint_pep484585_ref_names_relative_to` **getter rather than this
    lower-level getter,** which fails to guarantee canonicalization and is thus
    considerably less safe.

    Parameters
    ----------
    hint : object
        Forward reference to be introspected.
    exception_cls : Type[Exception]
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`.BeartypeDecorHintForwardRefException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Returns
    -------
    Tuple[Optional[str], str]
        2-tuple ``(ref_module_name, ref_name)`` where:

        * ``ref_module_name`` is the possibly undefined fully-qualified module
          name referred to by this forward reference, defined as either:

          * If this forward reference is a :class:`typing.ForwardRef` object
            passed a module name at instantiation time via the ``module``
            parameter, this module name.
          * Else, :data:`None`.

        * ``ref_name`` is the possibly qualified classname referred to by this
          forward reference.

    Raises
    ------
    exception_cls
        If either:

        * This forward reference is *not* actually a forward reference.
        * This forward reference is **relative** (i.e., contains *no* ``.``
          delimiters) and either:

          * Neither the passed callable nor class define the ``__module__``
            dunder attribute.
          * The passed callable and/or class define the ``__module__``
            dunder attribute, but the values of those attributes all refer to
            unimportable modules that do *not* appear to physically exist.

    See Also
    --------
    :func:`.get_hint_pep484585_ref_name`
        Lower-level getter returning possibly relative forward references.
    '''

    # If this is *NOT* a forward reference, raise an exception.
    die_unless_hint_pep484585_ref(hint)
    # Else, this is a forward reference.

    # Possibly unqualified basename of the class to which reference refers.
    hint_name: str = None  # type: ignore[assignment]

    # Fully-qualified name of the module to which this reference is relative if
    # this reference is relative to an importable module *OR* "None" otherwise
    # (i.e., if this reference is either absolute and thus not relative to a
    # module *OR* relative to an unimportable module).
    #
    # Note that, although *ALL* callables and classes should define the
    # "__module__" instance variable underlying the call to this getter, *SOME*
    # callables and classes do not. For this reason, we intentionally:
    # * Call the get_object_module_name_or_none() getter rather than
    #   get_object_module_name().
    # * Explicitly detect "None".
    # * Raise a human-readable exception.
    #
    # Doing so produces significantly more readable exceptions than merely
    # calling get_object_module_name(). Problematic objects include:
    # * Objects defined in Sphinx-specific "conf.py" configuration files. In all
    #   likelihood, Sphinx is running these files in some sort of arcane and
    #   non-standard manner (over which beartype has *NO* control).
    hint_module_name: Optional[str] = None

    # If this reference is a string, the classname of this reference is this
    # reference itself.
    if isinstance(hint, str):
        hint_name = hint
    # Else, this reference is *NOT* a string. By process of elimination, this
    # reference *MUST* be a "typing.ForwardRef" instance. In this case...
    else:
        # Forward reference classname referred to by this reference.
        hint_name = hint.__forward_arg__

        # Fully-qualified name of the module to which this presumably
        # relative forward reference is relative to if any *OR* "None"
        # otherwise (i.e., if *NO* such name was passed at forward reference
        # instantiation time).
        #
        # Since the active Python interpreter targets >= Python 3.10, this
        # "typing.ForwardRef" object defines an optional "__forward_module__:
        # Optional[str] = None" dunder attribute whose value is either:
        # * If Python passed the "module" parameter when instantiating this
        #   "typing.ForwardRef" object, the value of that parameter -- which is
        #   presumably the fully-qualified name of the module to which this
        #   presumably relative forward reference is relative to.
        # * Else, "None".
        #
        # Note that:
        # * This requires violating privacy encapsulation by accessing dunder
        #   attributes unique to "typing.ForwardRef" objects. Sad, yet true.
        # * This object defines a significant number of other
        #   "__forward_"-prefixed dunder instance variables, which exist *ONLY*
        #   to enable the blatantly useless typing.get_type_hints() function to
        #   avoid repeatedly (and thus inefficiently) reevaluating the same
        #   forward reference. *sigh*
        # * Technically, this dunder attribute has been defined since at least
        #   Python >= 3.9.18. Sadly, one or more unknown earlier patch releases
        #   of the Python 3.9 development cycle do *NOT* support this. This is
        #   currently only safely usable under Python >= 3.10 -- all patch
        #   releases of which are known to define this dunder attribute.
        hint_module_name = hint.__forward_module__

    # Return metadata describing this forward reference relative to this module.
    return hint_module_name, hint_name


def get_hint_pep484585_ref_names_relative_to(
    # Mandatory parameters.
    hint: Pep484585ForwardRef,

    # Optional parameters.
    cls_stack: TypeStack = None,
    func: Optional[Callable] = None,
    exception_cls: TypeException = BeartypeDecorHintForwardRefException,
    exception_prefix: str = '',
) -> Tuple[Optional[str], str]:
    '''
    Possibly undefined fully-qualified module name and possibly qualified
    classname referred to by the passed **forward reference type hint** (i.e.,
    object indirectly referring to a user-defined class that typically has yet
    to be defined), canonicalized relative to the module declaring the passed
    type stack and/or callable (in that order) if this classname is unqualified.

    This getter is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as the implementation mostly reduces to an
    efficient one-liner.

    Caveats
    -------
    This getter preferentially canonicalizes this forward reference if relative
    against the fully-qualified name of the module defining (in order):

    #. The passed class stack if *not* :data:`None`.
    #. The passed callable.

    This getter thus prioritizes classes over callables. Why? Because classes
    are more likely to define ``__module__`` dunder attributes referring to
    importable modules that physically exist. Why? Because dynamically
    synthesizing in-memory callables residing in imaginary and thus unimportable
    modules is trivial; dynamically synthesizing in-memory classes residing in
    imaginary and thus unimportable modules is less trivial.

    Consider the standard use case for :mod:`beartype`: beartype import hooks
    declared by the :mod:`beartype.claw` subpackage. Although hooks directly
    apply the :func:`beartype.beartype` decorator to classes and functions
    residing in importable modules that physically exist, that decorator then
    dynamically iterates over the methods of those classes. That iteration is
    dynamic and iterates over methods that both physically exist and only
    dynamically exist in-memory in unimportable modules.

    Does this edge case arise in real-world code? All too frequently. For
    unknown reasons, the :class:`typing.NamedTuple` superclass dynamically
    generates dunder methods (e.g., ``__new__``) whose ``__module__`` dunder
    attributes erroneously refer to imaginary and thus unimportable modules
    ``named_{subclass_name}`` for the unqualified basename ``{subclass_name}``
    of the current user-defined class subclassing :class:`typing.NamedTuple`
    despite that user-defined class residing in an importable module: e.g.,

    .. code-block:: pycon

       >>> from beartype import beartype
       >>> from typing import NamedTuple

       >>> @beartype
       ... class NamelessTupleIsBlameless(NamedTuple):
       ...     forward_ref: 'UndefinedType'

       >>> NamelessTupleIsBlameless.__module__
       '__main__'                        # <-- makes sense
       >>> NamelessTupleIsBlameless.__new__.__module__
       'named_NamelessTupleIsBlameless'  # <-- lol wut

    If this getter erroneously prioritized callables over classes *and* blindly
    accepted imaginary modules as valid, this getter would erroneously resolve
    the relative forward reference ``'UndefinedType'`` to
    ``'named_NamelessTupleIsBlameless.UndefinedType'`` rather than to
    ``'__main__.UndefinedType'``. And... this is why @leycec is currently bald.

    Parameters
    ----------
    hint : object
        Forward reference to be canonicalized.
    cls_stack : TypeStack
        Either:

        * If this forward reference annotates a method of a class, the
          corresponding **type stack** (i.e., tuple of the one or more
          :func:`beartype.beartype`-decorated classes lexically containing that
          method). If this forward reference is unqualified (i.e., relative),
          this getter then canonicalizes this reference against that class.
        * Else, :data:`None`.

        Defaults to :data:`None`.
    func : Optional[Callable]
        Either:

        * If this forward reference annotates a callable, that callable.
          If this forward reference is also unqualified (i.e., relative), this
          getter then canonicalizes this reference against that callable.
        * Else, :data:`None`.

        Defaults to :data:`None`.
    exception_cls : Type[Exception]
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`.BeartypeDecorHintForwardRefException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Returns
    -------
    Tuple[Optional[str], str]
        2-tuple ``(ref_module_name, ref_name)`` where:

        * ``ref_module_name`` is the possibly undefined fully-qualified module
          name referred to by this forward reference, defined as either:

          * If this forward reference is a :class:`typing.ForwardRef` object
            passed a module name at instantiation time via the ``module``
            parameter *or* a type stack or callable defining a module name via
            the ``__module`` dunder attribute are passed, this module name.
          * Else, :data:`None`.

        * ``ref_name`` is the possibly qualified classname referred to by this
          forward reference.

    Raises
    ------
    exception_cls
        If either:

        * This forward reference is *not* actually a forward reference.
        * This forward reference is **relative** (i.e., contains *no* ``.``
          delimiters) and either:

          * Neither the passed callable nor class define the ``__module__``
            dunder attribute.
          * The passed callable and/or class define the ``__module__``
            dunder attribute, but the values of those attributes all refer to
            unimportable modules that do *not* appear to physically exist.

    See Also
    --------
    :func:`.get_hint_pep484585_ref_names`
        Lower-level getter returning possibly relative forward references.
    '''

    # Possibly undefined fully-qualified module name and possibly unqualified
    # classname referred to by this forward reference.
    hint_module_name, hint_ref_name = get_hint_pep484585_ref_names(
        hint=hint,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # If either...
    if (
        # This reference was instantiated with a module name *OR*...
        hint_module_name or
        # This classname contains one or more "." characters and is thus already
        # (...hopefully) fully-qualified...
        '.' in hint_ref_name
    # Then this classname is either absolute *OR* relative to some module. In
    # either case, the class referred to by this reference can now be
    # dynamically imported at a later time. In this case...
    ):
        # Return this metadata as is.
        return hint_module_name, hint_ref_name
    # Else, this classname is relative to a module whose fully-qualified name
    # has yet to be decided.
    #
    # If this reference does *NOT* annotate a callable, then this reference also
    # does *NOT* annotate a method of a class (i.e., "cls is None"). Why?
    # Because a method is a callable. In this case...
    elif not func:
        # If a builtin type with this classname exists, assume this reference
        # refers to this builtin type exposed by the standard "builtins" module.
        if hint_ref_name in TYPE_BUILTIN_NAME_TO_TYPE:
            hint_module_name = BUILTINS_MODULE_NAME
        # Else, this reference does *NOT* refer to a builtin type. In this
        # case, there exists *NO* owner module against which to canonicalize
        # this relative reference. This edge case occurs when this getter is
        # transitively called by a high-level "beartype.door" runtime
        # type-checker (e.g., is_bearable(), die_if_unbearable()). In this case,
        # raise an exception.
        else:
            raise exception_cls(
                f'{exception_prefix}type hint relative forward reference '
                f'"{hint_ref_name}" currently only type-checkable in '
                f'type hints annotating '
                f'@beartype-decorated callables and classes. '
                f'For your own safety and those of the codebases you love, '
                f'consider canonicalizing this '
                f'relative forward reference into an '
                f'absolute forward reference '
                f'(e.g., replace "{hint_ref_name}" with '
                f'"{{your_package}}.{{your_submodule}}.{hint_ref_name}").'
            )
    # Else, this reference annotates a callable and is thus relative to the
    # module defining this callable.

    # Validate sanity.
    assert isinstance(cls_stack, NoneTypeOr[Sequence]), (
        f'{repr(cls_stack)} neither sequence nor "None".')
    assert isinstance(func, NoneTypeOr[Callable]), (
        f'{repr(func)} neither callable nor "None".')

    # If this reference annotates a method of a class...
    if cls_stack:
        # Class currently being decorated by @beartype.
        cls = cls_stack[-1]

        # Fully-qualified name of the module defining that class.
        hint_module_name = get_object_module_name_or_none(cls)
    # Else, this reference does *NOT* annotate a method of a class.

    # If it is *NOT* the case that...
    if not (
        # That class is declared by a module *AND*...
        hint_module_name and
        # That module is importable...
        is_module(hint_module_name)
    # Fallback to...
    ):
        # Fully-qualified name of the callable annotated by this reference.
        hint_module_name = get_object_module_name_or_none(func)

        # If it is *NOT* the case that...
        if not (
            # That callable is declared by a module *AND*...
            hint_module_name and
            # That module is importable...
            is_module(hint_module_name)
        # Fallback to...
        ):
            # If a builtin type with this name exists, assume this reference
            # refers to this builtin type exposed by the "builtins" module.
            #
            # Note that this edge case is shockingly common *AND* distinct from
            # the above similar edge case. Why? The "typing.NamedTuple"
            # superclass, which dynamically generates subclass dunder methods
            # (e.g., __new__()) residing in unimportable fake modules with the
            # name "named_{subclass_name}".
            if hint_ref_name in TYPE_BUILTIN_NAME_TO_TYPE:
                hint_module_name = BUILTINS_MODULE_NAME
            # Else, this reference does *NOT* refer to a builtin type. In this
            # case, there exists *NO* owner module against which to canonicalize
            # this relative reference. Raise an exception, please.
            else:
                # Exception message to be raised.
                exception_message = (
                    f'{exception_prefix}type hint relative forward reference '
                    f'"{hint_ref_name}" unresolvable relative to'
                )

                # If this reference annotates a method of a class...
                if cls_stack:
                    # Fully-qualified name of the module defining that class.
                    type_module_name = get_object_module_name_or_none(cls)  # pyright: ignore

                    # Append this message by...
                    exception_message += (
                        # Substring describing this class *AND*...
                        f':\n* {repr(cls)} ' +  # pyright: ignore
                        (
                            # If that class defines a "__module__" dunder
                            # attribute, substring describing that module.
                            f'in unimportable module "{type_module_name}".'
                            if type_module_name else
                            # Else, that class defines *NO* such attribute. In
                            # this case, a substring describing that failure.
                            'with undefined "__module__" attribute.'
                        ) +
                        # Substring suffixing this item and prefixing the next
                        # item.
                        '\n* '
                    )
                # Else, this reference annotates a global or local function. In
                # this case, append a substring prefixing the next item.
                else:
                    exception_message += ' '

                # Append this message by an appropriate substring defined as
                # the dynamic concatenation of...
                exception_message += (
                    # Substring describing this callable if callable is actually
                    # callable or falling back to its representation otherwise
                    # *AND*...
                    (
                        f'{label_callable(func)} '
                        if callable(func) else
                        f'{repr(func)} '
                    ) +
                    # Substring describing this module.
                    (
                        f'in unimportable module "{hint_module_name}".'
                        if hint_module_name else
                        'with undefined "__module__" attribute.'
                    )
                )

                # Raise this exception.
                raise exception_cls(exception_message)
        # Else, that function is declared by an importable module.
    # Else, that class is declared by an importable module.
    #
    # In either case, at least one of either that class or function is declared
    # by an importable module.

    # Return metadata describing this forward reference relative to this module.
    return hint_module_name, hint_ref_name

# ....................{ IMPORTERS                          }....................
#FIXME: Unit test us up, please.
def import_pep484585_ref_type(
    # Mandatory parameters.
    hint: Pep484585ForwardRef,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintForwardRefException,
    exception_prefix: str = '',
    **kwargs
) -> type:
    '''
    Class referred to by the passed :pep:`484` or :pep:`585`-compliant
    **forward reference type hint** (i.e., object indirectly referring to a
    user-defined class that typically has yet to be defined) canonicalized if
    this hint is unqualified relative to the module declaring the first of
    whichever of the passed owner type and/or callable is *not* :data:`None`.

    This getter is intentionally *not* memoized (e.g., by the
    :func:`callable_cached` decorator), as the passed object is typically a
    :func:`beartype.beartype`-decorated callable passed exactly once to this
    function.

    Parameters
    ----------
    hint : Pep484585ForwardRef
        Forward reference type hint to be resolved.
    exception_cls : Type[Exception]
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`.BeartypeDecorHintForwardRefException`.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    All remaining keyword parameters are passed as is to the lower-level
    :func:`.get_hint_pep484585_ref_names_relative_to` getter.

    Returns
    -------
    type
        Class referred to by this forward reference.

    Raises
    ------
    exception_cls
        If either:

        * This forward reference is *not* actually a forward reference.
        * This forward reference is **relative** (i.e., contains *no* ``.``
          delimiters) and either:

          * Neither the passed callable nor class define the ``__module__``
            dunder attribute.
          * The passed callable and/or class define the ``__module__``
            dunder attribute, but the values of those attributes all refer to
            unimportable modules that do *not* appear to physically exist.
        * The object referred to by this forward reference is either:

          * Undefined.
          * Defined but not a class.

    See Also
    --------
    :func:`.get_hint_pep484585_ref_names_relative_to`
        Further details.
    '''

    # Avoid circular import dependencies.
    from beartype._check.forward.reference.fwdrefmake import (
        make_forwardref_indexable_subtype)

    # Possibly undefined fully-qualified module name and possibly unqualified
    # classname referred to by this forward reference relative to this type
    # stack and callable.
    hint_module_name, hint_ref_name = get_hint_pep484585_ref_names_relative_to(
        hint=hint,
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
        **kwargs
    )

    # Forward reference proxy referring to this class.
    hint_ref = make_forwardref_indexable_subtype(
        hint_module_name, hint_ref_name)

    # Return the class dynamically imported from this proxy.
    return hint_ref.__type_beartype__
