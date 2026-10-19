"""
HubSpot CRM Tool - Manage contacts, companies, and deals via HubSpot API v3.

Supports Private App tokens and OAuth2 authentication.
"""

from .hubspot_tool import register_tools

__all__ = ["register_tools"]
