---
name: setup-credentials
description: Set up and install credentials for an agent. Detects missing credentials from agent config, collects them from the user, and stores them securely in the local encrypted store at ~/.hive/credentials.
license: Apache-2.0
metadata:
  author: hive
  version: "2.2"
  type: utility
---

# Setup Credentials

Interactive credential setup for agents with multiple authentication options. Detects what's missing, offers auth method choices, validates with health checks, and stores credentials securely.

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

### Step 2: Detect Required Credentials (Bash-First)

Use bash commands to determine what the agent needs and what's already configured. This avoids Python import issues and works even when `HIVE_CREDENTIAL_KEY` is not set.

#### Step 2a: Read Agent Requirements

Extract `required_tools` and node types from the agent config:

```bash
# Get required tools
jq -r '.required_tools[]?' exports/{agent_name}/agent.json 2>/dev/null

# Get node types from graph nodes
jq -r '.graph.nodes[]?.node_type' exports/{agent_name}/agent.json 2>/dev/null | sort -u
```

Map the extracted tools and node types to credentials by reading the spec files directly:

```bash
# Read all credential specs — each file defines tools, node_types, env_var, and credential_id
cat tools/src/aden_tools/credentials/llm.py tools/src/aden_tools/credentials/search.py tools/src/aden_tools/credentials/email.py tools/src/aden_tools/credentials/integrations.py
```

For each `CredentialSpec`, match its `tools` and `node_types` lists against the agent's required tools and node types. Extract the `env_var`, `credential_id`, and `credential_group` for every match. This is the list of needed credentials.

#### Step 2b: Check Existing Credential Sources

For each needed credential, check three sources. A credential is "found" if it exists in ANY of them:

**1. Encrypted store metadata index** (unencrypted JSON — no decryption key needed):

```bash
cat ~/.hive/credentials/metadata/index.json 2>/dev/null | jq -r '.credentials | keys[]'
```

If a credential ID appears in this list, it is stored in the encrypted store.

**2. Environment variables:**

```bash
# Check each needed env var, e.g.:
printenv ANTHROPIC_API_KEY > /dev/null 2>&1 && echo "ANTHROPIC_API_KEY: set" || echo "ANTHROPIC_API_KEY: not set"
printenv BRAVE_SEARCH_API_KEY > /dev/null 2>&1 && echo "BRAVE_SEARCH_API_KEY: set" || echo "BRAVE_SEARCH_API_KEY: not set"
```

**3. Project `.env` file:**

```bash
# Check each needed env var, e.g.:
grep -q '^ANTHROPIC_API_KEY=' .env 2>/dev/null && echo "ANTHROPIC_API_KEY: in .env" || echo "ANTHROPIC_API_KEY: not in .env"
grep -q '^BRAVE_SEARCH_API_KEY=' .env 2>/dev/null && echo "BRAVE_SEARCH_API_KEY: in .env" || echo "BRAVE_SEARCH_API_KEY: not in .env"
```

#### Step 2c: HIVE_CREDENTIAL_KEY Check

If any credentials were found in the encrypted store metadata index, verify the encryption key is available. The key is typically persisted to shell config by a previous setup-credentials run.

Check both the current session AND shell config files:

```bash
# Check 1: Current session
printenv HIVE_CREDENTIAL_KEY > /dev/null 2>&1 && echo "session: set" || echo "session: not set"

# Check 2: Shell config files (where setup-credentials persists it)
# Note: check each file individually to avoid non-zero exit when one doesn't exist
for f in ~/.zshrc ~/.bashrc ~/.profile; do [ -f "$f" ] && grep -q 'HIVE_CREDENTIAL_KEY' "$f" && echo "$f"; done
```

Decision logic:
- **In current session** — no action needed, credentials in the store are usable
- **In shell config but NOT in current session** — the key is persisted but this shell hasn't sourced it. Run `source ~/.zshrc` (or `~/.bashrc`), then re-check. Credentials in the store are usable after sourcing.
- **Not in session AND not in shell config** — the key was never persisted. Warn the user that credentials in the store cannot be decrypted. Help fix the key situation (recover/re-persist), do NOT re-collect credential values that are already stored.

#### Step 2d: Compute Missing & Group

Diff the "needed" credentials against the "found" credentials to get the truly missing list.

