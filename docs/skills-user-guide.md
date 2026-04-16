# Agent Skills User Guide

This guide covers how to use, create, and manage Agent Skills in the Hive framework. Agent Skills follow the open [Agent Skills standard](https://agentskills.io) — skills written for Claude Code, Cursor, or other compatible agents work in Hive unchanged.

## What are skills?

Skills are folders containing a `SKILL.md` file that teaches an agent how to perform a specific task. They can also bundle scripts, templates, and reference materials. Skills are loaded on demand — the agent sees a lightweight catalog at startup and pulls in full instructions only when relevant.

## Quick start

### Install a skill

Drop a skill folder into one of the discovery directories:

```bash
# Project-level (shared with the repo)
mkdir -p .hive/skills/my-skill
cat > .hive/skills/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: Does X when the user asks about Y.
---

# My Skill

Step-by-step instructions for the agent...
EOF
```

The agent will discover it automatically on the next session.

### List discovered skills

```bash
hive skill list
```

Output groups skills by scope:

```
PROJECT SKILLS
────────────────────────────────────
  • my-skill
    Does X when the user asks about Y.
    /home/user/project/.hive/skills/my-skill/SKILL.md

USER SKILLS
────────────────────────────────────
  • deep-research
    Multi-step web research with source verification.
    /home/user/.hive/skills/deep-research/SKILL.md
```

## Where to put skills

Hive scans five directories at startup, in this precedence order:

| Scope | Path | Use case |
|-------|------|----------|
| Project (Hive) | `<project>/.hive/skills/` | Skills specific to this repo |
| Project (cross-client) | `<project>/.agents/skills/` | Skills shared across Claude Code, Cursor, etc. |
| User (Hive) | `~/.hive/skills/` | Personal skills available in all projects |
| User (cross-client) | `~/.agents/skills/` | Personal cross-client skills |
| Framework | *(built-in)* | Default operational skills shipped with Hive |

**Precedence**: If two skills share the same name, the higher-precedence location wins. A project-level `code-review` skill overrides a user-level one with the same name.

**Cross-client paths**: The `.agents/skills/` directories are a convention shared across compatible agents. A skill installed at `~/.agents/skills/pdf-processing/` is visible to Hive, Claude Code, Cursor, and other compatible tools simultaneously.

## Creating a skill

### Directory structure

```
my-skill/
├── SKILL.md              # Required — metadata + instructions
├── scripts/              # Optional — executable code
│   └── run.py
├── references/           # Optional — supplementary docs
│   └── api-reference.md
└── assets/               # Optional — templates, data files
    └── template.json
```

### SKILL.md format

Every skill needs a `SKILL.md` with YAML frontmatter and a markdown body:

```markdown
---
name: my-skill
description: Extract and summarize PDF documents. Use when the user mentions PDFs or document extraction.
---

# PDF Processing

## When to use
Use this skill when the user needs to extract text from PDFs or merge documents.

## Steps
1. Check if pdfplumber is available...
2. Extract text using...

## Edge cases
- Scanned PDFs need OCR first...
```

### Frontmatter fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | Yes | Lowercase letters, numbers, hyphens. Must match the parent directory name. Max 64 chars. |
| `description` | Yes | What the skill does and when to use it. Max 1024 chars. Include keywords that help the agent match tasks. |
| `license` | No | License name or reference to a bundled LICENSE file. |
| `compatibility` | No | Environment requirements (e.g., "Requires git, docker"). |
| `metadata` | No | Arbitrary key-value pairs (author, version, etc.). |
| `allowed-tools` | No | Space-delimited list of pre-approved tools. |

### allowed-tools

The `allowed-tools` field defines a list of tools that an agent is explicitly permitted to use during execution.
<!-- updated -->
### Example

```yaml

allowed-tools: bash read_file write_file
```
#### What counts as a tool?

Tools refer to executable capabilities available to the agent, including:
- Built-in Hive tools (e.g., `read_file`, `write_file`)
- System-level tools (e.g., `bash`, if enabled)
- External integrations exposed via MCP

#### What does "pre-approved" mean?

Tools listed under `allowed-tools` are explicitly permitted without additional approval during execution.

#### What happens to tools not listed?

Tools not included may be:
- Blocked, or
- Subject to additional validation depending on configuration

#### Security implications

This field acts as a permission control layer, restricting the agent to a defined set of tools and helping ensure safe execution.





### Writing good descriptions

The description is critical — it's what the agent uses to decide whether to activate a skill. Be specific:

```yaml
# Good — tells the agent what and when
description: Extract text and tables from PDF files, fill PDF forms, and merge multiple PDFs. Use when working with PDF documents or when the user mentions PDFs, forms, or document extraction.

# Bad — too vague for the agent to match
description: Helps with PDFs.
```

### Writing good instructions

The markdown body is loaded into the agent's context when the skill is activated. Tips:

- **Be procedural**: Step-by-step instructions work better than abstract descriptions.
- **Keep it focused**: Stay under 500 lines / 5000 tokens. Move detailed reference material to `references/`.
- **Use relative paths**: Reference bundled files with relative paths (`scripts/run.py`, `references/guide.md`).
- **Include examples**: Show sample inputs and expected outputs.
- **Cover edge cases**: Tell the agent what to do when things go wrong.

## How skills are activated

Skills use **progressive disclosure** — three tiers that keep context usage efficient:

### Tier 1: Catalog (always loaded)

At session start, the agent sees a compact catalog of all available skills (name + description only, ~50-100 tokens each). This is how it knows what skills exist.

### Tier 2: Instructions (on demand)

When the agent determines a skill is relevant to the current task, it reads the full `SKILL.md` body into context. This happens automatically — the agent matches the task against skill descriptions and activates the best fit.

### Tier 3: Resources (on demand)

When skill instructions reference supporting files (`scripts/extract.py`, `references/api-docs.md`), the agent reads those individually as needed.

### Pre-activated skills

Some agents are configured to load specific skills at session start (skipping the catalog phase). This is set in the agent's configuration:

```python
# In agent definition
skills = ["code-review", "deep-research"]
```

Pre-activated skills have their full instructions loaded from the start, without waiting for the agent to decide they're relevant.

## Trust and security

### Why trust gating exists

Project-level skills come from the repository being worked on. If you clone an untrusted repo that contains a `.hive/skills/` directory, those skills could inject instructions into the agent's system prompt. Trust gating prevents this.

**User-level and framework skills are always trusted.** Only project-scope skills go through trust gating.

### What happens with untrusted project skills

When Hive encounters project-level skills from a repo you haven't trusted before, it shows a consent prompt:

```
============================================================
  SKILL TRUST REQUIRED
============================================================

  The project at /home/user/new-project wants to load 2 skill(s)
  that will inject instructions into the agent's system prompt.
  Source: github.com/org/new-project

  Skills requesting access:
    • deploy-pipeline
      "Automated deployment workflow for this project."
      /home/user/new-project/.hive/skills/deploy-pipeline/SKILL.md
    • code-standards
      "Project-specific coding standards and review checklist."
      /home/user/new-project/.hive/skills/code-standards/SKILL.md

  Options:
    1) Trust this session only
    2) Trust permanently  — remember for future runs
    3) Deny              — skip all project-scope skills from this repo
────────────────────────────────────────────────────────────
Select option (1-3):
```

### Trust a repo via CLI

To trust a repo permanently without the interactive prompt:

```bash
hive skill trust /path/to/project
```

This stores the trust decision in `~/.hive/trusted_repos.json`, keyed by the normalized git remote URL (e.g., `github.com/org/repo`).

### Automatic trust

Some repos are trusted automatically:

- **No git repo**: Directories without `.git/` are always trusted.
- **No remote**: Local-only git repos (no `origin` remote) are always trusted.
- **Localhost remotes**: Repos with `localhost`/`127.0.0.1` remotes are always trusted.
- **Own-remote patterns**: Repos matching patterns in `~/.hive/own_remotes` or the `HIVE_OWN_REMOTES` env var are always trusted.

### Configure own-remote patterns

If you trust all repos from your organization:

```bash
# Via file (one pattern per line)
echo "github.com/my-org/*" >> ~/.hive/own_remotes
echo "gitlab.com/my-team/*" >> ~/.hive/own_remotes

# Via environment variable (comma-separated)
export HIVE_OWN_REMOTES="github.com/my-org/*,github.com/my-corp/*"
```

### CI / headless environments

In non-interactive environments, untrusted project skills are silently skipped. To trust them explicitly:

```bash
export HIVE_TRUST_PROJECT_SKILLS=1
hive run my-agent
```

## Default skills

Hive ships with six built-in operational skills that provide runtime resilience. These are always loaded (unless disabled) and appear as "Operational Protocols" in the agent's system prompt.

| Skill | Purpose |
|-------|---------|
| `hive.note-taking` | Structured working notes in the shared buffer |
| `hive.batch-ledger` | Track per-item status in batch operations |
| `hive.context-preservation` | Save context before context window pruning |
| `hive.quality-monitor` | Self-assess output quality periodically |
| `hive.error-recovery` | Structured error classification and recovery |
| `hive.task-decomposition` | Break complex tasks into subtasks |

### Disable default skills

In your agent configuration:

```python
# Disable a specific default skill
default_skills = {
    "hive.quality-monitor": {"enabled": False},
}

# Disable all default skills
default_skills = {
    "_all": {"enabled": False},
}
```

## Environment variables

| Variable | Description |
|----------|-------------|
| `HIVE_TRUST_PROJECT_SKILLS=1` | Bypass trust gating for all project-level skills (CI override) |
| `HIVE_OWN_REMOTES` | Comma-separated glob patterns for auto-trusted remotes (e.g., `github.com/myorg/*`) |

## Compatibility with other agents

Skills written for any Agent Skills-compatible agent work in Hive:

- Place them in `.agents/skills/` (cross-client) or `.hive/skills/` (Hive-specific).
- The `SKILL.md` format is identical across Claude Code, Cursor, Gemini CLI, and others.
- Skills installed at `~/.agents/skills/` are visible to all compatible agents on your machine.

See the [Agent Skills specification](https://agentskills.io/specification) for the full format reference.
