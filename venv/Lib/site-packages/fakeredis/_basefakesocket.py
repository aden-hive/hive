import itertools
import logging
import queue
import time
import weakref
from typing import List, Any, Tuple, Optional, Callable, Union, Match, AnyStr, Generator, Sequence, Type

import redis

from fakeredis.model import XStream, ZSet, Hash, ExpiringMembersSet, ClientInfo
from . import _msgs as msgs
from ._command_args_parsing import extract_args
from ._commands import Int, Float, SUPPORTED_COMMANDS, COMMANDS_WITH_SUB, Signature, CommandItem
from ._helpers import (
    SimpleError,
    valid_response_type,
    SimpleString,
    NoResponse,
    casematch,
    compile_pattern,
    QUEUED,
    decode_command_bytes,
)
from ._typing import ResponseErrorType

LOGGER = logging.getLogger("fakeredis")


def _convert_to_resp2(val: Any) -> Any:
    if isinstance(val, str):
        return val.encode()
    if isinstance(val, float):
        return Float.encode(val, humanfriendly=False)
    if isinstance(val, dict):
        result = list(itertools.chain(*val.items()))
        return [_convert_to_resp2(item) for item in result]
    if isinstance(val, (list, tuple)):
        res = [_convert_to_resp2(item) for item in val]
        return res
    return val


def _extract_command(fields: List[bytes]) -> Tuple[Any, List[Any]]:
    """Extracts the command and command arguments from a list of `bytes` fields.

    :param fields: A list of `bytes` fields containing the command and command arguments.
    :return: A tuple of the command and command arguments.

    Example:
        ```
        fields = [b'GET', b'key1']
        result = _extract_command(fields)
        print(result) # ('GET', ['key1'])
        ```
    """
    cmd = decode_command_bytes(fields[0])
    if cmd in COMMANDS_WITH_SUB and len(fields) >= 2:
        cmd += " " + decode_command_bytes(fields[1])
        cmd_arguments = fields[2:]
    else:
        cmd_arguments = fields[1:]
    return cmd, cmd_arguments


def bin_reverse(x: int, bits_count: int) -> int:
    result = 0
    for i in range(bits_count):
        if (x >> i) & 1:
            result |= 1 << (bits_count - 1 - i)
    return result


_next_file_no = 8


def _get_next_file_no() -> int:
    global _next_file_no
    result = _next_file_no
    _next_file_no += 1
    return result


