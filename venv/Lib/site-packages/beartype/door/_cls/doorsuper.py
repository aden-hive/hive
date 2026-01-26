#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **Decidedly Object-Oriented Runtime-checking (DOOR) superclass**
(i.e., root of the object-oriented type hint class hierarchy encapsulating the
non-object-oriented type hint API standardized by the :mod:`typing` module).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: Slot "TypeHint" attributes for lookup efficiency, please.
#FIXME: Privatize most (...or perhaps all) public instance variables, please.

# ....................{ IMPORTS                            }....................
from beartype.door._cls.doormeta import _TypeHintMeta
from beartype.door._cls.util.doorclstest import die_unless_typehint
from beartype.door._func.doorcheck import (
    die_if_unbearable,
    is_bearable,
)
from beartype.roar import BeartypeDoorIsSubhintException
from beartype.typing import (
    Any,
    FrozenSet,
    Generic,
    Iterable,
    Tuple,
    overload,
)
from beartype._check.convert.convmain import sanify_hint_any
from beartype._check.metadata.hint.hintsane import HINT_SANE_IGNORABLE
from beartype._conf.confmain import BeartypeConf
from beartype._conf.confcommon import BEARTYPE_CONF_DEFAULT
from beartype._data.typing.datatypingport import T_Hint
from beartype._util.cache.utilcachecall import (
    method_cached_arg_by_id,
    property_cached,
)
from beartype._util.hint.pep.utilpepget import (
    get_hint_pep_args,
    get_hint_pep_origin_type_or_none,
)
from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none
from beartype._util.utilobject import get_object_type_basename

