#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype Inferential Type-hint Engine (BITE) builtin collections type hint
inferrers** (i.e., lower-level functions dynamically inferring subscripted type
hints describing instances of builtin C-based container types).
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Dict,
    ChainMap,
    Counter,
    Deque,
    FrozenSet,
    KeysView,
    List,
    Optional,
    Set,
    Tuple,
    ValuesView,
)
from beartype._cave._cavefast import (
    DictKeysViewType,
    DictValuesViewType,
)
from beartype._data.typing.datatyping import (
    DictTypeToAny,
)
from beartype._util.cache.utilcachecall import callable_cached
from collections import (
    ChainMap as ChainMapType,
    Counter as CounterType,
    deque,
)

# ....................{ INFERERS                           }....................
def infer_hint_collection_builtin(obj: object, **kwargs) -> Optional[object]:
    '''
    **Builtin collection type hint** (i.e., subscripted C-based type whose
    instances contain one or more reiterable items) recursively validating the
    passed object (including *all* items transitively reachable from this
    object) if this object is an instance of a builtin collection type *or*
    :data:`None` otherwise (i.e., if this object is *not* an instance of a
    builtin collection type).

    This function *cannot* be memoized, due to necessarily accepting the
    ``__beartype_obj_ids_seen__`` parameter unique to each call to the parent
    :func:`beartype.bite.infer_hint` function. Moreover, this function exhibits
    worst-case constant time complexity :math:`O(1)`; memoization is irrelevant.

    Parameters
    ----------
    obj : object
        Object to infer a type hint from.

    All remaining keyword parameters are passed as is to the lower-level
    :func:`beartype.bite.collection.infercollectionitems.infer_hint_collection_items`
    function.

    Returns
    -------
    Optional[object]
        Either:

        * If this object is a builtin collection type, this type subscripted by
          the union of the child type hints validating *all* items of this
          collection (e.g., ``list[str]``).
        * Else, :data:`None`.
    '''

    # Hint to be returned, defaulting to "None" as a fallback.
    hint: object = None

    # Type of this object.
    obj_type = obj.__class__
    # print(f'Inferring possibly builtin collection type {repr(obj_type)}...')

    # Type hint factory creating type hints validating this type if this
    # type is a subclass of a builtin collection type *OR* "None" otherwise.
    hint_factory = _infer_hint_factory_collection_builtin(obj_type)

    # If this type is a subclass of a builtin collection type...
    if hint_factory:
        # print(f'Inferring iterable {repr(obj_type_collections_abc)} subscription...')

        # Avoid circular import dependencies.
        from beartype.bite.collection.infercollectionitems import (
            infer_hint_collection_items)

        # Hint recursively validating this collection (including *ALL* items
        # transitively reachable from this collection), defined by subscripting
        # this collection type by the union of the child type hints validating
        # all items recursively reachable from this collection.
        hint = infer_hint_collection_items(
            obj=obj, hint_factory=hint_factory, **kwargs,)  # type: ignore[arg-type]
    # Else, this type is *NOT* a subclass of a builtin collection type. In this
    # case, fallback to returning "None".

    # Return this hint.
    return hint

