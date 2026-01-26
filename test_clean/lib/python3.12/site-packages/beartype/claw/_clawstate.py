#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **import hook state** (i.e., data class singletons safely centralizing
*all* global state maintained by beartype import hooks, enabling each external
unit test in our test suite to trivially reset that state after completion of
that test).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.claw._ast._scope.clawastscopebefore import (
    BeartypeNodeScopeBeforelist,
    make_node_scope_beforelist_global,
)
from beartype.claw._importlib.clawimpcache import ModuleNameToBeartypeConf
from beartype.claw._package.clawpkgtrie import (
    PackagesTrieBlacklist,
    PackagesTrieBlacklisted,
    PackagesTrieWhitelist,
    PackageBasenameToTrieBlacklist,
)
from beartype._data.conf.dataconfblack import (
    BLACKLIST_PACKAGE_NAMES)
from beartype.typing import (
    TYPE_CHECKING,
    Optional,
)
from beartype._data.typing.datatyping import ImportPathHook
from threading import RLock

# ....................{ CLASSES                            }....................
class BeartypeClawState(object):
    '''
    **Beartype import hook state** (i.e., non-thread-safe singleton safely
    centralizing global state maintained by beartype import hooks, enabling each
    external unit test in our test suite to trivially reset that state after
    completion of that test).

    Attributes
    ----------
    beartype_pathhook : Optional[ImportPathHook]
        Either:

        * If the
          :func:`beartype.claw._importlib.clawimpmain.add_beartype_pathhook`
          function has been previously called at least once under the active
          Python interpreter and the
          :func:`beartype.claw._importlib.clawimpmain.remove_beartype_pathhook`
          function has not been called more recently, the **beartype import path
          hook singleton** (i.e., factory closure creating and returning a new
          :class:`importlib.machinery.FileFinder` instance itself creating and
          leveraging a new :class:`.BeartypeSourceFileLoader` instance).
        * Else, :data:`None`.

        Initialized to :data:`None`.
    module_name_to_beartype_conf : ModuleNameToBeartypeConf
        **Hooked module beartype configuration cache** (i.e., non-thread-safe
        dictionary mapping from the fully-qualified name of each previously
        imported submodule of each package previously registered in our global
        package trie to the beartype configuration configuring type-checking by
        the :func:`beartype.beartype` decorator of that submodule).
    node_scope_beforelist_global : BeartypeNodeScopeBeforelist
        **Abstract syntax tree (AST) global scope beforelist** (i.e., low-level
        dataclass aggregating all metadata required to manage the beforelist
        automating decorator positioning across all global scopes of all modules
        recursively visited by :mod:`beartype.claw` AST transformers).
    packages_trie_blacklist : PackagesTrieWhitelist
        **Package trie blacklist** (i.e., non-thread-safe recursively nested
        dictionary implementing a prefix tree such that each key-value pair maps
        from the unqualified basename of each subpackage to *not* be implicitly
        type-checked on the first importation of that subpackage to another
        instance of the :class:`.PackagesTrieWhitelist` class similarly
        describing the sub-subpackages of that subpackage).
    packages_trie_whitelist : PackagesTrieWhitelist
        **Package trie whitelist** (i.e., non-thread-safe recursively nested
        dictionary implementing a prefix tree such that each key-value pair maps
        from the unqualified basename of each subpackage to be implicitly
        type-checked on the first importation of that subpackage to another
        instance of the :class:`.PackagesTrieWhitelist` class similarly
        describing the sub-subpackages of that subpackage).
    '''

    # ..................{ CLASS VARIABLES                    }..................
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: When adding a new slot, ensure that the copy_deep() method
    # defined below deeply copies that slot as well.
    # CAUTION: Subclasses declaring uniquely subclass-specific instance
    # variables *MUST* additionally slot those variables. Subclasses violating
    # this constraint will be usable but unslotted, which defeats our purposes.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # Slot all instance variables defined on this object to reduce the costs of
    # both reading and writing these variables by approximately ~10%.
    __slots__ = (
        'beartype_pathhook',
        'module_name_to_beartype_conf',
        'node_scope_beforelist_global',
        'packages_trie_blacklist',
        'packages_trie_whitelist',
    )

    # Squelch false negatives from mypy. This is absurd. This is mypy. See:
    #     https://github.com/python/mypy/issues/5941
    if TYPE_CHECKING:
        beartype_pathhook: Optional[ImportPathHook]
        module_name_to_beartype_conf: ModuleNameToBeartypeConf
        node_scope_beforelist_global: BeartypeNodeScopeBeforelist
        packages_trie_blacklist: PackagesTrieBlacklist
        packages_trie_whitelist: PackagesTrieWhitelist

    # ....................{ INITIALIZERS                   }....................
    def __init__(self) -> None:

        # Nullify the proper subset of instance variables requiring
        # nullification *BEFORE* reinitializing this singleton.
        self.beartype_pathhook: Optional[ImportPathHook] = None

        # Reinitialize this singleton safely.
        self._reinit_safe()


    def _reinit_safe(self) -> None:
        '''
        Reinitialize *all* beartype import hook state encapsulated by this data
        class back to their initial defaults, trivially clearing *all* metadata
        pertaining to previously hooked packages and configurations installed by
        previously called beartype import hooks.

        This method performs the subset of reinitialization that is safe to be
        called from the :meth:`__init__` method.
        '''

        # One one-liner to reinitialize them all.
        self.module_name_to_beartype_conf = ModuleNameToBeartypeConf()
        self.node_scope_beforelist_global = make_node_scope_beforelist_global()
        self.packages_trie_whitelist = PackagesTrieWhitelist()
        self.packages_trie_blacklist = PackagesTrieBlacklist(
            subpackage_basename_to_trie=_PACKAGE_NAME_TO_TRIE_BLACKLISTED)
        # print(f'node_scope_beforelist_global: {self.node_scope_beforelist_global}')

        #FIXME: Preserved because the above will inevitably break. *sigh*
        # self.packages_trie_blacklist = PackagesTrieBlacklist()


    def reinit(self) -> None:
        '''
        Reinitialize *all* beartype import hook state encapsulated by this data
        class back to their initial defaults, trivially clearing *all* metadata
        pertaining to previously hooked packages and configurations installed by
        previously called beartype import hooks.
        '''
        # print('Renitializing "beartype.claw" state...')

        # Avoid circular import dependencies.
        from beartype.claw._importlib.clawimpmain import (
            remove_beartype_pathhook)

        # Perform the subset of reinitialization that is safe to be called from
        # the __init__() method.
        self._reinit_safe()

        # Perform the remainder of reinitialization that is unsafe to be called
        # from the __init__() method.
        #
        # Remove our beartype import path hook if this path hook has already
        # been added (e.g., by a prior call to an import hook) *OR* silently
        # reduce to a noop otherwise.
        remove_beartype_pathhook()

    # ..................{ COPIERS                            }..................
    #FIXME: Unit test us up, please.
    #FIXME: Comment out all of this for the moment, please. That includes the
    #copy_deep() methods implemented below as well. They're not implemented
    #correctly at the moment, sadly. They need to call themselves recursively.
    #They don't. Thus, we all sigh. *sigh*
    # def copy_deep(self) -> 'BeartypeClawState':
    #     '''
    #     Deep copy of this beartype import hook state.
    #     '''
    #
    #     # New initially empty beartype import hook state.
    #     claw_state_copy = BeartypeClawState()
    #
    #     #FIXME: Deeply copy all of the remaining stuff, including:
    #     #* "module_name_to_beartype_conf".
    #     #* "node_scope_beforelist_global".
    #
    #     # Deeply copy *ALL* container-specific instance variables necessitating
    #     # a deep copy from the current beartype import hook state into this
    #     # copy.
    #     claw_state_copy.packages_trie_blacklist = (
    #         self.packages_trie_blacklist.copy_deep())
    #     claw_state_copy.packages_trie_whitelist = (
    #         self.packages_trie_whitelist.copy_deep())
    #
    #     # Shallowly copy *ALL* remaining instance variables.
    #     claw_state_copy.beartype_pathhook = self.beartype_pathhook
    #
    #     # Return this deep copy.
    #     return claw_state_copy

    # ..................{ DUNDERS                            }..................
    def __repr__(self) -> str:

        return '\n'.join((
            f'{self.__class__.__name__}(\n',
            f'    beartype_pathhook={repr(self.beartype_pathhook)},\n',
            f'    module_name_to_beartype_conf={repr(self.module_name_to_beartype_conf)},\n',
            f'    node_scope_beforelist_global={repr(self.node_scope_beforelist_global)},\n',
            f'    packages_trie_blacklist={repr(self.packages_trie_blacklist)},\n',
            f'    packages_trie_whitelist={repr(self.packages_trie_whitelist)},\n',
            f')',
        ))

