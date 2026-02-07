# Maintainer Service

An intelligent GitHub Issue & PR Management System that provides:
- **Smart Issue Triage**: Hourly digest of novel, high-value issues
- **PR Automation**: Auto-describe, review, and improve pull requests

## Architecture

- **Ingestion**: Real-time webhook processing → Vector DB
- **Analysis**: Hourly batch triage using ChromaDB + LLM
- **Reporting**: Compiled digest via Email/Slack

See `docs/design.md` for full technical specification.

## Quick Start

```bash
cd maintainer_service
uv pip install -r requirements.txt
python -m app.main
```
