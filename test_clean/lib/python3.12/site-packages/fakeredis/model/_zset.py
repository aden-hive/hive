from typing import Any, Tuple, Optional, Generator, Dict, ItemsView, Union

import sortedcontainers

from fakeredis._commands import AfterAny, BeforeAny


class ZSet:
    def __init__(self) -> None:
        self._bylex: Dict[bytes, float] = {}  # Maps value to score
        self._byscore = sortedcontainers.SortedList()

    def __contains__(self, value: bytes) -> bool:
        return value in self._bylex

    def add(self, value: bytes, score: float) -> bool:
        """Update the item and return whether it modified the zset"""
        old_score = self._bylex.get(value, None)
        if old_score is not None:
            if score == old_score:
                return False
            self._byscore.remove((old_score, value))
        self._bylex[value] = score
        self._byscore.add((score, value))
        return True

    def __setitem__(self, value: bytes, score: float) -> None:
        self.add(value, score)

    def __getitem__(self, key: bytes) -> float:
        return self._bylex[key]

    def get(self, key: bytes, default: Optional[float] = None) -> Optional[float]:
        return self._bylex.get(key, default)

    def __len__(self) -> int:
        return len(self._bylex)

    def __iter__(self) -> Generator[Any, Any, None]:
        def gen() -> Generator[Any, Any, None]:
            for score, value in self._byscore:
                yield value

        return gen()

    def discard(self, key: bytes) -> None:
        try:
            score = self._bylex.pop(key)
        except KeyError:
            return
        else:
            self._byscore.remove((score, key))

    def zcount(self, _min: float, _max: float) -> int:
        pos1: int = self._byscore.bisect_left(_min)
        pos2: int = self._byscore.bisect_left(_max)
        return max(0, pos2 - pos1)

    def zlexcount(self, min_value: float, min_exclusive: bool, max_value: float, max_exclusive: bool) -> int:
        pos1: int
        pos2: int
        if not self._byscore:
            return 0
        score = self._byscore[0][0]
        if min_exclusive:
            pos1 = self._byscore.bisect_right((score, min_value))
        else:
            pos1 = self._byscore.bisect_left((score, min_value))
        if max_exclusive:
            pos2 = self._byscore.bisect_left((score, max_value))
        else:
            pos2 = self._byscore.bisect_right((score, max_value))
        return max(0, pos2 - pos1)

    def islice_score(self, start: int, stop: int, reverse: bool = False) -> Any:
        return self._byscore.islice(start, stop, reverse)

    def irange_lex(
        self,
        start: Union[bytes, BeforeAny, AfterAny],
        stop: Union[bytes, BeforeAny, AfterAny],
        inclusive: Tuple[bool, bool] = (True, True),
        reverse: bool = False,
    ) -> Any:
        if len(self._byscore) == 0:
            return iter([])
        default_score = self._byscore[0][0]
        start_elem = (self._bylex.get(start, default_score), start) if start != BeforeAny else None
        stop_elem = (self._bylex.get(stop, default_score), stop) if stop != AfterAny else None
        it = self._byscore.irange(start_elem, stop_elem, inclusive=inclusive, reverse=reverse)
        return (item[1] for item in it)

    def irange_score(self, start: Tuple[Any, bytes], stop: Tuple[Any, bytes], reverse: bool) -> Any:
        return self._byscore.irange(start, stop, reverse=reverse)

    def rank(self, member: bytes) -> Tuple[int, float]:
        ind: int = self._byscore.index((self._bylex[member], member))
        return ind, self._byscore[ind][0]

    def items(self) -> ItemsView[bytes, Any]:
        return self._bylex.items()
