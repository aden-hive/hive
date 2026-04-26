#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Unmemoized beartype non-type decorators** (i.e., low-level decorators
decorating *all* types of decoratable objects except classes, which the sibling
:mod:`beartype._decor._type.decortype` submodule handles, on behalf of the parent
:mod:`beartype._decor.decorcore` submodule).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import (
    BeartypeDecorWrappeeException,
    BeartypeDecorWrapperException,
)
from beartype.typing import (
    Optional,
    no_type_check,
)
from beartype._check.metadata.metadecor import (
    cull_beartype_call,
    make_beartype_call,
)
from beartype._conf.confmain import BeartypeConf
from beartype._conf.confenum import BeartypeStrategy
from beartype._decor._nontype._decornontypemap import (
    MODULE_TO_TYPE_NAME_TO_BEARTYPE_DECORATOR_get,
    MODULE_TO_SUPERTYPE_NAME_TO_BEARTYPE_DECORATOR_get,
)
from beartype._data.typing.datatyping import BeartypeableT
from beartype._decor._nontype._wrap.wrapmain import generate_code
from beartype._util.bear.utilbearblack import is_object_blacklisted
from beartype._util.bear.utilbearfunc import (
    is_func_unbeartypeable,
    set_func_beartyped,
)
from beartype._util.api.standard.utilcontextlib import (
    get_func_contextlib_contextmanager_or_none)
from beartype._util.api.standard.utilfunctools import (
    beartype_functools_lru_cache,
    is_func_functools_lru_cache,
)
from beartype._util.func.utilfuncmake import make_func
from beartype._util.func.utilfunctest import (
    is_func_codeobjable,
    is_func_wrapper,
)
from beartype._util.func.utilfuncwrap import unwrap_func_once
from beartype._util.module.utilmodget import get_object_module_name_or_none
from beartype._util.text.utiltextrepr import represent_object
from collections.abc import Callable

