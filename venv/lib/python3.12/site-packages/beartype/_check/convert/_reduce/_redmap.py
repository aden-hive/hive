#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide **type hint reducer mappings** (i.e., low-level dictionaries
mapping from signs uniquely identifying type hints to low-level callables
converting those hints from one format into another).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.typing import (
    Dict,
    Optional,
)
from beartype._check.convert._reduce._nonpep.rednonpeptype import (
    reduce_hint_nonpep_type)
from beartype._check.convert._reduce._nonpep.api.redapinumpy import (
    reduce_hint_numpy_ndarray)
from beartype._check.convert._reduce._nonpep.api.redapipandera import (
    reduce_hint_pandera)
from beartype._check.convert._reduce._pep.pep484.redpep484 import (
    reduce_hint_pep484_any,
    reduce_hint_pep484_deprecated,
    reduce_hint_pep484_none,
)
from beartype._check.convert._reduce._pep.redpep484612646 import (
    reduce_hint_pep484612646_typearg)
from beartype._check.convert._reduce._pep.pep484585.redpep484585generic import (
    reduce_hint_pep484585_generic_subbed,
    reduce_hint_pep484585_generic_unsubbed,
)
from beartype._check.convert._reduce._pep.pep484585.redpep484585itemsview import (
    reduce_hint_pep484585_itemsview)
from beartype._check.convert._reduce._pep.pep484585.redpep484585type import (
    reduce_hint_pep484585_type)
from beartype._check.convert._reduce._pep.redpep484604 import (
    reduce_hint_pep484604)
from beartype._check.convert._reduce._pep.redpep544 import reduce_hint_pep544
from beartype._check.convert._reduce._pep.redpep557 import (
    reduce_hint_pep557_initvar)
from beartype._check.convert._reduce._pep.redpep585 import (
    reduce_hint_pep585_builtin_subbed_unknown)
from beartype._check.convert._reduce._pep.redpep589 import reduce_hint_pep589
from beartype._check.convert._reduce._pep.redpep591 import reduce_hint_pep591
from beartype._check.convert._reduce._pep.redpep593 import reduce_hint_pep593
from beartype._check.convert._reduce._pep.redpep646 import (
    reduce_hint_pep646_tuple)
from beartype._check.convert._reduce._pep.redpep647742 import (
    reduce_hint_pep647742)
from beartype._check.convert._reduce._pep.redpep673 import reduce_hint_pep673
from beartype._check.convert._reduce._pep.redpep675 import reduce_hint_pep675
from beartype._check.convert._reduce._pep.redpep692 import reduce_hint_pep692
from beartype._check.convert._reduce._pep.redpep695 import (
    reduce_hint_pep695_subbed,
    reduce_hint_pep695_unsubbed,
)
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.hint.sign.datahintsigns import (
    HintSignAbstractSet,
    HintSignAnnotated,
    HintSignAny,
    HintSignAsyncContextManager,
    HintSignAsyncGenerator,
    HintSignAsyncIterable,
    HintSignAsyncIterator,
    HintSignAwaitable,
    HintSignByteString,
    HintSignCallable,
    HintSignChainMap,
    HintSignCollection,
    HintSignContainer,
    HintSignContextManager,
    HintSignCoroutine,
    HintSignCounter,
    HintSignDefaultDict,
    HintSignDeque,
    HintSignDict,
    HintSignFinal,
    HintSignFrozenSet,
    HintSignGenerator,
    HintSignHashable,
    HintSignItemsView,
    HintSignIterable,
    HintSignIterator,
    HintSignKeysView,
    HintSignList,
    HintSignLiteralString,
    HintSignMappingView,
    HintSignMapping,
    HintSignMatch,
    HintSignMutableMapping,
    HintSignMutableSequence,
    HintSignMutableSet,
    HintSignNewType,
    HintSignNone,
    HintSignNumpyArray,
    HintSignOptional,
    HintSignOrderedDict,
    HintSignPanderaAny,
    HintSignParamSpecArgs,
    HintSignParamSpecKwargs,
    HintSignPattern,
    HintSignPep484585GenericSubbed,
    HintSignPep484585GenericUnsubbed,
    HintSignPep557DataclassInitVar,
    HintSignPep585BuiltinSubscriptedUnknown,
    HintSignPep646TupleFixedVariadic,
    HintSignPep646TypeVarTupleUnpacked,
    HintSignPep692TypedDictUnpacked,
    HintSignPep695TypeAliasUnsubscripted,
    HintSignPep695TypeAliasSubscripted,
    HintSignProtocol,
    HintSignReversible,
    HintSignSelf,
    HintSignSequence,
    HintSignSet,
    HintSignSized,
    HintSignTuple,
    HintSignPep484585TupleFixed,
    HintSignType,
    HintSignTypeAlias,
    HintSignTypeGuard,
    HintSignTypeIs,
    HintSignTypeVar,
    HintSignTypedDict,
    HintSignUnion,
    HintSignValuesView,
)
from beartype._util.hint.pep.proposal.pep484.pep484newtype import (
    get_hint_pep484_newtype_alias)
