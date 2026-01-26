# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Optional
from typing_extensions import Literal, TypedDict

__all__ = ["BetaOutputConfigParam"]


class BetaOutputConfigParam(TypedDict, total=False):
    effort: Optional[Literal["low", "medium", "high"]]
    """All possible effort levels."""
