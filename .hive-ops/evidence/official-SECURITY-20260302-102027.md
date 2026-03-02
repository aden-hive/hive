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

- Environment-based configuration (no hardcoded secrets)
- Input validation on API endpoints
- Secure session handling
- CORS configuration
- Rate limiting (configurable)
