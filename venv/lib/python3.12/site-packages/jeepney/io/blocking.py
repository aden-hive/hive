"""Synchronous IO wrappers around jeepney
"""
import array
from collections import deque
from errno import ECONNRESET
import functools
from itertools import count
import os
from selectors import DefaultSelector, EVENT_READ
import socket
import time
from typing import Optional

from jeepney import Parser, Message, MessageType, HeaderFields
from jeepney.auth import Authenticator, BEGIN
from jeepney.bus import get_bus
from jeepney.fds import FileDescriptor, fds_buf_size
from jeepney.wrappers import ProxyBase, unwrap_msg
from jeepney.bus_messages import message_bus
from .common import MessageFilters, FilterHandle, check_replyable

__all__ = [
    'open_dbus_connection',
    'DBusConnection',
    'Proxy',
]


class _Future:
    def __init__(self):
        self._result = None

    def done(self):
        return bool(self._result)

    def set_exception(self, exception):
        self._result = (False, exception)

    def set_result(self, result): 
        self._result = (True, result)

    def result(self):
        success, value = self._result
        if success:
            return value
        raise value


def timeout_to_deadline(timeout):
    if timeout is not None:
        return time.monotonic() + timeout
    return None

def deadline_to_timeout(deadline):
    if deadline is not None:
        return max(deadline - time.monotonic(), 0.)
    return None


class DBusConnectionBase:
    """Connection machinery shared by this module and threading"""
    def __init__(self, sock: socket.socket, enable_fds=False):
        self.sock = sock
        self.enable_fds = enable_fds
        self.parser = Parser()
        self.outgoing_serial = count(start=1)
        self.selector = DefaultSelector()
        self.select_key = self.selector.register(sock, EVENT_READ)
        self.unique_name = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _serialise(self, message: Message, serial) -> (bytes, Optional[array.array]):
        if serial is None:
            serial = next(self.outgoing_serial)
        fds = array.array('i') if self.enable_fds else None
        data = message.serialise(serial=serial, fds=fds)
        return data, fds

    def _send_with_fds(self, data, fds):
        bytes_sent = self.sock.sendmsg(
            [data], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, fds)]
        )
        # If sendmsg succeeds, I think ancillary data has been sent atomically?
        # So now we just need to send any leftover normal data.
        if bytes_sent < len(data):
            self.sock.sendall(data[bytes_sent:])

    def _receive(self, deadline):
        while True:
            msg = self.parser.get_next_message()
            if msg is not None:
                return msg

            b, fds = self._read_some_data(timeout=deadline_to_timeout(deadline))
            self.parser.add_data(b, fds=fds)

    def _read_some_data(self, timeout=None):
        for key, ev in self.selector.select(timeout):
            if key == self.select_key:
                if self.enable_fds:
                    return self._read_with_fds()
                else:
                    return unwrap_read(self.sock.recv(4096)), []

        raise TimeoutError

    def _read_with_fds(self):
        nbytes = self.parser.bytes_desired()
        data, ancdata, flags, _ = self.sock.recvmsg(nbytes, fds_buf_size())
        if flags & getattr(socket, 'MSG_CTRUNC', 0):
            self.close()
            raise RuntimeError("Unable to receive all file descriptors")
        return unwrap_read(data), FileDescriptor.from_ancdata(ancdata)

    def close(self):
        """Close the connection"""
        self.selector.close()
        self.sock.close()


class DBusConnection(DBusConnectionBase):
    def __init__(self, sock: socket.socket, enable_fds=False):
        super().__init__(sock, enable_fds)

        # Message routing machinery
        self._filters = MessageFilters()

        # Say Hello, get our unique name
        self.bus_proxy = Proxy(message_bus, self)
        hello_reply = self.bus_proxy.Hello()
        self.unique_name = hello_reply[0]

    def send(self, message: Message, serial=None):
        """Serialise and send a :class:`~.Message` object"""
        data, fds = self._serialise(message, serial)
        if fds:
            self._send_with_fds(data, fds)
        else:
            self.sock.sendall(data)

    send_message = send  # Backwards compatibility

    def receive(self, *, timeout=None) -> Message:
        """Return the next available message from the connection

        If the data is ready, this will return immediately, even if timeout<=0.
        Otherwise, it will wait for up to timeout seconds, or indefinitely if
        timeout is None. If no message comes in time, it raises TimeoutError.
        """
        return self._receive(timeout_to_deadline(timeout))

    def recv_messages(self, *, timeout=None):
        """Receive one message and apply filters

        See :meth:`filter`. Returns nothing.
        """
        msg = self.receive(timeout=timeout)
        for filter in self._filters.matches(msg):
            filter.queue.append(msg)

    def send_and_get_reply(self, message, *, timeout=None):
        """Send a message, wait for the reply and return it

        Filters are applied to other messages received before the reply -
        see :meth:`add_filter`.
        """
        check_replyable(message)
        deadline = timeout_to_deadline(timeout)

        serial = next(self.outgoing_serial)
        self.send_message(message, serial=serial)
        while True:
            msg_in = self.receive(timeout=deadline_to_timeout(deadline))
            reply_to = msg_in.header.fields.get(HeaderFields.reply_serial, -1)
            if reply_to == serial:
                return msg_in

            # Not the reply
            for filter in self._filters.matches(msg_in):
                filter.queue.append(msg_in)

    def filter(self, rule, *, queue: Optional[deque] =None, bufsize=1):
        """Create a filter for incoming messages

        Usage::

            with conn.filter(rule) as matches:
                # matches is a deque containing matched messages
                matching_msg = conn.recv_until_filtered(matches)

        :param jeepney.MatchRule rule: Catch messages matching this rule
        :param collections.deque queue: Matched messages will be added to this
        :param int bufsize: If no deque is passed in, create one with this size
        """
        if queue is None:
            queue = deque(maxlen=bufsize)
        return FilterHandle(self._filters, rule, queue)

    def recv_until_filtered(self, queue, *, timeout=None) -> Message:
        """Process incoming messages until one is filtered into queue

        Pops the message from queue and returns it, or raises TimeoutError if
        the optional timeout expires. Without a timeout, this is equivalent to::

            while len(queue) == 0:
                conn.recv_messages()
            return queue.popleft()

        In the other I/O modules, there is no need for this, because messages
        are placed in queues by a separate task.

        :param collections.deque queue: A deque connected by :meth:`filter`
        :param float timeout: Maximum time to wait in seconds
        """
        deadline = timeout_to_deadline(timeout)
        while len(queue) == 0:
            self.recv_messages(timeout=deadline_to_timeout(deadline))
        return queue.popleft()


