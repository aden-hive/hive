#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype sanified type hint metadata dataclass** (i.e., class aggregating
*all* metadata returned by :mod:`beartype._check.convert.convmain` functions).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: [SPACE] Memoize the HintSane.__new__() or __init__() constructors. In
#theory, we dimly recall already defining a caching metaclass somewhere in the
#codebase. Perhaps we can simply leverage that to get this trivially done?
#
#Note, however, that keyword arguments will be an issue. We currently
#instantiate "HintSane" objects throughout the codebase by passing keyword
#arguments -- which clearly conflict with memoization. That said, preserving
#keyword argument passing would be *EXTREMELY* beneficial here. Without keyword
#arguments, we lose the flexibility that keyword arguments enable -- especially
#with respect to adding new keyword arguments at some future date.
#
#Perhaps that aforementioned caching metaclass could be augmented to support
#keyword arguments? That would still be better than nothing.
#FIXME: When memoizing, only memoize *CONDITIONALLY.* Notably, there exist two
#common cases here:
#* Context-free "HintSane" instances are initialized with *ONLY* a "hint". They
#  lack contextual metadata and are thus context-free. Unsurprisingly,
#  context-free "HintSane" instances are readily memoizable.
#* Contextual "HintSane" instances are initialized with both a "hint" and one or
#  more supplemental parameters supplying contextual metadata (e.g.,
#  "hint_recursable_to_depth", "typearg_to_hint"). They are *NOT* context-free.
#  Ergo, contextual "HintSane" instances are *NOT* readily memoizable. Don't
#  even bother wasting space or time attempting to do so.
#FIXME: Indeed, the above suggests the following:
#* Trivially conditionally memoize the HintSane.__new__() or __init__()
#  constructors *ONLY* when passed no optional keyword-only parameters (i.e.,
#  *ONLY* when passed the single "hint" parameter positionally).
#
#That's it. Shouldn't be that arduous and should speed things along. *shrug*

# ....................{ IMPORTS                            }....................
from beartype.roar._roarexc import _BeartypeDecorHintSanifyException
from beartype.typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    Iterable,
    List,
    Set,
    Tuple,
    Union,
)
from beartype._data.typing.datatypingport import (
    Hint,
    Pep484612646TypeArgUnpackedToHint,
)
from beartype._data.kind.datakindmap import FROZENDICT_EMPTY
from beartype._util.kind.maplike.utilmapfrozen import FrozenDict
from beartype._util.utilobjmake import permute_object

# ....................{ HINTS                              }....................
FrozenDictHintToInt = Dict[Hint, int]
'''
PEP-compliant type hint matching any dictionary itself mapping from
PEP-compliant type hints to integers.

Caveats
-------
This hint currently erroneously matches mutable rather than immutable
dictionaries. While the latter would be preferable, Python lacks a builtin
immutable dictionary type and thus support for typing such types. So it goes.
'''

