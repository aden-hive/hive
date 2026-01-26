#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype type-checking error cause sleuth** (i.e., object recursively
fabricating the human-readable string describing the failure of the pith
associated with this object to satisfy this PEP-compliant type hint also
associated with this object) classes.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: The following "ViolationCause" instance variables are trivial aliases
#and thus useless. They should be excised where time permits; so, never:
#* "ViolationCause.hint" is just an alias for "ViolationCause.hint_sane.hint".
#* The "ViolationCause.hint_childs" tuple is only used in one other submodule
#  and can, in any case, be trivially reconstructed from the more useful
#  "ViolationCause.hint_childs_sane" tuple. In other words, please excise
#  "ViolationCause.hint_childs".

#FIXME: The recursive "ViolationCause" class strongly overlaps with the equally
#recursive (and substantially superior) "beartype.door.TypeHint" class. Ideally:
#* Define a new private "beartype.door._doorerror" submodule.
#* Shift the "ViolationCause" class to
#  "beartype.door._doorerror._TypeHintUnbearability".
#* Shift the _TypeHintUnbearability.find_cause() method to a new
#  *PRIVATE* TypeHint._find_cause() method.
#* Preserve most of the remainder of the "_TypeHintUnbearability" class as a
#  dataclass encapsulating metadata describing the current type-checking
#  violation. That metadata (e.g., "cause_indent") is inappropriate for
#  general-purpose type hints. Exceptions include:
#  * "hint", "hint_sign", and "hint_childs_sane" -- all of which are subsumed
#    by the "TypeHint" dataclass and should thus be excised.
#* Refactor the TypeHint._find_cause() method to accept an instance of
#  the "_TypeHintUnbearability" dataclass: e.g.,
#      class TypeHint(...):
#          def _get_unbearability_cause_or_none(
#              self, unbearability: _TypeHintUnbearability) -> Optional[str]:
#              ...
#* Refactor existing find_cause_*() getters (e.g.,
#  find_cause_sequence_args_1(), find_cause_pep484604_union()) into
#  _get_unbearability_cause_or_none() methods of the corresponding "TypeHint"
#  subclasses, please.
#
#This all seems quite reasonable. Now, let's see whether it is. *gulp*
#FIXME: Actually, the above comment now ties directly into feature request #235.
#Resolving the above comment mostly suffices to resolve #235. That said, the
#above isn't *QUITE* right. It's pretty nice -- but we can do better. See the
#following comment at #235 for that better:
#    https://github.com/beartype/beartype/issues/235#issuecomment-1707127231

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeCallHintPepRaiseException
from beartype.typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Optional,
)
from beartype._cave._cavemap import NoneTypeOr
from beartype._check.convert.convmain import sanify_hint_child
from beartype._check.metadata.hint.hintsane import (
    HINT_SANE_IGNORABLE,
    HintSane,
    TupleHintSane,
)
from beartype._conf.confmain import BeartypeConf
from beartype._data.typing.datatypingport import (
    Hint,
    TupleHints,
)
from beartype._data.typing.datatyping import (
    HintSignOrNoneOrSentinel,
    TypeStack,
)
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.hint.sign.datahintsignset import (
    HINT_SIGNS_SUPPORTED_DEEP,
    HINT_SIGNS_ORIGIN_ISINSTANCEABLE,
)
from beartype._data.kind.datakindiota import SENTINEL
from beartype._util.hint.pep.utilpepget import get_hint_pep_args
from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none
from beartype._util.hint.pep.utilpeptest import is_hint_pep
from beartype._util.utilobjmake import permute_object

