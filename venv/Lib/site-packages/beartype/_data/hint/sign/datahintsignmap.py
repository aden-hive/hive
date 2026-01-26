#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **type hint sign mappings** (i.e., dictionary globals mapping from
instances of the :class:`beartype._data.hint.sign.datahintsigncls.HintSign`
class to various metadata associated with categories of type hints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import Dict
from beartype._data.api.standard.datatyping import TYPING_MODULE_NAMES
from beartype._data.typing.datatyping import (
    DictStrToHintSign,
)
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.hint.sign.datahintsigns import (
    HintSignAbstractSet,
    HintSignAsyncContextManager,
    HintSignAsyncGenerator,
    HintSignAsyncIterator,
    HintSignAsyncIterable,
    HintSignAwaitable,
    HintSignChainMap,
    HintSignCollection,
    HintSignContainer,
    HintSignContextManager,
    HintSignCoroutine,
    HintSignCounter,
    HintSignDefaultDict,
    HintSignDeque,
    HintSignDict,
    HintSignForwardRef,
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
    HintSignNamedTuple,
    HintSignNewType,
    HintSignNone,
    HintSignOrderedDict,
    HintSignParamSpec,
    HintSignParamSpecArgs,
    HintSignParamSpecKwargs,
    HintSignPattern,
    HintSignPep484585GenericUnsubbed,
    HintSignPep557DataclassInitVar,
    HintSignPep695TypeAliasUnsubscripted,
    HintSignProtocol,
    HintSignReversible,
    HintSignSequence,
    HintSignSet,
    HintSignTuple,
    HintSignType,
    HintSignTypedDict,
    HintSignTypeVar,
    HintSignTypeVarTuple,
    HintSignUnion,
    HintSignUnpack,
    HintSignValuesView,
)

# ....................{ HINTS                              }....................
HintSignTrie = Dict[str, DictStrToHintSign]
'''
PEP-compliant type hint matching a **hint sign trie** (i.e.,
dictionary-of-dictionaries tree data structure mapping from the fully-qualified
names of packages and modules to nested dictionaries mapping from the
unqualified basenames of various PEP-compliant type hints residing in those
packages and modules to their identifying signs).
'''

# ....................{ PRIVATE ~ constructors             }....................
def _init_hint_sign_trie(hint_sign_trie: HintSignTrie) -> HintSignTrie:
    '''
    Initialize the passed **hint sign trie** (i.e., dictionary-of-dictionaries
    tree data structure mapping from the fully-qualified names of packages and
    modules to nested dictionaries mapping from the unqualified basenames of
    various PEP-compliant type hints residing in those packages and modules to
    their identifying signs).

    Parameters
    ----------
    hint_sign_trie : HintSignTrie
        Hint sign trie to be initialized.

    Returns
    -------
    HintSignTrie
        This same trie as a caller convenience.
    '''

    # For the fully-qualified name of each quasi-standard typing module...
    for typing_module_name in TYPING_MODULE_NAMES:
        # If this trie fails to map this name to a nested dictionary, map this
        # name to the empty nested dictionary. Doing so simplifies logic
        # performed by the _init() function called below.
        if typing_module_name not in hint_sign_trie:
            hint_sign_trie[typing_module_name] = {}

    # Return this same trie as a caller convenience.
    return hint_sign_trie

