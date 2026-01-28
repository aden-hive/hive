import asyncio
import contextlib
from itertools import count
from typing import Optional

from jeepney.auth import Authenticator, BEGIN
from jeepney.bus import get_bus
from jeepney import Message, MessageType, Parser
from jeepney.wrappers import ProxyBase, unwrap_msg
from jeepney.bus_messages import message_bus
from .common import (
    MessageFilters, FilterHandle, ReplyMatcher, RouterClosed, check_replyable,
)


class DBusConnection:
    """A plain D-Bus connection with no matching of replies.

    This doesn't run any separate tasks: sending and receiving are done in
    the task that calls those methods. It's suitable for implementing servers:
    several worker tasks can receive requests and send replies.
    For a typical client pattern, see :class:`DBusRouter`.
    """
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        self.reader = reader
        self.writer = writer
        self.parser = Parser()
        self.outgoing_serial = count(start=1)
        self.unique_name = None
        self.send_lock = asyncio.Lock()

    async def send(self, message: Message, *, serial=None):
        """Serialise and send a :class:`~.Message` object"""
        async with self.send_lock:
            if serial is None:
                serial = next(self.outgoing_serial)
            self.writer.write(message.serialise(serial))
            await self.writer.drain()

    async def receive(self) -> Message:
        """Return the next available message from the connection"""
        while True:
            msg = self.parser.get_next_message()
            if msg is not None:
                return msg

            b = await self.reader.read(4096)
            if not b:
                raise EOFError
            self.parser.add_data(b)

    async def close(self):
        """Close the D-Bus connection"""
        self.writer.close()
        await self.writer.wait_closed()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


async def open_dbus_connection(bus='SESSION'):
    """Open a plain D-Bus connection

    :return: :class:`DBusConnection`
    """
    bus_addr = get_bus(bus)
    reader, writer = await asyncio.open_unix_connection(bus_addr)

    # Authentication flow
    authr = Authenticator()
    for req_data in authr:
        writer.write(req_data)
        await writer.drain()
        b = await reader.read(1024)
        if not b:
            raise EOFError("Socket closed before authentication")
        authr.feed(b)

    writer.write(BEGIN)
    await writer.drain()
    # Authentication finished

    conn = DBusConnection(reader, writer)

    # Say *Hello* to the message bus - this must be the first message, and the
    # reply gives us our unique name.
    async with DBusRouter(conn) as router:
        reply_body = await asyncio.wait_for(Proxy(message_bus, router).Hello(), 10)
        conn.unique_name = reply_body[0]

    return conn

class DBusRouter:
    """A 'client' D-Bus connection which can wait for a specific reply.

    This runs a background receiver task, and makes it possible to send a
    request and wait for the relevant reply.
    """
    _nursery_mgr = None
    _send_cancel_scope = None
    _rcv_cancel_scope = None

    def __init__(self, conn: DBusConnection):
        self._conn = conn
        self._replies = ReplyMatcher()
        self._filters = MessageFilters()
        self._rcv_task = asyncio.create_task(self._receiver())

    @property
    def unique_name(self):
        return self._conn.unique_name

    async def send(self, message, *, serial=None):
        """Send a message, don't wait for a reply"""
        await self._conn.send(message, serial=serial)

    async def send_and_get_reply(self, message) -> Message:
        """Send a method call message and wait for the reply

        Returns the reply message (method return or error message type).
        """
        check_replyable(message)
        if self._rcv_task.done():
            raise RouterClosed("This DBusRouter has stopped")

        serial = next(self._conn.outgoing_serial)

        with self._replies.catch(serial, asyncio.Future()) as reply_fut:
            await self.send(message, serial=serial)
            return (await reply_fut)

    def filter(self, rule, *, queue: Optional[asyncio.Queue] =None, bufsize=1):
        """Create a filter for incoming messages

        Usage::

            with router.filter(rule) as queue:
                matching_msg = await queue.get()

        :param MatchRule rule: Catch messages matching this rule
        :param asyncio.Queue queue: Send matching messages here
        :param int bufsize: If no queue is passed in, create one with this size
        """
        return FilterHandle(self._filters, rule, queue or asyncio.Queue(bufsize))

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._rcv_task.done():
            self._rcv_task.result()  # Throw exception if receive task failed
        else:
            self._rcv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._rcv_task
        return False

    # Code to run in receiver task ------------------------------------

    def _dispatch(self, msg: Message):
        """Handle one received message"""
        if self._replies.dispatch(msg):
            return

        for filter in list(self._filters.matches(msg)):
            try:
                filter.queue.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    async def _receiver(self):
        """Receiver loop - runs in a separate task"""
        try:
            while True:
                msg = await self._conn.receive()
                self._dispatch(msg)
        finally:
            # Send errors to any tasks still waiting for a message.
            self._replies.drop_all()

class open_dbus_router:
    """Open a D-Bus 'router' to send and receive messages

    Use as an async context manager::

        async with open_dbus_router() as router:
            ...
    """
    conn = None
    req_ctx = None

    def __init__(self, bus='SESSION'):
        self.bus = bus

    async def __aenter__(self):
        self.conn = await open_dbus_connection(self.bus)
        self.req_ctx = DBusRouter(self.conn)
        return await self.req_ctx.__aenter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.req_ctx.__aexit__(exc_type, exc_val, exc_tb)
        await self.conn.close()


class Proxy(ProxyBase):
    """An asyncio proxy for calling D-Bus methods

    You can call methods on the proxy object, such as ``await bus_proxy.Hello()``
    to make a method call over D-Bus and wait for a reply. It will either
    return a tuple of returned data, or raise :exc:`.DBusErrorResponse`.
    The methods available are defined by the message generator you wrap.

    :param msggen: A message generator object.
    :param ~asyncio.DBusRouter router: Router to send and receive messages.
    """
    def __init__(self, msggen, router):
        super().__init__(msggen)
        self._router = router

    def __repr__(self):
        return 'Proxy({}, {})'.format(self._msggen, self._router)

    def _method_call(self, make_msg):
        async def inner(*args, **kwargs):
            msg = make_msg(*args, **kwargs)
            assert msg.header.message_type is MessageType.method_call
            reply = await self._router.send_and_get_reply(msg)
            return unwrap_msg(reply)

        return inner
