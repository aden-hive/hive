"""
Documentation for security enhancements implemented in Hive framework.

This document provides an overview of the security improvements, their usage,
and best practices for secure deployment.
"""

# Security Enhancements for Hive Agent Framework

## Overview

The Hive framework has been enhanced with comprehensive security controls to protect against common vulnerabilities and provide enterprise-grade security for agent deployments.

## Security Components

### 1. Input Sanitization (`framework/security/sanitizer.py`)

**Purpose**: Prevent injection attacks and malicious input processing.

**Features**:
- Code injection detection using pattern matching and AST parsing
- XSS attack prevention
- Path traversal protection
- Input size validation
- Filename sanitization
- Configurable security policies

**Usage**:
```python
from framework.security import InputSanitizer

sanitizer = InputSanitizer()
clean_data = sanitizer.sanitize_dict(user_input)
safe_filename = sanitizer.sanitize_filename(filename)
is_valid_path = sanitizer.validate_file_path(file_path)
```

**Security Violations Detected**:
- Python/JavaScript/SQL code injection
- XSS attacks (`<script>`, `javascript:`, etc.)
- Path traversal (`../`, encoded variants)
- Oversized inputs
- Dangerous characters in filenames

### 2. Audit Logging (`framework/security/audit.py`)

**Purpose**: Comprehensive security event logging for compliance and forensics.

**Features**:
- Structured JSON logging with timestamps
- Multiple output destinations (file, syslog, external webhooks)
- Event correlation and search
- Automatic log rotation
- Performance metrics

**Event Types**:
- Security violations
- Runtime operations (start/stop/execute)
- Configuration changes
- Resource limit exceeded
- Credential access
- Network access

**Usage**:
```python
from framework.security import AuditLogger, SecurityEvent

audit = AuditLogger(
    log_file=Path("./audit.log"),
    max_file_size=50*1024*1024,  # 50MB
    backup_count=5
)

audit.log_security_violation(
    violation_type="code_injection",
    description="Potential code injection detected",
    field_path="input.code",
    severity="high"
)
```

### 3. Secure Agent Runtime (`framework/runtime/secure_agent_runtime.py`)

**Purpose**: Security-hardened runtime with resource management and monitoring.

**Enhancements**:
- Thread-safe operations with proper locking
- Resource usage monitoring and limits
- Input sanitization integration
- Memory leak prevention
- Automatic cleanup of idle resources
- Comprehensive error handling

**Configuration**:
```python
from framework.runtime import SecureAgentRuntime, SecurityConfig

security_config = SecurityConfig(
    enable_sandbox=True,
    max_execution_time=300.0,  # 5 minutes
    max_memory_mb=1024,
    audit_enabled=True,
    sanitize_inputs=True
)

runtime = SecureAgentRuntime(
    graph=graph_spec,
    goal=goal_spec,
    storage_path="./storage",
    security_config=security_config
)
```

### 4. Secure Graph Executor (`framework/graph/secure_executor.py`)

**Purpose**: Secure execution of agent graphs with validation and monitoring.

**Features**:
- Input/output validation at each node
- Execution timeout enforcement
- Memory usage monitoring
- Security violation tracking
- Enhanced error handling and recovery
- Performance metrics collection

**Security Metrics**:
- Number of security violations
- Input sanitizations performed
- Output validations failed
- Memory peak usage
- Execution time tracking

### 5. Enhanced Storage (`framework/storage/concurrent.py`)

**Purpose**: Thread-safe storage with LRU caching and performance monitoring.

**Improvements**:
- Thread-safe lock manager (replaces problematic defaultdict)
- LRU cache implementation with TTL
- Batch write operations with error handling
- Resource cleanup and monitoring
- Performance statistics

### 6. Secure MCP Server (`tools/secure_mcp_server.py`)

**Purpose**: Security-hardened MCP server with network protection.

**Features**:
- Rate limiting (configurable requests per minute)
- IP whitelist/blacklist support
- Request size validation
- Input sanitization
- Comprehensive audit logging
- Health monitoring endpoints

**Configuration**:
```bash
# Environment variables
MAX_REQUESTS_PER_MINUTE=100
ENABLE_AUDIT_LOGGING=true
AUDIT_LOG_FILE=./mcp_audit.log
ENABLE_IP_WHITELIST=false
ALLOWED_NETWORKS=10.0.0.0/8,192.168.0.0/16
MAX_REQUEST_SIZE=10485760  # 10MB
REQUEST_TIMEOUT=30
```

## Security Controls

### Input Validation

- **Code Injection**: Pattern-based detection + AST parsing for Python code
- **XSS Prevention**: Remove dangerous HTML/JavaScript content
- **Path Traversal**: Normalize paths and block traversal sequences
- **Size Limits**: Enforce maximum input sizes for strings, dicts, and lists
- **Filename Security**: Sanitize filenames to prevent directory traversal

### Resource Protection

- **Memory Limits**: Monitor and enforce memory usage thresholds
- **Execution Timeouts**: Prevent infinite loops and hanging operations
- **Rate Limiting**: Throttle requests by IP to prevent abuse
- **Connection Limits**: Control concurrent execution capacity

### Monitoring & Auditing

- **Comprehensive Logging**: All security events logged with full context
- **Performance Metrics**: Track resource usage and execution patterns
- **Violation Tracking**: Detailed logging of security violations
- **Audit Trail**: Complete audit log for compliance requirements

