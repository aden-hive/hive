import time
from typing import List, Union, Optional, Any, Set, Dict

from fakeredis import _msgs as msgs
from fakeredis._command_args_parsing import extract_args
from fakeredis._commands import command, Key, CommandItem, Int, Float, Timestamp
from fakeredis._helpers import Database, SimpleString, OK, SimpleError, casematch
from fakeredis._typing import VersionType
from fakeredis.model import TimeSeries, TimeSeriesRule, AGGREGATORS, ClientInfo


class TimeSeriesCommandsMixin:  # TimeSeries commands
    _timeseries_keys: Set[bytes] = set()
    DUPLICATE_POLICIES = [b"BLOCK", b"FIRST", b"LAST", b"MIN", b"MAX", b"SUM"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._db: Database
        self.version: VersionType
        self._client_info: ClientInfo

    @staticmethod
    def _filter_expression_check(ts: TimeSeries, filter_expression: bytes) -> bool:
        if not filter_expression:
            return True
        if filter_expression.find(b"!=") != -1:
            if len(filter_expression.split(b"!=")) != 2:
                raise SimpleError(msgs.TIMESERIES_BAD_FILTER_EXPRESSION)
            label, value = filter_expression.split(b"!=")
            if value == b"-":
                return label in ts.labels

            if value.startswith(b"(") and value.endswith(b")"):
                values = set(value[1:-1].split(b","))
                return label in ts.labels and ts.labels[label] not in values
            return label not in ts.labels or ts.labels[label] != value
        if filter_expression.find(b"=") != -1:
            if len(filter_expression.split(b"=")) != 2:
                raise SimpleError(msgs.TIMESERIES_BAD_FILTER_EXPRESSION)
            label, value = filter_expression.split(b"=")
            if value == b"-":
                return label not in ts.labels
            if value.startswith(b"(") and value.endswith(b")"):
                values = set(value[1:-1].split(b","))
                return label in ts.labels and ts.labels[label] in values
            return label in ts.labels and ts.labels[label] == value
        raise SimpleError(msgs.TIMESERIES_BAD_FILTER_EXPRESSION)

    def _get_timeseries(self, filter_expressions: List[bytes]) -> List["TimeSeries"]:
        res: List["TimeSeries"] = []
        TimeSeriesCommandsMixin._timeseries_keys = {
            k for k in TimeSeriesCommandsMixin._timeseries_keys if k in self._db
        }
        for ts_key in TimeSeriesCommandsMixin._timeseries_keys:
            ts = self._db.get(ts_key).value
            if all(self._filter_expression_check(ts, expr) for expr in filter_expressions):
                res.append(ts)
        return res

    @staticmethod
    def _validate_duplicate_policy(duplicate_policy: bytes) -> bool:
        return duplicate_policy is None or any(
            casematch(duplicate_policy, item) for item in TimeSeriesCommandsMixin.DUPLICATE_POLICIES
        )

    def _create_timeseries(self, name: bytes, *args) -> TimeSeries:
        (retention, encoding, chunk_size, duplicate_policy, (ignore_max_time_diff, ignore_max_val_diff)), left_args = (
            extract_args(
                args,
                ("+retention", "*encoding", "+chunk_size", "*duplicate_policy", "++ignore"),
                error_on_unexpected=False,
            )
        )
        retention = retention or 0
        encoding = encoding or b"COMPRESSED"
        if not (casematch(encoding, b"COMPRESSED") or casematch(encoding, b"UNCOMPRESSED")):
            raise SimpleError(msgs.BAD_SUBCOMMAND_MSG.format("TS.CREATE"))
        encoding = encoding.lower()
        chunk_size = chunk_size or 4096
        if chunk_size % 8 != 0:
            raise SimpleError(msgs.TIMESERIES_BAD_CHUNK_SIZE)
        if not self._validate_duplicate_policy(duplicate_policy):
            raise SimpleError(msgs.TIMESERIES_INVALID_DUPLICATE_POLICY)
        duplicate_policy = duplicate_policy.lower() if duplicate_policy else None
        if len(left_args) > 0 and (not casematch(left_args[0], b"LABELS") or len(left_args) % 2 != 1):
            raise SimpleError(msgs.BAD_SUBCOMMAND_MSG.format("TS.ADD"))
        labels = dict(zip(left_args[1::2], left_args[2::2])) if len(left_args) > 0 else {}

        if duplicate_policy is None and self.version >= (8,):
            # In Redis 8.0, the default duplicate policy is BLOCK
            duplicate_policy = b"block"
        res = TimeSeries(
            name=name,
            database=self._db,
            retention=retention,
            encoding=encoding,
            chunk_size=chunk_size,
            duplicate_policy=duplicate_policy,
            ignore_max_time_diff=ignore_max_time_diff,
            ignore_max_val_diff=ignore_max_val_diff,
            labels=labels,
        )
        self._timeseries_keys.add(name)
        return res

    @command(name="TS.INFO", fixed=(Key(TimeSeries),), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def ts_info(self, key: CommandItem, *args: bytes) -> Dict[bytes, Any]:
        if key.value is None:
            raise SimpleError(msgs.TIMESERIES_KEY_DOES_NOT_EXIST)
        if self._client_info.protocol_version == 2:
            labels = [[k, v] for k, v in key.value.labels.items()]
            rules = [
                [rule.dest_key.name, rule.bucket_duration, rule.aggregator.upper(), rule.align_timestamp]
                for rule in key.value.rules
            ]
        else:
            labels = key.value.labels
            rules = {
                rule.dest_key.name: [rule.bucket_duration, rule.aggregator.upper(), rule.align_timestamp]
                for rule in key.value.rules
            }
        return {
            b"totalSamples": len(key.value.sorted_list),
            b"memoryUsage": len(key.value.sorted_list) * 8 + len(key.value.encoding),
            b"firstTimestamp": key.value.sorted_list[0][0] if len(key.value.sorted_list) > 0 else 0,
            b"lastTimestamp": key.value.sorted_list[-1][0] if len(key.value.sorted_list) > 0 else 0,
            b"retentionTime": key.value.retention,
            b"chunkCount": len(key.value.sorted_list) * 8 // key.value.chunk_size,
            b"chunkSize": key.value.chunk_size,
            b"chunkType": key.value.encoding,
            b"duplicatePolicy": key.value.duplicate_policy,
            b"labels": labels,
            b"sourceKey": key.value.source_key,
            b"rules": rules,
            b"keySelfName": key.value.name,
            b"Chunks": [],
        }

    @command(name="TS.CREATE", fixed=(Key(TimeSeries),), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def ts_create(self, key: CommandItem, *args: bytes) -> SimpleString:
        if key.value is not None:
            raise SimpleError(msgs.TIMESERIES_KEY_EXISTS)
        key.value = self._create_timeseries(key.key, *args)
        return OK

    @command(name="TS.ADD", fixed=(Key(TimeSeries), Timestamp, Float), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def ts_add(self, key: CommandItem, timestamp: int, value: float, *args: bytes) -> int:
        (on_duplicate,), left_args = extract_args(args, ("*on_duplicate",), error_on_unexpected=False)
        if key.value is None:
            key.update(self._create_timeseries(key.key, *args))
        if not self._validate_duplicate_policy(on_duplicate):
            raise SimpleError(msgs.TIMESERIES_INVALID_DUPLICATE_POLICY)
        res = key.value.add(timestamp, value, on_duplicate)
        return res

    @command(name="TS.GET", fixed=(Key(TimeSeries),), repeat=(bytes,))
    def ts_get(self, key: CommandItem, *args: bytes) -> Optional[List[Union[int, float]]]:
        if key.value is None:
            raise SimpleError(msgs.TIMESERIES_KEY_DOES_NOT_EXIST)
        res = key.value.get()
        if res is None and self._client_info.protocol_version == 3:
            res = []
        return res

    @command(
        name="TS.MADD",
        fixed=(Key(TimeSeries), Timestamp, Float),
        repeat=(Key(TimeSeries), Timestamp, Float),
        flags=msgs.FLAG_DO_NOT_CREATE,
    )
    def ts_madd(self, *args: Any) -> List[int]:
        if len(args) % 3 != 0:
            raise SimpleError(msgs.WRONG_ARGS_MSG6)
        results: List[int] = []
        for i in range(0, len(args), 3):
            key, timestamp, value = args[i : i + 3]
            if key.value is None:
                raise SimpleError(msgs.TIMESERIES_KEY_DOES_NOT_EXIST)
            results.append(key.value.add(timestamp, value))
        return results

    @command(name="TS.DEL", fixed=(Key(TimeSeries), Int, Int), repeat=(), flags=msgs.FLAG_DO_NOT_CREATE)
    def ts_del(self, key: CommandItem, from_ts: int, to_ts: int) -> bytes:
        if key.value is None:
            raise SimpleError(msgs.TIMESERIES_KEY_DOES_NOT_EXIST)
        return key.value.delete(from_ts, to_ts)

    @command(
        name="TS.CREATERULE",
        fixed=(Key(TimeSeries), Key(TimeSeries), bytes, bytes, Int),
        repeat=(bytes,),
        flags=msgs.FLAG_DO_NOT_CREATE,
    )
    def ts_createrule(
        self,
        source_key: CommandItem,
        dest_key: CommandItem,
        _: bytes,
        aggregator: bytes,
        bucket_duration: int,
        *args: bytes,
    ) -> SimpleString:
        if source_key.value is None:
            raise SimpleError(msgs.TIMESERIES_KEY_DOES_NOT_EXIST)
        if dest_key.value is None:
            raise SimpleError(msgs.TIMESERIES_KEY_DOES_NOT_EXIST)
        if len(args) > 1:
            raise SimpleError(msgs.WRONG_ARGS_MSG6.format("ts.createrule"))
        try:
            align_timestamp = int(args[0]) if len(args) == 1 else 0
        except ValueError:
            raise SimpleError(msgs.TIMESERIES_BAD_TIMESTAMP)
        existing_rule = source_key.value.get_rule(dest_key.key)
        if existing_rule is not None:
            raise SimpleError(msgs.TIMESERIES_RULE_EXISTS)
        if aggregator not in AGGREGATORS:
            raise SimpleError(msgs.TIMESERIES_BAD_AGGREGATION_TYPE)
        rule = TimeSeriesRule(source_key.value, dest_key.value, aggregator, bucket_duration, align_timestamp)
        source_key.value.add_rule(rule)
        return OK

    @command(
        name="TS.DELETERULE",
        fixed=(Key(TimeSeries), Key(TimeSeries)),
        repeat=(),
        flags=msgs.FLAG_DO_NOT_CREATE,
    )
    def ts_deleterule(self, source_key: CommandItem, dest_key: CommandItem) -> SimpleString:
        if source_key.value is None:
            raise SimpleError(msgs.TIMESERIES_KEY_DOES_NOT_EXIST)
        res: Optional[TimeSeriesRule] = source_key.value.get_rule(dest_key.key)
        if res is None:
            raise SimpleError(msgs.TIMESERIES_RULE_DOES_NOT_EXIST)
        source_key.value.delete_rule(res)
        return OK

    def _ts_inc_or_dec(self, key: CommandItem, addend: float, *args: bytes) -> SimpleString:
        (ts,), left_args = extract_args(
            args,
            ("+timestamp",),
            error_on_unexpected=False,
        )
        if key.value is None:
            key.update(self._create_timeseries(key.key, *left_args))
        timeseries = key.value
        if ts is None:
            if len(timeseries.sorted_list) == 0:
                ts = int(time.time())
            else:
                ts = timeseries.sorted_list[-1][0]
        if len(timeseries.sorted_list) > 0 and ts < timeseries.sorted_list[-1][0]:
            raise SimpleError(msgs.TIMESERIES_INVALID_TIMESTAMP)
        try:
            return key.value.incrby(ts, addend)
        except ValueError:
            msg = (
                msgs.TIMESERIES_TIMESTAMP_LOWER_THAN_MAX_V7
                if self.version >= (7,)
                else msgs.TIMESERIES_TIMESTAMP_LOWER_THAN_MAX_V6
            )
            raise SimpleError(msg)

    @command(name="TS.INCRBY", fixed=(Key(TimeSeries), Float), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def ts_incrby(self, key: CommandItem, addend: float, *args: bytes) -> bytes:
        return self._ts_inc_or_dec(key, addend, *args)

    @command(name="TS.DECRBY", fixed=(Key(TimeSeries), Float), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def ts_decrby(self, key: CommandItem, subtrahend: float, *args: bytes) -> bytes:
        return self._ts_inc_or_dec(key, -subtrahend, *args)

    @command(name="TS.ALTER", fixed=(Key(TimeSeries),), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def ts_alter(self, key: CommandItem, *args: bytes) -> bytes:
        if key.value is None:
            raise SimpleError(msgs.TIMESERIES_KEY_DOES_NOT_EXIST)

        ((retention, chunk_size, duplicate_policy, (ignore_max_time_diff, ignore_max_val_diff)), left_args) = (
            extract_args(
                args, ("+retention", "+chunk_size", "*duplicate_policy", "++ignore"), error_on_unexpected=False
            )
        )

        if chunk_size is not None and chunk_size % 8 != 0:
            raise SimpleError(msgs.TIMESERIES_BAD_CHUNK_SIZE)
        if not self._validate_duplicate_policy(duplicate_policy):
            raise SimpleError(msgs.TIMESERIES_INVALID_DUPLICATE_POLICY)
        duplicate_policy = duplicate_policy.lower() if duplicate_policy else None
        if len(left_args) > 0 and (not casematch(left_args[0], b"LABELS") or len(left_args) % 2 != 1):
            raise SimpleError(msgs.BAD_SUBCOMMAND_MSG.format("TS.ADD"))
        labels = dict(zip(left_args[1::2], left_args[2::2])) if len(left_args) > 0 else {}

        key.value.retention = retention or key.value.retention
        key.value.chunk_size = chunk_size or key.value.chunk_size
        key.value.duplicate_policy = duplicate_policy or key.value.duplicate_policy
        key.value.ignore_max_time_diff = ignore_max_time_diff or key.value.ignore_max_time_diff
        key.value.ignore_max_val_diff = ignore_max_val_diff or key.value.ignore_max_val_diff
        key.value.labels = labels or key.value.labels
        key.updated()
        return OK

    def _range(
        self, reverse: bool, ts: TimeSeries, from_ts: int, to_ts: int, *args: bytes
    ) -> List[List[Union[int, float]]]:
        RANGE_ARGS = ("latest", "++filter_by_value", "+count", "*align", "*+aggregation", "*buckettimestamp", "empty")
        (
            (
                latest,
                (value_min, value_max),
                count,
                align,
                (aggregator, bucket_duration),
                bucket_timestamp,
                empty,
            ),
            left_args,
        ) = extract_args(args, RANGE_ARGS, error_on_unexpected=False, left_from_first_unexpected=False)
        latest = True
        filter_ts: Optional[List[int]] = None
        if len(left_args) > 0:
            if not casematch(left_args[0], b"FILTER_BY_TS"):
                raise SimpleError(msgs.WRONG_ARGS_MSG6)
            left_args = left_args[1:]
            filter_ts = [int(x) for x in left_args]
        if aggregator is None and (align is not None or bucket_timestamp is not None or empty):
            raise SimpleError(msgs.WRONG_ARGS_MSG6)
        if bucket_timestamp is not None and bucket_timestamp not in (b"-", b"+", b"~"):
            raise SimpleError(msgs.WRONG_ARGS_MSG6)
        if align is not None:
            if align == b"+":
                align = to_ts
            elif align == b"-":
                align = from_ts
            else:
                align = int(align)
        if aggregator is not None and aggregator not in AGGREGATORS:
            raise SimpleError(msgs.TIMESERIES_BAD_AGGREGATION_TYPE)
        if aggregator is None:
            res = ts.range(from_ts, to_ts, value_min, value_max, count, filter_ts, reverse)
        else:
            res = ts.aggregate(
                from_ts,
                to_ts,
                latest,
                value_min,
                value_max,
                count,
                filter_ts,
                align,
                aggregator,
                bucket_duration,
                bucket_timestamp,
                empty,
                reverse,
            )

        res = [[x[0], x[1]] for x in res]
        return res

    @command(
        name="TS.RANGE", fixed=(Key(TimeSeries), Timestamp, Timestamp), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE
    )
    def ts_range(self, key: CommandItem, from_ts: int, to_ts: int, *args: bytes) -> List[List[Union[int, float]]]:
        if key.value is None:
            raise SimpleError(msgs.TIMESERIES_KEY_DOES_NOT_EXIST)
        return self._range(False, key.value, from_ts, to_ts, *args)

    @command(
        name="TS.REVRANGE",
        fixed=(Key(TimeSeries), Timestamp, Timestamp),
        repeat=(bytes,),
        flags=msgs.FLAG_DO_NOT_CREATE,
    )
    def ts_revrange(self, key: CommandItem, from_ts: int, to_ts: int, *args: bytes) -> List[List[Union[int, float]]]:
        if key.value is None:
            raise SimpleError(msgs.TIMESERIES_KEY_DOES_NOT_EXIST)
        res = self._range(True, key.value, from_ts, to_ts, *args)
        return res

    @command(name="TS.MGET", fixed=(bytes,), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def ts_mget(self, *args: bytes) -> List[List[Union[bytes, List[List[Union[int, float]]]]]]:
        latest, with_labels, selected_labels, filter_expression = False, False, None, None
        i = 0
        while i < len(args):
            if casematch(args[i], b"LATEST"):
                latest = True  # noqa: F841
                i += 1
            elif casematch(args[i], b"WITHLABELS"):
                with_labels = True
                i += 1
            elif casematch(args[i], b"SELECTED_LABELS"):
                selected_labels = []
                i += 1
                while i < len(args) and casematch(args[i], b"FILTER"):
                    selected_labels.append(args[i])
            elif casematch(args[i], b"FILTER"):
                filter_expression = []
                i += 1
                while i < len(args):
                    filter_expression.append(args[i])
                    i += 1

        if with_labels and selected_labels is not None:
            raise SimpleError(msgs.WRONG_ARGS_MSG6.format("ts.mget"))
        if filter_expression is None or len(filter_expression) == 0:
            raise SimpleError(msgs.WRONG_ARGS_MSG6.format("ts.mget"))

        timeseries = self._get_timeseries(filter_expression)
        if self._client_info.protocol_version == 2:
            if with_labels:
                return [[ts.name, [[k, v] for (k, v) in ts.labels.items()], ts.get()] for ts in timeseries]
            if selected_labels is not None:
                res = [
                    [ts.name, [[label, ts.labels[label]] for label in selected_labels if label in ts.labels], ts.get()]
                    for ts in timeseries
                ]
            else:
                res = [[ts.name, [], ts.get()] for ts in timeseries]
        else:
            if with_labels:
                res = {ts.name: [ts.labels, ts.get() or []] for ts in timeseries}
            elif selected_labels is not None:
                res = {
                    ts.name: [
                        {label: ts.labels[label] for label in selected_labels if label in ts.labels},
                        ts.get() or [],
                    ]
                    for ts in timeseries
                }
            else:
                res = {ts.name: [{}, ts.get() or []] for ts in timeseries}
        return res

    @command(name="TS.QUERYINDEX", fixed=(bytes,), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def ts_queryindex(self, *args: bytes) -> List[bytes]:
        filter_expressions = list(args)
        timeseries = self._get_timeseries(filter_expressions)
        return [ts.name for ts in timeseries]

    def _group_by_label(
        self, reverse: bool, ts_dict: Dict[bytes, List[Any]], label: bytes, reducer: bytes
    ) -> Dict[bytes, List[Any]]:
        # ts_dict: name -> [labels, ..., measurements]
        reducer = reducer.lower()
        if reducer not in AGGREGATORS:
            raise SimpleError(msgs.TIMESERIES_BAD_AGGREGATION_TYPE)
        ts_map: Dict[bytes, Dict[int, List[float]]] = {}  # label_value -> timestamp -> values
        for ts_data in ts_dict.values():
            # Find label value
            labels_dict = ts_data[0]
            label_value = labels_dict.get(label, None)
            if not label_value:
                raise SimpleError(msgs.TIMESERIES_BAD_FILTER_EXPRESSION)
            if label_value not in ts_map:
                ts_map[label_value] = {}
            # Collect measurements
            for timestamp, value in ts_data[-1]:
                if timestamp not in ts_map[label_value]:
                    ts_map[label_value][timestamp] = []
                ts_map[label_value][timestamp].append(value)
        res = {}
        for label_value, timestamp_values in ts_map.items():
            sorted_timestamps = sorted(timestamp_values.keys())
            name = f"{label.decode()}={label_value.decode()}"
            sources = [ts_name.decode() for ts_name in ts_map.keys()]
            labels = {label: label_value, b"__reducer__": reducer, b"__source__": sources}
            measurements: List[List[Union[int, float]]] = [
                [timestamp, float(AGGREGATORS[reducer](timestamp_values[timestamp]))] for timestamp in sorted_timestamps
            ]
            if reverse:
                measurements.reverse()
            res[name.encode("utf-8")] = [labels, {b"reducers": [reducer]}, {b"sources": sources}, measurements]
        return res

    def _mrange(self, reverse: bool, from_ts: int, to_ts: int, *args: bytes):
        args_lower = [arg.lower() for arg in args]
        arg_words = {
            b"latest",
            b"withlabels",
            b"selected_labels",
            b"filter",
            b"groupby",
            b"reduce",
            b"count",
            b"aggregation",
            b"filter_by_value",
            b"filter_by_ts",
            b"align",
            b"aggregation",
        }
        left_args = []
        latest, with_labels, selected_labels, filter_expression, group_by, reducer = (
            False,
            False,
            None,
            None,
            None,
            None,
        )
        i = 0
        while i < len(args_lower):
            if args_lower[i] == b"latest":
                latest = True  # noqa: F841
                i += 1
            elif args_lower[i] == b"withlabels":
                with_labels = True
                i += 1
            elif args_lower[i] == b"selected_labels":
                selected_labels = []
                i += 1
                while i < len(args_lower) and args_lower[i] not in arg_words:
                    selected_labels.append(args_lower[i])
                    i += 1
            elif args_lower[i] == b"filter":
                filter_expression = []
                i += 1
                while i < len(args_lower) and args_lower[i] not in arg_words:
                    filter_expression.append(args[i])
                    i += 1
            elif i + 3 < len(args_lower) and args_lower[i] == b"groupby" and args_lower[i + 2] == b"reduce":
                group_by = args[i + 1]
                reducer = args_lower[i + 3]
                i += 4
            else:
                left_args.append(args[i])
                i += 1

        if with_labels and selected_labels is not None:
            raise SimpleError(msgs.WRONG_ARGS_MSG6.format("ts.mrange"))
        if filter_expression is None or len(filter_expression) == 0:
            raise SimpleError(msgs.WRONG_ARGS_MSG6.format("ts.mrange"))

        timeseries = self._get_timeseries(filter_expression)
        res: Dict[bytes, List[Any]]
        if with_labels or (group_by is not None and reducer is not None):
            res = {
                ts.name: [ts.labels, {b"aggregators": []}, self._range(reverse, ts, from_ts, to_ts, *left_args)]
                for ts in timeseries
            }
        elif selected_labels is not None:
            res = {
                ts.name: [
                    {label: ts.labels[label] for label in selected_labels if label in ts.labels},
                    {b"aggregators": []},
                    self._range(reverse, ts, from_ts, to_ts, *left_args),
                ]
                for ts in timeseries
            }
        else:
            res = {
                ts.name: [
                    {},
                    {b"aggregators": []},
                    self._range(reverse, ts, from_ts, to_ts, *left_args),
                ]
                for ts in timeseries
            }
        if group_by is not None and reducer is not None:
            res = self._group_by_label(reverse, res, group_by, reducer)
        if self._client_info.protocol_version == 2:
            res = [[ts_name, [[k, v] for k, v in ts_data[0].items()], ts_data[-1]] for ts_name, ts_data in res.items()]
        return res

    @command(name="TS.MRANGE", fixed=(Timestamp, Timestamp), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def ts_mrange(
        self, from_ts: int, to_ts: int, *args: bytes
    ) -> List[List[Union[bytes, List[List[Union[int, float]]]]]]:
        return self._mrange(False, from_ts, to_ts, *args)

    @command(name="TS.MREVRANGE", fixed=(Timestamp, Timestamp), repeat=(bytes,), flags=msgs.FLAG_DO_NOT_CREATE)
    def ts_mrevrange(
        self, from_ts: int, to_ts: int, *args: bytes
    ) -> List[List[Union[bytes, List[List[Union[int, float]]]]]]:
        return self._mrange(True, from_ts, to_ts, *args)
