import pytest
from testpath import modified_env

from jeepney import bus

def test_get_connectable_addresses():
    a = list(bus.get_connectable_addresses('unix:path=/run/user/1000/bus'))
    assert a == ['/run/user/1000/bus']

    a = list(bus.get_connectable_addresses('unix:abstract=/tmp/foo'))
    assert a == ['\0/tmp/foo']

    with pytest.raises(RuntimeError):
        list(bus.get_connectable_addresses('unix:tmpdir=/tmp'))

def test_get_bus():
    with modified_env({
        'DBUS_SESSION_BUS_ADDRESS':'unix:path=/run/user/1000/bus',
        'DBUS_SYSTEM_BUS_ADDRESS': 'unix:path=/var/run/dbus/system_bus_socket'
    }):
        assert bus.get_bus('SESSION') == '/run/user/1000/bus'
        assert bus.get_bus('SYSTEM') == '/var/run/dbus/system_bus_socket'

    assert bus.get_bus('unix:path=/run/user/1002/bus') == '/run/user/1002/bus'
