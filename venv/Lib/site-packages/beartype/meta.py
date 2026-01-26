#!/usr/bin/env python3
# --------------------( LICENSE                            )--------------------
# Copyright (c) 2014-2025 Beartype authors.
# See "LICENSE" for further details.

'''
**Beartype metadata.**

This submodule exports global constants synopsizing this package -- including
versioning and dependencies.

For uniformity between this package and the ``pyproject.toml`` file describing
the installation of this package, this submodule also validates the version of
the active Python interpreter. An exception is raised if this version is
insufficient.

As a tradeoff between backward compatibility, security, and maintainability,
this package strongly attempts to preserve compatibility with the first stable
release of the oldest version of CPython still under active development. Hence,
obsolete and insecure versions of CPython that have reached their official End
of Life (EoL) (e.g., Python 3.5) are explicitly unsupported.
'''

# ....................{ IMPORTS                            }....................
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# CAUTION: To avoid polluting the public module namespace, external attributes
# should be locally imported at module scope *ONLY* under alternate private
# names (e.g., "from argparse import ArgumentParser as _ArgumentParser" rather
# than merely "from argparse import ArgumentParser").
#!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

import sys as _sys
from beartype._util.text.utiltextversion import (
    convert_str_version_to_tuple as _convert_str_version_to_tuple)
from importlib.metadata import metadata as _get_package_metadata
from typing import (
    TYPE_CHECKING,  # <-- *MUST* be import as "TYPE_CHECKING" or mypy ignores it
    Optional as _Optional,
)

# ....................{ METADATA                           }....................
NAME = 'beartype'
'''
Human-readable package name.
'''


# Ideally, this metadata would be parsed from the "_package_metadata" dictionary
# introspected below. Sadly, this metadata has yet to be standardized. The
# closest approximation is the "_package_metadata['License']" key, which
# provides the contents of the top-level "LICENSE" file rather than the name of
# the license licensing this package. It is what it is. It is sucky. *sigh*
LICENSE = 'MIT'
'''
Human-readable name of the license this package is licensed under.
'''

# ....................{ METADATA                           }....................
# If performing static type-checking, define a fake "_package_metadata"
# dictionary as a crude means of informing the static type-checker of the
# expected type of this dictionary. While awful, this is (probably) the least
# awful approach. All alternatives invite deprecation concerns.
if TYPE_CHECKING:
    _package_metadata = {'Requires-Python': '>=3.9'}
# Else, static type-checking is *NOT* being performed. In this case...
else:
    # Dictionary mapping from the name to value of all core packaging metadata
    # with which this package was installed under the active Python interpreter.
    #
    # See also the "Core metadata specifications," which standardizes the names
    # and values of this metadata via the PEP process:
    #     https://packaging.python.org/en/latest/specifications/core-metadata
    #
    # First, attempt to introspect this metadata from the physical (i.e.,
    # on-disk) distribution describing this package.
    try:
        _package_metadata = _get_package_metadata(NAME)
    # If doing so fails for *ANY* reason whatsoever, silently ignore this
    # failure by falling back to a default dictionary permissively mapping the
    # names of this metadata to the placeholder "None".
    #
    # Note that this edge case occurs in common use cases that compile,
    # transpile, or freeze this package. Downstream consumers of this submodule
    # *MUST* thus explicitly detect imported globals whose values are "None" and
    # react nicely.
    except Exception:
        from collections import defaultdict as _defaultdict
        _package_metadata = _defaultdict(lambda: None)

# ....................{ METADATA ~ package                 }....................
PACKAGE_NAME = NAME
'''
Fully-qualified name of the top-level Python package containing this submodule.
'''


PACKAGE_TEST_NAME = f'{PACKAGE_NAME}_test'
'''
Fully-qualified name of the top-level Python package testing this project.
'''

