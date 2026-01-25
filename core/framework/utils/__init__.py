"""Utils package - High-performance utilities for the framework."""

from framework.utils.fast_json import (
    fast_extract_json,
    extract_json_with_keys,
    safe_json_dumps,
    safe_json_loads,
)

__all__ = [
    "fast_extract_json",
    "extract_json_with_keys",
    "safe_json_dumps",
    "safe_json_loads",
]
