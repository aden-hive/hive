# Game Master Manual

Operations guide for maintainers running the Integration Bounty Program.

## Your Role

- Post bounty issues and set dollar values for Core Contributors
- Assign claimed bounties to contributors
- Review and merge bounty PRs (auto-triggers XP awards)
- Manage the Core Contributor role
- Monitor for gaming and low-quality submissions

## Handling Bounty Claims

When someone comments "I'd like to work on this":

1. For `difficulty:easy`, assign immediately
2. For `difficulty:medium`/`difficulty:hard`, check if they've done easier bounties first
3. Assign via GitHub. If no PR within 7 days, unassign and re-open

## Reviewing Bounty PRs

1. Verify the PR matches the bounty issue
2. Check quality gates (below)
3. A **different maintainer** must approve than the one who created the bounty
4. Apply the correct `bounty:*` label to the PR before merging
5. Merge — the GitHub Action auto-awards XP and posts to Discord
6. Close the linked bounty issue

### Quality Gates

**`bounty:docs`:**
- [ ] Follows the [tool README template](templates/tool-readme-template.md)
- [ ] Setup instructions are accurate (API key URL works)
- [ ] Function names match the actual code
- [ ] Not AI-generated without verification

**`bounty:test`:**
- [ ] Test report follows the [template](templates/agent-test-report-template.md)
- [ ] Includes logs, session ID, or screenshots
- [ ] Done with a real API key, not mocked
- [ ] Reports failures honestly

**`bounty:code`:**
- [ ] CI passes (`uv run pytest tools/tests/test_credential_registry.py` for health checks)
- [ ] Fix addresses root cause, not symptom
- [ ] New test added for bug fixes

**`bounty:new-tool`:**
- [ ] Full implementation: tool + credential spec + tests + README
- [ ] `make check && make test` passes
- [ ] Registered in `_register_unverified()` (not verified)

### Rejecting Submissions

1. Leave specific, constructive feedback
2. Request changes (don't close the PR)
3. 7 days to address. No response → close PR, unassign bounty

Never merge low-quality work just to be nice.

## Core Contributor Promotion

Core Contributor unlocks monetary rewards. The bar must be high.

**Promote when:**
- Active for **4+ weeks** with contributions across **3+ bounty types**
- PRs are consistently clean
- At least one maintainer vouches for them

**How:** Discuss with maintainers → assign role in Discord → announce in `#integrations-announcements` → add to `#bounty-payouts`

**Don't promote** if they only do easy bounties, have been active < 4 weeks, or show signs of gaming.

If a Core Contributor is inactive 8+ weeks, reach out privately first, then remove the role if no response.

## Dollar Values

Post dollar values in `#bounty-payouts` (Core Contributors only):

| Bounty Type | Dollar Range |
|-------------|-------------|
| `bounty:test` | $10–30 |
| `bounty:docs` | $10–20 |
| `bounty:code` | $20–50 |
| `bounty:new-tool` | $50–150 |

**Payout:** PR merged → verify quality → record in `#bounty-payouts` → process payment.

XP is always awarded regardless of budget. Money is a bonus layer.

## Anti-Gaming

| Pattern | Response |
|---------|----------|
| Splitting one change across multiple PRs | Reject extras, warn |
| AI-generated without verification | Reject, explain why |
| Claiming many bounties, completing few | Unassign after 7 days |

**First offense:** warning. **Second:** 2-week cooldown. **Third:** permanent removal.

## Keeping It Fresh

- Aim for 10+ unclaimed bounties at all times
- Unassign stale claims (>7 days)
- Shoutout exceptional contributions in announcements
- Post milestones ("10th tool promoted to verified!")
