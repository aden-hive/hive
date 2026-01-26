"""
OpenAPI v3.0 schema types, created according to the specification:
https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.4.md

The type orders are according to the contents of the specification:
https://github.com/OAI/OpenAPI-Specification/blob/master/versions/3.0.4.md#table-of-contents
"""

from typing import TYPE_CHECKING

from openapi_pydantic.compat import PYDANTIC_V2

from .callback import Callback as Callback
from .components import Components as Components
from .contact import Contact as Contact
from .datatype import DataType as DataType
from .discriminator import Discriminator as Discriminator
from .encoding import Encoding as Encoding
from .example import Example as Example
from .external_documentation import ExternalDocumentation as ExternalDocumentation
from .header import Header as Header
from .info import Info as Info
from .license import License as License
from .link import Link as Link
from .media_type import MediaType as MediaType
from .oauth_flow import OAuthFlow as OAuthFlow
from .oauth_flows import OAuthFlows as OAuthFlows
from .open_api import OpenAPI as OpenAPI
from .operation import Operation as Operation
from .parameter import Parameter as Parameter
from .parameter import ParameterLocation as ParameterLocation
from .path_item import PathItem as PathItem
from .paths import Paths as Paths
from .reference import Reference as Reference
from .request_body import RequestBody as RequestBody
from .response import Response as Response
from .responses import Responses as Responses
from .schema import Schema as Schema
from .schema import schema_validate as schema_validate
from .security_requirement import SecurityRequirement as SecurityRequirement
from .security_scheme import SecurityScheme as SecurityScheme
from .server import Server as Server
from .server_variable import ServerVariable as ServerVariable
from .tag import Tag as Tag
from .xml import XML as XML

if TYPE_CHECKING:
    pass
elif PYDANTIC_V2:
    # resolve forward references
    Encoding.model_rebuild()
    OpenAPI.model_rebuild()
    Components.model_rebuild()
    Operation.model_rebuild()
else:
    # resolve forward references
    Encoding.update_forward_refs(Header=Header)
    Schema.update_forward_refs()
    Operation.update_forward_refs(PathItem=PathItem)
