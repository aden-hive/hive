#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype import path hook trie** (i.e., data structure caching package names
on behalf of the higher-level :func:`beartype.claw._clawmain` submodule, which
beartype import path hooks internally created by that submodule subsequently
lookup when deciding whether or not (and how) to decorate by
:func:`beartype.beartype` the currently imported user-specific submodule).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.claw._importlib.clawimpmain import remove_beartype_pathhook
from beartype.roar import BeartypeClawHookException
from beartype.typing import (
    TYPE_CHECKING,
    Dict,
    Iterable,
    Optional,
)
from beartype._cave._cavemap import NoneTypeOr
from beartype._conf.confmain import BeartypeConf
from beartype._data.typing.datatyping import CollectionStrs
from collections.abc import (
    Collection as CollectionABC,
)

# ....................{ HINTS                              }....................
PackageBasenameToTrieBlacklist = Dict[str, 'PackagesTrieBlacklist']
'''
PEP-compliant type hint matching a dictionary mapping from the unqualified
basename of each subpackage of a package to *not* be runtime type-checked on the
first importation of that subpackage to either:

* If that subpackage has *not* itself been blacklisted but merely contains one
  or more sub-subpackages that have been blacklisted, a **subpackage trie
  blacklist** (i.e., :class:`.PackagesTrieBlacklist` object recursively
  describing those sub-subpackages).
* Else, that subpackage has itself been blacklisted. In this case, the
  :data:`.PackagesTrieBlacklisted` singleton. Although *any* singleton (e.g.,
  :data:`None`, :data:`True`) would suffice here,
  :data:`.PackagesTrieBlacklisted` is the simplest and most readable.
'''


PackageBasenameToTrieWhitelist = Dict[str, 'PackagesTrieWhitelist']
'''
PEP-compliant type hint matching a dictionary mapping from the unqualified
basename of each subpackage of a package to be runtime type-checked on the first
importation of that subpackage to the **subpackage trie whitelist** (i.e.,
:class:`.PackagesTrieWhitelist` object recursively describing the
sub-subpackages of that subpackage).
'''

