from typing import List, Optional, Union

from pydantic import BaseModel, Field

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

from .operation import Operation
from .parameter import Parameter
from .reference import Reference
from .server import Server

_examples = [
    {
        "get": {
            "description": "Returns pets based on ID",
            "summary": "Find pets by ID",
            "operationId": "getPetsById",
            "responses": {
                "200": {
                    "description": "pet response",
                    "content": {
                        "*/*": {
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/Pet"},
                            }
                        }
                    },
                },
                "default": {
                    "description": "error payload",
                    "content": {
                        "text/html": {
                            "schema": {"$ref": "#/components/schemas/ErrorModel"}
                        }
                    },
                },
            },
        },
        "parameters": [
            {
                "name": "id",
                "in": "path",
                "description": "ID of pet to use",
                "required": True,
                "schema": {"type": "array", "items": {"type": "string"}},
                "style": "simple",
            }
        ],
    }
]


class PathItem(BaseModel):
    """
    Describes the operations available on a single path.
    A Path Item MAY be empty, due to [ACL constraints](#securityFiltering).
    The path itself is still exposed to the documentation viewer
    but they will not know which operations and parameters are available.
    """

    ref: Optional[str] = Field(default=None, alias="$ref")
    """
    Allows for an external definition of this path item.
    The referenced structure MUST be in the format of a 
    [Path Item Object](#pathItemObject).
    
    In case a Path Item Object field appears both in the defined object and the 
    referenced object, the behavior is undefined.
    """

    summary: Optional[str] = None
    """
    An optional, string summary, intended to apply to all operations in this path.
    """

    description: Optional[str] = None
    """
    An optional, string description, intended to apply to all operations in this path.
    [CommonMark syntax](https://spec.commonmark.org/) MAY be used for rich text 
    representation.
    """

    get: Optional[Operation] = None
    """
    A definition of a GET operation on this path.
    """

    put: Optional[Operation] = None
    """
    A definition of a PUT operation on this path.
    """

    post: Optional[Operation] = None
    """
    A definition of a POST operation on this path.
    """

    delete: Optional[Operation] = None
    """
    A definition of a DELETE operation on this path.
    """

    options: Optional[Operation] = None
    """
    A definition of a OPTIONS operation on this path.
    """

    head: Optional[Operation] = None
    """
    A definition of a HEAD operation on this path.
    """

    patch: Optional[Operation] = None
    """
    A definition of a PATCH operation on this path.
    """

    trace: Optional[Operation] = None
    """
    A definition of a TRACE operation on this path.
    """

    servers: Optional[List[Server]] = None
    """
    An alternative `server` array to service all operations in this path.
    """

    parameters: Optional[List[Union[Parameter, Reference]]] = None
    """
    A list of parameters that are applicable for all the operations described under 
    this path. These parameters can be overridden at the operation level, but cannot be 
    removed there. The list MUST NOT include duplicated parameters.
    A unique parameter is defined by a combination of a [name](#parameterName) and 
    [location](#parameterIn). The list can use the [Reference Object](#referenceObject) 
    to link to parameters that are defined at the
    [OpenAPI Object's components/parameters](#componentsParameters).
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
