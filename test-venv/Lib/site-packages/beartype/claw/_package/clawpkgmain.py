#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
Beartype **import hook managers** (i.e., lower-level private-facing functions
internally driving the higher-level public facing import hooks exported by the
:mod:`beartype.claw._clawmain` submodule).

This private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ IMPORTS                            }....................
from beartype.claw._package.clawpkgenum import BeartypeClawCoverage
from beartype.claw._package.clawpkgtrie import (
    PackagesTrieBlacklist,
    PackagesTrieBlacklisted,
    PackagesTrieWhitelist,
    # iter_packages_trie,
    # remove_beartype_pathhook_unless_packages_trie,
)
from beartype.claw._package._clawpkgmake import (
    make_conf_hookable,
    make_package_names_from_args,
)
from beartype.claw._importlib.clawimpmain import (
    add_beartype_pathhook,
    # remove_beartype_pathhook,
)
from beartype.roar import BeartypeClawHookException
from beartype.typing import Optional
from beartype._conf.confmain import BeartypeConf
from beartype._data.typing.datatyping import IterableStrs
from beartype._util.py.utilpyinterpreter import is_python_optimized
from collections.abc import (
    Iterable as IterableABC,
)

# ....................{ HOOKERS                            }....................
#FIXME: Unit test us up, please.
def hook_packages(
    # Keyword-only arguments.
    *,

    # Mandatory keyword-only arguments.
    claw_coverage: BeartypeClawCoverage,
    conf: BeartypeConf,

    # Optional keyword-only arguments.
    package_name: Optional[str] = None,
    package_names: Optional[IterableStrs] = None,
) -> None:
    '''
    Register a new **beartype package import path hook** (i.e., callable
    inserted to the front of the standard :mod:`sys.path_hooks` list recursively
    applying the :func:`beartype.beartype` decorator to all typed callables and
    classes of all submodules of all packages with the passed names on the first
    importation of those submodules).

    Parameters
    ----------
    claw_coverage : BeartypeClawCoverage
        **Import hook coverage** (i.e., competing package scope over which to
        apply the path hook added by this function, each with concomitant
        tradeoffs with respect to runtime complexity and quality assurance).
    conf : BeartypeConf
        **Beartype configuration** (i.e., dataclass configuring the
        :mod:`beartype.beartype` decorator for *all* decoratable objects
        recursively decorated by the path hook added by this function).
    package_name : Optional[str]
        Either:

        * If ``coverage`` is :attr:`.BeartypeClawCoverage.PACKAGES_ONE`, the
          fully-qualified name of the package to be type-checked.
        * Else, ignored.

        Defaults to :data:`None`.
    package_names : Optional[Iterable[str]]]
        Either:

        * If ``coverage`` is :attr:`.BeartypeClawCoverage.PACKAGES_MANY`, an
          iterable of the fully-qualified names of one or more packages to be
          type-checked.
        * Else, ignored.

        Defaults to :data:`None`.

    Raises
    ------
    BeartypeClawHookException
        If either:

        * The passed ``package_names`` parameter is either:

          * Neither a string nor an iterable (i.e., fails to satisfy the
            :class:`collections.abc.Iterable` protocol).
          * An empty string or iterable.
          * A non-empty string that is *not* a valid **package name** (i.e.,
            ``"."``-delimited concatenation of valid Python identifiers).
          * A non-empty iterable containing at least one item that is either:

            * *Not* a string.
            * The empty string.
            * A non-empty string that is *not* a valid **package name** (i.e.,
              ``"."``-delimited concatenation of valid Python identifiers).

        * The passed ``conf`` parameter is *not* a beartype configuration (i.e.,
          :class:`.BeartypeConf` instance).

    See Also
    --------
    https://stackoverflow.com/a/43573798/2809027
        StackOverflow answer strongly inspiring the low-level implementation of
        this function with respect to inscrutable :mod:`importlib` machinery.
    '''
    # print(f'[hook_packages]:')

    # ....................{ PREAMBLE                       }....................
    # If the active Python interpreter is optimized either at process-invocation
    # time (e.g., by the user passing one or more "-O" command-line options *OR*
    # setting the '${PYTHONOPTIMIZE}" environment variable to a positive integer
    # when the active Python interpreter was forked) *OR* after
    # process-invocation time (e.g., by the user setting the '${PYTHONOPTIMIZE}"
    # environment variable to a positive integer in an interactive REPL). Our
    # awesome userbase requested this.
    if is_python_optimized():
        return 

    # ....................{ IMPORTS                        }....................
    # Avoid circular import dependencies.
    from beartype.claw._clawstate import claw_lock

    # ....................{ LOCALS                         }....................
    # Replace this beartype configuration (which is typically unsuitable for
    # usage in import hooks) with a new beartype configuration suitable for
    # usage in import hooks.
    conf = make_conf_hookable(conf)

    # Iterable of the passed fully-qualified names of all packages to be hooked.
    package_names = make_package_names_from_args(
        claw_coverage=claw_coverage,
        conf=conf,
        package_name=package_name,
        package_names=package_names,
    )

    # ....................{ HOOKS                          }....................
    # With a submodule-specific thread-safe reentrant lock...
    with claw_lock:
        # ....................{ BLACKLIST                  }....................
        # If blacklisting one or more packages from type-checking, do so.
        # print(f'Blacklisting packages: {repr(conf.claw_skip_package_names)}')
        if conf.claw_skip_package_names:
            _blacklist_packages(conf.claw_skip_package_names)
        # Else, *NO* packages are being blacklisted from type-checking. Fine!

        # ....................{ WHITELIST ~ beartype_all   }....................
        # If type-checking *ALL* packages, do so.
        if claw_coverage is BeartypeClawCoverage.PACKAGES_ALL:
            _whitelist_packages_all(conf)
        # ....................{ WHITELIST ~ beartype_packa }....................
        # Else, only a subset of packages are being type-checked. Do it! Do it!
        else:
            _whitelist_packages_some(package_names=package_names, conf=conf)  # type: ignore[arg-type]

        # ....................{ path hook                  }....................
        # Lastly, if our beartype import path hook singleton has *NOT* already
        # been added to the standard "sys.path_hooks" list, do so now.
        #
        # Note that we intentionally:
        # * Do so in a thread-safe manner *INSIDE* this lock.
        # * Defer doing so until *AFTER* the above iteration has successfully
        #   registered the desired packages with our global trie. Why? This path
        #   hook subsequently calls the companion get_package_conf_or_none()
        #   function, which accesses this trie.
        add_beartype_pathhook()

