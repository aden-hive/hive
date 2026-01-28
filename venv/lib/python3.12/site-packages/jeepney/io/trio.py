import array
import errno
import logging
import socket
from contextlib import asynccontextmanager, contextmanager
from itertools import count
from typing import Optional

from outcome import Value, Error
import trio
from trio.abc import Channel

from jeepney.auth import Authenticator, BEGIN
from jeepney.bus import get_bus
from jeepney.fds import FileDescriptor, fds_buf_size
from jeepney.low_level import Parser, MessageType, Message
from jeepney.wrappers import ProxyBase, unwrap_msg
from jeepney.bus_messages import message_bus
from .common import (
    MessageFilters, FilterHandle, ReplyMatcher, RouterClosed, check_replyable,
)

log = logging.getLogger(__name__)

__all__ = [
    'open_dbus_connection',
    'open_dbus_router',
    'Proxy',
]


# The function below is copied from trio, which is under the MIT license:

# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
@contextmanager
def _translate_socket_errors_to_stream_errors():
    try:
        yield
    except OSError as exc:
        if exc.errno in {errno.EBADF, errno.ENOTSOCK}:
            # EBADF on Unix, ENOTSOCK on Windows
            raise trio.ClosedResourceError("this socket was already closed") from None
        else:
            raise trio.BrokenResourceError(
                "socket connection broken: {}".format(exc)
            ) from exc



class DBusConnection(Channel):
    """A plain D-Bus connection with no matching of replies.

    This doesn't run any separate tasks: sending and receiving are done in
    the task that calls those methods. It's suitable for implementing servers:
    several worker tasks can receive requests and send replies.
    For a typical client pattern, see :class:`DBusRouter`.

    Implements trio's channel interface for Message objects.
    """
    def __init__(self, socket, enable_fds=False):
        self.socket = socket
        self.enable_fds = enable_fds
        self.parser = Parser()
        self.outgoing_serial = count(start=1)
        self.unique_name = None
        self.send_lock = trio.Lock()
        self.recv_lock = trio.Lock()
        self._leftover_to_send = None  # type: Optional[memoryview]

    async def send(self, message: Message, *, serial=None):
        """Serialise and send a :class:`~.Message` object"""
        async with self.send_lock:
            if serial is None:
                serial = next(self.outgoing_serial)
            fds = array.array('i') if self.enable_fds else None
            data = message.serialise(serial, fds=fds)
            await self._send_data(data, fds)

    # _send_data is copied & modified from trio's SocketStream.send_all() .
    # See above for the MIT license.
    async def _send_data(self, data: bytes, fds):
        if self.socket.did_shutdown_SHUT_WR:
            raise trio.ClosedResourceError("can't send data after sending EOF")

        with _translate_socket_errors_to_stream_errors():
            if self._leftover_to_send:
                # A previous message was partly sent - finish sending it now.
                await self._send_remainder(self._leftover_to_send)

            with memoryview(data) as data:
                if fds:
                    sent = await self.socket.sendmsg([data], [(
                        trio.socket.SOL_SOCKET, trio.socket.SCM_RIGHTS, fds
                    )])
                else:
                    sent = await self.socket.send(data)

                await self._send_remainder(data, sent)

    async def _send_remainder(self, data: memoryview, already_sent=0):
        try:
            while already_sent < len(data):
                with data[already_sent:] as remaining:
                    sent = await self.socket.send(remaining)
                already_sent += sent
            self._leftover_to_send = None
        except trio.Cancelled:
            # Sending cancelled mid-message. Keep track of the remaining data
            # so it can be sent before the next message, otherwise the next
            # message won't be recognised.
            self._leftover_to_send = data[already_sent:]
            raise

    async def receive(self) -> Message:
        """Return the next available message from the connection"""
        async with self.recv_lock:
            while True:
                msg = self.parser.get_next_message()
                if msg is not None:
                    return msg

                # Once data is read, it must be given to the parser with no
                # checkpoints (where the task could be cancelled).
                b, fds = await self._read_data()
                if not b:
                    raise trio.EndOfChannel("Socket closed at the other end")
                self.parser.add_data(b, fds)

    async def _read_data(self):
        if self.enable_fds:
            nbytes = self.parser.bytes_desired()
            with _translate_socket_errors_to_stream_errors():
                data, ancdata, flags, _ = await self.socket.recvmsg(
                    nbytes, fds_buf_size()
                )
            if flags & getattr(trio.socket, 'MSG_CTRUNC', 0):
                self._close()
                raise RuntimeError("Unable to receive all file descriptors")
            return data, FileDescriptor.from_ancdata(ancdata)

        else:  # not self.enable_fds
            with _translate_socket_errors_to_stream_errors():
                data = await self.socket.recv(4096)
            return data, []

    def _close(self):
        self.socket.close()
        self._leftover_to_send = None

    # Our closing is currently sync, but AsyncResource objects must have aclose
    async def aclose(self):
        """Close the D-Bus connection"""
        self._close()

    @asynccontextmanager
    async def router(self):
        """Temporarily wrap this connection as a :class:`DBusRouter`

        To be used like::

            async with conn.router() as req:
                reply = await req.send_and_get_reply(msg)

        While the router is running, you shouldn't use :meth:`receive`.
        Once the router is closed, you can use the plain connection again.
        """
        async with trio.open_nursery() as nursery:
            router = DBusRouter(self)
            await router.start(nursery)
            try:
                yield router
            finally:
                await router.aclose()


