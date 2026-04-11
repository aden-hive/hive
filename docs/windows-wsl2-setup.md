# Windows WSL2 Setup Guide

This guide walks Windows contributors through setting up Aden Hive inside WSL2 (Windows Subsystem for Linux). WSL2 gives you a full Linux environment on Windows and is the recommended path for contributors who want bash tooling, shell scripts, and a closer match to CI.

> **Prefer native Windows?** See the [environment-setup.md](./environment-setup.md) Windows section and use `quickstart.ps1` instead.

---

## 1. Enable WSL2 and Install Ubuntu

Open **PowerShell as Administrator** and run:

```powershell
wsl --install
```

This installs WSL2 and the Ubuntu distro by default. Restart when prompted.

After rebooting, Ubuntu opens automatically and asks you to create a UNIX username and password. Once that's done, your WSL2 environment is ready.

To verify WSL2 is running (not WSL1):

```powershell
wsl --list --verbose
```

The `VERSION` column should show `2` for your Ubuntu distro. If it shows `1`, upgrade with:

```powershell
wsl --set-version Ubuntu 2
```

---

## 2. Install uv and Python Inside WSL2

Open your Ubuntu terminal (search "Ubuntu" in Start, or run `wsl` in PowerShell).

Install `uv`, which manages Python and all project dependencies:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Reload your shell so `uv` is on the PATH:

```bash
source ~/.bashrc
```

`uv` will automatically fetch the correct Python version (3.11+) when you run the project setup — you do not need to install Python separately.

---

## 3. Clone the Repo and Run quickstart.sh

```bash
# Clone inside WSL2 (use the WSL2 filesystem, not /mnt/c/...)
git clone https://github.com/aden-hive/hive.git
cd hive

# Fix line endings and script permissions (see Troubleshooting below)
git config core.autocrlf false
chmod +x quickstart.sh

# Run automated setup
./quickstart.sh
```

The script installs the `framework` and `aden_tools` packages, initialises the credential store, and verifies the installation.

---

## 4. Running Tests from WSL2

```bash
# Run core tests
uv run pytest core/tests/

# Run tool tests (mocked, no real API calls)
uv run pytest tools/tests/

# Lint and format checks
uv run ruff check core/ tools/
uv run ruff format --check core/ tools/
```

---

## 5. Accessing the Dashboard from Your Windows Browser

The Hive web dashboard runs inside WSL2 but is accessible from your Windows browser because WSL2 bridges ports automatically.

Start the dashboard:

```bash
hive open
```

Then open your Windows browser and go to `http://localhost:8000` (or whatever port the output shows). Modern WSL2 (Windows 11 / WSL2 kernel 5.15+) forwards ports automatically. If the page does not load, check the WSL2 IP manually:

```bash
# Inside WSL2
ip route show default | awk '{print $3}'
```

Use that IP address in the browser instead of `localhost`.

---

## 6. Troubleshooting Common Issues

### Line ending problems (`core.autocrlf`)

If scripts fail with `^M` errors or unexpected token errors, Windows line endings (CRLF) have crept into shell scripts. Fix this before running anything:

```bash
git config core.autocrlf false
# Re-checkout files to apply the setting to already-cloned files
git rm --cached -r .
git reset --hard
```

To prevent this globally for all future clones on this machine:

```bash
git config --global core.autocrlf false
```

### Permission denied: `./quickstart.sh`

Shell scripts cloned from Windows or copied across the `/mnt/c/` boundary sometimes lose execute permissions. Fix with:

```bash
chmod +x quickstart.sh
```

### Node.js / npm for Frontend Development

If you are working on the React frontend, install Node.js inside WSL2 using `nvm` (Node Version Manager):

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 18
nvm use 18
node --version   # should print v18.x.x
```

Then install frontend dependencies:

```bash
cd <frontend-directory>
npm install
npm run dev
```

### File permission issues with `/mnt/c/` paths

Avoid cloning or working with the repo under `/mnt/c/Users/...` (the Windows filesystem). The Windows filesystem is mounted with fixed permissions and does not support Linux file modes properly, which causes `chmod` to have no effect and `uv` or `pytest` to behave unexpectedly.

Always clone into a native WSL2 path such as `~/hive` (`/home/<username>/hive`).

### `uv` not found after install

If `uv` is not found after installation, add it to your PATH manually:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

### Python version conflict

`uv` manages Python automatically. If you have a system Python installed separately and it causes conflicts, let `uv` handle the version:

```bash
uv python install 3.12
uv python pin 3.12
```

---

## Summary

| Step | Command |
|------|---------|
| Enable WSL2 | `wsl --install` (PowerShell, admin) |
| Install uv | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Clone repo | `git clone https://github.com/aden-hive/hive.git` |
| Fix permissions | `chmod +x quickstart.sh` |
| Run setup | `./quickstart.sh` |
| Run tests | `uv run pytest core/tests/` |
| Open dashboard | `hive open` → browser at `http://localhost:8000` |

For further help, visit the [Discord community](https://discord.com/invite/MXE49hrKDk) or open a [GitHub issue](https://github.com/aden-hive/hive/issues).
