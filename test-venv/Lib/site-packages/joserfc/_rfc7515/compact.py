import typing as t
from .model import JWSAlgModel, CompactSignature
from ..errors import (
    DecodeError,
    MissingAlgorithmError,
)
from ..util import (
    json_b64encode,
    json_b64decode,
    urlsafe_b64encode,
    urlsafe_b64decode,
)

__all__ = [
    "sign_compact",
    "verify_compact",
    "detach_compact_content",
    "decode_header",
]


def sign_compact(obj: CompactSignature, alg: JWSAlgModel, key: t.Any) -> bytes:
    header_segment = json_b64encode(obj.headers())
    payload_segment = urlsafe_b64encode(obj.payload)
    signing_input = header_segment + b"." + payload_segment
    signature = urlsafe_b64encode(alg.sign(signing_input, key))
    return signing_input + b"." + signature


def verify_compact(obj: CompactSignature, alg: JWSAlgModel, key: t.Any) -> bool:
    signing_input = obj.segments["header"] + b"." + obj.segments["payload"]
    try:
        sig = urlsafe_b64decode(obj.segments["signature"])
    except (TypeError, ValueError):
        return False
    return alg.verify(signing_input, sig, key)


def detach_compact_content(value: str) -> str:
    # https://www.rfc-editor.org/rfc/rfc7515#appendix-F
    parts = value.split(".")
    parts[1] = ""
    return ".".join(parts)


def decode_header(header_segment: bytes) -> dict[str, t.Any]:
    try:
        protected: dict[str, t.Any] = json_b64decode(header_segment)
        if "alg" not in protected:
            raise MissingAlgorithmError()
    except (TypeError, ValueError):
        raise DecodeError("Invalid header")
    return protected
