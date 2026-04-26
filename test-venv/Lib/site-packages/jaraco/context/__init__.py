from __future__ import annotations

import builtins
import contextlib
import errno
import functools
import operator
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from collections.abc import Callable, Generator, Iterator
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Literal,
    TypeVar,
    cast,
)

# jaraco/backports.tarfile#1
if TYPE_CHECKING or sys.version_info >= (3, 12):
    import tarfile  # pragma: no cover
else:
    from backports import tarfile  # pragma: no cover

if TYPE_CHECKING:
    from typing import TypeAlias

    from _typeshed import FileDescriptorOrPath, OptExcInfo, StrPath
    from typing_extensions import ParamSpec, Self, Unpack

    _FileDescriptorOrPathT = TypeVar(
        "_FileDescriptorOrPathT", bound=FileDescriptorOrPath
    )
    _P = ParamSpec("_P")

_UnpackableOptExcInfo: TypeAlias = tuple[
    type[BaseException] | None,
    BaseException | None,
    TracebackType | None,
]
_R = TypeVar("_R")
_T1_co = TypeVar("_T1_co", covariant=True)
_T2_co = TypeVar("_T2_co", covariant=True)


@contextlib.contextmanager
def pushd(dir: StrPath) -> Iterator[StrPath]:
    """
    >>> tmp_path = getfixture('tmp_path')
    >>> with pushd(tmp_path):
    ...     assert os.getcwd() == os.fspath(tmp_path)
    >>> assert os.getcwd() != os.fspath(tmp_path)
    """

    orig = os.getcwd()
    os.chdir(dir)
    try:
        yield dir
    finally:
        os.chdir(orig)


@contextlib.contextmanager
def tarball(url: str, target_dir: StrPath | None = None) -> Iterator[StrPath]:
    """
    Get a URL to a tarball, download, extract, yield, then clean up.

    Assumes everything in the tarball is prefixed with a common
    directory. That common path is stripped and the contents
    are extracted to ``target_dir``, similar to passing
    ``-C {target} --strip-components 1`` to the ``tar`` command.

    Uses the streaming protocol to extract the contents from a
    stream in a single pass without loading the whole file into
    memory.

    >>> import urllib.request
    >>> url = getfixture('tarfile_served')
    >>> target = getfixture('tmp_path') / 'out'
    >>> tb = tarball(url, target_dir=target)
    >>> import pathlib
    >>> with tb as extracted:
    ...     contents = pathlib.Path(extracted, 'contents.txt').read_text(encoding='utf-8')
    >>> assert not os.path.exists(extracted)

    If the target is not specified, contents are extracted to a
    directory relative to the current working directory named after
    the name of the file as extracted from the URL.

    >>> target = getfixture('tmp_path')
    >>> with pushd(target), tarball(url):
    ...     target.joinpath('served').is_dir()
    True
    """
    if target_dir is None:
        target_dir = os.path.basename(url).replace('.tar.gz', '').replace('.tgz', '')
    os.mkdir(target_dir)
    try:
        req = urllib.request.urlopen(url)
        with tarfile.open(fileobj=req, mode='r|*') as tf:
            tf.extractall(path=target_dir, filter=_default_filter)
        yield target_dir
    finally:
        shutil.rmtree(target_dir)


def _compose_tarfile_filters(*filters):  # type: ignore[no-untyped-def]
    def compose_two(f1, f2):  # type: ignore[no-untyped-def]
        return lambda member, path: f1(f2(member, path), path)

    return functools.reduce(compose_two, filters, lambda member, path: member)


def strip_first_component(
    member: tarfile.TarInfo,
    path: object,
) -> tarfile.TarInfo:
    _, member.name = member.name.split('/', 1)
    return member


_default_filter = _compose_tarfile_filters(tarfile.data_filter, strip_first_component)  # type: ignore[no-untyped-call]


