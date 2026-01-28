import pytest

from jeepney import new_method_call, MessageType, DBusAddress
from jeepney.bus_messages import message_bus, MatchRule
from jeepney.io.blocking import open_dbus_connection, Proxy
from .utils import have_session_bus

pytestmark = pytest.mark.skipif(
    not have_session_bus, reason="Tests require DBus session bus"
)

@pytest.fixture
def session_conn():
    with open_dbus_connection(bus='SESSION') as conn:
        yield conn


def test_connect(session_conn):
    assert session_conn.unique_name.startswith(':')

bus_peer = DBusAddress(
    bus_name='org.freedesktop.DBus',
    object_path='/org/freedesktop/DBus',
    interface='org.freedesktop.DBus.Peer'
)

def test_send_and_get_reply(session_conn):
    ping_call = new_method_call(bus_peer, 'Ping')
    reply = session_conn.send_and_get_reply(ping_call, timeout=5)
    assert reply.header.message_type == MessageType.method_return
    assert reply.body == ()

def test_proxy(session_conn):
    proxy = Proxy(message_bus, session_conn, timeout=5)
    name = "io.gitlab.takluyver.jeepney.examples.Server"
    res = proxy.RequestName(name)
    assert res in {(1,), (2,)}  # 1: got the name, 2: queued

    has_owner, = proxy.NameHasOwner(name, _timeout=3)
    assert has_owner is True

def test_filter(session_conn):
    bus = Proxy(message_bus, session_conn)
    name = "io.gitlab.takluyver.jeepney.tests.blocking_test_filter"

    match_rule = MatchRule(
        type="signal",
        sender=message_bus.bus_name,
        interface=message_bus.interface,
        member="NameOwnerChanged",
        path=message_bus.object_path,
    )
    match_rule.add_arg_condition(0, name)

    # Ask the message bus to subscribe us to this signal
    bus.AddMatch(match_rule)

    with session_conn.filter(match_rule) as matches:
        res, = bus.RequestName(name)
        assert res == 1  # 1: got the name

        signal_msg = session_conn.recv_until_filtered(matches, timeout=2)

        assert signal_msg.body == (name, '', session_conn.unique_name)


def test_recv_fd(respond_with_fd):
    getfd_call = new_method_call(respond_with_fd, 'GetFD')
    with open_dbus_connection(bus='SESSION', enable_fds=True) as conn:
        reply = conn.send_and_get_reply(getfd_call, timeout=5)

    assert reply.header.message_type is MessageType.method_return
    with reply.body[0].to_file('w+') as f:
        assert f.read() == 'readme'


def test_send_fd(temp_file_and_contents, read_from_fd):
    temp_file, data = temp_file_and_contents
    readfd_call = new_method_call(read_from_fd, 'ReadFD', 'h', (temp_file,))
    with open_dbus_connection(bus='SESSION', enable_fds=True) as conn:
        reply = conn.send_and_get_reply(readfd_call, timeout=5)

    assert reply.header.message_type is MessageType.method_return
    assert reply.body[0] == data