# ....................{ SUBCLASSES ~ blacklist             }....................
#FIXME: Unit test us up, please.
#FIXME: [SAFETY] Consider overriding the __setitem__() dunder method to ensure:
#* The passed key is a non-empty string.
#* The passed value is either "None" or another "PackagesTrieWhitelist" object.
#
#See the __init__() dunder method for similar validation logic, please.
class PackagesTrieBlacklist(PackageBasenameToTrieBlacklist):
    '''
    **(Sub)package (sub)trie blacklist** (i.e., recursively nested dictionary
    mapping from the unqualified basename of each subpackage of the current
    package to be *prevented* from being runtime type-checked on the first
    importation of that subpackage to another instance of this class similarly
    describing the sub-subpackages of that subpackage).

    This (sub)cache is suitable for caching as the values of:

    * The :data:`.packages_trie_blacklist` global dictionary.
    * Each (sub)value mapped to by that global dictionary.

    Caveats
    -------
    **This dictionary is only safely accessible in a thread-safe manner from
    within a** ``with claw_lock:`` **context manager.** Equivalently, this
    dictionary is *not* safely accessible outside that manager.

    Attributes
    ----------
    package_basename : Optional[str]
        Either:

        * If this (sub)trie is the global trie :data:`.packages_trie_blacklist`,
          :data:`None`.
        * Else, the unqualified basename of the (sub)package described by this
          (sub)trie.

    See Also
    --------
    :class:`.PackagesTrieWhitelist`
        Further details.
    '''

    # ..................{ CLASS VARIABLES                    }..................
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Subclasses declaring uniquely subclass-specific instance
    # variables *MUST* additionally slot those variables. Subclasses violating
    # this constraint will be usable but unslotted, which defeats our purposes.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # Slot all instance variables defined on this object to minimize the time
    # complexity of both reading and writing variables across frequently called
    # cache dunder methods. Slotting has been shown to reduce read and write
    # costs by approximately ~10%, which is non-trivial.
    __slots__ = (
        'package_basename',
    )

    # Squelch false negatives from mypy. This is absurd. This is mypy. See:
    #     https://github.com/python/mypy/issues/5941
    if TYPE_CHECKING:
        package_basename: Optional[str]

    # ..................{ INITIALIZERS                       }..................
    def __init__(
        self,

        # Optional parameters.
        package_basename: Optional[str] = None,
        subpackage_basename_to_trie: (
            Optional[PackageBasenameToTrieBlacklist]) = None,
    ) -> None:
        '''
        Initialize this packages trie blacklist.

        Parameters
        ----------
        package_basename : Optional[str]
            Either:

            * If this is the root of a packages trie blacklist (i.e., the
              :data:`beartype.claw._clawstate.claw_state.packages_trie_blacklist`
              global variable), :data:`None`.
            * Else, the unqualified basename of the (sub)package configured by
              this (sub)trie.

            Defaults to :data:`None`.
        subpackage_basename_to_trie: Optional[PackageBasenameToTrieBlacklist]
            Either:

            * If this package trie is initially empty, :data:`None`.
            * Else, a dictionary mapping from the unqualified basename of each
              initial subpackage of this package to another **packages trie
              blacklist** (i.e,. :class:`.PackagesTrieBlacklist` class)
              describing the sub-subpackages of that subpackage. In this case,
              this packages trie blacklist is initialized from the key-value
              pairs of this dictionary.

            Defaults to :data:`None`.
        '''
        assert isinstance(package_basename, NoneTypeOr[str]), (
            f'{repr(package_basename)} neither string nor "None".')
        assert isinstance(subpackage_basename_to_trie, NoneTypeOr[dict]), (
            f'{repr(subpackage_basename_to_trie)} '
            f'neither dictionary nor "None".'
        )

        # Initialize our superclass to the empty dictionary.
        super().__init__()

        # Classify all remaining passed parameters.
        self.package_basename = package_basename

        # If the caller explicitly passed an initial dictionary to initialize
        # this dictionary subclass with...
        if subpackage_basename_to_trie:
            # If this initial dictionary is *NOT* a dictionary such that...
            if not (
                isinstance(subpackage_basename_to_trie, dict) and
                all(
                    (
                        # All keys of this dictionary are strings *AND*...
                        isinstance(subpackage_basename, str) and
                        # All values of this dictionary are either "None" or
                        # nested subpackages tries.
                        isinstance(
                            subsubpackages_trie, PackagesTrieBlacklist)
                    )
                    for subpackage_basename, subsubpackages_trie in (
                        subpackage_basename_to_trie.items())
                )
            ):
                # Raise us up the exception bomb.
                raise BeartypeClawHookException(
                    f'{repr(subpackage_basename_to_trie)} neither "None" nor '
                    f'dictionary mapping keys to packages trie blacklists.'
                )
            # Else, this initial dictionary is valid.

            # Update this dictionary subclass from this initial dictionary.
            self.update(subpackage_basename_to_trie)
        # Else, the caller explicitly passed *NO* initial dictionary. In this
        # case, preserve this dictionary subclass as the empty dictionary.

    # ..................{ COPIERS                            }..................
    #FIXME: Unit test us up, please.
    #FIXME: Comment out all of this for the moment, please. This method isn't
    #implemented correctly at the moment, sadly. It needs to call itself
    #recursively. It currently doesn't. Thus, we all sigh. *sigh*
    # def copy_deep(self) -> 'PackagesTrieBlacklist':
    #     '''
    #     Deep copy of this packages trie blacklist.
    #     '''
    #
    #     # Create and return a new deep copy of this packages trie blacklist.
    #     return PackagesTrieBlacklist(
    #         package_basename=self.package_basename,
    #         subpackage_basename_to_trie=self,
    #     )

    # ..................{ DUNDERS                            }..................
    def __repr__(self) -> str:
        '''
        Machine-readable representation of this packages trie blacklist.
        '''

        # If this blacklist is actually the blacklisted singleton, return a
        # truncated representation indicating this.
        if self is PackagesTrieBlacklisted:
            return 'PackagesTrieBlacklisted()'
        # Else, this blacklist is *NOT* the blacklisted singleton.

        # Return a full representation of this blacklist.
        return '\n'.join((
            f'{self.__class__.__name__}(',
            f'    package_basename={repr(self.package_basename)},',
            f'    dict={super().__repr__()},',
            f')',
        ))