# ....................{ MAPPINGS                           }....................
# The majority of this dictionary is initialized with automated inspection
# iterating over the "_TYPING_ATTR_HINT_BASENAME_TO_SIGN" dictionary local
# defined by the _init() function below. The *ONLY* key-value pairs explicitly
# defined here are those *NOT* amenable to such inspection.
#
# Note that the root "object" superclass *CANNOT* be safely mapped to the
# "typing.Any" singleton with logic resembling:
#    # ..................{ BUILTINS                           }..................
#    # Standard builtins module.
#    'builtins': {
#        # ..................{ NON-PEP                        }..................
#        # The PEP-noncompliant root "object" superclass is semantically
#        # equivalent to the PEP-compliant "typing.Any" singleton from the
#        # runtime type-checking perspective. Why? Because "object" is the
#        # transitive superclass of all classes. Attributes annotated as "object"
#        # unconditionally match *ALL* objects under isinstance()-based type
#        # covariance and thus semantically reduce to unannotated attributes.
#        # Reduce this hint to "typing.Any", which then reduces this hint to the
#        # ignorable "HINT_SANE_IGNORABLE" singleton.
#        'object': HintSignAny,
#    },
#
# Why? Because doing so would then erroneously render the otherwise
# PEP-noncompliant "object" type PEP-compliant, which would then cause
# raisers like die_if_pep() and die_unless_pep() to exhibit anomalous
# behaviour with respect to that type. In short, the clever solution is the
# wrong solution. *sigh*
HINT_MODULE_NAME_TO_HINT_BASENAME_TO_SIGN = _init_hint_sign_trie({})
'''
**Type hint trie** (i.e., dictionary-of-dictionaries tree data structure mapping
from the fully-qualified names of packages and modules to nested dictionaries
mapping from the unqualified basenames of all PEP-compliant type hints residing
in those packages and modules such that those hints are either callables or
classes *and* uniquely identifiable by those callables or classes to their
identifying signs).
'''


