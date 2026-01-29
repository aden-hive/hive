# Securely remove `.env` from history (guide)

IMPORTANT: Do NOT run a history rewrite until you HAVE REVOKED/ROTATED any secrets found in `.env`.

Steps (recommended):

1. Immediately revoke or rotate any tokens/credentials found in `.env` (GitHub PATs, keys, etc.).
2. Verify you have a clean working tree and pushed branches backed up (create a backup branch):

```
git checkout -b backup/origin-main
git push origin backup/origin-main
```

3. Install `git-filter-repo` (preferred) or use the BFG Repo-Cleaner.

git-filter-repo (recommended):

- Install: `pip install git-filter-repo` or follow https://github.com/newren/git-filter-repo

- Example (dry-run not supported, so be careful):

```
# Make a local clone to operate on
git clone --mirror https://github.com/<your-user>/hive.git hive-mirror.git
cd hive-mirror.git

# Remove any file named .env from all history
git filter-repo --invert-paths --paths ".env"

# Push the cleaned mirror back to GitHub (force)
git remote add cleaned https://github.com/<your-user>/hive.git
git push --force cleaned refs/heads/*:refs/heads/*
```

BFG alternative:

```
git clone --mirror https://github.com/<your-user>/hive.git
java -jar bfg.jar --delete-files .env hive.git
cd hive.git
git reflog expire --expire=now --all && git gc --prune=now --aggressive
git push --force
```

4. After force-pushing, coordinate with any collaborators to re-clone and rotate credentials again.

5. Verify on GitHub that no `.env` file appears in the commit history and that all secrets are revoked.

If you want, I can prepare the exact commands tailored to your fork and run them after you confirm secrets revoked and approve the destructive force-push.
