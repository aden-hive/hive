---
name: setup-credentials
description: Set up and install credentials for an agent. Detects missing credentials from agent config, collects them from the user, and stores them securely in the encrypted credential store at ~/.hive/credentials.
license: Apache-2.0
metadata:
  author: hive
  version: "1.0"
  type: utility
---

# Setup Credentials

Interactive credential setup for agents. Detects what's missing, collects values from the user, and stores them securely in the encrypted credential store.

## When to Use

- Before running or testing an agent for the first time
- When `AgentRunner.run()` fails with "missing required credentials"
- When a user asks to configure credentials for an agent
- After building a new agent that uses tools requiring API keys

## Workflow

### Step 1: Identify the Agent

Determine which agent needs credentials. The user will either:
- Name the agent directly (e.g., "set up credentials for hubspot-agent")
- Have an agent directory open (check `exports/` for agent dirs)
- Be working on an agent in the current session

Locate the agent's directory under `exports/{agent_name}/`.

### Step 2: Detect Required Credentials

Read the agent's configuration to determine which tools and node types it uses:

```python
from core.framework.runner import AgentRunner

runner = AgentRunner.load("exports/{agent_name}")
validation = runner.validate()

# validation.missing_credentials contains env var names
# validation.warnings contains detailed messages with help URLs
```

Alternatively, inspect manually:
1. Read `exports/{agent_name}/agent.json` to find tool names in node specs
2. Cross-reference with credential specs:

```python
from aden_tools.credentials import CredentialManager

creds = CredentialManager()

# For tool-based credentials
missing_tools = creds.get_missing_for_tools(agent_tool_names)

# For node-type credentials (e.g., LLM nodes need ANTHROPIC_API_KEY)
missing_nodes = creds.get_missing_for_node_types(agent_node_types)
```

### Step 3: Present Missing Credentials to User

Show ALL missing credentials at once with clear instructions:

```
This agent requires the following credentials:

  ANTHROPIC_API_KEY (missing)
    Anthropic API key for LLM calls
    Get one at: https://console.anthropic.com/

  HUBSPOT_ACCESS_TOKEN (missing)
    HubSpot access token (Private App or OAuth2)
    Get one at: https://developers.hubspot.com/docs/api/private-apps

  BRAVE_SEARCH_API_KEY (already set)
```

Use AskUserQuestion to collect each missing credential value from the user. Collect them one at a time for security (so values aren't mixed in a single prompt).

### Step 4: Store Credentials Securely

For each credential the user provides, store it in the encrypted credential store:

```python
from core.framework.credentials import CredentialStore, CredentialObject, CredentialKey
from pydantic import SecretStr

store = CredentialStore.with_encrypted_storage()  # ~/.hive/credentials

cred = CredentialObject(
    id="{credential_name}",           # e.g., "hubspot"
    name="{Human-readable name}",     # e.g., "HubSpot Access Token"
    keys={
        "{key_name}": CredentialKey(   # e.g., "access_token"
            name="{key_name}",
            value=SecretStr("{user_provided_value}"),
        )
    },
)
store.save_credential(cred)
```

**Credential ID and key naming conventions:**

| Credential | ID | Key Name |
|---|---|---|
| Anthropic API Key | `anthropic` | `api_key` |
| OpenAI API Key | `openai` | `api_key` |
| HubSpot Access Token | `hubspot` | `access_token` |
| Brave Search API Key | `brave_search` | `api_key` |
| Google Search API Key | `google_search` | `api_key` |
| Google CSE ID | `google_cse` | `cse_id` |

### Step 5: Set Environment Variables for Current Session

The credential store is the persistent backend, but the current runtime also reads from environment variables. Export each credential so it takes effect immediately:

```bash
export HUBSPOT_ACCESS_TOKEN="the-value"
```

This is ephemeral (current session only). The credential store ensures persistence.

### Step 6: Verify

Run validation again to confirm everything is set:

```python
runner = AgentRunner.load("exports/{agent_name}")
validation = runner.validate()
assert not validation.missing_credentials, "Still missing credentials!"
```

Report the result to the user.

## Encryption Key (HIVE_CREDENTIAL_KEY)

The encrypted credential store requires `HIVE_CREDENTIAL_KEY` to encrypt/decrypt credentials.

- If the user doesn't have one, `EncryptedFileStorage` will auto-generate one and log it
- The user MUST persist this key (e.g., in `~/.bashrc` or a secrets manager)
- Without this key, stored credentials cannot be decrypted
- This is the ONLY secret that should live in `~/.bashrc` or environment config

If `HIVE_CREDENTIAL_KEY` is not set:
1. Let the store generate one
2. Tell the user to save it: `export HIVE_CREDENTIAL_KEY="{generated_key}"`
3. Recommend adding it to `~/.bashrc` or their shell profile

## Security Rules

- **NEVER** log, print, or echo credential values in tool output
- **NEVER** store credentials in plaintext files, git-tracked files, or agent configs
- **NEVER** hardcode credentials in source code
- **ALWAYS** use `SecretStr` from Pydantic when handling credential values in Python
- **ALWAYS** use the encrypted credential store (`~/.hive/credentials`) for persistence
- **ALWAYS** verify credentials were stored by re-running validation, not by reading them back
- When removing credentials from `~/.bashrc`, confirm with the user first

## Credential Sources Reference

All credential specs are defined in `tools/src/aden_tools/credentials/`:

| File | Category | Credentials |
|---|---|---|
| `llm.py` | LLM Providers | `anthropic`, `openai`, `cerebras`, `groq` |
| `search.py` | Search Tools | `brave_search`, `google_search`, `google_cse` |
| `integrations.py` | Integrations | `hubspot` |

To check what's registered:
```python
from aden_tools.credentials import CREDENTIAL_SPECS
for name, spec in CREDENTIAL_SPECS.items():
    print(f"{name}: {spec.env_var} -> {spec.tools}")
```

## Example Session

```
User: /setup-credentials for my hubspot-agent

Agent: Let me check what credentials your hubspot-agent needs.

[Runs validation, finds ANTHROPIC_API_KEY and HUBSPOT_ACCESS_TOKEN missing]

Agent: Your hubspot-agent requires 2 credentials:

  1. ANTHROPIC_API_KEY - Anthropic API key for LLM calls
     Get one at: https://console.anthropic.com/

  2. HUBSPOT_ACCESS_TOKEN - HubSpot access token (Private App or OAuth2)
     Get one at: https://developers.hubspot.com/docs/api/private-apps

Let me collect these one at a time.

[AskUserQuestion: "Please provide your Anthropic API key:"]
[User provides key]
[Stores in credential store, exports to env]

[AskUserQuestion: "Please provide your HubSpot access token:"]
[User provides token]
[Stores in credential store, exports to env]

Agent: All credentials are now configured:
  - Stored securely in ~/.hive/credentials (encrypted)
  - Available in current session via environment variables
  - Validation passed - your agent is ready to run
```
