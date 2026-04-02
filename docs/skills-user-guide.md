# Agent Skills User Guide

This guide covers how to use, create, and manage Agent Skills in the Hive framework. Agent Skills follow the open [Agent Skills standard](https://agentskills.io) — skills written for Claude Code, Cursor, or other compatible agents work in Hive unchanged.

## Phase 4 deliverables (split into subpages)

For the Phase 4 “Documentation Deliverables” (`#6371`), the authoritative content is being moved
into `docs/skills/*.md` as separate pages:

- [Install and use your first skill](./skills/install-first-skill.md)
- [Write your first skill](./skills/write-first-skill.md)
- [Port a skill](./skills/port-skill.md)
- [Default skills reference](./skills/default-skills-reference.md)
- [Tuning default skills](./skills/tuning-default-skills.md)
- [Starter pack guide](./skills/starter-pack-guide.md)

The remaining Phase 4 deliverables (skill cookbook and evaluating skill quality) are tracked
separately and will be added in a later pass.

## What are skills?

Skills are folders containing a `SKILL.md` file that teaches an agent how to perform a specific task. They can also bundle scripts, templates, and reference materials. Skills are loaded on demand — the agent sees a lightweight catalog at startup and pulls in full instructions only when relevant.

## Quick start

> TODO(#6370): Finalize registry default URL, starter-pack catalog, and copy-paste examples once the
> community registry index is live.

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

Or scaffold and validate with the CLI:

```bash
hive skill init --name my-skill
# edit my-skill/SKILL.md, then:
hive skill validate my-skill
```

User-scope installs from git go to `~/.hive/skills/`:

```bash
hive skill install --from https://github.com/org/skill-repo.git
```

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

### Registry install, search, and cache refresh

```bash
hive skill update              # refresh registry cache
hive skill search <query>
hive skill install <skill-name>
hive skill info <skill-name>
```

These require a fetchable `skill_index.json` (see `HIVE_REGISTRY_URL` in the environment table
below). Until the default community index is available ([#6370](https://github.com/aden-hive/hive/issues/6370)),
prefer `hive skill install --from <git-url>` or set `HIVE_REGISTRY_URL` to your own index.

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
| `hive.note-taking` | Structured working notes in shared memory |
| `hive.batch-ledger` | Track per-item status in batch operations |
| `hive.context-preservation` | Save context before context window pruning |
| `hive.quality-monitor` | Self-assess output quality periodically |
| `hive.error-recovery` | Structured error classification and recovery |
| `hive.task-decomposition` | Break complex tasks into subtasks |

### Default skills reference

| Skill | Typical trigger | Shared memory expectation | Main tuning knobs |
|-------|------------------|---------------------------|-------------------|
| `hive.note-taking` | Multi-step tasks with intermediate findings | Stores concise investigation notes | verbosity, section format, checkpoint cadence |
| `hive.batch-ledger` | Processing a list of items (files, tickets, rows) | Stores item status and retry metadata | batch size, retry policy, completion threshold |
| `hive.context-preservation` | Long sessions near context pressure | Stores compressed state snapshots | snapshot frequency, summary depth |
| `hive.quality-monitor` | Deliverables requiring quality bars | Stores self-check results and open risks | check interval, strictness, stop-on-fail |
| `hive.error-recovery` | Tool failures and runtime exceptions | Stores error type, mitigation, and retry decisions | max retries, fallback policy |
| `hive.task-decomposition` | Broad or ambiguous requests | Stores task breakdown and progress map | decomposition depth, merge policy |

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

## Tuning default skills

Use tuning when you want to keep the safety/value of operational skills while adapting behavior to workload.

Use disable only when:
- A skill causes measurable noise for a specific agent profile.
- A policy or environment constraint makes the behavior invalid.

Prefer configure over disable when:
- You only need less verbosity or lower frequency.
- You want guardrails, but in a narrower scope.

Suggested tuning sequence:
1. Keep all defaults enabled in baseline runs.
2. Measure latency, output quality, and retries over representative tasks.
3. Reduce the noisiest skill settings first (not all at once).
4. Re-run the same workload and compare deltas.
5. Disable only if measured regressions are not recoverable by tuning.

Audit the six built-in default skills:

```bash
hive skill doctor --defaults
```

## Skill cookbook

The cookbook is a set of annotated examples contributors can copy and adapt.

### Example 1: Research synthesis skill

- Goal: produce source-backed answers with explicit citation standards.
- Pattern: instruction-heavy `SKILL.md` + optional reference style guide.
- Validation focus: source quality checks and citation formatting.

### Example 2: Triage and classification skill

- Goal: classify incoming items into stable categories with rationale.
- Pattern: deterministic rubric section + confidence threshold policy.
- Validation focus: consistency across edge-case samples.

### Example 3: Outreach drafting skill

- Goal: draft concise personalized outreach with tone constraints.
- Pattern: template-driven body + red-flag checks before output.
- Validation focus: tone compliance and prohibited-content checks.

> TODO(#6370): Link cookbook examples to starter packs once pack definitions are finalized in the registry repo.

## Evaluating skill quality

A practical evaluation loop:
1. Define the skill goal and non-goals.
2. Build a small eval set of representative prompts.
3. Add pass/fail assertions (format, safety, correctness, policy).
4. Run evals after every material skill change.
5. Track regressions and iterate with focused fixes.

Quality dimensions to score:
- Activation precision: does the agent activate the skill when it should?
- Instruction adherence: does behavior follow the declared procedure?
- Robustness: does it handle edge cases and recover from tool errors?
- Output quality: is output accurate, clear, and policy-compliant?

Run checks from the CLI:

```bash
# Structural validation + doctor checks (no API key)
hive skill test path/to/my-skill

# Live invocation (requires ANTHROPIC_API_KEY); JSON input with a "prompt" key recommended
hive skill test path/to/my-skill --input '{"prompt": "..."}'

# Optional model override (default: claude-haiku-4-5-20251001)
hive skill test path/to/my-skill --input '{"prompt": "..."}' --model claude-haiku-4-5-20251001
```

If the skill has an `evals/` directory with `*.json` eval suites, the command runs cases and
LLM-judge assertions when an API key is available; otherwise it warns and skips eval execution.

## Port a skill from Claude Code or Cursor

Hive is compatible with Agent Skills format used by other clients.

Porting checklist:
1. Copy the skill directory to `.agents/skills/<skill-name>/` or `.hive/skills/<skill-name>/`.
2. Confirm frontmatter fields are valid and `name` matches directory name.
3. Verify relative references for `scripts/`, `references/`, and `assets/`.
4. Run `hive skill validate` on the skill path and fix reported errors.
5. Test activation against a prompt that should trigger the skill.

Optional: `hive skill doctor <skill-name> --project-dir /path/to/project` for script and parse checks.

## Starter packs

Starter packs bundle multiple complementary skills for common workflows.

Use packs when:
- You are onboarding quickly and want a tested baseline.
- Your team needs a consistent setup across projects.

Pack lifecycle:
1. Discover a pack by workflow.
2. Install pack contents.
3. Enable/disable individual skills for your agent profile.
4. Run a smoke test on one representative task.

> TODO(#6370): Add exact pack names, install commands, and pack metadata fields after registry pack format is finalized.

## Environment variables

| Variable | Description |
|----------|-------------|
| `HIVE_TRUST_PROJECT_SKILLS=1` | Bypass trust gating for all project-level skills (CI override) |
| `HIVE_OWN_REMOTES` | Comma-separated glob patterns for auto-trusted remotes (e.g., `github.com/myorg/*`) |
| `HIVE_REGISTRY_URL` | URL to `skill_index.json` for `hive skill search`, `install <name>`, and `update` |
| `ANTHROPIC_API_KEY` | Required for `hive skill test` live invocation and eval suites that use the LLM |

## Compatibility with other agents

Skills written for any Agent Skills-compatible agent work in Hive:

- Place them in `.agents/skills/` (cross-client) or `.hive/skills/` (Hive-specific).
- The `SKILL.md` format is identical across Claude Code, Cursor, Gemini CLI, and others.
- Skills installed at `~/.agents/skills/` are visible to all compatible agents on your machine.

See the [Agent Skills specification](https://agentskills.io/specification) for the full format reference.

## Documentation release checklist

Before marking documentation "ready for review" for Phase 4:
- Confirm `#6369` CLI behavior matches docs (re-run `hive skill --help` and command snippets).
- Confirm `#6370` registry structure, packs, and index behavior are stable.
- Re-run all command snippets and update output blocks.
- Replace every TODO anchor tied to `#6369` and `#6370`.
- Get at least one non-author review on the docs set.