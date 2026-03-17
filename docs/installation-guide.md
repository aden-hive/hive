# Hive Installation Guide

Step-by-step instructions to install Aden Hive on your machine. Follow every step in order. The wizard flow below was captured by running the quickstart on a real install.

---

## Prerequisites

Before you begin, ensure you have:

| Requirement | Version | Notes |
|-------------|---------|--------|
| **Python** | 3.11+ | 3.12 or 3.13 recommended. Check with `python3 --version`. |
| **uv** | Latest | Python package manager. Installed in Step 2 if missing. |
| **Node.js** | 20+ | Required for the web dashboard. Check with `node --version`. |
| **Chrome or Edge** | Any | Optional; needed for browser-automation (GCU) tools. |

---

## Step 1: Clone the repository

```bash
git clone https://github.com/aden-hive/hive.git
cd hive
```

(If you use a fork, clone your fork and add the upstream remote as needed.)

---

## Step 2: Install uv (if not already installed)

Hive uses [uv](https://docs.astral.sh/uv/) for Python dependencies. Install it with:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Then ensure `uv` is on your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
uv --version
```

To make this permanent, add that `export` line to your shell config (`~/.zshrc`, `~/.bashrc`, or `~/.profile`).

---

## Step 3: Install Python dependencies

From the project root:

```bash
cd /path/to/hive
uv sync
```

This will:

- Create a virtual environment at `.venv` in the project root (if needed)
- Download a compatible Python (e.g. 3.11) if required
- Install the `framework` and `tools` packages and all dependencies

Verify:

```bash
uv run python -c "import framework; import aden_tools; print('OK')"
```

You should see `OK`.

---

## Step 4: Install Node.js 20+ (for the web dashboard)

The dashboard is built with Node. You need **Node 20 or newer**.

**If you already have Node 20+:**

```bash
node --version   # should show v20.x or higher
```

**If you use nvm:**

```bash
nvm install 20
nvm use 20
```

**If you don’t have nvm**, install it first:

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh | bash
# Restart your terminal or: source ~/.nvm/nvm.sh
nvm install 20
nvm use 20
```

---

## Step 5: Build the frontend dashboard

From the project root:

```bash
cd core/frontend
npm install --no-fund --no-audit
npm run build
```

You should see output ending with something like:

```
dist/index.html                  0.46 kB
dist/assets/index-....css        ...
dist/assets/index-....js         ...
✓ built in ...
```

If you see an error about **“Cannot find native binding”** (e.g. from `@tailwindcss/oxide`), you are likely on Node &lt; 20. Switch to Node 20+, remove `node_modules` and `package-lock.json`, then run `npm install` and `npm run build` again.

---

## Step 6: Set up the credential store and config directory

Hive stores config and encrypted credentials under `~/.hive/`. The quickstart script creates these; if you are installing manually, ensure the credential key exists.

**Option A – Run quickstart (recommended)**  
Quickstart will create `~/.hive/`, the credential key, and `~/.hive/configuration.json`:

```bash
cd /path/to/hive
./quickstart.sh
```

After Steps 1–3 (Python, packages, frontend, imports), you’ll see **“Select your default LLM provider”** with two groups:

- **Subscription modes (no API key purchase needed):**  
  Options 1–6 (Claude Code, ZAI Code, Codex, MiniMax, Kimi, Hive LLM). If you have the matching app installed, the line shows **“(credential detected)”** in green — the wizard does **not** ask you to paste a key; it uses that credential and writes e.g. `use_claude_code_subscription: true` to config.
- **API key providers:**  
  Options 7–11 (Anthropic, OpenAI, Gemini, Groq, Cerebras). For these the wizard **does** ask you to paste a key and shows the signup URL for that provider (e.g. for option 7: **“Get your API key from: https://console.anthropic.com/settings/keys”** and **“Paste your Anthropic API key (or press Enter to skip):”**).

**Recommendation:** Choose **Option 7: Anthropic (Claude) - Recommended** and paste a key from [console.anthropic.com](https://console.anthropic.com/settings/keys). Do **not** choose **Option 1: Claude Code Subscription** unless you’re sure it works for you; that path uses the existing Claude app token and often causes `invalid_request_error` with Hive’s API calls.

Paste your Anthropic API key when prompted. Quickstart will write it to your shell config (e.g. `export ANTHROPIC_API_KEY="sk-ant-..."`).

**Option B – Manual setup (no quickstart)**  
If you skip quickstart:

1. Create the credential key and directories:

   ```bash
   uv run python -c "
   from cryptography.fernet import Fernet
   import os
   key_dir = os.path.expanduser('~/.hive/secrets')
   os.makedirs(key_dir, mode=0o700, exist_ok=True)
   key_file = os.path.join(key_dir, 'credential_key')
   if not os.path.exists(key_file):
       k = Fernet.generate_key().decode()
       with open(key_file, 'w') as f: f.write(k)
       os.chmod(key_file, 0o600)
   os.makedirs(os.path.expanduser('~/.hive/credentials/credentials'), exist_ok=True)
   os.makedirs(os.path.expanduser('~/.hive/credentials/metadata'), exist_ok=True)
   idx = os.path.expanduser('~/.hive/credentials/metadata/index.json')
   if not os.path.exists(idx):
       with open(idx, 'w') as f: f.write('{\"credentials\": {}, \"version\": \"1.0\"}')
   print('Credential store ready')
   "
   ```

2. Create `~/.hive/configuration.json`:

   ```json
   {
     "llm": {
       "provider": "anthropic",
       "model": "claude-sonnet-4-20250514",
       "max_tokens": 8192,
       "max_context_tokens": 180000,
       "api_key_env_var": "ANTHROPIC_API_KEY"
     },
     "gcu_enabled": true
   }
   ```

3. Set your API key in the same terminal (or in your shell config):

   ```bash
   export ANTHROPIC_API_KEY="sk-ant-your-key-here"
   ```

   Get a key from [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys).

---

## Step 7: Run the dashboard

From the **project root**:

```bash
cd /path/to/hive
./hive open
```

Or, if `hive` is not in your PATH:

```bash
uv run hive open
```

The server starts and opens the dashboard in your browser (e.g. http://localhost:8787). You can chat with the Queen and run agents from there.

To run the CLI without the browser:

```bash
./hive --help
./hive list
```

---

## Summary checklist

- [ ] Repository cloned, `cd hive`
- [ ] `uv` installed and on PATH
- [ ] `uv sync` run successfully
- [ ] Node 20+ installed (e.g. via `nvm use 20`)
- [ ] `core/frontend`: `npm install` and `npm run build` completed
- [ ] Credential store present under `~/.hive/`
- [ ] `~/.hive/configuration.json` exists with `api_key_env_var` (or quickstart was run)
- [ ] `ANTHROPIC_API_KEY` set in the environment (or in shell config and terminal restarted)
- [ ] `./hive open` starts the server and dashboard

---

## Troubleshooting

### Startup: `litellm.BadRequestError: AnthropicException - invalid_request_error`

- **Cause:** Hive is using a token that is not valid for the standard Anthropic API (e.g. Claude Code subscription token).
- **Fix:** Use an **API key** from [console.anthropic.com](https://console.anthropic.com/settings/keys), not the Claude Code subscription flow.
  1. Open `~/.hive/configuration.json`.
  2. Remove the line `"use_claude_code_subscription": true` (or set it to `false`).
  3. Ensure you have `"api_key_env_var": "ANTHROPIC_API_KEY"` in the `llm` section.
  4. Set `export ANTHROPIC_API_KEY="sk-ant-..."` in your shell (or in `~/.zshrc` / `~/.bashrc` and open a new terminal).
  5. Restart Hive (`./hive open`).

### When sending a message: `Queen executor failed: cannot access local variable 'turn_tokens'`

- **Cause:** Bug in the event loop when the Queen hits an LLM error (e.g. the Anthropic error above).
- **Fix:** Fix the API key/configuration as above so the first error goes away. The Queen then may not hit this path. If you are on a fork, pull the latest from upstream; the fix is to initialize `turn_tokens` before the retry loop in `core/framework/graph/event_loop_node.py`.

### Quickstart said “credential detected” but I didn’t paste a key

- If you chose **Option 1: Claude Code Subscription** (or another subscription option), the wizard shows **“(credential detected)”** next to that line and does **not** ask for a key — it uses the existing app credential and writes e.g. `use_claude_code_subscription: true` to config. That token often does not work with Hive’s Anthropic API calls.
- **Fix:** Re-run quickstart and choose **Option 7: Anthropic (Claude) - Recommended**; when it shows **“Get your API key from: https://console.anthropic.com/settings/keys”** and **“Paste your Anthropic API key”**, paste a key from console.anthropic.com. Or edit `~/.hive/configuration.json` as in the “invalid_request_error” section above.

### `Error: hive must be run from the project directory`

- Always run `./hive` or `uv run hive` from the **repository root** (where `pyproject.toml` and `core/` live).

### `Virtual environment not found` / `Run ./quickstart.sh first`

- Run `uv sync` from the project root to create `.venv`.

### Frontend build fails with `Cannot find native binding` (Tailwind/Oxide)

- Use **Node 20+**. Install with `nvm install 20` and `nvm use 20`, then in `core/frontend` run `rm -rf node_modules package-lock.json`, `npm install`, and `npm run build`.

---

## Next steps

- [Getting Started](getting-started.md) – Build your first agent
- [Configuration](configuration.md) – Full configuration reference
- [Developer Guide](developer-guide.md) – Architecture and development workflow
