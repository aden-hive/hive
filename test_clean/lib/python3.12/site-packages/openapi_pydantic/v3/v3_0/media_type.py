from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

from .encoding import Encoding
from .example import Example
from .reference import Reference
from .schema import Schema

_examples = [
    {
        "schema": {"$ref": "#/components/schemas/Pet"},
        "examples": {
            "cat": {
                "summary": "An example of a cat",
                "value": {
                    "name": "Fluffy",
                    "petType": "Cat",
                    "color": "White",
                    "gender": "male",
                    "breed": "Persian",
                },
            },
            "dog": {
                "summary": "An example of a dog with a cat's name",
                "value": {
                    "name": "Puma",
                    "petType": "Dog",
                    "color": "Black",
                    "gender": "Female",
                    "breed": "Mixed",
                },
            },
        },
    }
]


class MediaType(BaseModel):
    """Each Media Type Object provides schema and examples for the media type
    identified by its key."""

    media_type_schema: Optional[Union[Reference, Schema]] = Field(
        default=None, alias="schema"
    )
    """
    The schema defining the content of the request, response, or parameter.
    """

    example: Optional[Any] = None
    """
    Example of the media type.
    
    The example object SHOULD be in the correct format as specified by the media type.
    
    The `example` field is mutually exclusive of the `examples` field.
    
    Furthermore, if referencing a `schema` which contains an example,
    the `example` value SHALL _override_ the example provided by the schema.
    """

    examples: Optional[Dict[str, Union[Example, Reference]]] = None
    """
    Examples of the media type.
    
    Each example object SHOULD match the media type and specified schema if present.
    
    The `examples` field is mutually exclusive of the `example` field.
    
    Furthermore, if referencing a `schema` which contains an example,
    the `examples` value SHALL _override_ the example provided by the schema.
    """

    encoding: Optional[Dict[str, Encoding]] = None
    """
    A map between a property name and its encoding information.
    The key, being the property name, MUST exist in the schema as a property.
    The encoding object SHALL only apply to `requestBody` objects
    when the media type is `multipart` or `application/x-www-form-urlencoded`.
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
