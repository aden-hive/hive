# SecretStorage module for Python
# Access passwords using the SecretService DBus API
# Author: Dmitry Shachnev, 2013-2025
# License: 3-clause BSD, see LICENSE file

"""This module provides some utility functions, but these shouldn't
normally be used by external applications."""

import os
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from jeepney import (
    DBusAddress,
    DBusErrorResponse,
    MatchRule,
    Message,
    MessageType,
    Properties,
    new_method_call,
)
from jeepney.io.blocking import DBusConnection

from secretstorage.defines import (
    ALGORITHM_DH,
    ALGORITHM_PLAIN,
    DBUS_EXEC_FAILED,
    DBUS_NO_REPLY,
    DBUS_NO_SUCH_OBJECT,
    DBUS_NOT_SUPPORTED,
    DBUS_SERVICE_UNKNOWN,
    DBUS_UNKNOWN_METHOD,
    DBUS_UNKNOWN_OBJECT,
    SS_PATH,
    SS_PREFIX,
)
from secretstorage.dhcrypto import Session
from secretstorage.exceptions import (
    ItemNotFoundException,
    SecretServiceNotAvailableException,
)

BUS_NAME = 'org.freedesktop.secrets'
SERVICE_IFACE = SS_PREFIX + 'Service'
PROMPT_IFACE = SS_PREFIX + 'Prompt'


class DBusAddressWrapper(DBusAddress):  # type: ignore
    """A wrapper class around :class:`jeepney.wrappers.DBusAddress`
    that adds some additional methods for calling and working with
    properties, and converts error responses to SecretStorage
    exceptions.

    .. versionadded:: 3.0
    """
    def __init__(self, path: str, interface: str,
                 connection: DBusConnection) -> None:
        DBusAddress.__init__(self, path, BUS_NAME, interface)
        self._connection = connection

    def send_and_get_reply(self, msg: Message) -> Any:
        try:
            resp_msg: Message = self._connection.send_and_get_reply(msg)
            if resp_msg.header.message_type == MessageType.error:
                raise DBusErrorResponse(resp_msg)
            return resp_msg.body
        except DBusErrorResponse as resp:
            if resp.name in (
                DBUS_UNKNOWN_METHOD,
                DBUS_NO_SUCH_OBJECT,
                DBUS_UNKNOWN_OBJECT,
            ):
                raise ItemNotFoundException('Item does not exist!') from resp
            elif resp.name in (DBUS_SERVICE_UNKNOWN, DBUS_EXEC_FAILED,
                               DBUS_NO_REPLY):
                data = resp.data
                if isinstance(data, tuple):
                    data = data[0]
                raise SecretServiceNotAvailableException(data) from resp
            raise

    def call(self, method: str, signature: str, *body: Any) -> Any:
        msg = new_method_call(self, method, signature, body)
        return self.send_and_get_reply(msg)

    def get_property(self, name: str) -> Any:
        msg = Properties(self).get(name)
        (signature, value), = self.send_and_get_reply(msg)
        return value

    def set_property(self, name: str, signature: str, value: Any) -> None:
        msg = Properties(self).set(name, signature, value)
        self.send_and_get_reply(msg)


def open_session(connection: DBusConnection) -> Session:
    """Returns a new Secret Service session."""
    service = DBusAddressWrapper(SS_PATH, SERVICE_IFACE, connection)
    session = Session()
    try:
        output, result = service.call(
            'OpenSession', 'sv',
            ALGORITHM_DH,
            ('ay', session.my_public_key.to_bytes(128, 'big')))
    except DBusErrorResponse as resp:
        if resp.name != DBUS_NOT_SUPPORTED:
            raise
        output, result = service.call(
            'OpenSession', 'sv',
            ALGORITHM_PLAIN,
            ('s', ''))
        session.encrypted = False
    else:
        signature, value = output
        assert signature == 'ay'
        key = int.from_bytes(value, 'big')
        session.set_server_public_key(key)
    session.object_path = result
    return session


def format_secret(session: Session, secret: bytes,
                  content_type: str) -> tuple[str, bytes, bytes, str]:
    """Formats `secret` to make possible to pass it to the
    Secret Service API."""
    if isinstance(secret, str):
        secret = secret.encode('utf-8')
    elif not isinstance(secret, bytes):
        raise TypeError('secret must be bytes')
    assert session.object_path is not None
    if not session.encrypted:
        return (session.object_path, b'', secret, content_type)
    assert session.aes_key is not None
    # PKCS-7 style padding
    padding = 0x10 - (len(secret) & 0xf)
    secret += bytes((padding,) * padding)
    aes_iv = os.urandom(0x10)
    aes = algorithms.AES(session.aes_key)
    encryptor = Cipher(aes, modes.CBC(aes_iv), default_backend()).encryptor()
    encrypted_secret = encryptor.update(secret) + encryptor.finalize()
    return (
        session.object_path,
        aes_iv,
        encrypted_secret,
        content_type
    )


def exec_prompt(
    connection: DBusConnection,
    prompt_path: str,
    *,
    timeout: float | None = None,
) -> tuple[bool, tuple[str, Any]]:
    """Executes the prompt in a blocking mode.

    :returns: a two-element tuple:

       - The first element is a boolean value indicating whether the operation was
         dismissed.
       - The second element is a (signature, result) tuple. For creating items and
         collections, ``signature`` is ``'o'`` and ``result`` is a single object
         path. For unlocking, ``signature`` is ``'ao'`` and ``result`` is a list of
         object paths.

    .. versionchanged:: 3.5
       Added ``timeout`` keyword argument.
    """
    prompt = DBusAddressWrapper(prompt_path, PROMPT_IFACE, connection)
    rule = MatchRule(
        path=prompt_path,
        interface=PROMPT_IFACE,
        member='Completed',
        type=MessageType.signal,
    )
    with connection.filter(rule) as signals:
        prompt.call('Prompt', 's', '')
        message = connection.recv_until_filtered(signals, timeout=timeout)
        dismissed, result = message.body
    assert dismissed is not None
    assert result is not None
    return dismissed, result


def unlock_objects(
    connection: DBusConnection,
    paths: list[str],
    *,
    timeout: float | None = None,
) -> bool:
    """Requests unlocking objects specified in `paths`.
    Returns a boolean representing whether the operation was dismissed.

    .. versionadded:: 2.1.2

    .. versionchanged:: 3.5
       Added ``timeout`` keyword argument.
    """
    service = DBusAddressWrapper(SS_PATH, SERVICE_IFACE, connection)
    unlocked_paths, prompt = service.call('Unlock', 'ao', paths)
    if len(prompt) > 1:
        dismissed, (signature, unlocked) = exec_prompt(
            connection,
            prompt,
            timeout=timeout,
        )
        assert signature == 'ao'
        return dismissed
    return False


def add_match_rules(connection: DBusConnection) -> None:
    """Adds match rules for the given connection.

    Currently it matches all messages from the Prompt interface, as the
    mock service (unlike GNOME Keyring) does not specify the signal
    destination.

    .. versionadded:: 3.1
    """
    rule = MatchRule(sender=BUS_NAME, interface=PROMPT_IFACE)
    dbus = DBusAddressWrapper(path='/org/freedesktop/DBus',
                              interface='org.freedesktop.DBus',
                              connection=connection)
    dbus.bus_name = 'org.freedesktop.DBus'
    dbus.call('AddMatch', 's', rule.serialise())
