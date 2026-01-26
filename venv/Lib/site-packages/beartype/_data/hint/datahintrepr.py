#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **bare PEP-compliant type hint representations** (i.e., global
constants pertaining to machine-readable strings returned by the :func:`repr`
builtin suffixed by *no* "["- and "]"-delimited subscription representations).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    # Dict,
    Set,
)
from beartype._data.typing.datatyping import (
    DictStrToHintSign,
    FrozenSetStrs,
    HintSignTrie,
)
from beartype._data.hint.sign.datahintsigns import (
    HintSignAbstractSet,
    HintSignAsyncContextManager,
    HintSignAsyncIterable,
    HintSignAsyncIterator,
    HintSignAsyncGenerator,
    HintSignAwaitable,
    HintSignBinaryIO,
    HintSignByteString,
    HintSignCallable,
    HintSignChainMap,
    HintSignCollection,
    HintSignContainer,
    HintSignCoroutine,
    HintSignContextManager,
    HintSignCounter,
    HintSignDefaultDict,
    HintSignDeque,
    HintSignDict,
    HintSignFrozenSet,
    HintSignGenerator,
    HintSignItemsView,
    HintSignIterable,
    HintSignIterator,
    HintSignKeysView,
    HintSignList,
    HintSignMapping,
    HintSignMappingView,
    HintSignMatch,
    HintSignMutableMapping,
    HintSignMutableSequence,
    HintSignMutableSet,
    HintSignNumpyArray,
    HintSignOrderedDict,
    HintSignPanderaAny,
    HintSignPep484585GenericUnsubbed,
    HintSignReversible,
    HintSignSequence,
    HintSignSet,
    HintSignPattern,
    HintSignTextIO,
    HintSignTuple,
    HintSignType,
    HintSignUnion,
    HintSignValuesView,
)

# ....................{ MAPPINGS ~ repr                    }....................
# The majority of this dictionary is initialized with automated inspection below
# in the _init() function. The *ONLY* key-value pairs explicitly defined here
# are those *NOT* amenable to such inspection.
HINT_REPR_PREFIX_ARGS_0_OR_MORE_TO_SIGN: DictStrToHintSign = {
    # ..................{ PEP 484                            }..................
    # All other PEP 484-compliant representation prefixes are defined by
    # automated inspection below.

    # PEP 484-compliant abstract base classes (ABCs) requiring non-standard and
    # non-trivial type-checking. Although most types are trivially type-checked
    # by the isinstance() builtin, these types break the mold in various ways.

    #FIXME: Uhm. Shouldn't this be "HintSignIO" rather than
    #"HintSignPep484585GenericUnsubbed"? What's this about, exactly? Please
    #explain this away... somehow. Hmm. This is probably related to one of our
    #generics-specific reducers, isn't it? Makes sense, but let's document.
    "<class 'typing.IO'>":       HintSignPep484585GenericUnsubbed,
    "<class 'typing.BinaryIO'>": HintSignBinaryIO,
    "<class 'typing.TextIO'>":   HintSignTextIO,

    # ..................{ PEP (484|604)                      }..................
    # Python >= 3.14 implements both PEP 484-compliant old-school unions
    # (e.g., "typing.Union[int, float]") *AND* PEP 604-compliant new-school
    # unions (e.g., "int | float") as instances of the low-level C-based
    # "typing.Union" type. This has two implications:
    # * The unsubscripted "typing.Union" hint semantically equivalent to the
    #   subscripted "typing.Union[typing.Any]" hint is thus identical to the
    #   C-based "typing.Union" type, which is then also a valid hint.
    # * The type of *ALL* union hints (e.g., "type(typing.Union[str, float])",
    #   "type(int | bytes)") is invalid as a type hint but remains
    #   indistinguishable at runtime from the unsubscripted "typing.Union" hint.
    #   This implies that beartype is no longer capable of flagging the type of
    #   union hints as an invalid hint, which implies that beartype now emits
    #   false negatives for this type. That's not great, but also not the worst
    #   thing to ever happen to beartype. Pragmatically, there should exist *NO*
    #   real-world attempts by end users to use the union type as a hint. These
    #   false negatives should *NEVER* arise in real-world usage.
    "<class 'typing.Union'>": HintSignUnion,
}
'''
Dictionary mapping from the **possibly unsubscripted PEP-compliant type hint
representation prefix** (i.e., unsubscripted prefix of the machine-readable
strings returned by the :func:`repr` builtin for PEP-compliant type hints
permissible in both subscripted and unsubscripted forms) of each hint uniquely
identifiable by that representation to its identifying sign.

Notably, this dictionary maps from the representation prefixes of:

* *All* :pep:`484`-compliant type hints. Whereas *all* :pep:`585`-compliant type
  hints (e.g., ``list[str]``) are necessarily subscripted and thus omitted from
  this dictionary, *all* :pep:`484`-compliant type hints support at least
  unsubscripted form and most :pep:`484`-compliant type hints support
  subscription as well. Moreover, the unsubscripted forms of most
  :pep:`484`-compliant type hints convey deep semantics and thus require
  detection as PEP-compliant (e.g., :obj:`typing.List`, requiring detection and
  reduction to :class:`list`).
'''