PackagesTrieBlacklisted = PackagesTrieBlacklist()
'''
**Blacklisted (sub)package (sub)trie** (i.e., :class:`.PackagesTrieBlacklist`
singleton arbitrarily signifying the current leaf node of a packages trie
blacklist to blacklist the corresponding (sub)package).
'''

# ....................{ SUBCLASSES ~ whitelist             }....................
class PackagesTrieWhitelist(PackageBasenameToTrieWhitelist):
    '''
    **(Sub)package (sub)trie whitelist** (i.e., recursively nested dictionary
    mapping from the unqualified basename of each subpackage of the current
    package to be runtime type-checked on the first importation of that
    subpackage to another instance of this class similarly describing the
    sub-subpackages of that subpackage).

    This (sub)cache is suitable for caching as the values of:

    * The :data:`.packages_trie_whitelist` global dictionary.
    * Each (sub)value mapped to by that global dictionary.

    Motivation
    ----------
    This dictionary is intentionally implemented as a nested trie data structure
    rather than a trivial non-nested flat dictionary. Why? Efficiency. Consider
    this flattened set of package names:

    .. code-block:: python

       package_names = {'a.b', 'a.c', 'd'}

    Deciding whether an arbitrary package name is in this set requires
    worst-case :math:`O(n)` iteration across the set of :math:`n` package names.

    Consider instead this nested trie whose keys are package names split on
    ``"."`` delimiters and whose values are either recursively nested
    dictionaries of the same format *or* the :data:`None` singleton (terminating
    the current package name):

    .. code-block:: python

       package_names_trie = {'a': {'b': None, 'c': None}, 'd': None}

    Deciding whether an arbitrary package name is in this trie only requires
    worst-case :math:`O(h)` iteration across the height :math:`h` of this
    dictionary (equivalent to the largest number of ``"."`` delimiters for any
    fully-qualified package name encapsulated by this trie). ``h <<<< n``, so
    this trie offers *much* faster worst-case lookup than that set.

    Moreover, in the worst case:

    * That set requires one inefficient string prefix test for each item.
    * This trie requires *only* one efficient string equality test for each
      nested key-value pair while descending towards the target package name.

    Let's do this, fam.

    Caveats
    -------
    **This dictionary is only safely accessible in a thread-safe manner from
    within a** ``with claw_lock:`` **context manager.** Equivalently, this
    dictionary is *not* safely accessible outside that manager.

    Attributes
    ----------
    conf_if_hooked : Optional[BeartypeConf]
        Either:

        * If this (sub)package has been explicitly registered by a prior call to
          the :func:`beartype.claw._package.clawpkgmain.hook_packages` function,
          the beartype configuration encapsulating all settings configuring
          type-checking for this (sub)package.
        * Else, :data:`None`.
    package_basename : Optional[str]
        Either:

        * If this (sub)trie is the global trie :data:`.packages_trie_whitelist`,
          :data:`None`.
        * Else, the unqualified basename of the (sub)package configured by this
          (sub)trie.
    '''

    # ..................{ CLASS VARIABLES                    }..................
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
    # CAUTION: Subclasses declaring uniquely subclass-specific instance
    # variables *MUST* additionally slot those variables. Subclasses violating
    # this constraint will be usable but unslotted, which defeats our purposes.
    #!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

    # Slot all instance variables defined on this object to minimize the time
    # complexity of both reading and writing variables across frequently called
    # cache dunder methods. Slotting has been shown to reduce read and write
    # costs by approximately ~10%, which is non-trivial.
    __slots__ = (
        'conf_if_hooked',
        'package_basename',
    )

    # Squelch false negatives from mypy. This is absurd. This is mypy. See:
    #     https://github.com/python/mypy/issues/5941
    if TYPE_CHECKING:
        conf_if_hooked: Optional[BeartypeConf]
        package_basename: Optional[str]

    # ..................{ INITIALIZERS                       }..................
    def __init__(
        self,

        # Optional parameters.
        conf_if_hooked: Optional[BeartypeConf] = None,
        package_basename: Optional[str] = None,
    ) -> None:
        '''
        Initialize this packages trie whitelist.

        Parameters
        ----------
        conf_if_hooked : Optional[BeartypeConf], defaults: None
            Either:

            * If this (sub)package has been explicitly registered by a prior
              call to the
              :func:`beartype.claw._package.clawpkgmain.hook_packages` function,
              the beartype configuration encapsulating all settings configuring
              type-checking for this (sub)package.
            * Else, :data:`None`.

            Defaults to :data:`None`.
        package_basename : Optional[str], defaults: None
            Either:

            * If this is the root of a packages trie whitelist (i.e., the
              :data:`beartype.claw._clawstate.claw_state.packages_trie_whitelist`
              global variable), :data:`None`.
            * Else, the unqualified basename of the (sub)package configured by
              this (sub)trie.

            Defaults to :data:`None`.
        '''
        assert isinstance(conf_if_hooked, NoneTypeOr[BeartypeConf]), (
            f'{repr(conf_if_hooked)} neither beartype configuration nor "None".'
        )
        assert isinstance(package_basename, NoneTypeOr[str]), (
            f'{repr(package_basename)} neither string nor "None".')

        # Initialize our superclass to the empty dictionary.
        super().__init__()

        # Classify all remaining passed parameters.
        self.conf_if_hooked = conf_if_hooked
        self.package_basename = package_basename

    # ..................{ COPIERS                            }..................
    #FIXME: Unit test us up, please.
    #FIXME: Comment out all of this for the moment, please. This method isn't
    #implemented correctly at the moment, sadly. It needs to call itself
    #recursively. It currently doesn't. Thus, we all sigh. *sigh*
    # def copy_deep(self) -> 'PackagesTrieWhitelist':
    #     '''
    #     Deep copy of this packages trie whitelist.
    #     '''
    #
    #     # Create and return a new deep copy of this packages trie whitelist.
    #     return PackagesTrieWhitelist(
    #         conf_if_hooked=self.conf_if_hooked,
    #         package_basename=self.package_basename,
    #     )

    # ..................{ DUNDERS                            }..................
    def __repr__(self) -> str:
        '''
        Machine-readable representation of this packages trie whitelist.
        '''

        return '\n'.join((
            f'{self.__class__.__name__}(',
            f'    package_basename={repr(self.package_basename)},',
            f'    conf_if_hooked={repr(self.conf_if_hooked)},',
            f'    dict={super().__repr__()},',
            f')',
        ))

