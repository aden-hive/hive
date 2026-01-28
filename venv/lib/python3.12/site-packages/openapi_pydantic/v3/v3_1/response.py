from typing import Dict, Optional, Union

from pydantic import BaseModel

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

from .header import Header
from .link import Link
from .media_type import MediaType
from .reference import Reference

_examples = [
    {
        "description": "A complex object array response",
        "content": {
            "application/json": {
                "schema": {
                    "type": "array",
                    "items": {"$ref": "#/components/schemas/VeryComplexType"},
                }
            }
        },
    },
    {
        "description": "A simple string response",
        "content": {"text/plain": {"schema": {"type": "string"}}},
    },
    {
        "description": "A simple string response",
        "content": {"text/plain": {"schema": {"type": "string", "example": "whoa!"}}},
        "headers": {
            "X-Rate-Limit-Limit": {
                "description": "The number of allowed requests in the "
                "current period",
                "schema": {"type": "integer"},
            },
            "X-Rate-Limit-Remaining": {
                "description": "The number of remaining requests in the "
                "current period",
                "schema": {"type": "integer"},
            },
            "X-Rate-Limit-Reset": {
                "description": "The number of seconds left in the current period",
                "schema": {"type": "integer"},
            },
        },
    },
    {"description": "object created"},
]


class Response(BaseModel):
    """
    Describes a single response from an API Operation, including design-time,
    static `links` to operations based on the response.
    """

    description: str
    """
    **REQUIRED**. A short description of the response.
    [CommonMark syntax](https://spec.commonmark.org/) MAY be used for rich text 
    representation.
    """

    headers: Optional[Dict[str, Union[Header, Reference]]] = None
    """
    Maps a header name to its definition.
    [RFC7230](https://tools.ietf.org/html/rfc7230#page-22) states header names are case 
    insensitive.
    If a response header is defined with the name `"Content-Type"`, it SHALL be ignored.
    """

    content: Optional[Dict[str, MediaType]] = None
    """
    A map containing descriptions of potential response payloads.
    The key is a media type or [media type range](https://tools.ietf.org/html/rfc7231#appendix-D)
    and the value describes it.  
    
    For responses that match multiple keys, only the most specific key is applicable. 
    e.g. text/plain overrides text/*
    """

    links: Optional[Dict[str, Union[Link, Reference]]] = None
    """
    A map of operations links that can be followed from the response.
    The key of the map is a short name for the link, following the naming constraints 
    of the names for [Component Objects](#componentsObject).
    """

    if PYDANTIC_V2:
        model_config = ConfigDict(
            extra="allow",
            json_schema_extra={"examples": _examples},
        )

    else:

        class Config:
            extra = Extra.allow
            schema_extra = {"examples": _examples}