# The majority of this dictionary is defined by explicit key-value pairs here.
HINT_REPR_PREFIX_ARGS_1_OR_MORE_TO_SIGN: DictStrToHintSign = {
    # ..................{ PEP 585                            }..................
    # PEP 585-compliant type hints *MUST* by definition be subscripted (e.g.,
    # "list[str]" rather than "list"). While the stdlib types underlying those
    # hints are isinstanceable classes and thus also permissible as type hints
    # when unsubscripted (e.g., simply "list"), unsubscripted classes convey no
    # deep semantics and thus need *NOT* be detected as PEP-compliant.
    #
    # For maintainability, these key-value pairs are intentionally listed in the
    # same order as the official list in PEP 585 itself.
    'tuple': HintSignTuple,
    'list': HintSignList,
    'dict': HintSignDict,
    'set': HintSignSet,
    'frozenset': HintSignFrozenSet,
    'type': HintSignType,
    'collections.deque': HintSignDeque,
    'collections.defaultdict': HintSignDefaultDict,
    'collections.OrderedDict': HintSignOrderedDict,
    'collections.Counter': HintSignCounter,
    'collections.ChainMap': HintSignChainMap,
    'collections.abc.Awaitable': HintSignAwaitable,
    'collections.abc.Coroutine': HintSignCoroutine,
    'collections.abc.AsyncIterable': HintSignAsyncIterable,
    'collections.abc.AsyncIterator': HintSignAsyncIterator,
    'collections.abc.AsyncGenerator': HintSignAsyncGenerator,
    'collections.abc.Iterable': HintSignIterable,
    'collections.abc.Iterator': HintSignIterator,
    'collections.abc.Generator': HintSignGenerator,
    'collections.abc.Reversible': HintSignReversible,
    'collections.abc.Container': HintSignContainer,
    'collections.abc.Collection': HintSignCollection,
    'collections.abc.Callable': HintSignCallable,
    'collections.abc.Set': HintSignAbstractSet,
    'collections.abc.MutableSet': HintSignMutableSet,
    'collections.abc.Mapping': HintSignMapping,
    'collections.abc.MutableMapping': HintSignMutableMapping,
    'collections.abc.Sequence': HintSignSequence,
    'collections.abc.MutableSequence': HintSignMutableSequence,
    'collections.abc.ByteString': HintSignByteString,
    'collections.abc.MappingView': HintSignMappingView,
    'collections.abc.KeysView': HintSignKeysView,
    'collections.abc.ItemsView': HintSignItemsView,
    'collections.abc.ValuesView': HintSignValuesView,
    'contextlib.AbstractContextManager': HintSignContextManager,
    'contextlib.AbstractAsyncContextManager': HintSignAsyncContextManager,
    're.Pattern': HintSignPattern,
    're.Match': HintSignMatch,

    # ..................{ NON-PEP ~ lib : numpy              }..................
    # The PEP-noncompliant "numpy.typing.NDArray" type hint is permissible in
    # both subscripted and unsubscripted forms. In the latter case, this hint
    # is implicitly subscripted by generic type variables. In both cases, this
    # hint presents a uniformly reliable representation -- dramatically
    # simplifying detection via a common prefix of that representation here:
    #     >>> import numpy as np
    #     >>> import numpy.typing as npt
    #     >>> repr(npt.NDArray)
    #     numpy.ndarray[typing.Any, numpy.dtype[+ScalarType]]
    #     >>> repr(npt.NDArray[np.float64])
    #     repr: numpy.ndarray[typing.Any, numpy.dtype[numpy.float64]]
    #
    # Ergo, unsubscripted "numpy.typing.NDArray" type hints present themselves
    # as implicitly subscripted through their representation.
    'numpy.ndarray': HintSignNumpyArray,
}
'''
Dictionary mapping from the **necessarily subscripted PEP-compliant type hint
representation prefixes** (i.e., unsubscripted prefix of the machine-readable
strings returned by the :func:`repr` builtin for subscripted PEP-compliant type
hints) of all hints uniquely identifiable by those representations to
their identifying signs.

Notably, this dictionary maps from the representation prefixes of:

* All :pep:`585`-compliant type hints. Whereas all :pep:`484`-compliant type
  hints support both subscripted and unsubscripted forms (e.g.,
  ``typing.List``, ``typing.List[str]``), all :pep:`585`-compliant type hints
  necessarily require subscription. While the stdlib types underlying
  :pep:`585`-compliant type hints are isinstanceable classes and thus also
  permissible as type hints when unsubscripted (e.g., simply :class:`list`),
  isinstanceable classes convey *no* deep semantics and thus need *not* be
  detected as PEP-compliant.
'''

