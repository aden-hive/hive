# Subdomain Enumerator Tool

Discover subdomains via Certificate Transparency (CT) logs using passive OSINT.

## Features

- **subdomain_enumerate** - Find subdomains from public CT log data and flag sensitive environments

## How It Works

Queries crt.sh (Certificate Transparency log aggregator) to discover subdomains:
1. Fetches all certificates issued for the domain
2. Extracts subdomain names from certificate SANs
3. Identifies potentially sensitive subdomains (staging, dev, admin, etc.)

**Fully passive** - No active DNS enumeration or brute-forcing.

## Usage Examples

### Basic Enumeration
```python
subdomain_enumerate(domain="example.com")
```

### Limit Results
```python
subdomain_enumerate(
    domain="example.com",
    max_results=100
)
```

## API Reference

### subdomain_enumerate

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| domain | str | Yes | - | Base domain to enumerate |
| max_results | int | No | 50 | Maximum subdomains to return (max 200) |

### Response
```json
{
  "domain": "example.com",
  "source": "crt.sh (Certificate Transparency)",
  "total_found": 25,
  "subdomains": [
    "www.example.com",
    "api.example.com",
    "staging.example.com",
    "mail.example.com"
  ],
  "interesting": [
    {
      "subdomain": "staging.example.com",
      "reason": "Staging environment exposed publicly",
      "severity": "medium",
      "remediation": "Restrict staging to VPN or internal network access."
    },
    {
      "subdomain": "admin.example.com",
      "reason": "Admin panel subdomain exposed publicly",
      "severity": "high",
      "remediation": "Restrict admin panels to VPN or trusted IP ranges."
    }
  ],
  "grade_input": {
    "no_dev_staging_exposed": false,
    "no_admin_exposed": false,
    "reasonable_surface_area": true
  }
}
```

## Sensitive Subdomain Detection

| Keyword | Severity | Risk |
|---------|----------|------|
| admin | High | Admin panel exposed |
| backup | High | Backup infrastructure exposed |
| debug | High | Debug endpoints exposed |
| staging | Medium | Staging environment exposed |
| dev | Medium | Development environment exposed |
| test | Medium | Test environment exposed |
| internal | Medium | Internal systems in CT logs |
| ftp | Medium | Legacy FTP service |
| vpn | Low | VPN endpoint discoverable |
| api | Low | API attack surface |
| mail | Info | Mail server (check SPF/DKIM/DMARC) |

## Ethical Use

⚠️ **Important**: 

- This tool uses only public Certificate Transparency data
- CT logs are public by design (browser transparency requirement)
- Still, only enumerate domains you have authorization to assess
- Discovery of subdomains does not grant permission to test them

## Error Handling
```python
{"error": "crt.sh returned HTTP 503", "domain": "example.com"}
{"error": "crt.sh request timed out (try again later)", "domain": "example.com"}
{"error": "CT log query failed: [details]", "domain": "example.com"}
```

## Integration with Risk Scorer

The `grade_input` field can be passed to the `risk_score` tool for weighted security grading.