def _compose(
    *cmgrs: Unpack[
        tuple[
            # Flipped from compose_two because of reverse
            Callable[[_T1_co], contextlib.AbstractContextManager[_T2_co]],
            Callable[_P, contextlib.AbstractContextManager[_T1_co]],
        ]
    ],
) -> Callable[_P, contextlib._GeneratorContextManager[_T2_co]]:
    """
    Compose any number of dependent context managers into a single one.

    The last, innermost context manager may take arbitrary arguments, but
    each successive context manager should accept the result from the
    previous as a single parameter.

    Like :func:`jaraco.functools.compose`, behavior works from right to
    left, so the context manager should be indicated from outermost to
    innermost.

    Example, to create a context manager to change to a temporary
    directory:

    >>> temp_dir_as_cwd = _compose(pushd, temp_dir)
    >>> with temp_dir_as_cwd() as dir:
    ...     assert os.path.samefile(os.getcwd(), dir)
    """

    def compose_two(
        inner: Callable[_P, contextlib.AbstractContextManager[_T1_co]],
        outer: Callable[[_T1_co], contextlib.AbstractContextManager[_T2_co]],
    ) -> Callable[_P, contextlib._GeneratorContextManager[_T2_co]]:
        def composed(*args: _P.args, **kwargs: _P.kwargs) -> Generator[_T2_co]:
            with inner(*args, **kwargs) as saved, outer(saved) as res:
                yield res

        return contextlib.contextmanager(composed)

    # reversed makes cmgrs no longer variadic, breaking type validation
    # Mypy infers compose_two as Callable[[function, function], function]. See:
    # - https://github.com/python/typeshed/issues/7580
    # - https://github.com/python/mypy/issues/8240
    return functools.reduce(compose_two, reversed(cmgrs))  # type: ignore[return-value, arg-type]


tarball_cwd = _compose(pushd, tarball)
"""
A tarball context with the current working directory pointing to the contents.
"""


