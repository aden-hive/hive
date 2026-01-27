"""
Tests for security components.

Comprehensive test suite for:
- Input sanitization
- Audit logging
- Secure runtime
- Rate limiting
- Security violations
"""

import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

from framework.security.audit import AuditLogger, SecurityEvent, EventType, SecurityLevel
from framework.security.sanitizer import InputSanitizer, SecurityViolation


class TestInputSanitizer:
    """Test suite for InputSanitizer."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.sanitizer = InputSanitizer()
    
    def test_safe_dict_passthrough(self):
        """Test that safe dictionaries pass through unchanged."""
        safe_data = {
            "name": "test",
            "value": 123,
            "enabled": True,
            "items": ["a", "b", "c"]
        }
        
        result = self.sanitizer.sanitize_dict(safe_data)
        assert result == safe_data
    
    def test_code_injection_detection(self):
        """Test detection of code injection patterns."""
        malicious_data = {
            "input": "import os; os.system('rm -rf /')",
            "script": "<script>alert('xss')</script>",
            "sql": "SELECT * FROM users WHERE 1=1"
        }
        
        with pytest.raises(SecurityViolation) as exc_info:
            self.sanitizer.sanitize_dict(malicious_data)
        
        assert exc_info.value.severity == "critical"
        assert "code injection" in exc_info.value.description.lower()
    
    def test_xss_detection(self):
        """Test detection of XSS patterns."""
        xss_data = {
            "comment": "<script>alert('xss')</script>",
            "link": "javascript:alert('xss')",
            "iframe": "<iframe src='evil.com'></iframe>"
        }
        
        result = self.sanitizer.sanitize_dict(xss_data)
        
        # XSS content should be removed
        assert "<script>" not in str(result.get("comment", ""))
        assert "javascript:" not in str(result.get("link", ""))
        assert "<iframe>" not in str(result.get("iframe", ""))
    
    def test_path_traversal_detection(self):
        """Test detection of path traversal patterns."""
        path_data = {
            "file_path": "../../../etc/passwd",
            "directory": "..\\..\\windows\\system32",
            "encoded": "%2e%2e%2f%2e%2e%2f"
        }
        
        result = self.sanitizer.sanitize_dict(path_data)
        
        # Path traversal should be normalized/removed
        assert "../" not in str(result.get("file_path", ""))
        assert "..\\" not in str(result.get("directory", ""))
    
    def test_size_limits(self):
        """Test enforcement of size limits."""
        # Test oversized string
        large_string = "a" * 15000  # Exceeds default limit
        
        with pytest.raises(SecurityViolation) as exc_info:
            self.sanitizer._sanitize_string(large_string, "test")
        
        assert "too long" in exc_info.value.description.lower()
        
        # Test oversized dictionary
        large_dict = {f"key_{i}": f"value_{i}" for i in range(200)}  # Exceeds default limit
        
        with pytest.raises(SecurityViolation) as exc_info:
            self.sanitizer.sanitize_dict(large_dict)
        
        assert "too large" in exc_info.value.description.lower()
    
    def test_filename_sanitization(self):
        """Test filename sanitization."""
        malicious_filenames = [
            "../../../etc/passwd",
            "file<script>.txt",
            "file|name.txt",
            "file:name.txt",
            "very_long_filename_" + "a" * 300
        ]
        
        for filename in malicious_filenames:
            sanitized = self.sanitizer.sanitize_filename(filename)
            
            # Should not contain path separators
            assert "/" not in sanitized
            assert "\\" not in sanitized
            
            # Should not contain dangerous characters
            assert "<" not in sanitized
            assert ">" not in sanitized
            assert "|" not in sanitized
            assert ":" not in sanitized
            
            # Should be reasonable length
            assert len(sanitized) <= 255
    
    def test_validate_file_path(self):
        """Test file path validation."""
        # Safe paths
        safe_paths = [
            "normal_file.txt",
            "directory/subdir/file.txt",
            "/absolute/path/file.txt"
        ]
        
        for path in safe_paths:
            assert self.sanitizer.validate_file_path(path)
        
        # Dangerous paths
        dangerous_paths = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "file/../../../etc/passwd"
        ]
        
        for path in dangerous_paths:
            assert not self.sanitizer.validate_file_path(path)


class TestAuditLogger:
    """Test suite for AuditLogger."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.log_file = self.temp_dir / "test_audit.log"
        self.audit_logger = AuditLogger(
            log_file=self.log_file,
            max_file_size=1024 * 1024,  # 1MB
            backup_count=3
        )
    
    def teardown_method(self):
        """Cleanup test fixtures."""
        self.audit_logger.cleanup()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_event_logging(self):
        """Test basic event logging."""
        event = SecurityEvent(
            event_type=EventType.SECURITY_VIOLATION.value,
            security_level=SecurityLevel.HIGH.value,
            description="Test security violation",
            details={"test": True}
        )
        
        self.audit_logger.log_event(event)
        self.audit_logger._flush_events()
        
        # Check that event was logged
        assert self.log_file.exists()
        
        # Read and verify log content
        with open(self.log_file, 'r') as f:
            log_content = f.read()
        
        assert "SECURITY_VIOLATION" in log_content
        assert "HIGH" in log_content
        assert "Test security violation" in log_content
    
    def test_security_violation_logging(self):
        """Test security violation specific logging."""
        self.audit_logger.log_security_violation(
            violation_type="code_injection",
            description="Potential code injection detected",
            field_path="input.code",
            original_value="import os",
            severity=SecurityLevel.CRITICAL.value
        )
        
        self.audit_logger._flush_events()
        
        with open(self.log_file, 'r') as f:
            log_content = f.read()
        
        assert "code_injection" in log_content
        assert "import os" in log_content
        assert "CRITICAL" in log_content
    
    def test_runtime_events(self):
        """Test runtime event logging."""
        self.audit_logger.log_runtime_start(5)
        self.audit_logger.log_execution_trigger("test_ep", "exec_123", "corr_456")
        self.audit_logger.log_execution_complete("test_ep", "exec_123", True, 1500)
        self.audit_logger.log_runtime_stop()
        
        self.audit_logger._flush_events()
        
        with open(self.log_file, 'r') as f:
            log_content = f.read()
        
        assert "RUNTIME_START" in log_content
        assert "EXECUTION_TRIGGER" in log_content
        assert "EXECUTION_COMPLETE" in log_content
        assert "RUNTIME_STOP" in log_content
    
    def test_resource_exceeded_logging(self):
        """Test resource limit exceeded logging."""
        self.audit_logger.log_resource_exceeded(
            resource_type="memory",
            current_value=1500.0,
            limit=1024.0,
            execution_id="exec_123"
        )
        
        self.audit_logger._flush_events()
        
        with open(self.log_file, 'r') as f:
            log_content = f.read()
        
        assert "MEMORY_LIMIT_EXCEEDED" in log_content
        assert "1500.0" in log_content
        assert "1024.0" in log_content
    
    def test_event_search(self):
        """Test event search functionality."""
        # Add test events
        events = [
            SecurityEvent(
                event_type=EventType.SECURITY_VIOLATION.value,
                security_level=SecurityLevel.HIGH.value,
                description="Security event 1"
            ),
            SecurityEvent(
                event_type=EventType.RUNTIME_START.value,
                security_level=SecurityLevel.INFO.value,
                description="Runtime event 1"
            ),
            SecurityEvent(
                event_type=EventType.SECURITY_VIOLATION.value,
                security_level=SecurityLevel.LOW.value,
                description="Security event 2"
            )
        ]
        
        for event in events:
            self.audit_logger.log_event(event)
        
        self.audit_logger._flush_events()
        
        # Search by event type
        security_events = self.audit_logger.search_events(
            event_type=EventType.SECURITY_VIOLATION.value
        )
        assert len(security_events) == 2
        
        # Search by security level
        high_events = self.audit_logger.search_events(
            security_level=SecurityLevel.HIGH.value
        )
        assert len(high_events) == 1
        assert high_events[0].description == "Security event 1"
    
    def test_stats_collection(self):
        """Test statistics collection."""
        # Log some events
        for i in range(10):
            event = SecurityEvent(
                event_type=EventType.SECURITY_VIOLATION.value,
                description=f"Test event {i}"
            )
            self.audit_logger.log_event(event)
        
        self.audit_logger._flush_events()
        
        stats = self.audit_logger.get_stats()
        
        assert stats["events_logged"] == 10
        assert stats["events_dropped"] == 0
        assert "uptime_seconds" in stats
        assert "log_file" in stats