# ....................{ MAPPINGS ~ repr : trie             }....................
# The majority of this trie is defined by explicit key-value pairs here.
HINT_REPR_PREFIX_TRIE_ARGS_0_OR_MORE_TO_SIGN: HintSignTrie = {
    # ..................{ NON-PEP ~ lib : pandera            }..................
    # All PEP-noncompliant "pandera.typing" type hints are permissible in
    # both subscripted and unsubscripted forms.
    'pandera': {
        'typing': HintSignPanderaAny,
    }
}
'''
**Sign trie** (i.e., dictionary-of-dictionaries tree data structure enabling
efficient mapping from the machine-readable representations of type hints
created by an arbitrary number of type hint factories defined by an external
third-party package to their identifying sign) from the **possibly unsubscripted
PEP-compliant type hint representation prefix** (i.e., unsubscripted prefix of
the machine-readable strings returned by the :func:`repr` builtin for
PEP-compliant type hints permissible in both subscripted and unsubscripted
forms) of each hint uniquely identifiable by that representation to its
identifying sign.
'''

# ....................{ SETS ~ deprecated                  }....................
# Initialized with automated inspection below in the _init() function.
HINTS_PEP484_REPR_PREFIX_DEPRECATED: FrozenSetStrs = set()  # type: ignore[assignment]
'''
Frozen set of all **bare deprecated** :pep:`484`-compliant **type hint
representations** (i.e., machine-readable strings returned by the :func:`repr`
builtin suffixed by *no* "["- and "]"-delimited subscription representations
for all :pep:`484`-compliant type hints obsoleted by :pep:`585`-compliant
subscriptable classes).
'''

