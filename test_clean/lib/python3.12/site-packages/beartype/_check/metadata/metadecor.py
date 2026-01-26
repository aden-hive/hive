#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype decorator call metadata dataclass** (i.e., class aggregating *all*
metadata for the callable currently being decorated by the
:func:`beartype.beartype` decorator).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorWrappeeException
from beartype.typing import (
    TYPE_CHECKING,
    Callable,
    FrozenSet,
    Optional,
)
from beartype._cave._cavefast import CallableCodeObjectType
from beartype._cave._cavemap import NoneTypeOr
from beartype._check.forward.fwdscope import BeartypeForwardScope
from beartype._conf.confmain import BeartypeConf
from beartype._data.code.datacodefunc import (
    CODE_NORMAL_RETURN_CHECKED,
    CODE_NORMAL_RETURN_UNCHECKED_SYNC,
    CODE_NORMAL_RETURN_UNCHECKED_ASYNC,
)
from beartype._data.code.pep.datacodepep342 import (
    CODE_PEP342_RETURN_CHECKED,
    CODE_PEP342_RETURN_UNCHECKED,
)
from beartype._data.code.pep.datacodepep525 import (
    CODE_PEP525_RETURN_CHECKED,
    CODE_PEP525_RETURN_UNCHECKED,
)
from beartype._data.typing.datatyping import (
    LexicalScope,
    Pep649HintableAnnotations,
    TypeStack,
)
from beartype._data.typing.datatypingport import Hint
from beartype._util.cache.pool.utilcachepoolinstance import (
    acquire_instance,
    release_instance,
)
from beartype._util.func.utilfunccodeobj import (
    get_func_codeobj,
    get_func_codeobj_or_none,
)
from beartype._util.func.utilfunctest import (
    is_func_coro,
    is_func_nested,
    is_func_sync_generator,
    is_func_async_generator,
)
from beartype._util.func.utilfuncwrap import unwrap_func_all_isomorphic
from beartype._util.hint.pep.proposal.pep649 import (
    get_pep649_hintable_annotations,
    set_pep649_hintable_annotations,
)
from beartype._util.text.utiltextprefix import prefix_callable_pith

