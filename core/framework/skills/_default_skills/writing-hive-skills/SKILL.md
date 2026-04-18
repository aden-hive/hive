---
name: hive.writing-hive-skills
description: Author a new Agent Skill for a Hive agent that conforms to the Agent Skills specification (SKILL.md with YAML frontmatter, optional scripts/references/assets directories). Use when the user asks to create, scaffold, add, or package a new skill for a Hive agent.
metadata:
  author: hive
  type: default-skill
  spec-source: https://agentskills.io/specification
---

## Operational Protocol: Writing Hive Skills

Hive agents discover skills by scanning several roots, in precedence order:

1. `<project>/.hive/skills/` — project, Hive-specific
2. `<project>/.agents/skills/` — project, cross-client
3. `~/.hive/skills/` — user, Hive-specific
4. `~/.agents/skills/` — user, cross-client
5. Framework defaults shipped in `core/framework/skills/_default_skills/`

Each skill is a directory containing a `SKILL.md`. At startup, only the frontmatter `name` + `description` of every skill is loaded; the body is loaded only when the agent activates the skill. Design for that.

### Choosing where to put a new skill

- **Colony-scoped (via `create_colony`)**: when the skill is the operational protocol a single colony needs — its API auth, DOM selectors, DB schema, task-queue conventions — do NOT place it under `~/.hive/skills/` or `<project>/.hive/skills/` yourself. Those roots are SHARED and every colony on the machine will see it. Instead, pass the skill content INLINE to the `create_colony` tool (`skill_name`, `skill_description`, `skill_body`, optional `skill_files`). The tool materializes the folder under `~/.hive/colonies/<colony_name>/.hive/skills/<skill-name>/` where it is discovered as **project scope** by only that colony's workers. See the subsection below.
- **Project-scoped**: put under `<project>/.hive/skills/` when the skill is tied to that codebase's APIs, conventions, or infra and multiple agents in the project should share it.
- **User-scoped**: put under `~/.hive/skills/` when the skill is reusable across projects for this machine/user and all agents should see it.
- **Framework default**: add under `core/framework/skills/_default_skills/` AND register in `framework/skills/defaults.py::SKILL_REGISTRY` only when the skill is a universal operational protocol shipped with Hive. Default skills use the `hive.<name>` naming convention and include `type: default-skill` in metadata.

### Colony-scoped skills via `create_colony`

A colony-scoped skill is one that belongs to exactly ONE colony — e.g. it encodes the HoneyComb staging API the `honeycomb_research` colony polls, or the LinkedIn outbound flow the `linkedin_outbound_campaign` colony runs. Writing such a skill at `~/.hive/skills/` or `<project>/.hive/skills/` leaks it to every other colony, which will then see it at selection time.

**Do not reach for `write_file` to create the folder.** The `create_colony` tool takes the skill content INLINE and places it for you:

```
create_colony(
    colony_name="honeycomb_research",
    task="Build a daily honeycomb market report…",
    skill_name="honeycomb-api-protocol",
    skill_description="How to query the HoneyComb staging API…",
    skill_body="## Operational Protocol\n\nAuth: …",
    skill_files=[{"path": "scripts/fetch_tickers.py", "content": "…"}],  # optional
)
```

The tool writes `~/.hive/colonies/honeycomb_research/.hive/skills/honeycomb-api-protocol/SKILL.md` (plus any `skill_files`), which `SkillDiscovery` picks up as project scope when that colony's workers start — and ONLY that colony's workers. No cross-colony leakage.

Do not write colony-bound skill folders by hand under `~/.hive/skills/`. A skill placed there is user-scoped and becomes visible to every colony on the machine — defeating the isolation you wanted.

### Directory layout

```
<skill-name>/
├── SKILL.md          # Required
├── scripts/          # Optional — executable helpers
├── references/       # Optional — on-demand docs
└── assets/           # Optional — templates, data, images
```

Rules:
- The directory name **must** equal the `name` frontmatter field (for framework defaults, the directory is the unprefixed name, e.g. `note-taking/` for `hive.note-taking`).
- Keep `SKILL.md` under ~500 lines. Move long reference material into `references/`.
- Reference other files with relative paths from the skill root (`scripts/foo.py`, `references/API.md`). Keep references one level deep.

### SKILL.md frontmatter

Required fields:

| Field | Constraints |
|-------|-------------|
| `name` | 1–64 chars, `[a-z0-9-]`, no leading/trailing/consecutive hyphens. Must match the directory name. Framework defaults prefix with `hive.` |
| `description` | 1–1024 chars. Must describe **what** the skill does **and when to use it**. Include trigger keywords the user is likely to say. |

Optional fields:

