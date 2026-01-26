from __future__ import annotations

import functools
import itertools
import random
import sys
from typing import Union, Optional, List, Tuple, Callable, Any, Dict, Sequence

import math

from fakeredis import _msgs as msgs
from fakeredis._command_args_parsing import extract_args
from fakeredis._commands import (
    command,
    Key,
    Int,
    Float,
    CommandItem,
    Timeout,
    ScoreTest,
    StringTest,
    fix_range,
)
from fakeredis._helpers import (
    SimpleError,
    casematch,
    null_terminate,
    Database,
)
from fakeredis.model import ZSet, ExpiringMembersSet, ClientInfo
from fakeredis._typing import VersionType

SORTED_SET_METHODS = {
    "ZUNIONSTORE": lambda s1, s2: s1 | s2,
    "ZUNION": lambda s1, s2: s1 | s2,
    "ZINTERSTORE": lambda s1, s2: s1.intersection(s2),
    "ZINTER": lambda s1, s2: s1.intersection(s2),
    "ZDIFFSTORE": lambda s1, s2: s1 - s2,
    "ZDIFF": lambda s1, s2: s1 - s2,
}


class SortedSetCommandsMixin:
    _blocking: Callable[[Optional[Union[float, int]], Callable[[bool], Any]], Any]
    _scan: Callable[[Sequence[bytes], int, bytes, ...], List[Union[bytes, List[bytes]]]]
    _encodefloat: Callable[[float, bool], bytes]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(SortedSetCommandsMixin, self).__init__(*args, **kwargs)
        self.version: VersionType
        self._db: Database
        self._client_info: ClientInfo

    def _zpop(self, key: CommandItem, count: int, reverse: bool, flatten_list: bool) -> List[List[Any]]:
        zset = key.value
        members = list(zset)
        if reverse:
            members.reverse()
        members = members[:count]
        res = [[bytes(member), zset.get(member)] for member in members]
        if flatten_list and self._client_info.protocol_version == 2:
            res = list(itertools.chain.from_iterable(res))
        for item in members:
            zset.discard(item)
        return res

    def _bzpop(self, keys: List[bytes], reverse: bool, first_pass: bool) -> Optional[List[Union[bytes, List[bytes]]]]:
        for key in keys:
            item = CommandItem(key, self._db, item=self._db.get(key), default=[])
            temp_res = self._zpop(item, 1, reverse, flatten_list=False)
            if temp_res:
                return [key, temp_res[0][0], temp_res[0][1]]
        return None

    @command((Key(ZSet),), (Int,))
    def zpopmin(self, key: CommandItem, count: int = 1) -> List[List[bytes]]:
        return self._zpop(key, count, reverse=False, flatten_list=True)

    @command((Key(ZSet),), (Int,))
    def zpopmax(self, key: CommandItem, count: int = 1) -> List[List[bytes]]:
        return self._zpop(key, count, reverse=True, flatten_list=True)

    @command((bytes, bytes), (bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def bzpopmin(self, *args: bytes) -> Optional[List[List[bytes]]]:
        keys = args[:-1]
        timeout = Timeout.decode(args[-1])
        return self._blocking(timeout, functools.partial(self._bzpop, keys, False))  # type:ignore

    @command((bytes, bytes), (bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def bzpopmax(self, *args: bytes) -> Optional[List[List[bytes]]]:
        keys = args[:-1]
        timeout = Timeout.decode(args[-1])
        return self._blocking(timeout, functools.partial(self._bzpop, keys, True))  # type:ignore

    @staticmethod
    def _limit_items(items: List[bytes], offset: int, count: int) -> List[bytes]:
        out: List[bytes] = []
        for item in items:
            if offset:  # Note: not offset > 0, to match redis
                offset -= 1
                continue
            if count == 0:
                break
            count -= 1
            out.append(item)
        return out

    def _apply_withscores(self, items: List[Tuple[bytes, bytes]], withscores: bool) -> List[Any]:
        if withscores:
            if self._client_info.protocol_version == 2:
                out = []
                for item in items:
                    out.append(item[1])
                    out.append(item[0])
                return out
            return [[item[1], item[0]] for item in items]
        else:
            return [item[1] for item in items]

    @command((Key(ZSet), bytes, bytes), (bytes,))
    def zadd(self, key, *args) -> Union[int, None]:
        zset = key.value

        (nx, xx, ch, incr, gt, lt), left_args = extract_args(
            args,
            ("nx", "xx", "ch", "incr", "gt", "lt"),
            error_on_unexpected=False,
        )

        elements = left_args
        if not elements or len(elements) % 2 != 0:
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        if nx and xx:
            raise SimpleError(msgs.ZADD_NX_XX_ERROR_MSG)
        if [nx, gt, lt].count(True) > 1:
            raise SimpleError(msgs.ZADD_NX_GT_LT_ERROR_MSG)
        if incr and len(elements) != 2:
            raise SimpleError(msgs.ZADD_INCR_LEN_ERROR_MSG)
        # Parse all scores first, before updating
        items = [
            (
                (
                    0.0 + Float.decode(elements[j]) if self.version >= (7,) else Float.decode(elements[j]),
                    elements[j + 1],
                )
            )
            for j in range(0, len(elements), 2)
        ]
        old_len = len(zset)
        changed_items: int = 0

        if incr:
            item_score, item_name = items[0]
            if (nx and item_name in zset) or (xx and item_name not in zset):
                return None
            return self.zincrby(key, item_score, item_name)
        count = [nx, gt, lt, xx].count(True)
        for item_score, item_name in items:
            update = count == 0
            update = update or (count == 1 and nx and item_name not in zset)
            update = update or (count == 1 and xx and item_name in zset)
            update = update or (
                gt and ((item_name in zset and zset.get(item_name) < item_score) or (not xx and item_name not in zset))
            )
            update = update or (
                lt and ((item_name in zset and zset.get(item_name) > item_score) or (not xx and item_name not in zset))
            )

            if update:
                if zset.add(item_name, item_score):
                    changed_items += 1

        if changed_items:
            key.updated()

        if ch:
            return changed_items
        return len(zset) - old_len

    @command((Key(ZSet),))
    def zcard(self, key):
        return len(key.value)

    @command((Key(ZSet), ScoreTest, ScoreTest))
    def zcount(self, key, _min, _max):
        return key.value.zcount(_min.lower_bound, _max.upper_bound)

    @command((Key(ZSet), Float, bytes))
    def zincrby(self, key: CommandItem, increment: float, member: bytes) -> float:
        # Can't just default the old score to 0.0, because in IEEE754, adding
        # 0.0 to something isn't a nop (e.g., 0.0 + -0.0 == 0.0).
        try:
            score = key.value.get(member, None) + increment
        except TypeError:
            score = increment
        if math.isnan(score):
            raise SimpleError(msgs.SCORE_NAN_MSG)
        key.value[member] = score
        key.updated()
        return score

    @command((Key(ZSet), StringTest, StringTest))
    def zlexcount(self, key, _min, _max):
        return key.value.zlexcount(_min.value, _min.exclusive, _max.value, _max.exclusive)

    def _zrangebyscore(self, key, _min, _max, reverse, withscores, offset, count: int) -> List[bytes]:
        zset = key.value
        if reverse:
            _min, _max = _max, _min
        items = list(zset.irange_score(_min.lower_bound, _max.upper_bound, reverse=reverse))
        items = self._limit_items(items, offset, count)
        items = self._apply_withscores(items, withscores)
        return items

    def _zrange(
        self, key: CommandItem, start: ScoreTest, stop: ScoreTest, reverse: bool, withscores: bool, byscore: bool
    ) -> List[bytes]:
        zset = key.value
        if byscore:
            items = zset.irange_score(start.lower_bound, stop.upper_bound, reverse=reverse)
        else:
            start, stop = Int.decode(start.bytes_val), Int.decode(stop.bytes_val)
            start, stop = fix_range(start, stop, len(zset))
            if reverse:
                start, stop = len(zset) - stop, len(zset) - start
            items = zset.islice_score(start, stop, reverse)
        items = self._apply_withscores(items, withscores)
        return items

    def _zrangebylex(self, key, _min, _max, reverse, offset, count) -> List[bytes]:
        zset = key.value
        if reverse:
            _min, _max = _max, _min
        items = zset.irange_lex(
            _min.value,
            _max.value,
            inclusive=(not _min.exclusive, not _max.exclusive),
            reverse=reverse,
        )
        items = self._limit_items(items, offset, count)
        return items

    def _zrange_args(self, key: CommandItem, start: bytes, stop: bytes, *args: bytes):
        (bylex, byscore, rev, (offset, count), withscores), _ = extract_args(
            args, ("bylex", "byscore", "rev", "++limit", "withscores")
        )
        if offset is not None and not bylex and not byscore:
            raise SimpleError(msgs.SYNTAX_ERROR_LIMIT_ONLY_WITH_MSG)
        if bylex and byscore:
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)

        offset = offset or 0
        count = -1 if count is None else count

        if bylex:
            res = self._zrangebylex(key, StringTest.decode(start), StringTest.decode(stop), rev, offset, count)
        elif byscore:
            res = self._zrangebyscore(
                key, ScoreTest.decode(start), ScoreTest.decode(stop), rev, withscores, offset, count
            )
        else:
            res = self._zrange(key, ScoreTest.decode(start), ScoreTest.decode(stop), rev, withscores, byscore)
        return res

    @command((Key(ZSet), bytes, bytes), (bytes,))
    def zrange(self, key, start, stop, *args):
        return self._zrange_args(key, start, stop, *args)

    @command((Key(ZSet), Key(ZSet), bytes, bytes), (bytes,))
    def zrangestore(self, dest: CommandItem, src, start, stop, *args):
        results_list = self._zrange_args(src, start, stop, *args)
        res = ZSet()
        for item in results_list:
            res.add(item, src.value.get(item))
        dest.update(res)
        return len(res)

    @command((Key(ZSet), ScoreTest, ScoreTest), (bytes,))
    def zrevrange(self, key: CommandItem, start: ScoreTest, stop: ScoreTest, *args):
        (withscores, byscore), _ = extract_args(args, ("withscores", "byscore"))
        return self._zrange(key, start, stop, True, withscores, byscore)

    @command((Key(ZSet), StringTest, StringTest), (bytes,))
    def zrangebylex(self, key, _min, _max, *args):
        ((offset, count),), _ = extract_args(args, ("++limit",))
        offset = offset or 0
        count = -1 if count is None else count
        return self._zrangebylex(key, _min, _max, False, offset, count)

    @command((Key(ZSet), StringTest, StringTest), (bytes,))
    def zrevrangebylex(self, key, _min, _max, *args):
        ((offset, count),), _ = extract_args(args, ("++limit",))
        offset = offset or 0
        count = -1 if count is None else count
        return self._zrangebylex(key, _min, _max, True, offset, count)

    @command((Key(ZSet), ScoreTest, ScoreTest), (bytes,))
    def zrangebyscore(self, key, _min, _max, *args):
        (withscores, (offset, count)), _ = extract_args(args, ("withscores", "++limit"))
        offset = offset or 0
        count = -1 if count is None else count
        return self._zrangebyscore(key, _min, _max, False, withscores, offset, count)

    @command((Key(ZSet), ScoreTest, ScoreTest), (bytes,))
    def zrevrangebyscore(self, key, _min, _max, *args):
        (withscores, (offset, count)), _ = extract_args(args, ("withscores", "++limit"))
        offset = offset or 0
        count = -1 if count is None else count
        return self._zrangebyscore(key, _min, _max, True, withscores, offset, count)

    @command(name="ZRANK", fixed=(Key(ZSet), bytes), repeat=(bytes,))
    def zrank(self, key: CommandItem, member: bytes, *args: bytes) -> Union[None, int, List[Union[int, bytes]]]:
        (withscore,), _ = extract_args(args, ("withscore",))
        try:
            rank, score = key.value.rank(member)
            if withscore:
                return [rank, score]
            return rank
        except KeyError:
            return None

    @command(name="ZREVRANK", fixed=(Key(ZSet), bytes), repeat=(bytes,))
    def zrevrank(self, key: CommandItem, member: bytes, *args: bytes) -> Union[None, int, List[Union[int, bytes]]]:
        (withscore,), _ = extract_args(args, ("withscore",))
        try:
            rank, score = key.value.rank(member)
            rev_rank = len(key.value) - 1 - rank
            if withscore:
                return [rev_rank, score]
            return rev_rank
        except KeyError:
            return None

    @command((Key(ZSet), bytes), (bytes,))
    def zrem(self, key: CommandItem, *members: bytes) -> int:
        old_size = len(key.value)
        for member in members:
            key.value.discard(member)
        deleted = old_size - len(key.value)
        if deleted:
            key.updated()
        return deleted

    @command((Key(ZSet), StringTest, StringTest))
    def zremrangebylex(self, key, _min, _max):
        items = key.value.irange_lex(_min.value, _max.value, inclusive=(not _min.exclusive, not _max.exclusive))
        return self.zrem(key, *items)

    @command((Key(ZSet), ScoreTest, ScoreTest))
    def zremrangebyscore(self, key: CommandItem, _min: ScoreTest, _max: ScoreTest):
        items = key.value.irange_score(_min.lower_bound, _max.upper_bound, reverse=False)
        return self.zrem(key, *[item[1] for item in items])

    @command((Key(ZSet), Int, Int))
    def zremrangebyrank(self, key, start: int, stop: int):
        zset = key.value
        start, stop = fix_range(start, stop, len(zset))
        items = zset.islice_score(start, stop, reverse=False)
        return self.zrem(key, *[item[1] for item in items])

    @command((Key(ZSet), Int), (bytes, bytes))
    def zscan(self, key: CommandItem, cursor: int, *args: bytes) -> List[Union[int, List[bytes]]]:
        new_cursor, ans = self._scan(key.value.items(), cursor, *args)
        flat = []
        for key, score in ans:
            flat.append(key)
            flat.append(self._encodefloat(score, False))
        return [new_cursor, flat]

    @command((Key(ZSet), bytes))
    def zscore(self, key: CommandItem, member: bytes) -> Union[None, bytes]:
        try:
            return key.value[member]
        except KeyError:
            return None

    @staticmethod
    def _get_zset(value):
        if isinstance(value, ExpiringMembersSet):
            zset = ZSet()
            for item in value:
                zset[item] = 1.0
            return zset
        elif isinstance(value, ZSet):
            return value
        else:
            raise SimpleError(msgs.WRONGTYPE_MSG)

    def _zunioninterdiff(self, func, dest, numkeys, *args):
        if numkeys < 1:
            raise SimpleError(msgs.ZUNIONSTORE_KEYS_MSG.format(func.lower()))
        if numkeys > len(args):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        aggregate = b"sum"
        weights = [1.0] * numkeys

        i = numkeys
        while i < len(args):
            arg = args[i]
            if casematch(arg, b"weights") and i + numkeys < len(args):
                weights = [Float.decode(x, decode_error=msgs.INVALID_WEIGHT_MSG) for x in args[i + 1 : i + numkeys + 1]]
                i += numkeys + 1
            elif casematch(arg, b"aggregate") and i + 1 < len(args):
                aggregate = null_terminate(args[i + 1])
                if aggregate not in (b"sum", b"min", b"max"):
                    raise SimpleError(msgs.SYNTAX_ERROR_MSG)
                i += 2
            else:
                raise SimpleError(msgs.SYNTAX_ERROR_MSG)

        sets = []
        for i in range(numkeys):
            item = CommandItem(args[i], self._db, item=self._db.get(args[i]), default=ZSet())
            sets.append(self._get_zset(item.value))

        out_members = set(sets[0])
        method = SORTED_SET_METHODS[func]
        for s in sets[1:]:
            out_members = method(out_members, set(s))

        # We first build a regular dict and turn it into a ZSet. The
        # reason is subtle: a ZSet won't update a score from -0 to +0
        # (or vice versa) through assignment, but a regular dict will.
        out: Dict[bytes, Any] = {}
        # The sort affects the order of floating-point operations.
        # Note that redis uses qsort(1), which has no stability guarantees,
        # so we can't be sure to match it in all cases.
        for s, w in sorted(zip(sets, weights), key=lambda x: len(x[0])):
            for member, score in s.items():
                score *= w
                # Redis only does this step for ZUNIONSTORE. See
                # https://github.com/antirez/redis/issues/3954.
                if func in {"ZUNIONSTORE", "ZUNION"} and math.isnan(score):
                    score = 0.0
                if member not in out_members:
                    continue
                if member in out:
                    old = out[member]
                    if aggregate == b"sum":
                        score += old
                        if math.isnan(score):
                            score = 0.0
                    elif aggregate == b"max":
                        score = max(old, score)
                    elif aggregate == b"min":
                        score = min(old, score)
                    else:
                        assert False  # pragma: nocover
                if math.isnan(score):
                    score = 0.0
                out[member] = score

        out_zset = ZSet()
        for member, score in out.items():
            out_zset[member] = score

        if dest is None:
            return out_zset

        dest.value = out_zset
        return len(out_zset)

    @command((Key(), Int, bytes), (bytes,))
    def zunionstore(self, dest, numkeys, *args):
        return self._zunioninterdiff("ZUNIONSTORE", dest, numkeys, *args)

    @command((Key(), Int, bytes), (bytes,))
    def zinterstore(self, dest, numkeys, *args):
        return self._zunioninterdiff("ZINTERSTORE", dest, numkeys, *args)

    @command((Key(), Int, bytes), (bytes,))
    def zdiffstore(self, dest, numkeys, *args):
        return self._zunioninterdiff("ZDIFFSTORE", dest, numkeys, *args)

    @command((Int, bytes), (bytes,))
    def zdiff(self, numkeys, *args):
        withscores = casematch(b"withscores", args[-1])
        sets = args[:-1] if withscores else args
        res = self._zunioninterdiff("ZDIFF", None, numkeys, *sets)

        if not withscores:
            res = list(res)
        elif self._client_info.protocol_version == 2:
            res = [item for t in res for item in [t, res[t]]]
        else:
            res = [[i, res[i]] for i in res]
        return res

    @command((Int, bytes), (bytes,))
    def zunion(self, numkeys, *args):
        withscores = casematch(b"withscores", args[-1])
        sets = args[:-1] if withscores else args
        res = self._zunioninterdiff("ZUNION", None, numkeys, *sets)

        if not withscores:
            res = list(res)
        elif self._client_info.protocol_version == 2:
            res = [item for t in res for item in [t, res[t]]]
        else:
            res = [[i, res[i]] for i in res]
        return res

    @command((Int, bytes), (bytes,))
    def zinter(self, numkeys, *args):
        withscores = casematch(b"withscores", args[-1])
        sets = args[:-1] if withscores else args
        res = self._zunioninterdiff("ZINTER", None, numkeys, *sets)

        if not withscores:
            res = list(res)
        elif self._client_info.protocol_version == 2:
            res = [item for t in res for item in [t, res[t]]]
        else:
            res = [[i, res[i]] for i in res]
        return res

    @command(name="ZINTERCARD", fixed=(Int, bytes), repeat=(bytes,))
    def zintercard(self, numkeys, *args):
        (limit,), left_args = extract_args(
            args,
            ("+limit",),
            error_on_unexpected=False,
            left_from_first_unexpected=False,
        )
        limit = limit if limit != 0 else sys.maxsize
        res = self._zunioninterdiff("ZINTER", None, numkeys, *left_args)
        return min(limit, len(res))

    @command(name="ZMSCORE", fixed=(Key(ZSet), bytes), repeat=(bytes,))
    def zmscore(self, key: CommandItem, *members: Union[str, bytes]) -> list[Optional[float]]:
        """Get the scores associated with the specified members in the sorted set stored at the key.

        For every member that does not exist in the sorted set, a nil value is returned.
        """
        scores = map(key.value.get, members)
        return list(scores)

    @command(name="ZRANDMEMBER", fixed=(Key(ZSet),), repeat=(bytes,))
    def zrandmember(self, key: CommandItem, *args) -> Optional[list[float]]:
        count, withscores = 1, None
        if len(args) > 0:
            count = Int.decode(args[0])
        if len(args) > 1:
            if casematch(b"withscores", args[1]):
                withscores = True
            else:
                raise SimpleError(msgs.SYNTAX_ERROR_MSG)
        zset = key.value
        if zset is None:
            return None if len(args) == 0 else []
        if count < 0:  # Allow repetitions
            res = random.choices(sorted(key.value.items()), k=-count)
        else:  # Unique values from hash
            count = min(count, len(key.value))
            res = random.sample(sorted(key.value.items()), count)

        if not withscores:
            res = [t[0] for t in res]
        elif self._client_info.protocol_version == 2:
            res = [item for t in res for item in t]
        else:  # self._client_info.protocol_version == 3 and withscores
            res = [list(item) for item in res]
        return res

    def _zmpop(self, keys, count, reverse, first_pass):
        for key in keys:
            item = CommandItem(key, self._db, item=self._db.get(key), default=[])
            res = self._zpop(item, count, reverse, flatten_list=False)
            if res:
                return [key, res]
        return None

    @command(fixed=(Int,), repeat=(bytes,))
    def zmpop(self, numkeys: int, *args):
        if numkeys == 0:
            raise SimpleError(msgs.NUMKEYS_GREATER_THAN_ZERO_MSG)
        if casematch(args[-2], b"count"):
            count = Int.decode(args[-1])
            args = args[:-2]
        else:
            count = 1
        if len(args) != numkeys + 1 or (not casematch(args[-1], b"min") and not casematch(args[-1], b"max")):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)

        return self._zmpop(args[:-1], count, casematch(args[-1], b"max"), False)

    @command(fixed=(Timeout, Int), repeat=(bytes,))
    def bzmpop(self, timeout, numkeys: int, *args):
        if numkeys == 0:
            raise SimpleError(msgs.NUMKEYS_GREATER_THAN_ZERO_MSG)
        if casematch(args[-2], b"count"):
            count = Int.decode(args[-1])
            args = args[:-2]
        else:
            count = 1
        if len(args) != numkeys + 1 or (not casematch(args[-1], b"min") and not casematch(args[-1], b"max")):
            raise SimpleError(msgs.SYNTAX_ERROR_MSG)

        return self._blocking(
            timeout,
            functools.partial(self._zmpop, args[:-1], count, casematch(args[-1], b"max")),
        )
