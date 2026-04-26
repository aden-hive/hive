from typing import Dict, Optional

from pydantic import BaseModel

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

from .media_type import MediaType

_examples = [
    {
        "description": "user to add to the system",
        "content": {
            "application/json": {
                "schema": {"$ref": "#/components/schemas/User"},
                "examples": {
                    "user": {
                        "summary": "User Example",
                        "externalValue": "http://foo.bar/examples/user-example.json",
                    }
                },
            },
            "application/xml": {
                "schema": {"$ref": "#/components/schemas/User"},
                "examples": {
                    "user": {
                        "summary": "User example in XML",
                        "externalValue": "http://foo.bar/examples/user-example.xml",
                    }
                },
            },
            "text/plain": {
                "examples": {
                    "user": {
                        "summary": "User example in Plain text",
                        "externalValue": "http://foo.bar/examples/user-example.txt",
                    }
                }
            },
            "*/*": {
                "examples": {
                    "user": {
                        "summary": "User example in other format",
                        "externalValue": "http://foo.bar/examples/user-example.whatever",
                    }
                }
            },
        },
    },
    {
        "description": "user to add to the system",
        "content": {
            "text/plain": {"schema": {"type": "array", "items": {"type": "string"}}}
        },
    },
]


class RequestBody(BaseModel):
    """Describes a single request body."""

    description: Optional[str] = None
    """
    A brief description of the request body.
    This could contain examples of use.  
    
    [CommonMark syntax](https://spec.commonmark.org/) MAY be used for rich text 
    representation.
    """

    content: Dict[str, MediaType]
    """
    **REQUIRED**. The content of the request body.
    The key is a media type or [media type range](https://tools.ietf.org/html/rfc7231#appendix-D)
    and the value describes it.
    
    For requests that match multiple keys, only the most specific key is applicable. 
    e.g. text/plain overrides text/*
    """

    required: bool = False
    """
    Determines if the request body is required in the request. Defaults to `false`.
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
