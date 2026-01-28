import bisect
import itertools
import sys
import time
from collections import Counter
from dataclasses import dataclass
from typing import List, Union, Tuple, Optional, NamedTuple, Dict, Any, Sequence, Generator, AnyStr

from fakeredis._commands import BeforeAny, AfterAny
from fakeredis._helpers import current_time


class StreamEntryKey(NamedTuple):
    ts: int
    seq: int

    def encode(self) -> bytes:
        return f"{self.ts}-{self.seq}".encode()

    @staticmethod
    def parse_str(entry_key: AnyStr) -> "StreamEntryKey":
        entry_key_str: str = entry_key.decode() if isinstance(entry_key, bytes) else entry_key
        parts = entry_key_str.split("-")
        (timestamp, sequence) = (int(parts[0]), 0) if len(parts) == 1 else (int(parts[0]), int(parts[1]))
        return StreamEntryKey(timestamp, sequence)


class PelEntry(NamedTuple):
    """Pending Entry List entry: tracks consumer ownership and delivery count"""

    consumer_name: bytes
    time_read: int
    times_delivered: int


class StreamRangeTest:
    """Argument converter for sorted set LEX endpoints."""

    def __init__(self, value: Union[StreamEntryKey, BeforeAny, AfterAny], exclusive: bool):
        self.value = value
        self.exclusive = exclusive

    @staticmethod
    def valid_key(entry_key: AnyStr) -> bool:
        try:
            StreamEntryKey.parse_str(entry_key)
            return True
        except ValueError:
            return False

    @classmethod
    def decode(cls, value: bytes, exclusive: bool = False) -> "StreamRangeTest":
        if value == b"-":
            return cls(BeforeAny(), True)
        elif value == b"+":
            return cls(AfterAny(), True)
        elif value[:1] == b"(":
            return cls(StreamEntryKey.parse_str(value[1:]), True)
        return cls(StreamEntryKey.parse_str(value), exclusive)


@dataclass
class StreamConsumerInfo(object):
    name: bytes
    pending: int
    last_attempt: int  # Impacted by XREADGROUP, XCLAIM, XAUTOCLAIM
    last_success: int  # Impacted by XREADGROUP, XCLAIM, XAUTOCLAIM

    def __init__(self, name: bytes) -> None:
        self.name = name
        self.pending = 0
        _time = current_time()
        self.last_attempt = _time
        self.last_success = _time

    def info(self, curr_time: int) -> Dict[str, Union[bytes, int]]:
        return {
            "name": self.name,
            "pending": self.pending,
            "idle": curr_time - self.last_attempt,
            "inactive": curr_time - self.last_success,
        }


