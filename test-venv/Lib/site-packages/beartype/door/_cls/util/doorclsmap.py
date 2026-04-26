#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **Decidedly Object-Oriented Runtime-checking (DOOR) getters** (i.e.,
low-level callables introspecting metadata pertaining to high-level
:class:`beartype.door.TypeHint` wrappers).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.door._cls.doorsuper import TypeHint
from beartype.door._cls.pep.doorpep484604 import UnionTypeHint
from beartype.door._cls.pep.doorpep586 import LiteralTypeHint
from beartype.door._cls.pep.doorpep593 import AnnotatedTypeHint
from beartype.door._cls.pep.pep484.doorpep484any import AnyTypeHint
from beartype.door._cls.pep.pep484.doorpep484class import ClassTypeHint
from beartype.door._cls.pep.pep484.doorpep484newtype import NewTypeTypeHint
from beartype.door._cls.pep.pep484.doorpep484typevar import TypeVarTypeHint
from beartype.door._cls.pep.pep484585.doorpep484585callable import (
    CallableTypeHint)
from beartype.door._cls.pep.pep484585.doorpep484585generic import (
    GenericTypeHint)
from beartype.door._cls.pep.pep484585.doorpep484585subscripted import (
    SubscriptedTypeHint)
from beartype.door._cls.pep.pep484585.doorpep484585tuple import (
    TupleFixedTypeHint,
    TupleVariableTypeHint,
)
from beartype.roar import (
    BeartypeDoorNonpepException,
    # BeartypeDoorPepUnsupportedException,
)
from beartype.typing import (
    Dict,
    Type,
)
from beartype._data.typing.datatypingport import Hint
from beartype._data.hint.sign.datahintsigncls import HintSign
from beartype._data.hint.sign.datahintsigns import (
    HintSignAnnotated,
    HintSignAny,
    HintSignCallable,
    HintSignLiteral,
    HintSignNewType,
    HintSignPep484585GenericSubbed,
    HintSignPep484585GenericUnsubbed,
    HintSignTuple,
    HintSignPep484585TupleFixed,
    HintSignTypeVar,
)
from beartype._data.hint.sign.datahintsignset import (
    HINT_SIGNS_UNSUBSCRIPTABLE)
from beartype._util.hint.pep.utilpepget import get_hint_pep_args
from beartype._util.hint.pep.utilpepsign import get_hint_pep_sign_or_none
from beartype._util.hint.pep.utilpeptest import is_hint_pep_typing

# ....................{ GETTERS                            }....................
def get_typehint_subclass(hint: Hint) -> Type[TypeHint]:
    '''
    Concrete :class:`TypeHint` subclass handling the passed low-level unwrapped
    PEP-compliant type hint if any *or* raise an exception otherwise.

    Parameters
    ----------
    hint : Hint
        Low-level type hint to be inspected.

    Returns
    -------
    Type[TypeHint]
        Concrete subclass of the abstract :mod:`TypeHint` superclass handling
        this hint.

    Raises
    ------
    beartype.roar.BeartypeDoorNonpepException
        If this API does *not* currently support the passed hint.
    beartype.roar.BeartypeDecorHintPepSignException
        If the passed hint is *not* actually a PEP-compliant type hint.
    '''

    # ..................{ SUBCLASS                           }..................
    # Sign uniquely identifying this hint if any *OR* "None" otherwise (i.e., if
    # this hint is a PEP-noncompliant class).
    hint_sign = get_hint_pep_sign_or_none(hint)

    #FIXME: [SPEED] As a negligible optimization, globalize the
    #_HINT_SIGN_TO_TYPEHINT_CLS.get() method to avoid repeated lookups here.
    # Private concrete subclass of this ABC handling this hint if any *OR*
    # "None" otherwise (i.e., if no such subclass has been authored yet).
    wrapper_subclass = _HINT_SIGN_TO_TYPEHINT_CLS.get(hint_sign)  # type: ignore[arg-type]
    # print(f'Mapping hint {hint} sign {hint_sign} to subclass {wrapper_subclass}...')

    # If this hint appears to be currently unsupported...
    if wrapper_subclass is None:
        # If either...
        if (
            # This hint is a PEP-noncompliant isinstanceable class *OR*...
            isinstance(hint, type) or

            #FIXME: This condition is kinda intense. Should we really be
            #conflating typing attributes that aren't types with objects that
            #are types? Let's investigate exactly which kinds of type hints
            #require this and contemplate something considerably more elegant.
            # An unsupported kind of PEP-compliant type hint (e.g.,
            # "typing.TypedDict" instance)...
            is_hint_pep_typing(hint)
        # Return the concrete "TypeHint" subclass handling all such classes.
        ):
            wrapper_subclass = ClassTypeHint
            # print(f'[type fallback] hint: {repr(hint)}; sign: {repr(hint_sign)}; wrapper: {repr(wrapper_subclass)}')
        # Else, raise an exception.
        else:
            raise BeartypeDoorNonpepException(
                f'Type hint {repr(hint)} '
                f'currently unsupported by "beartype.door.TypeHint".'
            )
    # Else, this hint is supported.

    #FIXME: Instead of reducing to the inappropriate "ClassTypeHint" subclass
    #here, we should instead:
    #* Define a new "UnsubscriptedTypeHint" subclass wherever we currently
    #  define the existing "SubscriptedTypeHint" subclass.
    #* Reduce to "UnsubscriptedTypeHint" rather than "ClassTypeHint" below.

    # If it is *NOT* the case that either...
    elif not (
        # This hint is unsubscriptable (i.e., permissable as a valid hint even
        # when unsubscripted by child hints) and thus *NOT* safely reducible to
        # the "ClassTypeHint" subclass even when unsubscripted *OR*...
        hint_sign in HINT_SIGNS_UNSUBSCRIPTABLE or
        # This hint is subscripted by one or more child hints.
        get_hint_pep_args(hint)
    ):
        # Replace this inappropriate "SubscriptedTypeHint" wrapper with the more
        # appropriate "ClassTypeHint" subclass wrapping unsubscripted types.
        wrapper_subclass = ClassTypeHint
    # # In any case, this hint is supported by this concrete subclass.

    #FIXME: Alternately, it might be preferable to refactor this to resemble:
    #    if (
    #       not get_hint_pep_args(hint) and
    #       get_hint_pep_origin_type_or_none(hint) is not None
    #    ):
    #        wrapper_subclass = ClassTypeHint
    #
    #That's possibly simpler and cleaner, as it seamlessly conveys the exact
    #condition we're going for -- assuming it works, of course. *sigh*
    #FIXME: While sensible, the above approach induces non-trivial test
    #failures. Let's investigate this further at a later time, please.

    # Return this subclass.
    # print(f'Mapped hint {hint} sign {hint_sign} to subclass {wrapper_subclass}!')
    return wrapper_subclass

