#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Project-wide :pep:`613`-compliant **type alias** (i.e., :obj:`typing.TypeAlias`
type hint singleton) utilities.

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeDecorHintPep613DeprecationWarning
from beartype._util.error.utilerrwarn import issue_warning

# ....................{ REDUCERS                           }....................
def reduce_hint_pep613(hint: object, exception_prefix: str, **kwargs) -> object:
    '''
    Reduce the passed :pep:`613`-compliant **type alias** (i.e.,
    :obj:`typing.TypeAlias` type hint singleton) to the ignorable
    :class:`object` superclass.

    This reducer effectively ignores *all* :obj:`typing.TypeAlias` type hint
    singletons, which convey *no* meaningful metadata or semantics. Frankly,
    it's unclear why :pep:`613` even exists. The CPython developer community
    felt similarly, which is why :pep:`695` type aliases deprecate :pep:`613`.

    This reducer is intentionally *not* memoized (e.g., by the
    ``callable_cached`` decorator), as reducers cannot be memoized.

    Parameters
    ----------
    hint : object
        Typed dictionary to be reduced.
    exception_prefix : str, optional
        Substring prefixing exception messages raised by this reducer.

    All remaining passed arguments are silently ignored.

    Returns
    -------
    object
        Lower-level type hint currently supported by :mod:`beartype`.

    Warns
    -----
    BeartypeDecorHintPep613DeprecationWarning
        :pep:`613`-compliant type aliases have been officially deprecated by
        :pep:`695`-compliant type aliases.
    '''

    #FIXME: Improve this advice, please. When we wrote this a literal lifetime
    #ago, we didn't realize that "typing_extensions" astonishingly provides a
    #backport of the low-level C-based "typing.TypeAliasType" type available in
    #Python >= 3.12 as a high-level pure-Python
    #"typing_extensions.TypeAliasType" class available across all Python
    #versions. It's... pretty astonishing, actually! Instantiating the
    #"typing_extensions.TypeAliasType" class allows users to *MUCH* more
    #conveniently define PEP 612-compliant type aliases in older Python
    #versions. PEP 612 *DEFINITELY* should have at least mentioned this, as this
    #is essential information that makes PEP 612 *MUCH* more amenable. The
    #syntax is a bit wonky, but that's understandable:
    #    # This Python >= 3.12-specific logic...
    #    type ListOrSet[T] = list[T] | set[T]
    #    # ...is equivalent to this version-agnostic logic:
    #    T = TypeVar("T")
    #    ListOrSet = TypeAliasType("ListOrSet", list[T] | set[T], type_params=(T,))

    # Emit a non-fatal deprecation warning.
    issue_warning(
        cls=BeartypeDecorHintPep613DeprecationWarning,
        message=(
            f'{exception_prefix}PEP 613 type hint {repr(hint)} '
            f'deprecated by PEP 695. Consider either:\n'
            f'* Requiring Python >= 3.12 and refactoring PEP 613 type aliases '
            f'into PEP 695 type aliases. Note that Python < 3.12 will hate you '
            f'for this: e.g.,\n'
            f'    # Instead of this...\n'
            f'    from typing import TypeAlias\n'
            f'    alias_name: TypeAlias = alias_value\n'
            f'\n'
            f'    # ..."just" do this. Congrats. You destroyed your codebase.\n'
            f'    type alias_name = alias_value\n'
            f'* Refactoring PEP 613 type aliases into PEP 484 '
            f'"typing.NewType"-based type aliases. Note that static '
            f'type-checkers (e.g., mypy, pyright, Pyre) will hate you for '
            f'this: e.g.,\n'
            f'    # Instead of this...\n'
            f'    from typing import TypeAlias\n'
            f'    alias_name: TypeAlias = alias_value\n'
            f'\n'
            f'    # ..."just" do this. Congrats. You destroyed your codebase.\n'
            f'    from typing import NewType\n'
            f'    alias_name = NewType("alias_name", alias_value)\n'
            f'\n'
            f'Combine the above two approaches via The Ultimate Type Alias '
            f'(TUTA), a hidden ninja technique that supports all Python '
            f'versions and static type-checkers but may cause coworker heads '
            f'to pop off like in that one Kingsman scene:\n'
            f'    # Instead of this...\n'
            f'    from typing import TypeAlias\n'
            f'    alias_name: TypeAlias = alias_value\n'
            f'\n'
            f'    # ..."just" do this. If you think this sucks, know that you are not alone.\n'
            f'    from typing import TYPE_CHECKING, NewType, TypeAlias  # <-- sus af\n'
            f'    from sys import version_info  # <-- code just got real\n'
            f'    if TYPE_CHECKING:  # <-- if static type-checking, then PEP 613\n'
            f'        alias_name: TypeAlias = alias_value  # <-- grimdark coding style\n'
            f'    elif version_info >= (3, 12):  # <-- if Python >= 3.12, then PEP 695\n'
            f'        exec("type alias_name = alias_value")  # <-- eldritch abomination\n'
            f'    else:  # <-- if Python < 3.12, then PEP 484\n'
            f'        alias_name = NewType("alias_name", alias_value)  # <-- coworker gives up here\n'
        ),
    )

    # Reduce *ALL* PEP 613 type hints to an arbitrary ignorable type hint.
    return object
