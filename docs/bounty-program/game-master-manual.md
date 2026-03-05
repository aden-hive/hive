# Game Master Manual

Operations guide for maintainers running the Integration Bounty Program. This covers the day-to-day decisions: posting bounties, approving work, awarding points, managing tiers, and keeping the program healthy.

## Your Role

As a game master (maintainer), you:
- Post bounty issues and set dollar values for Core Contributors
- Assign claimed bounties to contributors
- Review and merge bounty PRs (which auto-triggers point/XP awards)
- Manually assign achievement badges and the Core Contributor role
- Monitor for gaming and low-quality submissions
- Keep the bounty board fresh and the community engaged

## Daily Operations

### Handling Bounty Claims

When someone comments "I'd like to work on this" on a bounty issue:

1. Check their GitHub profile — do they have relevant experience?
2. For `difficulty:easy` bounties, assign immediately (within 24 hours)
3. For `difficulty:medium` and `difficulty:hard`, check if they've completed easier bounties first
4. Assign the issue to them via GitHub
5. If they don't submit a PR within 7 days, unassign and re-open

### Reviewing Bounty PRs

When a bounty PR is submitted:

1. **Verify the PR matches the bounty** — does it actually complete what the issue asked for?
2. **Check quality gates** (see below)
3. **A different maintainer** must approve than the one who created the bounty issue
4. **Apply the correct `bounty:*` label** to the PR before merging (if not already present)
5. **Merge** — the GitHub Action automatically awards XP and posts to Discord
6. **Close the linked bounty issue**

### Quality Gate Checks

#### For `bounty:docs` (READMEs):
- [ ] Follows the [tool README template](templates/tool-readme-template.md)
- [ ] Setup instructions are accurate (API key URL works, steps are correct)
- [ ] Tool table lists all functions with correct names
- [ ] At least one usage example per tool function
- [ ] API reference link is valid
- [ ] Not obviously AI-generated without verification (check that API URLs and function names match reality)

#### For `bounty:health-check`:
- [ ] `health_check_endpoint` added to CredentialSpec
- [ ] HealthChecker class implemented with proper 200/401/429 handling
- [ ] Registered in `HEALTH_CHECKERS` dict
- [ ] `uv run pytest tools/tests/test_credential_registry.py` passes
- [ ] Endpoint is actually a lightweight validation call (no writes, no charges)

#### For `bounty:agent-test`:
- [ ] Test report follows the [template](templates/agent-test-report-template.md)
- [ ] Includes reproducible evidence (logs, session ID, or screenshots)
- [ ] Tests were done with a real API key, not mocked
- [ ] Reports both successes and failures honestly
- [ ] Edge cases section is filled out (even if "none found")

#### For `bounty:bug-fix`:
- [ ] Bug was found during actual integration testing (not invented)
- [ ] Fix addresses the root cause, not just the symptom
- [ ] Existing tests still pass
- [ ] New test added for the specific bug

#### For `bounty:new-tool`:
- [ ] Full implementation: tool + credential spec + tests + README
- [ ] Follows [BUILDING_TOOLS.md](../tools/BUILDING_TOOLS.md) patterns
- [ ] `make check && make test` passes
- [ ] Registered in `_register_unverified()` (not verified — needs community testing first)

#### For `bounty:promote`:
- [ ] Every item on the [promotion checklist](promotion-checklist.md) is checked
- [ ] At least 1 community agent test report exists
- [ ] Move registration from `_register_unverified()` to `_register_verified()`

### Rejecting Submissions

When quality is insufficient:

1. Leave a specific, constructive review comment — explain exactly what needs to change
2. Request changes on the PR (don't close it)
3. Give them 7 days to address feedback
4. If no response after 7 days, close the PR and unassign the bounty issue

**Never:**
- Reject without explanation
- Deduct points for good-faith attempts that need revision
- Merge low-quality work just to be nice — it degrades the codebase and the program's credibility

## Weekly Operations

### Monday: Leaderboard Day

The `weekly-leaderboard.yml` action auto-posts at 9:00 UTC every Monday. After it posts:

1. Check the leaderboard in `#integrations-announcements`
2. If anyone new entered the top 3, congratulate them in the channel
3. Review the bounty board — are there enough open bounties? Aim for 10+ unclaimed at all times

### Thursday: Bounty Refresh

Mid-week check:

1. Are any bounties stale (assigned >7 days, no PR)? Unassign them
2. Are any bounty types depleted? Post more
3. Check `#integrations-help` — are people asking questions that suggest missing documentation? That's a signal for new `bounty:docs` issues

## Tier Management

### Promoting to Agent Builder (Automatic)

Lurkr handles this via role reward at level 5. No action needed.

### Promoting to Open Source Contributor (Automatic)

Lurkr handles this via role reward at level 15. No action needed.

### Promoting to Core Contributor (Manual)

This is the most important decision you make. Core Contributor unlocks monetary rewards, so the bar must be high.

**When to promote:**

1. The contributor has been active for **4+ weeks**
2. They have contributions across **3+ bounty types** (not just one category)
3. Their PRs are consistently clean — they don't need multiple rounds of back-and-forth
4. They've demonstrated **technical depth** (not just documentation — they can fix bugs, add health checks, or build tools)
5. At least one maintainer is willing to vouch for them

**How to promote:**

1. Discuss with other maintainers in your private channel
2. If consensus, assign the Core Contributor role in Discord manually
3. Post an announcement in `#integrations-announcements`:
   ```
   Welcome @username as a Core Contributor! They've [brief summary of contributions].
   ```
4. Add them to the `#bounty-payouts` channel
5. Brief them on how dollar-value bounties work (see below)

**When NOT to promote:**

- They only do easy bounties (all docs, no code)
- They've been active for less than 4 weeks
- Their PRs frequently need significant rework
- They show signs of gaming (splitting work, low-effort submissions)

### Demoting / Pausing Core Contributor

If a Core Contributor becomes inactive or their quality drops:

1. Reach out privately first — "Hey, noticed you've been less active, everything okay?"
2. If quality is the issue, provide specific feedback
3. If they're inactive for 8+ weeks, remove the Core Contributor role (they can earn it back)
4. Never demote publicly — handle it in DMs

## Monetary Bounties

### Setting Dollar Values

For each bounty issue, post the dollar value in `#bounty-payouts` (visible only to Core Contributors):

```
Bounty #1234: Write README for salesforce_tool — $15
Bounty #1235: Add health checker for jira — $25
Bounty #1236: Full promotion of notion_tool — $75
```

**Suggested dollar ranges:**

| Bounty Type | Dollar Range | Notes |
|-------------|-------------|-------|
| `bounty:docs` | $10–20 | $10 for simple tools, $20 for complex ones |
| `bounty:health-check` | $15–30 | $15 for simple GET, $30 for complex auth |
| `bounty:smoke-test` | $5–10 | Quick validation |
| `bounty:agent-test` | $20–40 | Requires real API key and time |
| `bounty:bug-fix` | $20–50 | Depends on complexity |
| `bounty:new-tool` | $50–150 | Depends on integration complexity |
| `bounty:promote` | $50–100 | Full checklist completion |

### Payout Process

1. Core Contributor completes bounty, PR is merged
2. Verify the work meets quality gates
3. Record the payout in `#bounty-payouts`:
   ```
   PAID: @username — Bounty #1234 — $15 — [payment method/reference]
   ```
4. Process payment via your payment system (PayPal, Wise, crypto, etc.)

### Budget Management

- Set a monthly budget cap and communicate it
- When budget is tight, reduce dollar values rather than stopping bounties entirely
- Point values (XP) are always awarded regardless of budget — money is a bonus layer

## Achievement Badges

These are manually assigned when someone qualifies. Check periodically.

| Badge | Trigger | How to Verify |
|-------|---------|---------------|
| **First Blood** | First bounty completed | Check their first merged PR with `bounty:*` label |
| **Bug Hunter** | 3 `bounty:bug-fix` PRs merged | Search: `is:pr is:merged author:USERNAME label:bounty:bug-fix` |
| **Docs Champion** | 5 `bounty:docs` PRs merged | Search: `is:pr is:merged author:USERNAME label:bounty:docs` |
| **Health Inspector** | 5 `bounty:health-check` PRs merged | Search: `is:pr is:merged author:USERNAME label:bounty:health-check` |
| **Promoter** | 1 `bounty:promote` PR merged | Search: `is:pr is:merged author:USERNAME label:bounty:promote` |
| **Full Stack** | At least 1 PR with each bounty type | Check all 7 bounty labels |
| **Ironman** | 8 consecutive weeks with a bounty PR | Check merge dates — no gap > 7 days |

When assigning a badge:
1. Assign the role in Discord
2. Post in `#integrations-announcements`:
   ```
   @username just earned the Bug Hunter badge! 3 bugs found and fixed.
   ```

## Anti-Gaming Playbook

### Signs of Gaming

| Pattern | What It Looks Like | Response |
|---------|-------------------|----------|
| **Splitting** | One README split into 3 PRs | Reject extras, warn contributor |
| **AI spam** | README with wrong function names, hallucinated APIs | Reject, explain why verification matters |
| **Claim hoarding** | Claiming 10 bounties, completing 1 | Unassign after 7 days, limit to 3 active claims |
| **Self-review** | Reviewing their own work under alt account | Ban both accounts |
| **Low-effort agent tests** | Test report with no logs, no session ID | Request revision with specific feedback |

### Responses

**First offense:** Warning via PR comment or DM. Be specific about what was wrong.

**Second offense:** 2-week bounty cooldown (they can still contribute, but no bounty labels are applied to their PRs).

**Third offense:** Permanent removal from the bounty program. Core Contributor role revoked if applicable.

Document all actions in a private maintainer thread for transparency.

## Keeping the Program Alive

### What Makes It Stale

- No new bounties for 2+ weeks
- Same 3 people on the leaderboard every week
- Bounties claimed but never completed
- Announcements channel goes quiet

### What Keeps It Fresh

- **New bounty types** — when the Doc Sprint is done, launch the Health Check Sprint
- **Sprint events** — "This week: double XP on agent tests"
- **Shoutouts** — highlight exceptional contributions in announcements
- **Showcase pins** — pin the best demos in `#integration-showcase`
- **Rising stars** — mention newcomers who are ramping up fast
- **Milestones** — "We just promoted the 10th tool to verified!"

### Metrics to Track

| Metric | Healthy Range | Alarm |
|--------|-------------|-------|
| Open unclaimed bounties | 10–30 | < 5 (post more) or > 50 (too many, focus) |
| Active contributors (last 30 days) | 5+ | < 3 |
| Average days claim → PR | 3–7 | > 14 (bounties too hard or claims going stale) |
| Tools promoted (monthly) | 2–5 | 0 (investigate blockers) |
| Core Contributor count | 3–10 | > 15 (bar too low) or 0 (bar too high) |
