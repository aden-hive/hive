"""Error classes for key-value store operations.

This module provides a hierarchy of exception classes used throughout the key-value
store implementations. The hierarchy allows for fine-grained error handling while
maintaining backwards compatibility through base classes.

Exception Hierarchy:
    BaseKeyValueError (base for all KV errors)
    ├── KeyValueOperationError (operation-level errors)
    │   ├── SerializationError
    │   ├── DeserializationError
    │   ├── MissingKeyError
    │   ├── InvalidTTLError
    │   ├── InvalidKeyError
    │   ├── ValueTooLargeError
    │   ├── EncryptionError
    │   │   ├── DecryptionError
    │   │   │   └── CorruptedDataError
    │   │   └── EncryptionVersionError
    │   ├── ReadOnlyError
    │   ├── EntryTooLargeError
    │   └── EntryTooSmallError
    └── KeyValueStoreError (store-level errors)
        ├── StoreSetupError
        └── StoreConnectionError
"""

from key_value.aio.errors.base import BaseKeyValueError, ExtraInfoType
from key_value.aio.errors.key_value import (
    DeserializationError,
    InvalidKeyError,
    InvalidTTLError,
    KeyValueOperationError,
    MissingKeyError,
    SerializationError,
    ValueTooLargeError,
)
from key_value.aio.errors.store import KeyValueStoreError, PathSecurityError, StoreConnectionError, StoreSetupError
from key_value.aio.errors.wrappers import (
    CorruptedDataError,
    DecryptionError,
    EncryptionError,
    EncryptionVersionError,
    EntryTooLargeError,
    EntryTooSmallError,
    ReadOnlyError,
)

__all__ = [
    "BaseKeyValueError",
    "CorruptedDataError",
    "DecryptionError",
    "DeserializationError",
    "EncryptionError",
    "EncryptionVersionError",
    "EntryTooLargeError",
    "EntryTooSmallError",
    "ExtraInfoType",
    "InvalidKeyError",
    "InvalidTTLError",
    "KeyValueOperationError",
    "KeyValueStoreError",
    "MissingKeyError",
    "PathSecurityError",
    "ReadOnlyError",
    "SerializationError",
    "StoreConnectionError",
    "StoreSetupError",
    "ValueTooLargeError",
]
