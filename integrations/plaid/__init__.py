"""Plaid integration package for Hive."""

from __future__ import annotations

from .connector import PlaidConfig, PlaidConnector, create_plaid_connector_from_env

# Keep credentials export optional in case framework path isn't set at import time.
try:
    from .credentials import PLAID_CREDENTIAL_SPEC, PlaidCredentials
except Exception:  # pragma: no cover
    PlaidCredentials = None
    PLAID_CREDENTIAL_SPEC = None

__all__ = [
    "PlaidConnector",
    "PlaidConfig",
    "create_plaid_connector_from_env",
    "PlaidCredentials",
    "PLAID_CREDENTIAL_SPEC",
]
