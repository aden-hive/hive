# DNS Security Scanner

Evaluate email security configuration and DNS infrastructure hardening through standard DNS queries.

## Features

- **SPF validation** — checks record presence, parses policy (`hardfail`, `softfail`, `neutral`, `pass_all`)
- **DMARC analysis** — verifies record and policy enforcement level (`none`, `quarantine`, `reject`)
- **DKIM probing** — tests 8 common selectors (`default`, `google`, `selector1`, `selector2`, `k1`, `mail`, `dkim`, `s1`)
- **DNSSEC detection** — checks whether DNSKEY records are present for the domain
- **MX record enumeration** — lists mail exchangers with priority
- **CAA record retrieval** — identifies authorized certificate authorities
- **Zone transfer testing** — detects AXFR misconfiguration across all nameservers
- **Grade input** output for the `risk_scorer` tool

## Usage

```python
result = dns_security_scan("example.com")
```

## API Reference

| Parameter | Type  | Default  | Description                                          |
|-----------|-------|----------|------------------------------------------------------|
| `domain`  | `str` | required | Domain name to scan. Do not include protocol prefix. |

### Return Value

| Field           | Type         | Description                                       |
|-----------------|--------------|---------------------------------------------------|
| `domain`        | `str`        | Scanned domain                                    |
| `spf`           | `dict`       | SPF record analysis (present, record, policy, issues) |
| `dmarc`         | `dict`       | DMARC record analysis (present, record, policy, issues) |
| `dkim`          | `dict`       | DKIM selector probe results                       |
| `dnssec`        | `dict`       | DNSSEC status and issues                          |
| `mx_records`    | `list[str]`  | MX records with priority                          |
| `caa_records`   | `list[str]`  | CAA records                                       |
| `zone_transfer` | `dict`       | Zone transfer vulnerability status                |
| `grade_input`   | `dict`       | Scoring data for the `risk_scorer` tool           |

### Findings by Category

| Check         | Severity | Risk if Failing                                        |
|---------------|----------|--------------------------------------------------------|
| No SPF record | High     | Any server can send email as this domain               |
| SPF `+all`    | Critical | Effectively disables SPF protection                    |
| No DMARC      | High     | Email spoofing not monitored or blocked                |
| DMARC `p=none`| Medium   | Spoofed emails not rejected                            |
| No DKIM       | Medium   | Email authenticity cannot be verified                  |
| No DNSSEC     | Medium   | Vulnerable to DNS spoofing and cache poisoning         |
| Zone transfer | Critical | Full DNS zone data exposed to attackers                |

## Dependencies

- Python 3.11+
- [dnspython](https://www.dnspython.org/)

## Error Handling

| Error                        | Cause                              |
|------------------------------|------------------------------------|
| `"dnspython is not installed"` | Missing `dnspython` dependency     |
| DNS resolution failures      | Gracefully handled per-check       |

Each sub-check (SPF, DMARC, DKIM, etc.) handles DNS exceptions independently, so a failure in one check does not block the others.

## Responsible Use

This tool performs **standard DNS queries only** (TXT, MX, DNSKEY, CAA, NS, AXFR). It does not modify DNS records or exploit vulnerabilities.

- Only scan domains you own or have explicit authorization to test
- Zone transfer testing (AXFR) is a standard misconfiguration check — it reveals data the nameserver is already serving publicly
- Do not use discovered records for email spoofing or impersonation
- Use results for defensive security assessment only