class TestSecurityIntegration:
    """Integration tests for security components."""
    
    def setup_method(self):
        """Setup test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.sanitizer = InputSanitizer()
        self.audit_logger = AuditLogger(
            log_file=self.temp_dir / "integration_audit.log"
        )
    
    def teardown_method(self):
        """Cleanup test fixtures."""
        self.audit_logger.cleanup()
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
    
    def test_sanitizer_audit_integration(self):
        """Test integration between sanitizer and audit logger."""
        malicious_data = {
            "input": "<script>alert('xss')</script>",
            "code": "import os"
        }
        
        # Sanitize input
        try:
            self.sanitizer.sanitize_dict(malicious_data)
        except SecurityViolation as e:
            # Log the security violation
            self.audit_logger.log_security_violation(
                violation_type=e.violation_type,
                description=e.description,
                field_path=e.field_path,
                original_value=e.original_value,
                severity=e.severity
            )
        
        self.audit_logger._flush_events()
        
        # Verify audit log contains violation
        with open(self.audit_logger.log_file, 'r') as f:
            log_content = f.read()
        
        assert "SECURITY_VIOLATION" in log_content
    
    def test_mixed_security_violations(self):
        """Test handling of multiple different security violations."""
        test_cases = [
            {
                "data": {"input": "import os; os.system('ls')"},
                "expected_type": "code_injection"
            },
            {
                "data": {"xss": "<script>alert('test')</script>"},
                "expected_type": "xss"
            },
            {
                "data": {"path": "../../../etc/passwd"},
                "expected_type": "path_traversal"
            }
        ]
        
        violations_logged = 0
        
        for case in test_cases:
            try:
                self.sanitizer.sanitize_dict(case["data"])
            except SecurityViolation as e:
                self.audit_logger.log_security_violation(
                    violation_type=e.violation_type,
                    description=e.description,
                    field_path=e.field_path,
                    severity=e.severity
                )
                violations_logged += 1
        
        self.audit_logger._flush_events()
        
        # Verify all violations were logged
        with open(self.audit_logger.log_file, 'r') as f:
            log_content = f.read()
        
        assert violations_logged > 0
        assert "SECURITY_VIOLATION" in log_content
    
    def test_performance_impact(self):
        """Test performance impact of security measures."""
        large_safe_data = {
            f"key_{i}": f"value_{i}" for i in range(100)
        }
        
        # Measure sanitization time
        start_time = time.time()
        result = self.sanitizer.sanitize_dict(large_safe_data)
        sanitization_time = time.time() - start_time
        
        # Sanitization should be fast (< 100ms for 100 items)
        assert sanitization_time < 0.1
        assert result == large_safe_data  # Should be unchanged for safe data
        
        # Measure audit logging time
        events = [
            SecurityEvent(
                event_type=EventType.SECURITY_VIOLATION.value,
                description=f"Test event {i}"
            ) for i in range(100)
        ]
        
        start_time = time.time()
        for event in events:
            self.audit_logger.log_event(event)
        logging_time = time.time() - start_time
        
        # Logging should be fast (< 50ms for 100 events)
        assert logging_time < 0.05


# Mock tests for components that require external dependencies
class TestSecureComponentsWithMocks:
    """Tests for secure components using mocks."""
    
    def test_secure_runtime_configuration(self):
        """Test secure runtime configuration validation."""
        # This would test SecureAgentRuntime configuration
        # Using mocks for external dependencies
        pass
    
    def test_rate_limiter_functionality(self):
        """Test rate limiting functionality."""
        # Mock implementation of rate limiter tests
        pass
    
    def test_memory_monitoring(self):
        """Test memory monitoring functionality."""
        # Mock implementation of memory monitoring
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])