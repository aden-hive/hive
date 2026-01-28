import string
import struct
from collections import deque
from enum import Enum, IntEnum, IntFlag
from typing import Optional

class SizeLimitError(ValueError):
    """Raised when trying to (de-)serialise data exceeding D-Bus' size limit.

    This is currently only implemented for arrays, where the maximum size is
    64 MiB.
    """
    pass

class Endianness(Enum):
    little = 1
    big = 2

    def struct_code(self):
        return '<' if (self is Endianness.little) else '>'

    def dbus_code(self):
        return b'l' if (self is Endianness.little) else b'B'


endian_map = {b'l': Endianness.little, b'B': Endianness.big}


class MessageType(Enum):
    method_call = 1
    method_return = 2
    error = 3
    signal = 4


class MessageFlag(IntFlag):
    no_reply_expected = 1
    no_auto_start = 2
    allow_interactive_authorization = 4


class HeaderFields(IntEnum):
    path = 1
    interface = 2
    member = 3
    error_name = 4
    reply_serial = 5
    destination = 6
    sender = 7
    signature = 8
    unix_fds = 9


def padding(pos, step):
    pad = step - (pos % step)
    if pad == step:
        return 0
    return pad


class FixedType:
    def __init__(self, size, struct_code):
        self.size = self.alignment = size
        self.struct_code = struct_code

    def parse_data(self, buf, pos, endianness, fds=()):
        pos += padding(pos, self.alignment)
        code = endianness.struct_code() + self.struct_code
        val = struct.unpack(code, buf[pos:pos + self.size])[0]
        return val, pos + self.size

    def serialise(self, data, pos, endianness, fds=None):
        pad = b'\0' * padding(pos, self.alignment)
        code = endianness.struct_code() + self.struct_code
        return pad + struct.pack(code, data)

    def __repr__(self):
        return 'FixedType({!r}, {!r})'.format(self.size, self.struct_code)

    def __eq__(self, other):
        return (type(other) is FixedType) and (self.size == other.size) \
                and (self.struct_code == other.struct_code)


class Boolean(FixedType):
    def __init__(self):
        super().__init__(4, 'I')  # D-Bus booleans take 4 bytes

    def parse_data(self, buf, pos, endianness, fds=()):
        val, new_pos = super().parse_data(buf, pos, endianness)
        return bool(val), new_pos

    def __repr__(self):
        return 'Boolean()'

    def __eq__(self, other):
        return type(other) is Boolean


class FileDescriptor(FixedType):
    def __init__(self):
        super().__init__(4, 'I')

    def parse_data(self, buf, pos, endianness, fds=()):
        idx, new_pos = super().parse_data(buf, pos, endianness)
        return fds[idx], new_pos

    def serialise(self, data, pos, endianness, fds=None):
        if fds is None:
            raise RuntimeError("Sending FDs is not supported or not enabled")

        if hasattr(data, 'fileno'):
            data = data.fileno()
        if isinstance(data, bool) or not isinstance(data, int):
            raise TypeError("Cannot use {data!r} as file descriptor. Expected "
                            "an int or an object with fileno() method")

        if data < 0:
            raise ValueError(f"File descriptor can't be negative ({data})")

        fds.append(data)
        return super().serialise(len(fds) - 1, pos, endianness)

    def __repr__(self):
        return 'FileDescriptor()'

    def __eq__(self, other):
        return type(other) is FileDescriptor


simple_types = {
    'y': FixedType(1, 'B'),  # unsigned 8 bit
    'n': FixedType(2, 'h'),  # signed 16 bit
    'q': FixedType(2, 'H'),  # unsigned 16 bit
    'b': Boolean(),          # bool (32-bit)
    'i': FixedType(4, 'i'),  # signed 32-bit
    'u': FixedType(4, 'I'),  # unsigned 32-bit
    'x': FixedType(8, 'q'),  # signed 64-bit
    't': FixedType(8, 'Q'),  # unsigned 64-bit
    'd': FixedType(8, 'd'),  # double
    'h': FileDescriptor(),   # file descriptor (uint32 index in a separate list)
}


class StringType:
    def __init__(self, length_type):
        self.length_type = length_type

    @property
    def alignment(self):
        return self.length_type.size

    def parse_data(self, buf, pos, endianness, fds=()):
        length, pos = self.length_type.parse_data(buf, pos, endianness)
        end = pos + length
        val = buf[pos:end].decode('utf-8')
        assert buf[end:end + 1] == b'\0'
        return val, end + 1

    def check_data(self, data):
        if not isinstance(data, str):
            raise TypeError("Expected str, not {!r}".format(data))

    def serialise(self, data, pos, endianness, fds=None):
        self.check_data(data)
        encoded = data.encode('utf-8')
        len_data = self.length_type.serialise(len(encoded), pos, endianness)
        return len_data + encoded + b'\0'

    def __repr__(self):
        return 'StringType({!r})'.format(self.length_type)

    def __eq__(self, other):
        return (type(other) is StringType) \
               and (self.length_type == other.length_type)


