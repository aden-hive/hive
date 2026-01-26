"""Command mixin for emulating `redis-py`'s BF functionality."""

from typing import Any, List, Union, Dict

from probables import ExpandingBloomFilter

from fakeredis import _msgs as msgs
from fakeredis._command_args_parsing import extract_args
from fakeredis._commands import command, Key, CommandItem, Float, Int
from fakeredis._helpers import SimpleError, OK, casematch, SimpleString


class ScalableBloomFilter(ExpandingBloomFilter):
    NO_GROWTH = 0

    def __init__(self, capacity: int = 100, error_rate: float = 0.001, scale: int = 2):
        super().__init__(capacity, error_rate)
        self.scale: int = scale

    def add_item(self, key: bytes) -> bool:
        if key in self:
            return True
        if self.scale == self.NO_GROWTH and self.elements_added >= self.estimated_elements:
            raise SimpleError(msgs.FILTER_FULL_MSG)
        super(ScalableBloomFilter, self).add(key)
        return False

    @classmethod
    def bf_frombytes(cls, b: bytes, **kwargs: Any) -> "ScalableBloomFilter":
        size, est_els, added_els, fpr = cls._parse_footer(b)
        blm = ScalableBloomFilter(capacity=est_els, error_rate=fpr)
        blm._parse_blooms(b, size)
        blm._added_elements = added_els
        return blm


class BFCommandsMixin:
    @staticmethod
    def _bf_add(key: CommandItem, item: bytes) -> int:
        res = key.value.add_item(item)
        key.updated()
        return 0 if res else 1

    @staticmethod
    def _bf_exist(key: CommandItem, item: bytes) -> int:
        return 1 if (item in key.value) else 0

    @command(name="BF.ADD", fixed=(Key(ScalableBloomFilter), bytes), repeat=())
    def bf_add(self, key: CommandItem, value: bytes) -> int:
        return BFCommandsMixin._bf_add(key, value)

    @command(name="BF.CARD", fixed=(Key(ScalableBloomFilter),), repeat=())
    def bf_card(self, key: CommandItem) -> int:
        return key.value.elements_added  # type:ignore

    @command(name="BF.MADD", fixed=(Key(ScalableBloomFilter), bytes), repeat=(bytes,))
    def bf_madd(self, key: CommandItem, *values: bytes) -> List[int]:
        res = [BFCommandsMixin._bf_add(key, value) for value in values]
        return res

    @command(name="BF.EXISTS", fixed=(Key(ScalableBloomFilter), bytes), repeat=())
    def bf_exist(self, key: CommandItem, value: bytes) -> int:
        return BFCommandsMixin._bf_exist(key, value)

    @command(name="BF.MEXISTS", fixed=(Key(ScalableBloomFilter), bytes), repeat=(bytes,))
    def bf_mexists(self, key: CommandItem, *values: bytes) -> List[int]:
        res = [BFCommandsMixin._bf_exist(key, value) for value in values]
        return res

    @command(
        name="BF.RESERVE",
        fixed=(
            Key(),
            Float,
            Int,
        ),
        repeat=(bytes,),
        flags=msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def bf_reserve(self, key: CommandItem, error_rate: float, capacity: int, *args: bytes) -> SimpleString:
        if key.value is not None:
            raise SimpleError(msgs.ITEM_EXISTS_MSG)
        (expansion, non_scaling), _ = extract_args(args, ("+expansion", "nonscaling"))
        if expansion is not None and non_scaling:
            raise SimpleError(msgs.NONSCALING_FILTERS_CANNOT_EXPAND_MSG)
        if expansion is None:
            expansion = 2
        scale = ScalableBloomFilter.NO_GROWTH if non_scaling else expansion
        key.update(ScalableBloomFilter(capacity, error_rate, scale))
        return OK

    @command(name="BF.INSERT", fixed=(Key(),), repeat=(bytes,))
    def bf_insert(self, key: CommandItem, *args: bytes) -> List[int]:
        (capacity, error_rate, expansion, non_scaling, no_create), left_args = extract_args(
            args,
            ("+capacity", ".error", "+expansion", "nonscaling", "nocreate"),
            error_on_unexpected=False,
            left_from_first_unexpected=True,
        )
        # if no_create and (capacity is not None or error_rate is not None):
        #     raise SimpleError("...")
        if len(left_args) < 2 or not casematch(left_args[0], b"items"):
            raise SimpleError("...")
        items = left_args[1:]

        error_rate = error_rate or 0.001
        capacity = capacity or 100
        if key.value is None and no_create:
            raise SimpleError(msgs.NOT_FOUND_MSG)
        if expansion is not None and non_scaling:
            raise SimpleError(msgs.NONSCALING_FILTERS_CANNOT_EXPAND_MSG)
        if expansion is None:
            expansion = 2
        scale = ScalableBloomFilter.NO_GROWTH if non_scaling else expansion
        if key.value is None:
            key.value = ScalableBloomFilter(capacity, error_rate, scale)
        res = [self._bf_add(key, item) for item in items]
        key.updated()
        return res

    @command(name="BF.INFO", fixed=(Key(),), repeat=(bytes,))
    def bf_info(self, key: CommandItem, *args: bytes) -> Union[Any, Dict[bytes, Any]]:
        if key.value is None or type(key.value) is not ScalableBloomFilter:
            raise SimpleError("...")
        if len(args) > 1:
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        if len(args) == 0:
            return {
                b"Capacity": key.value.estimated_elements,
                b"Size": key.value.elements_added,
                b"Number of filters": key.value.expansions + 1,
                b"Number of items inserted": key.value.elements_added,
                b"Expansion rate": key.value.scale if key.value.scale > 0 else None,
            }
        if casematch(args[0], b"CAPACITY"):
            return key.value.estimated_elements
        elif casematch(args[0], b"SIZE"):
            return key.value.estimated_elements
        elif casematch(args[0], b"FILTERS"):
            return key.value.expansions + 1
        elif casematch(args[0], b"ITEMS"):
            return key.value.elements_added
        elif casematch(args[0], b"EXPANSION"):
            return key.value.expansions if key.value.expansions > 0 else None
        else:
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)

    @command(name="BF.SCANDUMP", fixed=(Key(), Int), repeat=(), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def bf_scandump(self, key: CommandItem, iterator: int) -> List[Any]:
        if key.value is None:
            raise SimpleError(msgs.NOT_FOUND_MSG)

        if iterator == 0:
            s = bytes(key.value)
            return [1, s]
        else:
            return [0, None]

    @command(name="BF.LOADCHUNK", fixed=(Key(), Int, bytes), repeat=(), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def bf_loadchunk(self, key: CommandItem, iterator: int, data: bytes) -> SimpleString:
        if key.value is not None and type(key.value) is not ScalableBloomFilter:
            raise SimpleError(msgs.NOT_FOUND_MSG)
        key.update(ScalableBloomFilter.bf_frombytes(data))
        return OK
