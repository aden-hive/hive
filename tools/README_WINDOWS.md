# Windows Installation Guide for Hive

If you are on Windows, the standard `./scripts/setup-python.sh` may not work directly in CMD or PowerShell. Follow these steps to set up your environment using `uv`.

### Prerequisites
1. **Install uv**: Open PowerShell and run:
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm [https://astral.sh/uv/install.ps1](https://astral.sh/uv/install.ps1) | iex"