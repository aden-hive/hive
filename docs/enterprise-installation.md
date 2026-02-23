# Enterprise Installation Guide

This guide covers installation scenarios for enterprise environments, including corporate proxy configurations and offline/air-gapped installations.

## Corporate Proxy Installation

Many enterprise environments, especially financial institutions, require all internet traffic to go through corporate proxies. This section explains how to configure Hive for these environments.

### Step 1: Configure Proxy Environment Variables

Before running `quickstart.sh`, set your proxy environment variables:

```bash
# Replace with your corporate proxy settings
export HTTP_PROXY="http://proxy.company.com:8080"
export HTTPS_PROXY="http://proxy.company.com:8080"
export NO_PROXY="localhost,127.0.0.1,.company.com"

# For proxies requiring authentication
export HTTP_PROXY="http://username:password@proxy.company.com:8080"
export HTTPS_PROXY="http://username:password@proxy.company.com:8080"
```

Add these to your shell configuration for persistence:

```bash
# Add to ~/.bashrc or ~/.zshrc
echo 'export HTTP_PROXY="http://proxy.company.com:8080"' >> ~/.bashrc
echo 'export HTTPS_PROXY="http://proxy.company.com:8080"' >> ~/.bashrc
source ~/.bashrc
```

### Step 2: Configure Git for Proxy

```bash
# Configure git to use proxy
git config --global http.proxy "http://proxy.company.com:8080"
git config --global https.proxy "http://proxy.company.com:8080"

# For proxies requiring authentication
git config --global http.proxy "http://username:password@proxy.company.com:8080"
git config --global https.proxy "http://username:password@proxy.company.com:8080"
```

### Step 3: Configure pip/uv for Proxy

The `uv` package manager respects standard proxy environment variables. You can also configure it explicitly:

```bash
# uv automatically uses HTTP_PROXY and HTTPS_PROXY
# No additional configuration needed if those are set

# Alternative: Configure pip (used by uv internally)
mkdir -p ~/.config/pip
cat > ~/.config/pip/pip.conf << EOF
[global]
proxy = http://proxy.company.com:8080
trusted-host = pypi.org
                pypi.python.org
                files.pythonhosted.org
EOF
```

### Step 4: Configure SSL Certificates (If Required)

If your corporate proxy uses custom SSL certificates:

```bash
# Set the certificate bundle path
export SSL_CERT_FILE=/path/to/company/ca-bundle.crt
export REQUESTS_CA_BUNDLE=/path/to/company/ca-bundle.crt
export CURL_CA_BUNDLE=/path/to/company/ca-bundle.crt

# For git
git config --global http.sslCAInfo /path/to/company/ca-bundle.crt
```

### Step 5: Verify Proxy Configuration

Test your proxy configuration before running quickstart:

```bash
# Test basic connectivity
curl -v https://pypi.org/

# Test git clone through proxy
git ls-remote https://github.com/adenhq/hive.git

# Test uv installation
uv pip install --dry-run requests
```

### Step 6: Run Quickstart

```bash
# Ensure proxy variables are set in current session
source ~/.bashrc  # or ~/.zshrc

# Clone and run quickstart
git clone https://github.com/adenhq/hive.git
cd hive
./quickstart.sh
```

## Offline/Air-Gapped Installation

For environments with no internet access, you can perform an offline installation by pre-downloading all dependencies.

### Option 1: Pre-Built Package (Recommended)

On an internet-connected machine:

```bash
# 1. Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

# 2. Download all dependencies
uv sync

# 3. Download Playwright browser (optional, for web scraping)
uv run python -m playwright install chromium

# 4. Create a portable archive
cd ..
tar -czvf hive-offline.tar.gz hive/
```

Transfer `hive-offline.tar.gz` to the air-gapped machine:

```bash
# On the air-gapped machine
tar -xzvf hive-offline.tar.gz
cd hive

# Set up environment (no network calls needed)
export HIVE_CREDENTIAL_KEY=$(uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
echo "export HIVE_CREDENTIAL_KEY=\"$HIVE_CREDENTIAL_KEY\"" >> ~/.bashrc

# Link CLI
mkdir -p ~/.local/bin
ln -s $(pwd)/hive ~/.local/bin/hive
```

### Option 2: Wheel-based Installation

On an internet-connected machine:

```bash
# 1. Download all wheels for the target platform
mkdir -p wheels
uv pip download -d wheels/ -r pyproject.toml

# 2. Also download the packages themselves
cd hive
uv sync
uv pip freeze > requirements.txt
cd ..
uv pip download -d wheels/ -r hive/requirements.txt

# 3. Create archive
tar -czvf hive-wheels.tar.gz hive/ wheels/
```

On the air-gapped machine:

```bash
# Extract and install
tar -xzvf hive-wheels.tar.gz
cd hive

# Install from local wheels
uv pip install --no-index --find-links ../wheels/ -e ./core
uv pip install --no-index --find-links ../wheels/ -e ./tools
```

### Playwright Offline Installation

If you need Playwright for web scraping on an air-gapped system:

```bash
# On connected machine, download browser binaries
uv run python -m playwright install chromium

# The browsers are stored in:
# Linux: ~/.cache/ms-playwright/
# macOS: ~/Library/Caches/ms-playwright/
# Windows: %USERPROFILE%\AppData\Local\ms-playwright/

# Archive and transfer
tar -czvf playwright-browsers.tar.gz ~/.cache/ms-playwright/
```

On the air-gapped machine:

```bash
# Extract to the same location
tar -xzvf playwright-browsers.tar.gz -C ~/
```

## Troubleshooting

### Connection Timeout

```bash
# Increase timeout values
export UV_TIMEOUT=300
export PIP_TIMEOUT=300
```

### SSL Certificate Errors

```bash
# Temporarily disable SSL verification (not recommended for production)
export UV_INSECURE_HOST=pypi.org
export PYTHONHTTPSVERIFY=0

# Better: Use proper certificates
export SSL_CERT_FILE=/path/to/ca-bundle.crt
```

### Proxy Authentication Issues

If your proxy uses NTLM authentication:

```bash
# Install cntlm as a local proxy
# cntlm handles NTLM authentication and provides a local proxy

# Configure cntlm
sudo apt install cntlm  # or brew install cntlm on macOS
cntlm -H -d COMPANY -u username  # Generate password hashes

# Edit /etc/cntlm.conf
# Then start cntlm
sudo systemctl start cntlm

# Use local cntlm proxy
export HTTP_PROXY="http://127.0.0.1:3128"
export HTTPS_PROXY="http://127.0.0.1:3128"
```

### Partial Installation Failures

If some packages fail to download:

```bash
# Retry with verbose output
UV_VERBOSE=1 uv sync

# Or install packages one at a time
uv pip install --verbose <package-name>
```

## Additional Resources

- [uv Documentation - Proxy Configuration](https://docs.astral.sh/uv/configuration/proxies/)
- [Python pip Proxy Configuration](https://pip.pypa.io/en/stable/user_guide/#proxy-server)
- [Git Proxy Configuration](https://git-scm.com/docs/git-config#Documentation/git-config.txt-httpproxy)
- [Playwright Offline Installation](https://playwright.dev/python/docs/browsers#installing-browsers-on-ci)

## Support

For enterprise-specific deployment questions, contact the Aden team at contact@adenhq.com.