# ....................{ DECORATORS                         }....................
def beartype_nontype(obj: BeartypeableT, **kwargs) -> BeartypeableT:
    '''
    Decorate the passed **non-class beartypeable** (i.e., caller-defined object
    that may be decorated by the :func:`beartype.beartype` decorator but is
    *not* a class) with dynamically generated type-checking.

    Parameters
    ----------
    obj : BeartypeableT
        Non-class beartypeable to be decorated.

    All remaining keyword parameters are passed as is to a lower-level decorator
    defined by this submodule (e.g., :func:`.beartype_func`).

    Returns
    -------
    BeartypeableT
        New pure-Python callable wrapping this beartypeable with type-checking.
    '''

    # Validate that the passed object is *NOT* a class.
    assert not isinstance(obj, type), f'{repr(obj)} is class.'
    # print(f'Decorating non-type {repr(obj)} with type-checking...')
    # print(f'Non-type contents: {dir(obj)}')
    # print(f'{dir(obj.__code__)}')
    # print(f'{obj.__code__.co_filename}')
    # print(f'{obj.__code__.co_name}')
    # print(f'{obj.__code__.co_names}')
    # print(f'{obj.__code__.co_qualname}')

    # ....................{ PASS 1 ~ dispatch : O(1)       }....................
    # First-pass logic efficiently dispatching a beartype decorator unique to
    # the type of this object in O(1) constant-time dispatch -- including:
    # * Uncallable builtin method descriptors -- including property, class
    #   method, instance method, and static method objects. In this case,
    #   @beartype was listed above rather than below the builtin decorator
    #   generating this descriptor in the chain of decorators decorating this
    #   decorated callable. Although @beartype typically *MUST* decorate a
    #   callable directly, this edge case is sufficiently common *AND* trivial
    #   to resolve to warrant doing so. To do so, this conditional branch
    #   effectively reorders @beartype to be the first decorator decorating the
    #   pure-Python function underlying this method descriptor: e.g.,
    #       # This branch detects and reorders this edge case...
    #       class MuhClass(object):
    #           @beartype
    #           @classmethod
    #           def muh_classmethod(cls) -> None: pass
    #
    #       # ...to resemble this direct decoration instead.
    #       class MuhClass(object):
    #           @classmethod
    #           @beartype
    #           def muh_classmethod(cls) -> None: pass
    #
    #   Note that most but *NOT* all of these objects are uncallable.
    #   Regardless, *ALL* of these objects are unsuitable for direct decoration.
    #   Specifically:
    #   * Under Python < 3.10, *ALL* of these objects are uncallable.
    #   * Under Python >= 3.10:
    #     * Descriptors created by @classmethod and @property are uncallable.
    #     * Descriptors created by @staticmethod are technically callable but
    #       C-based and thus unsuitable for direct decoration.

    # Type of this object.
    obj_type = obj.__class__

    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Synchronize with the "PHASE 2" heuristic implemented below.
    # Although these two heuristics are suspiciously similar, generalizing them
    # into a single utility function would only decrease efficiency and increase
    # complexity for no particularly good reason.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # Fully-qualified name of the module defining this type if any *OR* "None"
    # (i.e., if this type is only defined in-memory outside of a module).
    obj_type_module_name = get_object_module_name_or_none(obj_type)

    # If this type is defined by a module...
    if obj_type_module_name:
        # Dictionary mapping from the unqualified basename of each well-known
        # standard type of a @beartype-decoratable object defined by the module
        # defining this specific type to a decorator decorating that object with
        # dynamically generated type-checking if any *OR* "None" (i.e., if this
        # type is *NOT* defined by such a well-known dispatchable module).
        obj_type_name_to_beartype_decorator = (
            MODULE_TO_TYPE_NAME_TO_BEARTYPE_DECORATOR_get(
                obj_type_module_name))

        # If this type is defined by a well-known dispatchable module...
        if obj_type_name_to_beartype_decorator:
            # Decorator decorating this object with dynamically generated
            # type-checking if any *OR* "None" (i.e., if this type is *NOT* a
            # well-known type defined by this module).
            beartype_decorator = obj_type_name_to_beartype_decorator.get(
                obj_type.__name__)

            # If this type is dispatchable, trivially do so.
            if beartype_decorator:
                return beartype_decorator(obj, **kwargs)  # type: ignore[return-value]
            # Else, this type is *NOT* dispatchable.
        # Else, this type is *NOT* defined by a well-known dispatchable module.
    # Else, this type is defined in-memory outside a module.

    # ....................{ PASS 2 ~ dispatch : O(n)       }....................
    # Second-pass logic less efficiently dispatching a beartype decorator unique
    # to the method-resolution order (MRO) of this object in O(n) constant-time
    # dispatch -- including:
    # * Callable third-party objects requiring special handling -- including:
    #   * Click commands created by the @click.command() decorator.

    # Tuple of all superclasses of this object (including the type of this
    # object, which is of course its own superclass *AND* subclass, because set
    # theory just goes hard like that).
    #
    # Note that this includes the irrelevant root "object" superclass, which is
    # semantically meaningless and thus guaranteed to *NEVER* be matched below.
    # Although that superclass *COULD* be trivially sliced off (e.g., with an
    # assignment resembling "obj_bases = cls.__mro__[:-1]"), doing so only
    # uselessly consumes more time than it saves. So it goes.
    obj_bases = obj_type.__mro__

    # For each superclass of this object...
    for obj_base in obj_bases:
        #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        # CAUTION: Synchronize with the "PHASE 1" heuristic implemented above.
        # Although these two heuristics are suspiciously similar, generalizing
        # them into a single utility function would only decrease efficiency and
        # increase complexity for no particularly good reason.
        #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

        # Fully-qualified name of the module defining this superclass if any
        # *OR* "None" (i.e., if only defined in-memory outside of a module).
        obj_base_module_name = get_object_module_name_or_none(obj_base)

        # If this superclass is defined by a module...
        if obj_base_module_name:
            # Dictionary mapping from the unqualified basename of each
            # well-known superclass of a @beartype-decoratable object defined
            # by the module defining this specific type to a decorator
            # decorating that object with dynamically generated type-checking if
            # any *OR* "None" (i.e., if this superclass is *NOT* defined by such
            # a well-known dispatchable module).
            obj_base_name_to_beartype_decorator = (
                MODULE_TO_SUPERTYPE_NAME_TO_BEARTYPE_DECORATOR_get(
                    obj_base_module_name))

            # If this superclass is defined by a well-known dispatchable
            # module...
            if obj_base_name_to_beartype_decorator:
                # Decorator decorating this object with dynamically generated
                # type-checking if any *OR* "None" (i.e., if this superclass is
                # *NOT* a well-known superclass defined by this module).
                beartype_decorator = obj_base_name_to_beartype_decorator.get(  # type: ignore[assignment]
                    obj_base.__name__)

                # If this superclass is dispatchable, trivially do so.
                if beartype_decorator:
                    return beartype_decorator(obj, **kwargs)  # type: ignore[return-value]
                # Else, this superclass is *NOT* dispatchable.
            # Else, this superclass is *NOT* defined by a well-known
            # dispatchable module.
        # Else, this superclass is defined in-memory outside a module.

    # ....................{ PASS 3 ~ ad-hoc                }....................
    # Third-pass logic inefficiently dispatching a beartype decorator unique to
    # the type of this object with a series of ad-hoc heuristics, each of which
    # does *NOT* reduce to a trivial check against the fully-qualified name of
    # the type of this callable and thus *CANNOT* be integrated into the
    # efficient mapping-based O(1) dispatch employed above.

    # If this object is beartype-blacklisted (i.e., defined in a third-party
    # package or module that is hostile to runtime type-checking), silently
    # reduce to a noop and preserve this object as is -- even if this object is
    # uncallable. Of course, this is hardly ideal. But...
    #
    # Beartype didn't break it. Beartype can't fix it. Beartype ignores it!
    if is_object_blacklisted(obj):
        return obj
    # Else, this object is *NOT* beartype-blacklisted.
    #
    # If this object is uncallable, raise an exception.
    elif not callable(obj):
        raise BeartypeDecorWrappeeException(
            f'Uncallable {represent_object(obj)} not decoratable by @beartype.')
    # Else, this object is callable.
    #
    # If this object is *NOT* a pure-Python function, this object is a
    # pseudo-callable (i.e., arbitrary pure-Python *OR* C-based object whose
    # class defines the __call__() dunder method enabling this object to be
    # called like a standard callable). In this case, attempt to monkey-patch
    # runtime type-checking into this pseudo-callable by replacing the bound
    # method descriptor of the type of this object implementing the __call__()
    # dunder method with a comparable descriptor calling a @beartype-generated
    # runtime type-checking wrapper function. Go with it.
    elif not is_func_codeobjable(obj):
        return _beartype_pseudofunc(obj, **kwargs)  # type: ignore[return-value]
    # Else, this object is a pure-Python function.

    # Either:
    # * If this function is a "contextlib"-based isomorphic decorator closure
    #   (i.e., closure both created and returned by either the standard
    #   @contextlib.asynccontextmanager or @contextlib.contextmanager decorators
    #   where that closure isomorphically preserves both the number and types of
    #   all passed parameters and returns by accepting only a variadic positional
    #   argument and variadic keyword argument), that decorator.
    # * Else, "None".
    func_contextmanager = get_func_contextlib_contextmanager_or_none(obj)

    # If this function is a "contextlib"-based isomorphic decorator closure,
    # @beartype was listed above rather than below the "contextlib" decorator
    # creating and returning this closure in the chain of decorators decorating
    # this decorated callable.
    #
    # This is non-ideal, as the types of *ALL* objects created and returned by
    # "contextlib"-decorated context managers are private classes of the
    # "contextlib" module rather than the types implied by the type hints
    # originally annotating the returns of those context managers. If @beartype
    # failed to actively detect and intervene in this edge case, then runtime
    # type-checkers dynamically generated by @beartype for those managers would
    # erroneously raise type-checking violations after calling those managers
    # and detecting the apparent type violation: e.g.,
    #     >>> from beartype.typing import Iterator
    #     >>> from contextlib import contextmanager
    #     >>> @contextmanager
    #     ... def muh_context_manager() -> Iterator[None]: yield
    #     >>> type(muh_context_manager())
    #     <class 'contextlib._GeneratorContextManager'>  # <-- not an "Iterator"
    #
    # This conditional branch effectively reorders @beartype to be the first
    # decorator decorating the callable underlying this context manager,
    # preserving consistency between return types *AND* return type hints: e.g.,
    #     from beartype.typing import Iterator
    #     from contextlib import contextmanager
    #
    #     # This branch detects and reorders this edge case...
    #     @beartype
    #     @contextmanager
    #     def muh_contextmanager(cls) -> Iterator[None]: yield
    #
    #     # ...to resemble this direct decoration instead.
    #     @contextmanager
    #     @beartype
    #     def muh_contextmanager(cls) -> Iterator[None]: yield
    #
    # Note that detecting "contextlib"-based isomorphic decorator closures is
    # extremely non-trivial. Notably, this detection requires Python >= 3.11 and
    # silently fails under Python <= 3.10. It is what it is. Not our fault!
    if func_contextmanager is not None:
        return _beartype_func_contextlib_contextmanager(  # type: ignore[return-value]
            func=obj, func_contextmanager=func_contextmanager, **kwargs)
    # Else, that function is *NOT* a "contextlib"-based isomorphic decorator
    # closure. By elimination, that function *MUST* be a standard pure-Python
    # function.

    # Decorate that pure-Python function with runtime type-checking.
    return beartype_func(obj, **kwargs)  # type: ignore[return-value]


