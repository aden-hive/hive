"""Command mixin for emulating `redis-py`'s JSON functionality."""

import copy
import json
from json import JSONDecodeError
from typing import Any, Union, Dict, List, Optional, Callable, Tuple, Type

from jsonpath_ng import Root, JSONPath
from jsonpath_ng.exceptions import JsonPathParserError
from jsonpath_ng.ext import parse

from fakeredis import _helpers as helpers
from fakeredis import _msgs as msgs
from fakeredis._command_args_parsing import extract_args
from fakeredis._commands import Key, command, delete_keys, CommandItem, Int, Float
from fakeredis._helpers import SimpleString
from fakeredis.model import ZSet, ClientInfo

JsonType = Union[str, int, float, bool, None, Dict[str, Any], List[Any]]


def _format_path(path: Union[bytes, str]) -> str:
    path_str = path.decode() if isinstance(path, bytes) else path
    if path_str == ".":
        return "$"
    elif path_str.startswith("."):
        return "$" + path_str
    elif path_str.startswith("$"):
        return path_str
    else:
        return "$." + path_str


def _parse_jsonpath(path: Union[str, bytes]) -> JSONPath:
    path_str: str = _format_path(path)
    try:
        return parse(path_str)
    except JsonPathParserError:
        raise helpers.SimpleError(msgs.JSON_PATH_DOES_NOT_EXIST.format(path_str))


def _path_is_root(path: JSONPath) -> bool:
    return path == Root()  # type: ignore


def _dict_deep_merge(source: JsonType, destination: Dict[str, Any]) -> Dict[str, Any]:
    """Deep merge of two dictionaries"""
    if not isinstance(source, dict):
        return destination
    for key, value in source.items():
        if value is None and key in destination:
            del destination[key]
        elif isinstance(value, dict):
            node = destination.setdefault(key, {})
            _dict_deep_merge(value, node)
        else:
            destination[key] = value

    return destination


class JSONObject:
    """Argument converter for JSON objects."""

    DECODE_ERROR = msgs.JSON_WRONG_REDIS_TYPE
    ENCODE_ERROR = msgs.JSON_WRONG_REDIS_TYPE

    @classmethod
    def decode(cls, value: bytes) -> Any:
        """Deserialize the supplied bytes into a valid Python object."""
        try:
            return json.loads(value)
        except JSONDecodeError:
            raise helpers.SimpleError(cls.DECODE_ERROR)

    @classmethod
    def encode(cls, value: Any) -> Optional[bytes]:
        """Serialize the supplied Python object into a valid, JSON-formatted
        byte-encoded string."""
        return json.dumps(value, default=str).encode() if value is not None else None


def _json_write_iterate(
    method: Callable[[JsonType], Tuple[Optional[JsonType], Optional[JsonType], bool]],
    key: CommandItem,
    path_str: Union[str, bytes],
    allow_result_none: bool = False,
) -> Union[List[Optional[JsonType]], Optional[JsonType]]:
    """Implement json.* write commands.
    Iterate over values with path_str in key and running method to get new value for path item.
    """
    if key.value is None:
        raise helpers.SimpleError(msgs.JSON_KEY_NOT_FOUND)
    path = _parse_jsonpath(path_str)
    found_matches = path.find(key.value)
    if len(found_matches) == 0:
        raise helpers.SimpleError(msgs.JSON_PATH_NOT_FOUND_OR_NOT_STRING.format(path_str))

    curr_value = copy.deepcopy(key.value)
    res: List[Optional[JsonType]] = []
    for item in found_matches:
        new_value, res_val, update = method(item.value)
        if update:
            curr_value = item.full_path.update(curr_value, new_value)
        res.append(res_val)

    key.update(curr_value)

    if len(path_str) > 1 and path_str[0] == ord(b"."):
        if allow_result_none:
            return res[-1]
        else:
            return next(x for x in reversed(res) if x is not None)
    if len(res) == 1 and (path_str[0] != ord(b"$") or path_str == b"."):
        return res[0]
    return res


