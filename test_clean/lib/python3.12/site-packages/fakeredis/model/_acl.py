import fnmatch
import hashlib
from typing import Dict, Set, List, Union, Optional, Any, AnyStr

from fakeredis import _msgs as msgs
from ._command_info import get_commands_by_category, get_command_info
from .._helpers import SimpleError, current_time


class Selector:
    def __init__(self, command: bytes, allowed: bool, keys: bytes, channels: bytes) -> None:
        self.command: bytes = command
        self.allowed: bool = allowed
        self.keys: bytes = keys
        self.channels: bytes = channels

    def as_array(self) -> List[bytes]:
        return [b"+" if self.allowed else b"-", self.command, b"keys", self.keys, b"channels", self.channels]

    @classmethod
    def from_bytes(cls, data: bytes) -> "Selector":
        keys = b""
        channels = b""
        command = b""
        allowed = False
        data = data.split(b" ")
        for item in data:
            if item.startswith(b"&"):  # channels
                channels = item
                continue
            if item.startswith(b"%RW"):  # keys
                item = item[3:]
            key = item
            if key.startswith(b"%"):
                key = key[2:]
            if key.startswith(b"~"):
                keys = item
                continue
            # command
            if item[0] == ord("+") or item[0] == ord("-"):
                command = item[1:]
                allowed = item[0] == ord("+")

        return cls(command, allowed, keys, channels)


