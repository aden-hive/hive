import functools
import hashlib
import importlib
import itertools
import json
import logging
import os
from typing import Callable, AnyStr, Set, Any, Tuple, List, Optional

import lupa

from fakeredis import _msgs as msgs
from fakeredis._commands import command, Int, Signature, Float
from fakeredis._helpers import (
    SimpleError,
    SimpleString,
    null_terminate,
    OK,
    decode_command_bytes,
)
from fakeredis._typing import VersionType

__LUA_RUNTIMES_MAP = {
    "5.1": "lupa.lua51",
    "5.2": "lupa.lua52",
    "5.3": "lupa.lua53",
    "5.4": "lupa.lua54",
}
LUA_VERSION = os.getenv("FAKEREDIS_LUA_VERSION", "5.1")

with lupa.allow_lua_module_loading():
    LUA_MODULE = importlib.import_module(__LUA_RUNTIMES_MAP[LUA_VERSION])

LOGGER = logging.getLogger("fakeredis")
REDIS_LOG_LEVELS = {
    b"LOG_DEBUG": 0,
    b"LOG_VERBOSE": 1,
    b"LOG_NOTICE": 2,
    b"LOG_WARNING": 3,
}
REDIS_LOG_LEVELS_TO_LOGGING = {
    0: logging.DEBUG,
    1: logging.INFO,
    2: logging.INFO,
    3: logging.WARNING,
}


def _ensure_str(s: AnyStr, encoding: str, replaceerr: str) -> str:
    if isinstance(s, bytes):
        res = s.decode(encoding=encoding, errors=replaceerr)
    else:
        res = str(s)
    return res


def _check_for_lua_globals(lua_runtime: LUA_MODULE.LuaRuntime, expected_globals: Set[Any]) -> None:
    unexpected_globals = set(lua_runtime.globals().keys()) - expected_globals
    if len(unexpected_globals) > 0:
        unexpected = [_ensure_str(var, "utf-8", "replace") for var in unexpected_globals]
        raise SimpleError(msgs.GLOBAL_VARIABLE_MSG.format(", ".join(unexpected)))


def _lua_redis_log(lua_runtime: LUA_MODULE.LuaRuntime, expected_globals: Set[Any], lvl: int, *args: Any) -> None:
    _check_for_lua_globals(lua_runtime, expected_globals)
    if len(args) < 1:
        raise SimpleError(msgs.REQUIRES_MORE_ARGS_MSG.format("redis.log()", "two"))
    if lvl not in REDIS_LOG_LEVELS_TO_LOGGING.keys():
        raise SimpleError(msgs.LOG_INVALID_DEBUG_LEVEL_MSG)
    msg = " ".join([x.decode("utf-8") if isinstance(x, bytes) else str(x) for x in args if not isinstance(x, bool)])
    LOGGER.log(REDIS_LOG_LEVELS_TO_LOGGING[lvl], msg)


_lua_cjson_null = object()  # sentinel value


def _cjson_python_to_lua(obj: Any) -> Any:
    """Convert a pure python object obtained after JSON deserialization into a usable object in the lua runtime."""
    if obj is None:
        return _lua_cjson_null
    if isinstance(obj, str):
        return obj.encode()
    if isinstance(obj, list):
        return [_cjson_python_to_lua(item) for item in obj]
    if isinstance(obj, dict):
        return {_cjson_python_to_lua(key): _cjson_python_to_lua(value) for key, value in obj.items()}
    return obj


def _cjson_lua_to_python(obj: Any) -> Any:
    """Convert a passed lua runtime object obtained before JSON serialization into a pure python object."""
    if obj is _lua_cjson_null:
        return None
    if isinstance(obj, bytes):
        return obj.decode()

    lua_type = LUA_MODULE.lua_type(obj)
    if lua_type != "table":
        return obj

    # Check for array-like structure: integer keys from 1 to len(items)
    # (this check matches what cjson does, e.g. tables like {"a", "b", c=3} are treated as dicts
    # with int keys for the array-like parts)
    keys = list(obj.keys())
    is_array = all(isinstance(k, int) for k in keys) and sorted(keys) == list(range(1, len(keys) + 1))

    if is_array:
        return [_cjson_lua_to_python(item) for item in obj.values()]

    # We're working with a dict
    d = dict(obj)
    return {_cjson_lua_to_python(key): _cjson_lua_to_python(value) for key, value in d.items()}


