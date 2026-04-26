from typing import Optional

from pydantic import BaseModel

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

from .external_documentation import ExternalDocumentation

_examples = [{"name": "pet", "description": "Pets operations"}]


class Tag(BaseModel):
    """
    Adds metadata to a single tag that is used by the
    [Operation Object](#operationObject).
    It is not mandatory to have a Tag Object per tag defined in the Operation Object
    instances.
    """

    name: str
    """
    **REQUIRED**. The name of the tag.
    """

    description: Optional[str] = None
    """
    A short description for the tag.
    [CommonMark syntax](https://spec.commonmark.org/) MAY be used for rich text 
    representation.
    """

    externalDocs: Optional[ExternalDocumentation] = None
    """
    Additional external documentation for this tag.
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