# ....................{ INITIALIZERS                       }....................
def _init() -> None:
    '''
    Initialize this submodule.
    '''

    # ..................{ IMPORTS                            }..................
    # Defer initialization-specific imports.
    from beartype._data.api.standard.datatyping import TYPING_MODULE_NAMES
    from beartype._data.hint.sign.datahintsigns import HINT_SIGNS_TYPING

    # ..................{ GLOBALS                            }..................
    # Permit redefinition of these globals below.
    global HINTS_PEP484_REPR_PREFIX_DEPRECATED

    # ..................{ HINTS ~ repr                       }..................
    #FIXME: Odd. This appears to have been once used to map
    #"AbstractContextManager" to "typing.ContextManager" or something, but is no
    #longer used anywhere. Contemplate excising! *sigh*
    # # Dictionary mapping from the unqualified names of typing attributes whose
    # # names are erroneously desynchronized from their bare machine-readable
    # # representations to the actual representations of those attributes.
    # #
    # # The unqualified names and representations of *MOST* typing attributes are
    # # rigorously synchronized. However, those two strings are desynchronized
    # # for a proper subset of Python versions and typing attributes:
    # #     $ ipython3.8
    # #     >>> import typing
    # #     >>> repr(typing.List[str])
    # #     typing.List[str]   # <-- this is good
    # #     >>> repr(typing.ContextManager[str])
    # #     typing.AbstractContextManager[str]   # <-- this is pants
    # #
    # # This dictionary enables subsequent logic to transparently resynchronize
    # # the unqualified names and representations of pants typing attributes.
    # _HINT_TYPING_ATTR_NAME_TO_REPR_PREFIX: Dict[str, str] = {}

    # ..................{ HINTS ~ deprecated                 }..................
    # Set of the unqualified names of all deprecated PEP 484-compliant typing
    # attributes.
    _HINT_PEP484_TYPING_ATTR_BASENAMES_DEPRECATED: Set[str] = {
        # ..................{ PEP ~ 484                      }..................
        # Unqualified basenames of all deprecated PEP 484-compliant
        # typing attributes (e.g., "typing.List") that have since been obsoleted
        # by equivalent bare PEP 585-compliant builtin classes (e.g., "list").
        'AbstractSet',
        'AsyncContextManager',
        'AsyncGenerator',
        'AsyncIterable',
        'AsyncIterator',
        'Awaitable',
        'ByteString',
        'Callable',
        'ChainMap',
        'Collection',
        'Container',
        'ContextManager',
        'Coroutine',
        'Counter',
        'DefaultDict',
        'Deque',
        'Dict',
        'FrozenSet',
        'Generator',
        'Hashable',
        'ItemsView',
        'Iterable',
        'Iterator',
        'KeysView',
        'List',
        'MappingView',
        'Mapping',
        'Match',
        'MutableMapping',
        'MutableSequence',
        'MutableSet',
        'OrderedDict',
        'Pattern',
        'Reversible',
        'Sequence',
        'Set',
        'Sized',
        'Tuple',
        'Type',
        'ValuesView',
    }

    # ..................{ INITIALIZATION                     }..................
    # For the fully-qualified name of each quasi-standard typing module...
    for typing_module_name in TYPING_MODULE_NAMES:
        # For each deprecated PEP 484-compliant typing attribute name, add that
        # attribute relative to this module to this set.
        for typing_attr_basename in (
            _HINT_PEP484_TYPING_ATTR_BASENAMES_DEPRECATED):
            # print(f'[datahintrepr] Registering deprecated "{typing_module_name}.{typing_attr_basename}"...')
            HINTS_PEP484_REPR_PREFIX_DEPRECATED.add(  # type: ignore[attr-defined]
                f'{typing_module_name}.{typing_attr_basename}')

        # For the name of each typing sign (i.e., identifying *ALL* standard
        # PEP-compliant "typing" type hints and type hint factories available in
        # the most recent stable CPython release)...
        for hint_sign_typing in HINT_SIGNS_TYPING:
            # Unqualified basename of the typing attribute uniquely identified
            # by this sign.
            typing_attr_basename = hint_sign_typing.name

            #FIXME: Odd. This appears to have been once used to map
            #"AbstractContextManager" to "typing.ContextManager" or something,
            #but is no longer used anywhere. Contemplate excising! *sigh*
            # # Substring prefixing the machine-readable representation of this
            # # attribute, conditionally defined as either:
            # # * If this name is erroneously desynchronized from this
            # #   representation under the active Python interpreter, the actual
            # #   representation of this attribute under this interpreter (e.g.,
            # #   "AbstractContextManager" for the "typing.ContextManager" hint).
            # # * Else, this name is correctly synchronized with this
            # #   representation under the active Python interpreter. In this
            # #   case, fallback to this name as is (e.g., "List" for the
            # #   "typing.List" hint).
            # hint_repr_prefix = _HINT_TYPING_ATTR_NAME_TO_REPR_PREFIX.get(
            #     typing_attr_basename, typing_attr_basename)

            #FIXME: It'd be great to eventually generalize this to support
            #aliases from one unwanted sign to another wanted sign. Perhaps
            #something resembling:
            ## In global scope above:
            #_HINT_SIGN_REPLACE_SOURCE_BY_TARGET = {
            #    HintSignProtocol: HintSignPep484585GenericUnsubbed,
            #}
            #
            #    # In this iteration here:
            #    ...
            #    hint_sign_replaced = _HINT_SIGN_REPLACE_SOURCE_BY_TARGET.get(
            #        hint_sign, hint_sign)
            #
            #    # Map from that attribute in this module to this sign.
            #    # print(f'[datahintrepr] Mapping repr("{typing_module_name}.{hint_repr_prefix}[...]") -> {repr(hint_sign)}...')
            #    HINT_REPR_PREFIX_ARGS_0_OR_MORE_TO_SIGN[
            #        f'{typing_module_name}.{hint_repr_prefix}'] = hint_sign_replaced
            # print(f'[datahintrepr] Mapping repr("{typing_module_name}.{hint_repr_prefix}[...]") -> {repr(hint_sign)}...')

            #FIXME: Not quite right, obviously. The "HINT_SIGNS_TYPING" set used
            #to define this mapping includes *TONS* of unsubscriptable typing
            #attributes (e.g., "typing.TypeVar", "typing.TypeVarTuple"). The
            #only reason this works at all is that the higher-level
            #get_hint_pep_sign_or_none() getter internally leveraging this
            #mapping only accesses this mapping as a fallback *AFTER* accessing
            #type-specific mappings (e.g.,
            #"HINT_MODULE_NAME_TO_TYPE_BASENAME_TO_SIGN") first. Oh, well.
            #Nobody cares, huh? *sigh*

            # Map from the fully-qualified name of this typing attribute
            # relative to this module to this sign.
            #
            # Note that most typing attributes are subscriptable type hint
            # factories. Moreover, note that most subscriptable type hint
            # factories are implicitly subscripted by the "typing.Any" child
            # hint when unsubscripted (e.g., the unsubscripted "typing.Union"
            # factory is equivalent to "typing.Union[typing.Any]") and are thus
            # themselves valid hints. Ergo, we intentionally map these
            # attributes onto the "HINT_REPR_PREFIX_ARGS_0_OR_MORE_TO_SIGN"
            # rather than "HINT_REPR_PREFIX_ARGS_1_OR_MORE_TO_SIGN" factory.
            HINT_REPR_PREFIX_ARGS_0_OR_MORE_TO_SIGN[
                f'{typing_module_name}.{typing_attr_basename}'] = (
                hint_sign_typing)

    # ..................{ SYNTHESIS                          }..................
    # Freeze all relevant global sets for safety.
    HINTS_PEP484_REPR_PREFIX_DEPRECATED = frozenset(
        HINTS_PEP484_REPR_PREFIX_DEPRECATED)

    # ..................{ DEBUGGING                          }..................
    # Uncomment as needed to display the contents of these objects.

    # from pprint import pformat
    # print(f'HINTS_PEP484_REPR_PREFIX_DEPRECATED: {pformat(HINTS_PEP484_REPR_PREFIX_DEPRECATED)}')
    # print(f'HINT_REPR_PREFIX_ARGS_0_OR_MORE_TO_SIGN: {pformat(HINT_REPR_PREFIX_ARGS_0_OR_MORE_TO_SIGN)}')
    # print(f'HINT_REPR_PREFIX_ARGS_1_OR_MORE_TO_SIGN: {pformat(HINT_REPR_PREFIX_ARGS_1_OR_MORE_TO_SIGN)}')
    # print(f'HINT_MODULE_NAME_TO_TYPE_BASENAME_TO_SIGN: {pformat(HINT_MODULE_NAME_TO_TYPE_BASENAME_TO_SIGN)}')


# Initialize this submodule.
_init()
