# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Salesforce CRM MCP tool** — Search, get, create, and update for Leads, Contacts, Accounts, and Opportunities via Salesforce REST API. Credential spec for `SALESFORCE_INSTANCE_URL` and `SALESFORCE_ACCESS_TOKEN`; input validation and SOQL sanitization for security.
- Initial project structure
- React frontend (honeycomb) with Vite and TypeScript
- Node.js backend (hive) with Express and TypeScript
- Docker Compose configuration for local development
- Configuration system via `config.yaml`
- GitHub Actions CI/CD workflows
- Comprehensive documentation

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A


### Fixed
- tools: Fixed web_scrape tool attempting to parse non-HTML content (PDF, JSON) as HTML (#487)

### Security
- N/A

## [0.1.0] - 2025-01-13

### Added
- Initial release

[Unreleased]: https://github.com/adenhq/hive/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/adenhq/hive/releases/tag/v0.1.0
