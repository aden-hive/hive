#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`484`-compliant **type variable utilities** (i.e.,
callables generically applicable to :pep:`484`-compliant type variables).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep484TypeVarException
from beartype.typing import TypeVar
from beartype._data.kind.datakindiota import SENTINEL
from beartype._data.typing.datatyping import TypeException
from beartype._data.typing.datatypingport import (
    Hint,
    HintOrNone,
    TypeIs,
)
from beartype._util.cache.utilcachecall import callable_cached

# ....................{ RAISERS                            }....................
#FIXME: Unit test us up, please. *sigh*
def die_unless_hint_pep484_typevar(
    # Mandatory parameters.
    hint: TypeVar,

    # Optional parameters.
    exception_cls: TypeException = BeartypeDecorHintPep484TypeVarException,
    exception_prefix: str = '',
) -> None:
    '''
    Raise the passed exception unless the passed type hint is a
    :pep:`484`-compliant **type variable** (i.e., :class:`.TypeVar` object).

    Parameters
    ----------
    hint : TypeVar
        Type hint to be inspected.
    exception_cls : TypeException, default: BeartypeDecorHintPep484TypeVarException
        Type of exception to be raised. Defaults to
        :exc:`.BeartypeDecorHintPep484TypeVarException`.
    exception_prefix : str, default: ''
        Human-readable substring prefixing raised exception messages. Defaults
        to the empty string.

    Raises
    ------
    exception_cls
        If this hint is *not* a type variable.
    '''

    # If this hint is *NOT* a type variable...
    if not is_hint_pep484_typevar(hint):  # pyright: ignore
        assert isinstance(exception_cls, type), (
            f'{repr(exception_cls)} not type.')
        assert isinstance(exception_prefix, str), (
            f'{repr(exception_prefix)} not string.')

        # Raise an exception of this type prefixed by this prefix.
        raise exception_cls(
            f'{exception_prefix}type hint {repr(hint)} '
            f'not PEP 484 type variable.'
        )
    # Else, this hint is a type variable.

# ....................{ TESTERS                            }....................
#FIXME: Unit test us up, please.
def is_hint_pep484_typevar(hint: Hint) -> TypeIs[TypeVar]:  # pyright: ignore
    '''
    :data:`True` only if the passed object is a :pep:`484`-compliant **type
    variable** (i.e., :class:`typing.TypeVar` object).
    '''

    # Although this test currently reduces to a trivial one-liner, it's *NOT*
    # inconceivable that this test could become non-trivial under a subsequent
    # CPython version. *shrug*
    return isinstance(hint, TypeVar)

