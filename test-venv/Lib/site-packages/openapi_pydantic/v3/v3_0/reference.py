from pydantic import BaseModel, Field

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

_examples = [
    {"$ref": "#/components/schemas/Pet"},
    {"$ref": "Pet.json"},
    {"$ref": "definitions.json#/Pet"},
]


class Reference(BaseModel):
    """
    A simple object to allow referencing other components in the specification.

    The Reference Object is defined by [JSON Reference](https://tools.ietf.org/html/draft-pbryan-zyp-json-ref-03)
    and follows the same structure, behavior and rules.

    For this specification, reference resolution is accomplished as defined by the JSON
    Reference specification and not by the JSON Schema specification.
    """

    ref: str = Field(alias="$ref")
    """**REQUIRED**. The reference string."""

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
