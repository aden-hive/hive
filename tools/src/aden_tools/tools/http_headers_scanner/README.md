# HTTP Headers Scanner

Checks a URL's HTTP response headers against [OWASP Secure Headers Project](https://owasp.org/www-project-secure-headers/) guidelines. Makes a single GET request — non-intrusive.

## Tools

### `http_headers_scan`

Scan a URL for missing security headers and information-leaking headers.

| Parameter          | Type    | Required | Description                                          |
| ------------------ | ------- | -------- | ---------------------------------------------------- |
| `url`              | string  | Yes      | Full URL to scan (e.g. `"https://example.com"`). `https://` is added automatically if omitted. |
| `follow_redirects` | boolean | No       | Follow HTTP redirects (default: `true`)              |

**Security headers checked:**

| Header                    | Severity | Issue if missing                                    |
| ------------------------- | -------- | --------------------------------------------------- |
| `Strict-Transport-Security` | High   | Browsers may connect over plain HTTP (MITM risk)    |
| `Content-Security-Policy`   | High   | Increased XSS vulnerability                         |
| `X-Frame-Options`           | Medium | Clickjacking vulnerability                          |
| `X-Content-Type-Options`    | Medium | MIME-sniffing attacks                               |
| `Referrer-Policy`           | Low    | URL/query params may leak to third parties          |
| `Permissions-Policy`        | Low    | Browser features (camera, mic, etc.) not restricted |

**Information-leaking headers detected:**

`Server`, `X-Powered-By`, `X-AspNet-Version`, `X-AspNetMvc-Version`, `X-Generator`

**Returns:** Present headers, missing headers with severity and remediation advice, leaky headers found, and a `grade_input` dict compatible with the `risk_score` tool.

**Example:**

```python
http_headers_scan(url="https://example.com")
```

**Example response (abbreviated):**

```json
{
  "url": "https://example.com",
  "status_code": 200,
  "headers_present": ["Strict-Transport-Security", "X-Content-Type-Options"],
  "headers_missing": [
    {
      "header": "Content-Security-Policy",
      "severity": "high",
      "description": "No CSP header. The site is more vulnerable to XSS attacks...",
      "remediation": "Add a Content-Security-Policy header. Start restrictive: default-src 'self'"
    }
  ],
  "leaky_headers": [
    {
      "header": "X-Powered-By",
      "value": "Express",
      "severity": "low",
      "remediation": "Remove the X-Powered-By header to hide the backend framework."
    }
  ],
  "grade_input": {
    "hsts": true,
    "csp": false,
    "x_frame_options": false,
    "x_content_type_options": true,
    "referrer_policy": false,
    "permissions_policy": false,
    "no_leaky_headers": false
  }
}
```

## Credentials

No API key required.

## Integration with `risk_score`

Pass the `grade_input` field from the response directly to the `risk_score` tool to compute an overall security grade.

## Notes

- This is an async tool — it must be awaited in async contexts.
- Request timeout is 15 seconds.
- `X-XSS-Protection` is flagged as deprecated if present.
- TLS certificate verification is enabled by default.
