"""Tests for aden_tools.logging module."""

import logging


def test_get_logger_returns_logger():
    from aden_tools.logging import get_logger

    logger = get_logger(__name__)
    assert isinstance(logger, logging.Logger)


def test_get_logger_namespaced():
    from aden_tools.logging import get_logger

    logger = get_logger("my_tool")
    assert logger.name.startswith("aden_tools")


def test_configure_logging_idempotent():
    """Calling configure_logging() multiple times must not add duplicate handlers."""
    import aden_tools.logging as mod

    # Reset state so we start clean regardless of import order in test suite
    mod._CONFIGURED = False
    root = logging.getLogger("aden_tools")
    root.handlers.clear()

    mod.configure_logging()
    handlers_after_first = len(root.handlers)

    mod._CONFIGURED = False  # allow re-entry
    mod.configure_logging()
    handlers_after_second = len(root.handlers)

    # configure_logging sets _CONFIGURED=True on first call; second call is a no-op
    assert handlers_after_first == handlers_after_second


def test_configure_logging_uses_env_level(monkeypatch):
    import aden_tools.logging as mod

    monkeypatch.setenv("ADEN_TOOLS_LOG_LEVEL", "DEBUG")
    mod._CONFIGURED = False
    root = logging.getLogger("aden_tools")
    root.handlers.clear()

    mod.configure_logging()
    assert root.level == logging.DEBUG

    # Cleanup
    mod._CONFIGURED = False
    root.handlers.clear()
    monkeypatch.delenv("ADEN_TOOLS_LOG_LEVEL", raising=False)
