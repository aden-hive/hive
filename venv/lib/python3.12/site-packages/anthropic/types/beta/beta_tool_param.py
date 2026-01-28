# File generated from our OpenAPI spec by Stainless. See CONTRIBUTING.md for details.

from __future__ import annotations

from typing import Dict, List, Union, Iterable, Optional
from typing_extensions import Literal, Required, TypeAlias, TypedDict

from ..._types import SequenceNotStr
from .beta_cache_control_ephemeral_param import BetaCacheControlEphemeralParam

__all__ = ["BetaToolParam", "InputSchema"]


class InputSchemaTyped(TypedDict, total=False):
    """[JSON schema](https://json-schema.org/draft/2020-12) for this tool's input.

    This defines the shape of the `input` that your tool accepts and that the model will produce.
    """

    type: Required[Literal["object"]]

    properties: Optional[Dict[str, object]]

    required: Optional[SequenceNotStr[str]]


InputSchema: TypeAlias = Union[InputSchemaTyped, Dict[str, object]]


class BetaToolParam(TypedDict, total=False):
    input_schema: Required[InputSchema]
    """[JSON schema](https://json-schema.org/draft/2020-12) for this tool's input.

    This defines the shape of the `input` that your tool accepts and that the model
    will produce.
    """

    name: Required[str]
    """Name of the tool.

    This is how the tool will be called by the model and in `tool_use` blocks.
    """

    allowed_callers: List[Literal["direct", "code_execution_20250825"]]

    cache_control: Optional[BetaCacheControlEphemeralParam]
    """Create a cache control breakpoint at this content block."""

    defer_loading: bool
    """If true, tool will not be included in initial system prompt.

    Only loaded when returned via tool_reference from tool search.
    """

    description: str
    """Description of what this tool does.

    Tool descriptions should be as detailed as possible. The more information that
    the model has about what the tool is and how to use it, the better it will
    perform. You can use natural language descriptions to reinforce important
    aspects of the tool input JSON schema.
    """

    input_examples: Iterable[Dict[str, object]]

    strict: bool

    type: Optional[Literal["custom"]]