Group related credentials by their `credential_group` field from the spec files. Credentials that share the same non-empty `credential_group` value should be presented as a single setup step rather than asking for each one individually.

**If nothing is missing and there's no HIVE_CREDENTIAL_KEY issue:** Report all credentials as configured and skip Steps 3-5. Example:

```
All required credentials are already configured:
  ✓ anthropic (ANTHROPIC_API_KEY) — found in encrypted store
  ✓ brave_search (BRAVE_SEARCH_API_KEY) — found in environment
Your agent is ready to run!
```

**If credentials are missing:** Continue to Step 3 with only the missing ones.

### Step 3: Present Auth Options for Each Missing Credential

For each missing credential, check what authentication methods are available:

```python
from aden_tools.credentials import CREDENTIAL_SPECS

spec = CREDENTIAL_SPECS.get("hubspot")
if spec:
    # Determine available auth options
    auth_options = []
    if spec.aden_supported:
        auth_options.append("aden")
    if spec.direct_api_key_supported:
        auth_options.append("direct")
    auth_options.append("custom")  # Always available

    # Get setup info
    setup_info = {
        "env_var": spec.env_var,
        "description": spec.description,
        "help_url": spec.help_url,
        "api_key_instructions": spec.api_key_instructions,
    }
```

Present the available options using AskUserQuestion:

```
Choose how to configure HUBSPOT_ACCESS_TOKEN:

  1) Aden Platform (OAuth) (Recommended)
     Secure OAuth2 flow via integration.adenhq.com
     - Quick setup with automatic token refresh
     - No need to manage API keys manually

  2) Direct API Key
     Enter your own API key manually
     - Requires creating a HubSpot Private App
     - Full control over scopes and permissions

  3) Local Credential Setup (Advanced)
     Programmatic configuration for CI/CD
     - For automated deployments
     - Requires manual API calls
```

### Step 4: Execute Auth Flow Based on User Choice

#### Option 1: Aden Platform (OAuth)

This is the recommended flow for supported integrations (HubSpot, etc.).

**How Aden OAuth Works:**

The ADEN_API_KEY represents a user who has already completed OAuth authorization on Aden's platform. When users sign up and connect integrations on Aden, those OAuth tokens are stored server-side. Having an ADEN_API_KEY means:

1. User has an Aden account
2. User has already authorized integrations (HubSpot, etc.) via OAuth on Aden
3. We just need to sync those credentials down to the local credential store

**4.1a. Check for ADEN_API_KEY**

```python
import os
aden_key = os.environ.get("ADEN_API_KEY")
```

If not set, guide user to get one from Aden (this is where they do OAuth):

```python
from aden_tools.credentials import open_browser, get_aden_setup_url

# Open browser to Aden - user will sign up and connect integrations there
url = get_aden_setup_url()  # https://integration.adenhq.com/setup
success, msg = open_browser(url)

print("Please sign in to Aden and connect your integrations (HubSpot, etc.).")
print("Once done, copy your API key and return here.")
```

Ask user to provide the ADEN_API_KEY they received.

**4.1b. Save ADEN_API_KEY to Shell Config**

With user approval, persist ADEN_API_KEY to their shell config:

```python
from aden_tools.credentials import (
    detect_shell,
    add_env_var_to_shell_config,
    get_shell_source_command,
)

shell_type = detect_shell()  # 'bash', 'zsh', or 'unknown'

# Ask user for approval before modifying shell config
# If approved:
success, config_path = add_env_var_to_shell_config(
    "ADEN_API_KEY",
    user_provided_key,
    comment="Aden Platform (OAuth) API key"
)

if success:
    source_cmd = get_shell_source_command()
    print(f"Saved to {config_path}")
    print(f"Run: {source_cmd}")
```

Also save to `~/.hive/configuration.json` for the framework:

```python
import json
from pathlib import Path

config_path = Path.home() / ".hive" / "configuration.json"
config = json.loads(config_path.read_text()) if config_path.exists() else {}

config["aden"] = {
    "api_key_configured": True,
    "api_url": "https://api.adenhq.com"
}

config_path.parent.mkdir(parents=True, exist_ok=True)
config_path.write_text(json.dumps(config, indent=2))
```

**4.1c. Sync Credentials from Aden Server**