from beartype._util.hint.pep.proposal.pep612 import (
    reduce_hint_pep612_args,
    reduce_hint_pep612_kwargs,
)
from beartype._util.hint.pep.proposal.pep613 import reduce_hint_pep613
from collections.abc import Callable

# ....................{ PRIVATE ~ hints                    }....................
# Note that these type hints would ideally be defined with the mypy-specific
# "callback protocol" pseudostandard, documented here:
#     https://mypy.readthedocs.io/en/stable/protocols.html#callback-protocols
#
# Doing so would enable static type-checkers to type-check that the values of
# these dictionaries are valid reducer functions. Sadly, that pseudostandard is
# absurdly strict to the point of practical uselessness. Attempting to conform
# to that pseudostandard would require refactoring *ALL* reducer functions to
# explicitly define the same signature. However, we have intentionally *NOT*
# done that. Why? Doing so would substantially increase the fragility of this
# API by preventing us from readily adding and removing infrequently required
# parameters (e.g., "cls_stack", "pith_name"). Callback protocols suck, frankly.
_HintSignToReduceHintCached = Dict[Optional[HintSign], Callable]
'''
PEP-compliant type hint matching a **cached reducer dictionary** (i.e., mapping
from each sign uniquely identifying various type hints to a memoized callable
reducing those higher- to lower-level hints).
'''


_HintSignToReduceHintUncached = _HintSignToReduceHintCached
'''
PEP-compliant type hint matching an **uncached reducer dictionary** (i.e.,
mapping from each sign uniquely identifying various type hints to an unmemoized
callable reducing those higher- to lower-level hints).
'''

