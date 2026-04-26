from __future__ import annotations
import struct
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.concatkdf import ConcatKDFHash
from ..registry import Header
from ..util import to_bytes, urlsafe_b64decode


__all__ = [
    "derive_key_for_concat_kdf",
    "u32be_len_input",
]


def derive_key_for_concat_kdf(
    shared_key: bytes, header: Header, cek_size: int, key_size: int | None, tag: bytes | None = None
) -> bytes:
    # PartyUInfo
    apu_info = u32be_len_input(header.get("apu"), True)
    # PartyVInfo
    apv_info = u32be_len_input(header.get("apv"), True)
    # SuppPubInfo

    if key_size:
        alg_id = u32be_len_input(header["alg"])
        bit_size = key_size
    else:
        alg_id = u32be_len_input(header["enc"])
        bit_size = cek_size

    pub_info = struct.pack(">I", bit_size)
    fixed_info = alg_id + apu_info + apv_info + pub_info

    if tag:
        cctag = u32be_len_input(tag)
        fixed_info += cctag

    ckdf = ConcatKDFHash(
        algorithm=hashes.SHA256(),
        length=bit_size // 8,
        otherinfo=fixed_info,
    )
    return ckdf.derive(shared_key)


def u32be_len_input(s: bytes | str | None, use_base64: bool = False) -> bytes:
    if not s:
        return b"\x00\x00\x00\x00"
    sb: bytes
    if use_base64:
        sb = urlsafe_b64decode(to_bytes(s))
    else:
        sb = to_bytes(s)
    return struct.pack(">I", len(sb)) + sb
