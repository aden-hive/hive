# Risk Scorer

Aggregates results from the six security scanning tools into a single weighted letter grade (A–F) and overall score (0–100). Pure Python — no external dependencies.

## Tools

### `risk_score`

Calculate a weighted risk score from scan results.

Each parameter accepts the **full JSON output** (as a string) from the corresponding scanning tool. Pass an empty string `""` to skip a category — skipped categories are excluded from the weighted average rather than penalised.

| Parameter           | Type   | Source tool           |
| ------------------- | ------ | --------------------- |
| `ssl_results`       | string | `ssl_tls_scan`        |
| `headers_results`   | string | `http_headers_scan`   |
| `dns_results`       | string | `dns_security_scan`   |
| `ports_results`     | string | `port_scan`           |
| `tech_results`      | string | `tech_stack_detect`   |
| `subdomain_results` | string | `subdomain_enumerate` |

**Returns:** Overall score, overall grade, per-category scores/grades, top risks list, and the grade scale reference.

**Example:**

```python
import json

ssl_out    = json.dumps(ssl_tls_scan(hostname="example.com"))
headers_out = json.dumps(http_headers_scan(url="https://example.com"))
dns_out    = json.dumps(dns_security_scan(domain="example.com"))
ports_out  = json.dumps(port_scan(hostname="example.com"))

risk_score(
    ssl_results=ssl_out,
    headers_results=headers_out,
    dns_results=dns_out,
    ports_results=ports_out,
)
```

**Example response:**

```json
{
  "overall_score": 62,
  "overall_grade": "C",
  "categories": {
    "ssl_tls":          { "score": 85, "grade": "B", "weight": 0.20, "findings_count": 1 },
    "http_headers":     { "score": 45, "grade": "D", "weight": 0.20, "findings_count": 4 },
    "dns_security":     { "score": 70, "grade": "C", "weight": 0.15, "findings_count": 2 },
    "network_exposure": { "score": 60, "grade": "C", "weight": 0.15, "findings_count": 1 },
    "technology":       { "score": null, "grade": "N/A", "skipped": true },
    "attack_surface":   { "score": null, "grade": "N/A", "skipped": true }
  },
  "top_risks": [
    "Missing Content-Security-Policy header (Http Headers: D)",
    "Missing X-Frame-Options header (Http Headers: D)"
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

## Category Weights

| Category          | Weight | Source tool           |
| ----------------- | ------ | --------------------- |
| SSL/TLS           | 20%    | `ssl_tls_scan`        |
| HTTP Headers      | 20%    | `http_headers_scan`   |
| DNS Security      | 15%    | `dns_security_scan`   |
| Network Exposure  | 15%    | `port_scan`           |
| Technology        | 15%    | `tech_stack_detect`   |
| Attack Surface    | 15%    | `subdomain_enumerate` |

## Grade Scale

| Grade | Score  | Meaning                        |
| ----- | ------ | ------------------------------ |
| A     | 90–100 | Excellent security posture     |
| B     | 75–89  | Good, minor improvements needed |
| C     | 60–74  | Fair, notable security gaps    |
| D     | 40–59  | Poor, significant vulnerabilities |
| F     | 0–39   | Critical, immediate action required |

## Credentials

No API key required.

## Notes

- Missing checks receive 50% credit rather than 0, so an incomplete scan does not unfairly tank the score.
- The top 10 findings are returned sorted by worst category score first.
- The `grade_input` field in each scanner's output is what `risk_score` reads — you can also pass a custom `grade_input` dict serialised as JSON if building a custom scoring pipeline.
