"""Centralized logging configuration for aden_tools.

Usage::

    from aden_tools.logging import get_logger

    logger = get_logger(__name__)
    logger.info("Tool initialised")

Environment variables
---------------------
ADEN_TOOLS_LOG_LEVEL  : Log level (default: ``INFO``). Accepts any value
                        accepted by :func:`logging.getLevelName` (e.g.
                        ``DEBUG``, ``WARNING``, ``ERROR``).
ADEN_TOOLS_LOG_FORMAT : Log format string (default: a compact timestamped
                        format written to *stderr*).

Notes
-----
* All handlers write to **stderr** so that stdout remains clean for
  MCP STDIO / JSON-RPC communication.
* :func:`configure_logging` is idempotent — calling it multiple times
  does **not** add duplicate handlers.
* Avoid passing reserved :class:`logging.LogRecord` field names (such as
  ``name``, ``message``, ``asctime``) in the ``extra`` dict; use
  descriptive alternatives like ``file_name`` or ``tool_name`` instead.
"""

from __future__ import annotations

import logging
import os
import sys

_CONFIGURED = False
_DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LOGGER_NAME = "aden_tools"


def configure_logging(
    level: int | str | None = None,
    fmt: str | None = None,
) -> None:
    """Configure the *aden_tools* root logger.

    Safe to call multiple times — only installs the handler once.

    Args:
        level: Logging level.  Defaults to ``ADEN_TOOLS_LOG_LEVEL`` env var,
               falling back to ``INFO``.
        fmt:   Log format string.  Defaults to ``ADEN_TOOLS_LOG_FORMAT`` env
               var, falling back to a compact timestamp format.
    """
    global _CONFIGURED  # noqa: PLW0603
    if _CONFIGURED:
        return

    resolved_level = level or os.environ.get("ADEN_TOOLS_LOG_LEVEL", "INFO")
    resolved_fmt = fmt or os.environ.get("ADEN_TOOLS_LOG_FORMAT", _DEFAULT_FORMAT)

    root = logging.getLogger(_LOGGER_NAME)

    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(resolved_fmt))
        root.addHandler(handler)

    try:
        root.setLevel(resolved_level)
    except (ValueError, TypeError):
        root.setLevel(logging.INFO)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger namespaced under *aden_tools*.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A :class:`logging.Logger` configured to write to stderr.
    """
    configure_logging()
    # Ensure the logger is a child of the aden_tools hierarchy so it
    # inherits the handler installed by configure_logging().
    if not name.startswith(_LOGGER_NAME):
        name = f"{_LOGGER_NAME}.{name}"
    return logging.getLogger(name)
