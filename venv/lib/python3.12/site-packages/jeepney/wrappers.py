import re
from typing import Union
from warnings import warn

from .low_level import *

__all__ = [
    'DBusAddress',
    'new_method_call',
    'new_method_return',
    'new_error',
    'new_signal',
    'MessageGenerator',
    'Properties',
    'Introspectable',
    'DBusErrorResponse',
]

bus_name_pat = re.compile(
    r'([A-Za-z_-][A-Za-z0-9_-]*(\.[A-Za-z_-][A-Za-z0-9_-]*)+'  # Well known name
    r'|:[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+))$',  # Unique name
)

def check_bus_name(name):
    if len(name) > 255:
        abbr = name[:8] + '...'
        raise ValueError(f"Bus name ({abbr!r}) is too long (> 255 characters)")
    if not bus_name_pat.match(name):
        raise ValueError(f"Bus name ({name!r}) is not valid")

interface_pat = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$')

def check_interface(name):
    if len(name) > 255:
        abbr = name[:8] + '...'
        raise ValueError(f"Interface name ({abbr!r}) is too long (> 255 characters)")
    if not interface_pat.match(name):
        raise ValueError(f"Interface name ({name!r}) is not valid")

member_name_pat = re.compile(r'[A-Za-z_][A-Za-z0-9_]*$')

def check_member_name(name):
    if len(name) > 255:
        abbr = name[:8] + '...'
        raise ValueError(f"Member name ({abbr!r}) is too long (> 255 characters)")
    if not member_name_pat.match(name):
        raise ValueError(f"Member name ({name!r} is not valid")


class DBusAddress:
    """This identifies the object and interface a message is for.

    e.g. messages to display desktop notifications would have this address::

        DBusAddress('/org/freedesktop/Notifications',
                    bus_name='org.freedesktop.Notifications',
                    interface='org.freedesktop.Notifications')
    """
    def __init__(self, object_path, bus_name=None, interface=None):
        ObjectPathType().check_data(object_path)
        self.object_path = object_path

        if bus_name is not None:
            check_bus_name(bus_name)
        self.bus_name = bus_name

        if interface is not None:
            check_interface(interface)
        self.interface = interface

    def __repr__(self):
        return '{}({!r}, bus_name={!r}, interface={!r})'.format(type(self).__name__,
                    self.object_path, self.bus_name, self.interface)

    def with_interface(self, interface):
        check_interface(interface)
        return type(self)(self.object_path, self.bus_name, interface)

class DBusObject(DBusAddress):
    def __init__(self, object_path, bus_name=None, interface=None):
        super().__init__(object_path, bus_name, interface)
        warn('Deprecated alias, use DBusAddress instead', stacklevel=2)

def new_header(msg_type):
    return Header(Endianness.little, msg_type, flags=0, protocol_version=1,
                  body_length=-1, serial=-1, fields={})

def new_method_call(remote_obj, method, signature=None, body=()):
    """Construct a new method call message

    This is a relatively low-level method. In many cases, this will be called
    from a :class:`MessageGenerator` subclass which provides a more convenient
    API.

    :param DBusAddress remote_obj: The object to call a method on
    :param str method: The name of the method to call
    :param str signature: The DBus signature of the body data
    :param tuple body: Body data (i.e. method parameters)
    """
    check_member_name(method)
    header = new_header(MessageType.method_call)
    header.fields[HeaderFields.path] = remote_obj.object_path
    if remote_obj.bus_name is None:
        raise ValueError("remote_obj.bus_name cannot be None for method calls")
    header.fields[HeaderFields.destination] = remote_obj.bus_name
    if remote_obj.interface is not None:
        header.fields[HeaderFields.interface] = remote_obj.interface
    header.fields[HeaderFields.member] = method
    if signature is not None:
        header.fields[HeaderFields.signature] = signature

    return Message(header, body)

def new_method_return(parent_msg, signature=None, body=()):
    """Construct a new response message

    :param Message parent_msg: The method call this is a reply to
    :param str signature: The DBus signature of the body data
    :param tuple body: Body data
    """
    header = new_header(MessageType.method_return)
    header.fields[HeaderFields.reply_serial] = parent_msg.header.serial
    sender = parent_msg.header.fields.get(HeaderFields.sender, None)
    if sender is not None:
        header.fields[HeaderFields.destination] = sender
    if signature is not None:
        header.fields[HeaderFields.signature] = signature
    return Message(header, body)

