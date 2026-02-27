"""
Apollo.io Tool - Contact and company data enrichment via Apollo API.

Supports API key authentication for:
- Person enrichment by email or LinkedIn
- Company enrichment by domain
- People search with filters
- Company search with filters
"""

from .apollo_tool import register_tools

__all__ = ["register_tools"]
