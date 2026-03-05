# Integration Bounty Program

Gamified contribution program for expanding and hardening Aden's integration ecosystem. Community members earn points by testing, documenting, and building integrations — with monetary rewards unlocked at the Core Contributor tier.

## Why Contribute?

### Visible Status

Every Discord message you send shows your tier role and badges. When someone asks a question in `#integrations-help` and you answer it with a **Core Contributor** badge, people listen. Your role is earned, not bought.

### Your Name in the Product

When you promote a tool to verified, your GitHub handle goes in the tool's README under `Contributed by`. Every agent that uses that integration carries your name. This is permanent credit in a production codebase — not a profile badge that disappears.

### Weekly Races

Every Monday the bot posts the leaderboard. The top 3 get medal emojis next to their name all week. There's a `#integration-showcase` channel where people demo agents using the tools they tested — the best demos get pinned and highlighted in announcements.

### The Path to Paid

Core Contributor unlocks real money. But you can't buy your way in — it takes sustained quality work across testing, docs, and code. The scarcity makes it matter. When you see someone with Core Contributor status, you know they've shipped real integrations.

### Streaks

Consecutive weeks with at least one bounty completion earns streak multipliers:

| Streak | Multiplier | Example |
|--------|-----------|---------|
| 2 weeks | 1.1x | 20pt README = 22 pts |
| 4 weeks | 1.25x | 30pt agent test = 37 pts |
| 8+ weeks | 1.5x | 75pt new tool = 112 pts |

Missing a week resets the streak. This rewards consistency over bursts.

### Achievement Badges

Unlocked permanently and displayed on your Discord profile via bot roles:

| Badge | Requirement | Role Color |
|-------|-------------|------------|
| **First Blood** | Complete your first bounty | — |
| **Bug Hunter** | Find and fix 3 bugs via testing | Red |
| **Docs Champion** | Write 5 tool READMEs | Yellow |
| **Health Inspector** | Add 5 health checkers | Orange |
| **Promoter** | Promote a tool from unverified to verified | Gold |
| **Full Stack** | Complete at least 1 bounty of every type | Rainbow |
| **Ironman** | 8-week contribution streak | — |

## Tiers

| Tier | How to Reach | What You See | Rewards |
|------|-------------|--------------|---------|
| **Agent Builder** | Join Discord + start testing | Bounty board with point values | Discord role, community recognition, achievement badges |
| **Open Source Contributor** | First merged PR | Bounty board with point values | Discord role, listed in CONTRIBUTORS.md, name in tool READMEs |
| **Core Contributor** | Maintainer-approved promotion | Bounty board with **dollar values** | Monetary payout per completed bounty, private dev channel |

### Core Contributor Promotion

Core Contributor status is **maintainer-approved** and requires:

1. **Sustained contribution** — consistent activity over multiple weeks, not a one-time burst
2. **Breadth** — contributions across multiple activity types (not just 20 READMEs)
3. **Quality** — history of clean PRs that pass CI without excessive back-and-forth
4. **Maintainer nomination** — at least one maintainer vouches for the contributor

Core Contributors see dollar values on bounty issues via a private Discord channel. Payouts happen per completed bounty after the PR is merged and approved by a maintainer.

## Point System

### Testing (Highest Priority)

These are the most valuable contributions — testing integrations with real API keys and real agents is the bottleneck for promoting tools from unverified to verified.

| Activity | Points | Requirements |
|----------|--------|-------------|
| **Smoke Test** | 10 | Run a tool with a real API key, submit a pass/fail report with logs |
| **Agent Test Report** | 30 | Build an agent using an unverified tool, submit a structured test report with session ID |
| **Edge Case Report** | 15 | Document a specific edge case (rate limits, auth expiry, malformed data, etc.) |
| **Live Demo** | 25 | Record a short video/GIF of an integration working in an agent |

### Code Contributions

| Activity | Points | Requirements |
|----------|--------|-------------|
| **Bug Fix PR** | 40 | Fix a bug found during testing, merged PR |
| **Add Health Checker** | 25 | Implement health check class + register in HEALTH_CHECKERS, merged PR |
| **Add health_check_endpoint** | 10 | Research correct endpoint, add to CredentialSpec, merged PR |
| **Write README** | 20 | Add missing README following the [tool README template](templates/tool-readme-template.md), merged PR |
| **Complete Promotion Checklist** | 50 | Finish all items on the [promotion checklist](promotion-checklist.md) for a tool, merged PR |
| **New Integration** | 75 | Full implementation (tool + credential spec + tests + docs), merged PR |

