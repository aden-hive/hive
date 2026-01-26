# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Dict
from typing_extensions import Literal

from .._models import BaseModel

__all__ = ["ToolUseBlock"]


class ToolUseBlock(BaseModel):
    id: str

    input: Dict[str, object]

    name: str

    type: Literal["tool_use"]
