"""
Plaid Integration for Hive

Secure banking data access via Plaid API.
"""

from .connector import PlaidConnector, PlaidConfig, create_plaid_connector_from_env
from .credentials import PlaidCredentials, PLAID_CREDENTIAL_SPEC

__all__ = [
    "PlaidConnector",
    "PlaidConfig", 
    "PlaidCredentials",
    "PLAID_CREDENTIAL_SPEC",
    "create_plaid_connector_from_env"
]