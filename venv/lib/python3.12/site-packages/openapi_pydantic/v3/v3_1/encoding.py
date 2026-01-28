from typing import TYPE_CHECKING, Dict, Optional, Union

from pydantic import BaseModel

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

from .reference import Reference

if TYPE_CHECKING:
    from .header import Header

_examples = [
    {
        "contentType": "image/png, image/jpeg",
        "headers": {
            "X-Rate-Limit-Limit": {
                "description": "The number of allowed requests in the "
                "current period",
                "schema": {"type": "integer"},
            }
        },
    }
]


class Encoding(BaseModel):
    """A single encoding definition applied to a single schema property."""

    contentType: Optional[str] = None
    """
    The Content-Type for encoding a specific property.
    Default value depends on the property type:
    
    for `object` - `application/json`;
    for `array` – the default is defined based on the inner type;
    for all other cases the default is `application/octet-stream`.
    
    The value can be a specific media type (e.g. `application/json`), a wildcard media 
    type (e.g. `image/*`), or a comma-separated list of the two types.
    """

    headers: Optional[Dict[str, Union["Header", Reference]]] = None
    """
    A map allowing additional information to be provided as headers, for example 
    `Content-Disposition`.
    
    `Content-Type` is described separately and SHALL be ignored in this section.
    This property SHALL be ignored if the request body media type is not a `multipart`.
    """

    style: Optional[str] = None
    """
    Describes how a specific property value will be serialized depending on its type.
    
    See [Parameter Object](#parameterObject) for details on the 
    [`style`](#parameterStyle) property. The behavior follows the same values as 
    `query` parameters, including default values.
    This property SHALL be ignored if the request body media type
    is not `application/x-www-form-urlencoded` or `multipart/form-data`.
    If a value is explicitly defined, then the value of 
    [`contentType`](#encodingContentType) (implicit or explicit) SHALL be ignored.
    """

    explode: Optional[bool] = None
    """
    When this is true, property values of type `array` or `object` generate separate 
    parameters for each value of the array, or key-value-pair of the map.
    
    For other types of properties this property has no effect.
    When [`style`](#encodingStyle) is `form`, the default value is `true`.
    For all other styles, the default value is `false`.
    This property SHALL be ignored if the request body media type
    is not `application/x-www-form-urlencoded` or `multipart/form-data`.
    If a value is explicitly defined, then the value of 
    [`contentType`](#encodingContentType) (implicit or explicit) SHALL be ignored.
    """

    allowReserved: bool = False
    """
    Determines whether the parameter value SHOULD allow reserved characters,
    as defined by [RFC3986](https://tools.ietf.org/html/rfc3986#section-2.2)
    `:/?#[]@!$&'()*+,;=` to be included without percent-encoding.
    The default value is `false`.
    This property SHALL be ignored if the request body media type
    is not `application/x-www-form-urlencoded` or `multipart/form-data`.
    If a value is explicitly defined,
    then the value of [`contentType`](#encodingContentType) (implicit or explicit) 
    SHALL be ignored.
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