def _lua_cjson_encode(lua_runtime: LUA_MODULE.LuaRuntime, expected_globals: Set[Any], value: Any) -> bytes:
    _check_for_lua_globals(lua_runtime, expected_globals)
    value = _cjson_lua_to_python(value)
    return json.dumps(value, separators=(",", ":")).encode()


def _lua_cjson_decode(lua_runtime: LUA_MODULE.LuaRuntime, expected_globals: Set[Any], json_str: str) -> Any:
    _check_for_lua_globals(lua_runtime, expected_globals)
    json_obj = json.loads(json_str)
    json_obj = _cjson_python_to_lua(json_obj)
    if isinstance(json_obj, (dict, list)):
        json_obj = lua_runtime.table_from(json_obj, recursive=True)
    return json_obj


class ScriptingCommandsMixin:
    _name_to_func: Callable[[str], Tuple[Optional[Callable[..., Any]], Signature]]
    _run_command: Callable[[Callable[..., Any], Signature, List[Any], bool], Any]

    def __init__(self, *args: Any, **kwargs: Any):
        self.version: VersionType
        self.load_lua_modules = set()
        lua_modules_set: Set[str] = kwargs.pop("lua_modules", None) or set()
        if len(lua_modules_set) > 0:
            lua_runtime: LUA_MODULE.LuaRuntime = LUA_MODULE.LuaRuntime(encoding=None, unpack_returned_tuples=True)
            for module in lua_modules_set:
                try:
                    lua_runtime.require(module.encode())
                    self.load_lua_modules.add(module)
                except LUA_MODULE.LuaError as ex:
                    LOGGER.error(f'Failed to load LUA module "{module}", make sure it is installed: {ex}')

        super(ScriptingCommandsMixin, self).__init__(*args, **kwargs)

    def _convert_redis_arg(self, lua_runtime: LUA_MODULE.LuaRuntime, value: Any) -> bytes:
        # Type checks are exact to avoid issues like bool being a subclass of int.
        if type(value) is bytes:
            return value
        elif type(value) in {int, float}:
            return "{:.17g}".format(value).encode()
        else:
            raise SimpleError(msgs.LUA_COMMAND_ARG_MSG)

    def _convert_redis_result(self, lua_runtime: LUA_MODULE.LuaRuntime, result: Any) -> Any:
        if isinstance(result, (bytes, int)):
            return result
        if isinstance(result, float):
            return Float.encode(result, humanfriendly=False)
        elif isinstance(result, SimpleString):
            return lua_runtime.table_from({b"ok": result.value})
        elif result is None:
            return False
        elif isinstance(result, list):
            converted = [self._convert_redis_result(lua_runtime, item) for item in result]
            return lua_runtime.table_from(converted)
        if isinstance(result, dict):
            result = list(itertools.chain(*result.items()))
            converted = [self._convert_redis_result(lua_runtime, item) for item in result]
            return lua_runtime.table_from(converted)
        elif isinstance(result, SimpleError):
            if result.value.startswith("ERR wrong number of arguments"):
                raise SimpleError(msgs.WRONG_ARGS_MSG7)
            raise result
        else:
            raise RuntimeError("Unexpected return type from redis: {}".format(type(result)))

    def _convert_lua_result(self, result: Any, nested: bool = True) -> Any:
        if LUA_MODULE.lua_type(result) == "table":
            for key in (b"ok", b"err"):
                if key in result:
                    msg = self._convert_lua_result(result[key])
                    if not isinstance(msg, bytes):
                        raise SimpleError(msgs.LUA_WRONG_NUMBER_ARGS_MSG)
                    if key == b"ok":
                        return SimpleString(msg)
                    elif nested:
                        return SimpleError(msg.decode("utf-8", "replace"))
                    else:
                        raise SimpleError(msg.decode("utf-8", "replace"))
            # Convert Lua tables into lists, starting from index 1, mimicking the behavior of StrictRedis.
            result_list = []
            for index in itertools.count(1):
                if index not in result:
                    break
                item = result[index]
                result_list.append(self._convert_lua_result(item))
            return result_list
        elif isinstance(result, str):
            return result.encode()
        elif isinstance(result, float):
            return int(result)
        elif isinstance(result, bool):
            return 1 if result else None
        return result

    def _lua_redis_call(
        self, lua_runtime: LUA_MODULE.LuaRuntime, expected_globals: Set[Any], op: bytes, *args: Any
    ) -> Any:
        # Check if we've set any global variables before making any change.
        _check_for_lua_globals(lua_runtime, expected_globals)
        func, sig = self._name_to_func(decode_command_bytes(op))
        new_args = [self._convert_redis_arg(lua_runtime, arg) for arg in args]
        result = self._run_command(func, sig, new_args, True)
        result = self._convert_redis_result(lua_runtime, result)
        return result

    def _lua_redis_pcall(
        self, lua_runtime: LUA_MODULE.LuaRuntime, expected_globals: Set[Any], op: bytes, *args: Any
    ) -> Any:
        try:
            return self._lua_redis_call(lua_runtime, expected_globals, op, *args)
        except Exception as ex:
            return lua_runtime.table_from({b"err": str(ex)})

    @command((bytes, Int), (bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def eval(self, script: bytes, numkeys: int, *keys_and_args: bytes) -> Any:
        if numkeys > len(keys_and_args):
            raise SimpleError(msgs.TOO_MANY_KEYS_MSG)
        if numkeys < 0:
            raise SimpleError(msgs.NEGATIVE_KEYS_MSG)
        sha1 = hashlib.sha1(script).hexdigest().encode()
        self._server.script_cache[sha1] = script
        lua_runtime: LUA_MODULE.LuaRuntime = LUA_MODULE.LuaRuntime(encoding=None, unpack_returned_tuples=True)
        modules_import_str = "\n".join([f"{module} = require('{module}')" for module in self.load_lua_modules])
        set_globals = lua_runtime.eval(
            f"""
            function(keys, argv, redis_call, redis_pcall, redis_log, redis_log_levels, cjson_encode, cjson_decode, cjson_null)
                redis = {{}}
                redis.call = redis_call
                redis.pcall = redis_pcall
                redis.log = redis_log
                for level, pylevel in python.iterex(redis_log_levels.items()) do
                    redis[level] = pylevel
                end
                redis.error_reply = function(msg) return {{err=msg}} end
                redis.status_reply = function(msg) return {{ok=msg}} end

                cjson = {{}}
                cjson.encode = cjson_encode
                cjson.decode = cjson_decode
                cjson.null = cjson_null

                KEYS = keys
                ARGV = argv
                {modules_import_str}
            end
            """
        )
        expected_globals: Set[Any] = set()
        set_globals(
            lua_runtime.table_from(keys_and_args[:numkeys]),
            lua_runtime.table_from(keys_and_args[numkeys:]),
            functools.partial(self._lua_redis_call, lua_runtime, expected_globals),
            functools.partial(self._lua_redis_pcall, lua_runtime, expected_globals),
            functools.partial(_lua_redis_log, lua_runtime, expected_globals),
            LUA_MODULE.as_attrgetter(REDIS_LOG_LEVELS),
            functools.partial(_lua_cjson_encode, lua_runtime, expected_globals),
            functools.partial(_lua_cjson_decode, lua_runtime, expected_globals),
            _lua_cjson_null,
        )
        expected_globals.update(lua_runtime.globals().keys())

        try:
            result = lua_runtime.execute(script)
        except SimpleError as ex:
            if ex.value == msgs.LUA_COMMAND_ARG_MSG:
                if self.version < (7,):
                    raise SimpleError(msgs.LUA_COMMAND_ARG_MSG6)
                elif self._server.server_type == "valkey":
                    raise SimpleError(msgs.VALKEY_LUA_COMMAND_ARG_MSG.format(sha1.decode()))
                else:
                    raise SimpleError(msgs.LUA_COMMAND_ARG_MSG)
            if self.version < (7,):
                raise SimpleError(msgs.SCRIPT_ERROR_MSG.format(sha1.decode(), ex))
            raise SimpleError(ex.value)
        except LUA_MODULE.LuaError as ex:
            raise SimpleError(msgs.SCRIPT_ERROR_MSG.format(sha1.decode(), ex))

        _check_for_lua_globals(lua_runtime, expected_globals)

        return self._convert_lua_result(result, nested=False)

    @command(name="EVALSHA", fixed=(bytes, Int), repeat=(bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def evalsha(self, sha1: bytes, numkeys: Int, *keys_and_args: bytes) -> Any:
        try:
            script = self._server.script_cache[sha1]
        except KeyError:
            raise SimpleError(msgs.NO_MATCHING_SCRIPT_MSG)
        return self.eval(script, numkeys, *keys_and_args)

    @command(name="SCRIPT LOAD", fixed=(bytes,), repeat=(bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def script_load(self, *args: bytes) -> bytes:
        if len(args) != 1:
            raise SimpleError(msgs.BAD_SUBCOMMAND_MSG.format("SCRIPT"))
        script = args[0]
        sha1 = hashlib.sha1(script).hexdigest().encode()
        self._server.script_cache[sha1] = script
        return sha1

    @command(name="SCRIPT EXISTS", fixed=(), repeat=(bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def script_exists(self, *args: bytes) -> List[int]:
        if self.version >= (7,) and len(args) == 0:
            raise SimpleError(msgs.WRONG_ARGS_MSG7)
        return [int(sha1 in self._server.script_cache) for sha1 in args]

    @command(name="SCRIPT FLUSH", fixed=(), repeat=(bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def script_flush(self, *args: bytes) -> SimpleString:
        if len(args) > 1 or (len(args) == 1 and null_terminate(args[0]) not in {b"sync", b"async"}):
            raise SimpleError(msgs.BAD_SUBCOMMAND_MSG.format("SCRIPT"))
        self._server.script_cache = {}
        return OK

    @command((), flags=msgs.FLAG_NO_SCRIPT)
    def script(self, *args: bytes) -> None:
        raise SimpleError(msgs.BAD_SUBCOMMAND_MSG.format("SCRIPT"))

    @command(name="SCRIPT HELP", fixed=())
    def script_help(self, *args: bytes) -> List[bytes]:
        help_strings = [
            "SCRIPT <subcommand> [<arg> [value] [opt] ...]. Subcommands are:",
            "DEBUG (YES|SYNC|NO)",
            "    Set the debug mode for subsequent scripts executed.",
            "EXISTS <sha1> [<sha1> ...]",
            "    Return information about the existence of the scripts in the script cache.",
            "FLUSH [ASYNC|SYNC]",
            "    Flush the Lua scripts cache. Very dangerous on replicas.",
            "    When called without the optional mode argument, the behavior is determined by the",
            "    lazyfree-lazy-user-flush configuration directive. Valid modes are:",
            "    * ASYNC: Asynchronously flush the scripts cache.",
            "    * SYNC: Synchronously flush the scripts cache.",
            "KILL",
            "    Kill the currently executing Lua script.",
            "LOAD <script>",
            "    Load a script into the scripts cache without executing it.",
            "HELP",
            ("    Prints this help." if self.version < (7, 1) else "    Print this help."),
        ]

        return [s.encode() for s in help_strings]
