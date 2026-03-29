"""Backward-compatible re-exports from aden_tools.hashline.

This module has been moved to aden_tools.hashline for shared use across
both file_system_toolkits and file_ops (coder tools). All imports continue
to work via this shim.
"""

from aden_tools.hashline import (  # noqa: F401
    HASHLINE_PREFIX_RE,
    compute_line_hash,
    format_hashlines,
    maybe_strip,
    parse_anchor,
    strip_boundary_echo,
    strip_content_prefixes,
    strip_insert_echo,
    validate_anchor,
    whitespace_equal,
)
