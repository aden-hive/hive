"""
Zoho CRM Tool - Manage leads, contacts, accounts, and deals via Zoho CRM API v8.

Supports access tokens and OAuth2 refresh-token authentication.
"""

from .zoho_crm_tool import register_tools

__all__ = ["register_tools"]
