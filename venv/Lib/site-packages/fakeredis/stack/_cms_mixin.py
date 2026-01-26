"""Command mixin for emulating `redis-py`'s Count-min sketch functionality."""

from typing import Optional, Tuple, List, Any, Dict

import probables

from fakeredis import _msgs as msgs
from fakeredis._commands import command, CommandItem, Int, Key, Float
from fakeredis._helpers import OK, SimpleString, SimpleError, casematch, Database


class CountMinSketch(probables.CountMinSketch):
    def __init__(
        self,
        width: Optional[int] = None,
        depth: Optional[int] = None,
        probability: Optional[float] = None,
        error_rate: Optional[float] = None,
    ):
        super().__init__(width=width, depth=depth, error_rate=error_rate, confidence=probability)


class CMSCommandsMixin:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._db: Database

    @command(
        name="CMS.INCRBY",
        fixed=(Key(CountMinSketch), bytes, bytes),
        repeat=(bytes, bytes),
        flags=msgs.FLAG_DO_NOT_CREATE,
    )
    def cms_incrby(self, key: CommandItem, *args: bytes) -> List[Tuple[bytes, int]]:
        if key.value is None:
            raise SimpleError("CMS: key does not exist")
        pairs: List[Tuple[bytes, int]] = []
        for i in range(0, len(args), 2):
            try:
                pairs.append((args[i], int(args[i + 1])))
            except ValueError:
                raise SimpleError("CMS: Cannot parse number")
        res = [key.value.add(pair[0], pair[1]) for pair in pairs]
        key.updated()
        return res

    @command(name="CMS.INFO", fixed=(Key(CountMinSketch),), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE)
    def cms_info(self, key: CommandItem) -> Dict[bytes, Any]:
        if key.value is None:
            raise SimpleError("CMS: key does not exist")
        return {
            b"width": key.value.width,
            b"depth": key.value.depth,
            b"count": key.value.elements_added,
        }

    @command(name="CMS.INITBYDIM", fixed=(Key(CountMinSketch), Int, Int), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE)
    def cms_initbydim(self, key: CommandItem, width: int, depth: int) -> SimpleString:
        if key.value is not None:
            raise SimpleError("CMS key already set")
        if width < 1:
            raise SimpleError("CMS: invalid width")
        if depth < 1:
            raise SimpleError("CMS: invalid depth")
        key.update(CountMinSketch(width=width, depth=depth))
        return OK

    @command(name="CMS.INITBYPROB", fixed=(Key(CountMinSketch), Float, Float), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE)
    def cms_initby_prob(self, key: CommandItem, error_rate: float, probability: float) -> SimpleString:
        if key.value is not None:
            raise SimpleError("CMS key already set")
        if error_rate <= 0 or error_rate >= 1:
            raise SimpleError("CMS: invalid overestimation value")
        if probability <= 0 or probability >= 1:
            raise SimpleError("CMS: invalid prob value")
        key.update(CountMinSketch(probability=probability, error_rate=error_rate))
        return OK

    @command(name="CMS.MERGE", fixed=(Key(CountMinSketch), Int, bytes), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def cms_merge(self, dest_key: CommandItem, num_keys: int, *args: bytes) -> SimpleString:
        if dest_key.value is None:
            raise SimpleError("CMS: key does not exist")

        if num_keys < 1:
            raise SimpleError("CMS: Number of keys must be positive")
        weights = [
            1,
        ]
        for i, arg in enumerate(args):
            if casematch(b"weights", arg):
                weights = [int(i) for i in args[i + 1 :]]
                if len(weights) != num_keys:
                    raise SimpleError("CMS: wrong number of keys/weights")
                args = args[:i]
                break
        dest_key.value.clear()
        for i, arg in enumerate(args):
            item = self._db.get(arg, None)
            if item is None or not isinstance(item.value, CountMinSketch):
                raise SimpleError("CMS: key does not exist")
            for _ in range(weights[i % len(weights)]):
                dest_key.value.join(item.value)
        return OK

    @command(name="CMS.QUERY", fixed=(Key(CountMinSketch), bytes), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def cms_query(self, key: CommandItem, *items: bytes) -> List[int]:
        if key.value is None:
            raise SimpleError("CMS: key does not exist")
        return [key.value.check(item) for item in items]