# ....................{ CLASSES                            }....................
class BeartypeDecorMeta(object):
    '''
    **Beartype decorator call metadata** (i.e., object encapsulating *all*
    metadata for the callable currently being decorated by the
    :func:`beartype.beartype` decorator).

    Design
    ------
    This the *only* object instantiated by that decorator for that callable,
    substantially reducing both space and time costs. That decorator then
    passes this object to most lower-level functions, which then:

    #. Access read-only instance variables of this object as input.
    #. Modify writable instance variables of this object as output. In
       particular, these lower-level functions typically accumulate pure-Python
       code comprising the generated wrapper function type-checking the
       decorated callable by setting various instance variables of this object.

    Caveats
    -------
    **This object cannot be used to communicate state between low-level
    memoized callables** (e.g.,
    :func:`beartype._check.code.codemain.make_func_pith_code`) **and
    high-level unmemoized callables** (e.g.,
    :func:`beartype._decor._nontype._wrap.wrapmain.generate_code`). Instead,
    low-level memoized callables *must* return that state as additional return
    values up the call stack to those high-level unmemoized callables. By
    definition, memoized callables are *not* recalled on subsequent calls passed
    the same parameters. Since only the first call to those callables passed
    those parameters would set the appropriate state on this object intended to
    be communicated to unmemoized callables, *all* subsequent calls would subtly
    fail with difficult-to-diagnose issues. See also `<issue #5_>`__, which
    exhibited this very complaint.

    .. _issue #5:
       https://github.com/beartype/beartype/issues/5

    Attributes
    ----------
    cls_stack : TypeStack
        **Type stack** (i.e., either tuple of zero or more arbitrary types *or*
        :data:`None`). See also the parameter of the same name accepted by the
        :func:`beartype._decor.decorcore.beartype_object` function for details.
    conf : BeartypeConf
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all flags, options, settings, and other metadata configuring the
        current decoration of the decorated callable).
    func_annotations : dict[str, Hint]
        **Type hint dictionary** mapping from the name of each annotated
        parameter and return accepted by the decorated callable to the type hint
        annotating that parameter or return.

        Note that this dictionary is *not* directly mutable. When the active
        Python interpreter targets Python >= 3.14, :pep:`649`-compliant type
        hint dictionaries are *not* directly mutable. Attempting to do so will
        superficially appear to succeed but ultimately reduce to a silent noop.
        This particular dictionary is only indirectly mutable by calling the
        high-level :meth:`set_func_pith_hint` setter method, which mutates the
        type hint annotating the name of the passed parameter or return in a
        portable manner consistent with both :pep:`649` and Python >= 3.14.
        Although this constraint *could* be enforced by encapsulating this
        dictionary in a :class:`beartype.FrozenDict` instance, doing so would
        simply reduce space and time efficiency for little to no actual gain.
        Simply call :meth:`set_func_pith_hint` instead.
    func_annotations_get : Callable[[str, object], object]
        :meth:`dict.get` method bound to the :attr:`func_annotations`
        dictionary, localized as a negligible microoptimization. Blame Guido.
    _is_func_annotations_dirty : bool
        :data:`True` only if the type hint dictionary is **dirty** (i.e.,
        modified from the original type hint dictionary annotating the decorated
        callable by a prior call to the :meth:`set_func_pith_hint` setter).
    func_wrappee : Callable
        Possibly wrapping **decorated callable** (i.e., high-level callable
        currently being decorated by the :func:`beartype.beartype` decorator).
        Note the lower-level :attr:`func_wrappee_wrappee` callable should
        *usually* be accessed instead; although higher-level, this callable may
        only be a wrapper function and hence yield inaccurate or even erroneous
        metadata (especially the code object) for the callable being wrapped.
    func_wrappee_is_nested : bool
        Either:

        * If this wrappee callable is **nested** (i.e., declared in the body of
          another pure-Python callable or class), :data:`True`.
        * If this wrappee callable is **global** (i.e., declared at module scope
          in its submodule), :data:`False`.
    func_wrappee_scope_forward : Optional[BeartypeForwardScope]
        Either:

        * If this wrappee callable is annotated by at least one **stringified
          type hint** (i.e., declared as a :pep:`484`- or :pep:`563`-compliant
          forward reference referring to an actual type hint that has yet to be
          declared in the local and global scopes declaring this callable) that
          :mod:`beartype` has already resolved to its referent, this wrappee
          callable's **forward scope** (i.e., dictionary mapping from the name
          to value of each locally and globally accessible attribute in the
          local and global scope of this wrappee callable as well as deferring
          the resolution of each currently undeclared attribute in that scope by
          replacing that attribute with a forward reference proxy resolved only
          when that attribute is passed as the second parameter to an
          :func:`isinstance`-based runtime type-check).
        * Else, :data:`None`.

        Note that:

        * The reconstruction of this scope is computationally expensive and thus
          deferred until needed to resolve the first stringified type hint
          annotating this wrappee callable.
        * All callables have local scopes *except* global functions, whose local
          scopes are by definition the empty dictionary.
    func_wrappee_scope_nested_names : Optional[frozenset[str]]
        Either:

        * If this wrappee callable is annotated by at least one stringified type
          hint that :mod:`beartype` has already resolved to its referent,
          either:

          * If this wrappee callable is **nested** (i.e., declared in the body
            of another pure-Python callable or class), the non-empty frozen set
            of the unqualified names of all parent callables lexically
            containing this nested wrappee callable (including this nested
            wrappee callable itself).
          * Else, this wrappee callable is declared at global scope in its
            submodule. In this case, the empty frozen set.

        * Else, :data:`None`.
    func_wrappee_wrappee : Callable
        Possibly unwrapped **decorated callable wrappee** (i.e., low-level
        callable wrapped by the high-level :attr:`func_wrappee` callable
        currently being decorated by the :func:`beartype.beartype` decorator).
        If the higher-level :attr:`func_wrappee` callable does *not* actually
        wrap another callable, this callable is identical to that callable.
    func_wrappee_wrappee_codeobj : CallableCodeObjectType
        Possibly unwrapped **decorated callable wrappee code object** (i.e.,
        code object underlying the low-level :attr:`func_wrappee_wrappee`
        callable wrapped by the high-level :attr:`func_wrappee` callable
        currently being decorated by the :func:`beartype.beartype` decorator).
        For efficiency, this code object should *always* be accessed in lieu of
        inefficiently calling the comparatively slower
        :func:`beartype._util.func.utilfunccodeobj.get_func_codeobj` getter.
    func_wrapper : Callable
        **Wrapper callable** to be unwrapped in the event that the
        :attr:`func_wrappee` differs from the callable to be unwrapped.
        Typically, these two callables are the same. Edge cases in which these
        two callables differ include:

        * When the wrapper callable is a **pseudo-callable** (i.e., otherwise
          uncallable object whose type renders that object callable by defining
          the ``__call__()`` dunder method) *and* the :attr:`func_wrappee` is
          the ``__call__()`` dunder method. If that pseudo-callable wraps a
          lower-level callable, then that pseudo-callable (rather than that
          ``__call__()`` dunder method) defines the ``__wrapped__`` instance
          variable providing that callable.

        This callable is typically identical to the :attr:`func_wrappee`.
    func_wrapper_code_call_prefix : str
        Code snippet prefixing all calls to the decorated callable in the body
        of the wrapper function wrapping that callable with type checking. This
        string is guaranteed to be either:

        * If the decorated callable is synchronous (i.e., neither a coroutine
          nor asynchronous generator), the empty string.
        * If the decorated callable is asynchronous (i.e., either a coroutine
          nor asynchronous generator), the ``"await "`` keyword.
    func_wrapper_code_return_checked : str
        Code snippet returning the value returned by calling the decorated
        callable in the body of the wrapper function wrapping that callable with
        type-checking.
    func_wrapper_code_return_unchecked : str
        Code snippet returning the value returned by calling the decorated
        callable in the body of the wrapper function *without* wrapping that
        callable with type-checking. This snippet is an optimization for the
        common case in which the return of that callable is left unannotated.
    func_wrapper_code_signature_prefix : str
        Code snippet prefixing the signature declaring the wrapper function
        wrapping the decorated callable with type checking. This string is
        guaranteed to be either:

        * If the decorated callable is synchronous (i.e., neither a coroutine
          nor asynchronous generator), the empty string.
        * If the decorated callable is asynchronous (i.e., either a coroutine
          or asynchronous generator), the ``"async "`` keyword.
    func_wrapper_name : str
        Unqualified basename of the type-checking wrapper function to be
        generated and returned by the current invocation of the
        :func:`beartype.beartype` decorator.
    func_wrapper_scope : LexicalScope
        **Local scope** (i.e., dictionary mapping from the name to value of
        each attribute referenced in the signature) of this wrapper function.
    '''

    # ..................{ CLASS VARIABLES                    }..................
    # Slot all instance variables defined on this object to minimize the time
    # complexity of both reading and writing variables across frequently
    # called @beartype decorations. Slotting has been shown to reduce read and
    # write costs by approximately ~10%, which is non-trivial.
    __slots__ = (
        'cls_stack',
        'conf',
        'func_annotations',
        'func_annotations_get',
        '_is_func_annotations_dirty',
        'func_wrappee',
        'func_wrappee_is_nested',
        'func_wrappee_scope_forward',
        'func_wrappee_scope_nested_names',
        'func_wrappee_wrappee',
        'func_wrappee_wrappee_codeobj',
        'func_wrapper',
        'func_wrapper_code_call_prefix',
        'func_wrapper_code_return_checked',
        'func_wrapper_code_return_unchecked',
        'func_wrapper_code_signature_prefix',
        'func_wrapper_name',
        'func_wrapper_scope',
    )

    # Squelch false negatives from mypy. This is absurd. This is mypy. See:
    #     https://github.com/python/mypy/issues/5941
    if TYPE_CHECKING:
        cls_stack: TypeStack
        conf: BeartypeConf
        func_annotations: Pep649HintableAnnotations
        func_annotations_get: Callable[[str, object], object]
        _is_func_annotations_dirty: bool
        func_wrappee: Callable
        func_wrappee_is_nested: bool
        func_wrappee_scope_forward: Optional[BeartypeForwardScope]
        func_wrappee_scope_nested_names: Optional[FrozenSet[str]]
        func_wrappee_wrappee: Callable
        func_wrappee_wrappee_codeobj: CallableCodeObjectType
        func_wrapper: Callable
        func_wrapper_code_call_prefix: str
        func_wrapper_code_return_checked: str
        func_wrapper_code_return_unchecked: str
        func_wrapper_code_signature_prefix: str
        func_wrapper_name: str
        func_wrapper_scope: LexicalScope

    # Coerce instances of this class to be unhashable, preventing spurious
    # issues when accidentally passing these instances to memoized callables by
    # implicitly raising a "TypeError" exception on the first call to those
    # callables. There exists no tangible benefit to permitting these instances
    # to be hashed (and thus also cached), since these instances are:
    # * Specific to the decorated callable and thus *NOT* safely cacheable
    #   across functions applying to different decorated callables.
    # * Already cached via the acquire_instance() function called by the
    #   "beartype._decor.decormain" submodule.
    #
    # See also:
    #     https://docs.python.org/3/reference/datamodel.html#object.__hash__
    __hash__ = None  # type: ignore[assignment]

    # ..................{ INITIALIZERS                       }..................
    def __init__(self) -> None:
        '''
        Initialize this metadata by nullifying all instance variables.

        Caveats
        -------
        **This class is not intended to be explicitly instantiated.** Instead,
        callers are expected to (in order):

        #. Acquire cached instances of this class via the
           :mod:`beartype._util.cache.pool.utilcachepoolinstance` submodule.
        #. Call the :meth:`reinit` method on these instances to properly
           initialize these instances.
        '''

        # Nullify instance variables for safety.
        self.deinit()


    def deinit(self) -> None:
        '''
        Deassociate this metadata from the callable passed to the most recent
        call of the :meth:`reinit` method, typically before releasing this
        instance of this class back to the
        :mod:`beartype._util.cache.pool.utilcachepoolobject` submodule.

        This method prevents a minor (albeit still undesirable, of course)
        memory leak in which this instance would continue to remain accidentally
        associated with that callable despite this instance being released back
        to its object pool, which would then prevent that callable from being
        garbage-collected on the finalization of the last external reference to
        that callable.
        '''

        # Restore instance variables to initial defaults.
        self.func_wrapper_scope: LexicalScope = {}
        self._is_func_annotations_dirty = False

        # Nullify all remaining instance variables for safety.
        self.cls_stack = (  # type: ignore[assignment]
        self.conf) = (  # type: ignore[assignment]
        self.func_annotations) = (  # type: ignore[assignment]
        self.func_annotations_get) = (  # type: ignore[assignment]
        self.func_wrappee) = (  # type: ignore[assignment]
        self.func_wrappee_is_nested) = (  # type: ignore[assignment]
        self.func_wrappee_scope_forward) = (  # type: ignore[assignment]
        self.func_wrappee_scope_nested_names) = (  # type: ignore[assignment]
        self.func_wrappee_wrappee) = (  # type: ignore[assignment]
        self.func_wrappee_wrappee_codeobj) = (  # type: ignore[assignment]
        self.func_wrapper) = (  # type: ignore[assignment]
        self.func_wrapper_code_call_prefix) = (  # type: ignore[assignment]
        self.func_wrapper_code_return_checked) = (  # type: ignore[assignment]
        self.func_wrapper_code_return_unchecked) = (  # type: ignore[assignment]
        self.func_wrapper_code_signature_prefix) = (  # type: ignore[assignment]
        self.func_wrapper_name) = None  # type: ignore[assignment]


    def reinit(
        self,

        # Mandatory parameters.
        func: Callable,
        conf: BeartypeConf,

        # Optional parameters.
        cls_stack: TypeStack = None,
        wrapper: Optional[Callable] = None,
    ) -> None:
        '''
        Reinitialize this metadata from the passed callable, typically after
        acquisition of a previously cached instance of this class from the
        :mod:`beartype._util.cache.pool.utilcachepoolobject` submodule.

        If :pep:`563` is conditionally active for this callable, this function
        additionally resolves all postponed annotations on this callable to
        their referents (i.e., the intended annotations to which those
        postponed annotations refer).

        Parameters
        ----------
        func : Callable
            Callable currently being decorated by :func:`beartype.beartype`.
        conf : BeartypeConf
            Beartype configuration configuring :func:`beartype.beartype`
            specific to this callable.
        cls_stack : TypeStack
            **Type stack** (i.e., either tuple of zero or more arbitrary types
            *or* :data:`None`). See also the parameter of the same name accepted
            by the :func:`beartype._decor.decorcore.beartype_object` function.
        wrapper : Optional[Callable]
            **Wrapper callable** to be unwrapped in the event that the callable
            currently being decorated by :func:`beartype.beartype` differs from
            the callable to be unwrapped. Typically, these two callables are the
            same. Edge cases in which these two callables differ include:

            * When ``wrapper`` is a **pseudo-callable** (i.e., otherwise
              uncallable object whose type renders that object callable by
              defining the ``__call__()`` dunder method) *and* ``func`` is that
              ``__call__()`` dunder method. If that pseudo-callable wraps a
              lower-level callable, then that pseudo-callable (rather than that
              ``__call__()`` dunder method) defines the ``__wrapped__`` instance
              variable providing that callable.

            Defaults to :data:`None`, in which case this parameter *actually*
            defaults to ``func``.

        Raises
        ------
        BeartypePep563Exception
            If evaluating a postponed annotation on this callable raises an
            exception (e.g., due to that annotation referring to local state no
            longer accessible from this deferred evaluation).
        BeartypeDecorWrappeeException
            If either:

            * This callable is uncallable.
            * This callable is neither a pure-Python function *nor* method;
              equivalently, if this callable is either C-based *or* a class or
              object defining the ``__call__()`` dunder method.
            * This configuration is *not* actually a configuration.
            * ``cls_owner`` is neither a class *nor* :data:`None`.
        '''

        #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        # CAUTION: Note this method intentionally avoids creating and passing an
        # "exception_prefix" substring to callables called below. Why? Because
        # exhaustive profiling has shown that creating that substring consumes a
        # non-trivial slice of decoration time. In other words, raw efficiency.
        #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

        # ..................{ VALIDATE                       }..................
        # If the caller failed to pass a callable to be unwrapped, default that
        # to the callable to be type-checked.
        if wrapper is None:
            wrapper = func
        # Else, the caller passed a callable to be unwrapped. Preserve it up!
        # print(f'Beartyping func {repr(func)} + wrapper {repr(wrapper)}...')

        # If the callable to be type-checked is uncallable, raise an exception.
        if not callable(func):
            raise BeartypeDecorWrappeeException(f'{repr(func)} uncallable.')
        # Else, that callable is callable.
        #
        # If the callable to be unwrapped is uncallable, raise an exception.
        elif not callable(wrapper):
            raise BeartypeDecorWrappeeException(f'{repr(wrapper)} uncallable.')
        # Else, that callable is callable.
        #
        # If this configuration is *NOT* a configuration, raise an exception.
        elif not isinstance(conf, BeartypeConf):
            raise BeartypeDecorWrappeeException(
                f'BeartypeDecorMeta.reinit() method "conf" parameter '
                f'{repr(conf)} not beartype configuration.'
            )
        # Else, this configuration is a configuration.
        #
        # If this class stack is neither a tuple *NOR* "None", raise an
        # exception.
        elif not isinstance(cls_stack, NoneTypeOr[tuple]):
            raise BeartypeDecorWrappeeException(
                f'BeartypeDecorMeta.reinit() method "cls_stack" parameter '
                f'{repr(cls_stack)} neither tuple nor "None".'
            )
        # Else, this class stack is either a tuple *OR* "None".

        # If the caller passed a non-empty class stack...
        if cls_stack:
            # For each item of this class stack...
            for cls_stack_item in cls_stack:
                # If this item is *NOT* a type, raise an exception.
                if not isinstance(cls_stack_item, type):
                    raise BeartypeDecorWrappeeException(
                        f'BeartypeDecorMeta.reinit() method "cls_stack" item '
                        f'{repr(cls_stack_item)} not type.'
                    )
                # Else, this item is a type.
        # Else, the caller either passed no class stack *OR* an empty class
        # stack. In either case, ignore this parameter.

        # ..................{ VARS                           }..................
        # Classify all passed parameters.
        self.conf = conf
        self.cls_stack = cls_stack

        # ..................{ VARS ~ func : wrappee          }..................
        # Wrappee callable currently being decorated.
        self.func_wrappee = func

        # True only if this wrappee callable is nested. As a minor efficiency
        # gain, we can avoid the slightly expensive call to is_func_nested() by
        # noting that:
        # * If the class stack is non-empty, then this wrappee callable is
        #   necessarily nested in one or more classes.
        # * Else, defer to the is_func_nested() tester.
        self.func_wrappee_is_nested = bool(cls_stack) or is_func_nested(func)

        # Defer the resolution of both global and local scopes for this wrappee
        # callable until needed to subsequently resolve stringified type hints.
        self.func_wrappee_scope_forward = None
        self.func_wrappee_scope_nested_names = None

        # Possibly wrapped wrappee code object (i.e., code object underlying the
        # callable currently being type-checked by the @beartype decorator) if
        # this wrappee is pure-Python *OR* "None" otherwise.
        #
        # Note that only the possibly unwrapped wrappee wrappee defined below
        # (i.e., "func_wrappee_wrappee") *MUST* be pure-Python and thus *MUST*
        # have a code object. This higher-level wrappee is permitted to be
        # C-based and thus need *NOT* have a code object.
        func_wrappee_codeobj = get_func_codeobj_or_none(func)

        # ..................{ VARS ~ func : wrappee wrappee  }..................
        # Possibly unwrapped callable unwrapped from this wrappee callable.
        self.func_wrappee_wrappee = unwrap_func_all_isomorphic(
            func=func, wrapper=wrapper)
        # print(f'func_wrappee: {self.func_wrappee}')
        # print(f'func_wrappee_wrappee: {self.func_wrappee_wrappee}')
        # print(f'{dir(self.func_wrappee_wrappee)}')

        # Possibly unwrapped callable code object.
        self.func_wrappee_wrappee_codeobj = get_func_codeobj(
            func=self.func_wrappee_wrappee,
            exception_cls=BeartypeDecorWrappeeException,
        )

        # ..................{ VARS ~ func : wrapper          }..................
        # Wrapper callable to be unwrapped in the event that the
        # decorated callable differs from the callable to be unwrapped.
        self.func_wrapper = wrapper

        # Efficiently reduce this local scope back to the dictionary of all
        # parameters unconditionally required by *ALL* wrapper functions.
        self.func_wrapper_scope.clear()

        # Machine-readable name of the wrapper function to be generated.
        self.func_wrapper_name = func.__name__

        # ..................{ VARS ~ func : hints            }..................
        # Dictionary mapping from the name of each annotated parameter accepted
        # by the unwrapped callable to the type hint annotating that parameter
        # *AFTER* resolving all postponed type hints elsewhere.
        #
        # Note that:
        # * The functools.update_wrapper() function underlying the
        #   @functools.wrap decorator underlying all sane decorators propagates
        #   this dictionary from lower-level wrappees to higher-level wrappers
        #   by default. We intentionally classify the annotations dictionary of
        #   this higher-level wrapper, which *SHOULD* be the superset of that of
        #   this lower-level wrappee (and thus more reflective of reality).
        # * The type hints annotating the callable to be unwrapped (i.e.,
        #   "wrapper)" are preferred to those annotating the callable to be
        #   type-checked (i.e., "func"). Why? Because the callable to be
        #   unwrapped is either the original pure-Python function or method
        #   defined by the user *OR* a pseudo-callable object transitively
        #   wrapping that function or method; in either case, the type hints
        #   annotating that callable are guaranteed to be authoritative.
        #   However, the callable to be type-checked is in this case typically
        #   only a thin isomorphic wrapper deferring to the callable to be
        #   unwrapped.
        #
        # Consider the typical use case invoking this conditional logic:
        #     from functools import update_wrapper, wraps
        #
        #     def probably_lies(lies: str, more_lies: str) -> str:
        #         return lies + more_lies
        #
        #     class LyingClass(object):
        #         def __call__(self, *args, **kwargs):
        #             return probably_lies(*args, **kwargs)
        #
        #     cheating_object = LyingClass()
        #     update_wrapper(wrapper=cheating_object, wrapped=probably_lies)
        #     print(cheating_object.__annotations__)
        #
        # ...which would print:
        #     {'lies': <class 'str'>, 'more_lies': <class 'str'>, 'return':
        #     <class 'str'>}
        #
        # We thus see that this use case successfully propagated the
        # "__annotations__" dunder dictionary from the probably_lies()
        # function onto the pseudo-callable "cheating_object" object.
        #
        # In this case, the caller would have called this method as:
        #     decor_meta.reinit(
        #         func=cheating_object.__call__, wrapper=cheating_object)
        #
        # Note that "func" (i.e., the callable to be type-checked) is only a
        # thin isomorphic wrapper deferring to "wrapper" (i.e., the callable to
        # be unwrapped). Even if "func" were annotated with type hints, those
        # type hints would be useless for most intents and purposes.
        self.func_annotations = get_pep649_hintable_annotations(
            hintable=wrapper, exception_cls=BeartypeDecorWrappeeException)
        # print(f'Beartyping func {repr(func)} + wrapper {repr(wrapper)} w/ annotations {self.func_annotations}...')

        # dict.get() method bound to this dictionary.
        self.func_annotations_get = self.func_annotations.get

        # ..................{ VARS ~ func : kind             }..................
        # Default all remaining code snippets to the empty string.
        self.func_wrapper_code_signature_prefix = ''
        self.func_wrapper_code_call_prefix = ''

        # Default the same code snippets set below to those returning values
        # from normal (i.e., non-generator) synchronous callables for sanity.
        self.func_wrapper_code_return_checked = CODE_NORMAL_RETURN_CHECKED
        self.func_wrapper_code_return_unchecked = (
            CODE_NORMAL_RETURN_UNCHECKED_SYNC)

        # If the wrappee callable currently being decorated is pure-Python...
        if func_wrappee_codeobj:
            # print(f'Decorated callable {repr(func)}...')
            # print(f'synchronous generator factory? {is_func_sync_generator(func_wrappee_codeobj)}')

            # If this wrappee is an asynchronous coroutine factory (i.e.,
            # callable declared with "async def" rather than merely "def"
            # keywords and containing *NO* "yield" expressions)...
            #
            # Note that:
            # * The code object of the higher-level wrapper rather than
            #   lower-level wrappee is passed. Why? Because @beartype directly
            #   decorates *ONLY* the former, whose asynchronicity has *NO*
            #   relation to that of the latter. Notably, it is both feasible and
            #   (relatively) commonplace for third-party decorators to enable:
            #   * Synchronous callables to be called asynchronously by wrapping
            #     synchronous callables with asynchronous closures.
            #   * Asynchronous callables to be called synchronously by wrapping
            #     asynchronous callables with synchronous closures. Indeed, our
            #     top-level "conftest.py" pytest plugin does exactly this --
            #     enabling asynchronous tests to be safely called by pytest's
            #     currently synchronous framework.
            # * The higher-level is_func_async() tester is intentionally *NOT*
            #   called here, as doing so would also implicitly prefix all calls
            #   to asynchronous generator factories (i.e., callables also
            #   declared with the "async def" rather than merely "def" keywords
            #   but containing one or more "yield" expressions) with the "await"
            #   keyword. Whereas asynchronous coroutine objects implicitly
            #   returned by all asynchronous coroutine callables return a single
            #   awaitable value, asynchronous generator objects implicitly
            #   returned by all asynchronous generator callables *NEVER* return
            #   any awaitable value; they instead yield one or more values to
            #   external "async for" loops.
            if is_func_coro(func_wrappee_codeobj):
                # Code snippet prefixing the declaration of the wrapper function
                # wrapping this coroutine factory with type-checking.
                self.func_wrapper_code_signature_prefix = 'async '

                # Code snippet prefixing all calls to this coroutine factory.
                self.func_wrapper_code_call_prefix = 'await '

                # Default the same code snippets set below to those returning
                # values from normal (i.e., non-generator) asynchronous
                # callables.
                self.func_wrapper_code_return_unchecked = (
                    CODE_NORMAL_RETURN_UNCHECKED_ASYNC)
            # Else, this wrappee is *NOT* an asynchronous coroutine factory.
            #
            # If this wrappee is a synchronous generator factory (i.e.,
            # callable declared with merely the "def" rather than "async def"
            # keywords and containing one or more "yield" expressions)...
            if is_func_sync_generator(func_wrappee_codeobj):
                # print(f'Decorated synchronous generator factory {repr(func)} detected!')

                # Code snippet yielding from (i.e., deferring to) the
                # synchronous generator returned by calling this PEP
                # 380-compliant synchronous generator factory.
                #
                # Note that:
                # * This prefix is required *ONLY* to force the active Python
                #   interpreter to implicitly enable the "inspect.CO_GENERATOR"
                #   bit flag in the "func.__code__.co_flags" bit field of the
                #   high-level wrapper subsequently generated by the @beartype
                #   decorator wrapping this lower-level wrappee with
                #   type-checking when that wrapper is defined. Why? Because the
                #   standard inspect.isgeneratorfunction() tester conflates a
                #   fictitious one-to-one relation between synchronous generator
                #   factories and pure-Python callables enabling this bit flag.
                #   If @beartype neglected to add "yield from" expressions to
                #   the code generated for type-checking wrappers wrapping
                #   synchronous generator factories, then:
                #   * inspect.isgeneratorfunction() would declare those wrappers
                #     to *NOT* be synchronous generator factories despite those
                #     wrappers literally being such factories.
                #   * Third-party packages (e.g., Gradio) improperly calling
                #     inspect.isgeneratorfunction() to detect synchronous
                #     generator factories would misidentify those wrappers to
                #     *NOT* be synchronous generator factories.
                # * Technically, high-level synchronous generator factories that
                #   defer to lower-level synchronous generator factories do
                #   *NOT* need to perform "yield from" expressions to be usable
                #   as synchronous generator factories. Ergo, the standard
                #   inspect.isgeneratorfunction() tester blatantly returns false
                #   negatives in common use cases. Previously, @beartype was
                #   such a use case. No one should call that tester. Of course,
                #   everyone calls that tester.
                # * This prefix serves *NO* other practical or useful purpose.
                #   Indeed, @beartype previously generated high-level wrappers
                #   for synchronous generator factories simply by calling those
                #   factories and returning the synchronous generators returned
                #   by those calls. That worked for a decade... until
                #   third-party packages outside our control began
                #   inappropriately calling inspect.isgeneratorfunction().
                #
                # See also this closed issue:
                #     https://github.com/beartype/beartype/issues/423

                #FIXME: Actually, this has an additional side benefit. Thanks to
                #this, we can now type-check the value returned by a generator
                #as well against the child hint "{hint_return}" if the return
                #hint annotating this generator factory is of the expanded form
                #"Generator[{hint_yield}, {hint_send}, {hint_return}]". Of
                #course, basically *NOBODY* ever returns *ANYTHING* from a
                #generator. So, it's unclear how many practical value this has.
                #Still, it's feasible now. And that's half the battle.
                #FIXME: Actually, we can do *FAR* better than that. By employing
                #a similar technique as the solution below for asynchronous
                #generators, we can now efficiently (and, more importantly,
                #safely) type-check both synchronous and asynchronous generator
                #*YIELDS* in O(1) time. How? Just:
                #* If this callable is decorated by a return hint (which is
                #  trivially detectable here) *AND* the yield-specific child
                #  hint subscripting that return hint is unignorable (e.g., is
                #  neither "object" nor "typing.Any"), then we should instead
                #  assign "self.func_wrapper_code_return_prefix" here to a
                #  full-blown code snippet implementing our best approximation
                #  of "yield from" in pure-Python augmented with type-checking.
                #* Else, preserve this assignment of
                #  "self.func_wrapper_code_return_prefix" to "yield from", which
                #  is both implemented in C *AND* is the official
                #  implementation. So, it's guaranteed to be the fastest *AND*
                #  safest means of deferring between synchronous generators.

                self.func_wrapper_code_return_checked = (
                    CODE_PEP342_RETURN_CHECKED)
                self.func_wrapper_code_return_unchecked = (
                    CODE_PEP342_RETURN_UNCHECKED)
            # Else, this wrappee is *NOT* a synchronous generator factory.
            #
            # If this wrappee is a asynchronous generator factory (i.e.,
            # callable declared with "async def" keywords and containing one or
            # more "yield" expressions)...
            elif is_func_async_generator(func_wrappee_codeobj):
                # Code snippet prefixing the declaration of the wrapper function
                # wrapping this coroutine factory with type-checking.
                self.func_wrapper_code_signature_prefix = 'async '

                # Code snippet yielding from (i.e., deferring to) the
                # asynchronous generator returned by calling this PEP
                # 525-compliant asynchronous generator factory.
                #
                # Note that:
                # * All of the caveats documented above for the case in which
                #   this wrappee is a synchronous generator factory also apply
                #   here, substituting:
                #   * "inspect.CO_GENERATOR" with "CO_ASYNC_GENERATOR".
                #   * inspect.isgeneratorfunction() with
                #     inspect.isasyncgenfunction().
                # * Additional caveats also apply. Currently, there exists *NO*
                #   C-based "async yield from" expression for asynchronous
                #   generators equivalent to the PEP 380-compliant C-based
                #   "yield from" expression for synchronous generators. This
                #   pure-Python code snippet is our best approximation of a
                #   pure-Python "async yield from" expression. See the docstring
                #   and commentary surrounding the definition of this snippet
                #   for gruesome details that will exhaust your will to code.
                #
                # See also this closed issue:
                #     https://github.com/beartype/beartype/issues/592
                self.func_wrapper_code_return_checked = (
                    CODE_PEP525_RETURN_CHECKED)
                self.func_wrapper_code_return_unchecked = (
                    CODE_PEP525_RETURN_UNCHECKED)
            # Else, this wrappee is *NOT* an asynchronous generator factory.
        # Else, this wrappee is *NOT* pure-Python. In this case, preserve these
        # code snippets as the empty string.

    # ..................{ DUNDERS                            }..................
    def __repr__(self) -> str:
        '''
        Machine-readable representation of this metadata.
        '''

        # Represent this metadata with just the minimal subset of metadata
        # needed to reasonably describe this metadata.
        return (
            f'{self.__class__.__name__}('
            f'func={repr(self.func_wrappee)}, '
            f'conf={repr(self.conf)}'
            f')'
        )

    # ..................{ SETTERS                            }..................
    #FIXME: Unit test us up, please.
    def set_func_annotations_if_dirty(self) -> None:
        '''
        Safely set the ``__annotations__`` dunder dictionary annotating the
        decorated callable to the possibly mutated type hint dictionary
        associated with that callable if the latter is **dirty** (i.e., modified
        from the original type hint dictionary annotating the decorated callable
        by a prior call to the :meth:`set_func_pith_hint` setter).
        '''

        # If the type hint dictionary associated with the decorated callable is
        # dirty (i.e., changed from the original "__annotations__" dunder
        # dictionary annotating that callable), register these changes in a
        # manner compliant with both PEP 649 and Python >= 3.14. Specifically...
        if self._is_func_annotations_dirty:
            # print(f'Setting new function {self.func_wrapper} annotations {self.func_annotations}...')

            # Set these modified annotations on the decorated callable
            # originating these annotations.
            set_pep649_hintable_annotations(
                hintable=self.func_wrapper, annotations=self.func_annotations)

            # Note this type hint dictionary to now be clean.
            self._is_func_annotations_dirty = False
        # Else, the type hint dictionary associated with the decorated callable
        # is still clean (i.e., identical to the original "__annotations__"
        # dunder dictionary annotating that callable). In this case, silently
        # reduce to a noop.


    #FIXME: Unit test us up, please.
    def set_func_pith_hint(self, pith_name: str, hint: Hint) -> None:
        '''
        Safely set the hint annotating the parameter or return with the passed
        name of the decorated callable to the passed hint in a portable manner
        consistent with Python >= 3.14 (and thus both :pep:`649` and :pep:`749`,
        which fundamentally complicate hint mutation).

        Parameters
        ----------
        pith_name : str
            Name of the parameter or return to be re-annotated.
        hint: Hint
            Hint to re-annotate this parameter or return to.

        Raises
        ------
        BeartypeDecorWrappeeException
            If the decorated callable accepts *no* parameter or return with the
            passed name.
        '''
        assert isinstance(pith_name, str), f'{repr(pith_name)} not string.'
        # print(f'Setting new function {self.func_wrapper} pith "{pith_name}" hint {hint}...')

        # If the decorated callable accepts *NO* parameter or return with the
        # passed name, raise an exception.
        if pith_name not in self.func_annotations:
            raise BeartypeDecorWrappeeException(
                f'{prefix_callable_pith(func=self.func_wrapper, pith_name=pith_name)}'
                f'unrecognized.'
            )
        # Else, the decorated callable accepts this parameter or return.

        # Note that the type hint dictionary is now dirty (i.e., modified from
        # the original type hint dictionary annotating the decorated callable).
        self._is_func_annotations_dirty = True

        # Set the hint annotating this parameter or return to the passed hint.
        self.func_annotations[pith_name] = hint

    # ..................{ LABELLERS                          }..................
    def label_func_wrapper(self) -> str:
        '''
        Human-readable label describing the type-checking wrapper function to be
        generated and returned by the current invocation of the
        :func:`beartype.beartype` decorator.

        This method is a non-negligible optimization. Since string munging is
        *extremely* slow and this method necessarily munges strings, external
        callers delay this string munging as late as possible by delaying all
        calls to this method as late as possible (e.g., until an exception
        message requiring this label is actually required).
        '''

        # One-liner of Ultimate Beauty: we invoke thee in this line!
        return f'@beartyped {self.func_wrapper_name}() wrapper'