class ObjectPathType(StringType):
    def __init__(self):
        super().__init__(simple_types['u'])

    def check_data(self, data):
        super().check_data(data)
        if not data.startswith('/'):
            raise ValueError(f"Object path ({data!r}) must start with /")
        if data.endswith('/') and len(data) > 1:
            raise ValueError(f"Object path ({data!r}) cannot end with /")
        if '//' in data:
            raise ValueError(f"Object path ({data!r}) cannot contain double /")
        valid_chars = string.ascii_letters + string.digits + '/_'
        if any(c not in valid_chars for c in data):
            raise ValueError(
                f"Object path ({data!r}) can only contain A-Z, a-z, 0-9, / and _"
            )


simple_types.update({
    's': StringType(simple_types['u']),  # String
    'o': ObjectPathType(),               # Object path
    'g': StringType(simple_types['y']),  # Signature
})


class Struct:
    alignment = 8

    def __init__(self, fields):
        if any(isinstance(f, DictEntry) for f in fields):
            raise TypeError("Found dict entry outside array")
        self.fields = fields

    def parse_data(self, buf, pos, endianness, fds=()):
        pos += padding(pos, 8)
        res = []
        for field in self.fields:
            v, pos = field.parse_data(buf, pos, endianness, fds=fds)
            res.append(v)
        return tuple(res), pos

    def serialise(self, data, pos, endianness, fds=None):
        if not isinstance(data, tuple):
            raise TypeError("Expected tuple, not {!r}".format(data))
        if len(data) != len(self.fields):
            raise ValueError("{} entries for {} fields".format(
                len(data), len(self.fields)
            ))
        pad = b'\0' * padding(pos, self.alignment)
        pos += len(pad)
        res_pieces = []
        for item, field in zip(data, self.fields):
            res_pieces.append(field.serialise(item, pos, endianness, fds=fds))
            pos += len(res_pieces[-1])
        return pad + b''.join(res_pieces)

    def __repr__(self):
        return "{}({!r})".format(type(self).__name__, self.fields)

    def __eq__(self, other):
        return (type(other) is type(self)) and (self.fields == other.fields)


class DictEntry(Struct):
    def __init__(self, fields):
        if len(fields) != 2:
            raise TypeError(
                "Dict entry must have 2 fields, not %d" % len(fields))
        if not isinstance(fields[0], (FixedType, StringType)):
            raise TypeError(
                "First field in dict entry must be simple type, not {}"
                .format(type(fields[0])))
        super().__init__(fields)

class Array:
    alignment = 4
    length_type = FixedType(4, 'I')

    def __init__(self, elt_type):
        self.elt_type = elt_type

    def parse_data(self, buf, pos, endianness, fds=()):
        # print('Array start', pos)
        length, pos = self.length_type.parse_data(buf, pos, endianness)
        pos += padding(pos, self.elt_type.alignment)
        end = pos + length
        if self.elt_type == simple_types['y']:  # Array of bytes
            return buf[pos:end], end

        res = []
        while pos < end:
            # print('Array elem', pos)
            v, pos = self.elt_type.parse_data(buf, pos, endianness, fds=fds)
            res.append(v)
        if isinstance(self.elt_type, DictEntry):
            # Convert list of 2-tuples to dict
            res = dict(res)
        return res, pos

    def serialise(self, data, pos, endianness, fds=None):
        data_is_bytes = False
        if isinstance(self.elt_type, DictEntry) and isinstance(data, dict):
            data = data.items()
        elif (self.elt_type == simple_types['y']) and isinstance(data, bytes):
            data_is_bytes = True
        elif not isinstance(data, list):
            raise TypeError("Not suitable for array: {!r}".format(data))

        # Fail fast if we know in advance that the data is too big:
        if isinstance(self.elt_type, FixedType):
            if (self.elt_type.size * len(data)) > 2**26:
                raise SizeLimitError("Array size exceeds 64 MiB limit")

        pad1 = padding(pos, self.alignment)
        pos_after_length = pos + pad1 + 4
        pad2 = padding(pos_after_length, self.elt_type.alignment)

        if data_is_bytes:
            buf = data
        else:
            data_pos = pos_after_length + pad2
            limit_pos = data_pos + 2 ** 26
            chunks = []
            for item in data:
                chunks.append(self.elt_type.serialise(
                    item, data_pos, endianness, fds=fds
                ))
                data_pos += len(chunks[-1])
                if data_pos > limit_pos:
                    raise SizeLimitError("Array size exceeds 64 MiB limit")
            buf = b''.join(chunks)

        len_data = self.length_type.serialise(len(buf), pos+pad1, endianness)
        # print('Array ser: pad1={!r}, len_data={!r}, pad2={!r}, buf={!r}'.format(
        #       pad1, len_data, pad2, buf))
        return (b'\0' * pad1) + len_data + (b'\0' * pad2) + buf

    def __repr__(self):
        return 'Array({!r})'.format(self.elt_type)

    def __eq__(self, other):
        return (type(other) is Array) and (self.elt_type == other.elt_type)


