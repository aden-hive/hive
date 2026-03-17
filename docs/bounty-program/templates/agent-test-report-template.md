# Agent Test Report: {tool_name}

<!-- Submit this report as a comment on the bounty issue, or as a file in a PR. -->

## Summary

- **Tool tested:** `{tool_name}`
- **Tester:** @{github_handle}
- **Date:** {YYYY-MM-DD}
- **Verdict:** Pass / Partial / Fail

## Environment

- **OS:** {e.g., macOS 15.2, Ubuntu 24.04}
- **Python:** {e.g., 3.12.1}
- **Hive version:** {commit hash or version}
- **API tier:** {e.g., Free, Pro — relevant for rate limits}

## Credential Setup

- **Auth method:** {API key / OAuth / Bearer token}
- **Health check result:** {Pass / Fail / No health checker available}
- **Setup difficulty:** {Easy / Medium / Hard}
- **Setup notes:** {Any friction, confusing docs, extra steps not documented}

## Agent Configuration

<!-- Describe the agent you built or used to test this tool. -->

```
Agent name: {name}
Tools used: {tool_name}, {any other tools}
Goal: {What the agent was supposed to accomplish}
```

## Test Results

### Tool Functions Tested

| Function | Input | Expected | Actual | Status |
|----------|-------|----------|--------|--------|
| `{function_name}` | {brief input description} | {expected behavior} | {what happened} | Pass/Fail |
| `{function_name}` | {brief input description} | {expected behavior} | {what happened} | Pass/Fail |

### Agent Workflow Test

<!-- Did the agent successfully use this tool to accomplish a task? -->

**Goal:** {What you asked the agent to do}

**Result:** {What actually happened}

**Session ID:** `{session_id if available}`

### Edge Cases Found

<!-- Document any unexpected behavior, errors, or limitations. -->

| Edge Case | Behavior | Severity |
|-----------|----------|----------|
| {e.g., empty query} | {what happened} | Low/Medium/High |
| {e.g., rate limit hit} | {what happened} | Low/Medium/High |

## Issues Found

<!-- List any bugs or problems. Link to new issues if you filed them. -->

- [ ] {Issue description} — {filed as #XXXX / not yet filed}
- [ ] {Issue description}

## Recommendations

<!-- Suggestions for the tool maintainer. -->

- {e.g., "Error message for missing API key should include the help URL"}
- {e.g., "Rate limit handling should retry with backoff"}
- {e.g., "Ready for promotion after health checker is added"}

## Evidence

<!-- Attach or link to logs, screenshots, or recordings. At minimum, include the session ID or key log output. -->

<details>
<summary>Logs</summary>

```
{Paste relevant log output here}
```

</details>