# ....................{ PRIVATE ~ blacklisters             }....................
#FIXME: Docstring us up, please.
def _blacklist_packages(package_names: IterableStrs) -> None:
    '''
    Recursively **blacklist** (i.e., prevent import hooks from implicitly
    runtime type-checking) any subsequently imported packages and modules whose
    absolute names are either directly listed in the passed iterable *or* which
    are subpackages or submodules transitively residing in any packages or
    modules whose absolute names are directly listed in this iterable.

    Caveats
    -------
    **This function is only safely callable in a thread-safe manner from within
    a** ``with claw_lock:`` **context manager.** Equivalently, this function is
    *not* safely callable outside that manager.

    Parameters
    ----------
    package_names : IterableStrs
        Iterable of the absolute names of all packages to be blacklisted.
    '''
    assert isinstance(package_names, IterableABC), (
        f'{repr(package_names)} not iterable.')

    # Avoid circular import dependencies.
    from beartype.claw._clawstate import claw_state

    # For the fully-qualified name of each package to be blacklisted...
    for package_name in package_names:
        # List of each unqualified basename comprising this name, split from
        # this fully-qualified name on "." delimiters.
        #
        # Note that the "str.split('.')" and "str.rsplit('.')" calls produce the
        # same lists under all edge cases. We arbitrarily call the former rather
        # than the latter for simplicity.
        package_basenames = package_name.split('.')

        # Trailing unqualified basename of the desired target
        # (sub)package to be specifically blacklisted (e.g.,
        # "some_subpackage" given the list "['some_package',
        # 'some_subpackage']").
        #
        # Note that this index is guaranteed to be safe. See the
        # following discussion for further commentary.
        package_basename_last = package_basenames[-1]

        # Ignore the trailing unqualified basename of the desired target
        # (sub)package to be specifically blacklisted (e.g., reduce the
        # list "['some_package', 'some_subpackage']" to merely the list
        # "['some_package']"). Why? Because the loop performed below
        # only finds the direct parent package of the desired target
        # (sub)package to be specifically blacklisted. That target
        # (sub)package itself is *NOT* looped over.
        #
        # Note that this slice is guaranteed to be safe. By prior
        # validation performed at "BeartypeConf" instantiation time,
        # this iterable is guaranteed to contain *ONLY* non-empty
        # strings. Then "skip_package_basenames" is guaranteed to be a
        # non-empty list of one or more unqualified basenames. After
        # performing this slice, "skip_package_basenames" then reduces
        # to a possibly -empty list of zero or more such basenames.
        package_basenames = package_basenames[:-1]

        # Current subtrie of the global trie blacklist describing the
        # currently iterated basename of this package, initialized to
        # the global trie blacklist blacklisting all top-level packages.
        subpackages_trie_blacklist = claw_state.packages_trie_blacklist
        # print(f'Blacklist: {repr(claw_state.packages_trie_blacklist)}')

        # For each unqualified basename comprising the directed path
        # from the root package of this package through all intermediary
        # parent packages of this package down to this package...
        for package_basename in package_basenames:
            # If this parent package has yet to be described by a prior
            # call to this function, add a new subtrie blacklist
            # describing this parent package.
            if package_basename not in subpackages_trie_blacklist:
                subpackages_trie_blacklist[package_basename] = (
                    PackagesTrieBlacklist(package_basename=package_basename))
            # Else, this parent package has already been described by a
            # prior call to this function.
            #
            # In either case, a subtrie whitelist describing this parent
            # package is now guaranteed to exist.
            # print(f'Visiting blacklisting parent subpackage "{package_basename}"...')

            # Iterate the current subtrie one subpackage deeper.
            subpackages_trie_blacklist = subpackages_trie_blacklist[
                package_basename]
        # The "skip_package_basenames" list contains at least one
        # basename. The above iteration thus set the currently visited
        # "subpackages_trie_blacklist" to at least one subtrie of the
        # global trie blacklist. More importantly, this subtrie is
        # guaranteed to describe the direct parent package of the
        # current (sub)package being blacklisted.
        # print(f'Blacklisted package "{package_name}" trie {repr(subpackages_trie_blacklist)}...')
        # print(f'Blacklisting leaf subpackage "{package_basename_last}"...')

        # Blacklist this (sub)package from its direct parent package.
        #
        # Note that this seemingly trivial assignment adroitly handles
        # three distinct cases:
        # * If the subtrie
        #   "subpackages_trie_blacklist[skip_package_basename]" does
        #   *NOT* already exist, this assignment behaves as expected.
        # * Else, the subtrie
        #   "subpackages_trie_blacklist[skip_package_basename]" already
        #   exists. In this case, this subtrie is either:
        #   * "PackagesTrieBlacklisted", implying this package has
        #     already been blacklisted by a prior call of this function.
        #     In this case, reblacklisting this package effectively
        #     reduces to an efficient noop.
        #   * *ANY* other "PackagesTrieBlacklist" subtrie, implying that
        #     a prior call of this function previously blacklisted one
        #     or more subpackages of this package (but *NOT* this
        #     package itself). In this case, blacklisting this package
        #     expands that previous blacklisting of one or more
        #     subpackages of this package to the entire package. Score!
        subpackages_trie_blacklist[package_basename_last] = (
            PackagesTrieBlacklisted)

