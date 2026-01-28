from tempfile import TemporaryFile
import threading

import pytest

from jeepney import (
    DBusAddress,  HeaderFields, message_bus, MessageType, new_error,
    new_method_return,
)
from jeepney.io.threading import open_dbus_connection, DBusRouter, Proxy

@pytest.fixture()
def respond_with_fd():
    name = "io.gitlab.takluyver.jeepney.tests.respond_with_fd"
    addr = DBusAddress(bus_name=name, object_path='/')

    with open_dbus_connection(bus='SESSION', enable_fds=True) as conn:
        with DBusRouter(conn) as router:
            status, = Proxy(message_bus, router).RequestName(name)
        assert status == 1  # DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER

        def _reply_once():
            while True:
                msg = conn.receive()
                if msg.header.message_type is MessageType.method_call:
                    if msg.header.fields[HeaderFields.member] == 'GetFD':
                        with TemporaryFile('w+') as tf:
                            tf.write('readme')
                            tf.seek(0)
                            rep = new_method_return(msg, 'h', (tf,))
                            conn.send(rep)
                            return
                    else:
                        conn.send(new_error(msg, 'NoMethod'))

        reply_thread = threading.Thread(target=_reply_once, daemon=True)
        reply_thread.start()
        yield addr

    reply_thread.join()


@pytest.fixture()
def read_from_fd():
    name = "io.gitlab.takluyver.jeepney.tests.read_from_fd"
    addr = DBusAddress(bus_name=name, object_path='/')

    with open_dbus_connection(bus='SESSION', enable_fds=True) as conn:
        with DBusRouter(conn) as router:
            status, = Proxy(message_bus, router).RequestName(name)
        assert status == 1  # DBUS_REQUEST_NAME_REPLY_PRIMARY_OWNER

        def _reply_once():
            while True:
                msg = conn.receive()
                if msg.header.message_type is MessageType.method_call:
                    if msg.header.fields[HeaderFields.member] == 'ReadFD':
                        with msg.body[0].to_file('rb') as f:
                            f.seek(0)
                            b = f.read()
                        conn.send(new_method_return(msg, 'ay', (b,)))
                        return
                    else:
                        conn.send(new_error(msg, 'NoMethod'))

        reply_thread = threading.Thread(target=_reply_once, daemon=True)
        reply_thread.start()
        yield addr

    reply_thread.join()


@pytest.fixture()
def temp_file_and_contents():
    data = b'abc123'
    with TemporaryFile('w+b') as tf:
        tf.write(data)
        tf.flush()
        tf.seek(0)
        yield tf, data

