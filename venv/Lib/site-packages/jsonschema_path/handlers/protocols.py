from typing import Optional
from typing import Protocol


class SupportsRead(Protocol):
    def read(self, amount: Optional[int] = 0) -> str: ...
