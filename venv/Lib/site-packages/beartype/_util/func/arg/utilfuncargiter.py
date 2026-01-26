#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **callable parameter iterator utilities** (i.e., low-level
callables introspectively iterating over parameters accepted by arbitrary
callables).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeUtilCallableException
from beartype.typing import (
    Iterable,
    Optional,
    Tuple,
)
from beartype._data.typing.datatyping import TypeException
from beartype._data.kind.datakindiota import Iota
from beartype._data.kind.datakindmap import FROZENDICT_EMPTY
from beartype._util.func.arg.utilfuncarglen import get_func_args_lens
from collections.abc import Callable
from enum import (
    Enum,
    auto as next_enum_member_value,
    unique as die_unless_enum_member_values_unique,
)
from itertools import count
from types import CodeType

# ....................{ ENUMERATIONS                       }....................
@die_unless_enum_member_values_unique
class ArgKind(Enum):
    '''
    Enumeration of all kinds of **callable parameters** (i.e., arguments passed
    to pure-Python callables).

    This enumeration intentionally declares members of the same name as those
    declared by the standard :class:`inspect.Parameter` class. Whereas the
    former are unconditionally declared below and thus portable across Python
    versions, the latter are only conditionally declared depending on Python
    version and thus non-portable across Python versions. Notably, the
    :attr:`inspect.Parameter.POSITIONAL_ONLY` attribute is only defined under
    Python >= 3.8.

    Attributes
    ----------
    POSITIONAL_ONLY : EnumMemberType
        Kind of all **positional-only parameters** (i.e., parameters required
        to be passed positionally, syntactically followed in the signatures of
        their callables by the :pep:`570`-compliant ``/,`` pseudo-parameter).
    POSITIONAL_OR_KEYWORD : EnumMemberType
        Kind of all **flexible parameters** (i.e., parameters permitted to be
        passed either positionally or by keyword).
    VARIADIC_POSITIONAL : EnumMemberType
        Kind of all **variadic positional parameters** (i.e., tuple of zero or
        more positional parameters *not* explicitly named by preceding
        positional-only or flexible parameters, syntactically preceded by the
        ``*`` prefix and typically named ``*args``).
    KEYWORD_ONLY  : EnumMemberType
        Kind of all **keyword-only parameters** (i.e., parameters required to
        be passed by keyword, syntactically preceded in the signatures of
        their callables by the :pep:`3102`-compliant ``*,`` pseudo-parameter).
    VARIADIC_KEYWORD : EnumMemberType
        Kind of all **variadic keyword parameters** (i.e., tuple of zero or
        more keyword parameters *not* explicitly named by preceding
        keyword-only or flexible parameters, syntactically preceded by the
        ``**`` prefix and typically named ``**kwargs``).
    '''

    POSITIONAL_ONLY = next_enum_member_value()
    POSITIONAL_OR_KEYWORD = next_enum_member_value()
    VARIADIC_POSITIONAL = next_enum_member_value()
    KEYWORD_ONLY = next_enum_member_value()
    VARIADIC_KEYWORD = next_enum_member_value()

# ....................{ SINGLETONS                         }....................
ArgMandatory = Iota()
'''
Arbitrary sentinel singleton assigned by the :func:`.iter_func_args` generator
to the tuple item with index :data:`.ARG_META_INDEX_DEFAULT` of all
:class:`.ArgMeta` instances, describing **mandatory parameters** (i.e.,
parameters that *must* be explicitly passed to their callables).
'''

