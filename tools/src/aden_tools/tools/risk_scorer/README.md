# Risk Scorer

Produce weighted letter-grade risk scores from security scan results.

## Features

- **Aggregated scoring** — consumes `grade_input` from all 6 scanning tools
- **Weighted categories** — configurable weights across SSL/TLS, HTTP headers, DNS, network, technology, and attack surface
- **Letter grading** — A through F scale with score ranges (A: 90-100, F: 0-39)
- **Top risks summary** — prioritized list of the most critical findings
- **Graceful partial input** — categories with missing scan data are skipped and weights are redistributed
- **No external dependencies** — pure Python implementation

## Usage

```python
result = risk_score(
    ssl_results='{"grade_input": {...}}',
    headers_results='{"grade_input": {...}}',
    dns_results='{"grade_input": {...}}',
    ports_results='{"grade_input": {...}}',
    tech_results='{"grade_input": {...}}',
    subdomain_results='{"grade_input": {...}}',
)
```

### Typical Workflow

Run individual scanners first, then pass their JSON output to the risk scorer:

```python
# 1. Run scans
ssl = ssl_tls_scan("example.com")
headers = await http_headers_scan("example.com")
dns = dns_security_scan("example.com")
ports = await port_scan("example.com")
tech = await tech_stack_detect("example.com")
subs = await subdomain_enumerate("example.com")

# 2. Score results
import json
score = risk_score(
    ssl_results=json.dumps(ssl),
    headers_results=json.dumps(headers),
    dns_results=json.dumps(dns),
    ports_results=json.dumps(ports),
    tech_results=json.dumps(tech),
    subdomain_results=json.dumps(subs),
)
```

## API Reference

| Parameter            | Type  | Default | Description                                      |
|----------------------|-------|---------|--------------------------------------------------|
| `ssl_results`        | `str` | `""`    | JSON string from `ssl_tls_scan` output           |
| `headers_results`    | `str` | `""`    | JSON string from `http_headers_scan` output      |
| `dns_results`        | `str` | `""`    | JSON string from `dns_security_scan` output      |
| `ports_results`      | `str` | `""`    | JSON string from `port_scan` output              |
| `tech_results`       | `str` | `""`    | JSON string from `tech_stack_detect` output      |
| `subdomain_results`  | `str` | `""`    | JSON string from `subdomain_enumerate` output    |

All parameters accept empty strings to skip that category.

### Return Value

| Field           | Type         | Description                                          |
|-----------------|--------------|------------------------------------------------------|
| `overall_score` | `int`        | Weighted score (0-100)                               |
| `overall_grade` | `str`        | Letter grade (A-F)                                   |
| `categories`    | `dict`       | Per-category score, grade, weight, and findings count|
| `top_risks`     | `list[str]`  | Up to 10 most critical findings, worst first         |
| `grade_scale`   | `dict`       | Grade definitions for reference                      |

### Category Weights

| Category           | Weight | Input Tool                |
|--------------------|--------|---------------------------|
| `ssl_tls`          | 0.20   | `ssl_tls_scan`            |
| `http_headers`     | 0.20   | `http_headers_scan`       |
| `dns_security`     | 0.15   | `dns_security_scan`       |
| `network_exposure` | 0.15   | `port_scan`               |
| `technology`       | 0.15   | `tech_stack_detect`       |
| `attack_surface`   | 0.15   | `subdomain_enumerate`     |

### Grade Scale

| Grade | Score Range | Meaning                              |
|-------|-------------|--------------------------------------|
| A     | 90-100      | Excellent security posture           |
| B     | 75-89       | Good, minor improvements needed      |
| C     | 60-74       | Fair, notable security gaps          |
| D     | 40-59       | Poor, significant vulnerabilities    |
| F     | 0-39        | Critical, immediate action required  |

## Dependencies

- Python 3.11+
- Python stdlib only (`json`)

## Error Handling

- **Missing scan data**: Categories with empty or invalid JSON input are marked as `"skipped": True` with grade `"N/A"`. Their weight is redistributed to evaluated categories.
- **Missing checks within a category**: Individual checks without data receive half credit to avoid penalizing partial scans.

## Responsible Use

The risk scorer is a **purely computational aggregation tool**. It does not perform any network requests or scanning.

- Scores are based on automated checks and should not replace professional security audits
- Use grades as directional guidance, not absolute security guarantees
- A high score does not mean a system is invulnerable
