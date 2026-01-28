#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype.**

For :pep:`8` compliance, this namespace exposes a subset of the metadata
constants published by the :mod:`beartype.meta` submodule. These metadata
constants are commonly inspected (and thus expected) by external automation.
'''

# ....................{ TODO                               }....................
#FIXME: Consider significantly expanding the above module docstring, assuming
#Sphinx presents this module in its generated frontmatter.

# ....................{ IMPORTS                            }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: Explicitly list *ALL* public attributes imported below in the
# "__all__" list global declared below to avoid linter complaints.
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: To avoid polluting the public module namespace, external attributes
# should be locally imported at module scope *ONLY* under alternate private
# names (e.g., "from argparse import ArgumentParser as _ArgumentParser" rather
# than merely "from argparse import ArgumentParser").
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

# ....................{ GLOBALS                            }....................
# Initialized below by the _init() function. As a temporary fallback, this
# global is initialized to a placeholder tuple of integers to satisfy static
# type-checkers (e.g., mypy, pyright).
__version__ = '0.1.0'
'''
Human-readable package version as a ``.``-delimited string.

For :pep:`8` compliance, this specifier has the canonical name ``__version__``
rather than that of a typical global (e.g., ``VERSION_STR``).

Note that this is the canonical version specifier for this package. Indeed, the
top-level ``pyproject.toml`` file dynamically derives its own ``version`` string
from this string global.

See Also
--------
pyproject.toml
   The Hatch-specific ``[tool.hatch.version]`` subsection of the top-level
   ``pyproject.toml`` file, which parses its version from this string global.
'''


# Initialized below by the _init() function. As a temporary fallback, this
# global is initialized to a placeholder tuple of integers to satisfy static
# type-checkers (e.g., mypy, pyright).
__version_info__ = (0, 1, 0)
'''
Machine-readable package version as a tuple of integers.

For :pep:`8` compliance, this specifier has the canonical name
``__version_info__`` rather than that of a typical global (e.g.,
``VERSION_PARTS``).
'''

# ....................{ PRIVATE ~ callables                }....................
def _init() -> None:
    '''
    Initialize this submodule and thus this package.
    '''

    # Defer function-specific imports for safety.
    from beartype.meta import (
        VERSION,
        VERSION_PARTS,
        PYTHON_VERSION_MIN,
        PYTHON_VERSION_MIN_PARTS,
    )
    from sys import version_info

    # Global variables to be redefined below.
    global \
        __version__, \
        __version_info__

    # Alias PEP 8-compliant string globals defined by this submodule to PEP
    # 8-noncompliant string globals defined elsewhere.
    __version__      = VERSION
    __version_info__ = VERSION_PARTS  # type: ignore[assignment]

    # If this physical distribution installed with this package defines the
    # "Requires-Python" key underlying the "PYTHON_VERSION_MIN" string constant,
    # validate the version of the active Python interpreter *BEFORE* subsequent
    # logic possibly depending on this version. Specifically...
    if PYTHON_VERSION_MIN is not None:
        # Machine-readable current version of the active Python interpreter as a
        # tuple of integers.
        _PYTHON_VERSION_PARTS = version_info[:3]

        # If the active Python interpreter fails to satisfy minimum
        # requirements, raise an exception. Note that the "sys" module
        # publicizes three version-related constants for this purpose:
        # * "hexversion", an integer intended to be specified in an obscure
        #   (albeit both efficient and dependable) hexadecimal format: e.g.,
        #    >>> sys.hexversion
        #    33883376
        #    >>> '%x' % sys.hexversion
        #    '20504f0'
        # * "version", a human-readable string: e.g.,
        #    >>> sys.version
        #    2.5.2 (r252:60911, Jul 31 2008, 17:28:52)
        #    [GCC 4.2.3 (Ubuntu 4.2.3-2ubuntu7)]
        # * "version_info", a tuple of three or more integers *OR* strings: e.g.,
        #    >>> sys.version_info
        #    (2, 5, 2, 'final', 0)
        #
        # For sanity, this package will *NEVER* conditionally depend upon the
        # string-formatted release type of the current Python version exposed
        # via the fourth element of the "version_info" tuple. Since the first
        # three elements of that tuple are guaranteed to be integers *AND* since
        # a comparable 3-tuple of integers is declared above, comparing the
        # former and latter yield the simplest and most reliable Python version
        # test.
        if _PYTHON_VERSION_PARTS < PYTHON_VERSION_MIN_PARTS:  # type: ignore[operator]
            # Human-readable current version of Python. Ideally, "sys.version"
            # would be used here; sadly, that string embeds significantly more
            # than merely a version and hence is inapplicable: e.g.,
            #     >>> import sys
            #     >>> sys.version
            #     '3.6.5 (default, Oct 28 2018, 19:51:39) \n[GCC 7.3.0]'
            _PYTHON_VERSION = '.'.join(
                str(version_part) for version_part in _PYTHON_VERSION_PARTS)

            # Die ignominiously.
            raise RuntimeError(
                f'Beartype requires at least Python {PYTHON_VERSION_MIN}, but '
                f'the active interpreter only targets Python {_PYTHON_VERSION}. '
                f'We feel unbearable sadness for you.'
            )
        # Else, the active Python interpreter satisfies minimum requirements.
    # Else, this physical distribution installed with this package fails to
    # define the "Requires-Python" key underlying the "PYTHON_VERSION_MIN"
    # string constant.
    #
    # Note that this edge case occurs in common use cases that compile,
    # transpile, or freeze this package. While non-ideal, assume that the user
    # knows what the user is doing by assuming the active Python satisfies
    # minimum requirements. Userbase: if you break it, you bought it.


# Initialize this submodule and thus this package.
_init()

# ....................{ IMPORTS ~ non-meta                 }....................
# Import from the "beartype" codebase *AFTER* initializing this submodule above,
# thus validating the active Python interpreter to satisfy requirements.

# Publicize the private @beartype._decor.beartype decorator as
# @beartype.beartype, preserving all implementation details as private.
from beartype._decor.decormain import (
    beartype as beartype,
)

# Publicize all top-level configuration attributes required to configure the
# @beartype.beartype decorator.
from beartype._conf.confmain import (
    BeartypeConf as BeartypeConf,
)
from beartype._conf.confenum import (
    BeartypeStrategy as BeartypeStrategy,
    BeartypeViolationVerbosity as BeartypeViolationVerbosity,
)
from beartype._conf.decorplace.confplaceenum import (
    BeartypeDecorPlace as BeartypeDecorPlace,
)
from beartype._util.kind.maplike.utilmapfrozen import (
    FrozenDict as FrozenDict,
)

# ....................{ GLOBALS ~ __all__                  }....................
__all__ = [
    'BeartypeConf',
    'BeartypeDecorPlace',
    'BeartypeStrategy',
    'BeartypeViolationVerbosity',
    'FrozenDict',
    'beartype',
    '__version__',
    '__version_info__',
]
'''
Special list global of the unqualified names of all public package attributes
explicitly exported by and thus safely importable from this package.

