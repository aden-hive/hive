from typing import Any, Dict, Callable, List, Iterable

from fakeredis import _msgs as msgs
from fakeredis._commands import command
from fakeredis._helpers import NoResponse, compile_pattern, SimpleError
from fakeredis._typing import VersionType


class PubSubCommandsMixin:
    put_response: Callable[[Any], None]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super(PubSubCommandsMixin, self).__init__(*args, **kwargs)
        self._pubsub = 0  # Count of subscriptions
        self._server: Any
        self.version: VersionType

    def _subscribe(self, channels: Iterable[bytes], subscribers: Dict[bytes, Any], mtype: bytes) -> NoResponse:
        for channel in channels:
            subs = subscribers[channel]
            if self not in subs:
                subs.add(self)
                self._pubsub += 1
            msg = [mtype, channel, self._pubsub]
            self.put_response(msg)
        return NoResponse()

    def _unsubscribe(self, channels: Iterable[bytes], subscribers: Dict[bytes, Any], mtype: bytes) -> NoResponse:
        if not channels:
            channels = []
            for channel, subs in subscribers.items():
                if self in subs:
                    channels.append(channel)
        for channel in channels:
            subs = subscribers.get(channel, set())
            if self in subs:
                subs.remove(self)
                if not subs:
                    del subscribers[channel]
                self._pubsub -= 1
            msg = [mtype, channel, self._pubsub]
            self.put_response(msg)
        return NoResponse()

    def _numsub(self, subscribers: Dict[bytes, Any], *channels: bytes) -> List[Any]:
        tuples_list = [(ch, len(subscribers.get(ch, []))) for ch in channels]
        return [item for sublist in tuples_list for item in sublist]

    @command((bytes,), (bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def psubscribe(self, *patterns: bytes) -> NoResponse:
        return self._subscribe(patterns, self._server.psubscribers, b"psubscribe")

    @command((bytes,), (bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def subscribe(self, *channels: bytes) -> NoResponse:
        return self._subscribe(channels, self._server.subscribers, b"subscribe")

    @command((bytes,), (bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def ssubscribe(self, *channels: bytes) -> NoResponse:
        return self._subscribe(channels, self._server.ssubscribers, b"ssubscribe")

    @command((), (bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def punsubscribe(self, *patterns: bytes) -> NoResponse:
        return self._unsubscribe(patterns, self._server.psubscribers, b"punsubscribe")

    @command((), (bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def unsubscribe(self, *channels: bytes) -> NoResponse:
        return self._unsubscribe(channels, self._server.subscribers, b"unsubscribe")

    @command(fixed=(), repeat=(bytes,), flags=msgs.FLAG_NO_SCRIPT)
    def sunsubscribe(self, *channels: bytes) -> NoResponse:
        return self._unsubscribe(channels, self._server.ssubscribers, b"sunsubscribe")

    @command((bytes, bytes))
    def publish(self, channel: bytes, message: bytes) -> int:
        receivers = 0
        msg = [b"message", channel, message]
        subs = self._server.subscribers.get(channel, set())
        for sock in subs:
            sock.put_response(msg)
            receivers += 1
        for pattern, socks in self._server.psubscribers.items():
            regex = compile_pattern(pattern)
            if regex.match(channel):
                msg = [b"pmessage", pattern, channel, message]
                for sock in socks:
                    sock.put_response(msg)
                    receivers += 1
        return receivers

    @command((bytes, bytes))
    def spublish(self, channel: bytes, message: bytes) -> int:
        receivers = 0
        msg = [b"smessage", channel, message]
        subs = self._server.ssubscribers.get(channel, set())
        for sock in subs:
            sock.put_response(msg)
            receivers += 1
        for pattern, socks in self._server.psubscribers.items():
            regex = compile_pattern(pattern)
            if regex.match(channel):
                msg = [b"pmessage", pattern, channel, message]
                for sock in socks:
                    sock.put_response(msg)
                    receivers += 1
        return receivers

    @command(name="PUBSUB NUMPAT", fixed=(), repeat=())
    def pubsub_numpat(self, *_: Any) -> int:
        return len(self._server.psubscribers)

    def _channels(self, subscribers_dict: Dict[bytes, Any], *patterns: bytes) -> List[bytes]:
        channels = list(subscribers_dict.keys())
        if len(patterns) > 0:
            regex = compile_pattern(patterns[0])
            channels = [ch for ch in channels if regex.match(ch)]
        return channels

    @command(name="PUBSUB CHANNELS", fixed=(), repeat=(bytes,))
    def pubsub_channels(self, *args: bytes) -> List[bytes]:
        return self._channels(self._server.subscribers, *args)

    @command(name="PUBSUB SHARDCHANNELS", fixed=(), repeat=(bytes,))
    def pubsub_shardchannels(self, *args: bytes) -> List[bytes]:
        return self._channels(self._server.ssubscribers, *args)

    @command(name="PUBSUB NUMSUB", fixed=(), repeat=(bytes,))
    def pubsub_numsub(self, *args: bytes) -> List[Any]:
        return self._numsub(self._server.subscribers, *args)

    @command(name="PUBSUB SHARDNUMSUB", fixed=(), repeat=(bytes,))
    def pubsub_shardnumsub(self, *args: bytes) -> List[Any]:
        return self._numsub(self._server.ssubscribers, *args)

    @command(name="PUBSUB", fixed=())
    def pubsub(self, *args: Any) -> None:
        raise SimpleError(msgs.WRONG_ARGS_MSG6.format("pubsub"))

    @command(name="PUBSUB HELP", fixed=())
    def pubsub_help(self, *args: Any) -> List[bytes]:
        if self.version >= (7,):
            help_strings = [
                "PUBSUB <subcommand> [<arg> [value] [opt] ...]. Subcommands are:",
                "CHANNELS [<pattern>]",
                "    Return the currently active channels matching a <pattern> (default: '*').",
                "NUMPAT",
                "    Return number of subscriptions to patterns.",
                "NUMSUB [<channel> ...]",
                "    Return the number of subscribers for the specified channels, excluding",
                "    pattern subscriptions(default: no channels).",
                "SHARDCHANNELS [<pattern>]",
                "    Return the currently active shard level channels matching a <pattern> (default: '*').",
                "SHARDNUMSUB [<shardchannel> ...]",
                "    Return the number of subscribers for the specified shard level channel(s)",
                "HELP",
                ("    Prints this help." if self.version < (7, 1) else "    Print this help."),
            ]
        else:
            help_strings = [
                "PUBSUB <subcommand> [<arg> [value] [opt] ...]. Subcommands are:",
                "CHANNELS [<pattern>]",
                "    Return the currently active channels matching a <pattern> (default: '*').",
                "NUMPAT",
                "    Return number of subscriptions to patterns.",
                "NUMSUB [<channel> ...]",
                "    Return the number of subscribers for the specified channels, excluding",
                "    pattern subscriptions(default: no channels).",
                "HELP",
                "    Prints this help.",
            ]
        return [s.encode() for s in help_strings]
