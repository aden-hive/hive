from typing import Optional

from pydantic import BaseModel

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

_examples = [
    {"namespace": "http://example.com/schema/sample", "prefix": "sample"},
    {"name": "aliens", "wrapped": True},
]


class XML(BaseModel):
    """
    A metadata object that allows for more fine-tuned XML model definitions.

    When using arrays, XML element names are *not* inferred (for singular/plural forms)
    and the `name` property SHOULD be used to add that information.
    See examples for expected behavior.
    """

    name: Optional[str] = None
    """
    Replaces the name of the element/attribute used for the described schema property.
    When defined within `items`, it will affect the name of the individual XML elements 
    within the list. When defined alongside `type` being `array` (outside the `items`),
    it will affect the wrapping element and only if `wrapped` is `true`.
    If `wrapped` is `false`, it will be ignored.
    """

    namespace: Optional[str] = None
    """
    The URI of the namespace definition.
    Value MUST be in the form of an absolute URI.
    """

    prefix: Optional[str] = None
    """
    The prefix to be used for the [name](#xmlName).
    """

    attribute: bool = False
    """
    Declares whether the property definition translates to an attribute instead of an 
    element. Default value is `false`.
    """

    wrapped: bool = False
    """
    MAY be used only for an array definition.
    Signifies whether the array is wrapped (for example, 
    `<books><book/><book/></books>`) or unwrapped (`<book/><book/>`).
    Default value is `false`.
    The definition takes effect only when defined alongside `type` being `array` 
    (outside the `items`).
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