class Variant:
    alignment = 1

    def parse_data(self, buf, pos, endianness, fds=()):
        # print('variant', pos)
        sig, pos = simple_types['g'].parse_data(buf, pos, endianness)
        # print('variant sig:', repr(sig), pos)
        valtype = parse_signature(list(sig))
        val, pos = valtype.parse_data(buf, pos, endianness, fds=fds)
        # print('variant done', (sig, val), pos)
        return (sig, val), pos

    def serialise(self, data, pos, endianness, fds=None):
        sig, data = data
        valtype = parse_signature(list(sig))
        sig_buf = simple_types['g'].serialise(sig, pos, endianness)
        return sig_buf + valtype.serialise(
            data, pos + len(sig_buf), endianness, fds=fds
        )

    def __repr__(self):
        return 'Variant()'

    def __eq__(self, other):
        return type(other) is Variant

def parse_signature(sig):
    """Parse a symbolic signature into objects.
    """
    # Based on http://norvig.com/lispy.html
    token = sig.pop(0)
    if token == 'a':
        return Array(parse_signature(sig))
    if token == 'v':
        return Variant()
    elif token == '(':
        fields = []
        while sig[0] != ')':
            fields.append(parse_signature(sig))
        sig.pop(0)  # )
        return Struct(fields)
    elif token == '{':
        de = []
        while sig[0] != '}':
            de.append(parse_signature(sig))
        sig.pop(0)  # }
        return DictEntry(de)
    elif token in ')}':
        raise ValueError('Unexpected end of struct')
    else:
        return simple_types[token]


def calc_msg_size(buf):
    endian, = struct.unpack('c', buf[:1])
    endian = endian_map[endian]
    body_length, = struct.unpack(endian.struct_code() + 'I', buf[4:8])
    fields_array_len, = struct.unpack(endian.struct_code() + 'I', buf[12:16])
    header_len = 16 + fields_array_len
    return header_len + padding(header_len, 8) + body_length


_header_fields_type = Array(Struct([simple_types['y'], Variant()]))


def parse_header_fields(buf, endianness):
    l, pos = _header_fields_type.parse_data(buf, 12, endianness)
    return {HeaderFields(k): v[1] for (k, v) in l}, pos


header_field_codes = {
    1: 'o',
    2: 's',
    3: 's',
    4: 's',
    5: 'u',
    6: 's',
    7: 's',
    8: 'g',
    9: 'u',
}


def serialise_header_fields(d, endianness):
    l = [(i.value, (header_field_codes[i], v)) for (i, v) in sorted(d.items())]
    return _header_fields_type.serialise(l, 12, endianness)


class Header:
    def __init__(self, endianness, message_type, flags, protocol_version,
                 body_length, serial, fields):
        """A D-Bus message header

        It's not normally necessary to construct this directly: use higher level
        functions and methods instead.
        """
        self.endianness = endianness
        self.message_type = MessageType(message_type)
        self.flags = MessageFlag(flags)
        self.protocol_version = protocol_version
        self.body_length = body_length
        self.serial = serial
        self.fields = fields

    def __repr__(self):
        return 'Header({!r}, {!r}, {!r}, {!r}, {!r}, {!r}, fields={!r})'.format(
            self.endianness, self.message_type, self.flags,
            self.protocol_version, self.body_length, self.serial, self.fields)

    def serialise(self, serial=None):
        s = self.endianness.struct_code() + 'cBBBII'
        if serial is None:
            serial = self.serial
        return struct.pack(s, self.endianness.dbus_code(),
                           self.message_type.value, self.flags,
                           self.protocol_version,
                           self.body_length, serial) \
                + serialise_header_fields(self.fields, self.endianness)

    @classmethod
    def from_buffer(cls, buf):
        endian, msgtype, flags, pv = struct.unpack('cBBB', buf[:4])
        endian = endian_map[endian]
        bodylen, serial = struct.unpack(endian.struct_code() + 'II', buf[4:12])
        fields, pos = parse_header_fields(buf, endian)
        return cls(endian, msgtype, flags, pv, bodylen, serial, fields), pos


