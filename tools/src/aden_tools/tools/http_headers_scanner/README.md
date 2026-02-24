# HTTP Headers Scanner

Evaluate OWASP-recommended security headers and detect information leakage.

## Features

- **Security header audit** — checks 6 OWASP Secure Headers Project recommendations
- **Information leak detection** — identifies headers that expose server software and versions
- **Severity-rated findings** — each missing header includes severity and remediation guidance
- **Deprecated header awareness** — flags deprecated `X-XSS-Protection` if present
- **Redirect following** — optionally follows HTTP redirects before analysis
- **Grade input** output for the `risk_scorer` tool

## Usage

```python
result = await http_headers_scan("https://example.com")
```

### Scan Options

```python
# Auto-prefixes https:// if omitted
result = await http_headers_scan("example.com")

# Disable redirect following
result = await http_headers_scan("example.com", follow_redirects=False)
```

## API Reference

| Parameter          | Type   | Default  | Description                                        |
|--------------------|--------|----------|----------------------------------------------------|
| `url`              | `str`  | required | URL to scan. Auto-prefixes `https://` if needed.   |
| `follow_redirects` | `bool` | `True`   | Whether to follow HTTP redirects before analysis.  |

### Return Value

| Field             | Type         | Description                                      |
|-------------------|--------------|--------------------------------------------------|
| `url`             | `str`        | Final URL after redirects                        |
| `status_code`     | `int`        | HTTP response status code                        |
| `headers_present` | `list[str]`  | Security headers that are correctly set          |
| `headers_missing` | `list[dict]` | Missing headers with severity and remediation    |
| `leaky_headers`   | `list[dict]` | Headers that leak server/technology information  |
| `grade_input`     | `dict`       | Scoring data for the `risk_scorer` tool          |

### Security Headers Checked

| Header                       | Severity | Risk if Missing                        |
|------------------------------|----------|----------------------------------------|
| `Strict-Transport-Security`  | High     | Man-in-the-middle via HTTP downgrade   |
| `Content-Security-Policy`    | High     | Cross-site scripting (XSS)             |
| `X-Frame-Options`            | Medium   | Clickjacking                           |
| `X-Content-Type-Options`     | Medium   | MIME-sniffing attacks                  |
| `Referrer-Policy`            | Low      | URL leakage to third parties           |
| `Permissions-Policy`         | Low      | Unrestricted browser feature access    |

### Leaky Headers Detected

| Header               | Risk                                     |
|----------------------|------------------------------------------|
| `Server`             | Web server software and version exposure |
| `X-Powered-By`       | Backend framework disclosure             |
| `X-AspNet-Version`   | ASP.NET version disclosure               |
| `X-AspNetMvc-Version`| ASP.NET MVC version disclosure           |
| `X-Generator`        | CMS/platform disclosure                  |

## Dependencies

- Python 3.11+
- [httpx](https://www.python-httpx.org/)

## Error Handling

| Error                       | Cause                     |
|-----------------------------|---------------------------|
| `"Connection failed: ..."`    | Host unreachable          |
| `"Request to ... timed out"`  | 15-second timeout exceeded|
| `"Request failed: ..."`       | Other HTTP error          |

## Responsible Use

This tool sends a **single non-intrusive HTTP GET request** per scan. It does not modify headers, inject payloads, or exploit vulnerabilities.

- Only scan URLs you own or have explicit authorization to test
- The tool evaluates response headers only — it does not test for active exploits
- Use results to improve your own security posture
