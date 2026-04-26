from __future__ import annotations
import typing as t
import copy
from .model import (
    HeaderMember,
    GeneralJSONSignature,
    FlattenedJSONSignature,
)
from .types import (
    JSONSignatureDict,
    GeneralJSONSerialization,
    FlattenedJSONSerialization,
)
from .registry import JWSRegistry
from ..registry import reject_unprotected_crit_header
from ..util import (
    to_bytes,
    json_b64encode,
    json_b64decode,
    urlsafe_b64encode,
    urlsafe_b64decode,
)
from ..errors import DecodeError

__all__ = [
    "FindKey",
    "sign_general_json",
    "sign_flattened_json",
    "sign_json_member",
    "extract_general_json",
    "verify_general_json",
    "verify_flattened_json",
    "detach_json_content",
]

FindKey = t.Callable[[HeaderMember], t.Any]


def sign_general_json(
    members: list[HeaderMember],
    payload: bytes,
    registry: JWSRegistry,
    find_key: FindKey,
) -> GeneralJSONSerialization:
    payload_segment = urlsafe_b64encode(payload)
    signatures: list[JSONSignatureDict] = [
        sign_json_member(payload_segment, member, registry, find_key) for member in members
    ]
    return {
        "payload": payload_segment.decode("utf-8"),
        "signatures": signatures,
    }


def sign_flattened_json(
    member: HeaderMember,
    payload: bytes,
    registry: JWSRegistry,
    find_key: FindKey,
) -> FlattenedJSONSerialization:
    payload_segment = urlsafe_b64encode(payload)
    signature = sign_json_member(payload_segment, member, registry, find_key)
    data: FlattenedJSONSerialization = {"payload": payload_segment.decode("utf-8"), **signature}
    return data


def sign_json_member(
    payload_segment: bytes, member: HeaderMember, registry: JWSRegistry, find_key: FindKey
) -> JSONSignatureDict:
    reject_unprotected_crit_header(member.header)
    headers = member.headers()
    registry.check_header(headers)
    alg = registry.get_alg(headers["alg"])
    key = find_key(member)
    alg.check_key(key)
    if member.protected:
        protected_segment = json_b64encode(member.protected)
    else:
        protected_segment = b""
    signing_input = b".".join([protected_segment, payload_segment])
    signature = urlsafe_b64encode(alg.sign(signing_input, key))
    rv: JSONSignatureDict = {"signature": signature.decode("utf-8")}
    if member.protected:
        rv["protected"] = protected_segment.decode("utf-8")
    if member.header:
        rv["header"] = member.header
    return rv


def extract_general_json(value: GeneralJSONSerialization, registry: JWSRegistry) -> GeneralJSONSignature:
    payload_segment: bytes = value["payload"].encode("utf-8")
    registry.validate_payload_size(payload_segment)
    try:
        payload = urlsafe_b64decode(payload_segment)
    except (TypeError, ValueError):
        raise DecodeError("Invalid payload")

    signatures: list[JSONSignatureDict] = value["signatures"]
    members = [__signature_to_member(sig, registry) for sig in signatures]
    obj = GeneralJSONSignature(members, payload)
    obj.signatures = signatures
    obj.segments = {"payload": payload_segment}
    return obj


def __signature_to_member(sig: JSONSignatureDict, registry: JWSRegistry) -> HeaderMember:
    member = HeaderMember()
    if "protected" in sig:
        protected_segment = to_bytes(sig["protected"])
        registry.validate_header_size(protected_segment)
        member.protected = json_b64decode(protected_segment)
    if "header" in sig:
        member.header = sig["header"]
    return member


def verify_general_json(obj: GeneralJSONSignature, registry: JWSRegistry, find_key: FindKey) -> bool:
    payload_segment = obj.segments["payload"]
    for index, signature in enumerate(obj.signatures):
        member = obj.members[index]
        if not verify_signature(member, signature, payload_segment, registry, find_key):
            return False
    return True


def verify_flattened_json(obj: FlattenedJSONSignature, registry: JWSRegistry, find_key: FindKey) -> bool:
    payload_segment = obj.segments["payload"]
    assert obj.signature is not None
    return verify_signature(obj.member, obj.signature, payload_segment, registry, find_key)


def verify_signature(
    member: HeaderMember,
    signature: JSONSignatureDict,
    payload_segment: bytes,
    registry: JWSRegistry,
    find_key: FindKey,
) -> bool:
    reject_unprotected_crit_header(member.header)
    headers = member.headers()
    registry.check_header(headers)
    alg = registry.get_alg(headers["alg"])
    key = find_key(member)
    alg.check_key(key)

    if "protected" in signature:
        protected_segment = to_bytes(signature["protected"])
    else:
        protected_segment = b""

    signature_segment = to_bytes(signature["signature"])
    registry.validate_signature_size(signature_segment)

    sig = urlsafe_b64decode(signature_segment)
    signing_input = b".".join([protected_segment, payload_segment])
    return alg.verify(signing_input, sig, key)


def detach_json_content(value: dict[str, t.Any]) -> dict[str, t.Any]:
    # https://www.rfc-editor.org/rfc/rfc7515#appendix-F
    rv = copy.deepcopy(value)  # don't alter original value
    if "payload" in rv:
        del rv["payload"]
    return rv
