# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Union
from typing_extensions import TypeAlias

from .tool_param import ToolParam
from .tool_bash_20250124_param import ToolBash20250124Param
from .web_search_tool_20250305_param import WebSearchTool20250305Param
from .tool_text_editor_20250124_param import ToolTextEditor20250124Param
from .tool_text_editor_20250429_param import ToolTextEditor20250429Param
from .tool_text_editor_20250728_param import ToolTextEditor20250728Param

__all__ = ["ToolUnionParam"]

ToolUnionParam: TypeAlias = Union[
    ToolParam,
    ToolBash20250124Param,
    ToolTextEditor20250124Param,
    ToolTextEditor20250429Param,
    ToolTextEditor20250728Param,
    WebSearchTool20250305Param,
]
