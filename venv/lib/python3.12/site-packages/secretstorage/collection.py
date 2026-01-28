# SecretStorage module for Python
# Access passwords using the SecretService DBus API
# Author: Dmitry Shachnev, 2013-2025
# License: 3-clause BSD, see LICENSE file

"""Collection is a place where secret items are stored. Normally, only
the default collection should be used, but this module allows to use any
registered collection. Use :func:`get_default_collection` to get the
default collection (and create it, if necessary).

Collections are usually automatically unlocked when user logs in, but
collections can also be locked and unlocked using :meth:`Collection.lock`
and :meth:`Collection.unlock` methods (unlocking requires showing the
unlocking prompt to user and blocks until user accepts or declines it).
Creating new items and editing existing ones is possible only in unlocked
collections.
"""

from collections.abc import Iterator

from jeepney.io.blocking import DBusConnection

from secretstorage.defines import SS_PATH, SS_PREFIX
from secretstorage.dhcrypto import Session
from secretstorage.exceptions import (
    ItemNotFoundException,
    LockedException,
    PromptDismissedException,
)
from secretstorage.item import Item
from secretstorage.util import (
    DBusAddressWrapper,
    exec_prompt,
    format_secret,
    open_session,
    unlock_objects,
)

COLLECTION_IFACE = SS_PREFIX + 'Collection'
SERVICE_IFACE = SS_PREFIX + 'Service'
DEFAULT_COLLECTION = '/org/freedesktop/secrets/aliases/default'
SESSION_COLLECTION = '/org/freedesktop/secrets/collection/session'


class Collection:
    """Represents a collection."""

    def __init__(self, connection: DBusConnection,
                 collection_path: str = DEFAULT_COLLECTION,
                 session: Session | None = None) -> None:
        self.connection = connection
        self.session = session
        self.collection_path = collection_path
        self._collection = DBusAddressWrapper(
            collection_path, COLLECTION_IFACE, connection)
        self._collection.get_property('Label')

    def is_locked(self) -> bool:
        """Returns :const:`True` if item is locked, otherwise
        :const:`False`."""
        return bool(self._collection.get_property('Locked'))

    def ensure_not_locked(self) -> None:
        """If collection is locked, raises
        :exc:`~secretstorage.exceptions.LockedException`."""
        if self.is_locked():
            raise LockedException('Collection is locked!')

    def unlock(self, timeout: float | None = None) -> bool:
        """Requests unlocking the collection.

        Returns a boolean representing whether the prompt has been
        dismissed; that means :const:`False` on successful unlocking
        and :const:`True` if it has been dismissed.

        :raises: ``TimeoutError`` if `timeout` (in seconds) passed
           and the prompt was neither accepted nor dismissed.

        .. versionchanged:: 3.0
           No longer accepts the ``callback`` argument.

        .. versionchanged:: 3.5
           Added ``timeout`` argument.
        """
        return unlock_objects(self.connection, [self.collection_path], timeout=timeout)

    def lock(self) -> None:
        """Locks the collection."""
        service = DBusAddressWrapper(SS_PATH, SERVICE_IFACE, self.connection)
        service.call('Lock', 'ao', [self.collection_path])

    def delete(self) -> None:
        """Deletes the collection and all items inside it."""
        self.ensure_not_locked()
        prompt, = self._collection.call('Delete', '')
        if prompt != "/":
            dismissed, _result = exec_prompt(self.connection, prompt)
            if dismissed:
                raise PromptDismissedException('Prompt dismissed.')

    def get_all_items(self) -> Iterator[Item]:
        """Returns a generator of all items in the collection."""
        for item_path in self._collection.get_property('Items'):
            yield Item(self.connection, item_path, self.session)

    def search_items(self, attributes: dict[str, str]) -> Iterator[Item]:
        """Returns a generator of items with the given attributes.
        `attributes` should be a dictionary."""
        result, = self._collection.call('SearchItems', 'a{ss}', attributes)
        for item_path in result:
            yield Item(self.connection, item_path, self.session)

    def get_label(self) -> str:
        """Returns the collection label."""
        label = self._collection.get_property('Label')
        assert isinstance(label, str)
        return label

    def set_label(self, label: str) -> None:
        """Sets collection label to `label`."""
        self.ensure_not_locked()
        self._collection.set_property('Label', 's', label)

    def create_item(self, label: str, attributes: dict[str, str],
                    secret: bytes, replace: bool = False,
                    content_type: str = 'text/plain') -> Item:
        """Creates a new :class:`~secretstorage.item.Item` with given
        `label` (unicode string), `attributes` (dictionary) and `secret`
        (bytestring). If `replace` is :const:`True`, replaces the existing
        item with the same attributes. If `content_type` is given, also
        sets the content type of the secret (``text/plain`` by default).
        Returns the created item."""
        self.ensure_not_locked()
        if not self.session:
            self.session = open_session(self.connection)
        _secret = format_secret(self.session, secret, content_type)
        properties = {
            SS_PREFIX + 'Item.Label': ('s', label),
            SS_PREFIX + 'Item.Attributes': ('a{ss}', attributes),
        }
        item_path, prompt = self._collection.call(
            'CreateItem',
            'a{sv}(oayays)b',
            properties,
            _secret,
            replace
        )
        if len(item_path) > 1:
            return Item(self.connection, item_path, self.session)
        dismissed, result = exec_prompt(self.connection, prompt)
        if dismissed:
            raise PromptDismissedException('Prompt dismissed.')
        signature, item_path = result
        assert signature == 'o'
        return Item(self.connection, item_path, self.session)

    def __repr__(self) -> str:
        return f"<Collection {self.get_label()!r} path={self.collection_path!r}>"


