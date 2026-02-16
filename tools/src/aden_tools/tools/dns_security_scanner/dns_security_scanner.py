"""
DNS Security Scanner - Check SPF, DMARC, DKIM, DNSSEC, and zone transfer.

Performs non-intrusive DNS queries to evaluate email security configuration
and DNS infrastructure hardening. Uses dnspython for all lookups.
"""

from __future__ import annotations

from fastmcp import FastMCP

try:
    import dns.exception
    import dns.name
    import dns.query
    import dns.rdatatype
    import dns.resolver
    import dns.xfr
    import dns.zone

    _DNS_AVAILABLE = True
except ImportError:
    _DNS_AVAILABLE = False

# Common DKIM selectors to probe
DKIM_SELECTORS = ["default", "google", "selector1", "selector2", "k1", "mail", "dkim", "s1"]


def register_tools(mcp: FastMCP) -> None:
    """Register DNS security scanning tools with the MCP server."""

    @mcp.tool()
    def dns_security_scan(domain: str) -> dict:
        """
        Scan a domain's DNS records for email security and infrastructure hardening.

        Checks SPF, DMARC, DKIM (common selectors), DNSSEC, MX, CAA records,
        and tests for zone transfer vulnerability. Non-intrusive — uses standard
        DNS queries only.

        Args:
            domain: Domain name to scan (e.g., "example.com"). Do not include protocol.

        Returns:
            Dict with SPF, DMARC, DKIM, DNSSEC, MX, CAA results, zone transfer
            status, and grade_input for the risk_scorer tool.
        """
        if not _DNS_AVAILABLE:
            return {
                "error": ("dnspython is not installed. Install it with: pip install dnspython"),
            }

        # Clean domain
        domain = domain.replace("https://", "").replace("http://", "").strip("/")
        domain = domain.split("/")[0]
        if ":" in domain:
            domain = domain.split(":")[0]

        resolver = dns.resolver.Resolver()
        resolver.timeout = 10
        resolver.lifetime = 10

        spf = _check_spf(resolver, domain)
        dmarc = _check_dmarc(resolver, domain)
        dkim = _check_dkim(resolver, domain)
        dnssec = _check_dnssec(resolver, domain)
        mx = _check_mx(resolver, domain)
        caa = _check_caa(resolver, domain)
        zone_transfer = _check_zone_transfer(resolver, domain)

        grade_input = {
            "spf_present": spf["present"],
            "spf_strict": spf.get("policy") == "hardfail",
            "dmarc_present": dmarc["present"],
            "dmarc_enforcing": dmarc.get("policy") in ("quarantine", "reject"),
            "dkim_found": len(dkim.get("selectors_found", [])) > 0,
            "dnssec_enabled": dnssec["enabled"],
            "zone_transfer_blocked": not zone_transfer["vulnerable"],
        }

        return {
            "domain": domain,
            "spf": spf,
            "dmarc": dmarc,
            "dkim": dkim,
            "dnssec": dnssec,
            "mx_records": mx,
            "caa_records": caa,
            "zone_transfer": zone_transfer,
            "grade_input": grade_input,
        }


def _check_spf(resolver: dns.resolver.Resolver, domain: str) -> dict:
    """Check SPF record."""
    try:
        answers = resolver.resolve(domain, "TXT")
        for rdata in answers:
            txt = rdata.to_text().strip('"')
            if txt.startswith("v=spf1"):
                issues = []
                if "~all" in txt:
                    policy = "softfail"
                    issues.append(
                        "Uses ~all (softfail) instead of -all (hardfail). "
                        "Spoofed emails may still be delivered."
                    )
                elif "-all" in txt:
                    policy = "hardfail"
                elif "+all" in txt:
                    policy = "pass_all"
                    issues.append(
                        "Uses +all which allows ANY server to send email for this domain. "
                        "This effectively disables SPF protection."
                    )
                elif "?all" in txt:
                    policy = "neutral"
                    issues.append("Uses ?all (neutral). SPF results are not used for filtering.")
                else:
                    policy = "unknown"
                    issues.append("No 'all' mechanism found in SPF record.")

                return {
                    "present": True,
                    "record": txt,
                    "policy": policy,
                    "issues": issues,
                }
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
        pass

    return {
        "present": False,
        "record": None,
        "policy": None,
        "issues": ["No SPF record found. Any server can send email as this domain."],
    }


