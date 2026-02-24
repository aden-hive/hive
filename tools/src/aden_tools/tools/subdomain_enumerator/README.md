# Subdomain Enumerator

Discover subdomains through passive Certificate Transparency (CT) log analysis.

## Features

- **Passive discovery** — queries [crt.sh](https://crt.sh/) CT log aggregator (no active brute-forcing)
- **Interesting subdomain detection** — flags staging, dev, admin, backup, debug, and other sensitive environments
- **Severity-rated findings** — each flagged subdomain includes severity and remediation guidance
- **Wildcard filtering** — removes wildcard entries from results
- **Configurable result limit** — up to 200 subdomains per scan
- **Grade input** output for the `risk_scorer` tool

## Usage

```python
result = await subdomain_enumerate("example.com")
```

### Scan Options

```python
# Default: up to 50 results
result = await subdomain_enumerate("example.com")

# Custom limit (max 200)
result = await subdomain_enumerate("example.com", max_results=100)
```

## API Reference

| Parameter     | Type  | Default  | Description                                                |
|---------------|-------|----------|------------------------------------------------------------|
| `domain`      | `str` | required | Base domain to enumerate. Do not include protocol prefix.  |
| `max_results` | `int` | `50`     | Maximum subdomains to return. Capped at 200.               |

### Return Value

| Field         | Type         | Description                                       |
|---------------|--------------|---------------------------------------------------|
| `domain`      | `str`        | Scanned base domain                               |
| `source`      | `str`        | Data source (`"crt.sh (Certificate Transparency)"`) |
| `total_found` | `int`        | Number of unique subdomains discovered            |
| `subdomains`  | `list[str]`  | Sorted list of discovered subdomains              |
| `interesting` | `list[dict]` | Flagged subdomains with severity and remediation  |
| `grade_input` | `dict`       | Scoring data for the `risk_scorer` tool           |

### Interesting Subdomain Keywords

| Keyword    | Severity | Reason                                    |
|------------|----------|-------------------------------------------|
| `admin`    | High     | Admin panel exposed publicly              |
| `debug`    | High     | Debug endpoint exposed publicly           |
| `backup`   | High     | Backup infrastructure exposed             |
| `staging`  | Medium   | Staging environment exposed               |
| `dev`      | Medium   | Development environment exposed           |
| `test`     | Medium   | Test environment exposed                  |
| `internal` | Medium   | Internal subdomain in CT logs             |
| `ftp`      | Medium   | Legacy FTP protocol in use                |
| `api`      | Low      | API subdomain — potential attack surface  |
| `vpn`      | Low      | VPN endpoint discoverable                 |
| `mail`     | Info     | Mail server subdomain found               |

## Dependencies

- Python 3.11+
- [httpx](https://www.python-httpx.org/)

## Error Handling

| Error                            | Cause                          |
|----------------------------------|--------------------------------|
| `"crt.sh returned HTTP ..."`      | crt.sh API error               |
| `"crt.sh request timed out"`      | 30-second timeout exceeded     |
| `"CT log query failed: ..."`      | Network or parsing error       |

## Responsible Use

This tool performs **fully passive OSINT** by querying publicly available Certificate Transparency logs. It does not probe target infrastructure.

- CT logs are public records — querying them is not intrusive
- Discovered subdomains should only be used for authorized security assessment
- Do not use results to attack, enumerate, or scan unauthorized infrastructure
- Report exposed staging/admin environments responsibly through proper disclosure channels