# ....................{ RAISERS                            }....................
#FIXME: Excise us up, please. This is no longer required anywhere. *sigh*
# def die_if_packages_trie() -> None:
#     '''
#     Raise an exception if one or more packages have been registered by a prior
#     call to the :func:`beartype.claw._package.clawpkgmain.hook_packages`
#     function.
#
#     This raiser is thread-safe.
#
#     Raises
#     ------
#     BeartypeClawHookException
#         If one or more packages have been registered by a prior call to the
#         :func:`beartype.claw._package.clawpkgmain.hook_packages` function.
#     '''
#
#     # Avoid circular import dependencies.
#     from beartype.claw._clawstate import (
#         claw_lock,
#         claw_state,
#     )
#
#     # With a submodule-specific thread-safe reentrant lock...
#     with claw_lock:
#         # If one or more packages have been registered...
#         if is_packages_trie():
#             # Package trie whitelist, localized merely for readability. *sigh*
#             packages_trie_whitelist = claw_state.packages_trie_whitelist
#
#             # If a global configuration was already added by a prior call to the
#             # public beartype.claw.beartype_all() function, raise an exception.
#             if packages_trie_whitelist.conf_if_hooked is not None:
#                 raise BeartypeClawHookException(
#                     f'Prior call to package-agnostic import hook '
#                     f'beartype.claw.beartype_all() already registered '
#                     f'all packages for type-checking under '
#                     f'global beartype configuration '
#                     f'{repr(packages_trie_whitelist.conf_if_hooked)}.'
#                 )
#             # Else, or more package-specific configurations have been added by prior
#             # calls to public beartype.claw.beartype_*() functions. In this case,
#             # raise another exception.
#             else:
#                 raise BeartypeClawHookException(
#                     f'Prior call to package-specific import hook '
#                     f'beartype.claw.beartype_package() and/or '
#                     f'beartype_packages() already registered '
#                     f'{len(packages_trie_whitelist)} package(s) for '
#                     f'type-checking under beartype configurations:\n'
#                     f'{repr(packages_trie_whitelist)}'
#                 )

