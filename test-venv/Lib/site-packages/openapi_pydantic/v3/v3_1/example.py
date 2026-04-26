from typing import Any, Optional

from pydantic import BaseModel

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

_examples = [
    {
        "summary": "A foo example",
        "value": {"foo": "bar"},
    },
    {
        "summary": "This is an example in XML",
        "externalValue": "http://example.org/examples/address-example.xml",
    },
    {
        "summary": "This is a text example",
        "externalValue": "http://foo.bar/examples/address-example.txt",
    },
]


class Example(BaseModel):
    summary: Optional[str] = None
    """
    Short description for the example.
    """

    description: Optional[str] = None
    """
    Long description for the example.
    [CommonMark syntax](https://spec.commonmark.org/) MAY be used for rich text 
    representation.
    """

    value: Optional[Any] = None
    """
    Embedded literal example.
    The `value` field and `externalValue` field are mutually exclusive.
    To represent examples of media types that cannot naturally represented in JSON or 
    YAML, use a string value to contain the example, escaping where necessary.
    """

    externalValue: Optional[str] = None
    """
    A URL that points to the literal example.
    This provides the capability to reference examples that cannot easily be included 
    in JSON or YAML documents.
    
    The `value` field and `externalValue` field are mutually exclusive.
    See the rules for resolving [Relative References](#relativeReferencesURI).
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
