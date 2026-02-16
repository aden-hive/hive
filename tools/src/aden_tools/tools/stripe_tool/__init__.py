"""
Stripe Tool for Hive Framework

A comprehensive Stripe integration providing full billing automation capabilities.
"""

from .stripe_tool import StripeTool, StripeToolConfig
from .stripe_tool_registration import register_tools

__version__ = "1.0.0"

__all__ = [
    "StripeTool",
    "StripeToolConfig",
    "register_tools",
]
# Note: Stripe credentials are handled separately in aden_tools.credentials.stripe
