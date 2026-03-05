# Contributor Guide — Integration Bounty Program

Welcome. This is a program where you earn XP, Discord roles, and eventually real money by testing and building integrations for the Aden agent framework.

## How It Works

1. You pick a bounty from the [GitHub issues board](https://github.com/adenhq/hive/issues?q=is%3Aissue+is%3Aopen+label%3A%22bounty%3A*%22)
2. You claim it by commenting on the issue
3. You do the work and submit a PR (or test report)
4. A maintainer reviews and merges
5. You automatically get XP in Discord via Lurkr, and your level goes up
6. At certain levels, you unlock roles. At the top tier, you unlock paid bounties.

## Getting Started (10 min)

### 1. Link your GitHub and Discord

Fork this repo and add yourself to `contributors.yml`:

```yaml
contributors:
  # ... existing entries
  - github: your-github-username
    discord: "your-discord-id"
    name: Your Name
```

To find your Discord ID:
1. Open Discord Settings > Advanced > Enable **Developer Mode**
2. Right-click your name in any channel > **Copy User ID**

Submit this as a PR with title: `docs: link @your-github to Discord`

**Why this matters:** Without this link, you'll still get points tracked, but Lurkr can't push XP to your Discord account and you won't get role upgrades or pings.

### 2. Join the Discord channels

- `#integrations-announcements` — Bounty postings, leaderboard, promotions
- `#integrations-testing` — Coordinate with other testers
- `#integrations-help` — Ask questions about tools, credentials, setup
- `#integration-showcase` — Show off what you built

### 3. Pick your first bounty

Filter GitHub issues by label:
- [`bounty:docs`](https://github.com/adenhq/hive/issues?q=is%3Aissue+is%3Aopen+label%3A%22bounty%3Adocs%22) — Write a README for a tool (20 pts, easiest)
- [`bounty:smoke-test`](https://github.com/adenhq/hive/issues?q=is%3Aissue+is%3Aopen+label%3A%22bounty%3Asmoke-test%22) — Test a tool with a real API key (10 pts)
- [`difficulty:easy`](https://github.com/adenhq/hive/issues?q=is%3Aissue+is%3Aopen+label%3A%22difficulty%3Aeasy%22) — All easy bounties

Comment on the issue: "I'd like to work on this" and wait for a maintainer to assign you (usually within 24 hours).

## Tiers

| Tier | How to Reach | What You Get |
|------|-------------|--------------|
| **Agent Builder** | ~500 XP (Lurkr level 5) | Discord role, bounty board access |
| **Open Source Contributor** | ~2,000 XP (Lurkr level 15) | Discord role, name in CONTRIBUTORS.md and tool READMEs |
| **Core Contributor** | Maintainer nomination | Dollar values on bounties, paid per completion |

Lurkr auto-assigns the first two roles when you hit the level. Core Contributor requires sustained, high-quality contributions and a maintainer vouching for you.

### How XP Adds Up

You earn XP from two sources:

| Source | How |
|--------|-----|
| **GitHub bounties** | Merge a PR with a `bounty:*` label — auto-pushed to Lurkr |
| **Discord activity** | Messages in `#integrations-*` channels, helping others, voice chat |

Both feed into the same Lurkr level. Helping people in Discord AND doing bounties levels you up faster than either alone.

## Bounty Types

### Smoke Test (10 pts)

**What:** Run an unverified tool with a real API key and report if it works.

**How:**
1. Pick a tool from the bounty board
2. Get an API key for that service (the bounty issue links to the help URL)
3. Set the environment variable: `export TOOL_API_KEY=your-key`
4. Run the tool functions and note what happens
5. Comment on the bounty issue with your results: pass/fail, any errors, logs

**Difficulty:** Easy. You don't need to write code, just test and report.

### Agent Test Report (30 pts)

**What:** Build a real agent that uses an unverified tool and document the experience.

**How:**
1. Pick a tool from the bounty board
2. Build a simple agent that uses the tool (see [Building Agents Guide](../tools/BUILDING_TOOLS.md))
3. Run the agent with a real task
4. Fill out the [test report template](templates/agent-test-report-template.md)
5. Submit the report as a comment on the bounty issue, or as a file in a PR

**What to include:** Environment, credential setup, which functions you tested, what worked, what broke, edge cases found, and logs or session ID.

**Difficulty:** Medium. Requires an API key and some familiarity with the framework.

### Write README (20 pts)

**What:** Write documentation for a tool that's missing its README.

**How:**
1. Pick a tool from the bounty board
2. Read the tool's source code in `tools/src/aden_tools/tools/{tool_name}/`
3. Read the credential spec in `tools/src/aden_tools/credentials/`
4. Fill in the [tool README template](templates/tool-readme-template.md)
5. Submit a PR adding `README.md` to the tool directory

**Quality bar:** Function names must match the actual code. Setup instructions must be accurate. API URLs must be real.

**Difficulty:** Easy. Good first bounty — you learn the codebase by reading and documenting it.

### Add Health Checker (25 pts)

**What:** Implement a credential health check so the system can validate API keys at startup.

**How:**
1. Pick a tool from the bounty board
2. Find a lightweight API endpoint that validates the credential (GET, no writes, no charges)
3. Add `health_check_endpoint` to the tool's CredentialSpec
4. Implement a HealthChecker class in `tools/src/aden_tools/credentials/health_check.py`
5. Register it in the `HEALTH_CHECKERS` dict
6. Run `uv run pytest tools/tests/test_credential_registry.py` to verify wiring
7. Submit a PR

**Difficulty:** Medium. Requires reading the service's API docs to find the right endpoint.

### Bug Fix (40 pts)

**What:** Find a bug during testing and fix it.

**How:**
1. Find a bug while doing a smoke test or agent test
2. File an issue describing the bug (or comment on the existing bounty issue)
3. Fix the bug in a PR
4. Add a test that covers the specific bug
5. Reference the bounty issue in your PR

**Difficulty:** Varies. The bug itself tells you the difficulty.

### New Integration (75 pts)

**What:** Build a complete new integration from scratch.

**How:**
1. Check the [Integration Request issues](https://github.com/adenhq/hive/issues?q=is%3Aissue+is%3Aopen+label%3A%22Integration%22) for requested integrations
2. Follow the [BUILDING_TOOLS.md](../tools/BUILDING_TOOLS.md) guide
3. Create: tool implementation + credential spec + health checker + tests + README
4. Register in `_register_unverified()` in `tools/__init__.py`
5. Run `make check && make test`
6. Submit a PR

**Difficulty:** Hard. This is a significant contribution — expect multiple review rounds.

### Complete Promotion Checklist (50 pts)

**What:** Take an unverified tool through the full [promotion checklist](promotion-checklist.md) to make it verified.

**How:**
1. Pick a tool that has most checklist items already done (docs, health check, tests)
2. Complete the remaining items
3. Get at least 1 community test report (coordinate in `#integrations-testing`)
4. Submit a PR that moves the tool from `_register_unverified()` to `_register_verified()`
5. Include links to all checklist evidence in the PR description

**Difficulty:** Hard. Requires coordination and thoroughness.

## Achievement Badges

Permanent Discord roles earned through specific accomplishments:

| Badge | How to Earn |
|-------|-------------|
| **First Blood** | Complete your first bounty of any type |
| **Bug Hunter** | Fix 3 bugs found during testing |
| **Docs Champion** | Write 5 tool READMEs |
| **Health Inspector** | Add 5 health checkers |
| **Promoter** | Promote a tool from unverified to verified |
| **Full Stack** | Complete at least 1 bounty of every type |
| **Ironman** | 8 consecutive weeks with at least 1 bounty completion |

Badges are assigned by maintainers when you qualify. If you think you've earned one and it hasn't been assigned, ask in `#integrations-help`.

## Streaks

Consecutive weeks with at least one bounty completion earns XP multipliers:

| Streak | Multiplier |
|--------|-----------|
| 2 weeks | 1.1x |
| 4 weeks | 1.25x |
| 8+ weeks | 1.5x |

Missing a week resets the streak. A 20-point README bounty at an 8-week streak earns 30 XP instead of 20.

## Leaderboard

Posted every Monday at 9:00 UTC in `#integrations-announcements`. Top 3 get medal emojis.

You can also check your rank anytime in Discord:
```
/rank
```

Or view the web leaderboard via Lurkr's dashboard.

## Rules

1. **Claim before you start** — comment on the issue, wait to be assigned
2. **One person per bounty** — first to claim and get assigned gets it
3. **7-day window** — if you don't submit a PR within 7 days of being assigned, the bounty is unassigned and re-opened
4. **Maximum 3 active claims** — don't hoard bounties
5. **Quality matters** — PRs must pass CI, follow templates, and address review feedback
6. **No self-review** — you can't review your own PR
7. **Honest testing** — report failures, not just successes. Finding bugs is valuable
8. **No AI-only submissions** — AI tools are fine for assistance, but you must verify that function names, API URLs, and behavior match reality

## FAQ

**Q: Do I need an API key for every tool I test?**
A: Yes, for smoke tests and agent tests. Most services have free tiers. The bounty issue links to where you get the key.

**Q: Can I work on multiple bounties at once?**
A: Yes, up to 3 active claims at a time.

**Q: What if I find a bug but can't fix it?**
A: File an issue! Someone else can pick up the `bounty:bug-fix`. Finding bugs during testing is the whole point.

**Q: How do I become a Core Contributor?**
A: Keep contributing consistently across different bounty types for 4+ weeks. Maintainers will notice and nominate you when you're ready. There's no application process — just keep shipping quality work.

**Q: What if I haven't linked my Discord yet?**
A: You'll still be recognized in the GitHub Action logs and Discord webhook message, but Lurkr can't push XP to your account. Link your Discord ID in `contributors.yml` to start earning XP and roles.

**Q: Do I earn XP from Discord messages too?**
A: Yes. Lurkr awards XP for messages in `#integrations-*` channels (with a 60-second cooldown). Helping others in `#integrations-help` earns 2x XP. Both Discord XP and GitHub bounty XP feed into the same level.

## Quick Reference

| What | Where |
|------|-------|
| Bounty board | [GitHub Issues with bounty label](https://github.com/adenhq/hive/issues?q=is%3Aissue+is%3Aopen+label%3A%22bounty%3A*%22) |
| README template | [docs/bounty-program/templates/tool-readme-template.md](templates/tool-readme-template.md) |
| Test report template | [docs/bounty-program/templates/agent-test-report-template.md](templates/agent-test-report-template.md) |
| Promotion checklist | [docs/promotion-checklist.md](promotion-checklist.md) |
| Building tools guide | [tools/BUILDING_TOOLS.md](../tools/BUILDING_TOOLS.md) |
| Contributing guide | [CONTRIBUTING.md](../CONTRIBUTING.md) |
| Discord | [Join](https://discord.com/invite/MXE49hrKDk) |
| Your rank | Type `/rank` in Discord |
| Link your accounts | Add yourself to [contributors.yml](../contributors.yml) |
