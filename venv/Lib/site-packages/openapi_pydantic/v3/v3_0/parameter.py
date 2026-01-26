import enum
from typing import Any, Dict, Optional, Union

from pydantic import BaseModel, Field

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

from .example import Example
from .media_type import MediaType
from .reference import Reference
from .schema import Schema

_examples = [
    {
        "name": "token",
        "in": "header",
        "description": "token to be passed as a header",
        "required": True,
        "schema": {
            "type": "array",
            "items": {"type": "integer", "format": "int64"},
        },
        "style": "simple",
    },
    {
        "name": "username",
        "in": "path",
        "description": "username to fetch",
        "required": True,
        "schema": {"type": "string"},
    },
    {
        "name": "id",
        "in": "query",
        "description": "ID of the object to fetch",
        "required": False,
        "schema": {"type": "array", "items": {"type": "string"}},
        "style": "form",
        "explode": True,
    },
    {
        "in": "query",
        "name": "freeForm",
        "schema": {
            "type": "object",
            "additionalProperties": {"type": "integer"},
        },
        "style": "form",
    },
    {
        "in": "query",
        "name": "coordinates",
        "content": {
            "application/json": {
                "schema": {
                    "type": "object",
                    "required": ["lat", "long"],
                    "properties": {
                        "lat": {"type": "number"},
                        "long": {"type": "number"},
                    },
                }
            }
        },
    },
]


class ParameterLocation(str, enum.Enum):
    """The location of a given parameter."""

    QUERY = "query"
    HEADER = "header"
    PATH = "path"
    COOKIE = "cookie"


class ParameterBase(BaseModel):
    """
    Base class for Parameter and Header.

    (Header is like Parameter, but has no `name` or `in` fields.)
    """

    description: Optional[str] = None
    """
    A brief description of the parameter.
    This could contain examples of use.
    [CommonMark syntax](https://spec.commonmark.org/) MAY be used for rich text 
    representation.
    """

    required: bool = False
    """
    Determines whether this parameter is mandatory.
    If the [parameter location](#parameterIn) is `"path"`, this property is 
    **REQUIRED** and its value MUST be `true`.
    Otherwise, the property MAY be included and its default value is `false`.
    """

    deprecated: bool = False
    """
    Specifies that a parameter is deprecated and SHOULD be transitioned out of usage.
    Default value is `false`.
    """

    style: Optional[str] = None
    """
    Describes how the parameter value will be serialized depending on the type of the 
    parameter value. Default values (based on value of `in`):
    
    - for `query` - `form`;
    - for `path` - `simple`;
    - for `header` - `simple`;
    - for `cookie` - `form`.
    """

    explode: Optional[bool] = None
    """
    When this is true, parameter values of type `array` or `object` generate separate 
    parameters for each value of the array or key-value pair of the map.
    For other types of parameters this property has no effect.
    When [`style`](#parameterStyle) is `form`, the default value is `true`.
    For all other styles, the default value is `false`.
    """

    param_schema: Optional[Union[Reference, Schema]] = Field(
        default=None, alias="schema"
    )
    """
    The schema defining the type used for the parameter.
    """

    example: Optional[Any] = None
    """
    Example of the parameter's potential value.
    The example SHOULD match the specified schema and encoding properties if present.
    The `example` field is mutually exclusive of the `examples` field.
    Furthermore, if referencing a `schema` that contains an example, 
    the `example` value SHALL _override_ the example provided by the schema.
    To represent examples of media types that cannot naturally be represented in JSON 
    or YAML, a string value can contain the example with escaping where necessary.
    """

    examples: Optional[Dict[str, Union[Example, Reference]]] = None
    """
    Examples of the parameter's potential value.
    Each example SHOULD contain a value in the correct format as specified in the 
    parameter encoding. The `examples` field is mutually exclusive of the `example` 
    field. Furthermore, if referencing a `schema` that contains an example,
    the `examples` value SHALL _override_ the example provided by the schema.
    """

    """
    For more complex scenarios, the [`content`](#parameterContent) property 
    can define the media type and schema of the parameter.
    A parameter MUST contain either a `schema` property, or a `content` property, but 
    not both. When `example` or `examples` are provided in conjunction with the 
    `schema` object, the example MUST follow the prescribed serialization strategy for 
    the parameter.
    """

    content: Optional[Dict[str, MediaType]] = None
    """
    A map containing the representations for the parameter.
    The key is the media type and the value describes it.
    The map MUST only contain one entry.
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


class Parameter(ParameterBase):
    """
    Describes a single operation parameter.

    A unique parameter is defined by a combination of a [name](#parameterName) and
    [location](#parameterIn).
    """

    """Fixed Fields"""

    name: str
    """
    **REQUIRED**. The name of the parameter.
    Parameter names are *case sensitive*.

    - If [`in`](#parameterIn) is `"path"`, the `name` field MUST correspond to a
      template expression occurring within the [path](#pathsPath) field in the
      [Paths Object](#pathsObject). See [Path Templating](#pathTemplating) for further
      information.
    - If [`in`](#parameterIn) is `"header"` and the `name` field is `"Accept"`,
      `"Content-Type"` or `"Authorization"`, the parameter definition SHALL be ignored.
    - For all other cases, the `name` corresponds to the parameter name used by the
      [`in`](#parameterIn) property.
    """

    param_in: ParameterLocation = Field(alias="in")
    """
    **REQUIRED**. The location of the parameter. Possible values are `"query"`,
    `"header"`, `"path"` or `"cookie"`.
    """

    allowEmptyValue: bool = False
    """
    Sets the ability to pass empty-valued parameters.
    This is valid only for `query` parameters and allows sending a parameter with an 
    empty value. Default value is `false`.
    If [`style`](#parameterStyle) is used, and if behavior is `n/a` (cannot be 
    serialized), the value of `allowEmptyValue` SHALL be ignored.
    Use of this property is NOT RECOMMENDED, as it is likely to be removed in a later 
    revision.
    """

    allowReserved: bool = False
    """
    Determines whether the parameter value SHOULD allow reserved characters,
    as defined by [RFC3986](https://tools.ietf.org/html/rfc3986#section-2.2)
    `:/?#[]@!$&'()*+,;=` to be included without percent-encoding.
    This property only applies to parameters with an `in` value of `query`.
    The default value is `false`.
    """
