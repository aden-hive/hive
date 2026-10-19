# GPG Commit Signing — Setup Guide

Every contributor must sign their commits with a GPG key.  
This ensures all commits show as **Verified** on GitHub and proves the commit came from you.

---

## How It Works

When you commit, Git asks for your **GPG passphrase**.  
GitHub then checks your commit's signature against the **public key you uploaded to your account**.  
If they match → **Verified**. Simple.

---

## 🪟 Windows

### 1. Install GPG

Download and install **Gpg4win** → https://gpg4win.org/download.html  
This gives you the `gpg` command in Git Bash.

### 2. Generate Your GPG Key

Open **Git Bash** and run:
```bash
gpg --full-generate-key
```

Answer the prompts:
- Kind of key → **1** (RSA and RSA)
- Keysize → **4096**
- Key validity → **0** (does not expire)
- Real name → Your full name
- Email → **Must match your GitHub verified email exactly**
- Comment → leave blank or add description of what's the use of key.
- Passphrase → **Set a strong passphrase — you'll enter this on every commit**
### 3. Find Your Key ID
```bash
gpg --list-secret-keys --keyid-format=long
```

Output looks like:
```
sec   rsa4096/3AA5C34371567BD2 2024-01-01 [SC]
```

Your key ID is the part after `rsa4096/` → `3AA5C34371567BD2`

### 4. Tell Git to Use Your Key
```bash
git config --global user.signingkey 3AA5C34371567BD2
git config --global commit.gpgsign true
git config --global gpg.program "C:/Program Files (x86)/GnuPG/bin/gpg.exe"
```

> If Gpg4win installed elsewhere, adjust the path. Check in File Explorer under `Program Files`.

### 5. Export Your Public Key
```bash
gpg --armor --export 3AA5C34371567BD2
```

Copy everything including `-----BEGIN PGP PUBLIC KEY BLOCK-----` and `-----END PGP PUBLIC KEY BLOCK-----`.

### 6. Add Public Key to GitHub

1. Go to **GitHub → Settings → SSH and GPG keys**
2. Click **New GPG key**
3. Paste your exported public key
4. Click **Add GPG key**

### 7. Test It
```bash
git commit -m "test: gpg signing"
```

A dialog box (Kleopatra) or Git Bash prompt will ask for your **passphrase**.  
Enter it → commit is created.

Check on GitHub → the commit should show **Verified**.

---

## 🐧 Linux

### 1. Install GPG
```bash
# Debian / Ubuntu
sudo apt update && sudo apt install gnupg -y

# Fedora / RHEL
sudo dnf install gnupg2 -y

# Arch
sudo pacman -S gnupg
```

### 2. Generate Your GPG Key
```bash
gpg --full-generate-key
```

Answer the prompts:
- Kind of key → **1** (RSA and RSA)
- Keysize → **4096**
- Key validity → **0** (does not expire)
- Real name → Your full name
- Email → **Must match your GitHub verified email exactly**
- Passphrase → **Set a strong passphrase — you'll enter this on every commit**

### 3. Find Your Key ID
```bash
gpg --list-secret-keys --keyid-format=long
```
```
sec   rsa4096/3AA5C34371567BD2 2024-01-01 [SC]
```

Your key ID → `3AA5C34371567BD2`

### 4. Tell Git to Use Your Key
```bash
git config --global user.signingkey 3AA5C34371567BD2
git config --global commit.gpgsign true
```

### 5. Fix the GPG TTY (Important!)

Add this to your `~/.bashrc` or `~/.zshrc`:
```bash
export GPG_TTY=$(tty)
```

Then reload:
```bash
source ~/.bashrc
```

> Without this, Git may silently fail to sign and show `error: gpg failed to sign the data`.

### 6. Export Your Public Key
```bash
gpg --armor --export 3AA5C34371567BD2
```

Copy the full output.

### 7. Add Public Key to GitHub

1. Go to **GitHub → Settings → SSH and GPG keys**
2. Click **New GPG key**
3. Paste your exported public key
4. Click **Add GPG key**

### 8. Test It
```bash
git commit -m "test: gpg signing"
```

Your terminal will prompt: `Enter passphrase for key '...':`  
Enter your passphrase → commit is created and signed.

Push and check GitHub → **Verified**.

---

## 🍎 macOS

### 1. Install GPG
```bash
brew install gnupg pinentry-mac
```

### 2. Configure Pinentry (Required — otherwise passphrase prompt won't appear)
```bash
echo "pinentry-program $(which pinentry-mac)" >> ~/.gnupg/gpg-agent.conf
gpgconf --kill gpg-agent
```

### 3. Generate Your GPG Key
```bash
gpg --full-generate-key
```

Answer the prompts:
- Kind of key → **1** (RSA and RSA)
- Keysize → **4096**
- Key validity → **0** (does not expire)
- Real name → Your full name
- Email → **Must match your GitHub verified email exactly**
- Passphrase → **Set a strong passphrase — you'll enter this on every commit**

### 4. Find Your Key ID
```bash
gpg --list-secret-keys --keyid-format=long
```
```
sec   rsa4096/3AA5C34371567BD2 2024-01-01 [SC]
```

Your key ID → `3AA5C34371567BD2`

### 5. Tell Git to Use Your Key
```bash
git config --global user.signingkey 3AA5C34371567BD2
git config --global commit.gpgsign true
git config --global gpg.program gpg
```

### 6. Export Your Public Key
```bash
gpg --armor --export 3AA5C34371567BD2
```

Copy the full output.

### 7. Add Public Key to GitHub

1. Go to **GitHub → Settings → SSH and GPG keys**
2. Click **New GPG key**
3. Paste your exported public key
4. Click **Add GPG key**

### 8. Test It
```bash
git commit -m "test: gpg signing"
```

A macOS dialog will pop up asking for your **passphrase**.  
Enter it → Verified on GitHub.


---
## ⚠️WARNING: Your GPG passphrase is critical

You will need to enter this passphrase every time you sign a commit.
If you forget this passphrase, you cannot recover it.
Losing it means:
You won’t be able to use your GPG key anymore
You’ll need to generate a new key and reconfigure GitHub

---

## Verifying Your Commit Locally

After committing, run:
```bash
git log --show-signature -1
```

You should see:
```
gpg: Good signature from "Your Name <your@email.com>"
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `error: gpg failed to sign the data` | Run `export GPG_TTY=$(tty)` and add to shell profile |
| Pinentry dialog doesn't appear (macOS) | Run `gpgconf --kill gpg-agent` then retry |
| Commit shows **Unverified** on GitHub | Email in GPG key doesn't match GitHub verified email |
| Passphrase prompt doesn't appear (Linux SSH) | Add `pinentry-mode loopback` to `~/.gnupg/gpg-agent.conf` |
| Wrong key being used | Run `git config --global user.signingkey YOUR_KEY_ID` again |