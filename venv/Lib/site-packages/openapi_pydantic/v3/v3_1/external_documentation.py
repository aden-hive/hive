from typing import Optional

from pydantic import BaseModel

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

_examples = [{"description": "Find more info here", "url": "https://example.com"}]


class ExternalDocumentation(BaseModel):
    """Allows referencing an external resource for extended documentation."""

    description: Optional[str] = None
    """
    A short description of the target documentation.
    [CommonMark syntax](https://spec.commonmark.org/) MAY be used for rich text 
    representation.
    """

    url: str
    """
    **REQUIRED**. The URL for the target documentation.
    Value MUST be in the form of a URL.
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