Since the user has already authorized integrations on Aden, use the one-liner factory method:

```python
from core.framework.credentials import CredentialStore

# This single call handles everything:
# - Creates encrypted local storage at ~/.hive/credentials
# - Configures Aden client from ADEN_API_KEY env var
# - Syncs all credentials from Aden server automatically
store = CredentialStore.with_aden_sync(
    base_url="https://api.adenhq.com",
    auto_sync=True,  # Syncs on creation
)

# Check what was synced
synced = store.list_credentials()
print(f"Synced credentials: {synced}")

# If the required credential wasn't synced, the user hasn't authorized it on Aden yet
if "hubspot" not in synced:
    print("HubSpot not found in your Aden account.")
    print("Please visit https://integration.adenhq.com to connect HubSpot, then try again.")
```

For more control over the sync process:

```python
from core.framework.credentials import CredentialStore
from core.framework.credentials.aden import (
    AdenCredentialClient,
    AdenClientConfig,
    AdenSyncProvider,
)

# Create client (API key loaded from ADEN_API_KEY env var)
client = AdenCredentialClient(AdenClientConfig(
    base_url="https://api.adenhq.com",
))

# Create provider and store
provider = AdenSyncProvider(client=client)
store = CredentialStore.with_encrypted_storage()

# Manual sync
synced_count = provider.sync_all(store)
print(f"Synced {synced_count} credentials from Aden")
```

**4.1d. Run Health Check**

```python
from aden_tools.credentials import check_credential_health

# Get the token from the store
cred = store.get_credential("hubspot")
token = cred.keys["access_token"].value.get_secret_value()

result = check_credential_health("hubspot", token)
if result.valid:
    print("HubSpot credentials validated successfully!")
else:
    print(f"Validation failed: {result.message}")
    # Offer to retry the OAuth flow
```

#### Option 2: Direct API Key

For users who prefer manual API key management.

**4.2a. Show Setup Instructions**

```python
from aden_tools.credentials import CREDENTIAL_SPECS

spec = CREDENTIAL_SPECS.get("hubspot")
if spec and spec.api_key_instructions:
    print(spec.api_key_instructions)
# Output:
# To get a HubSpot Private App token:
# 1. Go to HubSpot Settings > Integrations > Private Apps
# 2. Click "Create a private app"
# 3. Name your app (e.g., "Hive Agent")
# ...

if spec and spec.help_url:
    print(f"More info: {spec.help_url}")
```

**4.2b. Collect API Key from User**

Use AskUserQuestion to securely collect the API key:

```
Please provide your HubSpot access token:
(This will be stored securely in ~/.hive/credentials)
```

**4.2c. Run Health Check Before Storing**

```python
from aden_tools.credentials import check_credential_health

result = check_credential_health("hubspot", user_provided_token)
if not result.valid:
    print(f"Warning: {result.message}")
    # Ask user if they want to:
    # 1. Try a different token
    # 2. Continue anyway (not recommended)
```

**4.2d. Store in Local Encrypted Store**

```python
from core.framework.credentials import CredentialStore, CredentialObject, CredentialKey
from pydantic import SecretStr

store = CredentialStore.with_encrypted_storage()

cred = CredentialObject(
    id="hubspot",
    name="HubSpot Access Token",
    keys={
        "access_token": CredentialKey(
            name="access_token",
            value=SecretStr(user_provided_token),
        )
    },
)
store.save_credential(cred)
```

**4.2e. Export to Current Session**

```bash
export HUBSPOT_ACCESS_TOKEN="the-value"
```

#### Option 3: Local Credential Setup (Advanced)

For programmatic/CI/CD setups.

**4.3a. Show Documentation**

```
For advanced credential management, you can use the CredentialStore API directly:

  from core.framework.credentials import CredentialStore, CredentialObject, CredentialKey
  from pydantic import SecretStr

  store = CredentialStore.with_encrypted_storage()

  cred = CredentialObject(
      id="hubspot",
      name="HubSpot Access Token",
      keys={"access_token": CredentialKey(name="access_token", value=SecretStr("..."))}
  )
  store.save_credential(cred)

For CI/CD environments:
  - Set HIVE_CREDENTIAL_KEY for encryption
  - Pre-populate ~/.hive/credentials programmatically
  - Or use environment variables directly (HUBSPOT_ACCESS_TOKEN)

Documentation: See core/framework/credentials/README.md
```

