from typing import List, Dict, Tuple, Union, Optional, Callable

from fakeredis import _msgs as msgs
from fakeredis._helpers import Database, SimpleError


class TimeSeries:
    def __init__(
        self,
        name: bytes,
        database: Database,
        retention: int = 0,
        encoding: bytes = b"compressed",
        chunk_size: int = 4096,
        duplicate_policy: bytes = b"block",
        ignore_max_time_diff: int = 0,
        ignore_max_val_diff: int = 0,
        labels: Optional[Dict[bytes, bytes]] = None,
        source_key: Optional[bytes] = None,
    ):
        super().__init__()
        self.name = name
        self._db = database
        self.retention = retention
        self.encoding = encoding
        self.chunk_size = chunk_size
        self.duplicate_policy = duplicate_policy
        self.ts_ind_map: Dict[int, int] = {}  # Map from timestamp to index in sorted_list
        self.sorted_list: List[Tuple[int, float]] = []
        self.max_timestamp: int = 0
        self.labels: Dict[bytes, bytes] = labels or {}
        self.source_key = source_key
        self.ignore_max_time_diff = ignore_max_time_diff
        self.ignore_max_val_diff = ignore_max_val_diff
        self.rules: List[TimeSeriesRule] = []

    def add(self, timestamp: int, value: float, duplicate_policy: Optional[bytes] = None) -> Union[int, None]:
        if self.retention != 0 and self.max_timestamp - timestamp > self.retention:
            raise SimpleError(msgs.TIMESERIES_TIMESTAMP_OLDER_THAN_RETENTION)
        if duplicate_policy is None:
            duplicate_policy = self.duplicate_policy
        if timestamp in self.ts_ind_map:  # Duplicate policy
            if duplicate_policy == b"block":
                raise SimpleError(msgs.TIMESERIES_DUPLICATE_POLICY_BLOCK)
            if duplicate_policy == b"first":
                return timestamp
            ind = self.ts_ind_map[timestamp]
            curr_value = self.sorted_list[ind][1]
            if duplicate_policy == b"max":
                value = max(curr_value, value)
            elif duplicate_policy == b"min":
                value = min(curr_value, value)
            self.sorted_list[ind] = (timestamp, value)
            return timestamp
        self.sorted_list.append((timestamp, value))
        self.ts_ind_map[timestamp] = len(self.sorted_list) - 1
        self.rules = [rule for rule in self.rules if rule.dest_key.name in self._db]
        for rule in self.rules:
            rule.add_record((timestamp, value))
        self.max_timestamp = max(self.max_timestamp, timestamp)
        return timestamp

    def incrby(self, timestamp: int, value: float) -> Union[int, None]:
        if len(self.sorted_list) == 0:
            return self.add(timestamp, value)
        if timestamp == self.max_timestamp:
            ind = self.ts_ind_map[timestamp]
            self.sorted_list[ind] = (timestamp, self.sorted_list[ind][1] + value)
        elif timestamp > self.max_timestamp:
            ind = self.ts_ind_map[self.max_timestamp]
            self.add(timestamp, self.sorted_list[ind][1] + value)
        else:  # timestamp < self.sorted_list[ind][0]
            raise ValueError()

        return timestamp

    def get(self) -> Optional[List[Union[int, float]]]:
        if len(self.sorted_list) == 0:
            return None
        ind = self.ts_ind_map[self.max_timestamp]
        return [self.sorted_list[ind][0], self.sorted_list[ind][1]]

    def delete(self, from_ts: int, to_ts: int) -> int:
        prev_size = len(self.sorted_list)
        self.sorted_list = [x for x in self.sorted_list if not (from_ts <= x[0] <= to_ts)]
        self.ts_ind_map = {k: v for k, v in self.ts_ind_map.items() if not (from_ts <= k <= to_ts)}
        return prev_size - len(self.sorted_list)

    def get_rule(self, dest_key: bytes) -> Optional["TimeSeriesRule"]:
        for rule in self.rules:
            if rule.dest_key.name == dest_key:
                return rule
        return None

    def add_rule(self, rule: "TimeSeriesRule") -> None:
        self.rules.append(rule)

    def delete_rule(self, rule: "TimeSeriesRule") -> None:
        self.rules.remove(rule)
        rule.dest_key.source_key = None

    def range(
        self,
        from_ts: int,
        to_ts: int,
        value_min: Optional[float],
        value_max: Optional[float],
        count: Optional[int],
        filter_ts: Optional[List[int]],
        reverse: bool,
    ) -> List[Tuple[int, float]]:
        value_min = value_min or float("-inf")
        value_max = value_max or float("inf")
        res: List[Tuple[int, float]] = [
            x
            for x in self.sorted_list
            if (from_ts <= x[0] <= to_ts)
            and value_min <= x[1] <= value_max
            and (filter_ts is None or x[0] in filter_ts)
        ]
        if reverse:
            res.reverse()
        if count is not None:
            return res[:count]
        return res

    def aggregate(
        self,
        from_ts: int,
        to_ts: int,
        latest: bool,
        value_min: Optional[float],
        value_max: Optional[float],
        count: Optional[int],
        filter_ts: Optional[List[int]],
        align: Optional[int],
        aggregator: bytes,
        bucket_duration: int,
        bucket_timestamp: Optional[bytes],
        empty: Optional[bool],
        reverse: bool,
    ) -> List[Tuple[int, float]]:
        align = align or 0
        value_min = value_min or float("-inf")
        value_max = value_max or float("inf")
        rule = TimeSeriesRule(self, TimeSeries(b"", self._db), aggregator, bucket_duration)
        for x in self.sorted_list:
            if from_ts <= x[0] <= to_ts and value_min <= x[1] <= value_max and (filter_ts is None or x[0] in filter_ts):
                rule.add_record((x[0], x[1]), bucket_timestamp)

        if latest and len(rule.current_bucket) > 0:
            rule.apply_curr_bucket(bucket_timestamp)
        if empty:
            min_bucket_ts = rule.dest_key.sorted_list[0][0]
            for ts in range(min_bucket_ts, rule.current_bucket_start_ts, bucket_duration):
                if ts not in rule.dest_key.ts_ind_map:
                    rule.dest_key.add(ts, float("nan"))
            rule.dest_key.sorted_list = sorted(rule.dest_key.sorted_list)
        if reverse:
            rule.dest_key.sorted_list.reverse()
        if count:
            return rule.dest_key.sorted_list[:count]
        return rule.dest_key.sorted_list