def beartype_func(
    # Mandatory parameters.
    func: BeartypeableT,
    conf: BeartypeConf,

    # Variadic keyword parameters.
    wrapper: Optional[Callable] = None,
    **kwargs
) -> BeartypeableT:
    '''
    Decorate the passed callable with dynamically generated type-checking.

    Parameters
    ----------
    func : BeartypeableT
        Callable to be decorated by :func:`beartype.beartype`.
    conf : BeartypeConf
        Beartype configuration configuring :func:`beartype.beartype` uniquely
        specific to this callable.
    wrapper : Optional[Callable]
        Wrapper callable to be unwrapped in the event that the callable to be
        unwrapped differs from the callable to be decorated. Typically, these
        two callables are the same. Edge cases in which these two callables
        differ include:

        * When ``wrapper`` is a **pseudo-callable** (i.e., otherwise uncallable
          object whose type renders that object callable by defining the
          ``__call__()`` dunder method) *and* ``func`` is that ``__call__()``
          dunder method. If that pseudo-callable wraps a lower-level callable,
          then that pseudo-callable (rather than ``__call__()`` dunder method)
          defines the ``__wrapped__`` instance variable providing that callable.

        Defaults to :data:`None`, in which case this parameter *actually*
        defaults to ``func``.

    All remaining keyword parameters are passed as is to the
    :meth:`beartype._check.metadata.metadecor.BeartypeDecorMeta.reinit` method.

    Returns
    -------
    BeartypeableT
        New pure-Python callable wrapping this callable with type-checking.
    '''

    # If the caller failed to pass a callable to be unwrapped, default that to
    # the callable to be type-checked.
    if wrapper is None:
        wrapper = func  # type: ignore[assignment]
    # Else, the caller passed a callable to be unwrapped. Preserve it up!

    # Validate all explicitly passed parameters.
    assert callable(func), f'{repr(func)} uncallable.'
    assert callable(wrapper), f'{repr(wrapper)} uncallable.'
    assert isinstance(conf, BeartypeConf), f'{repr(conf)} not configuration.'

    #FIXME: Uncomment to display all annotations in "pytest" tracebacks.
    # func_hints = func.__annotations__

    # If this configuration enables the no-time strategy performing *NO*
    # type-checking, monkey-patch that callable with the standard
    # @typing.no_type_check decorator detected below by the call to the
    # is_func_unbeartypeable() tester on all subsequent decorations passed the
    # same callable... Doing so prevents all subsequent decorations from
    # erroneously ignoring this previously applied no-time strategy.
    if conf.strategy is BeartypeStrategy.O0:
        no_type_check(func)  # pyright: ignore
    # Else, this configuration enables a positive-time strategy performing at
    # least the minimal amount of type-checking.

    # If the callable to be unwrapped is unbeartypeable (i.e., if this decorator
    # should preserve that callable as is rather than wrap that callable with
    # type-checking), silently reduce to the identity decorator.
    #
    # Note that this conditional implicitly handles the prior conditional! Ergo,
    # this conditional intentionally appears *AFTER* the prior conditional. :O
    if is_func_unbeartypeable(wrapper):  # type: ignore[arg-type]
        # print(f'Ignoring unbeartypeable callable {repr(func)}...')
        return func  # type: ignore[return-value]
    # Else, that callable is beartypeable. Let's do this, folks.

    # Beartype call metadata describing that callable.
    decor_meta = make_beartype_call(
        func=func, conf=conf, wrapper=wrapper, **kwargs)  # pyright: ignore
    # print(f'Decorating {repr(decor_meta)} with wrapper {repr(wrapper)}...')

    # Generate the raw string of Python statements implementing this wrapper.
    func_wrapper_code = generate_code(decor_meta)
    # print(f'func_wrapper_code: {func_wrapper_code}')

    # If that callable requires *NO* type-checking, silently reduce to a noop
    # and thus the identity decorator by returning that callable as is.
    if not func_wrapper_code:
        return func  # type: ignore[return-value]
    # Else, that callable requires type-checking. Let's *REALLY* do this, fam.

    # If the type hint dictionary associated with the decorated callable is
    # dirty (i.e., changed from the original "__annotations__" dunder dictionary
    # annotating that callable), register these changes in a manner compliant
    # with both PEP 649 and Python >= 3.14 *BEFORE* calling the make_func()
    # factory function below, which internally propagates these changes from the
    # "decor_meta.func_wrapper" callable into the created type-checking wrapper
    # function returned by the @beartype decorator. Look. It's complicated.
    decor_meta.set_func_annotations_if_dirty()

    # Function wrapping that callable with type-checking to be returned.
    #
    # For efficiency, this wrapper accesses *ONLY* local rather than global
    # attributes. The latter incur a minor performance penalty, since local
    # attributes take precedence over global attributes, implying all global
    # attributes are *ALWAYS* first looked up as local attributes before falling
    # back to being looked up as global attributes.
    func_wrapper = make_func(
        func_name=decor_meta.func_wrapper_name,
        func_code=func_wrapper_code,
        func_locals=decor_meta.func_wrapper_scope,
        func_wrapped=decor_meta.func_wrapper,  # pyright: ignore
        func_labeller=decor_meta.label_func_wrapper,
        is_debug=conf.is_debug,
        exception_cls=BeartypeDecorWrapperException,
    )

    # Declare this wrapper to be generated by @beartype, which tests for the
    # existence of this attribute above to avoid re-decorating callables
    # already decorated by @beartype by efficiently reducing to a noop.
    set_func_beartyped(func_wrapper)

    # Deinitialize this beartype call metadata.
    cull_beartype_call(decor_meta)

    # Return this wrapper.
    return func_wrapper  # type: ignore[return-value]