# ....................{ TESTERS                            }....................
#FIXME: Unit test us up, please.
def is_packages_trie() -> bool:
    '''
    :data:`True` only if one or more packages have been registered by a prior
    call to the :func:`beartype.claw._package.clawpkgmain.hook_packages`
    function.

    Caveats
    -------
    **This function is only safely callable in a thread-safe manner from within
    a** ``with claw_lock:`` **context manager.** Equivalently, this function is
    *not* safely callable outside that manager.

    Returns
    -------
    bool
        :data:`True` only if one or more packages have been registered.
    '''

    # Avoid circular import dependencies.
    from beartype.claw._clawstate import claw_state

    # Return true only if either...
    return (
        # A global configuration has been added by a prior call to the
        # beartype.claw.beartype_all() import hook *OR*...
        claw_state.packages_trie_whitelist.conf_if_hooked is not None or
        # One or more package-specific configurations have been added by
        # prior calls to either the beartype.claw.beartype_package() *OR*
        # beartype_packages() import hooks.
        bool(claw_state.packages_trie_whitelist)
    )


#FIXME: Unit test us up, please.
def is_package_blacklisted(package_basenames: CollectionStrs) -> bool:
    '''
    :data:`True` only if the package with the passed name has been
    **blacklisted** (i.e., prevented from being runtime type-checked on the
    first importation of that package) by being either:

    * Explicitly blacklisted by being directly listed in a previously configured
      :attr:`beartype.BeartypeConf.claw_skip_package_names` collection.
    * Implicitly blacklisted by being the subpackage of a parent package
      directly listed in such a collection.

    Caveats
    -------
    **This function is only safely callable in a thread-safe manner from within
    a** ``with claw_lock:`` **context manager.** Equivalently, this function is
    *not* safely callable outside that manager.

    Parameters
    ----------
    package_basenames : CollectionStrs
        Collection of each unqualified basename comprising the fully-qualified
        name of the package to be inspected, split by the caller from this
        name on ``"."`` delimiters.

    Returns
    -------
    bool
        :data:`True` only if this package has been blacklisted.
    '''
    assert isinstance(package_basenames, CollectionABC), (
        f'{repr(package_basenames)} not collection.')

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype.claw._clawstate import claw_state

    # ....................{ LOCALS                         }....................
    # True only if this package has been blacklisted.
    is_blacklisted = False

    # Current subtrie of the global trie blacklist describing the currently
    # iterated basename of each parent package of this package to be blacklisted
    # (i.e., ignored), initialized to this global trie.
    subpackages_trie_blacklist: Optional[PackagesTrieBlacklist] = (
        claw_state.packages_trie_blacklist)

    # ....................{ SEARCH                         }....................
    # For each unqualified basename of each parent package transitively
    # containing this package (as well as that of this package itself)...
    for package_basename in package_basenames:
        # print(f'Visiting blacklisting parent package "{package_basename}"...')

        # Current subtrie of this trie blacklist describing this parent package
        # if this parent package contains one or more subpackages that have been
        # blacklisted by a prior configuration of the
        # "BeartypeConf.claw_skip_package_names" list *OR* "None" otherwise
        # (i.e., if this parent package has yet to be blacklisted).
        subpackages_trie_blacklist = subpackages_trie_blacklist.get(  # type: ignore[union-attr]
            package_basename)

        # If *NO* subpackages of this parent package have been blacklisted,
        # halt iteration.
        if subpackages_trie_blacklist is None:
            break
        # Else, one or more subpackages of this parent package have been
        # blacklisted.
        #
        # If this parent package contains *NO* subpackages, this is a leaf
        # (i.e., terminal) subtrie. In this case, the subpackage of this parent
        # package that has been blacklisted is this parent package itself.
        # Return true immediately.
        #
        # You are now thinking: "B-b-but how can a package be a subpackage of
        # itself?" Simple. In the same set theoretic sense that all classes are
        # subclasses of themselves and all sets are subsets of themselves, all
        # packages are subpackages of themselves. \o/
        elif subpackages_trie_blacklist is PackagesTrieBlacklisted:
            # print(f'Skipping blacklisted package "{package_basename}"...')
            is_blacklisted = True
            break
        # Else, this parent package contains one or more subpackages. In this
        # case, continue iterating until exhausting all subtries *OR* visiting a
        # leaf subtrie.
    # Else, neither this package *NOR* a parent package of this package has
    # been blacklisted. In this case, this package *COULD* still have been
    # whitelisted. Proceed to the next phase, Dr. Demento!

    # Return this boolean.
    return is_blacklisted