### Network Security

- **IP Filtering**: Optional whitelist/blacklist for client IPs
- **Request Validation**: Size limits and content validation
- **Rate Limiting**: Token bucket algorithm for request throttling
- **Secure Headers**: Security headers in HTTP responses

## Deployment Guidelines

### Production Deployment

1. **Enable All Security Features**:
   ```python
   security_config = SecurityConfig(
       enable_sandbox=True,
       audit_enabled=True,
       sanitize_inputs=True
   )
   ```

2. **Configure Resource Limits**:
   ```python
   runtime_config = AgentRuntimeConfig(
       max_concurrent_executions=50,  # Reduced for safety
       max_execution_time=300.0,       # 5 minutes
       max_memory_mb=1024              # 1GB
   )
   ```

3. **Set Up Audit Logging**:
   ```python
   audit_logger = AuditLogger(
       log_file=Path("/var/log/hive/audit.log"),
       enable_syslog=True,
       external_webhook="https://your-audit-service.com/webhook"
   )
   ```

4. **Network Security**:
   ```bash
   # Enable IP whitelist for production
   ENABLE_IP_WHITELIST=true
   ALLOWED_NETWORKS=10.0.0.0/8,192.168.0.0/16
   
   # Set conservative rate limits
   MAX_REQUESTS_PER_MINUTE=50
   ```

### Monitoring and Alerting

1. **Security Event Monitoring**:
   - Monitor for CRITICAL and HIGH security level events
   - Set up alerts for rate limit exceeded
   - Track resource limit violations

2. **Performance Monitoring**:
   - Monitor memory usage trends
   - Track execution success rates
   - Watch for increasing security violation rates

3. **Audit Log Analysis**:
   - Regular review of audit logs
   - Correlate security events with application logs
   - Maintain audit log retention policies

### Best Practices

1. **Input Validation**:
   - Always sanitize user inputs
   - Validate file paths before filesystem operations
   - Use prepared statements for database queries

2. **Resource Management**:
   - Set appropriate memory and time limits
   - Monitor resource usage regularly
   - Implement proper cleanup procedures

3. **Security Monitoring**:
   - Enable comprehensive audit logging
   - Set up automated security alerts
   - Regular security reviews and updates

4. **Network Security**:
   - Use firewalls to restrict access
   - Implement VPN or private networks for internal services
   - Keep all dependencies updated

## Security Testing

### Running Security Tests

```bash
# Run the security test suite
cd core
python -m pytest tests/test_security.py -v

# Run with coverage
python -m pytest tests/test_security.py --cov=framework.security --cov-report=html
```

### Test Coverage

The security test suite covers:
- Input sanitization for various attack vectors
- Audit logging functionality
- Rate limiting behavior
- Security violation detection
- Performance impact assessment
- Integration between components

### Penetration Testing

For comprehensive security testing:
1. Run automated security scanners
2. Perform manual penetration testing
3. Test with real-world attack scenarios
4. Validate audit trail completeness
5. Test resource limit enforcement

## Incident Response

### Security Incident Response

1. **Detection**:
   - Monitor audit logs for security violations
   - Set up alerts for critical events
   - Watch for unusual patterns

2. **Analysis**:
   - Review audit logs for full incident timeline
   - Analyze impact and scope
   - Identify root cause

3. **Containment**:
   - Block malicious IP addresses
   - Increase rate limiting
   - Disable vulnerable features temporarily

4. **Recovery**:
   - Patch vulnerabilities
   - Review and update security configurations
   - Monitor for recurrence

5. **Documentation**:
   - Document incident details
   - Update security procedures
   - Share lessons learned

## Compliance

### Regulatory Compliance

The security features support compliance with:
- **GDPR**: Data processing and audit logging
- **SOC 2**: Security controls and monitoring
- **ISO 27001**: Information security management
- **PCI DSS**: Payment card data protection (if applicable)

### Audit Requirements

For compliance audits, the system provides:
- Complete audit trail with timestamps
- Security event logging
- Access control records
- Resource usage monitoring
- Configuration change tracking

## Troubleshooting

### Common Security Issues

1. **High False Positive Rate**:
   - Adjust sanitization patterns
   - Review security configuration
   - Customize input validation rules

2. **Performance Impact**:
   - Optimize cache settings
   - Review rate limiting configuration
   - Monitor memory usage patterns

3. **Audit Log Issues**:
   - Check disk space for log files
   - Verify log rotation settings
   - Review external webhook connectivity

### Debug Mode

For troubleshooting, enable debug logging:
```python
import logging
logging.getLogger("framework.security").setLevel(logging.DEBUG)
```

## Future Enhancements

Planned security improvements:
1. **Advanced Threat Detection**: Machine learning for anomaly detection
2. **Zero Trust Architecture**: Mutual TLS and certificate management
3. **Secret Management**: Integration with vault systems
4. **Container Security**: Runtime protection for containerized deployments
5. **Compliance Automation**: Automated compliance checking and reporting

## Support and Reporting

For security issues:
1. **Report Security Vulnerabilities**: Use the private security reporting process
2. **Security Questions**: Contact the security team
3. **Documentation**: Check the security documentation for guidance
4. **Community**: Join the security discussions in the community forums