# The majority of this dictionary is initialized with automated inspection
# iterating over the "_TYPING_ATTR_TYPE_BASENAME_TO_SIGN" dictionary local
# defined by the _init() function below. The *ONLY* key-value pairs explicitly
# defined here are those *NOT* amenable to such inspection.
HINT_MODULE_NAME_TO_TYPE_BASENAME_TO_SIGN = _init_hint_sign_trie({
    # ..................{ BUILTINS                           }..................
    # Standard builtins module.
    'builtins': {
        # ..................{ PEP 484                        }..................
        # PEP 484-compliant forward reference type hints may be annotated
        # either:
        # * Explicitly as "typing.ForwardRef" instances, which automated
        #   inspection performed by the _init() function below already handles.
        # * Implicitly as strings, which this key-value pair here detects. Note
        #   this unconditionally matches *ALL* strings, including both:
        #   * Invalid Python identifiers (e.g., "0d@yw@r3z").
        #   * Absolute forward references (i.e., fully-qualified classnames)
        #     technically non-compliant with PEP 484 but seemingly compliant
        #     with PEP 585.
        #
        #   Since the distinction between PEP-compliant and -noncompliant
        #   forward references is murky at best and since unconditionally
        #   matching *ALL* string as PEP-compliant substantially simplifies
        #   logic throughout the codebase, we (currently) opt to do so.
        'str': HintSignForwardRef,

        # The C-based "builtins.NoneType" type does *NOT* actually exist: e.g.,
        #     >>> from builtins import NoneType
        #     ImportError: cannot import name 'NoneType' from 'builtins'
        #     (unknown location)
        #
        # This implies that users *CANNOT* make user-defined instances of this
        # type, which then implies that the *ONLY* instance of this type is
        # guaranteed to be the PEP 484-compliant "None" singleton, which
        # circuitously reduces to "types.NoneType" under PEP 484.
        #
        # PEP 484 explicitly supports this singleton as follows:
        #     When used in a type hint, the expression None is considered
        #     equivalent to type(None).
        #
        # Note that the representation of the type of the "None" singleton
        # (i.e., "<class 'NoneType'>") is intentionally omitted here despite the
        # "None" singleton reducing to that type. Indeed, the *ONLY* reason we
        # detect this singleton at all is to enable that reduction. Although
        # this singleton conveys a PEP-compliant semantic, the type of this
        # singleton explicitly conveys *NO* PEP-compliant semantics. That type
        # is simply a standard isinstanceable type (like any other). Indeed,
        # attempting to erroneously associate the type of the "None" singleton
        # with the same sign here would cause that type to be detected as
        # conveying sign-specific PEP-compliant semantics rather than *NO* such
        # semantics, which would then substantially break and complicate dynamic
        # code generation for no benefit whatsoever.
        'NoneType': HintSignNone,
    },

    # ..................{ ANNOTATIONLIB                      }..................
    # Standard PEP 649- and 749-compliant annotation module.
    'annotationlib': {
        # ..................{ PEP (649|749)                  }..................
        # The "annotationlib.ForwardRef" type is now the canonical location of
        # this type under Python >= 3.14, which previously resided at
        # "typing.ForwardRef". The latter still exists but simply as a lazy
        # shallow alias of the former.
        'ForwardRef': HintSignForwardRef,
    },

    # ..................{ DATACLASSES                        }..................
    # Standard PEP 557-compliant dataclass module.
    'dataclasses': {
        # ..................{ PEP 557                        }..................
        # PEP 557-compliant "dataclasses.InitVar" type hints are merely
        # instances of that class.
        'InitVar': HintSignPep557DataclassInitVar,
    },

    # ..................{ TYPES                              }..................
    # Standard module containing common low-level C-based types.
    'types': {
        #FIXME: Excise this *AFTER* dropping Python 3.13 support, please.
        # ..................{ PEP 604                        }..................
        # Python <= 3.13 implements PEP 604-compliant |-style unions (e.g., "int
        # | float") as instances of the low-level C-based "types.UnionType"
        # type. Thankfully, these unions are semantically interchangeable with
        # comparable PEP 484-compliant unions (e.g., "typing.Union[int,
        # float]"); both kinds expose equivalent dunder attributes (e.g.,
        # "__args__", "__parameters__"), enabling subsequent code generation to
        # conflate the two without issue.
        'UnionType': HintSignUnion,
    },

    # ..................{ TYPING                             }..................
    # Standard typing module.
    'typing': {
        # ..................{ PEP 484                        }..................
        # Python >= 3.10 implements PEP 484-compliant "typing.NewType" type
        # hints as instances of that pure-Python class.
        #
        # Note that we intentionally omit both "beartype.typing.NewType" *AND*
        # "typing_extensions.NewType" here, as:
        # * "beartype.typing.NewType" is a merely an alias of "typing.NewType".
        # * Regardless of the current Python version,
        #   "typing_extensions.NewType" type hints remain implemented in the
        #   manner of Python < 3.10 -- which is to say, as closures of that
        #   function. See also:
        #       https://github.com/python/typing/blob/master/typing_extensions/src_py3/typing_extensions.py
        'NewType': HintSignNewType,

        # ..................{ PEP (484|604)                  }..................
        # Python >= 3.14 implements both PEP 484-compliant old-school unions
        # (e.g., "typing.Union[int, float]") *AND* PEP 604-compliant new-school
        # unions (e.g., "int | float") as instances of the low-level C-based
        # "typing.Union" type. Doing so unifies the syntactic treatment of
        # unions, mildly simplifying union detection: e.g.,
        #     >>> from typing import Optional, Union
        #
        #     >>> type(int | None)
        #     <class 'typing.Union'>  # <-- *GOOD*
        #     >>> type(Union[int, None])
        #     <class 'typing.Union'>  # <-- *GOOD*
        #     >>> type(Optional[int])
        #     <class 'typing.Union'>  # <-- *GOOD*
        #
        #     >>> int | None == Optional[int] == Union[int, None]
        #     True  # <-- woah. CPython mad lads finally did it, huh?
        'Union': HintSignUnion,
    },
})
'''
**Type hint type trie** (i.e., dictionary-of-dictionaries tree data structure
mapping from the fully-qualified names of packages and modules to a nested
dictionary mapping from the unqualified basenames of the types of all
PEP-compliant type hints residing in those packages and modules that are
uniquely identifiable by those types to their identifying signs).
'''

