# Write Your First Skill (Phase 4)

This page explains how to author a new `SKILL.md` skill package and validate it for use by Hive.

## 1) Create the directory

Create a folder whose name is the skill name, then add a `SKILL.md` file inside:

```text
my-skill/
├── SKILL.md              # Required — metadata + instructions
├── scripts/              # Optional — executable code
│   └── run.py
├── references/           # Optional — supplementary docs
│   └── api-reference.md
└── assets/               # Optional — templates, data files
    └── template.json
```

## 2) Write `SKILL.md`

Every skill needs:

- YAML frontmatter (metadata)
- a Markdown body (agent instructions)

Example:

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
```

### Frontmatter fields

At minimum, include:

- `name` (required): lowercase letters, numbers, hyphens; must match the parent directory name
- `description` (required): what the skill does and when to use it

Optional fields:

- `license`
- `compatibility`
- `metadata`
- `allowed-tools`

## 3) Add good matching text

The `description` is what the agent uses to decide whether to activate a skill. Make it specific.

## 4) Scaffold with `hive skill init`

Creates a new directory and writes a `SKILL.md` template.

```bash
hive skill init --name my-skill
hive skill init --name my-skill --dir /path/to/parent
```

If you omit `--name` in an interactive terminal, the CLI prompts for a name. Non-interactive use
requires `--name`.

Next steps printed by the command: edit `SKILL.md`, run `hive skill validate`, then copy or move the
skill under `~/.hive/skills/` (or a project `.hive/skills/`) so agents discover it.

## 5) Validate with `hive skill validate`

Strict validation against the Agent Skills spec. Pass either the path to `SKILL.md` or the skill
directory (the CLI resolves `SKILL.md` inside the directory).

```bash
hive skill validate path/to/my-skill/SKILL.md
hive skill validate path/to/my-skill
```

- Exit code `0` when valid (warnings allowed).
- Exit code `1` when invalid. Human output uses `[WARN]` and `[ERROR]` lines; use `--json` for
  machine-readable `passed`, `errors`, and `warnings`.

## 6) Optional: fork and test

```bash
hive skill fork <installed-skill-name> [--name my-skill-fork] [--dir ~/.hive/skills] [--yes]
hive skill test path/to/skill-or-SKILL.md
hive skill test path/to/skill --input '{"prompt": "..."}'   # needs ANTHROPIC_API_KEY
hive skill test path/to/skill --model claude-haiku-4-5-20251001
```

Without `--input` and without an `evals/` suite, `hive skill test` runs structural validation plus
doctor-style checks (no API key). With `evals/*.json` cases, an API key is required for LLM
invocation and judge assertions.

## 7) Submit to the community registry

> TODO(#6370): Document the exact PR flow against `hive-skill-registry` once the registry repo and
> contribution guide are finalized.

## 8) Make sure it behaves well in edge cases

In your instruction body:

- Provide step-by-step procedure (avoid vague prompts)
- Include edge cases and recovery behavior
- Use relative paths to bundled files (`scripts/...`, `references/...`)