# ....................{ MAPPINGS ~ cached                  }....................
HINT_SIGN_TO_REDUCE_HINT_CACHED: _HintSignToReduceHintCached = {
    # ..................{ NON-PEP                            }..................
    # If this hint is identified by *NO* sign, this hint is either:
    # * A valid PEP-noncompliant isinstanceable type, in which case this reducer
    #   preserves this type as is.
    # * A valid PEP-compliant hint unrecognized by beartype, in which case
    #   this reducer raises an exception.
    # * An invalid and thus PEP-noncompliant hint, in which case this reducer
    #   raises an exception.
    None: reduce_hint_nonpep_type,

    # ..................{ PEP 484                            }..................
    # Reduce the PEP 484-compliant "Any" singleton to the ignorable
    # "HINT_SANE_IGNORABLE" singleton.
    HintSignAny: reduce_hint_pep484_any,

    # Reduce PEP 484-compliant new types to the non-new type type hints (i.e.,
    # PEP-compliant type hints *NOT* new types) aliased by these new types.
    HintSignNewType: get_hint_pep484_newtype_alias,

    # If this hint is the PEP 484-compliant "None" singleton, reduce this hint
    # to the type of that singleton. While *NOT* explicitly defined by the
    # "typing" module, PEP 484 explicitly supports this singleton:
    #     When used in a type hint, the expression None is considered
    #     equivalent to type(None).
    #
    # The "None" singleton is used to type callables lacking an explicit
    # "return" statement and thus absurdly common.
    HintSignNone: reduce_hint_pep484_none,

    # ..................{ PEP (484|585)                      }..................
    # If this hint is a PEP 484- or 585-compliant items view type hint, reduce
    # this hint to a more trivially consumable PEP 593-compliant type hint.
    HintSignItemsView: reduce_hint_pep484585_itemsview,

    # If this hint is a PEP 484-compliant IO generic base class, reduce this
    # functionally useless hint to the corresponding functionally useful
    # beartype-specific PEP 544-compliant protocol implementing this hint.
    HintSignPep484585GenericUnsubbed: (
        reduce_hint_pep484585_generic_unsubbed),

    # ..................{ PEP 544                            }..................
    # Ignore *ALL* PEP 544-compliant "typing.Protocol[...]" subscriptions.
    HintSignProtocol: reduce_hint_pep544,

    # ..................{ PEP 557                            }..................
    # If this hint is a dataclass-specific initialization-only instance
    # variable (i.e., instance of the PEP 557-compliant "dataclasses.InitVar"
    # class introduced by Python 3.8.0), reduce this functionally useless hint
    # to the functionally useful child type hint subscripting this parent hint.
    HintSignPep557DataclassInitVar: reduce_hint_pep557_initvar,

    # ..................{ PEP 585                            }..................
    #FIXME: *NON-IDEAL.* Some hints superficially identified as
    #"HintSignPep585BuiltinSubscriptedUnknown" are actually deeply
    #type-checkable as is. This is the case for *ALL* builtin collection type
    #subclasses, for example -- hardly an uncommon edge case: e.g.,
    #    >>> from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign
    #    >>> class UserList(list): pass
    #    >>> get_hint_pep_sign(UserList[str])
    #    HintSignPep585BuiltinSubscriptedUnknown
    #
    #Although "UserList[str]" is identified as unknown, "UserList[str]" is
    #deeply type-checkable as a PEP 593-compliant type hint resembling:
    #    Annotated[List[str], IsInstance[UserList]]
    #
    #That is to say, "UserList[str]" should be deeply type-checked as
    #semantically equivalent to "List[str]" that just happens to be an instance
    #of "UserList" rather than "list".
    #
    #Thankfully, this isn't terribly arduous to support. Generalize
    #reduce_hint_pep585_builtin_subbed_unknown() as follows. The basic idea
    #is to just defer to the existing
    #_infer_hint_factory_collection_builtin() function, which interestingly does
    #a great deal of what we already need:
    #    def reduce_hint_pep585_builtin_subbed_unknown(
    #        hint: object, *args, **kwargs) -> type:
    #
    #        # Avoid circular import dependencies.
    #        from beartype.door._func.infer.collection.infercollectionbuiltin import (
    #            _infer_hint_factory_collection_builtin)
    #        from beartype._util.api.standard.utiltyping import import_typing_attr_or_none
    #        from beartype._util.hint.pep.utilpepget import (
    #            get_hint_pep_args,
    #            get_hint_pep_origin_type,
    #        )
    #
    #        # Pure-Python origin type originating this unrecognized subscripted builtin
    #        # type hint if this hint originates from such a type *OR* raise an
    #        # exception otherwise (i.e., if this hint originates from *NO* such type).
    #        hint_origin_type = get_hint_pep_origin_type(hint)
    #
    #        # Hint to be returned, defaulting to this origin type.
    #        hint = hint_origin_type
    #
    #        builtin_factory, builtin_origin_type = _infer_hint_factory_collection_builtin(
    #            hint_origin_type)
    #
    #        if builtin_factory is not None:
    #            Annotated = import_typing_attr_or_none('Annotated')
    #
    #            if Annotated is not None:
    #                # Defer heavyweight imports.
    #                from beartype.vale import IsInstance
    #
    #                hint_args = get_hint_pep_args(hint)
    #
    #                #FIXME: Unsure if this works. If not, try:
    #                #    hint_builtin = builtin_factory.__getitem__(*hint_args)
    #                #FIXME: Can "hint_args" be the empty tuple here? Probably.
    #                #We should probably avoid unpacking at all in that case.
    #                hint_builtin = builtin_factory[*hint_args]
    #
    #                hint = Annotated[hint_builtin, IsInstance[hint_origin_type]]
    #
    #        # Return this hint.
    #        return hint
    #
    #Since the _infer_hint_factory_collection_builtin() function appears to be
    #of public relevance, let's at least rename that to
    #infer_hint_factory_collection_builtin().
    #
    #Pretty cool, eh? Fairly trivial and *SHOULD* definitely work. Let's give
    #this a go as time permits, please.

    # If this hint is a PEP 585-compliant unrecognized subscripted builtin type
    # hint (i.e., C-based type hint that is *NOT* an isinstanceable type,
    # instantiated by subscripting a pure-Python origin class subclassing the
    # C-based "types.GenericAlias" type where that origin class is unrecognized
    # by :mod:`beartype` and thus PEP-noncompliant), reduce this C-based type
    # hint (which is *NOT* type-checkable as is) to its unsubscripted
    # pure-Python origin class (which is type-checkable as is). Examples include
    # "os.PathLike[...]" and "weakref.weakref[...]" type hints.
    HintSignPep585BuiltinSubscriptedUnknown: (
        reduce_hint_pep585_builtin_subbed_unknown),

    # ..................{ PEP 589                            }..................
    #FIXME: Remove *AFTER* deeply type-checking typed dictionaries. For now,
    #shallowly type-checking such hints by reduction to untyped dictionaries
    #remains the sanest temporary work-around.

    # If this hint is a PEP 589-compliant typed dictionary (i.e.,
    # "typing.TypedDict" or "typing_extensions.TypedDict" subclass), silently
    # ignore all child type hints annotating this dictionary by reducing this
    # hint to the "Mapping" superclass. Yes, "Mapping" rather than "dict". By
    # PEP 589 edict:
    #     First, any TypedDict type is consistent with Mapping[str, object].
    #
    # Typed dictionaries are largely discouraged in the typing community, due to
    # their non-standard semantics and syntax.
    HintSignTypedDict: reduce_hint_pep589,

    # ..................{ PEP 591                            }..................
    #FIXME: Remove *AFTER* deeply type-checking final type hints.

    # If this hint is a PEP 591-compliant "typing.Final[...]" type hint,
    # silently reduce this hint to its subscripted argument (e.g., from
    # "typing.Final[int]" to merely "int").
    HintSignFinal: reduce_hint_pep591,

    # ..................{ PEP 593                            }..................
    # If this hint is a PEP 593-compliant beartype-agnostic type metahint,
    # ignore all annotations on this hint by reducing this hint to the
    # lower-level hint it annotates.
    HintSignAnnotated: reduce_hint_pep593,

    # ..................{ PEP 646                            }..................
    # If this hint is a PEP 646-compliant tuple hint (i.e., tuple hint
    # subscripted by one or more PEP 646-compliant unpacked child hints), reduce
    # this hint to the semantically equivalent PEP 585-compliant fixed- or
    # variable-length tuple hint if feasible.
    HintSignPep646TupleFixedVariadic: reduce_hint_pep646_tuple,

    # ..................{ PEP 675                            }..................
    #FIXME: Remove *AFTER* deeply type-checking literal strings. Note that doing
    #so will prove extremely non-trivial or possibly even infeasible, suggesting
    #we will probably *NEVER* deeply type-check literal strings. It's *NOT*
    #simply a matter of efficiently parsing ASTs at runtime; it's that as well
    #as correctly transitively inferring literal strings across operations and
    #calls, which effectively requires parsing the entire codebase and
    #constructing an in-memory graph of all type relations. See also:
    #    https://peps.python.org/pep-0675/#inferring-literalstring

    # If this hint is a PEP 675-compliant "typing.LiteralString" type hint,
    # reduce this hint to the standard "str" type.
    HintSignLiteralString: reduce_hint_pep675,

    # ..................{ NON-PEP ~ numpy                    }..................
    # If this hint is a PEP-noncompliant typed NumPy array (e.g.,
    # "numpy.typing.NDArray[np.float64]"), reduce this hint to the equivalent
    # well-supported beartype validator.
    HintSignNumpyArray: reduce_hint_numpy_ndarray,

    # ..................{ NON-PEP ~ pandera                  }..................
    # If this hint is *ANY* PEP-noncompliant Pandera type hint (e.g.,
    # "pandera.typing.DataFrame[...]"), reduce this hint to an arbitrary
    # PEP-compliant ignorable type hint. See this reducer for commentary.
    HintSignPanderaAny: reduce_hint_pandera,
}
'''
Dictionary mapping from each sign uniquely identifying PEP-compliant type hints
to that sign's **cached reducer** (i.e., low-level function efficiently memoized
by the :func:`.callable_cached` decorator reducing those higher- to lower-level
hints).

Each value of this dictionary is expected to have a signature resembling:

.. code-block:: python

   def reduce_hint_pep{pep_number}(
       hint: object,
       conf: BeartypeConf,
       pith_name: Optional[str],
       exception_prefix: str,
       *args, **kwargs
   ) -> object:

Note that:

* Reducers should explicitly accept *only* those parameters they explicitly
  require. Ergo, a reducer requiring *only* the ``hint`` parameter should omit
  all of the other parameters referenced above.
* Reducers do *not* need to validate the passed type hint as being of the
  expected sign. By design, a reducer is only ever passed a type hint of the
  expected sign.
* Reducers should *not* be memoized (e.g., by the
  ``callable_cached`` decorator). Since the higher-level :func:`.reduce_hint`
  function that is the sole entry point to calling all lower-level reducers is
  itself memoized, reducers themselves neither require nor benefit from
  memoization. Moreover, even if they did either require or benefit from
  memoization, they couldn't be -- at least, not directly. Why? Because
  :func:`.reduce_hint` necessarily passes keyword arguments to all reducers. But
  memoized functions *cannot* receive keyword arguments (without destroying
  efficiency and thus the entire point of memoization).
'''

