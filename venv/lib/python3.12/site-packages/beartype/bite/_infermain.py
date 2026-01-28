#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype Inferential Type-hint Engine (BITE) type hint inferrers** (i.e.,
high-level functions dynamically inferring the type hints best describing
arbitrary objects).
'''

# ....................{ IMPORTS                            }....................
from beartype.bite.kind.infercallable import infer_hint_callable
from beartype.bite.kind.inferthirdparty import infer_hint_thirdparty
from beartype.bite.collection.infercollectionbuiltin import (
    infer_hint_collection_builtin)
from beartype.bite.collection.infercollectionsabc import (
    infer_hint_collections_abc)
from beartype.roar import BeartypeDoorInferHintRecursionWarning
from beartype.typing import (
    Callable,
    Optional,
    Tuple,
    Type,
)
from beartype._conf.confmain import BeartypeConf
from beartype._conf.confcommon import get_beartype_conf_strategy_on
from beartype._conf.conftest import die_unless_conf
from beartype._data.cls.datacls import TYPES_BUILTIN_SCALAR
from beartype._data.typing.datatyping import FrozenSetInts
from beartype._data.kind.datakindset import FROZENSET_EMPTY
from beartype._util.error.utilerrwarn import issue_warning
from beartype._util.hint.pep.utilpeptest import is_hint_pep
from beartype._util.text.utiltextrepr import represent_object

# ....................{ CLASSES                            }....................
class BeartypeInferHintContainerRecursion(object):
    '''
    Child type hint subscripting all **recursive container type hints** (i.e.,
    parent type hints describing a container containing one or more items
    self-referentially referring to the same container).
    '''

    def __repr__(self) -> str:
        return 'RecursiveContainer'

# ....................{ INFERERS                           }....................
def infer_hint(
    # Mandatory parameters.
    obj: object,

    # Optional keyword-only parameters.
    *,
    conf: Optional[BeartypeConf] = None,

    # Optional keyword-only hidden parameters. *GULP*
    __beartype_obj_ids_seen__: FrozenSetInts = FROZENSET_EMPTY,
) -> object:
    '''
    Type hint annotating the passed object.

    This function dynamically infers (i.e., computes, decides, deduces) a type
    hint sufficient for annotating (i.e., describing, matching, validating) the
    passed object.

    Caveats
    -------
    **This function explicitly guards against infinite recursion.** Notably,
    this function accepts **recursive containers** (i.e., pure-Python containers
    containing one or more items whose values self-referentially refer to the
    same containers). When passed a recursive container, this function guards
    against infinite recursion that would otherwise be induced by that container
    by instead returning a placeholder instance of the
    :class:`.BeartypeInferHintRecursion` class describing this recursion: e.g.,

    .. code-block:: python

       # Define a trivial recursive list.
       >>> recursive_list = ['this is fine', b'this is fine too, but...',]
       >>> recursive_list.append(recursive_list)

       # Infer the type hint annotating this list.
       >>> from beartype.bite import infer_hint
       >>> infer_hint(recursive_list)
       ##FIXME: INSERT SANE REPR HERE, PLEASE. *sigh*

    **This function exhibits best-, average-, and worst-case** :math:`O(n)`
    **linear-time complexity** for :math:`n` the number of nested items
    transitively contained in the passed object if this object is a container.
    This differs from most of the public :mod:`beartype` API, which exhibits at
    worst worst-case amortized :math:`O(1)` constant-time complexity. Although
    this function could certainly be generalized to support that sort of
    constant-time complexity, doing so would be largely pointless. Type hint
    inference only has real-world value insofar as it accurately infers hints.
    Inference operating in :math:`O(1)` time would necessarily be inaccurate and
    thus of *no* real-world value. Inference operating in :math:`O(n)` time, on
    the other hand, accurately infers hints for even arbitrarily large
    pure-Python containers by introspecting all objects transitively reachable
    from those containers.

    **This function cannot be reasonably memoized** (e.g., via the
    :func:`beartype._util.cache.utilcachecall.callable_cached` decorator).
    Technically, this function *could* be memoized... *sorta.* Pragmatically,
    this function *cannot* be memoized. Most arbitrary objects are mutable and
    thus unhashable and thus unmemoizable. While feasible, memoizing this
    function for the small subset of arbitrary objects that are immutable would
    dramatically increase the space complexity of this function. In short,
    memoizing arbitrary objects is effectively infeasible.

    Parameters
    ----------
    obj : object
        Arbitrary object to infer a type hint from.
    conf : BeartypeConf, optional
        **Beartype configuration** (i.e., self-caching dataclass encapsulating
        all settings configuring type-checking for the passed object). Defaults
        to ``BeartypeConf(strategy=BeartypeStrategy.On))``, the default
        :math:`O(n)` linear-time configuration. Why not the default
        :math:`O(1)` constant-time configuration like the remainder of the
        :mod:`beartype` codebase? Because type hints are *typically* only useful
        when perfectly describing the internal structure of objects; type hints
        that imperfectly describe the internal structure of objects induce
        **false positives** (i.e., cause both static and runtime type-checkers
        to improperly emit errors and raise exceptions for otherwise valid
        objects that would have satisfied those hints had those hints more
        perfectly described the internal structure of those objects). Exceptions
        do exist, however. Downstream third-party consumers that only call this
        function to create an temporary in-memory type hint that is then passed
        to other runtime type-checking functionality (e.g.,
        :func:`beartype.bite.is_bearable`, :func:`beartype.bite.is_subhint`)
        often benefits from :math:`O(1)` constant-time type hint inference.
    __beartype_obj_ids_seen__ : FrozenSet[int]
        **Recursion guard** (i.e., frozen set of the integers uniquely
        identifying all previously visited containers passed as the ``obj``
        parameter to some recursive parent call of this same function on the
        current call stack). If the integer identifying a passed object already
        resides in this recursion guard, that object has already been visited by
        a prior call to this function in the same call stack and is thus a
        recursive container; in that case, this function short-circuits infinite
        recursion by returning a placeholder instance of the
        :class:`.BeartypeInferHintRecursion` class describing this issue.

    Returns
    -------
    object
        Type hint inferred from the passed object.

    Warns
    -----
    BeartypeDoorInferHintRecursionWarning
        On detecting that the passed object is **recursive** (i.e.,
        self-referentially refers to itself, typically due to being a container
        containing one or more items that self-referentially refer to that same
        container).

    Raises
    ------
    BeartypeConfException
        If the passed ``conf`` parameter is *not* a beartype configuration.
    '''

    # ....................{ PREAMBLE                       }....................
    # If the integer uniquely identifying this object already resides in this
    # recursion guard, this object has already been visited by a prior call to
    # this function in the same call stack and is thus a recursive container.
    # In this case...
    if id(obj) in __beartype_obj_ids_seen__:
        # Emit a non-fatal warning informing the caller.
        issue_warning(
            cls=BeartypeDoorInferHintRecursionWarning,
            message=(
                f'Container recursion detected; short-circuiting for safety. '
                f'Container {represent_object(obj)} self-referentially '
                f'contains itself as an item.'
            ),
        )

        # Short-circuit infinite recursion by creating and returning a
        # placeholder instance of a dataclass describing this situation.
        return BeartypeInferHintContainerRecursion
    # Else, this object has yet to be visited.

    # If the caller explicitly passed *NO* configuration, default to the default
    # linear-time configuration.
    if conf is None:
        conf = get_beartype_conf_strategy_on()
    # Else, the caller explicitly passed a configuration.

    # If this configuration is invalid, raise an exception.
    die_unless_conf(conf)
    # Else, this configuration is valid.

    # ....................{ PEP                            }....................
    #FIXME: Generalize to support iterable parametrized generics (e.g.,
    #instances of "Generic[T]" subclasses); iterable parametrized generics
    #should be subscripted by a child type hint describing the items contained
    #by those iterables. For example, when this function is passed an instance
    #of a "List[T]" subclass, this function should return "List[hints_child]"
    #where "hints_child" is the union of the types of all items of this list.
    #
    #Doing so will require explicitly detecting generics here. *sigh*

    # If this object is a PEP-compliant type hint, this object is trivially
    # satisfied by itself. Interestingly:
    # * This includes the "None" singleton, which is a PEP 484-compliant type
    #   hint whose beartype sign is "HintSignNone".
    #
    # Note that PEP-compliant type hints are intentionally detected and
    # short-circuited first *BEFORE* any further inference. Why? Because
    # subjecting PEP-compliant type hints to any inference typically destroys
    # those hints. For example:
    # * Many PEP-compliant type hints are types. Subjecting these hints to
    #   further inference would incorrectly infer the hints for these hints as
    #   "Type[obj]" rather than "obj".
    #
    # Specifically, if...
    if (
        # This object is a PEP-compliant type hint *AND*...
        is_hint_pep(obj) and
        # This object is *NOT* a string. There exists an ambiguity here. Under
        # PEP 484, any string that is a type hint is a stringified forward
        # reference to another PEP-compliant hint that typically has yet to be
        # defined. However, unconditionally inferring *ALL* strings to be PEP
        # 484-compliant stringified forward references here would coerce
        # container items that are simple strings into references. Since doing
        # so would strongly conflict with common sense and sane semantics, this
        # function preserves strings as simple PEP-noncompliant objects.
        not isinstance(obj, str)
    ):
        # Return this PEP-compliant type hint as is.
        return obj
    # Else, this object is *NOT* a PEP-compliant type hint.

    # ....................{ PEP [484|585]                  }....................
    # If this object is a type, this type is trivially satisfied by a PEP 484-
    # or 585-compliant subclass type hint subscripted by this type.
    elif isinstance(obj, type):
        return Type[obj]
    # Else, this object is *NOT* a type.
    #
    # If this object is callable, defer to this lower-level function inferring a
    # "typing.Callable[...]" type hint from this callable.
    elif callable(obj):
        return infer_hint_callable(obj)
    # Else, this object is uncallable.

    # ....................{ NON-PEP ~ scalar               }....................
    # Type of this object.
    obj_type = obj.__class__

    # If this object is a builtin scalar (e.g., integer, string), return this
    # type as is.
    #
    # Note that this is *NOT* simply a negligible optimization, although it
    # certainly is that as well. This is an essential sanity check to ensure
    # that strings are annotated as the builtin "str" type rather than the
    # recursive "collections.abc.Sequence[str]" type hint, which they otherwise
    # would be. Since strings are infinitely recursively immutable sequences of
    # immutable sequences, this detection avoids *INSANE* infinite recursion.
    if obj_type in TYPES_BUILTIN_SCALAR:
        return obj_type
    # Else, this object is *NOT* a builtin scalar.

    # ....................{ INFER                          }....................
    # For each lower-level hint inferer...
    for hint_inferer in _HINT_INFERERS:
        # print(f'Inferring {repr(obj)} hint via inferer {repr(hint_inferer)}...')

        # Hint inferred by this inferer as validating this object if this
        # inferer inferred such a hint *OR* "None" otherwise (i.e., if this
        # inferer failed to infer a hint for this object).
        hint = hint_inferer(  # type: ignore[call-arg]
            obj=obj,
            conf=conf,
            __beartype_obj_ids_seen__=__beartype_obj_ids_seen__,
        )

        # If this inferer inferred a hint for this object, return this hint.
        if hint is not None:
            return hint
        # Else, this inferer inferred *NO* hint for this object. In this case,
        # silently continue to the next hint inferer and hope for better joy.
    # Else, *NO* inferer inferred a hint for this object. We tried, people.

    # ....................{ FALLBACK                       }....................
    # Return this type as a last-ditch fallback. By definition, *ANY* object is
    # trivially satisfied by a type hint that is the type of that object (e.g.,
    # the integer "42" is trivially satisfied by the builtin type "int").
    return obj_type

# ....................{ PRIVATE ~ constants                }....................
_HINT_INFERERS: Tuple[Callable, ...] = (
    # Builtin collections should typically (but *NOT* always, interestingly) be
    # annotated as builtin collection type hints. For example:
    # * Lists satisfy the "collections.abc.MutableSequence" protocol, but are
    #   better annotated as fine-grained "list[...]" type hints rather than as
    #   coarse-grained "collections.abc.MutableSequence[...]" type hints.
    #
    # Exceptions include:
    # * Dictionary keys views (e.g., "{'ugh': 42}.keys()"), which are actually
    #   set instances but still better annotated as fine-grained
    #   "collections.abc.KeysView[...]" type hints rather than as coarse-grained
    #   "set[...]" type hints.
    #
    # This inferer is intentionally listed first to force this prioritization.
    infer_hint_collection_builtin,

    # Non-standard popular third-party objects (e.g., NumPy arrays, PyTorch
    # tensors) should often (but *NOT* always, interestingly) be annotated as
    # PEP 593-compliant "typing(|_extensions).Annotated[...]" type hints
    # inferring both the types *AND* well-known metadata associated with those
    # types (e.g., dimensionality, dtypes, shapes).
    #
    # This inferer is intentionally listed next to force this prioritization.
    infer_hint_thirdparty,

    # User-defined collections satisfying standard "collections.abc" protocols
    # should often (but *NOT* always, interestingly) be annotated as
    # "collections.abc" type hints.
    #
    # This inferer is intentionally listed last to deprioritize this form of
    # coarse-grained inference in favour of more fine-grained inferers.
    infer_hint_collections_abc,
)
'''
Tuple of all **type hint inferers** (i.e., lower-level functions inferring the
type hint for the passed object according to some function-specific heuristic).

Each item of this set is a function accepting an arbitrary object ``obj`` and
the recursion guard ``__beartype_obj_ids_seen__`` and returning either the type
hint inferred validating that object *or* :data:`None` if that function failed
to infer such a type hint. Specifically, each function has a signature
resembling:

.. code-block:: python

   def infer_hint_{heuristic}(
       obj: object, __beartype_obj_ids_seen__: FrozenSetInts) -> Optional[object]:
'''