# ....................{ PRIVATE ~ whitelisters             }....................
def _whitelist_packages_all(conf: BeartypeConf) -> None:
    '''
    Globally **whitelist** (i.e., implicitly runtime type-check) *all*
    subsequently imported packages and modules.

    Caveats
    -------
    **This function is only safely callable in a thread-safe manner from within
    a** ``with claw_lock:`` **context manager.** Equivalently, this function is
    *not* safely callable outside that manager.

    Parameters
    ----------
    conf : BeartypeConf, optional
        **Beartype configuration** (i.e., dataclass configuring the
        :mod:`beartype.beartype` decorator for *all* decoratable objects
        recursively decorated by the path hook added by this function).
    '''
    assert isinstance(conf, BeartypeConf), f'{repr(conf)} not configuration.'

    # Avoid circular import dependencies.
    from beartype.claw._clawstate import claw_state

    # Beartype configuration currently associated with *ALL* packages by a prior
    # call to this function if any *OR* "None" (i.e., if this function has yet
    # to be called under this Python interpreter).
    conf_curr = claw_state.packages_trie_whitelist.conf_if_hooked

    # If the higher-level beartype_all() function (calling this lower-level
    # whitelister) has yet to be called under this interpreter, associate this
    # configuration with *ALL* packages.
    if conf_curr is None:
        claw_state.packages_trie_whitelist.conf_if_hooked = conf
    # Else, beartype_all() was already called under this interpreter.
    #
    # If the caller passed a different configuration to that prior call than
    # that passed to this current call, raise an exception.
    elif conf_curr != conf:
        raise BeartypeClawHookException(
            f'beartype_all() previously passed '
            f'conflicting beartype configuration:\n'
            f'\t----------( OLD "conf" PARAMETER )----------\n'
            f'\t{repr(conf_curr)}\n'
            f'\t----------( NEW "conf" PARAMETER )----------\n'
            f'\t{repr(conf)}\n'
        )
    # Else, the caller passed the same configuration to that prior call than
    # that passed to the current call. In this case, silently reduce to a noop.