### Step 5: Record Configuration Method

Track which auth method was used for each credential in `~/.hive/configuration.json`:

```python
import json
from pathlib import Path
from datetime import datetime

config_path = Path.home() / ".hive" / "configuration.json"
config = json.loads(config_path.read_text()) if config_path.exists() else {}

if "credential_methods" not in config:
    config["credential_methods"] = {}

config["credential_methods"]["hubspot"] = {
    "method": "aden",  # or "direct" or "custom"
    "configured_at": datetime.now().isoformat(),
}

config_path.write_text(json.dumps(config, indent=2))
```

### Step 6: Verify All Credentials

Run validation again to confirm everything is set:

```python
runner = AgentRunner.load("exports/{agent_name}")
validation = runner.validate()
assert not validation.missing_credentials, "Still missing credentials!"
```

Report the result to the user.

## Health Check Reference

Health checks validate credentials by making lightweight API calls:

| Credential      | Endpoint                                | What It Checks                     |
| --------------- | --------------------------------------- | ---------------------------------- |
| `anthropic`     | `POST /v1/messages`                     | API key validity                   |
| `brave_search`  | `GET /res/v1/web/search?q=test&count=1` | API key validity                   |
| `google_search` | `GET /customsearch/v1?q=test&num=1`     | API key + CSE ID validity          |
| `github`        | `GET /user`                             | Token validity, user identity      |
| `hubspot`       | `GET /crm/v3/objects/contacts?limit=1`  | Bearer token validity, CRM scopes  |
| `resend`        | `GET /domains`                          | API key validity                   |

```python
from aden_tools.credentials import check_credential_health, HealthCheckResult

result: HealthCheckResult = check_credential_health("hubspot", token_value)
# result.valid: bool
# result.message: str
# result.details: dict (status_code, rate_limited, etc.)
```

## Encryption Key (HIVE_CREDENTIAL_KEY)

The local encrypted store requires `HIVE_CREDENTIAL_KEY` to encrypt/decrypt credentials.

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
- **ALWAYS** use the local encrypted store (`~/.hive/credentials`) for persistence
- **ALWAYS** run health checks before storing credentials (when possible)
- **ALWAYS** verify credentials were stored by re-running validation, not by reading them back
- When modifying `~/.bashrc` or `~/.zshrc`, confirm with the user first

## Credential Sources Reference

All credential specs are defined in `tools/src/aden_tools/credentials/`:

| File              | Category      | Credentials                                   | Aden Supported |
| ----------------- | ------------- | --------------------------------------------- | -------------- |
| `llm.py`          | LLM Providers | `anthropic`                                   | No             |
| `search.py`       | Search Tools  | `brave_search`, `google_search`, `google_cse` | No             |
| `email.py`        | Email         | `resend`                                      | No             |
| `integrations.py` | Integrations  | `github`, `hubspot`                           | No / Yes       |

**Note:** Additional LLM providers (Cerebras, Groq, OpenAI) are handled by LiteLLM via environment
variables (`CEREBRAS_API_KEY`, `GROQ_API_KEY`, `OPENAI_API_KEY`) but are not yet in CREDENTIAL_SPECS.
Add them to `llm.py` as needed.

To check what's registered:

```python
from aden_tools.credentials import CREDENTIAL_SPECS
for name, spec in CREDENTIAL_SPECS.items():
    print(f"{name}: aden={spec.aden_supported}, direct={spec.direct_api_key_supported}")
```

## Migration: CredentialManager → CredentialStore

**CredentialManager is deprecated.** Use CredentialStore instead.

| Old (Deprecated)                          | New (Recommended)                                                    |
| ----------------------------------------- | -------------------------------------------------------------------- |
| `CredentialManager()`                     | `CredentialStore.with_encrypted_storage()`                           |
| `creds.get("hubspot")`                    | `store.get("hubspot")` or `store.get_key("hubspot", "access_token")` |
| `creds.validate_for_tools(tools)`         | Use `store.is_available(cred_id)` per credential                     |
| `creds.get_auth_options("hubspot")`       | Check `CREDENTIAL_SPECS["hubspot"].aden_supported`                   |
| `creds.get_setup_instructions("hubspot")` | Access `CREDENTIAL_SPECS["hubspot"]` directly                        |

