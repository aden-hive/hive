# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Union
from typing_extensions import Literal, TypeAlias

from ..._models import BaseModel
from .beta_web_fetch_block import BetaWebFetchBlock
from .beta_web_fetch_tool_result_error_block import BetaWebFetchToolResultErrorBlock

__all__ = ["BetaWebFetchToolResultBlock", "Content"]

Content: TypeAlias = Union[BetaWebFetchToolResultErrorBlock, BetaWebFetchBlock]


class BetaWebFetchToolResultBlock(BaseModel):
    content: Content

    tool_use_id: str

    type: Literal["web_fetch_tool_result"]
