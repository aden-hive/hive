import heapq
import random
import time
from typing import List, Optional, Tuple


class Bucket(object):
    def __init__(self, counter: int, fingerprint: int):
        self.counter = counter
        self.fingerprint = fingerprint

    def add(self, fingerprint: int, incr: int, decay: float) -> int:
        if self.fingerprint == fingerprint:
            self.counter += incr
            return self.counter
        elif self._decay(decay):
            self.counter += incr
            self.fingerprint = fingerprint
            return self.counter
        return 0

    def count(self, fingerprint: int) -> int:
        if self.fingerprint == fingerprint:
            return self.counter
        return 0

    def _decay(self, decay: float) -> bool:
        if self.counter > 0:
            probability = decay**self.counter
            if probability >= 1 or random.random() < probability:
                self.counter -= 1
        return self.counter == 0


class HashArray(object):
    def __init__(self, width: int, decay: float):
        self.width = width
        self.decay = decay
        self.array = [Bucket(0, 0) for _ in range(width)]
        self._seed = random.getrandbits(32)

    def count(self, item: bytes) -> int:
        return self.get_bucket(item).count(self._hash(item))

    def add(self, item: bytes, incr: int) -> int:
        bucket = self.get_bucket(item)
        return bucket.add(self._hash(item), incr, self.decay)

    def get_bucket(self, item: bytes) -> Bucket:
        return self.array[self._hash(item) % self.width]

    def _hash(self, item: bytes) -> int:
        return hash(item) ^ self._seed


class HeavyKeeper(object):
    is_topk_initialized = False

    def __init__(self, k: int, width: int = 1024, depth: int = 5, decay: float = 0.9) -> None:
        if not HeavyKeeper.is_topk_initialized:
            random.seed(time.time())
        self.k = k
        self.width = width
        self.depth = depth
        self.decay = decay
        self.hash_arrays = [HashArray(width, decay) for _ in range(depth)]
        self.min_heap: List[Tuple[int, bytes]] = []

    def _index(self, val: bytes) -> int:
        for ind, item in enumerate(self.min_heap):
            if item[1] == val:
                return ind
        return -1

    def add(self, item: bytes, incr: int) -> Optional[bytes]:
        max_count = 0
        for i in range(self.depth):
            count = self.hash_arrays[i].add(item, incr)
            max_count = max(max_count, count)
        if len(self.min_heap) < self.k:
            heapq.heappush(self.min_heap, (max_count, item))
            return None
        ind = self._index(item)
        if ind >= 0:
            self.min_heap[ind] = (max_count, item)
            heapq.heapify(self.min_heap)
            return None
        if max_count > self.min_heap[0][0]:
            expelled = heapq.heapreplace(self.min_heap, (max_count, item))
            return expelled[1]
        return None

    def count(self, item: bytes) -> int:
        ind = self._index(item)
        if ind > 0:
            return self.min_heap[ind][0]
        return max([ha.count(item) for ha in self.hash_arrays])

    def list(self, k: Optional[int] = None) -> List[Tuple[int, bytes]]:
        sorted_list = sorted(self.min_heap, key=lambda x: x[0], reverse=True)
        if k is None:
            return sorted_list
        return sorted_list[:k]