class Proxy(ProxyBase):
    """A blocking proxy for calling D-Bus methods

    You can call methods on the proxy object, such as ``bus_proxy.Hello()``
    to make a method call over D-Bus and wait for a reply. It will either
    return a tuple of returned data, or raise :exc:`.DBusErrorResponse`.
    The methods available are defined by the message generator you wrap.

    You can set a time limit on a call by passing ``_timeout=`` in the method
    call, or set a default when creating the proxy. The ``_timeout`` argument
    is not passed to the message generator.
    All timeouts are in seconds, and :exc:`TimeoutErrror` is raised if it
    expires before a reply arrives.

    :param msggen: A message generator object
    :param ~blocking.DBusConnection connection: Connection to send and receive messages
    :param float timeout: Default seconds to wait for a reply, or None for no limit
    """
    def __init__(self, msggen, connection, *, timeout=None):
        super().__init__(msggen)
        self._connection = connection
        self._timeout = timeout

    def __repr__(self):
        extra = '' if (self._timeout is None) else f', timeout={self._timeout}'
        return f"Proxy({self._msggen}, {self._connection}{extra})"

    def _method_call(self, make_msg):
        @functools.wraps(make_msg)
        def inner(*args, **kwargs):
            timeout = kwargs.pop('_timeout', self._timeout)
            msg = make_msg(*args, **kwargs)
            assert msg.header.message_type is MessageType.method_call
            return unwrap_msg(self._connection.send_and_get_reply(
                msg, timeout=timeout
            ))

        return inner


def unwrap_read(b):
    """Raise ConnectionResetError from an empty read.

    Sometimes the socket raises an error itself, sometimes it gives no data.
    I haven't worked out when it behaves each way.
    """
    if not b:
        raise ConnectionResetError(ECONNRESET, os.strerror(ECONNRESET))
    return b


def prep_socket(addr, enable_fds=False, timeout=2.0) -> socket.socket:
    """Create a socket and authenticate ready to send D-Bus messages"""
    sock = socket.socket(family=socket.AF_UNIX)

    # To impose the overall auth timeout, we'll update the timeout on the socket
    # before each send/receive. This is ugly, but we can't use the socket for
    # anything else until this has succeeded, so this should be safe.
    deadline = timeout_to_deadline(timeout)
    def with_sock_deadline(meth, *args):
        sock.settimeout(deadline_to_timeout(deadline))
        return meth(*args)

    try:
        with_sock_deadline(sock.connect, addr)
        authr = Authenticator(enable_fds=enable_fds, inc_null_byte=False)
        if hasattr(socket, 'SCM_CREDS'):
            # BSD: send credentials message to authenticate (kernel fills in data)
            sock.sendmsg([b'\0'], [(socket.SOL_SOCKET, socket.SCM_CREDS, bytes(512))])
        else:
            # Linux: no ancillary data needed, bus checks with SO_PEERCRED
            sock.send(b'\0')
        for req_data in authr:
            with_sock_deadline(sock.sendall, req_data)
            authr.feed(unwrap_read(with_sock_deadline(sock.recv, 1024)))
        with_sock_deadline(sock.sendall, BEGIN)
    except socket.timeout as e:
        sock.close()
        raise TimeoutError(f"Did not authenticate in {timeout} seconds") from e
    except:
        sock.close()
        raise

    sock.settimeout(None)  # Put the socket back in blocking mode
    return sock


def open_dbus_connection(
        bus='SESSION', enable_fds=False, auth_timeout=1.,
) -> DBusConnection:
    """Connect to a D-Bus message bus

    Pass ``enable_fds=True`` to allow sending & receiving file descriptors.
    An error will be raised if the bus does not allow this. For simplicity,
    it's advisable to leave this disabled unless you need it.

    D-Bus has an authentication step before sending or receiving messages.
    This takes < 1 ms in normal operation, but there is a timeout so that client
    code won't get stuck if the server doesn't reply. *auth_timeout* configures
    this timeout in seconds.
    """
    bus_addr = get_bus(bus)
    sock = prep_socket(bus_addr, enable_fds, timeout=auth_timeout)

    conn = DBusConnection(sock, enable_fds)
    return conn


if __name__ == '__main__':
    conn = open_dbus_connection()
    print("Unique name:", conn.unique_name)
