"""Test script: Codex vs OpenAI — tool call argument truncation repro.

Run: uv run python core/tests/test_two_llm_calls.py
"""

import json
import sys

sys.path.insert(0, "core")

from framework.llm.litellm import LiteLLMProvider
from framework.llm.provider import Tool
from framework.llm.stream_events import (
    FinishEvent,
    StreamErrorEvent,
    TextDeltaEvent,
    ToolCallEvent,
)

OPENAI_API_KEY = "sk-*****"

# ---------------------------------------------------------------------------
# Tool definitions — mimic the real vulnerability_assessment agent
# ---------------------------------------------------------------------------

SCAN_TOOLS = [
    Tool(
        name="ssl_tls_scan",
        description="Scan SSL/TLS configuration for a hostname",
        parameters={
            "type": "object",
            "properties": {
                "hostname": {"type": "string", "description": "Domain name to scan"},
                "port": {"type": "integer", "description": "Port to connect to", "default": 443},
            },
            "required": ["hostname"],
        },
    ),
    Tool(
        name="http_headers_scan",
        description="Scan HTTP security headers for a URL",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to scan"},
                "follow_redirects": {"type": "boolean", "default": True},
            },
            "required": ["url"],
        },
    ),
    Tool(
        name="dns_security_scan",
        description="Scan DNS security configuration for a domain",
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Domain name to scan"},
            },
            "required": ["domain"],
        },
    ),
    Tool(
        name="port_scan",
        description="Scan open ports for a hostname",
        parameters={
            "type": "object",
            "properties": {
                "hostname": {"type": "string", "description": "Domain or IP to scan"},
                "ports": {"type": "string", "default": "top20"},
                "timeout": {"type": "number", "default": 3.0},
            },
            "required": ["hostname"],
        },
    ),
    Tool(
        name="tech_stack_detect",
        description="Detect technology stack for a URL",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to analyze"},
            },
            "required": ["url"],
        },
    ),
    Tool(
        name="subdomain_enumerate",
        description="Enumerate subdomains for a domain",
        parameters={
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Base domain"},
                "max_results": {"type": "integer", "default": 50},
            },
            "required": ["domain"],
        },
    ),
    # The big one — takes 6 JSON-string params (whole scan results)
    Tool(
        name="set_output",
        description=(
            "Set the output for this node. Call this when you are done."
            " scan_results must be a JSON string containing the full"
            " consolidated results from all scans."
        ),
        parameters={
            "type": "object",
            "properties": {
                "scan_results": {
                    "type": "string",
                    "description": (
                        "JSON string with consolidated scan results"
                        " including ssl, headers, dns, ports, tech,"
                        " and subdomain data."
                    ),
                },
            },
            "required": ["scan_results"],
        },
    ),
]

# Fake scan results — realistic size to stress-test argument streaming
FAKE_SSL_RESULT = {
    "hostname": "example.com",
    "port": 443,
    "tls_version": "TLSv1.3",
    "cipher": "TLS_AES_256_GCM_SHA384",
    "cipher_bits": 256,
    "certificate": {
        "subject": "CN=example.com",
        "issuer": "CN=Let's Encrypt Authority X3",
        "not_before": "2025-01-01T00:00:00Z",
        "not_after": "2026-01-01T00:00:00Z",
        "days_until_expiry": 310,
        "san": ["example.com", "www.example.com"],
        "self_signed": False,
        "sha256_fingerprint": "AB:CD:EF:12:34:56:78:90",
    },
    "issues": [
        {
            "severity": "low",
            "finding": "Certificate expiring in 310 days",
            "remediation": "Monitor expiry",
        },
    ],
    "grade_input": {
        "tls_version_ok": True,
        "cert_valid": True,
        "cert_expiring_soon": False,
        "strong_cipher": True,
        "self_signed": False,
    },
}

FAKE_HEADERS_RESULT = {
    "url": "https://example.com",
    "status_code": 200,
    "headers_present": ["Strict-Transport-Security", "X-Content-Type-Options"],
    "headers_missing": [
        {
            "header": "Content-Security-Policy",
            "severity": "high",
            "description": "No CSP header",
            "remediation": "Add CSP header",
        },
        {
            "header": "X-Frame-Options",
            "severity": "medium",
            "description": "No X-Frame-Options",
            "remediation": "Add DENY or SAMEORIGIN",
        },
        {
            "header": "Permissions-Policy",
            "severity": "low",
            "description": "No Permissions-Policy",
            "remediation": "Add Permissions-Policy",
        },
    ],
    "leaky_headers": [
        {
            "header": "Server",
            "value": "nginx/1.21.0",
            "severity": "low",
            "remediation": "Remove server version",
        },
    ],
    "grade_input": {
        "hsts": True,
        "csp": False,
        "x_frame_options": False,
        "x_content_type_options": True,
        "referrer_policy": False,
        "permissions_policy": False,
        "no_leaky_headers": False,
    },
}

FAKE_DNS_RESULT = {
    "domain": "example.com",
    "source": "crt.sh",
    "spf": {
        "present": True,
        "record": "v=spf1 include:_spf.google.com ~all",
        "policy": "softfail",
        "issues": [],
    },
    "dmarc": {
        "present": True,
        "record": "v=DMARC1; p=reject; rua=mailto:dmarc@example.com",
        "policy": "reject",
        "issues": [],
    },
    "dkim": {"selectors_found": ["google", "default"], "selectors_missing": []},
    "dnssec": {
        "enabled": False,
        "issues": [{"severity": "medium", "finding": "DNSSEC not enabled"}],
    },
    "mx_records": ["10 mail.example.com"],
    "caa_records": ["0 issue letsencrypt.org"],
    "zone_transfer": {"vulnerable": False},
    "grade_input": {
        "spf_present": True,
        "spf_strict": False,
        "dmarc_present": True,
        "dmarc_enforcing": True,
        "dkim_found": True,
        "dnssec_enabled": False,
        "zone_transfer_blocked": True,
    },
}

