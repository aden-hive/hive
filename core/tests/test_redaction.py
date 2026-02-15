
import json
import logging
from io import StringIO
from framework.observability.logging import (
    HumanReadableFormatter,
    StructuredFormatter,
    strip_ansi_codes,
)

def test_strip_ansi_codes():
    """Test that ANSI codes are stripped correctly."""
    text = "\033[31mError\033[0m"
    assert strip_ansi_codes(text) == "Error"

def test_redaction_structured_formatter():
    """Test that StructuredFormatter redaction works for API keys."""
    # Setup
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(StructuredFormatter())
    logger = logging.getLogger("test_structured_redaction")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    
    # Log sensitive data
    sensitive_msg = "Error using key sk-1234567890abcdef1234567890abcdef1234567890abcdef in request"
    logger.info(sensitive_msg)
    
    # Get output
    output = stream.getvalue()
    log_entry = json.loads(output)
    
    # Assert
    assert "sk-[REDACTED]" in log_entry["message"]
    assert "1234567890abcdef" not in log_entry["message"]

def test_redaction_human_formatter():
    """Test that HumanReadableFormatter redaction works."""
    # Setup
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(HumanReadableFormatter())
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Leaked ghp_ABC123abc123ABC123abc123ABC123abc123 token here",
        args=(),
        exc_info=None
    )
    
    # Format
    formatted = handler.format(record)
    
    # Assert
    assert "ghp_[REDACTED]" in formatted
    assert "ABC123abc123" not in formatted
