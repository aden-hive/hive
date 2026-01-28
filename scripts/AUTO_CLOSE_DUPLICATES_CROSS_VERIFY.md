# Cross-verification: auto-close-duplicates changes

## 1. Files changed (this PR / session)

| File | Change |
|------|--------|
| `scripts/auto-close-duplicates.ts` | Circular-dup + self-ref prevention; extracted helpers (isDupeComment, isDupeCommentOldEnough, authorDisagreedWithDupe, getLastDupeComment, decideAutoClose); `if (import.meta.main)` guard |
| `scripts/auto-close-duplicates.test.ts` | New: 23 unit tests for all exported helpers |
| `package.json` | Added `"test:duplicates": "bun test scripts/auto-close-duplicates"` |
| `.github/workflows/auto-close-duplicates.yml` | Added step "Run auto-close-duplicates tests" before auto-close step |

**Not changed:** `core/`, `tools/`, main CI (`.github/workflows/ci.yml`), triage workflow logic (only the script that consumes its comments).

---

## 2. Dependencies / who uses what

- **Only consumer of the script:** `.github/workflows/auto-close-duplicates.yml` runs `bun run scripts/auto-close-duplicates.ts`. No other code imports or runs it.
- **Only consumer of the script’s exports:** `scripts/auto-close-duplicates.test.ts` imports the exported helpers for unit tests.
- **Triage workflow contract:** `.github/workflows/claude-issue-triage.yml` instructs the bot to post: `"Found a possible duplicate of #<issue_number>: ..."`. The script still recognises this via `isDupeComment` (body includes `"possible duplicate"` and `comment.user.type === "Bot"`). **No change to that contract.**

---

## 3. Backward compatibility

- **Happy path unchanged:** Issue A has a bot comment “possible duplicate of #B”, B is open, comment &gt; 12h old, no author thumbs-down → script still closes A as duplicate of B.
- **New safeguards only:** (1) If B is already closed → skip (no close). (2) If comment says “duplicate of #A” on issue A (self) → skip. (3) If target fetch fails or returns non-`open` state → skip.
- **Comment format:** Still `"possible duplicate"` + Bot; `extractDuplicateIssueNumber` still supports `#N` and GitHub issue URL. No change required in triage prompt.

---

## 4. What was not touched

- **Core / tools / agent_builder:** No edits to `core/`, `tools/`, or `agent_builder_server.py`. Grep hits for `agent_builder` / `SESSIONS_DIR` are in other docs or local issue/notes, not in this script.
- **Main CI:** `ci.yml` only runs Python (ruff + pytest). It does **not** run the TS script or `bun test`. So these changes do not affect main CI.
- **Triage workflow:** Only the **comment text** is consumed by the script. We did not change the triage YAML or the bot’s instructions; we only changed how the auto-close script interprets comments and when it skips closing.

---

## 5. Verification performed

- **Unit tests:** `bun test scripts/auto-close-duplicates` → 23 tests pass.
- **Script entry:** `bun run scripts/auto-close-duplicates.ts` with fake env runs and fails at first API call (401), so the main path still runs and `import.meta.main` guard works.
- **No other imports:** Only `scripts/auto-close-duplicates.test.ts` imports from `auto-close-duplicates.ts`.

---

## 6. Conclusion

- **Impact:** Limited to the auto-close-duplicates workflow and its tests. No impact on core, tools, main CI, or triage prompt text.
- **Behavior:** Same for the normal case; only adds skip conditions for circular duplicate, self-reference, and closed/unreachable target.
- **Contract:** Triage comment format and 12h + author-reaction behaviour unchanged; script remains compatible with existing triage.
