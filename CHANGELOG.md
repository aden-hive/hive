# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

### Changed

### Fixed

### Security

## [0.4.2] - 2026-02-08

### Added
- Resumable sessions: agents now automatically save state and can resume after interruptions
- `/resume` command in TUI to resume latest paused/failed session
- `/resume <session_id>` command to resume specific sessions
- `/sessions` command to list all sessions for current agent
- `--resume-session` CLI flag for automatic session resumption on startup
- `--checkpoint <checkpoint_id>` CLI flag for checkpoint-based recovery
- Ctrl+Z now immediately pauses execution with full state capture
- `/pause` command for immediate pause during execution
- Session state persistence: memory, execution path, node positions, visit counts
- Unified session storage at `~/.hive/agents/{agent_name}/sessions/`
- Automatic memory restoration on resume with full conversation history

### Changed
- TUI quit now pauses execution and saves state instead of cancelling
- Pause operations now use immediate task cancellation instead of waiting for node boundaries
- Session cleanup timeout increased from 0.5s to 5s to ensure proper state saving
- Session status now tracked as: active, paused, completed, failed, cancelled

### Deprecated
- Pause nodes (use client-facing EventLoopNodes instead)
- `request_pause()` method (replaced with immediate task cancellation)

### Removed
- N/A

### Fixed
- Memory persistence: ExecutionResult.session_state["memory"] now populated at all exit points
- Resume now starts at correct paused_at node instead of intake node
- Visit count double-counting on resume (paused node count now properly adjusted)
- Session selection now picks most recent session instead of oldest
- Quit state save failures due to insufficient timeout
- Ctrl+Z pause implementation (was only showing notification without pausing)
- Empty memory on resume by ensuring session_state["memory"] is properly populated

### Security
- N/A

## [0.1.0] - 2025-01-13

### Added
- Initial release

[Unreleased]: https://github.com/adenhq/hive/compare/v0.4.2...HEAD
[0.4.2]: https://github.com/adenhq/hive/compare/v0.4.0...v0.4.2
[0.1.0]: https://github.com/adenhq/hive/releases/tag/v0.1.0
