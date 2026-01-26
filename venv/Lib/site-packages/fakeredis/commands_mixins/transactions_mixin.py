from typing import Callable, Set, Any, List, Optional

from fakeredis import _msgs as msgs
from fakeredis._commands import command, Key, CommandItem
from fakeredis._helpers import OK, SimpleError, Database, SimpleString


class TransactionsCommandsMixin:
    _run_command: Callable  # type: ignore

    def __init__(self, *args, **kwargs) -> None:  # type: ignore
        super(TransactionsCommandsMixin, self).__init__(*args, **kwargs)
        self._watches: Set[Any] = set()
        # When in a MULTI, set to a list of function calls
        self._transaction: Optional[List[Any]] = None
        self._transaction_failed = False
        # Set when executing the commands from EXEC
        self._in_transaction = False
        self._watch_notified = False
        self._db: Database

    def _clear_watches(self) -> None:
        self._watch_notified = False
        while self._watches:
            (key, db) = self._watches.pop()
            db.remove_watch(key, self)

    # Transaction commands
    @command((), flags=[msgs.FLAG_NO_SCRIPT, msgs.FLAG_TRANSACTION])
    def discard(self) -> SimpleString:
        if self._transaction is None:
            raise SimpleError(msgs.WITHOUT_MULTI_MSG.format("DISCARD"))
        self._transaction = None
        self._transaction_failed = False
        self._clear_watches()
        return OK

    @command(name="exec", fixed=(), repeat=(), flags=[msgs.FLAG_NO_SCRIPT, msgs.FLAG_TRANSACTION])
    def exec_(self) -> Any:
        if self._transaction is None:
            raise SimpleError(msgs.WITHOUT_MULTI_MSG.format("EXEC"))
        if self._transaction_failed:
            self._transaction = None
            self._clear_watches()
            raise SimpleError(msgs.EXECABORT_MSG)
        transaction = self._transaction
        self._transaction = None
        self._transaction_failed = False
        watch_notified = self._watch_notified
        self._clear_watches()
        if watch_notified:
            return None
        result = []
        for func, sig, args in transaction:
            try:
                self._in_transaction = True
                ans = self._run_command(func, sig, args, False)
            except SimpleError as exc:
                ans = exc
            finally:
                self._in_transaction = False
            result.append(ans)
        return result

    @command((), flags=[msgs.FLAG_NO_SCRIPT, msgs.FLAG_TRANSACTION])
    def multi(self) -> SimpleString:
        if self._transaction is not None:
            raise SimpleError(msgs.MULTI_NESTED_MSG)
        self._transaction = []
        self._transaction_failed = False
        return OK

    @command((), flags=msgs.FLAG_NO_SCRIPT)
    def unwatch(self) -> SimpleString:
        self._clear_watches()
        return OK

    @command((Key(),), (Key(),), flags=[msgs.FLAG_NO_SCRIPT, msgs.FLAG_TRANSACTION])
    def watch(self, *keys: CommandItem) -> SimpleString:
        if self._transaction is not None:
            raise SimpleError(msgs.WATCH_INSIDE_MULTI_MSG)
        for key in keys:
            if key not in self._watches:
                self._watches.add((key.key, self._db))
                self._db.add_watch(key.key, self)
        return OK

    def notify_watch(self) -> None:
        self._watch_notified = True