# ....................{ SUPERCLASSES                       }....................
#FIXME: Subclass all applicable "collections.abc" ABCs for explicitness, please.
#FIXME: Document all public and private attributes of this class, please.
class TypeHint(Generic[T_Hint], metaclass=_TypeHintMeta):
    '''
    Abstract base class (ABC) of all **type hint wrapper** (i.e., high-level
    object encapsulating a low-level type hint augmented with a magically
    object-oriented Pythonic API, including equality and rich comparison
    testing) subclasses.

    Sorting
    -------
    **Type hint wrappers are partially ordered** with respect to one another.
    Type hints wrappers support all binary comparators (i.e., ``==``, ``!=``,
    ``<``, ``<=``, ``>``, and ``>=``) such that for any three type hint wrappers
    ``a``, ``b`, and ``c``:

    * ``a ≤ a`` (i.e., **reflexivity**).
    * If ``a ≤ b`` and ``b ≤ c``, then ``a ≤ c`` (i.e., **transitivity**).
    * If ``a ≤ b`` and ``b ≤ a``, then ``a == b`` (i.e., **antisymmetry**).

    **Type hint wrappers are not totally ordered,** however. Like unordered
    sets, type hint wrappers do *not* satisfy **totality** (i.e., either ``a ≤
    b`` or ``b ≤ a``, which is *not* necessarily the case for incommensurable
    type hint wrappers that *cannot* reasonably be compared with one another).

    Type hint wrappers are thus usable in algorithms and data structures
    requiring at most a partial ordering over their input.

    Examples
    --------
    .. code-block:: pycon

       >>> from beartype.door import TypeHint
       >>> hint_a = TypeHint(Callable[[str], list])
       >>> hint_b = TypeHint(Callable[Union[int, str], Sequence[Any]])
       >>> hint_a <= hint_b
       True
       >>> hint_a > hint_b
       False
       >>> hint_a.is_subhint(hint_b)
       True
       >>> list(hint_b)
       [TypeHint(typing.Union[int, str]), TypeHint(typing.Sequence[typing.Any])]

    Attributes
    ----------
    _args : Tuple[Hint, ...]
        Tuple of the zero or more low-level child type hints subscripting
        (indexing) the low-level parent type hint wrapped by this wrapper.
    _hint : T_Hint
        Low-level type hint wrapped by this wrapper.
    _hint_sign : beartype._data.hint.sign.datahintsigncls.HintSign | None
        Either:

        * If this hint is PEP-compliant and thus uniquely identified by a
          :mod:`beartype`-specific sign, that sign.
        * Else (i.e., if this hint is an isinstanceable class), :data:`None`.
    _origin: type
        Either:

        * If this hint originates from an **isinstanceable class** such that all
          objects satisfying this hint are instances of that class, that class.
        * Else, the root superclass :class:`object` of *all* classes,
          guaranteeing sanity when this instance variable is passed as either
          the first or second parameters to the :func:`issubclass` builtin.
    '''

    # ..................{ INITIALIZERS                       }..................
    def __init__(self, hint: T_Hint) -> None:
        '''
        Initialize this type hint wrapper from the passed low-level type hint.

        Parameters
        ----------
        hint : Hint
            Low-level type hint to be wrapped by this wrapper.
        '''

        # Classify all passed parameters. Note that this type hint is guaranteed
        # to be a type hint by validation performed by this metaclass __init__()
        # method.
        self._hint = hint

        # Sign uniquely identifying this and that hint if any *OR* "None"
        self._hint_sign = get_hint_pep_sign_or_none(hint)

        # Isinstance class originating this hint if any *OR* "None" otherwise,
        # defined as either...
        self._origin: type = (
            # If this hint originates from an origin type, that type;
            get_hint_pep_origin_type_or_none(
                hint=hint,
                # If this hint is a type defining the "__origin__" dunder
                # attribute to be a non-type, fallback to euphemistically
                # claiming that this hint originates from "itself." Boooo!
                is_self_fallback=True,
            ) or
            # Else, this hint does *NOT* originate from an origin type. In this
            # case, the root superclass "object" of *ALL* classes, guaranteeing
            # sanity when this instance variable is passed as either the first
            # or second parameters to the issubclass() builtin.
            object
        )

        # Tuple of all low-level child type hints of this hint *AFTER* defining
        # all other instance variables. Deferring this call allows subclass
        # _make_args() implementations to access these instance variables.
        self._args = self._make_args()

    # ..................{ DUNDERS                            }..................
    def __hash__(self) -> int:
        '''
        Hash of the low-level immutable type hint wrapped by this immutable
        wrapper.

        Defining this method satisfies the :class:`collections.abc.Hashable`
        abstract base class (ABC), enabling this wrapper to be used as in
        hashable containers (e.g., dictionaries, sets).
        '''

        return hash(self._hint)


    def __repr__(self) -> str:
        '''
        Machine-readable representation of this type hint wrapper.
        '''

        # Unqualified name of the concrete subclass wrapping this hint.
        hint_wrapper_basename = get_object_type_basename(self)
        # print('hint_wrapper_basename: {hint_wrapper_basename}')

        # If this concrete subclass is currently private, deviously hide this
        # implementation detail by defaulting to the unqualified name of this
        # public "TypeHint" superclass instead.
        if hint_wrapper_basename[0] == '_':
            hint_wrapper_basename = 'TypeHint'
        # Else, this concrete subclass is public.

        # Return this machine-readable representation.
        return f'{hint_wrapper_basename}({repr(self._hint)})'

    # ..................{ DUNDERS ~ compare : equals         }..................
    # Note that we intentionally avoid typing this method as returning
    # "Union[bool, NotImplementedType]". Why? Because mypy in particular has
    # epileptic fits about "NotImplementedType". This is *NOT* worth the agony!
    @method_cached_arg_by_id
    def __eq__(self, other: object) -> bool:
        '''
        :data:`True`` only if the low-level type hint wrapped by this wrapper is
        semantically equivalent to the other low-level type hint wrapped by the
        passed wrapper.

        This tester is memoized for efficiency, as Python implicitly calls this
        dunder method on hashable-based container lookups (e.g.,
        :meth:`dict.get`) expected to be ``O(1)`` fast.

        Parameters
        ----------
        other : object
            Other type hint to be tested against this type hint.

        Returns
        -------
        bool
            :data:`True` only if this type hint is equal to that other hint.
        '''

        # Return either...
        return (
            # If that object is a type hint wrapper, defer to the
            # subclass-specific implementation of this test;
            self._is_equal(other)
            if isinstance(other, TypeHint) else
            # Else, that object is *NOT* a type hint wrapper. In this case,
            # defer to either:
            # * If the class of that object defines a similar __eq__() method
            #   supporting the "TypeHint" API, that method.
            # * Else, Python's builtin C-based fallback equality comparator that
            #   merely compares whether two objects are identical (i.e., share
            #   the same object ID).
            NotImplemented
        )


    def __ne__(self, other: object) -> bool:

        # Return either...
        return (
            # If that object is a type hint wrapper, defer to the
            # subclass-specific implementation of this test;
            not self._is_equal(other)
            if isinstance(other, TypeHint) else
            # Else, that object is *NOT* a type hint wrapper. See __eq__().
            NotImplemented
        )

    # ..................{ DUNDERS ~ compare : rich           }..................
    def __le__(self, other: object) -> bool:
        '''
        :data:`True` if this hint is a subhint of the passed hint.
        '''

        # Return either...
        return (
            # If that object is a type hint wrapper, defer to the
            # subclass-specific implementation of this test;
            self.is_subhint(other)
            if isinstance(other, TypeHint) else
            # Else, that object is *NOT* a type hint wrapper. See __eq__().
            NotImplemented
        )


    def __lt__(self, other: object) -> bool:
        '''
        :data:`True` if this hint is a strict subhint of the passed hint.
        '''

        # Return either...
        return (
            # If that object is a type hint wrapper, defer to the
            # subclass-specific implementation of this test;
            (self.is_subhint(other) and self != other)
            if isinstance(other, TypeHint) else
            # Else, that object is *NOT* a type hint wrapper. See __eq__().
            NotImplemented
        )


    def __ge__(self, other: object) -> bool:
        '''
        :data:`True` if this hint is a superhint of the passed hint.
        '''

        # Return either...
        return (
            # If that object is a type hint wrapper, defer to the
            # subclass-specific implementation of this test;
            self.is_superhint(other)
            if isinstance(other, TypeHint) else
            # Else, that object is *NOT* a type hint wrapper. See __eq__().
            NotImplemented
        )


    def __gt__(self, other: object) -> bool:
        '''
        :data:`True` if this hint is a strict superhint of the passed hint.
        '''

        # Return either...
        return (
            # If that object is a type hint wrapper, defer to the
            # subclass-specific implementation of this test;
            (self.is_superhint(other) and self != other)
            if isinstance(other, TypeHint) else
            # Else, that object is *NOT* a type hint wrapper. See __eq__().
            NotImplemented
        )

    # ..................{ DUNDERS ~ iterable                 }..................
    def __contains__(self, hint_child: 'TypeHint') -> bool:
        '''
        :data:`True` only if the low-level type hint wrapped by the passed
        **type hint wrapper** (i.e., :class:`TypeHint` instance) is a child type
        hint originally subscripting the low-level parent type hint wrapped by
        this :class:`TypeHint` instance.
        '''

        # Sgt. Pepper's One-liners GitHub Club Band.
        return hint_child in self._args_wrapped_frozenset


    def __iter__(self) -> Iterable['TypeHint']:
        '''
        Generator iteratively yielding all **children type hint wrappers**
        (i.e., :class:`TypeHint` instances wrapping all low-level child type
        hints originally subscripting the low-level parent type hint wrapped by
        this :class:`TypeHint` instance).

        Defining this method satisfies the :class:`collections.abc.Iterable`
        abstract base class (ABC).
        '''

        # For those who are about to one-liner, we salute you.
        yield from self._args_wrapped_tuple

    # ..................{ DUNDERS ~ iterable : item          }..................
    # Inform static type-checkers of the one-to-one correspondence between the
    # type of the object subscripting an instance of this class with the type of
    # the object returned by that subscription. Note this constraint is strongly
    # inspired by this erudite StackOverflow answer:
    #     https://stackoverflow.com/a/71183076/2809027

    @overload
    def __getitem__(self, index: int) -> 'TypeHint': ...
    @overload
    def __getitem__(self, index: slice) -> Tuple['TypeHint', ...]: ...

    # Note that the actual implementation of this overload is intentionally:
    # * *NOT* decorated by the standard @overload decorator.
    # * *NOT* annotated by type hints. By PEP 484, only the signatures of
    #   @overload-decorated callables are annotated by type hints.
    def __getitem__(self, index):
        '''
        Either:

        * If the passed object is an integer, then this type hint wrapper was
          subscripted by either a positive 0-based absolute index or a negative
          -1-based relative index. In either case, this dunder method returns
          the **child type hint wrapper** (i.e., :class:`TypeHint` instance
          wrapping a low-level child type hint originally subscripting the
          low-level parent type hint wrapped by this :class:`TypeHint` instance)
          with the same index.
        * If the passed object is a slice, then this type hint wrapper was
          subscripted by a range of such indices. In this case, this dunder
          method returns a tuple of the zero or more child type hint wrappers
          with the same indices.

        Parameters
        ----------
        index : Union[int, slice]
            Either:

            * Positive 0-based absolute index or negative -1-based relative
              index of the child type hint originally subscripting the parent
              type hint wrapped by this :class:`TypeHint` instance to be
              returned wrapped by a new :class:`TypeHint` instance.
            * Slice of such indices of the zero or more child type hints
              originally subscripting the parent type hint wrapped by this
              :class:`TypeHint` instance to be returned in a tuple of these
              child type hints wrapped by new :class:`TypeHint` instances.

        Returns
        -------
        Union['TypeHint', Tuple['TypeHint', ...]]
            Child type hint wrapper(s) at these ind(ex|ices), as detailed above.
        '''

        # Defer validation of the correctness of the passed index or slice to
        # the low-level tuple.__getitem__() dunder method. Though we could (and
        # possibly should) perform that validation here, doing so is non-trivial
        # in the case of both a negative relative index *AND* a passed slice.
        # This trivial approach suffices for now.
        return self._args_wrapped_tuple[index]

    # ..................{ DUNDERS ~ iterable : sized         }..................
    #FIXME: Unit test us up, please.
    def __bool__(self) -> bool:
        '''
        :data:`True` only if the low-level parent type hint wrapped by this
        wrapper was subscripted by at least one child type hint.
        '''

        # See __len__() for further commentary.
        return bool(self._args_wrapped_tuple)


    #FIXME: Unit test us up, please.
    def __len__(self) -> int:
        '''
        Number of low-level child type hints subscripting the low-level parent
        type hint wrapped by this wrapper.

        Defining this method satisfies the :class:`collections.abc.Sized`
        abstract base class (ABC).
        '''

        # Return the exact length of the same iterable returned by the
        # __iter__() dunder method rather than the possibly differing length of
        # the "self._args" tuple, for safety. Theoretically, these two iterables
        # should exactly coincide in length. Pragmatically, it's best to assume
        # nothing in the murky waters we swim in.
        return len(self._args_wrapped_tuple)

    # ..................{ PROPERTIES ~ read-only             }..................
    # Read-only properties intentionally defining *NO* corresponding setter.

    #FIXME: Unit test us up, please.
    @property
    def args(self) -> tuple:
        '''
        Tuple of the zero or more low-level child type hints subscripting
        (indexing) the low-level parent type hint wrapped by this wrapper.

        Caveats
        -------
        Note that this property is intentionally *not* annotated as returning a
        tuple of valid type hints (e.g., ``Tuple[Hint, ...]``). Although most
        child hints *are* valid type hints outside the context of this parent
        hint, some are not. Examples include:

        * :pep:`586`-compliant ``typing.Literal[...]`` hints, subscripted by
          literal objects that are *not* valid hints (e.g.,
          ``typing.Literal['totally', 'not', 'a', 'type']``,).
        '''

        # Who could argue with a working one-liner? Not you. Surely, not you.
        return self._args


    @property
    def hint(self) -> T_Hint:
        '''
        **Original type hint** (i.e., low-level PEP-compliant type hint wrapped
        by this wrapper at :meth:`TypeHint.__init__` instantiation time).
        '''

        # Q: Can one-liners solve all possible problems? A: Yes.
        return self._hint


    @property
    def is_ignorable(self) -> bool:
        '''
        :data:`True` only if this type hint is **ignorable** (i.e., conveys
        *no* meaningful semantics despite superficially appearing to do so).

        While one might expect the set of all ignorable type hints to be both
        finite and small, this set is actually **countably infinite** in size.
        Countably infinitely many type hints are ignorable. This includes:

        * :attr:`typing.Any`, by design.
        * :class:`object`, the root superclass of all types. Ergo, parameters
          and return values annotated as :class:`object` unconditionally match
          *all* objects under :func:`isinstance`-based type covariance and thus
          semantically reduce to unannotated parameters and return values.
        * The unsubscripted :attr:`typing.Optional` singleton, which
          semantically expands to the implicit ``Optional[Any]`` type hint under
          :pep:`484`. Since :pep:`484` also stipulates that all ``Optional[t]``
          type hints semantically expand to ``Union[t, type(None)]`` type hints
          for arbitrary arguments ``t``, ``Optional[Any]`` semantically expands
          to merely ``Union[Any, type(None)]``. Since all unions subscripted by
          :attr:`typing.Any` semantically reduce to merely :attr:`typing.Any`,
          the unsubscripted :attr:`typing.Optional` singleton also reduces to
          merely :attr:`typing.Any`. This intentionally excludes the
          ``Optional[type(None)]`` type hint, which the :mod:`typing` module
          reduces to merely ``type(None)``.
        * The unsubscripted :attr:`typing.Union` singleton, which
          semantically reduces to :attr:`typing.Any` by the same argument.
        * Any subscription of :attr:`typing.Union` by one or more ignorable type
          hints. There exists a countably infinite number of such subscriptions,
          many of which are non-trivial to find by manual inspection. The
          ignorability of a union is a transitive property propagated "virally"
          from child to parent type hints. Consider:

          * ``Union[Any, bool, str]``. Since :attr:`typing.Any` is ignorable,
            this hint is trivially ignorable by manual inspection.
          * ``Union[str, List[int], NewType('MetaType', Annotated[object,
            53])]``. Although several child type hints of this union are
            non-ignorable, the deeply nested :class:`object` child type hint is
            ignorable by the argument above. It transitively follows that the
            ``Annotated[object, 53]`` parent type hint subscripted by
            :class:`object`, the :obj:`typing.NewType` parent type hint aliased
            to ``Annotated[object, 53]``, *and* the entire union subscripted by
            that :obj:`typing.NewType` are themselves all ignorable as well.

        * Any subscription of :attr:`typing.Annotated` by one or more ignorable
          type hints. As with :attr:`typing.Union`, there exists a countably
          infinite number of such subscriptions. (See the prior item.)
        * The :class:`typing.Generic` and :class:`typing.Protocol` superclasses,
          both of which impose no constraints *in and of themselves.* Since all
          possible objects satisfy both superclasses. Both superclasses are
          synonymous to the ignorable :class:`object` root superclass: e.g.,

          .. code-block:: pycon

             >>> from typing as Protocol
             >>> isinstance(object(), Protocol)
             True
             >>> isinstance('wtfbro', Protocol)
             True
             >>> isinstance(0x696969, Protocol)
             True

        * Any subscription of either the :class:`typing.Generic` or
          :class:`typing.Protocol` superclasses, regardless of whether the child
          type hints subscripting those superclasses are ignorable or not.
          Subscripting a type that conveys no meaningful semantics continues to
          convey no meaningful semantics. For example, the type hints
          ``typing.Generic[typing.Any]`` and ``typing.Generic[str]`` are both
          equally ignorable – despite the :class:`str` class being otherwise
          unignorable in most type hinting contexts.
        * And frankly many more. And... *now we know why this tester exists.*

        This property is memoized for efficiency.

        Returns
        -------
        bool
            :data:`True` only if this type hint is ignorable.
        '''

        #FIXME: [SPEED] *SLOW.* Ideally, the result of calling
        #sanify_hint_child() should be lazily memoized with a new private
        #"_hint_sane" property, which this logic would then access instead.

        # Return true only if this hint is ignorable.
        return sanify_hint_any(self._hint) is HINT_SANE_IGNORABLE  # pyright: ignore

    # ..................{ CHECKERS                           }..................
    def die_if_unbearable(
        self,

        # Mandatory flexible parameters.
        obj: object,

        # Optional keyword-only parameters.
        *,
        conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
        exception_prefix: str = 'die_if_unbearable() ',
    ) -> None:
        '''
        Raise an exception if the passed arbitrary object violates this type
        hint under the passed beartype configuration.

        To configure the type of violation exception raised by this method, set
        the :attr:`.BeartypeConf.violation_door_type` option of the passed
        ``conf`` parameter accordingly.

        Parameters
        ----------
        obj : object
            Arbitrary object to be tested against this hint.
        conf : BeartypeConf, optional
            **Beartype configuration** (i.e., self-caching dataclass
            encapsulating all settings configuring type-checking for the passed
            object). Defaults to ``BeartypeConf()``, the default ``O(1)``
            constant-time configuration.
        exception_prefix : str, optional
            Human-readable label prefixing the representation of this object in
            the exception message. Defaults to a reasonably sensible string.

        Raises
        ------
        ``conf.violation_door_type``
            If this object violates this hint.
        beartype.roar.BeartypeDecorHintNonpepException
            If this hint is *not* PEP-compliant (i.e., complies with *no* Python
            Enhancement Proposals (PEPs) currently supported by
            :mod:`beartype`).
        beartype.roar.BeartypeDecorHintPepUnsupportedException
            If this hint is currently unsupported by :mod:`beartype`.

        Examples
        --------
        .. code-block:: pycon

           >>> from beartype.door import TypeHint
           >>> TypeHint(list[str]).die_if_unbearable(
           ...     ['And', 'what', 'rough', 'beast,'], )
           >>> TypeHint(list[str]).die_if_unbearable(
           ...     ['its', 'hour', 'come', 'round'], list[int])
           beartype.roar.BeartypeDoorHintViolation: Object ['its', 'hour',
           'come', 'round'] violates type hint list[int], as list index 0 item
           'its' not instance of int.
        '''

        # One-liner, one love, one heart. Let's get together and code alright.
        die_if_unbearable(
            obj=obj,
            hint=self._hint,
            conf=conf,
            exception_prefix=exception_prefix,
        )


    def is_bearable(
        self,

        # Mandatory flexible parameters.
        obj: object,

        # Optional keyword-only parameters.
        *, conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
    ) -> bool:
        '''
        :data:`True` only if the passed arbitrary object satisfies this type
        hint under the passed beartype configuration.

        Parameters
        ----------
        obj : object
            Arbitrary object to be tested against this hint.
        conf : BeartypeConf, optional
            **Beartype configuration** (i.e., self-caching dataclass
            encapsulating all settings configuring type-checking for the passed
            object). Defaults to ``BeartypeConf()``, the default
            constant-time configuration.

        Returns
        -------
        bool
            :data:`True` only if this object satisfies this hint.

        Raises
        ------
        beartype.roar.BeartypeDecorHintForwardRefException
            If this hint contains one or more relative forward references, which
            this tester explicitly prohibits to improve both the efficiency and
            portability of calls to this tester.

        Examples
        --------
        .. code-block:: pycon

           >>> from beartype.door import TypeHint
           >>> TypeHint(list[str]).is_bearable(['Things', 'fall', 'apart;'])
           True
           >>> TypeHint(list[int]).is_bearable(
           ...     ['the', 'centre', 'cannot', 'hold;'])
           False
        '''

        # One-liners justify their own existence.
        return is_bearable(obj=obj, hint=self._hint, conf=conf)  # pyright: ignore

    # ..................{ TESTERS ~ subhint                  }..................
    # Note that the @method_cached_arg_by_id rather than @callable_cached
    # decorator is *ABSOLUTELY* required here. Why? Because the @callable_cached
    # decorator internally caches the passed "other" argument as the key of a
    # dictionary. Subsequent calls to this method when passed the same argument
    # lookup that "other" in that dictionary. Since dictionary lookups
    # implicitly call other.__eq__() to resolve key collisions *AND* since the
    # TypeHint.__eq__() method calls TypeHint.is_subhint(), infinite recursion!
    @method_cached_arg_by_id
    def is_subhint(self, other: 'TypeHint') -> bool:
        '''
        :data:`True` only if this type hint is a **subhint** of the passed type
        hint.

        This tester method is memoized for efficiency.

        Parameters
        ----------
        other : TypeHint
            Other type hint to be tested against this type hint.

        Returns
        -------
        bool
            :data:`True` only if this type hint is a subhint of that other hint.

        See Also
        --------
        :func:`beartype.door.is_subhint`
            Further details.
        '''
        # print(f'[TypeHint.is_subhint] Comparing {self} to {other}...')

        # If the passed object is *NOT* a type hint wrapper, raise an exception.
        die_unless_typehint(other)
        # Else, that object is a type hint wrapper.

        # Return true only if either...
        return (
            # That hint is the "typing.Any" catch-all (then this hint is
            # necessarily a subhint of that hint) *OR*...
            other._hint is Any or
            # This hint is a subhint of that hint (according to the
            # subclass-specific implementation of this test).
            self._is_subhint(other)
        )


    def is_superhint(self, other: 'TypeHint') -> bool:
        '''
        :data:`True` only if this type hint is a **superhint** of the passed
        type hint.

        This tester method is memoized for efficiency.

        Parameters
        ----------
        other : TypeHint
            Other type hint to be tested against this type hint.

        Returns
        -------
        bool
            :data:`True` only if this type hint is a superhint of that other
            hint.

        See Also
        --------
        :func:`beartype.door.is_subhint`
            Further details.
        '''

        # If the passed object is *NOT* a type hint wrapper, raise an exception.
        die_unless_typehint(other)
        # Else, that object is a type hint wrapper.

        # Return true only if this hint is a superhint of the passed hint.
        return other.is_subhint(self)

    # ..................{ PRIVATE                            }..................
    # Subclasses are encouraged to override these concrete methods defaulting to
    # general-purpose implementations suitable for most subclasses.

    # ..................{ PRIVATE ~ factories                }..................
    def _make_args(self) -> tuple:
        '''
        Tuple of the zero or more low-level child type hints subscripting
        (indexing) the low-level parent type hint wrapped by this wrapper, which
        the :meth:`TypeHint.__init__` method assigns to the :attr:`_args`
        instance variable of this wrapper.

        Subclasses are advised to override this method to set the :attr:`_args`
        instance variable of this wrapper in a subclass-specific manner.

        Caveats
        -------
        Note that this method is intentionally *not* annotated as returning a
        tuple of valid type hints (e.g., ``Tuple[Hint, ...]``). Although most
        child hints *are* valid type hints outside the context of this parent
        hint, some are not. Examples include:

        * :pep:`586`-compliant ``typing.Literal[...]`` hints, subscripted by
          literal objects that are *not* valid hints (e.g.,
          ``typing.Literal['totally', 'not', 'a', 'type']``,).
        '''

        # We are the one-liner. We are the codebase.
        return get_hint_pep_args(self._hint)

    # ..................{ PRIVATE ~ testers                  }..................
    def _is_equal(self, other: 'TypeHint') -> bool:
        '''
        :data:`True` only if the low-level type hint wrapped by this wrapper is
        semantically equivalent to the other low-level type hint wrapped by the
        passed wrapper.

        Subclasses are advised to override this method to implement the public
        :meth:`is_subhint` tester method (which internally defers to this
        private tester method) in a subclass-specific manner. Since the default
        implementation is guaranteed to suffice for *all* possible use cases,
        subclasses should override this method only for efficiency reasons; the
        default implementation calls the :meth:`is_subhint` method twice and is
        thus *not* necessarily the optimal implementation for subclasses.
        Notably, the default implementation exploits the well-known syllogism
        between two partially ordered items ``A`` and ``B``:

        * If ``A <= B`` and ``A >= B``, then ``A == B``.

        This private tester method is *not* memoized for efficiency, as the
        caller is guaranteed to be the public :meth:`__eq__` tester method,
        which is already memoized.

        Parameters
        ----------
        other : TypeHint
            Other type hint to be tested against this type hint.

        Returns
        -------
        bool
            :data:`True` only if this type hint is equal to that other hint.
        '''

        # Return true only if both...
        #
        # Note that this conditional implements the trivial boolean syllogism
        # that we all know and adore: "If A <= B and B <= A, then A == B".
        return (
            # This union is a subhint of that object.
            self.is_subhint(other) and
            # That object is a subhint of this union.
            other.is_subhint(self)
        )

    # ..................{ PRIVATE ~ testers : subhint        }..................
    def _is_subhint(self, other: 'TypeHint') -> bool:
        '''
        :data:`True` only if this type hint is a **subhint** of the passed type
        hint.

        Subclasses are advised to override this method to implement the public
        :meth:`is_subhint` tester method (which internally defers to this
        private tester method) in a subclass-specific manner.

        This private tester method is *not* memoized for efficiency, as the
        caller is guaranteed to be the public :meth:`is_subhint` tester method,
        which is already memoized.

        Parameters
        ----------
        other : TypeHint
            Other type hint to be tested against this type hint.

        Returns
        -------
        bool
            :data:`True` only if this type hint is a subhint of that other hint.

        See Also
        --------
        :func:`beartype.door.is_subhint`
            Further details.
        '''
        # print(f'[TypeHint._is_subhint] Comparing {self} to {other}...')

        # For each branch of that hint...
        for other_branch in other._branches:
            # If either...
            if (
                # That branch is the "typing.Any" catch-all (then this hint is
                # necessarily a subhint of that branch) *OR*...
                other_branch._hint is Any or
                # This hint is a subhint of that branch (according to the
                # subclass-specific implementation of this test)...
                self._is_subhint_branch(other_branch)
            ):
                # Then this hint is a subhint of that hint.
                return True
            # Else, this hint is *NOT* a subhint of that branch. In this case,
            # continue to the next branch of that other hint.
        # Else, this hint is *NOT* a subhint of any branch of that other hint.

        # Return false as a fallback.
        return False


    def _is_subhint_branch(self, branch: 'TypeHint') -> bool:
        '''
        :data:`True` only if this type hint is a subhint of the passed branch of
        another type hint passed to a parent call of the :meth:`is_subhint`
        method, itself called by the :meth:`__le__` dunder method.

        Parameters
        ----------
        branch : TypeHint
            Conditional branch of another type hint to be tested against.

        Raises
        ------
        BeartypeDoorIsSubhintException
            If this type hint and the passed branch are **incommensurable**
            (i.e., incomparable with respect to the subhint relation). This rare
            edge case typically arises due to an unexpected internal issue
            (i.e., bug) within the :mod:beartype.door` API. Computing the
            subhint relation between any two type hints is a surprisingly
            non-trivial decision problem. Unsurprisingly, doing so mostly
            rarely blows up with this exception.

        See Also
        --------
        :meth:`__le__`
            Further details.
        '''
        # print(f'Entering is_subhint_branch({self}, {branch})...')

        # If the type originating this hint is *NOT* a subclass of the type
        # originating that branch, this hint *CANNOT* be a subhint of that
        # branch. Return false immediately.
        if not issubclass(self._origin, branch._origin):
            return False
        # Else, the class originating this hint is a subclass of the class
        # originating that branch. In this case, this hint *COULD* be a subhint
        # of that branch. Further tests are warranted.
        #
        # If that branch is unsubscripted, assume that branch to have been
        # subscripted by "Any". Since *ANY* child hint subscripting this hint is
        # necessarily a subhint of "Any", this hint is a subhint of that branch.
        # Return true immediately.
        elif branch._is_args_ignorable:
            # print(f'is_subhint_branch({self}, {branch} [unsubscripted])')
            return True
        # Else, that branch is subscripted.
        #
        # If that branch is *NOT* also a type hint wrapper of the same subclass
        # as this type hint wrapper, these two wrappers are incommensurable
        # (i.e., *NOT* comparable). Return false immediately.
        elif not isinstance(branch, type(self)):
            return False
        # Else, that branch is also a type hint wrapper of the same subclass
        # as this type hint wrapper, implying these two wrappers are
        # incommensurable (i.e., comparable). In this case, this hint *COULD* be
        # a subhint of that branch. Further tests are warranted.

        # If these two hints are subscripted by a differing number of child
        # hints, raise an exception. Why? Because this rare edge case almost
        # certainly signifies a low-level issue internal to this "beartype.door"
        # subpackage. Silently "accepting" this issue by instead returning a
        # boolean would constitute a false negative or positive. Moreover, the
        # zip() builtin called below silently ignores the trailing portion of
        # the longest iterable exceeding the length of the smallest iterable.
        # Silently permitting that would invite issues throughout this API.
        if len(self._args_wrapped_tuple) != len(branch._args_wrapped_tuple):
            # Number of child hints subscripting these two hints.
            self_args_len = len(self._args_wrapped_tuple)
            branch_args_len = len(branch._args_wrapped_tuple)

            # Raise an exception embedding these numbers.
            raise BeartypeDoorIsSubhintException(
                f'{self} <= {branch} undecidable, as '
                f'{self._hint} and {branch._hint} subscripted by '
                f'differing number of child type hints '
                f'(i.e., {self_args_len} != {branch_args_len}).'
            )
        # Else, these two hints are subscripted by the same number of child
        # hints.

        # For each pair of corresponding child hints subscripting these two
        # hints, encapsulated as type hint wrappers...
        #
        # Note that the zip() builtin has been quantitatively profiled to be
        # approximately as fast as manual iteration (e.g., leveraging some
        # combination of the enumerate(), len(), and range() builtins). Since
        # zip() is likely to be optimized even further *AND* since this approach
        # is substantially more concise, let's go. See also:
        #     https://stackoverflow.com/a/62479781/2809027
        for self_child, branch_child in zip(
            self._args_wrapped_tuple, branch._args_wrapped_tuple):
            # If this child hint is *NOT* a subhint of that child hint, this
            # hint is *NOT* a subhint of that branch. In this case,
            # short-circuit by immediately returning false.
            if not self_child.is_subhint(branch_child):
                return False
            # Else, this child hint is a subhint of that child hint. In this
            # case, this hint *COULD* be a subhint of that branch. Decide by
            # continuing to the next pair of child hints.
        # Else, each child hint of this hint is a subhint of the corresponding
        # child hint of that branch. In this case, this hint is a subhint of
        # that branch.

        # Return true! We have liftoff.
        return True

    # ..................{ PRIVATE ~ properties : read-only   }..................
    # Read-only properties intentionally defining *NO* corresponding setter.

    @property  # type: ignore
    @property_cached
    def _args_wrapped_tuple(self) -> Tuple['TypeHint', ...]:
        '''
        Tuple of the zero or more high-level **child type hint wrappers** (i.e.,
        :class:`TypeHint` instances) wrapping the low-level child type hints
        subscripting (indexing) the low-level parent type hint wrapped by this
        wrapper.

        This attribute is intentionally defined as a memoized property to
        minimize space and time consumption for use cases *not* accessing this
        attribute.
        '''

        # One-liner, don't fail us now!
        return tuple(TypeHint(hint_child) for hint_child in self._args)


    @property  # type: ignore
    @property_cached
    def _args_wrapped_frozenset(self) -> FrozenSet['TypeHint']:
        '''
        Frozen set of the zero or more high-level child **type hint wrappers**
        (i.e., :class:`TypeHint` instances) wrapping the low-level child type
        hints subscripting (indexing) the low-level parent type hint wrapped by
        this wrapper.

        This attribute is intentionally defined as a memoized property to
        minimize space and time consumption for use cases *not* accessing this
        attribute.
        '''

        return frozenset(self._args_wrapped_tuple)


    @property  # type: ignore
    @property_cached
    def _branches(self) -> Iterable['TypeHint']:
        '''
        Immutable iterable of all **branches** (i.e., high-level type hint
        wrappers encapsulating all low-level child type hints subscripting
        (indexing) the low-level parent type hint encapsulated by this
        high-level parent type hint wrappers if this is a union (and thus an
        instance of the :class:`UnionTypeHint` subclass) *or* the 1-tuple
        containing only this instance itself otherwise) of this type hint
        wrapper.

        This property enables the child type hints of both :pep:`484`- and
        :pep:`604`-compliant unions (e.g., :attr:`typing.Union`,
        :attr:`typing.Optional`, and ``|``-delimited type objects) to be handled
        transparently *without* special cases in subclass implementations.
        '''

        # Default to returning the 1-tuple containing only this instance, as
        # *ALL* subclasses except "_HintTypeUnion" require this default.
        return (self,)


    @property  # type: ignore
    @property_cached
    def _is_args_ignorable(self) -> bool:
        '''
        :data:`True` only if this hint is effectively **unsubscripted** (i.e.,
        either indexed by *no* child type hints or only indexed by ignorable
        child type hints).

        If :data:`True`, this hint can be trivially and efficiently evaluated
        by simply inspecting its :attr:`_origin` property. Relevant type hints
        include:

        * Unsubscripted type hint factories (e.g., ``Tuple``, ``Callable``).
        * Type hints subscripted only by ignorable child type hints (e.g.,
          ``Tuple[Any, ...]``, ``Callable[..., Any]``).

        This boolean trivializes comparisons between syntactically unrelated
        type hints that are nonetheless semantically equivalent: e.g.,

        .. code-block:: pycon

           >>> from beartype.door import TypeHint
           >>> from typing import Any, Tuple

           # These type hints are all semantically equivalent despite being
           # mostly syntactically unrelated.
           >>> TypeHint(tuple) == TypeHint(typing.Tuple) == \
           ... TypeHint(typing.Tuple[Any, ...])
           True

        Note that this property is *not* equivalent to the :meth:`is_ignorable`
        property. Although related, a non-ignorable parent type hint can
        trivially have ignorable child type hints (e.g., ``list[Any]``).
        '''

        # Return true only if all child type hints subscripting this parent type
        # hint are themselves ignorable.
        # print(f'[_is_args_ignorable] {self}._args_wrapped_tuple: {self._args_wrapped_tuple}')
        return all(
            hint_child.is_ignorable for hint_child in self._args_wrapped_tuple)