# ....................{ HINTS                              }....................
ArgMeta = Tuple[ArgKind, str, object]
'''
PEP-compliant type hint matching each **callable parameter metadata**
iteratively yielded by the :func:`.iter_func_args` generator for each parameter
accepted by the pure-Python callable passed to that generator, defined as the
4-tuple ``(arg_kind, arg_name, arg_default_or_mandatory, arg_hint_or_unhinted)``
where:

* ``arg_kind`` is this parameter's **kind** (i.e., :class:`.ArgKind` enumeration
  member conveying the syntactic class of this parameter, constraining how the
  callable declaring this parameter requires this parameter to be passed).
* ``arg_name`` is this parameter's **name** (i.e., syntactically valid Python
  identifier uniquely identifying this parameter in its parameter list).
* ``arg_default_or_mandatory`` is either:

  * If this parameter is mandatory, the magic constant :data:`.ArgMandatory`.
  * Else, this parameter is optional and thus defaults to a default value when
    unpassed. In this case, this is that default value.

Caveats
-------
**This metadata intentionally omits the type hint annotating this parameter.**
Why? Because deciding *which* type hint annotates this parameter (if any) is
non-trivial in common edge cases. Notably, if the pure-Python callable passed to
that generator differs from the callable to be unwrapped with respect to type
hints, then that generator *cannot* reliably decide which type hint annotates
this parameter without refactoring both that generator and all other callables
transitively calling that generator to also accept and forward on a new
``type_hint_wrapper`` parameter providing the callable to be unwrapped with
respect to type hints. Although feasible, doing so would only invite even
further API confusion with little to no tangible benefit. Edge cases in which
this arises include:

* When ``type_hint_wrapper`` is a **pseudo-callable** (i.e., otherwise
  uncallable object whose type renders that object callable by defining the
  ``__call__()`` dunder method) *and* ``func`` is that ``__call__()`` dunder
  method. If that pseudo-callable wraps a lower-level callable, then that
  pseudo-callable (rather than ``__call__()`` dunder method) defines the
  ``__wrapped__`` instance variable providing that callable.

The caller is thus responsible for mapping parameters to type hints. Thankfully,
the existing
:attr:`beartype._check.meta.checkdecor.BeartypeDecorMeta.func_annotations`
dictionary makes this trivial for most use cases.
'''

# ....................{ CONSTANTS ~ index                  }....................
# Iterator yielding the next integer incrementation starting at 0, to be safely
# deleted *AFTER* defining the following 0-based indices via this iterator.
__arg_meta_index_counter = count(start=0, step=1)


ARG_META_INDEX_KIND = next(__arg_meta_index_counter)
'''
0-based index into each 4-tuple iteratively yielded by the generator returned by
the :func:`.iter_func_args` generator function providing the currently iterated
parameter's **kind** (i.e., :class:`ArgKind` enumeration member conveying this
parameter's syntactic class, constraining how the callable declaring this
parameter requires this parameter to be passed).
'''


ARG_META_INDEX_NAME = next(__arg_meta_index_counter)
'''
0-based index into each 4-tuple iteratively yielded by the generator returned by
the :func:`.iter_func_args` generator function providing the currently iterated
parameter's **name** (i.e., syntactically valid Python identifier uniquely
identifying this parameter in its parameter list).
'''


ARG_META_INDEX_DEFAULT = next(__arg_meta_index_counter)
'''
0-based index into each 4-tuple iteratively yielded by the generator returned by
the :func:`.iter_func_args` generator function providing the currently iterated
parameter's **default value**, defined as either:

* If this parameter is mandatory, the magic constant :data:`.ArgMandatory`.
* Else, this parameter is optional and thus defaults to a default value when
  unpassed. In this case, this is that default value.
'''


# Delete the above counter for safety and sanity in equal measure.
del __arg_meta_index_counter