def _whitelist_packages_some(
    package_names: IterableStrs,
    conf: BeartypeConf,
) -> None:
    '''
    Globally **whitelist** (i.e., implicitly runtime type-check) the proper
    subset of subsequently imported packages and modules whose absolute names
    are either directly listed in the passed iterable *or* which are subpackages
    or submodules transitively residing in any packages or modules whose
    absolute names are directly listed in this iterable.

    Caveats
    -------
    **This function is only safely callable in a thread-safe manner from within
    a** ``with claw_lock:`` **context manager.** Equivalently, this function is
    *not* safely callable outside that manager.

    Parameters
    ----------
    package_names : Iterable[str]
        Iterable of the absolute names of all packages to be whitelisted.
    conf : BeartypeConf
        **Beartype configuration** (i.e., dataclass configuring the
        :mod:`beartype.beartype` decorator for *all* decoratable objects
        recursively decorated by the path hook added by this function).
    '''
    assert isinstance(package_names, IterableABC), (
        f'{repr(package_names)} not iterable.')
    assert isinstance(conf, BeartypeConf), f'{repr(conf)} not configuration.'

    # Avoid circular import dependencies.
    from beartype.claw._clawstate import claw_state

    # For the fully-qualified name of each package to be whitelisted...
    for package_name in package_names:  # type: ignore[union-attr]
        # List of each unqualified basename comprising this name, split from
        # this fully-qualified name on "." delimiters.
        #
        # Note that the "str.split('.')" and "str.rsplit('.')" calls produce the
        # same lists under all edge cases. We arbitrarily call the former rather
        # than the latter for simplicity.
        package_basenames = package_name.split('.')

        # Current subtrie of the global trie whitelist describing the currently
        # iterated basename of this package, initialized to the global trie
        # whitelist configuring all top-level packages.
        subpackages_trie_whitelist = claw_state.packages_trie_whitelist

        # For each unqualified basename comprising the directed path from the
        # root package of this package through all intermediary parent packages
        # of this package down to this package...
        for package_basename in package_basenames:
            # If this parent package has yet to be described by a prior call to
            # this function, add a new subtrie whitelist describing this parent
            # package.
            if package_basename not in subpackages_trie_whitelist:
                subpackages_trie_whitelist[package_basename] = (
                    PackagesTrieWhitelist(package_basename=package_basename))
            # Else, this parent package has already been described by a prior
            # call to this function.
            #
            # In either case, a subtrie whitelist describing this parent package
            # is now guaranteed to exist.

            # Iterate the current subtrie one subpackage deeper.
            subpackages_trie_whitelist = subpackages_trie_whitelist[
                package_basename]
        # The "package_basenames" list contains at least one basename. The above
        # iteration thus set the currently visited "subpackages_trie_whitelist"
        # to at least one subtrie of the global trie whitelist. More
        # importantly, this subtrie is guaranteed to describe the current
        # (sub)package being whitelisted.
        # print(f'Hooked package "{package_name}" subpackage trie {repr(subpackages_trie)}...')

        # Beartype configuration currently associated with this package by a
        # prior call to this function if any *OR* "None" (i.e., if this package
        # has yet to be hooked by such a call).
        conf_curr = subpackages_trie_whitelist.conf_if_hooked

        # If this package has yet to be whitelisted by a prior call to this
        # function, associate this configuration with this package.
        if conf_curr is None:
            subpackages_trie_whitelist.conf_if_hooked = conf
        # Else, that package was already whitelisted by such a call.
        #
        # If the caller passed a different configuration to this current call
        # than that prior call, raise an exception.
        elif conf_curr != conf:
            raise BeartypeClawHookException(
                f'Beartype import hook '
                f'(e.g., beartype.claw.beartype_*() function) '
                f'previously passed conflicting beartype configuration for '
                f'package "{package_name}":\n'
                f'\t----------( OLD "conf" PARAMETER )----------\n'
                f'\t{repr(conf_curr)}\n'
                f'\t----------( NEW "conf" PARAMETER )----------\n'
                f'\t{repr(conf)}\n'
            )
        # Else, the caller passed the same configuration to both the prior and
        # current calls. In this case, ignore this redundant request to
        # rewhitelist this package.

