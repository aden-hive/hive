from typing import TYPE_CHECKING, Any, Union

from pydantic import BaseModel, Field

from openapi_pydantic.compat import PYDANTIC_V2

from .v3_0 import OpenAPI as OpenAPIv3_0
from .v3_1 import OpenAPI as OpenAPIv3_1

OpenAPIv3 = Union[OpenAPIv3_1, OpenAPIv3_0]

if TYPE_CHECKING:

    def parse_obj(data: Any) -> OpenAPIv3:
        """Parse a raw object into an OpenAPI model with version inference."""
        ...

elif PYDANTIC_V2:
    from pydantic import RootModel

    class _OpenAPI(RootModel):
        root: OpenAPIv3 = Field(discriminator="openapi")

    def parse_obj(data: Any) -> OpenAPIv3:
        return _OpenAPI.model_validate(data).root

else:

    class _OpenAPI(BaseModel):
        __root__: OpenAPIv3 = Field(discriminator="openapi")

    def parse_obj(data: Any) -> OpenAPIv3:
        return _OpenAPI.parse_obj(data).__root__