# ....................{ MAPPINGS ~ generics                }....................
# The majority of this dictionary is initialized with automated inspection
# iterating over the "_TYPING_ATTR_HINT_BASENAME_TO_SIGN" dictionary local
# defined by the _init() function below. The *ONLY* key-value pairs explicitly
# defined here are those *NOT* amenable to such inspection.
HINT_MODULE_NAME_TO_HINT_BASE_EXTRINSIC_BASENAME_TO_SIGN = (
    _init_hint_sign_trie({}))
'''
**Extrinsic pseudo-superclass trie** (i.e., dictionary-of-dictionaries tree data
structure mapping from the fully-qualified names of packages and modules to
nested dictionaries mapping from the unqualified basenames of all PEP-compliant
objects residing in those packages and modules such that those objects are valid
extrinsic pseudo-superclasses of :pep:`484`- or :pep:`585`-compliant generics
extrinsically identifiable by signs to those signs).
'''

# ....................{ PRIVATE ~ globals                  }....................
# Note that the builtin "range" class:
# * Initializer "range.__init__(start, stop)" is effectively instantiated as
#   [start, stop) -- that is to say, such that:
#   * The initial "start" integer is *INCLUSIVE* (i.e., the instantiated range
#     includes this integer).
#   * The final "stop" integer is *EXCLUSIVE* (i.e., the instantiated range
#     excludes this integer).
# * Publicizes these integers as the instance variables "start" and "stop" such
#   that these invariants are guaranteed:
#       >>> range(min, max).start == min
#       True
#       >>> range(min, max).stop == max
#       True

_ARGS_LEN_0 = range(0, 1)  # == [0, 1) == [0, 0]
'''
**Zero-argument length range** (i.e., :class:`range` instance effectively
equivalent to the integer ``0``, describing type hint factories subscriptable by
*no* child type hints).
'''


_ARGS_LEN_1 = range(1, 2)  # == [1, 2) == [1, 1]
'''
**One-argument length range** (i.e., :class:`range` instance effectively
equivalent to the integer ``1``, describing type hint factories subscriptable by
exactly one child type hint).
'''


_ARGS_LEN_2 = range(2, 3)  # == [2, 3) == [2, 2]
'''
**Two-argument length range** (i.e., :class:`range` instance effectively
equivalent to the integer ``2``, describing type hint factories subscriptable by
exactly two child type hints).
'''


_ARGS_LEN_3 = range(3, 4)  # == [3, 4) == [3, 3]
'''
**Three-argument length range** (i.e., :class:`range` instance effectively
equivalent to the integer ``3``, describing type hint factories subscriptable by
exactly three child type hints).
'''


_ARGS_LEN_1_OR_2 = range(1, 3)  # == [1, 3) == [1, 2]
'''
**One- or two-argument length range** (i.e., :class:`range` instance effectively
equivalent to the integer range ``[1, 2]``, describing type hint factories
subscriptable by either one or two child type hints).
'''

