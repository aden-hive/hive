import os
import warnings

from . import python_aio, python_aio_asyncio
from .abstract import AbstractContext, AbstractOperation
from .version import __author__, __version__


try:
    from . import linux_aio, linux_aio_asyncio
except ImportError:
    linux_aio = None            # type: ignore
    linux_aio_asyncio = None    # type: ignore

try:
    from . import thread_aio, thread_aio_asyncio
except ImportError:
    thread_aio = None           # type: ignore
    thread_aio_asyncio = None   # type: ignore


variants = tuple(filter(None, [linux_aio, thread_aio, python_aio]))
variants_asyncio = tuple(
    filter(
        None, [
            linux_aio_asyncio,
            thread_aio_asyncio,
            python_aio_asyncio,
        ],
    ),
)

preferred = variants[0]
preferred_asyncio = variants_asyncio[0]


def __select_implementation():
    global preferred
    global preferred_asyncio

    implementations = {
        "linux": (linux_aio, linux_aio_asyncio),
        "thread": (thread_aio, thread_aio_asyncio),
        "python": (python_aio, python_aio_asyncio),
    }

    implementations = {k: v for k, v in implementations.items() if all(v)}

    default_implementation = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "default_implementation",
    )

    requested = os.getenv("CAIO_IMPL")

    if not requested and os.path.isfile(default_implementation):
        with open(default_implementation, "r") as fp:
            for line in fp:
                line = line.strip()
                if line.startswith("#") or not line:
                    continue
                if line in implementations:
                    requested = line
                    break

    elif requested and requested not in implementations:
        warnings.warn(
            "CAIO_IMPL contains unsupported value %r. Use one of %r" % (
                requested, tuple(implementations),
            ),
            RuntimeWarning,
        )
        return

    preferred, preferred_asyncio = implementations.get(
        requested,
        (preferred, preferred_asyncio),
    )


__select_implementation()


Context = preferred.Context      # type: ignore
Operation = preferred.Operation  # type: ignore
AsyncioContext = preferred_asyncio.AsyncioContext   # type: ignore


__all__ = (
    "Context",
    "Operation",
    "AsyncioContext",
    "AbstractContext",
    "AbstractOperation",
    "python_aio",
    "python_aio_asyncio",
    "linux_aio",
    "linux_aio_asyncio",
    "thread_aio",
    "thread_aio_asyncio",
    "__version__",
    "__author__",
    "variants",
    "variants_asyncio",
)