def new_error(parent_msg, error_name, signature=None, body=()):
    """Construct a new error response message

    :param Message parent_msg: The method call this is a reply to
    :param str error_name: The name of the error
    :param str signature: The DBus signature of the body data
    :param tuple body: Body data
    """
    header = new_header(MessageType.error)
    header.fields[HeaderFields.reply_serial] = parent_msg.header.serial
    header.fields[HeaderFields.error_name] = error_name
    sender = parent_msg.header.fields.get(HeaderFields.sender, None)
    if sender is not None:
        header.fields[HeaderFields.destination] = sender
    if signature is not None:
        header.fields[HeaderFields.signature] = signature
    return Message(header, body)

def new_signal(emitter, signal, signature=None, body=()):
    """Construct a new signal message

    :param DBusAddress emitter: The object sending the signal
    :param str signal: The name of the signal
    :param str signature: The DBus signature of the body data
    :param tuple body: Body data
    """
    check_member_name(signal)
    header = new_header(MessageType.signal)
    header.fields[HeaderFields.path] = emitter.object_path
    if emitter.interface is None:
        raise ValueError("emitter.interface cannot be None for signals")
    header.fields[HeaderFields.interface] = emitter.interface
    header.fields[HeaderFields.member] = signal
    if signature is not None:
        header.fields[HeaderFields.signature] = signature
    return Message(header, body)


class MessageGenerator:
    """Subclass this to define the methods available on a DBus interface.
    
    jeepney.bindgen can automatically create subclasses using introspection.
    """
    interface: Optional[str] = None

    def __init__(self, object_path, bus_name):
        ObjectPathType().check_data(object_path)
        check_bus_name(bus_name)
        if self.interface is not None:
            check_interface(self.interface)

        self.object_path = object_path
        self.bus_name = bus_name

    def __repr__(self):
        return "{}({!r}, bus_name={!r})".format(type(self).__name__,
                                                self.object_path, self.bus_name)


class ProxyBase:
    """A proxy is an IO-aware wrapper around a MessageGenerator
    
    Calling methods on a proxy object will send a message and wait for the
    reply. This is a base class for proxy implementations in jeepney.io.
    """
    def __init__(self, msggen):
        self._msggen = msggen

    def __getattr__(self, item):
        if item.startswith('__'):
            raise AttributeError(item)

        make_msg = getattr(self._msggen, item, None)
        if callable(make_msg):
            return self._method_call(make_msg)

        raise AttributeError(item)

    def _method_call(self, make_msg):
        raise NotImplementedError("Needs to be implemented in subclass")

class Properties:
    """Build messages for accessing object properties

    If a D-Bus object has multiple interfaces, each interface has its own
    set of properties.

    This uses the standard DBus interface ``org.freedesktop.DBus.Properties``
    """
    def __init__(self, obj: Union[DBusAddress, MessageGenerator]):
        self.obj = obj
        self.props_if = DBusAddress(obj.object_path, bus_name=obj.bus_name,
                                    interface='org.freedesktop.DBus.Properties')

    def get(self, name):
        """Get the value of the property *name*"""
        return new_method_call(self.props_if, 'Get', 'ss',
                   (self.obj.interface, name))

    def get_all(self):
        """Get all property values for this interface"""
        return new_method_call(self.props_if, 'GetAll', 's',
                               (self.obj.interface,))

    def set(self, name, signature, value):
        """Set the property *name* to *value* (with appropriate signature)"""
        return new_method_call(self.props_if, 'Set', 'ssv',
                   (self.obj.interface, name, (signature, value)))

class Introspectable(MessageGenerator):
    interface = 'org.freedesktop.DBus.Introspectable'

    def Introspect(self):
        """Request D-Bus introspection XML for a remote object"""
        return new_method_call(self, 'Introspect')

class DBusErrorResponse(Exception):
    """Raised by proxy method calls when the reply is an error message"""
    def __init__(self, msg):
        self.name = msg.header.fields.get(HeaderFields.error_name)
        self.data = msg.body

    def __str__(self):
        return '[{}] {}'.format(self.name, self.data)


def unwrap_msg(msg: Message):
    """Get the body of a message, raising DBusErrorResponse for error messages

    This is to be used with replies to method_call messages, which may be
    method_return or error.
    """
    if msg.header.message_type == MessageType.error:
        raise DBusErrorResponse(msg)

    return msg.body
