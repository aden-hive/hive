# Integration Bounty Program

Earn XP, Discord roles, and money by testing, documenting, and building integrations for the Aden agent framework.

## Why Contribute?

**Your name in the product.** When you promote a tool to verified, your GitHub handle goes in the tool's README under `Contributed by`. Every agent that uses that integration carries your name — permanent credit in a production codebase.

**Visible status.** Your Discord tier role is earned, not bought. When you answer a question in `#integrations-help` with a Core Contributor badge, people listen.

**Weekly races.** Every Monday the bot posts the leaderboard. Top 3 get medal emojis. The best work gets highlighted in announcements.

**The path to paid.** Core Contributor unlocks real money. It takes sustained quality work across testing, docs, and code — the scarcity makes it matter.

## How It Works

1. Pick a bounty from the [GitHub issues board](https://github.com/adenhq/hive/issues?q=is%3Aissue+is%3Aopen+label%3A%22bounty%3A*%22)
2. Claim it by commenting on the issue
3. Do the work and submit a PR (or test report)
4. A maintainer reviews and merges
5. You automatically get XP in Discord via Lurkr
6. At certain levels, you unlock roles. At the top tier, you unlock paid bounties.

## Tiers

| Tier                        | How to Reach               | Rewards                                                       |
| --------------------------- | -------------------------- | ------------------------------------------------------------- |
| **Agent Builder**           | ~500 XP (Lurkr level 5)    | Discord role, bounty board access                             |
| **Open Source Contributor** | ~2,000 XP (Lurkr level 15) | Discord role, name in CONTRIBUTORS.md and tool READMEs        |
| **Core Contributor**        | Maintainer-approved        | Monetary payout per bounty, private `#bounty-payouts` channel |

Lurkr auto-assigns the first two roles. Core Contributor requires sustained, quality contributions across multiple bounty types and a maintainer vouching for you.

## Bounty Types

| Type                  | Label             | Points | What You Do                                                                |
| --------------------- | ----------------- | ------ | -------------------------------------------------------------------------- |
| **Test a tool**       | `bounty:test`     | 20     | Test with a real API key, submit a report with logs                        |
| **Write docs**        | `bounty:docs`     | 20     | Write a README following the [template](templates/tool-readme-template.md) |
| **Code contribution** | `bounty:code`     | 30     | Add health checker, fix a bug, or improve an integration                   |
| **New integration**   | `bounty:new-tool` | 75     | Build a complete integration from scratch                                  |

Promoting a tool from unverified to verified is the final step — submit a PR moving it from `_register_unverified()` to `_register_verified()` after the [promotion checklist](promotion-checklist.md) is complete.

## Quality Gates

- **PRs** must be merged by a maintainer (not self-merged)
- **Test reports** must follow the [test report template](templates/agent-test-report-template.md) with logs or session ID
- **READMEs** must follow the [tool README template](templates/tool-readme-template.md)
- **Claim before you start** — comment on the issue, wait for assignment
- No self-review, no splitting one change across multiple PRs, no AI-only submissions without verification

## Labels

| Label               | Color              | Meaning                                 |
| ------------------- | ------------------ | --------------------------------------- |
| `bounty:test`       | `#1D76DB` (blue)   | Test a tool with a real API key         |
| `bounty:docs`       | `#FBCA04` (yellow) | Write or improve documentation          |
| `bounty:code`       | `#D93F0B` (orange) | Health checker, bug fix, or improvement |
| `bounty:new-tool`   | `#6F42C1` (purple) | Build a new integration from scratch    |
| `difficulty:easy`   | `#BFD4F2`          | Good first contribution                 |
| `difficulty:medium` | `#D4C5F9`          | Requires some familiarity               |
| `difficulty:hard`   | `#F9D0C4`          | Significant effort or expertise needed  |

## Discord

```
#integrations-announcements  — Bounties, leaderboard, tool promotions (bot + admin only)
#integrations-help           — Questions, testing coordination, showcases
#bounty-payouts              — Dollar values and payout tracking (Core Contributors only)
```

## Leaderboard

Weekly leaderboard auto-posts to `#integrations-announcements` every Monday. Top 3 get medal emojis. Check your rank anytime with `/rank` in Discord.

XP comes from two sources: GitHub bounties (auto-pushed on PR merge) and Discord activity in `#integrations-help`.

## Launch Plan: The 55-Tool Blitz

A 2-week sprint to get all 55 unverified tools tested, documented, and health-checked.

### Day 1: Post Everything

- **41 `bounty:docs` issues** — tools missing READMEs, `difficulty:easy`, 20 pts each
- **40 `bounty:code` issues** — tools missing health checkers, `difficulty:medium`, 30 pts each
- **55 `bounty:test` issues** — one per unverified tool, `difficulty:medium`, 20 pts each

### Week 1-2

All bounty types open in parallel. Contributors self-select. Daily progress updates in `#integrations-announcements`. Day 14 wrap-up with final leaderboard and shoutouts.

## Automation

```
PR merged with bounty:* label
  → GitHub Action runs bounty-tracker.ts
  → Calculates points from label
  → Resolves GitHub → Discord ID via contributors.yml
  → Pushes XP to Lurkr API
  → Posts notification to #integrations-announcements
```

See the [Setup Guide](setup-guide.md) for full configuration (Lurkr, webhooks, secrets, labels).

### Identity Linking

Contributors link GitHub ↔ Discord by opening a [Link Discord Account](https://github.com/aden-hive/hive/issues/new?template=link-discord.yml) issue. A GitHub Action auto-adds them to `contributors.yml` and closes the issue.

Without this link, bounties are still tracked but Lurkr can't push XP to your Discord account.

### What Handles What

| Concern                  | Handled By                 | How                                             |
| ------------------------ | -------------------------- | ----------------------------------------------- |
| Bounty point calculation | GitHub Actions             | `bounty-completed.yml` reads PR labels          |
| XP push to Discord       | GitHub Actions → Lurkr API | `PATCH /levels/{guild}/users/{user}`            |
| Discord engagement XP    | Lurkr bot                  | Native message XP (configurable per-channel)    |
| Leaderboard              | Lurkr bot + GitHub Actions | `/leaderboard` in Discord + weekly webhook post |
| Agent Builder role       | Lurkr bot                  | Auto-assigned at level 5                        |
| OSS Contributor role     | Lurkr bot                  | Auto-assigned at level 15                       |
| Core Contributor role    | Maintainer                 | Manual (involves money)                         |
| Identity linking         | contributors.yml           | PR-based, reviewed by maintainers               |

## Guides

- **[Setup Guide](setup-guide.md)** — Admin setup from zero to running
- **[Game Master Manual](game-master-manual.md)** — Maintainer operations
- **[Contributor Guide](contributor-guide.md)** — Everything a contributor needs to start

## Reference

- [Promotion Checklist](promotion-checklist.md) — Criteria for unverified → verified
- [Tool README Template](templates/tool-readme-template.md)
- [Agent Test Report Template](templates/agent-test-report-template.md)
- [Building Tools Guide](../tools/BUILDING_TOOLS.md)
- [Lurkr API Docs](https://lurkr.gg/docs/api)

### Automation Files

- `.github/workflows/bounty-completed.yml` — PR merge → XP push + Discord notification
- `.github/workflows/weekly-leaderboard.yml` — Monday leaderboard post
- `scripts/bounty-tracker.ts` — Point calculation, Lurkr API, Discord formatting
- `scripts/setup-bounty-labels.sh` — One-time label setup
- `contributors.yml` — GitHub ↔ Discord identity mapping