# ....................{ GENERATORS                         }....................
def iter_func_args(
    # Mandatory parameters.
    func: Callable,

    # Optional parameters.
    func_codeobj: Optional[CodeType] = None,
    is_omit_boundmethod_arg_first: bool = True,
    is_unwrap: bool = True,
    exception_cls: TypeException = _BeartypeUtilCallableException,
    exception_prefix: str = '',
# Note this generator is intentionally annotated as returning a high-level
# "Iterable[...]" rather than a low-level "Generator[..., ..., ...]", as the
# syntax governing the latter is overly verbose and largely unhelpful.
) -> Iterable[ArgMeta]:
    '''
    Generator yielding one **parameter metadata tuple** (i.e., tuple whose items
    describe a single parameter) for each parameter accepted by the passed
    pure-Python callable.

    For consistency with the official grammar for callable signatures
    standardized by :pep:`570`, this generator is guaranteed to yield parameter
    metadata in the same order as required by Python syntax and semantics. In
    order, this is:

    * **Mandatory positional-only parameters** (i.e., parameter metadata
      whose kind is :attr:`ArgKind.POSITIONAL_ONLY` and whose default value is
      :data:`ArgMandatory`).
    * **Optional positional-only parameters** (i.e., parameter metadata
      whose kind is :attr:`ArgKind.POSITIONAL_ONLY` and whose default value is
      *not* :data:`ArgMandatory`).
    * **Mandatory flexible parameters** (i.e., parameter metadata whose kind is
      :attr:`ArgKind.POSITIONAL_OR_KEYWORD` and whose default value is
      :data:`ArgMandatory`).
    * **Optional flexible parameters** (i.e., parameter metadata whose kind is
      :attr:`ArgKind.POSITIONAL_OR_KEYWORD` and whose default value is *not*
      :data:`ArgMandatory`).
    * **Variadic positional parameters** (i.e., parameter metadata whose kind
      is :attr:`ArgKind.VARIADIC_POSITIONAL` and whose default value is
      :data:`ArgMandatory`).
    * **Mandatory and optional keyword-only parameters** (i.e., parameter
      metadata whose kind is :attr:`ArgKind.KEYWORD_ONLY`). Unlike all other
      parameter kinds, keyword-only parameters are (by definition) unordered;
      ergo, Python explicitly permits mandatory and optional keyword-only
      parameters to be heterogeneously intermingled rather than clustered.
    * **Variadic keyword parameters** (i.e., parameter metadata whose kind
      is :attr:`ArgKind.VARIADIC_KEYWORD` and whose default value is
      :data:`ArgMandatory`).

    Caveats
    -------
    **This highly optimized generator function should always be called in lieu
    of the highly unoptimized** :func:`inspect.signature` **function,** which
    implements a similar introspection as this generator with significantly
    worse space and time consumption. Seriously. *Never* call that anywhere.

    Parameters
    ----------
    func : Callable
        Pure-Python callable to be inspected.
    func_codeobj: CodeType, optional
        Code object underlying that callable unwrapped. Defaults to
        :data:`None`, in which case this iterator internally defers to the
        comparatively slower :func:`.get_func_codeobj` function.
    is_omit_boundmethod_arg_first : bool, optional
        :data:`True` only if this generator implicitly omits the first mandatory
        flexible parameter accepted by that callable if that callable is a
        C-based bound method descriptor encapsulating either an instance method
        bound to an instance of a class *or* a class method bound to a class.
        Defaults to :data:`True`, instructing this generator to transparently
        yield the *actual* high-level parameters accepted by this bound method
        descriptor (rather than the low-level parameters accepted by the unbound
        method encapsulated by this bound method descriptor). While the default
        behaviour is typically desirable, valid use cases for the non-default
        behaviour do exist (e.g., crudely detecting the kind of that based on
        whether the unbound method encapsulated by this bound method descriptor
        accepts a first parameter named ``cls`` or ``self``).

        The default behaviour enables:

        * This generator to transparently support bound method descriptors,
          which then enables...
        * The private :func:`beartype._decor._nontype.decornontype.beartype_pseudofunc`
          decorator to type-check the bound ``__call__()`` method descriptor
          encapsulating the unbound ``__call__()`` dunder method defined on the
          class of pseudo-callable objects, which then enables...
        * The public :func:`beartype.beartype` decorator to type-check
          pseudo-callable objects.

        How? In this case, the aforementioned ``beartype_pseudofunc``
        decorator wraps this bound method descriptor with a dynamically
        generated wrapper function that does *not* accept a ``self`` or ``cls``
        parameter, since a bound method does *not* accept a ``self`` or ``cls``
        parameter. After all, that's why bound methods exist; they implicitly
        pass the instance or class to which they are bound as the value of the
        ``self`` or ``cls`` parameter to the unbound method they encapsulate.
        However, the code object of a bound method descriptor is only an alias
        to the code object of the corresponding unbound method. Since the latter
        accepts a ``self`` parameter, so too does the former.

        The default behaviour resolves this internal discrepancy (contradiction)
        that arises between:

        * The code object of a bound method descriptor, which declares that
          callable object to accept a ``self`` parameter.
        * The real-world calling semantics of a bound method descriptor, which
          by definition accepts *no* ``self`` parameter.
    is_unwrap : bool, optional
        :data:`True` only if this generator implicitly calls the
        :func:`unwrap_func_all_isomorphic` function to unwrap this possibly
        higher-level wrapper into its possibly lowest-level wrappee *before*
        returning the code object of that wrappee. Note that doing so incurs
        worst-case time complexity ``O(n)`` for ``n`` the number of lower-level
        wrappees wrapped by this wrapper. Defaults to :data:`True` for
        robustness. Why? Because this generator *must* always introspect
        lowest-level wrappees rather than higher-level wrappers. The latter
        typically do *not* wrap the default values of the former, since this is
        the default behaviour of the :func:`functools.update_wrapper` function
        underlying the :func:`functools.wrap` decorator underlying all sane
        decorators. If this boolean is set to :data:`False` while that callable
        is actually a wrapper, this generator will erroneously misidentify
        optional as mandatory parameters and fail to yield their default values.
        Only set this boolean to :data:`False` if you pretend to know what
        you're doing.
    exception_cls : type, optional
        Type of exception to be raised in the event of a fatal error. Defaults
        to :class:`._BeartypeUtilCallableException`.
    exception_prefix : str, optional
        Human-readable label prefixing the message of any exception raised in
        the event of a fatal error. Defaults to the empty string.

    Yields
    ------
    ArgMeta
        Parameter metadata tuple describing the currently yielded parameter.

    Raises
    ------
    exception_cls
         If that callable is *not* pure-Python.
    '''
    assert isinstance(is_omit_boundmethod_arg_first, bool), (
        f'{repr(is_omit_boundmethod_arg_first)} not boolean.')
    assert isinstance(is_unwrap, bool), f'{repr(is_unwrap)} not boolean.'

    # ..................{ IMPORTS                            }..................
    # Avoid circular import dependencies.
    from beartype._util.func.utilfunccodeobj import get_func_codeobj
    from beartype._util.func.utilfunctest import is_func_boundmethod
    from beartype._util.func.utilfuncwrap import unwrap_func_all_isomorphic

    # ..................{ LOCALS ~ core                      }..................
    # If unwrapping that callable, do so *BEFORE* obtaining the code object of
    # that callable for safety (to avoid desynchronization between the two).
    if is_unwrap:
        func = unwrap_func_all_isomorphic(func)
    # Else, that callable is assumed to have already been unwrapped by the
    # caller. We should probably assert that, but doing so requires an
    # expensive call to hasattr(). What you gonna do?

    # Number of various kinds of parameters accepted by that callable.
    (
        # Number of both optional and mandatory non-keyword-only parameters
        # (i.e., positional-only *AND* flexible (i.e., positional or keyword)
        # parameters) accepted by that callable.
        args_len_posonly_or_flex,
        # Number of both optional and mandatory keyword-only parameters accepted
        # by that callable.
        args_len_kwonly,
        # 1 only if that callable accepts variadic positional or keyword
        # parameters and 0 otherwise.
        is_arg_var_pos,
        is_arg_var_kw,
    ) = get_func_args_lens(
        func=func,
        is_unwrap=False,  # <-- "func" was already unwrapped above. I sigh.
        exception_cls=exception_cls,
        exception_prefix=exception_prefix,
    )

    # If that callable accepts *NO* parameters, silently reduce to the empty
    # generator (i.e., noop) for both space and time efficiency. Just. Do. It.
    #
    # Note that this is a critical optimization for the common use case that
    # @beartype is unconditionally applied with "beartype.claw"-based import
    # hook automation to *ALL* callables physically declared by a package, many
    # of which will inevitably be argumentless.
    if (
        args_len_posonly_or_flex +
        args_len_kwonly +
        is_arg_var_pos +
        is_arg_var_kw
    ) == 0:
        yield from ()
        return
    # Else, that callable accepts one or more parameters.

    # If passed *NO* code object, query that callable for its code object.
    if func_codeobj is None:
        func_codeobj = get_func_codeobj(
            func=func,
            is_unwrap=False,  # <-- "func" was already unwrapped above. I sigh.
            exception_cls=exception_cls,
            exception_prefix=exception_prefix,
        )
    # In any case, that code object is now defined.

    # Tuple of the names of all variables localized to that callable.
    #
    # Note that this tuple contains the names of both:
    # * All parameters accepted by that callable.
    # * All local variables internally declared in that callable's body.
    #
    # Ergo, this tuple *CANNOT* be searched in full. Only the subset of this
    # tuple containing argument names is relevant and may be safely searched.
    #
    # Lastly, note the "func_codeobj.co_names" attribute is incorrectly
    # documented in the "inspect" module as the "tuple of names of local
    # variables." That's a lie. Instead, that attribute is a mostly useless
    # tuple of the names of both globals and object attributes accessed in the
    # body of that callable. *shrug*
    args_name = func_codeobj.co_varnames

    # ..................{ LOCALS ~ defaults                  }..................
    # Tuple of the default values assigned to all optional non-keyword-only
    # parameters (i.e., all optional positional-only *AND* optional flexible
    # (i.e., positional or keyword) parameters) accepted by that callable if any
    # *OR* the empty tuple otherwise.
    args_defaults_posonly_or_flex = func.__defaults__ or ()  # type: ignore[attr-defined]
    # print(f'args_defaults_posonly_or_flex: {args_defaults_posonly_or_flex}')

    # Dictionary mapping from the name of each optional keyword-only parameter
    # accepted by that callable to the default value assigned to that parameter
    # if any *OR* the empty dictionary otherwise.
    #
    # For both space and time efficiency, the empty dictionary is intentionally
    # *NOT* accessed here as "{}". Whereas each instantiation of the empty tuple
    # efficiently reduces to the same empty tuple, each instantiation of the
    # empty dictionary inefficiently creates a new empty dictionary: e.g.,
    #     >>> () is ()
    #     True
    #     >>> {} is {}
    #     False
    args_defaults_kwonly = func.__kwdefaults__ or FROZENDICT_EMPTY  # type: ignore[attr-defined]

    # ..................{ LOCALS ~ len                       }..................
    # Number of both optional and mandatory positional-only parameters accepted
    # by that callable, standardized under Python >= 3.8 by PEP 570.
    args_len_posonly = func_codeobj.co_posonlyargcount  # type: ignore[attr-defined]
    assert args_len_posonly_or_flex >= args_len_posonly, (
        f'Positional-only and flexible argument count {args_len_posonly_or_flex} < '
        f'positional-only argument count {args_len_posonly}.')

    # Number of both optional and mandatory flexible parameters accepted by
    # that callable.
    args_len_flex = args_len_posonly_or_flex - args_len_posonly

    # Number of optional non-keyword-only parameters accepted by that callable.
    args_len_posonly_or_flex_optional = len(args_defaults_posonly_or_flex)

    # Number of optional flexible parameters accepted by that callable, defined
    # as the number of optional non-keyword-only parameters capped to the total
    # number of flexible parameters. Why? Because optional flexible parameters
    # preferentially consume non-keyword-only default values first; optional
    # positional-only parameters consume all remaining non-keyword-only default
    # values. Why? Because:
    # * Default values are *ALWAYS* assigned to positional parameters from
    #   right-to-left.
    # * Flexible parameters reside to the right of positional-only parameters.
    #
    # Specifically, this number is defined as...
    args_len_flex_optional = min(
        # If the number of optional non-keyword-only parameters exceeds the
        # total number of flexible parameters, the total number of flexible
        # parameters. For obvious reasons, the number of optional flexible
        # parameters *CANNOT* exceed the total number of flexible parameters;
        args_len_flex,
        # Else, the total number of flexible parameters is strictly greater
        # than the number of optional non-keyword-only parameters, implying
        # optional flexible parameters consume all non-keyword-only default
        # values. In this case, the number of optional flexible parameters is
        # the number of optional non-keyword-only parameters.
        args_len_posonly_or_flex_optional,
    )

    # Number of optional positional-only parameters accepted by that callable,
    # defined as all remaining optional non-keyword-only parameters *NOT*
    # already consumed by positional parameters. Note that this number is
    # guaranteed to be non-negative. Why? Because, it is the case that either:
    # * "args_len_posonly_or_flex_optional >= args_len_flex", in which case
    #   "args_len_flex_optional == args_len_flex", in which case
    #   "args_len_posonly_or_flex_optional >= args_len_flex_optional".
    # * "args_len_posonly_or_flex_optional < args_len_flex", in which case
    #   "args_len_flex_optional == args_len_posonly_or_flex_optional", in which
    #   case "args_len_posonly_or_flex_optional == args_len_flex_optional".
    #
    # Just roll with it, folks. It's best not to question the unfathomable.
    args_len_posonly_optional = (
        args_len_posonly_or_flex_optional - args_len_flex_optional)

    # Number of mandatory positional-only parameters accepted by that callable.
    args_len_posonly_mandatory = args_len_posonly - args_len_posonly_optional

    # Number of mandatory flexible parameters accepted by that callable.
    args_len_flex_mandatory = args_len_flex - args_len_flex_optional

    # ..................{ ITERATE ~ positional-only          }..................
    # 0-based index of the first parameter of the currently iterated kind
    # accepted by that callable in the "args_name" tuple.
    args_index_kind_first = 0

    # If that callable accepts at least one mandatory positional-only
    # parameter...
    if args_len_posonly_mandatory:
        # For each mandatory positional-only parameter accepted by that
        # callable, yield a tuple describing this parameter.
        for arg_name in args_name[
            args_index_kind_first:args_len_posonly_mandatory]:
            yield (ArgKind.POSITIONAL_ONLY, arg_name, ArgMandatory,)

        # 0-based index of the first parameter of the next iterated kind.
        args_index_kind_first = args_len_posonly_mandatory
    # Else, that callable accepts *NO* mandatory positional-only parameters.

    # If that callable accepts at least one optional positional-only
    # parameter...
    if args_len_posonly_optional:
        # 0-based index of the parameter following the last optional
        # positional-only parameter in the "args_name" tuple.
        args_index_kind_last_after = (
            args_index_kind_first + args_len_posonly_optional)

        # For the 0-based index of each optional positional-only parameter
        # accepted by that callable and that parameter, yield a tuple
        # describing this parameter.
        for arg_index, arg_name in enumerate(args_name[
            args_index_kind_first:args_index_kind_last_after]):
            # assert arg_posonly_optional_index < args_len_posonly_optional, (
            #     f'Optional positional-only parameter index {arg_posonly_optional_index} >= '
            #     f'optional positional-only parameter count {args_len_posonly_optional}.')
            yield (
                ArgKind.POSITIONAL_ONLY,
                arg_name,
                args_defaults_posonly_or_flex[arg_index],
            )

        # 0-based index of the first parameter of the next iterated kind.
        args_index_kind_first = args_index_kind_last_after
    # Else, that callable accepts *NO* optional positional-only parameters.

    # ..................{ ITERATE ~ flexible                 }..................
    # If that callable accepts at least one mandatory flexible parameter...
    if args_len_flex_mandatory:
        # 0-based index of the parameter following the last mandatory flexible
        # parameter in the "args_name" tuple.
        args_index_kind_last_after = (
            args_index_kind_first + args_len_flex_mandatory)

        # If...
        if (
            # Omitting the first mandatory flexible parameter accepted by that
            # callable if that callable is a C-based bound method descriptor
            # encapsulating either an instance method bound to an instance of a
            # class or a class method bound to a class *AND*...
            is_omit_boundmethod_arg_first and
            # That callable is such a C-based bound method descriptor...
            is_func_boundmethod(func)
        ):
            # print(f'Ignoring bound method {repr(func)} first argument...')
            # Increment the 0-based index of the first mandatory flexible
            # parameter accepted by this method in the "args_name" tuple to
            # account for the first mandatory flexible "self" parameter
            # implicitly passed by this bound method descriptor to this method,
            # effectively ignoring this "self" parameter.
            #
            # Note that:
            # * We intentionally increment this index *AFTER* computing the
            #   derivative "args_index_kind_last_after" index above with the
            #   original value of this index.
            # * Handling this common edge case enables:
            #   * This generator to transparently support bound method
            #     descriptors, which then enables...
            #   * The private @beartype._decor._nontype.decornontype.beartype_pseudofunc
            #     decorator to type-check the bound __call__() method descriptor
            #     encapsulating the unbound __call__() dunder method defined on
            #     the class of pseudo-callable objects, which then enables...
            #   * The public @beartype.beartype decorator to type-check
            #     pseudo-callable objects.
            #
            #   How? In this case, the aforementioned @beartype_pseudofunc
            #   decorator wraps this bound method descriptor with a dynamically
            #   generated wrapper function that does *NOT* accept a "self"
            #   parameter, since a bound method does *NOT* accept a "self"
            #   parameter. However, the code object of a bound method descriptor
            #   is simply an alias of the code object of the corresponding
            #   unbound method. Since the latter accepts a "self" parameter, so
            #   too does the former. Thus, an internal discrepancy (arguably,
            #   contradiction) arises between:
            #
            #   * The code object of a bound method descriptor, which declares
            #     that callable object to accept a "self" parameter.
            #   * The real-world calling semantics of a bound method descriptor,
            #     which by definition accepts *NO* "self" parameter.
            args_index_kind_first += 1
        # Else, that callable is *NOT* such a descriptor (and is thus almost
        # certainly a vanilla pure-Python callable).

        # For each mandatory flexible parameter accepted by that callable, yield
        # a tuple describing this parameter.
        for arg_name in args_name[
            args_index_kind_first:args_index_kind_last_after]:
            yield (ArgKind.POSITIONAL_OR_KEYWORD, arg_name, ArgMandatory,)

        # 0-based index of the first parameter of the next iterated kind.
        args_index_kind_first = args_index_kind_last_after
    # Else, that callable accepts *NO* mandatory flexible parameters.

    # If that callable accepts at least one optional flexible parameter...
    if args_len_flex_optional:
        # 0-based index of the parameter following the last optional
        # flexible parameter in the "args_name" tuple.
        args_index_kind_last_after = (
            args_index_kind_first + args_len_flex_optional)

        # For the 0-based index of each optional flexible parameter accepted by
        # this callable and that parameter, yield a 3-tuple describing this
        # parameter.
        for arg_index, arg_name in enumerate(args_name[
            args_index_kind_first:args_index_kind_last_after]):
            # assert arg_flex_optional_index < args_len_flex_optional, (
            #     f'Optional flexible parameter index {arg_flex_optional_index} >= '
            #     f'optional flexible parameter count {args_len_flex_optional}.')
            yield (
                ArgKind.POSITIONAL_OR_KEYWORD,
                arg_name,
                args_defaults_posonly_or_flex[
                    args_len_posonly_optional + arg_index],
            )

        # 0-based index of the first parameter of the next iterated kind.
        args_index_kind_first = args_index_kind_last_after
    # Else, that callable accepts *NO* optional flexible parameters.

    # ..................{ ITERATE ~ variadic positional      }..................
    # 0-based index of the parameter following the last keyword-only
    # parameter in the "args_name" tuple. This index is required by multiple
    # branches below (rather than merely one branch) and thus unconditionally
    # computed for all these branches.
    args_index_kind_last_after = args_index_kind_first + args_len_kwonly

    # If that callable accepts a variadic positional parameter, yield a tuple
    # describing this parameter.
    #
    # Note that:
    # * This parameter is intentionally yielded *BEFORE* keyword-only
    #   parameters to conform with syntactic standards. A variadic positional
    #   parameter necessarily appears before any keyword-only parameters in the
    #   signature of that callable.
    # * The 0-based index of this parameter in the "args_name" tuple is exactly
    #   one *AFTER* the last keyword-only parameter in that tuple if any and
    #   one *BEFORE* the variadic keyword parameter in that tuple if any. This
    #   idiosyncrasy is entirely the fault of CPython, which grouped the
    #   two variadic positional and keyword parameters at the end of this list
    #   despite syntactic constraints on their lexical position.
    if is_arg_var_pos:
        yield (
            ArgKind.VARIADIC_POSITIONAL,
            args_name[args_index_kind_last_after],
            ArgMandatory,
        )
    # Else, that callable accepts *NO* variadic positional parameter.

    # ..................{ ITERATE ~ keyword-only             }..................
    # If that callable accepts at least one keyword-only parameter...
    if args_len_kwonly:
        # dict.get() method repeatedly called below and thus localized for
        # negligible efficiency. Look. Just do this. We needs godspeed.
        args_defaults_kwonly_get = args_defaults_kwonly.get

        # For each keyword-only parameter accepted by that callable, yield a
        # tuple describing this parameter.
        for arg_name in args_name[
            args_index_kind_first:args_index_kind_last_after]:
            yield (
                ArgKind.KEYWORD_ONLY,
                arg_name,
                # Either:
                # * If this is an optional keyword-only parameter, the default
                #   value of this parameter.
                # * If this is a mandatory keyword-only parameter, the
                #   placeholder "ArgMandatory" singleton.
                args_defaults_kwonly_get(arg_name, ArgMandatory),
            )
    # Else, that callable accepts *NO* keyword-only parameters.

    # ..................{ ITERATE ~ variadic keyword         }..................
    # If that callable accepts a variadic keyword parameter...
    if is_arg_var_kw:
        # 0-based index of the variadic keyword parameter accepted by that
        # callable in the "args_name" tuple, optimized by noting that Python
        # booleans are literally integers that can be computed with. Notably:
        # * If that callable accepts *NO* variadic positional parameter, then:
        #       is_arg_var_pos == 0
        #       args_index_var_kw == args_index_var_pos
        # * If that callable accepts a variadic positional parameter, then:
        #       is_arg_var_kw == 1
        #       args_index_var_pos == args_index_var_pos + 1
        args_index_kind_last_after += is_arg_var_pos

        # Yield a tuple describing this parameter.
        yield (
            ArgKind.VARIADIC_KEYWORD,
            args_name[args_index_kind_last_after],
            ArgMandatory,
        )
    # Else, that callable accepts *NO* variadic keyword parameter.