| Field | Notes |
|-------|-------|
| `license` | License name or reference to a bundled file |
| `compatibility` | ≤500 chars. Only include if env requirements are non-trivial (network, tools, runtime) |
| `metadata` | Free-form string→string map. Namespace keys to avoid collisions. Default skills set `type: default-skill`. |
| `allowed-tools` | Experimental. Space-separated pre-approved tools, e.g. `Bash(curl:*) Bash(jq:*) Read` |

Minimal template:

```markdown
---
name: my-skill
description: One sentence on what it does. One sentence on when to use it, with concrete trigger words the agent will see in user requests.
---

# My Skill

<body>
```

### Writing a good `description`

This is the single most important field — it's the only thing the agent sees at skill-selection time.

- **Bad**: `Helps with trading.`
- **Good**: `Buy and sell shares on the HoneyComb exchange. Handles auth, slippage-protected orders, idempotent retries, and AMM output estimation. Use when placing trades or interacting with the AMM.`

Include verbs the user is likely to say (`buy`, `sell`, `place trade`) and proper nouns (`HoneyComb`, `AMM`).

### Writing the body

Structure the body for the agent, not a human reader:

1. **Lead with what the agent can't guess** — API base URLs, auth shape, project conventions, specific function names. Skip generic background ("PDFs are a document format").
2. **Show exact request/response shapes** — include JSON payloads, headers, status codes. Copy real examples rather than paraphrasing.
3. **Document failure modes** — error codes, retry rules, rate limits. This is where skills earn their keep vs. a generic agent.
4. **Give a short end-to-end example** — a "typical flow" section at the bottom anchors everything above.

Recommended sections (adapt to the domain):
- Authentication / setup
- Core operations (one per endpoint or action)
- Error reference table
- Rate limits / gotchas
- End-to-end example pattern

### Progressive disclosure

Three tiers of context cost:

1. **Always loaded** (~100 tokens per skill): `name` + `description`. Keep tight.
2. **Loaded on activation** (<5k tokens target): body of `SKILL.md`.
3. **Loaded on demand**: files under `scripts/`, `references/`, `assets/`. The agent reads these only when the body points to them.

If a section is long and only needed sometimes (e.g., a full schema dump, rarely-used edge cases), move it to `references/SOMETHING.md` and link to it from the body: `See [the error catalog](references/ERRORS.md) for the full list.`

### Scripts

Put executable helpers in `scripts/`. They should:
- Be self-contained or document dependencies in a comment header.
- Print human-readable errors to stderr and exit non-zero on failure.
- Accept arguments via CLI flags, not env vars (easier for the agent to invoke).

Reference them from the body by relative path:

```markdown
Estimate buy output with `scripts/estimate_buy.py --v-hc 1000000 --v-shares 1000000 --hc 500`.
```

For Python scripts in a Hive project, prefer `uv run scripts/foo.py ...`.

### Creating a new skill — workflow

1. Pick a `<skill-name>` (lowercase-hyphenated).
2. Decide scope: **colony** (pass content INLINE to `create_colony` — STOP here, do not hand-author the folder), project (`<project>/.hive/skills/`), user (`~/.hive/skills/`), or framework default (`core/framework/skills/_default_skills/` + registry entry).
3. For the non-colony scopes: create the directory and write `SKILL.md` with frontmatter + body.
4. Add `scripts/`, `references/`, `assets/` only if needed.
5. Validate the frontmatter: name matches dir, description is specific, no forbidden characters.
6. Validate using the Hive CLI:
   ```bash
   uv run hive skill validate <path-to-skill-dir>
   uv run hive skill doctor
   ```
7. Confirm discovery with `uv run hive skill list`.
8. Test by invoking a Hive agent on a task the skill should match — confirm it activates and follows the instructions.

### Registering as a framework default

When adding a skill as a shipped default:

1. Place the directory under `core/framework/skills/_default_skills/<unprefixed-name>/`.
2. Set frontmatter `name: hive.<unprefixed-name>` and `metadata.type: default-skill`.
3. Add the mapping to `SKILL_REGISTRY` in `core/framework/skills/defaults.py`:
   ```python
   SKILL_REGISTRY: dict[str, str] = {
       ...
       "hive.<unprefixed-name>": "<unprefixed-name>",
   }
   ```
4. If the skill uses `{{placeholder}}` substitution, add defaults to `_SKILL_DEFAULTS` in the same file.
5. If the skill reads/writes shared buffer keys, list them in `DATA_BUFFER_KEYS`.

### What NOT to put in a skill

- Generic programming knowledge the agent already has.
- Conversation-specific state (use memory or plans instead).
- Secrets or credentials (skills are plaintext; reference env vars or credential stores).
- Deeply nested reference chains — keep everything one hop from `SKILL.md`.