# ....................{ CLASSES                            }....................
#FIXME: Unit test us up, please.
class HintSane(object):
    '''
    **Sanified type hint metadata** (i.e., immutable and thus hashable object
    encapsulating *all* metadata returned by
    :mod:`beartype._check.convert.convmain` sanifiers after sanitizing a
    possibly PEP-noncompliant hint into a fully PEP-compliant hint).

    For efficiency, sanifiers only conditionally return this metadata for the
    proper subset of hints associated with this metadata; since most hints are
    *not* associated with this metadata, sanifiers typically only return a
    sanified type hint (rather than both that hint *and* this metadata).

    Caveats
    -------
    **Callers should avoid modifying this metadata.** For efficiency, this class
    does *not* explicitly prohibit modification of this metadata. Nonetheless,
    this class is implemented under the assumption that callers *never* modify
    this metadata. This metadata is effectively frozen. Any attempts to modify
    this metadata *will* induce nondeterminism throughout :mod:`beartype`,
    especially in memoized callables accepting and/or returning this metadata.

    Attributes
    ----------
    hint : Hint
        Type hint sanified (i.e., sanitized) from a possibly insane type hint
        into a hopefully sane type hint by a
        :mod:`beartype._check.convert.convmain` function.
    hint_recursable_to_depth : FrozenDictHintToInt
        Recursion guard implemented as a frozen dictionary mapping from each
        **transitive recursable parent hint** (i.e., direct or indirect parent
        hint of this sanified type hint such that that parent hint explicitly
        supports recursion) to that parent hint's **recursion depth** (i.e.,
        total number of times that parent hint has been visited during the
        current search from the root type hint down to this sanified type hint).
        If a subsequently visited child hint subscripting this hint already
        resides in this recursion guard, that child hint has already been
        visited by prior iteration and is thus recursive. Since recursive hints
        are valid (rather than constituting an unexpected error), the caller is
        expected to detect this use case and silently short-circuit infinite
        recursion by avoiding revisiting previously visited recursive hints.
    typearg_to_hint : Pep484612646TypeArgUnpackedToHint
        **Type parameter lookup table** (i.e., immutable dictionary mapping from
        the **type parameter** (i.e., :pep:`484`-compliant type variable or
        :pep:`646`-compliant unpacked type variable tuple) originally
        parametrizing the origins of all transitive parent hints of this hint if
        any to the corresponding child hints subscripting those parent hints).
        This table enables :func:`beartype.beartype` to efficiently reduce a
        proper subset of type parameters to non-type parameters at decoration
        time, including:

        * :pep:`484`- or :pep:`585`-compliant **subscripted generics.** For
          example, this table enables runtime type-checkers to reduce the
          semantically useless pseudo-superclass ``list[T]`` to the
          semantically useful pseudo-superclass ``list[int]`` at decoration time
          in the following example:

          .. code-block:: python

             class MuhGeneric[T](list[T]): pass

             @beartype
             def muh_func(muh_arg: MuhGeneric[int]) -> None: pass

        * :pep:`695`-compliant **subscripted type aliases.** For example, this
          table enables runtime type-checkers to reduce the semantically useless
          type hint ``muh_type_alias[float]`` to the semantically useful type
          hint ``float | int`` at decoration time in the following example:

          .. code-block:: python

             type muh_type_alias[T] = T | int

             @beartype
             def muh_func(muh_arg: muh_type_alias[float]) -> None: pass
    _hash : int
        Hash identifying this object, precomputed for efficiency.
    '''

    # ..................{ CLASS VARIABLES                    }..................
    # Slot all instance variables defined on this object to minimize the time
    # complexity of both reading and writing variables across frequently
    # called @beartype decorations. Slotting has been shown to reduce read and
    # write costs by approximately ~10%, which is non-trivial.
    __slots__ = (
        'hint',
        'hint_recursable_to_depth',
        'typearg_to_hint',
        '_hash',
    )


    # Squelch false negatives from mypy. This is absurd. This is mypy. See:
    #     https://github.com/python/mypy/issues/5941
    if TYPE_CHECKING:
        hint: Hint
        hint_recursable_to_depth: FrozenDictHintToInt
        typearg_to_hint: Pep484612646TypeArgUnpackedToHint


    _INIT_ARG_NAMES = frozenset((
        var_name
        for var_name in __slots__
        # Ignore private slotted instance variables defined above.
        if not var_name.startswith('_')
    ))
    '''
    Frozen set of the names of all parameters accepted by the :meth:`init`
    method, defined as the frozen set comprehension of all public slotted
    instance variables of this class.

    This frozen set enables efficient membership testing.
    '''

    # ..................{ INITIALIZERS                       }..................
    def __init__(
        self,

        # Mandatory parameters.
        hint: Hint,

        # Optional keyword-only parameters.
        *,
        hint_recursable_to_depth: FrozenDictHintToInt = FROZENDICT_EMPTY,
        typearg_to_hint: Pep484612646TypeArgUnpackedToHint = FROZENDICT_EMPTY,
    ) -> None:
        '''
        Initialize this sanified type hint metadata with the passed parameters.

        Parameters
        ----------
        hint : Hint
            Type hint sanified (i.e., sanitized) from a possibly insane type
            hint into a hopefully sane type hint by a
            :mod:`beartype._check.convert.convmain` function.
        hint_recursable_to_depth : FrozenDictHintToInt, default: FROZENDICT_EMPTY
            Recursion guard implemented as a frozen dictionary mapping from each
            **transitive recursable parent hint** (i.e., direct or indirect
            parent hint of this sanified type hint such that that parent hint
            explicitly supports recursion) to that parent hint's **recursion
            depth** (i.e., total number of times that parent hint has been
            visited during the current search from the root type hint down to
            this sanified type hint). Defaults to the empty frozen dictionary.
        typearg_to_hint : Pep484612646TypeArgUnpackedToHint, default: FROZENDICT_EMPTY
            **Type variable lookup table** (i.e., immutable dictionary mapping
            from the **type variables** (i.e., :pep:`484`-compliant
            :class:`typing.TypeVar` objects) originally parametrizing the
            origins of all transitive parent hints of this hint if any to the
            corresponding child hints subscripting those parent hints). Defaults
            to the empty frozen dictionary.

        See the class docstring for further details.
        '''
        assert isinstance(hint_recursable_to_depth, FrozenDict), (
            f'{repr(hint_recursable_to_depth)} not frozen dictionary.')
        assert isinstance(typearg_to_hint, FrozenDict), (
            f'{repr(typearg_to_hint)} not frozen dictionary.')

        # Classify all passed parameters as instance variables.
        self.hint = hint
        self.hint_recursable_to_depth = hint_recursable_to_depth
        self.typearg_to_hint = typearg_to_hint

        # Hash identifying this object, precomputed for efficiency.
        self._hash = hash((hint, hint_recursable_to_depth, typearg_to_hint))

    # ..................{ DUNDERS                            }..................
    def __hash__(self) -> int:
        '''
        Hash identifying this sanified type hint metadata.

        Returns
        -------
        int
            This hash.
        '''

        return self._hash


    def __eq__(self, other: object) -> bool:
        '''
        :data:`True` only if this sanified type hint metadata is equal to the
        passed arbitrary object.

        Parameters
        ----------
        other : object
            Arbitrary object to be compared for equality against this metadata.

        Returns
        -------
        Union[bool, type(NotImplemented)]
            Either:

            * If this other object is also sanified type hint metadata, either:

              * If these metadatum share equal instance variables, :data:`True`.
              * Else, :data:`False`.

            * Else, :data:`NotImplemented`.
        '''

        # Return either...
        return (
            # If this other object is also sanified hint metadata, true only
            # if these metadatum share the same instance variables;
            (
                self.hint == other.hint and
                self.hint_recursable_to_depth == other.hint_recursable_to_depth and
                self.typearg_to_hint == other.typearg_to_hint
            )
            if isinstance(other, HintSane) else
            # Else, this other object is *NOT* also sanified hint metadata. In
            # this case, the standard singleton informing Python that this
            # equality comparator fails to support this comparison.
            NotImplemented  # type: ignore[return-value]
        )


    def __repr__(self) -> str:
        '''
        Machine-readable representation of this metadata.
        '''

        # If this metadata is the ignorable "HINT_SANE_IGNORABLE" singleton,
        # trivially return the unqualified basename of this singleton for
        # debuggability, disambiguity, and readability.
        if self is HINT_SANE_IGNORABLE:
            return 'HINT_SANE_IGNORABLE'
        # Else, this metadata is *NOT* the ignorable "HINT_SANE_IGNORABLE" singleton.

        # Represent this metadata with just the minimal subset of metadata
        # needed to reasonably describe this metadata.
        return (
            f'{self.__class__.__name__}('
            f'hint={repr(self.hint)}, '
            f'hint_recursable_to_depth={repr(self.hint_recursable_to_depth)}, '
            f'typearg_to_hint={repr(self.typearg_to_hint)}'
            f')'
        )

    # ..................{ PERMUTERS                          }..................
    def permute_sane(self, **kwargs) -> 'HintSane':
        '''
        Shallow copy of this metadata such that each passed keyword parameter
        overwrites the instance variable of the same name in this copy.

        Parameters
        ----------
        Keyword parameters of the same name and type as instance variables of
        this object (e.g., ``hint: Hint``, ``typearg_to_hint:
        Pep484612646TypeArgUnpackedToHint``).

        Returns
        -------
        HintSane
            Shallow copy of this metadata such that each keyword parameter
            overwrites the instance variable of the same name in this copy.

        Raises
        ------
        _BeartypeDecorHintSanifyException
            If the name of any passed keyword parameter is *not* that of an
            existing instance variable of this object.
        '''

        # Set us up the permutation! Make your time!
        return permute_object(
            obj=self,
            init_arg_name_to_value=kwargs,
            init_arg_names=self._INIT_ARG_NAMES,
            exception_cls=_BeartypeDecorHintSanifyException,
        )