# ....................{ GETTERS                            }....................
#FIXME: *UHM.* We probably shouldn't be treating type variable constraints and
#upper bounds as semantically equivalent. They're really not at all. We suspect
#our younger self was simply confused by the frankly unreadable PEP
#documentation surrounding this subject. In a readable nutshell:
#* Type variable *BOUNDS* are arbitrary type hints. An object satisfies a type
#  variable bound if and only if that object is an instance of that bound (i.e.,
#  the type hint of that object is a subhint of that bound). Subclasses are thus
#  permitted. Standard code generation thus suffices here.
#* Type variable *CONSTRAINTS* are a tuple of one or more... what exactly?
#  Types? Type hints? If merely types, constraints are trivial to support. If
#  arbitrary type hints, however, constraints are definitely non-trivial to
#  support. We suspect that, as with bounds, constraints may be arbitrary type
#  hints. *sigh*
#
#  In either case, the distinction is clear: an object satisfies a type variable
#  constraint if and only if that object is *EXACTLY* matched by one of those
#  constraints (i.e., the type hint of that object is exactly one of those
#  constraints). Subclasses are thus prohibited. This is non-trivial to support,
#  as the only means of performing exact type hint matching is probably to:
#  * Call "beartype.bite.infer_hint(obj)" to infer the type hint for an object.
#  * Iteratively test whether that hint is one of these constraints.
#
#  That's pretty awful, though. We really shouldn't be calling infer_hint() on
#  arbitrary objects at type-checking time.
#
#  An alternative presents itself. It's extremely non-trivial, but something we
#  probably need to do anyway to support contravariant, covariant, and invariant
#  type variables. If you consider the formal definitions of bounds and
#  constraints, it's clear that:
#  * Bounds are type-checked *COVARIANTLY.* This is what almost everyone wants.
#    It's also how isinstance() and issubclass() work. So, it's how runtime
#    type-checkers behave out-of-the-box. Easy.
#  * Constraints are type-checked *INVARIANTLY.*
#
#  First, consider how our code generation algorithm currently type-checks
#  types: it assumes covariance everywhere by calling isinstance() and
#  issubclass() to perform type-checks. But what if we instead augmented our
#  make_check_expr() factory to internally track what the current kind of
#  type-checking variance is? Notably, we could:
#  * Define a new "CheckVariance" enumeration somewhere resembling:
#        class CheckVariance(Enum):
#            COVARIANCE = auto()  # <-- standard default, thus first
#            CONTRAVARIANCE = auto()
#            INVARIANCE = auto()
#  * Add a new "check_variance: CheckVariance = CheckVariance.COVARIANCE"
#    instance variable to our existing "HintMeta" dataclass.
#  * Refactor this get_hint_pep484_typevar_bounded_constraints_or_none() to return a 2-tuple
#    "(typevar_bound, check_variance)" where:
#    * "typevar_bound" is the current return value.
#    * "check_variance" is either:
#      * "None" if this type variable is unbounded and unconstrained.
#      * "CheckVariance.COVARIANCE" if this type variable is bounded.
#      * "CheckVariance.INVARIANCE" if this type variable is constrained.
#  * Refactor make_check_expr() to:
#    * Track this new "HintMeta.check_variance" instance variable. Mostly
#      trivial. Child hints inherit their parent hint's "check_variance".
#    * Dynamically generate code appropriate for this new
#      "HintMeta.check_variance" instance variable. That's the super-hard part.
#      Even if we initially ignore "CheckVariance.CONTRAVARIANCE" (which we
#      really should), we'd still basically have to:
#      * Refactor *MOST* single magic code string globals into dictionary
#        globals mapping from all possible "CheckVariance" members to the
#        corresponding magic code strings appropriate for those variances.
#      * Lookup the appropriate magic code strings in those dictionaries with
#        the current "hint_curr_meta.check_variable" instance variable.
#
#  Kinda fun, but *REALLY* non-trivial -- and probably no one cares. Guh!
@callable_cached
def get_hint_pep484_typevar_bounded_constraints_or_none(
    # Mandatory parameters.
    hint: TypeVar,

    # Optional parameters.
    exception_prefix: str = '',
) -> HintOrNone:
    '''
    PEP-compliant type hint synthesized from all bounded constraints
    parametrizing the passed :pep:`484`-compliant **type variable** (i.e.,
    :class:`typing.TypeVar` instance) if any *or* :data:`None` otherwise (i.e.,
    if this type variable was parametrized by *no* bounded constraints).

    Specifically, if this type variable was parametrized by:

    #. One or more **constraints** (i.e., positional arguments passed by the
       caller to the :meth:`typing.TypeVar.__init__` call initializing this
       type variable), this getter returns a new **PEP-compliant union type
       hint** (e.g., :attr:`typing.Union` subscription) of those constraints.
    #. One **upper bound** (i.e., ``bound`` keyword argument passed by the
       caller to the :meth:`typing.TypeVar.__init__` call initializing this
       type variable), this getter returns that bound as is.
    #. Else, this getter returns the :data:`None` singleton.

    Caveats
    -------
    **This getter treats constraints and upper bounds as semantically
    equivalent,** preventing callers from distinguishing between these two
    technically distinct variants of type variable metadata.

    For runtime type-checking purposes, type variable constraints and bounds are
    sufficiently similar as to be semantically equivalent for all intents and
    purposes. To simplify handling of type variables, this getter ambiguously
    aggregates both into the same tuple.

    For static type-checking purposes, type variable constraints and bounds are
    *still* sufficiently similar as to be semantically equivalent for all
    intents and purposes. Any theoretical distinction between the two is likely
    to be lost on *most* engineers, who tend to treat the two interchangeably.
    To quote :pep:`484`:

        ...type constraints cause the inferred type to be _exactly_ one of the
        constraint types, while an upper bound just requires that the actual
        type is a subtype of the boundary type.

    Inferred types are largely only applicable to static type-checkers, which
    internally assign type variables contextual types inferred from set and
    graph theoretic operations on the network of all objects (nodes) and
    callables (edges) relating those objects. Runtime type-checkers have *no*
    analogous operations, due to runtime space and time constraints.

    This getter is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator). If this type variable was parametrized by
    one or more constraints, the :attr:`typing.Union` type hint factory already
    caches these constraints; else, this getter performs no work. In any case,
    this getter effectively performs to work.

    Parameters
    ----------
    hint : object
        :pep:`484`-compliant type variable to be inspected.
    exception_prefix : str, optional
        Human-readable label prefixing the representation of this object in the
        exception message. Defaults to the empty string.

    Returns
    -------
    Optional[Hint]
        Either:

        * If this type variable was parametrized by one or more constraints, a
          new PEP-compliant union type hint aggregating those constraints.
        * If this type variable was parametrized by an upper bound, that bound.
        * Else, :data:`None`.

    Raises
    ------
    BeartypeDecorHintPep484TypeVarException
        if this object is *not* a :pep:`484`-compliant type variable.
    '''

    # Avoid circular import dependencies.
    from beartype._util.hint.pep.proposal.pep484604 import (
        make_hint_pep484604_union)
    from beartype._util.hint.pep.proposal.pep749 import (
        get_hint_pep749_subhint_mandatory,
        get_hint_pep749_subhint_optional,
    )

    # If this hint is *NOT* a type variable, raise an exception.
    die_unless_hint_pep484_typevar(
        hint=hint, exception_prefix=exception_prefix)
    # Else, this hint is a type variable.

    # Bounded constraints parametrizing this type variable to be returned.
    hint_bounded_constraints: Hint = None

    # Tuple of the zero or more child hints constraining this type variable.
    hint_constraints = get_hint_pep749_subhint_mandatory(
        hint=hint,  # pyright: ignore
        subhint_name_dynamic='evaluate_constraints',
        subhint_name_static='__constraints__',
        exception_cls=BeartypeDecorHintPep484TypeVarException,
        exception_prefix=exception_prefix,
    )

    #
    # If this type variable was parametrized by one or more constraints, create
    # and return the PEP 484-compliant union of these constraints.
    if hint_constraints:
        hint_bounded_constraints = make_hint_pep484604_union(hint_constraints)  # pyright: ignore
    # Else, this type variable was parametrized by *NO* constraints. In this
    # case...
    else:
        # Child hint binding this type parameter if this type parameter has a
        # bound *OR* the sentinel placeholder otherwise.
        #
        # Note that:
        # * Constraints are effectively mandatory (i.e., *ALWAYS* specified),
        #   due to the low-level C implementation of the "TypeVar" type
        #   defaulting unspecified constraints to the empty tuple -- a
        #   technically valid constraint matching zero child hints.
        # * Bounds are effectively optional (i.e., possibly unspecified), due to
        #   the low-level C implementation of the "TypeVar" type defaulting
        #   unspecified bounds to the "None" singleton. Since "None" is *NOT* a
        #   type, there exist no subclasses and thus subhints that match "None".
        #   Ergo, a type variable bound to "None" would prevent that type
        #   variable from matching any hints other than "None". That type
        #   variable would thus be equivalent to "None", which is useless,
        #   because "None" could (and should) just be used instead. PEP 484
        #   thus treats "None" as an invalid bound synonymous with *NO* bound.
        hint_bound = get_hint_pep749_subhint_optional(
            hint=hint,  # pyright: ignore
            subhint_name_dynamic='evaluate_bound',
            subhint_name_static='__bound__',
            subhint_value_null=None,
            exception_cls=BeartypeDecorHintPep484TypeVarException,
            exception_prefix=exception_prefix,
        )

        # If this type variable was parametrized by a bound, return this bound.
        if hint_bound is not SENTINEL:
            hint_bounded_constraints = hint_bound  # pyright: ignore
        # Else, this type variable was parametrized by *NO* bound.
    # Else, this type variable was parametrized by *NO* constraints.

    # Return these bounded constraints.
    return hint_bounded_constraints
