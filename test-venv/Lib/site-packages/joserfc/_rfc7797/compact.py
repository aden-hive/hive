from __future__ import annotations
import re
from typing import Any
from ..util import (
    to_bytes,
    to_str,
    json_b64encode,
    urlsafe_b64encode,
    urlsafe_b64decode,
)
from .._rfc7515.model import JWSAlgModel, CompactSignature
from .._rfc7515.compact import decode_header
from .._rfc7515.registry import JWSRegistry, default_registry
from ..errors import DecodeError
from .util import is_rfc7797_enabled


def sign_rfc7515_compact(obj: CompactSignature, alg: JWSAlgModel, key: Any) -> bytes:
    header_segment = json_b64encode(obj.headers())
    signing_input = header_segment + b"." + obj.payload
    signature = urlsafe_b64encode(alg.sign(signing_input, key))

    # if need to detach payload
    if __is_urlsafe_characters(obj.payload):
        out = signing_input + b"." + signature
    else:
        out = header_segment + b".." + signature
    return out


def extract_rfc7515_compact(
    value: bytes, payload: bytes | str | None = None, registry: JWSRegistry | None = None
) -> CompactSignature:
    """Extract the JWS Compact Serialization from bytes to object.

    :param value: JWS in bytes
    :param payload: optional payload, required with detached content
    :param registry: optional JWSRegistry instance
    :raise DecodeError: when decoding fails
    """
    parts = value.split(b".")
    if len(parts) != 3:
        raise DecodeError("Invalid JSON Web Signature")

    if registry is None:
        registry = default_registry

    header_segment, payload_segment, signature_segment = parts

    registry.validate_header_size(header_segment)
    registry.validate_signature_size(signature_segment)

    protected = decode_header(header_segment)

    if is_rfc7797_enabled(protected):
        if not payload_segment and payload:
            payload_segment = to_bytes(payload)
        payload = payload_segment
    else:
        if not payload_segment and payload:
            payload = to_bytes(payload)
            payload_segment = urlsafe_b64encode(payload)
        else:
            registry.validate_payload_size(payload_segment)
            try:
                payload = urlsafe_b64decode(payload_segment)
            except (TypeError, ValueError):
                raise DecodeError("Invalid payload")

    obj = CompactSignature(protected, payload)
    obj.segments.update(
        {
            "header": header_segment,
            "payload": payload_segment,
            "signature": signature_segment,
        }
    )
    return obj


# https://datatracker.ietf.org/doc/html/rfc7797#section-5.2
# the application MUST ensure that the payload contains only the URL-safe
# characters 'a'-'z', 'A'-'Z', '0'-'9', dash ('-'), underscore ('_'),
# and tilde ('~')
_re_urlsafe = re.compile("^[a-zA-Z0-9-_~]+$")


def __is_urlsafe_characters(s: bytes | str) -> bool:
    return bool(_re_urlsafe.match(to_str(s)))