# ....................{ SIGNS ~ origin : args              }....................
# Fully initialized by the _init() function below.
HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE: Dict[HintSign, range] = {
    # Type hint factories subscriptable by exactly one child type hint.
    HintSignAbstractSet: _ARGS_LEN_1,
    HintSignAsyncIterable: _ARGS_LEN_1,
    HintSignAsyncIterator: _ARGS_LEN_1,
    HintSignAwaitable: _ARGS_LEN_1,
    # HintSignByteString: _ARGS_LEN_1,
    HintSignCollection: _ARGS_LEN_1,
    HintSignContainer: _ARGS_LEN_1,
    HintSignCounter: _ARGS_LEN_1,
    HintSignDeque: _ARGS_LEN_1,
    HintSignFrozenSet: _ARGS_LEN_1,
    HintSignIterable: _ARGS_LEN_1,
    HintSignIterator: _ARGS_LEN_1,
    HintSignKeysView: _ARGS_LEN_1,
    HintSignList: _ARGS_LEN_1,
    HintSignMatch: _ARGS_LEN_1,
    HintSignMappingView: _ARGS_LEN_1,
    HintSignMutableSequence: _ARGS_LEN_1,
    HintSignMutableSet: _ARGS_LEN_1,
    HintSignPattern: _ARGS_LEN_1,
    HintSignReversible: _ARGS_LEN_1,
    HintSignSequence: _ARGS_LEN_1,
    HintSignSet: _ARGS_LEN_1,
    HintSignType: _ARGS_LEN_1,
    HintSignValuesView: _ARGS_LEN_1,

    # Type hint factories subscriptable by exactly two child type hints.
    HintSignAsyncGenerator: _ARGS_LEN_2,
    HintSignChainMap: _ARGS_LEN_2,
    HintSignDefaultDict: _ARGS_LEN_2,
    HintSignDict: _ARGS_LEN_2,
    HintSignItemsView: _ARGS_LEN_2,
    HintSignMapping: _ARGS_LEN_2,
    HintSignMutableMapping: _ARGS_LEN_2,
    HintSignOrderedDict: _ARGS_LEN_2,
    HintSignTuple: _ARGS_LEN_2,

    # Type hint factories subscriptable by exactly three child type hints.
    HintSignCoroutine: _ARGS_LEN_3,
    HintSignGenerator: _ARGS_LEN_3,
}
'''
Dictionary mapping from each sign uniquely identifying a PEP-compliant type hint
factory originating from an **isinstanceable origin type** (i.e., isinstanceable
class such that *all* objects satisfying type hints created by subscripting this
factory are instances of this class) to this factory's **argument length range**
(i.e., :class:`range` instance describing the minimum and maximum number of
child type hints that may subscript this factory).
'''