class Aggregators:
    @staticmethod
    def var_p(values: List[float]) -> float:
        if len(values) == 0:
            return 0
        avg = sum(values) / len(values)
        return sum((x - avg) ** 2 for x in values) / len(values)

    @staticmethod
    def var_s(values: List[float]) -> float:
        if len(values) == 0:
            return 0
        avg = sum(values) / len(values)
        return sum((x - avg) ** 2 for x in values) / (len(values) - 1)

    @staticmethod
    def std_p(values: List[float]) -> float:
        return float(Aggregators.var_p(values) ** 0.5)

    @staticmethod
    def std_s(values: List[float]) -> float:
        return float(Aggregators.var_s(values) ** 0.5)


AGGREGATORS: Dict[bytes, Callable[[List[float]], float]] = {
    b"avg": lambda x: sum(x) / len(x),
    b"sum": sum,
    b"min": min,
    b"max": max,
    b"range": lambda x: max(x) - min(x),
    b"count": len,
    b"first": lambda x: x[0],
    b"last": lambda x: x[-1],
    b"std.p": Aggregators.std_p,
    b"std.s": Aggregators.std_s,
    b"var.p": Aggregators.var_p,
    b"var.s": Aggregators.var_s,
    b"twa": lambda x: 0,
}


def apply_aggregator(
    bucket: List[Tuple[int, float]], bucket_start_ts: int, bucket_duration: int, aggregator: bytes
) -> float:
    if len(bucket) == 0:
        return 0.0
    if aggregator == b"twa":
        total = 0.0
        curr_ts = bucket_start_ts
        for i, (ts, val) in enumerate(bucket):
            # next_ts = bucket[i + 1][0] if len(bucket) > i + 1 else bucket_start_ts + bucket_duration
            total += (ts - curr_ts) * val
            curr_ts = ts
        total += val * (bucket_start_ts + bucket_duration - curr_ts)

        return total / bucket_duration

    relevant_values: List[float] = [x[1] for x in bucket]
    return AGGREGATORS[aggregator](relevant_values)


class TimeSeriesRule:
    def __init__(
        self,
        source_key: TimeSeries,
        dest_key: TimeSeries,
        aggregator: bytes,
        bucket_duration: int,
        align_timestamp: int = 0,
    ):
        self.source_key = source_key
        self.dest_key = dest_key
        self.aggregator = aggregator.lower()
        self.bucket_duration = bucket_duration
        self.align_timestamp = align_timestamp
        self.current_bucket_start_ts: int = 0
        self.current_bucket: List[Tuple[int, float]] = []
        self.dest_key.source_key = source_key.name

    def add_record(self, record: Tuple[int, float], bucket_timestamp: Optional[bytes] = None) -> bool:
        ts, val = record
        bucket_start_ts = ts - (ts % self.bucket_duration) + self.align_timestamp
        if self.current_bucket_start_ts == bucket_start_ts:
            self.current_bucket.append(record)
        if (
            self.current_bucket_start_ts != bucket_start_ts
            or ts == self.current_bucket_start_ts + self.bucket_duration - 1
        ):
            should_add = self.current_bucket_start_ts != bucket_start_ts
            self.apply_curr_bucket(bucket_timestamp)
            self.current_bucket_start_ts = (
                bucket_start_ts
                if self.current_bucket_start_ts != bucket_start_ts
                else self.current_bucket_start_ts + self.bucket_duration
            )
            if should_add:
                self.current_bucket.append(record)
            return True
        return False

    def apply_curr_bucket(self, bucket_timestamp: Optional[bytes] = None) -> None:
        if len(self.current_bucket) == 0:
            return
        value = apply_aggregator(
            self.current_bucket, self.current_bucket_start_ts, self.bucket_duration, self.aggregator
        )
        self.current_bucket = []
        timestamp = self.current_bucket_start_ts
        if bucket_timestamp == b"+":
            timestamp = int(self.current_bucket_start_ts + self.bucket_duration)
        elif bucket_timestamp == b"~":
            timestamp = int(self.current_bucket_start_ts + self.bucket_duration / 2)
        self.dest_key.add(timestamp, value)