# ....................{ GLOBALS                            }....................
HINT_IGNORABLE = Any
'''
**Ignorable sanified type hint** (i.e., singleton :class:`.Any` type hint
encapsulated by the metadata to which *all* deeply or shallowly ignorable type
hints are reduced by :mod:`beartype._check.convert.convmain` sanifiers).
'''


HINT_SANE_IGNORABLE = HintSane(hint=HINT_IGNORABLE)
'''
**Ignorable sanified type hint metadata** (i.e., singleton :class:`.HintSane`
instance to which *all* deeply or shallowly ignorable type hints are reduced by
:mod:`beartype._check.convert.convmain` sanifiers).

This singleton enables callers to trivially differentiate ignorable from
unignorable hints. After sanification, if a hint is sanified to:

* Literally this singleton, then that hint is ignorable.
* Any other object, then that hint is unignorable.
'''


HINT_SANE_RECURSIVE = HintSane(hint=HINT_IGNORABLE)
'''
**Recursive sanified type hint metadata** (i.e., singleton :class:`.HintSane`
instance to which **deeply recursive type hints** (i.e., recursive type hints
whose reducers recursively expand to at least two levels of of recursion) are
reduced by :mod:`beartype._check.convert.convmain` sanifiers).

This singleton enables callers to trivially differentiate deeply recursive from
ignorable hints. While deeply recursive hints are ignorable in *most* contexts,
deeply recursive hints are unignorable in other contexts (e.g., when child hints
of parent unions). Differentiating between these two cases thus requires a
distinct singleton from the comparable and significantly more common
:data:`.HINT_SANE_IGNORABLE` singleton.

After sanification, if a hint is sanified to:

* Literally this singleton, then that hint is deeply recursive.
* Any other object, then that hint is *not* deeply recursive.
'''

