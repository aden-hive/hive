from typing import List, Dict, Any

from sortedcontainers import SortedList

from fakeredis import _msgs as msgs
from fakeredis._command_args_parsing import extract_args
from fakeredis._commands import command, CommandItem, Int, Key, Float
from fakeredis._helpers import SimpleString, SimpleError, OK, Database


class TDigest(SortedList):
    def __init__(self, compression: int = 100):
        super().__init__()
        self.compression = compression


class TDigestCommandsMixin:
    def __init__(self, *args, **kwargs):
        self._db: Database

    @command(
        name="TDIGEST.CREATE",
        fixed=(Key(TDigest),),
        repeat=(bytes,),
        flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def tdigest_create(self, key: CommandItem, *args: bytes) -> SimpleString:
        if key.value is not None:
            raise SimpleError(msgs.TDIGEST_KEY_EXISTS)
        (compression,), left_args = extract_args(args, ("+compression",))
        if compression is None:
            compression = 100
        key.update(TDigest(compression))
        return OK

    @command(
        name="TDIGEST.RESET",
        fixed=(Key(TDigest),),
        repeat=(),
        flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def tdigest_reset(self, key: CommandItem) -> SimpleString:
        if key.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        key.value.clear()
        return OK

    @command(
        name="TDIGEST.ADD",
        fixed=(Key(TDigest), Float),
        repeat=(Float,),
        flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def tdigest_add(self, key: CommandItem, *values: float) -> SimpleString:
        if key.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        # parsing
        try:
            values_to_add = [float(val) for val in values]
        except ValueError:
            raise SimpleError(msgs.TDIGEST_ERROR_PARSING_VALUE)
        # adding
        key.value.update(values_to_add)
        return OK

    @command(
        name="TDIGEST.MERGE",
        fixed=(Key(TDigest), Int, bytes),
        repeat=(bytes,),
        flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def tdigest_merge(self, dest: CommandItem, numkeys: int, *args: bytes) -> SimpleString:
        if len(args) < numkeys:
            raise SimpleError(msgs.WRONG_ARGS_MSG6.format("tdigest.merge"))
        sources_names = args[:numkeys]
        (compression, override), _ = extract_args(args[numkeys:], ("+compression", "override"))
        sources = [self._db.get(name).value for name in sources_names if name in self._db]
        if len(sources) != len(sources_names):
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)

        if override:
            if dest.value is None:
                compression = compression or max([source.compression for source in sources])
                dest.value = TDigest(compression)
            else:
                dest.value.clear()
        if dest.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        for source in sources:
            dest.value.update(source)
        dest.updated()
        return OK

    @command(
        name="TDIGEST.MAX", fixed=(Key(TDigest),), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL
    )
    def tdigest_max(self, key: CommandItem) -> float:
        if key.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        if len(key.value) == 0:
            return float("nan")
        return key.value[-1]

    @command(
        name="TDIGEST.MIN", fixed=(Key(TDigest),), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL
    )
    def tdigest_min(self, key: CommandItem) -> float:
        if key.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        if len(key.value) == 0:
            return float("nan")
        return key.value[0]

    @command(
        name="TDIGEST.RANK",
        fixed=(Key(TDigest), Float),
        repeat=(Float,),
        flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def tdigest_rank(self, key: CommandItem, *values: float) -> List[int]:
        if key.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        if len(key.value) == 0:
            return [
                -2,
            ]
        res = []
        for v in values:
            if v > key.value[-1]:
                res.append(len(key.value))
            else:
                res.append(key.value.bisect_right(v) - 1)
        return res

    @command(
        name="TDIGEST.REVRANK",
        fixed=(Key(TDigest), Float),
        repeat=(Float,),
        flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def tdigest_revrank(self, key: CommandItem, *values: float) -> List[int]:
        if key.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        if len(key.value) == 0:
            return [-2]
        res = []
        length = len(key.value)
        for v in values:
            loc = key.value.bisect_right(v)
            if loc == length:
                loc += 1
            res.append(length - loc)
        return res

    @command(
        name="TDIGEST.QUANTILE",
        fixed=(Key(TDigest), Float),
        repeat=(Float,),
        flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def tdigest_quantile(self, key: CommandItem, *quantiles: float) -> List[float]:
        if key.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        if len(key.value) <= 1:
            return [float("nan")]
        res: List[float] = []
        for q in quantiles:
            if q < 0 or q > 1:
                raise SimpleError(msgs.TDIGEST_BAD_QUANTILE)
            ind = int(q * len(key.value))
            if ind == len(key.value):
                ind -= 1
            res.append(key.value[ind])
        return res

    @command(
        name="TDIGEST.CDF",
        fixed=(Key(TDigest), Float),
        repeat=(Float,),
        flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def tdigest_cdf(self, key: CommandItem, *values: float) -> List[float]:  # Cumulative Distribution Function
        """Returns, for each input value, an estimation of the fraction (floating-point) of
        (observations smaller than the given value + half the observations equal to the given value).
        """
        if key.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        res: List[float] = []
        for v in values:
            left = key.value.bisect_left(v)
            right = key.value.bisect_right(v)
            if right == 0:
                res.append(0.0)
            elif left == len(key.value):
                res.append(1.0)
            else:
                res.append(float((left + right) / 2) / len(key.value))
        return res

    @command(
        name="TDIGEST.INFO", fixed=(Key(TDigest),), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL
    )
    def tdigest_info(self, key: CommandItem) -> Dict[bytes, Any]:
        return {
            b"Compression": key.value.compression,
            b"Capacity": len(key.value),
            b"Merged nodes": len(key.value),
            b"Unmerged nodes": 0,
            b"Merged weight": len(key.value),
            b"Unmerged weight": 0,
            b"Observations": len(key.value),
            b"Total compressions": len(key.value),
            b"Memory usage": len(key.value),
        }

    @command(
        name="TDIGEST.TRIMMED_MEAN",
        fixed=(Key(TDigest), Float, Float),
        repeat=(),
        flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def tdigest_trimmed_mean(self, key: CommandItem, lower: float, upper: float) -> float:
        if key.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        if lower < 0 or upper > 1 or lower > upper:
            raise SimpleError(msgs.TDIGEST_BAD_QUANTILE)
        if len(key.value) == 0:
            return float("nan")
        left = int(lower * len(key.value))
        right = int(upper * len(key.value))
        res = key.value[(left + right) // 2]
        if right == left + 1:
            res = (res + key.value[right]) / 2
        return res

    @command(
        name="TDIGEST.BYRANK",
        fixed=(Key(TDigest), Int),
        repeat=(Int,),
        flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def tdigest_byrank(self, key: CommandItem, *ranks: int) -> List[float]:
        if key.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        if len(key.value) == 0:
            return [float("nan")]
        res: List[float] = []
        for rank in ranks:
            if rank < 0:
                raise SimpleError(msgs.TDIGEST_BAD_RANK)
            if rank >= len(key.value):
                res.append(float("inf"))
            else:
                res.append(key.value[rank])
        return res

    @command(
        name="TDIGEST.BYREVRANK",
        fixed=(Key(TDigest), Int),
        repeat=(Int,),
        flags=msgs.FLAG_DO_NOT_CREATE + msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def tdigest_byrevrank(self, key: CommandItem, *ranks: int) -> List[float]:
        if key.value is None:
            raise SimpleError(msgs.TDIGEST_KEY_NOT_EXISTS)
        if len(key.value) == 0:
            return [float("nan")]
        res: List[float] = []
        for rank in ranks:
            if rank < 0:
                raise SimpleError(msgs.TDIGEST_BAD_RANK)
            if rank >= len(key.value):
                res.append(float("-inf"))
            else:
                res.append(key.value[-rank - 1])
        return res