# ....................{ PRIVATE ~ constants                }....................
# Fully initialized by the _init() function called below.
_PACKAGE_NAME_TO_TRIE_BLACKLISTED: PackageBasenameToTrieBlacklist = {}
'''
Dictionary mapping from the unqualified basename of each top-level package to be
blacklisted (i.e., prevented from being runtime type-checked on the first
importation of that package) to the :data:`.PackagesTrieBlacklisted` object
similarly blacklisting the subpackages of that package if any.
'''

# ....................{ PRIVATE ~ initializers             }....................
def _init() -> None:
    '''
    Initialize this submodule.
    '''

    # Set of the names of all top-level packages to be blacklisted with respect
    # to "beartype.claw" import hooks -- defined as the union of:
    # * The frozen set of the names all third-party packages to be unilaterally
    #   blacklisted across this entire codebase.
    # * The root "beartype" package. Doing so effectively silently ignores
    #   dangerous attempts to recursively type-check the "beartype" package by
    #   the @beartype.beartype decorator. See the
    #   beartype.claw._importlib._clawimpload.BeartypeSourceFileLoader.get_code()
    #   method docstring for further commentary.
    #
    # Note that "beartype" is intentionally *OMITTED* from the global
    # "BLACKLIST_PACKAGE_NAMES" frozen set iterated over below. Why?
    # Because "beartype" should *ONLY* be blacklisted with respect to
    # "beartype.claw" import hooks. "beartype" should *NOT* be unilaterally
    # blacklisted across the entirety of this codebase, as doing so would
    # erroneously destroy our ability to (in no particular order):
    # * Define deeply type-checkable PEP 484- and 585-compliant generics.
    package_names_blacklist = BLACKLIST_PACKAGE_NAMES | {
        'beartype',
    }

    # For the name of each top-level package to be blacklisted with respect to
    # "beartype.claw" import hooks...
    for package_name_blacklist in package_names_blacklist:
        # Validate this package to actually be top-level.
        assert '.' not in package_name_blacklist, (
            f'{repr(package_name_blacklist)} not top-level package name '
            f'(i.e., contains one or more "." delimiters).'
        )

        # Map this package name to the "PackagesTrieBlacklist" singleton
        # implying this package to be blacklisted.
        _PACKAGE_NAME_TO_TRIE_BLACKLISTED[package_name_blacklist] = (
            PackagesTrieBlacklisted)


# Initialize this submodule.
_init()

# ....................{ GLOBALS                            }....................
# These globals require this submodule to be fully initialized and are thus
# intentionally defined *AFTER* all other code above. We sigh, fam. *sigh*

claw_lock = RLock()
'''
Reentrant reusable thread-safe context manager gating access to the otherwise
non-thread-safe :data:`.claw_state` global.
'''


claw_state = BeartypeClawState()
'''
**Beartype import hook state** (i.e., non-thread-safe singleton safely
centralizing *all* global state maintained by beartype import hooks, enabling
each external unit test in our test suite to trivially reset that state after
completion of that test).
'''