class BaseFakeSocket:
    _clear_watches: Callable[[], None]
    ACCEPTED_COMMANDS_WHILE_PUBSUB = {
        "ping",
        "subscribe",
        "unsubscribe",
        "psubscribe",
        "punsubscribe",
        "ssubscribe",
        "sunsubscribe",
    }
    _connection_error_class = redis.ConnectionError

    def __init__(
        self,
        server: "FakeServer",  # type: ignore # noqa: F821
        db: int,
        client_class: Type,  # type: ignore
        *args: Any,
        **kwargs: Any,
    ) -> None:
        super(BaseFakeSocket, self).__init__(*args, **kwargs)
        from fakeredis import FakeServer

        self._server: FakeServer = server
        self._fileno = _get_next_file_no()
        self._db_num = db
        self._db = server.dbs[self._db_num]
        self._client_class = client_class
        self.responses: Optional[queue.Queue[bytes]] = queue.Queue()
        # Prevents parser from processing commands. Not used in this module,
        # but set by aioredis module to prevent new commands being processed
        # while handling a blocking command.
        self._paused = False
        self._parser = self._parse_commands()
        self._parser.send(None)
        # Assigned elsewhere
        self._transaction: Optional[List[Any]]
        self._in_transaction: bool
        self._pubsub: int
        self._transaction_failed: bool
        info = kwargs.pop("client_info", {})
        self._client_info = ClientInfo(**info)
        self._server.sockets.append(self)

    @property
    def current_user(self) -> bytes:
        return self._client_info.user

    @property
    def version(self) -> Tuple[int, ...]:
        return self._server.version

    @property
    def server_type(self) -> str:
        return self._server.server_type

    def put_response(self, msg: Any) -> None:
        """Put a response message into the queue of responses.

        :param msg: The response message.
        """
        # redis.Connection.__del__ might call self.close at any time, which
        # will set self.responses to None. We assume this will happen
        # atomically, and the code below then protects us against this.
        responses = self.responses
        if responses:
            responses.put(msg)

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False
        self._parser.send(b"")

    def shutdown(self, _: Any) -> None:
        self._parser.close()

    def fileno(self) -> int:
        return self._fileno

    def _cleanup(self, server: Any) -> None:  # noqa: F821
        """Remove all the references to `self` from `server`.

        This is called with the server lock held, but it may be some time after
        self.close.
        """
        for subs in server.subscribers.values():
            subs.discard(self)
        for subs in server.psubscribers.values():
            subs.discard(self)
        self._clear_watches()

    def close(self) -> None:
        # Mark ourselves for cleanup. This might be called from
        # redis.Connection.__del__, which the garbage collection could call
        # at any time, and hence we can't safely take the server lock.
        # We rely on list.append being atomic.
        self._server.sockets.remove(self)
        self._server.closed_sockets.append(weakref.ref(self))
        self._server = None  # type: ignore
        self._db = None
        self.responses = None

    @staticmethod
    def _extract_line(buf: bytes) -> Tuple[bytes, bytes]:
        pos = buf.find(b"\n") + 1
        if pos <= 0:
            raise SimpleError(msgs.UNKNOWN_COMMAND_MSG.format(buf.decode().strip()))
        line = buf[:pos]
        buf = buf[pos:]
        if not line.endswith(b"\r\n"):
            command = line.decode().strip().split(" ")[0]
            args = " ".join(line.decode().strip().split(" ")[1:])
            raise SimpleError(msgs.UNKNOWN_COMMAND_MSG.format(command) + f"'{args}' ")
        return line, buf

    def _parse_commands(self) -> Generator[None, Any, None]:
        """Generator that parses commands.

        It is fed pieces of redis protocol data (via `send`) and calls
        `_process_command` whenever it has a complete one.
        """
        buf = b""
        while True:
            while self._paused or b"\n" not in buf:
                buf += yield
            line, buf = self._extract_line(buf)
            if not line[:1] == b"*":  # array
                raise SimpleError(msgs.UNKNOWN_COMMAND_MSG.format(buf.decode().strip()))
            n_fields = int(line[1:-2])
            fields = []
            for i in range(n_fields):
                while b"\n" not in buf:
                    buf += yield
                line, buf = self._extract_line(buf)
                if line[:1] != b"$":
                    raise SimpleError(msgs.UNKNOWN_COMMAND_MSG.format(buf.decode().strip()))
                length = int(line[1:-2])
                while len(buf) < length + 2:
                    buf += yield
                fields.append(buf[:length])
                buf = buf[length + 2 :]  # +2 to skip the CRLF
            self._process_command(fields)

    def _process_command(self, fields: List[bytes]) -> None:
        if not fields:
            return
        LOGGER.debug(f">>> {self._client_info.get('raddr')}: {fields}")
        result: Any
        cmd, cmd_arguments = _extract_command(fields)
        try:
            func, sig = self._name_to_func(cmd)
            # ACL check
            self._server.acl.validate_command(self._client_info.user, self._client_info.as_bytes(), fields)
            with self._server.lock:
                # Clean out old connections
                while True:
                    try:
                        weak_sock = self._server.closed_sockets.pop()
                    except IndexError:
                        break
                    else:
                        sock = weak_sock()
                        if sock:
                            sock._cleanup(self._server)
                now = time.time()
                for db in self._server.dbs.values():
                    db.time = now
                sig.check_arity(cmd_arguments, self.version)
                if self._transaction is not None and msgs.FLAG_TRANSACTION not in sig.flags:
                    self._transaction.append((func, sig, cmd_arguments))
                    result = QUEUED
                else:
                    result = self._run_command(func, sig, cmd_arguments, False)
        except SimpleError as exc:
            if self._transaction is not None:
                # TODO: should not apply if the exception is from _run_command
                # e.g. watch inside multi
                self._transaction_failed = True
            if cmd == "exec" and exc.value.startswith("ERR "):
                exc.value = "EXECABORT Transaction discarded because of: " + exc.value[4:]
                self._transaction = None
                self._transaction_failed = False
                self._clear_watches()
            result = exc
        result = self._decode_result(result)
        if not isinstance(result, NoResponse):
            self.put_response(result)

    def _run_command(
        self, func: Optional[Callable[[Any], Any]], sig: Signature, args: List[Any], from_script: bool
    ) -> Any:
        command_items: List[CommandItem] = []
        try:
            ret = sig.apply(args, self._db, self.version)
            if from_script and msgs.FLAG_NO_SCRIPT in sig.flags:
                raise SimpleError(msgs.COMMAND_IN_SCRIPT_MSG)
            if self._pubsub and sig.name not in BaseFakeSocket.ACCEPTED_COMMANDS_WHILE_PUBSUB:
                raise SimpleError(msgs.BAD_COMMAND_IN_PUBSUB_MSG)
            if len(ret) == 1:
                result = ret[0]
            else:
                args, command_items = ret
                result = func(*args)  # type: ignore
                if self._client_info.protocol_version == 2 and msgs.FLAG_SKIP_CONVERT_TO_RESP2 not in sig.flags:
                    result = _convert_to_resp2(result)
                if msgs.FLAG_SKIP_CONVERT_TO_RESP2 not in sig.flags and not valid_response_type(
                    result, self._client_info.protocol_version
                ):
                    raise AssertionError(f"Invalid response type for {result}")
        except SimpleError as exc:
            result = exc
        for command_item in command_items:
            command_item.writeback(remove_empty_val=msgs.FLAG_LEAVE_EMPTY_VAL not in sig.flags)
        return result

    def _decode_error(self, error: SimpleError) -> ResponseErrorType:
        if self._client_class.__module__.startswith("valkey"):
            from valkey.connection import DefaultParser as ValkeyDefaultParser

            return ValkeyDefaultParser(socket_read_size=65536).parse_error(error.value)  # type: ignore
        else:
            from redis.connection import DefaultParser as RedisDefaultParser

            return RedisDefaultParser(socket_read_size=65536).parse_error(error.value)  # type: ignore

    def _decode_result(self, result: Any) -> Any:
        """Convert SimpleString and SimpleError, recursively"""
        if isinstance(result, list):
            return [self._decode_result(r) for r in result]
        elif isinstance(result, SimpleString):
            return result.value
        elif isinstance(result, SimpleError):
            return self._decode_error(result)
        else:
            return result

    def _blocking(self, timeout: Optional[Union[float, int]], func: Callable[[bool], Any]) -> Any:
        """Run a function until it succeeds or timeout is reached.

        The timeout is in seconds, and 0 means infinite. The function
        is called with a boolean to indicate whether this is the first call.
        If it returns None, it is considered to have "failed" and is retried
        each time the condition variable is notified, until the timeout is
        reached.

        Returns the function return value, or None if the timeout has passed.
        """
        ret = func(True)  # Call with first_pass=True
        if ret is not None or self._in_transaction:
            return ret
        deadline = time.time() + timeout if timeout else None
        while True:
            timeout = (deadline - time.time()) if deadline is not None else None
            if timeout is not None and timeout <= 0:
                return None
            if self._db.condition.wait(timeout=timeout) is False:
                return None  # Timeout expired
            ret = func(False)  # Second pass => first_pass=False
            if ret is not None:
                return ret

    def _name_to_func(self, cmd_name: str) -> Tuple[Optional[Callable[[Any], Any]], Signature]:
        """Get the signature and the method from the command name."""
        if cmd_name not in SUPPORTED_COMMANDS:
            # redis remaps \r or \n in an error to ' ' to make it legal protocol
            clean_name = cmd_name.replace("\r", " ").replace("\n", " ")
            raise SimpleError(msgs.UNKNOWN_COMMAND_MSG.format(clean_name))
        sig = SUPPORTED_COMMANDS[cmd_name]
        if self._server.server_type not in sig.server_types:
            # redis remaps \r or \n in an error to ' ' to make it legal protocol
            clean_name = cmd_name.replace("\r", " ").replace("\n", " ")
            raise SimpleError(msgs.UNKNOWN_COMMAND_MSG.format(clean_name))
        func = getattr(self, sig.func_name, None)
        return func, sig

    def sendall(self, data: AnyStr) -> None:
        if not self._server.connected:
            raise self._connection_error_class(msgs.CONNECTION_ERROR_MSG)
        if isinstance(data, str):
            data = data.encode("ascii")  # type: ignore
        self._parser.send(data)

    def _scan(self, keys: Sequence[bytes], cursor: int, *args: bytes) -> List[Union[bytes, List[bytes]]]:
        """This is the basis of most of the ``scan`` methods.

        This implementation is KNOWN to be un-performant, as it requires grabbing the full set of keys over which
        we are investigating subsets.

        The SCAN command, and the other commands in the SCAN family, are able to provide to the user a set of
        guarantees associated with full iterations.

        - A full iteration always retrieves all the elements that were present in the collection from the start to the
          end of a full iteration. This means that if a given element is inside the collection when an iteration is
          started and is still there when an iteration terminates, then at some point the SCAN command returned it to
          the user.

        - A full iteration never returns any element that was NOT present in the collection from the start to the end
          of a full iteration. So if an element was removed before the start of an iteration and is never added back
          to the collection for all the time an iteration lasts, the SCAN command ensures that this element will never
          be returned.

        However, because the SCAN command has very little state associated (just the cursor),
        it has the following drawbacks:

        - A given element may be returned multiple times. It is up to the application to handle the case of duplicated
          elements, for example, only using the returned elements to perform operations that are safe when re-applied
          multiple times.
        - Elements that were not constantly present in the collection during a full iteration may be returned or not:
          it is undefined.

        """
        cursor = int(cursor)
        (pattern, _type, count), _ = extract_args(args, ("*match", "*type", "+count"))
        count = 10 if count is None else count
        data = sorted(keys)
        bits_len = (len(keys) - 1).bit_length()
        cursor = bin_reverse(cursor, bits_len)
        if cursor >= len(keys):
            return [b"0", []]
        result_cursor = cursor + count
        result_data = []

        regex = compile_pattern(pattern) if pattern is not None else None

        def match_key(key: bytes) -> Union[bool, Match[bytes], None]:
            if isinstance(key, str):
                key = key.encode("utf-8")
            return regex.match(key) if regex is not None else True

        def match_type(key: bytes) -> bool:
            return _type is None or casematch(BaseFakeSocket._key_value_type(self._db[key]).value, _type)

        if pattern is not None or _type is not None:
            for val in itertools.islice(data, cursor, cursor + count):
                compare_val = val[0] if isinstance(val, tuple) else val
                if match_key(compare_val) and match_type(compare_val):
                    result_data.append(val)
        else:
            result_data = data[cursor : cursor + count]

        if result_cursor >= len(data):
            result_cursor = 0
        return [str(bin_reverse(result_cursor, bits_len)).encode(), result_data]

    def _ttl(self, key: CommandItem, scale: float) -> int:
        if not key:
            return -2
        elif key.expireat is None:
            return -1
        else:
            return int(round((key.expireat - self._db.time) * scale))

    def _encodefloat(self, value: float, humanfriendly: bool) -> bytes:
        if self.version >= (7,):
            value = 0 + value
        return Float.encode(value, humanfriendly)

    def _encodeint(self, value: int) -> bytes:
        if self.version >= (7,):
            value = 0 + value
        return Int.encode(value)

    @staticmethod
    def _key_value_type(key: CommandItem) -> SimpleString:
        if key.value is None:
            return SimpleString(b"none")
        elif isinstance(key.value, bytes):
            return SimpleString(b"string")
        elif isinstance(key.value, list):
            return SimpleString(b"list")
        elif isinstance(key.value, ExpiringMembersSet):
            return SimpleString(b"set")
        elif isinstance(key.value, ZSet):
            return SimpleString(b"zset")
        elif isinstance(key.value, Hash):
            return SimpleString(b"hash")
        elif isinstance(key.value, XStream):
            return SimpleString(b"stream")
        else:
            assert False  # pragma: nocover
