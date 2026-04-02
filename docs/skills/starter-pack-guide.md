# Starter Pack Guide (Phase 4)

Starter packs bundle multiple complementary skills into a reusable workflow baseline.

## When to use packs

Use starter packs when:

- You want a tested baseline quickly.
- Your team needs consistent setup across projects.

## Pack lifecycle

1. Discover a starter pack that matches your workflow.
2. Install pack contents.
3. Enable/disable individual skills for your agent profile.
4. Run a smoke test on a representative task.

## Install a pack (CLI)

```bash
hive skill install --pack <pack-name>
```

Pack resolution and catalog contents depend on the registry index and pack definitions
([#6370](https://github.com/aden-hive/hive/issues/6370)). Until those are published, this command may
not match any pack.

## Notes about what is finalized later

The exact pack names and metadata fields are owned by the registry repo.

> TODO(#6370): Add finalized pack naming, index schema, and customization examples once the
> community registry is live.