### Community

| Activity | Points | Requirements |
|----------|--------|-------------|
| **PR Review** | 15 | Substantive code review on an integration PR (not just "LGTM") |
| **Help in Discord** | 5 | Answer an integration question (mod-verified) |
| **Propose Integration** | 5 | File a well-structured `[Integration]:` issue per existing template |

## Quality Gates

Points are only awarded after quality verification:

- **PRs**: Must be merged by a maintainer (not self-merged)
- **Test reports**: Must follow the [test report template](templates/agent-test-report-template.md) with reproducible evidence (logs, session ID, screenshots)
- **Health checkers**: Must pass CI (`uv run pytest tools/tests/test_credential_registry.py`)
- **READMEs**: Must follow the [tool README template](templates/tool-readme-template.md)
- **Reviews**: Must include actionable feedback, not just approval
- **Bounties are claimed before work starts** — comment on the issue to claim, wait for maintainer assignment

### Anti-Gaming Rules

- No self-review on PRs
- A different maintainer must approve bounty completion than the one who created it
- Duplicate or near-duplicate submissions are rejected
- Low-effort submissions (copy-pasted from AI without verification) are rejected and may result in point deduction
- Splitting a single change across multiple PRs to farm points is not allowed

## Bounty Issues

Integration bounties are tracked as GitHub Issues with specific labels.

### Labels

| Label | Color | Meaning |
|-------|-------|---------|
| `bounty:smoke-test` | `#0E8A16` (green) | Run tool with real API key, report results |
| `bounty:agent-test` | `#1D76DB` (blue) | Test tool in a real agent workflow |
| `bounty:docs` | `#FBCA04` (yellow) | Write or improve documentation |
| `bounty:health-check` | `#D93F0B` (orange) | Add health check endpoint or checker |
| `bounty:bug-fix` | `#B60205` (red) | Fix a discovered bug |
| `bounty:new-tool` | `#6F42C1` (purple) | Build a new integration from scratch |
| `bounty:promote` | `#C2A000` (gold) | Complete full promotion checklist |
| `difficulty:easy` | `#BFD4F2` | Good first contribution |
| `difficulty:medium` | `#D4C5F9` | Requires some familiarity |
| `difficulty:hard` | `#F9D0C4` | Significant effort or expertise needed |

### Bounty Issue Structure

Each bounty issue includes:
- **Activity type** (label)
- **Difficulty** (label)
- **Point value** (visible to all in issue body)
- **Dollar value** (visible only to Core Contributors via private Discord channel)
- **Acceptance criteria** (what "done" looks like)
- **Relevant files** (links to the tool directory, credential spec, etc.)

See the [bounty issue template](../.github/ISSUE_TEMPLATE/integration-bounty.yml) for the standard format.

## Discord Structure

```
#integrations-announcements  — New bounties, tool promotions, leaderboard updates
#integrations-testing        — Coordinate who's testing what, share test reports
#integrations-help           — Get help with credential setup, tool development
#integration-showcase        — Demos of agents using integrations

# Private (Core Contributors only)
#bounty-payouts              — Dollar values, payout tracking, claims
```

## Leaderboard

Weekly leaderboard posted to `#integrations-announcements`:
- Top 10 contributors by points (rolling 30 days)
- Top 10 contributors all-time
- Recently promoted tools (unverified -> verified)
- Number of open bounties by type

Tracking is done via GitHub labels on merged PRs and closed issues. Maintainers tag completed work with the appropriate `bounty:*` label and contributor handle.

## Launch Plan: The 55-Tool Blitz

The initial launch targets the 55 unverified tools that need testing, documentation, and health checks.

### Phase 1: Doc Sprint (Week 1-2)

- Post 41 `bounty:docs` issues for tools missing READMEs
- `difficulty:easy`, 20 points each
- Provide the [tool README template](templates/tool-readme-template.md) so contributors fill in the blanks

### Phase 2: Health Check Sprint (Week 2-3)

- Post 40 `bounty:health-check` issues for tools missing health check endpoints
- `difficulty:medium`, 25 points each
- Provide example health checker code in each issue