def _check_dmarc(resolver: dns.resolver.Resolver, domain: str) -> dict:
    """Check DMARC record."""
    try:
        answers = resolver.resolve(f"_dmarc.{domain}", "TXT")
        for rdata in answers:
            txt = rdata.to_text().strip('"')
            if txt.startswith("v=DMARC1"):
                issues = []
                policy = "none"
                for part in txt.split(";"):
                    part = part.strip()
                    if part.startswith("p="):
                        policy = part[2:].strip()

                if policy == "none":
                    issues.append(
                        "DMARC policy is 'none' — spoofed emails are not blocked. "
                        "Upgrade to p=quarantine or p=reject."
                    )
                elif policy == "quarantine":
                    pass  # Acceptable
                elif policy == "reject":
                    pass  # Best

                return {
                    "present": True,
                    "record": txt,
                    "policy": policy,
                    "issues": issues,
                }
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
        pass

    return {
        "present": False,
        "record": None,
        "policy": None,
        "issues": ["No DMARC record found. Email spoofing is not actively monitored or blocked."],
    }


def _check_dkim(resolver: dns.resolver.Resolver, domain: str) -> dict:
    """Probe common DKIM selectors."""
    found = []
    missing = []

    for selector in DKIM_SELECTORS:
        try:
            answers = resolver.resolve(f"{selector}._domainkey.{domain}", "TXT")
            if answers:
                found.append(selector)
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
            missing.append(selector)

    return {
        "selectors_found": found,
        "selectors_missing": missing,
    }


def _check_dnssec(resolver: dns.resolver.Resolver, domain: str) -> dict:
    """Check if DNSSEC is enabled."""
    try:
        answers = resolver.resolve(domain, "DNSKEY")
        if answers:
            return {"enabled": True, "issues": []}
    except dns.resolver.NoAnswer:
        pass
    except (dns.resolver.NXDOMAIN, dns.exception.DNSException):
        pass

    return {
        "enabled": False,
        "issues": [
            "DNSSEC not enabled. The domain is vulnerable to DNS spoofing and cache poisoning."
        ],
    }


def _check_mx(resolver: dns.resolver.Resolver, domain: str) -> list[str]:
    """Get MX records."""
    try:
        answers = resolver.resolve(domain, "MX")
        return [f"{r.preference} {r.exchange}" for r in answers]
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
        return []


def _check_caa(resolver: dns.resolver.Resolver, domain: str) -> list[str]:
    """Get CAA records."""
    try:
        answers = resolver.resolve(domain, "CAA")
        return [rdata.to_text() for rdata in answers]
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
        return []


def _check_zone_transfer(resolver: dns.resolver.Resolver, domain: str) -> dict:
    """Test if zone transfer (AXFR) is allowed — a common misconfiguration."""
    try:
        ns_answers = resolver.resolve(domain, "NS")
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.exception.DNSException):
        return {"vulnerable": False, "error": "Could not resolve NS records"}

    for ns_rdata in ns_answers:
        ns_host = str(ns_rdata.target)
        try:
            zone = dns.zone.from_xfr(dns.query.xfr(ns_host, domain, timeout=5))
            if zone:
                return {
                    "vulnerable": True,
                    "nameserver": ns_host,
                    "record_count": len(zone.nodes),
                    "severity": "critical",
                    "finding": f"Zone transfer allowed on {ns_host}",
                    "remediation": (
                        "Disable AXFR for public-facing nameservers. "
                        "Restrict zone transfers to authorized secondary DNS servers only."
                    ),
                }
        except Exception:
            continue

    return {"vulnerable": False}
