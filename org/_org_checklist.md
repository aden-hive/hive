# Org-Wide Security & Quality Checklist

Use this checklist when onboarding a new repository to the org's security and quality standards.

## Per-Repository Setup

- [ ] **Enable GitHub Advanced Security** (if on GHEC/GHES with license)
  - Settings → Code security and analysis → GitHub Advanced Security → Enable
- [ ] **Enable CodeQL Code Scanning**
  - Option A (Default Setup): Settings → Code security → Code scanning → CodeQL analysis → Default setup → Enable
  - Option B (Advanced): Copy `.github/workflows/codeql.yml` from the org template repo or use the reusable workflow (see below)
- [ ] **Verify Copilot Autofix is active**
  - Settings → Code security → Code scanning → Copilot Autofix → Enable (enabled by default with GHAS)
- [ ] **Add `SECURITY.md`** — copy from this repo's template
- [ ] **Branch Protection Rules**
  - Settings → Branches → Add rule for `main`
  - ✅ Require status checks to pass: `code-scanning`, `lint`, `test`
  - ✅ Require branches to be up to date
  - ✅ Enforce for administrators
  - Or use the GH CLI snippet below

## Org-Level Extensions (Install Once per Developer)

- [ ] **Sentry for GitHub Copilot**
  - Install from VS Code / Codespaces Marketplace
  - Connect to org's Sentry project (DSN in `.env.example`)
  - In PRs: use `@sentry` in Copilot Chat for error context, fix suggestions, and test generation
- [ ] **Docker for GitHub Copilot**
  - Install Docker extension in VS Code / Codespaces
  - Use Copilot Chat prompts to optimize Dockerfiles (see README)

## Reusable Workflow

Place the reusable workflow in the org's `.github` repo:

```
kostasuser01gr/.github/
  .github/
    workflows/
      reusable-codeql.yml   ← copy from org/reusable-codeql.yml
```

Then, in each repo's CI:

```yaml
# .github/workflows/ci.yml (caller example)
name: org-ci
on: [pull_request]
jobs:
  security:
    uses: kostasuser01gr/.github/.github/workflows/reusable-codeql.yml@main
    secrets: inherit
  build-and-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install uv && cd core && uv sync && uv run pytest tests/ -v
```

> The reusable workflow is maintained centrally in `kostasuser01gr/.github` so updates automatically propagate to all repos that call it.

## GH CLI — Branch Protection (Quick Apply)

```bash
# Replace <REPO> with the target repo name
gh api \
  -X PUT \
  -H "Accept: application/vnd.github+json" \
  /repos/kostasuser01gr/<REPO>/branches/main/protection \
  --input - <<'EOF'
{
  "required_status_checks": {
    "strict": true,
    "contexts": ["code-scanning", "lint", "test"]
  },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
EOF
```
