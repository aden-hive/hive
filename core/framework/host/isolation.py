"""State isolation level enum."""

from enum import StrEnum


class IsolationLevel(StrEnum):
    ISOLATED = "isolated"
    SHARED = "shared"
    SYNCHRONIZED = "synchronized"
