from typing import Optional, Set, Any

from fakeredis.commands_mixins import (
    BitmapCommandsMixin,
    ConnectionCommandsMixin,
    GenericCommandsMixin,
    GeoCommandsMixin,
    HashCommandsMixin,
    ListCommandsMixin,
    PubSubCommandsMixin,
    ScriptingCommandsMixin,
    ServerCommandsMixin,
    StringCommandsMixin,
    TransactionsCommandsMixin,
    SetCommandsMixin,
    StreamsCommandsMixin,
    AclCommandsMixin,
)
from fakeredis.stack import (
    JSONCommandsMixin,
    BFCommandsMixin,
    CFCommandsMixin,
    CMSCommandsMixin,
    TopkCommandsMixin,
    TDigestCommandsMixin,
    TimeSeriesCommandsMixin,
)
from ._basefakesocket import BaseFakeSocket
from ._server import FakeServer
from .commands_mixins.sortedset_mixin import SortedSetCommandsMixin
from .server_specific_commands import DragonflyCommandsMixin


class FakeSocket(
    BaseFakeSocket,
    GenericCommandsMixin,
    ScriptingCommandsMixin,
    HashCommandsMixin,
    ConnectionCommandsMixin,
    ListCommandsMixin,
    ServerCommandsMixin,
    StringCommandsMixin,
    TransactionsCommandsMixin,
    PubSubCommandsMixin,
    SetCommandsMixin,
    BitmapCommandsMixin,
    SortedSetCommandsMixin,
    StreamsCommandsMixin,
    JSONCommandsMixin,
    GeoCommandsMixin,
    BFCommandsMixin,
    CFCommandsMixin,
    CMSCommandsMixin,
    TopkCommandsMixin,
    TDigestCommandsMixin,
    TimeSeriesCommandsMixin,
    DragonflyCommandsMixin,
    AclCommandsMixin,
):
    def __init__(
        self,
        server: FakeServer,
        db: int,
        lua_modules: Optional[Set[str]] = None,  # noqa: F821
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super(FakeSocket, self).__init__(server, db, *args, lua_modules=lua_modules, **kwargs)