### Phase 3: Agent Test Sprint (Week 3-5)

- Post 55 `bounty:agent-test` issues — one per unverified tool
- `difficulty:medium`, 30 points each
- Provide a template agent that contributors can swap their tool into

### Phase 4: Promotion Sprint (Week 5-8)

- Post `bounty:promote` issues for tools that have completed docs + health checks + testing
- `difficulty:hard`, 50 points each
- The contributor who completes the final checklist item gets the promotion bonus
- Each promoted tool gets an announcement in `#integrations-announcements`

## Automation

The bounty program runs on **GitHub Actions + Lurkr bot + Discord webhooks**. GitHub Actions calculate points from merged PRs, push XP to Lurkr via its API, and post notifications. Lurkr handles the Discord leveling, leaderboard display, and automatic role assignments.

### How It Works

```
PR merged with bounty:* label
  → GitHub Action fires bounty-tracker.ts
  → Script calculates points from label
  → Script resolves GitHub → Discord ID via contributors.yml
  → Script calls Lurkr API: PATCH /levels/{guild}/users/{user} (+XP)
  → Lurkr auto-assigns role rewards at XP thresholds
  → Script posts Discord webhook notification to #integrations-announcements
```

One system, one leaderboard, one set of roles. Discord activity XP and GitHub bounty XP flow into the same Lurkr leveling system.

### GitHub Actions

| Workflow | Trigger | What It Does |
|----------|---------|-------------|
| `bounty-completed.yml` | PR merged with `bounty:*` label | Calculates points, pushes XP to Lurkr, posts Discord notification |
| `weekly-leaderboard.yml` | Every Monday 9:00 UTC (or manual) | Generates leaderboard from all merged bounty PRs, posts to Discord |

Both use `scripts/bounty-tracker.ts` (Bun/TypeScript) which:
- Reads `bounty:*` labels from merged PRs to calculate points
- Resolves GitHub username → Discord ID via `contributors.yml`
- Calls Lurkr API to atomically increment XP: `PATCH /levels/{guildId}/users/{userId}` with `{"xp": {"increment": N}}`
- Posts formatted messages to Discord via webhook

### Lurkr Bot Setup

