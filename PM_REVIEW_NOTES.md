# PM Review Notes (Aden Hive)

## 1) Product understanding
- What the product does: Hive is an agent framework/platform for building, running, and iterating AI agents.
- Primary user persona: AI developers/builders and technical contributors who want to prototype and operate agents.
- Core workflow: Set up environment -> configure provider/tools -> launch dashboard/CLI (`hive tui`) -> run and iterate agents.

## 2) Onboarding journey tested
- Environment: macOS, VS Code terminal (bash), local fork.
- Steps followed: reviewed README/quickstart, ran `bash quickstart.sh`, completed interactive setup.
- Where I got blocked: quickstart required manual LLM provider selection (interactive prompt).
- Time to first success: setup completed after interactive input; instructions suggested running `hive tui` and `source ~/.zshrc`.

## 3) Friction points (ranked)
1. Quickstart requires interactive provider selection; no non-interactive review mode for contributors.
2. No explicit post-setup verification checkpoint (expected output for a “successful first run”).
3. Environment variable activation step (`source ~/.zshrc`) is easy to miss and may vary by shell.

## 4) Proposed issue candidates
1. Add non-interactive/review mode for quickstart.
2. Add deterministic “verify setup” command + expected output.
3. Clarify shell-specific environment activation and troubleshooting.

## 5) Proposed PR candidates
1. Docs: add onboarding prerequisites, review mode guidance, and verification section.
2. Script/docs: support `--non-interactive` (default provider skip) and print final verification command.
