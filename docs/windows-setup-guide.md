# Windows Setup Guide for Aden Hive

Complete guide for setting up Aden Hive on Windows using WSL (recommended) or Git Bash.

## Table of Contents

- [Why WSL?](#why-wsl)
- [Quick Decision Guide](#quick-decision-guide)
- [WSL2 Setup (Recommended)](#wsl2-setup-recommended)
- [Hive Installation in WSL](#hive-installation-in-wsl)
- [Git Bash Alternative](#git-bash-alternative)
- [Troubleshooting](#troubleshooting)
- [IDE Integration](#ide-integration)
- [FAQ](#faq)

---

## Why WSL?

Aden Hive uses bash scripts and Unix-style tools that work best in a Linux environment. While Git Bash provides some compatibility, **WSL (Windows Subsystem for Linux)** offers:

- **Full Linux compatibility** - Native bash, Python, and package management
- **Better performance** - Faster file I/O for agent operations
- **Fewer edge cases** - Avoid path conversion and script execution issues
- **Production parity** - Develop in an environment similar to deployment

**Bottom line:** WSL provides the smoothest experience for building and running agents.

---

## Quick Decision Guide

**Use WSL if:**
- You're setting up Hive for the first time
- You plan to build custom agents
- You want the most reliable experience
- You're comfortable with basic Linux commands

**Use Git Bash if:**
- You already have Git Bash installed and configured
- You need a quick test without installing WSL
- You understand the limitations (see [Git Bash Alternative](#git-bash-alternative))

---

## WSL2 Setup (Recommended)

### Prerequisites

- **Windows 10** version 2004 or higher (Build 19041+), **OR**
- **Windows 11** (any version)

To check your Windows version:
```powershell
winver
```

### Step 1: Install WSL

Open **PowerShell as Administrator** and run:

```powershell
wsl --install
```

This command will:
- Enable WSL and Virtual Machine Platform features
- Download and install the latest Linux kernel
- Install Ubuntu as the default distribution
- Set WSL 2 as the default version

**Restart your computer** when prompted.

### Step 2: Set Up Ubuntu

After reboot, Ubuntu will launch automatically:

1. **Create a username** (lowercase, no spaces)
   ```
   Enter new UNIX username: yourname
   ```

2. **Create a password** (you won't see characters as you type)
   ```
   New password: 
   Retype new password:
   ```

3. **Update packages** (recommended)
   ```bash
   sudo apt update && sudo apt upgrade -y
   ```

### Step 3: Verify Installation

Check that WSL 2 is running:

```powershell
# In PowerShell
wsl --list --verbose
```

You should see:
```
  NAME      STATE           VERSION
* Ubuntu    Running         2
```

If VERSION shows `1`, upgrade to WSL 2:
```powershell
wsl --set-version Ubuntu 2
```

### Step 4: Install Python 3.11+

Ubuntu 22.04 LTS comes with Python 3.10. Install Python 3.11:

```bash
# In WSL terminal
sudo apt update
sudo apt install -y python3.11 python3.11-venv python3-pip
```

Verify installation:
```bash
python3.11 --version
# Should show: Python 3.11.x
```

### Step 5: Install uv (Python Package Manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Restart your terminal or run:
```bash
source $HOME/.cargo/env
```

Verify:
```bash
uv --version
```

---

## Hive Installation in WSL

### Step 1: Clone the Repository

**Important:** Clone inside the WSL filesystem for best performance.

```bash
# Navigate to your home directory
cd ~

# Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive
```

> **Note:** Avoid cloning to `/mnt/c/` (Windows filesystem). WSL filesystem (`~` or `/home/username/`) is much faster.

### Step 2: Run Quickstart Script

```bash
./quickstart.sh
```

This will:
- Verify Python 3.11+
- Install framework and tools packages
- Set up virtual environments
- Verify all dependencies

### Step 3: Set Up API Keys

Add your API keys to your shell profile:

```bash
# Edit .bashrc
nano ~/.bashrc

# Add at the end:
export ANTHROPIC_API_KEY="your-key-here"
export OPENAI_API_KEY="your-key-here"  # if using OpenAI

# Save: Ctrl+O, Enter, Ctrl+X
```

Reload your shell:
```bash
source ~/.bashrc
```

### Step 4: Verify Installation

```bash
# Test framework import
uv run python -c "import framework; print('✓ framework OK')"

# Test tools import
uv run python -c "import aden_tools; print('✓ aden_tools OK')"
```

You're ready to build agents! 🎉

---

## Git Bash Alternative

Git Bash provides a Unix-like shell on Windows but has limitations.

### When to Use Git Bash

- Quick testing without WSL setup
- You're already familiar with Git Bash
- WSL installation is not possible (corporate restrictions)

### Installation

1. Download [Git for Windows](https://git-scm.com/download/win)
2. During installation, select **"Use Git and optional Unix tools from the Command Prompt"**
3. Complete installation

### Setup Steps

```bash
# Clone repository
git clone https://github.com/adenhq/hive.git
cd hive

# Install Python 3.11+ from python.org if not already installed
# Verify Python version
python --version

# Install uv
pip install uv

# Run quickstart (may have issues)
./quickstart.sh
```

### Known Limitations

1. **Python App Execution Aliases**
   - Windows may intercept `python` commands
   - **Fix:** Disable in Windows Settings → Apps → App Execution Aliases

2. **Path Conversion Issues**
   - Git Bash may incorrectly convert Unix paths
   - **Workaround:** Use `MSYS_NO_PATHCONV=1` before commands

3. **Script Execution Failures**
   - Some bash scripts may not run correctly
   - **Workaround:** Run commands manually instead of using `./quickstart.sh`

4. **Performance**
   - Slower than WSL for file-intensive operations

### Recommendation

If you encounter issues with Git Bash, **switch to WSL**. The setup time investment pays off in reliability.

---

## Troubleshooting

### WSL Issues

#### "WSL 2 requires an update to its kernel component"

**Solution:**
1. Download the [WSL2 Linux kernel update package](https://aka.ms/wsl2kernel)
2. Install the update
3. Run `wsl --install` again

#### "The requested operation requires elevation"

**Solution:** Run PowerShell as Administrator (Right-click → "Run as administrator")

#### "Virtual Machine Platform is not enabled"

**Solution:**
```powershell
# In PowerShell as Administrator
dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
```
Restart your computer.

#### Permission Denied Errors in WSL

**Cause:** Files cloned in Windows filesystem (`/mnt/c/`)

**Solution:** Clone repository in WSL filesystem:
```bash
cd ~
git clone https://github.com/adenhq/hive.git
```

#### Slow Performance in WSL

**Cause:** Working in `/mnt/c/` (Windows filesystem)

**Solution:** Always work in WSL filesystem (`~` or `/home/username/`)

#### Network/DNS Issues in WSL

**Solution:** Create or edit `/etc/wsl.conf`:
```bash
sudo nano /etc/wsl.conf
```

Add:
```ini
[network]
generateResolvConf = false
```

Then create `/etc/resolv.conf`:
```bash
sudo rm /etc/resolv.conf
sudo nano /etc/resolv.conf
```

Add:
```
nameserver 8.8.8.8
nameserver 8.8.4.4
```

Restart WSL:
```powershell
# In PowerShell
wsl --shutdown
```

### Git Bash Issues

#### Python App Execution Aliases Conflict

**Symptom:** `python` command opens Microsoft Store

**Solution:**
1. Open Windows Settings
2. Go to Apps → App Execution Aliases
3. Disable "App Installer" for `python.exe` and `python3.exe`

#### "bash: ./quickstart.sh: Permission denied"

**Solution:**
```bash
chmod +x quickstart.sh
./quickstart.sh
```

#### Path Conversion Problems

**Symptom:** Paths like `/c/Users/...` instead of `C:\Users\...`

**Solution:** Prefix command with:
```bash
MSYS_NO_PATHCONV=1 ./quickstart.sh
```

### General Windows Issues

#### "ModuleNotFoundError: No module named 'framework'"

**Solution:**
```bash
cd core
uv pip install -e .
```

#### "externally-managed-environment" Error

**Solution:** Create a virtual environment:
```bash
uv venv
source .venv/bin/activate  # WSL/Git Bash
# .venv\Scripts\activate   # PowerShell
./quickstart.sh
```

#### Python Version Conflicts

**Symptom:** Multiple Python versions installed

**Solution in WSL:**
```bash
# Use python3.11 explicitly
sudo update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
```

#### PowerShell Execution Policy

**Symptom:** "running scripts is disabled on this system"

**Solution:**
```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

---

## IDE Integration

### VSCode with WSL

**Recommended setup for the best development experience.**

1. **Install WSL Extension**
   - Open VSCode
   - Install "WSL" extension by Microsoft

2. **Open Project in WSL**
   ```bash
   # In WSL terminal, inside hive directory
   code .
   ```

3. **Configure Python Path**
   - VSCode will detect WSL Python automatically
   - Select Python 3.11+ from WSL

4. **Terminal Integration**
   - VSCode terminal will use WSL bash by default
   - All commands run in WSL environment

### Cursor with WSL

1. **Open WSL Terminal**
   ```bash
   cd ~/hive
   cursor .
   ```

2. **Enable MCP Servers**
   - Open Command Palette (`Cmd+Shift+P` / `Ctrl+Shift+P`)
   - Run `MCP: Enable`
   - Restart Cursor

### File System Best Practices

- **DO:** Keep all project files in WSL filesystem (`~/hive`)
- **DON'T:** Work in `/mnt/c/` (Windows drives)
- **Access WSL files from Windows:** `\\wsl$\Ubuntu\home\username\hive`
- **Performance:** WSL filesystem is 2-5x faster for file operations

---

## FAQ

### Can I use native Windows (PowerShell/CMD)?

**Not recommended.** The `quickstart.sh` script and many agent operations rely on bash and Unix tools. While some workarounds exist, you'll encounter frequent issues. Use WSL for the best experience.

### Should I install Python in Windows or WSL?

**Install Python in WSL only.** If you install Python in both Windows and WSL, you may encounter conflicts. Keep your development environment entirely in WSL.

### How do I access WSL files from Windows Explorer?

**Method 1:** Type in Windows Explorer address bar:
```
\\wsl$\Ubuntu\home\yourusername\hive
```

**Method 2:** From WSL terminal:
```bash
explorer.exe .
```

This opens the current WSL directory in Windows Explorer.

### Can I use Windows Git with WSL?

**No.** Use Git installed in WSL:
```bash
sudo apt install git
```

Using Windows Git with WSL filesystem causes permission and line-ending issues.

### How much disk space does WSL need?

- **WSL itself:** ~500 MB
- **Ubuntu:** ~1 GB
- **Hive + dependencies:** ~2 GB
- **Total:** ~4 GB recommended

### Does WSL affect Windows performance?

**No.** WSL 2 runs in a lightweight VM that only uses resources when active. When not in use, it consumes minimal memory.

### Can I run multiple Linux distributions?

**Yes.** You can install multiple distributions (Ubuntu, Debian, etc.) and switch between them:
```powershell
wsl --list
wsl -d Ubuntu
wsl -d Debian
```

### How do I uninstall WSL?

```powershell
# Unregister distribution
wsl --unregister Ubuntu

# Disable WSL feature (optional)
dism.exe /online /disable-feature /featurename:Microsoft-Windows-Subsystem-Linux
```

### Where can I get more help?

- **Aden Discord:** https://discord.com/invite/MXE49hrKDk
- **GitHub Issues:** https://github.com/adenhq/hive/issues
- **WSL Documentation:** https://learn.microsoft.com/en-us/windows/wsl/

---

## Next Steps

Now that you have Hive set up on Windows:

1. **Build your first agent:**
   ```bash
   claude> /building-agents-construction
   ```

2. **Read the complete setup guide:**
   - [ENVIRONMENT_SETUP.md](../ENVIRONMENT_SETUP.md)

3. **Explore example agents:**
   - [examples/](../examples/)

4. **Join the community:**
   - [Discord](https://discord.com/invite/MXE49hrKDk)

---

**Happy agent building! 🚀**
