#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **Decidedly Object-Oriented Runtime-checking (DOOR) any type hint
classes** (i.e., :class:`beartype.door.TypeHint` subclasses implementing support
for the :pep:`484`-compliant :obj:`typing.Any` singleton type hint).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.door._cls.doorsuper import TypeHint
from beartype.typing import (
    TYPE_CHECKING,
    Any,
)

# ....................{ SUBCLASSES                         }....................
class AnyTypeHint(TypeHint):
    '''
    **Any type hint wrapper** (i.e., high-level object encapsulating the
    low-level :pep:`484`-compliant :obj:`typing.Any` singleton type hint).
    '''

    # ..................{ STATIC                             }..................
    # Squelch false negatives from static type checkers.
    if TYPE_CHECKING:
        _hint: type

    # ..................{ PRIVATE ~ properties               }..................
    @property
    def _is_args_ignorable(self) -> bool:

        # Unconditionally return true, as "typing.Any" is *ALWAYS* unsubscripted
        # and could thus be said to only have ignorable arguments. Semantics.
        return True

    # ..................{ PRIVATE ~ methods                  }..................
    def _is_subhint_branch(self, branch: TypeHint) -> bool:
        # print(f'[AnyTypeHint._is_subhint_branch] Comparing {self} to {branch}...')

        # Unconditionally return false, as "typing.Any" is a subhint of *NO*
        # hint other than itself. However, the following superclass methods
        # already universally handle this common edge case in which the passed
        # hint is "typing.Any":
        # * The public is_subhint() method.
        # * The private _is_subhint_branch() method.
        #
        # The passed hint is thus guaranteed to *NOT* also be "typing.Any", so
        # this hint *CANNOT* be a subhint of that hint.
        return False
