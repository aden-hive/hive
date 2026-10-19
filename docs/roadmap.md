# Roadmap

Where Hive stands after V1, and what's still open. For how things work today, read the [architecture overview](architecture/README.md). The maintainers set priorities; [GitHub issues](https://github.com/aden-hive/hive/issues) are the place to propose an item or discuss one.

## Shipped in V1

### Colonies

- [x] A queen that spawns worker clones at runtime with `run_worker`, with no graph to design
- [x] A shared SQLite tracker per colony: workers write one row per unit of work, and the queen checks progress with SQL
- [x] `run_playbook`: one worker per tracker row, with retries and backoff, rate-limited lanes, a circuit breaker, a dead-letter list, and resume by re-running
- [x] Skills the queen writes once a pilot works (`write_skill`), which every worker she spawns afterwards can load
- [x] Scheduled colonies, with cron, interval and webhook triggers
- [x] Importing a colony from a tar archive (`POST /api/colonies/import`)

### Queens

- [x] 13 persona queens: 6 active by default, the rest hired from the Org Chart, plus queens you create
- [x] Questions with options (`ask_user`), a task plan you can see, and a confirm dialog before any colony is created
- [x] The Prompt Library, which deploys a ready-made prompt straight to the queen it was written for

### Tools

- [x] Built-in tools that run in-process: shell and background jobs, files, code search, charts, web scraping, PDFs, CSV and memory search
- [x] External MCP servers (`hive mcp add`, `hive mcp install`), on the same allowlists as the built-in tools
- [x] Tool categories, per-queen and per-colony allowlists, and on-demand loading with `search_tools`
- [x] Your own Chrome, driven through the Hive Browser Bridge extension and the `hive-browser` CLI
- [x] Skills in the open [Agent Skills](https://agentskills.io) format, managed in the Skills Library

### Memory

- [x] Reflection notes, global and per queen, recalled into context when they're relevant
- [x] Automatic recall of relevant past conversations, and `search_messages` to search them on demand
- [x] A dated timeline of the events, facts and plans you mention (opt-in, with the `memory_timeline` flag)

### Oversight and reliability

- [x] Sentinel, opt-in per colony: it nudges a parked queen on, or escalates to you through the Hive inbox, Telegram or Slack
- [x] Park and resume from disk after a question, a stop, an error or a crash
- [x] Context compaction, with large tool results spilled to files instead of the conversation
- [x] Stall and doom-loop detection, tool-call budgets per turn and per run, and a cap on concurrent workers
- [x] Usage metering on every model call

### Models and setup

- [x] Any [LiteLLM](https://docs.litellm.ai/docs/providers) provider or OpenAI-compatible endpoint, coding subscriptions (Claude Code, OpenAI Codex and others), Hive LLM and Ollama
- [x] A separate model for workers, and a vision fallback for text-only models
- [x] An encrypted credential store, with OAuth2 for HubSpot and Zoho
- [x] Quickstart scripts for macOS, Linux and Windows, and a web dashboard (`hive open`) backed by a REST and server-sent events API
- [x] Live end-to-end specs that run a real queen and check her results against ground truth (`core/tests/e2e`)
- [x] CI on Ubuntu and Windows that runs the core, framework and tools test suites

## Still open

- [ ] **Spend limits in dollars.** Every model call is metered, but nothing stops a run at a dollar amount yet. A `cost_guard` pipeline stage exists, but nothing feeds it a cost estimate.
- [ ] **Enterprise secret managers.** Credentials live in the encrypted local store or in environment variables. There's no backend for HashiCorp Vault, AWS Secrets Manager, GCP Secret Manager or Azure Key Vault.
- [ ] **Packages.** Hive installs from a clone with the quickstart. There's no PyPI package (`pip install -e .` installs a placeholder) and no Docker image.
- [ ] **Semantic memory search.** Recall and `search_messages` match keywords; there's no embedding search.
- [ ] **A JavaScript/TypeScript SDK.**

## Retired in V1

- **The graph executor**, with its nodes, edges and shared data buffer. The agent loop, `run_worker` and the tracker replace it.
- **The terminal UI.** Use the web dashboard (`hive open`).
- **Bundled MCP server subprocesses**, including `gcu-tools`. Built-in tools now run inside Hive, and the browser runs through the `hive-browser` CLI.
- **The automatic queen router.** You choose the queen that takes a task.
- **The example agent templates and the credential tester.**
