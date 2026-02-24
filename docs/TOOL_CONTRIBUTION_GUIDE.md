# Tool Contribution Guide: Acceptance Rules & Standards

> **Strict acceptance criteria for community-contributed tools.**
> Every PR adding a new tool integration must satisfy ALL rules in this document. PRs that fail any gate will be requested to amend before merge.

---

## Table of Contents

1. [Before You Start](#before-you-start)
2. [Required Deliverables](#required-deliverables)
3. [Acceptance Gate 1: Issue & Assignment](#acceptance-gate-1-issue--assignment)
4. [Acceptance Gate 2: Tool Implementation](#acceptance-gate-2-tool-implementation)
5. [Acceptance Gate 3: Credential Spec](#acceptance-gate-3-credential-spec)
6. [Acceptance Gate 4: Health Checker](#acceptance-gate-4-health-checker)
7. [Acceptance Gate 5: Tests](#acceptance-gate-5-tests)
8. [Acceptance Gate 6: Registration & Wiring](#acceptance-gate-6-registration--wiring)
9. [Acceptance Gate 7: Documentation](#acceptance-gate-7-documentation)
10. [Acceptance Gate 8: CI Must Pass](#acceptance-gate-8-ci-must-pass)
11. [Quick Reference Checklist](#quick-reference-checklist)
12. [Examples](#examples)

---

## Before You Start

### Scope of This Guide

This guide covers **tool integrations** -- external API integrations that agents use to interact with third-party services (Slack, Stripe, Brevo, etc.). It does NOT cover:
- Core framework changes (`core/`)
- Agent definitions (`exports/`)
- File system toolkits (no credentials required)
- Security scanner tools (no credentials required)

### Prerequisites

- Python 3.11+
- Development environment set up via `./quickstart.sh`
- Familiarity with [CONTRIBUTING.md](../CONTRIBUTING.md) and [BUILDING_TOOLS.md](../tools/BUILDING_TOOLS.md)
- Read at least one existing tool implementation (recommended: `telegram_tool` for simple, `stripe_tool` for complex)

### What the Existing CI Enforces Automatically

The following tests run on every PR. You do NOT need to manually verify these -- CI will catch violations:

| CI Test | What It Catches |
|---|---|
| `TestModuleStructure` | Tool module doesn't export `register_tools` |
| `TestRegisterToolsSignature` | Wrong function signature |
| `TestCredentialSpecFields` | Incomplete `CredentialSpec` fields |
| `TestSpecToolsMatchRegistered` | Tool names in spec don't match registered tools |
| `TestCredentialCoverage` | Tool accepts `credentials` but has no `CredentialSpec` |
| `test_specs_with_endpoint_have_checkers` | `CredentialSpec` has `health_check_endpoint` but no health checker |
| `test_checkers_have_corresponding_specs` | Orphaned health checker with no matching spec |
| `test_all_checkers_pass_wiring` | `validate_integration_wiring()` finds issues |
| `test_no_accidental_env_var_collisions` | Two unrelated specs share the same env var |

If CI is green, the structural wiring is correct.

---

## Required Deliverables

Every tool contribution PR must include exactly these files:

```
tools/src/aden_tools/
├── credentials/
│   └── <service>.py                  # CredentialSpec definition
├── tools/
│   └── <service>_tool/
│       ├── __init__.py               # Exports register_tools
│       ├── <service>_tool.py         # Tool implementation
│       └── README.md                 # Tool documentation
```

Plus modifications to:
- `tools/src/aden_tools/credentials/__init__.py` (import + merge spec)
- `tools/src/aden_tools/credentials/health_check.py` (add health checker + register)
- `tools/src/aden_tools/tools/__init__.py` (import + register tool)
- `tools/tests/test_health_checks.py` (import checker + add test class + update expected set)

---

## Acceptance Gate 1: Issue & Assignment

| Rule | Details |
|---|---|
| **Must have an issue** | Every tool PR must reference an open issue (e.g., `Closes #5127`) |
| **Must be assigned** | You must be assigned to the issue before opening a PR |
| **Issue must define scope** | The issue should list the specific API endpoints / tool functions in scope |
| **Must match parent tracking** | Tool integrations should reference the parent tracking issue [#2805](https://github.com/adenhq/hive/issues/2805) |

**Why:** Prevents duplicate work and ensures the community agrees the integration is needed.

---

## Acceptance Gate 2: Tool Implementation

### 2.1 Directory Structure

```
tools/src/aden_tools/tools/<service>_tool/
├── __init__.py            # MUST export register_tools
├── <service>_tool.py      # Main implementation
└── README.md              # User-facing documentation
```

### 2.2 `__init__.py` -- Exact Pattern

```python
"""<Service> tool -- brief description."""

from .<service>_tool import register_tools

__all__ = ["register_tools"]
```

### 2.3 `register_tools` Function Signature

Tools requiring credentials **MUST** use this exact signature:

```python
from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

import httpx
from fastmcp import FastMCP

if TYPE_CHECKING:
    from aden_tools.credentials import CredentialStoreAdapter


def register_tools(
    mcp: FastMCP,
    credentials: CredentialStoreAdapter | None = None,
) -> None:
    """Register <Service> tools with the MCP server."""
    ...
```

Tools that do NOT require credentials use the simpler `register_tools(mcp: FastMCP) -> None` signature.

### 2.4 Credential Retrieval Pattern

**MUST** follow this pattern -- credential store first, env var fallback:

```python
def _get_api_key() -> str | None:
    """Get <Service> API key from credential store or environment."""
    if credentials is not None:
        key = credentials.get("<service>")
        if key is not None and not isinstance(key, str):
            raise TypeError(
                f"Expected string from credentials.get('<service>'), "
                f"got {type(key).__name__}"
            )
        return key
    return os.getenv("<SERVICE_API_KEY>")
```

### 2.5 Client Wrapper Pattern

External API calls **MUST** go through an internal client class:

```python
class _<Service>Client:
    """Internal client wrapping <Service> API calls."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "<auth-header>": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Handle common HTTP error codes."""
        if response.status_code == 401:
            return {"error": "Invalid <Service> API key"}
        if response.status_code == 400:
            ...
        # Handle 403, 404, 429, other 4xx/5xx
        ...

    def some_api_call(self, ...) -> dict[str, Any]:
        response = httpx.post(
            f"{BASE_URL}/endpoint",
            headers=self._headers,
            json=payload,
            timeout=30.0,
        )
        return self._handle_response(response)
```

### 2.6 Client Factory Pattern

```python
def _get_client() -> _<Service>Client | dict[str, str]:
    """Get a client, or return an error dict if no credentials."""
    api_key = _get_api_key()
    if not api_key:
        return {
            "error": "<Service> API key not configured",
            "help": (
                "Set <SERVICE_API_KEY> environment variable or configure via "
                "credential store. Get your key at <help_url>"
            ),
        }
    return _<Service>Client(api_key)
```

### 2.7 Tool Function Rules

| Rule | Requirement |
|---|---|
| **Decorator** | Every tool uses `@mcp.tool()` |
| **Naming** | `<service>_<action>` (e.g., `brevo_send_email`, `stripe_create_customer`) |
| **Return type** | `dict[str, Any]` -- always |
| **Success format** | `{"success": True, ...relevant_data}` |
| **Error format** | `{"error": "message", "help": "optional guidance"}` |
| **No raised exceptions** | All exceptions caught and returned as error dicts |
| **Input validation** | Validate required fields before API calls |
| **Timeout** | All HTTP calls must set explicit `timeout=` (30s default) |
| **Docstring** | Must include: what, when to use, Args with types/constraints, Returns |

```python
@mcp.tool()
def brevo_send_email(
    to: list[dict[str, str]],
    subject: str,
    html_content: str,
    sender_email: str,
) -> dict[str, Any]:
    """
    Send a transactional email via Brevo.

    Use this for notifications, alerts, confirmations, or any triggered email.

    Args:
        to: Recipients. Each: {"email": "user@example.com", "name": "User"}.
        subject: Email subject line.
        html_content: Email body as HTML.
        sender_email: Verified sender email.

    Returns:
        Dict with messageId on success, or error dict on failure.
    """
    client = _get_client()
    if isinstance(client, dict):
        return client

    # Validate inputs
    if not to:
        return {"error": "At least one recipient is required"}

    try:
        result = client.send_email(...)
        if "error" in result:
            return result
        return {"success": True, "message_id": result.get("messageId", "")}
    except httpx.TimeoutException:
        return {"error": "<Service> request timed out"}
    except httpx.RequestError as e:
        return {"error": f"Network error: {e}"}
```

### 2.8 Prohibited Patterns

| Prohibited | Why | Do Instead |
|---|---|---|
| Raising exceptions from tool functions | Breaks MCP protocol | Return `{"error": "..."}` |
| Global mutable state | Race conditions in server mode | State in client instances |
| Hardcoded credentials | Security vulnerability | Use credential store / env var |
| `requests` library | Project standardizes on `httpx` | Use `httpx` |
| Unbounded API responses | Can OOM the agent | Always paginate or set limits |
| Printing to stdout | Invisible in server mode | Return in dict |

---

## Acceptance Gate 3: Credential Spec

### 3.1 File Location

Create `tools/src/aden_tools/credentials/<service>.py`:

```python
"""
<Service> tool credentials.

Contains credentials for <Service> <brief description> integration.
"""

from .base import CredentialSpec

<SERVICE>_CREDENTIALS = {
    "<service>": CredentialSpec(
        env_var="<SERVICE>_API_KEY",
        tools=[
            "<service>_action_one",
            "<service>_action_two",
            # ... EVERY tool name that uses this credential
        ],
        required=True,
        startup_required=False,
        help_url="<url where users get the API key>",
        description="<Human-readable description of what this credential is>",
        # Auth method support
        aden_supported=False,  # True only if Aden OAuth2 flow is implemented
        direct_api_key_supported=True,
        api_key_instructions="""To get a <Service> API key:
1. Go to <url> and create an account (or sign in)
2. Navigate to <specific settings path>
3. Click "<button name>"
4. Copy the API key
5. Store it securely""",
        # Health check configuration
        health_check_endpoint="<lightweight API endpoint for validation>",
        health_check_method="GET",  # or "POST"
        # Credential store mapping
        credential_id="<service>",
        credential_key="api_key",  # or "access_token", "bot_token", etc.
    ),
}
```

### 3.2 Required Fields -- All MUST Be Non-Empty

| Field | Enforced By | Example |
|---|---|---|
| `env_var` | `test_has_env_var` | `"BREVO_API_KEY"` |
| `description` | `test_has_description` | `"Brevo API key for email and SMS"` |
| `tools` or `node_types` | `test_has_tools_or_node_types` | `["brevo_send_email", ...]` |
| `help_url` | `validate_integration_wiring` | `"https://app.brevo.com/settings/keys/api"` |
| `health_check_endpoint` | `test_specs_with_endpoint_have_checkers` | `"https://api.brevo.com/v3/account"` |
| `credential_id` | `TestCredentialSpecFields` | `"brevo"` |
| `credential_key` | `TestCredentialSpecFields` | `"api_key"` |
| `api_key_instructions` | `validate_integration_wiring` (if `direct_api_key_supported`) | Step-by-step guide |

### 3.3 Tools List Completeness

The `tools` list **MUST** include every `@mcp.tool()` function name registered by your `register_tools()`. CI will fail with `TestCredentialCoverage` if any tool is missing.

### 3.4 Health Check Endpoint Selection

Choose a lightweight, read-only endpoint that:
- Returns 200 with a valid credential
- Returns 401 with an invalid credential
- Does NOT create, modify, or delete data
- Has minimal rate limit cost
- Ideally returns identity info (email, account name)

Good examples:
- `GET /v3/account` (Brevo)
- `GET /v1/balance` (Stripe)
- `GET /api/auth.test` (Slack)
- `GET /users/me/profile` (Gmail)

Bad examples:
- `POST /v3/smtp/email` (sends an actual email)
- `GET /v3/contacts` (returns potentially large list)
- Any endpoint that requires a request body

---

## Acceptance Gate 4: Health Checker

### 4.1 Implementation

Add your health checker to `tools/src/aden_tools/credentials/health_check.py`.

**MUST** subclass `BaseHttpHealthChecker` (unless you need custom logic that truly cannot be expressed via its hooks):

```python
class <Service>HealthChecker(BaseHttpHealthChecker):
    """Health checker for <Service> API key."""

    ENDPOINT = "<same as health_check_endpoint in CredentialSpec>"
    SERVICE_NAME = "<Service>"  # Human-readable name for messages
    AUTH_TYPE = BaseHttpHealthChecker.<AUTH_PATTERN>
    # Plus any auth-specific overrides
```

### 4.2 Auth Pattern Reference

| Your API Auth | `AUTH_TYPE` | Additional Config |
|---|---|---|
| `Authorization: Bearer <key>` | `AUTH_BEARER` (default) | None needed |
| Custom header (e.g., `api-key: <key>`) | `AUTH_HEADER` | `AUTH_HEADER_NAME = "api-key"`, `AUTH_HEADER_TEMPLATE = "{token}"` |
| Query param (e.g., `?apiKey=<key>`) | `AUTH_QUERY` | `AUTH_QUERY_PARAM_NAME = "apiKey"` |
| HTTP Basic Auth | `AUTH_BASIC` | None needed |
| Token in URL (e.g., `/bot<key>/getMe`) | `AUTH_URL` | Override `_build_url()` |

### 4.3 Optional Overrides

| Hook | When to Override |
|---|---|
| `_extract_identity(data)` | API returns account info (email, company, username) |
| `_interpret_response(response)` | Non-standard status code semantics |
| `_build_json_body(credential_value)` | POST-based health check requiring a body |
| `_build_url(credential_value)` | Token embedded in URL path |

### 4.4 Registration

Add your checker to the `HEALTH_CHECKERS` dict (alphabetical order by convention is not required, but add near the bottom):

```python
HEALTH_CHECKERS: dict[str, CredentialHealthChecker] = {
    # ... existing checkers
    "<service>": <Service>HealthChecker(),
}
```

### 4.5 Endpoint Consistency Rule

The `ENDPOINT` class attribute **MUST** match the `health_check_endpoint` in the `CredentialSpec` (ignoring query strings). `validate_integration_wiring()` will catch mismatches.

---

## Acceptance Gate 5: Tests

### 5.1 Health Checker Tests (REQUIRED)

In `tools/tests/test_health_checks.py`:

**Step 1:** Add your checker to the import block:
```python
from aden_tools.credentials.health_check import (
    # ... existing imports
    <Service>HealthChecker,
)
```

**Step 2:** Add your service to the expected checkers set in `test_all_expected_checkers_registered`:
```python
expected = {
    # ... existing entries
    "<service>",
}
```

**Step 3:** Add a test class using `HealthCheckerTestSuite`:
```python
class Test<Service>HealthChecker(HealthCheckerTestSuite):
    CHECKER_CLASS = <Service>HealthChecker
    HTTP_METHOD = "get"  # or "post"
```

This gives you **6 tests automatically**:
- `test_valid_credential_200` -- 200 = valid
- `test_invalid_credential_401` -- 401 = invalid
- `test_forbidden_403` -- 403 = invalid
- `test_rate_limited_429` -- 429 = valid (credential works, just rate limited)
- `test_timeout` -- timeout = invalid with clear error message
- `test_network_error` -- connection failure = invalid with clear error message

**Step 4 (if needed):** Override test expectations:
```python
class Test<Service>HealthChecker(HealthCheckerTestSuite):
    CHECKER_CLASS = <Service>HealthChecker
    HTTP_METHOD = "get"
    EXPECT_429_VALID = False  # If your API returns 429 for invalid keys
```

**Step 5 (if needed):** Add custom tests for non-standard behavior:
```python
class TestTelegramHealthChecker(HealthCheckerTestSuite):
    CHECKER_CLASS = TelegramHealthChecker
    HTTP_METHOD = "get"
    EXPECT_429_VALID = False

    def test_ok_false_invalid(self, mock_client_cls):
        """200 with ok=false means invalid bot token."""
        self._setup_mock(mock_client_cls, 200, {"ok": False, "description": "Unauthorized"})
        result = self._make_checker().check("bad-token")
        assert result.valid is False
```

### 5.2 Registry Tests (AUTOMATIC)

You do NOT need to write these -- they are parametrized over `CREDENTIAL_SPECS` and `HEALTH_CHECKERS` and will automatically include your new integration:

- `test_has_env_var[<service>]`
- `test_has_description[<service>]`
- `test_has_tools_or_node_types[<service>]`
- `test_all_checkers_pass_wiring[<service>]`
- `test_specs_with_endpoint_have_checkers` (checks your spec is covered)
- `test_checkers_have_corresponding_specs` (checks your checker isn't orphaned)
- `test_no_accidental_env_var_collisions` (checks your env var is unique)

### 5.3 Minimum Test Count

Every tool integration must produce at minimum:
- **6 health checker tests** (from `HealthCheckerTestSuite`)
- **4+ registry tests** (auto-parametrized from `test_credential_registry.py`)
- Total: **10+ tests minimum** per integration

### 5.4 Running Tests Locally

```bash
cd tools && uv run pytest tests/test_health_checks.py tests/test_credential_registry.py -v
```

You can also verify wiring interactively:
```python
from aden_tools.credentials.health_check import validate_integration_wiring
issues = validate_integration_wiring("<service>")
for issue in issues:
    print(f"  - {issue}")
# Empty list = fully wired
```

---

## Acceptance Gate 6: Registration & Wiring

### 6.1 Credential Spec Registration

In `tools/src/aden_tools/credentials/__init__.py`:

```python
# Add import (alphabetical)
from .<service> import <SERVICE>_CREDENTIALS

# Add to CREDENTIAL_SPECS merge
CREDENTIAL_SPECS = {
    # ... existing entries
    **<SERVICE>_CREDENTIALS,
}

# Add to __all__
__all__ = [
    # ... existing entries
    "<SERVICE>_CREDENTIALS",
]
```

### 6.2 Tool Registration

In `tools/src/aden_tools/tools/__init__.py`:

```python
# Add import (alphabetical)
from .<service>_tool import register_tools as register_<service>

# Add to register_all_tools() body
def register_all_tools(mcp, credentials=None):
    # ... existing registrations
    register_<service>(mcp, credentials=credentials)
```

### 6.3 Wiring Validation

Run `validate_integration_wiring("<service>")` and confirm it returns an empty list. This checks:

| Check | What It Verifies |
|---|---|
| Spec exists | `CredentialSpec` is in `CREDENTIAL_SPECS` |
| `env_var` set | Environment variable name defined |
| `description` set | Human-readable description present |
| `tools` or `node_types` set | At least one tool or node type mapped |
| `help_url` set | Users can find where to get the credential |
| `api_key_instructions` set | Step-by-step guide (if `direct_api_key_supported`) |
| `health_check_endpoint` set | Validation endpoint defined |
| Checker registered | Entry exists in `HEALTH_CHECKERS` |
| Endpoint match | Spec endpoint matches checker's `ENDPOINT` |

---

## Acceptance Gate 7: Documentation

### 7.1 Tool README (REQUIRED)

Create `tools/src/aden_tools/tools/<service>_tool/README.md` with:

```markdown
# <Service> Tool

<1-2 sentence description>

## Available Tools

| Tool | Description |
|---|---|
| `<service>_action` | Brief description |

## Setup

### Get API Key
<Step-by-step instructions (same as api_key_instructions)>

### Configure
\```bash
export <SERVICE>_API_KEY=your_key_here
\```

## Usage Examples

### <Action Name>
\```json
{
  "tool": "<service>_action",
  "arguments": {
    "param": "value"
  }
}
\```

## Error Handling

| Error | Cause | Resolution |
|---|---|---|
| "Invalid API key" | Wrong or expired key | Regenerate at <url> |
| "Rate limit exceeded" | Too many requests | Wait and retry |
```

### 7.2 PR Description (REQUIRED)

Use this template:

```markdown
## Summary
- Adds <Service> integration with <N> tools: <list tools>
- Implements <auth pattern> authentication via BaseHttpHealthChecker
- Closes #<issue>

## Tools Added
| Tool | Endpoint | Method |
|---|---|---|
| `<service>_action` | `<API endpoint>` | POST |

## Credential Configuration
- Env var: `<SERVICE>_API_KEY`
- Auth: `<auth-header>: <key>` (custom header / Bearer / query param / etc.)
- Health check: `GET <endpoint>` (returns account info)

## Test Results
- <N> health checker tests (via HealthCheckerTestSuite)
- <N> registry wiring tests (auto-parametrized)
- All <total> tests passing

## API Documentation
- <link to API docs>
```

---

## Acceptance Gate 8: CI Must Pass

All of the following must be green:

```bash
# Lint + format
make check

# Core framework tests
make test

# Tools package tests (includes health check + registry tests)
cd tools && uv run pytest tests/ -v
```

**Specific CI checks that will block merge:**

| Check | How to Fix |
|---|---|
| `test_all_expected_checkers_registered` FAILED | Add `"<service>"` to the expected set |
| `test_specs_with_endpoint_have_checkers` FAILED | Register a health checker for your spec |
| `test_all_checkers_pass_wiring[<service>]` FAILED | Fix the wiring issue reported in the assertion |
| `TestCredentialCoverage` FAILED | Add missing tool names to `CredentialSpec.tools` |
| ruff lint FAILED | Run `ruff check --fix` and `ruff format` |

---

## Quick Reference Checklist

Copy this into your PR description and check off each item:

```markdown
### Tool Contribution Checklist

**Issue & Assignment**
- [ ] Linked issue exists and I am assigned
- [ ] Issue references parent tracking issue #2805

**Implementation**
- [ ] `tools/src/aden_tools/tools/<service>_tool/__init__.py` created
- [ ] `tools/src/aden_tools/tools/<service>_tool/<service>_tool.py` created
- [ ] `register_tools(mcp, credentials=None)` signature used
- [ ] Credential retrieval: store first, env var fallback
- [ ] Internal `_<Service>Client` class wraps all API calls
- [ ] All tools return `dict[str, Any]` (no raised exceptions)
- [ ] All HTTP calls have explicit `timeout=`
- [ ] Error format: `{"error": "...", "help": "..."}`
- [ ] Success format: `{"success": True, ...data}`

**Credential Spec**
- [ ] `tools/src/aden_tools/credentials/<service>.py` created
- [ ] All required fields populated (env_var, description, tools, help_url, health_check_endpoint, credential_id, credential_key, api_key_instructions)
- [ ] `tools` list includes EVERY @mcp.tool() function name
- [ ] Imported and merged in `credentials/__init__.py`
- [ ] Added to `__all__` in `credentials/__init__.py`

**Health Checker**
- [ ] Checker class added to `health_check.py` (subclasses `BaseHttpHealthChecker`)
- [ ] `ENDPOINT` matches `health_check_endpoint` in CredentialSpec
- [ ] Registered in `HEALTH_CHECKERS` dict
- [ ] Auth pattern correctly configured (bearer/header/query/basic/url)

**Tests**
- [ ] Checker imported in `test_health_checks.py`
- [ ] Added to `test_all_expected_checkers_registered` expected set
- [ ] `Test<Service>HealthChecker(HealthCheckerTestSuite)` class added
- [ ] `validate_integration_wiring("<service>")` returns empty list
- [ ] All tests pass locally: `cd tools && uv run pytest tests/ -v`

**Registration**
- [ ] Tool imported in `tools/__init__.py`
- [ ] `register_<service>(mcp, credentials=credentials)` added to `register_all_tools()`

**Documentation**
- [ ] `README.md` in tool directory
- [ ] Tool docstrings complete (what, when, args, returns)

**CI**
- [ ] `make check` passes
- [ ] `make test` passes
- [ ] `cd tools && uv run pytest tests/ -v` passes
```

---

## Examples

### Minimal Integration (4-Line Health Checker)

Brevo uses a custom header (`api-key: <token>`):

```python
class BrevoHealthChecker(BaseHttpHealthChecker):
    ENDPOINT = "https://api.brevo.com/v3/account"
    SERVICE_NAME = "Brevo"
    AUTH_TYPE = BaseHttpHealthChecker.AUTH_HEADER
    AUTH_HEADER_NAME = "api-key"
    AUTH_HEADER_TEMPLATE = "{token}"
```

Test (3 lines, produces 6 tests):
```python
class TestBrevoHealthChecker(HealthCheckerTestSuite):
    CHECKER_CLASS = BrevoHealthChecker
    HTTP_METHOD = "get"
```

### Query Parameter Auth

Cal.com passes the key as `?apiKey=<token>`:

```python
class CalcomHealthChecker(BaseHttpHealthChecker):
    ENDPOINT = "https://api.cal.com/v1/me"
    SERVICE_NAME = "Cal.com"
    AUTH_TYPE = BaseHttpHealthChecker.AUTH_QUERY
    AUTH_QUERY_PARAM_NAME = "apiKey"
```

### URL-Embedded Token

Telegram embeds the token in the URL path:

```python
class TelegramHealthChecker(BaseHttpHealthChecker):
    SERVICE_NAME = "Telegram"
    AUTH_TYPE = BaseHttpHealthChecker.AUTH_URL

    def _build_url(self, credential_value):
        return f"https://api.telegram.org/bot{credential_value}/getMe"

    def _build_headers(self, credential_value):
        return {"Accept": "application/json"}

    def _interpret_response(self, response):
        # Telegram returns 200 with ok=false for invalid tokens
        if response.status_code == 200:
            data = response.json()
            if data.get("ok"):
                return HealthCheckResult(valid=True, message="Telegram bot token valid")
            return HealthCheckResult(valid=False, message="Invalid Telegram bot token")
        return super()._interpret_response(response)
```

### POST-Based Health Check

Exa Search requires a POST with a body:

```python
class ExaSearchHealthChecker(BaseHttpHealthChecker):
    ENDPOINT = "https://api.exa.ai/search"
    SERVICE_NAME = "Exa Search"
    HTTP_METHOD = "POST"

    def _build_json_body(self, credential_value):
        return {"query": "test", "numResults": 1}
```

---

## Rejection Reasons (Common PR Feedback)

| Reason | Fix |
|---|---|
| "Health checker missing" | Add a `BaseHttpHealthChecker` subclass and register it |
| "Tools list incomplete" | Add every `@mcp.tool()` name to `CredentialSpec.tools` |
| "No health check endpoint" | Find a lightweight read-only endpoint that returns 200/401 |
| "Using `requests` instead of `httpx`" | Replace with `httpx` (project standard) |
| "Tool raises exceptions" | Wrap in try/except and return error dicts |
| "No input validation" | Add checks before API calls |
| "Missing README" | Add `README.md` to tool directory |
| "Expected checkers set not updated" | Add service name to `test_all_expected_checkers_registered` |
| "Hardcoded timeout" / "No timeout" | Add explicit `timeout=30.0` to all HTTP calls |
| "Credential only from env var" | Must check credential store first, then fall back to env var |
