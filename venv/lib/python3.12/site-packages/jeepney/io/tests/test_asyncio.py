import asyncio
import sys

if sys.version_info >= (3, 11):
    from asyncio import timeout
else:
    from async_timeout import timeout
import pytest
import pytest_asyncio

from jeepney import DBusAddress, new_method_call
from jeepney.bus_messages import message_bus, MatchRule
from jeepney.io.asyncio import (
    open_dbus_connection, open_dbus_router, Proxy
)
from .utils import have_session_bus

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not have_session_bus, reason="Tests require DBus session bus"
    ),
]

bus_peer = DBusAddress(
    bus_name='org.freedesktop.DBus',
    object_path='/org/freedesktop/DBus',
    interface='org.freedesktop.DBus.Peer'
)


@pytest_asyncio.fixture()
async def connection():
    async with (await open_dbus_connection(bus='SESSION')) as conn:
        yield conn

async def test_connect(connection):
    assert connection.unique_name.startswith(':')

@pytest_asyncio.fixture()
async def router():
    async with open_dbus_router(bus='SESSION') as router:
        yield router

async def test_send_and_get_reply(router):
    ping_call = new_method_call(bus_peer, 'Ping')
    reply = await asyncio.wait_for(
        router.send_and_get_reply(ping_call), timeout=5
    )
    assert reply.body == ()

async def test_proxy(router):
    proxy = Proxy(message_bus, router)
    name = "io.gitlab.takluyver.jeepney.examples.Server"
    res = await proxy.RequestName(name)
    assert res in {(1,), (2,)}  # 1: got the name, 2: queued

    has_owner, = await proxy.NameHasOwner(name)
    assert has_owner is True

async def test_filter(router):
    bus = Proxy(message_bus, router)
    name = "io.gitlab.takluyver.jeepney.tests.asyncio_test_filter"

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

    with router.filter(match_rule) as queue:
        res, = await bus.RequestName(name)
        assert res == 1  # 1: got the name

        signal_msg = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert signal_msg.body == (name, '', router.unique_name)

async def test_recv_after_connect():
    # Can't use here:
    # 1. 'connection' fixture
    # 2. asyncio.wait_for()
    # If (1) and/or (2) is used, the error won't be triggered.
    conn = await open_dbus_connection(bus='SESSION')
    try:
        with pytest.raises(asyncio.TimeoutError):
            async with timeout(0):
                await conn.receive()
    finally:
        await conn.close()
