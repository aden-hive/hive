# Windows WSL2 Setup Guide for Hive

This guide helps Windows users those who want to set up the Hive framework correctly using 
WSL2 (Windows Subsystem for Linux). This is also alternative 
for Windows users as native PowerShell/Command Prompt setups have known issues.

---

## Why WSL2?

Running Hive directly on Windows somtimes causes several issues:
- `quickstart.sh` fails due to CRLF line ending problems.
- `uv` workspace installation fails on Windows NTFS paths (`/mnt/c/`).
- Symlinks break on Windows filesystem.
- Virtual environment creation fails intermittently.
- Node.js path conflicts between Windows and Linux installations.

WSL2 provides a native Linux environment that resolves all these issues.

---

## Prerequisites

- Windows 10 (version 2004+) or Windows 11
- At least 8GB RAM recommended
- 10GB free disk space

---

## Step 1 — Install WSL2

Open **PowerShell as Administrator** and run:
```powershell
wsl --install
```

This installs WSL2 with Ubuntu by default.

---

## Step 2 — Set Up Ubuntu

After restart, Ubuntu will launch automatically and ask you to:
- Create a **username** (lowercase, no spaces)
- Create a **password**

---

## Step 3 — Update Ubuntu Packages
```bash
sudo apt update && sudo apt upgrade -y
```

---

## Step 4 — Clone Hive in Linux Filesystem

> ⚠️ **Critical:** Always clone inside the Linux home directory (`~`), 
> NOT on the Windows filesystem (`/mnt/c/`).

**Wrong ❌ (causes failures):**
```bash
cd /mnt/c/Users/YourName/projects
git clone https://github.com/aden-hive/hive.git
```

**Correct ✅:**
```bash
cd ~
git clone https://github.com/aden-hive/hive.git
cd hive
```

### Why this matters:
| Location | Filesystem | Result |
|---|---|---|
| `/mnt/c/...` | Windows NTFS | ❌ Breaks uv, symlinks, permissions |
| `~/hive` | Linux ext4 | ✅ Everything works correctly |

---

## Step 5 — Fix Line Endings (If Needed)

If you see this error:
```
/usr/bin/env: 'bash\r': No such file or directory
```

Fix it by running:
```bash
sudo apt install dos2unix -y
dos2unix ~/hive/quickstart.sh
```

This converts Windows CRLF line endings to Linux LF format.

---

## Step 6 — Run Quickstart
```bash
cd ~/hive
./quickstart.sh
```

The quickstart script will automatically:
- Install `uv` (Python package manager).
- Install Python 3.11+ if needed.
- Install Node.js via nvm.
- Set up `core/.venv` and `tools/.venv`.
- Configure `~/.hive/credentials/`.
- Set up your default LLM provider.

---

## Step 7 — Set Up Node.js (If Claude Code Needed)

During quickstart, nvm is installed but may not be active in your 
current terminal session. Fix this by running:
```bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
nvm use 20
```

Make it permanent:
```bash
echo 'export NVM_DIR="$HOME/.nvm"' >> ~/.bashrc
echo '[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"' >> ~/.bashrc
source ~/.bashrc
```

---

## Step 8 — Set API Keys
```bash
# Anthropic
echo 'export ANTHROPIC_API_KEY="your-key-here"' >> ~/.bashrc

# OR Gemini (free alternative)
echo 'export GEMINI_API_KEY="your-key-here"' >> ~/.bashrc

# Apply changes
source ~/.bashrc
```
---

## Step 9 — Verify Installation
```bash
# Check Python version (should be 3.11+)
python3 --version

# Check uv
uv --version

# Check hive CLI
hive --help
```

---

## Step 10 — Run Your First Agent
```bash
# Launch interactive dashboard
hive tui

# Or run an example agent directly
uv run python core/examples/web_summarizer_agent.py
```

---

## Common Errors & Fixes

### Error 1 — `bash\r` not found
```
/usr/bin/env: 'bash\r': No such file or directory
```
**Fix:**
```bash
sudo apt install dos2unix -y
dos2unix quickstart.sh
./quickstart.sh
```

---

### Error 2 — uv workspace installation failed
```
✗ workspace installation failed
```
**Fix:** You are on `/mnt/c/` Windows path. Move to Linux home:
```bash
cd ~
git clone https://github.com/aden-hive/hive.git
cd hive
./quickstart.sh
```

---

### Error 3 — Node not found after nvm install
```
/mnt/c/.../claude: No such file or directory
```
**Fix:**
```bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
nvm install 20
nvm use 20
```

---


### Error 5 — GitHub push password rejected
```
remote: Invalid username or token
```
**Fix:** GitHub no longer accepts passwords. Use a Personal Access Token:
1. Go to https://github.com/settings/tokens/new
2. Select **repo** scope
3. Generate and copy token
4. Use token as password when pushing

---

### Error 6 — Python version too low
```
Python 3.10 found, requires 3.11+
```
**Fix:**
```bash
sudo apt install python3.12 python3.12-venv -y
```

---

## Accessing Files from Windows

Your Linux files are accessible from Windows Explorer:
```
\\wsl$\Ubuntu\home\your-username\hive
```

Or open VS Code directly from WSL:
```bash
cd ~/hive
code .
```

---

## Tips for Windows Users

- ✅ Always work in `~/` not `/mnt/c/`
- ✅ Use WSL2 terminal,
- ✅ Open VS Code with `code .` from WSL terminal
- ✅ Use `source ~/.bashrc` after adding env variables
- ✅ Restart terminal after nvm installation
- ❌ Never run `pip install -e .` directly — use `uv`
- ❌ Never clone into `/mnt/c/` path

---

## Still Having Issues?

Join the community Discord: **https://discord.com/invite/MXE49hrKDk**

Or open an issue: **https://github.com/aden-hive/hive/issues**