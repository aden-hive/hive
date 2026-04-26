#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **configuration class hierarchy** (i.e., public dataclasses enabling
users to configure :mod:`beartype` with optional runtime behaviours).

Most of the public attributes defined by this private submodule are explicitly
exported to external users in our top-level :mod:`beartype.__init__` submodule.
This private submodule is *not* intended for direct importation by downstream
callers.
'''

# ....................{ TODO                               }....................
#FIXME: Generalize "warning_cls_on_decorator_exception", please. Specifically:
#* Deprecate "warning_cls_on_decorator_exception".
#* Define a new "decor_exception_type: Optional[TypeException] = None"
#  parameter accepting *ANY* arbitrary exception rather than merely a warning.

#FIXME: [DOCOS] Document all newly defined configuration parameters in our
#reST-formatted docos, please -- including:
#* "claw_decor_place_func".
#* "claw_decor_place_type".
#* "claw_is_pep526".
#* "claw_skip_package_names".
#* "hint_overrides".
#* "is_pep557_fields".
#* "violation_door_type".
#* "violation_param_type".
#* "violation_return_type".
#* "violation_type".
#* "violation_verbosity".
#* "warning_cls_on_decorator_exception".

# ....................{ IMPORTS                            }....................
from beartype.roar._roarwarn import (
    _BeartypeConfReduceDecoratorExceptionToWarningDefault)
from beartype.typing import (
    TYPE_CHECKING,
    Dict,
    Optional,
)
from beartype._conf.confenum import (
    BeartypeStrategy,
    BeartypeViolationVerbosity,
)
from beartype._conf.conftest import (
    default_conf_kwargs,
    die_if_conf_kwargs_invalid,
    issue_warning_deprecated_option,
    sanify_conf_kwargs,
)
from beartype._conf.decorplace.confplaceenum import BeartypeDecorPlace
from beartype._conf._confget import get_is_color
from beartype._data.typing.datatyping import (
    BoolTristate,
    BoolTristateUnpassable,
    CollectionStrs,
    DictStrToAny,
    TypeException,
    TypeWarning,
)
from beartype._data.func.datafuncarg import ARG_VALUE_UNPASSED
from beartype._data.kind.datakindmap import FROZENDICT_EMPTY
from beartype._util.kind.maplike.utilmapfrozen import FrozenDict
from beartype._util.utilobject import get_object_type_basename
from threading import Lock

# ....................{ DATACLASSES                        }....................
class BeartypeConf(object):
    '''
    **Beartype configuration** (i.e., self-caching dataclass encapsulating all
    flags, options, settings, and other metadata configuring each type-checking
    operation performed by :mod:`beartype` -- including each decoration of a
    callable or class by the :func:`beartype.beartype` decorator).

    Attributes
    ----------
    _claw_decor_place_func : BeartypeDecorPlace
        **Import hook callable decorator place** (i.e., relative position in
        existing chains of one or more decorators decorating user-defined
        functions and methods to which :mod:`beartype.claw` import hooks will
        automatically inject the :func:`beartype.beartype` decorator).
    _claw_decor_place_type : BeartypeDecorPlace
        **Import hook class decorator place** (i.e., relative position in
        existing chains of one or more decorators decorating user-defined
        classes to which :mod:`beartype.claw` import hooks will automatically
        inject the :func:`beartype.beartype` decorator).
    _claw_is_pep526 : bool
        :data:`True` only if type-checking **annotated variable assignments**
        (i.e., :pep:`526`-compliant assignments to local, global, class, and
        instance variables annotated by type hints) when importing modules
        under import hooks published by the :mod:`beartype.claw` subpackage.
    _claw_skip_package_names: Collection[str], optional
        Collection of the absolute names of all packages and modules to be
        **skipped** (i.e., blacklisted, excluded, ignored, omitted) rather than
        runtime type-checked by import hooks published by the
        :mod:`beartype.claw` subpackage -- especially the otherwise fragile
        :mod:`beartype.claw.beartype_all` import hook, which subjects *all*
        packages to runtime type-checking by default.
    _conf_args : tuple
        Tuple of the values of *all* possible keyword parameters (in arbitrary
        order) configuring this configuration.
    _conf_kwargs : Dict[str, object]
        Dictionary mapping from the names to values of *all* possible keyword
        parameters configuring this configuration.
    _hash : int
        Precomputed configuration hash returned by the :meth:`__hash__` dunder
        method for efficiency.
    _hint_overrides : FrozenDict
        **Type hint overrides** (i.e., frozen dictionary mapping from arbitrary
        source to target type hints), enabling callers to lie to both their
        users and all other packages other than :mod:`beartype`. See also the
        :meth:`__new__` method docstring.
    _is_color : Optional[bool]
        Tri-state boolean governing how and whether beartype colours
        **type-checking violations** (i.e.,
        :class:`beartype.roar.BeartypeCallHintViolation` exceptions) with
        POSIX-compliant ANSI escape sequences for readability. Specifically, if
        this boolean is:

        * :data:`False`, beartype *never* colours type-checking violations
          raised by callables configured with this configuration.
        * :data:`True`, beartype *always* colours type-checking violations
          raised by callables configured with this configuration.
        * :data:`None`, beartype conditionally colours type-checking violations
          raised by callables configured with this configuration only when
          standard output is attached to an interactive terminal.
    _is_debug : bool
        :data:`True` only if debugging :mod:`beartype`. See also the
        :meth:`__new__` method docstring.
    _is_pep484_tower : bool
        :data:`True` only if enabling support for the :pep:`484`-compliant
        implicit numeric tower. See also the :meth:`__new__` method docstring.
    _is_pep557_fields : bool
        :data:`True` only if type-checking **dataclass** (i.e., pure-Python
        classes decorated by the :pep:`557`-compliant
        :obj:`dataclasses.dataclass` decorator) **fields** (i.e., class
        attributes annotated by *any* type hints other than :pep:`526`-compliant
        ``dataclasses.ClassVar[...]`` or :pep:`557`-compliant
        ``dataclasses.InitVar[...]`` type hints) on both:
        * **Dataclass object initialization** (i.e., at ``__init__()`` time).
        * **Dataclass field assignment** (i.e., when each field is subsequently
          assigned to by an assignment statement).
    _is_violation_door_warn : bool
        :data:`True` only if :attr:`violation_door_type` is a warning subclass.
        Note that this is stored only as a negligible optimization to avoid
        needless recomputation of this boolean during code generation.
    _is_violation_param_warn : bool
        :data:`True` only if :attr:`violation_param_type` is a warning subclass.
        Note that this is stored only as a negligible optimization to avoid
        needless recomputation of this boolean during code generation.
    _is_violation_return_warn : bool
        :data:`True` only if :attr:`violation_return_type` is a warning
        subclass. Note that this is stored only as a negligible optimization to
        avoid needless recomputation of this boolean during code generation.
    _is_warning_cls_on_decorator_exception_set : bool
        :data:`True` only if the caller explicitly passed the
        :attr:`_warning_cls_on_decorator_exception` parameter. See
        also the :meth:`__new__` method docstring.
    _repr : Optional[str]
        Either:

        * If the :func:`repr` builtin has yet to call the :meth:`__repr__`
          dunder method, :data:`None`.
        * Else, the machine-readable representation of this configuration,
    _strategy : BeartypeStrategy
        **Type-checking strategy** (i.e., :class:`BeartypeStrategy` enumeration
        member) with which to implement all type-checks in the wrapper function
        dynamically generated by the :func:`beartype.beartype` decorator for
        the decorated callable.
    _violation_door_type : TypeException
        **DOOR violation type** (i.e., type of exception raised by the
        :func:`beartype.door.die_if_unbearable` type-checker when the object
        passed to that type-checker violates the type hint passed to that
        type-checker). See also the :meth:`__new__` method docstring.
    _violation_param_type : TypeException
        **Parameter violation type** (i.e., type of exception raised by
        callables generated by the :func:`beartype.beartype` decorator when
        those callables receive parameters violating the type hints annotating
        those parameters). See also the :meth:`__new__` method docstring.
    _violation_return_type : TypeException
        **Return violation type** (i.e., type of exception raised by callables
        generated by the :func:`beartype.beartype` decorator when those
        callables return values violating the type hints annotating those
        returns). See also the :meth:`__new__` method docstring.
    _violation_type : Optional[TypeException]
        **Default violation type** (i.e., type of exception to default whichever
        of the ``violation_door_type``, ``violation_param_type``, and
        ``violation_return_type`` exception types are unpassed and thus
        :data:`None`). See also the :meth:`__new__` method docstring.
    _violation_verbosity : BeartypeViolationVerbosity
        **Violation verbosity** (i.e., positive integer in the inclusive range
        ``[1, 5]`` governing the verbosity of exception messages raised by
        type-checking wrappers generated by the :func:`beartype.beartype`
        decorator when either receiving parameters *or* returning values
        violating their annotated type hints). See also the :meth:`__new__`
        method docstring.
    _warning_cls_on_decorator_exception : Optional[TypeWarning]
        Configuration parameter governing whether the :func:`beartype.beartype`
        decorator reduces otherwise fatal exceptions raised at decoration time
        to equivalent non-fatal warnings of this warning category. See also the
        :meth:`__new__` method docstring.
    '''

    # ..................{ CLASS VARIABLES                    }..................
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Synchronize this slots list with the implementations of:
    # * The __new__() dunder method.
    # CAUTION: Subclasses declaring uniquely subclass-specific instance
    # variables *MUST* additionally slot those variables. Subclasses violating
    # this constraint will be usable but unslotted, which defeats our purposes.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # Slot all instance variables defined on this object to minimize the time
    # complexity of both reading and writing variables across frequently called
    # cache dunder methods. Slotting has been shown to reduce read and write
    # costs by approximately ~10%, which is non-trivial.
    __slots__ = (
        '_claw_decor_place_func',
        '_claw_decor_place_type',
        '_claw_is_pep526',
        '_claw_skip_package_names',
        '_conf_args',
        '_conf_kwargs',
        '_hash',
        '_hint_overrides',
        '_is_color',
        '_is_debug',
        '_is_pep484_tower',
        '_is_pep557_fields',
        '_is_violation_door_warn',
        '_is_violation_param_warn',
        '_is_violation_return_warn',
        '_is_warning_cls_on_decorator_exception_set',
        '_repr',
        '_strategy',
        '_violation_door_type',
        '_violation_param_type',
        '_violation_return_type',
        '_violation_type',
        '_violation_verbosity',
        '_warning_cls_on_decorator_exception',
    )

    # Squelch false negatives from mypy. This is absurd. This is mypy. See:
    #     https://github.com/python/mypy/issues/5941
    if TYPE_CHECKING:
        _claw_decor_place_func: BeartypeDecorPlace
        _claw_decor_place_type: BeartypeDecorPlace
        _claw_is_pep526: bool
        _claw_skip_package_names: CollectionStrs
        _conf_args: tuple
        _conf_kwargs: DictStrToAny
        _hash: int
        _hint_overrides: FrozenDict
        _is_color: BoolTristate
        _is_debug: bool
        _is_pep484_tower: bool
        _is_pep557_fields: bool
        _is_violation_door_warn: bool
        _is_violation_param_warn: bool
        _is_violation_return_warn: bool
        _is_warning_cls_on_decorator_exception_set: bool
        _repr: Optional[str]
        _strategy: BeartypeStrategy
        _violation_door_type: TypeException
        _violation_param_type: TypeException
        _violation_return_type: TypeException
        _violation_type: Optional[TypeException]
        _violation_verbosity: BeartypeViolationVerbosity
        _warning_cls_on_decorator_exception: Optional[TypeWarning]

    # ..................{ INSTANTIATORS                      }..................
    # Note that this __new__() dunder method implements the superset of the
    # functionality typically implemented by the __init__() dunder method. Due
    # to Python instantiation semantics, the __init__() dunder method is
    # intentionally left undefined. Why? Because Python unconditionally invokes
    # __init__() if defined, even when the initialization performed by that
    # __init__() has already been performed for the cached instance returned by
    # __new__(). In short, __init__() and __new__() are largely mutually
    # exclusive; one typically defines one or the other but *NOT* both.

    def __new__(
        cls,

        # Optional keyword-only parameters.
        *,

        # Uncomment us when implementing O(n) type-checking, please.
        # check_time_max_multiplier: Union[int, None] = 1000,
        claw_decor_place_func: BeartypeDecorPlace = (
            BeartypeDecorPlace.LAST_BEFORE_DECOR_HOSTILE),
        claw_decor_place_type: BeartypeDecorPlace = (
            BeartypeDecorPlace.LAST),
        claw_is_pep526: bool = True,
        claw_skip_package_names: CollectionStrs = (),
        hint_overrides: FrozenDict = FROZENDICT_EMPTY,
        is_color: BoolTristateUnpassable = ARG_VALUE_UNPASSED,  # pyright: ignore
        is_debug: bool = False,
        is_pep484_tower: bool = False,
        is_pep557_fields: bool = False,
        strategy: BeartypeStrategy = BeartypeStrategy.O1,
        violation_door_type: Optional[TypeException] = None,
        violation_param_type: Optional[TypeException] = None,
        violation_return_type: Optional[TypeException] = None,
        violation_type: Optional[TypeException] = None,
        violation_verbosity: BeartypeViolationVerbosity = (
            BeartypeViolationVerbosity.DEFAULT),
        warning_cls_on_decorator_exception: Optional[TypeWarning] = (
            _BeartypeConfReduceDecoratorExceptionToWarningDefault),

        #FIXME: Consider removing these at some point, please.
        # Optional keyword-only *DEPRECATED* parameters.
        claw_decoration_position_funcs: Optional[BeartypeDecorPlace] = None,
        claw_decoration_position_types: Optional[BeartypeDecorPlace] = None,
        is_check_pep557: Optional[bool] = None,
    ) -> 'BeartypeConf':
        '''
        Instantiate this configuration if needed (i.e., if *no* prior
        configuration with these same parameters was previously instantiated)
        *or* reuse that previously instantiated configuration otherwise.

        This dunder methods guarantees beartype configurations to be memoized:

        .. code-block:: python

           >>> from beartype import BeartypeConf
           >>> BeartypeConf() is BeartypeConf()
           True

        This memoization is *not* merely an optimization. The
        :func:`beartype.beartype` decorator internally memoizes the private
        closure it creates and returns on the basis of this configuration,
        which *must* thus also be memoized.

        Parameters
        ----------
        check_time_max_multiplier : Union[int, None] = 1000
            **Deadline multiplier** (i.e., positive integer instructing
            :mod:`beartype` to prematurely halt the current type-check when the
            total running time of the active Python interpreter exceeds this
            integer multiplied by the running time consumed by both the current
            type-check and all prior type-checks *and* the caller also passed a
            non-default ``strategy``) *or* :data:`None` if :mod:`beartype`
            should never prematurely halt runtime type-checks.

            Increasing this integer increases the number of container items that
            :mod:`beartype` type-checks at a cost of decreasing application
            responsiveness. Likewise, decreasing this integer increases
            application responsiveness at a cost of decreasing the number of
            container items that :mod:`beartype` type-checks.

            Ignored when ``strategy`` is :attr:`BeartypeStrategy.O1`, as that
            strategy is already effectively instantaneous; imposing deadlines
            and thus bureaucratic bookkeeping on that strategy would only
            reduce its efficiency for no good reason, which is a bad reason.

            Defaults to 1000, in which case a maximum of 0.10% of the total
            runtime of the active Python process will be devoted to performing
            non-constant :mod:`beartype` type-checks over container items. This
            default has been carefully tuned to strike a reasonable balance
            between runtime type-check coverage and application responsiveness,
            typically enabling smaller containers to be fully type-checked
            without noticeably impacting codebase performance.

            **Theory time.** Let:

            * :math:`T` be the total time this interpreter has been running.
            * :math:``b` be the total time :mod:`beartype` has spent
              type-checking in this interpreter.

            Clearly, :math:`b <= T`. Generally, :math:`b <<<<<<< T` (i.e.,
            type-checks consume much less time than the total time consumed by
            the process). However, it's all too easy to exhibit worst-case
            behaviour of :math:`b ~= T` (i.e., type-checks consume most of the
            total time). How? By passing the :func:`beartype.door.is_bearable`
            tester an absurdly large nested container subject to the non-default
            ``strategy`` of :attr:`BeartypeStrategy.On`.

            This deadline multiplier mitigates that worst-case behaviour.
            Specifically, :mod:`beartype` will prematurely halt any iterative
            type-check across a container when this constraint is triggered:

            .. code-block:: python

               b * check_time_max_multiplier >= T
        claw_decor_place_func : BeartypeDecorPlace, optional
            **Import hook callable decorator place** (i.e., relative position in
            existing chains of one or more decorators decorating user-defined
            functions and methods to which :mod:`beartype.claw` import hooks
            will automatically inject the :func:`beartype.beartype` decorator).
            Defaults to :attr:`BeartypeDecorPlace.LAST_BEFORE_DECOR_HOSTILE`.

            Modifying this configures import hooks to inject
            :func:`beartype.beartype` as the first (rather than last) decorator
            for callables. If your codebase requires this, consider submitting
            an issue to the :mod:`beartype` issue tracker. Ideally, the
            :func:`beartype.beartype` decorator should be order-invariant with
            respect to decorator chaining and thus support decoration in *any*
            position – including the default last position: e.g.,

            .. code-block:: python

               # Registering this import hook...
               from beartype import BeartypeConf, BeartypeDecorPlace
               from beartype.claw import beartype_this_package
               beartype_this_package(conf=BeartypeConf(
                   claw_decor_place_func=(
                       BeartypeDecorPlace.FIRST)))

               # ...transforms chains of function decorators like this...
               from functools import cache
               @cache
               def chad_func() -> int:
                   return 42

               # ...into chains of function decorators like this.
               from beartype import beartype
               from functools import cache
               @cache
               @beartype  # <-- @beartype decorates first rather than last! \\o/
               def chad_func() -> int:
                   return 42
        claw_decor_place_type : BeartypeDecorPlace, optional
            **Import hook class decorator place** (i.e., relative position in
            existing chains of one or more decorators decorating user-defined
            classes to which :mod:`beartype.claw` import hooks will
            automatically inject the :func:`beartype.beartype` decorator).
            Defaults to :attr:`BeartypeDecorPlace.LAST`.

            Modifying this configures import hooks to inject
            :func:`beartype.beartype` as the first (rather than last) decorator
            for classes. If your codebase requires this, consider submitting an
            issue to the :mod:`beartype` issue tracker. Ideally, the
            :func:`beartype.beartype` decorator should be order-invariant with
            respect to decorator chaining and thus support decoration in *any*
            position – including the default last position: e.g.,

            .. code-block:: python

               # Registering this import hook...
               from beartype import BeartypeConf, BeartypeDecorPlace
               from beartype.claw import beartype_this_package
               beartype_this_package(conf=BeartypeConf(
                   claw_decor_place_type=(
                       BeartypeDecorPlace.FIRST)))

               # ...transforms chains of class decorators like this...
               from dataclasses import dataclass
               @dataclass
               class ClassyData(object):
                   integral_datum: int

               # ...into chains of class decorators like this.
               from beartype import beartype
               from dataclasses import dataclass
               @dataclass
               @beartype  # <-- @beartype decorates first rather than last! \\o/
               class ClassyData(object):
                   integral_datum: int
        claw_is_pep526 : bool, optional
            :data:`True` only if implicitly type-checking **annotated variable
            assignments** (i.e., :pep:`526`-compliant assignments to local,
            global, class, or instance variables annotated by type hints) when
            importing modules under :mod:`beartype.claw` import hooks by
            injecting calls to the :func:`beartype.door.die_if_unbearable`
            function immediately *after* those assignments in those modules.
            Enabling this boolean:

            * Effectively augments :mod:`beartype` into a full-blown **hybrid
              runtime-static type-checker** (i.e., performing both standard
              runtime type-checking *and* non-standard static type-checking at
              runtime).
            * Adds mostly negligible runtime overhead to all annotated variable
              assignments in all modules imported under those import hooks.
              Although the *individual* cost of this overhead for any given
              assignment is negligible, the *aggregate* cost across all such
              assignments could be non-negligible in worst-case use cases.

            Ideally, this boolean should only be disabled for a small subset of
            performance-sensitive modules *after* profiling those modules to
            suffer performance regressions under :mod:`beartype.claw` import
            hooks. Defaults to :data:`True`.
        claw_skip_package_names: Collection[str], optional
            Collection of the absolute names of all packages and modules to be
            **skipped** (i.e., blacklisted, excluded, ignored, omitted) rather
            than runtime type-checked by import hooks published by the
            :mod:`beartype.claw` subpackage -- especially the otherwise fragile
            :mod:`beartype.claw.beartype_all` import hook, which subjects *all*
            packages to runtime type-checking by default.

            Import hooks published by the :mod:`beartype.claw` subpackage will
            avoid applying runtime type-checking to *any* package or module:

            * Whose absolute name is directly listed in this iterable *or*...
            * Which is a subpackage or submodule transitively residing in *any*
              package or module whose absolute name is directly listed in this
              iterable. Listing the name of a package in this iterable thus
              suffices to skip both that package *and* all transitive
              subpackages and submodules of that package in entirety. Individual
              subpackages and submodules need *not* be explicitly listed
              (e.g., ``claw_skip_package_names=('worst_package_evah',)`` skips
              the ``worst_package_evah`` package in entirety).

            Defaults to the empty tuple.
        hint_overrides : FrozenDict, default: FROZENDICT_EMPTY
            **Type hint overrides** (i.e., frozen dictionary mapping from
            arbitrary source to target type hints), enabling callers to lie to
            both their users and all other packages other than :mod:`beartype`.
            This dictionary enables callers to externally present a public API
            annotated by simplified type hints while internally instructing
            :mod:`beartype` to privately type-check that API under a completely
            different set of (typically more complicated) type hints. Doing so
            preserves a facade of simplicity for downstream consumers like end
            users, static type-checkers, and document generators. Defaults to
            the empty frozen dictionary.

            Specifically, for each source type hint annotating each callable,
            class, or variable assignment observed by :mod:`beartype`, if that
            source type hint is a key of this dictionary, :mod:`beartype` maps
            that source type hint to the corresponding target type hint in this
            dictionary. That target type hint then globally "overrides" (i.e.,
            replaces, substitutes for) that source type hint. :mod:`beartype`
            then uses that target type hint in place of that source type hint.

            Note that this parameter *must* be a **frozen dictionary** (i.e.,
            :mod:`beartype`-specific :class:`beartype.FrozenDict` object) rather
            than a **mutable dictionary** (i.e., standard :class:`dict` object).
            Sadly, Python still lacks a standard frozen dictionary type. Since
            beartype configurations are memoized (i.e., cached), mutable
            containers like dictionaries are prohibited for safety.

            For example, consider this Abomination Unto the Eyes of Guido:

            .. code-block:: python

               from beartype, BeartypeConf, FrozenDict

               # @beartype decorator configured to expand all "float" type hints
               # to "int | float" type hints.
               lyingbeartype = beartype(conf=BeartypeConf(
                   hint_overrides=FrozenDict({float: int | float})))

               # The @lyingbeartype decorator now expands this signature...
               @lyingbeartype
               def lies(all_lies: list[int]) -> int:
                   return all_lies[0]

               # ...as if it had been annotated like this instead.
               @beartype
               def lies(all_lies: list[int | float]) -> int | float:
                   return all_lies[0]
        is_color : BoolTristateUnpassable
            Tri-state boolean governing how and whether beartype colours
            **type-checking violations** (i.e.,
            :class:`beartype.roar.BeartypeCallHintViolation` exceptions) with
            POSIX-compliant ANSI escape sequences for readability. Specifically,
            if this boolean is:

            * :data:`False`, beartype *never* colours type-checking violations
              raised by callables configured with this configuration.
            * :data:`True`, beartype *always* colours type-checking violations
              raised by callables configured with this configuration.
            * :data:`None`, beartype conditionally colours type-checking
              violations raised by callables configured with this configuration
              only when standard output is attached to an interactive terminal.

            The ``${BEARTYPE_IS_COLOR}`` environment variable globally overrides
            *all* attempts by *all* callers to explicitly pass this parameter,
            enabling end users to enforce a global colour policy across their
            full app stack. If ``${BEARTYPE_IS_COLOR}`` is set to a different
            value than that of this parameter, this constructor emits a
            non-fatal :class:`beartype.roar.BeartypeConfShellVarWarning` warning
            informing the caller of this configuration conflict. To avoid this
            conflict, open-source libraries are recommended to *not* pass this
            parameter; ideally, *only* end user apps should pass this parameter.

            Effectively defaults to :data:`None`. Technically, this parameter
            defaults to a private magic constant *not* intended to be passed by
            callers, enabling :mod:`beartype` to reliably detect whether the
            caller has explicitly passed this parameter or not.
        is_debug : bool, optional
            :data:`True` only if debugging :mod:`beartype`. Enabling this
            boolean:

            * Prints the definition (including both the signature and body) of
              each type-checking wrapper function dynamically generated by
              :mod:`beartype` to standard output.
            * Caches the body of each type-checking wrapper function dynamically
              generated by :mod:`beartype` with the standard :mod:`linecache`
              module, enabling these function bodies to be introspected at
              runtime *and* improving the readability of tracebacks whose call
              stacks contain one or more calls to these
              :func:`beartype.beartype`-decorated functions.
            * Appends to the declaration of each **hidden parameter** (i.e.,
              whose name is prefixed by ``"__beartype_"`` and whose value is
              that of an external attribute internally referenced in the body of
              that function) the machine-readable representation of the initial
              value of that parameter, stripped of newlines and truncated to a
              hopefully sensible length. Since the
              :func:`beartype._util.text.utiltextrepr.represent_object` function
              called to do so is shockingly slow, these substrings are
              conditionally embedded in the returned signature *only* when
              enabling this boolean.

            Defaults to :data:`False`.
        is_pep484_tower : bool, optional
            :data:`True` only if enabling support for the :pep:`484`-compliant
            **implicit numeric tower** (i.e., lossy conversion of integers to
            floating-point numbers *and* both integers and floating-point
            numbers to complex numbers). Specifically, enabling this instructs
            :mod:`beartype` to automatically expand:

            * All :class:`float` type hints to ``float | int``, thus implicitly
              accepting both integers and floating-point numbers for objects
              annotated as only accepting floating-point numbers.
            * All :class:`complex` type hints to ``complex | float | int``, thus
              implicitly accepting integers, floating-point, and complex numbers
              for objects annotated as only accepting complex numbers.

            Defaults to :data:`False` to minimize precision error introduced by
            lossy conversions from integers to floating-point numbers to complex
            numbers. Since most integers do *not* have exact representations
            as floating-point numbers, each conversion of an integer into a
            floating-point number typically introduces a small precision error
            that accumulates over multiple conversions and operations into a
            larger precision error. Enabling this improves the usability of
            public APIs at a cost of introducing precision errors.
        is_pep557_fields : bool, default: False
            :data:`True` only if type-checking **dataclass** (i.e., pure-Python
            classes decorated by the :pep:`557`-compliant
            :obj:`dataclasses.dataclass` decorator) **fields** (i.e., class
            attributes annotated by *any* type hints other than
            :pep:`526`-compliant ``dataclasses.ClassVar[...]`` or
            :pep:`557`-compliant ``dataclasses.InitVar[...]`` type hints) on
            both:
            * **Dataclass object initialization** (i.e., at ``__init__()``
              time) *and*...
            * **Dataclass field assignment** (i.e., when each field is
              subsequently assigned to by an assignment statement).

            Currently defaults to :data:`False`, due to the non-triviality of
            safely type-checking dataclass fields across all possible dataclass
            configurations and use cases.
        strategy : BeartypeStrategy, optional
            **Type-checking strategy** (i.e., :class:`BeartypeStrategy`
            enumeration member) with which to implement all type-checks in the
            wrapper function dynamically generated by the
            :func:`beartype.beartype` decorator for the decorated callable.
            Defaults to :attr: `BeartypeStrategy.O1`, the ``O(1)`` constant-time
            strategy.
        violation_door_type : Optional[TypeException]
            **DOOR violation type** (i.e., type of exception raised by the
            :func:`beartype.door.die_if_unbearable` type-checker when the object
            passed to that type-checker violates the type hint passed to that
            type-checker). Defaults to :data:`None`, in which case this type
            defaults to either:

            * If ``violation_type`` is passed and *not* :data:`None`, that type.
            * Else, :exc:`.BeartypeDoorHintViolation`.
        violation_param_type : Optional[TypeException]
            **Parameter violation type** (i.e., type of exception raised by
            callables generated by the :func:`beartype.beartype` decorator when
            those callables receive parameters violating the type hints
            annotating those parameters). Defaults to :data:`None`, in which
            case this type defaults to either:

            * If ``violation_type`` is passed and *not* :data:`None`, that type.
            * Else, :exc:`.BeartypeCallHintParamViolation`.
        violation_return_type : Optional[TypeException]
            **Return violation type** (i.e., type of exception raised by
            callables generated by the :func:`beartype.beartype` decorator when
            those callables return values violating the type hints annotating
            those returns). Defaults to :data:`None`, in which case this type
            defaults to either:

            * If ``violation_type`` is passed and *not* :data:`None`, that type.
            * Else, :exc:`.BeartypeCallHintReturnViolation`.
        violation_type : Optional[TypeException]
            **Default violation type** (i.e., type of exception to default
            whichever of the ``violation_door_type``, ``violation_param_type``,
            and ``violation_return_type`` exception types are unpassed and thus
            :data:`None`).  This parameter is merely a convenience enabling
            callers to trivially control the ``violation_door_type``,
            ``violation_param_type``, and ``violation_return_type`` parameters
            *without* having to explicitly pass all three of those parameters.
            Specifically, if this parameter is:

            * *Not* :data:`None`, then the ``violation_door_type``,
              ``violation_param_type``, and ``violation_return_type`` parameters
              all default to the value of this parameter.
            * :data:`None`, then:

              * ``violation_door_type`` defaults to
                :exc:`.BeartypeDoorHintViolation`.
              * ``violation_param_type`` defaults to
                :exc:`.BeartypeCallHintParamViolation`.
              * ``violation_return_type`` defaults to
                :exc:`.BeartypeCallHintReturnViolation`.

            Defaults to :data:`None`.
        violation_verbosity : BeartypeViolationVerbosity, optional
            **Violation verbosity** (i.e., positive integer in the inclusive
            range ``[1, 5]`` governing the verbosity of exception messages
            raised by type-checking wrappers generated by the
            :func:`beartype.beartype` decorator when either receiving parameters
            *or* returning values violating their annotated type hints).
            Defaults to :attr:`.BeartypeViolationVerbosity.DEFAULT`.
        warning_cls_on_decorator_exception : Optional[TypeWarning]
            Configuration parameter governing whether the
            :func:`beartype.beartype` decorator reduces what would otherwise be
            fatal exceptions raised at decoration time to equivalent non-fatal
            warnings of the passed **warning category** (i.e., subclass of the
            standard :class:`Warning` class). Specifically, this parameter may
            be either:

            * :data:`None`, in which case the :func:`beartype.beartype`
              decorator raises fatal exceptions at decoration time.
            * A warning category, in which case the :func:`beartype.beartype`
              decorator reduces fatal exceptions to non-fatal warnings of this
              category at decoration time.

            Defaults to a private warning type *not* intended to be passed by
            callers, enabling :mod:`beartype` to reliably detect when the caller
            has *not* explicitly passed this parameter and respond accordingly
            by defaulting this parameter to a context-dependent value. Notably,
            if this parameter is *not* explicitly passed:

            * The :func:`beartype.beartype` decorator defaults this parameter to
              :data:`None`, thus raising decoration-time exceptions.
            * The :mod:`beartype.claw` API defaults this parameter to the public
              :class:`beartype.roar.BeartypeClawDecorWarning` warning category,
              thus reducing decoration-time exceptions to warnings of that
              category when performing import hooks. This default behaviour
              significantly increases the likelihood that import hooks installed
              by :mod:`beartype.claw` will successfully decorate the entirety of
              their target packages rather than prematurely halt with a single
              fatal exception at the first decoration issue.

        Returns
        -------
        BeartypeConf
            Beartype configuration memoized with these parameters.

        Raises
        ------
        BeartypeConfParamException
            If either:

            * ``is_color`` is *not* a tri-state boolean.
            * ``is_debug`` is *not* a boolean.
            * ``is_pep484_tower`` is *not* a boolean.
            * ``is_pep557_fields`` is *not* a boolean.
            * ``strategy`` is *not* a :class:`BeartypeStrategy` enumeration
              member.
            * ``warning_cls_on_decorator_exception`` is neither :data:`None`
              *nor* a **warning category** (i.e., :class:`Warning` subclass).
        BeartypeConfShellVarException
            If either:

            * The external ``${BEARTYPE_IS_COLOR}`` shell environment variable
              is set to an unrecognized string (i.e., neither ``"True"``,
              ``"False"``, nor ``"None"``).

        Warns
        -----
        DeprecationWarning
            If a deprecated parameter is passed, including any of the following:

            * ``is_check_pep557``.
        '''

        # In a non-reentrant thread lock specific to beartype configurations...
        #
        # Note that this lock is potentially overkill and thus unnecessary.
        # Nonetheless, since the number of beartype configurations instantiated
        # over the lifetime of the average Python interpreter is small, since
        # non-reentrant thread locks are reasonably fast to enter, and since the
        # cost of race conditions is high, this lock does no real-world harm and
        # may actually do a great deal of real-world good. Safety first, all!
        with _beartype_conf_lock:
            # ..................{ DEPRECATED                 }..................
            # If the caller passed any deprecated parameter:
            # * Issue one non-fatal deprecation warning for each.
            # * Pass the corresponding non-deprecated parameter instead.
            #
            # Note that:
            # * Deprecated parameters *MUST* be coerced into non-deprecated
            #   parameters before caching the latter.
            # * This could be automated with iteration iterating over a private
            #   frozen dictionary mapping deprecated to non-deprecated option
            #   names. Why didn't we just do that, then? *SPEED.* The current
            #   inline approach is considerably faster. Since this logic is
            #   necessarily performed *BEFORE* reducing to a previously cached
            #   configuration, this logic warrants this micro-optimization.
            #   Moreover, automation only saves a few lines... at best.
            #   Moreover, deprecated parameters should be removed at some point
            #   anyway! This is just irrelevant cruft, mostly.
            if claw_decoration_position_funcs is not None:
                issue_warning_deprecated_option(
                    option_name_old='claw_decoration_position_funcs',
                    option_name_new='claw_decor_place_func',
                )
                claw_decor_place_func = claw_decoration_position_funcs
            if claw_decoration_position_types is not None:
                issue_warning_deprecated_option(
                    option_name_old='claw_decoration_position_types',
                    option_name_new='claw_decor_place_type',
                )
                claw_decor_place_type = claw_decoration_position_types
            if is_check_pep557 is not None:
                issue_warning_deprecated_option(
                    option_name_old='is_check_pep557',
                    option_name_new='is_pep557_fields',
                )
                is_pep557_fields = is_check_pep557

            # ..................{ CACHE                      }..................
            # Validate and possibly override the "is_color" parameter by the
            # value of the ${BEARTYPE_IS_COLOR} environment variable (if set).
            is_color = get_is_color(is_color)

            #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
            # CAUTION: Synchronize this tuple with the similar
            # "self._conf_kwargs" dictionary defined below.
            #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
            # Efficiently hashable tuple of these parameters in arbitrary order.
            conf_args = (
                claw_decor_place_func,
                claw_decor_place_type,
                claw_is_pep526,
                claw_skip_package_names,
                hint_overrides,
                is_color,
                is_debug,
                is_pep484_tower,
                is_pep557_fields,
                strategy,
                violation_door_type,
                violation_param_type,
                violation_return_type,
                violation_type,
                violation_verbosity,
                warning_cls_on_decorator_exception,
            )

            # If this method has already instantiated a configuration with these
            # parameters, return that configuration for consistency and
            # efficiency.
            if conf_args in _beartype_conf_args_to_conf:
                return _beartype_conf_args_to_conf[conf_args]
            # Else, this method has *NOT* yet instantiated a configuration with
            # these parameters. In this case, continue to do so and then cache
            # that configuration.

            # Dictionary mapping from the names to values of *ALL* possible
            # keyword parameters configuring this configuration, intentionally
            # defined *AFTER* this method first attempts to efficiently reduce
            # to a noop by returning a previously instantiated configuration.
            conf_kwargs = dict(
                claw_decor_place_func=claw_decor_place_func,
                claw_decor_place_type=claw_decor_place_type,
                claw_is_pep526=claw_is_pep526,
                claw_skip_package_names=claw_skip_package_names,
                hint_overrides=hint_overrides,
                is_color=is_color,
                is_debug=is_debug,
                is_pep484_tower=is_pep484_tower,
                is_pep557_fields=is_pep557_fields,
                strategy=strategy,
                violation_door_type=violation_door_type,
                violation_param_type=violation_param_type,
                violation_return_type=violation_return_type,
                violation_type=violation_type,
                violation_verbosity=violation_verbosity,
                warning_cls_on_decorator_exception=(
                    warning_cls_on_decorator_exception),
            )

            # Default all parameters not explicitly passed by the user to sane
            # defaults *BEFORE* validating these parameters.
            default_conf_kwargs(conf_kwargs)

            # If one or more passed parameters are invalid, raise an exception.
            die_if_conf_kwargs_invalid(conf_kwargs)
            # Else, all passed parameters are valid.

            # Sanify all passed parameters *AFTER* validating these parameters.
            sanify_conf_kwargs(conf_kwargs)

            # ..................{ INSTANTIATE                }..................
            # Instantiate a new configuration of this type.
            self = super().__new__(cls)

            # Nullify critical instance variables for safety.
            self._repr = None

            # Precompute the hash to be returned by the __hash__() dunder method
            # as the hash of a tuple containing these parameters in an arbitrary
            # (albeit well-defined) order.
            #
            # Note this has been profiled to be the optimal means of hashing
            # object attributes in Python, where "optimal" means:
            # * Optimally fast. CPython in particular optimizes the creation and
            #   garbage collection of "small" tuples, where "small" is
            #   ill-defined but almost certainly applies here.
            # * Optimally uniformly distributed, thus minimizing the likelihood
            #   of expensive hash collisions.
            self._hash = hash(conf_args)

            # Store data structures encapsulating these passed parameters for
            # subsequent reuse *BEFORE* possibly modifying the values of these
            # parameters below.
            self._conf_args = conf_args
            self._conf_kwargs = conf_kwargs

            # Assert that these two data structures encapsulate the same number
            # of configuration parameters.
            #
            # Note that this is a feeble safety check against internal issues.
            # Although this condition should *ALWAYS* be true, asserting this
            # condition costs us nothing and gains us much: namely, QA.
            assert len(self._conf_args) == len(self._conf_kwargs)

            # Cache this configuration with all relevant dictionary singletons
            # *BEFORE* possibly modifying the values of passed parameters below.
            _beartype_conf_args_to_conf[conf_args] = self

            # ..................{ CLASSIFY                   }..................
            # Classify all passed parameters that have now been possibly
            # modified above with this configuration.
            #
            # Note that this classification intentionally accesses these
            # parameters from the "conf_kwargs" dictionary possibly modified by
            # the above call to the default_conf_kwargs() function rather than
            # the original passed values of these parameters.
            self._claw_decor_place_func = conf_kwargs[  # pyright: ignore
                'claw_decor_place_func']
            self._claw_decor_place_type = conf_kwargs[  # pyright: ignore
                'claw_decor_place_type']
            self._claw_is_pep526 = conf_kwargs['claw_is_pep526']  # pyright: ignore
            self._claw_skip_package_names = conf_kwargs[
                'claw_skip_package_names']  # pyright: ignore
            self._hint_overrides = conf_kwargs['hint_overrides']  # pyright: ignore
            self._is_color = conf_kwargs['is_color']  # pyright: ignore
            self._is_debug = conf_kwargs['is_debug']  # pyright: ignore
            self._is_pep484_tower = conf_kwargs['is_pep484_tower']  # pyright: ignore
            self._is_pep557_fields = conf_kwargs['is_pep557_fields']  # pyright: ignore
            self._strategy = conf_kwargs['strategy']  # pyright: ignore
            self._violation_door_type = conf_kwargs['violation_door_type']  # pyright: ignore
            self._violation_param_type = conf_kwargs['violation_param_type']  # pyright: ignore
            self._violation_return_type = conf_kwargs['violation_return_type']  # pyright: ignore
            self._violation_type = conf_kwargs['violation_type']  # pyright: ignore
            self._violation_verbosity = conf_kwargs['violation_verbosity']  # pyright: ignore

            # Classify all remaining instance variables.
            self._is_violation_door_warn = issubclass(
                self._violation_door_type, Warning)  # pyright: ignore
            self._is_violation_param_warn = issubclass(
                self._violation_param_type, Warning)  # pyright: ignore
            self._is_violation_return_warn = issubclass(
                self._violation_return_type, Warning)  # pyright: ignore

            # ..................{ CLASSIFY ~ more            }..................
            # If the value of the "warning_cls_on_decorator_exception" parameter
            # is the default private fake warning category established above,
            # the caller failed to pass a valid value. In this case...
            #
            # Note that this default is intentionally handled manually here
            # rather than in either the default_conf_kwargs_before() or
            # default_conf_kwargs_after() functions called above. Why? Because
            # the original default
            # "_BeartypeConfReduceDecoratorExceptionToWarningDefault" *MUST* be
            # preserved in the public "conf_kwargs" property to ensure that
            # permutations of this configuration created via that property
            # preserve the original default. (Look. It's complicated. I sigh!)
            if (
                warning_cls_on_decorator_exception is
                _BeartypeConfReduceDecoratorExceptionToWarningDefault
            ):
                # Note this fact for subsequent reference elsewhere (e.g., in
                # the "beartype.claw" subpackage).
                self._is_warning_cls_on_decorator_exception_set = False

                # Default this parameter to "None" for safety. Since this
                # default private fake warning category is *NOT* an actual
                # warning category intended for real-world use, this category
                # *MUST* be replaced with a sane default that is safely usable.
                warning_cls_on_decorator_exception = None
            # Else, the caller explicitly passed a valid value for this
            # parameter. In this case, preserve this value and note this fact.
            else:
                self._is_warning_cls_on_decorator_exception_set = True

            self._warning_cls_on_decorator_exception = (
                warning_cls_on_decorator_exception)

        # Return this configuration.
        return self

    # ..................{ PROPERTIES                         }..................
    # Read-only public properties effectively prohibiting mutation of their
    # underlying private attributes.

    #FIXME: Publicly document this in our reST-formatted docos, please.
    @property
    def kwargs(self) -> DictStrToAny:
        '''
        **Beartype configuration keyword dictionary** (i.e., dictionary mapping
        from the names of all keyword parameters accepted by the :meth:`__new__`
        method to the corresponding values of those parameters in this
        configuration).

        This property can be used to permute a new beartype configuration from
        an existing beartype configuration, overriding only a small handful of
        parameters while preserving all other parameters as is: e.g.,

        .. code-block:: python

           # Input beartype configuration.
           conf = BeartypeConf(is_color=True)

           # New keyword dictionary permuted from this input.
           conf_kwargs = conf.kwargs.copy()
           conf_kwargs['is_debug'] = True

           # New beartype configuration initialized by this dictionary.
           debug_conf = BeartypeConf(**conf_kwargs)

        Caveats
        -------
        **Avoid modifying this dictionary directly.** Instead, only modify
        shallow copies of this dictionary as in the above example. If this
        dictionary is directly modified, this beartype configuration *will*
        behave erratically, erroneously, and non-deterministically.

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._conf_kwargs

    # ..................{ PROPERTIES ~ options               }..................
    # Read-only public properties with which this configuration was originally
    # instantiated (as keyword-only parameters).
    #
    # Note that *ALL* of these properties could be automated away with a single
    # sufficiently intelligent __getattr__() implementation. Indeed, we briefly
    # attempted to do just that. So what happened? Static type-checkers.
    # Although tedious and error-prone, the current approach of manually
    # implementing one read-only public property for each keyword-only parameter
    # has the distinct advantage of informing static type-checkers of the type
    # hints annotating these properties. While automated and error-free, the
    # __getattr__() approach destroyed that typing -- which then effectively
    # broke backward compatibility with end users using static type-checkers.

    @property
    def hint_overrides(self) -> FrozenDict:
        '''
        **Type hint overrides** (i.e., frozen dictionary mapping from arbitrary
        source to target type hints), enabling callers to lie to both their
        users and all other packages other than :mod:`beartype`. This dictionary
        enables callers to externally present a public API annotated by
        simplified type hints while internally instructing :mod:`beartype` to
        privately type-check that API under a completely different set of
        (typically more complicated) type hints.

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._hint_overrides


    @property
    def strategy(self) -> BeartypeStrategy:
        '''
        **Type-checking strategy** (i.e., :class:`BeartypeStrategy`
        enumeration member) with which to implement all type-checks in the
        wrapper function dynamically generated by the
        :func:`beartype.beartype` decorator for the decorated callable.

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._strategy


    @property
    def warning_cls_on_decorator_exception(self) -> (
        Optional[TypeWarning]):
        '''
        Configuration parameter governing whether the :func:`beartype.beartype`
        decorator reduces otherwise fatal exceptions raised at decoration time
        to equivalent non-fatal warnings of this warning category.

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._warning_cls_on_decorator_exception

    # ..................{ PROPERTIES ~ options : bool        }..................
    @property
    def is_color(self) -> BoolTristate:
        '''
        Tri-state boolean governing how and whether beartype colours
        **type-checking violations** (i.e.,
        :class:`beartype.roar.BeartypeCallHintViolation` exceptions) with
        POSIX-compliant ANSI escape sequences for readability. Specifically, if
        this boolean is:

        * :data:`False`, beartype *never* colours type-checking violations
          raised by callables configured with this configuration.
        * :data:`True`, beartype *always* colours type-checking violations
          raised by callables configured with this configuration.
        * :data:`None`, beartype conditionally colours type-checking violations
          raised by callables configured with this configuration only when
          standard output is attached to an interactive terminal.

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._is_color


    @property
    def is_debug(self) -> bool:
        '''
        :data:`True` only if debugging :mod:`beartype`.

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._is_debug

    # ..................{ PROPERTIES ~ options : bool : pep  }..................
    @property
    def is_pep484_tower(self) -> bool:
        '''
        :data:`True` only if enabling support for the :pep:`484`-compliant
        implicit numeric tower.

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._is_pep484_tower


    @property
    def is_pep557_fields(self) -> bool:
        '''
        :data:`True` only if type-checking **dataclass** (i.e., pure-Python
        classes decorated by the :pep:`557`-compliant
        :obj:`dataclasses.dataclass` decorator) **fields** (i.e., class
        attributes annotated by *any* type hints other than :pep:`526`-compliant
        ``dataclasses.ClassVar[...]`` or :pep:`557`-compliant
        ``dataclasses.InitVar[...]`` type hints) on both **dataclass object
        initialization** (i.e., at ``__init__()`` time) *and* **dataclass field
        assignment** (i.e., when each field is subsequently assigned to by an
        assignment statement).

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._is_pep557_fields

    # ..................{ PROPERTIES ~ options : claw        }..................
    @property
    def claw_decor_place_func(self) -> BeartypeDecorPlace:
        '''
        **Import hook callable decorator place** (i.e., relative position in
        existing chains of one or more decorators decorating user-defined
        functions and methods to which :mod:`beartype.claw` import hooks will
        automatically inject the :func:`beartype.beartype` decorator).

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._claw_decor_place_func


    @property
    def claw_decor_place_type(self) -> BeartypeDecorPlace:
        '''
        **Import hook class decorator place** (i.e., relative position in
        existing chains of one or more decorators decorating user-defined
        classes to which :mod:`beartype.claw` import hooks will automatically
        inject the :func:`beartype.beartype` decorator).

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._claw_decor_place_type


    @property
    def claw_is_pep526(self) -> bool:
        '''
        :data:`True` only if type-checking **annotated variable assignments**
        (i.e., :pep:`526`-compliant assignments to local, global, class, and
        instance variables annotated by type hints) when importing modules
        under import hooks published by the :mod:`beartype.claw` subpackage.

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._claw_is_pep526


    @property
    def claw_skip_package_names(self) -> CollectionStrs:
        '''
        Collection of the absolute names of all packages and modules to be
        **skipped** (i.e., blacklisted, excluded, ignored, omitted) rather than
        runtime type-checked by import hooks published by the
        :mod:`beartype.claw` subpackage -- especially the otherwise fragile
        :mod:`beartype.claw.beartype_all` import hook, which subjects *all*
        packages to runtime type-checking by default.

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._claw_skip_package_names

    # ..................{ PROPERTIES ~ options : violation   }..................
    @property
    def violation_door_type(self) -> TypeException:
        '''
        **DOOR violation type** (i.e., type of exception raised by the
        :func:`beartype.door.die_if_unbearable` type-checker when the object
        passed to that type-checker violates the type hint passed to that
        type-checker).

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._violation_door_type


    @property
    def violation_param_type(self) -> TypeException:
        '''
        **Parameter violation type** (i.e., type of exception raised by
        callables generated by the :func:`beartype.beartype` decorator when
        those callables receive parameters violating the type hints annotating
        those parameters).

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._violation_param_type


    @property
    def violation_return_type(self) -> TypeException:
        '''
        **Return violation type** (i.e., type of exception raised by callables
        generated by the :func:`beartype.beartype` decorator when those
        callables return values violating the type hints annotating those
        returns).

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._violation_return_type


    @property
    def violation_type(self) -> Optional[TypeException]:
        '''
        **Default violation type** (i.e., type of exception to default whichever
        of the ``violation_door_type``, ``violation_param_type``, and
        ``violation_return_type`` exception types are unpassed and thus
        :data:`None`).

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._violation_type


    @property
    def violation_verbosity(self) -> BeartypeViolationVerbosity:
        '''
        **Violation verbosity** (i.e., positive integer in the inclusive range
        ``[1, 5]`` governing the verbosity of exception messages raised by
        type-checking wrappers generated by the :func:`beartype.beartype`
        decorator when either receiving parameters *or* returning values
        violating their annotated type hints).

        See Also
        --------
        :meth:`__new__`
            Further details.
        '''

        return self._violation_verbosity

    # ..................{ DUNDERS                            }..................
    def __eq__(self, other: object) -> bool:
        '''
        **Beartype configuration equality comparator.**

        Parameters
        ----------
        other : object
            Arbitrary object to be compared for equality against this
            configuration.

        Returns
        -------
        Union[bool, type(NotImplemented)]
            Either:

            * If this other object is also a beartype configuration, either:

              * If these configurations share the same settings, :data:`True`.
              * Else, :data:`False`.

            * Else, :data:`NotImplemented`.

        See Also
        --------
        :func:`_hash_beartype_conf`
            Further details.
        '''

        # Return either...
        return (
            # If this other object is also a beartype configuration, true only
            # if these configurations share the same settings;
            self._conf_args == other._conf_args
            if isinstance(other, BeartypeConf) else
            # Else, this other object is *NOT* also a beartype configuration. In
            # this case, the standard singleton informing Python that this
            # equality comparator fails to support this comparison.
            NotImplemented  # type: ignore[return-value]
        )


    def __hash__(self) -> int:
        '''
        **Hash** (i.e., non-negative integer quasi-uniquely identifying this
        beartype configuration with respect to hashable container membership).

        Returns
        -------
        int
            Hash of this configuration.
        '''

        # Return the precomputed hash for this configuration.
        return self._hash


    def __repr__(self) -> str:
        '''
        **Beartype configuration representation** (i.e., machine-readable
        string which, when dynamically evaluated as code, restores access to
        this exact configuration object).

        Returns
        -------
        str
            Representation of this configuration.
        '''

        # If machine-readable representation of this configuration has yet to be
        # computed...
        if self._repr is None:
            # Avoid circular import dependencies.
            from beartype._conf.confcommon import BEARTYPE_CONF_DEFAULT

            # Initialize this representation to the unqualified basename of the
            # class of this configuration.
            conf_repr = f'{get_object_type_basename(self)}('

            # Dictionary mapping from the names to values of *ALL* possible
            # keyword parameters configuring the default beartype configuration.
            KWARGS_DEFAULT = BEARTYPE_CONF_DEFAULT._conf_kwargs

            # For the name and value of each keyword parameter with which this
            # configuration was instantiated...
            for kwarg_name, kwarg_value in self._conf_kwargs.items():
                # If this value differs from that of the default value for this
                # keyword parameter...
                if kwarg_value != KWARGS_DEFAULT[kwarg_name]:
                    # Append a comma-delimited representation of this keyword
                    # argument to this representation.
                    conf_repr += f'{kwarg_name}={kwarg_value}, '
                # Else, this value is the default value for this keyword
                # parameter. In this case, silently ignore this value. Appending
                # this value to this representation would convey *NO* meaningful
                # semantics and, indeed, only inhibit the readability of this
                # representation for end users and developers alike.

            # If this representation is suffixed by a whitespaced comma, remove
            # that suffix.
            if conf_repr[-2:] == ', ':
                conf_repr = conf_repr[:-2]
            # Else, this representation is *NOT* suffixed by a comma. In this
            # case, preserve this representation as is.

            # Preserve this representation for subsequent use.
            self._repr = f'{conf_repr})'
        # Else, the machine-readable representation of this configuration has
        # already been computed.

        # Return the machine-readable representation of this configuration.
        return self._repr

# ....................{ PRIVATE ~ globals                  }....................
_beartype_conf_lock = Lock()
'''
**Non-reentrant beartype configuration thread lock** (i.e., low-level thread
locking mechanism implemented as a highly efficient C extension, defined as an
global for non-reentrant reuse elsewhere as a context manager).
'''


_beartype_conf_args_to_conf: Dict[tuple, BeartypeConf] = {}
'''
Non-thread-safe **beartype configuration parameter cache** (i.e., dictionary
mapping from the hash of each set of parameters accepted by a prior call of the
:meth:`BeartypeConf.__new__` instantiator to the unique :class:`BeartypeConf`
instance instantiated by that call).

Caveats
-------
**This cache is non-thread-safe.** However, since this cache is only used as a
memoization optimization, the only harmful consequences of a race condition
between threads contending over this cache is a mildly inefficient (but
otherwise harmless) repeated re-memoization of duplicate configurations.
'''
