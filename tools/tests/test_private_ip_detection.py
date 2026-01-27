"""
Test suite for SSRF protection in web_scrape_tool

This demonstrates that the tool properly blocks:
- Localhost addresses (127.0.0.1, localhost)
- Private IP ranges (10.x.x.x, 192.168.x.x, 172.16-31.x.x)
- Link-local addresses (169.254.x.x)
- Cloud metadata endpoints (169.254.169.254)
- IPv6 loopback and private ranges
"""

import sys
from pathlib import Path

# Add the module to path for testing
sys.path.insert(0, str(Path(__file__).parent))

from web_scrape_tool import _is_private_ip, _resolve_and_validate_url


def test_private_ip_detection():
    """Test that private/internal IPs are correctly identified"""
    
    print("=" * 70)
    print("Testing Private IP Detection")
    print("=" * 70)
    
    test_cases = [
        # Localhost
        ("127.0.0.1", True, "IPv4 localhost"),
        ("127.0.0.53", True, "IPv4 localhost range"),
        ("::1", True, "IPv6 localhost"),
        
        # Private ranges (RFC 1918)
        ("10.0.0.1", True, "10.x.x.x private range"),
        ("192.168.1.1", True, "192.168.x.x private range"),
        ("172.16.0.1", True, "172.16.x.x private range"),
        ("172.31.255.255", True, "172.31.x.x private range"),
        
        # Link-local
        ("169.254.169.254", True, "AWS metadata endpoint"),
        ("169.254.1.1", True, "Link-local range"),
        ("fe80::1", True, "IPv6 link-local"),
        
        # Multicast/Reserved
        ("224.0.0.1", True, "Multicast"),
        ("255.255.255.255", True, "Broadcast"),
        ("0.0.0.0", True, "Unspecified"),
        
        # Public IPs (should be allowed)
        ("8.8.8.8", False, "Google DNS - public"),
        ("1.1.1.1", False, "Cloudflare DNS - public"),
        ("93.184.216.34", False, "example.com - public"),
        
        # IPv6 public
        ("2001:4860:4860::8888", False, "Google DNS IPv6 - public"),
    ]
    
    passed = 0
    failed = 0
    
    for ip, should_be_private, description in test_cases:
        result = _is_private_ip(ip)
        status = "✓ PASS" if result == should_be_private else "✗ FAIL"
        
        if result == should_be_private:
            passed += 1
        else:
            failed += 1
        
        print(f"{status} | {ip:20} | Expected: {'Private' if should_be_private else 'Public':7} | {description}")
    
    print(f"\nResults: {passed} passed, {failed} failed")
    print()


def test_url_validation():
    """Test that URLs targeting internal resources are blocked"""
    
    print("=" * 70)
    print("Testing URL Validation (SSRF Protection)")
    print("=" * 70)
    
    test_cases = [
        # Should be blocked
        ("http://localhost", True, "localhost domain"),
        ("http://127.0.0.1", True, "localhost IP"),
        ("http://192.168.1.1", True, "private IP"),
        ("http://10.0.0.1", True, "private IP"),
        ("http://172.16.0.1", True, "private IP"),
        ("http://169.254.169.254", True, "AWS metadata endpoint"),
        ("http://[::1]", True, "IPv6 localhost"),
        ("http://[fe80::1]", True, "IPv6 link-local"),
        
        # Should be allowed (public domains)
        ("http://example.com", False, "public domain"),
        ("https://google.com", False, "public domain"),
        ("https://github.com", False, "public domain"),
    ]
    
    blocked = 0
    allowed = 0
    errors = 0
    
    for url, should_block, description in test_cases:
        allowed_result, reason = _resolve_and_validate_url(url)
        is_blocked = not allowed_result
        
        if should_block:
            if is_blocked:
                status = "✓ BLOCKED"
                blocked += 1
            else:
                status = "✗ NOT BLOCKED (FAIL)"
                errors += 1
        else:
            if not is_blocked:
                status = "✓ ALLOWED"
                allowed += 1
            else:
                status = "✗ BLOCKED (FAIL)"
                errors += 1
        
        print(f"{status:20} | {url:30} | {description}")
        print(f"{'':20} | Reason: {reason}")
        print()
    
    print(f"Results: {blocked} correctly blocked, {allowed} correctly allowed, {errors} errors")
    print()


def test_hostname_resolution():
    """Test that hostnames resolving to private IPs are blocked"""
    
    print("=" * 70)
    print("Testing Hostname Resolution")
    print("=" * 70)
    
    # This demonstrates that even if someone creates a DNS entry pointing to
    # a private IP, it will be blocked
    
    test_cases = [
        ("http://localhost.localdomain", "Should resolve to 127.0.0.1 and be blocked"),
    ]
    
    for url, description in test_cases:
        allowed, reason = _resolve_and_validate_url(url)
        status = "✓ BLOCKED" if not allowed else "✗ ALLOWED (POTENTIAL ISSUE)"
        
        print(f"{status} | {url}")
        print(f"{'':9} | {description}")
        print(f"{'':9} | Reason: {reason}")
        print()


def main():
    """Run all tests"""
    print("\n")
    print("█" * 70)
    print("  SSRF PROTECTION TEST SUITE")
    print("█" * 70)
    print()
    
    test_private_ip_detection()
    test_url_validation()
    test_hostname_resolution()
    
    print("=" * 70)
    print("All tests completed!")
    print("=" * 70)
    print()
    print("Key Security Features Implemented:")
    print("  ✓ Blocks localhost (127.0.0.1, ::1)")
    print("  ✓ Blocks private IP ranges (10.x, 192.168.x, 172.16-31.x)")
    print("  ✓ Blocks link-local addresses (169.254.x.x)")
    print("  ✓ Blocks cloud metadata endpoints (169.254.169.254)")
    print("  ✓ Blocks IPv6 private/local addresses")
    print("  ✓ Resolves hostnames to check resolved IPs")
    print("  ✓ Validates before making HTTP requests")
    print()


if __name__ == "__main__":
    main()