def _json_read_iterate(
    method: Callable[[JsonType], Optional[Any]],
    key: CommandItem,
    *args: Any,
    error_on_zero_matches: bool = False,
) -> Union[List[Optional[Any]], Optional[Any]]:
    path_str = args[0] if len(args) > 0 else "$"
    if key.value is None:
        if path_str[0] == ord(b"$"):
            raise helpers.SimpleError(msgs.JSON_KEY_NOT_FOUND)
        else:
            return None

    path = _parse_jsonpath(path_str)
    found_matches = path.find(key.value)
    if error_on_zero_matches and len(found_matches) == 0 and path_str[0] != ord(b"$"):
        raise helpers.SimpleError(msgs.JSON_PATH_NOT_FOUND_OR_NOT_STRING.format(path_str))
    res = [method(item.value) for item in found_matches]

    if len(path_str) > 1 and path_str[0] == ord(b"."):
        return res[0] if len(res) > 0 else None
    if len(res) == 1 and (len(args) == 0 or path_str[0] == ord(b".")):
        return res[0]

    return res


class JSONCommandsMixin:
    """`CommandsMixin` for enabling RedisJSON compatibility in `fakeredis`."""

    TYPES_EMPTY_VAL_DICT: Dict[Type[object], Any] = {
        dict: {},
        int: 0,
        float: 0.0,
        list: [],
    }
    TYPE_NAMES: Dict[Type[object], bytes] = {
        dict: b"object",
        int: b"integer",
        float: b"number",
        bytes: b"string",
        list: b"array",
        set: b"set",
        str: b"string",
        bool: b"boolean",
        type(None): b"null",
        ZSet: b"zset",
    }

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._db: helpers.Database
        self._client_info: ClientInfo

    @staticmethod
    def _get_single(
        key: CommandItem,
        path_str: Union[str, bytes],
        always_return_list: bool = False,
        empty_list_as_none: bool = False,
    ) -> Any:
        path: JSONPath = _parse_jsonpath(path_str)
        path_value = path.find(key.value)
        val = [i.value for i in path_value]
        if empty_list_as_none and len(val) == 0:
            return None
        elif len(val) == 1 and not always_return_list:
            return val[0]
        return val

    @command(
        name=["JSON.DEL", "JSON.FORGET"],
        fixed=(Key(),),
        repeat=(bytes,),
        flags=msgs.FLAG_LEAVE_EMPTY_VAL,
    )
    def json_del(self, key: CommandItem, path_str: bytes) -> int:
        if key.value is None:
            return 0

        path = _parse_jsonpath(path_str)
        if _path_is_root(path):
            delete_keys(key)
            return 1
        curr_value = copy.deepcopy(key.value)

        found_matches = path.find(curr_value)
        res = 0
        while len(found_matches) > 0:
            item = found_matches[0]
            curr_value = item.full_path.filter(lambda _: True, curr_value)
            res += 1
            found_matches = path.find(curr_value)

        key.update(curr_value)
        return res

    @staticmethod
    def _json_set(key: CommandItem, path_str: bytes, value: JsonType, *args: Any) -> Optional[SimpleString]:
        path = _parse_jsonpath(path_str)
        if key.value is not None and (type(key.value) is not dict) and not _path_is_root(path):
            raise helpers.SimpleError(msgs.JSON_WRONG_REDIS_TYPE)
        old_value_list = path.find(key.value)
        (nx, xx), _ = extract_args(args, ("nx", "xx"))
        if xx and nx:
            raise helpers.SimpleError(msgs.SYNTAX_ERROR_MSG)
        old_value = old_value_list[0].value if len(old_value_list) > 0 else None
        if (nx and old_value is not None) or (xx and old_value is None):
            return None
        new_value = path.update_or_create(key.value, value)
        key.update(new_value)
        return helpers.OK

    @command(
        name="JSON.SET",
        fixed=(Key(), bytes, JSONObject),
        repeat=(bytes,),
        flags=msgs.FLAG_LEAVE_EMPTY_VAL + msgs.FLAG_DO_NOT_CREATE,
    )
    def json_set(self, key: CommandItem, path_str: bytes, value: JsonType, *args: bytes) -> Optional[SimpleString]:
        """Set the JSON value at key `name` under the `path` to `obj`.

        For more information see `JSON.SET <https://redis.io/commands/json.set>`_.
        """
        return JSONCommandsMixin._json_set(key, path_str, value, *args)

    @command(name="JSON.GET", fixed=(Key(),), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_get(self, key: CommandItem, *args: bytes) -> Optional[bytes]:
        if key.value is None:
            return None
        paths = [arg for arg in args if not helpers.casematch(b"noescape", arg)]
        no_wrapping_array = len(paths) == 1 and paths[0][0] == ord(b".")

        formatted_paths: List[str] = [_format_path(arg) for arg in args if not helpers.casematch(b"noescape", arg)]
        path_values = [self._get_single(key, path, len(formatted_paths) > 1) for path in formatted_paths]

        # Emulate the behavior of `redis-py`:
        #   - if only one path was supplied => return a single value
        #   - if more than one path was specified => return one value for each specified path
        if no_wrapping_array or (len(path_values) == 1 and isinstance(path_values[0], list)):
            return JSONObject.encode(path_values[0])
        if len(path_values) == 1:
            return JSONObject.encode(path_values)
        return JSONObject.encode(dict(zip(formatted_paths, path_values)))

    @command(name="JSON.MGET", fixed=(bytes,), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_mget(self, *args: bytes) -> List[Optional[bytes]]:
        if len(args) < 2:
            raise helpers.SimpleError(msgs.WRONG_ARGS_MSG6.format("json.mget"))
        path_str = args[-1]
        keys = [CommandItem(key, self._db, item=self._db.get(key), default=[]) for key in args[:-1]]

        result = [JSONObject.encode(self._get_single(key, path_str, empty_list_as_none=True)) for key in keys]
        return result

    @command(name="JSON.TOGGLE", fixed=(Key(),), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_toggle(self, key: CommandItem, *args: bytes) -> Union[List[Optional[bool]], Optional[bool]]:
        if key.value is None:
            raise helpers.SimpleError(msgs.JSON_KEY_NOT_FOUND)
        path_str = args[0] if len(args) > 0 else b"$"
        path = _parse_jsonpath(path_str)
        found_matches = path.find(key.value)

        curr_value = copy.deepcopy(key.value)
        res: List[Optional[bool]] = []
        for item in found_matches:
            if type(item.value) is bool:
                curr_value = item.full_path.update(curr_value, not item.value)
                res.append(not item.value)
            else:
                res.append(None)
        if all(x is None for x in res):
            raise helpers.SimpleError(msgs.JSON_KEY_NOT_FOUND)
        key.update(curr_value)

        if len(res) == 1 and (len(args) == 0 or (len(args) == 1 and args[0] == b".")):
            return res[0]

        return res

    @command(name="JSON.CLEAR", fixed=(Key(),), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_clear(self, key: CommandItem, *args: bytes) -> int:
        if key.value is None:
            raise helpers.SimpleError(msgs.JSON_KEY_NOT_FOUND)
        path_str: bytes = args[0] if len(args) > 0 else b"$"
        path = _parse_jsonpath(path_str)
        found_matches = path.find(key.value)
        curr_value = copy.deepcopy(key.value)
        res = 0
        for item in found_matches:
            new_val = self.TYPES_EMPTY_VAL_DICT.get(type(item.value), None)
            if new_val is not None:
                curr_value = item.full_path.update(curr_value, new_val)
                res += 1

        key.update(curr_value)
        return res

    @command(name="JSON.STRAPPEND", fixed=(Key(), bytes), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_strappend(
        self, key: CommandItem, path_str: bytes, *args: bytes
    ) -> Union[List[Optional[JsonType]], Optional[JsonType]]:
        if len(args) == 0:
            raise helpers.SimpleError(msgs.WRONG_ARGS_MSG6.format("json.strappend"))
        addition = JSONObject.decode(args[0])

        def strappend(val: JsonType) -> Tuple[Optional[JsonType], Optional[int], bool]:
            if type(val) is str:
                new_value = val + addition
                return new_value, len(new_value), True
            else:
                return None, None, False

        return _json_write_iterate(strappend, key, path_str)

    @command(name="JSON.ARRAPPEND", fixed=(Key(), bytes), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_arrappend(
        self, key: CommandItem, path_str: bytes, *args: bytes
    ) -> Union[List[Optional[JsonType]], Optional[JsonType]]:
        if len(args) == 0:
            raise helpers.SimpleError(msgs.WRONG_ARGS_MSG6.format("json.arrappend"))

        addition = [JSONObject.decode(item) for item in args]

        def arrappend(val: JsonType) -> Tuple[Optional[JsonType], Optional[int], bool]:
            if type(val) is list:
                new_value = val + addition
                return new_value, len(new_value), True
            else:
                return None, None, False

        return _json_write_iterate(arrappend, key, path_str)

    @command(name="JSON.ARRINSERT", fixed=(Key(), bytes, Int), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_arrinsert(
        self, key: CommandItem, path_str: bytes, index: int, *args: bytes
    ) -> Union[List[Optional[JsonType]], Optional[JsonType]]:
        if len(args) == 0:
            raise helpers.SimpleError(msgs.WRONG_ARGS_MSG6.format("json.arrinsert"))

        addition = [JSONObject.decode(item) for item in args]

        def arrinsert(val: JsonType) -> Tuple[Optional[JsonType], Optional[int], bool]:
            if type(val) is list:
                new_value = val[:index] + addition + val[index:]
                return new_value, len(new_value), True
            else:
                return None, None, False

        return _json_write_iterate(arrinsert, key, path_str)

    @command(name="JSON.ARRPOP", fixed=(Key(),), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_arrpop(self, key: CommandItem, *args: bytes) -> Union[List[Optional[JsonType]], Optional[JsonType]]:
        path_str: Union[bytes, str] = args[0] if len(args) > 0 else "$"
        index = Int.decode(args[1]) if len(args) > 1 else -1

        def arrpop(val: JsonType) -> Tuple[Optional[JsonType], Optional[bytes], bool]:
            if type(val) is list and len(val) > 0:
                ind = index if index < len(val) else -1
                res = val.pop(ind)
                return val, JSONObject.encode(res), True
            else:
                return None, None, False

        return _json_write_iterate(arrpop, key, path_str, allow_result_none=True)

    @command(name="JSON.ARRTRIM", fixed=(Key(),), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_arrtrim(self, key: CommandItem, *args: bytes) -> Union[List[Optional[JsonType]], Optional[JsonType]]:
        path_str: bytes = args[0] if len(args) > 0 else b"$"
        start = Int.decode(args[1]) if len(args) > 1 else 0
        stop = Int.decode(args[2]) if len(args) > 2 else None

        def arrtrim(val: JsonType) -> Tuple[Optional[JsonType], Optional[int], bool]:
            if type(val) is list:
                start_ind = min(start, len(val))
                stop_ind = len(val) if stop is None or stop == -1 else stop + 1
                if stop_ind < 0:
                    stop_ind = len(val) + stop_ind + 1
                new_val = val[start_ind:stop_ind]
                return new_val, len(new_val), True
            else:
                return None, None, False

        return _json_write_iterate(arrtrim, key, path_str)

    @command(
        name="JSON.NUMINCRBY",
        fixed=(Key(), bytes, Float),
        repeat=(bytes,),
        flags=msgs.FLAG_LEAVE_EMPTY_VAL + msgs.FLAG_SKIP_CONVERT_TO_RESP2,
    )
    def json_numincrby(
        self, key: CommandItem, path_str: bytes, inc_by: float, *_: bytes
    ) -> Union[List[Optional[JsonType]], Optional[JsonType]]:
        def numincrby(val: Optional[JsonType]) -> Tuple[Optional[JsonType], Optional[float], bool]:
            if val is not None and type(val) in {int, float}:
                new_value = val + inc_by  # type: ignore
                return new_value, new_value, True
            else:
                return None, None, False

        return self._resp3_wrapping_list(_json_write_iterate(numincrby, key, path_str))

    @command(
        name="JSON.NUMMULTBY",
        fixed=(Key(), bytes, Float),
        repeat=(bytes,),
        flags=msgs.FLAG_LEAVE_EMPTY_VAL + msgs.FLAG_SKIP_CONVERT_TO_RESP2,
    )
    def json_nummultby(
        self, key: CommandItem, path_str: bytes, mult_by: float, *_: bytes
    ) -> Union[List[Optional[JsonType]], Optional[JsonType]]:
        def nummultby(val: Optional[JsonType]) -> Tuple[Optional[JsonType], Optional[float], bool]:
            if type(val) in {int, float}:
                new_value = val * mult_by  # type: ignore
                return new_value, new_value, True
            else:
                return None, None, False

        return self._resp3_wrapping_list(_json_write_iterate(nummultby, key, path_str))

    # Read operations
    @command(name="JSON.ARRINDEX", fixed=(Key(), bytes, bytes), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_arrindex(
        self, key: CommandItem, path_str: bytes, encoded_value: bytes, *args: bytes
    ) -> Union[List[Optional[JsonType]], Optional[JsonType]]:
        start = max(0, Int.decode(args[0]) if len(args) > 0 else 0)
        end = Int.decode(args[1]) if len(args) > 1 else -1
        end = end if end > 0 else -1
        expected_value = JSONObject.decode(encoded_value)

        def check_index(value: JsonType) -> Optional[int]:
            if type(value) is not list:
                return None
            try:
                ind = next(
                    filter(
                        lambda x: x[1] == expected_value and type(x[1]) is type(expected_value),
                        enumerate(value[start:end]),
                    )
                )
                return ind[0] + start
            except StopIteration:
                return -1

        return _json_read_iterate(check_index, key, path_str, error_on_zero_matches=True)

    @command(name="JSON.STRLEN", fixed=(Key(),), repeat=(bytes,))
    def json_strlen(self, key: CommandItem, *args: bytes) -> Union[List[Optional[int]], Optional[int]]:
        return _json_read_iterate(lambda val: len(val) if type(val) is str else None, key, *args)

    @command(name="JSON.ARRLEN", fixed=(Key(),), repeat=(bytes,))
    def json_arrlen(self, key: CommandItem, *args: bytes) -> Union[List[Optional[int]], Optional[int]]:
        return _json_read_iterate(lambda val: len(val) if type(val) is list else None, key, *args)

    @command(name="JSON.OBJLEN", fixed=(Key(),), repeat=(bytes,))
    def json_objlen(self, key: CommandItem, *args: bytes) -> Union[List[Optional[int]], Optional[int]]:
        return _json_read_iterate(lambda val: len(val) if type(val) is dict else None, key, *args)

    def _resp3_wrapping_list(self, res: Any, wrap_list: bool = False) -> Any:
        if self._client_info.protocol_version == 2:
            return res
        if isinstance(res, list) and not wrap_list:
            return res
        return [res]

    @command(name="JSON.TYPE", fixed=(Key(),), repeat=(bytes,), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_type(self, key: CommandItem, *args: bytes) -> Union[List[Optional[bytes]], Optional[bytes]]:
        res = _json_read_iterate(lambda val: self.TYPE_NAMES.get(type(val), None), key, *args)
        return self._resp3_wrapping_list(res, wrap_list=True)

    @command(name="JSON.OBJKEYS", fixed=(Key(),), repeat=(bytes,))
    def json_objkeys(self, key: CommandItem, *args: bytes) -> Union[List[Optional[bytes]], Optional[bytes]]:
        return _json_read_iterate(
            lambda val: [i.encode() for i in val.keys()] if type(val) is dict else None, key, *args
        )

    @command(name="JSON.MSET", fixed=(), repeat=(Key(), bytes, JSONObject), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_mset(self, *args: Any) -> SimpleString:
        if len(args) < 3 or len(args) % 3 != 0:
            raise helpers.SimpleError(msgs.WRONG_ARGS_MSG6.format("json.mset"))
        for i in range(0, len(args), 3):
            key, path_str, value = args[i], args[i + 1], args[i + 2]
            JSONCommandsMixin._json_set(key, path_str, value)
        return helpers.OK

    @command(name="JSON.MERGE", fixed=(Key(), bytes, JSONObject), repeat=(), flags=msgs.FLAG_LEAVE_EMPTY_VAL)
    def json_merge(self, key: CommandItem, path_str: bytes, value: JsonType) -> SimpleString:
        path: JSONPath = _parse_jsonpath(path_str)
        if key.value is not None and (type(key.value) is not dict) and not _path_is_root(path):
            raise helpers.SimpleError(msgs.JSON_WRONG_REDIS_TYPE)
        matching = path.find(key.value)
        for item in matching:
            prev_value = item.value if item is not None else {}
            _dict_deep_merge(value, prev_value)
        if len(matching) > 0:
            key.updated()
        return helpers.OK
