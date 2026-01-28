from typing import Any

from .acl_mixin import AclCommandsMixin
from .bitmap_mixin import BitmapCommandsMixin
from .connection_mixin import ConnectionCommandsMixin
from .generic_mixin import GenericCommandsMixin
from .geo_mixin import GeoCommandsMixin
from .hash_mixin import HashCommandsMixin
from .list_mixin import ListCommandsMixin
from .pubsub_mixin import PubSubCommandsMixin
from .server_mixin import ServerCommandsMixin
from .set_mixin import SetCommandsMixin
from .streams_mixin import StreamsCommandsMixin
from .string_mixin import StringCommandsMixin
from .transactions_mixin import TransactionsCommandsMixin

try:
    from .scripting_mixin import ScriptingCommandsMixin
except ImportError:

    class ScriptingCommandsMixin:  # type: ignore  # noqa: E303
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs.pop("lua_modules", None)
            self.server_supports_lua_scripts = False
            super(ScriptingCommandsMixin, self).__init__(*args, **kwargs)  # type: ignore


__all__ = [
    "BitmapCommandsMixin",
    "ConnectionCommandsMixin",
    "GenericCommandsMixin",
    "GeoCommandsMixin",
    "HashCommandsMixin",
    "ListCommandsMixin",
    "PubSubCommandsMixin",
    "ScriptingCommandsMixin",
    "TransactionsCommandsMixin",
    "ServerCommandsMixin",
    "SetCommandsMixin",
    "StreamsCommandsMixin",
    "StringCommandsMixin",
    "AclCommandsMixin",
]
