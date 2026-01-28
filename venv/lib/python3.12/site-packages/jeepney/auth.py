from binascii import hexlify
from enum import Enum
import os
from typing import Optional

def make_auth_external() -> bytes:
    """Prepare an AUTH command line with the current effective user ID.

    This is the preferred authentication method for typical D-Bus connections
    over a Unix domain socket.
    """
    hex_uid = hexlify(str(os.geteuid()).encode('ascii'))
    return b'AUTH EXTERNAL %b\r\n' % hex_uid

def make_auth_anonymous() -> bytes:
    """Format an AUTH command line for the ANONYMOUS mechanism

    Jeepney's higher-level wrappers don't currently use this mechanism,
    but third-party code may choose to.

    See <https://tools.ietf.org/html/rfc4505> for details.
    """
    from . import __version__
    trace = hexlify(('Jeepney %s' % __version__).encode('ascii'))
    return b'AUTH ANONYMOUS %s\r\n' % trace

BEGIN = b'BEGIN\r\n'
NEGOTIATE_UNIX_FD = b'NEGOTIATE_UNIX_FD\r\n'

class ClientState(Enum):
    # States from the D-Bus spec (plus 'Success'). Not all used in Jeepney.
    WaitingForData = 1
    WaitingForOk = 2
    WaitingForReject = 3
    WaitingForAgreeUnixFD = 4
    Success = 5

class AuthenticationError(ValueError):
    """Raised when DBus authentication fails"""
    def __init__(self, data, msg="Authentication failed"):
        self.msg = msg
        self.data = data

    def __str__(self):
        return f"{self.msg}. Bus sent: {self.data!r}"

class FDNegotiationError(AuthenticationError):
    """Raised when file descriptor support is requested but not available"""
    def __init__(self, data):
        super().__init__(data, msg="File descriptor support not available")


class Authenticator:
    """Process data for the SASL authentication conversation

    If enable_fds is True, this includes negotiating support for passing
    file descriptors. If inc_null_byte is True, sends the '\0' byte
    at the beginning of the negotiations, which was the past behavior,
    but which prevents sending the SCM_CREDS ancillary data over the socket,
    breaking authentication on *BSD; the caller should rather send that
    null byte and ancillary data and pass inc_null_byte=False to prevent
    it being done here.
    """
    def __init__(self, enable_fds=False, inc_null_byte=True):
        self.enable_fds = enable_fds
        self.buffer = bytearray()
        if inc_null_byte:
            self._to_send = b'\0' + make_auth_external()
        else:
            self._to_send = make_auth_external()
        self.state = ClientState.WaitingForOk
        self.error = None

    @property
    def authenticated(self):
        return self.state is ClientState.Success

    def __iter__(self):
        return iter(self.data_to_send, None)

    def data_to_send(self) -> Optional[bytes]:
        """Get a line of data to send to the server

        The data returned should be sent before waiting to receive data.
        Returns empty bytes if waiting for more data from the server, and None
        if authentication is finished (success or error).

        Iterating over the Authenticator object will also yield these lines;
        :meth:`feed` should be called with received data inside the loop.
        """
        if self.authenticated or self.error:
            return None
        self._to_send, to_send = b'', self._to_send
        return to_send

    def process_line(self, line):
        if self.state is ClientState.WaitingForOk:
            if line.startswith(b'OK '):
                if self.enable_fds:
                    return NEGOTIATE_UNIX_FD, ClientState.WaitingForAgreeUnixFD
                else:
                    return BEGIN, ClientState.Success
            # We only support EXTERNAL authentication, but if we allow others,
            # 'REJECTED <mechs>' would tell us to try another one.

        elif self.state is ClientState.WaitingForAgreeUnixFD:
            if line.startswith(b'AGREE_UNIX_FD'):
                return BEGIN, ClientState.Success
            # The protocol allows us to continue if FD passing is rejected,
            # but Jeepney assumes that if you enable FD support you need it,
            # so we fail rather
            self.error = line
            raise FDNegotiationError(line)

        self.error = line
        raise AuthenticationError(line)

    def feed(self, data: bytes):
        """Process received data

        Raises AuthenticationError if the incoming data is not as expected for
        successful authentication. The connection should then be abandoned.
        """
        self.buffer += data
        if b'\r\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\r\n', 1)
            if self.buffer:
                # We only expect one line before we reply
                raise AuthenticationError(self.buffer, "Unexpected data received")

            self._to_send, self.state = self.process_line(line)

        # Avoid consuming lots of memory if the server is not sending what we
        # expect. There doesn't appear to be a specified maximum line length,
        # but 8192 bytes leaves a sizeable margin over all the examples in the
        # spec (all < 100 bytes per line).
        elif len(self.buffer) > 8192:
            raise AuthenticationError(
                self.buffer, "Too much data received without line ending"
            )


# Old name (behaviour on errors has changed, but should work for standard case)
SASLParser = Authenticator
