from typing import Optional

from pydantic import BaseModel, Field

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

_examples = [
    {"$ref": "#/components/schemas/Pet"},
    {"$ref": "Pet.json"},
    {"$ref": "definitions.json#/Pet"},
]


class Reference(BaseModel):
    """
    A simple object to allow referencing other components in the OpenAPI document.

    The `$ref` string value contains a URI [RFC3986](https://tools.ietf.org/html/rfc3986),
    which identifies the location of the value being referenced.

    See the rules for resolving [Relative References](#relativeReferencesURI).
    """

    ref: str = Field(alias="$ref")
    """**REQUIRED**. The reference identifier. This MUST be in the form of a URI."""

    summary: Optional[str] = None
    """
    A short summary which by default SHOULD override that of the referenced component.
    If the referenced object-type does not allow a `summary` field, then this field has 
    no effect.
    """

    description: Optional[str] = None
    """
    A description which by default SHOULD override that of the referenced component.
    [CommonMark syntax](https://spec.commonmark.org/) MAY be used for rich text 
    representation.
    If the referenced object-type does not allow a `description` field, then this field 
    has no effect.
    """

    if PYDANTIC_V2:
        model_config = ConfigDict(
            extra="allow",
            populate_by_name=True,
            json_schema_extra={"examples": _examples},
        )

    else:

        class Config:
            extra = Extra.allow
            allow_population_by_field_name = True
            schema_extra = {"examples": _examples}
