"""
HashiCorp Vault integration for the credential store.

This module provides enterprise-grade secret management through
HashiCorp Vault integration.

Quick Start:
    from core.framework.credentials import CredentialStore
    from core.framework.credentials.vault import HashiCorpVaultStorage

    # Configure Vault storage
    storage = HashiCorpVaultStorage(
        url="https://vault.example.com:8200",
        # token read from VAULT_TOKEN env var
        mount_point="secret",
        path_prefix="hive/agents/prod"
    )

    # Create credential store with Vault backend
    store = CredentialStore(storage=storage)

    # Use normally - credentials are stored in Vault
    credential = store.get_credential("my_api")

Requirements:
    pip install hvac

Authentication:
    Set the VAULT_TOKEN environment variable or pass the token directly:

        export VAULT_TOKEN="hvs.xxxxxxxxxxxxx"

    For production, consider using Vault auth methods:
    - Kubernetes auth
    - AppRole auth
    - AWS IAM auth

Vault Configuration:
    Ensure KV v2 secrets engine is enabled:

        vault secrets enable -path=secret kv-v2

    Grant appropriate policies:

        path "secret/data/hive/credentials/*" {
            capabilities = ["create", "read", "update", "delete", "list"]
        }
        path "secret/metadata/hive/credentials/*" {
            capabilities = ["list", "delete"]
        }
"""

from .hashicorp import HashiCorpVaultStorage

__all__ = ["HashiCorpVaultStorage"]
