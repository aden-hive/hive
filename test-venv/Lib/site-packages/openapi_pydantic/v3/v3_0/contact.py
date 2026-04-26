from typing import Optional

from pydantic import BaseModel

from openapi_pydantic.compat import PYDANTIC_V2, ConfigDict, Extra

_examples = [
    {
        "name": "API Support",
        "url": "http://www.example.com/support",
        "email": "support@example.com",
    }
]


class Contact(BaseModel):
    """
    Contact information for the exposed API.
    """

    name: Optional[str] = None
    """
    The identifying name of the contact person/organization.
    """

    url: Optional[str] = None
    """
    The URL pointing to the contact information.
    MUST be in the format of a URL.
    """

    email: Optional[str] = None
    """
    The email address of the contact person/organization.
    MUST be in the format of an email address.
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
