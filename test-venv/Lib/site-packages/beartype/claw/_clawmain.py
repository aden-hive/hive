#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype import hooks** (i.e., public-facing functions integrating high-level
:mod:`importlib` machinery required to implement :pep:`302`- and
:pep:`451`-compliant import hooks with the abstract syntax tree (AST)
transformations defined by the low-level :mod:`beartype.claw._ast.clawastmain`
submodule).

This private submodule is the main entry point for this subpackage. Nonetheless,
this private submodule is *not* intended for importation by downstream callers.
'''

# ....................{ TODO                               }....................
#FIXME: Improve the beartype_package() and beartype_packages() functions to emit
#non-fatal warnings when the passed package or packages have already been
#imported (i.e., are in the "sys.modules" list).

# ....................{ IMPORTS                            }....................
from beartype.claw._package.clawpkgenum import BeartypeClawCoverage
from beartype.claw._package.clawpkgmain import hook_packages
from beartype.roar import BeartypeClawHookUnpackagedException
from beartype._cave._cavefast import CallableFrameType
from beartype._conf.confmain import BeartypeConf
from beartype._conf.confcommon import BEARTYPE_CONF_DEFAULT
from beartype._data.api.standard.datapy import SCRIPT_MODULE_NAME
from beartype._util.func.utilfuncfile import get_func_filename_or_none
from beartype._util.func.utilfuncframe import (
    get_frame,
    get_frame_module_name_or_none,
    get_frame_package_name_or_none,
)
from collections.abc import Iterable
from pathlib import PurePath

# ....................{ HOOKERS                            }....................
def beartype_all(
    # Optional keyword-only parameters.
    *,
    conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
) -> None:
    '''
    Register a new **universal beartype import path hook** (i.e., callable
    inserted to the front of the standard :mod:`sys.path_hooks` list recursively
    decorating *all* annotated callables, classes, and variable assignments
    across *all* submodules of *all* packages on the first importation of those
    submodules with the :func:`beartype.beartype` decorator, wrapping those
    callables and classes with performant runtime type-checking).

    This function is the runtime equivalent of a full-blown static type checker
    like ``mypy`` or ``pyright``, enabling full-stack runtime type-checking of
    the current app -- including submodules defined by both:

    * First-party proprietary packages directly authored for this app.
    * Third-party open-source packages authored and maintained elsewhere.

    This function is thread-safe.

    Usage
    -----
    This function is intended to be called from module scope as the first
    statement of the top-level ``__init__`` submodule of the top-level package
    of an app to be fully type-checked by :mod:`beartype`. This function then
    registers an import path hook type-checking *all* annotated callables,
    classes, and variable assignments across *all* submodules of *all* packages
    on the first importation of those submodules: e.g.,

    .. code-block:: python

       # At the very top of "muh_package.__init__":
       from beartype.claw import beartype_all
       beartype_all()  # <-- beartype all subsequent imports, yo

       # Import submodules *AFTER* calling beartype_all().
       from muh_package._some_module import muh_function  # <-- @beartype it!
       from yer_package.other_module import muh_class     # <-- @beartype it!

    Caveats
    -------
    **This function is not intended to be called from intermediary APIs,
    libraries, frameworks, or other middleware.** This function is *only*
    intended to be called from full stack end-user applications as a convenient
    alternative to manually passing the names of all packages to be type-checked
    to the more granular :func:`.beartype_packages` function. This function
    imposes runtime type-checking on downstream reverse dependencies that may
    not necessarily want, expect, or tolerate runtime type-checking. This
    function should typically *only* be called by proprietary packages not
    expected to be reused by others. Open-source packages are advised to call
    other functions instead.

    **tl;dr:** *Only call this function in non-reusable end-user apps.*

    Parameters
    ----------
    conf : BeartypeConf, optional
        **Beartype configuration** (i.e., dataclass configuring the
        :mod:`beartype.beartype` decorator for *all* decoratable objects
        recursively decorated by the path hook added by this function).
        Defaults to ``BeartypeConf()``, the default :math:`O(1)` configuration.

    Raises
    ------
    BeartypeClawHookException
        If the passed ``conf`` parameter is *not* a beartype configuration
        (i.e., :class:`BeartypeConf` instance).
    '''

    # The advantage of one-liners is the vantage of vanity.
    hook_packages(claw_coverage=BeartypeClawCoverage.PACKAGES_ALL, conf=conf)


def beartype_this_package(
    # Optional keyword-only parameters.
    *,
    conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
) -> None:
    '''
    Register a new **current package beartype import path hook** (i.e., callable
    inserted to the front of the standard :mod:`sys.path_hooks` list recursively
    applying the :func:`beartype.beartype` decorator to *all*
    annotated callables, classes, and variable assignments across *all*
    submodules of the current user-defined package calling this function on the
    first importation of those submodules).

    This function is thread-safe.

    Usage
    -----
    This function is intended to be called from module scope as the first
    statement of the top-level ``__init__`` submodule of any package to be
    type-checked by :mod:`beartype`. This function then registers an import path
    hook type-checking *all* annotated callables, classes, and variable
    assignments across *all* submodules of that package on the first importation
    of those submodules: e.g.,

    .. code-block:: python

       # At the very top of "muh_package.__init__":
       from beartype.claw import beartype_this_package
       beartype_this_package()  # <-- beartype all subsequent imports, yo

       # Import package submodules *AFTER* calling beartype_this_package().
       from muh_package._some_module import muh_function  # <-- @beartype it!
       from muh_package.other_module import muh_class     # <-- @beartype it!

    Parameters
    ----------
    conf : BeartypeConf, optional
        **Beartype configuration** (i.e., dataclass configuring the
        :mod:`beartype.beartype` decorator for *all* decoratable objects
        recursively decorated by the path hook added by this function).
        Defaults to ``BeartypeConf()``, the default :math:`O(1)` configuration.

    Raises
    ------
    BeartypeClawHookException
        If the passed ``conf`` parameter is *not* a beartype configuration
        (i.e., :class:`.BeartypeConf` instance).
    BeartypeClawHookUnpackagedException
        If this function is called from outside any package structure (e.g.,
        top-level module or executable script).
    '''

    # Stack frame encapsulating the user-defined lexical scope directly calling
    # this import hook.
    #
    # Note that:
    # * This call is guaranteed to succeed without error. Why? Because:
    #   * The current call stack *ALWAYS* contains at least one stack frame.
    #     Ergo, get_frame(0) *ALWAYS* succeeds without error.
    #   * The call to this import hook guaranteeably adds yet another stack
    #     frame to the current call stack. Ergo, get_frame(1) also *ALWAYS*
    #     succeeds without error in this context.
    # * This and the following logic *CANNOT* reasonably be isolated to a new
    #   private helper function. Why? Because this logic itself calls existing
    #   private helper functions assuming the caller to be at the expected
    #   position on the current call stack.
    frame_caller: CallableFrameType = get_frame(1)  # type: ignore[assignment,misc]

    # Fully-qualified name of the parent package of the child module defining
    # that caller if that module resides in some package *OR* the empty string
    # otherwise (i.e., if that module is a top-level module or script residing
    # outside any package structure).
    frame_package_name = get_frame_package_name_or_none(frame_caller)
    # print(f'beartype_this_package: {frame_caller_package_name}')
    # print(f'beartype_this_package: {repr(frame_caller)}')

    #FIXME: Is "pragma: no cover" accurate here? Is this condition untestable?
    # If that module has *NO* parent package, raise an exception. Why? Because
    # this function uselessly (but silently) reduces to a noop when called from
    # a top-level module or script residing outside any package. Why? Because
    # this function installs an import hook applicable only to subsequently
    # imported submodules of the current package. By definition, a top-level
    # module or script has *NO* package and thus *NO* sibling submodules and
    # thus *NO* meaningful imports to be hooked. To avoid unwanted confusion, we
    # intentionally notify the user with a loud exception.
    if not frame_package_name:  # pragma: no cover
        # Exception message to be raised below.
        exception_message: str = None  # type: ignore[assignment]

        # Fully-qualified name of the module encapsulating the caller.
        frame_module_name = get_frame_module_name_or_none(frame_caller)

        # If the caller is a script rather than a module, this name is the
        # useless magic string "__main__". In this case...
        if frame_module_name == SCRIPT_MODULE_NAME:
            # Absolute filename of this script if this script physically resides
            # on the local filesystem *OR* "None" otherwise (i.e., if this
            # script is dynamically defined in-memory).
            frame_filename = get_func_filename_or_none(frame_caller)

            # If this script physically exists...
            if frame_filename:
                # Prefix this message appropriately.
                exception_message_prefix = (
                    f'Top-level script "{frame_filename}" ')
            # Else, this script only exists in memory. In this case...
            else:
                # Prefix this message appropriately.
                exception_message_prefix = 'In-memory script '

                # Fabricate an arbitrary filename. Just do it!
                frame_filename = 'scripts/main.py'

            # Path object encapsulating this filename.
            frame_path = PurePath(frame_filename)

            # Basename of the parent directory containing this script, defined
            # as either...
            frame_package_basename = (
                # If this filename contains at least two basenames, then:
                # * The last basename is that of this script.
                # * The second-to-last basename is that of the parent directory
                #   containing this script.
                frame_path.parts[-2]
                if len(frame_path.parts) >= 2 else
                # Else, this filename contains only the basename of this script.
                # In this case, fabricate an arbitrary basename. Just do it!
                'scripts'
            )

            # Exception message to be raised below.
            exception_message = (
                f'{exception_message_prefix}resides outside package structure. '
                f'Consider calling another "beartype.claw" import hook. '
                f'However, note that only other modules will be type-checked. '
                f'"{frame_filename}" itself will remain unchecked. '
                f'All business logic should reside in submodules '
                f'subsequently imported by "{frame_filename}": e.g.,\n'
                f'    # Instead of this at the top of "{frame_filename}"...\n'
                f'    from beartype.claw import beartype_this_package  # <-- you are here\n'
                f'    beartype_this_package()                          # <-- feels bad\n'
                f'\n'
                f'    # ...pass the basename of the "{frame_package_basename}/" subdirectory explicitly.\n'
                f'    from beartype.claw import beartype_package  # <-- you want to be here\n'
                f'    beartype_package("{frame_package_basename}")  # <-- feels good\n'
                f'\n'
                f'    from {frame_package_basename}.main_submodule import main_func  # <-- still feels good\n'
                f'    main_func()                   # <-- *GOOD*! "beartype.claw" type-checks this\n'
                f'    some_global: str = 0xFEEDFACE  # <-- *BAD*! "beartype.claw" ignores this\n'
                f'This has been a message from your friendly neighbourhood bear.'
            )
        # Else, the caller is a module with a useful name. In this case, define
        # an exception message.
        #
        # Note that this edge case implies that this is a top-level module
        # residing outside a package that was *NOT* run as a script. Since this
        # should *BASICALLY* never occur, there isn't terribly much we can do.
        else:
            exception_message = (
                f'Top-level module "{frame_module_name}" '
                f'resides outside package structure but was '
                f'*NOT* directly run as a script. '
                f'"beartype.claw" import hooks require that modules either '
                f'reside inside a package structure or be '
                f'directly run as scripts. '
                f'Since neither applies here, you are now off the deep end. '
                f'@beartype no longer has any idea what is going on, sadly. '
                f'Consider directly decorating classes and functions by the '
                f'@beartype.beartype decorator instead: e.g.,\n'
                f'    # Instead of this at the top of "{frame_module_name}"...\n'
                f'    from beartype.claw import beartype_this_package  # <-- you are here\n'
                f'    beartype_this_package()                          # <-- feels bad\n'
                f'\n'
                f"    # ...go old-school like it's 2017 and you just don't care.\n"
                f'    from beartype import beartype  # <-- you want to be here\n'
                f'    @beartype  # <-- feels good, yet kinda icky at same time\n'
                f'    def spicy_func() -> str: ...  # <-- *GOOD*! @beartype type-checks this\n'
                f'    some_global: str = 0xFEEDFACE  # <-- *BAD*! @beartype ignores this, but what can you do\n'
                f'For your safety, @beartype will now crash and burn.'
            )

        # Raise an exception.
        raise BeartypeClawHookUnpackagedException(exception_message)
    # Else, that module has a parent package.

    # Add a new import path hook beartyping this package.
    hook_packages(
        claw_coverage=BeartypeClawCoverage.PACKAGES_ONE,
        package_name=frame_package_name,
        conf=conf,
    )


#FIXME: Add a "Usage" docstring section resembling that of the docstring for the
#beartype_this_package() function.
def beartype_package(
    # Mandatory parameters.
    package_name: str,

    # Optional keyword-only parameters.
    *,
    conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
) -> None:
    '''
    Register a new **single package beartype import path hook** (i.e., callable
    inserted to the front of the standard :mod:`sys.path_hooks` list recursively
    applying the :func:`beartype.beartype` decorator to *all* annotated
    callables, classes, and variable assignments across *all* submodules of the
    package with the passed names on the first importation of those submodules).

    This function is thread-safe.

    Parameters
    ----------
    package_name : str
        Fully-qualified name of the package to be type-checked.
    conf : BeartypeConf, optional
        **Beartype configuration** (i.e., dataclass configuring the
        :mod:`beartype.beartype` decorator for *all* decoratable objects
        recursively decorated by the path hook added by this function).
        Defaults to ``BeartypeConf()``, the default :math:`O(1)` configuration.

    Raises
    ------
    BeartypeClawHookException
        If either:

        * The passed ``conf`` parameter is *not* a beartype configuration (i.e.,
          :class:`BeartypeConf` instance).
        * The passed ``package_name`` parameter is either:

          * *Not* a string.
          * The empty string.
          * A non-empty string that is *not* a valid **package name** (i.e.,
            ``"."``-delimited concatenation of valid Python identifiers).
    '''

    # Add a new import path hook beartyping this package.
    hook_packages(
        claw_coverage=BeartypeClawCoverage.PACKAGES_ONE,
        package_name=package_name,
        conf=conf,
    )


#FIXME: Add a "Usage" docstring section resembling that of the docstring for the
#beartype_this_package() function.
def beartype_packages(
    # Mandatory parameters.
    package_names: Iterable[str],

    # Optional keyword-only parameters.
    *,
    conf: BeartypeConf = BEARTYPE_CONF_DEFAULT,
) -> None:
    '''
    Register a new **multiple package beartype import path hook** (i.e.,
    callable inserted to the front of the standard :mod:`sys.path_hooks` list
    recursively applying the :func:`beartype.beartype` decorator to *all*
    annotated callables, classes, and variable assignments across *all*
    submodules of all packages with the passed names on the first importation of
    those submodules).

    This function is thread-safe.

    Parameters
    ----------
    package_names : Iterable[str]
        Iterable of the fully-qualified names of one or more packages to be
        type-checked.
    conf : BeartypeConf, optional
        **Beartype configuration** (i.e., dataclass configuring the
        :mod:`beartype.beartype` decorator for *all* decoratable objects
        recursively decorated by the path hook added by this function).
        Defaults to ``BeartypeConf()``, the default :math:`O(1)` configuration.

    Raises
    ------
    BeartypeClawHookException
        If either:

        * The passed ``conf`` parameter is *not* a beartype configuration (i.e.,
          :class:`BeartypeConf` instance).
        * The passed ``package_names`` parameter is either:

          * Non-iterable (i.e., fails to satisfy the
            :class:`collections.abc.Iterable` protocol).
          * An empty iterable.
          * A non-empty iterable containing at least one item that is either:

            * *Not* a string.
            * The empty string.
            * A non-empty string that is *not* a valid **package name** (i.e.,
              ``"."``-delimited concatenation of valid Python identifiers).
    '''

    # Add a new import path hook beartyping these packages.
    hook_packages(
        claw_coverage=BeartypeClawCoverage.PACKAGES_MANY,
        package_names=package_names,
        conf=conf,
    )
