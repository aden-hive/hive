# Windows Setup Troubleshooting Guide

This guide addresses common issues Windows users encounter when setting up the Hive Framework.

## Table of Contents
- [Prerequisites](#prerequisites)
- [Common Issues](#common-issues)
  - [1. Quickstart Script Won't Run](#1-quickstart-script-wont-run)
  - [2. API Key Not Persisting](#2-api-key-not-persisting)
  - [3. Hive Command Not Found](#3-hive-command-not-found)
  - [4. Drive Letter Confusion](#4-drive-letter-confusion)
  - [5. MCP Tools Connection Failed](#5-mcp-tools-connection-failed)

---

## Prerequisites

**Required:**
- Windows 10 or later
- Python 3.11 or higher
- Git Bash or WSL (Windows Subsystem for Linux)

**Recommended:**
- Git Bash (comes with [Git for Windows](https://git-scm.com/download/win))
- VS Code with integrated terminal

> **⚠️ Important:** PowerShell and Command Prompt have limited support for bash scripts. Always use **Git Bash** or **WSL** for running Hive setup and commands.

---

## Common Issues

### 1. Quickstart Script Won't Run

**Symptom:**
```bash
./quickstart.sh
# Opens the file in an editor instead of running it
# OR shows "command not found"
```

**Cause:** You're using PowerShell or Command Prompt instead of Git Bash.

**Solution:**

**Option A: Switch to Git Bash in VS Code**
1. In VS Code, click the dropdown arrow next to `+` in the terminal panel
2. Select **"Git Bash"** from the list
3. A new Git Bash terminal will open
4. Run: `./quickstart.sh`

**Option B: Use WSL**
1. Install WSL: `wsl --install` (in PowerShell as admin)
2. Open WSL terminal
3. Navigate to your project directory
4. Run: `./quickstart.sh`

**Option C: Run with bash explicitly** (if Git Bash is installed)
```bash
bash ./quickstart.sh
```

---

### 2. API Key Not Persisting

**Symptom:**
```bash
echo $GROQ_API_KEY
# Shows blank even after quickstart setup
```

**Cause:** Environment variables weren't saved to your shell configuration file, or the file wasn't reloaded.

**Solution:**

**Step 1: Verify your API key was saved**
```bash
cat ~/.bashrc | grep API_KEY
```

If nothing appears, the key wasn't saved. Add it manually:

```bash
echo 'export GROQ_API_KEY="your-actual-api-key-here"' >> ~/.bashrc
```

**Step 2: Reload your shell configuration**
```bash
source ~/.bashrc
```

**Step 3: Verify the key is set**
```bash
echo $GROQ_API_KEY
# Should show your API key
```

**Common mistake:** Opening a new terminal without sourcing `.bashrc`. Each new Git Bash terminal automatically sources `.bashrc`, but if you're in an existing session, you must run `source ~/.bashrc`.

---

### 3. Hive Command Not Found

**Symptom:**
```bash
hive --help
# bash: hive: command not found
```

**Cause:** The `hive` CLI script needs to be run from the project directory, or `~/.local/bin` isn't in your PATH.

**Solution:**

**Option A: Run from project directory** (Simplest)
```bash
cd /path/to/hive
./hive --help
./hive tui
```

**Option B: Create an alias** (Run from anywhere)
```bash
# Add to ~/.bashrc (replace /path/to/hive with your actual path)
echo 'alias hive="cd /path/to/hive && ./hive"' >> ~/.bashrc
source ~/.bashrc

# Now works from any directory
hive --help
```

**Option C: Add to PATH** (Advanced)
```bash
# Add project directory to PATH (replace with your actual path)
echo 'export PATH="/path/to/hive:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

**Why symlinks don't work:** The `hive` script checks if it's being run from the project directory and will fail if executed from elsewhere (even via symlink).

---

### 4. Drive Letter Confusion

**Symptom:**
- Repository is on a different drive than your user folder (e.g., `D:\projects\hive`)
- Confused about where configuration and credentials should be stored

**Clarification: This is Normal and Correct**

The separation between code and configuration is intentional:

**Your Repository Location (can be anywhere):**
```
D:\projects\hive\  (or wherever you cloned it)
├── core/              ← Framework code
├── tools/             ← MCP tools
├── examples/          ← Example agents
├── exports/           ← YOUR custom agents go here
└── hive               ← CLI script
```

**C: Drive (User Configuration):**
```
C:\Users\YourName\
├── .hive/
│   ├── credentials/           ← Encrypted API keys
│   └── configuration.json     ← LLM provider settings
└── .bashrc                    ← Shell config (API keys, PATH)
```

**What happens when you run hive:**
1. ✅ Executes code from **D: drive** (repository)
2. ✅ Reads API keys from **C: drive** (`~/.hive/`)
3. ✅ Creates/runs agents in **D: drive** (`exports/`)

**You don't need to move anything.** This setup follows standard practices where:
- Code repositories can be anywhere
- User configuration stays in the home directory
- The system automatically finds configuration files via `~/.hive/`

---

### 5. MCP Tools Connection Failed

**Symptom:**
```
Failed to register MCP server: Failed to connect to MCP server: Connection closed
Warning: ANTHROPIC_API_KEY not set. LLM calls will fail.
```

**Cause:** Example agents may have MCP tools server connection issues or expect a different LLM provider than configured.

**Solution:**

**Step 1: Verify configuration exists**
```bash
cat ~/.hive/configuration.json
```

If file doesn't exist, create it:
```bash
mkdir -p ~/.hive
cat > ~/.hive/configuration.json << 'EOF'
{
  "llm": {
    "provider": "groq",
    "model": "mixtral-8x7b-32768",
    "api_key_env_var": "GROQ_API_KEY"
  },
  "created_at": "2026-02-09T00:00:00+00:00"
}
EOF
```

**Step 2: Verify API key is set**
```bash
source ~/.bashrc
echo $GROQ_API_KEY
```

**Step 3: For example agents with connection issues**

The pre-built example agents may have MCP server configuration issues. Consider:

**Option A: Build your own agent** (Recommended)
- Use `/hive` skill in Claude Code to build a fresh agent
- It will be configured correctly for your setup

**Option B: Run agents directly without TUI**
```bash
cd examples/templates/deep_research_agent
PYTHONPATH=../../core:.. uv run python -m deep_research_agent run --topic "test"
```

---

## General Troubleshooting Tips

### Check Your Environment
```bash
# Verify you're in Git Bash (not PowerShell)
echo $SHELL
# Should show: /usr/bin/bash or similar

# Check Python version
python --version
# Should be 3.11 or higher

# Verify packages are installed
uv run python -c "import framework; import aden_tools; print('Imports OK')"
```

### Start Fresh
If nothing works, you can reset your configuration:

```bash
# Backup existing config
mv ~/.hive ~/.hive.backup

# Re-run quickstart
./quickstart.sh
```

### Get Help
- [Discord Community](https://discord.com/invite/MXE49hrKDk)
- [GitHub Issues](https://github.com/adenhq/hive/issues)
- Include your OS version, Python version, and error messages

---

## Next Steps

Once setup is complete:
1. Run `hive tui` to explore example agents
2. Use `/hive` in Claude Code to build your first agent
3. Read [Developer Guide](developer-guide.md) for more details

---

**Last Updated:** 2026-02-09
**Tested On:** Windows 11, Git Bash 2.43, Python 3.13