# ....................{ HINTS                              }....................
HintOrSane = Union[Hint, HintSane]
'''
PEP-compliant type hint matching either a type hint *or* **sanified type hint
metadata** (i.e., :class:`.HintSane` object).
'''

# ....................{ HINTS ~ container                  }....................
DictHintSaneToAny = Dict[HintSane, Any]
'''
PEP-compliant type hint matching a dictionary mapping from keys that are
**sanified type hint metadata** (i.e., :class:`.HintSane` objects) to arbitrary
objects.
'''


IterableHintSane = Iterable[HintSane]
'''
PEP-compliant type hint matching an iterable of zero or more **sanified type
hint metadata** (i.e., :class:`.HintSane` objects).
'''


ListHintOrSane = List[HintOrSane]
'''
PEP-compliant type hint matching a list of zero or more items, each of which is
either a type hint *or* **sanified type hint metadata** (i.e.,
:class:`.HintSane` object).
'''


ListHintSane = List[HintSane]
'''
PEP-compliant type hint matching a list of zero or more **sanified type hint
metadata** (i.e., :class:`.HintSane` objects).
'''


SetHintSane = Set[HintSane]
'''
PEP-compliant type hint matching a set of zero or more **sanified type hint
metadata** (i.e., :class:`.HintSane` objects).
'''


TupleHintSane = Tuple[HintSane, ...]
'''
PEP-compliant type hint matching a tuple of zero or more **sanified type hint
metadata** (i.e., :class:`.HintSane` objects).
'''
