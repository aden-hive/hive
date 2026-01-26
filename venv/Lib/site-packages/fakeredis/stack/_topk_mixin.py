from typing import Any, List, Optional, Tuple, Dict

from fakeredis import _msgs as msgs
from fakeredis._command_args_parsing import extract_args
from fakeredis._commands import Key, Int, Float, command, CommandItem
from fakeredis._helpers import OK, SimpleError, SimpleString
from fakeredis.model import HeavyKeeper


class TopkCommandsMixin:
    """`CommandsMixin` for enabling TopK compatibility in `fakeredis`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)

    @command(name="TOPK.ADD", fixed=(Key(HeavyKeeper), bytes), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def topk_add(self, key: CommandItem, *args: bytes) -> List[Optional[bytes]]:
        if key.value is None:
            raise SimpleError("TOPK: key does not exist")
        if not isinstance(key.value, HeavyKeeper):
            raise SimpleError("TOPK: key is not a HeavyKeeper")
        res = [key.value.add(_item, 1) for _item in args]
        key.updated()
        return res

    @command(name="TOPK.COUNT", fixed=(Key(HeavyKeeper), bytes), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def topk_count(self, key: CommandItem, *args: bytes) -> List[int]:
        if key.value is None:
            raise SimpleError("TOPK: key does not exist")
        if not isinstance(key.value, HeavyKeeper):
            raise SimpleError("TOPK: key is not a HeavyKeeper")
        res: List[int] = [key.value.count(_item) for _item in args]
        return res

    @command(name="TOPK.QUERY", fixed=(Key(HeavyKeeper), bytes), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def topk_query(self, key: CommandItem, *args: bytes) -> List[int]:
        if key.value is None:
            raise SimpleError("TOPK: key does not exist")
        if not isinstance(key.value, HeavyKeeper):
            raise SimpleError("TOPK: key is not a HeavyKeeper")
        topk = {item[1] for item in key.value.list()}
        res: List[int] = [1 if _item in topk else 0 for _item in args]
        return res

    @command(name="TOPK.INCRBY", fixed=(Key(), bytes, Int), repeat=(bytes, Int), flags=msgs.FLAG_DO_NOT_CREATE)
    def topk_incrby(self, key: CommandItem, *args: Any) -> List[Optional[bytes]]:
        if key.value is None:
            raise SimpleError("TOPK: key does not exist")
        if not isinstance(key.value, HeavyKeeper):
            raise SimpleError("TOPK: key is not a HeavyKeeper")
        if len(args) % 2 != 0:
            raise SimpleError("TOPK: number of arguments must be even")
        res = []
        for i in range(0, len(args), 2):
            val, count = args[i], int(args[i + 1])
            res.append(key.value.add(val, count))
        key.updated()
        return res

    @command(name="TOPK.INFO", fixed=(Key(),), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE)
    def topk_info(self, key: CommandItem) -> Dict[bytes, Any]:
        if key.value is None:
            raise SimpleError("TOPK: key does not exist")
        if not isinstance(key.value, HeavyKeeper):
            raise SimpleError("TOPK: key is not a HeavyKeeper")
        return {
            b"k": key.value.k,
            b"width": key.value.width,
            b"depth": key.value.depth,
            b"decay": key.value.decay,
        }

    @command(name="TOPK.LIST", fixed=(Key(),), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def topk_list(self, key: CommandItem, *args: Any) -> List[Any]:
        (withcount,), _ = extract_args(args, ("withcount",))
        if key.value is None:
            raise SimpleError("TOPK: key does not exist")
        if not isinstance(key.value, HeavyKeeper):
            raise SimpleError("TOPK: key is not a HeavyKeeper")
        value_list: List[Tuple[int, bytes]] = key.value.list()
        if not withcount:
            return [item[1] for item in value_list]
        else:
            temp = [[item[1], item[0]] for item in value_list]
            return [item for sublist in temp for item in sublist]

    @command(name="TOPK.RESERVE", fixed=(Key(), Int), repeat=(Int, Int, Float), flags=msgs.FLAG_DO_NOT_CREATE)
    def topk_reserve(self, key: CommandItem, topk: int, *args: Any) -> SimpleString:
        if len(args) == 3:
            width, depth, decay = args
        else:
            width, depth, decay = 8, 7, 0.9
        if key.value is not None:
            raise SimpleError("TOPK: key already set")
        key.update(HeavyKeeper(topk, width, depth, decay))
        return OK
