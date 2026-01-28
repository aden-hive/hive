#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype :pep:`484`-compliant **type variable violation describers** (i.e.,
functions returning human-readable strings explaining violations of
:pep:`484`-compliant :class:`typing.TypeVar` objects).

This private submodule is *not* intended for importation by downstream callers.
'''

#FIXME: Excise this submodule up, please. *sigh*
# # ....................{ IMPORTS                            }....................
# from beartype.typing import Optional
# from beartype._data.typing.datatypingport import Hint
# from beartype._data.hint.sign.datahintsigns import HintSignTypeVar
# from beartype._check.error.errcause import ViolationCause
# from beartype._util.hint.pep.proposal.pep484.pep484typevar import (
#     get_hint_pep484_typevar_bounded_constraints_or_none)
#
# # ....................{ GETTERS                            }....................
# def find_cause_pep484_typevar(cause: ViolationCause) -> ViolationCause:
#     '''
#     Output cause describing describing the failure of the decorated callable to
#     *not* return a value in violation of the passed **type variable** (i.e.,
#     :pep:`484`-compliant :class:`typing.TypeVar` object).
#
#     Parameters
#     ----------
#     cause : ViolationCause
#         Input cause providing this data.
#
#     Returns
#     -------
#     ViolationCause
#         Output cause type-checking this data.
#     '''
#     assert isinstance(cause, ViolationCause), f'{repr(cause)} not cause.'
#     assert cause.hint_sign is HintSignTypeVar, (
#         f'{repr(cause.hint)} not "HintSignTypeVar".')
#
#     # ....................{ LOCALS                         }....................
#     # Hint mapped to by this type variable if one or more transitive parent
#     # hints previously mapped this type variable to a hint *OR* "None".
#     hint_child: Optional[Hint] = cause.typearg_to_hint.get(cause.hint)  # pyright: ignore
#
#     # ....................{ REDUCTION                      }....................
#     # If *NO* transitive parent hints previously mapped this type variable to a
#     # hint...
#     if hint_child is None:
#         # PEP-compliant hint synthesized from all bounded constraints
#         # parametrizing this type variable if any *OR* "None" otherwise.
#         #
#         # Note this call is intentionally passed positional rather positional
#         # keywords due to memoization.
#         hint_curr_bound = get_hint_pep484_typevar_bounded_constraints_or_none(
#             cause.hint, cause.exception_prefix)  # type: ignore[arg-type]
#
#         # If this type variable was parametrized by one or more bounded
#         # constraints, reduce this type variable to these bounded constraints.
#         if hint_curr_bound is not None:
#             hint_child = hint_curr_bound
#         # Else, this type variable was unparametrized. In this case, preserve
#         # this type variable as is.
#     # Else, one or more transitive parent hints previously mapped this type
#     # variable to a hint.
#
#     # If this type variable was either mapped to another hint by one or more
#     # transitive parent hints *OR* parametrized by one or more bounded
#     # constraints...
#     if hint_child is not None:
#         # Unignorable sane hint sanified from this possibly ignorable insane
#         # hint *OR* "None" otherwise (i.e., if this hint is ignorable).
#         hint_child = cause.sanify_hint_child(hint_child)
#     # Else, this type variable was neither mapped to another hint by one or more
#     # transitive parent hints *NOR* parametrized by one or more bounded
#     # constraints.
#
#     # If this type variable is reducible to an unignorable hint...
#     if hint_child is not None:
#         # Ignore this semantically useless type variable in favour of this
#         # semantically useful hint by replacing *ALL* hint metadata describing
#         # the former with the latter.
#         cause_return = cause.permute_cause(hint=hint_child).find_cause()
#     # Else, this type variable is *NOT* reducible to an unignorable hint. Since
#     # @beartype currently fails to generate type-checking code for type
#     # variables in and of themselves, type variables have *NO* intrinsic
#     # semantic meaning and are thus ignorable.
#     else:
#         cause_return = cause
#
#     # ....................{ RETURN                         }....................
#     # Return this output cause.
#     return cause_return