class UserAccessControlList:
    def __init__(self, enabled: bool = True, nopass: bool = False):
        self._passwords: Set[bytes] = set()
        self.enabled: bool = enabled
        self._nopass: bool = nopass
        self._key_patterns: Set[bytes] = set()
        self._channel_patterns: Set[bytes] = set()
        self._commands: Dict[bytes, bool] = {b"@all": False}
        self._selectors: Dict[bytes, Selector] = {}

    def reset(self) -> None:
        self.enabled = False
        self._nopass = False
        self._commands = {b"@all": False}
        self._passwords.clear()
        self._key_patterns.clear()
        self._channel_patterns.clear()
        self._selectors.clear()

    @staticmethod
    def _get_command_info(fields: List[bytes]) -> Optional[List[Any]]:
        command = fields[0].lower()
        command_info = get_command_info(command)
        if not command_info and len(fields) > 1:
            command = command + b" " + fields[1].lower()
            command_info = get_command_info(command)
        return command_info

    def command_allowed(self, command_info: Optional[List[Any]], fields: List[bytes]) -> bool:
        res = fields[0].lower() == b"auth" or self._commands.get(fields[0].lower(), False)
        res = res or self._commands.get(b"@all", False)
        if not command_info:
            return res
        for category in command_info[6]:
            res = res or self._commands.get(category, False)
        return res

    def _get_keys(self, command_info: Optional[List[Any]], fields: List[bytes]) -> List[bytes]:
        if not command_info:
            return []
        first_key, last_key, step = command_info[3:6]
        if first_key == 0:
            return []
        last_key = (last_key + 1) if last_key >= 0 else last_key
        step = step + 1
        return fields[first_key : last_key + 1 : step]

    def keys_not_allowed(self, command_info: Optional[List[Any]], fields: List[bytes]) -> List[bytes]:
        if len(self._key_patterns) == 0:
            return []
        keys = self._get_keys(command_info, fields)
        res = set()
        for pat in self._key_patterns:
            res = res.union(fnmatch.filter(keys, pat))
        return list(set(keys) - res)

    def channels_not_allowed(self, command_info: Optional[List[Any]], fields: List[bytes]) -> List[bytes]:
        if len(self._key_patterns) == 0:
            return []
        channels = fields[1:2]
        res = set()
        for pat in self._channel_patterns:
            res = res.union(fnmatch.filter(channels, pat))
        return list(set(channels) - res)

    def set_nopass(self) -> None:
        self._nopass = True
        self._passwords.clear()

    def check_password(self, password: Optional[bytes]) -> bool:
        password_provided: bool = password is not None and password != b""
        if self._nopass:
            return not password_provided
        elif not password_provided:
            return False
        password_hex = hashlib.sha256(password).hexdigest().encode()
        return password_hex in self._passwords and self.enabled

    def add_password_hex(self, password_hex: bytes) -> None:
        self._nopass = False
        self._passwords.add(password_hex)

    def add_password(self, password: bytes) -> None:
        self._nopass = False
        password_hex = hashlib.sha256(password).hexdigest().encode()
        self.add_password_hex(password_hex)

    def remove_password_hex(self, password_hex: bytes) -> None:
        self._passwords.discard(password_hex)

    def remove_password(self, password: bytes) -> None:
        password_hex = hashlib.sha256(password).hexdigest().encode()
        self.remove_password_hex(password_hex)

    def add_command_or_category(self, selector: bytes) -> None:
        enabled, command = selector[0] == ord("+"), selector[1:]
        if command[0] == ord("@"):
            self._commands[command] = enabled
            category_commands = get_commands_by_category(command[1:])
            for command in category_commands:
                if command in self._commands:
                    del self._commands[command]
        else:
            self._commands[command] = enabled

    def add_key_pattern(self, key_pattern: bytes) -> None:
        self._key_patterns.add(key_pattern)

    def reset_key_patterns(self) -> None:
        self._key_patterns.clear()

    def reset_channels_patterns(self) -> None:
        self._channel_patterns.clear()

    def add_channel_pattern(self, channel_pattern: bytes) -> None:
        self._channel_patterns.add(channel_pattern)

    def add_selector(self, selector: bytes) -> None:
        selector = Selector.from_bytes(selector)
        self._selectors[selector.command] = selector

    def _get_selectors(self) -> List[Dict[str, str]]:
        results: List[Dict[str, str]] = []
        for command, selector in self._selectors.items():
            s: Dict[str, str] = {
                "commands": "-@all " + ("+" if selector.allowed else "-") + command.decode(),
                "keys": selector.keys,
                "channels": selector.channels,
            }
            results.append(s)
        return results

    def _get_commands(self) -> List[bytes]:
        res = []
        for command, enabled in self._commands.items():
            inc = b"+" if enabled else b"-"
            res.append(inc + command)
        return res

    def _get_key_patterns(self) -> List[bytes]:
        return [b"~" + key_pattern for key_pattern in self._key_patterns]

    def _get_channel_patterns(self) -> List[bytes]:
        return [b"&" + channel_pattern for channel_pattern in self._channel_patterns]

    def _get_flags(self) -> List[bytes]:
        flags = []
        flags.append(b"on" if self.enabled else b"off")
        if self._nopass:
            flags.append(b"nopass")
        if "*" in self._key_patterns:
            flags.append(b"allkeys")
        if "*" in self._channel_patterns:
            flags.append(b"allchannels")
        return flags

    def as_array(self) -> List[Union[bytes, List[bytes]]]:
        results: List[Union[bytes, List[bytes]]] = []
        results.extend(
            [
                b"flags",
                self._get_flags(),
                b"passwords",
                list(self._passwords),
                b"commands",
                b" ".join(self._get_commands()),
                b"keys",
                b" ".join(self._get_key_patterns()),
                b"channels",
                b" ".join(self._get_channel_patterns()),
                b"selectors",
                self._get_selectors(),
            ]
        )
        return results

    def _get_selectors_for_rule(self) -> List[bytes]:
        results: List[bytes] = []
        for command, selector in self._selectors.items():
            s = b"-@all " + (b"+" if selector.allowed else b"-") + command
            channels = b"resetchannels" + ((b" " + selector.channels) if selector.channels != b"" else b"")
            results.append(b"(" + b" ".join([selector.keys, channels, s]) + b")")
        return results

    def as_rule(self) -> bytes:
        selectors = self._get_selectors_for_rule()
        channels = self._get_channel_patterns()
        if channels != [b"&*"]:
            channels = [b"resetchannels"] + channels
        rule_parts: List[bytes] = (
            self._get_flags()
            + [b"#" + password for password in self._passwords]
            + self._get_commands()
            + self._get_key_patterns()
            + channels
            + selectors
        )
        return b" ".join(rule_parts)