# ....................{ UNHOOKERS                          }....................
#FIXME: Preserved in perpetuity. Who knows what was going on here? Unhooking is
#almost certainly useful -- but this is useless until (A) someone actually
#requests this functionality and (B) we actually test this extensively. *sigh*
#FIXME: [WAT] *UHM.* This is great, *BUT NEVER ACTUALLY EXPOSED TO USERS OR
#INTERNALLY CALLED ANYWHERE.* Seriously. What was the original game plan here?
#No idea. Never documented it. Consider:
#* For each permanent public "beartype.claw" import hook (e.g., beartype_all()),
#  define a corresponding temporary public "beartype.claw" import hook
#  internally deferring to this unhook_packages() function: e.g.,
#      @contextmanager
#      def beartyping_all(*args, **kwargs) -> None:
#          try:
#              beartype_all(*args, **kwargs)
#          finally:
#              #FIXME: Not quite right, obviously. We'll need to pass the proper
#              #parameters like "claw_coverage". Blah, blah. Boring! Next.
#              #FIXME: Uhm... wait. Should we even be calling unhook_packages()
#              #here? Probably not. We should probably just be snapshotting the
#              #existing "claw_state" or something. Shaking my head, fam.
#              unhook_packages(*args, **kwargs)
#FIXME: Unit test us up, please. Since this is never internally called anywhere,
#this is currently completely untested (and probably totally broken). Yikes.
# def unhook_packages(
#     # Keyword-only arguments.
#     *,
#
#     # Mandatory keyword-only arguments.
#     claw_coverage: BeartypeClawCoverage,
#     conf: BeartypeConf,
#
#     # Optional keyword-only arguments.
#     package_name: Optional[str] = None,
#     package_names: Optional[Iterable[str]] = None,
# ) -> None:
#     '''
#     Unregister a previously registered **beartype package import path hook**
#     (i.e., callable inserted to the front of the standard :mod:`sys.path_hooks`
#     list recursively applying the :func:`beartype.beartype` decorator to all
#     typed callables and classes of all submodules of all packages with the
#     passed names on the first importation of those submodules).
#
#     See Also
#     --------
#     :func:`.hook_packages`
#         Further details.
#     '''
#
#     # ....................{ IMPORTS                        }....................
#     # Avoid circular import dependencies.
#     from beartype.claw._clawstate import (
#         claw_lock,
#         claw_state,
#     )
#
#     # ....................{ LOCALS                         }....................
#     # Replace this beartype configuration (which is typically unsuitable for
#     # usage in import hooks) with a new beartype configuration suitable for
#     # usage in import hooks.
#     conf = make_conf_hookable(conf)
#
#     # Iterable of the passed fully-qualified names of all packages to be
#     # unhooked.
#     package_names = make_package_names_from_args(
#         claw_coverage=claw_coverage,
#         conf=conf,
#         package_name=package_name,
#         package_names=package_names,
#     )
#
#     # ....................{ WHITELIST                      }....................
#     # With a submodule-specific thread-safe reentrant lock...
#     with claw_lock:
#         # ....................{ beartype_all()             }....................
#         # If the caller requested all-packages coverage...
#         if claw_coverage is BeartypeClawCoverage.PACKAGES_ALL:
#             # Unhook the beartype configuration previously associated with *ALL*
#             # packages by a prior call to the beartype_all() function.
#             claw_state.packages_trie_whitelist.conf_if_hooked = None
#         # ....................{ beartype_packages()        }....................
#         # Else, the caller requested coverage over a subset of packages. In this
#         # case...
#         else:
#             # For the fully-qualified names of each package to be
#             # unregistered...
#             for package_name in package_names:  # type: ignore[union-attr]
#                 # List of all subpackages tries describing each parent package
#                 # transitively containing the passed package (as well as that of
#                 # that package itself).
#                 subpackages_tries = list(iter_packages_trie(package_name))
#
#                 # Reverse this list in-place, such that:
#                 # * The first item of this list is the subpackages trie
#                 #   describing that package itself.
#                 # * The last item of this list is the subpackages trie
#                 #   describing the root package of that package.
#                 subpackages_tries.reverse()
#
#                 # Unhook the beartype configuration previously associated with
#                 # that package by a prior call to the hook_packages() function.
#                 subpackages_tries[0].conf_if_hooked = None
#
#                 # Child sub-subpackages trie of the currently iterated
#                 # subpackages trie, describing the child subpackage of the
#                 # current parent package transitively containing that package.
#                 subsubpackages_trie = None
#
#                 # For each subpackages trie describing a parent package
#                 # transitively containing that package...
#                 for subpackages_trie in subpackages_tries:
#                     # If this is *NOT* the first iteration of this loop (in
#                     # which case this subpackages trie is a parent package
#                     # rather than that package itself) *AND*...
#                     if subsubpackages_trie is not None:
#                         # If this child sub-subpackages trie describing this
#                         # child sub-subpackage has one or more children, then
#                         # this child sub-subpackages trie still stores
#                         # meaningful metadata and is thus *NOT* safely
#                         # deletable. Moreover, this implies that:
#                         # * *ALL* parent subpackages tries of this child
#                         #   sub-subpackages trie also still store meaningful
#                         #   metadata and are thus also *NOT* safely deletable.
#                         # * There exists no more meaningful work to be performed
#                         #   by this iteration. Ergo, we immediately halt this
#                         #   iteration now.
#                         if subsubpackages_trie:
#                             break
#                         # Else, this child sub-subpackages trie describing this
#                         # child sub-subpackage has *NO* children, implying this
#                         # child sub-subpackages trie no longer stores any
#                         # meaningful metadata and is thus safely deletable.
#
#                         # Unqualified basename of this child sub-subpackage.
#                         subsubpackage_basename = (
#                             subsubpackages_trie.package_basename)
#
#                         # Delete this child sub-subpackages trie from this
#                         # parent subpackages trie.
#                         del subpackages_trie[subsubpackage_basename]  # pyright: ignore
#                     # Else, this is the first iteration of this loop.
#
#                     # Treat this parent subpackages trie as the child
#                     # sub-subpackages trie in the next iteration of this loop.
#                     subsubpackages_trie = subpackages_trie
#
#         # ....................{ path hook                  }....................
#         # Lastly, if *ALL* meaningful metadata has now been removed from our
#         # global trie, remove our beartype import path hook singleton from the
#         # standard "sys.path_hooks" list.
#         #
#         # Note that we intentionally:
#         # * Do so in a thread-safe manner *INSIDE* this lock.
#         # * Defer doing so until *AFTER* the above iteration has successfully
#         #   unregistered the desired packages with our global trie.
#         remove_beartype_pathhook_unless_packages_trie()