async def open_dbus_connection(bus='SESSION', *, enable_fds=False) -> DBusConnection:
    """Open a plain D-Bus connection

    :return: :class:`DBusConnection`
    """
    bus_addr = get_bus(bus)
    sock : trio.SocketStream = await trio.open_unix_socket(bus_addr)

    # Authentication
    authr = Authenticator(enable_fds=enable_fds, inc_null_byte=False)
    if hasattr(socket, 'SCM_CREDS'):
        # BSD: send credentials message to authenticate (kernel fills in data)
        await sock.socket.sendmsg(
            [b'\0'], [(socket.SOL_SOCKET, socket.SCM_CREDS, bytes(512))]
        )
    else:
        # Linux: no ancillary data needed, bus checks with SO_PEERCRED
        await sock.send_all(b'\0')
    for req_data in authr:
        await sock.send_all(req_data)
        authr.feed(await sock.receive_some())
    await sock.send_all(BEGIN)

    conn = DBusConnection(sock.socket, enable_fds=enable_fds)

    # Say *Hello* to the message bus - this must be the first message, and the
    # reply gives us our unique name.
    async with conn.router() as router:
        reply = await router.send_and_get_reply(message_bus.Hello())
        conn.unique_name = reply.body[0]

    return conn


class TrioFilterHandle(FilterHandle):
    def __init__(self, filters: MessageFilters, rule, send_chn, recv_chn):
        super().__init__(filters, rule, recv_chn)
        self.send_channel = send_chn

    @property
    def receive_channel(self):
        return self.queue

    async def aclose(self):
        self.close()
        await self.send_channel.aclose()

    async def __aenter__(self):
        return self.queue

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()


class Future:
    """A very simple Future for trio based on `trio.Event`."""
    def __init__(self):
        self._outcome = None
        self._event = trio.Event()

    def set_result(self, result):
        self._outcome = Value(result)
        self._event.set()

    def set_exception(self, exc):
        self._outcome = Error(exc)
        self._event.set()

    async def get(self):
        await self._event.wait()
        return self._outcome.unwrap()


