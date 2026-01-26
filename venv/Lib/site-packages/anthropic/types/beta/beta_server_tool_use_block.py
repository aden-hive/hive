# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from typing import Dict, Union
from typing_extensions import Literal, Annotated, TypeAlias

from ..._utils import PropertyInfo
from ..._models import BaseModel
from .beta_direct_caller import BetaDirectCaller
from .beta_server_tool_caller import BetaServerToolCaller

__all__ = ["BetaServerToolUseBlock", "Caller"]

Caller: TypeAlias = Annotated[Union[BetaDirectCaller, BetaServerToolCaller], PropertyInfo(discriminator="type")]


class BetaServerToolUseBlock(BaseModel):
    id: str

    caller: Caller
    """Tool invocation directly from the model."""

    input: Dict[str, object]

    name: Literal[
        "web_search",
        "web_fetch",
        "code_execution",
        "bash_code_execution",
        "text_editor_code_execution",
        "tool_search_tool_regex",
        "tool_search_tool_bm25",
    ]

    type: Literal["server_tool_use"]
