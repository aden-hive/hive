"""
Tests for CRM-specific credential specifications.
"""

import pytest
from aden_tools.credentials import CredentialManager, CRM_CREDENTIALS

def test_hubspot_spec_exists():
    """Verify that hubspot specimen is registered."""
    creds = CredentialManager()
    assert "hubspot" in creds._specs
    assert "hubspot_webhook_secret" in creds._specs

def test_hubspot_env_vars():
    """Verify environment variable mappings."""
    creds = CredentialManager()
    assert creds.get_spec("hubspot").env_var == "HUBSPOT_ACCESS_TOKEN"
    assert creds.get_spec("hubspot_webhook_secret").env_var == "HUBSPOT_WEBHOOK_SIGNING_SECRET"

def test_hubspot_tool_requirements():
    """Verify tools mapped to hubspot credential."""
    spec = CRM_CREDENTIALS["hubspot"]
    assert "hubspot_health_check" in spec.tools
    assert "hubspot_webhook_receive" in spec.tools
    assert "hubspot_register_webhook_subscription" in spec.tools
