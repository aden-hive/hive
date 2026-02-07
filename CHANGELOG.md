# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Initial project structure
- React frontend (honeycomb) with Vite and TypeScript
- Node.js backend (hive) with Express and TypeScript
- Docker Compose configuration for local development
- Configuration system via `config.yaml`
- GitHub Actions CI/CD workflows
- Comprehensive documentation
- **Enterprise Infrastructure Modules**:
  - `framework/telemetry.py` - OpenTelemetry distributed tracing and Prometheus metrics
  - `framework/cache.py` - Multi-tier LRU cache with TTL support
  - `framework/ratelimit.py` - Token bucket rate limiting
  - `framework/health.py` - Multi-component health check system
  - `framework/logging.py` - Structured JSON logging with correlation IDs
  - `framework/llm/pool.py` - Async connection pooling
- **Enterprise Security Modules** (`framework/security/`):
  - `config.py` - Centralized security configuration
  - `validation.py` - SQL, XSS, command, prompt injection detection
  - `encryption.py` - AES-256-GCM encryption with PBKDF2
  - `secrets.py` - Secrets management with auto-masking
  - `audit.py` - Tamper-evident audit logging
  - `sanitizer.py` - Deep input sanitization
  - `auth.py` - Role-based access control (RBAC)
- **Node Modularization** - Refactored monolithic `node.py` into modular package:
  - `framework/graph/node/` with 7 focused modules
- **Error Hierarchy** - 30+ typed exceptions in `framework/errors.py`
- **Active Integration** - Tracing, metrics, and security wired into core execution flow

### Changed

- N/A

### Deprecated

- N/A

### Removed

- N/A

### Fixed

- tools: Fixed web_scrape tool attempting to parse non-HTML content (PDF, JSON) as HTML (#487)

### Security

- Added comprehensive input validation against injection attacks
- Added encryption support for sensitive data at rest
- Added RBAC for fine-grained access control
- Added tamper-evident audit logging

## [0.1.0] - 2025-01-13

### Added

- Initial release

[Unreleased]: https://github.com/adenhq/hive/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/adenhq/hive/releases/tag/v0.1.0