# ....................{ PRIVATE ~ decorators : pure-python }....................
def _beartype_func_contextlib_contextmanager(
    func: BeartypeableT,
    func_contextmanager: Callable,
    **kwargs
) -> BeartypeableT:
    '''
    Decorate the passed :mod:`contextlib`-based **isomorphic decorator closure**
    (i.e., closure both defined and returned by either the standard
    :func:`contextlib.asynccontextmanager` or :func:`contextlib.contextmanager`
    decorator where that closure isomorphically preserves both the number and
    types of all passed parameters and returns by accepting only a variadic
    positional argument and variadic keyword argument) with dynamically
    generated type-checking.

    Parameters
    ----------
    func : BeartypeableT
        Context manager to be decorated by :func:`beartype.beartype`.
    func_contextmanager : Callable
        Either:

        * If this context manager is a
          :func:`contextlib.asynccontextmanager`-based isomorphic decorator
          closure, :func:`contextlib.asynccontextmanager`.
        * Else, this context manager is a
          :func:`contextlib.contextmanager`-based isomorphic decorator closure.
          In this case, :func:`contextlib.contextmanager`.

    All remaining keyword parameters are passed as is to the lower-level
    :func:`.beartype_func` decorator internally called by this higher-level
    decorator on the pure-Python function encapsulated in this descriptor.

    Returns
    -------
    BeartypeableT
        New pure-Python callable wrapping this context manager with
        type-checking.
    '''
    assert callable(func_contextmanager), (
        f'{repr(func_contextmanager)} uncallable.')

    # Original pure-Python generator factory function decorated by either the
    # @contextlib.asynccontextmanager or @contextlib.contextmanager decorator.
    generator = unwrap_func_once(func)  # type: ignore[arg-type]

    # Decorate this generator factory function with type-checking.
    generator_checked = beartype_func(func=generator, **kwargs)

    # Re-decorate this generator factory function by the same decorator.
    generator_checked_contextmanager = func_contextmanager(generator_checked)

    # Return this context manager.
    return generator_checked_contextmanager  # type: ignore[return-value]