# ....................{ PYTHON ~ version                   }....................
def _convert_requires_python_to_version_min(requires_python: str) -> str:
    '''
    Convert the passed :pep:`621`-compliant Python version requirements string
    into a human-readable ``.``-delimited version string (e.g., from
    ``'requires-python = ">=3.10,!=3.14rc1,!=3.14rc2"'`` to ``"3.10"``).

    Parameters
    ----------
    requires_python : str
        Python version requirements string to be converted.

    Returns
    -------
    str
        Python version string converted from this requirements string.
    '''

    # 0-based index of two characters past the first ">=" substring in this
    # version specifier, thus ignoring the ignorable ">=" delimiter.
    python_version_min_index_ge_first = requires_python.index('>=') + 2

    # 0-based index of the first ignorable character in this version specifier
    # following this first ">=" substring if this specifier contains such a
    # character *OR* -1 otherwise. Specifiers may contain optional ","-delimited
    # constraints additionally constraining this minimum version. For example,
    # this specifier blacklists various release candidates known to behave
    # problematically:
    #     requires-python = ">=3.10,!=3.14rc1,!=3.14rc2"
    #
    # Although feasible, validating these optional constraints is non-trivial.
    # Frankly, it's *NOT* worth the excruciating effort at the moment. We are
    # *NOT* building a full-blown Python version validator here. Ergo, we
    # instead ignore these optional constraints.
    python_version_min_index_ignorable_first = requires_python.find(
        ',', python_version_min_index_ge_first)

    # Version string to be returned, defined as the value of "Requires-Python"
    # key stripped of its ">=" prefix. Notably, the value of this key is the
    # value of the "requires-python" key in the "pyproject.toml" file: e.g.,
    #     requires-python = ">=3.8"
    #
    # Since the latter is guaranteed to be prefixed by the substring ">=" of
    # length 2, removing this prefix from this string yields the minimum version
    # of Python required by this package as a "."-delimited string. Phew!
    #
    # If this version specifier contains one or more optional constraints,
    # ignore those constraints.
    if python_version_min_index_ignorable_first >= 1:
        python_version_min = requires_python[
            python_version_min_index_ge_first:
            python_version_min_index_ignorable_first - 1
        ]
    # Else, this version specifier contains *NO* optional constraints.
    else:
        python_version_min = requires_python[
            python_version_min_index_ge_first:]
    # print(f'python_version_min: {python_version_min}')
    # print(f'python_version_min_index_ge_first: {python_version_min_index_ge_first}')
    # print(f'python_version_min_index_ignorable_first: {python_version_min_index_ignorable_first}')

    # Return this version specifier.
    return python_version_min


PYTHON_VERSION_MIN: _Optional[str] = (
    # If this package distribution defines the "Requires-Python" key, the value
    # of this key stripped of its ">=" prefix. Notably, the value of this key is
    # the value of the "requires-python" key in the "pyproject.toml" file: e.g.,
    #     requires-python = ">=3.8"
    #
    # Since the latter is guaranteed to be prefixed by the substring ">=" of
    # length 2, removing this prefix from this string yields the minimum version
    # of Python required by this package as a "."-delimited string. Phew!
    _convert_requires_python_to_version_min(
        _package_metadata['Requires-Python'])
    if _package_metadata['Requires-Python'] else
    # Else, this package distribution fails to define this key. In this case,
    # fallback to "None".
    None
)
'''
Human-readable minimum version of Python required by this package as a
``.``-delimited string if this package distribution provides this metadata *or*
:data:`None` otherwise (i.e., if this package distribution fails to provide this
metadata).
'''


PYTHON_VERSION_MIN_PARTS = (
    # If this package distribution defines the "Requires-Python" key, the value
    # of this key stripped of its ">=" prefix and coerced into a tuple of
    # integers.
    _convert_str_version_to_tuple(PYTHON_VERSION_MIN)
    if PYTHON_VERSION_MIN is not None else
    # Else, this package distribution fails to define this key. In this case,
    # fallback to "None".
    None
)
'''
Machine-readable minimum version of Python required by this package as a
tuple of integers if this package distribution provides this metadata *or*
:data:`None` otherwise (i.e., if this package distribution fails to provide this
metadata).
'''

