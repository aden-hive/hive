from typing import Any

from attrs import evolve, field

from cyclopts.utils import UNSET, frozen


@frozen(kw_only=True)
class Token:
    """Tracks how a user supplied a value to the application."""

    keyword: str | None = None
    value: str = ""
    source: str = ""
    index: int = field(default=0, kw_only=True)
    keys: tuple[str, ...] = field(default=(), kw_only=True)
    implicit_value: Any = field(default=UNSET, kw_only=True)

    @property
    def address(self) -> tuple[tuple[str, ...], int]:
        """Hashable subkey destination address for this token."""
        return (self.keys, self.index)

    def evolve(self, **kwargs) -> "Token":
        # TODO: replace return-hint with Self cp311
        return evolve(self, **kwargs)
