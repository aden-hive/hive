#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **common configurations** (i.e., global :class:`beartype.BeartypeConf`
singletons providing frequently required default configurations leveraged
throughout the remainder of the public :mod:`beartype` API, typically as the
default values of optional keyword-only ``conf`` parameters).

This private submodule is *not* intended for direct importation by downstream
callers.
'''

# ....................{ IMPORTS                            }....................
from beartype._conf.confmain import BeartypeConf
from beartype._conf.confenum import BeartypeStrategy
from beartype._util.cache.utilcachecall import callable_cached

# ....................{ GLOBALS                            }....................
BEARTYPE_CONF_DEFAULT = BeartypeConf()
'''
**Default beartype configuration** (i.e., :class:`BeartypeConf` class
instantiated with *no* parameters and thus default parameters), globalized to
trivially optimize external access to this configuration throughout this
codebase.

This global is intentionally *not* publicized to end users, who can simply
instantiate ``BeartypeConf()`` to efficiently obtain the same singleton.
'''

# ....................{ GETTERS                            }....................
@callable_cached
def get_beartype_conf_strategy_on() -> BeartypeConf:
    '''
    **Linear-time beartype configuration** (i.e., :class:`BeartypeConf` class
    instantiated with only a single parameter enabling :math:`O(n)` linear time
    complexity and otherwise with default parameters), globalized to trivially
    optimize external access to this configuration throughout this codebase.

    This configuration is intentionally exposed indirectly through this memoized
    getter rather than directly through a global singleton. While cumbersome,
    doing so marginally reduces the cost of importing this submodule for end
    users *not* importing a public :mod:`beartype` API calling this getter
    (e.g., the :mod:`beartype.door` subpackage).
    '''

    # Piercing through the frozen eternity of one-liners.
    return BeartypeConf(strategy=BeartypeStrategy.On)