# ....................{ CLASSES                            }....................
class ViolationCause(object):
    '''
    **Type-checking violation cause finder** (i.e., object recursively
    fabricating the human-readable string describing the failure of the pith
    associated with this finder to satisfy this PEP-compliant type hint also
    associated with this finder).

    Attributes
    ----------
    cause_indent : str
        **Indentation** (i.e., string of zero or more spaces) preceding each
        line of the string returned by this getter if this string spans
        multiple lines *or* ignored otherwise (i.e., if this string is instead
        embedded in the current line).
    cause_str_or_none : Optional[str]
        If this pith either:

        * Violates this hint, a human-readable string describing this violation.
        * Satisfies this hint, :data:`None`.
    cls_stack : TypeStack, optional
        **Type stack** (i.e., either a tuple of the one or more
        :func:`beartype.beartype`-decorated classes lexically containing the
        class variable or method annotated by this hint *or* :data:`None`).
    conf : BeartypeConf
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all flags, options, settings, and other metadata configuring the
        current decoration of the decorated callable or class).
    exception_prefix : str
        Human-readable label describing the parameter or return value from
        which this object originates, typically embedded in exceptions raised
        from this getter in the event of unexpected runtime failure.
    func : Optional[Callable]
        Either:

        * If this violation originates from a decorated callable, that
          callable.
        * Else, :data:`None`.
    hint : Hint
        Type hint to validate this object against.
    hint_childs : Optional[TupleHints]
        Either:

        * If this hint is PEP-compliant, the possibly empty tuple of all child
          hints subscripting (indexing) this hint.
        * Else, :data:`None`.

        This instance variable is effectively a streamlined variant of the
        :attr:`hint_childs_sane` instance variable. Whereas the latter
        *includes* all supplementary metadata, the former instance variable
        *excludes* all supplementary metadata and thus only contains hints.
    hint_childs_sane : Optional[TupleHintSane]
        Either:

        * If this hint is PEP-compliant, the possibly empty tuple of all child
          hints subscripting (indexing) this hint such that each item is either:

          * If sanifying this child hint generated supplementary metadata, that
            metadata (i.e., a :class:`.HintSane` object).
          * Else, this child hint as is.

        * Else, :data:`None`.
    hint_sane : HintSane
        Metadata encapsulating the sanification (i.e., sanitization) of the type
        hint to validate this object against.
    hint_sign : Optional[HintSign]
        Either:

        * If this hint is PEP-compliant, the sign identifying this hint.
        * Else, :data:`None`.
    pith : Any
        Arbitrary object to be validated.
    pith_name : Optional[str]
        Either:

        * If this hint directly annotates a callable parameter (as the root type
          hint of that parameter), the name of this parameter.
        * If this hint directly annotates a callable return (as the root type
          hint of that return), the magic string ``"return"``.
        * Else, :data:`None`.
    random_int : Optional[int]
        **Pseudo-random integer** (i.e., unsigned 32-bit integer
        pseudo-randomly generated by the parent :func:`beartype.beartype`
        wrapper function in type-checking randomly indexed container items by
        the current call to that function) if that function generated such an
        integer *or* ``None`` otherwise (i.e., if that function generated *no*
        such integer). See the same parameter accepted by the higher-level
        :func:`beartype._check.error.errmain.get_func_pith_violation` function.
    '''

    # ..................{ CLASS VARIABLES                    }..................
    # Slot *ALL* instance variables defined on this object to both:
    # * Prevent accidental declaration of erroneous instance variables.
    # * Minimize space and time complexity.
    __slots__ = (
        'cause_indent',
        'cause_str_or_none',
        'cls_stack',
        'conf',
        'exception_prefix',
        'func',
        'hint',
        'hint_childs',
        'hint_childs_sane',
        'hint_sane',
        'hint_sign',
        'pith',
        'pith_name',
        'random_int',
    )


    # Squelch false negatives from mypy. This is absurd. This is mypy. See:
    #     https://github.com/python/mypy/issues/5941
    if TYPE_CHECKING:
        cause_indent: str
        cause_str_or_none: Optional[str]
        cls_stack: TypeStack
        conf: BeartypeConf
        exception_prefix: str
        func: Optional[Callable]
        hint: Hint
        hint_childs: TupleHints
        hint_childs_sane: TupleHintSane
        hint_sane: HintSane
        hint_sign: Optional[HintSign]
        pith: Any
        pith_name: Optional[str]
        random_int: Optional[int]

    # ..................{ CLASS VARIABLES ~ set              }..................
    _COPY_VAR_NAMES = frozenset((
        'cause_indent',
        'cls_stack',
        'conf',
        'exception_prefix',
        'func',
        'hint_sane',
        'pith',
        'pith_name',
        'random_int',
        'cause_str_or_none',
    ))
    '''
    Frozen set of the names of *all* instance variables whose values will be
    copied as the default values of all **unpassed parameters** (i.e.,
    parameters *not* explicitly passed to the :meth:`permute_cause` method),
    defined as a set to enable efficient membership testing.

    Note that the :attr:`hint_sign` instance variable is intentionally omitted.
    This variable's value is unique to the current cause and thus *not* safely
    copyable from parent to child hints by the :meth:`permute_cause` method.
    '''


    _INIT_ARG_NAMES = _COPY_VAR_NAMES | frozenset(('hint_sign',))
    '''
    Frozen set of the names of *all* parameters accepted by the :meth:`init`
    method, defined as a set to enable efficient membership testing.
    '''

    # ..................{ INITIALIZERS                       }..................
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Whenever adding, deleting, or renaming any parameter accepted by
    # this method, make similar changes to the "_INIT_ARG_NAMES" set above.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    def __init__(
        self,

        # Mandatory parameters.
        hint_sane: HintSane,
        cause_indent: str,
        cls_stack: TypeStack,
        conf: BeartypeConf,
        exception_prefix: str,
        func: Optional[Callable],
        pith: Any,
        pith_name: Optional[str],
        random_int: Optional[int],

        # Optional parameters.
        cause_str_or_none: Optional[str] = None,
        hint_sign: HintSignOrNoneOrSentinel = SENTINEL,
    ) -> None:
        '''
        Initialize this violation cause.

        Parameters
        ----------
        hint_sign : Union[Optional[HintSign], Iota], default: SENTINEL
            Either:

            * If this child hint is uniquely identified by a **non-default
              sign** (i.e., a singleton instance of the :class:`.HintSign` class
              *other* than the standard sign returned by the
              :func:`.get_hint_pep_sign_or_none` getter), this sign.
            * Else, the sentinel placeholder, in which case this parameter
              defaults to the **default sign** (i.e., the standard sign returned
              by the :func:`.get_hint_pep_sign_or_none` getter).

            Defaults to the sentinel placeholder. This parameter should
            typically *not* be passed. Almost all hints are uniquely identified
            by the default sign. A small subset of hints, however, concurrently
            satisfy the detection criteria for multiple signs and are thus
            identifiable with multiple signs. This parameter supports those
            hints by enabling callers to call this method multiple times with
            the same hint passed different signs.

            Prominent examples include:

            * :pep:`484`- and :pep:`585`-compliant unsubscripted generics --
              which, due to being user-defined types, may subclass another
              PEP-compliant :mod:`typing` superclass also identifiable by
              another sign. Prominent examples include:

              * **Generic typed dictionaries** identifiable as both the
                :data:`.HintSignPep484585GenericUnsubbed` sign *and* the
                :data:`HintSignTypedDict` sign for :pep:`589`-compliant typed
                dictionaries: e.g.,

                .. code-block:: python

                   from typing import Generic, TypedDict
                   class GenericTypedDict[T](TypedDict, Generic[T]):
                       generic_item: T

              * **Generic named tuples** identifiable as both the
                :data:`.HintSignPep484585GenericUnsubbed` sign *and* the
                :data:`HintSignNamedTuple` sign for :pep:`484`-compliant named
                tuples: e.g.,

                .. code-block:: python

                   from typing import Generic, NamedTuple
                   class GenericNamedTuple[T](NamedTuple, Generic[T]):
                       generic_item: T

        See the class docstring for a description of all remaining parameters.
        '''
        assert isinstance(cls_stack, NoneTypeOr[tuple]), (
            f'{repr(cls_stack)} neither tuple nor "None".')
        assert isinstance(conf, BeartypeConf), (
            f'{repr(conf)} not configuration.')
        assert func is None or callable(func), (
            f'{repr(func)} neither callable nor "None".')
        assert isinstance(cause_indent, str), (
            f'{repr(cause_indent)} not string.')
        assert isinstance(cause_str_or_none, NoneTypeOr[str]), (
            f'{repr(cause_str_or_none)} not string or "None".')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')
        assert isinstance(hint_sane, HintSane), (
            f'{repr(hint_sane)} not sanified metadata.')
        assert isinstance(pith_name, NoneTypeOr[str]), (
            f'{repr(pith_name)} not string or "None".')
        assert isinstance(random_int, NoneTypeOr[int]), (
            f'{repr(random_int)} not integer or "None".')

        # If the caller did *NOT* pass a non-default sign identifying this hint,
        # default this sign to the default sign identifying this hint.
        if hint_sign is SENTINEL:
            hint_sign = get_hint_pep_sign_or_none(hint_sane.hint)
        # Else, the caller passed a non-default sign identifying this hint.
        # Preserve this sign as is.
        assert isinstance(hint_sign, NoneTypeOr[HintSign]), (
            f'{repr(hint_sane)} neither hint sign, "None", nor "SENTINEL".')

        # Classify all passed parameters.
        self.cause_indent = cause_indent
        self.cause_str_or_none = cause_str_or_none
        self.cls_stack = cls_stack
        self.conf = conf
        self.exception_prefix = exception_prefix
        self.func = func
        self.hint_sane = hint_sane
        self.hint_sign = hint_sign  # pyright: ignore
        self.pith = pith
        self.pith_name = pith_name
        self.random_int = random_int

        # Nullify all remaining parameters for safety.
        self.hint_childs = None  # type: ignore[assignment]
        self.hint_childs_sane = None  # type: ignore[assignment]

        # Sane hint sanified from this possibly insane hint.
        self.hint = hint_sane.hint

        # Initialize the "hint_childs" and "hint_childs_sane" instance variables
        # of this violation cause.
        self._init_hint_childs()


    def _init_hint_childs(self) -> None:
        '''
        Initialize the :attr:`hint_childs` and :attr:`hint_childs_sane` instance
        variables of this violation cause.
        '''

        # If this hint is either...
        if (
            # Ignorable *OR*...
            self.hint_sane is HINT_SANE_IGNORABLE or
            # PEP-noncompliant...
            not is_hint_pep(self.hint)
        ):
            # Then this hint *CANNOT* by definition be subscripted by any
            # meaningful child hints. Silently reduce to a noop.
            return
        # Else, this is an unignorable PEP-compliant hint. Since this hint
        # *COULD* be subscripted by meaningful child hints, continue.

        # Tuple of the zero or more arguments subscripting this hint.
        hint_childs_insane = get_hint_pep_args(self.hint)

        # List of the zero or more possibly ignorable sane child hints
        # subscripting this parent hint, initialized to the empty list.
        hint_childs = []

        # List of the zero or more possibly ignorable metadata generated by
        # sanifying these child hints, initialized to the empty list.
        hint_childs_sane = []

        # For each possibly ignorable insane child hints subscripting this
        # parent hint...
        for hint_child_insane in hint_childs_insane:
            # Sane child hint sanified from this possibly insane child hint.
            hint_child: Hint = None  # pyright: ignore

            # Metadata encapsulating the sanification of this child hint.
            hint_child_sane: HintSane = None  # type: ignore[assignment]

            # If this child hint is either...
            #
            # Note that arbitrary PEP-noncompliant arguments *CANNOT* be safely
            # sanified. Arbitrary arguments are *NOT* necessarily valid hints.
            # Consider the hint "tuple[()]", where the argument "()" is invalid
            # as a hint but valid an argument to that hint.
            if (
                # PEP-compliant *OR*...
                is_hint_pep(hint_child_insane) or
                # A type, which is effectively PEP 484-compliant.
                isinstance(hint_child_insane, type)
            ):
                # Sanify this child hint into this metadata.
                hint_child_sane = self.sanify_hint_child(
                    hint_child_insane=hint_child_insane,
                    hint_parent_sane=self.hint_sane,
                )

                # Sane child hint encapsulated by this metadata.
                hint_child = hint_child_sane.hint
            # Else, this child hint is PEP-noncompliant. In this case, preserve
            # this child hint as is.
            else:
                hint_child = hint_child_sane = hint_child_insane

            # Append this possibly ignorable sane child hint and supplementary
            # metadata to these lists.
            hint_childs.append(hint_child)
            hint_childs_sane.append(hint_child_sane)

        # Tuples of the zero or more possibly ignorable sane child hints and
        # supplementary metadatum, coerced from these lists.
        self.hint_childs = tuple(hint_childs)
        self.hint_childs_sane = tuple(hint_childs_sane)

    # ..................{ DUNDERS                            }..................
    def __repr__(self) -> str:
        '''
        Machine-readable representation of this error cause.
        '''

        # Represent this metadata with just the minimal subset of metadata
        # needed to reasonably describe this metadata.
        return (
            f'{self.__class__.__name__}('
            f'hint={repr(self.hint)}, '
            f'hint_sane={repr(self.hint_sane)}, '
            f'hint_sign={repr(self.hint_sign)}, '
            f'hint_childs={repr(self.hint_childs)}, '
            f'hint_childs_sane={repr(self.hint_childs_sane)}, '
            f'cause_indent={repr(self.cause_indent)}, '
            f'cause_str_or_none={repr(self.cause_str_or_none)}, '
            f'cls_stack={repr(self.cls_stack)}, '
            f'conf={repr(self.conf)}, '
            f'func={repr(self.func)}, '
            f'pith={repr(self.pith)}, '
            f'pith_name={repr(self.pith_name)}, '
            f'random_int={repr(self.random_int)}, '
            f'exception_prefix={repr(self.exception_prefix)}, '
            f')'
        )

    # ..................{ FINDERS                            }..................
    def find_cause(self) -> 'ViolationCause':
        '''
        Output cause describing whether the pith of this input cause either
        satisfies or violates the type hint of this input cause.

        Design
        ------
        This method is intentionally generalized to support objects both
        satisfying and *not* satisfying hints as equally valid use cases. While
        the parent
        :func:`beartype._check.error.errmain.get_func_pith_violation` function
        calling this method is *always* passed an object *not* satisfying the
        passed hint, this method is under no such constraints. Why? Because this
        method is also called to find which of an arbitrary number of objects
        transitively nested in the object passed to
        :func:`beartype._check.error.errmain.get_func_pith_violation` fails to
        satisfy the corresponding hint transitively nested in the hint passed to
        that function.

        For example, consider the type hint ``List[Union[int, str]]`` describing
        a list whose items are either integers or strings and the list
        ``list(range(256)) + [False,]`` consisting of the integers 0 through 255
        followed by boolean :data:`False`. Since that list is a sequence, the
        :func:`._peperrorsequence.find_cause_sequence_args_1` function must
        decide the cause of this list's failure to comply with this hint by
        finding the list item that is neither an integer nor a string,
        implemented by by iteratively passing each list item to the
        :func:`._peperrorunion.find_cause_pep484604_union` function. Since the
        first 256 items of this list are integers satisfying this hint,
        :func:`._peperrorunion.find_cause_pep484604_union` returns a dataclass
        instance whose :attr:`cause` field is :data:`None` up to
        :func:`._peperrorsequence.find_cause_sequence_args_1` before finally
        finding the non-compliant boolean item and returning its cause.

        Returns
        -------
        ViolationCause
            Output cause type-checking this pith against this type hint.

        Raises
        ------
        _BeartypeCallHintPepRaiseException
            If this type hint is either:

            * PEP-noncompliant (e.g., tuple union).
            * PEP-compliant but no getter function has been implemented to
              handle this category of PEP-compliant type hint yet.
        '''
        # print(f'Finding cause for {self.hint} identified by {self.hint_sign}...')

        # If this hint is ignorable, all possible objects satisfy this hint.
        # Since this hint *CANNOT* (by definition) be the cause of this failure,
        # return the same cause as is.
        if self.hint_sane is HINT_SANE_IGNORABLE:
            return self
        # Else, this hint is unignorable.

        # Getter function returning the desired string.
        cause_finder: Callable[[ViolationCause], ViolationCause] = None  # type: ignore[assignment]

        # If this hint...
        if (
            # Originates from an origin type and may thus be shallowly
            # type-checked against that type *AND is either...
            self.hint_sign in HINT_SIGNS_ORIGIN_ISINSTANCEABLE and (
                # Unsubscripted *OR*...
                not get_hint_pep_args(self.hint) or
                # Currently unsupported with deep type-checking...
                self.hint_sign not in HINT_SIGNS_SUPPORTED_DEEP
            )
        # Then this hint is both unsubscripted and originating from a standard
        # type origin. In this case, this hint was type-checked shallowly.
        ):
            # Avoid circular import dependencies.
            from beartype._check.error._errtype import (
                find_cause_type_instance_origin)

            # Defer to the getter function supporting hints originating from
            # origin types.
            cause_finder = find_cause_type_instance_origin
        # Else, this hint is either subscripted *OR* unsubscripted but not
        # originating from a standard type origin. In either case, this hint was
        # type-checked deeply.
        else:
            # Avoid circular import dependencies.
            from beartype._check.error._errmap import (
                HINT_SIGN_TO_GET_CAUSE_FUNC)

            # Getter function returning the desired string for this attribute if
            # any *OR* "None" otherwise.
            cause_finder = HINT_SIGN_TO_GET_CAUSE_FUNC.get(  # type: ignore[assignment]
                self.hint_sign, None)  # type: ignore[arg-type]

            # If no such function has been implemented to handle this attribute
            # yet, raise an exception.
            if cause_finder is None:
                raise _BeartypeCallHintPepRaiseException(
                    f'{self.exception_prefix}type hint '
                    f'{repr(self.hint)} unsupported (i.e., no '
                    f'"find_cause_"-prefixed getter function defined '
                    f'for this category of hint).'
                )
            # Else, a getter function has been implemented to handle this
            # attribute.

        # Call this getter function with ourselves and return the string
        # returned by this getter.
        return cause_finder(self)

    # ..................{ PERMUTERS                          }..................
    def permute_cause(self, **kwargs) -> 'ViolationCause':
        '''
        Shallow copy of this violation cause such that each passed keyword
        parameter overwrites the instance variable of the same name in this
        copy.

        Parameters
        ----------
        Keyword parameters of the same name and type as instance variables of
        this object (e.g., ``pith: object``).

        Returns
        -------
        ViolationCause
            Shallow copy of this violation cause such that each keyword
            parameter overwrites the instance variable of the same name in this
            copy.

        Raises
        ------
        _BeartypeCallHintPepRaiseException
            If the name of any passed keyword parameter is *not* that of an
            existing instance variable of this violation cause.

        Examples
        --------
        .. code-block:: pycon

           >>> sleuth = ViolationCause(
           ...     pith=[42,]
           ...     hint=typing.List[int],
           ...     cause_indent='',
           ...     exception_prefix='List of integers',
           ... )
           >>> sleuth_copy = sleuth.permute_cause(pith=[24,])
           >>> sleuth_copy.pith
           [24,]
           >>> sleuth_copy.hint
           typing.List[int]
        '''

        # Set us up the permutation! Make your time!
        return permute_object(
            obj=self,
            init_arg_name_to_value=kwargs,
            init_arg_names=self._INIT_ARG_NAMES,
            copy_var_names=self._COPY_VAR_NAMES,
            exception_cls=_BeartypeCallHintPepRaiseException,
        )


    def permute_cause_hint_child_insane(
        self, hint_child_insane: Hint, **kwargs) -> 'ViolationCause':
        '''
        Shallow copy of this violation cause such that each passed keyword
        parameter overwrites the instance variable of the same name in this copy
        *after* sanifying (i.e., sanitizing) the passed **possibly insane child
        hint** (i.e., child hint that has yet to be sanified subscripting the
        current hint encapsulated by this cause) and passing the metadata
        encapsulating that sanification as the ``hint_sane`` parameter of this
        dictionary.

        Parameters
        ----------
        hint_child_insane : Hint
            Possibly insane child hint to be sanified.

        All other keyword parameters are of the same name and type as instance
        variables of this object (e.g., ``pith: object``).

        Returns
        -------
        ViolationCause
            Shallow copy of this violation cause, permuted as detailed above.

        Raises
        ------
        _BeartypeCallHintPepRaiseException
            If the name of any passed keyword parameter is *not* that of an
            existing instance variable of this violation cause.

        See Also
        --------
        :meth:`permute_cause`
            Further details.
        '''

        # Metadata encapsulating the sanification of the passed hint relative to
        # the current previously sanified hint, which effectively serves as the
        # "parent" of the passed hint for all intents and purposes.
        hint_sane = self.sanify_hint_child(
            hint_child_insane=hint_child_insane,
            hint_parent_sane=self.hint_sane,
        )

        # Violation cause permuted from this metadata and these keywords.
        cause_permuted = self.permute_cause(hint_sane=hint_sane, **kwargs)

        # Return this permuted cause.
        return cause_permuted

    # ..................{ SANIFIERS                          }..................
    def sanify_hint_child(
        self,

        # Mandatory parameters.
        hint_child_insane: Hint,

        # Optional parameters.
        hint_parent_sane: Optional[HintSane] = None,
    ) -> HintSane:
        '''
        Metadata encapsulating the sanification (i.e., sanitization) of the
        passed **possibly insane child type hint** (i.e., possibly
        PEP-noncompliant hint transitively subscripting the root hint annotating
        a parameter or return of the currently decorated callable) if this hint
        is both reducible and unignorable, this hint unmodified if this hint is
        both irreducible and unignorable, or :obj:`.HINT_SANE_IGNORABLE` otherwise
        (i.e., if this hint is ignorable).

        This method is merely a convenience wrapper for the lower-level
        :func:`.sanify_hint_child` sanifier.

        Parameters
        ----------
        hint_child_insane : Hint
            Child type hint to be sanified.
        hint_parent_sane : HintSane
            **Sanified parent type hint metadata** (i.e., immutable and thus
            hashable object encapsulating *all* metadata previously returned by
            :mod:`beartype._check.convert.convmain` sanifiers after sanitizing
            the possibly PEP-noncompliant parent hint of this child hint into a
            fully PEP-compliant parent hint).
        hint_parent_sane : Optional[HintSane], default: None
            **Sanified parent type hint metadata** (i.e., immutable and thus
            hashable object encapsulating *all* metadata previously returned by
            :mod:`beartype._check.convert.convmain` sanifiers after sanitizing
            the possibly PEP-noncompliant parent hint of this child hint into a
            fully PEP-compliant parent hint). Defaults to :data:`None`, in which
            case this parameter actually defaults to ``self.hint_sane``, the
            previously sanified metadata encapsulating the direct parent hint of
            this child hint. Since this default suffices in the common case,
            callers should only pass this parameter when explicitly sanifying
            the parent hint of this child hint.

        Returns
        -------
        HintSane
            Either:

            * If this child hint is ignorable, :data:`.HINT_SANE_IGNORABLE`.
            * Else if this unignorable child hint is reducible to another hint,
              metadata encapsulating this reduction.
            * Else, this unignorable child hint is irreducible. In this case,
              metadata encapsulating this child hint unmodified.
        '''

        # If the caller explicitly passed *NO* sanified parent hint metadata,
        # default this metadata to that of the currently visited hint.
        if hint_parent_sane is None:
            hint_parent_sane = self.hint_sane
        # Else, the caller explicitly passed sanified parent hint metadata.
        # Silently preserve this metadata as is.

        # Metadata encapsulating the sanification of this child hint.
        hint_sane_child = sanify_hint_child(
            hint=hint_child_insane,
            hint_parent_sane=hint_parent_sane,
            cls_stack=self.cls_stack,
            conf=self.conf,
            pith_name=self.pith_name,
            exception_prefix=self.exception_prefix,
        )
        # print(f'Sanified child hint {hint_child_insane} to {hint_sane_child} of parent {hint_parent_sane}!')

        # Return this metadata.
        return hint_sane_child
