# Port a Skill (Claude Code / Cursor -> Hive) (Phase 4)

Hive supports skills written for Agent Skills-compatible clients. Porting usually means copying
the skill directory and ensuring the structure matches what Hive expects.

## Porting checklist

1. Copy the skill directory to one of Hive discovery locations:
   - Cross-client: `.agents/skills/<skill-name>/`
   - Hive/project: `.hive/skills/<skill-name>/`
2. Confirm the `SKILL.md` frontmatter is valid and the `name` matches the parent directory name.
3. Verify relative references for `scripts/`, `references/`, and `assets/`.
4. Validate the skill package (planned contributor flow):
   - Run local checks, then use the CLI once Phase 2 is finalized.
5. Test activation by using a prompt that should strongly map to the skill’s description.

> TODO(#6369): Replace local validation guidance with the finalized `hive skill validate` flow.

## What “works” usually means

If Hive can:

- Discover the skill (it shows up in `hive skill list`)
- Parse the `SKILL.md`
- Execute any referenced scripts (when needed)

then porting is typically successful.

