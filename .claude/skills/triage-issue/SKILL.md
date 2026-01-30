# Triage Issue Skill

Analyze a GitHub issue, verify claims against the codebase, and close invalid issues with a technical response.

## Trigger

User provides a GitHub issue URL or number, e.g.:
- `/triage-issue 1970`
- `/triage-issue https://github.com/adenhq/hive/issues/1970`

## Workflow

### Step 1: Fetch Issue Details

```bash
gh issue view <number> --repo adenhq/hive --json title,body,state,labels,author
```

Extract:
- Title
- Body (the claim/bug report)
- Current state
- Labels
- Author

If issue is already closed, inform user and stop.

### Step 2: Analyze the Claim

Read the issue body and identify:
1. **The core claim** - What is the user asserting?
2. **Technical specifics** - File paths, function names, code snippets mentioned
3. **Expected behavior** - What do they think should happen?
4. **Severity claimed** - Security issue? Bug? Feature request?

### Step 3: Investigate the Codebase

For each technical claim:
1. Find the referenced code using Grep/Glob/Read
2. Understand the actual implementation
3. Check if the claim accurately describes the behavior
4. Look for related tests, documentation, or design decisions

### Step 4: Evaluate Validity

Categorize the issue as one of:

| Category | Action |
|----------|--------|
| **Valid Bug** | Do NOT close. Inform user this is a real issue. |
| **Valid Feature Request** | Do NOT close. Suggest labeling appropriately. |
| **Misunderstanding** | Prepare technical explanation for why behavior is correct. |
| **Fundamentally Flawed** | Prepare critique explaining the technical impossibility or design rationale. |
| **Duplicate** | Find the original issue and prepare duplicate notice. |
| **Incomplete** | Prepare request for more information. |

### Step 5: Draft Response

For issues to be closed, draft a response that:

1. **Acknowledges the concern** - Don't be dismissive
2. **Explains the actual behavior** - With code references
3. **Provides technical rationale** - Why it works this way
4. **References industry standards** - If applicable
5. **Offers alternatives** - If there's a better approach for the user

Use this template:

```markdown
## Analysis

[Brief summary of what was investigated]

## Technical Details

[Explanation with code references]

## Why This Is Working As Designed

[Rationale]

## Recommendation

[What the user should do instead, if applicable]

---
*This issue was reviewed and closed by the maintainers.*
```

### Step 6: User Review

Present the draft to the user with:

```
## Issue #<number>: <title>

**Claim:** <summary of claim>

**Finding:** <valid/invalid/misunderstanding/etc>

**Draft Response:**
<the markdown response>

---
Do you want me to post this comment and close the issue?
```

Use AskUserQuestion with options:
- "Post and close" - Post comment, close issue
- "Edit response" - Let user modify the response
- "Skip" - Don't take action

### Step 7: Execute Action

If user approves:

```bash
# Post comment
gh issue comment <number> --repo adenhq/hive --body "<response>"

# Close issue
gh issue close <number> --repo adenhq/hive --reason "not planned"
```

Report success with link to the issue.

## Important Guidelines

1. **Never close valid issues** - If there's any merit to the claim, don't close it
2. **Be respectful** - The reporter took time to file the issue
3. **Be technical** - Provide code references and evidence
4. **Be educational** - Help them understand, don't just dismiss
5. **Check twice** - Make sure you understand the code before declaring something invalid
6. **Consider edge cases** - Maybe their environment reveals a real issue

## Example Critiques

### Security Misunderstanding
> "The claim that secrets are exposed in plaintext misunderstands the encryption architecture. While `SecretStr` is used for logging protection, actual encryption is provided by Fernet (AES-128-CBC) at the storage layer. The code path is: serialize → encrypt → write. Only encrypted bytes touch disk."

### Impossible Request
> "The requested feature would require [X] which violates [fundamental constraint]. This is not a limitation of our implementation but a fundamental property of [technology/protocol]."

### Already Handled
> "This scenario is already handled by [code reference]. The reporter may be using an older version or misconfigured environment."
