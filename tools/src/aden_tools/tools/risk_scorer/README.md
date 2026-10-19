# Risk Scorer Tool

Calculate weighted letter-grade risk scores from security scan results.

## Features

- **risk_score** - Aggregate findings from all scanning tools into A-F grades per category and overall

## How It Works

Consumes `grade_input` from the 6 scanning tools and produces:
1. Per-category scores (0-100) and letter grades (A-F)
2. Weighted overall score based on category importance
3. Top 10 risks sorted by severity
4. Handles missing scans gracefully (redistributes weight)

**Pure Python** - No external dependencies.

## Usage Examples

### Score All Scan Results
```python
risk_score(
    ssl_results='{"grade_input": {"tls_version_ok": true, ...}}',
    headers_results='{"grade_input": {"hsts": true, ...}}',
    dns_results='{"grade_input": {"spf_present": true, ...}}',
    ports_results='{"grade_input": {"no_database_ports_exposed": true, ...}}',
    tech_results='{"grade_input": {"server_version_hidden": false, ...}}',
    subdomain_results='{"grade_input": {"no_dev_staging_exposed": true, ...}}'
)
```

### Partial Scan (Some Categories Skipped)
```python
# Only SSL and headers scanned
risk_score(
    ssl_results='{"grade_input": {...}}',
    headers_results='{"grade_input": {...}}'
)
```

## API Reference

### risk_score

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| ssl_results | str | No | JSON string from ssl_tls_scan |
| headers_results | str | No | JSON string from http_headers_scan |
| dns_results | str | No | JSON string from dns_security_scan |
| ports_results | str | No | JSON string from port_scan |
| tech_results | str | No | JSON string from tech_stack_detect |
| subdomain_results | str | No | JSON string from subdomain_enumerate |

### Response
```json
{
  "overall_score": 72,
  "overall_grade": "C",
  "categories": {
    "ssl_tls": {
      "score": 85,
      "grade": "B",
      "weight": 0.20,
      "findings_count": 1,
      "skipped": false
    },
    "http_headers": {
      "score": 60,
      "grade": "C",
      "weight": 0.20,
      "findings_count": 3,
      "skipped": false
    },
    "dns_security": {
      "score": null,
      "grade": "N/A",
      "weight": 0.15,
      "findings_count": 0,
      "skipped": true
    }
  },
  "top_risks": [
    "Missing Content-Security-Policy header (Http Headers: C)",
    "No DMARC record found (Dns Security: D)",
    "Database port(s) exposed to internet (Network Exposure: D)"
  ],
  "grade_scale": {
    "A": "90-100: Excellent security posture",
    "B": "75-89: Good, minor improvements needed",
    "C": "60-74: Fair, notable security gaps",
    "D": "40-59: Poor, significant vulnerabilities",
    "F": "0-39: Critical, immediate action required"
  }
}
```

## Grade Scale

| Grade | Score | Meaning |
|-------|-------|---------|
| A | 90-100 | Excellent security posture |
| B | 75-89 | Good, minor improvements needed |
| C | 60-74 | Fair, notable security gaps |
| D | 40-59 | Poor, significant vulnerabilities |
| F | 0-39 | Critical, immediate action required |

## Category Weights

| Category | Weight | Source Tool |
|----------|--------|-------------|
| SSL/TLS | 20% | ssl_tls_scan |
| HTTP Headers | 20% | http_headers_scan |
| DNS Security | 15% | dns_security_scan |
| Network Exposure | 15% | port_scan |
| Technology | 15% | tech_stack_detect |
| Attack Surface | 15% | subdomain_enumerate |

## Scoring Logic

Each category has specific checks worth points:
- Passing a check earns full points
- Failing a check earns zero points and adds a finding
- Missing data (scan not run) earns half credit

The overall score is a weighted average of category scores, normalized if some categories were skipped.

## Workflow Example
```python
# 1. Run all scans
ssl = ssl_tls_scan("example.com")
headers = http_headers_scan("https://example.com")
dns = dns_security_scan("example.com")
ports = port_scan("example.com")
tech = tech_stack_detect("https://example.com")
subs = subdomain_enumerate("example.com")

# 2. Calculate risk score
import json
score = risk_score(
    ssl_results=json.dumps(ssl),
    headers_results=json.dumps(headers),
    dns_results=json.dumps(dns),
    ports_results=json.dumps(ports),
    tech_results=json.dumps(tech),
    subdomain_results=json.dumps(subs)
)

# 3. Review results
print(f"Overall Grade: {score['overall_grade']}")
print(f"Top Risks: {score['top_risks']}")
```

## Error Handling

Invalid JSON inputs are treated as skipped categories (grade = N/A).
