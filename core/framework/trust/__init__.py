"""Trust module for managing trusted repositories.

This module provides trust gating for project-level skills to prevent
prompt injection from untrusted repositories.
"""

from .store import (
    TrustStore,
    TrustedRepo,
    get_project_remote_url,
    get_all_remote_urls,
    get_trust_store,
)

__all__ = [
    "TrustStore",
    "TrustedRepo",
    "get_project_remote_url",
    "get_all_remote_urls",
    "get_trust_store",
]
