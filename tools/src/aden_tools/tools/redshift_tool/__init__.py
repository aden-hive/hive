"""
Redshift Tool - Query and manage Amazon Redshift data warehouse.

Supports:
- AWS IAM credentials (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
- Temporary session tokens via credential store
- Read-only SQL queries (recommended for security)
- Schema and table metadata inspection

API Reference: https://docs.aws.amazon.com/redshift/
"""

from __future__ import annotations

from .redshift_tool import register_tools

__all__ = ["register_tools"]
