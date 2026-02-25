# SSL/TLS Scanner Tool

Analyze SSL/TLS configuration and certificate security for any HTTPS endpoint.

## Features

- **ssl_tls_scan** - Check TLS version, cipher suite, certificate validity, and common misconfigurations

## How It Works

Performs non-intrusive TLS handshake analysis using Python's ssl module:
1. Establishes a TLS connection to the target
2. Extracts certificate details (issuer, expiry, SANs)
3. Checks TLS version and cipher strength
4. Identifies security issues and misconfigurations

**No credentials required** - Uses only Python stdlib (ssl + socket).

## Usage Examples

### Basic Scan
```python
ssl_tls_scan(hostname="example.com")
```

### Scan Non-Standard Port
```python
ssl_tls_scan(hostname="example.com", port=8443)
```

## API Reference

### ssl_tls_scan

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| hostname | str | Yes | - | Domain name to scan (e.g., "example.com") |
| port | int | No | 443 | Port to connect to |

### Response
```json
{
  "hostname": "example.com",
  "port": 443,
  "tls_version": "TLSv1.3",
  "cipher": "TLS_AES_256_GCM_SHA384",
  "cipher_bits": 256,
  "certificate": {
    "subject": "CN=example.com",
    "issuer": "CN=R3, O=Let's Encrypt, C=US",
    "not_before": "2024-01-01T00:00:00+00:00",
    "not_after": "2024-04-01T00:00:00+00:00",
    "days_until_expiry": 45,
    "san": ["example.com", "www.example.com"],
    "self_signed": false,
    "sha256_fingerprint": "abc123..."
  },
  "issues": [],
  "grade_input": {
    "tls_version_ok": true,
    "cert_valid": true,
    "cert_expiring_soon": false,
    "strong_cipher": true,
    "self_signed": false
  }
}
```

## Security Checks

| Check | Severity | Description |
|-------|----------|-------------|
| Insecure TLS version | High | TLS 1.0, 1.1, SSLv2, SSLv3 are vulnerable |
| Weak cipher suite | High | RC4, DES, 3DES, MD5, NULL, EXPORT ciphers |
| Certificate expired | Critical | SSL certificate has expired |
| Certificate expiring soon | Medium | Expires within 30 days |
| Self-signed certificate | High | Not trusted by browsers |
| Verification failed | Critical | Certificate chain validation failed |

## Ethical Use

⚠️ **Important**: Only scan systems you own or have explicit permission to test.

- This tool performs active TLS connections
- Scanning third-party sites without permission may violate terms of service

## Error Handling
```python
{"error": "Connection to example.com:443 timed out"}
{"error": "Connection to example.com:443 refused. Port may be closed."}
{"error": "Connection failed: [SSL error details]"}
```

## Integration with Risk Scorer

The `grade_input` field can be passed to the `risk_score` tool for weighted security grading.
