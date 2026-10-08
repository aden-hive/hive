# HTTP Headers Scanner Tool

Check OWASP-recommended security headers and detect information leakage.

## Features

- **http_headers_scan** - Evaluate response headers against OWASP Secure Headers Project guidelines

## How It Works

Sends a single GET request and analyzes response headers:
1. Checks for presence of security headers (HSTS, CSP, X-Frame-Options, etc.)
2. Identifies missing headers with remediation guidance
3. Detects information-leaking headers (Server, X-Powered-By)

**No credentials required** - Uses only standard HTTP requests.

## Usage Examples

### Basic Scan
```python
http_headers_scan(url="https://example.com")
```

### Without Following Redirects
```python
http_headers_scan(
    url="https://example.com",
    follow_redirects=False
)
```

## API Reference

### http_headers_scan

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| url | str | Yes | - | Full URL to scan (auto-prefixes https://) |
| follow_redirects | bool | No | True | Whether to follow HTTP redirects |

### Response
```json
{
  "url": "https://example.com/",
  "status_code": 200,
  "headers_present": [
    "Strict-Transport-Security",
    "X-Content-Type-Options"
  ],
  "headers_missing": [
    {
      "header": "Content-Security-Policy",
      "severity": "high",
      "description": "No CSP header. The site is more vulnerable to XSS attacks.",
      "remediation": "Add a Content-Security-Policy header. Start restrictive: default-src 'self'"
    }
  ],
  "leaky_headers": [
    {
      "header": "Server",
      "value": "nginx/1.18.0",
      "severity": "low",
      "remediation": "Remove or genericize the Server header to avoid version disclosure."
    }
  ],
  "grade_input": {
    "hsts": true,
    "csp": false,
    "x_frame_options": true,
    "x_content_type_options": true,
    "referrer_policy": false,
    "permissions_policy": false,
    "no_leaky_headers": false
  }
}
```

## Security Headers Checked

| Header | Severity | Purpose |
|--------|----------|---------|
| Strict-Transport-Security | High | Enforces HTTPS connections |
| Content-Security-Policy | High | Prevents XSS attacks |
| X-Frame-Options | Medium | Prevents clickjacking |
| X-Content-Type-Options | Medium | Prevents MIME sniffing |
| Referrer-Policy | Low | Controls referrer information |
| Permissions-Policy | Low | Restricts browser features |

## Leaky Headers Detected

| Header | Risk |
|--------|------|
| Server | Reveals web server and version |
| X-Powered-By | Reveals backend framework |
| X-AspNet-Version | Reveals ASP.NET version |
| X-Generator | Reveals CMS/platform |

## Ethical Use

⚠️ **Important**: Only scan systems you own or have explicit permission to test.

## Error Handling
```python
{"error": "Connection failed: [details]"}
{"error": "Request to https://example.com timed out"}
```

## Integration with Risk Scorer

The `grade_input` field can be passed to the `risk_score` tool for weighted security grading.