**Why migrate?**

- **CredentialStore** supports encrypted storage, multi-key credentials, template resolution, and automatic token refresh
- **CredentialManager** only reads from environment variables and .env files (no encryption, no refresh)
- **CredentialStoreAdapter** exists for backward compatibility during migration

```python
# Old way (deprecated)
from aden_tools.credentials import CredentialManager
creds = CredentialManager()
token = creds.get("hubspot")

# New way (recommended)
from core.framework.credentials import CredentialStore
store = CredentialStore.with_encrypted_storage()
token = store.get("hubspot")

# With Aden sync (recommended for OAuth integrations)
store = CredentialStore.with_aden_sync()
token = store.get_key("hubspot", "access_token")
```

## Example Session

```
User: /setup-credentials for my research-agent

Agent: Let me check what credentials your research-agent needs.

[Reads agent config]
$ jq -r '.required_tools[]?' exports/research-agent/agent.json
web_search
google_search

$ jq -r '.graph.nodes[]?.node_type' exports/research-agent/agent.json | sort -u
llm_tool_use

[Maps tools/nodes to credentials using lookup table]
Needed: anthropic, brave_search, google_search, google_cse

[Checks encrypted store metadata index]
$ cat ~/.hive/credentials/metadata/index.json | jq -r '.credentials | keys[]'
anthropic
brave_search

[Checks environment variables]
$ printenv ANTHROPIC_API_KEY > /dev/null 2>&1 && echo "set" || echo "not set"
not set
$ printenv BRAVE_SEARCH_API_KEY > /dev/null 2>&1 && echo "set" || echo "not set"
not set
$ printenv GOOGLE_API_KEY > /dev/null 2>&1 && echo "set" || echo "not set"
not set
$ printenv GOOGLE_CSE_ID > /dev/null 2>&1 && echo "set" || echo "not set"
not set

[Checks HIVE_CREDENTIAL_KEY since credentials found in store]
$ printenv HIVE_CREDENTIAL_KEY > /dev/null 2>&1 && echo "session: set" || echo "session: not set"
session: not set
$ for f in ~/.zshrc ~/.bashrc ~/.profile; do [ -f "$f" ] && grep -q 'HIVE_CREDENTIAL_KEY' "$f" && echo "$f"; done
/Users/user/.zshrc

[Key is in shell config but not current session — sourcing it]
$ source ~/.zshrc

[Computes missing credentials]
Found:
  ✓ anthropic (ANTHROPIC_API_KEY) — in encrypted store
  ✓ brave_search (BRAVE_SEARCH_API_KEY) — in encrypted store
Missing:
  ✗ google_search (GOOGLE_API_KEY)
  ✗ google_cse (GOOGLE_CSE_ID)

Agent: 2 of 4 required credentials are already configured. Only Google Custom
Search needs setup (2 values as a single group).

--- Setting up Google Custom Search (google_search + google_cse) ---

This requires two values that work together.

First, the Google API Key:
1. Go to https://console.cloud.google.com/apis/credentials
2. Create a new project (or select an existing one)
3. Enable the "Custom Search API" from the API Library
4. Go to Credentials > Create Credentials > API Key
5. Copy the generated API key

[AskUserQuestion: "Please provide your Google API key:"]
[User provides key]

Now, the Custom Search Engine ID:
1. Go to https://programmablesearchengine.google.com/controlpanel/all
2. Click "Add" to create a new search engine
3. Under "What to search", select "Search the entire web"
4. Give your search engine a name
5. Click "Create"
6. Copy the Search Engine ID (cx value)

[AskUserQuestion: "Please provide your Google CSE ID:"]
[User provides ID]

[Runs health check with both values - GET /customsearch/v1?q=test&num=1 → 200 OK]
[Stores both in local encrypted store, exports to env]

✓ Google Custom Search credentials valid

All credentials are now configured:
  ✓ anthropic (ANTHROPIC_API_KEY) — already in encrypted store
  ✓ brave_search (BRAVE_SEARCH_API_KEY) — already in encrypted store
  ✓ google_search (GOOGLE_API_KEY) — stored in encrypted store
  ✓ google_cse (GOOGLE_CSE_ID) — stored in encrypted store
  Your agent is ready to run!
```
