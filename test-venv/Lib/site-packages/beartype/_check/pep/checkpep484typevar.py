#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`-compliant **type variable type-checkers** (i.e.,
low-level callables validating that arbitrary objects satisfy a given type
variable's associated bounds and/or constraints).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep484TypeVarViolation
from beartype.typing import TypeVar
from beartype._data.typing.datatyping import (
    TypeException,
)
from beartype._data.typing.datatypingport import (
    Hint,
)
from beartype._util.cls.pep.clspep3119 import is_object_issubclassable
from beartype._util.hint.nonpep.utilnonpeptest import is_hint_nonpep_type
from beartype._util.hint.pep.proposal.pep484.pep484typevar import (
    get_hint_pep484_typevar_bounded_constraints_or_none,
    # is_hint_pep484_typevar,
)
from beartype._util.hint.pep.utilpeptest import is_hint_pep

# ....................{ TODO                               }....................
#FIXME: Generalize the die_if_hint_pep484_typevar_bound_unbearable()
#type-checker to generically validate the passed hint to be a full-blown
#*SUBHINT* of the passed type parameter. Specifically, if this type parameter is
#bounded by one or more bounded constraints, then we should validate this hint
#to be a *SUBHINT* of those constraints: e.g.,
#    class MuhClass(object): pass
#
#    # PEP 695 type alias parametrized by a type parameter bound to a
#    # subclass of the "MuhClass" type.
#    type muh_alias[T: MuhClass] = T | int
#
#    # *INVALID.* Ideally, @beartype should reject this, as "int" is
#    # *NOT* a subhint of "MuhClass".
#    def muh_func(muh_arg: muh_alias[int]) -> None: pass
#
#Doing so is complicated, however, by forward reference proxies. For obvious
#reasons, forward reference proxies are *NOT* safely resolvable at this early
#decoration time that this function is typically called at. If this hint either:
#* Is itself a forward reference proxy, ignore rather than validate this hint as
#  a subhint of these bounded constraints. Doing so is trivial by simply calling
#  "is_beartype_forwardref(hint)" here.
#* Is *NOT* itself a forward reference proxy but is transitively subscripted by
#  one or more forward reference proxies, ignore rather than validate this hint
#  as a subhint of these bounded constraints. Doing so is *EXTREMELY
#  NON-TRIVIAL.* Indeed, there's *NO* reasonable way to do so directly here.
#  Rather, we'd probably have to embrace an EAFP approach: that is, just crudely
#  try to:
#  * Detect whether this hint is a subhint of these bounded constraints.
#  * If doing so raises an exception indicative of a forward reference issue,
#    silently ignore that exception.
#
#  Of course, we're unclear what exception type that would even be. Does the
#  beartype.door.is_subhint() tester even explicitly detect forward reference
#  issues and raise an appropriate exception type? No idea. Probably *NOT*,
#  honestly. Interestingly, is_subhint() currently even fails to support
#  standard PEP 484-compliant forward references:
#      >>> is_subhint('int', int)
#      beartype.roar.BeartypeDoorNonpepException: Type hint 'int'
#      currently unsupported by "beartype.door.TypeHint".
#
#Due to these (and probably more) issues, we currently *ONLY* validate this hint
#to be a subhint of these bounded constraints.

# ....................{ RAISERS                            }....................
#FIXME: Unit test us up, please. *sigh*
def die_if_hint_pep484_typevar_bound_unbearable(
    # Mandatory parameters.
    hint: Hint,
    typevar: TypeVar,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep484TypeVarViolation,
    exception_prefix: str = '',
):
    '''
    Raise an exception unless the passed type hint satisfies the bounds and/or
    constraints of the passed :pep:`484`-compliant **type variable** (i.e.,
    :class:`typing.TypeVar` object).

    Equivalently, raise an exception if this hint violates these bounds and/or
    constraints. This raiser thus superficially type-checks this hint against
    this type variable *without* regard for any lookup table previously mapping
    this type variable to another concrete type hint.

    Parameters
    ----------
    hint : Hint
        Type hint to be validated.
    hint : TypeVar
        Type variable to validate this type hint against.
    exception_cls : Type[Exception], default: BeartypeDecorHintPep484TypeVarViolation
        Type of exception to be raised in the event of a fatal error. Defaults
        to :exc:`.BeartypeDecorHintPep484TypeVarViolation`.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    exception_cls
        If this hint violates this type variable's bounds and/or constraints.
    '''

    # If this hint is *NOT* an isinstanceable type after explicitly rejecting
    # beartype-specific forward reference proxies as isinstanceable types, this
    # hint *COULD* possibly be a such a proxy. If this hint is such a proxy,
    # this proxy could be unresolvable at the early time this raiser is called
    # despite otherwise being valid. To avoid raising false positives, this
    # raiser avoids the conundrum entirely by reducing to a noop. *shrug*
    if not is_hint_nonpep_type(hint=hint, is_forwardref_valid=False):
        return
    # Else, this hint is an isinstanceable type.

    # PEP-compliant type hint synthesized from all bounded constraints
    # parametrizing this type variable if any *OR* "None" otherwise (i.e., if
    # this type variable was neither bounded nor constrained).
    #
    # Note that this call is intentionally passed positional rather positional
    # keywords due to memoization.
    typevar_bound = get_hint_pep484_typevar_bounded_constraints_or_none(
        typevar, exception_prefix)
    # print(f'[{typearg}] is_object_issubclassable({typevar_bound})? ...')
    # print(f'{is_object_issubclassable(typevar_bound, False)}')

    # If...
    if (
        # This type variable was bounded or constrained *AND*...
        typevar_bound is not None and
        # These bounded constraints are PEP-noncompliant *AND*...
        #
        # PEP-compliant constraints are *NOT* safely passable to the
        # isinstance() or issubclass() testers, even if they technically are
        # isinstanceable or issubclassable. Why? Consider the "typing.Any"
        # singleton. Under newer Python versions, the "typing.Any" singleton is
        # actually defined as a subclassable type. Although effectively *NO*
        # real-world types subclass "typing.Any", literally *ALL* objects
        # (including types) satisfy the "typing.Any" type hint. Passing
        # "typing.Any" as the second variable to the issubclass() tester below
        # would thus erroneously reject (rather than silently accept) *ALL*
        # objects as unconditionally violating these bounds.
        not is_hint_pep(typevar_bound) and
        # These bounded constraints are issubclassable (i.e., an object safely
        # passable as the second variable to the issubclass() builtin) *AND*...
        #
        # Note that this function is memoized and thus permits *ONLY* positional
        # variables.
        is_object_issubclassable(
            typevar_bound,
            # Ignore unresolvable forward reference proxies (i.e.,
            # beartype-specific objects referring to user-defined external types
            # that have yet to be defined).
            False,
        ) and
        # This PEP-noncompliant isinstanceable type hint is *NOT* a subclass of
        # these bounded constraints...
        not issubclass(hint, typevar_bound)  # type: ignore[arg-type]
    ):
        # Raise a type-checking violation.
        raise BeartypeDecorHintPep484TypeVarViolation(
            message=(
                f'{exception_prefix}type hint {repr(hint)} violates '
                f'PEP 484 type variable {repr(typevar)} '
                f'bounds or constraints {repr(typevar_bound)}.'
            ),
            culprits=(hint,),
        )
    # Else, this type variable was either:
    # * Unbounded and unconstrained.
    # * Bounded or constrained by a hint that is *NOT* issubclassable.
    # * Bounded or constrained by an issubclassable object that is the
    #   superclass of this corresponding hint, which thus satisfies these
    #   bounded constraints.