def remove_readonly(
    func: Callable[[_FileDescriptorOrPathT], object],
    path: _FileDescriptorOrPathT,
    exc_info: tuple[object, OSError, object],
) -> None:
    """
    Add support for removing read-only files on Windows.
    """
    _, exc, _ = exc_info
    if func in (os.rmdir, os.remove, os.unlink) and exc.errno == errno.EACCES:
        # change the file to be readable,writable,executable: 0777
        os.chmod(path, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
        # retry
        func(path)
    else:
        raise


def robust_remover() -> Callable[..., None]:
    return (
        functools.partial(
            # cast for python/mypy#18637 / python/mypy#17585
            cast("Callable[..., None]", shutil.rmtree),
            onerror=remove_readonly,
        )
        if platform.system() == 'Windows'
        else shutil.rmtree
    )


@contextlib.contextmanager
def temp_dir(remover: Callable[[str], object] = shutil.rmtree) -> Generator[str]:
    """
    Create a temporary directory context. Pass a custom remover
    to override the removal behavior.

    >>> import pathlib
    >>> with temp_dir() as the_dir:
    ...     assert os.path.isdir(the_dir)
    >>> assert not os.path.exists(the_dir)
    """
    temp_dir = tempfile.mkdtemp()
    try:
        yield temp_dir
    finally:
        remover(temp_dir)


robust_temp_dir = functools.partial(temp_dir, remover=robust_remover())


@contextlib.contextmanager
def repo_context(
    url: str,
    branch: str | None = None,
    quiet: bool = True,
    dest_ctx: Callable[[], contextlib.AbstractContextManager[str]] = robust_temp_dir,
) -> Generator[str]:
    """
    Check out the repo indicated by url.

    If dest_ctx is supplied, it should be a context manager
    to yield the target directory for the check out.

    >>> getfixture('ensure_git')
    >>> getfixture('needs_internet')
    >>> repo = repo_context('https://github.com/jaraco/jaraco.context')
    >>> with repo as dest:
    ...     listing = os.listdir(dest)
    >>> 'README.rst' in listing
    True
    """
    exe = 'git' if 'git' in url else 'hg'
    with dest_ctx() as repo_dir:
        cmd = [exe, 'clone', url, repo_dir]
        cmd.extend(['--branch', branch] * bool(branch))  # type: ignore[list-item]
        stream = subprocess.DEVNULL if quiet else None
        subprocess.check_call(cmd, stdout=stream, stderr=stream)
        yield repo_dir


class ExceptionTrap:
    """
    A context manager that will catch certain exceptions and provide an
    indication they occurred.

    >>> with ExceptionTrap() as trap:
    ...     raise Exception()
    >>> bool(trap)
    True

    >>> with ExceptionTrap() as trap:
    ...     pass
    >>> bool(trap)
    False

    >>> with ExceptionTrap(ValueError) as trap:
    ...     raise ValueError("1 + 1 is not 3")
    >>> bool(trap)
    True
    >>> trap.value
    ValueError('1 + 1 is not 3')
    >>> trap.tb
    <traceback object at ...>

    >>> with ExceptionTrap(ValueError) as trap:
    ...     raise Exception()
    Traceback (most recent call last):
    ...
    Exception

    >>> bool(trap)
    False
    """

    exc_info: OptExcInfo = None, None, None

    def __init__(self, exceptions: tuple[type[BaseException], ...] = (Exception,)):
        self.exceptions = exceptions

    def __enter__(self) -> Self:
        return self

    @property
    def type(self) -> type[BaseException] | None:
        return self.exc_info[0]

    @property
    def value(self) -> BaseException | None:
        return self.exc_info[1]

    @property
    def tb(self) -> TracebackType | None:
        return self.exc_info[2]

    def __exit__(
        self,
        *exc_info: Unpack[_UnpackableOptExcInfo],  # noqa: PYI036 # We can do better than object
    ) -> builtins.type[BaseException] | None | bool:
        exc_type = exc_info[0]
        matches = exc_type and issubclass(exc_type, self.exceptions)
        if matches:
            self.exc_info = exc_info  # type: ignore[assignment]
        return matches

    def __bool__(self) -> bool:
        return bool(self.type)

    def raises(
        self, func: Callable[_P, _R], *, _test: Callable[[ExceptionTrap], bool] = bool
    ) -> functools._Wrapped[_P, _R, _P, bool]:
        """
        Wrap func and replace the result with the truth
        value of the trap (True if an exception occurred).

        Decorate a function that always fails.

        >>> @ExceptionTrap(ValueError).raises
        ... def fail():
        ...     raise ValueError('failed')
        >>> fail()
        True
        """

        @functools.wraps(func)
        def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> bool:
            with ExceptionTrap(self.exceptions) as trap:
                func(*args, **kwargs)
            return _test(trap)

        return wrapper

    def passes(self, func: Callable[_P, _R]) -> functools._Wrapped[_P, _R, _P, bool]:
        """
        Wrap func and replace the result with the truth
        value of the trap (True if no exception).

        Decorate a function that always fails.

        >>> @ExceptionTrap(ValueError).passes
        ... def fail():
        ...     raise ValueError('failed')

        >>> fail()
        False
        """
        return self.raises(func, _test=operator.not_)


class suppress(contextlib.suppress, contextlib.ContextDecorator):
    """
    A version of contextlib.suppress with decorator support.

    >>> @suppress(KeyError)
    ... def key_error():
    ...     {}['']
    >>> key_error()
    """


class on_interrupt(contextlib.ContextDecorator):
    """
    Replace a KeyboardInterrupt with SystemExit(1).

    Useful in conjunction with console entry point functions.

    >>> def do_interrupt():
    ...     raise KeyboardInterrupt()
    >>> on_interrupt('error')(do_interrupt)()
    Traceback (most recent call last):
    ...
    SystemExit: 1
    >>> on_interrupt('error', code=255)(do_interrupt)()
    Traceback (most recent call last):
    ...
    SystemExit: 255
    >>> on_interrupt('suppress')(do_interrupt)()
    >>> with __import__('pytest').raises(KeyboardInterrupt):
    ...     on_interrupt('ignore')(do_interrupt)()
    """

    def __init__(
        self, action: Literal['ignore', 'suppress', 'error'] = 'error', /, code: int = 1
    ):
        self.action = action
        self.code = code

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exctype: type[BaseException] | None,
        excinst: BaseException | None,
        exctb: TracebackType | None,
    ) -> None | bool:
        if exctype is not KeyboardInterrupt or self.action == 'ignore':
            return None
        elif self.action == 'error':
            raise SystemExit(self.code) from excinst
        return self.action == 'suppress'