class AclLogRecord:
    def __init__(
        self,
        count: int,
        reason: bytes,
        context: bytes,
        _object: bytes,
        username: bytes,
        created_ts: int,
        updated_ts: int,
        client_info: bytes,
        entry_id: int,
    ):
        self.count: int = count
        self.reason: bytes = reason  # command, key, channel, or auth
        self.context: bytes = context  # toplevel, multi, lua, or module
        self.object: bytes = _object  # resource user couldn't access. AUTH when the reason is auth
        self.username: bytes = username
        self.created_ts: int = created_ts  # milliseconds
        self.updated_ts: int = updated_ts
        self.client_info: bytes = client_info
        self.entry_id: int = entry_id

    def as_dict(self) -> Dict[str, AnyStr]:
        age_seconds = (current_time() - self.created_ts) / 1000
        res: Dict[str, AnyStr] = {
            "count": str(self.count).encode(),
            "reason": self.reason,
            "context": self.context,
            "object": self.object,
            "username": self.username,
            "age-seconds": f"{age_seconds:.3f}",
            "client-info": self.client_info,
            "entry-id": str(self.entry_id),
            "timestamp-created": str(self.created_ts),
            "timestamp-last-updated": str(self.updated_ts),
        }
        return res


class AccessControlList:
    def __init__(self) -> None:
        default_user_acl = UserAccessControlList(nopass=True)
        default_user_acl.add_key_pattern(b"*")
        default_user_acl.add_channel_pattern(b"*")
        default_user_acl.add_command_or_category(b"+@all")
        self._user_acl: Dict[bytes, UserAccessControlList] = {b"default": default_user_acl}
        self._log: List[AclLogRecord] = []

    def get_users(self) -> List[bytes]:
        return list(self._user_acl.keys())

    def get_user_acl(self, username: bytes) -> UserAccessControlList:
        return self._user_acl.setdefault(username, UserAccessControlList())

    def as_rules(self) -> List[bytes]:
        res: List[bytes] = []
        for username, user_acl in self._user_acl.items():
            rule_str = b"user " + username + b" " + user_acl.as_rule()
            res.append(rule_str)
        return res

    def del_user(self, username: bytes) -> None:
        self._user_acl.pop(username, None)

    def reset_log(self) -> None:
        self._log.clear()

    def log(self, count: int) -> List[Dict[str, AnyStr]]:
        if count > len(self._log) or count < 0:
            count = 0
        res = [x.as_dict() for x in self._log[-count:]]
        res.reverse()
        return res

    def add_log_record(
        self,
        reason: bytes,
        context: bytes,
        _object: bytes,
        username: bytes,
        client_info: bytes,
    ) -> None:
        if len(self._log) > 0:
            last_entry = self._log[-1]
            if (
                last_entry.reason == reason
                and last_entry.context == context
                and last_entry.object == _object
                and last_entry.username == username
            ):
                last_entry.count += 1
                last_entry.updated_ts = current_time()
                return
        entry = AclLogRecord(
            1, reason, context, _object, username, current_time(), current_time(), client_info, len(self._log) + 1
        )
        self._log.append(entry)

    def validate_command(self, username: bytes, client_info: bytes, fields: List[bytes]):
        if username not in self._user_acl:
            return
        if fields and fields[0].lower() == b"auth":
            # auth command is always allowed
            return
        user_acl = self._user_acl[username]
        if not user_acl.enabled:
            raise SimpleError("User disabled")
        command_info = UserAccessControlList._get_command_info(fields)
        if command_info is None:
            return
        if not user_acl.command_allowed(command_info, fields):
            self.add_log_record(b"command", b"toplevel", fields[0], username, client_info)
            raise SimpleError(msgs.NO_PERMISSION_ERROR.format(username.decode(), fields[0].lower().decode()))
        keys_not_allowed = user_acl.keys_not_allowed(command_info, fields)
        if len(keys_not_allowed) > 0:
            self.add_log_record(b"key", b"toplevel", keys_not_allowed[0], username, client_info)
            raise SimpleError(msgs.NO_PERMISSION_KEY_ERROR)
        if b"@pubsub" in command_info[6]:
            channels_not_allowed = user_acl.channels_not_allowed(command_info, fields)
            if len(channels_not_allowed) > 0:
                self.add_log_record(b"channel", b"toplevel", channels_not_allowed[0], username, client_info)
                raise SimpleError(msgs.NO_PERMISSION_CHANNEL_ERROR)
