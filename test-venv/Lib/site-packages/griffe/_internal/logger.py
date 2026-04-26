# This module contains the logger used throughout Griffe.
# The logger is actually a wrapper around the standard Python logger.
# We wrap it so that it is easier for other downstream libraries to patch it.
# For example, mkdocstrings-python patches the logger to relocate it as a child
# of `mkdocs.plugins` so that it fits in the MkDocs logging configuration.
#
# We use a single, global logger because our public API is exposed in a single module, `griffe`.
# Extensions however should use their own logger, which is why we provide the `get_logger` function.

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


class Logger:
    _default_logger: Any = logging.getLogger
    _instances: ClassVar[dict[str, Logger]] = {}

    def __init__(self, name: str) -> None:
        # Default logger that can be patched by third-party.
        self._logger = self.__class__._default_logger(name)

    def __getattr__(self, name: str) -> Any:
        # Forward everything to the logger.
        return getattr(self._logger, name)

    @contextmanager
    def disable(self) -> Iterator[None]:
        """Temporarily disable logging."""
        old_level = self._logger.level
        self._logger.setLevel(100)
        try:
            yield
        finally:
            self._logger.setLevel(old_level)

    @classmethod
    def _get(cls, name: str = "griffe") -> Logger:
        if name not in cls._instances:
            cls._instances[name] = cls(name)
        return cls._instances[name]

    @classmethod
    def _patch_loggers(cls, get_logger_func: Callable) -> None:
        # Patch current instances.
        for name, instance in cls._instances.items():
            instance._logger = get_logger_func(name)

        # Future instances will be patched as well.
        cls._default_logger = get_logger_func


logger: Logger = Logger._get()
"""Our global logger, used throughout the library.

Griffe's output and error messages are logging messages.

Griffe provides the [`patch_loggers`][griffe.patch_loggers]
function so dependent libraries can patch Griffe loggers as they see fit.

For example, to fit in the MkDocs logging configuration
and prefix each log message with the module name:

```python
import logging
from griffe import patch_loggers


class LoggerAdapter(logging.LoggerAdapter):
    def __init__(self, prefix, logger):
        super().__init__(logger, {})
        self.prefix = prefix

    def process(self, msg, kwargs):
        return f"{self.prefix}: {msg}", kwargs


def get_logger(name):
    logger = logging.getLogger(f"mkdocs.plugins.{name}")
    return LoggerAdapter(name, logger)


patch_loggers(get_logger)
```
"""


def get_logger(name: str = "griffe") -> Logger:
    """Create and return a new logger instance.

    Parameters:
        name: The logger name.

    Returns:
        The logger.
    """
    return Logger._get(name)


def patch_loggers(get_logger_func: Callable[[str], Any]) -> None:
    """Patch Griffe logger and Griffe extensions' loggers.

    Parameters:
        get_logger_func: A function accepting a name as parameter and returning a logger.
    """
    Logger._patch_loggers(get_logger_func)
