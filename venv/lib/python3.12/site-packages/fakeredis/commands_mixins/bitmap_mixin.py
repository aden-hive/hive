import re
from typing import Any, Callable, List, Optional

from fakeredis import _msgs as msgs
from fakeredis._commands import (
    command,
    Key,
    Int,
    BitOffset,
    BitValue,
    fix_range_string,
    fix_range,
    CommandItem,
)
from fakeredis._helpers import SimpleError, casematch
from fakeredis._typing import VersionType


class BitfieldEncoding:
    signed: bool
    size: int

    def __init__(self, encoding: bytes) -> None:
        match = re.match(rb"^([ui])(\d+)$", encoding)
        if match is None:
            raise SimpleError(msgs.INVALID_BITFIELD_TYPE)

        self.signed = match[1] == b"i"
        self.size = int(match[2])

        if self.size < 1 or self.size > (64 if self.signed else 63):
            raise SimpleError(msgs.INVALID_BITFIELD_TYPE)


class BitmapCommandsMixin:
    def __init(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.version: VersionType

    @staticmethod
    def _bytes_as_bin_string(value: bytes) -> str:
        return "".join([bin(i).lstrip("0b").rjust(8, "0") for i in value])

    @command((Key(bytes), Int), (bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def bitpos(self, key: CommandItem, bit: int, *args: bytes) -> int:
        if bit != 0 and bit != 1:
            raise SimpleError(msgs.BIT_ARG_MUST_BE_ZERO_OR_ONE)
        if len(args) > 3:
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        if len(args) == 3 and self.version < (7,):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        bit_mode = False
        if len(args) == 3 and self.version >= (7,):
            bit_mode = casematch(args[2], b"bit")
            if not bit_mode and not casematch(args[2], b"byte"):
                raise SimpleError(msgs.SYNTAX_ERROR_MSG)

        if key.value is None:
            # The first clear bit is at 0, the first set bit is not found (-1).
            return -1 if bit == 1 else 0

        start = 0 if len(args) == 0 else Int.decode(args[0])
        source_value = self._bytes_as_bin_string(key.value) if bit_mode else key.value
        end = len(source_value) if len(args) <= 1 else Int.decode(args[1])
        length = len(source_value)
        start, end = fix_range(start, end, length)
        if start == end == -1:
            return -1
        source_value = source_value[start:end] if bit_mode else self._bytes_as_bin_string(source_value[start:end])

        result = source_value.find(str(bit))
        if result != -1:
            result += start if bit_mode else (start * 8)
        elif bit == 0 and len(args) <= 1:
            # Redis treats the value as padded with zero bytes to an infinity
            # if the user is looking for the first clear bit and no end is set.
            result = len(key.value) * 8
        return result

    @command(name="BITCOUNT", fixed=(Key(bytes),), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def bitcount(self, key: CommandItem, *args: bytes) -> int:
        # Redis checks the argument count before decoding integers. That's why
        # we can't declare them as Int.
        if len(args) == 0:
            if key.value is None:
                return 0
            return bin(int.from_bytes(key.value, "little")).count("1")

        if not 2 <= len(args) <= 3:
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        try:
            start = Int.decode(args[0])
            end = Int.decode(args[1])
        except SimpleError as e:
            if self.version >= (7, 4):
                raise e
            return 0
        bit_mode = False
        if len(args) == 3 and self.version < (7,):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        if len(args) == 3 and self.version >= (7,):
            bit_mode = casematch(args[2], b"bit")
            if not bit_mode and not casematch(args[2], b"byte"):
                raise SimpleError(msgs.SYNTAX_ERROR_MSG)

        if key.value is None:
            return 0
        if bit_mode:
            value = self._bytes_as_bin_string(key.value if key.value else b"")
            start, end = fix_range_string(start, end, len(value))
            res: int = value.count("1", start, end)
            return res
        start, end = fix_range_string(start, end, len(key.value))
        value = key.value[start:end]

        return bin(int.from_bytes(value, "little")).count("1")

    @command(fixed=(Key(bytes), BitOffset))
    def getbit(self, key: CommandItem, offset: int) -> int:
        value = key.get(b"")
        byte = offset // 8
        remaining = offset % 8
        actual_bitoffset = 7 - remaining
        try:
            actual_val = value[byte]
        except IndexError:
            return 0
        return 1 if (1 << actual_bitoffset) & actual_val else 0

    @command((Key(bytes), BitOffset, BitValue))
    def setbit(self, key: CommandItem, offset: int, value: int) -> int:
        val = key.value if key.value is not None else b"\x00"
        byte = offset // 8
        remaining = offset % 8
        actual_bitoffset = 7 - remaining
        if len(val) - 1 < byte:
            # We need to expand val so that we can set the appropriate
            # bit.
            needed = byte - (len(val) - 1)
            val += b"\x00" * needed
        old_byte = val[byte]
        if value == 1:
            new_byte = old_byte | (1 << actual_bitoffset)
        else:
            new_byte = old_byte & ~(1 << actual_bitoffset)
        old_value = value if old_byte == new_byte else 1 - value
        reconstructed = bytearray(val)
        reconstructed[byte] = new_byte
        if bytes(reconstructed) != key.value or (self.version == (6,) and old_byte != new_byte):
            key.update(bytes(reconstructed))
        return old_value

    @staticmethod
    def _bitop(op: Callable[[Any, Any], Any], *keys: CommandItem) -> Any:
        value = keys[0].value
        ans = keys[0].value
        i = 1
        while i < len(keys):
            value = keys[i].value if keys[i].value is not None else b""
            ans = bytes(op(a, b) for a, b in zip(ans, value))
            i += 1
        return ans

    @command((bytes, Key()), (Key(bytes),))
    def bitop(self, op_name: bytes, dst: CommandItem, *keys: CommandItem) -> int:
        if len(keys) == 0:
            raise SimpleError(msgs.WRONG_ARGS_MSG6.format("bitop"))
        if casematch(op_name, b"and"):
            res = self._bitop(lambda a, b: a & b, *keys)
        elif casematch(op_name, b"or"):
            res = self._bitop(lambda a, b: a | b, *keys)
        elif casematch(op_name, b"xor"):
            res = self._bitop(lambda a, b: a ^ b, *keys)
        elif casematch(op_name, b"not"):
            if len(keys) != 1:
                raise SimpleError(msgs.BITOP_NOT_ONE_KEY_ONLY)
            val = keys[0].value
            res = bytes([((1 << 8) - 1 - val[i]) for i in range(len(val))])
        else:
            raise SimpleError(msgs.WRONG_ARGS_MSG6.format("bitop"))
        dst.value = res
        return len(dst.value)

    def _bitfield_get(self, key: CommandItem, encoding: BitfieldEncoding, offset: int) -> int:
        ans = 0
        for i in range(0, encoding.size):
            ans <<= 1
            if self.getbit(key, offset + i):
                ans += -1 if encoding.signed and i == 0 else 1
        return ans

    def _bitfield_set(
        self,
        key: CommandItem,
        encoding: BitfieldEncoding,
        offset: int,
        overflow: bytes,
        value: Optional[int] = None,
        incr: int = 0,
    ) -> Optional[int]:
        if encoding.signed:
            min_value = -(1 << (encoding.size - 1))
            max_value = (1 << (encoding.size - 1)) - 1
        else:
            min_value = 0
            max_value = (1 << encoding.size) - 1

        ans = self._bitfield_get(key, encoding, offset)
        new_value = ans if value is None else value
        if not encoding.signed:
            new_value &= (1 << 64) - 1  # force cast to uint64_t

        if overflow == b"FAIL" and not (min_value <= new_value + incr <= max_value):
            return None  # yes, failing in this context is not writing the value
        elif overflow == b"SAT":
            if new_value + incr > max_value:
                new_value, incr = max_value, 0
            # REDIS only checks for unsigned underflow on negative incr:
            if (encoding.signed or incr < 0) and new_value + incr < min_value:
                new_value, incr = min_value, 0

        new_value += incr
        new_value &= (1 << encoding.size) - 1
        # normalize signed number by changing the sign associated to higher bit:
        if encoding.signed and new_value > max_value:
            new_value -= 1 << encoding.size

        for i in range(0, encoding.size):
            bit = (new_value >> (encoding.size - i - 1)) & 1
            self.setbit(key, offset + i, bit)
        return new_value if value is None else ans

    @command(fixed=(Key(bytes),), repeat=(bytes,))
    def bitfield(self, key: CommandItem, *args: bytes) -> List[Optional[int]]:
        overflow = b"WRAP"
        results: List[Optional[int]] = []
        i = 0
        while i < len(args):
            if casematch(args[i], b"overflow") and i + 1 < len(args):
                overflow = args[i + 1].upper()
                if overflow not in (b"WRAP", b"SAT", b"FAIL"):
                    raise SimpleError(msgs.INVALID_OVERFLOW_TYPE)
                i += 2
            elif casematch(args[i], b"get") and i + 2 < len(args):
                encoding = BitfieldEncoding(args[i + 1])
                offset = BitOffset.decode(args[i + 2])
                results.append(self._bitfield_get(key, encoding, offset))
                i += 3
            elif casematch(args[i], b"set") and i + 3 < len(args):
                old_value = self._bitfield_set(
                    key=key,
                    encoding=BitfieldEncoding(args[i + 1]),
                    offset=BitOffset.decode(args[i + 2]),
                    value=Int.decode(args[i + 3]),
                    overflow=overflow,
                )
                results.append(old_value)
                i += 4
            elif casematch(args[i], b"incrby") and i + 3 < len(args):
                old_value = self._bitfield_set(
                    key=key,
                    encoding=BitfieldEncoding(args[i + 1]),
                    offset=BitOffset.decode(args[i + 2]),
                    incr=Int.decode(args[i + 3]),
                    overflow=overflow,
                )
                results.append(old_value)
                i += 4
            else:
                raise SimpleError(msgs.SYNTAX_ERROR_MSG)

        return results