class StreamGroup(object):
    def __init__(
        self,
        stream: "XStream",
        name: bytes,
        start_key: StreamEntryKey,
        entries_read: Optional[int] = None,
    ):
        self.stream = stream
        self.name = name
        self.start_key = start_key
        self.entries_read = entries_read
        # consumer_name -> #pending_messages
        self.consumers: Dict[bytes, StreamConsumerInfo] = {}
        self.last_delivered_key = start_key
        self.last_ack_key = start_key
        # Pending entry List, see https://redis.io/commands/xreadgroup/
        # msg_id -> PelEntry(consumer_name, time_read, times_delivered)
        self.pel: Dict[StreamEntryKey, PelEntry] = {}

    def set_id(self, last_delivered_str: bytes, entries_read: Optional[int]) -> None:
        """Set last_delivered_id for the group"""
        self.start_key = self.stream.parse_ts_seq(last_delivered_str)
        (start_index, _) = self.stream.find_index(self.start_key)
        self.entries_read = entries_read or 0
        self.last_delivered_key = self.stream.get_index(min(start_index + (entries_read or 0), len(self.stream) - 1))

    def add_consumer(self, consumer_name: bytes) -> int:
        if consumer_name in self.consumers:
            return 0
        self.consumers[consumer_name] = StreamConsumerInfo(consumer_name)
        return 1

    def del_consumer(self, consumer_name: bytes) -> int:
        if consumer_name not in self.consumers:
            return 0
        res = self.consumers[consumer_name].pending
        del self.consumers[consumer_name]
        return res

    def consumers_info(self) -> List[Dict[str, Union[bytes, int]]]:
        return [self.consumers[k].info(current_time()) for k in self.consumers]

    def group_info(self) -> Dict[bytes, Any]:
        start_index, _ = self.stream.find_index(self.start_key)
        last_delivered_index, _ = self.stream.find_index(self.last_delivered_key)
        last_ack_index, _ = self.stream.find_index(self.last_ack_key)
        if start_index + (self.entries_read or 0) > len(self.stream):
            lag = len(self.stream) - start_index - (self.entries_read or 0)
        else:
            lag = len(self.stream) - 1 - last_delivered_index
        res = {
            b"name": self.name,
            b"consumers": len(self.consumers),
            b"pending": len(self.pel),
            b"last-delivered-id": self.last_delivered_key.encode(),
            b"entries-read": self.entries_read,
            b"lag": lag,
        }
        return res

    def group_read(
        self, consumer_name: bytes, start_id: bytes, count: int, noack: bool
    ) -> List[List[Union[bytes, Dict[bytes, bytes]]]]:
        _time = current_time()
        if consumer_name not in self.consumers:
            self.consumers[consumer_name] = StreamConsumerInfo(consumer_name)

        self.consumers[consumer_name].last_attempt = _time
        if start_id == b">":
            start_key = self.last_delivered_key
        else:
            start_key = max(StreamEntryKey.parse_str(start_id), self.last_delivered_key)
        ids_read = self.stream.stream_read(start_key, count)
        if not noack:
            for k in ids_read:
                # Initialize with times_delivered=1 for new messages
                self.pel[k] = PelEntry(consumer_name, _time, 1)
        if len(ids_read) > 0:
            self.last_delivered_key = max(self.last_delivered_key, ids_read[-1])
            self.entries_read = (self.entries_read or 0) + len(ids_read)
        self.consumers[consumer_name].last_success = _time
        self.consumers[consumer_name].pending += len(ids_read)
        return [self.stream.format_record(x) for x in ids_read]

    def _calc_consumer_last_time(self) -> None:
        # pel values are PelEntry namedtuples
        # Extract just consumer_name and time_read for grouping
        new_last_success_map = {
            k: min(v, key=lambda x: x.time_read).time_read
            for k, v in itertools.groupby(self.pel.values(), key=lambda x: x.consumer_name)
        }
        for consumer in new_last_success_map:
            if consumer not in self.consumers:
                self.consumers[consumer] = StreamConsumerInfo(consumer)
            self.consumers[consumer].last_attempt = new_last_success_map[consumer]
            self.consumers[consumer].last_success = new_last_success_map[consumer]

    def ack(self, args: Tuple[bytes]) -> int:
        res = 0
        for k in args:
            try:
                parsed = StreamEntryKey.parse_str(k)
            except Exception:
                continue
            if parsed in self.pel:
                consumer_name = self.pel[parsed].consumer_name
                self.consumers[consumer_name].pending -= 1
                del self.pel[parsed]
                res += 1
        self._calc_consumer_last_time()
        return res

    def pending(
        self,
        idle: Optional[int],
        start: Optional[StreamRangeTest],
        end: Optional[StreamRangeTest],
        count: Optional[int],
        consumer: Optional[bytes],
    ) -> List[List[bytes]]:
        _time = current_time()
        relevant_ids = list(self.pel.keys())
        if consumer is not None:
            relevant_ids = [k for k in relevant_ids if self.pel[k].consumer_name == consumer]
        if idle is not None:
            relevant_ids = [k for k in relevant_ids if self.pel[k].time_read + idle < _time]
        if start is not None and end is not None:
            relevant_ids = [
                k
                for k in relevant_ids
                if (
                    ((start.value < k) or (start.value == k and not start.exclusive))
                    and ((end.value > k) or (end.value == k and not end.exclusive))
                )
            ]
        if count is not None:
            relevant_ids = sorted(relevant_ids)[:count]

        # Return all 4 fields: message_id, consumer, time_since_delivered, times_delivered
        return [
            [k.encode(), self.pel[k].consumer_name, _time - self.pel[k].time_read, self.pel[k].times_delivered]
            for k in relevant_ids
        ]

    def pending_summary(self) -> List[Any]:
        counter = Counter([self.pel[k].consumer_name for k in self.pel])
        data = [
            len(self.pel),
            min(self.pel).encode() if len(self.pel) > 0 else None,
            max(self.pel).encode() if len(self.pel) > 0 else None,
            [[i, counter[i]] for i in counter],
        ]
        return data

    def claim(
        self,
        min_idle_ms: int,
        msgs: Union[Sequence[bytes], Sequence[StreamEntryKey]],
        consumer_name: bytes,
        _time: Optional[int],
        force: bool,
    ) -> Tuple[List[StreamEntryKey], List[StreamEntryKey]]:
        curr_time = current_time()
        if _time is None:
            _time = curr_time
        self.consumers.get(consumer_name, StreamConsumerInfo(consumer_name)).last_attempt = curr_time
        claimed_msgs, deleted_msgs = [], []
        for msg in msgs:
            try:
                key = StreamEntryKey.parse_str(msg) if isinstance(msg, bytes) else msg
            except Exception:
                continue
            if key not in self.pel:
                if force:
                    # Force claim msg - initialize with times_delivered=1
                    self.pel[key] = PelEntry(consumer_name, _time, 1)
                    if key in self.stream:
                        claimed_msgs.append(key)
                    else:
                        deleted_msgs.append(key)
                        del self.pel[key]
                continue
            if curr_time - self.pel[key].time_read < min_idle_ms:
                continue  # Not idle enough time to be claimed
            # Increment times_delivered when claiming
            old_times_delivered = self.pel[key].times_delivered
            self.pel[key] = PelEntry(consumer_name, _time, old_times_delivered + 1)
            if key in self.stream:
                claimed_msgs.append(key)
            else:
                deleted_msgs.append(key)
                del self.pel[key]
        self._calc_consumer_last_time()
        return sorted(claimed_msgs), sorted(deleted_msgs)

    def read_pel_msgs(self, min_idle_ms: int, start: bytes, count: int) -> List[StreamEntryKey]:
        start_key = StreamEntryKey.parse_str(start)
        curr_time = current_time()
        msgs = sorted([k for k in self.pel if (curr_time - self.pel[k].time_read >= min_idle_ms) and k >= start_key])
        count = min(count, len(msgs))
        return msgs[:count]


