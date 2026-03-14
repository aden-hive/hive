# OSS Contributor Accelerator

**Version**: 1.0.0  
**Type**: Multi-node agent template

## Overview

Find high-leverage issues in an OSS repo and generate an execution-ready contribution brief.

This template is designed for contributors who want to ship meaningful PRs quickly:

1. Collect contributor context (skills, time, preferences)
2. Discover and rank issues from GitHub
3. Let the user pick 1-3 targets
4. Generate a markdown brief with implementation plan, test strategy, and PR drafts

## Architecture

Execution flow:

```text
intake -> issue-scout -> selection -> contribution-pack
```

### Nodes

1. **intake** (client-facing)
   - Collects repo + contributor context
   - Output: `repo_context`

2. **issue-scout**
   - Uses GitHub APIs to shortlist/rank 8 issues
   - Output: `shortlisted_issues`
   - Tools: `github_get_repo`, `github_list_issues`, `github_get_issue`

3. **selection** (client-facing)
   - Presents ranked issues and captures user selection
   - Output: `selected_issues`

4. **contribution-pack** (client-facing, terminal)
   - Generates `contribution_brief.md`
   - Includes implementation plan, tests, PR title/body drafts, maintainer update draft
   - Tools: `save_data`, `append_data`, `serve_file_to_user`

## Goal Criteria

- High-impact issue shortlist
- Strong contributor-to-issue fit
- Actionable implementation and test plans
- PR-ready draft quality

## Usage

```bash
# Copy template to exports
cp -r examples/templates/oss_contributor_accelerator exports/my_oss_agent

# Run
uv run python -m exports.my_oss_agent run
```

## Notes

- Requires GitHub credentials for GitHub tools.
- Designed with human-in-the-loop selection before deep planning.
