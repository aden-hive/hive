from __future__ import annotations
from .._rfc7515.types import FlattenedJSONSerialization, JSONSignatureDict
from .._rfc7515.model import HeaderMember, FlattenedJSONSignature
from .._rfc7515.registry import JWSRegistry
from .._rfc7515.json import sign_json_member, FindKey
from ..util import to_bytes, json_b64decode, urlsafe_b64decode
from ..errors import DecodeError
from .util import is_rfc7797_enabled


def sign_rfc7797_json(
    member: HeaderMember,
    payload: bytes,
    registry: JWSRegistry,
    find_key: FindKey,
) -> FlattenedJSONSerialization:
    signature = sign_json_member(payload, member, registry, find_key)
    data: FlattenedJSONSerialization = {"payload": payload.decode("utf-8"), **signature}
    return data


def extract_rfc7797_json(value: FlattenedJSONSerialization, registry: JWSRegistry) -> FlattenedJSONSignature:
    if "protected" in value:
        protected_segment = to_bytes(value["protected"])
        registry.validate_header_size(protected_segment)
        protected = json_b64decode(protected_segment)
    else:
        protected = None

    header = value.get("header")
    member = HeaderMember(protected, header)

    payload_segment: bytes = value["payload"].encode("utf-8")
    if is_rfc7797_enabled(member.headers()):
        payload = payload_segment
    else:
        registry.validate_payload_size(payload_segment)
        try:
            payload = urlsafe_b64decode(payload_segment)
        except (TypeError, ValueError):
            raise DecodeError("Invalid payload")

    obj = FlattenedJSONSignature(member, payload)
    _sig: JSONSignatureDict = {"signature": value["signature"]}
    if "protected" in value:
        _sig["protected"] = value["protected"]
    if "header" in value:
        _sig["header"] = value["header"]
    obj.signature = _sig
    obj.segments = {"payload": payload_segment}
    return obj