[Lurkr](https://lurkr.gg/) is a free, no-paywall leveling bot with a full REST API that accepts external XP pushes — the only major leveling bot that supports this.

#### 1. Invite Lurkr to your Discord server

Go to https://lurkr.gg/ and invite the bot.

#### 2. Enable leveling

```
/levels enable
```

#### 3. Configure XP for Discord activity

Lurkr will also award XP for regular Discord messages. Configure this so Discord engagement and GitHub bounties both feed into the same system:

- Set message XP range (e.g., 15-25 XP per message)
- Set cooldown (e.g., 60 seconds — prevents spam farming)
- Optionally boost XP in `#integrations-help` and `#integrations-testing` channels so helping others earns more

```
/levels set-xp min:15 max:25
/levels set-cooldown seconds:60
/levels multiplier channel:#integrations-help multiplier:2
/levels multiplier channel:#integrations-testing multiplier:1.5
```

#### 4. Configure role rewards

Map Lurkr levels to your existing Discord tiers. The XP thresholds should be calibrated so that a mix of Discord activity and GitHub bounties is needed to level up.

| Lurkr Level | XP Threshold | Discord Role | How to Reach |
|-------------|-------------|-------------|-------------|
| 5 | ~500 XP | **Agent Builder** | A few bounties or active Discord participation |
| 15 | ~2,000 XP | **Open Source Contributor** | Sustained bounty contributions |
| 30 | ~5,000 XP | Core Contributor *eligible* | Significant sustained contribution |

Note: **Core Contributor** role is still manually assigned by maintainers (since it involves money). Lurkr level 30 signals eligibility, not automatic promotion.

Add role rewards in the Lurkr dashboard or via commands:

```
/levels role-reward add level:5 role:@Agent Builder
/levels role-reward add level:15 role:@Open Source Contributor
```

Achievement badge roles (First Blood, Bug Hunter, etc.) are added manually by maintainers when someone qualifies — these are not level-based.

#### 5. Generate a Read/Write API key

- Go to https://lurkr.gg/ and log in
- Navigate to your profile / API settings
- Create a **Read/Write** API key (not read-only — we need PATCH access)
- Copy the key

#### 6. Add secrets to GitHub repository

Add three secrets in **Repo Settings > Secrets and variables > Actions**:

| Secret | Value |
|--------|-------|
| `DISCORD_BOUNTY_WEBHOOK_URL` | Discord webhook URL for `#integrations-announcements` |
| `LURKR_API_KEY` | Your Lurkr Read/Write API key |
| `LURKR_GUILD_ID` | Your Discord server ID |

To find your server ID: Enable Developer Mode in Discord (Settings > Advanced), then right-click the server name > Copy Server ID.

#### 7. Create the labels and start posting bounties

```bash
./scripts/setup-bounty-labels.sh
```

That's it. When a maintainer merges a PR with a `bounty:*` label, the contributor automatically gets:
- XP added to their Lurkr level
- A notification in `#integrations-announcements` with their new level
- Role upgrades when they cross level thresholds

### Identity Linking (GitHub ↔ Discord)

Contributors link their accounts by adding themselves to `contributors.yml` at the repo root:

```yaml
contributors:
  - github: jane-doe
    discord: "123456789012345678"
    name: Jane Doe
```

This is intentionally a file-in-repo approach (not a database) because:
- It's version-controlled and auditable
- Adding yourself is a PR — which is itself a contribution
- No bot infrastructure needed for identity storage
- Maintainers can review and approve linkages

**To find your Discord ID:** Enable Developer Mode in Discord Settings > Advanced, then right-click your name > Copy User ID.

**Important:** Contributors who haven't linked their Discord ID in `contributors.yml` will still get bounty notifications on GitHub, but won't receive Lurkr XP or Discord pings. The notification will remind them to link.

### What Handles What

| Concern | Handled By | How |
|---------|-----------|-----|
| Bounty point calculation | GitHub Actions | `bounty-completed.yml` reads PR labels |
| XP push to Discord | GitHub Actions → Lurkr API | `PATCH /levels/{guild}/users/{user}` with `{"xp": {"increment": N}}` |
| Discord engagement XP | Lurkr bot | Native message XP (configurable per-channel) |
| Leaderboard | Lurkr bot | Built-in `/levels leaderboard` + web leaderboard |
| Weekly announcement | GitHub Actions | `weekly-leaderboard.yml` posts via webhook |
| Agent Builder role | Lurkr bot | Auto-assigned at level 5 via role reward |
| OSS Contributor role | Lurkr bot | Auto-assigned at level 15 via role reward |
| Core Contributor role | Maintainer | Manual (involves money, level 30 = eligible) |
| Achievement badges | Maintainer | Manual role assignment when criteria met |
| Streak tracking | GitHub Actions | `bounty-tracker.ts` calculates from PR merge dates |
| Identity linking | contributors.yml | PR-based, reviewed by maintainers |
| Discord notifications | GitHub Actions | Webhook post to `#integrations-announcements` |

## Guides

- **[Setup Guide](setup-guide.md)** — Complete admin setup from zero to running (30 min)
- **[Game Master Manual](game-master-manual.md)** — Maintainer operations: posting bounties, reviewing work, managing tiers, anti-gaming
- **[Contributor Guide](contributor-guide.md)** — Everything a contributor needs to start earning XP and completing bounties

## Reference

- [Integration Promotion Checklist](promotion-checklist.md) — Formal criteria for unverified -> verified
- [Tool README Template](templates/tool-readme-template.md) — Standard format for tool documentation
- [Agent Test Report Template](templates/agent-test-report-template.md) — Standard format for test reports
- [Building Tools Guide](../tools/BUILDING_TOOLS.md) — How to build integrations
- [Parent Issue #2805](https://github.com/adenhq/hive/issues/2805) — Master integration tracking issue
- [Lurkr API Docs](https://lurkr.gg/docs/api) — API reference for XP push
- [Lurkr Leveling Setup](https://lurkr.gg/docs/guides/setting-up-server-leveling) — Bot configuration guide

### Automation Files

- `.github/workflows/bounty-completed.yml` — PR merge → Lurkr XP push + Discord notification
- `.github/workflows/weekly-leaderboard.yml` — Monday leaderboard post
- `scripts/bounty-tracker.ts` — Point calculation, Lurkr API integration, Discord formatting
- `scripts/setup-bounty-labels.sh` — One-time label setup
- `contributors.yml` — GitHub ↔ Discord identity mapping