# ....................{ PRIVATE ~ main                     }....................
def _init() -> None:
    '''
    Initialize this submodule.
    '''

    # ..................{ IMPORTS                            }..................
    # Defer initialization-specific imports.
    from beartype._util.py.utilpyversion import (
        IS_PYTHON_AT_MOST_3_13,
        IS_PYTHON_AT_LEAST_3_13,
        IS_PYTHON_3_11,
    )

    # ..................{ LOCALS                             }..................
    # Dictionary mapping from the unqualified names of all callables and classes
    # defined by typing modules that are themselves valid PEP-compliant type
    # hints to their corresponding signs.
    _TYPING_ATTR_HINT_BASENAME_TO_SIGN = {
        # ..................{ PEP 484                        }..................
        # Unsubscripted "typing.Generic" superclass, which imposes no
        # constraints and is also semantically synonymous with the "object"
        # superclass. Since PEP 484 stipulates that *ANY* unsubscripted
        # subscriptable PEP-compliant type hint factories semantically expand to
        # those factories subscripted by an implicit "Any" argument, "Generic"
        # semantically expands to the implicit "Generic[Any]" singleton.
        'Generic': HintSignPep484585GenericUnsubbed,

        # ..................{ PEP 544                        }..................
        # Unsubscripted "typing.Protocol" superclass. For unknown and presumably
        # uninteresting reasons, *ALL* possible objects satisfy this superclass.
        # Ergo, this superclass is synonymous with the "object" root superclass:
        #     >>> from typing import Protocol
        #     >>> isinstance(object(), Protocol)
        #     True
        #     >>> isinstance('wtfbro', Protocol)
        #     True
        #     >>> isinstance(0x696969, Protocol)
        #     True
        'Protocol': HintSignProtocol,
    }

    # Dictionary mapping from the unqualified names of all callables and classes
    # defined by typing modules that are themselves valid extrinsic
    # pseudo-superclasses to their corresponding signs.
    _TYPING_ATTR_HINT_BASE_EXTRINSIC_BASENAME_TO_SIGN = {
        # ..................{ PEP 484                        }..................
        # PEP 484-compliant "typing.NamedTuple" superclass, whose metaclass
        # permits subclasses to also subclass the PEP 484-compliant
        # "typing.Generic" superclass under Python >= 3.11. The resulting
        # user-defined subclasses are referred to as "generic named tuples,"
        # which convey extrinsic type-checking courtesy being named tuples.
        'NamedTuple': HintSignNamedTuple,

        # ..................{ PEP 589                        }..................
        # PEP 589-compliant "typing.TypedDict" superclass, whose metaclass
        # permits subclasses to also subclass the PEP 484-compliant
        # "typing.Generic" superclass under Python >= 3.11. The resulting
        # user-defined subclasses are referred to as "generic typed
        # dictionaries," which convey extrinsic type-checking courtesy being
        # typed dictionaries.
        'TypedDict': HintSignTypedDict,
    }

    # Dictionary mapping from the unqualified names of all classes defined by
    # typing modules used to instantiate PEP-compliant type hints to their
    # corresponding signs.
    _TYPING_ATTR_TYPE_BASENAME_TO_SIGN = {
        # ....................{ PEP 484                    }....................
        # All PEP 484-compliant type variables are necessarily instances of the
        # same class.
        'TypeVar': HintSignTypeVar,

        #FIXME: "Generic" is ignorable when unsubscripted. Excise this up!
        # The unsubscripted PEP 484-compliant "Generic" superclass is
        # explicitly equivalent under PEP 484 to the "Generic[Any]"
        # subscription and thus slightly conveys meaningful semantics.
        # 'Generic': HintSignPep484585GenericUnsubbed,

        # ....................{ PEP 612                    }....................
        # PEP 612-compliant "typing.ParamSpec" type hints as merely instances of
        # that low-level C-based type.
        'ParamSpec': HintSignParamSpec,

        # PEP 612-compliant "*args: P.args" type hints as merely instances of
        # the low-level C-based "typing.ParamSpecArgs" type.
        'ParamSpecArgs': HintSignParamSpecArgs,

        # PEP 612-compliant "**kwargs: P.kwargs" type hints as merely instances
        # of the low-level C-based "typing.ParamSpecKwargs" type.
        'ParamSpecKwargs': HintSignParamSpecKwargs,

        # ....................{ PEP 646                    }....................
        # All PEP 646-compliant type variable tuples are necessarily instances
        # of the same class.
        'TypeVarTuple': HintSignTypeVarTuple,

        # ....................{ PEP 695                    }....................
        # PEP 695-compliant "type" aliases are merely instances of the low-level
        # C-based "typing.TypeAliasType" type.
        'TypeAliasType': HintSignPep695TypeAliasUnsubscripted,
    }

    # ..................{ INIT ~ versions                    }..................
    # If the active Python interpreter targets Python <= 3.13...
    if IS_PYTHON_AT_MOST_3_13:
        # Map both the "typing.ForwardRef" and "typing_extensions.ForwardRef"
        # types (the latter of which is simply an alias of the former) to the
        # sign uniquely identifying forward references. All PEP 484-compliant
        # forward references are necessarily instances of this type.
        #
        # Under Python >= 3.14, both of these types are simply aliases of
        # "annotationlib.ForwardRef" type -- which is now the canonical
        # implementation of this type but which resides outside a typing module.
        _TYPING_ATTR_TYPE_BASENAME_TO_SIGN['ForwardRef'] = HintSignForwardRef
    # Else, the active Python interpreter targets Python >= 3.14.

    # If the active Python interpreter targets Python >= 3.13...
    if IS_PYTHON_AT_LEAST_3_13:
        # Add all signs uniquely identifying one- or two-argument type hint
        # factories under Python >= 3.13, which generalized various one-argument
        # type hint factories to accept an additional optional child type hint
        # via "PEP 696 – Type Defaults for Type Parameters".
        HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE.update({
            HintSignAsyncContextManager: _ARGS_LEN_1_OR_2,
            HintSignContextManager: _ARGS_LEN_1_OR_2,
        })
    # Else, the active Python interpreter targets Python <= 3.12. In this
    # case...
    else:
        # Add all signs uniquely identifying two-argument type hint factories
        # under Python <= 3.12.
        HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE.update({
            HintSignAsyncContextManager: _ARGS_LEN_1,
            HintSignContextManager: _ARGS_LEN_1,
        })
    # print(f'HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE: {HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE}')

    # ..................{ INIT ~ modules                     }..................
    # For the fully-qualified name of each quasi-standard typing module...
    for typing_module_name in TYPING_MODULE_NAMES:
        # For the unqualified basename of each type hint that is itself a class
        # or callable identifiable by a sign to that sign, map from the
        # fully-qualified name of that type in this module to this sign.
        for hint_basename, hint_sign in (
            _TYPING_ATTR_HINT_BASENAME_TO_SIGN.items()):
            # print(f'[datahintrepr] Mapping hint "{typing_module_name}.{typing_attr_basename}" -> {hint_sign}')
            HINT_MODULE_NAME_TO_HINT_BASENAME_TO_SIGN[
                typing_module_name][hint_basename] = hint_sign

        # For the unqualified basename of each extrinsic pseudo-superclass of a
        # PEP 484- or 585-compliant generic identifiable by a sign to that sign,
        # map from the fully-qualified name of that type in this module to this
        # sign.
        for hint_basename, hint_sign in (
            _TYPING_ATTR_HINT_BASE_EXTRINSIC_BASENAME_TO_SIGN.items()):
            # print(f'[datahintrepr] Mapping hint "{typing_module_name}.{typing_attr_basename}" -> {hint_sign}')
            HINT_MODULE_NAME_TO_HINT_BASE_EXTRINSIC_BASENAME_TO_SIGN[
                typing_module_name][hint_basename] = hint_sign

        # For the unqualified basename of each type of each type hint
        # identifiable by a sign to that sign, map from the fully-qualified name
        # of that type in this module to this sign.
        for type_basename, hint_sign in (
            _TYPING_ATTR_TYPE_BASENAME_TO_SIGN.items()):
            # print(f'[datahintrepr] Mapping type "{typing_module_name}.{typing_attr_basename}" -> {hint_sign}')
            HINT_MODULE_NAME_TO_TYPE_BASENAME_TO_SIGN[
                typing_module_name][type_basename] = hint_sign

        # If the active Python interpreter targets Python 3.11, identify PEP
        # 646- and 692-compliant hints that are instances of the private
        # "typing._UnpackGenericAlias" as "Unpack[...]" hints.
        #
        # Note that this fragile violation of privacy encapsulation is *ONLY*
        # needed under Python 3.11, where the machine-readable representation of
        # unpacked type variable tuples is ambiguously idiosyncratic and thus
        # *NOT* a reasonable heuristic for detecting such unpacking: e.g.,
        #     $ python3.11
        #     >>> from typing import TypeVarTuple
        #     >>> Ts = TypeVarTuple('Ts')
        #     >>> list_of_Ts = [*Ts]
        #     >>> repr(list_of_Ts[0])
        #     *Ts    # <-- ambiguous and thus a significant issue
        #
        #     $ python3.12
        #     >>> from typing import TypeVarTuple
        #     >>> Ts = TypeVarTuple('Ts')
        #     >>> list_of_Ts = [*Ts]
        #     >>> repr(list_of_Ts[0])
        #     typing.Unpack[Ts]    # <-- unambiguous and thus a non-issue
        if IS_PYTHON_3_11:
            HINT_MODULE_NAME_TO_TYPE_BASENAME_TO_SIGN[
                typing_module_name]['_UnpackGenericAlias'] = HintSignUnpack
        # Else, the active Python interpreter does *NOT* target Python 3.11.

    # ..................{ DEBUGGING                          }..................
    # Uncomment as needed to display the contents of these objects.

    # from pprint import pformat
    # print(f'HINT_MODULE_NAME_TO_TYPE_BASENAME_TO_SIGN: {pformat(HINT_MODULE_NAME_TO_TYPE_BASENAME_TO_SIGN)}')

# Initialize this submodule.
_init()
