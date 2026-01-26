"""Command mixin for emulating `redis-py`'s cuckoo filter functionality."""

import io
from typing import List, Any, Dict

from probables import CountingCuckooFilter, CuckooFilterFullError

from fakeredis import _msgs as msgs
from fakeredis._command_args_parsing import extract_args
from fakeredis._commands import command, CommandItem, Int, Key
from fakeredis._helpers import SimpleError, OK, casematch, SimpleString


class ScalableCuckooFilter(CountingCuckooFilter):
    def __init__(self, capacity: int, bucket_size: int = 2, max_iterations: int = 20, expansion: int = 1):
        super().__init__(capacity, bucket_size, max_iterations, expansion)
        self.initial_capacity: int = capacity
        self.inserted: int = 0
        self.deleted: int = 0

    def insert(self, item: bytes) -> bool:
        try:
            super().add(item)
        except CuckooFilterFullError:
            return False
        self.inserted += 1
        return True

    def count(self, item: bytes) -> int:
        return super().check(item)

    def delete(self, item: bytes) -> bool:
        if super().remove(item):
            self.deleted += 1
            return True
        return False


class CFCommandsMixin:
    @staticmethod
    def _cf_add(key: CommandItem, item: bytes) -> int:
        if key.value is None:
            key.update(ScalableCuckooFilter(1024))
        res = key.value.insert(item)  # type:ignore
        key.updated()
        return 1 if res else 0

    @staticmethod
    def _cf_exist(key: CommandItem, item: bytes) -> int:
        return 1 if (key.value is not None and item in key.value) else 0

    @command(name="CF.ADD", fixed=(Key(ScalableCuckooFilter), bytes), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE)
    def cf_add(self, key: CommandItem, value: bytes) -> int:
        return CFCommandsMixin._cf_add(key, value)

    @command(name="CF.ADDNX", fixed=(Key(ScalableCuckooFilter), bytes), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE)
    def cf_addnx(self, key: CommandItem, value: bytes) -> int:
        if value in key.value:
            return 0
        return CFCommandsMixin._cf_add(key, value)

    @command(name="CF.COUNT", fixed=(Key(ScalableCuckooFilter), bytes), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE)
    def cf_count(self, key: CommandItem, item: bytes) -> int:
        if key.value is None:
            return 0
        if type(key.value) is not ScalableCuckooFilter:
            raise SimpleError(msgs.WRONGTYPE_MSG)
        return key.value.count(item)

    @command(name="CF.DEL", fixed=(Key(ScalableCuckooFilter), bytes), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE)
    def cf_del(self, key: CommandItem, value: bytes) -> int:
        if key.value is None:
            raise SimpleError(msgs.NOT_FOUND_MSG)
        res = key.value.delete(value)
        return 1 if res else 0

    @command(name="CF.EXISTS", fixed=(Key(ScalableCuckooFilter), bytes), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE)
    def cf_exist(self, key: CommandItem, value: bytes) -> int:
        return CFCommandsMixin._cf_exist(key, value)

    @command(name="CF.INFO", fixed=(Key(),), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE)
    def cf_info(self, key: CommandItem) -> Dict[bytes, Any]:
        if key.value is None or type(key.value) is not ScalableCuckooFilter:
            raise SimpleError("...")
        return {
            b"Size": key.value.capacity,
            b"Number of buckets": len(key.value.buckets),
            b"Number of filters": int((key.value.capacity / key.value.initial_capacity) / key.value.expansion_rate),
            b"Number of items inserted": key.value.inserted,
            b"Number of items deleted": key.value.deleted,
            b"Bucket size": key.value.bucket_size,
            b"Max iterations": key.value.max_swaps,
            b"Expansion rate": key.value.expansion_rate,
        }

    @command(name="CF.INSERT", fixed=(Key(),), repeat=(bytes,))
    def cf_insert(self, key: CommandItem, *args: bytes) -> List[int]:
        (capacity, no_create), left_args = extract_args(
            args, ("+capacity", "nocreate"), error_on_unexpected=False, left_from_first_unexpected=True
        )
        # if no_create and (capacity is not None or error_rate is not None):
        #     raise SimpleError("...")
        if len(left_args) < 2 or not casematch(left_args[0], b"items"):
            raise SimpleError("...")
        items = left_args[1:]
        capacity = capacity or 1024

        if key.value is None and no_create:
            raise SimpleError(msgs.NOT_FOUND_MSG)
        if key.value is None:
            key.value = ScalableCuckooFilter(capacity)
        res = [self._cf_add(key, item) for item in items]
        key.updated()
        return res

    @command(name="CF.INSERTNX", fixed=(Key(),), repeat=(bytes,))
    def cf_insertnx(self, key: CommandItem, *args: bytes) -> List[int]:
        (capacity, no_create), left_args = extract_args(
            args, ("+capacity", "nocreate"), error_on_unexpected=False, left_from_first_unexpected=True
        )
        # if no_create and (capacity is not None or error_rate is not None):
        #     raise SimpleError("...")
        if len(left_args) < 2 or not casematch(left_args[0], b"items"):
            raise SimpleError("...")
        items = left_args[1:]
        capacity = capacity or 1024
        if key.value is None and no_create:
            raise SimpleError(msgs.NOT_FOUND_MSG)
        if key.value is None:
            key.value = ScalableCuckooFilter(capacity)
        res = []
        for item in items:
            if item in key.value:
                res.append(0)
            else:
                res.append(self._cf_add(key, item))
        key.updated()
        return res

    @command(name="CF.MEXISTS", fixed=(Key(ScalableCuckooFilter), bytes), repeat=(bytes,))
    def cf_mexists(self, key: CommandItem, *values: bytes) -> List[int]:
        res = [CFCommandsMixin._cf_exist(key, value) for value in values]
        return res

    @command(name="CF.RESERVE", fixed=(Key(), Int), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def cf_reserve(self, key: CommandItem, capacity: int, *args: bytes) -> SimpleString:
        if key.value is not None:
            raise SimpleError(msgs.ITEM_EXISTS_MSG)
        (bucket_size, max_iterations, expansion), _ = extract_args(
            args, ("+bucketsize", "+maxiterations", "+expansion")
        )

        max_iterations = max_iterations or 20
        bucket_size = bucket_size or 2
        value = ScalableCuckooFilter(capacity, bucket_size=bucket_size, max_iterations=max_iterations)
        key.update(value)
        return OK

    @command(name="CF.SCANDUMP", fixed=(Key(), Int), repeat=(), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def cf_scandump(self, key: CommandItem, iterator: int) -> List[Any]:
        if key.value is None:
            raise SimpleError(msgs.NOT_FOUND_MSG)
        f = io.BytesIO()

        if iterator == 0:
            key.value.tofile(f)
            f.seek(0)
            s = f.read()
            f.close()
            return [1, s]
        else:
            return [0, None]

    @command(name="CF.LOADCHUNK", fixed=(Key(), Int, bytes), repeat=(), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def cf_loadchunk(self, key: CommandItem, _: int, data: bytes) -> SimpleString:
        if key.value is not None and type(key.value) is not ScalableCuckooFilter:
            raise SimpleError(msgs.NOT_FOUND_MSG)
        key.value = ScalableCuckooFilter.frombytes(data)
        key.updated()
        return OK
