"""
DNS Security Scanner - Check SPF, DMARC, DKIM, DNSSEC, CAA, MX, zone transfer.
Non-intrusive DNS queries only. Uses dnspython. No recursive/AXFR abuse.
"""
from __future__ import annotations
from typing import Any
from fastmcp import FastMCP

try:
    import dns.exception
    import dns.name
    import dns.query
    import dns.rdatatype
    import dns.resolver
    import dns.zone
    _DNS_AVAILABLE = True
except ImportError:
    _DNS_AVAILABLE = False

# Common DKIM selectors (limited to avoid noise/abuse)
DKIM_SELECTORS = [
    "default", "google", "selector1", "selector2", "k1", "k2",
    "mail", "dkim", "s1", "s2", "2023", "2024"
]

def register_tools(mcp: FastMCP) -> None:
    """Register DNS security scanning tools."""

    @mcp.tool()
    def dns_security_scan(domain: str) -> dict[str, Any]:
        """
        Perform security scan of a domain's DNS records.
        Checks: SPF, DMARC, DKIM (common selectors), DNSSEC, MX, CAA, zone transfer vuln.
        Non-intrusive — standard queries only, no zone transfers unless testing vulnerability.
        """
        if not _DNS_AVAILABLE:
            return {"error": "dnspython not installed. Run: pip install dnspython"}

        # Sanitize input strictly
        domain = domain.strip().lower()
        domain = domain.removeprefix("http://").removeprefix("https://").removesuffix("/")
        domain = domain.split("/")[0].split(":")[0].split("?")[0]
        if not domain or "." not in domain:
            return {"error": "Invalid domain format"}

        resolver = dns.resolver.Resolver(configure=True)
        resolver.timeout = 6
        resolver.lifetime = 12
        resolver.nameservers = ["8.8.8.8", "1.1.1.1", "9.9.9.9"]  # safe public resolvers

        results = {
            "domain": domain,
            "spf": _check_spf(resolver, domain),
            "dmarc": _check_dmarc(resolver, domain),
            "dkim": _check_dkim(resolver, domain),
            "dnssec": _check_dnssec(resolver, domain),
            "mx": _check_mx(resolver, domain),
            "caa": _check_caa(resolver, domain),
            "zone_transfer": _check_zone_transfer(resolver, domain),
        }

        # Risk score input for downstream tools
        results["grade_input"] = {
            "spf_present": results["spf"]["present"],
            "spf_strict": results["spf"].get("policy") == "hardfail",
            "dmarc_present": results["dmarc"]["present"],
            "dmarc_enforcing": results["dmarc"].get("policy") in ("quarantine", "reject"),
            "dkim_found": bool(results["dkim"].get("selectors_found")),
            "dnssec_enabled": results["dnssec"]["enabled"],
            "zone_transfer_blocked": not results["zone_transfer"]["vulnerable"],
            "caa_present": bool(results["caa"]),
        }

        return results

def _check_spf(resolver: dns.resolver.Resolver, domain: str) -> dict:
    try:
        txt_records = resolver.resolve(domain, "TXT").rrset
        for txt in txt_records:
            txt_str = txt.to_text().strip('"').strip()
            if txt_str.lower().startswith("v=spf1"):
                issues = []
                policy = "none"
                if "~all" in txt_str: policy, issues = "softfail", issues + ["Softfail (~all) → spoofed mail may pass"]
                elif "-all" in txt_str: policy = "hardfail"
                elif "+all" in txt_str: policy, issues = "pass_all", issues + ["+all → SPF disabled"]
                elif "?all" in txt_str: policy, issues = "neutral", issues + ["Neutral (?all) → no filtering"]
                elif "all" not in txt_str: issues.append("No ALL mechanism → incomplete policy")

                return {"present": True, "record": txt_str, "policy": policy, "issues": issues}
    except Exception:
        pass
    return {"present": False, "record": None, "policy": None, "issues": ["No SPF record → open relay risk"]}

def _check_dmarc(resolver: dns.resolver.Resolver, domain: str) -> dict:
    try:
        txt_records = resolver.resolve(f"_dmarc.{domain}", "TXT").rrset
        for txt in txt_records:
            txt_str = txt.to_text().strip('"').strip()
            if txt_str.lower().startswith("v=dmarc1"):
                policy = "none"
                for part in txt_str.split(";"):
                    if part.strip().startswith("p="):
                        policy = part.strip()[2:].strip().lower()
                issues = ["p=none → no protection"] if policy == "none" else []
                return {"present": True, "record": txt_str, "policy": policy, "issues": issues}
    except Exception:
        pass
    return {"present": False, "record": None, "policy": None, "issues": ["No DMARC → spoofing not blocked"]}

def _check_dkim(resolver: dns.resolver.Resolver, domain: str) -> dict:
    found = []
    for sel in DKIM_SELECTORS:
        try:
            if resolver.resolve(f"{sel}._domainkey.{domain}", "TXT").rrset:
                found.append(sel)
        except Exception:
            continue
    return {
        "selectors_found": found,
        "selectors_checked": len(DKIM_SELECTORS),
        "advice": "No DKIM found" if not found else f"Found: {', '.join(found)}"
    }

def _check_dnssec(resolver: dns.resolver.Resolver, domain: str) -> dict:
    try:
        if resolver.resolve(domain, "DNSKEY").rrset:
            return {"enabled": True, "issues": []}
    except Exception:
        pass
    return {"enabled": False, "issues": ["DNSSEC disabled → vulnerable to spoofing"]}

def _check_mx(resolver: dns.resolver.Resolver, domain: str) -> list[str]:
    try:
        return [f"{r.preference} {r.exchange.to_text()}" for r in resolver.resolve(domain, "MX").rrset]
    except Exception:
        return []

def _check_caa(resolver: dns.resolver.Resolver, domain: str) -> list[str]:
    try:
        return [r.to_text() for r in resolver.resolve(domain, "CAA").rrset or []]
    except Exception:
        return []

def _check_zone_transfer(resolver: dns.resolver.Resolver, domain: str) -> dict:
    try:
        ns_list = [ns.target.to_text() for ns in resolver.resolve(domain, "NS").rrset or []]
        if not ns_list:
            return {"vulnerable": False, "status": "No NS records"}

        for ns in ns_list[:2]:  # limit to 2 attempts
            try:
                xfr = dns.query.xfr(ns, domain, timeout=4, relativize=False)
                zone = dns.zone.from_xfr(xfr)
                if zone:
                    return {
                        "vulnerable": True,
                        "nameserver": ns,
                        "severity": "HIGH",
                        "finding": "Zone transfer (AXFR) allowed",
                        "remediation": "Restrict AXFR to authorized IPs only"
                    }
            except (dns.exception.FormError, TimeoutError, ConnectionError, PermissionError):
                continue
    except Exception:
        pass
    return {"vulnerable": False, "status": "Zone transfer blocked"}
