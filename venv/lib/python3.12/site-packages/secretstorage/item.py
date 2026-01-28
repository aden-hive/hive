# SecretStorage module for Python
# Access passwords using the SecretService DBus API
# Author: Dmitry Shachnev, 2013-2025
# License: 3-clause BSD, see LICENSE file

"""SecretStorage item contains a *secret*, some *attributes* and a
*label* visible to user. Editing all these properties and reading the
secret is possible only when the :doc:`collection <collection>` storing
the item is unlocked. The collection can be unlocked using collection's
:meth:`~secretstorage.collection.Collection.unlock` method."""

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from jeepney.io.blocking import DBusConnection

from secretstorage.defines import SS_PREFIX
from secretstorage.dhcrypto import Session
from secretstorage.exceptions import LockedException, PromptDismissedException
from secretstorage.util import (
    DBusAddressWrapper,
    exec_prompt,
    format_secret,
    open_session,
    unlock_objects,
)

ITEM_IFACE = SS_PREFIX + 'Item'


class Item:
    """Represents a secret item."""

    def __init__(self, connection: DBusConnection,
                 item_path: str, session: Session | None = None) -> None:
        self.item_path = item_path
        self._item = DBusAddressWrapper(item_path, ITEM_IFACE, connection)
        self._item.get_property('Label')
        self.session = session
        self.connection = connection

    def __eq__(self, other: "DBusConnection") -> bool:
        assert isinstance(other.item_path, str)
        return self.item_path == other.item_path

    def is_locked(self) -> bool:
        """Returns :const:`True` if item is locked, otherwise
        :const:`False`."""
        return bool(self._item.get_property('Locked'))

    def ensure_not_locked(self) -> None:
        """If collection is locked, raises
        :exc:`~secretstorage.exceptions.LockedException`."""
        if self.is_locked():
            raise LockedException('Item is locked!')

    def unlock(self, timeout: float | None = None) -> bool:
        """Requests unlocking the item. Usually, this means that the
        whole collection containing this item will be unlocked.

        Returns a boolean representing whether the prompt has been
        dismissed; that means :const:`False` on successful unlocking
        and :const:`True` if it has been dismissed.

        :raises: ``TimeoutError`` if `timeout` (in seconds) passed
           and the prompt was neither accepted nor dismissed.

        .. versionadded:: 2.1.2

        .. versionchanged:: 3.0
           No longer accepts the ``callback`` argument.

        .. versionchanged:: 3.5
           Added ``timeout`` argument.
        """
        return unlock_objects(self.connection, [self.item_path], timeout=timeout)

    def get_attributes(self) -> dict[str, str]:
        """Returns item attributes (dictionary)."""
        attrs = self._item.get_property('Attributes')
        return dict(attrs)

    def set_attributes(self, attributes: dict[str, str]) -> None:
        """Sets item attributes to `attributes` (dictionary)."""
        self._item.set_property('Attributes', 'a{ss}', attributes)

    def get_label(self) -> str:
        """Returns item label (unicode string)."""
        label = self._item.get_property('Label')
        assert isinstance(label, str)
        return label

    def set_label(self, label: str) -> None:
        """Sets item label to `label`."""
        self.ensure_not_locked()
        self._item.set_property('Label', 's', label)

    def delete(self) -> None:
        """Deletes the item."""
        self.ensure_not_locked()
        prompt, = self._item.call('Delete', '')
        if prompt != "/":
            dismissed, _result = exec_prompt(self.connection, prompt)
            if dismissed:
                raise PromptDismissedException('Prompt dismissed.')

    def get_secret(self) -> bytes:
        """Returns item secret (bytestring)."""
        self.ensure_not_locked()
        if not self.session:
            self.session = open_session(self.connection)
        secret, = self._item.call('GetSecret', 'o', self.session.object_path)
        if not self.session.encrypted:
            return bytes(secret[2])
        assert self.session.aes_key is not None
        aes = algorithms.AES(self.session.aes_key)
        aes_iv = bytes(secret[1])
        decryptor = Cipher(aes, modes.CBC(aes_iv), default_backend()).decryptor()
        encrypted_secret = secret[2]
        padded_secret = decryptor.update(bytes(encrypted_secret)) + decryptor.finalize()
        assert isinstance(padded_secret, bytes)
        return padded_secret[:-padded_secret[-1]]

    def get_secret_content_type(self) -> str:
        """Returns content type of item secret (string)."""
        self.ensure_not_locked()
        if not self.session:
            self.session = open_session(self.connection)
        secret, = self._item.call('GetSecret', 'o', self.session.object_path)
        return str(secret[3])

    def set_secret(self, secret: bytes,
                   content_type: str = 'text/plain') -> None:
        """Sets item secret to `secret`. If `content_type` is given,
        also sets the content type of the secret (``text/plain`` by
        default)."""
        self.ensure_not_locked()
        if not self.session:
            self.session = open_session(self.connection)
        _secret = format_secret(self.session, secret, content_type)
        self._item.call('SetSecret', '(oayays)', _secret)

    def get_created(self) -> int:
        """Returns UNIX timestamp (integer) representing the time
        when the item was created.

        .. versionadded:: 1.1"""
        created = self._item.get_property('Created')
        assert isinstance(created, int)
        return created

    def get_modified(self) -> int:
        """Returns UNIX timestamp (integer) representing the time
        when the item was last modified."""
        modified = self._item.get_property('Modified')
        assert isinstance(modified, int)
        return modified

    def __repr__(self) -> str:
        return f"<Item {self.get_label()!r} path={self.item_path!r}>"
