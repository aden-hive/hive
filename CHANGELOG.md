# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Developer Experience improvements: Makefile commands (`make lint`, `make test`, `make check`)
- Pre-commit hooks for linting and formatting
- Pyright and VS Code configuration for better type checking and editor support
- New documentation guides for contributing and lint setup
- Improved CI workflows for linting and formatting
- Additional test coverage across core runtime components
- Initial groundwork for lifecycle APIs and runtime management

### Changed
- Refactored project tooling for better cross-package import resolution
- Documentation structure improved for onboarding clarity
- Updated contribution workflow to better align with actual contributor experience


### Fixed
- tools: Fixed web_scrape tool attempting to parse non-HTML content (PDF, JSON) as HTML (#487)
- Multiple setup inconsistencies that caused confusion for first-time contributors
- Import resolution issues between `core/` and `tools/`
- Linting and formatting inconsistencies across packages

### Deprecated
- Legacy setup assumptions relying on PYTHONPATH hacks for editor resolution

### Removed
- N/A


### Security
- N/A

## [0.1.0] - 2025-01-13

### Added
- Initial public release of the Hive framework

[Unreleased]: https://github.com/adenhq/hive/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/adenhq/hive/releases/tag/v0.1.0

---

### Changelog Maintenance (Contributor Note)

For significant user-facing changes (features, breaking changes, major fixes), contributors are encouraged to include a brief changelog entry in their PR description.  
Maintainers may periodically curate and update this file based on merged PRs.