# ....................{ METADATA ~ version                 }....................
VERSION = '0.22.9'
'''
Human-readable package version as a ``.``-delimited string.
'''


VERSION_PARTS = _convert_str_version_to_tuple(VERSION)
'''
Machine-readable package version as a tuple of integers.
'''

# ....................{ METADATA ~ synopsis                }....................
SYNOPSIS: _Optional[str] = _package_metadata['Summary']
'''
Human-readable single-line synopsis of this package.

By PyPI design, this string must *not* span multiple lines or paragraphs.
'''

# ....................{ METADATA ~ authors                 }....................
AUTHOR_EMAIL: _Optional[str] = _package_metadata['Author-email']
'''
Email address of the principal corresponding author (i.e., the principal author
responding to public correspondence).
'''


AUTHORS = 'Cecil Curry, et al.'
'''
Human-readable list of all principal authors of this package as a
comma-delimited string.

For brevity, this string *only* lists authors explicitly assigned copyrights.
For the list of all contributors regardless of copyright assignment or
attribution, see the `contributors graph`_ for this project.

.. _contributors graph:
   https://github.com/beartype/beartype/graphs/contributors
'''


COPYRIGHT = '2014-2025 Beartype authors'
'''
Legally binding copyright line excluding the license-specific prefix (e.g.,
``"Copyright (c)"``).

For brevity, this string *only* lists authors explicitly assigned copyrights.
For the list of all contributors regardless of copyright assignment or
attribution, see the `contributors graph`_ for this project.

.. _contributors graph:
   https://github.com/beartype/beartype/graphs/contributors
'''

# ....................{ METADATA ~ urls                    }....................
# Although feasible, parsing URLs from "_package_metadata" is non-trivial.
# Rather than break our body over something nobody cares about, violate the DRY
# (Don't Repeat Yourself) principle by repeating various URLs already specified
# in our top-level "pyproject.toml" file.

URL_BLUESKY = 'https://leycec.bsky.social'
'''
URL of this project's entry on **Bluesky** (i.e., popular third-party social
media site, leveraged by project maintainers to publicly announce new releases
and associated news).
'''


URL_CONDA = f'https://anaconda.org/conda-forge/{PACKAGE_NAME}'
'''
URL of this project's entry on **Anaconda** (i.e., alternate third-party Python
package repository utilized by the Anaconda Python distribution).
'''


URL_LIBRARIES = f'https://libraries.io/pypi/{PACKAGE_NAME}'
'''
URL of this project's entry on **Libraries.io** (i.e., third-party open-source
package registrar associated with the Tidelift open-source funding agency).
'''


URL_PYPI = f'https://pypi.org/project/{PACKAGE_NAME}'
'''
URL of this project's entry on **PyPI** (i.e., official Python package
repository, also colloquially known as the "cheeseshop").
'''


URL_RTD = f'https://readthedocs.org/projects/{PACKAGE_NAME}'
'''
URL of this project's entry on **ReadTheDocs (RTD)** (i.e., popular Python
documentation host, shockingly hosting this project's documentation).
'''

# ....................{ METADATA ~ urls : docs             }....................
URL_HOMEPAGE = f'https://{PACKAGE_NAME}.readthedocs.io'
'''
URL of this project's homepage.
'''


URL_PEP585_DEPRECATIONS = (
    f'{URL_HOMEPAGE}/en/latest/api_roar/#pep-585-deprecations')
'''
URL documenting :pep:`585` deprecations of :pep:`484` type hints.
'''

