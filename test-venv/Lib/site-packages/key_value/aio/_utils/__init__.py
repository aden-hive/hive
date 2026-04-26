"""Internal utilities and types for key-value store implementations.

This package provides internal utilities used across store implementations:

- beartype: Type checking decorators using beartype
- compound: Key/collection compounding and prefixing utilities
- constants: Default values for TTL, etc.
- managed_entry: ManagedEntry dataclass for storing values with metadata
- retry: Async retry operation with exponential backoff
- sanitization: Key/collection sanitization strategies
- sanitize: Low-level string sanitization functions
- serialization: Serialization adapters for ManagedEntry objects
- time_to_live: TTL handling and datetime utilities
- wait: Async wait utilities for testing
"""

# Re-export commonly used items for convenience
from key_value.aio._utils.managed_entry import ManagedEntry

__all__ = ["ManagedEntry"]
