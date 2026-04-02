# Install and Use Your First Skill (Phase 4)

This page covers how to discover a skill and get an agent to activate it during a session.

## 1) Prerequisites

- You have an agent you can run in Hive (see `docs/getting-started.md`).
- You have a skill package containing a `SKILL.md` file.

## 2) Install a skill

### Local install (works immediately)

Place your skill directory into one of Hive’s discovery locations (highest precedence wins):

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

On the next agent session, the skill will be discovered automatically.

### Install via CLI from a git URL

`hive skill install` copies the skill into `~/.hive/skills/<name>/` (user scope). On first install,
Hive prints a one-time security notice (NFR-5).

```bash
hive skill install --from https://github.com/org/skill-repo.git
hive skill install --from https://github.com/org/skill-repo.git --name my-skill
hive skill install --from https://github.com/org/skill-repo.git --version main
```

Use `hive skill remove <name>` to uninstall from `~/.hive/skills/`.

### Registry name, search, and info (needs a live index)

The CLI already supports registry-backed flows:

```bash
hive skill update              # refresh registry cache (no skill name)
hive skill search <query>
hive skill install <skill-name>
hive skill info <skill-name>
```

The client fetches `skill_index.json` from a configurable URL (default is set in
`framework/skills/registry.py`). Override with `HIVE_REGISTRY_URL` if you host your own index.

Until the community registry ships a reachable default index ([#6370](https://github.com/aden-hive/hive/issues/6370)),
`search` / `install <name>` may report the registry as unavailable. In that case use
`hive skill install --from <git-url>` or a custom `HIVE_REGISTRY_URL`.

## 3) Verify the skill is discovered

```bash
hive skill list
```

Expected output groups skills by scope (project/user/framework).

## 4) Trigger activation in a session

Skill activation uses progressive disclosure:

1. The agent loads a lightweight catalog of skills (name + description).
2. When the agent decides a skill is relevant, it loads the full `SKILL.md` instructions.
3. Any referenced supporting files are loaded on demand.

To get a skill to activate:

- Phrase your request so it matches the skill `description` and/or instruction triggers.
- For a first test, use a prompt that strongly maps to the skill’s purpose (keywords mentioned
  in `description` and any explicit “when to use” section).

## 5) Troubleshooting

Common issues and fixes:

- Skill not listed: confirm `SKILL.md` exists and the `name` frontmatter matches the directory name.
- Skill listed but not activating: improve `description` (make it specific about when to use it)
  and ensure your skill instructions are clear and procedural.
- Project-level trust prompt: if the skill comes from an untrusted repo, Hive will require trust
  consent before loading instructions.

