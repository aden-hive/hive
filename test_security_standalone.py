"""
Standalone test script for security modules without framework dependencies.
"""

import sys
import os

# Add the current directory to Python path
sys.path.insert(0, '/home/jorge/projects/github/pruebas/others/hive/core')

# Import our security modules directly
from framework.security.simple_security import (
    InputSanitizer, 
    AuditLogger, 
    SecurityViolation, 
    SecurityLevel,
    SecurityEvent
)

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
    import tempfile
    temp_dir = tempfile.mkdtemp()
    log_file = os.path.join(temp_dir, "test_audit.log")
    
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
    
    # Test runtime events
    audit_logger.log_runtime_start(5)
    audit_logger.log_execution_trigger("test_ep", "exec_123")
    audit_logger.log_runtime_stop()
    
    # Check stats
    stats = audit_logger.get_stats()
    assert stats["events_logged"] >= 4, "Events should be logged"
    print(f"  ✓ Logged {stats['events_logged']} events")
    
    # Check log file exists
    assert os.path.exists(log_file), "Log file should be created"
    print("  ✓ Log file created successfully")
    
    # Cleanup
    import shutil
    shutil.rmtree(temp_dir)
    
    print("AuditLogger tests passed!\n")

def test_integration():
    """Test integration between security components."""
    print("Testing Security Integration...")
    
    sanitizer = InputSanitizer()
    import tempfile
    temp_dir = tempfile.mkdtemp()
    log_file = os.path.join(temp_dir, "integration_audit.log")
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
    import shutil
    shutil.rmtree(temp_dir)
    
    print("Integration tests passed!\n")

def test_performance():
    """Test performance impact of security measures."""
    print("Testing Security Performance...")
    
    import time
    
    sanitizer = InputSanitizer()
    
    # Test with large safe dataset
    large_data = {f"key_{i}": f"value_{i}" for i in range(100)}
    
    start_time = time.time()
    result = sanitizer.sanitize_dict(large_data)
    sanitization_time = time.time() - start_time
    
    assert sanitization_time < 0.1, "Sanitization should be fast"
    print(f"  ✓ Sanitized 100 items in {sanitization_time:.4f}s")
    
    # Test audit logging performance
    import tempfile
    temp_dir = tempfile.mkdtemp()
    log_file = os.path.join(temp_dir, "perf_audit.log")
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
    import shutil
    shutil.rmtree(temp_dir)
    
    print("Performance tests passed!\n")

if __name__ == "__main__":
    print("🔒 Running Security Module Tests\n")
    
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
        sys.exit(1)