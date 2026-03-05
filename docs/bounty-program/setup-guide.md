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

This creates 10 labels: 7 bounty types (`bounty:smoke-test`, `bounty:agent-test`, `bounty:docs`, `bounty:health-check`, `bounty:bug-fix`, `bounty:new-tool`, `bounty:promote`) and 3 difficulty levels (`difficulty:easy`, `difficulty:medium`, `difficulty:hard`).

Verify at: `https://github.com/adenhq/hive/labels`

## Step 2: Create Discord Channels (5 min)

Create these channels (or rename existing ones):

```
Category: Integrations
  #integrations-announcements  (read-only for non-admins)
  #integrations-testing
  #integrations-help
  #integration-showcase

Category: Private
  #bounty-payouts  (visible only to Core Contributor role)
```

**Channel permissions:**
- `#integrations-announcements`: Everyone can read, only bots + admins can post
- `#bounty-payouts`: Visible only to users with the Core Contributor role
- All others: open to everyone

## Step 3: Create Discord Roles (3 min)

Create these roles if they don't exist. Order matters — higher = more prestigious:

| Role | Color | Hoisted | Mentionable |
|------|-------|---------|-------------|
| Core Contributor | Gold `#F1C40F` | Yes | Yes |
| Open Source Contributor | Purple `#9B59B6` | Yes | No |
| Agent Builder | Green `#2ECC71` | Yes | No |

Achievement badge roles (optional, create as needed):

| Role | Color |
|------|-------|
| First Blood | Default |
| Bug Hunter | Red `#E74C3C` |
| Docs Champion | Yellow `#F39C12` |
| Health Inspector | Orange `#E67E22` |
| Promoter | Gold `#F1C40F` |
| Full Stack | Teal `#1ABC9C` |
| Ironman | Default |

## Step 4: Install and Configure Lurkr (10 min)

### 4a. Invite Lurkr

Go to https://lurkr.gg/ and invite the bot to your server. Grant it the permissions it requests (Manage Roles, Send Messages, etc).

### 4b. Enable Leveling

In any channel:
```
/levels enable
```

### 4c. Configure Message XP

```
/levels set-xp min:15 max:25
/levels set-cooldown seconds:60
```

### 4d. Set Channel XP Multipliers

Boost XP in channels where helping others matters:

```
/levels multiplier channel:#integrations-help multiplier:2
/levels multiplier channel:#integrations-testing multiplier:1.5
```

Disable XP in bot-only channels:

```
/levels ignore channel:#integrations-announcements
/levels ignore channel:#bounty-payouts
```

### 4e. Configure Role Rewards

```
/levels role-reward add level:5 role:@Agent Builder
/levels role-reward add level:15 role:@Open Source Contributor
```

Do NOT auto-assign Core Contributor — that's maintainer-only.

### 4f. Generate Lurkr API Key

1. Go to https://lurkr.gg/ and log in with Discord
2. Navigate to your profile / API settings
3. Click "Create API Key"
4. Select **Read/Write** (not read-only)
5. Copy the key — you'll need it in the next step

## Step 5: Create Discord Webhook (2 min)

1. Go to **Server Settings > Integrations > Webhooks**
2. Click **New Webhook**
3. Name it `Bounty Tracker`
4. Set the channel to `#integrations-announcements`
5. Copy the webhook URL

## Step 6: Add GitHub Repository Secrets (3 min)

Go to **Repo Settings > Secrets and variables > Actions > New repository secret** and add:

| Secret Name | Value |
|-------------|-------|
| `DISCORD_BOUNTY_WEBHOOK_URL` | The webhook URL from Step 5 |
| `LURKR_API_KEY` | The Lurkr API key from Step 4f |
| `LURKR_GUILD_ID` | Your Discord server ID* |

*To find server ID: Enable Developer Mode in Discord (Settings > Advanced), then right-click the server name > Copy Server ID.

## Step 7: Test the Pipeline (5 min)

### Test 1: Verify the script runs locally

```bash
GITHUB_TOKEN=$(gh auth token) \
GITHUB_REPOSITORY_OWNER=adenhq \
GITHUB_REPOSITORY_NAME=hive \
bun run scripts/bounty-tracker.ts leaderboard
```

Expected: `Found 0 merged bounty PRs` (or more if you already have bounty PRs).

### Test 2: Test a webhook notification

Create a test PR, add the `bounty:docs` and `difficulty:easy` labels, merge it, and verify:
- GitHub Action `Bounty completed` runs successfully
- A message appears in `#integrations-announcements`
- If the contributor is in `contributors.yml`, Lurkr XP is awarded

### Test 3: Verify Lurkr role rewards

Check that role rewards are configured:
```
/levels role-rewards
```

## Step 8: Seed the First Bounty Issues (ongoing)

Use the bounty issue template in GitHub to create issues. Start with the easiest batch:

### Phase 1 (Week 1): Documentation bounties

For each unverified tool missing a README, create an issue:
- Title: `[Bounty]: Write README for {tool_name}`
- Bounty type: `Write README (20 pts)`
- Difficulty: `Easy`
- Labels: `bounty:docs`, `difficulty:easy`

### Quick list of tools missing READMEs

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

After setup, verify everything works:

- [ ] Labels exist on the repo (`bounty:*` and `difficulty:*`)
- [ ] Discord channels created and permissions set
- [ ] Discord roles created in correct order
- [ ] Lurkr installed, leveling enabled, XP configured
- [ ] Lurkr role rewards set for levels 5 and 15
- [ ] Lurkr API key is Read/Write
- [ ] All 3 GitHub secrets added
- [ ] `bounty-completed.yml` workflow exists and is enabled
- [ ] `weekly-leaderboard.yml` workflow exists and is enabled
- [ ] Test PR + merge triggers notification in Discord
- [ ] `contributors.yml` exists at repo root

## Troubleshooting

**Action runs but no Discord message:**
- Check the `DISCORD_BOUNTY_WEBHOOK_URL` secret is set correctly
- Check the webhook channel still exists and the webhook hasn't been deleted
- Check the Action logs for error messages

**Lurkr XP not awarded:**
- Confirm `LURKR_API_KEY` and `LURKR_GUILD_ID` secrets are set
- Confirm the API key is Read/Write (not read-only)
- Confirm the contributor has linked their Discord ID in `contributors.yml`
- Check Action logs for `Lurkr XP push failed` messages

**Role not assigned after level up:**
- Verify role rewards are configured: `/levels role-rewards`
- Lurkr assigns roles on level-up, not retroactively. The user may need to send a message or run `/rank` to trigger it
- Verify Lurkr's role is above the roles it needs to assign in the server role hierarchy

**Weekly leaderboard not posting:**
- The cron schedule is Monday 9:00 UTC. Check that the workflow is enabled
- Manually trigger: Actions > Weekly bounty leaderboard > Run workflow
