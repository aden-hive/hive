## Summary
- **Added HubSpot integration** — new HubSpot MCP tool with search, get, create, and update operations for contacts, companies, and deals. Includes OAuth2 provider for HubSpot credentials and credential store adapter for the tools layer.
- **Replaced web_scrape tool with Playwright + stealth** — swapped httpx/BeautifulSoup for a headless Chromium browser using `playwright` (async API) and `playwright-stealth`, enabling JS-rendered page scraping and bot detection evasion
- **Added empty response retry logic** — LLM provider now detects empty responses (e.g. Gemini returning 200 with no content on rate limit) and retries with exponential backoff, preventing hallucinated output from the cleanup LLM
- **Added context-aware input compaction** — LLM nodes now estimate input token count before calling the model and progressively truncate the largest values if they exceed the context window budget
- **Increased rate limit retries to 10** with verbose `[retry]` and `[compaction]` logging that includes model name, finish reason, and attempt count
- **Interactive quickstart onboarding** — `quickstart.sh` rewritten as bee-themed interactive wizard that detects existing API keys (including Claude Code subscription), lets user pick ONE default LLM provider, and saves configuration to `~/.hive/configuration.json`
- **Fixed lint errors** across `hubspot_tool.py` (line length) and `agent_builder_server.py` (unused variable)

## Changed files

### HubSpot Integration
- `tools/src/aden_tools/tools/hubspot_tool/` — New MCP tool: contacts, companies, and deals CRUD
- `tools/src/aden_tools/tools/__init__.py` — Registered HubSpot tools
- `tools/src/aden_tools/credentials/integrations.py` — HubSpot credential integration
- `tools/src/aden_tools/credentials/__init__.py` — Updated credential exports
- `core/framework/credentials/oauth2/hubspot_provider.py` — HubSpot OAuth2 provider
- `core/framework/credentials/oauth2/__init__.py` — Registered HubSpot OAuth2 provider
- `core/framework/runner/runner.py` — Updated runner for credential support

### Web Scrape Rewrite
- `tools/src/aden_tools/tools/web_scrape_tool/web_scrape_tool.py` — Playwright async rewrite
- `tools/src/aden_tools/tools/web_scrape_tool/README.md` — Updated docs
- `tools/pyproject.toml` — Added `playwright`, `playwright-stealth` deps
- `tools/Dockerfile` — Added `playwright install chromium --with-deps`
### LLM Reliability
- `core/framework/llm/litellm.py` — Empty response retry + max retries 10 + verbose logging
- `core/framework/graph/node.py` — Input compaction via `_compact_inputs()`, `_estimate_tokens()`, `_get_context_limit()`

### Quickstart & Setup
- `quickstart.sh` — Interactive bee-themed onboarding wizard with single provider selection
- `~/.hive/configuration.json` — New user config file for default LLM provider/model

### Fixes
- `core/framework/mcp/agent_builder_server.py` — Removed unused variable
- `tools/src/aden_tools/tools/hubspot_tool/hubspot_tool.py` — Fixed E501 line length violations

## Test plan
- [ ] Run `make lint` — passes clean
- [ ] Run `./quickstart.sh` and verify interactive flow works, config saved to `~/.hive/configuration.json`
- [ ] Run `pytest tests/tools/test_web_scrape_tool.py -v`
- [ ] Run agent against a JS-heavy site and verify `web_scrape` returns rendered content
- [ ] Set `HUBSPOT_ACCESS_TOKEN` and verify HubSpot tool CRUD operations work
- [ ] Trigger rate limit and verify `[retry]` logs appear with correct attempt counts
- [ ] Run agent with large inputs and verify `[compaction]` logs show truncation

🤖 Generated with [Claude Code](https://claude.com/claude-code)
