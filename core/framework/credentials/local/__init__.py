"""
Local credential registry — named API key accounts with identity metadata.

Provides feature parity with Aden OAuth credentials for locally-stored API keys:
aliases, identity metadata, status tracking, CRUD, and health validation.

Usage:
    import logging
    from framework.credentials.local import LocalCredentialRegistry, LocalAccountInfo
    
    logger = logging.getLogger(__name__)
    registry = LocalCredentialRegistry.default()

    # Add a named account
    info, health = registry.save_account("brave_search", "work", "BSA-xxx")

    # List all stored local accounts
    for account in registry.list_accounts():
        logger.info("%s/%s: %s", account.credential_id, account.alias, account.status)
        if account.identity.is_known:
            logger.info("  Identity: %s", account.identity.label)

    # Re-validate a stored account
    result = registry.validate_account("github", "personal")
"""

from .models import LocalAccountInfo
from .registry import LocalCredentialRegistry

__all__ = [
    "LocalAccountInfo",
    "LocalCredentialRegistry",
]