# ....................{ PRIVATE ~ inferers                 }....................
@callable_cached
def _infer_hint_factory_collection_builtin(cls: type) -> Optional[object]:
    '''
    **Builtin collection superclass** (i.e., unsubscripted C-based type whose
    instances contain one or more reiterable items) of the passed class if this
    class subclasses a builtin collection type *or* :data:`None` otherwise
    (i.e., if this class does *not* subclass a builtin collection type).

    This function does *not* return a type hint annotating the passed class.
    This function merely returns a subscriptable type hint factory suitable for
    the caller to subscript with a child type hint, which then produces the
    desired type hint annotating the passed class. Why this indirection? In a
    word: efficiency. If this function recursively inferred and returned a full
    type hint, this function would need to guard against infinite recursion by
    accepting the ``__beartype_obj_ids_seen__`` parameter also accepted by the
    parent :func:`beartype.bite.inferhint.infer_hint` function;
    doing so would prevent memoization, substantially reducing efficiency.

    This function is memoized for efficiency.

    Parameters
    ----------
    cls : type
        Class to be introspected.

    Returns
    -------
    Optional[object]
        Either:

        * If this class subclasses a builtin collection type, the type hint
          factory validating that type.
        * Else, :data:`None`.
    '''
    assert isinstance(cls, type), f'{repr(cls)} not type.'

    # ....................{ IS                             }....................
    # Hint factory describing this class if this class is a builtin collection
    # type (e.g., "list", "tuple") *OR* "None" otherwise.
    hint_factory: object = _COLLECTION_BUILTIN_TYPE_TO_HINT_FACTORY_get(cls)

    # If this class is a builtin collection type, return this hint factory.
    if hint_factory:
        # print(f'Inferred builtin collection {repr(cls)} factory {repr(hint_factory)}...')
        return hint_factory
    # Else, this class is *NOT* a builtin collection type. However, this class
    # could still be a proper subclass of a builtin collection type: e.g.,
    #     class MuhList(list): ...
    #
    # Further logic is required to detect which collection type this class
    # subclasses if any.

    # ....................{ SUBCLASS                       }....................
    # Set of all superclasses of the passed class (including the passed class,
    # which is of course its own superclass *AND* subclass, because set theory
    # just goes hard like that).
    #
    # Note that this includes the irrelevant root "object" superclass, which is
    # *NOT* a builtin collection type and is thus guaranteed to *NEVER* be
    # matched below. Although that superclass *COULD* be trivially sliced off
    # (e.g., with an assignment resembling "classes = set(cls.__mro__[:-1])"),
    # doing so only uselessly consumes more time than it saves. So it goes.
    types = set(cls.__mro__)

    # Intersection of the set of all superclasses of this class with the set of
    # all builtin collection types.
    types_collection_builtin = types & _COLLECTION_BUILTIN_TYPES

    # Return either...
    return (
        # If this intersection is non-empty, this class subclasses one or more
        # builtin collection types. In this case, reduce to this class as is.
        # Since *ALL* builtin containers types are PEP 585-compliant
        # subscriptable type hint factories under Python >= 3.9 (e.g.,
        # "list[str]") and since this class subclasses a builtin container type,
        # this subclass is necessarily also implicitly a PEP 585-compliant
        # subscriptable type hint factory.
        cls
        if types_collection_builtin else
        # Else, this intersection is empty, implying this class does *NOT*
        # subclass a builtin collection type. In this case, reduce to a noop.
        None
    )

# ....................{ PRIVATE ~ mappings                 }....................
#FIXME: Also add:
#* "ItemsView". Actually, "ItemsView" support will probably have to be
#  implemented manually. "ItemsViews" are really just iterables over 2-tuples.

# Note that key-value pairs are intentionally defined in decreasing order of
# real-world commonality to reduce time costs in the average case for downstream
# functions leveraging this dictionary (e.g., the
# beartype.bite.collection.infercollectionbuiltin.infer_hint_collection_builtin()
# function).
_COLLECTION_BUILTIN_TYPE_TO_HINT_FACTORY: DictTypeToAny = {
    # Single-argument builtin reiterable types (i.e., C-based collections whose
    # hint factories are subscriptable by only a single child type hint).
    tuple: Tuple,
    list: List,
    frozenset: FrozenSet,
    set: Set,
    deque: Deque,
    DictKeysViewType: KeysView,
    DictValuesViewType: ValuesView,

    # Dual-argument builtin mapping types (i.e., C-based collections whose hint
    # factories are subscriptable by a pair of child key and value type hints).
    dict: Dict,
    ChainMapType: ChainMap,
    CounterType: Counter,
}
'''
Dictionary mapping from each **builtin collection type** (i.e., C-based type
satisfying the :class:`collections.abc.Collection` protocol described by a
corresponding type hint factory) to that factory.
'''


_COLLECTION_BUILTIN_TYPE_TO_HINT_FACTORY_get = (
    _COLLECTION_BUILTIN_TYPE_TO_HINT_FACTORY.get)
'''
:meth:`._COLLECTION_BUILTIN_TYPE_TO_HINT_FACTORY.get` method, globalized for
negligible efficiency gains.
'''


_COLLECTION_BUILTIN_TYPE_TO_HINT_FACTORY_ITEMS = (
    _COLLECTION_BUILTIN_TYPE_TO_HINT_FACTORY.items())
'''
Iterable of all builtin collection types (e.g., :class:`list`) and the type hint
factories describing those types (e.g., :obj:`typing.List`).
'''

# ....................{ PRIVATE ~ sets                     }....................
_COLLECTION_BUILTIN_TYPES = _COLLECTION_BUILTIN_TYPE_TO_HINT_FACTORY.keys()
'''
Set of all **builtin collection types** (i.e., C-based types satisfying the
:class:`collections.abc.Collection` protocol).
'''
