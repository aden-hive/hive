from typing import Dict, Optional, Union

from pydantic import BaseModel

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

from .callback import Callback
from .example import Example
from .header import Header
from .link import Link
from .parameter import Parameter
from .reference import Reference
from .request_body import RequestBody
from .response import Response
from .schema import Schema
from .security_scheme import SecurityScheme

_examples = [
    {
        "schemas": {
            "GeneralError": {
                "type": "object",
                "properties": {
                    "code": {"type": "integer", "format": "int32"},
                    "message": {"type": "string"},
                },
            },
            "Category": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "format": "int64"},
                    "name": {"type": "string"},
                },
            },
            "Tag": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer", "format": "int64"},
                    "name": {"type": "string"},
                },
            },
        },
        "parameters": {
            "skipParam": {
                "name": "skip",
                "in": "query",
                "description": "number of items to skip",
                "required": True,
                "schema": {"type": "integer", "format": "int32"},
            },
            "limitParam": {
                "name": "limit",
                "in": "query",
                "description": "max records to return",
                "required": True,
                "schema": {"type": "integer", "format": "int32"},
            },
        },
        "responses": {
            "NotFound": {"description": "Entity not found."},
            "IllegalInput": {"description": "Illegal input for operation."},
            "GeneralError": {
                "description": "General Error",
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/GeneralError"}
                    }
                },
            },
        },
        "securitySchemes": {
            "api_key": {
                "type": "apiKey",
                "name": "api_key",
                "in": "header",
            },
            "petstore_auth": {
                "type": "oauth2",
                "flows": {
                    "implicit": {
                        "authorizationUrl": "http://example.org/api/oauth/dialog",
                        "scopes": {
                            "write:pets": "modify pets in your account",
                            "read:pets": "read your pets",
                        },
                    }
                },
            },
        },
    }
]


class Components(BaseModel):
    """
    Holds a set of reusable objects for different aspects of the OAS.
    All objects defined within the components object will have no effect on the API
    unless they are explicitly referenced from properties outside the components object.
    """

    schemas: Optional[Dict[str, Union[Reference, Schema]]] = None
    """An object to hold reusable [Schema Objects](#schemaObject)."""

    responses: Optional[Dict[str, Union[Response, Reference]]] = None
    """An object to hold reusable [Response Objects](#responseObject)."""

    parameters: Optional[Dict[str, Union[Parameter, Reference]]] = None
    """An object to hold reusable [Parameter Objects](#parameterObject)."""

    examples: Optional[Dict[str, Union[Example, Reference]]] = None
    """An object to hold reusable [Example Objects](#exampleObject)."""

    requestBodies: Optional[Dict[str, Union[RequestBody, Reference]]] = None
    """An object to hold reusable [Request Body Objects](#requestBodyObject)."""

    headers: Optional[Dict[str, Union[Header, Reference]]] = None
    """An object to hold reusable [Header Objects](#headerObject)."""

    securitySchemes: Optional[Dict[str, Union[SecurityScheme, Reference]]] = None
    """An object to hold reusable [Security Scheme Objects](#securitySchemeObject)."""

    links: Optional[Dict[str, Union[Link, Reference]]] = None
    """An object to hold reusable [Link Objects](#linkObject)."""

    callbacks: Optional[Dict[str, Union[Callback, Reference]]] = None
    """An object to hold reusable [Callback Objects](#callbackObject)."""

    if PYDANTIC_V2:
        model_config = ConfigDict(
            extra="allow",
            json_schema_extra={"examples": _examples},
        )

    else:

        class Config:
            extra = Extra.allow
            schema_extra = {"examples": _examples}