# ....................{ PRIVATE ~ globals                  }....................
# Further initialized below by the _init() function.
_HINT_SIGN_TO_TYPEHINT_CLS: Dict[HintSign, Type[TypeHint]] = {
    HintSignAnnotated:  AnnotatedTypeHint,
    HintSignAny:        AnyTypeHint,
    HintSignCallable:   CallableTypeHint,
    HintSignLiteral:    LiteralTypeHint,
    HintSignNewType:    NewTypeTypeHint,
    HintSignTuple:      TupleVariableTypeHint,
    HintSignPep484585TupleFixed: TupleFixedTypeHint,
    HintSignTypeVar:    TypeVarTypeHint,
    HintSignPep484585GenericSubbed:   GenericTypeHint,
    HintSignPep484585GenericUnsubbed: GenericTypeHint,
}
'''
Dictionary mapping from each sign uniquely identifying PEP-compliant type hints
to the :class:`.TypeHint` subclass handling those hints.
'''

# ....................{ PRIVATE ~ initializers             }....................
def _init() -> None:
    '''
    Initialize this submodule.
    '''

    # Isolate function-specific imports.
    from beartype._data.hint.sign.datahintsignmap import (
        HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE)
    from beartype._data.hint.sign.datahintsignset import HINT_SIGNS_UNION

    # Fully initialize the "_HINT_SIGN_TO_TYPEHINT_CLS" global dictionary.
    #
    # For each sign in the dictionary mapping from signs uniquely identifying
    # type hint factories originating from isinstanceable types to the fixed
    # number of child type hints subscripting those factories...
    for hint_sign in HINT_SIGN_ORIGIN_ISINSTANCEABLE_TO_ARGS_LEN_RANGE.keys():
        # If this sign has *NOT* already been mapped to an existing "TypeHint"
        # subclass, map this sign to the generic private
        # "SubscriptedTypeHint" subclass.
        if hint_sign not in _HINT_SIGN_TO_TYPEHINT_CLS:
            _HINT_SIGN_TO_TYPEHINT_CLS[hint_sign] = (
                SubscriptedTypeHint)
        # Else, this sign has already been mapped to an existing "TypeHint"
        # subclass. Preserve this mapping as is.

    # For each sign uniquely identifying a union, map this sign to the
    # union-specific "TypeHint" subclass.
    for hint_sign in HINT_SIGNS_UNION:
        _HINT_SIGN_TO_TYPEHINT_CLS[hint_sign] = UnionTypeHint

    # For each concrete "TypeHint" subclass registered with this dictionary
    # (*AFTER* initializing this dictionary)...
    for typehint_cls in _HINT_SIGN_TO_TYPEHINT_CLS.values():
        # If the unqualified basename of this subclass is prefixed by an
        # underscore, this subclass is private rather than public. In this case,
        # silently ignore this private subclass and continue to the next.
        if typehint_cls.__name__.startswith('_'):
            continue
        # Else, this subclass is public.

        # Sanitize the fully-qualified module name of this public subclass from
        # the private submodule declaring this subclass (e.g.,
        # "beartype.door._cls.pep.doorpep484604.UnionTypeHint") to the public
        # "beartype.door" subpackage to both improve the readability of
        # exceptions and discourage users from violating privacy encapsulation.
        typehint_cls.__module__ = 'beartype.door'

# ....................{ MAIN                               }....................
# Initialize this submodule.
_init()
