#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **hint overrides class hierarchy** (i.e., public classes implementing
immutable mappings intended to be passed as the value of the ``hint_overrides``
parameter accepted by the :class:`beartype.BeartypeConf.__init__` method).
'''

# ....................{ IMPORTS                            }....................
from beartype.roar import BeartypeConfParamException
from beartype.typing import Optional
from beartype._data.typing.datatyping import (
    DictStrToAny,
    Pep484TowerComplex,
    Pep484TowerFloat,
)
from beartype._util.cache.utilcachecall import callable_cached
from beartype._util.kind.maplike.utilmapfrozen import FrozenDict

# ....................{ GETTERS                            }....................
def sanify_conf_kwargs_is_pep484_tower(conf_kwargs: DictStrToAny) -> None:
    '''
    Sanify (i.e., sanitize) the passed ``is_pep484_tower`` property of the
    passed dictionary of configuration parameters.

    Parameters
    ----------
    conf_kwargs : Dict[str, object]
        Dictionary mapping from the names to values of *all* possible keyword
        parameters configuring this configuration.
    '''
    assert isinstance(conf_kwargs, dict), f'{repr(conf_kwargs)} not dictionary.'

    # ....................{ LOCALS                         }....................
    # PEP 484-compliant implicit tower type hint overrides (i.e., "FrozenDict"
    # instance lossily convering integers to floating-point numbers *AND* both
    # integers and floating-point numbers to complex numbers).
    HINT_OVERRIDES_PEP484_TOWER = _hint_overrides_pep484_tower()

    # Hint overrides if passed by the caller *OR* "None" otherwise.
    hint_overrides = conf_kwargs['hint_overrides']

    # Target hint overrides for the source "float" and "complex" types if any
    # *OR* "None" otherwise.
    hint_overrides_float = hint_overrides.get(float)
    hint_overrides_complex = hint_overrides.get(complex)

    # Whichever of the "float" or "complex" types are already existing overrides
    # in the passed type hint overrides.
    hint_override_cls_conflict: Optional[type] = None

    # ....................{ TEST                           }....................
    # If these overrides already define conflicting overrides for either the
    # "float" or "complex" types, record that fact.
    if (
        hint_overrides_float and
        hint_overrides_float != HINT_OVERRIDES_PEP484_TOWER[float]
    ):
        hint_override_cls_conflict = float
    elif (
        hint_overrides_complex and
        hint_overrides_complex != HINT_OVERRIDES_PEP484_TOWER[complex]
    ):
        hint_override_cls_conflict = complex
    # Else, these overrides do *NOT* already define conflicting overrides
    # for either the "float" or "complex" types.

    # If these overrides already define conflicting overrides for either the
    # "float" or "complex" types, raise an exception.
    if hint_override_cls_conflict:
        raise BeartypeConfParamException(
            f'Beartype configuration '
            f'parameter "is_pep484_tower" conflicts with '
            f'parameter "hint_overrides" key '
            f'"{hint_override_cls_conflict.__name__}" value '
            f'{repr(hint_overrides[hint_override_cls_conflict])}.'
        )
    # Else, these overrides do *NOT* already define conflicting overrides
    # for either the "float" or "complex" types.

    # ....................{ SANIFY                         }....................
    # Add hint overrides expanding the passed type hint overrides with
    # additional overrides mapping:
    # * The "float" type to the "float | int" type hint.
    # * The "complex" type to the "complex | float | int" type hint.
    conf_kwargs['hint_overrides'] = hint_overrides | HINT_OVERRIDES_PEP484_TOWER  # type: ignore[assignment]

# ....................{ FACTORIES                          }....................
@callable_cached
def _hint_overrides_pep484_tower() -> FrozenDict:
    '''
    :pep:`484`-compliant **implicit tower type hint overrides** (i.e.,
    :class:`.FrozenDict` instance lossily converting integers to floating-point
    numbers *and* both integers and floating-point numbers to complex numbers).

    Specifically, these overrides instruct :mod:`beartype` to automatically
    expand:

    * All :class:`float` type hints to ``float | int``, thus implicitly
      accepting both integers and floating-point numbers for objects annotated
      as only accepting floating-point numbers.
    * All :class:`complex` type hints to ``complex | float | int``, thus
      implicitly accepting integers, floating-point, and complex numbers for
      objects annotated as only accepting complex numbers.

    This getter is memoized for efficiency. Note that this getter is
    intentionally defined as a memoized function rather than a global variable
    of this submodule. Why? Because the latter approach induces a circular
    import dependency. (I sigh.)
    '''

    # Beartype on the job, Sir!
    return FrozenDict({float: Pep484TowerFloat, complex: Pep484TowerComplex,})
