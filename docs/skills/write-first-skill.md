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

## 4) Validate locally (and then via CLI)

Planned contributor workflow once Phase 2 CLI UX is frozen:

1. Scaffold a skill directory
2. Fill in `SKILL.md`
3. Validate
4. Submit the registry PR

> TODO(#6369): Replace this section with the exact `hive skill init` and `hive skill validate` commands,
> including expected output and error messages.

## 5) Make sure it behaves well in edge cases

In your instruction body:

- Provide step-by-step procedure (avoid vague prompts)
- Include edge cases and recovery behavior
- Use relative paths to bundled files (`scripts/...`, `references/...`)

