# Skill Registry — Product & Business Requirements Document

**Status**: Draft v1
**Last updated**: 2026-03-13
**Authors**: Timothy
**Reviewers**: Platform, Product, OSS/Community, Developer Experience

---

## 1. Executive Summary

This document proposes a **Skill System** for Hive — a portable implementation of the open [Agent Skills](https://agentskills.io) standard — combined with a community registry and a set of built-in default skills that give every worker agent runtime resiliency out of the box.

### 1.1 The Agent Skills Standard

Agent Skills is an open format, originally developed by Anthropic, for giving agents new capabilities and expertise. It has been adopted by 30+ products including Claude Code, Cursor, VS Code, GitHub Copilot, Gemini CLI, OpenHands, Goose, Roo Code, OpenAI Codex, and more.

A skill is a directory containing a `SKILL.md` file — YAML frontmatter (name, description) plus markdown instructions — optionally accompanied by scripts, reference docs, and assets. Agents discover skills at startup, load only the name and description into context (progressive disclosure tier 1), and activate the full instructions on demand when the task matches (tier 2). Supporting files are loaded only when the instructions reference them (tier 3).

```
my-skill/
├── SKILL.md          # Required: metadata + instructions
├── scripts/          # Optional: executable code
├── references/       # Optional: documentation
├── assets/           # Optional: templates, resources
└── evals/            # Optional: test cases and assertions
```

### 1.2 What Hive Adds

Hive implements the Agent Skills standard faithfully — no forks, no proprietary extensions to the `SKILL.md` format. A skill written for Claude Code, Cursor, or any other compatible product works in Hive with zero changes, and vice versa.

On top of the standard, Hive adds two things:

1. **Default skills** — Six built-in skills shipped with the Hive framework that every worker agent loads automatically. These encode runtime operational discipline: structured note-taking, batch progress tracking, context preservation, quality self-assessment, error recovery protocols, and task decomposition. They are the "muscle memory" that makes agents reliable by default.

2. **Community registry** (`hive-skill-registry`) — A curated GitHub repository where contributors submit skill packages via pull request. Skills in the registry are standard Agent Skills packages. Includes CI validation, trust tiers, starter packs, and bounty program integration.

### 1.3 Abstraction Hierarchy

| Layer             | What it is                                              | Example                                           |
| ----------------- | ------------------------------------------------------- | ------------------------------------------------- |
| **Tool**          | A single function call via MCP                          | `web_search`, `gmail_send`, `jira_create_issue`   |
| **Skill**         | A `SKILL.md` with instructions, scripts, and references | "Deep Research", "Code Review", "Data Analysis"   |
| **Default Skill** | A built-in skill for runtime resiliency                 | "Structured Note-Taking", "Batch Progress Ledger" |
| **Agent**         | A complete goal-driven worker composed of skills        | "Sales Outreach Agent", "Support Triage Agent"    |

---

## 2. Problem Statement

### 2.1 Current State

- Worker agents have no skill system. There is no mechanism to discover, load, or follow reusable procedural instructions on demand.
- The 12 example templates in `examples/templates/` are copy-paste only — they cannot be composed, imported, versioned, or discovered at runtime.
- Agent builders must either hand-write all prompts and tool orchestration from scratch, or copy patterns from other agents manually.
- Skills written for Claude Code, Cursor, and other Agent Skills-compatible products do not work in Hive. Users who adopt Hive lose access to the growing ecosystem of community skills.
- Worker agents have no standardized operational discipline. The framework provides mechanical safeguards (stall detection, doom-loop fingerprinting, checkpoint/resume), but there is no cognitive protocol for how an agent should take structured notes when processing a 50-item batch, when to proactively save data before context pruning, or how to self-assess quality degradation. Each agent author either reinvents these patterns in their system prompts or — more commonly — skips them entirely.
- When a community member builds a battle-tested skill (research pattern, triage workflow, outreach playbook), there is no pathway to share it, no discovery mechanism, no versioning, and no quality signals.

### 2.2 Who Is Affected

| Persona                      | Pain Point                                                                                                                                             |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **OSS contributor**          | Built a great skill for another Agent Skills-compatible product; wants it to work in Hive too, or wants to share a Hive skill with the wider ecosystem |
| **Agent builder (beginner)** | Overwhelmed by framework concepts; wants to install a "deep research" skill and use it without understanding graph internals                           |
| **Agent builder (advanced)** | Copies the same prompt patterns and tool orchestration across agents; wants reusable, version-pinned building blocks                                   |
| **Platform team**            | Cannot codify best practices as reusable runtime primitives; every quality improvement is a docs change, not a skill update                            |
| **Enterprise user**          | Wants an internal skill library so teams share proven patterns; needs cross-product compatibility                                                      |

### 2.3 Impact of Not Solving

- Hive is incompatible with the Agent Skills ecosystem — a growing open standard adopted by 30+ products. Users choosing Hive lose access to community skills; contributors targeting the ecosystem skip Hive.
- Agent quality depends entirely on individual author skill. No mechanism to propagate proven patterns.
- Worker agents are unreliable during long-running or batch processing sessions — no built-in operational discipline.
- The self-improvement loop's output (better prompts, better patterns) stays locked in individual deployments with no pathway to contribute back.

---

## 3. Goals & Success Criteria

### 3.1 Primary Goals

| #   | Goal                                                                                             | Metric                                                                         |
| --- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------ |
| G1  | Any `SKILL.md` from the Agent Skills ecosystem works in Hive with zero modifications             | Compatibility test suite against `github.com/anthropics/skills` example skills |
| G2  | A Hive skill works in Claude Code, Cursor, and other compatible products with zero modifications | Cross-product verification on 5+ skills                                        |
| G3  | A user can install and use a community skill in under 2 minutes                                  | Time from `hive skill install X` to skill activating in a session              |
| G4  | A contributor can publish a skill in under 10 minutes                                            | Time from `hive skill init` to PR submission                                   |
| G5  | Default skills measurably improve agent reliability on batch processing tasks                    | A/B comparison: agents with default skills vs. without on 10+ batch scenarios  |
| G6  | Zero breaking changes to existing agent configurations                                           | All current agents continue to work unchanged                                  |

### 3.2 Community & Ecosystem Goals

| #   | Goal                                                                                         | Metric                                                          |
| --- | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| G7  | Registry has 100+ community skills within 30 days of launch                                  | Skill count in registry                                         |
| G8  | All registry skills are portable Agent Skills packages — usable in any compatible product    | 100% of registry entries conform to the standard                |
| G9  | Bounty program integrates with skill contributions                                           | Skill submissions tracked in bounty-tracker                     |
| G10 | Contributors receive attribution when their skills are used                                  | Skill metadata includes author; agent logs credit loaded skills |
| G11 | Existing skills from `github.com/anthropics/skills` are installable via `hive skill install` | All example skills pass validation and activate correctly       |

### 3.3 Non-Goals (Explicit Exclusions)

- **Forking or extending the Agent Skills standard** — Hive implements the spec faithfully. No proprietary sidecar files, no Hive-specific schema extensions.
- **Runtime skill marketplace** — no billing, licensing, or monetization. The registry is free and open-source.
- **Hosting skill execution** — the registry stores packages; execution happens locally.
- **AI-generated skills** — automatic skill generation from natural language is a future phase.
- **Graph-level skill composition** — skills are instruction-following units, not graph fragments. Agents compose skills by activating multiple skills and following their combined instructions.

---

## 4. Agent Skills Standard — Implementation Spec

This section defines how Hive implements the open Agent Skills standard. The specification at [agentskills.io/specification](https://agentskills.io/specification) is authoritative; this section describes Hive's conforming implementation.

### 4.1 Skill Discovery

At session startup, Hive scans for skill directories containing a `SKILL.md` file. Both cross-client and Hive-specific locations are scanned:

| Scope     | Path                              | Purpose                                             |
| --------- | --------------------------------- | --------------------------------------------------- |
| Project   | `<project>/.agents/skills/`       | Cross-client interoperability (standard convention) |
| Project   | `<project>/.hive/skills/`         | Hive-specific project skills                        |
| User      | `~/.agents/skills/`               | Cross-client user-level skills                      |
| User      | `~/.hive/skills/`                 | Hive-specific user-level skills                     |
| Framework | `<hive-install>/skills/defaults/` | Built-in default skills                             |

**Precedence** (deterministic): Project-level skills override user-level skills. Within the same scope, `.hive/skills/` overrides `.agents/skills/`. Framework-level default skills have lowest precedence and can be overridden at any scope.

**Scanning rules:**

- Skip `.git/`, `node_modules/`, `__pycache__/`, `.venv/` directories
- Max depth: 4 levels from the skills root
- Max directories: 2000 per scope
- Respect `.gitignore` in project scope

**Trust:** Project-level skills from untrusted repositories (not marked trusted by the user) require explicit user consent before loading.

### 4.2 `SKILL.md` Parsing

Each discovered `SKILL.md` is parsed per the standard:

1. Extract YAML frontmatter between `---` delimiters
2. Parse required fields: `name`, `description`
3. Parse optional fields: `license`, `compatibility`, `metadata`, `allowed-tools`
4. Everything after the closing `---` is the skill's markdown body (instructions)

**Validation (lenient):**

- Name doesn't match parent directory → warn, load anyway
- Name exceeds 64 characters → warn, load anyway
- Description missing or empty → skip the skill, log error
- YAML unparseable → try wrapping unquoted colon values in quotes as fallback; if still fails, skip and log

**In-memory record per skill:**

| Field          | Source                            |
| -------------- | --------------------------------- |
| `name`         | Frontmatter                       |
| `description`  | Frontmatter                       |
| `location`     | Absolute path to `SKILL.md`       |
| `base_dir`     | Parent directory of `SKILL.md`    |
| `source_scope` | `project`, `user`, or `framework` |

### 4.3 Progressive Disclosure

Hive implements the standard three-tier loading model:

| Tier                | What's loaded                | When                             | Token cost               |
| ------------------- | ---------------------------- | -------------------------------- | ------------------------ |
| **1. Catalog**      | Name + description per skill | Session start                    | ~50-100 tokens per skill |
| **2. Instructions** | Full `SKILL.md` body         | When skill is activated          | <5000 tokens recommended |
| **3. Resources**    | Scripts, references, assets  | When instructions reference them | Varies                   |

**Catalog disclosure**: At session start, all discovered skill names and descriptions are injected into the system prompt:

```xml
<available_skills>
  <skill>
    <name>deep-research</name>
    <description>Multi-step web research with source verification. Use when the task requires gathering and synthesizing information from multiple sources.</description>
    <location>/home/user/.hive/skills/deep-research/SKILL.md</location>
  </skill>
  ...
</available_skills>
```

**Behavioral instruction** injected alongside the catalog:

```
The following skills provide specialized instructions for specific tasks.
When a task matches a skill's description, read the SKILL.md at the listed
location to load the full instructions before proceeding.
When a skill references relative paths, resolve them against the skill's
directory (the parent of SKILL.md) and use absolute paths in tool calls.
```

### 4.4 Skill Activation

Skills are activated via two mechanisms:

**Model-driven**: The agent reads the skill catalog, decides a skill is relevant, and reads the `SKILL.md` file using its file-read tool. No special infrastructure needed — the agent's standard file-reading capability is sufficient.

**User-driven**: Users can activate skills explicitly via `@skill-name` mention syntax or via agent configuration that pre-activates specific skills for every session.

**What happens on activation:**

1. The full `SKILL.md` body is loaded into context
2. Bundled resources (scripts, references) are listed but NOT eagerly loaded
3. The skill directory is allowlisted for file access (no permission prompts for bundled files)
4. Activation is logged: `{skill_name, scope, timestamp}`

**Deduplication**: If a skill is already active in the current session, re-activation is skipped.

**Context protection**: Activated skill content is exempt from context pruning/compaction — skill instructions are durable behavioral guidance that must persist for the session duration.

### 4.5 Skill Execution

The agent follows the instructions in `SKILL.md`. It can:

- Execute bundled scripts from `scripts/`
- Read reference materials from `references/`
- Use assets from `assets/`
- Call any MCP tools available in the agent's tool registry

This is identical to how skills work in Claude Code, Cursor, or any other Agent Skills-compatible product.

### 4.6 Pre-Activated Skills

Agents can declare skills that should be activated at session start — bypassing model-driven activation. This is useful for skills that an agent always needs (e.g., a coding standards skill for a code review agent).

**In agent config (`agent.json`):**

```json
{
  "skills": ["deep-research", "code-review"]
}
```

**In Python:**

```python
agent = Agent(
    name="my-agent",
    skills=["deep-research", "code-review"],
)
```

Pre-activated skills have their full `SKILL.md` body loaded into context at session start (tier 2), skipping the catalog-only tier 1 phase.

---

## 5. Default Skills

Default skills are **built-in skills shipped with the Hive framework** that every worker agent loads automatically. They use the Agent Skills format (`SKILL.md`) but live in the framework's install directory and serve as runtime operational protocols.

### 5.1 Why Default Skills

The framework provides mechanical safeguards: stall detection via n-gram similarity, doom-loop fingerprinting, checkpoint/resume, token budget pruning, and max iteration limits. But these are reactive — they trigger after something has gone wrong.

Default skills encode **proactive cognitive protocols**: how to take structured notes so you don't lose track of a 50-item batch, when to pause and summarize before you hit context limits, how to self-assess whether your output quality is degrading. They are the operational habits that experienced agent builders already encode in their system prompts — standardized so every agent benefits.

### 5.2 Integration Model

Default skills differ from community skills in how they integrate:

| Aspect       | Default Skills                                 | Community Skills                                      |
| ------------ | ---------------------------------------------- | ----------------------------------------------------- |
| Loaded by    | Framework automatically                        | Agent decides at runtime (or pre-activated in config) |
| Integration  | System prompt injection + shared memory hooks  | Instruction-following (standard Agent Skills)         |
| Graph impact | No dedicated nodes — woven into existing nodes | None (just context)                                   |
| Overridable  | Yes (disable, configure, or replace)           | N/A                                                   |

Default skills integrate at four injection points in the `EventLoopNode`:

1. **System prompt injection** (before first LLM call): Default skill protocols are appended to the node's system prompt
2. **Iteration boundary callbacks** (between iterations): Quality check, notes staleness warning, budget tracking
3. **Node completion hooks** (when node finishes): Batch completeness check, handoff summary
4. **Phase transition hooks** (on edge traversal): Context carry-over, notes persistence

### 5.3 Default Skill Catalog

Six default skills ship with Hive:

#### 5.3.1 Structured Note-Taking (`hive.note-taking`)

**Purpose:** Maintain a structured working document throughout execution so the agent never loses track of what it knows, what it's decided, and what's pending.

**Problem:** Without structured notes, agents processing long sessions rely entirely on conversation history. When context is pruned (automatically at 60% token usage), intermediate reasoning is lost. Agents repeat work, contradict earlier decisions, or silently drop items.

**Protocol (injected into system prompt):**

```markdown
## Operational Protocol: Structured Note-Taking

Maintain structured working notes in shared memory key `_working_notes`.
Update at these checkpoints:

- After completing each discrete subtask or batch item
- After receiving new information that changes your plan
- Before any tool call that will produce substantial output

Structure:

### Objective — restate the goal

### Current Plan — numbered steps, mark completed with ✓

### Key Decisions — decisions made and WHY

### Working Data — intermediate results, extracted values

### Open Questions — uncertainties to verify

### Blockers — anything preventing progress

Update incrementally — do not rewrite from scratch each time.
```

**Shared memory:** `_working_notes` (string), `_notes_updated_at` (timestamp)

**Config:** `enabled` (default true), `update_frequency` (default `per_subtask`), `max_notes_length` (default 4000 chars)

---

#### 5.3.2 Batch Progress Ledger (`hive.batch-ledger`)

**Purpose:** When processing a collection of items, maintain a structured ledger tracking each item's status so no item is skipped, duplicated, or silently dropped.

**Problem:** Agents processing batches lose track of which items they've handled, especially after context compaction or checkpoint resume. Without a ledger, agents re-process items (waste) or skip items (data loss).

**Protocol (injected into system prompt):**

```markdown
## Operational Protocol: Batch Progress Ledger

When processing a collection of items, maintain a batch ledger in `_batch_ledger`.

Initialize when you identify the batch:

- `_batch_total`: total item count
- `_batch_ledger`: JSON with per-item status

Per-item statuses: pending → in_progress → completed|failed|skipped

- Set `in_progress` BEFORE processing
- Set final status AFTER processing with 1-line result_summary
- Include error reason for failed/skipped items
- Update aggregate counts after each item
- NEVER remove items from the ledger
- If resuming, skip items already marked completed
```

**Shared memory:** `_batch_ledger` (dict), `_batch_total` (int), `_batch_completed` (int), `_batch_failed` (int)

**Config:** `enabled` (default true), `auto_detect_batch` (default true), `checkpoint_every_n` (default 5)

**Completion check:** At node completion, if `_batch_completed + _batch_failed + _batch_skipped < _batch_total`, emit warning.

---

#### 5.3.3 Context Preservation (`hive.context-preservation`)

**Purpose:** Proactively preserve critical information before automatic context pruning destroys it.

**Problem:** The framework's `prune_old_tool_results()` at 60% token usage removes content indiscriminately. Agents that don't proactively save important data into working notes lose it permanently.

**Protocol (injected into system prompt):**

```markdown
## Operational Protocol: Context Preservation

You operate under a finite context window. Important information WILL be pruned.

Save-As-You-Go: After any tool call producing information you'll need later,
immediately extract key data into `_working_notes` or `_preserved_data`.
Do NOT rely on referring back to old tool results.

What to extract: URLs and key snippets (not full pages), relevant API fields
(not raw JSON), specific lines/values (not entire files), analysis results
(not raw data).

Before transitioning to the next phase/node, write a handoff summary to
`_handoff_context` with everything the next phase needs to know.
```

**Shared memory:** `_handoff_context` (string), `_preserved_data` (dict)

**Config:** `enabled` (default true), `warn_at_usage_ratio` (default 0.45), `require_handoff` (default true)

---

#### 5.3.4 Quality Self-Assessment (`hive.quality-monitor`)

**Purpose:** Periodically prompt the agent to self-evaluate output quality, catching degradation before the judge does.

**Problem:** The judge system evaluates at node completion — once per node, not during execution. An agent can degrade gradually over many iterations without detection until the node completes.

**Protocol (injected into system prompt):**

```markdown
## Operational Protocol: Quality Self-Assessment

Every 5 iterations, self-assess:

1. On-task? Still working toward the stated objective?
2. Thorough? Cutting corners compared to earlier?
3. Non-repetitive? Producing new value or rehashing?
4. Consistent? Latest output contradict earlier decisions?
5. Complete? Tracking all items, or silently dropped some?

If degrading: write assessment to `_quality_log`, re-read `_working_notes`,
change approach explicitly. If acceptable: brief note in `_quality_log`.
```

**Shared memory:** `_quality_log` (list), `_quality_degradation_count` (int)

**Config:** `enabled` (default true), `assessment_interval` (default 5), `degradation_threshold` (default 3)

---

#### 5.3.5 Error Recovery Protocol (`hive.error-recovery`)

**Purpose:** When a tool call fails or returns unexpected results, follow a structured recovery protocol instead of blindly retrying or giving up.

**Problem:** The framework retries transient errors automatically. But non-transient failures (wrong input, business logic error, missing resource) are handed back to the agent with no guidance. Agents often retry the same call or abandon the task.

**Protocol (injected into system prompt):**

```markdown
## Operational Protocol: Error Recovery

When a tool call fails:

1. Diagnose — record error in notes, classify as transient or structural
2. Decide — transient: retry once. Structural fixable: fix and retry.
   Structural unfixable: record as failed, move to next item.
   Blocking all progress: record escalation note.
3. Adapt — if same tool failed 3+ times, stop using it and find alternative.
   Update plan in notes. Never silently drop the failed item.
```

**Shared memory:** `_error_log` (list), `_failed_tools` (dict), `_escalation_needed` (bool)

**Config:** `enabled` (default true), `max_retries_per_tool` (default 3), `escalation_on_block` (default true)

---

#### 5.3.6 Task Decomposition (`hive.task-decomposition`)

**Purpose:** Decompose complex tasks into explicit subtasks before diving in. Maintain the decomposition as a living checklist.

**Problem:** Agents facing complex tasks start executing immediately without planning, leading to incomplete coverage and iteration budget exhaustion on the first sub-problem.

**Protocol (injected into system prompt):**

```markdown
## Operational Protocol: Task Decomposition

Before starting a complex task:

1. Decompose — break into numbered subtasks in `_working_notes` Current Plan
2. Estimate — relative effort per subtask (small/medium/large)
3. Execute — work through in order, mark ✓ when complete
4. Budget — if running low on iterations, prioritize by impact
5. Verify — before declaring done, every subtask must be ✓, skipped (with reason), or blocked
```

**Shared memory:** `_subtasks` (list), `_iteration_budget_remaining` (int)

**Config:** `enabled` (default true), `decomposition_threshold` (default `auto`), `budget_awareness` (default true)

---

### 5.4 Default Skill Configuration

Agents configure default skills via `default_skills` in their agent definition:

**Declarative (`agent.json`):**

```json
{
  "default_skills": {
    "hive.note-taking": { "enabled": true },
    "hive.batch-ledger": { "enabled": true, "checkpoint_every_n": 10 },
    "hive.context-preservation": {
      "enabled": true,
      "warn_at_usage_ratio": 0.4
    },
    "hive.quality-monitor": { "enabled": false },
    "hive.error-recovery": { "enabled": true },
    "hive.task-decomposition": { "enabled": true }
  }
}
```

**Disable all:** `"default_skills": {"_all": {"enabled": false}}`

### 5.5 Prompt Budget

All default skill protocols combined must total under **2000 tokens** to minimize impact on the agent's domain reasoning budget. Protocols are terse operational checklists, not verbose documentation.

### 5.6 Shared Memory Convention

All default skill shared memory keys use the `_` prefix (`_working_notes`, `_batch_ledger`, etc.) to avoid collisions with domain-level keys. These keys are:

- Visible to the agent (for self-reference)
- Visible to the judge (for evaluation context)
- Excluded from the agent's declared output contract (operational, not domain output)

---

## 6. Community Registry

### 6.1 Registry Repository

A public GitHub repository (`hive-skill-registry`) serves as the curated community index. Every entry is a standard Agent Skills package — portable to any compatible product.

```
hive-skill-registry/
├── registry/
│   ├── skills/
│   │   ├── deep-research/
│   │   │   ├── SKILL.md
│   │   │   ├── scripts/
│   │   │   ├── references/
│   │   │   ├── evals/
│   │   │   └── README.md
│   │   ├── email-triage/
│   │   └── ...
│   ├── packs/
│   │   ├── research-pack.json
│   │   └── ...
│   └── _template/
├── skill_index.json               (auto-generated)
├── CONTRIBUTING.md
└── README.md
```

### 6.2 Trust Tiers

| Tier        | Meaning                        | Requirements                                  |
| ----------- | ------------------------------ | --------------------------------------------- |
| `official`  | Maintained by Hive team        | Internal review                               |
| `verified`  | Audited community contribution | Code audit, maintainer SLA, test coverage     |
| `community` | Community-submitted            | Passes CI validation, maintainer review on PR |

### 6.3 Registry Index

The registry auto-generates a `skill_index.json` on merge for client consumption:

```json
{
  "name": "deep-research",
  "description": "Multi-step web research with source verification...",
  "status": "verified",
  "author": { "name": "Alex Researcher", "github": "alexr" },
  "maintainer": { "github": "alexr" },
  "version": "1.2.0",
  "license": "MIT",
  "tags": ["research", "web", "synthesis"],
  "categories": ["knowledge-work"],
  "install_count": 342,
  "last_validated_at": "2026-03-13T10:00:00Z",
  "deprecated": false
}
```

### 6.4 Starter Packs

Themed collections of skills that work well together:

```json
{
  "name": "research-pack",
  "display_name": "Research & Analysis Pack",
  "description": "Skills for research-heavy agents",
  "skills": [
    { "name": "deep-research", "version": ">=1.0.0" },
    { "name": "synthesis", "version": ">=1.0.0" },
    { "name": "executive-summary", "version": ">=1.0.0" }
  ]
}
```

### 6.5 Evaluation Framework

Skills in the registry can include an `evals/` directory following the Agent Skills evaluation pattern:

```json
{
  "skill_name": "deep-research",
  "evals": [
    {
      "id": 1,
      "prompt": "Research the current state of quantum computing and summarize the top 3 breakthroughs from the past year.",
      "expected_output": "A structured summary with 3 breakthroughs, each with source citations.",
      "assertions": [
        "Output includes at least 3 distinct breakthroughs",
        "Each breakthrough has at least one source URL",
        "Sources are from the past 12 months"
      ]
    }
  ]
}
```

CI runs these evals on submitted skills to validate quality.

### 6.6 Bounty Integration

| Contribution         | Points |
| -------------------- | ------ |
| New skill            | 75     |
| Skill improvement PR | 30     |
| Skill tests/evals    | 20     |
| Skill docs           | 20     |

---

## 7. Requirements

### 7.1 Functional Requirements — Agent Skills Standard

| ID    | Requirement                                                                                                                                                       | Priority |
| ----- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| AS-1  | Discover skills by scanning `.agents/skills/` and `.hive/skills/` at project and user scopes                                                                      | P0       |
| AS-2  | Parse `SKILL.md` YAML frontmatter per the Agent Skills spec: `name`, `description` (required), `license`, `compatibility`, `metadata`, `allowed-tools` (optional) | P0       |
| AS-3  | Lenient validation: warn on non-critical issues, skip only on missing description or unparseable YAML                                                             | P0       |
| AS-4  | Progressive disclosure tier 1: skill catalog (name + description + location) injected into system prompt at session start                                         | P0       |
| AS-5  | Progressive disclosure tier 2: full `SKILL.md` body loaded into context when agent or user activates a skill                                                      | P0       |
| AS-6  | Progressive disclosure tier 3: scripts, references, and assets loaded on demand when instructions reference them                                                  | P0       |
| AS-7  | Model-driven activation: agent reads `SKILL.md` via file-read tool when it decides a skill is relevant                                                            | P0       |
| AS-8  | User-driven activation: `@skill-name` mention syntax intercepted by harness                                                                                       | P1       |
| AS-9  | Skill directories allowlisted for file access — no permission prompts for bundled resources                                                                       | P0       |
| AS-10 | Activated skill content protected from context pruning/compaction                                                                                                 | P0       |
| AS-11 | Duplicate activations in the same session deduplicated                                                                                                            | P1       |
| AS-12 | Name collisions resolved deterministically: project overrides user, `.hive/` overrides `.agents/`, log warning                                                    | P0       |
| AS-13 | Trust gating: project-level skills from untrusted repos require user consent                                                                                      | P1       |
| AS-14 | Compatibility with `github.com/anthropics/skills` example skills — all pass validation and activate correctly                                                     | P0       |
| AS-15 | Cross-client YAML compatibility: handle unquoted colon values via automatic fixup                                                                                 | P1       |
| AS-16 | Pre-activated skills via `skills` list in agent config (`agent.json` and Python API)                                                                              | P0       |
| AS-17 | Subagent delegation: optionally run a skill's instructions in an isolated sub-session                                                                             | P2       |

### 7.2 Functional Requirements — Default Skills

| ID    | Requirement                                                                                                                                                           | Priority |
| ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------- |
| DS-1  | Ship 6 default skills: `hive.note-taking`, `hive.batch-ledger`, `hive.context-preservation`, `hive.quality-monitor`, `hive.error-recovery`, `hive.task-decomposition` | P0       |
| DS-2  | Default skills are valid Agent Skills packages (`SKILL.md` format) in the framework install directory                                                                 | P0       |
| DS-3  | All default skills loaded automatically for every worker agent unless explicitly disabled                                                                             | P0       |
| DS-4  | Default skills integrate via system prompt injection — no additional graph nodes                                                                                      | P0       |
| DS-5  | Default skills use `_`-prefixed shared memory keys to avoid domain collisions                                                                                         | P0       |
| DS-6  | Each default skill independently configurable via `default_skills` in agent config                                                                                    | P0       |
| DS-7  | All defaults disableable at once: `{"_all": {"enabled": false}}`                                                                                                      | P0       |
| DS-8  | Default skill protocols appended in a `## Operational Protocols` system prompt section                                                                                | P0       |
| DS-9  | Iteration boundary callbacks for quality check and notes staleness                                                                                                    | P0       |
| DS-10 | Node completion hooks for batch completeness and handoff write                                                                                                        | P0       |
| DS-11 | Phase transition hooks for context carry-over and notes persistence                                                                                                   | P1       |
| DS-12 | `hive.batch-ledger` auto-detects batch scenarios via heuristic                                                                                                        | P1       |
| DS-13 | `hive.context-preservation` warns at 0.45 token usage (before 0.6 framework prune)                                                                                    | P0       |
| DS-14 | Combined default skill prompts total under 2000 tokens                                                                                                                | P0       |
| DS-15 | Agent startup logs active default skills and config                                                                                                                   | P0       |

### 7.3 Functional Requirements — CLI

| ID     | Requirement                                                                                       | Priority |
| ------ | ------------------------------------------------------------------------------------------------- | -------- |
| CLI-1  | `hive skill list` — list discovered skills (all scopes) with source and status                    | P0       |
| CLI-2  | `hive skill install <name> [--version X]` — install from registry to `~/.hive/skills/`            | P0       |
| CLI-3  | `hive skill install --pack <name>` — install a starter pack                                       | P1       |
| CLI-4  | `hive skill remove <name>` — uninstall                                                            | P0       |
| CLI-5  | `hive skill search <query>` — search registry by name, tag, description                           | P1       |
| CLI-6  | `hive skill info <name>` — show details: description, author, scripts, references                 | P0       |
| CLI-7  | `hive skill init [--name X]` — scaffold a skill directory with `SKILL.md` template                | P0       |
| CLI-8  | `hive skill validate <path>` — validate `SKILL.md` against the Agent Skills spec                  | P0       |
| CLI-9  | `hive skill test <path> [--input <json>]` — run skill in isolation, execute evals if present      | P1       |
| CLI-10 | `hive skill doctor [name]` — check health: SKILL.md parseable, scripts executable, deps available | P0       |
| CLI-11 | `hive skill doctor --defaults` — check all default skills operational                             | P1       |
| CLI-12 | `hive skill fork <name> [--name new-name]` — create local editable copy of a registry skill       | P1       |
| CLI-13 | `hive skill update [name]` — update registry cache or specific skill                              | P1       |

### 7.4 Functional Requirements — Registry

| ID     | Requirement                                                                                      | Priority |
| ------ | ------------------------------------------------------------------------------------------------ | -------- |
| REG-1  | Public GitHub repo with defined directory structure                                              | P0       |
| REG-2  | CI validates `SKILL.md` on every PR using `skills-ref validate`                                  | P0       |
| REG-3  | Flat index (`skill_index.json`) auto-generated on merge                                          | P0       |
| REG-4  | `_template/` directory with starter skill for contributors                                       | P0       |
| REG-5  | `CONTRIBUTING.md` with step-by-step submission guide                                             | P0       |
| REG-6  | CI runs skill evals when `evals/` directory is present                                           | P1       |
| REG-7  | Trust tiers: `official`, `verified`, `community`                                                 | P0       |
| REG-8  | Tags follow controlled taxonomy                                                                  | P1       |
| REG-9  | Seed with 10+ skills: extract from existing templates + port from `github.com/anthropics/skills` | P0       |
| REG-10 | Starter pack definitions in `registry/packs/`                                                    | P1       |

### 7.5 Failure Handling & Diagnostics

| ID   | Requirement                                                                               | Priority |
| ---- | ----------------------------------------------------------------------------------------- | -------- |
| DX-1 | Structured error codes: `SKILL_NOT_FOUND`, `SKILL_PARSE_ERROR`, `SKILL_ACTIVATION_FAILED` | P0       |
| DX-2 | Every error includes: what failed, why, and suggested fix                                 | P0       |
| DX-3 | Agent startup logs per-skill summary: `{name, scope, status}`                             | P0       |
| DX-4 | `hive skill doctor` machine-parseable with `--json` flag                                  | P2       |

### 7.6 Non-Functional Requirements

| ID    | Requirement                                                                  | Priority |
| ----- | ---------------------------------------------------------------------------- | -------- |
| NFR-1 | Skill discovery (scanning + parsing) completes in <500ms for up to 50 skills | P1       |
| NFR-2 | Installing a skill does not require a Hive restart                           | P0       |
| NFR-3 | All new code has unit test coverage                                          | P0       |
| NFR-4 | Registry CI runs in <120s                                                    | P1       |
| NFR-5 | `hive skill install` prints security notice on first use                     | P0       |
| NFR-6 | Skills loaded at runtime are read-only — modifications require forking       | P0       |

---

## 8. Architecture Overview

```
                    ┌─────────────────────────────────────┐
                    │     hive-skill-registry (GitHub)      │
                    │                                       │
                    │  registry/skills/deep-research/       │
                    │    ├── SKILL.md                       │
                    │    ├── scripts/                       │
                    │    └── evals/                         │
                    │  registry/packs/research-pack.json    │
                    │  skill_index.json (auto-built)        │
                    └──────────────┬────────────────────────┘
                                   │  hive skill install
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│                           Skill Sources                              │
│                                                                      │
│  ~/.hive/skills/           .agents/skills/       <hive>/skills/     │
│  (user, Hive-specific)     (project, cross-      defaults/          │
│                             client portable)      (framework built-  │
│                                                    in defaults)      │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
                       ▼
              ┌────────────────────┐
              │   SkillDiscovery   │
              │                    │
              │ scan() → catalog   │
              │ parse SKILL.md     │
              │ resolve collisions │
              └────────┬───────────┘
                       │
           ┌───────────┴───────────┐
           │                       │
           ▼                       ▼
  ┌──────────────────┐   ┌───────────────────────┐
  │ Community Skills │   │ Default Skills         │
  │                  │   │                        │
  │ Catalog injected │   │ DefaultSkillManager    │
  │ into system      │   │ • prompt injection     │
  │ prompt (tier 1)  │   │ • iteration hooks      │
  │                  │   │ • completion hooks      │
  │ Activated on     │   │ • transition hooks      │
  │ demand (tier 2)  │   │                        │
  │                  │   │ Always active           │
  │ Agent follows    │   │ (unless disabled)       │
  │ SKILL.md         │   │                        │
  │ instructions     │   │ Protocols woven into   │
  │                  │   │ existing node prompts   │
  └──────────────────┘   └───────────────────────┘
           │                       │
           └───────────┬───────────┘
                       │
                       ▼
              ┌────────────────────┐
              │   EventLoopNode    │
              │                    │
              │ System prompt =    │
              │   agent prompt     │
              │ + node prompt      │
              │ + default skill    │
              │   protocols        │
              │ + activated skill  │
              │   instructions     │
              │                    │
              │ Same iteration     │
              │ loop, tools,       │
              │ judges             │
              └────────────────────┘
```

### Component Responsibilities

| Component                        | Responsibility                                                                                                                                     |
| -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| **SkillDiscovery**               | Scan skill directories, parse `SKILL.md`, resolve collisions, build catalog                                                                        |
| **SkillCatalog**                 | In-memory index of discovered skills; injected into system prompt at session start                                                                 |
| **DefaultSkillManager**          | Load, configure, and inject the 6 built-in default skills; manage prompt injection and hook registration                                           |
| **EventLoopNode** (extended)     | New hook points for default skills: iteration callbacks, completion hooks. Appends default protocols and activated skill content to system prompt. |
| **AgentRunner** (extended)       | Resolve `skills` (pre-activation) and `default_skills` config; trigger discovery; log skill summary at startup                                     |
| **hive skill CLI**               | User-facing commands for install, search, validate, test, doctor                                                                                   |
| **hive-skill-registry** (GitHub) | Community-curated skill packages; CI validation; trust tiers; starter packs                                                                        |

---

## 9. Risks & Mitigations

| Risk                                                  | Impact                                                   | Likelihood | Mitigation                                                                                                                                                                       |
| ----------------------------------------------------- | -------------------------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Agent Skills spec evolves in breaking ways            | Hive implementation falls out of sync                    | Low        | Standard is backed by Anthropic and adopted by 30+ products; changes are conservative. Track spec repo; participate in governance.                                               |
| Low community adoption — nobody submits skills        | Registry empty, no value                                 | Medium     | Seed with 10+ skills from existing templates + ported from `github.com/anthropics/skills`; bounty program; `hive skill init` trivializes creation                                |
| Prompt injection via malicious skill instructions     | Skill manipulates agent behavior                         | Medium     | Trust gating for project-level skills; maintainer review on registry PRs; `verified` tier requires audit; security notice on install                                             |
| Default skill prompts bloat system prompt             | Reduced token budget for reasoning                       | Medium     | Hard cap of 2000 tokens total; individually disableable; terse checklist format                                                                                                  |
| Default skills create rigid behavior for simple tasks | Agent follows batch protocol on trivial single-item task | Medium     | `auto_detect_batch` heuristic; `task_decomposition` threshold defaults to `auto`; all defaults individually disableable                                                          |
| Context window consumed by too many active skills     | Multiple skills + default skills exhaust context         | Medium     | Progressive disclosure limits base cost (~100 tokens/skill); skills activated one-at-a-time on demand; skill body recommended <5000 tokens; default skills capped at 2000 tokens |
| Skill quality inconsistent across registry            | Users install ineffective skills                         | Medium     | Trust tiers; eval framework in CI; `hive skill test`; community signals (install count); `deprecated` flag                                                                       |

---

## 10. Backward Compatibility

This system is **fully additive**:

- Existing agents without skills continue to work unchanged.
- Default skills are loaded automatically but are behaviorally non-breaking: they add operational instructions to system prompts but do not change graph structure, tool availability, or output contracts.
- Default skills can be fully disabled via `"default_skills": {"_all": {"enabled": false}}`.
- Agents without a `skills` list load zero community skills (model may still activate from catalog).
- The `GraphExecutor` is unchanged — no new execution model.
- Existing `tools.py`, `mcp_servers.json`, and `mcp_registry.json` work alongside skills.
- Skills from the Agent Skills ecosystem (Claude Code, Cursor, etc.) work without modification.

---

## 11. Interaction with MCP Registry

Skills and MCP servers are complementary:

| Concern        | MCP Registry                               | Skill System                                    |
| -------------- | ------------------------------------------ | ----------------------------------------------- |
| What it shares | Tool infrastructure (servers, connections) | Agent behavior (instructions, prompts, scripts) |
| Format         | Manifest JSON (Hive-specific)              | `SKILL.md` (open standard)                      |
| Granularity    | Atomic tool functions                      | Multi-step behavioral patterns                  |

**Integration:** Skills reference tools by name in their `SKILL.md` instructions; the agent resolves them via the normal tool registry. If a skill requires a tool that isn't available, the agent will encounter an error at execution time — `hive skill doctor` can pre-check this.

---

## 12. Documentation & Examples Strategy

| Doc                                    | Audience          | Deliverable                                                                    |
| -------------------------------------- | ----------------- | ------------------------------------------------------------------------------ |
| "Install and use your first skill"     | Users             | From `hive skill search` to skill activating in a session                      |
| "Write your first skill"               | Contributors      | Step-by-step: `hive skill init` → write SKILL.md → validate → submit PR        |
| "Port a skill from Claude Code/Cursor" | Contributors      | Usually just install it — guide explains verification                          |
| "Default skills reference"             | All users         | All 6 defaults: purpose, config, shared memory keys, tuning                    |
| "Tuning default skills"                | Advanced builders | When to disable vs. configure; per-agent overrides; measuring impact           |
| Skill cookbook                         | Contributors      | Annotated examples: research, triage, draft, review, outreach, data extraction |
| "Evaluating skill quality"             | Contributors      | Setting up evals, writing assertions, iterating with the eval-driven loop      |
| Starter pack guide                     | Users             | Finding, installing, and customizing starter packs                             |

### 12.1 Draft-Then-Finalize Delivery Model

To reduce launch risk while Phase 2 and Phase 3 are still moving, documentation work should follow a
two-step model:

1. Draft narrative and structure early (conceptual guides, examples, cookbook scaffolding).
2. Finalize CLI- and registry-dependent details only after behavior is frozen.

Dependency-gated sections must be tracked explicitly:
- Gate A (`#6369`): command names, flags, output examples, diagnostics language.
- Gate B (`#6370`): registry paths, starter pack details, index examples, contribution flow specifics.

Minimum readiness bar before requesting docs review:
- Re-run all command snippets against current CLI behavior.
- Validate install/search/pack onboarding against actual registry state.
- Replace every dependency TODO anchor.
- Get at least one non-author docs review.

---

## 13. Phased Delivery

| Phase                                   | Scope                                                                                                                                                                                                                                                                                                                                                      | Depends On |
| --------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| **Phase 0: Default Skills**             | Implement 6 default skills as `SKILL.md` packages; `DefaultSkillManager` with system prompt injection, iteration callbacks, node completion hooks, phase transition hooks; `DefaultSkillConfig` in Python API and `agent.json`; `_`-prefixed shared memory convention; startup logging                                                                     | —          |
| **Phase 1: Agent Skills Standard**      | `SkillDiscovery` scanning `.agents/skills/` and `.hive/skills/`; `SKILL.md` parsing with lenient validation; progressive disclosure (catalog injection, activation, resource loading); model-driven and user-driven activation; context protection; deduplication; pre-activated skills config; compatibility tests against `github.com/anthropics/skills` | —          |
| **Phase 2: CLI & Contributor Tooling**  | `hive skill init`, `validate`, `test`, `fork`; `hive skill doctor`; `hive skill install/remove/list/search/info/update`; version pinning; `skills-ref` integration for validation                                                                                                                                                                          | Phase 1    |
| **Phase 3: Registry Repo**              | Create `hive-skill-registry` GitHub repo; CI validation using `skills-ref`; `_template/`; `CONTRIBUTING.md`; seed with 10+ skills (extracted from templates + ported from anthropics/skills); eval CI                                                                                                                                                      | Phase 1    |
| **Phase 4: Docs & Launch**              | All documentation from section 12; example agents using skills; announcement; bounty program integration                                                                                                                                                                                                                                                   | Phase 2, 3 |
| **Phase 5: Community Growth**           | Trust tier promotion process; starter packs; community signals (install counts); monthly skill spotlight; eval-driven quality ranking                                                                                                                                                                                                                      | Phase 4    |
| **Phase 6: Advanced Features** (future) | Subagent delegation for skill execution; skill-level telemetry; AI-assisted skill creation                                                                                                                                                                                                                                                                 | Phase 5    |

Phase 0 and Phase 1 can proceed in parallel — default skills depend on the prompt injection pipeline, while Agent Skills standard depends on discovery/parsing/activation.

---

## 14. Open Questions

| #   | Question                                                                                                                               | Owner               | Status |
| --- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------- | ------ |
| Q1  | Should the registry repo live under `aden-hive` org or a shared `agentskills` org?                                                     | Platform            | Open   |
| Q2  | Should default skill protocols be adaptive (e.g., `hive.batch-ledger` adjusts checkpoint frequency based on item size)?                | Engineering         | Open   |
| Q3  | Should default skills be tunable per-node (not just per-agent)?                                                                        | Engineering         | Open   |
| Q4  | How should default skill protocols interact with existing `adapt.md` working memory? Should `_working_notes` replace or supplement it? | Engineering         | Open   |
| Q5  | Should `hive.quality-monitor` self-assessments feed into judge decisions (auto-trigger RETRY on self-reported degradation)?            | Engineering         | Open   |
| Q6  | What is the right combined token budget for default skill prompts? 2000 tokens proposed — configurable or fixed?                       | Engineering         | Open   |
| Q7  | Should Hive support subagent delegation for skill execution (run skill in isolated session, return summary)?                           | Engineering         | Open   |
| Q8  | Should Hive also scan `.claude/skills/` for pragmatic compatibility with Claude Code's native skill location?                          | Engineering         | Open   |
| Q9  | What is the process for promoting a `community` skill to `verified`?                                                                   | Platform + Security | Open   |
| Q10 | Should the registry support private/enterprise skill indexes (`hive skill config --index-url`)?                                        | Platform            | Open   |
| Q11 | Should `hive skill test` use the official `skills-ref` library or a Hive-native implementation?                                        | Engineering         | Open   |
| Q12 | How should skill-level telemetry (activation counts, eval pass rates) be collected without compromising privacy?                       | Product + Privacy   | Open   |

---

## 15. Stakeholder Sign-Off

| Role                 | Name | Status  |
| -------------------- | ---- | ------- |
| Engineering Lead     |      | Pending |
| Product              |      | Pending |
| OSS / Community      |      | Pending |
| Security             |      | Pending |
| Developer Experience |      | Pending |
