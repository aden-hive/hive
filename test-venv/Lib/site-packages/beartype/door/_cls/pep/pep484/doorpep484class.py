#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **Decidedly Object-Oriented Runtime-checking (DOOR) class type hint
classes** (i.e., :class:`beartype.door.TypeHint` subclasses implementing support
for :pep:`484`-compliant type hints that are, in fact, simple classes).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.door._cls.doorsuper import TypeHint
from beartype.typing import TYPE_CHECKING

# ....................{ SUBCLASSES                         }....................
class ClassTypeHint(TypeHint):
    '''
    **Class type hint wrapper** (i.e., high-level object encapsulating a
    low-level :pep:`484`-compliant type hint that is, in fact, a simple class).

    Caveats
    -------
    This wrapper also intentionally wraps :pep:`484`-compliant :data:``None`
    type hints as the simple type of the :data:``None` singleton, as :pep:`484`
    standardized the reduction of the former to the latter:

         When used in a type hint, the expression None is considered equivalent
         to type(None).

    Although a unique ``NoneTypeHint`` subclass of this class specific to the
    :data:`None` singleton *could* be declared, doing so is substantially
    complicated by the fact that numerous PEP-compliant type hints internally
    elide :data:`None` to the type of that singleton before the
    :mod:`beartype.door` API ever sees a distinction. Notably, this includes
    :pep:`484`-compliant unions subscripted by that singleton: e.g.,

    .. code-block:: python

       >>> from typing import Union
       >>> Union[str, None].__args__
       (str, NoneType)
    '''

    # ..................{ STATIC                             }..................
    # Squelch false negatives from static type checkers.
    if TYPE_CHECKING:
        _hint: type

    # ..................{ PRIVATE ~ properties               }..................
    @property
    def _is_args_ignorable(self) -> bool:

        # Unconditionally return true, as simple classes are unsubscripted and
        # could thus be said to only have ignorable arguments. Look. Semantics.
        return True

    # ..................{ PRIVATE ~ methods                  }..................
    def _is_subhint_branch(self, branch: TypeHint) -> bool:
        # print(f'Entering ClassTypeHint._is_subhint_branch({self}, {branch})...')
        # print(f'{branch}._is_args_ignorable: {branch._is_args_ignorable}')
        # print(f'{self}._origin: {self._origin}')
        # print(f'{branch}._origin: {branch._origin}')

        # print(f'{self}._hint: {self._hint}')
        # print(f'{branch}._hint: {branch._hint}')
        # # print(f'{repr(self)}._origin.__args__: {self._origin.__args__}')
        # print(f'{repr(self)}._origin.__parameters__: {self._origin.__parameters__}')
        # # print(f'{repr(branch)}._origin.__args__: {branch._origin.__args__}')
        # print(f'{repr(branch)}._origin.__parameters__: {branch._origin.__parameters__}')
        # print(f'{repr(self)}._is_args_ignorable: {self._is_args_ignorable}')

        #FIXME: Actually, let's avoid the implicit numeric tower for now.
        #Explicit is better than implicit and we really strongly disagree with
        #this subsection of PEP 484, which does more real-world harm than good.
        # # Numeric tower:
        # # https://peps.python.org/pep-0484/#the-numeric-tower
        # if self._origin is float and branch._origin in {float, int}:
        #     return True
        # if self._origin is complex and branch._origin in {complex, float, int}:
        #     return True

        # Return true only if...
        return (
            # That class is unsubscripted (and thus *NOT* a subscripted generic)
            # *AND*...
            branch._is_args_ignorable and
            # The unsubscripted type originating this class is a subclass of the
            # unsubscripted type originating that class.
            issubclass(self._origin, branch._origin)
        )