class XStream:
    """Class representing stream.

    The stream contains entries with keys (timestamp, sequence) and field->value pairs.
    This implementation has them as a sorted list of tuples, the first value in the tuple
    is the key (timestamp, sequence).

    The structure of _values list is:
    [
       ((timestamp, sequence), [field1, value1, field2, value2, ...]),
       ((timestamp, sequence), [field1, value1, field2, value2, ...]),
    ]
    """

    def __init__(self) -> None:
        self._ids: List[StreamEntryKey] = []
        self._values_dict: Dict[StreamEntryKey, List[bytes]] = {}
        self._groups: Dict[bytes, StreamGroup] = {}
        self._max_deleted_id = StreamEntryKey(0, 0)
        self._entries_added = 0

    def group_get(self, group_name: bytes) -> Optional[StreamGroup]:
        return self._groups.get(group_name, None)

    def group_add(self, name: bytes, start_key_str: bytes, entries_read: Optional[int]) -> None:
        """Add a group listening to stream

        :param name: Group name
        :param start_key_str: start_key in `timestamp-sequence` format, or $ listen from last.
        :param entries_read: Number of entries read.
        """
        if start_key_str == b"$":
            start_key = self._ids[-1] if len(self._ids) > 0 else StreamEntryKey(0, 0)
        else:
            start_key = StreamEntryKey.parse_str(start_key_str)
        self._groups[name] = StreamGroup(self, name, start_key, entries_read)

    def group_delete(self, group_name: bytes) -> int:
        if group_name in self._groups:
            del self._groups[group_name]
            return 1
        return 0

    def groups_info(self) -> List[Dict[bytes, Any]]:
        res: List[Dict[bytes, Any]] = []
        for group in self._groups.values():
            group_res = group.group_info()
            res.append(group_res)
        return res

    def stream_info(self, full: bool) -> List[Any]:
        res: Dict[bytes, Any] = {
            b"length": len(self._ids),
            b"groups": len(self._groups),
            b"first-entry": self.format_record(self._ids[0]) if len(self._ids) > 0 else None,
            b"last-entry": self.format_record(self._ids[-1]) if len(self._ids) > 0 else None,
            b"max-deleted-entry-id": self._max_deleted_id.encode(),
            b"entries-added": self._entries_added,
            b"recorded-first-entry-id": self._ids[0].encode() if len(self._ids) > 0 else b"0-0",
        }
        if full:
            res[b"entries"] = [self.format_record(i) for i in self._ids]
            res[b"groups"] = [g.group_info() for g in self._groups.values()]
        return list(itertools.chain(*res.items()))

    def delete(self, lst: List[AnyStr]) -> int:
        """Delete items from stream

        :param lst: List of IDs to delete, in the form of `timestamp-sequence`.
        :returns: Number of items deleted
        """
        res = 0
        for item in lst:
            ind, found = self.find_index_key_as_str(item)
            if found:
                self._max_deleted_id = max(self._ids[ind], self._max_deleted_id)
                del self._values_dict[self._ids[ind]]
                del self._ids[ind]
                res += 1
        return res

    def add(self, fields: Sequence[Union[bytes, int]], entry_key: str = "*") -> Union[None, bytes]:
        """Add entry to a stream.

        If the entry_key cannot be added (because its timestamp is before the last entry, etc.),
        nothing is added.

        :param fields: List of fields to add, must [key1, value1, key2, value2, ... ]
        :param entry_key:
            Key for the entry, formatted as 'timestamp-sequence'
            If entry_key is '*', the timestamp will be calculated as current time and the sequence based
            on the last entry key of the stream.
            If entry_key is 'ts-*', and the timestamp is greater or equal than the last entry timestamp,
            then the sequence will be calculated accordingly.
        :returns:
            The key of the added entry.
            None if nothing was added.
        :raises AssertionError: If len(fields) is not even.
        """
        if len(fields) % 2 != 0:
            raise AssertionError("The number of fields is not even")
        if isinstance(entry_key, bytes):
            entry_key = entry_key.decode()

        if entry_key is None or entry_key == "*":
            ts, seq = int(1000 * time.time()), 0
            if len(self._ids) > 0 and self._ids[-1].ts >= ts and self._ids[-1].seq >= seq:
                ts = self._ids[-1].ts
                seq = self._ids[-1].seq + 1
            ts_seq = StreamEntryKey(ts, seq)
        elif entry_key[-1] == "*":  # entry_key has `timestamp-*` structure
            split = entry_key.split("-")
            if len(split) != 2:
                return None
            ts, seq = int(split[0]), split[1]  # type: ignore
            if len(self._ids) > 0 and ts == self._ids[-1].ts:
                seq = self._ids[-1].seq + 1
            else:
                seq = 0
            ts_seq = StreamEntryKey(ts, seq)
        else:
            ts_seq = StreamEntryKey.parse_str(entry_key)

        if len(self._ids) > 0 and self._ids[-1] > ts_seq:
            return None
        self._ids.append(ts_seq)
        self._values_dict[ts_seq] = list(fields)
        self._entries_added += 1
        return ts_seq.encode()

    def __bool__(self):
        return True

    def __len__(self) -> int:
        return len(self._ids)

    def __iter__(self) -> Generator[List[Union[bytes, List[bytes]]], Any, None]:
        def gen() -> Generator[List[Union[bytes, List[bytes]]], Any, None]:
            for k in self._ids:
                yield self.format_record(k)

        return gen()

    def __getitem__(self, key: bytes) -> Union[StreamEntryKey, List[bytes]]:
        return self._values_dict[StreamEntryKey.parse_str(key)]

    def get_index(self, ind: int) -> StreamEntryKey:
        return self._ids[ind]

    def __contains__(self, key: StreamEntryKey) -> bool:
        return key in self._values_dict

    def find_index(self, entry_key: StreamEntryKey, from_left: bool = True) -> Tuple[int, bool]:
        """Find the closest index to entry_key_str in the stream
        :param entry_key: Key for the entry.
        :param from_left: If not found exact match, return index of last smaller element
        :returns: A tuple
            (index of entry with the closest (from the left) key to entry_key_str,
             whether the entry key is equal)
        """
        if len(self._ids) == 0:
            return 0, False
        if from_left:
            ind = bisect.bisect_left(self._ids, entry_key)
            check_idx = ind
        else:
            ind = bisect.bisect_right(self._ids, entry_key)
            check_idx = ind - 1
        return ind, (check_idx < len(self._ids) and self._ids[check_idx] == entry_key)

    def find_index_key_as_str(self, entry_key_str: AnyStr) -> Tuple[int, bool]:
        """Find the closest index to entry_key_str in the stream
        :param entry_key_str: key for the entry, formatted as 'timestamp-sequence.'
        :returns: A tuple
            (index of entry with the closest (from the left) key to entry_key_str,
             whether the entry key is equal)
        """
        if entry_key_str == b"$":
            return max(len(self._ids) - 1, 0), True
        ts_seq = StreamEntryKey.parse_str(entry_key_str)
        return self.find_index(ts_seq)

    @staticmethod
    def parse_ts_seq(ts_seq_str: AnyStr) -> StreamEntryKey:
        if ts_seq_str == b"$":
            return StreamEntryKey(0, 0)
        return StreamEntryKey.parse_str(ts_seq_str)

    def trim(
        self,
        max_length: Optional[int] = None,
        start_entry_key: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> int:
        """Trim a stream

        :param max_length: Max length of the resulting stream after trimming (number of last values to keep)
        :param start_entry_key: Min entry-key to keep, cannot be given together with max_length.
        :param limit: Number of entries to keep from minid.
        :returns: The resulting stream after trimming.
        :raises ValueError: When both max_length and start_entry_key are passed.
        """
        if max_length is not None and start_entry_key is not None:
            raise ValueError("Can not use both max_length and start_entry_key")
        start_ind: Optional[int] = None
        if max_length is not None:
            start_ind = len(self._ids) - max_length
        elif start_entry_key is not None:
            ind, exact = self.find_index_key_as_str(start_entry_key)
            start_ind = ind
        res: int = min(max(start_ind or 0, 0), limit or sys.maxsize)

        remove_keys, self._ids = self._ids[:res], self._ids[res:]
        for k in remove_keys:
            del self._values_dict[k]
        return res

    def irange(self, start: StreamRangeTest, stop: StreamRangeTest, reverse: bool = False) -> List[Any]:
        """Returns a range of the stream values from start to stop.

        :param start: Start key
        :param stop: Stop key
        :param reverse: Should the range be in reverse order?
        :returns: The range between start and stop
        """

        def _find_index(elem: StreamRangeTest, from_left: bool = True) -> int:
            if isinstance(elem.value, BeforeAny):
                return 0
            if isinstance(elem.value, AfterAny):
                return len(self._ids)
            ind, found = self.find_index(elem.value, from_left)
            if found and elem.exclusive:
                ind += 1 if from_left else -1
            return ind

        start_ind = _find_index(start)
        stop_ind = _find_index(stop, from_left=False)
        matches = [self.format_record(self._ids[x]) for x in range(start_ind, stop_ind)]
        if reverse:
            return list(reversed(matches))
        return matches

    def last_item_key(self) -> bytes:
        return self._ids[-1].encode() if len(self._ids) > 0 else "0-0".encode()

    def stream_read(self, start_key: StreamEntryKey, count: Union[int, None]) -> List[StreamEntryKey]:
        start_ind, found = self.find_index(start_key)
        if found:
            start_ind += 1
        if start_ind >= len(self):
            return []
        end_ind = len(self) if count is None or start_ind + count >= len(self) else start_ind + count
        return self._ids[start_ind:end_ind]

    def format_record(self, key: StreamEntryKey) -> List[Union[bytes, Dict[bytes, bytes]]]:
        # results: Dict[bytes, bytes] = dict(zip(*[iter(self._values_dict[key])] * 2))
        results = self._values_dict[key]
        return [key.encode(), results]
