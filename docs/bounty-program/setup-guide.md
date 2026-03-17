# Integration Bounty Program — Setup Guide

Complete setup from zero to running. Estimated time: 30 minutes.

## Prerequisites

- Admin access to the GitHub repo
- Admin access to the Discord server
- `gh` CLI installed and authenticated

## Step 1: Create GitHub Labels (2 min)

```bash
./scripts/setup-bounty-labels.sh
```

This creates 11 labels: 4 integration bounty types (`bounty:test`, `bounty:docs`, `bounty:code`, `bounty:new-tool`), 4 standard bounty sizes (`bounty:small`, `bounty:medium`, `bounty:large`, `bounty:extreme`), and 3 difficulty levels (`difficulty:easy`, `difficulty:medium`, `difficulty:hard`).

## Step 2: Create Discord Channels (3 min)

```
Category: Integrations
  #integrations-announcements  (read-only for non-admins)
  #integrations-help

Category: Private
  #bounty-payouts  (visible only to Core Contributor role)
```

**Permissions:**

- `#integrations-announcements`: Everyone reads, only bots + admins post
- `#bounty-payouts`: Core Contributor role only

## Step 3: Create Discord Roles (2 min)

Order matters — higher = more prestigious:

| Role                    | Color            | Hoisted | Mentionable |
| ----------------------- | ---------------- | ------- | ----------- |
| Core Contributor        | Gold `#F1C40F`   | Yes     | Yes         |
| Open Source Contributor | Purple `#9B59B6` | Yes     | No          |
| Agent Builder           | Green `#2ECC71`  | Yes     | No          |

## Step 4: Install and Configure Lurkr (10 min)

### 4a. Invite Lurkr

Go to https://lurkr.gg/ and invite the bot. Grant requested permissions.

### 4b. Enable Leveling

In Discord, run:

```
/config toggle option:Leveling System
```

### 4c. Configure XP and Cooldown (Dashboard)

Lurkr configures XP range and cooldown through the web dashboard, not slash commands.

1. Go to https://lurkr.gg/dashboard and select your server
2. Open the **Leveling** category
3. Set **XP range** to min 15, max 25
4. Set **Cooldown** to 60 seconds

### 4d. Configure Channel Settings

Set `#integrations-help` as a leveling channel with a 2x multiplier, and exclude announcement/payout channels:

1. In the Lurkr dashboard **Leveling** settings, add `#integrations-help` as a leveling channel
2. Set a **channel multiplier** of 2x for `#integrations-help` using `/config set` (channel multiplier option)
3. Do NOT add `#integrations-announcements` or `#bounty-payouts` as leveling channels

### 4e. Configure Role Rewards

Use `/config set` to add role rewards:

1. Set `@Agent Builder` as a role reward at **level 5**
2. Set `@Open Source Contributor` as a role reward at **level 15**

Do NOT auto-assign Core Contributor — that's maintainer-only.

### 4f. Generate Lurkr API Key

1. Go to https://lurkr.gg/ and log in
2. Profile > API settings > Create API Key
3. Select **Read/Write** (not read-only)
4. Copy the key

## Step 5: Create Discord Webhook (2 min)

1. Server Settings > Integrations > Webhooks > New Webhook
2. Name: `Bounty Tracker`, channel: `#integrations-announcements`
3. Copy the webhook URL

## Step 6: Add GitHub Secrets (3 min)

Repo Settings > Secrets and variables > Actions:

| Secret                       | Value                      |
| ---------------------------- | -------------------------- |
| `DISCORD_BOUNTY_WEBHOOK_URL` | Webhook URL from Step 5    |
| `LURKR_API_KEY`              | Lurkr API key from Step 4f |
| `LURKR_GUILD_ID`             | Your Discord server ID\*   |

\*Enable Developer Mode in Discord, right-click server name > Copy Server ID.

## Step 7: Test the Pipeline (5 min)

```bash
GITHUB_TOKEN=$(gh auth token) \
GITHUB_REPOSITORY_OWNER=aden-hive \
GITHUB_REPOSITORY_NAME=hive \
bun run scripts/bounty-tracker.ts leaderboard
```

Then create a test PR with `bounty:docs` label, merge it, verify the Discord notification appears.

## Step 8: Seed the 55-Tool Blitz

Post all bounties at once on launch day:

**Documentation (41 issues):** `bounty:docs`, `difficulty:easy`, 20 pts
**Health checks (40 issues):** `bounty:code`, `difficulty:medium`, 30 pts
**Testing (55 issues):** `bounty:test`, `difficulty:medium`, 20 pts

### Tools missing READMEs

```
azure_sql, cloudinary, confluence, databricks, docker_hub, duckduckgo,
google_search_console, google_sheets, greenhouse, jira, kafka, lusha,
mongodb, notion, obsidian, pagerduty, pinecone, pipedrive, plaid,
pushover, quickbooks, redshift, sap, salesforce, shopify, snowflake,
supabase, terraform, tines, trello, twilio, twitter, vercel,
yahoo_finance, zoom, huggingface, langfuse, microsoft_graph, n8n,
powerbi, redis
```

## Verification Checklist

- [ ] Labels exist (`bounty:*` and `difficulty:*`)
- [ ] Discord channels and roles created
- [ ] Lurkr installed, leveling enabled, XP/cooldown configured in dashboard, role rewards set
- [ ] All 3 GitHub secrets added
- [ ] Both workflows enabled (`bounty-completed.yml`, `weekly-leaderboard.yml`)
- [ ] Test PR + merge triggers Discord notification
- [ ] `contributors.yml` exists at repo root

## Troubleshooting

**No Discord message:** Check `DISCORD_BOUNTY_WEBHOOK_URL` secret and Action logs.

**Lurkr XP not awarded:** Confirm API key is Read/Write, contributor is in `contributors.yml`, check Action logs for `Lurkr XP push failed`.

**Role not assigned:** Verify role rewards in the Lurkr dashboard or via `/config set`. Lurkr's role must be above the roles it assigns in server hierarchy.
