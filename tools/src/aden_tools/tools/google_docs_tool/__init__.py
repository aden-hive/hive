"""
Google Docs Tool - Create and manage Google Docs documents.

Supports OAuth2 authentication via Google service account or OAuth2 tokens.
"""

from .google_docs_tool import register_tools

__all__ = ["register_tools"]