class Message:
    """Object representing a DBus message.

    It's not normally necessary to construct this directly: use higher level
    functions and methods instead.
    """
    def __init__(self, header, body):
        self.header = header
        self.body = body

    def __repr__(self):
        return "{}({!r}, {!r})".format(type(self).__name__, self.header, self.body)

    @classmethod
    def from_buffer(cls, buf: bytes, fds=()) -> 'Message':
        header, pos = Header.from_buffer(buf)
        n_fds = header.fields.get(HeaderFields.unix_fds, 0)
        if n_fds > len(fds):
            raise ValueError(
                f"Message expects {n_fds} FDs, but only {len(fds)} were received"
            )
        fds = fds[:n_fds]
        body = ()
        if HeaderFields.signature in header.fields:
            sig = header.fields[HeaderFields.signature]
            body_type = parse_signature(list('(%s)' % sig))
            body = body_type.parse_data(buf, pos, header.endianness, fds=fds)[0]
        return Message(header, body)

    def serialise(self, serial=None, fds=None) -> bytes:
        """Convert this message to bytes.

        Specifying *serial* overrides the ``msg.header.serial`` field, so a
        connection can use its own serial number without modifying the message.

        If file-descriptor support is in use, *fds* should be a
        :class:`array.array` object with type ``'i'``. Any file descriptors in
        the message will be added to the array. If the message contains FDs,
        it can't be serialised without this array.
        """
        endian = self.header.endianness

        if HeaderFields.signature in self.header.fields:
            sig = self.header.fields[HeaderFields.signature]
            body_type = parse_signature(list('(%s)' % sig))
            body_buf = body_type.serialise(self.body, 0, endian, fds=fds)
        else:
            body_buf = b''

        self.header.body_length = len(body_buf)
        if fds:
            self.header.fields[HeaderFields.unix_fds] = len(fds)

        header_buf = self.header.serialise(serial=serial)
        pad  = b'\0' * padding(len(header_buf), 8)
        return header_buf + pad + body_buf


class Parser:
    """Parse DBus messages from a stream of incoming data.
    """
    def __init__(self):
        self.buf = BufferPipe()
        self.fds = []
        self.next_msg_size = None

    def add_data(self, data: bytes, fds=()):
        """Provide newly received data to the parser"""
        self.buf.write(data)
        self.fds.extend(fds)

    def feed(self, data):
        """Feed the parser newly read data.

        Returns a list of messages completed by the new data.
        """
        self.add_data(data)
        return list(iter(self.get_next_message, None))

    def bytes_desired(self):
        """How many bytes can be received without going beyond the next message?

        This is only used with file-descriptor passing, so we don't get too many
        FDs in a single recvmsg call.
        """
        got = self.buf.bytes_buffered
        if got < 16:  # The first 16 bytes tell us the message size
            return 16 - got

        if self.next_msg_size is None:
            self.next_msg_size = calc_msg_size(self.buf.peek(16))
        return self.next_msg_size - got

    def get_next_message(self) -> Optional[Message]:
        """Parse one message, if there is enough data.

        Returns None if it doesn't have a complete message.
        """
        if self.next_msg_size is None:
            if self.buf.bytes_buffered >= 16:
                self.next_msg_size = calc_msg_size(self.buf.peek(16))
        nms = self.next_msg_size
        if (nms is not None) and self.buf.bytes_buffered >= nms:
            raw_msg = self.buf.read(nms)
            msg = Message.from_buffer(raw_msg, fds=self.fds)
            self.next_msg_size = None
            fds_consumed = msg.header.fields.get(HeaderFields.unix_fds, 0)
            self.fds = self.fds[fds_consumed:]
            return msg


class BufferPipe:
    """A place to store received data until we can parse a complete message

    The main difference from io.BytesIO is that read & write operate at
    opposite ends, like a pipe.
    """
    def __init__(self):
        self.chunks = deque()
        self.bytes_buffered = 0

    def write(self, b: bytes):
        self.chunks.append(b)
        self.bytes_buffered += len(b)

    def _peek_iter(self, nbytes: int):
        assert nbytes <= self.bytes_buffered
        for chunk in self.chunks:
            chunk = chunk[:nbytes]
            nbytes -= len(chunk)
            yield chunk
            if nbytes <= 0:
                break

    def peek(self, nbytes: int) -> bytes:
        """Get exactly nbytes bytes from the front without removing them"""
        return b''.join(self._peek_iter(nbytes))

    def _read_iter(self, nbytes: int):
        assert nbytes <= self.bytes_buffered
        while True:
            chunk = self.chunks.popleft()
            self.bytes_buffered -= len(chunk)
            if nbytes <= len(chunk):
                break
            nbytes -= len(chunk)
            yield chunk

        # Final chunk
        chunk, rem = chunk[:nbytes], chunk[nbytes:]
        if rem:
            self.chunks.appendleft(rem)
            self.bytes_buffered += len(rem)
        yield chunk

    def read(self, nbytes: int) -> bytes:
        """Take & return exactly nbytes bytes from the front"""
        return b''.join(self._read_iter(nbytes))
