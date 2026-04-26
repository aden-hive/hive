from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

from .components import Components
from .external_documentation import ExternalDocumentation
from .info import Info
from .path_item import PathItem
from .paths import Paths
from .reference import Reference
from .security_requirement import SecurityRequirement
from .server import Server
from .tag import Tag


class OpenAPI(BaseModel):
    """This is the root document object of the OpenAPI document."""

    openapi: Literal["3.1.1", "3.1.0"] = "3.1.1"
    """
    **REQUIRED**. This string MUST be the [version number](#versions)
    of the OpenAPI Specification that the OpenAPI document uses.
    The `openapi` field SHOULD be used by tooling to interpret the OpenAPI document.
    This is *not* related to the API [`info.version`](#infoVersion) string.
    """

    info: Info
    """
    **REQUIRED**. Provides metadata about the API. The metadata MAY be used by tooling 
    as required.
    """

    jsonSchemaDialect: Optional[str] = None
    """
    The default value for the `$schema` keyword within [Schema Objects](#schemaObject)
    contained within this OAS document. This MUST be in the form of a URI.
    """

    servers: List[Server] = [Server(url="/")]
    """
    An array of Server Objects, which provide connectivity information to a target 
    server. If the `servers` property is not provided, or is an empty array,
    the default value would be a [Server Object](#serverObject) with a 
    [url](#serverUrl) value of `/`.
    """

    paths: Optional[Paths] = None
    """
    The available paths and operations for the API.
    """

    webhooks: Optional[Dict[str, Union[PathItem, Reference]]] = None
    """
    The incoming webhooks that MAY be received as part of this API and that the API 
    consumer MAY choose to implement.
    Closely related to the `callbacks` feature, this section describes requests 
    initiated other than by an API call,
    for example by an out of band registration.
    The key name is a unique string to refer to each webhook,
    while the (optionally referenced) Path Item Object describes a request
    that may be initiated by the API provider and the expected responses.
    An [example](../examples/v3.1/webhook-example.yaml) is available.
    """

    components: Optional[Components] = None
    """
    An element to hold various schemas for the document.
    """

    security: Optional[List[SecurityRequirement]] = None
    """
    A declaration of which security mechanisms can be used across the API. 
    The list of values includes alternative security requirement objects that can be 
    used.  Only one of the security requirement objects need to be satisfied to 
    authorize a request. Individual operations can override this definition. 
    To make security optional, an empty security requirement (`{}`) can be included in 
    the array.
    """

    tags: Optional[List[Tag]] = None
    """
    A list of tags used by the document with additional metadata.
    The order of the tags can be used to reflect on their order by the parsing tools.
    Not all tags that are used by the [Operation Object](#operationObject) must be 
    declared. The tags that are not declared MAY be organized randomly or based on the 
    tools' logic. Each tag name in the list MUST be unique.
    """

    externalDocs: Optional[ExternalDocumentation] = None
    """
    Additional external documentation.
    """

    if PYDANTIC_V2:
        model_config = ConfigDict(
            extra="allow",
        )

    else:

        class Config:
            extra = Extra.allow
