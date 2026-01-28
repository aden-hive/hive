import pytest

from jeepney.wrappers import *

def test_bad_bus_name():
    obj = '/com/example/foo'
    DBusAddress(obj, 'com.example.a')  # Valid (well known name)
    DBusAddress(obj, 'com.example.a-b')  # Valid but discouraged
    DBusAddress(obj, ':1.13')  # Valid (unique name)

    with pytest.raises(ValueError, match='too long'):
        DBusAddress(obj, 'com.example.' + ('a' * 256))

    with pytest.raises(ValueError):
        DBusAddress(obj, '.com.example.a')

    with pytest.raises(ValueError):
        DBusAddress(obj, 'com..example.a')

    with pytest.raises(ValueError):
        DBusAddress(obj, 'com.2example.a')

    with pytest.raises(ValueError):
        DBusAddress(obj, 'cöm.example.a')  # Non-ASCII character

    with pytest.raises(ValueError):
        DBusAddress(obj, 'com')

def test_bad_interface():
    obj = '/com/example/foo'
    busname = 'com.example.foo'
    DBusAddress(obj, 'com.example.a', 'com.example.a_b')  # Valid

    with pytest.raises(ValueError, match='too long'):
        DBusAddress(obj, 'com.example.a', 'com.example.' + ('a' * 256))

    with pytest.raises(ValueError):
        DBusAddress(obj, 'com.example.a', 'com.example.a-b')  # No hyphens

    with pytest.raises(ValueError):
        DBusAddress(obj, busname, '.com.example.a')

    with pytest.raises(ValueError):
        DBusAddress(obj, busname, 'com..example.a')

    with pytest.raises(ValueError):
        DBusAddress(obj, busname, 'com.2example.a')

    with pytest.raises(ValueError):
        DBusAddress(obj, busname, 'cöm.example.a')  # Non-ASCII character

    with pytest.raises(ValueError):
        DBusAddress(obj, busname, 'com')


def test_bad_member_name():
    addr = DBusAddress(
        '/org/freedesktop/DBus',
        bus_name='org.freedesktop.DBus',
        interface='org.freedesktop.DBus',
    )
    new_method_call(addr, 'Hello')

    with pytest.raises(ValueError, match='too long'):
        new_method_call(addr, 'Hell' + ('o' * 256))

    with pytest.raises(ValueError):
        new_method_call(addr, 'org.Hello')

    with pytest.raises(ValueError):
        new_method_call(addr, '9Hello')

    with pytest.raises(ValueError):
        new_method_call(addr, '')