# ....................{ FACTORIES                          }....................
#FIXME: Unit test us up, please.
def make_beartype_call(**kwargs) -> BeartypeDecorMeta:
    '''
    **Beartype call metadata** (i.e., object encapsulating *all* metadata for
    the passed user-defined callable, typically currently being decorated by the
    :func:`beartype.beartype` decorator).

    Caveats
    -------
    **This higher-level factory function should always be called in lieu of
    instantiating the** :class:`.BeartypeDecorMeta` **class directly.** Why?
    Brute-force efficiency. This factory efficiently reuses previously
    instantiated :class:`.BeartypeDecorMeta` objects rather than inefficiently
    instantiating new :class:`.BeartypeDecorMeta` objects.

    **The caller must pass the metadata returned by this factory back to the**
    :func:`beartype._util.cache.pool.utilcachepoolinstance.release_instance`
    **function.** If accidentally omitted, this metadata will simply be
    garbage-collected rather than available for efficient reuse by this factory.
    Although hardly a worst-case outcome, omitting that explicit call largely
    defeats the purpose of calling this factory in the first place.

    Parameters
    ----------
    All keyword parameters are passed as is to the :meth:`.BeartypeDecorMeta.reinit`
    method.

    Returns
    -------
    BeartypeDecorMeta
        Beartype call metadata describing this callable.
    '''

    # Acquire previously cached beartype call metadata from its object pool.
    decor_meta = acquire_instance(BeartypeDecorMeta)

    # Reinitialize this metadata with the passed keyword parameters.
    decor_meta.reinit(**kwargs)

    # Return this metadata.
    return decor_meta


#FIXME: Unit test us up, please.
def cull_beartype_call(decor_meta: BeartypeDecorMeta) -> None:
    '''
    Deinitialize the passed **beartype call metadata** (i.e., object
    encapsulating *all* metadata for the passed user-defined callable, typically
    currently being decorated by the :func:`beartype.beartype` decorator).

    Parameters
    ----------
    decor_meta : BeartypeDecorMeta
        Beartype call metadata to be deinitialized.
    '''

    # If the type hint dictionary associated with the decorated callable is
    # dirty (i.e., changed from the original "__annotations__" dunder dictionary
    # annotating that callable), register these changes in a manner compliant
    # with both PEP 649 and Python >= 3.14 *BEFORE* nullifying these type hints.
    decor_meta.set_func_annotations_if_dirty()

    # Deinitialize this beartype call metadata.
    decor_meta.deinit()

    # Release this beartype call metadata back to its object pool.
    release_instance(decor_meta)