# ....................{ MAPPINGS ~ uncached                }....................
HINT_SIGN_TO_REDUCE_HINT_UNCACHED: _HintSignToReduceHintUncached = {
    # ..................{ PEP 484                            }..................
    # Reduce PEP 484-compliant type variables that have subsequently been
    # semantically (but *NOT* syntactically) "replaced" by concrete hints to
    # those hints, usually due to higher-level hints initially parametrized by
    # those type variables then being subscripted by those concrete hints.
    #
    # tl;dr: the "typearg_to_hint" dictionary, which is uncached.
    HintSignTypeVar: reduce_hint_pep484612646_typearg,

    # Preserve deprecated PEP 484-compliant hints while emitting one non-fatal
    # deprecation warning for each.
    #
    # Note that:
    # * To ensure that one such warning is emitted for each such hint, these
    #   reducers are intentionally uncached rather than cached.
    # * To avoid conflict with more specific reducers mapped elsewhere, these
    #   signs that would otherwise be mapped here are intentionally omitted:
    #   * "HintSignItemsView", instead mapped to the more specific
    #     reduce_hint_pep484585_itemsview() reducer.
    HintSignAbstractSet: reduce_hint_pep484_deprecated,
    HintSignAsyncContextManager: reduce_hint_pep484_deprecated,
    HintSignAsyncGenerator: reduce_hint_pep484_deprecated,
    HintSignAsyncIterable: reduce_hint_pep484_deprecated,
    HintSignAsyncIterator: reduce_hint_pep484_deprecated,
    HintSignAwaitable: reduce_hint_pep484_deprecated,
    HintSignByteString: reduce_hint_pep484_deprecated,
    HintSignCallable: reduce_hint_pep484_deprecated,
    HintSignChainMap: reduce_hint_pep484_deprecated,
    HintSignCollection: reduce_hint_pep484_deprecated,
    HintSignContainer: reduce_hint_pep484_deprecated,
    HintSignContextManager: reduce_hint_pep484_deprecated,
    HintSignCoroutine: reduce_hint_pep484_deprecated,
    HintSignCounter: reduce_hint_pep484_deprecated,
    HintSignDefaultDict: reduce_hint_pep484_deprecated,
    HintSignDeque: reduce_hint_pep484_deprecated,
    HintSignDict: reduce_hint_pep484_deprecated,
    HintSignFrozenSet: reduce_hint_pep484_deprecated,
    HintSignGenerator: reduce_hint_pep484_deprecated,
    HintSignHashable: reduce_hint_pep484_deprecated,
    HintSignIterable: reduce_hint_pep484_deprecated,
    HintSignIterator: reduce_hint_pep484_deprecated,
    HintSignKeysView: reduce_hint_pep484_deprecated,
    HintSignList: reduce_hint_pep484_deprecated,
    HintSignMappingView: reduce_hint_pep484_deprecated,
    HintSignMapping: reduce_hint_pep484_deprecated,
    HintSignMatch: reduce_hint_pep484_deprecated,
    HintSignMutableMapping: reduce_hint_pep484_deprecated,
    HintSignMutableSequence: reduce_hint_pep484_deprecated,
    HintSignMutableSet: reduce_hint_pep484_deprecated,
    HintSignOrderedDict: reduce_hint_pep484_deprecated,
    HintSignPattern: reduce_hint_pep484_deprecated,
    HintSignReversible: reduce_hint_pep484_deprecated,
    HintSignSequence: reduce_hint_pep484_deprecated,
    HintSignSet: reduce_hint_pep484_deprecated,
    HintSignSized: reduce_hint_pep484_deprecated,
    HintSignTuple: reduce_hint_pep484_deprecated,
    HintSignPep484585TupleFixed: reduce_hint_pep484_deprecated,
    HintSignValuesView: reduce_hint_pep484_deprecated,

    # Note that the reducers for these signs mapped below call this reducer.
    # HintSignType: reduce_hint_pep484_deprecated,

    # ..................{ PEP (484|585)                      }..................
    # If this hint is a PEP 484- or 585-compliant subscripted generic:
    # * Reduce this alias to the unsubscripted generic underlying this
    #   subscripted generic.
    # * Map the child hint subscripting this subscripted generic to the PEP
    #   484-compliant type variable parametrizing that unsubscripted generic.
    HintSignPep484585GenericSubbed: reduce_hint_pep484585_generic_subbed,

    # If this hint is a PEP 484- or 585-compliant subclass hint subscripted
    # by an ignorable child hint (e.g., "object", "typing.Any"), silently
    # ignore this child hint by reducing this hint to the "type" superclass.
    #
    # Note that doing so requires recursively reducing this child hint first.
    # Since this child hints may require an uncached reduction in the worst
    # case, reducing subclass hints *ALSO* requires an uncached reduction in the
    # worst case. This is that case.
    HintSignType: reduce_hint_pep484585_type,

    # ..................{ PEP (484|604)                      }..................
    # Reduce PEP 484- and 604-compliant unions subscripted by one or more
    # ignorable child hints to the ignorable "HINT_SANE_IGNORABLE" singleton.
    #
    # Note that doing so requires recursively reducing these child hints first.
    # Since one or more of these child hints may require an uncached reduction
    # in the worst case, reducing unions *ALSO* requires an uncached reduction
    # in the worst case. This is that case.
    HintSignOptional: reduce_hint_pep484604,
    HintSignUnion:    reduce_hint_pep484604,

    # ..................{ PEP 612                            }..................
    #FIXME: Ideally, PEP 612-compliant type hints like "*args: P.args" and
    #"**kwargs: P.kwargs" would be runtime-checkable. However, it's unclear
    #whether these hints even *CAN* be runtime type-checked in theory -- let
    #alone practice. For the moment, shallowly ignoring them is the best that
    #@beartype can do. Let's readdress this if and when @beartype begins deeply
    #type-checking type variables (i.e., "typing.TypeVar" objects), which share
    #a vague similarity with PEP 612-compliant "typing.ParamSpec" objects.

    # Reduce PEP 612-compliant type hints that are instances of the low-level
    # C-based "typing.ParamSpecArgs" or "typing.ParamSpecKwargs" types when
    # annotating variadic positional or keyword arguments with syntax resembling
    # "*args: P.args" or "**kwargs: P.kwargs" to an arbitrary ignorable hint.
    HintSignParamSpecArgs:   reduce_hint_pep612_args,
    HintSignParamSpecKwargs: reduce_hint_pep612_kwargs,

    # ..................{ PEP 613                            }..................
    # Reduce PEP 613-compliant "typing.TypeAlias" type hints to an arbitrary
    # ignorable type hint *AND* emit a non-fatal deprecation warning.
    #
    # Note that, to ensure that one such warning is emitted for each such hint,
    # this reducer is intentionally uncached rather than cached.
    HintSignTypeAlias: reduce_hint_pep613,

    # ..................{ PEP 646                            }..................
    # Reduce PEP 646-compliant unpacked type variable tuples (i.e., hints of the
    # form "typing.Unpack[{typevartuple}]" hints where "{typevartuple}" is a
    # "typing.TypeVarTuple" object) that have subsequently been semantically
    # (but *NOT* syntactically) "replaced" by concrete hints to those hints,
    # usually due to higher-level hints initially parametrized by those type
    # variable tuples then being subscripted by those concrete hints.
    #
    # tl;dr: the "typearg_to_hint" dictionary, which is uncached.
    HintSignPep646TypeVarTupleUnpacked: reduce_hint_pep484612646_typearg,

    # ..................{ PEP 692                            }..................
    # Reduce PEP 692-compliant unpacked typed dictionaries (i.e., hints of the
    # form "typing.Unpack[{typeddict}]" hints where "{typeddict}" is a PEP
    # 589-compliant "typing.TypedDict" subclass) annotating the variadic
    # positional argument of some callable to the ignorable
    # "HINT_SANE_IGNORABLE" singleton.
    HintSignPep692TypedDictUnpacked: reduce_hint_pep692,

    # ..................{ PEP 647                            }..................
    # Reduce PEP 647-compliant "typing.TypeIs[...]" type hints to either:
    # * If this hint annotates the return of some callable, the "bool" type.
    # * Else, raise an exception.
    HintSignTypeGuard: reduce_hint_pep647742,

    # ..................{ PEP 673                            }..................
    # Reduce PEP 673-compliant "typing.Self" type hints to either:
    # * If @beartype is currently decorating a class, the most deeply nested
    #   class on the passed type stack.
    # * Else, raise an exception.
    HintSignSelf: reduce_hint_pep673,

    # ..................{ PEP 695                            }..................
    # If this hint is a PEP 695-compliant subscripted type alias:
    # * Reduce this alias to the underlying hint referred to by the
    #   unsubscripted type alias underlying this subscripted type alias.
    # * Map the PEP 484-compliant type variables parametrizing that
    #   unsubscripted type alias to the child hints subscripting this
    #   subscripted type alias.
    HintSignPep695TypeAliasSubscripted: reduce_hint_pep695_subbed,

    # If this hint is a PEP 695-compliant unsubscripted type alias, reduce this
    # alias to the underlying hint lazily referred to by this alias.
    HintSignPep695TypeAliasUnsubscripted: reduce_hint_pep695_unsubbed,

    # ..................{ PEP 742                            }..................
    # Reduce PEP 742-compliant "typing.TypeIs[...]" type hints to either:
    # * If this hint annotates the return of some callable, the "bool" type.
    # * Else, raise an exception.
    HintSignTypeIs: reduce_hint_pep647742,
}
'''
Dictionary mapping from each sign uniquely identifying various type hints to
that sign's **uncached reducer** (i.e., low-level function whose reduction
decision contextually depends on the currently decorated callable and thus
*cannot* be efficiently memoized by the :func:`.callable_cached` decorator).

See Also
--------
:data:`._HINT_SIGN_TO_REDUCE_HINT_CACHED`
    Further details.
'''

# ....................{ METHODS                            }....................
HINT_SIGN_TO_REDUCE_HINT_CACHED_get = HINT_SIGN_TO_REDUCE_HINT_CACHED.get
'''
:meth:`_HINT_SIGN_TO_REDUCE_HINT_CACHED.get` method globalized for negligible
lookup gains when subsequently calling this method.
'''


HINT_SIGN_TO_REDUCE_HINT_UNCACHED_get = HINT_SIGN_TO_REDUCE_HINT_UNCACHED.get
'''
:meth:`_HINT_SIGN_TO_REDUCE_HINT_UNCACHED.get` method globalized for negligible
lookup gains when subsequently calling this method.
'''
