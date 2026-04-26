from collections.abc import Hashable
from typing import Protocol
from typing import TypeVar
from typing import runtime_checkable

TKey = TypeVar("TKey", bound=Hashable, contravariant=True)
TValue_co = TypeVar("TValue_co", covariant=True)


@runtime_checkable
class Subscriptable(Protocol[TKey, TValue_co]):
    def __contains__(self, key: TKey) -> bool: ...
    def __getitem__(self, key: TKey) -> TValue_co: ...
    def __len__(self) -> int: ...
