import binascii


def encode_int(num: int, bits: int) -> bytes:
    length = ((bits + 7) // 8) * 2
    padded_hex = "%0*x" % (length, num)
    big_endian = binascii.a2b_hex(padded_hex.encode("ascii"))
    return big_endian


def decode_int(s: bytes) -> int:
    return int(binascii.b2a_hex(s), 16)
