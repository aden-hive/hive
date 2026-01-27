"""Tests for logging configuration module."""

import logging
import tempfile
from pathlib import Path

import pytest

from framework.logging_config import (
    VALID_LOG_LEVELS,
    disable_framework_logging,
    get_logger,
    set_framework_log_level,
    setup_logging,
)


@pytest.fixture(autouse=True)
def reset_logging():
    """Fixture to save and restore logging configuration between tests.
    
    This ensures test isolation by capturing the root logger's handlers
    and level before each test and restoring them after.
    """
    # Save current state
    root_logger = logging.getLogger()
    original_level = root_logger.level
    original_handlers = root_logger.handlers.copy()
    
    yield
    
    # Restore original state
    root_logger.setLevel(original_level)
    root_logger.handlers.clear()
    for handler in original_handlers:
        root_logger.addHandler(handler)


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_basic_setup(self):
        """Test basic logging setup."""
        setup_logging(level="INFO")
        logger = get_logger(__name__)
        assert logger.level == logging.NOTSET  # Inherits from root
        assert logging.getLogger().level == logging.INFO

    def test_with_file(self):
        """Test logging setup with file output."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = Path(tmpdir) / "test.log"
            setup_logging(level="DEBUG", log_file=log_file)

            logger = get_logger(__name__)
            logger.debug("Test message")

            assert log_file.exists()
            content = log_file.read_text()
            assert "Test message" in content

    def test_with_string_file_path(self):
        """Test logging setup with string file path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_file = str(Path(tmpdir) / "test_string.log")
            setup_logging(level="DEBUG", log_file=log_file)

            logger = get_logger(__name__)
            logger.debug("Test string path message")

            assert Path(log_file).exists()
            content = Path(log_file).read_text()
            assert "Test string path message" in content

    def test_custom_format(self):
        """Test logging setup with custom format."""
        custom_format = "%(levelname)s: %(message)s"
        setup_logging(level="INFO", format_string=custom_format)

        # Should not raise any errors
        logger = get_logger(__name__)
        logger.info("Test")

    def test_without_timestamp(self):
        """Test logging setup without timestamps."""
        setup_logging(level="INFO", include_timestamp=False)

        # Should not raise any errors
        logger = get_logger(__name__)
        logger.info("Test without timestamp")

    def test_all_valid_levels(self):
        """Test all valid logging levels."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            setup_logging(level=level)
            numeric_level = getattr(logging, level)
            assert logging.getLogger().level == numeric_level

    def test_invalid_log_level_raises_error(self):
        """Test that invalid log level raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            setup_logging(level="INVALID_LEVEL")
        
        assert "Invalid log level" in str(exc_info.value)
        assert "INVALID_LEVEL" in str(exc_info.value)

    def test_invalid_log_level_trace(self):
        """Test that TRACE (non-standard) level raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            setup_logging(level="TRACE")
        
        assert "Invalid log level" in str(exc_info.value)

    def test_invalid_log_level_verbose(self):
        """Test that VERBOSE (non-standard) level raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            setup_logging(level="VERBOSE")
        
        assert "Invalid log level" in str(exc_info.value)


class TestGetLogger:
    """Tests for get_logger function."""

    def test_returns_logger_instance(self):
        """Test logger creation."""
        logger = get_logger("test_module")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_module"

    def test_same_name_returns_same_logger(self):
        """Test that same name returns same logger instance."""
        logger1 = get_logger("same_module")
        logger2 = get_logger("same_module")
        assert logger1 is logger2


class TestSetFrameworkLogLevel:
    """Tests for set_framework_log_level function."""

    def test_sets_debug_level(self):
        """Test setting framework log level to DEBUG."""
        # Create a framework logger
        framework_logger = logging.getLogger("framework.test")

        set_framework_log_level("DEBUG")
        assert framework_logger.level == logging.DEBUG

    def test_sets_warning_level(self):
        """Test setting framework log level to WARNING."""
        framework_logger = logging.getLogger("framework.test")

        set_framework_log_level("WARNING")
        assert framework_logger.level == logging.WARNING

    def test_invalid_level_raises_error(self):
        """Test that invalid log level raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            set_framework_log_level("INVALID")
        
        assert "Invalid log level" in str(exc_info.value)


class TestDisableFrameworkLogging:
    """Tests for disable_framework_logging function."""

    def test_disables_logging(self):
        """Test disabling framework logging."""
        framework_logger = logging.getLogger("framework")
        disable_framework_logging()

        # Logger should be set to a level higher than CRITICAL
        assert framework_logger.level > logging.CRITICAL


class TestValidLogLevels:
    """Tests for VALID_LOG_LEVELS constant."""

    def test_contains_all_standard_levels(self):
        """Test that VALID_LOG_LEVELS contains all standard Python log levels."""
        expected_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        assert VALID_LOG_LEVELS == expected_levels


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
