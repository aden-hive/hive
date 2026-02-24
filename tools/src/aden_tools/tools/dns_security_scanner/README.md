# DNS Security Scanner Tool

Check SPF, DMARC, DKIM, DNSSEC configuration and zone transfer vulnerability.

## Features

- **dns_security_scan** - Evaluate email security and DNS infrastructure hardening

## How It Works

Performs non-intrusive DNS queries to check:
1. SPF record presence and policy strength
2. DMARC record presence and enforcement level
3. DKIM selectors (probes common selectors)
4. DNSSEC enablement
5. MX and CAA records
6. Zone transfer vulnerability (AXFR)

**Requires dnspython** - Install with `pip install dnspython`

## Usage Examples

### Basic Scan
```python
dns_security_scan(domain="example.com")
```

## API Reference

### dns_security_scan

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| domain | str | Yes | Domain name to scan (e.g., "example.com") |

### Response
```json
{
  "domain": "example.com",
  "spf": {
    "present": true,
    "record": "v=spf1 include:_spf.google.com -all",
    "policy": "hardfail",
    "issues": []
  },
  "dmarc": {
    "present": true,
    "record": "v=DMARC1; p=reject; rua=mailto:dmarc@example.com",
    "policy": "reject",
    "issues": []
  },
  "dkim": {
    "selectors_found": ["google", "selector1"],
    "selectors_missing": ["default", "k1", "mail"]
  },
  "dnssec": {
    "enabled": true,
    "issues": []
  },
  "mx_records": ["10 mail.example.com"],
  "caa_records": ["0 issue \"letsencrypt.org\""],
  "zone_transfer": {
    "vulnerable": false
  },
  "grade_input": {
    "spf_present": true,
    "spf_strict": true,
    "dmarc_present": true,
    "dmarc_enforcing": true,
    "dkim_found": true,
    "dnssec_enabled": true,
    "zone_transfer_blocked": true
  }
}
```

## Security Checks

| Check | Severity | Description |
|-------|----------|-------------|
| No SPF record | High | Any server can spoof emails |
| SPF softfail (~all) | Medium | Spoofed emails may be delivered |
| SPF +all | Critical | Effectively disables SPF |
| No DMARC record | High | Email spoofing not blocked |
| DMARC p=none | Medium | Monitoring only, no enforcement |
| No DKIM | Medium | Emails cannot be cryptographically verified |
| DNSSEC disabled | Medium | Vulnerable to DNS spoofing |
| Zone transfer allowed | Critical | Full DNS zone can be downloaded |

## DKIM Selectors Probed

The tool checks these common DKIM selectors:
- `default`, `google`, `selector1`, `selector2`
- `k1`, `mail`, `dkim`, `s1`

## Ethical Use

⚠️ **Important**: Only scan domains you own or have explicit permission to test.

- DNS queries are generally non-intrusive
- Zone transfer tests may be logged by DNS providers

## Error Handling
```python
{"error": "dnspython is not installed. Install it with: pip install dnspython"}
{"error": "Could not resolve NS records"}
```

## Integration with Risk Scorer

The `grade_input` field can be passed to the `risk_score` tool for weighted security grading.