FAKE_PORTS_RESULT = {
    "hostname": "example.com",
    "ip": "93.184.216.34",
    "ports_scanned": 20,
    "open_ports": [
        {"port": 80, "service": "http", "banner": "nginx/1.21.0"},
        {"port": 443, "service": "https", "banner": "nginx/1.21.0"},
        {
            "port": 22,
            "service": "ssh",
            "banner": "OpenSSH_8.9",
            "severity": "medium",
            "finding": "SSH port open",
            "remediation": "Restrict SSH access",
        },
    ],
    "closed_ports": [21, 23, 25, 53, 110, 143, 993, 995, 3306, 5432, 6379, 8080, 8443, 27017],
    "grade_input": {
        "no_database_ports_exposed": True,
        "no_admin_ports_exposed": False,
        "no_legacy_ports_exposed": True,
        "only_web_ports": False,
    },
}

FAKE_TECH_RESULT = {
    "url": "https://example.com",
    "server": {"name": "nginx", "version": "1.21.0", "raw": "nginx/1.21.0"},
    "framework": "React",
    "language": "JavaScript",
    "cms": None,
    "javascript_libraries": ["react-18.2.0", "lodash-4.17.21", "axios-1.6.0"],
    "cdn": "Cloudflare",
    "analytics": ["Google Analytics"],
    "security_txt": True,
    "robots_txt": True,
    "interesting_paths": ["/admin", "/.env", "/api/docs"],
    "cookies": [
        {"name": "session", "secure": True, "httponly": True, "samesite": "Strict"},
        {"name": "_ga", "secure": False, "httponly": False, "samesite": "None"},
    ],
    "grade_input": {
        "server_version_hidden": False,
        "framework_version_hidden": True,
        "security_txt_present": True,
        "cookies_secure": False,
        "cookies_httponly": False,
    },
}

FAKE_SUBDOMAIN_RESULT = {
    "domain": "example.com",
    "source": "crt.sh",
    "total_found": 8,
    "subdomains": [
        "www.example.com",
        "mail.example.com",
        "api.example.com",
        "staging.example.com",
        "dev.example.com",
        "admin.example.com",
        "cdn.example.com",
        "blog.example.com",
    ],
    "interesting": [
        {
            "subdomain": "staging.example.com",
            "reason": "staging environment exposed",
            "severity": "high",
            "remediation": "Restrict access",
        },
        {
            "subdomain": "dev.example.com",
            "reason": "development environment exposed",
            "severity": "high",
            "remediation": "Restrict access",
        },
        {
            "subdomain": "admin.example.com",
            "reason": "admin panel exposed",
            "severity": "medium",
            "remediation": "Add IP restriction",
        },
    ],
    "grade_input": {
        "no_dev_staging_exposed": False,
        "no_admin_exposed": False,
        "reasonable_surface_area": True,
    },
}


def _make_codex_provider():
    from framework.config import get_api_base, get_api_key, get_llm_extra_kwargs

    api_key = get_api_key()
    api_base = get_api_base()
    extra_kwargs = get_llm_extra_kwargs()
    if not api_key or not api_base:
        return None
    return LiteLLMProvider(
        model="openai/gpt-5.3-codex",
        api_key=api_key,
        api_base=api_base,
        **extra_kwargs,
    )


async def _stream_and_collect(provider, messages, system, tools):
    """Stream a call, collect text + tool calls, print events.  Returns (text, tool_calls)."""
    text = ""
    tool_calls: list[ToolCallEvent] = []
    async for event in provider.stream(messages=messages, system=system, tools=tools):
        if isinstance(event, TextDeltaEvent):
            text = event.snapshot
        elif isinstance(event, ToolCallEvent):
            tool_calls.append(event)
        elif isinstance(event, FinishEvent):
            print(
                f"  finish: stop={event.stop_reason}"
                f" in={event.input_tokens}"
                f" out={event.output_tokens}"
            )
        elif isinstance(event, StreamErrorEvent):
            print(f"  STREAM ERROR: {event.error}")
            return text, tool_calls
    return text, tool_calls


def _validate_tool_args(tool_calls: list[ToolCallEvent]) -> bool:
    """Check that every tool call has valid, non-truncated JSON arguments."""
    ok = True
    for tc in tool_calls:
        print(f"  ToolCall: {tc.tool_name}  id={tc.tool_use_id}")
        args = tc.tool_input

        # Check for the _raw fallback (means JSON parse failed → truncated)
        if "_raw" in args:
            print(f"    TRUNCATED — raw args: {args['_raw'][:200]}...")
            ok = False
            continue

        # For set_output, validate the nested JSON string
        if tc.tool_name == "set_output" and "scan_results" in args:
            raw_json = args["scan_results"]
            print(f"    scan_results length: {len(raw_json)} chars")
            try:
                parsed = json.loads(raw_json)
                keys = list(parsed.keys()) if isinstance(parsed, dict) else "not-a-dict"
                print(f"    parsed OK — keys: {keys}")
            except json.JSONDecodeError as e:
                print(f"    INVALID JSON in scan_results: {e}")
                print(f"    tail: ...{raw_json[-200:]}")
                ok = False
        else:
            print(f"    args: {json.dumps(args)}")
    return ok


if __name__ == "__main__":
    pass
