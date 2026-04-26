from __future__ import annotations
from typing import Any, Callable, Union
from .errors import (
    MissingHeaderError,
    MissingCritHeaderError,
    UnsupportedHeaderError,
    InvalidHeaderValueError,
)

Header = dict[str, Any]


def is_str(value: Any) -> None:
    if not isinstance(value, str):
        raise ValueError("must be a str")


def is_url(value: str) -> None:
    is_str(value)
    if not value.startswith(("http://", "https://")):
        raise ValueError("must be a URL")


def is_int(value: int) -> None:
    if not isinstance(value, int):
        raise ValueError("must be an int")


def is_bool(value: bool) -> None:
    if not isinstance(value, bool):
        raise ValueError("must be an bool")


def is_list_str(values: list[str]) -> None:
    if not isinstance(values, list):
        raise ValueError("must be a list[str]")

    if not all(isinstance(value, str) for value in values):
        raise ValueError("must be a list[str]")


def is_jwk(value: dict[str, Any]) -> None:
    if not isinstance(value, dict):
        raise ValueError("must be a JWK")


def in_choices(choices: list[str]) -> Callable[[Union[str, list[str]]], None]:
    def _is_one_of(value: str | list[str]) -> None:
        if isinstance(value, list):
            if not all(v in choices for v in value):
                raise ValueError(f"must be one of {choices}")

        elif value not in choices:
            raise ValueError(f"must be one of {choices}")

    return _is_one_of


def not_support(_: Any) -> None:
    raise ValueError("is not supported")


Validate = Callable[[Any], None]
_value_validators: dict[str, Validate] = {
    "str": is_str,
    "list[str]": is_list_str,
    "int": is_int,
    "bool": is_bool,
    "url": is_url,
    "jwk": is_jwk,
    "none": not_support,
}


class HeaderParameter:
    """Define the header parameter for JWS and JWE."""

    def __init__(self, description: str, validate: str | Validate, required: bool = False):
        #: a short description of the header parameter
        self.description = description
        #: a function for validating the header parameter's value
        self.validate = _value_validators[validate] if isinstance(validate, str) else validate
        #: if this header parameter is required
        self.required = required


#: Define header parameters for JWS and JWE
HeaderRegistryDict = dict[str, HeaderParameter]


class KeyParameter:
    """Define the key parameter for JWK."""

    def __init__(self, description: str, validate: str | Validate, private: bool | None = None, required: bool = False):
        #: a short description of the key parameter
        self.description: str = description
        #: a function for validating the key parameter's value
        self.validate = _value_validators[validate] if isinstance(validate, str) else validate
        #: if this key parameter for private key only
        self.private = private
        #: if this key parameter is required
        self.required = required


class KeyOperation:
    def __init__(self, description: str, use: str, private: bool | None):
        self.description = description
        self.use = use
        self.private = private


#: Define parameters for JWK
KeyParameterRegistryDict = dict[str, KeyParameter]
KeyOperationRegistryDict = dict[str, KeyOperation]

#: Basic JWS header registry
JWS_HEADER_REGISTRY: HeaderRegistryDict = {
    "alg": HeaderParameter("Algorithm", is_str, True),
    "jku": HeaderParameter("JWK Set URL", is_url),
    "jwk": HeaderParameter("JSON Web Key", is_jwk),
    "kid": HeaderParameter("Key ID", is_str),
    "x5u": HeaderParameter("X.509 URL", is_url),
    "x5c": HeaderParameter("X.509 Certificate Chain", is_list_str),
    "x5t": HeaderParameter("X.509 Certificate SHA-1 Thumbprint", is_str),
    "x5t#S256": HeaderParameter("X.509 Certificate SHA-256 Thumbprint", is_str),
    "typ": HeaderParameter("Type", is_str),
    "cty": HeaderParameter("Content Type", is_str),
    "crit": HeaderParameter("Critical", is_list_str),
    # Enable RFC7797 by default.
    "b64": HeaderParameter("JWS Signing Input Formula", is_bool),
}

#: Basic JWE header registry
JWE_HEADER_REGISTRY = {
    "enc": HeaderParameter("Encryption Algorithm", is_str, True),
    "zip": HeaderParameter("Compression Algorithm", is_str),
    **JWS_HEADER_REGISTRY,
}

#: Basic JWK parameter registry
JWK_PARAMETER_REGISTRY = {
    "kty": KeyParameter("Key Type", is_str, required=True),  # This member MUST be present in a JWK.
    "use": KeyParameter("Public Key Use", in_choices(["sig", "enc"])),
    "key_ops": KeyParameter(
        "Key Operations",
        in_choices(
            [
                "sign",
                "verify",
                "encrypt",
                "decrypt",
                "wrapKey",
                "unwrapKey",
                "deriveKey",
                "deriveBits",
            ]
        ),
    ),
    "alg": KeyParameter("Algorithm", is_str),
    "kid": KeyParameter("Key ID", is_str),
    "x5u": KeyParameter("X.509 URL", is_url),
    "x5c": KeyParameter("X.509 Certificate Chain", is_list_str),
    "x5t": KeyParameter("X.509 Certificate SHA-1 Thumbprint", is_str),
    "x5t#S256": KeyParameter("X.509 Certificate SHA-256 Thumbprint", is_str),
}

#: Common JWK operations
#: https://www.rfc-editor.org/rfc/rfc7517#section-4.3
JWK_OPERATION_REGISTRY = {
    "sign": KeyOperation("compute digital signature or MAC", "sig", True),
    "verify": KeyOperation("verify digital signature or MAC", "sig", False),
    "encrypt": KeyOperation("encrypt content", "enc", False),
    "decrypt": KeyOperation("decrypt content and validate decryption, if applicable", "enc", True),
    "wrapKey": KeyOperation("encrypt key", "enc", False),
    "unwrapKey": KeyOperation("decrypt key and validate decryption, if applicable", "enc", True),
    "deriveKey": KeyOperation("derive key", "enc", False),
    "deriveBits": KeyOperation("derive bits not to be used as a key", "enc", None),
}


def check_supported_header(registry: HeaderRegistryDict, header: Header) -> None:
    allowed_keys = set(registry.keys())
    unsupported_keys = set(header.keys()) - allowed_keys
    if unsupported_keys:
        raise UnsupportedHeaderError(f"Unsupported {unsupported_keys} in header")


def check_registry_header(registry: HeaderRegistryDict, header: Header, check_required: bool = True) -> None:
    for key, reg in registry.items():
        if check_required and reg.required and key not in header:
            raise MissingHeaderError(key)
        if key in header:
            try:
                reg.validate(header[key])
            except ValueError as error:
                raise InvalidHeaderValueError(f"'{key}' in header {error}")


def check_crit_header(registry: HeaderRegistryDict, header: Header) -> None:
    # check `crit` header
    missing_crit_headers = []
    unsupported_crit_headers = []
    if "crit" in header:
        for k in header["crit"]:
            if k not in header:
                missing_crit_headers.append(k)
            elif k not in registry:
                unsupported_crit_headers.append(k)

    if missing_crit_headers:
        raise MissingCritHeaderError(",".join(missing_crit_headers))
    elif unsupported_crit_headers:
        raise UnsupportedHeaderError(f"Unsupported {unsupported_crit_headers} in header")


def reject_unprotected_crit_header(unprotected: Header | None) -> None:
    if unprotected and "crit" in unprotected:
        raise UnsupportedHeaderError("'crit' header MUST be protected header")