def create_collection(connection: DBusConnection, label: str, alias: str = '',
                      session: Session | None = None) -> Collection:
    """Creates a new :class:`Collection` with the given `label` and `alias`
    and returns it. This action requires prompting.

    :raises: :exc:`~secretstorage.exceptions.PromptDismissedException`
             if the prompt is dismissed.
    """
    if not session:
        session = open_session(connection)
    properties = {SS_PREFIX + 'Collection.Label': ('s', label)}
    service = DBusAddressWrapper(SS_PATH, SERVICE_IFACE, connection)
    collection_path, prompt = service.call('CreateCollection', 'a{sv}s',
                                           properties, alias)
    if len(collection_path) > 1:
        return Collection(connection, collection_path, session=session)
    dismissed, result = exec_prompt(connection, prompt)
    if dismissed:
        raise PromptDismissedException('Prompt dismissed.')
    signature, collection_path = result
    assert signature == 'o'
    return Collection(connection, collection_path, session=session)


def get_all_collections(connection: DBusConnection) -> Iterator[Collection]:
    """Returns a generator of all available collections."""
    service = DBusAddressWrapper(SS_PATH, SERVICE_IFACE, connection)
    for collection_path in service.get_property('Collections'):
        yield Collection(connection, collection_path)


def get_default_collection(connection: DBusConnection,
                           session: Session | None = None) -> Collection:
    """Returns the default collection. If it doesn't exist,
    creates it."""
    try:
        return Collection(connection)
    except ItemNotFoundException:
        return create_collection(connection, 'Default', 'default', session)


def get_any_collection(connection: DBusConnection) -> Collection:
    """Returns any collection, in the following order of preference:

    - The default collection;
    - The "session" collection (usually temporary);
    - The first collection in the collections list."""
    try:
        return Collection(connection)
    except ItemNotFoundException:
        pass
    try:
        # GNOME Keyring provides session collection where items
        # are stored in process memory.
        return Collection(connection, SESSION_COLLECTION)
    except ItemNotFoundException:
        pass
    collections = list(get_all_collections(connection))
    if collections:
        return collections[0]
    else:
        raise ItemNotFoundException('No collections found.')


def get_collection_by_alias(connection: DBusConnection,
                            alias: str) -> Collection:
    """Returns the collection with the given `alias`. If there is no
    such collection, raises
    :exc:`~secretstorage.exceptions.ItemNotFoundException`."""
    service = DBusAddressWrapper(SS_PATH, SERVICE_IFACE, connection)
    collection_path, = service.call('ReadAlias', 's', alias)
    if len(collection_path) <= 1:
        raise ItemNotFoundException('No collection with such alias.')
    return Collection(connection, collection_path)


def search_items(connection: DBusConnection,
                 attributes: dict[str, str]) -> Iterator[Item]:
    """Returns a generator of items in all collections with the given
    attributes. `attributes` should be a dictionary."""
    service = DBusAddressWrapper(SS_PATH, SERVICE_IFACE, connection)
    locked, unlocked = service.call('SearchItems', 'a{ss}', attributes)
    for item_path in locked + unlocked:
        yield Item(connection, item_path)
