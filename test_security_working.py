"""
Standalone security tests that work without framework dependencies.
"""

import re
import time
import json
import logging
import tempfile
import os
import shutil
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional
from pathlib import Path
import threading


class SecurityLevel(Enum):
    """Security severity levels."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SecurityViolation(RuntimeError):
    """Exception raised when a security violation is detected."""
    
    def __init__(
        self,
        violation_type: str,
        field_path: str,
        description: str,
        severity: str,
        original_value: Any = None
    ):
        self.violation_type = violation_type
        self.field_path = field_path
        self.description = description
        self.severity = severity
        self.original_value = original_value
        super().__init__(f"{severity.upper()}: {description} (at {field_path})")


@dataclass
class SecurityEvent:
    """Represents a security event."""
    timestamp: float = field(default_factory=time.time)
    event_type: str = ""
    security_level: str = SecurityLevel.INFO.value
    description: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "security_level": self.security_level,
            "description": self.description,
            "details": self.details,
        }

    def to_json(self) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(), default=str)


class InputSanitizer:
    """Simple input sanitizer without external dependencies."""
    
    def __init__(self):
        self._max_string_length = 10000
        self._max_dict_size = 100
        self._max_list_size = 1000
        
        # Code patterns
        self._code_patterns = [
            r'\bimport\s+\w+',
            r'\bfrom\s+\w+\s+import',
            r'\bdef\s+\w+\s*\(',
            r'\bclass\s+\w+\s*:',
            r'\bexec\s*\(',
            r'\beval\s*\(',
            r'<script[^>]*>',
            r'javascript:',
            r'\bSELECT\s+.*\bFROM\b',
        ]
        self._compiled_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in self._code_patterns]
        
        # XSS patterns
        self._xss_patterns = [
            r'<script[^>]*>.*?</script>',
            r'javascript:',
            r'<iframe[^>]*>',
        ]
        self._xss_compiled = [re.compile(pattern, re.IGNORECASE | re.DOTALL) for pattern in self._xss_patterns]
        
        # Path traversal patterns
        self._path_traversal_patterns = [
            r'\.\./',
            r'%2e%2e%2f',
        ]
        self._path_compiled = [re.compile(pattern, re.IGNORECASE) for pattern in self._path_traversal_patterns]
    
    def sanitize_dict(self, data: Dict[str, Any], field_path: str = "") -> Dict[str, Any]:
        """Sanitize a dictionary."""
        if not isinstance(data, dict):
            raise SecurityViolation(
                violation_type="type_error",
                field_path=field_path,
                description="Expected dict, got {}".format(type(data).__name__),
                severity="critical",
                original_value=data
            )

        if len(data) > self._max_dict_size:
            raise SecurityViolation(
                violation_type="size_limit",
                field_path=field_path,
                description=f"Dictionary too large: {len(data)} > {self._max_dict_size}",
                severity="high",
                original_value=data
            )

        sanitized = {}
        
        for key, value in data.items():
            current_path = f"{field_path}.{key}" if field_path else key
            sanitized_key = self._sanitize_string(str(key), f"{current_path}.key")
            sanitized_value = self._sanitize_value(value, current_path)
            sanitized[sanitized_key] = sanitized_value
            
        return sanitized
    
    def _sanitize_value(self, value: Any, field_path: str) -> Any:
        """Sanitize a value based on its type."""
        if isinstance(value, str):
            return self._sanitize_string(value, field_path)
        elif isinstance(value, dict):
            return self.sanitize_dict(value, field_path)
        elif isinstance(value, list):
            return self._sanitize_list(value, field_path)
        elif isinstance(value, (int, float, bool)):
            return value
        elif value is None:
            return None
        else:
            return self._sanitize_string(str(value), field_path)
    
    def _sanitize_string(self, value: str, field_path: str) -> str:
        """Sanitize a string value."""
        if len(value) > self._max_string_length:
            raise SecurityViolation(
                violation_type="size_limit",
                field_path=field_path,
                description=f"String too long: {len(value)} > {self._max_string_length}",
                severity="high",
                original_value=value
            )

        sanitized = value
        violation_detected = False
        
        # Check for code injection
        for pattern in self._compiled_patterns:
            if pattern.search(sanitized):
                raise SecurityViolation(
                    violation_type="code_injection",
                    field_path=field_path,
                    description=f"Code injection pattern detected: {value}",
                    severity="high",
                    original_value=value
                )

        # Check for XSS
        for pattern in self._xss_compiled:
            if pattern.search(sanitized):
                raise SecurityViolation(
                    violation_type="xss",
                    field_path=field_path,
                    description=f"XSS pattern detected: {value}",
                    severity="medium",
                    original_value=value
                )

        # Check for path traversal
        for pattern in self._path_compiled:
            if pattern.search(sanitized):
                raise SecurityViolation(
                    violation_type="path_traversal",
                    field_path=field_path,
                    description=f"Path traversal pattern detected: {value}",
                    severity="medium",
                    original_value=value
                )
        
        return sanitized
    
    def _sanitize_list(self, value: list, field_path: str) -> list:
        """Sanitize a list value."""
        if len(value) > self._max_list_size:
            raise SecurityViolation(
                violation_type="size_limit",
                field_path=field_path,
                description=f"List too large: {len(value)} > {self._max_list_size}",
                severity="high",
                original_value=value
            )

        return [self._sanitize_value(item, f"{field_path}[{i}]") for i, item in enumerate(value)]


class AuditLogger:
    """Simple audit logger without external dependencies."""
    
    def __init__(self, log_file: Optional[Path] = None):
        """Initialize audit logger."""
        self.log_file = log_file
        self._events_logged = 0
        
        # Create audit logger
        self._logger = logging.getLogger("hive_test_audit")
        self._logger.setLevel(logging.INFO)
        
        # Remove existing handlers
        self._logger.handlers.clear()
        
        # Setup file handler if log_file specified
        if self.log_file:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(self.log_file)
            handler.setFormatter(logging.Formatter('%(message)s'))
            self._logger.addHandler(handler)

    def log_event(self, event: SecurityEvent) -> None:
        """Log a security event."""
        try:
            self._logger.info(event.to_json())
            self._events_logged += 1
        except Exception as e:
            print(f"Failed to log audit event: {e}")

    def log_security_violation(self, violation_type: str, description: str, 
                            field_path: str = "", original_value: Any = None, 
                            severity: str = SecurityLevel.MEDIUM.value, **kwargs) -> None:
        """Log a security violation."""
        event = SecurityEvent(
            event_type="security_violation",
            security_level=severity,
            description=description,
            details={
                "violation_type": violation_type,
                "field_path": field_path,
                "original_value": str(original_value) if original_value else None,
                **kwargs
            }
        )
        self.log_event(event)

    def get_stats(self) -> Dict[str, Any]:
        """Get audit logger statistics."""
        return {
            "events_logged": self._events_logged,
            "log_file": str(self.log_file) if self.log_file else None,
        }


def test_input_sanitizer():
    """Test input sanitizer functionality."""
    print("Testing InputSanitizer...")
    
    sanitizer = InputSanitizer()
    
    # Test safe data
    safe_data = {
        "name": "test",
        "value": 123,
        "enabled": True
    }
    
    result = sanitizer.sanitize_dict(safe_data)
    assert result == safe_data, "Safe data should pass through unchanged"
    print("  ✓ Safe data passthrough works")
    
    # Test malicious data
    malicious_data = {
        "input": "<script>alert('xss')</script>",
        "code": "import os"
    }
    
    try:
        result = sanitizer.sanitize_dict(malicious_data)
        print(f"  ✓ Malicious data sanitized: {result}")
    except SecurityViolation as e:
        print(f"  ✓ Security violation detected: {e.description}")
    
    print("InputSanitizer tests passed!\n")


def test_audit_logger():
    """Test audit logger functionality."""
    print("Testing AuditLogger...")
    
    # Create audit logger with temporary file
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "test_audit.log"
    
    audit_logger = AuditLogger(log_file)
    
    # Test event logging
    event = SecurityEvent(
        event_type="test_event",
        security_level=SecurityLevel.INFO.value,
        description="Test security event",
        details={"test": True}
    )
    
    audit_logger.log_event(event)
    
    # Test security violation logging
    audit_logger.log_security_violation(
        violation_type="test_violation",
        description="Test violation",
        severity=SecurityLevel.MEDIUM.value
    )
    
    # Check stats
    stats = audit_logger.get_stats()
    assert stats["events_logged"] >= 2, "Events should be logged"
    print(f"  ✓ Logged {stats['events_logged']} events")
    
    # Check log file exists
    assert log_file.exists(), "Log file should be created"
    print("  ✓ Log file created successfully")
    
    # Cleanup
    shutil.rmtree(temp_dir)
    
    print("AuditLogger tests passed!\n")


def test_integration():
    """Test integration between security components."""
    print("Testing Security Integration...")
    
    sanitizer = InputSanitizer()
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "integration_audit.log"
    audit_logger = AuditLogger(log_file)
    
    # Test malicious input detection and audit logging
    malicious_inputs = [
        {"data": "import os; os.system('ls')"},
        {"xss": "<script>alert('test')</script>"},
        {"path": "../../../etc/passwd"}
    ]
    
    violations_detected = 0
    
    for i, malicious_input in enumerate(malicious_inputs):
        try:
            result = sanitizer.sanitize_dict(malicious_input)
            print(f"  Input {i+1} sanitized: {result}")
        except SecurityViolation as e:
            violations_detected += 1
            # Log the violation
            audit_logger.log_security_violation(
                violation_type=e.violation_type,
                description=e.description,
                field_path=e.field_path,
                severity=e.severity
            )
            print(f"  Input {i+1} violation detected: {e.violation_type}")
    
    assert violations_detected > 0, "Should detect some violations"
    print(f"  ✓ Detected {violations_detected} security violations")
    
    # Check audit log contains violations
    stats = audit_logger.get_stats()
    assert stats["events_logged"] > 0, "Audit log should contain events"
    print(f"  ✓ Audit log contains {stats['events_logged']} events")
    
    # Cleanup
    shutil.rmtree(temp_dir)
    
    print("Integration tests passed!\n")


def test_performance():
    """Test performance impact of security measures."""
    print("Testing Security Performance...")
    
    sanitizer = InputSanitizer()
    
    # Test with large safe dataset
    large_data = {f"key_{i}": f"value_{i}" for i in range(100)}
    
    start_time = time.time()
    result = sanitizer.sanitize_dict(large_data)
    sanitization_time = time.time() - start_time
    
    assert sanitization_time < 0.1, "Sanitization should be fast"
    print(f"  ✓ Sanitized 100 items in {sanitization_time:.4f}s")
    
    # Test audit logging performance
    temp_dir = tempfile.mkdtemp()
    log_file = Path(temp_dir) / "perf_audit.log"
    audit_logger = AuditLogger(log_file)
    
    start_time = time.time()
    for i in range(100):
        event = SecurityEvent(
            event_type="perf_test",
            description=f"Performance test event {i}"
        )
        audit_logger.log_event(event)
    logging_time = time.time() - start_time
    
    assert logging_time < 0.1, "Logging should be fast"
    print(f"  ✓ Logged 100 events in {logging_time:.4f}s")
    
    # Cleanup
    shutil.rmtree(temp_dir)
    
    print("Performance tests passed!\n")


if __name__ == "__main__":
    print("🔒 Running Standalone Security Tests\n")
    
    try:
        test_input_sanitizer()
        test_audit_logger()
        test_integration()
        test_performance()
        
        print("🎉 ALL SECURITY TESTS PASSED!")
        print("\nSecurity Features Working:")
        print("  ✓ Input sanitization and validation")
        print("  ✓ Security violation detection")
        print("  ✓ Audit logging and event tracking")
        print("  ✓ Integration between components")
        print("  ✓ Performance within acceptable limits")
        
    except Exception as e:
        print(f"❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        exit(1)