class DBusRouter:
    """A client D-Bus connection which can wait for replies.

    This runs a separate receiver task and dispatches received messages.
    """
    _nursery_mgr = None
    _rcv_cancel_scope = None

    def __init__(self, conn: DBusConnection):
        self._conn = conn
        self._replies = ReplyMatcher()
        self._filters = MessageFilters()

    @property
    def unique_name(self):
        return self._conn.unique_name

    async def send(self, message, *, serial=None):
        """Send a message, don't wait for a reply
        """
        await self._conn.send(message, serial=serial)

    async def send_and_get_reply(self, message) -> Message:
        """Send a method call message and wait for the reply

        Returns the reply message (method return or error message type).
        """
        check_replyable(message)
        if self._rcv_cancel_scope is None:
            raise RouterClosed("This DBusRouter has stopped")

        serial = next(self._conn.outgoing_serial)

        with self._replies.catch(serial, Future()) as reply_fut:
            await self.send(message, serial=serial)
            return (await reply_fut.get())

    def filter(self, rule, *, channel: Optional[trio.MemorySendChannel]=None, bufsize=1):
        """Create a filter for incoming messages

        Usage::

            async with router.filter(rule) as receive_channel:
                matching_msg = await receive_channel.receive()

            # OR:
            send_chan, recv_chan = trio.open_memory_channel(1)
            async with router.filter(rule, channel=send_chan):
                matching_msg = await recv_chan.receive()

        If the channel fills up,
        The sending end of the channel is closed when leaving the ``async with``
        block, whether or not it was passed in.

        :param jeepney.MatchRule rule: Catch messages matching this rule
        :param trio.MemorySendChannel channel: Send matching messages here
        :param int bufsize: If no channel is passed in, create one with this size
        """
        if channel is None:
            channel, recv_channel = trio.open_memory_channel(bufsize)
        else:
            recv_channel = None
        return TrioFilterHandle(self._filters, rule, channel, recv_channel)

    # Task management -------------------------------------------

    async def start(self, nursery: trio.Nursery):
        if self._rcv_cancel_scope is not None:
            raise RuntimeError("DBusRouter receiver task is already running")
        self._rcv_cancel_scope = await nursery.start(self._receiver)

    async def aclose(self):
        """Stop the sender & receiver tasks"""
        # It doesn't matter if we receive a partial message - the connection
        # should ensure that whatever is received is fed to the parser.
        if self._rcv_cancel_scope is not None:
            self._rcv_cancel_scope.cancel()
            self._rcv_cancel_scope = None

        # Ensure trio checkpoint
        await trio.sleep(0)

    # Code to run in receiver task ------------------------------------

    def _dispatch(self, msg: Message):
        """Handle one received message"""
        if self._replies.dispatch(msg):
            return

        for filter in self._filters.matches(msg):
            try:
                filter.send_channel.send_nowait(msg)
            except trio.WouldBlock:
                pass

    async def _receiver(self, task_status=trio.TASK_STATUS_IGNORED):
        """Receiver loop - runs in a separate task"""
        with trio.CancelScope() as cscope:
            self.is_running = True
            task_status.started(cscope)
            try:
                while True:
                    msg = await self._conn.receive()
                    self._dispatch(msg)
            finally:
                self.is_running = False
                # Send errors to any tasks still waiting for a message.
                self._replies.drop_all()

                # Closing a memory channel can't block, but it only has an
                # async close method, so we need to shield it from cancellation.
                with trio.move_on_after(3) as cleanup_scope:
                    for filter in self._filters.filters.values():
                        cleanup_scope.shield = True
                        await filter.send_channel.aclose()


class Proxy(ProxyBase):
    """A trio proxy for calling D-Bus methods

    You can call methods on the proxy object, such as ``await bus_proxy.Hello()``
    to make a method call over D-Bus and wait for a reply. It will either
    return a tuple of returned data, or raise :exc:`.DBusErrorResponse`.
    The methods available are defined by the message generator you wrap.

    :param msggen: A message generator object.
    :param ~trio.DBusRouter router: Router to send and receive messages.
    """
    def __init__(self, msggen, router):
        super().__init__(msggen)
        if not isinstance(router, DBusRouter):
            raise TypeError("Proxy can only be used with DBusRequester")
        self._router = router

    def _method_call(self, make_msg):
        async def inner(*args, **kwargs):
            msg = make_msg(*args, **kwargs)
            assert msg.header.message_type is MessageType.method_call
            reply = await self._router.send_and_get_reply(msg)
            return unwrap_msg(reply)

        return inner


@asynccontextmanager
async def open_dbus_router(bus='SESSION', *, enable_fds=False):
    """Open a D-Bus 'router' to send and receive messages.

    Use as an async context manager::

        async with open_dbus_router() as req:
            ...

    :param str bus: 'SESSION' or 'SYSTEM' or a supported address.
    :return: :class:`DBusRouter`

    This is a shortcut for::

        conn = await open_dbus_connection()
        async with conn:
            async with conn.router() as req:
                ...
    """
    conn = await open_dbus_connection(bus, enable_fds=enable_fds)
    async with conn:
        async with conn.router() as rtr:
            yield rtr
