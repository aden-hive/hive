"""Enterprise Security Module for Hive Framework.

Provides comprehensive security controls:
- Input validation and sanitization
- Encryption for sensitive data
- Secure secrets management
- Audit logging
- Injection prevention
- Authentication and authorization

Usage:
    from framework.security import (
        SecurityConfig,
        validate_input,
        encrypt_sensitive,
        audit_log,
        sanitize,
    )
"""

from framework.security.validation import (
    InputValidator,
    ValidationResult,
    validate_input,
    validate_node_output,
)
from framework.security.encryption import (
    EncryptionService,
    encrypt_value,
    decrypt_value,
    hash_value,
)
from framework.security.secrets import (
    SecretManager,
    get_secret,
    mask_secret,
)
from framework.security.audit import (
    AuditLogger,
    SecurityEvent,
    audit_log,
    get_audit_logger,
)
from framework.security.sanitizer import (
    Sanitizer,
    sanitize_input,
    sanitize_output,
    sanitize_for_llm,
)
from framework.security.auth import (
    AuthContext,
    Permission,
    Role,
    require_permission,
    check_permission,
)
from framework.security.config import (
    SecurityConfig,
    get_security_config,
    configure_security,
)

__all__ = [
    # Validation
    "InputValidator",
    "ValidationResult",
    "validate_input",
    "validate_node_output",
    # Encryption
    "EncryptionService",
    "encrypt_value",
    "decrypt_value",
    "hash_value",
    # Secrets
    "SecretManager",
    "get_secret",
    "mask_secret",
    # Audit
    "AuditLogger",
    "SecurityEvent",
    "audit_log",
    "get_audit_logger",
    # Sanitization
    "Sanitizer",
    "sanitize_input",
    "sanitize_output",
    "sanitize_for_llm",
    # Auth
    "AuthContext",
    "Permission",
    "Role",
    "require_permission",
    "check_permission",
    # Config
    "SecurityConfig",
    "get_security_config",
    "configure_security",
]
