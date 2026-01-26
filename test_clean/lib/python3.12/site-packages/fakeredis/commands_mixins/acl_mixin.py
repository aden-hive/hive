import secrets
from typing import Any, List, Dict, Optional, Union

from fakeredis import _msgs as msgs
from fakeredis._commands import command, Int
from fakeredis._helpers import SimpleError, OK, casematch, SimpleString
from fakeredis._typing import VersionType
from fakeredis._server import FakeServer
from fakeredis.model import AccessControlList, ClientInfo, get_categories, get_commands_by_category


class AclCommandsMixin:
    def __init(self, *args: Any, **kwargs: Any) -> None:
        super(AclCommandsMixin, self).__init__(*args, **kwargs)
        self.version: VersionType
        self._server: FakeServer
        self._client_info: ClientInfo

    @property
    def _server_config(self) -> Dict[bytes, bytes]:
        return self._server.config

    @property
    def _acl(self) -> AccessControlList:
        return self._server.acl

    def _check_user_password(self, username: bytes, password: Optional[bytes]) -> bool:
        return self._acl.get_user_acl(username).check_password(password)

    def _set_user_acl(self, username: bytes, *args: bytes) -> None:
        user_acl = self._acl.get_user_acl(username)
        for arg in args:
            if casematch(arg, b"resetchannels"):
                user_acl.reset_channels_patterns()
                continue
            elif casematch(arg, b"resetkeys"):
                user_acl.reset_key_patterns()
                continue
            elif casematch(arg, b"on"):
                user_acl.enabled = True
                continue
            elif casematch(arg, b"off"):
                user_acl.enabled = False
                continue
            elif casematch(arg, b"nopass"):
                user_acl.set_nopass()
                continue
            elif casematch(arg, b"reset"):
                user_acl.reset()
                continue
            elif casematch(arg, b"nocommands"):
                arg = b"-@all"
            elif casematch(arg, b"allcommands"):
                arg = b"+@all"
            elif casematch(arg, b"allkeys"):
                arg = b"~*"
            elif casematch(arg, b"allchannels"):
                arg = b"&*"
            elif arg[0] == ord("(") and arg[-1] == ord(")"):
                user_acl.add_selector(arg[1:-1])
                continue

            prefix = arg[0]
            if prefix == ord(">"):
                user_acl.add_password(arg[1:])
            elif prefix == ord("<"):
                user_acl.remove_password(arg[1:])
            elif prefix == ord("#"):
                user_acl.add_password_hex(arg[1:])
            elif prefix == ord("!"):
                user_acl.remove_password_hex(arg[1:])
            elif prefix == ord("+") or prefix == ord("-"):
                user_acl.add_command_or_category(arg)
            elif prefix == ord("~"):
                user_acl.add_key_pattern(arg[1:])
            elif prefix == ord("&"):
                user_acl.add_channel_pattern(arg[1:])

    @command(name="CONFIG SET", fixed=(bytes, bytes), repeat=(bytes, bytes))
    def config_set(self, *args: bytes) -> SimpleString:
        if len(args) % 2 != 0:
            raise SimpleError(msgs.WRONG_ARGS_MSG6.format("CONFIG SET"))
        for i in range(0, len(args), 2):
            self._server_config[args[i]] = args[i + 1]
        return OK

    @command(name="AUTH", fixed=(), repeat=(bytes,))
    def _auth(self, *args: bytes) -> SimpleString:
        if not 1 <= len(args) <= 2:
            raise SimpleError(msgs.WRONG_ARGS_MSG6.format("AUTH"))
        username = None if len(args) == 1 else args[0]
        password = args[1] if len(args) == 2 else args[0]
        if (username is None or username == b"default") and (password == self._server_config.get(b"requirepass", b"")):
            self._client_info["user"] = "default"
            return OK
        username = username or b"default"
        if len(args) >= 1 and self._check_user_password(username, password):
            self._client_info["user"] = username.decode()
            return OK
        self._acl.add_log_record(b"auth", b"auth", b"AUTH", username, self._client_info.as_bytes())
        raise SimpleError(msgs.AUTH_FAILURE)

    @command(name="ACL CAT", fixed=(), repeat=(bytes,))
    def acl_cat(self, *category: bytes) -> List[bytes]:
        if len(category) == 0:
            res = get_categories()
        else:
            res = get_commands_by_category(category[0])
            res = [cmd.replace(b" ", b"|") for cmd in res]
        return res

    @command(name="ACL GENPASS", fixed=(), repeat=(bytes,))
    def acl_genpass(self, *args: bytes) -> bytes:
        bits = Int.decode(args[0]) if len(args) > 0 else 256
        bits = bits + bits % 4  # Round to 4
        nbytes: int = bits // 8
        return secrets.token_hex(nbytes).encode()

    @command(name="ACL SETUSER", fixed=(bytes,), repeat=(bytes,))
    def acl_setuser(self, username: bytes, *args: bytes) -> SimpleString:
        self._set_user_acl(username, *args)
        return OK

    @command(name="ACL LIST", fixed=(), repeat=())
    def acl_list(self) -> List[bytes]:
        return self._acl.as_rules()

    @command(name="ACL DELUSER", fixed=(bytes,), repeat=())
    def acl_deluser(self, username: bytes) -> SimpleString:
        self._acl.del_user(username)
        return OK

    @command(name="ACL GETUSER", fixed=(bytes,), repeat=())
    def acl_getuser(self, username: bytes) -> List[Union[bytes, List[bytes]]]:
        res = self._acl.get_user_acl(username).as_array()
        return res

    @command(name="ACL USERS", fixed=(), repeat=())
    def acl_users(self) -> List[bytes]:
        res = self._acl.get_users()
        return res

    @command(name="ACL WHOAMI", fixed=(), repeat=())
    def acl_whoami(self) -> bytes:
        return self._client_info.user

    @command(name="ACL SAVE", fixed=(), repeat=())
    def acl_save(self) -> SimpleString:
        if b"aclfile" not in self._server_config:
            raise SimpleError(msgs.MISSING_ACLFILE_CONFIG)
        acl_filename = self._server_config[b"aclfile"]
        with open(acl_filename, "wb") as f:
            f.write(b"\n".join(self._acl.as_rules()))
        return OK

    @command(name="ACL LOAD", fixed=(), repeat=())
    def acl_load(self) -> SimpleString:
        if b"aclfile" not in self._server_config:
            raise SimpleError(msgs.MISSING_ACLFILE_CONFIG)
        acl_filename = self._server_config[b"aclfile"]
        with open(acl_filename, "rb") as f:
            rules_list = f.readlines()
            for rule in rules_list:
                if not rule.startswith(b"user "):
                    continue
                splitted = rule.split(b" ")
                components = []
                i = 1
                while i < len(splitted):
                    current_component = splitted[i]
                    if current_component.startswith(b"("):
                        while not current_component.endswith(b")"):
                            i += 1
                            current_component += b" " + splitted[i]
                    components.append(current_component)
                    i += 1

                self._set_user_acl(components[0], *components[1:])
        return OK

    @command(name="ACL LOG", fixed=(), repeat=(bytes,))
    def acl_log(self, *args: bytes) -> Union[SimpleString, List[Dict[str, str]]]:
        if len(args) == 1 and casematch(args[0], b"RESET"):
            self._acl.reset_log()
            return OK
        count = Int.decode(args[0]) if len(args) == 1 else 0
        return self._acl.log(count)
