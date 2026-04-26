import sys
import os

# Add the specific tool directory to path to bypass aden_tools/__init__.py
sys.path.insert(0, os.path.abspath('tools/src/aden_tools/tools/dns_security_scanner'))

import dns.resolver
from dns_security_scanner import _check_dnssec

def test_domain(domain):
    print(f"--- Testing {domain} ---")
    resolver = dns.resolver.Resolver()
    result = _check_dnssec(resolver, domain)
    print("Result:", result)

test_domain("ietf.org")
test_domain("example.com")
test_domain("cloudflare.com")
test_domain("google.com")