# ....................{ GETTERS                            }....................
#FIXME: Unit test us up, please.
def get_package_conf_or_none(package_name: str) -> Optional[BeartypeConf]:
    '''
    Beartype configuration with which to type-check the package with the passed
    name if that package *or* a parent package of that package was registered by
    a prior call to the :func:`.hook_packages` function *or* :data:`None`
    otherwise (i.e., if neither that package *nor* a parent package of that
    package was registered by such a call).

    This getter is thread-safe.

    Parameters
    ----------
    package_name : str
        Fully-qualified name of the package to be inspected.

    Returns
    -------
    Optional[BeartypeConf]
        Either:

        * If that package or a parent package of that package was registered by
          a prior call to the :func:`.hook_packages` function, the beartype
          configuration with which to type-check that package.
        * Else, :data:`None`.
    '''

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype.claw._clawstate import (
        claw_lock,
        claw_state,
    )

    # ....................{ LOCALS                         }....................
    # Beartype configuration to be returned, defaulting to "None".
    subpackage_conf: Optional[BeartypeConf] = None

    # List of each unqualified basename comprising this name, split from this
    # fully-qualified name on "." delimiters. Note that the "str.split('.')" and
    # "str.rsplit('.')" calls produce the exact same lists under all possible
    # edge cases. We arbitrarily call the former rather than the latter for
    # simplicity and readability.
    package_basenames = package_name.split('.')

    # ....................{ SEARCH                         }....................
    # With a submodule-specific thread-safe reentrant lock...
    with claw_lock:
        # print(f'claw_state: {claw_state}')

        # ....................{ PHASE 1 ~ blacklist        }....................
        # In this first phase, decide whether this package has been either:
        # * Explicitly blacklisted by being directly listed in a previously
        #   configured "BeartypeConf.claw_skip_package_names" collection.
        # * Implicitly blacklisted by being the subpackage of a parent package
        #   directly listed in such a collection.
        #
        # If either of these is the case, this getter function *IMMEDIATELY*
        # reduces to a noop by returning "None". For that reason, these two
        # phases *CANNOT* be efficiently interleaved with one another. Before
        # the second phase returns *ANYTHING*, the first phase decides whether
        # the second phase should even be performed at all.
        #
        # If this package has *NOT* been blacklisted...
        if not is_package_blacklisted(package_basenames):
            # ....................{ PHASE 2 ~ whitelist    }....................
            # In this second phase, decide whether this package has been either:
            # * Explicitly whitelisted by being directly passed to a public
            #   "beartype.claw" import hook (e.g., beartype_package()).
            # * Implicitly blacklisted by being the subpackage of a parent
            #   package directly passed to such an import hook.

            # Beartype configuration registered for the currently iterated
            # package, defaulting to the beartype configuration registered for
            # the global trie applicable to *ALL* packages if an external caller
            # previously called the public beartype.claw.beartype_all() function
            # *OR* "None" otherwise (i.e., if that function has yet to be
            # called).
            subpackage_conf = claw_state.packages_trie_whitelist.conf_if_hooked

            # For each subpackages trie describing each parent package
            # transitively containing this package (as well as that of that
            # package itself)...
            for subpackages_trie in iter_packages_trie(package_basenames):
                # Beartype configuration registered with either...
                subpackage_conf = (
                    # That parent package if any *OR*...
                    #
                    # Since that parent package is more granular (i.e., unique)
                    # than any transitive parent package of that parent package,
                    # the former takes precedence over the latter when defined.
                    subpackages_trie.conf_if_hooked or
                    # A transitive parent package of that parent package if any.
                    subpackage_conf
                )
            # print(f'Discovered package "{package_name}" beartype conf {repr(subpackage_conf)}!')
        # Else, this package has been blacklisted.
        # else:
        #     print(f'Skipping blacklisted package "{package_name}"...')

    # ....................{ RETURN                         }....................
    # Return this beartype configuration if any *OR* "None" otherwise.
    return subpackage_conf

