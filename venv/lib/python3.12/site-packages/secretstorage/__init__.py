# SecretStorage module for Python
# Access passwords using the SecretService DBus API
# Author: Dmitry Shachnev, 2013-2020
# License: 3-clause BSD, see LICENSE file

"""This file provides quick access to all SecretStorage API. Please
refer to documentation of individual modules for API details.
"""

from jeepney.bus_messages import message_bus
from jeepney.io.blocking import DBusConnection, Proxy, open_dbus_connection

from secretstorage.collection import (
    Collection,
    create_collection,
    get_all_collections,
    get_any_collection,
    get_collection_by_alias,
    get_default_collection,
    search_items,
)
from secretstorage.exceptions import (
    ItemNotFoundException,
    LockedException,
    PromptDismissedException,
    SecretServiceNotAvailableException,
    SecretStorageException,
)
from secretstorage.item import Item
from secretstorage.util import add_match_rules

__version_tuple__ = (3, 5, 0)
__version__ = '.'.join(map(str, __version_tuple__))

__all__ = [
    'Collection',
    'Item',
    'ItemNotFoundException',
    'LockedException',
    'PromptDismissedException',
    'SecretServiceNotAvailableException',
    'SecretStorageException',
    'check_service_availability',
    'create_collection',
    'dbus_init',
    'get_all_collections',
    'get_any_collection',
    'get_collection_by_alias',
    'get_default_collection',
    'search_items',
]


def dbus_init() -> DBusConnection:
    """Returns a new connection to the session bus, instance of
    jeepney's :class:`DBusConnection` class. This connection can
    then be passed to various SecretStorage functions, such as
    :func:`~secretstorage.collection.get_default_collection`.

    .. warning::
       The D-Bus socket will not be closed automatically. You can
       close it manually using the :meth:`DBusConnection.close` method,
       or you can use the :class:`contextlib.closing` context manager:

       .. code-block:: python

          from contextlib import closing
          with closing(dbus_init()) as conn:
              collection = secretstorage.get_default_collection(conn)
              items = collection.search_items({'application': 'myapp'})

       However, you will not be able to call any methods on the objects
       created within the context after you leave it.

    .. versionchanged:: 3.0
       Before the port to Jeepney, this function returned an
       instance of :class:`dbus.SessionBus` class.

    .. versionchanged:: 3.1
       This function no longer accepts any arguments.
    """
    try:
        connection = open_dbus_connection()
        add_match_rules(connection)
        return connection
    except KeyError as ex:
        # os.environ['DBUS_SESSION_BUS_ADDRESS'] may raise it
        reason = f"Environment variable {ex.args[0]} is unset"
        raise SecretServiceNotAvailableException(reason) from ex
    except (ConnectionError, ValueError) as ex:
        raise SecretServiceNotAvailableException(str(ex)) from ex


def check_service_availability(connection: DBusConnection) -> bool:
    """Returns True if the Secret Service daemon is either running or
    available for activation via D-Bus, False otherwise.

    .. versionadded:: 3.2
    """
    from secretstorage.util import BUS_NAME
    proxy = Proxy(message_bus, connection)
    return (proxy.NameHasOwner(BUS_NAME)[0] == 1
            or BUS_NAME in proxy.ListActivatableNames()[0])
