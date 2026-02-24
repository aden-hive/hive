# SSL/TLS Scanner

Analyze SSL/TLS configuration and certificate security through non-intrusive inspection.

## Features

- **TLS version detection** — identifies the negotiated protocol version
- **Cipher suite analysis** — flags weak ciphers (RC4, DES, 3DES, NULL, EXPORT)
- **Certificate validation** — checks expiry, self-signed status, and trust chain
- **SAN extraction** — lists Subject Alternative Names from certificates
- **Certificate fingerprinting** — SHA-256 hash of the certificate
- **Graceful error handling** — inspects invalid certificates instead of rejecting them
- **Grade input** output for the `risk_scorer` tool

## Usage

```python
result = ssl_tls_scan("example.com")
```

### Scan Options

```python
# Default HTTPS port
result = ssl_tls_scan("example.com")

# Custom port
result = ssl_tls_scan("example.com", port=8443)
```

## API Reference

| Parameter  | Type  | Default  | Description                                          |
|------------|-------|----------|------------------------------------------------------|
| `hostname` | `str` | required | Domain name to scan. Do not include protocol prefix. |
| `port`     | `int` | `443`    | Port to connect to.                                  |

### Return Value

| Field         | Type         | Description                                    |
|---------------|--------------|------------------------------------------------|
| `hostname`    | `str`        | Scanned hostname                               |
| `port`        | `int`        | Scanned port                                   |
| `tls_version` | `str`        | Negotiated TLS version (e.g., `"TLSv1.3"`)    |
| `cipher`      | `str`        | Cipher suite name                              |
| `cipher_bits` | `int`        | Cipher key length in bits                      |
| `certificate` | `dict`       | Subject, issuer, expiry, SAN, fingerprint      |
| `issues`      | `list[dict]` | Security findings with severity and remediation|
| `grade_input` | `dict`       | Scoring data for the `risk_scorer` tool        |

### Issue Severities

| Finding                        | Severity |
|--------------------------------|----------|
| SSL certificate verification failed | Critical |
| Certificate expired            | Critical |
| Insecure TLS version (1.0/1.1) | High     |
| Weak cipher suite              | High     |
| Self-signed certificate        | High     |
| Certificate expiring within 30 days | Medium |

## Dependencies

- Python 3.11+
- Python stdlib only (`ssl`, `socket`, `hashlib`)

## Error Handling

| Error                       | Cause                          |
|-----------------------------|--------------------------------|
| `"Connection ... timed out"`  | Host unreachable or slow       |
| `"Connection ... refused"`    | Port closed or blocked         |
| `"Connection failed: ..."`    | Network or SSL error           |

## Responsible Use

This tool performs **non-intrusive TLS handshake inspection** using Python's standard library. It does not modify certificates or exploit vulnerabilities.

- Only scan domains you own or have explicit authorization to test
- The tool temporarily disables certificate verification to inspect invalid certs — this is for analysis purposes only
- Do not use scan results to attack or impersonate services
- Use results for defensive security assessment only