def _beartype_pseudofunc(pseudofunc: BeartypeableT, **kwargs) -> BeartypeableT:
    '''
    Monkey-patch the passed **pseudo-callable** (i.e., arbitrary pure-Python
    *or* C-based object whose class defines the ``__call__()`` dunder method
    enabling this object to be called like a standard callable) with dynamically
    generated type-checking.

    For each bound method descriptor encapsulating a method bound to this
    object, this function monkey-patches (i.e., replaces) that descriptor with a
    comparable descriptor calling a new :func:`beartype.beartype`-generated
    runtime type-checking wrapper function wrapping the original method.

    Parameters
    ----------
    pseudofunc : BeartypeableT
        Pseudo-callable to be monkey-patched by :func:`beartype.beartype`.

    All remaining keyword parameters are passed as is to the lower-level
    :func:`.beartype_func` decorator internally called by this higher-level
    decorator on the pure-Python function encapsulated in this descriptor.

    Returns
    -------
    BeartypeableT
        The object monkey-patched by :func:`beartype.beartype`.
    '''
    # print(f'@beartyping pseudo-callable {repr(pseudofunc)}...')

    # Bound __call__() dunder method bound to this object if this object defines
    # this method *OR* "None" otherwise.
    pseudofunc_call_boundmethod = getattr(pseudofunc, '__call__')

    # Unbound __call__() dunder method defined by the type of this object if
    # this type defines this method *OR* "None" otherwise.
    pseudofunc_call_type_method = getattr(pseudofunc.__class__, '__call__')

    # If this object does *NOT* define this method, this object is *NOT* a
    # pseudo-callable. In this case, raise an exception.
    #
    # Note this edge case should *NEVER* occur. By definition, this object has
    # already been validated to be callable. But this object is *NOT* a
    # pure-Python function. Since the only other category of callable in Python
    # is a pseudo-callable, this object *MUST* be a pseudo-callable. That said,
    # languages change; it's not inconceivable that Python could introduce yet
    # another kind of callable object under future versions.
    if pseudofunc_call_boundmethod is None:  # pragma: no cover
        raise BeartypeDecorWrappeeException(
            f'Callable {repr(pseudofunc)} not pseudo-callable object '
            f'(i.e., defines no bound __call__() dunder method).'
        )
    # Else, this object is a pseudo-callable.
    #
    # If this object does *NOT* define this method, this object is *NOT* a
    # pseudo-callable. In this case, raise an exception.
    elif pseudofunc_call_type_method is None:  # pragma: no cover
        raise BeartypeDecorWrappeeException(
            f'Callable {repr(pseudofunc)} type {repr(pseudofunc.__class__)} '
            f'not pseudo-callable object type '
            f'(i.e., defines no unbound __call__() dunder method).'
        )
    # Else, this object type is a pseudo-callable type.
    #
    # If this is a C-based @functools.lru_cache-memoized callable (i.e.,
    # low-level C-based callable object both created and returned by the
    # standard @functools.lru_cache decorator), @beartype was listed above
    # rather than below the @functools.lru_cache decorator creating and
    # returning this callable in the chain of decorators decorating this
    # decorated callable.
    #
    # This conditional branch effectively reorders @beartype to be the first
    # decorator decorating the pure-Python callable underlying this C-based
    # pseudo-callable: e.g.,
    #     from functools import lru_cache
    #
    #     # This branch detects and reorders this edge case...
    #     @beartype
    #     @lru_cache
    #     def muh_lru_cache() -> None: pass
    #
    #     # ...to resemble this direct decoration instead.
    #     @lru_cache
    #     @beartype
    #     def muh_lru_cache() -> None: pass
    elif is_func_functools_lru_cache(pseudofunc):
        # Return a new callable decorating that callable with type-checking.
        return beartype_functools_lru_cache(  # type: ignore
            pseudofunc=pseudofunc, **kwargs)  # pyright: ignore
    # Else, this is *NOT* a C-based @functools.lru_cache-memoized callable.
    #
    # If...
    elif (
        # This pseudo-callable object is a wrapper *AND*...
        is_func_wrapper(pseudofunc) and
        # This unbound __call__() dunder method is *NOT* a wrapper...
        not is_func_wrapper(pseudofunc_call_type_method)
    ):
        # print(f'Pseudo-callable wrapper {repr(pseudofunc)} identified!')

        # Transitively pass the optional "wrapper" parameter to the
        # BeartypeDecorMeta.reinit() method, ensuring that this pseudo-callable
        # wrapper object is correctly unwrapped.
        #
        # This edge case handles edge-case pseudo-callable wrapper objects
        # defined by popular third-party packages, including:
        # * The pseudo-callable wrapper objects created and returned by the
        #   @equinox.filter_jit wrapper. Although private and extremely
        #   non-trivial, the types of these objects vaguely resembles:
        #       class _JitWrapper(object):
        #           def __init__(self, func):
        #               self.__wrapped__ = func
        #
        #           def __call__(self, *args, **kwargs):
        #               return self.__wrapped__(*args, **kwargs)
        kwargs['wrapper'] = pseudofunc
    # Else, either this pseudo-callable object is not a wrapper *OR* this
    # unbound __call__() dunder method is already a wrapper.

    # Unbound __call__() dunder method runtime type-checking the original bound
    # __call__() dunder method of the passed pseudo-callable object.
    pseudofunc_call_type_method_checked = beartype_func(
        func=pseudofunc_call_boundmethod, **kwargs)
    return pseudofunc_call_type_method_checked
