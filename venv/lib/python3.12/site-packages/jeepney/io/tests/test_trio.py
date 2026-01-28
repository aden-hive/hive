import trio
import pytest

from jeepney import DBusAddress, DBusErrorResponse, MessageType, new_method_call
from jeepney.bus_messages import message_bus, MatchRule
from jeepney.io.trio import (
    open_dbus_connection, open_dbus_router, Proxy,
)
from .utils import have_session_bus

pytestmark = [
    pytest.mark.trio,
    pytest.mark.skipif(
        not have_session_bus, reason="Tests require DBus session bus"
    ),
]

# Can't use any async fixtures here, because pytest-asyncio tries to handle
# all of them: https://github.com/pytest-dev/pytest-asyncio/issues/124

async def test_connect():
    conn = await open_dbus_connection(bus='SESSION')
    async with conn:
        assert conn.unique_name.startswith(':')

bus_peer = DBusAddress(
    bus_name='org.freedesktop.DBus',
    object_path='/org/freedesktop/DBus',
    interface='org.freedesktop.DBus.Peer'
)

async def test_send_and_get_reply():
    ping_call = new_method_call(bus_peer, 'Ping')
    async with open_dbus_router(bus='SESSION') as req:
        with trio.fail_after(5):
            reply = await req.send_and_get_reply(ping_call)

    assert reply.header.message_type == MessageType.method_return
    assert reply.body == ()


async def test_send_and_get_reply_error():
    ping_call = new_method_call(bus_peer, 'Snart')  # No such method
    async with open_dbus_router(bus='SESSION') as req:
        with trio.fail_after(5):
            reply = await req.send_and_get_reply(ping_call)

    assert reply.header.message_type == MessageType.error


async def test_proxy():
    async with open_dbus_router(bus='SESSION') as req:
        proxy = Proxy(message_bus, req)
        name = "io.gitlab.takluyver.jeepney.examples.Server"
        res = await proxy.RequestName(name)
        assert res in {(1,), (2,)}  # 1: got the name, 2: queued

        has_owner, = await proxy.NameHasOwner(name)
        assert has_owner is True


async def test_proxy_error():
    async with open_dbus_router(bus='SESSION') as req:
        proxy = Proxy(message_bus, req)
        with pytest.raises(DBusErrorResponse):
            await proxy.RequestName(":123")  # Invalid name


async def test_filter():
    name = "io.gitlab.takluyver.jeepney.tests.trio_test_filter"
    async with open_dbus_router(bus='SESSION') as router:
        bus = Proxy(message_bus, router)

        match_rule = MatchRule(
            type="signal",
            sender=message_bus.bus_name,
            interface=message_bus.interface,
            member="NameOwnerChanged",
            path=message_bus.object_path,
        )
        match_rule.add_arg_condition(0, name)

        # Ask the message bus to subscribe us to this signal
        await bus.AddMatch(match_rule)

        async with router.filter(match_rule) as chan:
            res, = await bus.RequestName(name)
            assert res == 1  # 1: got the name

            with trio.fail_after(2.0):
                signal_msg = await chan.receive()
            assert signal_msg.body == (name, '', router.unique_name)


async def test_recv_fd(respond_with_fd):
    getfd_call = new_method_call(respond_with_fd, 'GetFD')
    with trio.fail_after(5):
        async with open_dbus_router(bus='SESSION', enable_fds=True) as router:
            reply = await router.send_and_get_reply(getfd_call)

    assert reply.header.message_type is MessageType.method_return
    with reply.body[0].to_file('w+') as f:
        assert f.read() == 'readme'


async def test_send_fd(temp_file_and_contents, read_from_fd):
    temp_file, data = temp_file_and_contents
    readfd_call = new_method_call(read_from_fd, 'ReadFD', 'h', (temp_file,))
    with trio.fail_after(5):
        async with open_dbus_router(bus='SESSION', enable_fds=True) as router:
            reply = await router.send_and_get_reply(readfd_call)

    assert reply.header.message_type is MessageType.method_return
    assert reply.body[0] == data
