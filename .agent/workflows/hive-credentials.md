---
description: Set up and install credentials for an agent. Detects missing credentials from agent config, offers Aden OAuth or direct API key options, validates with health checks, and stores securely in the encrypted store at ~/.hive/credentials.
when_to_use: |
  - Before running or testing an agent for the first time
  - Agent fails with "missing required credentials"
  - After building a new agent that uses tools requiring API keys
  - Need to configure Aden OAuth or direct API keys
---

use hive-credentials skill