Caveats
-------
**This global is defined only for conformance with static type checkers,** a
necessary prerequisite for :pep:`561`-compliance. This global is *not* intended
to enable star imports of the form ``from beartype import *`` (now largely
considered a harmful anti-pattern by the Python community), although it
technically does the latter as well.

This global would ideally instead reference *only* a single package attribute
guaranteed *not* to exist (e.g., ``'STAR_IMPORTS_CONSIDERED_HARMFUL'``),
effectively disabling star imports. Since doing so induces spurious static
type-checking failures, we reluctantly embrace the standard approach. For
example, :mod:`mypy` emits an error resembling:

    error: Module 'beartype' does not explicitly export attribute 'beartype';
    implicit reexport disabled.
'''

# ....................{ DUNDERS                            }....................
def __getattr__(attr_name: str) -> object:
    '''
    Dynamically retrieve a deprecated attribute with the passed unqualified name
    from this submodule and emit a non-fatal deprecation warning on each such
    retrieval if this submodule defines this attribute *or* raise an exception
    otherwise.

    The Python interpreter implicitly calls this :pep:`562`-compliant module
    dunder function under Python >= 3.7 *after* failing to directly retrieve an
    explicit attribute with this name from this submodule. Since this dunder
    function is only called in the event of an error, neither space nor time
    efficiency are a concern here.

    Parameters
    ----------
    attr_name : str
        Unqualified name of the deprecated attribute to be retrieved.

    Returns
    -------
    object
        Value of this deprecated attribute.

    Warns
    -----
    DeprecationWarning
        If this attribute is deprecated.

    Raises
    ------
    AttributeError
        If this attribute is unrecognized and thus erroneous.
    '''

    # Isolate imports to avoid polluting the module namespace.
    from beartype._util.module.utilmoddeprecate import deprecate_module_attr

    # Package scope (i.e., dictionary mapping from the names to values of all
    # non-deprecated attributes defined by this package).
    attr_nondeprecated_name_to_value = globals()

    # If this deprecated attribute is the deprecated "beartype.abby" submodule,
    # forcibly import the non-deprecated "beartype.door" submodule aliased to
    # "beartype.abby" into this package scope. For efficiency, this package does
    # *NOT* unconditionally import and expose the "beartype.door" submodule
    # above. That submodule does *NOT* exist in the globals() dictionary
    # defaulted to above and *MUST* now be forcibly injected there.
    if attr_name == 'abby':
        from beartype import door
        attr_nondeprecated_name_to_value = {'door': door}
        attr_nondeprecated_name_to_value.update(globals())
    #FIXME: To support attribute-based deferred importation ala "lazy loading"
    #of heavyweight subpackages like "beartype.door" and "beartype.vale", it
    #looks like we'll need to manually add support here for that: e.g.,
    #    elif attr_name in {'cave', 'claw', 'door', 'vale',}:
    #        #FIXME: Dynamically import this attribute here... somehow. Certainly, if
    #        #such functionality does *NOT* exist, add it to the existing
    #        #"utilmodimport" submodule: e.g.,
    #        attr_value = import_module_attr(f'beartype.{attr_name}')
    #        attr_nondeprecated_name_to_value = {attr_name: attr_value}
    #FIXME: Revise docstring accordingly, please.
    #FIXME: Exhaustively test this, please. Because we'll never manage to keep
    #this in sync, we *ABSOLUTELY* should author a unit test that:
    #* Decides the set of all public subpackages of "beartype".
    #* Validates that each subpackage in this set is accessible as a
    #  "beartype.{subpackage_name}" attribute.

    # Else, this deprecated attribute is any other attribute.

    # Return the value of this deprecated attribute and emit a warning.
    return deprecate_module_attr(
        attr_deprecated_name=attr_name,
        attr_deprecated_name_to_nondeprecated_name={
            'BeartypeDecorationPosition': 'BeartypeDecorPlace',
            'BeartypeHintOverrides': 'FrozenDict',
            'abby': 'door',
        },
        attr_nondeprecated_name_to_value=attr_nondeprecated_name_to_value,
    )

# print('!!!!!!HERE!!!!!!')  # <-- don't ask
