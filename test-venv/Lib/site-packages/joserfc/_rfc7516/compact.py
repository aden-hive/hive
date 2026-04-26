from .models import CompactEncryption, Recipient
from .registry import JWERegistry
from .._keys import Key
from ..errors import (
    MissingAlgorithmError,
    MissingEncryptionError,
    DecodeError,
)
from ..util import (
    json_b64decode,
    urlsafe_b64encode,
    urlsafe_b64decode,
)

__all__ = [
    "represent_compact",
    "extract_compact",
]


def represent_compact(obj: CompactEncryption) -> bytes:
    assert obj.recipient is not None
    encrypted_key = obj.recipient.encrypted_key
    assert encrypted_key is not None
    return b".".join(
        [
            obj.base64_segments["aad"],
            urlsafe_b64encode(encrypted_key),
            obj.base64_segments["iv"],
            obj.base64_segments["ciphertext"],
            obj.base64_segments["tag"],
        ]
    )


def extract_compact(value: bytes, registry: JWERegistry) -> CompactEncryption:
    parts = value.split(b".")
    if len(parts) != 5:
        raise ValueError("Invalid JSON Web Encryption")

    header_segment, ek_segment, iv_segment, ciphertext_segment, tag_segment = parts
    registry.validate_protected_header_size(header_segment)
    registry.validate_encrypted_key_size(ek_segment)
    registry.validate_initialization_vector_size(iv_segment)
    registry.validate_ciphertext_size(ciphertext_segment)
    registry.validate_auth_tag_size(tag_segment)
    try:
        protected = json_b64decode(header_segment)
        if "alg" not in protected:
            raise MissingAlgorithmError()
        if "enc" not in protected:
            raise MissingEncryptionError()
    except (TypeError, ValueError):
        raise DecodeError("Invalid header")

    obj = CompactEncryption(protected)
    obj.base64_segments.update(
        {
            "aad": header_segment,
            "iv": iv_segment,
            "ciphertext": ciphertext_segment,
            "tag": tag_segment,
        }
    )
    obj.bytes_segments.update(
        {
            "iv": urlsafe_b64decode(iv_segment),
            "ciphertext": urlsafe_b64decode(ciphertext_segment),
            "tag": urlsafe_b64decode(tag_segment),
        }
    )
    recipient: Recipient[Key] = Recipient(obj)
    recipient.encrypted_key = urlsafe_b64decode(ek_segment)
    obj.recipient = recipient
    return obj
