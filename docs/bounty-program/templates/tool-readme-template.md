# {Tool Name} Tool

<!-- One-liner: what this tool does and what it enables agents to do. -->

{Brief description of what the tool does and its primary use case.}

## Setup

```bash
# Required
export {ENV_VAR}=your-api-key
```

**Get your key:**
1. Go to {help_url}
2. {Step to create/generate a key}
3. {Step to copy the key}
4. Set `{ENV_VAR}` environment variable

Alternatively, configure via the credential store (`CredentialStoreAdapter`).

<!-- If OAuth is supported, add: -->
<!-- **OAuth:** This integration also supports OAuth2 via Aden. -->

## Tools ({count})

| Tool | Description |
|------|-------------|
| `{tool_function_name}` | {What it does} |
| `{tool_function_name}` | {What it does} |

## Usage

### {Action name}

```python
result = {tool_function_name}(
    param="value",
)
# Returns: {brief description of return value}
```

### {Action name}

```python
result = {tool_function_name}(
    param="value",
)
# Returns: {brief description of return value}
```

## Scope

<!-- What this integration covers in its current form. -->

- {Capability 1}
- {Capability 2}
- {Capability 3}

## Rate Limits

<!-- Document known rate limits if applicable. Remove this section if not relevant. -->

| Tier | Limit |
|------|-------|
| Free | {X requests/minute} |
| Paid | {Y requests/minute} |

## API Reference

- [{Service} API Docs]({url})
