from typing import List, Optional

from pydantic import BaseModel

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra


class ServerVariable(BaseModel):
    """An object representing a Server Variable for server URL template substitution."""

    enum: Optional[List[str]] = None
    """
    An enumeration of string values to be used if the substitution options are from a 
    limited set. The array SHOULD NOT be empty.
    """

    default: str
    """
    **REQUIRED**. The default value to use for substitution,
    which SHALL be sent if an alternate value is _not_ supplied.
    Note this behavior is different than the [Schema Object's](#schemaObject) treatment 
    of default values, because in those cases parameter values are optional.
    If the [`enum`](#serverVariableEnum) is defined, the value MUST exist in the enum's 
    values.
    """

    description: Optional[str] = None
    """
    An optional description for the server variable.
    [CommonMark syntax](https://spec.commonmark.org/) MAY be used for rich text 
    representation.
    """

    if PYDANTIC_V2:
        model_config = ConfigDict(
            extra="allow",
        )

    else:

        class Config:
            extra = Extra.allow
