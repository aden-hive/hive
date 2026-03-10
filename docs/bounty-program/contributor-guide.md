# Contributor Guide — Integration Bounty Program

Earn XP, Discord roles, and eventually real money by testing and building integrations for the Aden agent framework.

## Getting Started

### 1. Link your GitHub and Discord

Open a [Link Discord Account](https://github.com/aden-hive/hive/issues/new?template=link-discord.yml) issue — just paste your Discord ID and submit. A GitHub Action will automatically add you to `contributors.yml` and close the issue.

To find your Discord ID: Discord Settings > Advanced > Enable **Developer Mode**, then right-click your name > **Copy User ID**.

Without this link, Lurkr can't push XP to your Discord account.

### 2. Pick your first bounty

Browse [GitHub Issues with bounty labels](https://github.com/adenhq/hive/issues?q=is%3Aissue+is%3Aopen+label%3A%22bounty%3A*%22). Start with `bounty:docs` or `difficulty:easy`.

Comment "I'd like to work on this" and wait for a maintainer to assign you.

## Tiers

| Tier | How to Reach | What You Get |
|------|-------------|--------------|
| **Agent Builder** | ~500 XP (Lurkr level 5) | Discord role, bounty board access |
| **Open Source Contributor** | ~2,000 XP (Lurkr level 15) | Discord role, name in CONTRIBUTORS.md and tool READMEs |
| **Core Contributor** | Maintainer nomination | Dollar values on bounties, paid per completion |

XP comes from GitHub bounties (auto-pushed on PR merge) and Discord activity in `#integrations-help`.

## Bounty Types

### Test a Tool (20 pts)

Test an unverified tool with a real API key and report what happens.

1. Get an API key for the service (the bounty issue links to where)
2. Run the tool functions with real data
3. Fill out the [test report template](templates/agent-test-report-template.md)
4. Submit as a comment on the issue or a file in a PR

Report both successes and failures. Finding bugs is valuable.

### Write Docs (20 pts)

Write a README for a tool that's missing one.

1. Read the tool's source code in `tools/src/aden_tools/tools/{tool_name}/`
2. Read the credential spec in `tools/src/aden_tools/credentials/`
3. Fill in the [tool README template](templates/tool-readme-template.md)
4. Submit a PR adding `README.md` to the tool directory

Function names and API URLs must match reality — no AI hallucinations.

### Code Contribution (30 pts)

Add a health checker, fix a bug, or improve an integration.

**Health checker:**
1. Find a lightweight API endpoint that validates the credential (GET, no writes)
2. Add `health_check_endpoint` to the tool's CredentialSpec
3. Implement a HealthChecker class in `tools/src/aden_tools/credentials/health_check.py`
4. Register in `HEALTH_CHECKERS`, run `uv run pytest tools/tests/test_credential_registry.py`

**Bug fix:**
1. Find a bug during testing, file an issue
2. Fix it in a PR with a test covering the bug

### New Integration (75 pts)

Build a complete integration from scratch.

1. Follow the [BUILDING_TOOLS.md](../tools/BUILDING_TOOLS.md) guide
2. Create: tool + credential spec + health checker + tests + README
3. Register in `_register_unverified()` in `tools/__init__.py`
4. Run `make check && make test`

Expect multiple review rounds.

## Rules

1. **Claim before you start** — comment on the issue, wait for assignment
2. **7-day window** — no PR within 7 days = bounty gets re-opened
3. **Max 3 active claims** — don't hoard bounties
4. **Quality matters** — PRs must pass CI and follow templates
5. **No self-review** and no AI-only submissions without verification

## FAQ

**Q: Do I need an API key for every tool I test?**
A: Yes. Most services have free tiers. The bounty issue links to where you get the key.

**Q: How do I become a Core Contributor?**
A: Contribute consistently across different bounty types for 4+ weeks. Maintainers will nominate you.

**Q: What if I haven't linked my Discord yet?**
A: You'll still get credit in GitHub, but no Lurkr XP or Discord roles. Add yourself to `contributors.yml`.

## Quick Reference

| What | Where |
|------|-------|
| Bounty board | [GitHub Issues](https://github.com/adenhq/hive/issues?q=is%3Aissue+is%3Aopen+label%3A%22bounty%3A*%22) |
| README template | [templates/tool-readme-template.md](templates/tool-readme-template.md) |
| Test report template | [templates/agent-test-report-template.md](templates/agent-test-report-template.md) |
| Promotion checklist | [promotion-checklist.md](promotion-checklist.md) |
| Building tools | [BUILDING_TOOLS.md](../tools/BUILDING_TOOLS.md) |
| Discord | [Join](https://discord.com/invite/MXE49hrKDk) |
| Your rank | `/rank` in Discord |
