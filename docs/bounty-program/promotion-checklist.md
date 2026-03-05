# Integration Promotion Checklist

Formal criteria for promoting a tool from **unverified** to **verified**. A tool must satisfy every required item before a maintainer moves it from `_register_unverified()` to `_register_verified()` in [tools/__init__.py](../tools/src/aden_tools/tools/__init__.py).

## Checklist

### Code Quality (Required)

- [ ] **`register_tools` function** follows the standard signature pattern from [BUILDING_TOOLS.md](../tools/BUILDING_TOOLS.md)
- [ ] **Error handling** — all tools return `{"error": ...}` dicts instead of raising exceptions
- [ ] **Credential handling** — graceful fallback when credentials are missing, with actionable `"help"` message
- [ ] **Input validation** — parameters are validated before making API calls
- [ ] **No hardcoded secrets** — API keys come from credentials adapter or environment variables only

### Credential Spec (Required)

- [ ] **CredentialSpec exists** in `tools/src/aden_tools/credentials/{category}.py`
- [ ] **`env_var`** is set and unique (no collisions with other specs)
- [ ] **`tools`** list includes every tool function name registered by this module
- [ ] **`help_url`** points to the page where users get their API key
- [ ] **`description`** is a clear one-liner
- [ ] **`credential_id`** and **`credential_key`** are set for credential store mapping
- [ ] **Spec is merged** into `CREDENTIAL_SPECS` in `credentials/__init__.py`

### Health Check (Required)

- [ ] **`health_check_endpoint`** is set in the CredentialSpec
- [ ] **HealthChecker class** is implemented in `tools/src/aden_tools/credentials/health_check.py`
- [ ] **Checker is registered** in the `HEALTH_CHECKERS` dict
- [ ] **Handles 200** (valid), **401** (invalid/expired), and **429** (rate limited but valid) responses
- [ ] **Registry tests pass** — `uv run pytest tools/tests/test_credential_registry.py -v`

### Documentation (Required)

- [ ] **README.md** exists in the tool directory, following the [tool README template](templates/tool-readme-template.md)
- [ ] **Setup instructions** — how to get and configure the API key
- [ ] **Tool table** — lists all tool functions with descriptions
- [ ] **Usage examples** — at least one example per tool function
- [ ] **API reference link** — link to the service's API docs

### Testing (Required)

- [ ] **Unit tests exist** in `tools/tests/tools/test_{tool_name}.py`
- [ ] **Tests mock external APIs** — no live API calls in unit tests
- [ ] **Tests cover happy path** for each tool function
- [ ] **Tests cover error cases** — missing credentials, invalid input, API errors
- [ ] **CI passes** — `make check && make test`

### Community Testing (Required)

- [ ] **At least 1 community member** has tested with a real API key
- [ ] **Agent test report submitted** following the [test report template](templates/agent-test-report-template.md)
- [ ] **Tool works in a real agent workflow** (not just isolated function calls)
- [ ] **No blocking issues** reported in the test report

### Optional (Bonus)

- [ ] Multiple community test reports from different testers
- [ ] Rate limit documentation
- [ ] Integration tests with sandboxed API accounts
- [ ] Pagination support for list endpoints
- [ ] Webhook support (if applicable to the service)

## Promotion Process

1. **Contributor opens a PR** that checks off all required items above
2. **PR description** includes links to: the tool README, the health checker, the test report(s)
3. **Maintainer reviews** the checklist — every required item must be verified
4. **Maintainer moves** the tool registration from `_register_unverified()` to `_register_verified()` in `tools/__init__.py`
5. **Maintainer adds the `bounty:code` label** to the PR — this triggers the GitHub Action to award XP via Lurkr and post a Discord notification
6. **Announcement** auto-posted in `#integrations-announcements` on Discord

## Current Status

### Tools Ready for Promotion Testing

The following 55 unverified tools have implementations, credential specs, and unit tests. They need documentation, health checks, and community testing to be promoted:

<details>
<summary>Full list of unverified tools</summary>

airtable, apify, asana, attio, aws_s3, azure_sql, calendly, cloudinary, confluence,
databricks, docker_hub, duckduckgo, gitlab, google_analytics, google_search_console,
google_sheets, greenhouse, huggingface, jira, kafka, langfuse, linear, lusha,
microsoft_graph, mongodb, n8n, notion, obsidian, pagerduty, pinecone, pipedrive,
plaid, powerbi, pushover, quickbooks, reddit, redis, redshift, salesforce, sap,
shopify, snowflake, supabase, terraform, tines, trello, twilio, twitter, vercel,
yahoo_finance, youtube, youtube_transcript, zendesk, zoho_crm, zoom

</details>

### Gap Summary

| Gap | Count | Bounty Type |
|-----|-------|-------------|
| Missing README | ~41 | `bounty:docs` |
| Missing health_check_endpoint | ~40 | `bounty:code` |
| Missing HealthChecker class | ~40 | `bounty:code` |
| No community test report | 55 | `bounty:test` |
