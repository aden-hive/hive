"""DNS Security Scanner - Check SPF, DMARC, DKIM, DNSSEC, and zone transfer."""

from .dns_security_scanner import register_tools

__all__ = ["register_tools"]