# ....................{ METADATA ~ urls : repo             }....................
URL_REPO_ORG_NAME = PACKAGE_NAME
'''
Name of the **organization** (i.e., parent group or user principally responsible
for maintaining this project, indicated as the second-to-last trailing
subdirectory component) of the URL of this project's git repository.
'''


URL_REPO_BASENAME = PACKAGE_NAME
'''
**Basename** (i.e., trailing subdirectory component) of the URL of this
project's git repository.
'''


URL_REPO = f'https://github.com/{URL_REPO_ORG_NAME}/{URL_REPO_BASENAME}'
'''
URL of this project's git repository.
'''


URL_DOWNLOAD = f'{URL_REPO}/archive/{VERSION}.tar.gz'
'''
URL of the source tarball for the current version of this project.

This URL assumes a tag whose name is ``v{VERSION}`` where ``{VERSION}`` is the
human-readable current version of this project (e.g., ``v0.4.0``) to exist.
Typically, no such tag exists for live versions of this project -- which
have yet to be stabilized and hence tagged. Hence, this URL is typically valid
*only* for previously released (rather than live) versions of this project.
'''


URL_FORUMS = f'{URL_REPO}/discussions'
'''
URL of this project's user forums.
'''


URL_ISSUES = f'{URL_REPO}/issues'
'''
URL of this project's issue tracker.
'''


URL_RELEASES = f'{URL_REPO}/releases'
'''
URL of this project's release list.
'''

# ....................{ METADATA ~ dependency : names      }....................
#FIXME: Switch! So, "pydata-sphinx-theme" is ostensibly *MOSTLY* great. However,
#there are numerous obvious eccentricities in "pydata-sphinx-theme" that we
#strongly disagree with -- especially that theme's oddball division in TOC
#heading levels between the top and left sidebars.
#
#Enter "sphinx-book-theme", stage left. "sphinx-book-theme" is based on
#"pydata-sphinx-theme", but entirely dispenses with all of the obvious
#eccentricities that hamper usage of "pydata-sphinx-theme". We no longer have
#adequate time to maintain custom documentation CSS against the moving target
#that is "pydata-sphinx-theme". Ergo, we should instead let "sphinx-book-theme"
#do all of that heavy lifting for us. Doing so will enable us to:
#* Lift the horrifying constraint above on a maximum Sphinx version. *gulp*
#* Substantially simplify our Sphinx configuration. Notably, the entire fragile
#  "doc/src/_templates/" subdirectory should be *ENTIRELY* excised away.
#
#Please transition to "sphinx-book-theme" as time permits.

# Note that documentation-time functionality in the Sphinx-specific
# "doc/src/conf.py" script imports this private string global. *shrug*
SPHINX_THEME_NAME = 'pydata-sphinx-theme'
'''
Name of the third-party Sphinx extension providing the custom HTML theme
preferred by this documentation.

See Also
--------
pyproject.toml
    Further discussion in the ``doc-rtd`` key of our top-level
    ``pyproject.toml`` file.
'''

# ....................{ METADATA ~ dependency : versions   }....................
# Note that test-time functionality imports this private string global. *shrug*
_LIB_RUNTIME_OPTIONAL_VERSION_MINIMUM_NUMPY = '1.21.0'
'''
Minimum optional version of NumPy recommended for use with this project.

NumPy >= 1.21.0 first introduced the third-party PEP-noncompliant
:attr:`numpy.typing.NDArray` type hint supported by the
:func:`beartype.beartype` decorator.
'''


# Note that test-time functionality imports this private string global. *shrug*
_LIB_RUNTIME_OPTIONAL_VERSION_MINIMUM_TYPING_EXTENSIONS = '3.10.0.0'
'''
Minimum optional version of the third-party :mod:`typing_extensions` package
recommended for use with this project.

:mod:`typing_extensions` >= 3.10.0.0 backports all :mod:`typing` attributes
unavailable under older Python interpreters supported by the
:func:`beartype.beartype` decorator.
'''
