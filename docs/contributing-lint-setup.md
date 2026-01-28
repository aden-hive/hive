# Linting & Formatting Setup

Hive uses [Ruff](https://docs.astral.sh/ruff/) for all Python linting and formatting. This document explains the tooling, how to set it up locally, and what happens in CI.

---

## Quick Setup

```bash
# 1. Install dev dependencies
cd core && pip install -e ".[dev]"

# 2. Install pre-commit hooks (runs ruff automatically before each commit)
make install-hooks

# 3. Done. Every commit is now auto-linted and formatted.
```

---

## What Ruff Enforces

| Rule Set | Code | What It Catches |
|----------|------|-----------------|
| pyflakes | `F` | Unused imports, undefined names |
| pycodestyle | `E`, `W` | Style violations, whitespace issues |
| bugbear | `B` | Common Python gotchas (e.g., mutable default args, missing `from` on `raise`) |
| comprehensions | `C4` | Unnecessary `list()` / `dict()` calls that should be comprehensions |
| isort | `I` | Import ordering and grouping |
| quotes | `Q` | Consistent double-quote usage |
| pyupgrade | `UP` | Modernize syntax for Python 3.11+ |

**Line length:** 100 characters.

**Import order:** stdlib, third-party, first-party (`framework` / `aden_tools`), local.

---

## Makefile Commands

Run these from the repository root:

```bash
make lint           # Auto-fix lint issues across core/, tools/, exports/
make format         # Apply ruff formatting
make check          # Dry-run check (same as CI) — no files modified
make test           # Run the test suite
make install-hooks  # One-time: install pre-commit hooks
make help           # Show all available targets
```

`make check` is the exact set of checks that CI runs. If it passes locally, CI will pass.

---

## Pre-Commit Hooks

After running `make install-hooks`, every `git commit` will automatically:

1. **Lint** staged Python files with `ruff check --fix`
2. **Format** staged Python files with `ruff format`

If ruff modifies a file, the commit is aborted so you can review and re-stage. This is intentional — it prevents unlinted code from entering the repository.

To skip hooks in an emergency (not recommended):

```bash
git commit --no-verify -m "message"
```

---

## Editor Setup

### VS Code (Recommended)

The repository includes `.vscode/extensions.json` and `.vscode/settings.json`. On first open, VS Code will prompt you to install the recommended Ruff extension.

Once installed, the editor will:

- **Format on save** using ruff
- **Auto-fix lint issues** on save (import sorting, fixable violations)
- Show a **ruler at column 100**

No manual configuration needed.

### Other Editors

The `.editorconfig` file sets baseline formatting (UTF-8, LF line endings, 4-space indent for Python, trailing whitespace trimming). Most editors support EditorConfig natively or via plugin.

For any editor, you can always rely on `make lint` and `make format` from the command line.

---

## AI-Assisted Development

### Claude Code

The repository includes a `.claude/settings.json` hook that automatically runs `ruff check --fix` and `ruff format` after every file edit made by Claude Code. No setup needed — it works out of the box.

### Cursor

The `.cursorrules` file at the repo root tells Cursor's AI the project's style rules (line length, import order, quote style, etc.) so generated code follows convention.

---

## CI Pipeline

Every push and PR to `main` runs the `Lint Python` job in GitHub Actions (`.github/workflows/ci.yml`):

```
ruff check   → core/, tools/, exports/
ruff format  → core/, tools/, exports/ (--check mode, no modifications)
```

Both must pass. If CI fails:

```bash
make lint     # Fix lint issues
make format   # Fix formatting
make check    # Verify locally before pushing
```

---

## Configuration Files

| File | Scope |
|------|-------|
| `core/pyproject.toml` `[tool.ruff]` | Ruff rules for `core/` and `exports/` |
| `tools/pyproject.toml` `[tool.ruff]` | Ruff rules for `tools/` (mirrors core, first-party = `aden_tools`) |
| `.editorconfig` | Editor-agnostic formatting defaults |
| `.pre-commit-config.yaml` | Pre-commit hook definitions |
| `.vscode/settings.json` | VS Code ruff integration |
| `.vscode/extensions.json` | Recommended VS Code extensions |
| `.cursorrules` | AI assistant context |
| `.claude/settings.json` | Claude Code post-edit hooks |

The single source of truth for lint rules is the `[tool.ruff]` section in each package's `pyproject.toml`. All other configs (VS Code, pre-commit, Makefile, CI) reference these.

---

## FAQ

**Q: Do I need to install anything beyond `pip install -e ".[dev]"`?**
Only if you want pre-commit hooks: `make install-hooks`. Everything else (VS Code settings, editorconfig) works automatically.

**Q: Can I use a different formatter (black, autopep8)?**
No. The project standardizes on ruff for both linting and formatting. Using a different formatter will cause CI failures.

**Q: What if ruff and my editor disagree?**
The `.vscode/settings.json` is configured to use ruff as the formatter. If you use a different editor, run `make format` before committing, or rely on the pre-commit hook.

**Q: I'm getting lint errors in code I didn't write. Do I need to fix them?**
Only fix lint errors in files you modified. Don't send drive-by lint fix PRs for unrelated files without coordinating first.

**Q: How do I suppress a specific rule on one line?**
```python
x = eval("1+1")  # noqa: S307
```
Use sparingly and only with a comment explaining why.
