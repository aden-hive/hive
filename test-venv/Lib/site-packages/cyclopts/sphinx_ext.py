"""Backward compatibility wrapper for Sphinx extension.

This module maintains backward compatibility for users who have
``cyclopts.sphinx_ext`` in their Sphinx conf.py files.

The actual implementation is in :mod:`cyclopts.ext.sphinx`.

.. deprecated:: 4.0
    Use :mod:`cyclopts.ext.sphinx` instead.
    This backward-compatibility location will be removed in v5.
"""

import warnings

warnings.warn(
    "Importing from 'cyclopts.sphinx_ext' is deprecated. "
    "Please update your Sphinx conf.py to use 'cyclopts.ext.sphinx' instead. "
    "This compatibility shim will be removed in Cyclopts v5.",
    DeprecationWarning,
    stacklevel=2,
)

from cyclopts.ext.sphinx import (
    CycloptsDirective,
    DirectiveOptions,
    setup,
)

__all__ = [
    "CycloptsDirective",
    "DirectiveOptions",
    "setup",
]
