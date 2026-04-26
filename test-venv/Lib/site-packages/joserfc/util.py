from __future__ import annotations
from typing import Any
import base64
import struct
import binascii
import json


def to_bytes(x: Any, charset: str = "utf-8", errors: str = "strict") -> bytes:
    if isinstance(x, bytes):
        return x
    if isinstance(x, str):
        return x.encode(charset, errors)
    if isinstance(x, (int, float)):
        return str(x).encode(charset, errors)
    return bytes(x)


def to_str(x: bytes | str, charset: str = "utf-8") -> str:
    if isinstance(x, bytes):
        return x.decode(charset)
    return x


def urlsafe_b64decode(s: bytes) -> bytes:
    if b"+" in s or b"/" in s:
        raise binascii.Error

    pad = -len(s) % 4
    if pad == 3:
        raise binascii.Error

    safe_ending = (b"AEIMQUYcgkosw048", b"AQgw")
    if pad and s[-1] not in safe_ending[pad - 1]:
        raise binascii.Error

    s += b"=" * pad
    return base64.b64decode(s, b"-_", validate=True)


def urlsafe_b64encode(s: bytes) -> bytes:
    return base64.urlsafe_b64encode(s).rstrip(b"=")


def base64_to_int(s: str) -> int:
    data = urlsafe_b64decode(to_bytes(s))
    buf = struct.unpack("%sB" % len(data), data)
    return int("".join(["%02x" % byte for byte in buf]), 16)


def int_to_base64(num: int, byte_count: int | None = None) -> str:
    if num < 0:
        raise ValueError("Must be a positive integer")

    if byte_count is None:
        byte_count = (num.bit_length() + 7) // 8
    elif num.bit_length() > byte_count * 8:
        raise ValueError("Number too large for byte count")

    s = num.to_bytes(byte_count, "big", signed=False)
    return urlsafe_b64encode(s).decode("utf-8", "strict")


def json_b64encode(data: dict[str, Any]) -> bytes:
    text = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
    return urlsafe_b64encode(to_bytes(text, "ascii"))


def json_b64decode(text: bytes) -> Any:
    return json.loads(urlsafe_b64decode(text))
