# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.x.x   | :white_check_mark: |

## Reporting a Vulnerability

We take security vulnerabilities seriously. If you discover a security issue, please report it responsibly.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please send an email to contact@adenhq.com with:

1. A description of the vulnerability
2. Steps to reproduce the issue
3. Potential impact of the vulnerability
4. Any possible mitigations you've identified

### What to Expect

- **Acknowledgment**: We will acknowledge receipt of your report within 48 hours
- **Communication**: We will keep you informed of our progress
- **Resolution**: We aim to resolve critical vulnerabilities within 7 days
- **Credit**: We will credit you in our security advisories (unless you prefer to remain anonymous)

### Safe Harbor

We consider security research conducted in accordance with this policy to be:

- Authorized concerning any applicable anti-hacking laws
- Authorized concerning any relevant anti-circumvention laws
- Exempt from restrictions in our Terms of Service that would interfere with conducting security research

## Security Best Practices for Users

1. **Keep Updated**: Always run the latest version
2. **Secure Configuration**: Review `config.yaml` settings, especially in production
3. **Environment Variables**: Never commit `.env` files or `config.yaml` with secrets
4. **Network Security**: Use HTTPS in production, configure firewalls appropriately
5. **Database Security**: Use strong passwords, limit network access

## Security Features

Hive includes comprehensive enterprise-grade security:

### Built-in Protection

- Environment-based configuration (no hardcoded secrets)
- Input validation on API endpoints
- Secure session handling
- CORS configuration
- Rate limiting (configurable)

### Security Modules (`framework/security/`)

| Module          | Purpose                                                            |
| --------------- | ------------------------------------------------------------------ |
| `config.py`     | Centralized security configuration with environment detection      |
| `validation.py` | Input validation detecting SQL, XSS, command, and prompt injection |
| `encryption.py` | AES-256-GCM encryption with PBKDF2 key derivation                  |
| `secrets.py`    | Secrets management with auto-masking in logs                       |
| `audit.py`      | Tamper-evident audit logging with chain hashing                    |
| `sanitizer.py`  | Deep sanitization for HTML, control chars, Unicode                 |
| `auth.py`       | Role-based access control (RBAC)                                   |

### Usage Example

```python
from framework.security import (
    SecurityConfig,
    validate_input,
    encrypt_value,
    decrypt_value,
    mask_secret,
    sanitize_input,
    AuthContext,
    Role,
    Permission,
)

# Configure for production
config = SecurityConfig.for_production()

# Validate user input
result = validate_input(user_input)
if not result.is_valid:
    print(f"Threats detected: {result.threats_detected}")
    user_input = sanitize_input(user_input)

# Encrypt sensitive data
encrypted = encrypt_value("secret_data", key="master_key")
decrypted = decrypt_value(encrypted, key="master_key")

# Mask secrets in logs
safe_log = mask_secret("sk-abc123xyz789")  # -> "sk-ab***89"

# Role-based authorization
ctx = AuthContext.for_role("user_id", Role.DEVELOPER)
if ctx.has_permission(Permission.EXECUTE_GRAPH):
    # User is authorized
    pass
```

### Attack Prevention

The framework automatically detects and blocks:

- **SQL Injection** - `SELECT * FROM users WHERE...`
- **XSS Attacks** - `<script>alert('xss')</script>`
- **Command Injection** - `; rm -rf /`
- **Prompt Injection** - `Ignore previous instructions...`
- **Path Traversal** - `../../../etc/passwd`