# ....................{ ITERATORS                          }....................
#FIXME: Unit test us up, please.
def iter_packages_trie(
    package_basenames: CollectionStrs) -> Iterable[PackagesTrieWhitelist]:
    '''
    Thread-safe generator iteratively yielding one **(sub)package (sub)trie
    whitelist** (i.e., :class:`PackagesTrieWhitelist` instance) describing each
    transitive parent package of the package with the passed name if this
    package or a parent package of this package was hooked by a prior call to
    the :func:`beartype.claw._package.clawpkgmain.hook_packages` function *or*
    the empty iterable otherwise otherwise (i.e., if neither this package nor a
    parent package of this package was hooked by such a call).

    Specifically, this generator yields (in order):

    #. The subtrie of this trie configuring the root package of the passed
       (sub)package.
    #. And so on, until eventually yielding...
    #. The subsubtrie of this subtrie configuring the passed (sub)package
       itself.

    This generator intentionally avoids yielding the global trie
    :data:`beartype.claw._clawstate.packages_trie_whitelist`, which is already
    accessible via that global.

    Caveats
    -------
    **This function is only safely callable in a thread-safe manner from within
    a** ``with claw_lock:`` **context manager.** Equivalently, this function is
    *not* safely callable outside that manager.

    Parameters
    ----------
    package_basenames : CollectionStrs
        Collection of each unqualified basename comprising the fully-qualified
        name of the package to be inspected, split by the caller from this
        name on ``"."`` delimiters.

    Yields
    ------
    PackagesTrieWhitelist
        (Sub)package configuration (sub)trie describing the currently iterated
        transitive parent package of the package with this name.
    '''
    assert isinstance(package_basenames, CollectionABC), (
        f'{repr(package_basenames)} not collection.')

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype.claw._clawstate import claw_state

    # ....................{ LOCALS                         }....................
    # Current subtrie of the global trie whitelist describing the currently
    # iterated basename of each parent package of this package to be
    # whitelisted (i.e., hooked), initialized to this global trie.
    subpackages_trie_whitelist: Optional[PackagesTrieWhitelist] = (  # type: ignore[union-attr]
        claw_state.packages_trie_whitelist)

    # ....................{ SEARCH                         }....................
    # For each unqualified basename of each parent package transitively
    # containing this package (as well as that of this package itself)...
    for package_basename in package_basenames:
        # Current subtrie of this trie whitelist describing this parent package
        # if this parent package was hooked by a prior call to the
        # hook_packages() function *OR* "None" otherwise (i.e., if this parent
        # package has yet to be hooked).
        subpackages_trie_whitelist = subpackages_trie_whitelist.get(  # type: ignore[union-attr]
            package_basename)

        # If this parent package has yet to be hooked, halt iteration.
        if subpackages_trie_whitelist is None:
            break
        # Else, this parent package was previously hooked.

        # Yield this subtrie whitelist describing this parent package.
        yield subpackages_trie_whitelist

# ....................{ REMOVERS                           }....................
#FIXME: Unit test us up, please.
def remove_beartype_pathhook_unless_packages_trie() -> None:
    '''
    Remove our **beartype import path hook singleton** (i.e., single callable
    guaranteed to be inserted at most once to the front of the standard
    :mod:`sys.path_hooks` list recursively applying the
    :func:`beartype.beartype` decorator to all well-typed callables and classes
    defined by all submodules of all packages previously registered by a call to
    a public :func:`beartype.claw` function) if this path hook has already been
    added and all previously registered packages have been unregistered *or*
    silently reduce to a noop otherwise (i.e., if either this path hook has yet
    to be added or one or more packages are still registered).

    Caveats
    -------
    **This function is only safely callable in a thread-safe manner from within
    a** ``with claw_lock:`` **context manager.** Equivalently, this function is
    *not* safely callable outside that manager.
    '''

    # If all previously registered packages have been unregistered, safely
    # remove our import path hook from the "sys.path_hooks" list.
    if not is_packages_trie():
        remove_beartype_pathhook()
