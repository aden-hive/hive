# SecretStorage module for Python
# Access passwords using the SecretService DBus API
# Author: Dmitry Shachnev, 2012-2018
# License: 3-clause BSD, see LICENSE file

"""All secretstorage functions may raise various exceptions when
something goes wrong. All exceptions derive from base
:exc:`SecretStorageException` class."""


class SecretStorageException(Exception):
    """All exceptions derive from this class."""


class SecretServiceNotAvailableException(SecretStorageException):
    """Raised by :class:`~secretstorage.item.Item` or
    :class:`~secretstorage.collection.Collection` constructors, or by
    other functions in the :mod:`secretstorage.collection` module, when
    the Secret Service API is not available."""


class LockedException(SecretStorageException):
    """Raised when an action cannot be performed because the collection
    is locked. Use :meth:`~secretstorage.collection.Collection.is_locked`
    to check if the collection is locked, and
    :meth:`~secretstorage.collection.Collection.unlock` to unlock it.
    """


class ItemNotFoundException(SecretStorageException):
    """Raised when an item does not exist or has been deleted. Example of
    handling:

    >>> import secretstorage
    >>> connection = secretstorage.dbus_init()
    >>> item_path = '/not/existing/path'
    >>> try:
    ...     item = secretstorage.Item(connection, item_path)
    ... except secretstorage.ItemNotFoundException:
    ...     print('Item not found!')
    ...
    Item not found!
    """


class PromptDismissedException(ItemNotFoundException):
    """Raised when a prompt was dismissed by the user.

    .. versionadded:: 3.1
    """
